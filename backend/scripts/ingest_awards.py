"""Ingest Insurance Ombudsman award PDFs into the knowledge base.

Usage (from backend/):
    .venv\\Scripts\\python -m scripts.ingest_awards path\\to\\award_pdfs [--source-url URL]

Download award PDFs from the official Council for Insurance Ombudsmen
website (https://www.cioins.co.in) first. Each PDF is read by Claude,
non-health awards are skipped, and health awards are stored as
`ombudsman_award` entries. Re-running is safe: ids are derived from the file
hash, so the same PDF updates its existing entry.

Entries are stored as unverified because the summary is machine-written;
the original PDF stays the source of truth.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import llm  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import connect, init_db  # noqa: E402
from app.knowledge import store  # noqa: E402


class AwardRecord(BaseModel):
    is_health_insurance_claim_dispute: bool
    insurer_name: Optional[str]
    ombudsman_office: Optional[str]
    award_date: Optional[str]
    complaint_reference: Optional[str]
    dispute_category: Literal[
        "pre_existing_disease_non_disclosure", "room_rent_proportionate_deduction", "waiting_period",
        "exclusion_clause", "hospitalisation_not_required", "documents_or_procedure",
        "reasonable_customary_charges", "consumables_non_payable", "cashless_denial", "delay", "other",
    ]
    insurer_reason: str
    outcome: Literal["allowed", "partly_allowed", "dismissed", "settled_in_mediation", "unclear"]
    amount_claimed: Optional[float]
    amount_awarded: Optional[float]
    reasoning_summary: str
    principles: list[str]
    keywords: list[str]


INSTRUCTION = """The document above is an Insurance Ombudsman award (India). Extract a record of it.

- is_health_insurance_claim_dispute: false for life, motor, travel or other non-health awards.
- insurer_reason: the insurer's ground for rejecting or cutting the claim, in one or two sentences.
- reasoning_summary: 3-5 plain sentences on why the Ombudsman decided as it did.
- principles: short, reusable statements the Ombudsman applied (e.g. "Proportionate deduction \
cannot be applied to pharmacy and implants"). Only what the award actually says.
- keywords: search terms a policyholder with a similar case would use.
- Use null for anything not stated. Dates as YYYY-MM-DD."""


def ingest_file(conn, pdf: Path, source_url: str | None) -> str:
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()[:12]
    doc = llm.CaseDocument(role="award", filename=pdf.name, media_type="application/pdf", path=str(pdf))
    rec = llm.structured([doc], INSTRUCTION, AwardRecord, step="extract")
    if not rec.is_health_insurance_claim_dispute:
        return "skipped (not health)"

    outcome_text = rec.outcome.replace("_", " ")
    amount = ""
    if rec.amount_awarded is not None:
        amount = f" Awarded ₹{rec.amount_awarded:,.0f}"
        amount += f" of ₹{rec.amount_claimed:,.0f} claimed." if rec.amount_claimed else "."
    body = (
        f"Insurer: {rec.insurer_name or 'not stated'}. Ombudsman office: {rec.ombudsman_office or 'not stated'}. "
        f"Date: {rec.award_date or 'not stated'}.\n"
        f"Insurer's ground: {rec.insurer_reason}\n"
        f"Outcome: {outcome_text}.{amount}\n"
        f"Reasoning: {rec.reasoning_summary}\n"
        + ("Principles applied: " + " ".join(f"- {p}" for p in rec.principles) if rec.principles else "")
    )
    store.upsert(conn, {
        "id": f"award-{digest}",
        "kind": "ombudsman_award",
        "title": f"Ombudsman award ({outcome_text}): {rec.dispute_category.replace('_', ' ')}"
                 + (f" vs {rec.insurer_name}" if rec.insurer_name else ""),
        "body": body,
        "source_name": f"Insurance Ombudsman award {rec.complaint_reference or pdf.name}",
        "source_url": source_url,
        "tags": " ".join([rec.dispute_category.replace("_", " "), rec.insurer_name or "", *rec.keywords]),
        "verified": False,
        "meta": {"file": pdf.name, "sha": digest, **rec.model_dump(exclude={"keywords"})},
    })
    conn.commit()
    return f"stored as award-{digest} ({outcome_text})"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--source-url", default="https://www.cioins.co.in",
                        help="Where these awards were downloaded from (shown to users as the source).")
    args = parser.parse_args()

    pdfs = sorted(args.folder.glob("*.pdf"))
    if not pdfs:
        sys.exit(f"No PDFs found in {args.folder}")

    conn = connect(settings.db_path)
    init_db(conn)
    ok = failed = 0
    for pdf in pdfs:
        try:
            print(f"{pdf.name}: {ingest_file(conn, pdf, args.source_url)}")
            ok += 1
        except llm.LLMError as e:
            print(f"{pdf.name}: FAILED - {e}")
            failed += 1
    print(f"\nDone. {ok} processed, {failed} failed. Knowledge base now: {store.stats(conn)}")


if __name__ == "__main__":
    main()
