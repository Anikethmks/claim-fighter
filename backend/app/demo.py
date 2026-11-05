"""Demo mode (CF_DEMO=1): canned LLM responses so the app can be explored without an API key.

Everything except the two LLM calls runs for real: uploads, storage,
retrieval, the citation guard and the deadline engine. The UI shows a
banner whenever this mode is on.
"""

from __future__ import annotations

import time

from . import llm
from .schemas import Analysis, CaseFacts, Deduction, Issue, SelfCheck

SAMPLE_FACTS = CaseFacts(
    insurer_name="Sample Health Insurance Co. (demo)", policy_name="Family Health Plan", policy_number="DEMO-0001",
    policy_type="family_floater", policy_start_date="2023-04-01", continuous_coverage_since="2019-04-01",
    sum_insured=500000.0, room_rent_limit="1% of sum insured per day (₹5,000)", patient_age=58,
    hospital_name="City Care Hospital", admission_date="2026-08-10", discharge_date="2026-08-14",
    diagnosis="Coronary artery disease", treatment="Angioplasty with one drug-eluting stent",
    claim_type="reimbursement", claim_amount=310000.0, amount_approved=176000.0, decision="partially_settled",
    decision_date="2026-09-05", specific_reason_given=True,
    rejection_reasons=[
        "Proportionate deduction applied as room rent (₹8,000/day) exceeded eligibility (₹5,000/day)",
        "Non-medical consumables not payable",
    ],
    clauses_cited_by_insurer=["Clause 3.1 (Room rent limit)", "Annexure II (Non-payable items)"],
    deductions=[
        Deduction(item="Proportionate deduction on hospital bill incl. stent and pharmacy", amount=124000.0,
                  reason_given="Room rent exceeded eligibility"),
        Deduction(item="Gloves, masks, admission kit", amount=10000.0, reason_given="Non-payable items"),
    ],
    documents_missing_or_unreadable=[],
    summary=("A 58-year-old was admitted for 4 days for angioplasty. The insurer paid ₹1,76,000 of the ₹3,10,000 "
             "claim, cutting ₹1,24,000 by applying the room-rent ratio to the whole bill and ₹10,000 as non-payable items."),
)

SAMPLE_ANALYSIS = Analysis(
    overall_strength="strong",
    headline=("Most of the ₹1,34,000 cut comes from applying the room-rent ratio to the stent and medicines, "
              "which the rules don't allow. The ₹10,000 for gloves and masks is probably a valid deduction."),
    issues=[
        Issue(
            title="Room-rent ratio applied to the stent and medicines",
            insurer_position="Room rent was ₹8,000/day against an eligibility of ₹5,000/day, so every charge was cut in that proportion.",
            assessment=("Proportionate deduction can apply to charges linked to the room category, but not to implants, "
                        "pharmacy, consumables or diagnostics. The stent (₹95,000) and pharmacy (₹38,000) should be "
                        "excluded from the ratio. Roughly ₹1,00,000 of the deduction looks recoverable."),
            strength="strong", amount_at_stake=100000.0,
            citation_ids=["reg-proportionate-deduction", "reg-rejection-in-writing"],
            evidence_to_gather=["Itemised final bill showing stent, pharmacy and diagnostics separately",
                                "Hospital's tariff showing whether charges differ by room category"],
        ),
        Issue(
            title="Room-rent ratio on remaining hospital charges",
            insurer_position="Doctor fees and nursing were cut in the same ratio.",
            assessment=("This part follows the policy's room-rent clause, unless the hospital charges the same rates "
                        "for every room category. Worth asking the hospital for a letter on this."),
            strength="moderate", amount_at_stake=24000.0, citation_ids=["reg-proportionate-deduction"],
            evidence_to_gather=["Letter from hospital stating whether it follows differential billing"],
        ),
        Issue(
            title="Gloves, masks and admission kit",
            insurer_position="Listed as non-payable items.",
            assessment="These are on the standard non-payable list and the policy has no consumables add-on. The insurer is likely right here.",
            strength="weak", amount_at_stake=10000.0, citation_ids=["reg-non-payable-items"],
            evidence_to_gather=[],
        ),
    ],
    amount_recoverable_estimate=124000.0,
    questions_for_user=["Was a room within the ₹5,000/day limit available when you were admitted?",
                        "Does the hospital charge different procedure rates for different room types?"],
    honest_caveats=["This is a sample demo case, not an analysis of your documents."],
    recommended_next_stage="insurer_grievance",
)

SAMPLE_LETTER = """To,
The Grievance Redressal Officer
Sample Health Insurance Co.

Subject: Request to review partial settlement of claim under policy DEMO-0001

Dear Sir/Madam,

I write regarding my reimbursement claim of ₹3,10,000 for hospitalisation at City Care Hospital from 10 August 2026 to 14 August 2026, which was settled for ₹1,76,000 on 5 September 2026.

The settlement letter applies a proportionate deduction to the entire hospital bill because the room rent exceeded the eligible limit under Clause 3.1. Proportionate deduction cannot be applied to implants, pharmacy, consumables or diagnostics [[kb:reg-proportionate-deduction]]. The drug-eluting stent (₹95,000) and pharmacy charges (₹38,000) have nonetheless been reduced in the same ratio.

I request that you re-compute the settlement excluding these items from the proportionate deduction and pay the balance due. If you maintain the deduction, please give the specific policy clause and the calculation in writing [[kb:reg-rejection-in-writing]].

Enclosures: policy schedule, settlement letter, itemised final bill.

Yours faithfully,
[Your full name]
[Your address]
[Your phone number]"""


def _structured(docs, instruction, output_type, step="analyse"):
    time.sleep(2)  # let the progress UI show
    if output_type is CaseFacts:
        return SAMPLE_FACTS
    if output_type is Analysis:
        return SAMPLE_ANALYSIS
    if output_type is SelfCheck:
        return SelfCheck(consistent=True, problems=[])
    raise llm.LLMError("Demo mode only supports case analysis.")


def _text(docs, instruction, step="draft"):
    time.sleep(2)
    return SAMPLE_LETTER


def enable() -> None:
    llm.structured = _structured
    llm.text = _text
