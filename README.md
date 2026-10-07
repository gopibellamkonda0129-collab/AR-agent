# AR Agent

**AI-powered receivables assistant for small and mid-sized B2B businesses.**

AR Agent helps finance and AR teams understand *why* overdue invoices are stuck —
missing POs, approval delays, disputes, missed payment promises, or no response —
and recommends the right owner and next action for each one.

Status: working MVP. See [`v1/QA_REPORT.md`](v1/QA_REPORT.md) for the latest
pilot-readiness QA pass (demo workspace, live HTTP, and static frontend build all green).

---

## What it does

- **Ingests messy ledgers** — CSV, Excel, PDF (single or multi-invoice packs), Word, and text files are normalized into one AR ledger schema.
- **Diagnoses stuck invoices** — classifies each open invoice's process status (`po_pending`, `approval_pending`, `disputed`, `payment_promised`, `payment_overdue`, …) from real evidence, never guesses.
- **Reads the inbox** — connects Gmail/Outlook (OAuth) or IMAP, matches emails to customers and invoices, and extracts payment promises, disputes, wrong-PO replies, approval blockers, questions, and bounces. Vague phrases like "we'll try next week" never fabricate a promise date.
- **Builds a prioritized action queue** — every item carries an action type (`ESCALATE`, `FOLLOW_UP_MISSED_PROMISE`, `INVESTIGATE_DISPUTE`, `REQUEST_CORRECTED_PO`, `REQUEST_APPROVAL_STATUS`, …), category, risk/priority score, ownership, and source-email evidence.
- **Drafts follow-ups** — generates reminder/dispute/PO/missed-promise email drafts containing only verified facts. **Human-gated sending**: nothing is ever sent without explicit approval (`AR_ALLOW_SEND=1` + SMTP creds).
- **Forecasts cash** — per-invoice coverage of expected cash from confirmed future promises plus ledger buckets, promise tracking (upcoming / due today / missed), and money-recovered totals that stay consistent across the API.

## Repository layout

```
ar_agent/          V0 — Flask prototype: file-upload triage + draft emails
v1/
  backend/         FastAPI API (routers, services, demo seed, Supabase)
  frontend/
    dashboard/     Next.js dashboard (static export)
  QA_REPORT.md     Pilot-readiness QA report
```

## Quickstart (demo mode — no credentials needed)

Demo mode bundles a synthetic workspace (12 customers, 27 invoices, scenario
emails) and runs the full import → analyze → match → queue pipeline.

### 1. Backend

```bash
cd v1/backend
python -m venv .venv
.venv\Scripts\activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
set AR_DEMO=1                 # macOS/Linux: export AR_DEMO=1
python -m uvicorn app:app --reload --port 8000
```

API + static dashboard: http://localhost:8000

### 2. Dashboard (dev server, optional)

```bash
cd v1/frontend/dashboard
npm install
npm run dev                   # http://localhost:3000 (API on :8000)
```

### 3. V0 prototype (optional)

```bash
cd ar_agent
pip install -r requirements.txt
python app.py                 # file-upload triage prototype
```

## Configuration

Set in the environment or `v1/backend/.env`:

| Variable | Default | Purpose |
|---|---|---|
| `AR_DEMO` | `1` | `1` = bundled synthetic data, no external services |
| `SUPABASE_URL` / `SUPABASE_KEY` | — | persistence in live mode |
| `OPENAI_API_KEY` | — | optional LLM-powered email analysis |
| `GMAIL_CLIENT_SECRET` / `OUTLOOK_CLIENT_SECRET` | — | OAuth inbox connect |
| `AR_SYNC_INTERVAL` | `300` | background inbox poll (seconds; `0` disables) |
| `AR_ALLOW_SEND` | `0` | `1` + SMTP vars enables approved sends |
| `AR_SMTP_HOST/PORT/USER/PASSWORD` | — | outgoing mail |
| `AR_SENDER_NAME` / `AR_SENDER_EMAIL` | — | draft signature |

## Tests

```bash
# backend end-to-end contract test (demo mode, no network)
cd v1/backend && python test_backend.py

# V0 loader/pipeline checks
cd ar_agent
python test_formats.py
python test_pipeline.py
python test_pack.py
```

## Before a pilot (deployment gates)

The QA report recommends fixing these at deploy time, not in the app:

- **Authentication** — the API is single-tenant with no auth; put the dashboard behind a reverse proxy (Basic Auth / SSO).
- **CORS** — currently `allow_origins=["*"]`; lock to the dashboard origin.
- **Secrets** — use real env/secret management; never expose in-memory demo mode publicly.

## License

Private / unlicensed (pre-pilot).
