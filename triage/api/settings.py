"""Backend settings, from environment variables (a .env file is NOT read here: keep secrets out of the web process's repo)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from triage import config

DATA = config.PROJECT_ROOT / "data" / "processed" / "docker"
DEV_SECRET = "dev-secret-change-me"
DEV_PASSCODE = "engineer-demo"


@dataclass
class Settings:
    database_url: str = f"sqlite:///{(DATA / 'app.db').as_posix()}"
    checkpoint_path: str = str(DATA / "checkpoints.sqlite")       # LangGraph conversation state (survives restarts)
    secret: str = DEV_SECRET                                       # signs login tokens
    engineer_passcode: str = DEV_PASSCODE                          # demo-grade gate for the engineer role
    resolver_llm: str = "fake"                                     # fake (offline) | gemini | anthropic | openai
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])
    token_ttl_hours: int = 12
    frontend_dir: str = str(config.PROJECT_ROOT / "frontend" / "dist")   # served at / when it has been built (npm run build)

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ
        base = cls()
        return cls(
            database_url=e.get("DATABASE_URL", base.database_url), checkpoint_path=e.get("CHECKPOINT_DB", base.checkpoint_path),
            secret=e.get("APP_SECRET", base.secret), engineer_passcode=e.get("ENGINEER_PASSCODE", base.engineer_passcode),
            resolver_llm=e.get("RESOLVER_LLM", base.resolver_llm).lower(),
            cors_origins=[o.strip() for o in e.get("CORS_ORIGINS", ",".join(base.cors_origins)).split(",") if o.strip()],
            token_ttl_hours=int(e.get("TOKEN_TTL_HOURS", base.token_ttl_hours)),
            frontend_dir=e.get("FRONTEND_DIR", base.frontend_dir))

    def warn_if_insecure(self) -> None:
        if self.secret == DEV_SECRET or self.engineer_passcode == DEV_PASSCODE:
            print("WARNING: APP_SECRET / ENGINEER_PASSCODE are the development defaults. Login here is demo-grade "
                  "(no passwords); do not expose this server publicly.", file=sys.stderr)
        Path(self.checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
