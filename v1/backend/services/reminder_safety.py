"""Reminder Safety Engine.

Decides whether a customer can be sent a payment-demand-reminder at all, and
which action is appropriate instead. The product rule: NEVER send a generic
payment demand when the reason the invoice is unpaid is a process blocker
(approval pending, PO/reference issue, missing invoice, documentation request,
bounce, dispute). In those cases the engine recommends the process action that
unblocks the invoice. Every verdict is backed by the checks that produced it.
"""
from __future__ import annotations

import datetime as dt
from typing import Any


def _d(iso: str | None) -> dt.date | None:
    if not iso:
        return None
    try:
        return dt.date.fromisoformat(str(iso)[:10])
    except ValueError:
        return None


def _agree(verdict: str, label: str, checks: list[dict[str, Any]],
           recommended: str, note: str, product_rule: bool) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "verdict_label": label,
        "recommended_action": recommended,
        "note": note,
        "product_rule": product_rule,
        "checks": checks,
    }


def reminder_safety(repo: Any, item: dict[str, Any]) -> dict[str, Any]:
    """Run the safety checks for one action/queue item."""
    name = item.get("customer_name", "")
    types = set(item.get("open_signal_types") or [])
    status = item.get("status")  # work-queue status, not invoice status
    promise = item.get("promise") or {}
    promise_stat = promise.get("status")
    amount = float(item.get("overdue_amount") or 0)
    checks: list[dict[str, Any]] = []

    def flag(key, label, outcome: bool, evidence, note):
        checks.append({"key": key, "label": label,
                       "outcome": outcome, "evidence": evidence, "note": note})

    # 1. paid?
    qpaid = repo.select("actions_queue", where={"customer_name": name, "status": "contacted"})
    paid_rows = [p for p in repo.select("payments", where={"customer_name": name})
                 if float(p.get("amount") or 0) > 0]
    still_open = [
        i for i in repo.select("invoices", where={"customer_name": name})
        if float(i.get("amount_outstanding") or 0) > 0
        and str(i.get("status") or "").lower() != "paid"
    ]
    flag("paid", "Outstanding balance", bool(not still_open), "KNOWN",
         "all invoices settled" if not still_open else f"{len(still_open)} invoice(s) still open")
    if not still_open:
        return _agree("NO_ACTION", "Nothing to chase - balance is settled",
                      checks, "No reminder needed",
                      "Recording a payment removes the customer from the queue.",
                      product_rule=False)

    # 2. dispute
    disputed = "dispute" in types
    flag("dispute", "Dispute / chargeback", disputed, "KNOWN",
         "the charge is under dispute" if disputed else "no dispute on file")
    if disputed:
        return _agree("ESCALATE", "Resolve the dispute before any payment demand",
                      checks,
                      "Handle the dispute - clarify scope/charges with the customer",
                      "A generic demand during a dispute damages the relationship.",
                      product_rule=True)

    # 3. approval pending
    approval = "approval_pending" in types
    flag("approval", "Internal approval pending", approval, "KNOWN",
         "customer is awaiting internal approval" if approval else "no approval hold")
    if approval:
        return _agree("PAUSE", "Wait - customer approval is in progress",
                      checks,
                      "Let the customer finish their approval; follow up around the "
                      "expected approval date",
                      "The invoice is unpaid because of the customer's approval cycle, "
                      "not unwillingness. Sending a demand now achieves nothing.",
                      product_rule=True)

    # 4. PO / reference
    po_issue = "wrong_po" in types
    flag("po", "PO / reference matched", not po_issue, "KNOWN" if po_issue else "UNKNOWN",
         "PO mismatch flagged" if po_issue else "no PO confirmation on file")
    if po_issue:
        return _agree("REQUEST_INFORMATION", "Confirm the correct PO / reference",
                      checks,
                      "Ask the customer which PO/reference the invoice should carry, "
                      "then re-issue or re-send",
                      "AP holds invoices on PO mismatches - the demand is NOT the fix.",
                      product_rule=True)

    # 5. not received
    missing = "missing_invoice" in types
    flag("receipt", "Invoice received", not missing, "KNOWN" if missing else "UNKNOWN",
         "customer says the invoice never arrived" if missing else "receipt not proven")
    if missing:
        return _agree("RESEND", "Re-send the invoice (not a payment demand)",
                      checks,
                      "Re-send the invoice to the right AP contact and confirm delivery",
                      "The customer cannot pay an invoice they never saw.",
                      product_rule=True)

    # 6. documentation request
    docs = "documentation_request" in types
    flag("docs", "Supporting documents", not docs, "KNOWN",
         "customer is waiting on documents" if docs else "no document request")
    if docs:
        return _agree("REQUEST_INFORMATION", "Provide the requested documents",
                      checks,
                      "Send the documents/info the customer asked for and re-confirm",
                      "The invoice is parked on a documentation need - send the "
                      "documents, not a demand.",
                      product_rule=True)

    # 7. bounced email
    bounced = "bounced_email" in types
    flag("bounce", "Contact reachable", not bounced, "KNOWN",
         "the mailbox address bounced" if bounced else "contact not flagged")
    if bounced:
        return _agree("RESEND", "Fix the address and re-connect",
                      checks,
                      "Correct the contact email and re-send there",
                      "Demanding payment from an address that bounces is noise.",
                      product_rule=True)

    # 8. a live promise with a date
    promise_fresh = promise_stat in ("upcoming", "due_today")
    flag("promise", "Live payment promise", not promise_fresh,
         "KNOWN" if promise_fresh else "UNKNOWN",
         f"customer committed to pay by {promise.get('promised_date')}"
         if promise_fresh else "no open promise with a date")
    if promise_fresh:
        return _agree("PAUSE", "Wait for the promised date",
                      checks,
                      "Wait until the promised date, then verify the payment",
                      "A dated commitment means today's demand would be redundant.",
                      product_rule=False)

    # 9. missed / overdue promise
    missed = promise_stat == "overdue"
    flag("promise_missed", "Promise kept", not missed, "KNOWN",
         "the promised date has passed without payment" if missed
         else "no overdue promise")
    if missed:
        return _agree("SEND", "Chase - the promise was missed",
                      checks,
                      "Ask for a FIRM revised date, not open 'we will pay' intent",
                      "A missed promise justifies a direct follow-up and a revised "
                      "commitment with a date.",
                      product_rule=False)

    # 10. payment plan / partial payments in progress
    plans = repo.select("actions_queue", where={"customer_name": name, "status": "contacted"})
    partial = repo.select("payments", where={"customer_name": name})
    plan_active = False
    partial_note = ""
    if partial:
        notes = [p.get("note") or "" for p in partial]
        plan_active = any(("plan" in n.lower() or "installment" in n.lower()) for n in notes)
        partial_note = f"{len(partial)} partial payment(s) recorded"
    flag("plan", "Payment plan in progress", not plan_active,
         "KNOWN" if partial else "UNKNOWN",
         partial_note if partial else "no recorded partial payments")
    if plan_active:
        return _agree("PAUSE", "Continue the agreed plan",
                      checks,
                      "Track the plan and follow up only if a plan date is missed",
                      "The customer is paying under an agreed arrangement.",
                      product_rule=False)

    # 11. recent contact with no reply
    recently_contacted = False
    q = repo.select("actions_queue", where={"customer_name": name}, limit=1)
    if q and q[0].get("contacted_at"):
        try:
            last = dt.datetime.fromisoformat(str(q[0]["contacted_at"]).replace("Z", "+00:00"))
            recently_contacted = (dt.datetime.now(dt.timezone.utc) - last).days < 7
        except ValueError:
            recently_contacted = False
    flag("recent_contact", "No recent follow-up sent", not recently_contacted,
         "KNOWN" if recently_contacted else "UNKNOWN",
         "contacted within the last 7 days - allow them to respond"
         if recently_contacted else "no recent contact on file")
    if recently_contacted:
        return _agree("PAUSE", "Wait for their reply",
                      checks,
                      "Give them a few days - follow up only if no reply arrives",
                      "Re-sending within 7 days of contact looks automated.",
                      product_rule=False)

    # 12. repeated missed promises (history) -> escalate
    missed_hist = 0
    for s in repo.select("signals", where={"customer_name": name,
                                           "signal_type": "payment_promise"}):
        note = (s.get("resolution_note") or "").upper()
        if note.startswith("MISSED") or (
                s.get("resolved") and note.startswith("MISSED")):
            missed_hist += 1
    flag("repeat_misses", "Repeated missed promises", missed_hist < 2, "KNOWN",
         f"{missed_hist} missed promise(s) on file" if missed_hist
         else "no repeated misses")
    if missed_hist >= 2:
        return _agree("ESCALATE", "Escalate to a manager / owner",
                      checks,
                      "Move the account to the owner or manager with the full history",
                      "Two or more broken commitments mean routine chasing is "
                      "unlikely to work - escalate instead.",
                      product_rule=True)

    # 13. default: overdue balance, nothing blocking -> standard send is fine
    flag("due", "Invoice past due", amount > 0, "KNOWN",
         f"${amount:,.2f} overdue" if amount > 0 else "no overdue balance")
    if amount > 0:
        return _agree("SEND", "Overdue - send the reminder",
                      checks,
                      "Send a payment reminder with the invoice details",
                      "No blocker on file - a direct reminder is appropriate.",
                      product_rule=False)

    return _agree("NO_ACTION", "Nothing to act on",
                  checks, "Monitor", "No reason to send anything today.",
                  product_rule=False)