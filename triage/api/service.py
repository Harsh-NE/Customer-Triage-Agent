"""service.py -- conversations: run the joint graph, persist every turn, and expose customer and engineer views.

One conversation = one LangGraph thread (id `C-xxxxxxxx`, also the agent's ticket id). The graph pauses with interrupt() when
it needs the customer; each pause becomes an agent message (a question with its menu options, or a fix with its sources).
When the graph finishes, its outcome becomes the conversation status:

    resolved   -> status "resolved"  (resolved_by "agent")
    escalated  -> status "escalated" (reason, priority P1..P4, full escalation payload kept for the engineer)
    rejected   -> status "declined"  (out of scope / blocked; never goes to an engineer)

After an escalation the graph is finished: the customer and an engineer talk through plain messages. Customers never see
gate scores or internal notes; engineers see both. Any exception from the graph (LLM outage, store error) escalates the
conversation as SYSTEM_ERROR instead of leaving the customer hanging.
"""

from __future__ import annotations

import threading
import uuid
from datetime import timedelta
from typing import Any, Optional

from langgraph.types import Command
from sqlalchemy import func, select

from triage.api.db import (AgentEvent, CaseAction, CaseNote, Conversation, Message, User, iso, utcnow)

PRIORITIES = ("P1", "P2", "P3", "P4")
CLOSED = ("resolved", "declined")
ACTION_TEXT = {"resolved": "That fixed it, thanks.", "not_fixed": "I tried that but it is still the same error."}
OUTCOME_STATUS = {"resolved": "resolved", "escalated": "escalated", "rejected": "declined"}
CLOSING_KIND = {"resolved": "resolved", "escalated": "escalation", "declined": "decline"}


class ServiceError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status, self.detail = status, detail


def _light_evidence(evidence: list[dict]) -> list[dict]:
    return [{"id": e.get("evidence_id"), "tier": e.get("tier"), "url": e.get("url"), "score": e.get("rerank_score"),
             "issue": (e.get("metadata") or {}).get("issue"), "trust": e.get("trust"),
             "license": (e.get("metadata") or {}).get("license"), "snippet": (e.get("text") or "")[:300]} for e in evidence or []]


def summarize_state(st: dict) -> dict:
    return {"signature": st.get("signature") or {}, "confidence": st.get("confidence"), "gate": st.get("gate_detail"),
            "gate_decision": st.get("gate_decision"), "cache_status": st.get("cache_status"), "tier": st.get("tier"),
            "attempts": st.get("attempts") or [], "evidence": _light_evidence(st.get("evidence")),
            "escalation_payload": st.get("escalation_payload"), "clarify_returns": st.get("clarify_returns", 0)}


