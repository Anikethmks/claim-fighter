"""Claude via the Anthropic SDK.

Documents get a cache breakpoint after the last one, so extraction,
analysis and drafting reuse the cached documents.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Sequence, TypeVar

import anthropic
from pydantic import BaseModel

from .. import usage
from ..llm import SYSTEM_PROMPT, CaseDocument, LLMError

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=3)
    return _client


def document_blocks(docs: Sequence[CaseDocument]) -> list[dict]:
    blocks: list[dict] = []
    for doc in docs:
        data = base64.standard_b64encode(Path(doc.path).read_bytes()).decode("ascii")
        blocks.append({"type": "text", "text": f"Document ({doc.role}): {doc.filename}"})
        if doc.media_type == "application/pdf":
            blocks.append({
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": data},
                "title": f"{doc.role}: {doc.filename}",
            })
        else:
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": doc.media_type, "data": data},
            })
    if blocks:
        blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks


def _check_stop(response) -> None:
    if response.stop_reason == "refusal":
        raise LLMError("The AI declined to process these documents. Try removing unrelated pages and upload again.")
    if response.stop_reason == "max_tokens":
        raise LLMError("The response was cut off because the documents are very long. Upload fewer pages.")


def _friendly(e: anthropic.APIError) -> LLMError:
    if isinstance(e, anthropic.AuthenticationError):
        return LLMError("Server is missing a valid Anthropic API key (set ANTHROPIC_API_KEY).")
    if isinstance(e, anthropic.BadRequestError):
        return LLMError(f"The documents could not be processed: {e.message}")
    if isinstance(e, anthropic.RateLimitError):
        return LLMError("Too many requests right now. Please try again in a minute.")
    if isinstance(e, anthropic.APIStatusError):
        return LLMError(f"AI service error ({e.status_code}). Please try again.")
    if isinstance(e, anthropic.APIConnectionError):
        return LLMError("Could not reach the AI service. Check the server's internet connection.")
    return LLMError("AI service error. Please try again.")


def _request(docs: Sequence[CaseDocument], instruction: str, model: str, effort: str) -> dict:
    return dict(
        model=model,
        system=SYSTEM_PROMPT,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        output_config={"effort": effort},
        messages=[{"role": "user", "content": [*document_blocks(docs), {"type": "text", "text": instruction}]}],
    )


def _record(response, model: str, started: float) -> None:
    u = response.usage
    # Cache writes cost slightly more than plain input; counted as input here.
    uncached = u.input_tokens + (u.cache_creation_input_tokens or 0)
    usage.record("anthropic", model, uncached, u.cache_read_input_tokens or 0, u.output_tokens, 0,
                 time.monotonic() - started)


def structured(docs: Sequence[CaseDocument], instruction: str, output_type: type[T], model: str, effort: str) -> T:
    started = time.monotonic()
    try:
        response = client().beta.messages.parse(
            **_request(docs, instruction, model, effort), max_tokens=16000, output_format=output_type
        )
    except anthropic.APIError as e:
        raise _friendly(e) from e
    _record(response, model, started)
    _check_stop(response)
    if response.parsed_output is None:
        raise LLMError("The AI returned an unexpected format. Please try again.")
    return response.parsed_output


def text(docs: Sequence[CaseDocument], instruction: str, model: str, effort: str) -> str:
    started = time.monotonic()
    try:
        with client().beta.messages.stream(**_request(docs, instruction, model, effort), max_tokens=32000) as stream:
            response = stream.get_final_message()
    except anthropic.APIError as e:
        raise _friendly(e) from e
    _record(response, model, started)
    _check_stop(response)
    return "".join(b.text for b in response.content if b.type == "text").strip()
