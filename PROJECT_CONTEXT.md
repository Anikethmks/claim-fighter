# ClaimFighter: project context

Paste or attach this file to give an AI assistant (or a new collaborator) full context on the project.
Last updated: 2026-11-04.

## 1. What we're building

ClaimFighter is a web app that helps people in India **contest rejected or partially paid health insurance claims**.

The user uploads three documents (PDFs or phone photos):
1. the insurer's rejection or settlement letter (required);
2. the policy document (wording and schedule);
3. the hospital bill or discharge summary.

In about 15–30 seconds they get:
- a plain-language **verdict**: strong, moderate or weak case, plus the amount likely recoverable;
- a **point-by-point analysis** of each rejection reason or deduction: what the insurer said, what the policy wording and rules actually say, how strong the user's position is, what evidence to gather, and clickable sources;
- an **escalation timeline with deadlines**: insurer grievance → Insurance Ombudsman → consumer commission;
- a **drafted complaint letter** for the chosen stage (insurer grievance, IRDAI Bima Bharosa portal, Ombudsman, or consumer commission), with numbered references;
- an **outcome form** (won, partial, lost) so the product can learn which arguments work.

## 2. Why this problem

- Health claim rejections and cuts are a large, publicly visible pain in India; people post about them daily on X, LinkedIn and Reddit. Media reports put rejected or disallowed health claims at around ₹26,000 crore in one recent year.
- Most people give up: policies are long and confusing, and few people know the IRDAI rules or the free Ombudsman route.
- **Why not just use ChatGPT?** A general chatbot can explain a letter, but it invents circular numbers and case citations, doesn't know the escalation process or deadlines, and doesn't follow up. ClaimFighter's edge:
  1. a curated knowledge base, and only citations from it;
  2. past Ombudsman decisions (ingestion pipeline built; data not loaded yet);
  3. deterministic deadlines;
  4. multi-stage follow-through;
  5. outcome data over time.

## 3. Core principles (do not break these)

1. **Never fabricate legal sources.** The model may cite only knowledge-base entries, by id. Code removes any other citation (the citation guard). Never add invented regulations, circular numbers or Ombudsman awards to the knowledge base.
2. **Be honest.** If the insurer is right, say so. The tool must not encourage hopeless complaints.
3. **Dates and arithmetic are computed in code, not by the LLM.** This covers deadlines and years of continuous coverage (which decides the 5-year moratorium rule).
4. **Information, not legal advice.** Never promise outcomes.
5. **Privacy.** Uploaded medical documents are auto-deleted after 30 days; the user can delete a case at any time.
6. **Cost-conscious.** The owner pays for API credits personally. Prefer cheap models when the evals show quality holds, and state what a paid test run will cost before running it.

## 4. Architecture

```
frontend/ (React + TypeScript + Vite)  ──/api──▶  backend/ (Python, FastAPI, SQLite)
```

### Agent 1: Case Workflow (LangGraph), `app/workflow.py`
A stateful graph, checkpointed per case in `data/workflow.db` (thread id = case id), so a case can wait for the user for days and resume after a restart:

```
START ─► route ─┬─► extract ─► gaps ─► analyse ─► self_check ─┬─► finalize ─► clarify ─► END
                │                │  ▲                │         │                 │
                │       (ask user, pause)   (problems found,   │      (optional questions:
                │                   │        retry once)───────┘       pause; answers ─► analyse)
                └─(re-run with new facts)─► analyse
```

| Node | What it does |
|---|---|
| **extract** | LLM, structured output: documents → `CaseFacts` |
| **gaps** | Code: if the basics are missing (no rejection reason, unknown decision), **pause** and ask the user (`status = needs_input`) before any paid analysis |
| **analyse** | Code computes facts (continuous coverage, moratorium, amount disputed); SQLite FTS5 retrieves rules; the LLM produces `Analysis`; the citation guard drops unknown ids |
| **self_check** | A second LLM pass verifies the analysis against the documents (amounts, dates, clauses, strength ratings). Material problems send it back to `analyse` **once**, with the problems as feedback |
| **finalize** | Marks the case analysed |
| **clarify** | **Pauses** with the analysis's optional questions. Answers → re-analyse (no re-extraction); skip → end. At most 2 rounds |

