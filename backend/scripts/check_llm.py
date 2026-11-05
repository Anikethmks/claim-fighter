"""Check that the configured AI provider, key and model work before running real cases.

Usage (from backend/):
    .venv\\Scripts\\python -m scripts.check_llm            # test the configured model
    .venv\\Scripts\\python -m scripts.check_llm --list     # list models the key can use (OpenAI)
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import llm  # noqa: E402
from app.config import settings  # noqa: E402

# A tiny valid PNG is enough to prove the document path works; the text carries the test.
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000100e221bc330000000049454e44ae426082"
)


class Probe(BaseModel):
    insurer_reason_category: Literal["room_rent", "pre_existing_disease", "other"]
    amount: float


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true", help="List available models (OpenAI only).")
    args = parser.parse_args()

    print(f"Provider: {settings.provider}   Model: {settings.model}")
    if args.list:
        if settings.provider != "openai":
            sys.exit("--list is only implemented for OpenAI.")
        from app.providers.openai_provider import client
        names = sorted(m.id for m in client().models.list() if m.id.startswith(("gpt", "o")))
        print("\n".join(names))
        return

    with tempfile.TemporaryDirectory() as tmp:
        img = Path(tmp) / "blank.png"
        img.write_bytes(PNG_1X1)
        doc = llm.CaseDocument(role="other", filename="blank.png", media_type="image/png", path=str(img))
        try:
            result = llm.structured(
                [doc],
                "Ignore the blank image. A letter says: 'Claim cut by Rs 42,000 due to room rent exceeding "
                "eligibility.' Classify the reason and give the amount.",
                Probe,
                step="extract",
            )
        except llm.LLMError as e:
            sys.exit(f"FAILED: {e}")
    print(f"OK: {result}")
    if result.insurer_reason_category != "room_rent" or round(result.amount) != 42000:
        print("Warning: the model answered, but not as expected. Check the model choice.")


if __name__ == "__main__":
    main()
