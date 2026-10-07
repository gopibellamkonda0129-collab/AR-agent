"""WEEKLY RECEIVABLES BRIEF - the auto-generated summary for a founder/CFO.

Everything here is derived from stored facts; nothing is invented. Rows the
product cannot know yet (e.g. actual cash received) are reported as 'not yet
tracked' instead of guessed.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Any

from services.next_action_engine import build_queue
from services.sync import evaluate_promise


def weekly_brief(repo: Any, week_start: str | None = None) -> dict[str, Any]:
    today = dt.date.today()
    if week_start:
        try:
            start = dt.date.fromisoformat(week_start)
        except ValueError:
            start = today - dt.timedelta(days=today.weekday())
    else:
        start = today - dt.timedelta(days=today.weekday())
    end = start + dt.timedelta(days=7)

    invoices = repo.select("invoices")
    signals = repo.select("signals")

    # 1. cash collected (only counted from verbose facts - usually not tracked yet)
    paid = 0.0
    paid_n = 0
    for inv in invoices:
        if (inv.get("status") or "").lower() == "paid" or float(inv.get("amount_outstanding") or 0) <= 0:
            paid += float(inv.get("amount_outstanding") or 0)
            paid_n += 1
    paid_marker = "not yet tracked - connect a bank feed or mark invoices paid" if not signals else ""

    # 2. new overdue invoices this week (due date fell inside this week)
    new_overdue = [i for i in invoices
                   if i.get("due_date") and start <= dt.date.fromisoformat(i["due_date"]) < end]
    new_overdue_amt = sum(float(i.get("amount_outstanding") or 0) for i in new_overdue)

    # 3. missed promises this week
    missed = [s for s in signals
              if s.get("signal_type") == "payment_promise"
              and s.get("promised_date")
              and start <= dt.date.fromisoformat(s["promised_date"]) < end
              and evaluate_promise(s, today) == "overdue"]
    missed_amt = sum(float(s.get("promised_amount") or 0)
                     for s in missed if s.get("promised_amount"))
    missed_n = len(missed)

    # 4. disputes
    open_sigs = [s for s in signals if not s.get("resolved")]
    disputes = [s for s in open_sigs if s.get("signal_type") == "dispute"]
    dispute_amt = sum(_related_amount(s, invoices) for s in disputes)

    # 5. expected incoming payments (open promises, forward-looking only)
    fwd = [s for s in signals
           if s.get("signal_type") == "payment_promise"
           and s.get("promised_date")
           and not s.get("resolved")
           and dt.date.fromisoformat(s["promised_date"]) >= today]
    fwd_amt = sum(float(s.get("promised_amount") or 0) for s in fwd if s.get("promised_amount"))

    # 6. largest overdue accounts + escalation list + next-week priorities
    queue = build_queue(repo)
    top = sorted(queue["actions"], key=lambda i: -i["overdue_amount"])[:5]
    escalate = [i["customer_name"] for i in queue["actions"]
                if i["priority"] == "critical"]
    top_next_week = queue["actions"][:3]

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "week": {"start": start.isoformat(), "end": end.isoformat()},
        "cash_collected": {"amount": round(paid, 2), "count": paid_n,
                           "note": paid_marker},
        "new_overdue_invoices": {"count": len(new_overdue),
                                 "amount": round(new_overdue_amt, 2),
                                 "customers": sorted({i.get("customer_name", "") for i in new_overdue})},
        "missed_payment_promises": {"count": missed_n, "amount": round(missed_amt, 2),
                                    "customers": sorted({s.get("customer_name", "") for s in missed})},
        "open_disputes": {"count": len(disputes), "amount": round(dispute_amt, 2)},
        "customers_requiring_escalation": escalate[:10],
        "largest_overdue_accounts": [
            {"customer_name": i["customer_name"], "overdue_amount": i["overdue_amount"],
             "days_overdue": i["max_days_overdue"], "priority": i["priority"]}
            for i in top
        ],
        "expected_incoming_payments": round(fwd_amt, 2),
        "recommended_priorities_next_week": [
            {"customer_name": i["customer_name"], "action": i["action_label"],
             "priority": i["priority"], "amount": i["overdue_amount"]}
            for i in top_next_week
        ],
    }


def _related_amount(sig: dict, invoices: list[dict]) -> float:
    related = sig.get("related_invoice") or ""
    if related:
        for inv in invoices:
            if (inv.get("invoice_number") or "").strip().upper() == related.upper():
                return float(inv.get("amount_outstanding") or 0)
    return float(sig.get("promised_amount") or 0)