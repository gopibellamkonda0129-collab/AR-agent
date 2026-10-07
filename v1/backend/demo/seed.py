"""Bundled sample workspace so the whole system runs with zero credentials.

This is fictional sample data meant to demonstrate the product - a first-time
user should see a realistic receivables workspace, not an empty one. The
invoices + emails flow through the SAME import/analyze/matcher pipeline real
data uses, so every signal, promise, and recommended action is produced by the
real code - nothing is faked in the UI.

The workspace intentionally covers the scenarios a pilot evaluator looks for:

    12 customers / 27 invoices
    - 7 overdue invoices (2 with no customer response)
    - 4 due within 7 days
    - 5 paid invoices (payments recorded in the payments table)
    - 2 disputed invoices
    - 2 confirmed payment promises (future) + 1 promise due today
    - 1 missed payment promise
    - 2 missing-PO (wrong PO reference) situations
    - 1 bounced email
    - 1 payment-plan customer paying in instalments (cash-flow evidence)
    - 1 invoice awaiting internal customer approval (approval-pending
      process blocker - not chased, checked)
    - remaining normal invoices

    Beyond the live pipeline, the seed also inserts recorded HISTORY (older
    payments - some paid late, past promises kept/missed, earlier responses,
    and prior follow-up drafts) so the collections intelligence panels have
    real facts to explain payment behaviour, chase stage and "why late?".

NOTE: repeated calls are idempotent (guarded by a non-empty ledger).
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from database import repo

# ---------------------------------------------------------------------------
# Fictional workspace (never real customer data)
# ---------------------------------------------------------------------------

# (customer, contact_email, invoice_number, amount, due_ago_days)
# negative due_ago_days = due date in the future.
_LEDGER: list[tuple[str, str, str, float, int]] = [
    # --- overdue (with scenarios) -----------------------------------------
    ("Acme Digital",            "ap@acme-digital.com",        "INV-1001", 18700.00, 42),   # no response
    ("Vertex Systems",          "ap@vertexsystems.com",       "INV-1004", 12400.00, 38),   # MISSED promise
    ("Marlowe & Co",            "accounts@marlowe-co.com",    "INV-1006", 5200.00,  25),   # no response
    ("Northstar Media",         "accounts@northstar-media.com", "INV-1008", 8400.00, 14),  # replied w/ question
    ("Sunrise Bakery & Cafe",   "owner@sunrisebakery.example", "INV-1010", 706.20,  10),   # bounced email
    ("Beacon Press Group",      "payables@beaconpress.example", "INV-1017", 6800.00, 20),  # wrong PO
    ("BluePeak Solutions",      "accounts@bluepeak.example",  "INV-1018", 9100.00,  18),   # dispute
    ("Harbor Court Hotels",     "ap@harborcourt.example",    "INV-1042", 11600.00, 33),   # payment plan (cash-flow evidence)
    # --- due within 7 days ------------------------------------------------
    ("Fieldstone Partners",     "accounts@fieldstone-partners.com", "INV-1012", 5600.00, -5),  # promise today
    ("Oak & Stone",             "billing@oak-stone.com",      "INV-1014", 7400.00,  -4),   # promise next Friday
    ("Beacon Press Group",      "payables@beaconpress.example", "INV-1016", 4320.00,  -6),  # approaching
    ("Sterling & Vale",         "ap@sterling-vale.com",       "INV-1043", 9400.00,  -5),   # awaiting approval
    # --- normal open invoices ---------------------------------------------
    ("Acme Digital",            "ap@acme-digital.com",        "INV-1002", 5800.00, -38),
    ("Acme Digital",            "ap@acme-digital.com",        "INV-1003", 12400.00, -60),
    ("Vertex Systems",          "ap@vertexsystems.com",       "INV-1005", 8750.00,  -2),   # wrong PO
    ("Marlowe & Co",            "accounts@marlowe-co.com",    "INV-1007", 3200.00, -18),
    ("Sunrise Bakery & Cafe",   "owner@sunrisebakery.example", "INV-1011", 2150.00, -20),
    ("Fieldstone Partners",     "accounts@fieldstone-partners.com", "INV-1013", 3200.00, -21),  # dispute
    ("Fieldstone Partners",     "accounts@fieldstone-partners.com", "INV-1023", 18900.00, -45),
    ("BluePeak Solutions",      "accounts@bluepeak.example",  "INV-1024", 11750.00, -14),
    ("GreenLeaf Landscaping",   "billing@greenleaf.example",  "INV-1020", 1620.00,  -9),   # promise next Friday
    ("GreenLeaf Landscaping",   "billing@greenleaf.example",  "INV-1022", 3200.00, -30),
    # --- paid ------------------------------------------------------------------
    ("Northstar Media",         "accounts@northstar-media.com", "INV-1009", 5800.00, -20),
    ("Oak & Stone",             "billing@oak-stone.com",      "INV-1015", 1500.00, -25),
    ("BluePeak Solutions",      "accounts@bluepeak.example",  "INV-1019", 4500.00, -22),
    ("GreenLeaf Landscaping",   "billing@greenleaf.example",  "INV-1021", 8400.00, -18),
    ("Northstar Media",         "accounts@northstar-media.com", "INV-1025", 750.00,  -12),
]

# invoice_number -> days since payment was recorded (money recovered history)
_PAID_AGO: dict[str, int] = {
    "INV-1009": 2,
    "INV-1015": 5,
    "INV-1019": 9,
    "INV-1021": 12,
    "INV-1025": 3,
}


def seed_demo() -> None:
    if repo.select("invoices", limit=1):
        _ensure_account()
        return  # already seeded

    today = dt.date.today()

    invoices = []
    for customer, email, number, amount, due_ago in _LEDGER:
        due = today - dt.timedelta(days=due_ago)
        invoices.append({
            "customer_name": customer,
            "contact_email": email,
            "invoice_number": number,
            "invoice_date": (due - dt.timedelta(days=15)).isoformat(),
            "due_date": due.isoformat(),
            "amount_outstanding": amount,
            # the engine recomputes risk; paid invoices are flagged below
            "status": "overdue" if due_ago >= 0 else "open",
            "source": "sample workspace",
        })
    repo.insert("invoices", invoices)

    # Paid invoices get a real recorded payment + zero outstanding, so every
    # downstream number (Money Recovered, ledger total, queue) matches reality.
    inv_by_number = {inv["invoice_number"]: inv for inv in invoices}
    payments = []
    for number, ago in _PAID_AGO.items():
        inv = inv_by_number.get(number)
        if not inv:
            continue
        paid_at = (today - dt.timedelta(days=ago)).isoformat()
        payments.append({
            "invoice_id": inv["id"],
            "invoice_number": number,
            "customer_name": inv["customer_name"],
            "amount": round(float(inv["amount_outstanding"]), 2),
            "paid_at": paid_at,
            "note": "Sample payment - recorded payment (fictional data)",
        })
        repo.update("invoices", inv["id"], {
            "amount_outstanding": 0.0,
            "status": "paid",
            "expected_payment_date": None,
        })
    if payments:
        repo.insert("payments", payments)

    # Payment-plan scenario (Harbor Court Hotels): two instalments already
    # received against an open invoice. This is EVIDENCE of chunked payment -
    # the behaviour + why-late panels use it as a cash-flow signal, and the
    # outstanding balance is reduced to what is genuinely still owed.
    for number, parts in [("INV-1042", [(3000.00, 21), (3000.00, 9)])]:
        inv = inv_by_number.get(number)
        if not inv:
            continue
        paid_total = 0.0
        for amt, ago in parts:
            repo.insert("payments", [{
                "invoice_id": inv["id"],
                "invoice_number": number,
                "customer_name": inv["customer_name"],
                "amount": round(amt, 2),
                "paid_at": (today - dt.timedelta(days=ago)).isoformat(),
                "note": "Partial payment - instalment plan (fictional demo data)",
            }])
            paid_total += amt
        repo.update("invoices", inv["id"], {
            "amount_outstanding": round(float(inv["amount_outstanding"]) - paid_total, 2),
        })

    _seed_history(today)

    repo.insert("email_accounts", [_account_row()])


# ---------------------------------------------------------------------------
# Richer history so the collections intelligence has facts to explain.
# All of it is recorded fiction (never real customer data): past payments
# (some paid late), past promises (kept / missed), earlier responses and
# prior follow-up drafts. Rows are inserted directly here because they are
# OLD history - they don't need to re-run through the live email pipeline.
# ---------------------------------------------------------------------------

def _seed_history(today: dt.date) -> None:
    # (customer, email, invoice_number, amount, issued_days_ago, due_days_ago, paid_days_ago)
    # delay_days = due_days_ago - paid_days_ago (positive = paid AFTER the due date)
    _PAID_HISTORY = [
        # Acme Digital            -> 2/2 late, avg 10d
        ("Acme Digital",        "ap@acme-digital.com",        "INV-1031", 4200.00, 200, 160, 155),
        ("Acme Digital",        "ap@acme-digital.com",        "INV-1032", 3110.00, 150, 105, 90),
        # Vertex Systems         -> 1/1 late, avg 22d
        ("Vertex Systems",      "ap@vertexsystems.com",       "INV-1033", 21800.00, 230, 170, 148),
        # Marlowe & Co           -> 2/2 late, avg 18d
        ("Marlowe & Co",        "accounts@marlowe-co.com",    "INV-1034", 7600.00, 95, 60, 58),
        ("Marlowe & Co",        "accounts@marlowe-co.com",    "INV-1035", 5400.00, 130, 95, 60),
        # Northstar Media        -> on time
        ("Northstar Media",     "accounts@northstar-media.com", "INV-1036", 12000.00, 175, 140, 141),
        # Beacon Press Group     -> 1/1 late, avg 35d
        ("Beacon Press Group",  "payables@beaconpress.example", "INV-1037", 9400.00, 110, 75, 40),
        # BluePeak Solutions     -> 1/1 late, avg 5d
        ("BluePeak Solutions",  "accounts@bluepeak.example",  "INV-1038", 6100.00, 80, 45, 40),
        # Oak & Stone            -> on time
        ("Oak & Stone",         "billing@oak-stone.com",      "INV-1039", 2600.00, 90, 55, 55),
        # Fieldstone Partners    -> 2/2 late, avg 6.5d
        ("Fieldstone Partners", "accounts@fieldstone-partners.com", "INV-1040", 18000.00, 235, 200, 189),
        ("Fieldstone Partners", "accounts@fieldstone-partners.com", "INV-1041", 2200.00, 65, 30, 32),
    ]

    hist_invoices = []
    for customer, email, number, amount, issued_ago, due_ago, paid_ago in _PAID_HISTORY:
        hist_invoices.append({
            "customer_name": customer,
            "contact_email": email,
            "invoice_number": number,
            "invoice_date": (today - dt.timedelta(days=issued_ago)).isoformat(),
            "due_date": (today - dt.timedelta(days=due_ago)).isoformat(),
            "amount_outstanding": 0.0,
            "status": "paid",
            "source": "sample workspace",
        })
    repo.insert("invoices", hist_invoices)

    hist_payments = []
    for customer, email, number, amount, issued_ago, due_ago, paid_ago in _PAID_HISTORY:
        hist_payments.append({
            "invoice_id": "",
            "invoice_number": number,
            "customer_name": customer,
            "amount": amount,
            "paid_at": (today - dt.timedelta(days=paid_ago)).isoformat(),
            "note": "Past payment history (fictional demo data)",
        })
    repo.insert("payments", hist_payments)

    # (customer, email, invoice_number, amount, promised_days_ago,
    #  created_days_ago, resolved, resolution_note)
    _PROMISE_HISTORY = [
        ("Acme Digital",        "ap@acme-digital.com",        "INV-1031", 4200.00, 158, 165, True, "KEPT: paid $4,200.00 by ACH"),
        ("Acme Digital",        "ap@acme-digital.com",        "INV-1032", 3110.00, 99, 106, True, "KEPT: paid $3,110.00"),
        ("Vertex Systems",      "ap@vertexsystems.com",       "INV-1033", 21800.00, 150, 160, True, "KEPT: paid $21,800.00 (late)"),
        ("Marlowe & Co",        "accounts@marlowe-co.com",    "INV-1034", 7600.00, 62, 66, True, "KEPT: paid $7,600.00 (2 days late)"),
        ("Marlowe & Co",        "accounts@marlowe-co.com",    "INV-1035", 5400.00, 88, 94, True, "MISSED: paid 35 days after the due date"),
        ("Northstar Media",     "accounts@northstar-media.com", "INV-1025", 750.00, 10, 14, True, "KEPT: paid $750.00"),
        ("Beacon Press Group",  "payables@beaconpress.example", "INV-1037", 9400.00, 40, 46, True, "MISSED: invoicing error held the invoice"),
        ("BluePeak Solutions",  "accounts@bluepeak.example",  "INV-1019", 4500.00, 20, 24, True, "KEPT: paid $4,500.00"),
        ("Oak & Stone",         "billing@oak-stone.com",      "INV-1015", 1500.00, 8, 12, True, "KEPT: paid $1,500.00"),
        ("Fieldstone Partners", "accounts@fieldstone-partners.com", "INV-1040", 18000.00, 195, 202, True, "KEPT: paid $18,000.00"),
        ("GreenLeaf Landscaping", "billing@greenleaf.example", "INV-1021", 8400.00, 15, 19, True, "KEPT: paid $8,400.00"),
        # open promise with NO confirmed date + their own cash-flow wording ->
        # drives the "cash-flow signal" why-late category and a collaborative action.
        ("Harbor Court Hotels", "ap@harborcourt.example", "INV-1042", 11600.00, None, 6, False,
         "OPEN: managing cash flow carefully, will keep paying INV-1042 in monthly installments"),
    ]
    promise_rows = []
    for customer, email, number, amount, promised_ago, created_ago, resolved, note in _PROMISE_HISTORY:
        promised_iso = (today - dt.timedelta(days=promised_ago)).isoformat() \
            if promised_ago is not None else None
        promise_rows.append({
            "customer_name": customer,
            "customer_email": email,
            "signal_type": "payment_promise",
            "priority": "high",
            "confidence": 0.85,
            "summary": f"Payment for {number} promised by {promised_ago} days after creation (demo history)"
            if promised_ago is not None
            else f"Customer will keep paying {number} in monthly installments (demo history)",
            "related_invoice": number,
            "promised_date": promised_iso,
            "promised_amount": amount,
            "resolved": resolved,
            "resolution_note": note,
            "from_email": email,
            "created_at": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=created_ago)).isoformat(),
        })
    if promise_rows:
        repo.insert("signals", promise_rows)

    # resolved earlier responses (enrich the timeline & "they do respond" signal)
    _RESPONSE_HISTORY = [
        ("Acme Digital",       "info_question",    55, "Asked for a duplicate of the statement - sent same day", True),
        ("Marlowe & Co",       "info_question",    30, "Asked which invoice was still outstanding - replied", True),
        ("BluePeak Solutions", "info_question",    25, "Asked for the invoice breakdown - provided", True),
    ]
    resp_rows = []
    for customer, sig_type, ago_days, summary, resolved in _RESPONSE_HISTORY:
        resp_rows.append({
            "customer_name": customer,
            "customer_email": "",
            "signal_type": sig_type,
            "priority": "medium",
            "confidence": 0.7,
            "summary": summary,
            "related_invoice": "",
            "promised_date": None,
            "promised_amount": None,
            "resolved": resolved,
            "resolution_note": "Resolved historically (demo data)",
            "from_email": "",
            "created_at": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=ago_days)).isoformat(),
        })
    if resp_rows:
        repo.insert("signals", resp_rows)

    # prior follow-up drafts (drive the Smart Chase "which reminder is this?" count)
    # (customer, draft_type, subject, days_ago)
    _FOLLOWUP_HISTORY = [
        ("Acme Digital",       "friendly_reminder", "Invoice INV-1001 - quick reminder", 20),
        ("Acme Digital",       "overdue_reminder",  "Invoice INV-1001 - 14 days past due", 7),
        ("Marlowe & Co",       "friendly_reminder", "Invoice INV-1006 - quick reminder", 18),
        ("Northstar Media",    "friendly_reminder", "Invoice INV-1008 - quick reminder", 4),
    ]
    fu_rows = []
    for customer, draft_type, subject, ago_days in _FOLLOWUP_HISTORY:
        fu_rows.append({
            "customer_name": customer,
            "draft_type": draft_type,
            "subject": subject,
            "body": "",
            "status": "approved",
            "created_at": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=ago_days)).isoformat(),
        })
    if fu_rows:
        repo.insert("followups", fu_rows)


def _account_row() -> dict:
    return {
        "provider": "demo",
        "email": "ar@yourcompany.com",
        "display_name": "AR Inbox (sample)",
        "provider_config": {"mode": "demo"},
        "status": "connected",
    }


def _ensure_account() -> None:
    if repo.select("email_accounts", limit=1):
        return
    repo.insert("email_accounts", [_account_row()])


# ---------------------------------------------------------------------------
# Sample inbox messages. Each is written to classify into a specific signal
# type via the deterministic analyzer, so the whole pipeline is exercised.
# ---------------------------------------------------------------------------

def _demo_messages(account_id: str, today: dt.date) -> list[dict]:
    friday = today + dt.timedelta(days=(4 - today.weekday()) % 7)
    next_friday = friday + dt.timedelta(days=7)
    # an ISO date in the past -> creates a MISSED promise (Vertex)
    missed_date = (today - dt.timedelta(days=6)).isoformat()
    # a promise due today for Fieldstone
    stem_date = today.isoformat()

    data = [
        # --- missed promise (past ISO date) -> follow up missed promise ---
        {
            "subject": "Payment for INV-1004 confirmed",
            "body": (
                f"Just to let you know, we will pay the balance of invoice "
                f"INV-1004 for $12,400.00 by {missed_date}. Our CFO has signed "
                f"off on it."
            ),
            "from_email": "ap@vertexsystems.com",
            "from_name": "Omar Haddad - Vertex Systems",
            "received_ago_h": 80,
        },
        # --- wrong PO -> request corrected PO (Vertex) ---------------------
        {
            "subject": "PO reference incorrect on INV-1005",
            "body": (
                "Invoice INV-1005 references PO-22901 which is incorrect, it "
                "should be PO-44810. Please update the PO number and resend."
            ),
            "from_email": "ap@vertexsystems.com",
            "from_name": "Dana Price - Vertex Systems",
            "received_ago_h": 30,
        },
        # --- wrong PO -> request corrected PO (Beacon Press) ---------------
        {
            "subject": "PO mismatch on INV-1017",
            "body": (
                "INV-1017 references PO-77610 which is incorrect, should be "
                "PO-88143. Please update the PO number and resend."
            ),
            "from_email": "payables@beaconpress.example",
            "from_name": "Hannah Liu - Beacon Press Group",
            "received_ago_h": 52,
        },
        # --- info question (overdue + customer responded) ------------------
        {
            "subject": "Re: INV-1008 status",
            "body": (
                "Can you confirm invoice INV-1008 was received on your side? "
                "What's the current status of this account on your records?"
            ),
            "from_email": "accounts@northstar-media.com",
            "from_name": "Nina Cole - Northstar Media",
            "received_ago_h": 6,
        },
        # --- promise due today (Fieldstone) --------------------------------
        {
            "subject": "Payment for INV-1012 going out today",
            "body": (
                f"We will pay invoice INV-1012 in full today ({stem_date}), "
                "you should see the transfer shortly."
            ),
            "from_email": "accounts@fieldstone-partners.com",
            "from_name": "Priya Sen - Fieldstone Partners",
            "received_ago_h": 8,
        },
        # --- dispute (Fieldstone) -------------------------------------------
        {
            "subject": "Dispute: INV-1013 billed incorrectly",
            "body": (
                "We are disputing invoice INV-1013. We were double charged - "
                "the amount of $3,200.00 does not match the agreed scope. "
                "Please issue a corrected invoice."
            ),
            "from_email": "accounts@fieldstone-partners.com",
            "from_name": "Marcus Webb - Fieldstone Partners",
            "received_ago_h": 40,
        },
        # --- confirmed future promise (Oak & Stone) -------------------------
        {
            "subject": "Payment for INV-1014 - will send next Friday",
            "body": (
                "Hi, our bookkeeper confirmed the balance for invoice INV-1014 "
                f"($7,400.00). We will pay by next Friday ({next_friday.isoformat()}) "
                "once the deposit clears. Thank you for your patience."
            ),
            "from_email": "billing@oak-stone.com",
            "from_name": "Elena Ruiz - Oak & Stone",
            "received_ago_h": 22,
        },
        # --- dispute (BluePeak) ---------------------------------------------
        {
            "subject": "Dispute: INV-1018 charge does not match",
            "body": (
                "We are disputing invoice INV-1018 for $9,100.00. The billed "
                "amount does not match the agreed scope - please review the "
                "line items and send us a corrected invoice. Happy to have a "
                "quick call to resolve this."
            ),
            "from_email": "accounts@bluepeak.example",
            "from_name": "Sam Whitfield - BluePeak Solutions",
            "received_ago_h": 36,
        },
        # --- approval pending -> check approval status (Sterling & Vale) ---
        {
            "subject": "Re: INV-1043 is with our finance team",
            "body": (
                "Hi, invoice INV-1043 for $9,400.00 is with our finance team "
                "for approval. We will pay the balance immediately once "
                "approval is granted. Please be patient with us while it's "
                "being reviewed."
            ),
            "from_email": "ap@sterling-vale.com",
            "from_name": "Rebecca Ortiz - Sterling & Vale",
            "received_ago_h": 20,
        },
        # --- bounced -> find alternate contact (Sunrise) --------------------
        {
            "subject": "Delivery Status Notification (Failure)",
            "body": (
                "This is the mail system at host smtp.yourcompany.com.\n\n"
                "<owner@sunrisebakery.example>: Host or domain name not found. "
                "Delivery failed."
            ),
            "from_email": "mailer-daemon@smtp.yourcompany.com",
            "from_name": "Mail Delivery Subsystem",
            "received_ago_h": 2,
        },
        # --- confirmed future promise (GreenLeaf) ---------------------------
        {
            "subject": "Payment for INV-1020 - will send next Friday",
            "body": (
                "Hi, our bookkeeper confirmed the balance for invoice INV-1020 "
                f"($1,620.00). We will pay by next Friday ({next_friday.isoformat()}) "
                "once the deposit clears. Thanks for your patience."
            ),
            "from_email": "billing@greenleaf.example",
            "from_name": "Marta Reyes - GreenLeaf Landscaping",
            "received_ago_h": 26,
        },
        # --- payment confirmation (GreenLeaf, paid invoice) ------------------
        {
            "subject": "Re: INV-1021 paid",
            "body": (
                "Just an update - we paid $8,400.00 today via wire for invoice "
                "INV-1021. You should see it in a couple of days. Thanks!"
            ),
            "from_email": "billing@greenleaf.example",
            "from_name": "Marta Reyes - GreenLeaf Landscaping",
            "received_ago_h": 8,
        },
    ]

    msgs = []
    for d in data:
        ts = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=d["received_ago_h"])
        sid = f"demo-{abs(hash(d['subject']) + abs(hash(d['from_email'])))}@demo"
        msgs.append({
            "account_id": account_id,
            "subject": d["subject"],
            "body": d["body"],
            "from_email": d["from_email"],
            "from_name": d["from_name"],
            "message_id": sid,
            "thread_id": sid,
            "received_at": ts.isoformat(),
        })
    return msgs


def demo_emails() -> tuple[list[dict], Any]:
    """Return the bundled sample emails plus the account row (for sync).

    Messages are generated fresh per call and flow through the normal sync
    pipeline; message_id dedupe keeps repeated syncs idempotent.
    """
    seed_demo()
    account = repo.select("email_accounts", limit=1)[0]
    today = dt.date.today()
    msgs = _demo_messages(account["id"], today)
    return msgs, account