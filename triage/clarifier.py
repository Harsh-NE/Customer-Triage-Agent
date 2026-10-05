"""
clarifier.py -- A3: the Clarifier agent (a LangGraph node, one invocation per customer message).

One turn =
    ingest      redact PII, store the message, interpret it as an answer to any open question
    understand  extract fields (LLM, or heuristic fallback), merge into session memory, find gaps
    -- hard gap?  ask_gap     ask for the missing product / symptom                      -> ASK
    -- else        diagnose    search_kb + cluster into hypotheses (differential.py)
                   decide      one cause clearly leads? -> READY
                               else ask the most discriminating question (after reflection) -> ASK
                               or, budget spent / nothing left to ask                    -> UNRESOLVED

The turn is stateless apart from SessionMemory, so a caller (UI, simulator, test, or the
integrated LangGraph) just calls turn() again with the customer's next message. The Resolver
can call reenter(NeedClarification) to ask ONE more targeted question; it counts against the
same question budget.

The deterministic graph owns control flow; the LLM is used for exactly one thing by default
(field extraction, small model). Question wording is template-based unless
cfg.llm_phrase_questions is on.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, TypedDict

from triage import understand as U
from triage.answers import match_option
from triage.config import ClarifierConfig
from triage.context_session import SessionMemory
from triage.differential import AmbiguityResult, Discriminator, ambiguity_check
from triage.llm import LLM
from triage.reflect import ReflectionVerdict, reflect_question
from triage.retrieval import Retriever
from triage.state import (PLATFORMS, ClarifierResult, ClarifierStatus, Gap, NeedClarification, QuestionPlan,
                          SignatureConfidence)
from triage.tools import ToolRegistry, make_clarifier_registry

PRODUCT_DISPLAY = {
    "desktop": "Docker Desktop", "engine": "Docker Engine (daemon/CLI)", "docker-hub": "Docker Hub",
    "build": "Docker Build/BuildKit", "compose": "Docker Compose", "security": "SSO/SCIM/security settings",
    "accounts": "Docker accounts/organizations", "subscription-billing": "billing/subscriptions",
    "scout": "Docker Scout", "extensions": "Docker Extensions", "ai": "Docker AI (Model Runner/MCP/Sandboxes)",
    "dhi": "Docker Hardened Images", "build-cloud": "Docker Build Cloud", "offload": "Docker Offload",
}
PRODUCT_QUESTION_OPTIONS = ["desktop", "engine", "docker-hub", "build", "compose", "security"]
_NO_ERROR_RE = re.compile(r"(?i)\b(no error|there'?s no error|don'?t (see|get|have) any|nothing (shows|appears)|"
                          r"just (fails|crashes|hangs|stops)|no message)\b")
_PLATFORM_NAMES = {"windows": "Windows", "mac": "macOS", "linux": "Linux"}


# ---------------------------------------------------------------------------
# Question wording (deterministic templates; variant 1 = the rephrase used on a re-ask)
# ---------------------------------------------------------------------------

def _human_list(items: list[str], joiner: str = "or") -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {joiner} " + items[-1]


def render_question(feature: str, options: list[str], variant: int, product: str | None = None) -> str:
    if feature == "platform":
        names = _human_list([_PLATFORM_NAMES.get(o, o) for o in (options or PLATFORMS)])
        return (f"Which operating system are you running Docker on: {names}?" if variant == 0
                else f"Just to narrow this down, is this on {names}?")
    if feature == "error_message":
        if not options:   # e.g. a Resolver callback: no candidate list, so ask open-ended
            return ("Could you copy the exact error message you see, including any error code?" if variant == 0
                    else "Sorry, could you paste the full error text exactly as it appears?")
        quoted = "\n".join(f'  {i}. "{o}"' for i, o in enumerate(options, 1))
        lead = ("I found several similar issues. Which of these error messages do you see?"
                if variant == 0 else "Sorry to ask again. Does the error you see match one of these?")
        return f"{lead}\n{quoted}\n(or tell me if none of these match)"
    if feature == "issue":
        quoted = "\n".join(f"  {i}. {o}" for i, o in enumerate(options, 1))
        lead = ("Which of these sounds closest to your problem?" if variant == 0
                else "Sorry to ask again. Is your problem closest to one of these?")
        return f"{lead}\n{quoted}\n(reply with the number, or tell me if none of these fit)"
    if feature == "component":
        where = f" of {PRODUCT_DISPLAY.get(product, product)}" if product else ""
        if not options:   # e.g. a Resolver callback: no candidate list to offer, so ask open-ended
            return (f"Which feature or part{where} is this about?" if variant == 0
                    else f"Could you tell me which specific feature{where} you were using when this happened?")
        where = f" in {PRODUCT_DISPLAY.get(product, product)}" if product else ""
        return (f"Which part{where} is this about: {_human_list(options)}?" if variant == 0
                else f"Is the problem related to {_human_list(options)}?")
    if feature == "product_area":
        names = _human_list([PRODUCT_DISPLAY.get(o, o) for o in options] + ["something else"])
        return (f"Which Docker product is this about: {names}?" if variant == 0
                else f"Which of these are you using when the problem happens: {names}?")
    if feature == "symptoms":
        return ("Could you describe what is going wrong, such as what you were trying to do, what happened "
                "instead, and any error message shown." if variant == 0 else
                "I need a bit more detail to find the right fix: what exactly happens when it fails, "
                "and what error text (if any) do you see?")
    return f"Could you tell me more about the {feature.replace('_', ' ')}?"


_PHRASE_PROMPT = """Rewrite this clarifying question for a customer: friendly, concise, ONE question.
Keep every option and the meaning exactly. Return only the rewritten question.

