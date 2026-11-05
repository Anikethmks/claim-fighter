"""OpenAI via the Responses API.

OpenAI caches repeated prompt prefixes automatically; the instructions and
documents come first and `prompt_cache_key` groups a case's three calls so
they land on the same cache.
"""

from __future__ import annotations

import base64
import hashlib
import time
from pathlib import Path
from typing import Sequence, TypeVar

import openai
from pydantic import BaseModel

from .. import usage
from ..llm import SYSTEM_PROMPT, CaseDocument, LLMError

T = TypeVar("T", bound=BaseModel)

_client: openai.OpenAI | None = None


def client() -> openai.OpenAI:
    global _client
    if _client is None:
        _client = openai.OpenAI(max_retries=3)
    return _client


def content_parts(docs: Sequence[CaseDocument]) -> list[dict]:
    parts: list[dict] = []
    for doc in docs:
        data = base64.standard_b64encode(Path(doc.path).read_bytes()).decode("ascii")
        parts.append({"type": "input_text", "text": f"Document ({doc.role}): {doc.filename}"})
        if doc.media_type == "application/pdf":
            parts.append({
                "type": "input_file",
                "filename": doc.filename,
                "file_data": f"data:application/pdf;base64,{data}",
            })
        else:
            parts.append({
                "type": "input_image",
                "image_url": f"data:{doc.media_type};base64,{data}",
                "detail": "high",  # small print on scanned letters matters
            })
    return parts


def _cache_key(docs: Sequence[CaseDocument]) -> str:
    return "cf-" + hashlib.sha256("|".join(d.path for d in docs).encode()).hexdigest()[:24]


def _request(docs: Sequence[CaseDocument], instruction: str, model: str, effort: str, max_tokens: int) -> dict:
    return dict(
        model=model,
        instructions=SYSTEM_PROMPT,
        input=[{"role": "user", "content": [*content_parts(docs), {"type": "input_text", "text": instruction}]}],
        reasoning={"effort": effort},
        max_output_tokens=max_tokens,
        prompt_cache_key=_cache_key(docs),
    )


def _friendly(e: openai.APIError, model: str) -> LLMError:
    if isinstance(e, openai.AuthenticationError):
        return LLMError("Server is missing a valid OpenAI API key (set OPENAI_API_KEY).")
    if isinstance(e, openai.NotFoundError):
        return LLMError(f"Model '{model}' is not available on this OpenAI account. Set CF_MODEL to a model you can use.")
    if isinstance(e, openai.BadRequestError):
        return LLMError(f"The documents could not be processed: {e.message}")
    if isinstance(e, openai.RateLimitError):
        return LLMError("Too many requests, or the OpenAI account is out of credit. Please try again shortly.")
    if isinstance(e, openai.APIStatusError):
        return LLMError(f"AI service error ({e.status_code}). Please try again.")
    if isinstance(e, openai.APIConnectionError):
        return LLMError("Could not reach the AI service. Check the server's internet connection.")
    return LLMError("AI service error. Please try again.")


def _check(response) -> None:
    if response.status == "incomplete":
        reason = getattr(response.incomplete_details, "reason", None)
        if reason == "max_output_tokens":
            raise LLMError("The response was cut off because the documents are very long. Upload fewer pages.")
        raise LLMError("The AI declined to process these documents. Try removing unrelated pages and upload again.")
    for item in response.output:
        if item.type == "message" and any(c.type == "refusal" for c in item.content):
            raise LLMError("The AI declined to process these documents. Try removing unrelated pages and upload again.")


def _record(response, model: str, started: float) -> None:
    u = response.usage
    if u is None:
        return
    cached = getattr(u.input_tokens_details, "cached_tokens", 0) or 0
    usage.record("openai", model, u.input_tokens - cached, cached, u.output_tokens,
                 getattr(u.output_tokens_details, "reasoning_tokens", 0) or 0, time.monotonic() - started)


def structured(docs: Sequence[CaseDocument], instruction: str, output_type: type[T], model: str, effort: str) -> T:
    started = time.monotonic()
    try:
        response = client().responses.parse(**_request(docs, instruction, model, effort, 16000), text_format=output_type)
    except openai.APIError as e:
        raise _friendly(e, model) from e
    _record(response, model, started)
    _check(response)
    if response.output_parsed is None:
        raise LLMError("The AI returned an unexpected format. Please try again.")
    return response.output_parsed


def text(docs: Sequence[CaseDocument], instruction: str, model: str, effort: str) -> str:
    started = time.monotonic()
    try:
        response = client().responses.create(**_request(docs, instruction, model, effort, 32000))
    except openai.APIError as e:
        raise _friendly(e, model) from e
    _record(response, model, started)
    _check(response)
    return response.output_text.strip()
