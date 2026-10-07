"""Money Recovered: totals derived strictly from recorded payments.

The dashboard's "Money Recovered" metric must only ever reflect payments a user
has actually recorded (via /invoices/{id}/mark-paid or imported). Never invented.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from database import repo


def _start_of_month(d: dt.date) -> dt.date:
    return d.replace(day=1)


def _month_range(d: dt.date) -> tuple[dt.date, dt.date]:
    start = _start_of_month(d)
    nxt = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return start, nxt - dt.timedelta(days=1)


def money_recovered() -> dict[str, Any]:
    """Return total / this-month / last-month recovered amounts."""
    today = dt.date.today()
    this_start, this_end = _month_range(today)
    last_end = this_start - dt.timedelta(days=1)
    last_start, _ = _month_range(last_end)

    payments = repo.select("payments")

    def total(a: dt.date, b: dt.date) -> float:
        s = 0.0
        for p in payments:
            paid = p.get("paid_at")
            if not paid:
                continue
            try:
                d = dt.date.fromisoformat(str(paid)[:10])
            except ValueError:
                continue
            if a <= d <= b:
                s += float(p.get("amount") or 0)
        return round(s, 2)

    return {
        "total": round(sum(float(p.get("amount") or 0) for p in payments), 2),
        "this_month": total(this_start, this_end),
        "last_month": total(last_start, last_end),
        "this_month_label": this_start.strftime("%B %Y"),
    }
