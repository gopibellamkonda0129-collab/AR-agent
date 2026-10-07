"""Cash-at-Risk view: per-invoice exposure, additive to the existing risk score.

The product already has a customer-level risk score
(collections_intelligence.risk_score). This module adds a SEPARATE signal:
for every open invoice, how much cash is exposed, weighted by time and by
whatever is holding the billing process up (blocker, missed promise, overdue days).

Principles kept from the rest of the engine:
  - money/dates only from stored facts (ledger rows, signals, payments)
  - blockers and process stages come from invoice_process_status
  - the recommended next action comes from the action engine (build_queue)
  - nothing here overwrites the existing risk score
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from services.behavior import payment_behavior
from services.process_status import invoice_process_status
from services.readiness import invoice_send_readiness

_BAND_ORDER = {
    "blocked": 0,     # cash is held up by a process item, not a payment problem
    "critical": 1,    # 30+ days overdue
    "late": 2,        # 15-29 days overdue
    "overdue": 3,     # 1-14 days overdue
    "due_soon": 4,    # due within 7 days (unconfirmed readiness)
    "open": 5,        # on time, no confirmed blocker
}

_BLOCKED_STATUSES = {"disputed", "po_pending", "approval_pending",
                     "receipt_unknown", "process_blocked"}


def _days(iso: str | None, today: dt.date) -> int | None:
    if not iso:
        return None
    try:
        day = dt.date.fromisoformat(str(iso)[:10])
    except ValueError:
        return None
    return (today - day).days


def cash_risk_view(repo: Any, sort: str = "weight") -> dict[str, Any]:
    """Rows + totals for the Cash-at-Risk view (open invoices only).

    Two sort schemes, neither presented as superior:
      - weight (default): blocked/critical bands first, then amount x days
      - agent: the action engine's decision order (blockers and missed
        promises float to the top) - a different lens, not a "better" one.
    """
    today = dt.date.today()

    # reuse the action engine's decision for the recommended "next action"
    from services.next_action_engine import build_queue
    built = build_queue(repo)
    by_name = {a["customer_name"]: a for a in built["actions"]}
    agent_rank = {a["customer_name"]: a.get("agent_rank") or 999
                  for a in built["actions"]}

    rows: list[dict[str, Any]] = []
    for inv in repo.select("invoices"):
        amt = round(float(inv.get("amount_outstanding") or 0), 2)
        if amt <= 0 or str(inv.get("status") or "").lower() == "paid":
            continue
        num = str(inv.get("invoice_number") or "")
        name = str(inv.get("customer_name") or "")
        due = _days(inv.get("due_date"), today)
        days_overdue = max(due or 0, 0)
        ps = invoice_process_status(repo, inv)
        status = ps.get("status") or "unknown"

        if ps.get("blocker") and status in _BLOCKED_STATUSES:
            band, band_label = "blocked", "Blocked in process"
        elif days_overdue >= 30:
            band, band_label = "critical", "Extended overdue"
        elif days_overdue >= 15:
            band, band_label = "late", "Late"
        elif days_overdue >= 1:
            band, band_label = "overdue", "Overdue"
        elif due is not None and due >= -7:
            band, band_label = "due_soon", "Due soon"
        else:
            band, band_label = "open", "Open"

        qi = by_name.get(name)
        pre_due = bool(qi and qi.get("pre_due", {}).get("needed"))
        if (qi and (not qi.get("primary_invoice_number")
                    or qi.get("primary_invoice_number") == num)
                and qi.get("action_label")):
            next_action = str(qi["action_label"])
        elif qi and qi.get("next_action_override"):
            next_action = f"Override: {qi['next_action_override']}"
        elif ps.get("blocker"):
            next_action = f"Attend to {ps['blocker']}"
        elif ps.get("stage"):
            next_action = f"{ps['stage']} — next step"
        else:
            next_action = ""

        if band == "blocked" and ps.get("blocker"):
            reason = f"waiting on: {ps['blocker']}"
        elif pre_due:
            reason = f"confirm payment readiness before the due date"
        elif days_overdue > 0:
            reason = f"{days_overdue}d overdue"
        elif qi and qi.get("reason"):
            reason = str(qi["reason"])
        else:
            reason = band_label.lower()

        readiness = invoice_send_readiness(repo, inv)
        behavior = payment_behavior(repo, name)
        rows.append({
            "invoice_number": num,
            "customer_name": name,
            "amount_outstanding": amt,
            "due_date": inv.get("due_date"),
            "days_overdue": days_overdue,
            "status": status,
            "status_label": ps.get("status_label"),
            "stage": ps.get("stage"),
            "blocker": ps.get("blocker"),
            "evidence_status": ps.get("evidence_status"),
            "risk_weight": round(amt * days_overdue, 2),
            "band": band,
            "band_label": band_label,
            "pre_due": pre_due,
            "next_action": next_action,
            "reason": reason,
            "readiness_verdict": readiness.get("verdict"),
            "readiness_label": readiness.get("verdict_label"),
            "reliability": behavior.get("reliability_label"),
            "missed_promises": behavior.get("promises_missed"),
            "owner": ((qi or {}).get("ownership") or {}).get("owner") or "",
            "agent_rank": agent_rank.get(name) or 999,
            "primary_invoice_id": inv.get("id"),
        })

    if sort == "agent":
        rows.sort(key=lambda r: (r["agent_rank"], _BAND_ORDER.get(r["band"], 9),
                                 -r["risk_weight"], r["invoice_number"]))
    else:
        rows.sort(key=lambda r: (_BAND_ORDER.get(r["band"], 9), -r["risk_weight"],
                                 r["invoice_number"]))

    amt = lambda row: row["amount_outstanding"]  # noqa: E731
    band_amt = lambda b: round(sum(r["risk_weight"] for r in rows if r["band"] == b), 2)  # noqa: E731
    band_count = lambda b: sum(1 for r in rows if r["band"] == b)  # noqa: E731

    overdue_inv = [r for r in rows if r["days_overdue"] > 0]
    blocked_inv = [r for r in rows if r["band"] == "blocked"]
    critical_inv = [r for r in rows if r["band"] == "critical"]

    by_customer: dict[str, dict[str, Any]] = {}
    for r in rows:
        agg = by_customer.setdefault(r["customer_name"], {
            "customer_name": r["customer_name"],
            "invoice_count": 0,
            "outstanding": 0.0,
            "overdue_amount": 0.0,
            "worst_days_overdue": 0,
            "risk_weight": 0.0,
            "bands": {},
            "blockers": [],
        })
        agg["invoice_count"] += 1
        agg["outstanding"] = round(agg["outstanding"] + amt(r), 2)
        agg["overdue_amount"] = round(agg["overdue_amount"]
                                      + (amt(r) if r["days_overdue"] > 0 else 0.0), 2)
        agg["worst_days_overdue"] = max(agg["worst_days_overdue"], r["days_overdue"])
        agg["risk_weight"] = round(agg["risk_weight"] + amt(r) * r["days_overdue"], 2)
        agg["bands"][r["band"]] = agg["bands"].get(r["band"], 0) + 1
        if r.get("blocker") and r["blocker"] not in agg["blockers"]:
            agg["blockers"].append(str(r["blocker"]))

    customers = sorted(by_customer.values(),
                       key=lambda c: (sum(c["bands"].values()), -c["risk_weight"]))

    return {
        "as_of": dt.datetime.now(dt.timezone.utc).isoformat(),
        "totals": {
            "open_invoices": len(rows),
            "open_amount": round(sum(amt(r) for r in rows), 2),
            "overdue_invoices": len(overdue_inv),
            "overdue_amount": round(sum(amt(r) for r in overdue_inv), 2),
            "weighted_risk": round(sum(amt(r) * r["days_overdue"] for r in rows), 2),
            "critical_invoices": len(critical_inv),
            "critical_amount": round(sum(amt(r) for r in critical_inv), 2),
            "blocked_cash": round(sum(amt(r) for r in blocked_inv), 2),
            "blocked_invoices": len(blocked_inv),
        },
        "by_band": [
            {"band": b, "label": lbl, "count": band_count(b), "risk_value": band_amt(b)}
            for b, lbl in [("blocked", "Blocked in process"),
                           ("critical", "30+ days overdue"),
                           ("late", "15-29 days overdue"),
                           ("overdue", "1-14 days overdue"),
                           ("due_soon", "Due within 7 days"),
                           ("open", "On time")]
            if band_count(b) > 0
        ],
        "customers": customers,
        "rows": rows,
    }