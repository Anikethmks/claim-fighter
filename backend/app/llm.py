"""Provider-neutral LLM interface used by the pipeline.

Every step sends the same system prompt followed by the same case
documents, then step-specific instructions, so providers can cache the
documents across extraction, analysis and drafting. The provider is chosen
in config (CF_PROVIDER, or whichever API key is present).
"""

from __future__ import annotations

from typing import Sequence, TypeVar

from pydantic import BaseModel

from . import usage
from .config import settings

T = TypeVar("T", bound=BaseModel)

SYSTEM_PROMPT = """You are ClaimFighter, an assistant that helps people in India understand and \
contest rejected or partially paid health insurance claims.

Ground rules:
- You give information and drafting help, not legal advice. Never promise an outcome.
- Be honest. If the insurer's decision looks correct under the policy, say so plainly; \
a person who files a hopeless complaint wastes months.
- Read the policy wording itself. Insurers often cite a clause that does not say what \
the rejection letter claims, or apply a limit that the policy does not contain.
- Only cite regulations, rules or past decisions that are provided to you as knowledge \
base entries, referring to them by their id. Never cite a circular number, rule, case \
name or award from memory, even if you believe it exists.
- Write for a non-expert: plain language, short sentences, concrete numbers.
- Documents may be photos or scans; if something is unreadable, say what is missing \
instead of guessing."""


class LLMError(RuntimeError):
    """Raised for failures the user should see as a friendly message."""


class CaseDocument(BaseModel):
    role: str
    filename: str
    media_type: str
    path: str


def _provider():
    if settings.provider == "openai":
        from .providers import openai_provider
        return openai_provider
    if settings.provider == "ollama":
        from .providers import ollama_provider
        return ollama_provider
    from .providers import anthropic_provider
    return anthropic_provider


def _model_for(step: str) -> str:
    return settings.extract_model if step == "extract" else settings.model


def structured(docs: Sequence[CaseDocument], instruction: str, output_type: type[T], step: str = "analyse") -> T:
    """Run one pipeline step (extract | analyse | draft) and return a validated object."""
    with usage.step(step):
        return _provider().structured(docs, instruction, output_type, _model_for(step), settings.effort.get(step, "medium"))


def text(docs: Sequence[CaseDocument], instruction: str, step: str = "draft") -> str:
    """Run one pipeline step and return plain text."""
    with usage.step(step):
        return _provider().text(docs, instruction, _model_for(step), settings.effort.get(step, "medium"))
