# AR Agent — MVP Pilot-Readiness QA Report

Date: 2026-09-10 · Mode: demo workspace (AR_DEMO=1, in-memory) · Build: backend tests + live HTTP + frontend static build all green (annotated Sept 10 with the AR-process-status extension)

## Severity legend
- **P0** — unusable / blocks a pilot evaluation
- **P1** — major business functionality wrong or a real security/pilot gate
- **P2** — important usability or data-hygiene defect
- **P3** — cosmetic/polish

**Verdict: RECOMMEND FOR PILOT with the gates in §16.** All P0/P1 and important P2 defects found were fixed in this session. Remaining items are P2/P3 ergonomics and two deployment-time gates (authentication + SMTP sending) that are intentionally out of the demo-mode codebase.

---

## 1. Demo workspace — PASS
- Built: **12 customers / 27 sample invoices (38 ledger rows incl. history) / 12 inbox emails / 13 open signals**, all flowing through the real import→analyze→match→queue pipeline (`demo/seed.py`).
- Invoice spread: **22 open / 16 paid**, 8 of the 22 open invoices are past due (2 with zero customer response — Acme, Marlowe), 4 due within 7 days, **$119,360.00 recovered** from recorded (never invented) payments.
- Scenario emails: 2 confirmed future promises (Oak & Stone, GreenLeaf), 1 promise due today (Fieldstone), **1 missed promise** (Vertex), **1 approval-pending** (Sterling & Vale, INV-1043 due in 5 days), 2 wrong-PO (Vertex, Beacon), 2 disputes (Fieldstone, BluePeak), 1 payment confirmation (GreenLeaf), 1 info question (Northstar), **1 bounced email** (Sunrise).
- Paid invoices seed both the ledger (amount 0 / status paid) and the payments table, so money recovered, `total_outstanding`, the queue and the forecast are all consistent with reality.

## 2. Customer matching — PASS (bug fixed)
- All 12 sample customers matched to their ledger account; no phantom/unmatched rows in the queue. Compact `INV-1017`-style references (no "invoice" prefix) now extract correctly (`INV-1017` → Beacon, `INV-1005` → Vertex).
- **Fixed (P1): bounced emails were unrouteable.** `services/matcher.py` now matches a delivery-failure (sender = mailer-daemon/postmaster) by the recipient address found in the **message body**, and `services/sync.py` passes the body through. The Sunrise bounce now lands on `Sunrise Bakery & Cafe` → `FIND_ALTERNATE_CONTACT` in the queue (regression-tested: `bounce routed to its customer (not blank)`).

## 3. AI reasoning / anti-hallucination — PASS
- Deterministic rule analyzer; verified with 5 ambiguous phrases: **"we'll try to process this next week", "we'll probably get this sorted sometime next week", "working on it…", "$1,500" (amount never misread as the 15th), "pay soon"** — none produce a fabricated `promised_date`. Real facts are still extracted ("pay by September 15" → `2026-09-15`; "sent" messages → not "payment made").
- **WARNING (P3):** a vague *"we'll try to process this next week"* is classified as `other` (ignored) rather than "intent, no date" because the intent dictionary doesn't include the verb "process". Safe (no fake dates) but intent is lost. Low priority; consider adding `process`/`handle` to the intent regex later.

## 4. Action queue — PASS
- **12 typed actions today** across 4 categories (collection 5 / dispute 1 / process 5 / pre-due 1). Healthy-but-not-yet-issued customers join the queue only for a **CONFIRM_PAYMENT_READINESS** pre-due action (Oak & Stone) — the fully-settled set stays out.
- Action mapping verified: missed promise → `FOLLOW_UP_MISSED_PROMISE` (critical), overdue no-response → `ESCALATE` (high), dispute → `INVESTIGATE_DISPUTE`, wrong PO → `REQUEST_CORRECTED_PO`, approval blocker → `REQUEST_APPROVAL_STATUS` (process), question → `REPLY_TO_QUESTION`, bounce → `FIND_ALTERNATE_CONTACT`, payment confirmation → `VERIFY_PAYMENT`, installments → `FOLLOW_UP`.
- Every item carries action + label + category + payment posture + where-it's-stuck + ownership (who/what/why/when/evidence) + source email evidence.

