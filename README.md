# ClaimFighter

Helps people in India contest rejected or partially paid **health insurance claims**.
Upload the insurer's letter, the policy and the hospital bill, and ClaimFighter:

1. **Reads the documents** (PDFs or phone photos) and extracts the facts.
2. **Checks each rejection reason** against IRDAI rules, Ombudsman process rules and past Ombudsman awards in its knowledge base.
3. **Gives an honest verdict** per issue (strong / moderate / weak), including when the insurer is right.
4. **Computes deadlines** (insurer grievance → Ombudsman → consumer commission) in code, not by the AI.
5. **Drafts the complaint** for the right stage, citing only knowledge-base sources.
6. **Collects outcomes** (won / partial / lost) so the product learns which arguments work.

## Accounts, privacy and limits

- **Sign-in:** an email one-time code. Each user sees only their own cases. In dev, codes are printed in the server log.
- **Consent:** required before any document is processed; see the in-app Privacy page.
- **Admin dashboard** (`/#/admin`, for emails in `CF_ADMIN_EMAILS`): users, cases, letters, outcomes, money recovered, AI cost.
- **Cost guards:** a daily AI budget (`CF_DAILY_BUDGET_USD`) and a per-user daily case limit.
- **Deploying:** see [DEPLOY.md](DEPLOY.md) (Render, Docker).

## Escalation and data

- **Ombudsman record:** official per-insurer health statistics from the Council for Insurance Ombudsmen annual report (statements H3/H5), e.g. "65% of 11,480 complaints resolved for policyholders". Shown as a record, never a prediction; matched strictly by insurer name. Refresh: `python -m scripts.ingest_ombudsman_stats --url <report pdf> --year <yyyy-yy>`.
- **Escalation tracker:** paste the insurer's reply → records the date (starts the Ombudsman clock) and drafts an Ombudsman complaint answering each point.
- **Deadline reminders:** an hourly job emails each reminder once: complaint not sent yet, Ombudsman now open, Ombudsman deadline (30/7/1 days), consumer-court deadline, award not complied with. Reminders stop when the outcome is reported.
- **Scanned PDFs:** read via page images (OpenAI natively; Ollama renders pages with pypdfium2).

## Agents

- **Case Workflow (LangGraph)** ([workflow.py](backend/app/workflow.py)):
  - extract → check for gaps → analyse → **self-check** → finalize;
  - **pauses to ask the user** when facts are missing, and resumes with the answers;
  - retries the analysis once if the self-check finds material errors;
  - state is checkpointed per case, so a case survives restarts.
- **Case Assistant (OpenAI Agents SDK)** ([assistant.py](backend/app/assistant.py)):
  - chat on the case page; the agent chooses tools: case summary, rule search, deadlines, record a new fact (which triggers a workflow re-analysis), draft a letter;
  - guardrails in code: citation guard, question cap, tracing off.

See [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) for the full design.

## Why not just use ChatGPT?

| | General chatbot | ClaimFighter |
|---|---|---|
| Citations | Can invent circular numbers and cases | Only cites knowledge-base entries; anything else is stripped by code ([citations.py](backend/app/citations.py)) |
| Past Ombudsman awards | Not searchable | Ingested from official PDFs ([ingest_awards.py](backend/scripts/ingest_awards.py)) |
| Deadlines | Often wrong | Deterministic ([deadlines.py](backend/app/deadlines.py)), tested |
| Follow-through | One answer | Timeline, multi-stage drafts, outcome tracking |

## Architecture

```
frontend/ (React + Vite)  ──/api──▶  backend/ (FastAPI)
                                       ├─ pipeline.py   extract → retrieve → analyse → draft
                                       ├─ llm.py        provider-neutral interface: PDFs/images in, validated JSON out
                                       ├─ providers/    OpenAI (Responses API) and Anthropic (Claude) implementations
                                       ├─ knowledge/    SQLite FTS5 knowledge base + seed rules
                                       ├─ citations.py  citation guard
                                       ├─ deadlines.py  escalation timeline
                                       └─ db.py         SQLite: cases, documents, drafts, milestones
```

- **Works with OpenAI, Claude, or free local models (Ollama).** The provider is picked from whichever key is in `.env` (or forced with `CF_PROVIDER`). Each step has its own model and effort (`CF_MODEL`, `CF_EXTRACT_MODEL`, `CF_EFFORT_*`).
- **Every AI call is metered** (tokens, seconds, cost) and saved per case. `GET /api/usage` shows spend by day and model.
- All three AI steps send the same system prompt and documents first, so both providers can **cache the documents** across a case's calls.
- With Claude, refusals fall back server-side (`fallbacks: "default"`); with either provider, refusals and truncated answers become clear user-facing errors.
- Uploaded files are checked by content (magic bytes), not by extension, and **auto-deleted after 30 days** (`CF_RETENTION_DAYS`).

