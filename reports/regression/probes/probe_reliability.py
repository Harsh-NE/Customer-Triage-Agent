"""Reliability probes through the real HTTP app, offline: odd inputs, a drafting model that returns malformed or failing output,
and an empty knowledge base. Nothing here changes application code; each case records what the customer would have seen."""
import sqlite3, sys, tempfile
from pathlib import Path
sys.path.insert(0, "D:/CustomerSupportTriage-Microsoft")
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite import SqliteSaver
from tests.test_api import RATE_LIMIT, MeteredFake, login, make_settings
from triage.api.app import create_app
from triage.clarifier import Clarifier
from triage.eval.demo_corpus import demo_corpus
from triage.joint import build_joint_graph
from triage.resolver.adapters import KBEvidenceRetriever
from triage.resolver.cache import SemanticCache
from triage.resolver.graph import ResolverDeps
from triage.resolver.interface import LexicalRetriever, TieredRetriever, load_tickets_jsonl
from triage.retrieval import MockRetriever

FX = Path("D:/CustomerSupportTriage-Microsoft/triage/resolver/fixtures")


class Bad(MeteredFake):
    """Drafting model that answers the 'draft' task with `out` (or raises it)."""
    def __init__(self, out): super().__init__(); self.out = out
    def complete_json(self, system, user, max_tokens=1200):
        if "TASK: draft" in system:
            if isinstance(self.out, Exception): raise self.out
            return self.out
        return super().complete_json(system, user, max_tokens)


def factory(llm=None, corpus=None):
    def f(logger, settings):
        mock = MockRetriever(demo_corpus() if corpus is None else corpus)
        tickets = LexicalRetriever(load_tickets_jsonl(FX / "tickets_mini.jsonl"), "tickets")
        deps = ResolverDeps(retriever=TieredRetriever(KBEvidenceRetriever(mock), tickets), llm=llm or MeteredFake(), cache=SemanticCache(), logger=logger)
        saver = SqliteSaver(sqlite3.connect(settings.checkpoint_path, check_same_thread=False))
        return build_joint_graph(Clarifier(None, mock), deps, checkpointer=saver)
    return f


def run(name, fac, body, expect=""):
    tmp = Path(tempfile.mkdtemp())
    with TestClient(create_app(make_settings(tmp), fac), raise_server_exceptions=False) as c:
        h = login(c, "alice")
        r = c.post("/api/conversations", json=body, headers=h)
        if r.status_code >= 400:
            print(f"{name:42} HTTP {r.status_code}  {str(r.json())[:110]}"); return
        v = r.json(); last = v["messages"][-1]
        steps = (last["payload"] or {}).get("steps")
        print(f"{name:42} HTTP {r.status_code} status={v['status']:9} last={last['kind']:10} steps={len(steps) if steps is not None else '-'}  {last['content'][:90]!r}")


print("--- A. unusual customer input")
ok = factory()
for name, msg in [("whitespace only", "   \n  "), ("emoji + unicode", "docker 🐳 pull fails 429 rate limit ✨ ñandú"), ("4000 chars", "docker pull fails " + "x" * 3980),
                  ("4001 chars", "y" * 4001), ("script tag", "<script>alert(1)</script> docker pull rate limit 429"),
                  ("sql-ish", "'; DROP TABLE conversations;-- docker pull 429 rate limit"), ("null byte", "docker pull 429 rate limit\x00 please"),
                  ("one 3000-char token", "A" * 3000), ("non-english", "Docker 이미지 pull 이 실패합니다 429 오류")]:
    run(name, ok, {"message": msg})
print("--- B. drafting model misbehaves (offline demo corpus, clear rate-limit question)")
good_step = {"text": "Authenticate", "evidence_ids": ["E1"]}
for name, out in [("steps is a string", {"status": "OK", "steps": "just do it", "diagnosis": "d", "verification": "v"}),
                  ("steps are plain strings", {"status": "OK", "steps": ["do a", "do b"], "diagnosis": "d", "verification": "v"}),
                  ("evidence_ids is a string", {"status": "OK", "steps": [{"text": "x", "evidence_ids": "E1"}], "diagnosis": "d", "verification": "v"}),
                  ("empty object {}", {}), ("a list instead of an object", [1, 2]),
                  ("diagnosis null", {"status": "OK", "steps": [good_step], "diagnosis": None, "verification": None}),
                  ("INSUFFICIENT_EVIDENCE", {"status": "INSUFFICIENT_EVIDENCE", "steps": []}),
                  ("raises TimeoutError", TimeoutError("read timed out")), ("raises RuntimeError", RuntimeError("503 unavailable"))]:
    run(name, factory(Bad(out)), {"message": RATE_LIMIT})
print("--- C. empty knowledge base")
run("no documents at all", factory(corpus=[]), {"message": RATE_LIMIT})
