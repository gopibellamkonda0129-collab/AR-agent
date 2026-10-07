"""Your real invoices: list, import (upload), clear, mark paid + money recovered."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from database import repo
from services.cash_risk import cash_risk_view
from services.invoice_import import clear_invoices, import_file_bytes
from services.process_status import invoice_lifecycle, invoice_process_status
from services.readiness import invoice_send_readiness, payment_readiness_score
from services.reminder_safety import reminder_safety

router = APIRouter(prefix="/invoices", tags=["invoices"])


class MarkPaid(BaseModel):
    """Record a real payment for an invoice (feeds Money Recovered)."""
    paid_at: str | None = None        # ISO date; defaults to today
    amount: float | None = None        # partial payments allowed; defaults to outstanding
    note: str = ""


@router.get("")
def list_invoices(limit: int = 500):
    invoices = repo.select("invoices", order_by="due_date", desc=True, limit=limit)
    for inv in invoices:
        ps = invoice_process_status(repo, inv)
        inv["process_status"] = ps
        lc = invoice_lifecycle(repo, inv, status=ps)
        inv["lifecycle"] = {
            "current_stage": lc.get("current_stage"),
            "current_stage_label": lc.get("current_stage_label"),
            "progress": lc.get("progress"),
            "terminal": lc.get("terminal"),
        }
        rd = invoice_send_readiness(repo, inv)
        inv["readiness_summary"] = {
            "verdict": rd.get("verdict"),
            "verdict_label": rd.get("verdict_label"),
            "passed": rd.get("passed"),
            "blockers": rd.get("blockers"),
        }
    total = sum(float(i.get("amount_outstanding") or 0) for i in invoices)
    return {
        "count": len(invoices),
        "total_outstanding": round(total, 2),
        "invoices": invoices,
    }


@router.get("/cash-at-risk")
def cash_at_risk(sort: str = "weight"):
    """Invoice-level cash exposure, separate from the customer risk score.

    Additive signal: outstanding balance x days overdue + what's holding the
    billing process up. The existing collections_intelligence.risk_score is
    untouched. `sort` switches between amount×days (weight) and the action
    engine's order (agent) - two lenses, neither claimed as superior.
    """
    if sort not in ("weight", "agent"):
        raise HTTPException(400, 'sort must be "weight" or "agent"')
    return cash_risk_view(repo, sort=sort)


@router.post("/import")
async def import_invoices(files: list[UploadFile] = File(...)):
    results = []
    for f in files:
        data = await f.read()
        try:
            results.append(import_file_bytes(f.filename or "upload", data))
        except Exception:  # noqa: BLE001
            fname = f.filename or "the uploaded file"
            results.append({"imported": 0, "skipped": 0,
                            "warnings": [f"{fname} could not be imported - "
                                         "the file format appears invalid."]})
    by_customer: set[str] = set()
    total_imported = sum(r["imported"] for r in results)
    warnings: list[str] = []
    for r in results:
        by_customer.update(r.get("customers", []))
        warnings.extend(r.get("warnings", []))
    return {
        "imported": total_imported,
        "files": len(files),
        "customers": sorted(by_customer),
        "warnings": warnings,
    }


@router.post("/clear")
def clear():
    """Remove all invoices (your data, not demo) - irreversible."""
    return clear_invoices()


@router.post("/{invoice_id}/mark-paid")
def mark_paid(invoice_id: str, body: MarkPaid | None = None):
    """Record a payment against an invoice and mark it paid.

    This is the ONLY source of "Money Recovered" - it never invents data.
    Supports partial payments; an invoice with zero outstanding is marked paid.
    """
    body = body or MarkPaid()
    rows = repo.select("invoices", where={"id": invoice_id})
    if not rows:
        raise HTTPException(404, "invoice not found")
    inv = rows[0]
    outstanding = float(inv.get("amount_outstanding") or 0)
    amount = outstanding if body.amount is None else float(body.amount)
    if amount <= 0:
        raise HTTPException(400, "payment amount must be positive")
    if amount > outstanding + 0.005:
        raise HTTPException(400, f"amount exceeds outstanding balance ({outstanding:,.2f})")

    paid_at = body.paid_at or dt.date.today().isoformat()
    repo.insert("payments", [{
        "invoice_id": inv["id"],
        "invoice_number": inv.get("invoice_number", ""),
        "customer_name": inv.get("customer_name", ""),
        "amount": round(amount, 2),
        "paid_at": paid_at,
        "note": body.note,
    }])

    remaining = round(outstanding - amount, 2)
    if remaining <= 0.005:
        new_status = "paid"
        repo.update("invoices", invoice_id,
                    {"amount_outstanding": 0.0, "status": "paid",
                     "expected_payment_date": None})
    else:
        new_status = "open"
        repo.update("invoices", invoice_id,
                    {"amount_outstanding": remaining, "status": "open",
                     "expected_payment_date": None})
    return {"ok": True, "status": new_status, "paid": round(amount, 2),
            "remaining": remaining}


@router.get("/payments")
def list_payments():
    """All recorded payments (Money Recovered) - the basis for the metric."""
    return repo.select("payments", order_by="paid_at", desc=True)


@router.get("/{invoice_id}/action-panel")
def invoice_action_panel(invoice_id: str):
    """One invoice's full action panel: lifecycle + send readiness +
    reminder-safety verdict + payment-readiness score + recommended next step
    and control flags. Everything comes from stored facts.
    """
    rows = repo.select("invoices", where={"id": invoice_id})
    if not rows:
        raise HTTPException(404, "invoice not found")
    inv = rows[0]
    num = str(inv.get("invoice_number") or "")
    name = str(inv.get("customer_name") or "")

    ps = invoice_process_status(repo, inv)
    lifecycle = invoice_lifecycle(repo, inv, status=ps)
    readiness = invoice_send_readiness(repo, inv)

    from services.behavior import enrich_action_item
    from services.next_action_engine import build_action_item
    item = enrich_action_item(repo, build_action_item(repo, name))

    safety = reminder_safety(repo, item)
    score = payment_readiness_score(repo, item)

    q = repo.select("actions_queue", where={"customer_name": name}, limit=1)
    qstate = q[0] if q else {}

    from services.behavior import exception_group_for
    group, group_label = exception_group_for(item)

    return {
        "invoice_number": num,
        "customer_name": name,
        "amount_outstanding": float(inv.get("amount_outstanding") or 0),
        "due_date": inv.get("due_date"),
        "invoice_date": inv.get("invoice_date"),
        "process_status": ps,
        "lifecycle": lifecycle,
        "readiness": readiness,
        "reminder_safety": safety,
        "payment_readiness_score": score,
        "recommended_action": {
            "action": item.get("action"),
            "action_label": item.get("action_label"),
            "reason": item.get("reason"),
            "confidence": item.get("recommendation_confidence"),
            "priority": item.get("priority"),
            "draft_type": item.get("draft_type"),
            "exception_group": group,
            "exception_label": group_label,
            "owner": (item.get("ownership") or {}).get("owner") or "",
            "chase_stage": (item.get("chase") or {}).get("stage_label"),
            "suggested_follow_up": item.get("suggested_follow_up_date"),
        },
        "control": {
            "primary_invoice_id": inv.get("id"),
            "paused": bool(qstate.get("paused")),
            "paused_until": qstate.get("paused_until"),
            "paused_reason": qstate.get("paused_reason", ""),
            "next_action_override": qstate.get("next_action_override", ""),
            "owner_override": qstate.get("owner_override", ""),
            "snoozed_until": qstate.get("snoozed_until"),
            "status": qstate.get("status", "active"),
        },
    }