## Run it

Requirements: Python 3.12+, Node 20+.

```powershell
# Backend
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env          # then put your OPENAI_API_KEY (or ANTHROPIC_API_KEY) in .env
.venv\Scripts\python -m scripts.check_llm          # verifies key + model with one tiny request
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

# Frontend (second terminal)
cd frontend
npm install
npm run dev                      # http://localhost:5173
```

**No API key yet?** Start the backend with demo mode to click through the full app with a fixed sample case:

```powershell
$env:CF_DEMO = "1"; .venv\Scripts\python -m uvicorn app.main:app --port 8000
```

**Single deployable:** `npm run build` in `frontend/`, then the backend serves the built app at `http://localhost:8000`.

### Checking the AI on known cases

[samples/](samples/) holds 5 fictional cases with known correct answers: 3 the policyholder should win and 2 where the insurer is right (to test honesty). The answers are in [samples/ANSWERS.md](samples/ANSWERS.md).

```powershell
cd backend
.venv\Scripts\python -m scripts.make_samples        # regenerate the sample documents
.venv\Scripts\python -m scripts.run_eval --draft    # run all 5 through the real AI and check them
```

Run this after every prompt or model change. Full outputs, including per-call token counts and cost, are saved in `samples/results/`.

**Cost results on the 5 sample cases (2026-11-04, without drafting):**

| Settings | Passed | Cost per case | Time per case |
|---|---|---|---|
| gpt-5.5 everywhere, high effort (original) | 5/5 | ~$0.23 (~₹20) | ~80 s |
| gpt-5.4-mini extraction + gpt-5.5 analysis, medium | 5/5 | $0.06–0.10 | 20–45 s |
| **gpt-5.4-mini everywhere (current default)** | 5/5 | **$0.013–0.03 (₹1–2.6)** | 15–32 s |

The sample cases are clean and fairly easy. Before launch, re-test on real documents with `CF_MODEL=gpt-5.5` and keep the bigger model for analysis only if mini fails.

### Free local mode (Ollama)

```powershell
ollama pull qwen3-vl:8b     # reads text and images; about 6 GB
$env:CF_PROVIDER = "ollama"; .venv\Scripts\python -m uvicorn app.main:app --port 8000
```

Zero cost and documents never leave the machine, but it is slow on a laptop CPU and less accurate. Digital PDFs are sent as text; scanned PDFs must be uploaded as photos. Use it for developing features; use an API model for real analysis.

### Tests

```powershell
cd backend
.venv\Scripts\python -m pytest -q
```

The tests cover the deadline engine, the citation guard, knowledge search, and the full API flow with the AI mocked, so they run offline at no cost.

## Knowledge base

- **Seed** ([seed_regulations.json](backend/app/knowledge/seed_regulations.json)): 18 plain-language summaries of IRDAI rules, Ombudsman Rules 2017 and the Consumer Protection Act. **All are marked unverified** and shown with a "Check source" badge. Before launch, someone must check each one against the official text, then set `"verified": true`.
- **Ombudsman awards**: download award PDFs from the [Council for Insurance Ombudsmen](https://www.cioins.co.in), then:

  ```powershell
  cd backend
  .venv\Scripts\python -m scripts.ingest_awards path\to\pdfs
  ```

  Non-health awards are skipped. Re-running is safe (ids come from the file hash).

## Before a public launch

These are deliberately not done yet:

- [ ] **Verify every seed entry** against official IRDAI / CIO / statute text.
- [ ] **Ingest a real award corpus** (hundreds of health awards) and spot-check extraction quality.
- [ ] **Run the real pipeline on 10–20 real, consented cases** and review every output by hand; build an eval set from them.
- [ ] **Accounts / auth.** Today a case is protected only by its unguessable URL. Add phone OTP login before real users.
- [ ] **Data protection:** DPDP Act review, encryption at rest, privacy policy, and a medical-data consent screen.
- [ ] **Legal review** of the "information, not legal advice" positioning.
- [ ] Move background jobs to a queue (e.g. RQ/Celery) and SQLite to Postgres when traffic warrants it.
- [ ] Hindi and regional-language output, and a WhatsApp entry point.
