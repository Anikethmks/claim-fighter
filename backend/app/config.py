"""Runtime configuration, read once from environment / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    provider: str           # "anthropic" | "openai" | "ollama"
    model: str              # analysis and drafting
    extract_model: str      # reading facts off documents (an easier task)
    effort: dict[str, str]  # per pipeline step: extract | analyse | draft
    ollama_url: str
    # Uploaded medical documents are deleted after this many days.
    retention_days: int
    max_upload_mb: int
    cors_origins: list[str]
    # Canned LLM responses for exploring the UI without an API key.
    demo: bool
    env: str                     # "dev" | "prod"
    smtp: dict                   # host, port, user, password, sender; empty host = log codes (dev only)
    admin_emails: set[str]
    daily_budget_usd: float      # stop new AI work once today's spend reaches this
    max_cases_per_user_day: int

    @property
    def prod(self) -> bool:
        return self.env == "prod"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "claimfighter.db"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"


# (analysis/draft model, extraction model).
# OpenAI: gpt-5.4-mini passed 5/5 sample cases at ~$0.01-0.03 per case (2026-11-04), vs ~$0.23 for
# gpt-5.5 at high effort. Re-run scripts.run_eval with CF_MODEL=gpt-5.5 on real documents before launch.
DEFAULT_MODELS = {
    "anthropic": ("claude-opus-5-5", "claude-opus-5-5"),
    "openai": ("gpt-5.4-mini", "gpt-5.4-mini"),
    "ollama": ("qwen3-vl:8b", "qwen3-vl:8b"),
}
# Chosen with scripts.run_eval: lowest settings that still pass the sample cases.
DEFAULT_EFFORT = {"extract": "low", "analyse": "medium", "check": "low", "draft": "low", "chat": "low"}


def _provider() -> str:
    explicit = os.getenv("CF_PROVIDER", "").strip().lower()
    if explicit in DEFAULT_MODELS:
        return explicit
    # Otherwise use whichever key is configured, preferring Anthropic when both are.
    if not os.getenv("ANTHROPIC_API_KEY") and os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "anthropic"


def load_settings() -> Settings:
    data_dir = Path(os.getenv("CF_DATA_DIR", BACKEND_DIR / "data"))
    provider = _provider()
    model, extract_model = DEFAULT_MODELS[provider]
    return Settings(
        data_dir=data_dir,
        provider=provider,
        model=os.getenv("CF_MODEL") or model,
        extract_model=os.getenv("CF_EXTRACT_MODEL") or os.getenv("CF_MODEL") or extract_model,
        effort={s: os.getenv(f"CF_EFFORT_{s.upper()}") or e for s, e in DEFAULT_EFFORT.items()},
        ollama_url=os.getenv("CF_OLLAMA_URL", "http://localhost:11434").rstrip("/"),
        retention_days=int(os.getenv("CF_RETENTION_DAYS", "30")),
        max_upload_mb=int(os.getenv("CF_MAX_UPLOAD_MB", "20")),
        cors_origins=[o.strip() for o in os.getenv("CF_CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()],
        demo=os.getenv("CF_DEMO", "").lower() in ("1", "true", "yes"),
        env=os.getenv("CF_ENV", "dev").lower(),
        smtp={"host": os.getenv("CF_SMTP_HOST", ""), "port": int(os.getenv("CF_SMTP_PORT", "587")),
              "user": os.getenv("CF_SMTP_USER", ""), "password": os.getenv("CF_SMTP_PASSWORD", ""),
              "sender": os.getenv("CF_EMAIL_FROM", "")},
        admin_emails={e.strip().lower() for e in os.getenv("CF_ADMIN_EMAILS", "").split(",") if e.strip()},
        daily_budget_usd=float(os.getenv("CF_DAILY_BUDGET_USD", "2.0")),
        max_cases_per_user_day=int(os.getenv("CF_MAX_CASES_PER_USER_DAY", "5")),
    )


settings = load_settings()
