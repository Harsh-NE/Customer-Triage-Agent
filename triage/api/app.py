"""app.py -- the HTTP API (FastAPI). Start it with:

    uvicorn "triage.api.app:create_app" --factory --port 8000      # RESOLVER_LLM=gemini for the real model

Customers: /api/conversations (start, reply, history, feedback). Engineers: /api/cases (queue, case view, actions) and
/api/analytics. Auth is demo-grade: a username (+ the engineer passcode for the engineer role) returns a signed token.
The graph is built once at startup (the embedding model is warmed then, not on the first customer's request); tests inject
an offline graph through `graph_factory`.
"""

from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select

from triage import pricing
from triage.api import analytics
from triage.api.db import User, init_db, make_engine, session_factory
from triage.api.events import DBEventLogger
from triage.api.service import ConversationService, ServiceError
from triage.api.settings import Settings


# ---------------------------------------------------------------------------
# request bodies
# ---------------------------------------------------------------------------
class LoginIn(BaseModel):
    username: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_.@-]+$")
    role: str = "customer"
    passcode: Optional[str] = None


class StartIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class MessageIn(BaseModel):
    text: Optional[str] = Field(default=None, max_length=4000)
    action: Optional[str] = None            # "resolved" | "not_fixed": the UI's fixed / still-failing buttons


class FeedbackIn(BaseModel):
    rating: Optional[int] = None
    helpful: Optional[bool] = None
    comment: Optional[str] = Field(default=None, max_length=2000)


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class AssignIn(BaseModel):
    engineer: Optional[str] = None          # username; omitted = assign to me


class PriorityIn(BaseModel):
    priority: str


class ResolveIn(BaseModel):
    resolution: str = Field(min_length=1, max_length=4000)
    promote_to_kb: bool = False


# ---------------------------------------------------------------------------
# graph factories
# ---------------------------------------------------------------------------
GraphFactory = Callable[[DBEventLogger, Settings], object]


def real_graph_factory(logger: DBEventLogger, settings: Settings):
    """The real system: hybrid KB + ticket store, the configured Resolver LLM, conversation state in SQLite."""
    from langgraph.checkpoint.sqlite import SqliteSaver

    from triage.clarifier import Clarifier
    from triage.joint import build_default_deps, build_joint_graph
    from triage.resolver.llm import get_llm
    kb, deps = build_default_deps(get_llm(settings.resolver_llm), logger=logger)
    kb.search("docker", top_k=1)            # warm the embedding model and stores now, not on the first customer's request
    saver = SqliteSaver(sqlite3.connect(settings.checkpoint_path, check_same_thread=False))
    return build_joint_graph(Clarifier(None, kb), deps, checkpointer=saver)


