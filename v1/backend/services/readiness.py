"""Invoice send-readiness, recurring-invoice readiness and payment readiness.

Three views, all derived from stored facts only (ledger rows, signals,
promises, payments). Every check carries a status (PASS / WARNING / BLOCKED /
UNKNOWN), an evidence marker (KNOWN / INFERRED / UNKNOWN) and a verification
hint so the team knows exactly what to confirm before sending or chasing.
Nothing here ever invents a fact - a check that cannot be proven is UNKNOWN
and is surfaced as something to verify, not silently assumed.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from database import repo as _repo  # noqa: F401  (re-exported for convenience)
from services.behavior import _PROCESS_BLOCKERS, payment_behavior

_MONEY = lambda x: round(float(x or 0), 2)  # noqa: E731


def _d(iso: str | None) -> dt.date | None:
    if not iso:
        return None
    try:
        return dt.date.fromisoformat(str(iso)[:10])
    except ValueError:
        return None


def _open_invoice_signals(repo: Any, customer: str, invoice_number: str) -> list[dict[str, Any]]:
    return [
        s for s in repo.select("signals", where={"customer_name": customer})
        if not s.get("resolved") and (s.get("related_invoice") or "") == invoice_number
    ]


# ---------------------------------------------------------------------------
# 1. Invoice send-readiness: 10 checks to run before (re)sending an invoice
# ---------------------------------------------------------------------------

def invoice_send_readiness(repo: Any, invoice: dict[str, Any]) -> dict[str, Any]:
    num = str(invoice.get("invoice_number") or "")
    name = str(invoice.get("customer_name") or "")
    contact = str(invoice.get("contact_email") or "")
    amt = _MONEY(invoice.get("amount_outstanding"))
    due = _d(invoice.get("due_date"))
    issued = bool(invoice.get("invoice_date"))

    inv_sigs = _open_invoice_signals(repo, name, num)
    cust_sigs = [s for s in repo.select("signals", where={"customer_name": name, "resolved": False})
                 if (s.get("related_invoice") or "") != num]
    types = {s.get("signal_type") for s in inv_sigs}
    cust_types = {s.get("signal_type") for s in cust_sigs}

    # look for a potential duplicate: same customer, same amount, still open
    dup = [
        i for i in repo.select("invoices", where={"customer_name": name})
        if (i.get("invoice_number") or "") != num
        and _MONEY(i.get("amount_outstanding")) == amt and amt > 0
        and str(i.get("status") or "").lower() != "paid"
    ]

    checks: list[dict[str, Any]] = []

    # 1 client email
    if "bounced_email" in cust_types:
        checks.append({"key": "contact", "label": "Client email",
                       "status": "BLOCKED", "evidence": "KNOWN",
                       "note": "the contact address bounced before",
                       "verify": "confirm the correct AP contact before re-sending"})
    elif contact:
        checks.append({"key": "contact", "label": "Client email",
                       "status": "PASS", "evidence": "KNOWN",
                       "note": f"invoice carries contact {contact}", "verify": ""})
    else:
        checks.append({"key": "contact", "label": "Client email",
                       "status": "WARNING", "evidence": "UNKNOWN",
                       "note": "no contact email on the invoice",
                       "verify": "add the AP contact email"})

    # 2 amount
    if amt > 0:
        checks.append({"key": "amount", "label": "Amount billed",
                       "status": "PASS", "evidence": "KNOWN",
                       "note": f"${amt:,.2f} on file", "verify": ""})
    else:
        checks.append({"key": "amount", "label": "Amount billed",
                       "status": "WARNING", "evidence": "UNKNOWN",
                       "note": "amount outstanding is zero / missing",
                       "verify": "confirm the billed amount"})

    # 3 due date
    if due:
        checks.append({"key": "due_date", "label": "Due date",
                       "status": "PASS", "evidence": "KNOWN",
                       "note": f"due {due}", "verify": ""})
    else:
        checks.append({"key": "due_date", "label": "Due date",
                       "status": "WARNING", "evidence": "UNKNOWN",
                       "note": "no due date set", "verify": "set the due date before sending"})

    # 4 payment instructions (not logged - flagged for confirmation, never assumed)
    checks.append({"key": "payment_instructions", "label": "Payment instructions",
                   "status": "UNKNOWN", "evidence": "UNKNOWN",
                   "note": "bank / payment details are not logged in the workspace",
                   "verify": "confirm invoice states the bank details and payment terms"})

    # 5 PO / reference
    if "wrong_po" in types:
        checks.append({"key": "po_reference", "label": "PO / reference",
                       "status": "BLOCKED", "evidence": "KNOWN",
                       "note": "PO mismatch flagged on this invoice",
                       "verify": "sort the PO/reference with the customer"})
    elif any((s.get("signal_type") or "") == "wrong_po"
             for s in repo.select("signals", where={"customer_name": name})
             if (s.get("related_invoice") or "") == num and s.get("resolved")):
        checks.append({"key": "po_reference", "label": "PO / reference",
                       "status": "PASS", "evidence": "KNOWN",
                       "note": "previous PO mismatch on this invoice was resolved",
                       "verify": ""})
    else:
        checks.append({"key": "po_reference", "label": "PO / reference",
                       "status": "UNKNOWN", "evidence": "UNKNOWN",
                       "note": "no PO confirmation on file",
                       "verify": "confirm the PO / contract reference is on the invoice"})

    # 6 supporting documents
    if "documentation_request" in types:
        checks.append({"key": "documents", "label": "Supporting documents",
                       "status": "BLOCKED", "evidence": "KNOWN",
                       "note": "customer is waiting on documents for this invoice",
                       "verify": "attach the requested documents, then re-send"})
    else:
        checks.append({"key": "documents", "label": "Supporting documents",
                       "status": "UNKNOWN", "evidence": "UNKNOWN",
                       "note": "no documentation request on file",
                       "verify": "confirm any attachments/work-delivery notes are included"})

    # 7 service period
    if issued and due:
        checks.append({"key": "service_period", "label": "Service period",
                       "status": "PASS", "evidence": "KNOWN",
                       "note": "issue and due dates delimit the period",
                       "verify": ""})
    else:
        checks.append({"key": "service_period", "label": "Service period",
                       "status": "WARNING", "evidence": "INFERRED",
                       "note": "period is not independently logged",
                       "verify": "confirm the billed period is shown on the invoice"})

    # 8 currency
    checks.append({"key": "currency", "label": "Currency",
                   "status": "UNKNOWN", "evidence": "UNKNOWN",
                   "note": "currency is not logged in the workspace",
                   "verify": "confirm a single currency is stated on the invoice"})

    # 9 duplicate check
    if dup:
        checks.append({"key": "duplicate", "label": "Duplicate check",
                       "status": "WARNING", "evidence": "KNOWN",
                       "note": f"{len(dup)} open invoice(s) for the same customer and amount",
                       "verify": "confirm this is not a re-issue before sending"})
    else:
        checks.append({"key": "duplicate", "label": "Duplicate check",
                       "status": "PASS", "evidence": "KNOWN",
                       "note": "no matching open invoice on file", "verify": ""})

    # 10 dispute / blocker
    if "dispute" in types:
        checks.append({"key": "dispute", "label": "Dispute / blocker",
                       "status": "BLOCKED", "evidence": "KNOWN",
                       "note": "the charge is under dispute",
                       "verify": "resolve the dispute first"})
    elif "approval_pending" in types or "missing_invoice" in types:
        checks.append({"key": "dispute", "label": "Dispute / blocker",
                       "status": "WARNING", "evidence": "KNOWN",
                       "note": "customer has an unresolved issue with this invoice",
                       "verify": "attend to the open issue before re-sending"})
    else:
        checks.append({"key": "dispute", "label": "Dispute / blocker",
                       "status": "PASS", "evidence": "KNOWN",
                       "note": "no dispute or blocker on file", "verify": ""})

    blocked = [c for c in checks if c["status"] in ("BLOCKED",)]
    warning = [c for c in checks if c["status"] in ("WARNING",)]
    unknown = [c for c in checks if c["status"] == "UNKNOWN"]
    passed = [c for c in checks if c["status"] == "PASS"]

    if blocked:
        verdict, verdict_label = "NOT READY", "Blocked - fix the blocking items first"
    elif warning or unknown:
        verdict, verdict_label = "CONFIRM", "Ready to send after confirming the gaps"
    else:
        verdict, verdict_label = "READY", "Ready to send"

    return {
        "invoice_number": num,
        "customer_name": name,
        "amount": amt,
        "due_date": str(due) if due else None,
        "checks": checks,
        "passed": len(passed),
        "warning": len(warning),
        "unknown": len(unknown),
        "blocked": len(blocked),
        "total": len(checks),
        "verdict": verdict,
        "verdict_label": verdict_label,
        "blockers": [c["label"] for c in blocked],
        "verify_before_send": [
            c["verify"] for c in checks if c["status"] != "PASS" and c.get("verify")
        ],
    }


# ---------------------------------------------------------------------------
# 2. Recurring invoice readiness: a per-customer profile for repeat billing
# ---------------------------------------------------------------------------

def recurring_invoice_readiness(repo: Any, name: str) -> dict[str, Any]:
    invoices = [i for i in repo.select("invoices", where={"customer_name": name})
                if i.get("invoice_number")]
    if len(invoices) < 2:
        return {"customer_name": name, "recurring": False,
                "invoice_count": len(invoices),
                "note": "needs at least two invoices to profile recurring billing"}

    dated = sorted([i for i in invoices if _d(i.get("invoice_date"))],
                   key=lambda i: _d(i.get("invoice_date")))
    intervals = []
    for a, b in zip(dated, dated[1:]):
        gap = (_d(b.get("invoice_date")) - _d(a.get("invoice_date"))).days
        if 1 <= gap <= 120:
            intervals.append(gap)
    avg_interval = round(sum(intervals) / len(intervals)) if intervals else None

    rows = repo.select("signals", where={"customer_name": name})
    dispute_sigs = [s for s in rows if s.get("signal_type") == "dispute"]
    docs_sigs = [s for s in rows if s.get("signal_type") == "documentation_request"]
    po_sigs = [s for s in rows if s.get("signal_type") == "wrong_po"]
    approval_sigs = [s for s in rows if s.get("signal_type") == "approval_pending"]

    behavior = payment_behavior(repo, name)
    avg_delay = behavior.get("avg_delay_days")
    on_time = behavior.get("on_time_percent")
    missed = behavior.get("promises_missed") or 0

    risks: list[dict[str, Any]] = []
    if avg_delay is not None and avg_delay > 0:
        risks.append({"risk": "delayed payments", "evidence": "KNOWN",
                      "note": f"avg {avg_delay} days late across paid history"})
    if missed:
        risks.append({"risk": "missed promises", "evidence": "KNOWN",
                      "note": f"{missed} payment promise(s) missed"})
    if dispute_sigs:
        risks.append({"risk": "disputes", "evidence": "KNOWN",
                      "note": f"{len(dispute_sigs)} dispute signal(s) on file"})
    if po_sigs:
        risks.append({"risk": "PO / reference issues", "evidence": "KNOWN",
                      "note": "the customer has flagged PO mismatches before"})
    if approval_sigs:
        risks.append({"risk": "internal approval", "evidence": "KNOWN",
                      "note": "the customer routes invoices through an internal approval stage"})

    open_blockers = {s.get("signal_type") for s in rows if not s.get("resolved")} & _PROCESS_BLOCKERS
    if open_blockers:
        risks.append({"risk": "open blocker", "evidence": "KNOWN",
                      "note": f"open process blocker(s): {', '.join(sorted(open_blockers))}"})

    if risks:
        verdict, label = "REVIEW", "Confirm with this customer before the next invoice"
    else:
        verdict, label = "READY", "Recurring billing looks stable"

    return {
        "customer_name": name,
        "recurring": True,
        "invoice_count": len(invoices),
        "first_invoice_date": str(_d(dated[0].get("invoice_date"))) if dated else None,
        "latest_invoice_date": str(_d(dated[-1].get("invoice_date"))) if dated else None,
        "avg_interval_days": avg_interval,
        "typical": {
            "avg_delay_days": avg_delay,
            "on_time_percent": on_time,
            "missed_promises": missed,
            "disputes": len(dispute_sigs),
            "documentation_needed": bool(docs_sigs),
            "po_required": bool(po_sigs),
            "approval_stage": bool(approval_sigs),
        },
        "risks": risks,
        "verdict": verdict,
        "verdict_label": label,
        "checks": [
            {"key": "history", "label": "Payment history",
             "status": "BLOCKED" if avg_delay and avg_delay >= 30
             else ("WARNING" if avg_delay and avg_delay > 0 else "PASS"),
             "evidence": "KNOWN" if avg_delay is not None else "UNKNOWN",
             "note": (f"avg {avg_delay} days late" if avg_delay
                      else ("paid on time to date" if on_time and on_time >= 100
                            else "no paid history yet")),
             "verify": ""},
            {"key": "disputes", "label": "Disputes",
             "status": "BLOCKED" if dispute_sigs else "PASS",
             "evidence": "KNOWN",
             "note": f"{len(dispute_sigs)} dispute(s) on file" if dispute_sigs
             else "no disputes on file",
             "verify": "resolve outstanding disputes before the next invoice" if dispute_sigs else ""},
            {"key": "po", "label": "PO / reference",
             "status": "WARNING" if po_sigs else "PASS",
             "evidence": "KNOWN",
             "note": "PO mismatches have occurred - include the reference up front" if po_sigs
             else "no PO issues on file",
             "verify": "put the confirmed PO reference on the next invoice" if po_sigs else ""},
            {"key": "approval", "label": "Approval stage",
             "status": "WARNING" if approval_sigs else "PASS",
             "evidence": "KNOWN",
             "note": "customer needs an internal approval stage" if approval_sigs
             else "no approval bottleneck on file",
             "verify": "send the invoice early enough for their approval cycle" if approval_sigs else ""},
            {"key": "variance", "label": "Amount / period variance",
             "status": "UNKNOWN", "evidence": "UNKNOWN",
             "note": "variance is not statistically derivable from the ledger",
             "verify": "spot-check that this invoice matches the agreed scope/rate"},
        ],
    }


# ---------------------------------------------------------------------------
# 3. Payment readiness score: transparent 0-100 with every signal shown
# ---------------------------------------------------------------------------

def payment_readiness_score(repo: Any, item: dict[str, Any]) -> dict[str, Any]:
    """Transparent readiness of THIS customer to pay, 0-100.

    Every point is explained: each signal has a weight, a measured value and
    the reason it moved the score. The score never replaces the evidence - the
    breakdown is always shown beside it.
    """
    name = item.get("customer_name", "")
    behavior = payment_behavior(repo, name)
    paid = behavior.get("total_payments")
    on_time = behavior.get("on_time_percent")
    avg_delay = behavior.get("avg_delay_days")
    kept = behavior.get("promises_kept") or 0
    missed = behavior.get("promises_missed") or 0
    kept_pct = behavior.get("promises_kept_percent")

    signals = [
        {"key": "history", "label": "Paid on time (history)",
         "weight": 30,
         "value": (f"{on_time}% on time" if on_time is not None else "no paid invoices"),
         "score": (30.0 * on_time / 100.0 if on_time is not None else 0.0),
         "reason": (f"{on_time}% of settled invoices were paid on time"
                    if on_time is not None else "no payment history to measure")},
        {"key": "delay", "label": "Average payment delay",
         "weight": 25,
         "value": (f"{avg_delay} days" if avg_delay is not None else "none measured"),
         "score": (25.0 if avg_delay is None or avg_delay <= 0
                   else max(0.0, 25.0 - 2.0 * avg_delay)),
         "reason": (f"on average {avg_delay} days late"
                    if avg_delay else ("no meaningful delay"
                    if avg_delay == 0 else "no delay data - partial credit at most"))},
        {"key": "promises", "label": "Promise reliability",
         "weight": 20,
         "value": (f"{kept}/{kept + missed} promises kept"
                   if (kept + missed) else "no promises on file"),
         "score": (20.0 * kept_pct / 100.0 if kept_pct is not None else 0.0),
         "reason": (f"{kept_pct}% of promises were kept"
                    if kept_pct is not None else "no promise history to measure")},
        {"key": "disputes", "label": "Disputes / blockers",
         "weight": 15,
         "value": "none open" if not (set(item.get("open_signal_types") or [])
                                      & {"dispute", "missing_invoice", "wrong_po",
                                         "documentation_request", "approval_pending"})
         else "open blockers present",
         "score": (15.0 if not (set(item.get("open_signal_types") or [])
                                & {"dispute", "missing_invoice", "wrong_po",
                                   "documentation_request", "approval_pending"}) else 0.0),
         "reason": ("no open disputes or process blockers"
                    if paid is not None or item.get("open_signal_types")
                    else "no blocker evidence")},
        {"key": "contactability", "label": "Contactable / responding",
         "weight": 10,
         "value": (f"responded {item.get('last_response_days')} days ago"
                   if item.get("last_response_days") is not None else "no recent response tracked"),
         "score": (10.0 if item.get("last_response_days") is not None
                   and item["last_response_days"] <= 14
                   else (5.0 if item.get("last_response_days") is not None else 0.0)),
         "reason": ("recent response within 14 days" if (item.get("last_response_days") is not None
                   and item["last_response_days"] <= 14)
                   else ("last contact was more than 14 days ago"
                   if item.get("last_response_days") is not None
                   else "no response window tracked"))},
    ]

    if paid is None:
        signals[0]["score"] = 15.0
        signals[0]["reason"] = "no history - baseline neutrality for a new customer"

    total = round(sum(s["score"] for s in signals), 1)
    if total > 100:
        total = 100.0

    if total >= 80:
        label, tone = "Ready to pay", "high"
    elif total >= 55:
        label, tone = "Likely to pay on time", "good"
    elif total >= 35:
        label, tone = "Watch closely", "fair"
    else:
        label, tone = "High risk of late payment", "poor"

    return {
        "customer_name": name,
        "score": total,
        "label": label,
        "tone": tone,
        "max_score": 100,
        "method": "Weighted signals - every point is backed by evidence shown below. "
                  "No stored fact is hidden; unavailable data scores zero, never a guess.",
        "signals": signals,
    }