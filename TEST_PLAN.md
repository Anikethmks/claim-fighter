# Manual test plan: every workflow path

All test files are in `samples\` (fictional documents). Expected answers are also in `samples\ANSWERS.md`.

**Start the app first:**
```powershell
cd D:\Workspace\Personal\claim-fighter\backend
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```
Open http://localhost:8000 and sign in (Part 0). Each new case costs about ₹2–5; chat questions cost about ₹0.5–1 each.

AI answers vary slightly between runs. Judge the **meaning** (verdict, amounts, which tool the agent used), not the exact wording.

---

## Part 0: Sign-in, consent, privacy, dashboard

Locally, sign-in codes are printed in the server terminal (`DEV LOGIN CODE for …`). For the dashboard, add `CF_ADMIN_EMAILS=<your email>` to `backend\.env` and restart.

| # | Do this | Expect |
|---|---|---|
| L1 | Open the home page while signed out | The intro text plus a **"Sign in to start your case"** card; no upload form |
| L2 | Enter your email → **Email me a code** → type the code from the terminal | You're signed in; the email and **Sign out** show at the top right |
| L3 | Type a wrong code | "Wrong code…" |
| L4 | Pick files but don't tick the consent box → Analyse | "Please tick the consent box…" |
| L5 | Click **Privacy details** / the footer **Privacy** link | The privacy page |
| L6 | After creating a case, return home | **"Your cases"** lists it, with the insurer and verdict |
| L7 | Sign out, then open a case link | **"Sign in to see this case"** |
| L8 | Sign in as a **different** email and open the first user's case link | "Couldn't open this case" (cases are private) |
| L9 | As the admin email, click **Dashboard** | Users, cases, letters, outcomes, cost per case, and a daily table |
| L10 | Start a 6th case in one day | "You can start up to 5 cases a day" |

☐ L1 ☐ L2 ☐ L3 ☐ L4 ☐ L5 ☐ L6 ☐ L7 ☐ L8 ☐ L9 ☐ L10

---

## Part A: Verdicts (one upload each)

For each case, upload the three files in that folder (policy → Policy, bill → Hospital bill, rejection letter → Rejection letter) and click **Analyse my claim**.

**What you should see every time:**
1. A progress screen: "Reading your documents" → "Checking the rules…" → "Double-checking it against your policy". It may briefly say the double-check found something to fix.
2. The verdict page, with **"✓ Double-checked against your policy documents"** (or an amber "points to verify" note).

| # | Folder | Expected verdict | Also check |
|---|---|---|---|
| A1 | `case-1-room-rent` | **Strong or Moderate**, about **₹58,125** recoverable | The stent/pharmacy issue is Strong; the gloves/masks issue is Weak |
| A2 | `case-2-moratorium` | **Strong** | Mentions continuous cover since 2019 and the 60-month moratorium; "Covered since 1 May 2019" |
| A3 | `case-3-day-care` (letter is a **photo**) | **Strong** | Reads the photo correctly; says cataract is a listed day-care procedure |
| A4 | `case-4-initial-waiting` | **Weak**: the insurer is right | Blue box: "Our honest view: … complaint is unlikely to succeed" |
| A5 | `case-5-specific-waiting` | **Weak**: the insurer is right | Same honest-view box |

☐ A1 ☐ A2 ☐ A3 ☐ A4 ☐ A5

---

## Part B: Workflow pauses (LangGraph)

### B1. Required question: the workflow stops before analysing
- Upload `case-6-no-reason` (all three files). The letter gives **no reason**.
- **Expect:** a page titled **"We need a little more information"** asking what reason the insurer gave. Only about ₹0.3 has been spent at this point.
- Click **Re-check my case** with the box empty → the button stays disabled; you can't continue without an answer.
- Type `They said appendicitis is excluded in the first two years` and click **Re-check my case**.
- **Expect:** "Analysing…" → a verdict, most likely **Strong** (appendicitis isn't in this policy's waiting-period lists, and cover started in Feb 2023).

☐ B1

### B2. Optional questions: answer them
- On any case from Part A, look for the card **"Answer these to sharpen your verdict"** under the verdict. Whether it appears depends on whether the AI had questions.
- Answer one question and click **Re-check my case**.
- **Expect:** "Re-checking your case" → the page reloads with an updated analysis, and that question is no longer asked.

☐ B2

### B3. Optional questions: skip
- On another case that shows the card, click **Skip**.
- **Expect:** the card disappears instantly; nothing else changes, and no AI cost.

☐ B3

### B4. Self-check retry (can't be forced)
- Sometimes the double-check finds an error and the analysis is redone. You'll briefly see "The double-check found something to fix…" on the progress screen.
- It happened in one of our test runs. You can't force it from the UI. To see it in logs, run `.venv\Scripts\python -m scripts.run_eval --case case-4-initial-waiting` and look for `analyse -> self_check -> analyse -> self_check`.

---

## Part C: Case Assistant chat (OpenAI Agents SDK)

Use the **"Ask about your case"** box on a finished case. Under each answer, check the small line "Agent read your case · …", which shows the tools it chose.

| # | Case | Ask | Expected tool(s) | Expected answer |
|---|---|---|---|---|
| C1 | case 1 | `When is my last date to go to the Ombudsman?` | checked deadlines | First complain to the insurer; the Ombudsman opens after their reply or after 1 month. No made-up date |
| C2 | case 1 | `What does the rule say about medicines and implants?` | searched the rules | Explains the room-rent ratio doesn't apply to pharmacy/implants; **"Show sources"** opens a rule |
| C3 | case 1 | `No room within my room-rent limit was available when I was admitted.` | noted a new fact | Says the case will be re-checked → **the page switches to "Re-checking your case"**, then shows the updated analysis |
| C4 | case 4 | `Is there any point in complaining?` | read your case | Honest: probably not, because of the 30-day waiting period |
| C5 | case 2 | `Write the complaint letter in simpler English` | drafted a letter | The letter appears under **"Get your complaint drafted"** |
| C6 | any | A message over 1,000 characters | none | Error: keep questions under 1,000 characters |

☐ C1 ☐ C2 ☐ C3 ☐ C4 ☐ C5 ☐ C6

---

## Part D: Deadlines, letters, outcome

| # | Do this | Expect |
|---|---|---|
| D1 | Case 1 → "Your steps and deadlines" → **Update what has happened** → "I sent my complaint" = today | The Ombudsman step shows **Earliest** = one month from today and **Last date** = one year after that |
| D2 | Also set "Insurer replied" = today | The Ombudsman becomes **Do this now**, with the last date one year from today |
| D3 | Clear a date | The timeline goes back to how it was |
| D4 | "Get your complaint drafted" → Complaint to insurer → enter a name → **Draft the letter** | The letter uses the real amounts and clause numbers, with numbered references [1], [2] listed under it; **Copy** and **Download** work |
| D5 | Choose **Insurance Ombudsman** and draft again | A different, more formal complaint format |
| D6 | "How did it go?" → **Got paid partly** → amount → Save | Shows "Saved, thank you"; still there after a page refresh |

☐ D1 ☐ D2 ☐ D3 ☐ D4 ☐ D5 ☐ D6

---

## Part D2: New features

| # | Do this | Expect |
|---|---|---|
| N1 | Upload a case with a real insurer's name in the letter (e.g. Star Health) | The analysis mentions that insurer's Ombudsman record as a numbered source ("Ombudsman record"); fictional insurers get only the all-insurers figure |
| N2 | Upload `case-7-scanned-pdf` (the letter is a scanned PDF) | Same verdict as case 3 (Strong) |
| N3 | On a case, set "I sent my complaint" → the **Got a reply from the insurer?** box appears → paste a reply → **Draft my Ombudsman complaint** | The Ombudsman step shows the new dates, and an Ombudsman letter answering the reply appears under drafts |
| N4 | Reminders (local): keep the server running for over a minute after creating a strong case dated 3+ days ago, or run `python -c "from app import reminders, db; from app.config import settings; print(reminders.send_due(db.connect(settings.db_path)))"` | `DEV EMAIL to …` lines in the server terminal |

☐ N1 ☐ N2 ☐ N3 ☐ N4

---

## Part E: Errors and edge cases

| # | Do this | Expect |
|---|---|---|
| E1 | Click **Analyse my claim** with no files | "Please add the rejection or settlement letter…" |
| E2 | Upload `samples\not-a-document.txt` as the rejection letter | Error: file must be a PDF, JPG, PNG or WEBP |
| E3 | Upload **only** `case-1-room-rent\rejection-letter.pdf` (no policy, no bill) | It still analyses, with a blue note listing the missing documents; the verdict is more cautious |
| E4 | Open http://localhost:8000/#/case/doesnotexist | "Couldn't open this case" |
| E5 | On any case, click **Delete this case and my documents** → confirm | Back to home; the case's link no longer opens |

☐ E1 ☐ E2 ☐ E3 ☐ E4 ☐ E5

---

## Part F: Cost and demo mode

| # | Do this | Expect |
|---|---|---|
| F1 | As the admin, open http://localhost:8000/api/usage (or the Dashboard) | Spend by day and model; the total should roughly match ₹2–5 per case tested. Non-admins get "Admins only" |
| F2 | Stop the server, then run `$env:CF_DEMO="1"; .venv\Scripts\python -m uvicorn app.main:app --port 8000` and upload any file | An orange **DEMO MODE** banner, a fixed sample verdict, no chat box, and no AI cost. Close that terminal afterwards so demo mode doesn't stay on |

☐ F1 ☐ F2

---

## Automated checks (optional)

```powershell
.venv\Scripts\python -m pytest -q                 # 40 code tests, free
.venv\Scripts\python -m scripts.run_eval --chat   # all 6 sample cases + chat via the real AI, about ₹15
```
