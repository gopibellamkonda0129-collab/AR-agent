"""Customers: AR ledger aggregates + the payment-promise tracker."""
from __future__ import annotations

import datetime as dt
from collections import Counter
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from database import repo
from services.behavior import (
    chase_strategy,
    collections_intelligence,
    collections_timeline,
    decision_order_for,
    invoice_readiness,
    ownership_for,
    payment_behavior,
    pre_due_readiness,
    why_late,
)
from services.next_action_engine import build_action_item
from services.process_status import customer_ar_process
from services.sync import evaluate_promise

router = APIRouter(prefix="/customers", tags=["customers"])

# Next.js static-export prefetches route payloads as /customers/index.txt;
# the {customer_name} route must not swallow those (it would 404 → retry spam).
_STATIC_OUT = Path(__file__).resolve().parents[2] / "frontend" / "dashboard" / "out"


@router.get("")
def list_customers():
    invoices = repo.select("invoices", order_by="amount_outstanding", desc=True)
    today = dt.date.today()
    groups: dict[str, dict] = {}
    for inv in invoices:
        name = inv.get("customer_name") or "Unknown"
        g = groups.setdefault(name, {
            "customer_name": name,
            "contact_email": inv.get("contact_email", ""),
            "invoice_count": 0,
            "total_outstanding": 0.0,
            "overdue_amount": 0.0,
            "avg_days_overdue": 0,
            "open_signals": 0,
            "promises": [],
        })
        amt = float(inv.get("amount_outstanding") or 0)
        g["invoice_count"] += 1
        g["total_outstanding"] = round(g["total_outstanding"] + amt, 2)
        due = inv.get("due_date")
        if due:
            days = (today - dt.date.fromisoformat(due)).days
            if days > 0:
                g["overdue_amount"] = round(g["overdue_amount"] + amt, 2)
                g["avg_days_overdue"] = max(g["avg_days_overdue"], days)

    for sig in repo.select("signals", where={"resolved": False}):
        name = sig.get("customer_name") or ""
        if not name:
            continue
        g = groups.get(name)
        if not g:
            continue
        g["open_signals"] += 1
        if sig.get("promised_date"):
            status = evaluate_promise(sig, today)
            g["promises"].append({
                "signal_id": sig["id"],
                "promised_date": sig["promised_date"],
                "promised_amount": sig.get("promised_amount"),
                "related_invoice": sig.get("related_invoice", ""),
                "status": status,
                "summary": sig.get("summary", ""),
                "days_overdue": max(0, (today - dt.date.fromisoformat(sig["promised_date"])).days),
            })

    return sorted(groups.values(), key=lambda g: g["overdue_amount"], reverse=True)


@router.get("/promises")
def promise_tracker():
    """All open payment promises with status: how close/far each customer is."""
    today = dt.date.today()
    out = []
    for sig in repo.select("signals", where={"resolved": False, "signal_type": "payment_promise"}):
        status = evaluate_promise(sig, today)
        promised = dt.date.fromisoformat(sig["promised_date"]) if sig.get("promised_date") else None
        out.append({
            "signal_id": sig["id"],
            "customer_name": sig.get("customer_name", ""),
            "customer_email": sig.get("customer_email", ""),
            "promised_date": sig["promised_date"],
            "promised_amount": sig.get("promised_amount"),
            "related_invoice": sig.get("related_invoice", ""),
            "status": status,
            "days_until": (promised - today).days if promised else None,
            "summary": sig.get("summary", ""),
            "confirmation_sent": False,
        })
    out.sort(key=lambda p: (p["status"] != "overdue", p["status"] != "due_today", p.get("days_until") or 10**9))
    return out


@router.get("/overview")
def overview():
    signals = repo.select("signals")
    open_signals = [s for s in signals if not s.get("resolved")]
    by_type = Counter(s.get("signal_type") for s in open_signals)
    by_priority = Counter(s.get("priority") for s in open_signals)
    promises = [s for s in signals if s.get("signal_type") == "payment_promise" and not s.get("resolved")]
    overdue_promises = sum(1 for s in promises if evaluate_promise(s) == "overdue")
    return {
        "total_invoices": len(repo.select("invoices")),
        "total_outstanding": round(sum(float(i.get("amount_outstanding") or 0)
                                       for i in repo.select("invoices")), 2),
        "open_signals": len(open_signals),
        "by_type": dict(by_type),
        "by_priority": dict(by_priority),
        "open_promises": len(promises),
        "overdue_promises": overdue_promises,
        "messages_processed": len(repo.select("messages")),
    }