# ---------------------------------------------------------------------------
# app
# ---------------------------------------------------------------------------
def create_app(settings: Optional[Settings] = None, graph_factory: Optional[GraphFactory] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    factory = graph_factory or real_graph_factory

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.warn_if_insecure()
        engine = make_engine(settings.database_url)
        init_db(engine)
        sf = session_factory(engine)
        logger = DBEventLogger(sf)
        app.state.settings, app.state.sf = settings, sf
        app.state.service = ConversationService(sf, factory(logger, settings))
        yield
        engine.dispose()

    app = FastAPI(title="Evidence-first support triage", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(ServiceError)
    async def service_error(_: Request, exc: ServiceError):
        return JSONResponse(status_code=exc.status, content={"detail": exc.detail})

    # -- auth ------------------------------------------------------------------------------------------------
    def current_user(request: Request, authorization: Optional[str] = Header(default=None)) -> User:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "missing bearer token")
        try:
            claims = jwt.decode(authorization[7:], settings.secret, algorithms=["HS256"])
        except jwt.PyJWTError:
            raise HTTPException(401, "invalid or expired token")
        with request.app.state.sf() as s:
            user = s.get(User, int(claims["sub"]))
        if user is None:
            raise HTTPException(401, "unknown user")
        return user

    def engineer(user: User = Depends(current_user)) -> User:
        if user.role != "engineer":
            raise HTTPException(403, "engineers only")
        return user

    def svc(request: Request) -> ConversationService:
        return request.app.state.service

    @app.post("/api/auth/login")
    def login(body: LoginIn, request: Request):
        if body.role not in ("customer", "engineer"):
            raise HTTPException(422, "role must be customer or engineer")
        if body.role == "engineer" and body.passcode != settings.engineer_passcode:
            raise HTTPException(403, "wrong engineer passcode")
        with request.app.state.sf() as s:
            user = s.scalar(select(User).where(User.username == body.username))
            if user is not None and user.role != body.role:
                raise HTTPException(403, f"'{body.username}' is registered as a {user.role}")
            if user is None:
                user = User(username=body.username, role=body.role)
                s.add(user)
                s.commit()
        exp = datetime.now(timezone.utc) + timedelta(hours=settings.token_ttl_hours)
        token = jwt.encode({"sub": str(user.id), "role": user.role, "exp": exp}, settings.secret, algorithm="HS256")
        return {"token": token, "user": {"id": user.id, "username": user.username, "role": user.role}}

    @app.get("/api/me")
    def me(user: User = Depends(current_user)):
        return {"id": user.id, "username": user.username, "role": user.role}

    @app.get("/api/health")
    def health(request: Request):
        p = pricing.table()
        return {"status": "ok", "resolver_llm": settings.resolver_llm, "priced_models": sorted(p.get("models", {})),
                "prices_retrieved": p.get("retrieved")}

    # -- customer --------------------------------------------------------------------------------------------
    @app.post("/api/conversations", status_code=201)
    def start(body: StartIn, user: User = Depends(current_user), service: ConversationService = Depends(svc)):
        if user.role != "customer":
            raise HTTPException(403, "customers only")
        conv_id = service.create(user, body.message)
        return service.customer_view(user, conv_id)

    @app.get("/api/conversations")
    def my_conversations(user: User = Depends(current_user), service: ConversationService = Depends(svc)):
        return {"conversations": service.list_mine(user)}

    @app.get("/api/conversations/{conv_id}")
    def conversation(conv_id: str, after: int = Query(0, description="only messages with id greater than this (for polling)"),
                     user: User = Depends(current_user), service: ConversationService = Depends(svc)):
        return service.customer_view(user, conv_id, after)

    @app.post("/api/conversations/{conv_id}/messages")
    def post_message(conv_id: str, body: MessageIn, user: User = Depends(current_user), service: ConversationService = Depends(svc)):
        service.post_message(user, conv_id, body.text, body.action)
        return service.customer_view(user, conv_id)

    @app.post("/api/conversations/{conv_id}/feedback")
    def feedback(conv_id: str, body: FeedbackIn, user: User = Depends(current_user), service: ConversationService = Depends(svc)):
        service.feedback(user, conv_id, body.rating, body.helpful, body.comment)
        return {"ok": True}

    # -- engineer --------------------------------------------------------------------------------------------
    @app.get("/api/cases")
    def cases(status: Optional[str] = Query(None, description="escalated (default) | resolved | declined | active | all"),
              priority: Optional[str] = None, reason: Optional[str] = None, assigned: Optional[str] = Query(None, description="username or 'unassigned'"),
              q: Optional[str] = None, limit: int = Query(50, le=200), offset: int = 0,
              _: User = Depends(engineer), service: ConversationService = Depends(svc)):
        return service.list_cases(status, priority, reason, assigned, q, limit, offset)

    @app.get("/api/cases/{conv_id}")
    def case(conv_id: str, _: User = Depends(engineer), service: ConversationService = Depends(svc)):
        return service.case_detail(conv_id)

    @app.post("/api/cases/{conv_id}/reply")
    def reply(conv_id: str, body: TextIn, user: User = Depends(engineer), service: ConversationService = Depends(svc)):
        service.engineer_reply(user, conv_id, body.text)
        return service.case_detail(conv_id)

    @app.post("/api/cases/{conv_id}/assign")
    def assign(conv_id: str, body: AssignIn, user: User = Depends(engineer), service: ConversationService = Depends(svc)):
        service.assign(user, conv_id, body.engineer)
        return service.case_detail(conv_id)

    @app.post("/api/cases/{conv_id}/priority")
    def priority(conv_id: str, body: PriorityIn, user: User = Depends(engineer), service: ConversationService = Depends(svc)):
        service.set_priority(user, conv_id, body.priority)
        return service.case_detail(conv_id)

    @app.post("/api/cases/{conv_id}/notes")
    def note(conv_id: str, body: TextIn, user: User = Depends(engineer), service: ConversationService = Depends(svc)):
        service.add_note(user, conv_id, body.text)
        return service.case_detail(conv_id)

    @app.post("/api/cases/{conv_id}/resolve")
    def resolve(conv_id: str, body: ResolveIn, user: User = Depends(engineer), service: ConversationService = Depends(svc)):
        service.resolve(user, conv_id, body.resolution, body.promote_to_kb)
        return service.case_detail(conv_id)

    @app.post("/api/cases/{conv_id}/reopen")
    def reopen(conv_id: str, user: User = Depends(engineer), service: ConversationService = Depends(svc)):
        service.reopen(user, conv_id)
        return service.case_detail(conv_id)

    # -- analytics -------------------------------------------------------------------------------------------
    @app.get("/api/analytics/summary")
    def a_summary(request: Request, days: int = Query(30, ge=1, le=365), _: User = Depends(engineer)):
        with request.app.state.sf() as s:
            return analytics.summary(s, days)

    @app.get("/api/analytics/timeseries")
    def a_series(request: Request, days: int = Query(30, ge=1, le=365), _: User = Depends(engineer)):
        with request.app.state.sf() as s:
            return {"days": analytics.timeseries(s, days)}

    @app.get("/api/analytics/cost")
    def a_cost(request: Request, days: int = Query(30, ge=1, le=365), _: User = Depends(engineer)):
        with request.app.state.sf() as s:
            return analytics.cost(s, days)

    # -- the built frontend (optional): one process serves the API and the UI -------------------------------
    dist = Path(settings.frontend_dir)
    if (dist / "index.html").exists():
        if (dist / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404, "not found")
            candidate = (dist / path).resolve()
            if path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")          # client-side routes (/chat/C-1, /cases/C-1 ...)

    return app
