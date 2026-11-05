"""Local models via Ollama (free, private, slower and less capable).

Meant for development and for privacy-first setups. Differences from the
API providers:
- PDFs are sent as extracted text (local models don't read PDFs directly);
  scanned PDFs without a text layer are rejected with a clear message.
- Photos are downscaled before sending; full-size phone photos are very slow on CPU.
- Ollama's default context window is small and truncates silently, so it is set explicitly.
"""

from __future__ import annotations

import base64
import io
import os
import time
from pathlib import Path
from typing import Sequence, TypeVar

import httpx
from PIL import Image
from pydantic import BaseModel, ValidationError
from pypdf import PdfReader

from .. import usage
from ..config import settings
from ..llm import SYSTEM_PROMPT, CaseDocument, LLMError

T = TypeVar("T", bound=BaseModel)

NUM_CTX = int(os.getenv("CF_OLLAMA_NUM_CTX", "16384"))
MAX_IMAGE_SIDE = 1600
TIMEOUT = httpx.Timeout(1800.0, connect=5.0)  # CPU inference can take many minutes


def _pdf_text(doc: CaseDocument) -> str:
    try:
        reader = PdfReader(doc.path)
        pages = [p.extract_text() or "" for p in reader.pages]
    except Exception as e:
        raise LLMError(f"Could not read {doc.filename}: {e}") from e
    if sum(len(p.strip()) for p in pages) < 40 * max(1, len(pages)):
        raise LLMError(
            f"{doc.filename} looks like a scanned PDF. Local mode can't read scanned PDFs yet; "
            "upload photos of the pages instead."
        )
    return "\n\n".join(f"[page {i + 1}]\n{p}" for i, p in enumerate(pages))


def _image_b64(path: str) -> str:
    img = Image.open(path)
    img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _messages(docs: Sequence[CaseDocument], instruction: str) -> list[dict]:
    parts, images = [], []
    for doc in docs:
        if doc.media_type == "application/pdf":
            parts.append(f'<document role="{doc.role}" name="{doc.filename}">\n{_pdf_text(doc)}\n</document>')
        else:
            images.append(_image_b64(doc.path))
            parts.append(f'<document role="{doc.role}" name="{doc.filename}">[attached image {len(images)}]</document>')
    user = {"role": "user", "content": "\n\n".join(parts) + "\n\n" + instruction}
    if images:
        user["images"] = images
    return [{"role": "system", "content": SYSTEM_PROMPT}, user]


def _chat(model: str, messages: list[dict], fmt: dict | None) -> str:
    body = {"model": model, "messages": messages, "stream": False, "options": {"num_ctx": NUM_CTX}}
    if fmt is not None:
        body["format"] = fmt
    started = time.monotonic()
    try:
        r = httpx.post(f"{settings.ollama_url}/api/chat", json=body, timeout=TIMEOUT)
    except httpx.ConnectError as e:
        raise LLMError("Ollama is not running. Start the Ollama app, then try again.") from e
    except httpx.TimeoutException as e:
        raise LLMError("The local model took too long. Try fewer pages or a smaller model.") from e
    except httpx.TransportError as e:
        # Typically Ollama crashing mid-request, e.g. out of memory on a large prompt.
        raise LLMError("The local model stopped responding (often out of memory). Try a smaller model "
                       "or lower CF_OLLAMA_NUM_CTX.") from e
    if r.status_code == 404:
        raise LLMError(f"Local model '{model}' is not installed. Run: ollama pull {model}")
    if r.status_code >= 400:
        raise LLMError(f"Local model error: {r.text[:300]}")
    data = r.json()
    usage.record("ollama", model, data.get("prompt_eval_count", 0), 0, data.get("eval_count", 0), 0,
                 time.monotonic() - started)
    if data.get("done_reason") == "length":
        raise LLMError("The local model ran out of room. Increase CF_OLLAMA_NUM_CTX or upload fewer pages.")
    return data["message"]["content"]


def structured(docs: Sequence[CaseDocument], instruction: str, output_type: type[T], model: str, effort: str) -> T:
    messages = _messages(docs, instruction)
    schema = output_type.model_json_schema()
    content = _chat(model, messages, schema)
    try:
        return output_type.model_validate_json(content)
    except ValidationError as first_error:
        # Small models sometimes slip; one corrective retry.
        messages += [{"role": "assistant", "content": content},
                     {"role": "user", "content": f"That JSON did not match the schema: {first_error}. Return corrected JSON only."}]
        content = _chat(model, messages, schema)
        try:
            return output_type.model_validate_json(content)
        except ValidationError as e:
            raise LLMError("The local model returned an unexpected format. Try again or use a larger model.") from e


def text(docs: Sequence[CaseDocument], instruction: str, model: str, effort: str) -> str:
    return _chat(model, _messages(docs, instruction), None).strip()