@router.get("/intelligence/{customer_name}")
def customer_intelligence(customer_name: str):
    """Combined collections intelligence for one customer: behaviour profile,
    the "why act" card, the chase strategy, the why-late explanation, and the
    full collections timeline. Everything is derived from stored facts."""
    invoices = repo.select("invoices", where={"customer_name": customer_name})
    if not invoices:
        raise HTTPException(404, "customer not found in the ledger")
    item = build_action_item(repo, customer_name)
    behavior = payment_behavior(repo, customer_name)
    wl = why_late(repo, item, behavior)
    rdn = invoice_readiness(repo, item)
    pre = pre_due_readiness(repo, item)
    return {
        "customer_name": customer_name,
        "behavior": behavior,
        "collections": collections_intelligence(repo, customer_name, item, behavior),
        "strategy": chase_strategy(repo, item),
        "why_late": wl,
        "readiness": rdn,
        "pre_due": pre,
        "decision_order": decision_order_for(item, rdn, pre, wl["group"]),
        "ownership": ownership_for(item),
        "ar_process": customer_ar_process(repo, customer_name, item, wl, rdn, pre),
        "timeline": collections_timeline(repo, customer_name),
    }


@router.get("/{customer_name}")
def customer_detail(customer_name: str):
    """Full account view: ledger, emails, signals, promises, recommendation,
    and a timeline built from stored facts (invoices + signals)."""
    if "." in customer_name:
        f = _STATIC_OUT / "customers" / customer_name
        if f.is_file():
            return FileResponse(f)
    invoices = repo.select("invoices", where={"customer_name": customer_name})
    if not invoices:
        raise HTTPException(404, "customer not found in the ledger")

    emails = {inv.get("contact_email", "").lower() for inv in invoices if inv.get("contact_email")}
    matches = []
    for m in repo.select("messages", order_by="received_at", desc=True):
        fe = (m.get("from_email") or "").lower()
        if fe in emails:
            matches.append(m)

    signals = repo.select("signals", where={"customer_name": customer_name},
                          order_by="created_at", desc=True)
    actions = build_action_item(repo, customer_name)
    behavior = payment_behavior(repo, customer_name)
    wl = why_late(repo, actions, behavior)
    rdn = invoice_readiness(repo, actions)
    pre = pre_due_readiness(repo, actions)
    today = dt.date.today()

    promises = []
    for s in repo.select("signals",
                         where={"customer_name": customer_name,
                                "resolved": False, "signal_type": "payment_promise"}):
        promises.append({
            "promised_date": s.get("promised_date"),
            "promised_amount": s.get("promised_amount"),
            "status": evaluate_promise(s, today),
            "days_late": max(0, (today - dt.date.fromisoformat(s["promised_date"])).days)
            if s.get("promised_date") else 0,
            "summary": s.get("summary", ""),
            "signal_id": s["id"],
        })

    overdue_amt = sum(float(i.get("amount_outstanding") or 0)
                      for i in invoices
                      if i.get("due_date")
                      and (today - dt.date.fromisoformat(i["due_date"])).days > 0)

    return {
        "customer_name": customer_name,
        "contact_email": invoices[0].get("contact_email", ""),
        "invoice_count": len(invoices),
        "total_outstanding": round(sum(float(i.get("amount_outstanding") or 0) for i in invoices), 2),
        "overdue_amount": round(overdue_amt, 2),
        "max_days_overdue": max(
            ([(today - dt.date.fromisoformat(i["due_date"])).days
              for i in invoices if i.get("due_date")]
             or [0])),
        "invoices": invoices,
        "signals": signals,
        "emails": matches,
        "promises": promises,
        "recommended_action": {k: actions[k] for k in (
            "action", "action_label", "reason", "recommendation_confidence",
            "suggested_follow_up_date", "draft_type", "priority",
            "priority_score", "priority_reasons",
        )},
        "behavior": behavior,
        "collections": collections_intelligence(repo, customer_name, actions, behavior),
        "strategy": chase_strategy(repo, actions),
        "why_late": wl,
        "readiness": rdn,
        "pre_due": pre,
        "decision_order": decision_order_for(actions, rdn, pre, wl["group"]),
        "ownership": ownership_for(actions),
        "ar_process": customer_ar_process(repo, customer_name, actions, wl, rdn, pre),
        "timeline": collections_timeline(repo, customer_name),
    }