class ConversationService:
    def __init__(self, session_factory, graph) -> None:
        self.sf, self.graph = session_factory, graph
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # -- helpers -----------------------------------------------------------------------------------------------
    def _lock(self, conv_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(conv_id, threading.Lock())

    @staticmethod
    def _cfg(conv_id: str) -> dict:
        return {"configurable": {"thread_id": conv_id}}

    @staticmethod
    def _add_message(s, conv_id: str, role: str, kind: str, content: str, payload: Optional[dict] = None,
                     author_id: Optional[int] = None) -> Message:
        m = Message(conversation_id=conv_id, role=role, kind=kind, content=content, payload=payload or {}, author_id=author_id)
        s.add(m)
        return m

    # -- running the graph -------------------------------------------------------------------------------------
    def _run(self, conv_id: str, first: Optional[str], resume: Optional[str]) -> None:
        """Invoke the graph once (start or resume) and persist what came out. Never raises."""
        try:
            if first is not None:
                out = self.graph.invoke({"ticket_id": conv_id, "customer_message": first, "transcript": []}, self._cfg(conv_id))
            else:
                out = self.graph.invoke(Command(resume=resume), self._cfg(conv_id))
            self._apply(conv_id, out)
        except Exception as exc:  # noqa: BLE001 -- an outage must not strand the customer
            self._fail(conv_id, exc)

    def _apply(self, conv_id: str, out: dict) -> None:
        with self.sf() as s:
            conv = s.get(Conversation, conv_id)
            conv.updated_at = utcnow()
            if "__interrupt__" in out:
                v = out["__interrupt__"][0].value
                if v["type"] == "clarifier_question":
                    self._add_message(s, conv_id, "agent", "question", v["message"],
                                      {"options": v.get("options") or [], "feature": v.get("feature") or ""})
                else:
                    self._add_message(s, conv_id, "agent", "fix", v["message"],
                                      {"diagnosis": v.get("diagnosis", ""), "steps": v.get("steps") or [],
                                       "verification": v.get("verification", ""), "sources": v.get("sources") or []})
                conv.status = "active"
                s.commit()
                return
            st = self.graph.get_state(self._cfg(conv_id)).values
            conv.status = OUTCOME_STATUS.get(st.get("outcome"), "active")
            conv.summary = summarize_state(st)
            payload = st.get("escalation_payload") or {}
            if conv.status == "escalated":
                conv.escalation_reason, conv.priority = st.get("escalation_reason"), payload.get("priority") or "P3"
            elif conv.status == "declined":
                conv.escalation_reason = st.get("escalation_reason")
            elif conv.status == "resolved":
                conv.resolved_by, conv.closed_at = "agent", utcnow()
            if conv.status in CLOSING_KIND:
                final = (st.get("transcript") or [{}])[-1].get("content", "")
                self._add_message(s, conv_id, "agent", CLOSING_KIND[conv.status], final)
            if conv.status in CLOSED:
                conv.closed_at = conv.closed_at or utcnow()
            s.commit()

    def _fail(self, conv_id: str, exc: Exception) -> None:
        with self.sf() as s:
            conv = s.get(Conversation, conv_id)
            conv.status, conv.escalation_reason, conv.priority = "escalated", "SYSTEM_ERROR", "P2"
            conv.updated_at = utcnow()
            conv.summary = {**(conv.summary or {}), "error": f"{type(exc).__name__}: {exc}"[:400]}
            self._add_message(s, conv_id, "system", "escalation",
                              "I ran into a technical problem and could not finish this. I've passed it to a support engineer "
                              "along with what we discussed.")
            s.add(AgentEvent(conversation_id=conv_id, ts=utcnow(), event="error", data={"error": conv.summary["error"]}))
            s.commit()

    # -- customer operations -----------------------------------------------------------------------------------
    def create(self, user: User, text: str) -> str:
        text = text.strip()
        if not text:
            raise ServiceError(422, "message is empty")
        conv_id = f"C-{uuid.uuid4().hex[:8]}"
        with self.sf() as s:
            s.add(Conversation(id=conv_id, user_id=user.id, title=text[:80], status="active"))
            s.flush()
            self._add_message(s, conv_id, "customer", "text", text, author_id=user.id)
            s.commit()
        with self._lock(conv_id):
            self._run(conv_id, first=text, resume=None)
        return conv_id

    def post_message(self, user: User, conv_id: str, text: Optional[str], action: Optional[str]) -> None:
        if action and action not in ACTION_TEXT:
            raise ServiceError(422, f"unknown action '{action}'")
        text = ACTION_TEXT[action] if action else (text or "").strip()
        if not text:
            raise ServiceError(422, "message is empty")
        with self._lock(conv_id):
            with self.sf() as s:
                conv = self._owned(s, user, conv_id)
                if conv.status in CLOSED:
                    raise ServiceError(409, f"this conversation is {conv.status}; start a new one")
                self._add_message(s, conv_id, "customer", "text", text, {"action": action} if action else {}, user.id)
                conv.updated_at = utcnow()
                escalated = conv.status == "escalated"
                s.commit()
            if not escalated:                       # an escalated case has no graph left to run: an engineer reads it
                self._run(conv_id, first=None, resume=text)

    def _owned(self, s, user: User, conv_id: str) -> Conversation:
        conv = s.get(Conversation, conv_id)
        if conv is None or (user.role == "customer" and conv.user_id != user.id):
            raise ServiceError(404, "conversation not found")           # 404, not 403: do not reveal other people's ids
        return conv

    def feedback(self, user: User, conv_id: str, rating: Optional[int], helpful: Optional[bool], comment: Optional[str]) -> None:
        if rating is not None and not 1 <= rating <= 5:
            raise ServiceError(422, "rating must be 1-5")
        with self.sf() as s:
            conv = self._owned(s, user, conv_id)
            conv.rating = rating if rating is not None else conv.rating
            conv.helpful = helpful if helpful is not None else conv.helpful
            conv.feedback_text = (comment or conv.feedback_text or "")[:2000] or None
            s.commit()

    # -- views -------------------------------------------------------------------------------------------------
    def _usage(self, s, conv_id: str) -> dict:
        row = s.execute(select(func.coalesce(func.sum(AgentEvent.input_tokens), 0), func.coalesce(func.sum(AgentEvent.output_tokens), 0),
                               func.coalesce(func.sum(AgentEvent.cost_usd), 0.0),
                               func.count().filter(AgentEvent.event == "llm_call"),
                               func.count().filter((AgentEvent.event == "llm_call") & (AgentEvent.cost_usd.is_(None))))
                        .where(AgentEvent.conversation_id == conv_id)).one()
        return {"input_tokens": int(row[0]), "output_tokens": int(row[1]), "cost_usd": round(float(row[2]), 8),
                "llm_calls": int(row[3]), "unpriced_calls": int(row[4])}

    def _names(self, s, ids: set) -> dict[int, str]:
        ids = {i for i in ids if i}
        return {u.id: u.username for u in s.scalars(select(User).where(User.id.in_(ids)))} if ids else {}

    def _message_out(self, m: Message, names: dict[int, str], engineer: bool) -> dict:
        payload = m.payload or {}
        if not engineer and m.kind == "fix":                   # customers get the fix and its sources, never scores
            payload = {k: payload.get(k) for k in ("diagnosis", "steps", "verification", "sources")}
        return {"id": m.id, "role": m.role, "kind": m.kind, "content": m.content, "payload": payload, "created_at": iso(m.created_at),
                "author": names.get(m.author_id) if m.role == "engineer" else None}

    def list_mine(self, user: User) -> list[dict]:
        with self.sf() as s:
            rows = s.scalars(select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.created_at.desc())).all()
            return [self._summary_out(c) for c in rows]

    @staticmethod
    def _summary_out(c: Conversation) -> dict:
        end = c.closed_at or utcnow()
        return {"id": c.id, "title": c.title, "status": c.status, "escalated": c.escalation_reason is not None and c.status != "declined",
                "created_at": iso(c.created_at), "updated_at": iso(c.updated_at), "closed_at": iso(c.closed_at),
                "duration_s": int((end - c.created_at).total_seconds()), "rating": c.rating, "helpful": c.helpful,
                "resolved_by": c.resolved_by}

    def customer_view(self, user: User, conv_id: str, after: int = 0) -> dict:
        with self.sf() as s:
            c = self._owned(s, user, conv_id)
            msgs = s.scalars(select(Message).where(Message.conversation_id == conv_id, Message.id > after).order_by(Message.id)).all()
            names = self._names(s, {m.author_id for m in msgs})
            return {**self._summary_out(c), "can_reply": c.status not in CLOSED, "feedback": {"rating": c.rating, "helpful": c.helpful, "comment": c.feedback_text},
                    "assigned": c.assigned_to is not None,
                    "messages": [self._message_out(m, names, engineer=False) for m in msgs]}

    # -- engineer operations -----------------------------------------------------------------------------------
    def list_cases(self, status: Optional[str], priority: Optional[str], reason: Optional[str], assigned: Optional[str],
                   q: Optional[str], limit: int, offset: int) -> dict:
        with self.sf() as s:
            stmt = select(Conversation)
            stmt = stmt.where(Conversation.status == (status or "escalated")) if status != "all" else stmt
            if priority:
                stmt = stmt.where(Conversation.priority == priority)
            if reason:
                stmt = stmt.where(Conversation.escalation_reason == reason)
            if assigned == "unassigned":
                stmt = stmt.where(Conversation.assigned_to.is_(None))
            elif assigned:
                uid = s.scalar(select(User.id).where(User.username == assigned))
                stmt = stmt.where(Conversation.assigned_to == uid)
            if q:
                stmt = stmt.where(Conversation.title.ilike(f"%{q}%"))
            total = s.scalar(select(func.count()).select_from(stmt.subquery()))
            rows = s.scalars(stmt.order_by(Conversation.priority.asc().nulls_last(), Conversation.created_at.asc()).limit(limit).offset(offset)).all()
            names = self._names(s, {c.assigned_to for c in rows})
            return {"total": total, "cases": [{**self._summary_out(c), "priority": c.priority, "reason": c.escalation_reason,
                                               "assigned_to": names.get(c.assigned_to),
                                               "age_minutes": int((utcnow() - c.created_at).total_seconds() // 60)} for c in rows]}

    def case_detail(self, conv_id: str) -> dict:
        with self.sf() as s:
            c = s.get(Conversation, conv_id)
            if c is None:
                raise ServiceError(404, "case not found")
            msgs = s.scalars(select(Message).where(Message.conversation_id == conv_id).order_by(Message.id)).all()
            notes = s.scalars(select(CaseNote).where(CaseNote.conversation_id == conv_id).order_by(CaseNote.id)).all()
            actions = s.scalars(select(CaseAction).where(CaseAction.conversation_id == conv_id).order_by(CaseAction.id)).all()
            events = s.scalars(select(AgentEvent).where(AgentEvent.conversation_id == conv_id).order_by(AgentEvent.id)).all()
            names = self._names(s, {m.author_id for m in msgs} | {n.author_id for n in notes} | {a.actor_id for a in actions}
                                | {c.assigned_to, c.user_id})
            summary = c.summary or {}
            return {**self._summary_out(c), "customer": names.get(c.user_id), "priority": c.priority, "reason": c.escalation_reason,
                    "assigned_to": names.get(c.assigned_to), "resolution_text": c.resolution_text, "promote_to_kb": c.promote_to_kb,
                    "feedback": {"rating": c.rating, "helpful": c.helpful, "comment": c.feedback_text},
                    "messages": [self._message_out(m, names, engineer=True) for m in msgs],
                    "agent": {"signature": summary.get("signature"), "hypotheses": (summary.get("signature") or {}).get("hypotheses", []),
                              "entities": (summary.get("signature") or {}).get("entities", []),
                              "clarifier": (summary.get("signature") or {}).get("clarifier", {}), "confidence": summary.get("confidence"),
                              "gate": summary.get("gate"), "gate_decision": summary.get("gate_decision"), "cache_status": summary.get("cache_status"),
                              "attempts": summary.get("attempts", []), "evidence": summary.get("evidence", []),
                              "escalation": summary.get("escalation_payload"), "error": summary.get("error")},
                    "activity": activity(events), "usage": self._usage(s, conv_id),
                    "notes": [{"id": n.id, "author": names.get(n.author_id), "body": n.body, "created_at": iso(n.created_at)} for n in notes],
                    "actions": [{"actor": names.get(a.actor_id), "action": a.action, "data": a.data, "created_at": iso(a.created_at)} for a in actions]}

    def _case(self, s, conv_id: str) -> Conversation:
        c = s.get(Conversation, conv_id)
        if c is None:
            raise ServiceError(404, "case not found")
        return c

    @staticmethod
    def _log(s, conv_id: str, user: User, action: str, data: Optional[dict] = None) -> None:
        s.add(CaseAction(conversation_id=conv_id, actor_id=user.id, action=action, data=data or {}))

    def engineer_reply(self, user: User, conv_id: str, text: str) -> None:
        if not text.strip():
            raise ServiceError(422, "reply is empty")
        with self.sf() as s:
            c = self._case(s, conv_id)
            if c.status != "escalated":
                raise ServiceError(409, f"case is {c.status}; reopen it first" if c.status in CLOSED else "case is not escalated")
            self._add_message(s, conv_id, "engineer", "engineer_reply", text.strip(), author_id=user.id)
            c.assigned_to = c.assigned_to or user.id
            c.updated_at = utcnow()
            self._log(s, conv_id, user, "reply")
            s.commit()

    def assign(self, user: User, conv_id: str, username: Optional[str]) -> None:
        with self.sf() as s:
            c = self._case(s, conv_id)
            target = user.id
            if username:
                target = s.scalar(select(User.id).where(User.username == username, User.role == "engineer"))
                if target is None:
                    raise ServiceError(404, "no such engineer")
            c.assigned_to = target
            self._log(s, conv_id, user, "assign", {"to": username or user.username})
            s.commit()

    def set_priority(self, user: User, conv_id: str, priority: str) -> None:
        if priority not in PRIORITIES:
            raise ServiceError(422, f"priority must be one of {PRIORITIES}")
        with self.sf() as s:
            c = self._case(s, conv_id)
            old, c.priority = c.priority, priority
            self._log(s, conv_id, user, "priority", {"from": old, "to": priority})
            s.commit()

    def add_note(self, user: User, conv_id: str, body: str) -> None:
        if not body.strip():
            raise ServiceError(422, "note is empty")
        with self.sf() as s:
            self._case(s, conv_id)
            s.add(CaseNote(conversation_id=conv_id, author_id=user.id, body=body.strip()))
            self._log(s, conv_id, user, "note")
            s.commit()

    def resolve(self, user: User, conv_id: str, resolution: str, promote: bool) -> None:
        if not resolution.strip():
            raise ServiceError(422, "a resolution is required")
        with self.sf() as s:
            c = self._case(s, conv_id)
            if c.status != "escalated":
                raise ServiceError(409, f"case is {c.status}")
            c.status, c.resolved_by, c.resolution_text, c.promote_to_kb = "resolved", "engineer", resolution.strip(), promote
            c.closed_at, c.updated_at = utcnow(), utcnow()
            c.assigned_to = c.assigned_to or user.id
            self._add_message(s, conv_id, "engineer", "resolution", resolution.strip(), author_id=user.id)
            self._log(s, conv_id, user, "resolve", {"promote_to_kb": promote})
            s.commit()

    def reopen(self, user: User, conv_id: str) -> None:
        with self.sf() as s:
            c = self._case(s, conv_id)
            if c.status == "escalated":
                raise ServiceError(409, "case is already open")
            if c.status == "declined":
                raise ServiceError(409, "a declined (out of scope) request has no case to reopen")
            c.status, c.closed_at, c.resolved_by = "escalated", None, None
            c.escalation_reason = c.escalation_reason or "REOPENED"
            c.priority = c.priority or "P3"
            c.updated_at = utcnow()
            self._log(s, conv_id, user, "reopen")
            s.commit()


# ---------------------------------------------------------------------------
# Agent Activity: the raw event log, summarised into steps an engineer can read
# ---------------------------------------------------------------------------

def activity(events: list[AgentEvent]) -> list[dict]:
    steps: list[dict] = []

    def add(ev: AgentEvent, label: str, level: str = "ok") -> None:
        steps.append({"ts": iso(ev.ts), "event": ev.event, "label": label, "level": level, "latency_ms": ev.latency_ms})

    for ev in events:
        d = ev.data or {}
        if ev.event == "guardrail":
            add(ev, f"Guardrail blocked the request ({d.get('detail')})", "warn")
        elif ev.event == "clarifier_turn":
            conf = d.get("confidence") or {}
            if d.get("status") == "ask":
                add(ev, f"Clarifier asked a question about '{d.get('question_feature')}'")
            else:
                level = "ok" if d.get("status") == "ready" else "warn"
                add(ev, f"Clarifier {d.get('status')} ({d.get('reason')}; top cause {conf.get('p_top')})", level)
        elif ev.event == "cache_lookup":
            add(ev, f"Cache: {d.get('status')}")
        elif ev.event == "retrieval":
            add(ev, f"Retrieved {d.get('n')} {d.get('tier')} passages (top score {d.get('top_score')})")
        elif ev.event == "gate":
            add(ev, f"Evidence gate -> {d.get('decision')} (confidence {d.get('confidence')}; {', '.join(d.get('reasons') or [])})",
                "ok" if d.get("decision") == "resolve" else "warn")
        elif ev.event == "llm_call":
            tokens = ev.input_tokens + ev.output_tokens
            cost = f", ${ev.cost_usd:.5f}" if ev.cost_usd is not None else ", unpriced"
            add(ev, f"LLM {ev.node}: {tokens} tokens{cost}")
        elif ev.event == "verify":
            dropped = len(d.get("dropped") or [])
            add(ev, f"Verified the draft: kept {d.get('kept')} step(s), dropped {dropped}", "ok" if d.get("ok") else "warn")
        elif ev.event == "handoff":
            add(ev, "Handed back to the Clarifier for more information", "warn")
        elif ev.event == "escalation":
            add(ev, f"Escalated: {d.get('reason')} ({d.get('priority')})", "warn")
        elif ev.event == "outcome":
            add(ev, f"Outcome: {d.get('outcome')}")
        elif ev.event == "error":
            add(ev, f"System error: {d.get('error')}", "error")
    return steps