The API streams node updates (`durability="sync"`) and writes progress to the case after each step: `processing → extracted → checking → (rechecking) → analyzed`, or `needs_input`.

### Agent 2: Case Assistant (OpenAI Agents SDK), `app/assistant.py`
A chat agent on the case page. The model chooses tools:

| Tool | What it does |
|---|---|
| `get_case_summary` | Facts and the current analysis |
| `search_rules` | Knowledge-base search |
| `get_deadlines` | The deadline engine (exact dates) |
| `record_new_fact` | Hands a new fact to the **LangGraph workflow**, which re-analyses the case; the agent doesn't re-judge on its own |
| `draft_letter` | Drafts a letter and saves it to the case |

Rules enforced in code:
- the citation guard (only ids its tools returned);
- 20 questions per case;
- 1,000 characters per message;
- tracing disabled (case data isn't sent to a trace dashboard);
- off in demo mode and for non-OpenAI providers.

Chat history is stored per case and the last 10 messages are sent each turn.

### Other steps
- **Draft** (LLM, plain text, on demand): a letter with `[[kb:ID]]` markers → code turns them into numbered references and strips unknown ids.
- **Deadline engine** (code): computes the escalation timeline from milestone dates the user enters.
- **Where agents are deliberately not used:** dates, citation checking and cost limits are plain code.

### LLM layer (provider-neutral)
- `app/llm.py` defines the interface: `structured(docs, instruction, schema, step)` and `text(docs, instruction, step)`, where step is `extract`, `analyse` or `draft`.
- Providers live in `app/providers/`:
  - **OpenAI** (Responses API): the current default.
  - **Anthropic Claude.**
  - **Ollama** (local models; PDFs sent as extracted text, photos downscaled).
- The provider is auto-picked from whichever API key is in `backend/.env`, or forced with `CF_PROVIDER`.
- Per-step model and effort settings: `CF_MODEL`, `CF_EXTRACT_MODEL`, `CF_EFFORT_EXTRACT`, `CF_EFFORT_ANALYSE`, `CF_EFFORT_DRAFT`.
- All three steps send the system prompt and documents first, so providers can cache the documents across a case's calls.
- **Every AI call is metered** (`app/usage.py`, `llm_calls` table): tokens, seconds and cost in USD. `GET /api/usage` shows spend by day and model.

### Key files
| File | Purpose |
|---|---|
| `backend/app/main.py` | API routes, uploads (validated by file content), background processing, retention purge |
| `backend/app/workflow.py` | LangGraph case workflow (Agent 1) |
| `backend/app/assistant.py` | OpenAI Agents SDK Case Assistant (Agent 2) |
| `backend/app/pipeline.py` | Prompts and the extract, retrieve, analyse, self-check and draft steps; computed facts; critical-gap rules |
| `backend/app/schemas.py` | Pydantic models: `CaseFacts`, `Analysis`, `Issue`, request bodies |
| `backend/app/llm.py`, `providers/*.py` | LLM interface and provider implementations |
| `backend/app/citations.py` | Citation guard |
| `backend/app/deadlines.py` | Escalation timeline |
| `backend/app/knowledge/store.py` | Knowledge base (SQLite FTS5) |
| `backend/app/knowledge/seed_regulations.json` | 18 seed entries (rules and process) |
| `backend/app/usage.py` | Token and cost accounting, price table |
| `backend/app/demo.py` | Demo mode (`CF_DEMO=1`): canned AI responses, no API calls |
| `backend/scripts/ingest_awards.py` | Loads Ombudsman award PDFs into the knowledge base |
| `backend/scripts/make_samples.py` | Generates the 5 fictional test cases |
| `backend/scripts/run_eval.py` | Runs test cases through the real AI and checks answers and cost |
| `backend/scripts/check_llm.py` | Verifies the API key and model with one tiny call |
| `frontend/src/components/*` | Home (upload), CasePage, Timeline, Drafts, Sources, Outcome |

### API endpoints
| Endpoint | Purpose |
|---|---|
| `POST /api/cases` | Multipart upload: `policy`, `bill`, `rejection`, `other`, `notes` |
| `GET /api/cases/{id}` | Full case view: facts, analysis, sources, timeline, drafts, AI usage |
| `POST /api/cases/{id}/reanalyze` | Run the analysis again (fresh workflow) |
| `POST /api/cases/{id}/answers` | Answer the questions the workflow paused on; `[]` skips optional ones |
| `POST /api/cases/{id}/chat` | Ask the Case Assistant |
| `POST /api/cases/{id}/drafts` | Draft a letter for a stage |
| `PUT /api/cases/{id}/milestones` | Record a milestone date; `DELETE …/milestones/{kind}` removes one |
| `POST /api/cases/{id}/outcome` | Record the result: won, partial or lost |
| `DELETE /api/cases/{id}` | Delete the case and its documents |
| `GET /api/health`, `GET /api/knowledge`, `GET /api/usage` | Status, knowledge base contents, spend |

## 5. Knowledge base

- **Seed:** 21 entries (process rules, IRDAI rules, consumer law). **All were checked against primary sources on 2026-11-05**: the Insurance Ombudsman Rules 2017 as amended to Nov 2023, the IRDAI Master Circulars on Health Insurance and on Protection of Policyholders' Interests (2024), the IRDAI Insurance Products Regulations 2024, the Consumer Protection Act 2019 and its 2021 jurisdiction rules, and the Mental Healthcare Act 2017. Key corrections made: the Ombudsman cap is ₹50 lakh (not ₹30 lakh); reimbursement settlement is 15 days (not 30); the 2020 IRDAI standardisation circulars (proportionate deduction, non-payable items, day care) were superseded in May 2024, so those entries point to the policy wording. Each entry cites the document and clause. Laws change: re-verify periodically, and get a lawyer's review before relying on it at scale.
- **Ombudsman awards:** none loaded yet. The ingestion script reads official award PDFs (from cioins.co.in), skips non-health awards, and stores the insurer, dispute category, outcome, amounts, reasoning and principles.

## 6. Testing and evaluation

- **Unit and API tests:** 40 pytest tests, all passing; run `pytest -q` from `backend/`. They cover:
  - deadlines, the citation guard and search;
  - the full API flow with the AI mocked;
  - the LangGraph pause/resume, required gaps and self-check retry cap;
  - the chat agent's guardrails, history and fact → re-analysis hand-off;
  - provider request shapes, usage accounting and Ollama handling.
- **Agent eval (2026-11-04, gpt-5.4-mini):** `run_eval --chat` passed all 5 verdicts and self-checks. The Case Assistant chose the expected tools (`get_deadlines` for a date question, `record_new_fact` for a new fact) and said honestly that a complaint is unlikely to succeed in the dengue case. Full run ₹11.43. A live run also exercised the self-check retry (analyse → self_check → analyse → self_check).
- **Eval set:** 5 fictional cases in `samples/`, each with policy, bill and letter PDFs (case 3's letter is a phone-photo image). Expected answers are in `samples/ANSWERS.md` and `samples/expected.json`.

| Case | Expected |
|---|---|
| 1. Room-rent ratio applied to stent, medicines and diagnostics | Strong/moderate; about ₹58,125 recoverable |
| 2. Non-disclosure claimed after 7.3 years of continuous cover (ported) | Strong (moratorium) |
| 3. Cataract rejected for "less than 24 hours" | Strong (listed day-care procedure) |
| 4. Dengue 17 days after the policy started | **Weak** (insurer is right; 30-day waiting period) |
| 5. Knee replacement in year 1 | **Weak** (insurer is right; 24-month waiting period) |
| 6. Letter with no specific reason | Workflow **pauses** to ask the reason before any paid analysis (passed live, ₹0.33) |

The manual test checklist for every workflow path is in `TEST_PLAN.md`.

**Results (2026-11-04, no drafting):**

| Settings | Passed | Cost per case | Time per case |
|---|---|---|---|
| gpt-5.5 everywhere, high effort | 5/5 | ~$0.23 (~₹20) | ~80 s |
| mini extraction + gpt-5.5 analysis, medium effort | 5/5 | $0.06–0.10 | 20–45 s |
| **gpt-5.4-mini everywhere (current default)** | 5/5 | **$0.013–0.03 (₹1–2.6)** | 15–32 s |
| Local qwen3-vl:8b via Ollama on a laptop CPU (16 GB RAM, no GPU) | Crashed (likely out of memory) | Free | n/a |

The caveat: the sample cases are clean and fairly easy. **No real-world documents have been tested yet.**

## 7. Current status

| Area | Status |
|---|---|
| End-to-end flow (upload → analysis → letter → deadlines → outcome) | Working prototype |
| Evals | Pass on fictional cases |
| Cost | ~₹1–3 per case, metered |
| Not done | Real-document testing, knowledge base verification, award corpus, login/auth (cases protected only by an unguessable URL), DPDP privacy compliance and consent screen, hosting, Hindi and regional languages, WhatsApp |
| Mobile layout | Not visually confirmed |

## 8. Roadmap

1. **Validate (1–2 weeks):** collect 5–10 real rejection letters (with consent, details masked) and add them as eval cases; verify the 18 seed rules against official text; ingest 50–100 real health Ombudsman awards.
2. **Launch readiness (~2 weeks):** phone OTP login, consent and privacy screen, privacy policy, deploy on a cheap server, Hindi output.
3. **Launch:** free analysis; post before-and-after demos on X and LinkedIn; reply to complaint threads; track outcomes.
4. **Grow:** WhatsApp bot, regional languages, paid escalation packs (₹299–999 for Ombudsman and consumer-court drafts), B2B versions (HR teams, hospital insurance desks, advisors).

## 9. Business view (honest)

- **Strengths:** a real, public, emotional, high-value pain; AI is genuinely useful here; strong social impact and portfolio value.
- **Weaknesses:** one-time use per person, low willingness to pay in distress, existing human services (e.g. Insurance Samadhan, commission-based), legal and privacy risk.
- **Rough potential:** a side business at ₹50k–2L per month if it spreads; bigger only with a B2B pivot. Revenue today: ₹0 (not launched).

## 10. How to run (Windows, PowerShell)

```powershell
cd D:\Workspace\Personal\claim-fighter\backend
.venv\Scripts\python -m uvicorn app.main:app --port 8000      # open http://localhost:8000
$env:CF_DEMO="1"; .venv\Scripts\python -m uvicorn app.main:app --port 8000   # free demo mode
.venv\Scripts\python -m pytest -q                             # code tests (free)
.venv\Scripts\python -m scripts.run_eval --case case-1-room-rent   # one live eval (~₹2)
```

After frontend changes: run `npm run build` in `frontend/`. The API key lives in `backend/.env` (never commit it).

## 11. Owner context

- The owner is building this as a side project and portfolio piece, and is applying to an AI Builder role at Razorpay.
- Built end to end with **Claude Code** as the coding agent; the owner directed the product decisions, testing and cost trade-offs.
- **Frameworks used:** LangGraph (case workflow), OpenAI Agents SDK (Case Assistant), and direct provider SDKs for single LLM calls. LangChain and the Claude Agent SDK are not used: LangChain added nothing the pipeline needed, and the Claude Agent SDK needs a Claude API key, which the owner doesn't have.
- The owner is cost-sensitive about API credits.