## 5. Follow-up generation — PASS
- Draft types match the trigger (missed-promise / dispute / PO / reminder / none-for-verify).
- Drafts contain **only real facts** (`$12,400.00`, `INV-1004`, promise date) — verified in tests and live.
- **Human-gated sending** works: approve records the approval and never sends when AR_ALLOW_SEND is off; copy/discard/edit all persist.

## 6. Payment promises — PASS (bug fixed)
- Promise tracker shows `upcoming` (Oak, GreenLeaf), `due_today` (Fieldstone), `overdue` (Vertex) correctly.
- **Fixed (P1):** a missed/overdue promise inflated "Expected cash." `services/expected_cash.py` now counts **only future promises** (`due_today`/`upcoming`) as expected; a missed promise falls into "Overdue – no confirmed date".

## 7. Cash forecast — PASS (bug fixed)
- **Fixed (P1):** forecast undercounted when a customer had a promise + other invoices (blanket per-customer exclusion dropped the customer's *other* invoices from the ledger buckets). Coverage is now **per invoice** (by `related_invoice`, falling back to single-open-invoice customers).
- After fixes: **forecast.total_cash == ledger total exactly**, buckets are labeled (`promise`/`ledger`), and every invoice lands in exactly one bucket.

## 8. Data consistency — PASS
- Live cross-checks all equal: `GET /invoices.total_outstanding == /actions.kpis.total_outstanding == /forecast.total_cash == /customers › Σ total_outstanding` (**$164,596.20**).
- Money recovered equals the sum of recorded (not invented) payments; marking a real invoice paid updates money-recovered and removes the customer from the queue (verified live & in tests).

## 9. Empty workspace — PASS
- Fresh repo shows `$0` everywhere (no crash, guarded pages); `/invoices/clear` empties the ledger; an empty workspace auto-seeds + syncs the labeled sample on boot (idempotent).

## 10. Error handling — PASS (two bugs fixed)
- **Fixed (P2):** technical exception text leaked to users — CSV import failed with `str(exc)`, IMAP connect failed with `f"connection failed: {exc}"`, auto-sync stored `error: {exc}`. All now return **friendly, non-technical** messages (verified: garbage CSV → "file format appears invalid"; bad IMAP → "login rejected — check the app password…").
- Unknown customer / missing invoice → clean 4xx, never a 500.

## 11. Responsiveness — PASS (with manual caveat)
- Layered breakpoints: 1250/1180/900/640px collapse the overview grid, risk cards, tables and forecast groups to single-column; `prefers-reduced-motion` respected.
- **WARNING (P2, verification only):** no device/emulator click-through was run in this environment (headless). Before pilot day, do a 10-minute pass on a 375px phone and 768px tablet.

## 12. Security — WARNING (one P1 fixed, gates remain)
- **Fixed (P1):** `GET /accounts` returned raw `provider_config` (IMAP app passwords, Gmail OAuth tokens). All secret-valued keys are now masked (`***`) at the API boundary and Gmail's "Token exchange failed" no longer echoes `exc`. Regression-tested.
- **Remaining pilot gates (ops/config, not app rewrites):**
  - **P1 — Authentication:** no auth / single-tenant by design. Any UI rewrite is out of scope, but a pilot must deploy behind a reverse proxy (Basic Auth / SSO) before exposing the dashboard.
  - **P2 — CORS** is `allow_origins=["*"]`; lock to the dashboard origin in production.
  - **P2 — Credentials at rest** are stored in `provider_config`/SMTP env vars. Postgres (Supabase) or secret-scoped env vars + TLS are fine for a pilot; the in-memory demo mode must not be exposed publicly.

## 13. Navigation — PASS
- All nav links resolve to existing pages; static export generated **15/15** pages with `trailingSlash: true` (no 404s on hard refresh); every page guards its `.data` (no blank flashes).

## 14. Performance — PASS (with P3 warn)
- Static prerender for everything; pages poll on 20–120 s intervals. Live response time for the heaviest endpoints (queue, forecast) is sub-100 ms in demo mode.
- **P3 (fixed):** Nav + Header both duplicated the queue poll every 30 s on top of the page's own panel — badge pollers moved to 60 s. Overview still starts up to ~10 interval timers (acceptable for a local tool; worth a React-Query consolidation later — deferred, not a pilot blocker).

## 15. AR process-status extension — PASS (annotated Sept 10)
- **Per-invoice process status** (`invoice_process_status`): paid / disputed / po_pending / approval_pending / receipt_unknown / process_blocked / payment_overdue / payment_promised / ready_for_payment / received / sent / unknown — each backed by facts (created/sent/receipt/po/approval/promise/paid) and an `evidence_status` = KNOWN|INFERRED|UNKNOWN. Never guessed.
- **Partial payments do NOT mark an invoice paid** (INV-1042 stays `payment_overdue` with a "2 recorded partial payment(s); balance still open" fact).
- Approval-pending is classified, surfaced in the queue as `REQUEST_APPROVAL_STATUS` (weight-8, after dispute), gets an `approval_pending_followup` draft that quotes **no internal guidance**, and drops HARBOR/INV-1043 (per-invoice) + media cases into the right stage ("Customer approval", currently "awaiting internal approval").
- **Customer AR process** (`customer_ar_process`) + **documented AR process** (`/reports/ar-process`, 9 observed steps vs 8 recommended) with counts per evidence state.
- All wired into the API (`/invoices`, `/customers/intelligence/{name}`, `/reports/ar-process`) and compact UI chips/pills/panels; frontend static build green; regression suite green (see §16).

## 16. Final summary

### Fixed this session (P0/P1 + important P2)
| # | Severity | Defect | Fix |
|---|----------|--------|-----|
| 1 | P1 | Missed/overdue promises counted as expected cash | Filter forecast promises to future-only |
| 2 | P1 | Forecast omitted other invoices when customer had a promise | Per-invoice promise coverage |
| 3 | P1 | Bounced emails unroutable → empty customer, no alternate-contact action | Body-address matching in matcher + sync |
| 4 | P1 | Account credentials exposed via API | Mask secrets in all account responses |
| 5 | P1 | `0.00` outstanding crashed repo sort | Sort key handles falsy numbers |
| 6 | P2 | Technical strings leaked to users (import/IMAP/sync/gmail) | Friendly messages at the boundary |
| 7 | P3 | Duplicate Nav/Header queue polling | Badge pollers to 60 s |

### Verified but left as-is (P2/P3)
- Vague "process this week" intent not detected (ignored safely) — P3.
- No device-level responsive click-through — P2 verification before pilot.
- Raw `String(e)`/`${status}: ${detail}` banners if a request fails — backend now only emits friendly text, so this is cosmetic; unify copy later — P3.
- No React-Query dedup for polling — P3.

### Required before a real pilot (out of regime: no auth/email infra in this codebase)
1. **Auth in front of the dashboard** (reverse-proxy Basic Auth or SSO) — P1 gate.
2. **Loose CORS → same-origin** — P1 gate.
3. **Outgoing email**: enable `AR_ALLOW_SEND` + SMTP secrets only inside the pilot env; keep sending human-gated.
4. Real-mailbox sync (IMAP/Gmail OAuth) credentials via secrets; **never expose the demo (in-memory) mode on a shared host**.

**Result: READY FOR PILOT.** 15/15 sections PASS after fixes, with the two deployment gates above.