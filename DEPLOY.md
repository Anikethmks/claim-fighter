# Deploying ClaimFighter (Render)

**Cost:** Render Starter about $7/month + 1 GB disk about $0.25/month, plus AI usage (capped by `CF_DAILY_BUDGET_USD`, default $2/day).
The free plan can't keep a disk, so all users and cases would vanish on every restart. Don't use it for real users.

## 1. Email for sign-in codes (free)
Pick one:
- **Brevo** (300 emails/day free): sign up → SMTP & API → create an SMTP key.
  Host `smtp-relay.brevo.com`, port `587`; the user and password are shown there. Verify your sender email.
- **Gmail:** turn on 2-step verification → create an *App password*.
  Host `smtp.gmail.com`, port `587`; user = your Gmail address, password = the app password.

## 2. Put the code on GitHub
See "GitHub" below.

## 3. Create the service
1. Go to https://render.com and sign in with GitHub.
2. **New + → Blueprint** → choose the `claim-fighter` repo. Render reads `render.yaml`.
3. Fill in the secrets it asks for:

| Variable | Value |
|---|---|
| `OPENAI_API_KEY` | your key |
| `CF_ADMIN_EMAILS` | your email (unlocks the Dashboard) |
| `CF_PUBLIC_URL` | the site address Render gives you (used in reminder emails); add it after the first deploy |
| `CF_SMTP_HOST`, `CF_SMTP_USER`, `CF_SMTP_PASSWORD` | from step 1 |
| `CF_EMAIL_FROM` | the verified sender, e.g. `ClaimFighter <you@gmail.com>` |

4. Click **Apply**. The first build takes about 5 minutes. Your site will be at `https://claimfighter-xxxx.onrender.com`.

## 4. Check it
1. Open the site → sign in with your email → the code should arrive within a minute.
2. Upload `samples/case-1-room-rent` → expect a Strong/Moderate verdict.
3. Open **Dashboard** (top right) → you should see 1 user, 1 case and its cost.

## Settings you may change later (Render → Environment)
| Variable | Default | Meaning |
|---|---|---|
| `CF_DAILY_BUDGET_USD` | 2 | New AI work stops for the day after this spend |
| `CF_MAX_CASES_PER_USER_DAY` | 5 | Per-user abuse limit |
| `CF_MODEL` | gpt-5.4-mini | Model for analysis, chat and letters |
| `CF_RETENTION_DAYS` | 30 | Days uploaded documents are kept |

## GitHub
The local repo is already committed. To publish it:
1. Create an empty repo on GitHub named `claim-fighter`. Don't add a README.
2. Run:
   ```powershell
   cd D:\Workspace\Personal\claim-fighter
   git remote add origin https://github.com/<your-username>/claim-fighter.git
   git push -u origin main
   ```
`backend/.env` (your API key) is in `.gitignore` and is never committed.
