# Test cases and correct answers

All documents are fictional. Upload a case folder's files in the app, then compare.

## case-1-room-rent: Room-rent ratio applied to the whole bill

Files: `policy.pdf`, `bill.pdf`, `rejection-letter.pdf`

**Expected:** Strong (partly). Clause 1.2 excludes pharmacy, implants and diagnostics from 'Associated Medical Expenses', so the 62.5% ratio should apply only to room, nursing, doctor and OT charges (Rs 1,25,000 -> Rs 78,125). Correct payable is about Rs 2,33,125, so about Rs 58,125 is recoverable. The Rs 6,000 for gloves/masks/kit is a valid deduction (weak point).

## case-2-moratorium: Non-disclosure claimed after 7 years of continuous cover

Files: `policy.pdf`, `bill.pdf`, `rejection-letter.pdf`

**Expected:** Strong. Coverage has been continuous since 1 May 2019 (ported in 2024), i.e. over 7 years at admission. Clause 4.4 (moratorium after 60 months) bars contesting the claim for non-disclosure except for proven fraud, and Clause 7.1 gives credit for prior cover. The 36-month PED waiting period was also long over.

## case-3-day-care: Cataract surgery rejected for 'less than 24 hours'

Files: `policy.pdf`, `bill.pdf`, `rejection-letter-photo.jpg`

**Expected:** Strong. Cataract surgery is a listed Day Care procedure (Annexure I), covered under Clause 2.4 regardless of the 24-hour rule. The 24-month cataract waiting period (Clause 4.2) does not apply: the policy has run since March 2022, over 4 years. The rejection letter also comes as a phone-photo image, to test image reading.

## case-4-initial-waiting: Dengue 17 days after buying the policy (insurer is right)

Files: `policy.pdf`, `bill.pdf`, `rejection-letter.pdf`

**Expected:** Weak - the insurer is right. Fresh policy (no portability) started 1 July 2026; dengue began within 30 days and is an illness, not an accident. Clause 4.1 clearly applies. A good tool should say so honestly rather than encourage a complaint.

## case-5-specific-waiting: Knee replacement in year one (insurer is right)

Files: `policy.pdf`, `bill.pdf`, `rejection-letter.pdf`

**Expected:** Weak - the insurer is right. About 11 months of cover against a clearly stated 24-month waiting period for joint replacement/osteoarthritis, and the cause is not an accident. The tool should say the rejection looks valid.

## case-6-no-reason: Rejection letter that gives no reason (workflow must ask)

Files: `policy.pdf`, `bill.pdf`, `rejection-letter.pdf`

**Expected:** The workflow should PAUSE before analysis and ask what reason the insurer gave (the letter gives none). Status 'needs_input', no paid analysis yet. After you answer (e.g. 'They said appendicitis is excluded in the first two years'), it analyses: appendicitis is not in this policy's waiting-period lists and cover started in Feb 2023, so expect a strong case.

## case-7-scanned-pdf: Same as case 3, but the letter is a scanned PDF with no text layer

Files: `policy.pdf`, `bill.pdf`, `rejection-letter-scanned.pdf`

**Expected:** Same as case 3 (Strong). Tests that a scanned PDF (no selectable text) is read correctly.
