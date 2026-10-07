"""Expected-cash buckets.

Only explicit customer facts are used: a promise date from the email analyzer,
or the ledger due date. We never invent an expected payment date - an invoice
with no promise stays in 'no confirmed payment date'.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from services.sync import evaluate_promise


def build_forecast(repo: Any) -> dict[str, Any]:
    today = dt.date.today()
    week_end = today + dt.timedelta(days=7)
    month_end = today + dt.timedelta(days=30)

    invoices = repo.select("invoices")
    signals = repo.select("signals")

    # Only promises that are still in the future are "expected" cash. A missed
    # or overdue promise means money we were told about but that hasn't shown
    # up - it counts as overdue, not as expected.
    def _status(sig: dict) -> str:
        return evaluate_promise(sig, today)

    promises = [s for s in signals
                if s.get("signal_type") == "payment_promise"
                and not s.get("resolved")
                and s.get("promised_date")
                and _status(s) in ("due_today", "upcoming")]

    def invoice_amount_for(sig: dict) -> float:
        amt = sig.get("promised_amount")
        if amt:
            return float(amt)
        related = sig.get("related_invoice") or ""
        if related:
            for inv in invoices:
                if (inv.get("invoice_number") or "").strip().upper() == related.upper():
                    return float(inv.get("amount_outstanding") or 0)
        same = [i for i in invoices if (i.get("customer_name") or "") == (sig.get("customer_name") or "")]
        if len(same) == 1:
            return float(same[0].get("amount_outstanding") or 0)
        return 0.0

    buckets = {
        "expected_today": {"label": "Expected today",
                           "amount": 0.0, "items": [], "source": "promise"},
        "expected_this_week": {"label": "Expected this week",
                               "amount": 0.0, "items": [], "source": "promise"},
        "expected_next_30_days": {"label": "Expected next 30 days",
                                  "amount": 0.0, "items": [], "source": "promise"},
        "expected_later": {"label": "Expected later",
                           "amount": 0.0, "items": [], "source": "promise"},
        "overdue_unconfirmed": {"label": "Overdue - no confirmed date",
                                "amount": 0.0, "items": [], "source": "ledger"},
        "due_no_confirmed_date": {"label": "Not yet due - no confirmed date",
                                  "amount": 0.0, "items": [], "source": "ledger"},
    }

    for p in promises:
        pdate = dt.date.fromisoformat(p["promised_date"])
        amt = invoice_amount_for(p)
        if amt <= 0:
            continue
        ex = p.get("promised_amount")
        src = "customer promise" if ex else "promised on customer promise - amount from ledger"
        if pdate == today:
            key = "expected_today"
        elif pdate <= week_end:
            key = "expected_this_week"
        elif pdate <= month_end:
            key = "expected_next_30_days"
        else:
            key = "expected_later"
        buckets[key]["items"].append({
            "customer_name": p.get("customer_name", ""),
            "amount": round(amt, 2),
            "date": p["promised_date"],
            "status": evaluate_promise(p, today),
            "source": src,
        })
        buckets[key]["amount"] = round(buckets[key]["amount"] + amt, 2)

    def _covered_by_promise(inv: dict) -> bool:
        """Is this invoice covered by a specific (or the only) open promise?"""
        number = (inv.get("invoice_number") or "").strip().upper()
        name = inv.get("customer_name", "")
        for p in promises:
            related = (p.get("related_invoice") or "").strip().upper()
            if related and related == number:
                return True
        open_same = [i for i in invoices
                     if (i.get("customer_name") or "") == name
                     and float(i.get("amount_outstanding") or 0) > 0]
        if len(open_same) == 1:
            return any((p.get("customer_name") or "") == name for p in promises)
        return False

    for inv in invoices:
        amt = float(inv.get("amount_outstanding") or 0)
        if amt <= 0:
            continue
        name = inv.get("customer_name", "")
        due = inv.get("due_date")
        overdue = (today - dt.date.fromisoformat(due)).days > 0 if due else False
        if _covered_by_promise(inv):
            continue
        bucket = "overdue_unconfirmed" if overdue else "due_no_confirmed_date"
        buckets[bucket]["items"].append({
            "customer_name": name,
            "amount": round(amt, 2),
            "date": due,
            "status": "overdue" if overdue else "upcoming",
            "source": "ledger due date",
        })
        buckets[bucket]["amount"] = round(buckets[bucket]["amount"] + amt, 2)

    order = [
        "expected_today", "expected_this_week", "expected_next_30_days",
        "expected_later", "overdue_unconfirmed", "due_no_confirmed_date",
    ]
    total = round(sum(buckets[b]["amount"] for b in order), 2)
    return {
        "as_of": today.isoformat(),
        "total_cash": total,
        "buckets": [
            {"key": key, **buckets[key]}
            for key in order if buckets[key]["amount"] > 0 or buckets[key]["items"]
        ],
    }