Question: {question}"""


def _llm_rephrase(question: str, options: list[str], llm: LLM | None) -> str:
    if llm is None:
        return question
    try:
        out = llm.complete(_PHRASE_PROMPT.format(question=question)).strip()
    except Exception:  # noqa: BLE001 -- wording is optional; never fail a turn over it
        return question
    keeps_options = all(o.lower() in out.lower() or PRODUCT_DISPLAY.get(o, o).lower() in out.lower() for o in options)
    return out if out and keeps_options and len(out) < 600 else question


# ---------------------------------------------------------------------------
# Turn context shared by the stages (and by the LangGraph nodes)
# ---------------------------------------------------------------------------

@dataclass
class TurnContext:
    session: SessionMemory
    message: str
    turn_idx: int = -1
    extraction: U.ExtractionResult | None = None
    hard_gaps: list[Gap] = field(default_factory=list)
    ambiguity: AmbiguityResult | None = None
    result: ClarifierResult | None = None
    notes: dict[str, Any] = field(default_factory=dict)
    log_start: int = 0      # registry.log length when the turn began, to slice THIS turn's tool calls


class GraphState(TypedDict, total=False):
    session: Any
    customer_message: str
    ctx: Any
    result: Any


class Clarifier:
    def __init__(self, llm: LLM | None, retriever: Retriever, cfg: ClarifierConfig | None = None,
                 embedder: U.Embedder | None = None, known_products: list[str] | None = None) -> None:
        self.llm = llm
        self.cfg = cfg or ClarifierConfig()
        self.embedder = embedder
        self.known_products = known_products or U.load_known_products()
        self.registry: ToolRegistry = make_clarifier_registry(retriever, self.cfg.top_k,
                                                              self.cfg.max_tool_calls_per_turn)

    # -- public API --------------------------------------------------------------
    def start(self, ticket_id: str | None = None) -> SessionMemory:
        return SessionMemory(ticket_id=ticket_id or f"T-{uuid.uuid4().hex[:8]}")

    def turn(self, session: SessionMemory, customer_message: str) -> ClarifierResult:
        ctx = TurnContext(session, customer_message)
        self._ingest(ctx)
        self._understand(ctx)
        if ctx.hard_gaps:
            self._ask_gap(ctx)
        else:
            self._diagnose(ctx)
            self._decide(ctx)
        return self._finish(ctx)

    def reenter(self, session: SessionMemory, need: NeedClarification) -> ClarifierResult:
        """Resolver callback: ask one targeted question about `need.field`, within the shared budget."""
        self.registry.begin_turn()
        if session.questions_asked >= self.cfg.max_clarify_turns:
            return self._unresolved(session, "budget_exhausted", {"callback": need.field})
        plan = self._plan_for_field(session, need.field)
        verdict = reflect_question(plan, session)
        if not verdict.ask:
            return self._unresolved(session, f"cannot_clarify:{verdict.reason}", {"callback": need.field})
        return self._emit_question(session, plan, {"callback": need.field, "reflection": verdict.reason})

    # -- stages -----------------------------------------------------------------------
    def _ingest(self, ctx: TurnContext) -> None:
        s = ctx.session
        self.registry.begin_turn()
        ctx.log_start = len(self.registry.log)
        ctx.turn_idx = s.add_turn("customer", ctx.message).idx
        pending = s.open_question
        if pending is not None:
            reply = s.turns[ctx.turn_idx].text
            if pending.feature == "error_open":
                # open-ended "paste the exact error": the whole reply IS the error text, unless
                # the customer says there isn't one
                if _NO_ERROR_RE.search(reply):
                    value = "unknown"
                else:
                    value = "provided"
                    ctx.notes["error_text"] = " ".join(reply.split())[:200]
            else:
                value = match_option(pending.feature, reply, pending.options)
                if (value is None and pending.feature in ("issue", "error_message")
                        and U.looks_like_error_text(reply)):
                    # didn't pick a menu option but pasted something error-shaped: that IS evidence
                    ctx.notes["error_text"] = " ".join(reply.split())[:200]
            if value:
                s.mark_answered(value)
                ctx.notes["answered"] = {pending.feature: value}

    def _understand(self, ctx: TurnContext) -> None:
        s = ctx.session
        # If our previous turn was a question, tell the extractor what this message replies to
        # (a bare "Mac" is only meaningful next to "which operating system?").
        prev = s.turns[ctx.turn_idx - 1] if ctx.turn_idx > 0 else None
        pending_text = prev.text if prev is not None and prev.role == "assistant" else None
        ctx.extraction = U.extract(s.turns[ctx.turn_idx].text, self.llm, self.known_products,
                                   known=s.fields, pending_question=pending_text)
        s.apply_extraction(ctx.extraction.fields, ctx.turn_idx)
        error_text = ctx.notes.get("error_text")
        if error_text and error_text not in s.fields.error_messages:
            s.fields.error_messages = (s.fields.error_messages + [error_text])[:4]
            s.field_sources["error_messages"] = ctx.turn_idx
        for feature, value in ctx.notes.get("answered", {}).items():
            self._apply_answer_to_fields(s, feature, value, ctx.turn_idx)
        ctx.hard_gaps = [g for g in U.detect_gaps(s.fields) if g.hard]

    def _ask_gap(self, ctx: TurnContext) -> None:
        s = ctx.session
        for _ in range(3):  # a reflection may fill a gap from earlier turns; re-check, bounded
            gap = ctx.hard_gaps[0] if ctx.hard_gaps else None
            if gap is None:
                self._diagnose(ctx)
                self._decide(ctx)
                return
            if s.questions_asked >= self.cfg.max_clarify_turns:
                ctx.result = self._unresolved(s, "budget_exhausted_with_hard_gap", {"gap": gap.field})
                return
            plan = self._plan_for_field(s, gap.field)
            verdict = reflect_question(plan, s)
            if verdict.ask:
                ctx.result = self._emit_question(s, plan, {"gap": gap.field, "reflection": verdict.reason})
                return
            if verdict.filled_value:
                self._apply_answer_to_fields(s, gap.field, verdict.filled_value, ctx.turn_idx)
                ctx.hard_gaps = [g for g in U.detect_gaps(s.fields) if g.hard]
                continue
            ctx.result = self._unresolved(s, f"cannot_ask:{verdict.reason}", {"gap": gap.field})
            return
        ctx.result = self._unresolved(s, "gap_not_resolvable", {})

    def _diagnose(self, ctx: TurnContext) -> None:
        s = ctx.session
        exclude = self._excluded_features(s)
        ctx.ambiguity = ambiguity_check(s.fields, self.registry, s.answered, exclude, self.cfg)

    def _decide(self, ctx: TurnContext) -> None:
        if ctx.result is not None:
            return
        s, amb = ctx.session, ctx.ambiguity
        if not amb.confidence.ambiguous:
            ctx.result = self._signature_result(s, amb, ClarifierStatus.READY, "clear")
            return
        if s.questions_asked >= self.cfg.max_clarify_turns:
            ctx.result = self._signature_result(s, amb, ClarifierStatus.UNRESOLVED, "budget_exhausted")
            return
        for _ in range(3):  # reflection can recover an answer from earlier turns -> re-diagnose
            for disc in amb.discriminators:
                plan = self._plan_for_discriminator(s, disc)
                verdict = reflect_question(plan, s)
                if verdict.ask:
                    ctx.result = self._emit_question(
                        s, plan, {"reflection": verdict.reason, "gain": disc.gain, "p_top": amb.confidence.p_top,
                                  "margin": amb.confidence.margin})
                    return
                if verdict.filled_value:
                    self._apply_answer_to_fields(s, disc.feature, verdict.filled_value, ctx.turn_idx)
                    s.answered.setdefault(disc.feature, verdict.filled_value)
                    amb = ambiguity_check(s.fields, self.registry, s.answered, self._excluded_features(s), self.cfg)
                    ctx.ambiguity = amb
                    if not amb.confidence.ambiguous:
                        ctx.result = self._signature_result(s, amb, ClarifierStatus.READY, "clear_after_recall")
                        return
                    break  # restart over the refreshed discriminators
            else:
                break
        # Nothing in the candidate pool separates the causes (or a menu was answered "none of
        # these"). Do what a human agent does: ask for the exact error text -- once.
        if (s.questions_asked < self.cfg.max_clarify_turns and not s.fields.error_messages
                and "error_open" not in self._excluded_features(s)):
            plan = QuestionPlan("error_open", render_question("error_message", [], self._variant(s, "error_open")), [])
            verdict = reflect_question(plan, s)
            if verdict.ask:
                ctx.result = self._emit_question(s, plan, {"reflection": verdict.reason, "last_resort": True,
                                                           "p_top": amb.confidence.p_top})
                return
        reason = ("no_discriminating_question" if amb.confidence.reason == "split" else amb.confidence.reason)
        ctx.result = self._signature_result(s, amb, ClarifierStatus.UNRESOLVED, reason)

    def _finish(self, ctx: TurnContext) -> ClarifierResult:
        r = ctx.result
        r.questions_asked = ctx.session.questions_asked
        r.meta.update({
            "extraction_source": ctx.extraction.source if ctx.extraction else None,
            "extraction_error": ctx.extraction.error if ctx.extraction else None,
            "tool_calls": list(self.registry.log[ctx.log_start:]),
        })
        if ctx.ambiguity:
            amb = ctx.ambiguity
            r.meta["queries"] = amb.queries
            r.meta["confidence"] = {"p_top": round(amb.confidence.p_top, 3), "margin": round(amb.confidence.margin, 3),
                                    "top_score": round(amb.confidence.top_score, 3), "reason": amb.confidence.reason}
            r.meta["hypotheses"] = [{"label": h.label, "weight": round(h.weight, 3)} for h in amb.hypotheses[:5]]
        return r

    # -- planning questions ------------------------------------------------------------
    def _variant(self, session: SessionMemory, feature: str) -> int:
        return 1 if any(q.feature == feature for q in session.questions) else 0

    def _excluded_features(self, session: SessionMemory) -> set[str]:
        asked_counts: dict[str, int] = {}
        for q in session.questions:
            asked_counts[q.feature] = asked_counts.get(q.feature, 0) + 1
        return ({f for f, n in asked_counts.items() if n >= 2}
                | {q.feature for q in session.questions if q.answered} | set(session.answered))

    def _plan_for_field(self, session: SessionMemory, feature: str) -> QuestionPlan:
        options: list[str] = []
        if feature == "product_area":
            options = list(PRODUCT_QUESTION_OPTIONS)
        elif feature == "platform":
            options = list(PLATFORMS)
        text = render_question(feature, options, self._variant(session, feature), session.fields.product_area)
        return QuestionPlan(feature, text, options)

    def _plan_for_discriminator(self, session: SessionMemory, disc: Discriminator) -> QuestionPlan:
        text = render_question(disc.feature, disc.options, self._variant(session, disc.feature),
                               session.fields.product_area)
        return QuestionPlan(disc.feature, text, list(disc.options))

    def _emit_question(self, session: SessionMemory, plan: QuestionPlan, meta: dict) -> ClarifierResult:
        if self.cfg.llm_phrase_questions:
            plan.text = _llm_rephrase(plan.text, plan.options, self.llm)
        plan = self.registry.call("ask_customer", feature=plan.feature, text=plan.text, options=plan.options)
        turn = session.add_turn("assistant", plan.text, feature=plan.feature)
        session.record_question(plan, turn.idx)
        return ClarifierResult(ClarifierStatus.ASK, question=plan, reason=f"asking:{plan.feature}", meta=dict(meta))

    # -- results -------------------------------------------------------------------------
    def _signature_result(self, session: SessionMemory, amb: AmbiguityResult, status: ClarifierStatus,
                          reason: str) -> ClarifierResult:
        meta: dict[str, Any] = {}
        if status is ClarifierStatus.READY and not session.fields.product_area and amb.hypotheses:
            inferred = U.normalize_product(amb.hypotheses[0].features.get("product_area"), self.known_products)
            if inferred:       # the pool agreed on a cause, so its product is the best evidence we have
                session.fields.product_area = inferred
                meta["inferred"] = {"product_area": inferred}
        sig = U.build_signature(session.fields, amb.confidence, amb.hypotheses[:3], self.embedder)
        return ClarifierResult(status, signature=sig, reason=reason, meta=meta)

    def _unresolved(self, session: SessionMemory, reason: str, meta: dict) -> ClarifierResult:
        sig = U.build_signature(session.fields, SignatureConfidence(0, 0, 0, True, reason), [], self.embedder)
        return ClarifierResult(ClarifierStatus.UNRESOLVED, signature=sig, reason=reason,
                               questions_asked=session.questions_asked, meta=dict(meta))

    @staticmethod
    def _apply_answer_to_fields(session: SessionMemory, feature: str, value: str, turn_idx: int) -> None:
        if value == "unknown":
            return
        if feature in ("platform", "product_area", "component") and not getattr(session.fields, feature):
            setattr(session.fields, feature, value)
            session.field_sources[feature] = turn_idx
        if feature in ("error_message",):
            session.answered.setdefault("error_message", value)

    # -- LangGraph ---------------------------------------------------------------------------
    def build_graph(self):
        """The same stages as turn(), wired as LangGraph nodes (standalone Clarifier graph).
        Invoke with {"session": SessionMemory, "customer_message": str}; read ["result"]."""
        from langgraph.graph import END, START, StateGraph

        def n_ingest(state: GraphState) -> GraphState:
            ctx = TurnContext(state["session"], state["customer_message"])
            self._ingest(ctx)
            return {"ctx": ctx}

        def n_understand(state: GraphState) -> GraphState:
            self._understand(state["ctx"])
            return {}

        def n_ask_gap(state: GraphState) -> GraphState:
            self._ask_gap(state["ctx"])
            return {"result": self._finish(state["ctx"])}

        def n_diagnose(state: GraphState) -> GraphState:
            self._diagnose(state["ctx"])
            return {}

        def n_decide(state: GraphState) -> GraphState:
            self._decide(state["ctx"])
            return {"result": self._finish(state["ctx"])}

        graph = StateGraph(GraphState)
        for name, fn in (("ingest", n_ingest), ("understand", n_understand), ("ask_gap", n_ask_gap),
                         ("diagnose", n_diagnose), ("decide", n_decide)):
            graph.add_node(name, fn)
        graph.add_edge(START, "ingest")
        graph.add_edge("ingest", "understand")
        graph.add_conditional_edges("understand", lambda s: "ask_gap" if s["ctx"].hard_gaps else "diagnose",
                                    {"ask_gap": "ask_gap", "diagnose": "diagnose"})
        graph.add_edge("ask_gap", END)
        graph.add_edge("diagnose", "decide")
        graph.add_edge("decide", END)
        return graph.compile()

    def as_node(self):
        """Plug-in point for the integrated graph (J1): reads state['session'] and
        state['customer_message'], writes state['clarifier_result']."""
        def node(state: dict) -> dict:
            return {"clarifier_result": self.turn(state["session"], state["customer_message"])}
        return node
