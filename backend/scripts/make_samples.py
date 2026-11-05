"""Generate fictional test cases with known correct answers.

Usage (from backend/):
    .venv\\Scripts\\python -m scripts.make_samples

Writes ../samples/<case>/ (policy.pdf, bill.pdf, rejection letter) plus
../samples/expected.json (used by scripts.run_eval) and ../samples/ANSWERS.md
(for checking by hand). Every page is marked as a fictional sample.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = Path(__file__).resolve().parents[2] / "samples"
INSURER = "Suraksha Health Insurance Ltd."
BANNER = "FICTIONAL SAMPLE FOR TESTING - NOT A REAL DOCUMENT"
STYLES = getSampleStyleSheet()

# ---------------------------------------------------------------------------
# Shared policy wording. Clause numbers are what the rejection letters cite.
# ---------------------------------------------------------------------------
WORDING = [
    ("1. Definitions", [
        "1.1 <b>Pre-Existing Disease</b> means any condition, ailment, injury or disease that is diagnosed by a "
        "physician, or for which medical advice or treatment was recommended by or received from a physician, "
        "within 36 months prior to the date of commencement of the first policy issued by the insurer.",
        "1.2 <b>Associated Medical Expenses</b> means room charges, nursing charges, operation theatre charges, "
        "and fees of the medical practitioner, surgeon, anaesthetist and specialist, but excluding the cost of "
        "pharmacy, consumables, implants, medical devices and diagnostics.",
        "1.3 <b>Day Care Treatment</b> means medical treatment or a surgical procedure listed in Annexure I which "
        "is undertaken under general or local anaesthesia in a hospital or day care centre in less than 24 hours "
        "because of technological advancement.",
    ]),
    ("2. Coverage", [
        "2.1 <b>In-patient Hospitalisation.</b> The Company shall indemnify medical expenses incurred for "
        "hospitalisation of the Insured Person for a minimum period of 24 consecutive hours, except for Day Care "
        "Treatment covered under Clause 2.4.",
        "2.4 <b>Day Care Treatment.</b> Medical expenses for Day Care Treatment listed in Annexure I are covered "
        "even where hospitalisation is less than 24 hours.",
    ]),
    ("3. Limits", [
        "3.1 <b>Room Rent.</b> Room, boarding and nursing expenses are payable up to 1% of the Sum Insured per day. "
        "ICU charges are payable up to 2% of the Sum Insured per day. If the Insured Person occupies a room with a "
        "higher rent than the eligible limit, the Associated Medical Expenses shall be payable in the same "
        "proportion as the eligible room rent bears to the actual room rent.",
    ]),
    ("4. Waiting Periods", [
        "4.1 <b>Initial Waiting Period.</b> Expenses for any illness contracted within 30 days from the first policy "
        "commencement date are excluded, except claims arising from an accident.",
        "4.2 <b>Specific Waiting Period.</b> Expenses for the following are excluded until 24 months of continuous "
        "coverage have elapsed since the first policy commencement date: cataract; benign prostatic hypertrophy; "
        "hernia; joint replacement surgery unless necessitated by an accident; treatment of osteoarthritis.",
        "4.3 <b>Pre-Existing Diseases.</b> Expenses related to Pre-Existing Diseases are excluded until 36 months of "
        "continuous coverage have elapsed since the first policy commencement date.",
        "4.4 <b>Moratorium Period.</b> After completion of 60 continuous months of coverage (including portability "
        "and migration), no policy and claim shall be contestable on grounds of non-disclosure or "
        "misrepresentation, except on grounds of established fraud.",
    ]),
    ("5. Exclusions", [
        "5.1 Items listed in Annexure II (non-payable items) are not payable.",
    ]),
    ("7. Portability", [
        "7.1 Where the policy is ported from another insurer, the waiting periods under Clauses 4.2 and 4.3 and the "
        "moratorium under Clause 4.4 shall be reduced to the extent of continuous prior coverage, up to the prior "
        "sum insured.",
    ]),
    ("9. Disclosure", [
        "9.1 The policy shall be void and all premium forfeited in the event of misrepresentation, mis-description "
        "or non-disclosure of any material fact, subject to Clause 4.4.",
    ]),
    ("Annexure I - Day Care Procedures (extract)", [
        "Cataract surgery (phacoemulsification with IOL); Haemodialysis; Chemotherapy; Lithotripsy; "
        "Tonsillectomy; Dilatation and curettage; Coronary angiography.",
    ]),
    ("Annexure II - Non-Payable Items (extract)", [
        "Gloves; face masks; admission kit; toiletries; attendant charges; registration and documentation charges.",
    ]),
]


@dataclass
class Case:
    slug: str
    title: str
    patient: str
    age: int
    policy_no: str
    sum_insured: int
    policy_start: str
    continuity_since: str | None
    previous_insurer: str | None
    hospital: str
    admitted: str
    discharged: str
    diagnosis: str
    procedure: str
    room_rate: int | None
    bill_items: list[tuple[str, int]]
    letter_date: str
    claim_no: str
    paid: int
    letter_body: list[str]
    letter_as_image: bool = False
    expected: dict = field(default_factory=dict)
    answer: str = ""

    @property
    def total(self) -> int:
        return sum(a for _, a in self.bill_items)


def room_rent_case() -> Case:
    items = [
        ("Room rent - Deluxe single (4 days x Rs 8,000)", 32000), ("Nursing charges", 8000),
        ("Surgeon / cardiologist fees", 40000), ("Operation theatre / cath lab charges", 45000),
        ("Drug-eluting stent (implant)", 95000), ("Pharmacy - medicines", 38000),
        ("Diagnostics - angiography, ECG, blood tests", 22000), ("Gloves, masks, admission kit", 6000),
    ]
    ratio = 5000 / 8000
    # Insurer's (wrong) settlement: ratio applied to everything payable.
    payable = sum(a for n, a in items if not n.startswith("Gloves"))
    paid = round(payable * ratio)
    return Case(
        slug="case-1-room-rent", title="Room-rent ratio applied to the whole bill", patient="Ramesh Iyer (fictional)", age=58,
        policy_no="SHI/FAM/2021/004417", sum_insured=500000, policy_start="2021-06-01", continuity_since=None,
        previous_insurer=None, hospital="Lotus Heart Hospital, Pune (fictional)", admitted="2026-08-10",
        discharged="2026-08-14", diagnosis="Coronary artery disease (double vessel)", procedure="PTCA with one drug-eluting stent",
        room_rate=8000, bill_items=items, letter_date="2026-09-05", claim_no="CLM-26-118842", paid=paid,
        letter_body=[
            f"We have processed your reimbursement claim for Rs {sum(a for _, a in items):,} and approved Rs {paid:,}.",
            "Deductions: (a) The insured occupied a room at Rs 8,000 per day against an eligible room rent of Rs 5,000 "
            "per day (1% of Sum Insured) under Clause 3.1. Accordingly, all admissible expenses have been settled in the "
            "proportion of 5,000/8,000 (62.5%). (b) Rs 6,000 towards gloves, masks and admission kit is non-payable "
            "under Clause 5.1 / Annexure II.",
        ],
        expected={"overall": ["strong", "moderate"], "citations_any": ["reg-proportionate-deduction"],
                  "decision": ["partially_settled"], "claim_amount": 286000, "amount_approved": paid},
        answer=("Strong (partly). Clause 1.2 excludes pharmacy, implants and diagnostics from 'Associated Medical "
                "Expenses', so the 62.5% ratio should apply only to room, nursing, doctor and OT charges "
                f"(Rs 1,25,000 -> Rs 78,125). Correct payable is about Rs 2,33,125, so about Rs {233125 - paid:,} is "
                "recoverable. The Rs 6,000 for gloves/masks/kit is a valid deduction (weak point)."),
    )


def moratorium_case() -> Case:
    return Case(
        slug="case-2-moratorium", title="Non-disclosure claimed after 7 years of continuous cover",
        patient="Sunita Deshmukh (fictional)", age=61, policy_no="SHI/IND/2024/019922", sum_insured=1000000,
        policy_start="2024-05-01", continuity_since="2019-05-01", previous_insurer="Raksha General Insurance (fictional)",
        hospital="Sahyadri Care Hospital, Nashik (fictional)", admitted="2026-08-20", discharged="2026-08-24",
        diagnosis="Diabetic foot infection; Type 2 diabetes mellitus", procedure="Surgical debridement and IV antibiotics",
        room_rate=6000, bill_items=[
            ("Room rent (4 days x Rs 6,000)", 24000), ("Nursing charges", 6000), ("Surgeon fees", 35000),
            ("Operation theatre charges", 28000), ("Pharmacy - antibiotics, insulin", 52000),
            ("Diagnostics - cultures, X-ray, blood tests", 18000), ("Dressings and consumables", 22000),
        ],
        letter_date="2026-09-12", claim_no="CLM-26-121907", paid=0,
        letter_body=[
            "We regret to inform you that your claim stands repudiated.",
            "On investigation, hospital records show that the insured has been a known case of Type 2 Diabetes Mellitus "
            "since 2017. This material fact was not disclosed in the proposal form submitted at the time of porting the "
            "policy to Suraksha Health Insurance in May 2024. The claim is therefore repudiated under Clause 9.1 "
            "(Disclosure) and Clause 4.3 (Pre-Existing Diseases).",
        ],
        expected={"overall": ["strong", "moderate"],
                  "citations_any": ["reg-moratorium", "reg-portability-continuity", "reg-ped-waiting"],
                  "decision": ["fully_rejected"], "claim_amount": 185000, "moratorium": True},
        answer=("Strong. Coverage has been continuous since 1 May 2019 (ported in 2024), i.e. over 7 years at admission. "
                "Clause 4.4 (moratorium after 60 months) bars contesting the claim for non-disclosure except for proven "
                "fraud, and Clause 7.1 gives credit for prior cover. The 36-month PED waiting period was also long over."),
    )


def day_care_case() -> Case:
    return Case(
        slug="case-3-day-care", title="Cataract surgery rejected for 'less than 24 hours'",
        patient="Abdul Rahman (fictional)", age=67, policy_no="SHI/SEN/2022/007351", sum_insured=300000,
        policy_start="2022-03-01", continuity_since=None, previous_insurer=None,
        hospital="Clearview Eye Institute, Hyderabad (fictional)", admitted="2026-09-02", discharged="2026-09-02",
        diagnosis="Senile mature cataract, right eye", procedure="Phacoemulsification with foldable IOL (right eye), day care",
        room_rate=None, bill_items=[
            ("Surgeon fees", 18000), ("Operation theatre charges", 12000), ("Intraocular lens (implant)", 22000),
            ("Pharmacy and eye drops", 4500), ("Pre-operative diagnostics", 5500),
        ],
        letter_date="2026-09-20", claim_no="CLM-26-125530", paid=0, letter_as_image=True,
        letter_body=[
            "Your claim has been examined and is not admissible.",
            "Reason: The insured was admitted at 09:00 hrs and discharged at 15:30 hrs on 02-09-2026. The duration of "
            "hospitalisation is less than 24 hours, which does not meet the requirement of Clause 2.1 of the policy. "
            "The claim is therefore rejected.",
        ],
        expected={"overall": ["strong", "moderate"], "citations_any": ["reg-day-care"],
                  "decision": ["fully_rejected"], "claim_amount": 62000},
        answer=("Strong. Cataract surgery is a listed Day Care procedure (Annexure I), covered under Clause 2.4 regardless "
                "of the 24-hour rule. The 24-month cataract waiting period (Clause 4.2) does not apply: the policy has run "
                "since March 2022, over 4 years. The rejection letter also comes as a phone-photo image, to test image reading."),
    )


def initial_waiting_case() -> Case:
    return Case(
        slug="case-4-initial-waiting", title="Dengue 17 days after buying the policy (insurer is right)",
        patient="Priya Nair (fictional)", age=29, policy_no="SHI/IND/2026/031876", sum_insured=500000,
        policy_start="2026-07-01", continuity_since=None, previous_insurer=None,
        hospital="Seaside General Hospital, Kochi (fictional)", admitted="2026-07-18", discharged="2026-07-22",
        diagnosis="Dengue fever with thrombocytopenia", procedure="Medical management, platelet monitoring",
        room_rate=4000, bill_items=[
            ("Room rent (4 days x Rs 4,000)", 16000), ("Nursing charges", 4000), ("Physician fees", 14000),
            ("Pharmacy", 21000), ("Diagnostics - platelet counts, NS1, blood tests", 19000),
        ],
        letter_date="2026-08-03", claim_no="CLM-26-109214", paid=0,
        letter_body=[
            "Your claim is not payable.",
            "The policy commenced on 01-07-2026 and the insured was hospitalised on 18-07-2026 for dengue fever, an illness "
            "contracted within the first 30 days of the policy. Such expenses are excluded under Clause 4.1 (Initial "
            "Waiting Period). This is a first policy with no prior continuous coverage.",
        ],
        expected={"overall": ["weak"], "citations_any": [], "decision": ["fully_rejected"], "claim_amount": 74000},
        answer=("Weak - the insurer is right. Fresh policy (no portability) started 1 July 2026; dengue began within 30 "
                "days and is an illness, not an accident. Clause 4.1 clearly applies. A good tool should say so honestly "
                "rather than encourage a complaint."),
    )


def specific_waiting_case() -> Case:
    return Case(
        slug="case-5-specific-waiting", title="Knee replacement in year one (insurer is right)",
        patient="Harish Gupta (fictional)", age=64, policy_no="SHI/IND/2025/026640", sum_insured=500000,
        policy_start="2025-09-01", continuity_since=None, previous_insurer=None,
        hospital="Medistar Ortho Hospital, Jaipur (fictional)", admitted="2026-08-10", discharged="2026-08-15",
        diagnosis="Primary osteoarthritis, left knee (non-traumatic)", procedure="Total knee replacement, left",
        room_rate=5000, bill_items=[
            ("Room rent (5 days x Rs 5,000)", 25000), ("Nursing charges", 7500), ("Surgeon and anaesthetist fees", 70000),
            ("Operation theatre charges", 48000), ("Knee implant", 145000), ("Pharmacy", 31500), ("Diagnostics", 18000),
        ],
        letter_date="2026-09-01", claim_no="CLM-26-117765", paid=0,
        letter_body=[
            "Your claim stands rejected.",
            "The insured underwent total knee replacement for primary osteoarthritis (not due to accident). The policy "
            "commenced on 01-09-2025 with no prior continuous coverage. Joint replacement and treatment of osteoarthritis "
            "are subject to a 24-month waiting period under Clause 4.2, which had not been completed on the date of "
            "admission.",
        ],
        expected={"overall": ["weak"], "citations_any": [], "decision": ["fully_rejected"], "claim_amount": 345000},
        answer=("Weak - the insurer is right. About 11 months of cover against a clearly stated 24-month waiting period for "
                "joint replacement/osteoarthritis, and the cause is not an accident. The tool should say the rejection "
                "looks valid."),
    )


def no_reason_case() -> Case:
    return Case(
        slug="case-6-no-reason", title="Rejection letter that gives no reason (workflow must ask)",
        patient="Meena Kulkarni (fictional)", age=45, policy_no="SHI/IND/2023/014480", sum_insured=500000,
        policy_start="2023-02-01", continuity_since=None, previous_insurer=None,
        hospital="Riverside Hospital, Surat (fictional)", admitted="2026-08-03", discharged="2026-08-06",
        diagnosis="Acute appendicitis", procedure="Laparoscopic appendectomy",
        room_rate=5000, bill_items=[
            ("Room rent (3 days x Rs 5,000)", 15000), ("Nursing charges", 4500), ("Surgeon and anaesthetist fees", 48000),
            ("Operation theatre charges", 30000), ("Pharmacy", 14500), ("Diagnostics", 9000),
        ],
        letter_date="2026-08-25", claim_no="CLM-26-112093", paid=0,
        letter_body=["We regret that we are unable to process your claim further at this stage.",
                     "For any clarification, please contact our customer care."],
        expected={"pause": "required", "decision": ["fully_rejected", "unknown"], "claim_amount": 121000},
        answer=("The workflow should PAUSE before analysis and ask what reason the insurer gave (the letter gives "
                "none). Status 'needs_input', no paid analysis yet. After you answer (e.g. 'They said appendicitis "
                "is excluded in the first two years'), it analyses: appendicitis is not in this policy's waiting-period "
                "lists and cover started in Feb 2023, so expect a strong case."),
    )


CASES = [room_rent_case(), moratorium_case(), day_care_case(), initial_waiting_case(), specific_waiting_case(),
         no_reason_case()]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _banner(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#b00020"))
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawCentredString(A4[0] / 2, A4[1] - 12 * mm, BANNER)
    canvas.drawCentredString(A4[0] / 2, 10 * mm, BANNER)
    canvas.restoreState()


def _table(rows, widths, header=True):
    t = Table(rows, colWidths=widths)
    style = [("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 9),
             ("VALIGN", (0, 0), (-1, -1), "TOP")]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef3")), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    t.setStyle(TableStyle(style))
    return t


def _build(path: Path, story) -> None:
    SimpleDocTemplate(str(path), pagesize=A4, topMargin=20 * mm, bottomMargin=18 * mm,
                      leftMargin=18 * mm, rightMargin=18 * mm).build(story, onFirstPage=_banner, onLaterPages=_banner)


def write_policy(c: Case, path: Path) -> None:
    p = STYLES["BodyText"]
    rows = [
        ["Policy number", c.policy_no], ["Insured person", f"{c.patient}, age {c.age}"],
        ["Plan", "Suraksha Health Plan (fictional)"], ["Sum insured", f"Rs {c.sum_insured:,}"],
        ["Policy period", f"{c.policy_start} to one year later (renewed annually)"],
        ["First policy commencement date with this insurer", c.policy_start],
        ["Continuous coverage since", c.continuity_since or c.policy_start],
        ["Ported from", c.previous_insurer or "Not applicable (fresh policy)"],
        ["Room rent eligibility", f"1% of sum insured per day (Rs {c.sum_insured // 100:,})"],
    ]
    story = [Paragraph(f"{INSURER} (fictional)", STYLES["Title"]), Paragraph("Policy Schedule", STYLES["Heading2"]),
             _table(rows, [70 * mm, 100 * mm], header=False), PageBreak(),
             Paragraph("Policy Wording (extract)", STYLES["Heading2"])]
    for heading, clauses in WORDING:
        story.append(Paragraph(heading, STYLES["Heading4"]))
        story += [Paragraph(cl, p) for cl in clauses]
    _build(path, story)


def write_bill(c: Case, path: Path) -> None:
    rows = [["Particulars", "Amount (Rs)"]] + [[n, f"{a:,}"] for n, a in c.bill_items] + [["TOTAL", f"{c.total:,}"]]
    meta = [["Patient", c.patient], ["Admitted", c.admitted], ["Discharged", c.discharged],
            ["Diagnosis", c.diagnosis], ["Procedure", c.procedure]]
    _build(path, [Paragraph(c.hospital, STYLES["Title"]), Paragraph("Final Itemised Bill and Discharge Summary", STYLES["Heading2"]),
                  _table(meta, [40 * mm, 130 * mm], header=False), Spacer(1, 8 * mm), _table(rows, [130 * mm, 40 * mm])])


def letter_lines(c: Case) -> list[str]:
    return [f"{INSURER} (fictional) - Claims Department", f"Date: {c.letter_date}", "",
            f"To: {c.patient}", f"Policy No: {c.policy_no}    Claim No: {c.claim_no}",
            f"Hospital: {c.hospital}", f"Claimed: Rs {c.total:,}    Approved: Rs {c.paid:,}", "",
            *c.letter_body, "", "Yours faithfully,", "Claims Manager"]


def write_letter_pdf(c: Case, path: Path) -> None:
    _build(path, [Paragraph(line or "&nbsp;", STYLES["BodyText"]) for line in letter_lines(c)])


def write_letter_image(c: Case, path: Path) -> None:
    """A slightly skewed, off-white 'phone photo' of the letter."""
    import textwrap
    font = ImageFont.truetype("arial.ttf", 26)
    bold = ImageFont.truetype("arialbd.ttf", 26)
    page = Image.new("RGB", (1240, 1650), (250, 248, 240))
    d = ImageDraw.Draw(page)
    d.text((60, 30), BANNER, font=bold, fill=(176, 0, 32))
    y = 100
    for line in letter_lines(c):
        for chunk in textwrap.wrap(line, 80) or [""]:
            d.text((60, y), chunk, font=font, fill=(30, 30, 30))
            y += 38
    photo = Image.new("RGB", (1400, 1800), (120, 110, 95))
    photo.paste(page.rotate(1.5, expand=True, fillcolor=(120, 110, 95)), (60, 40))
    photo.save(path, "JPEG", quality=82)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    expected, answers = {}, ["# Test cases and correct answers\n",
                            "All documents are fictional. Upload a case folder's files in the app, then compare.\n"]
    for c in CASES:
        folder = OUT / c.slug
        folder.mkdir(exist_ok=True)
        write_policy(c, folder / "policy.pdf")
        write_bill(c, folder / "bill.pdf")
        letter = folder / ("rejection-letter-photo.jpg" if c.letter_as_image else "rejection-letter.pdf")
        (write_letter_image if c.letter_as_image else write_letter_pdf)(c, letter)
        expected[c.slug] = {"files": {"policy": "policy.pdf", "bill": "bill.pdf", "rejection": letter.name}, **c.expected}
        answers.append(f"## {c.slug}: {c.title}\n\nFiles: `policy.pdf`, `bill.pdf`, `{letter.name}`\n\n**Expected:** {c.answer}\n")
        print(f"wrote {folder.name}")
    # A file that is not a PDF or image, for testing the upload error.
    (OUT / "not-a-document.txt").write_text("This is a plain text file, not a claim document.\n", encoding="utf-8")
    (OUT / "expected.json").write_text(json.dumps(expected, indent=2), encoding="utf-8")
    (OUT / "ANSWERS.md").write_text("\n".join(answers), encoding="utf-8")
    print(f"\nSamples in {OUT}")


if __name__ == "__main__":
    main()
