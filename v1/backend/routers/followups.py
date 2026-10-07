"""AI follow-up composer: draft, edit, approve & send (human-gated), copy, discard.

Outgoing email is OFF by default. Even with AR_ALLOW_SEND=1 every send still
requires the explicit /approve-send call from the UI (a two-click confirm).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from database import repo
from models import FollowUpApprove, FollowUpSave
from services.followups import build_draft, send_approved
from services.next_action_engine import build_action_item

router = APIRouter(prefix="/followups", tags=["followups"])


@router.get("")
def list_followups(limit: int = 100):
    return repo.select("followups", order_by="created_at", desc=True, limit=limit)


@router.get("/{customer}")
def get_followup(customer: str, draft: bool = True):
    """Return the existing draft for a customer, or generate one.

    Generating is a pure function of DB facts; it never invents numbers.
    """
    existing = repo.select("followups", where={"customer_name": customer},
                           order_by="created_at", desc=True, limit=1)
    if existing and existing[0].get("status") not in ("discarded", "sent"):
        row = _clean(existing[0])
        row["current"] = True
        return row
    if not draft:
        raise HTTPException(404, "no follow-up yet")
    item = build_action_item(repo, customer)
    d = build_draft(item)
    row = repo.insert("followups", [{
        "customer_name": customer,
        "draft_type": d["draft_type"],
        "subject": d["subject"],
        "body": d["body"],
        "status": "draft" if d["draft_type"] != "none" else "no_email",
        "context": _ctx(item),
    }])[0]
    row["current"] = True
    return _clean(row)


def _ctx(item: dict) -> dict:
    latest = item.get("latest_signal") or {}
    return {
        "customer_name": item["customer_name"],
        "customer_email": item["customer_email"],
        "overdue_amount": item["overdue_amount"],
        "max_days_overdue": item["max_days_overdue"],
        "action_label": item["action_label"],
        "reason": item["reason"],
        "priority": item["priority"],
        "priority_reasons": item.get("priority_reasons", []),
        "recommendation_confidence": item.get("recommendation_confidence"),
        "suggested_follow_up_date": item.get("suggested_follow_up_date"),
        "draft_type": item.get("draft_type"),
        "promise": item.get("promise") or None,
        "latest_signal": {
            "signal_type": latest.get("signal_type", ""),
            "summary": latest.get("summary", ""),
            "priority": latest.get("priority", ""),
            "source_email": latest.get("source_email") or {},
            "source_email_body": latest.get("source_email_body", ""),
        },
    }


def _clean(row: dict) -> dict:
    out = {k: v for k, v in row.items() if k != "context"}
    out["current"] = bool(row.get("current"))
    out["context"] = row.get("context", {})
    return out


@router.post("/{customer}")
def save_followup(customer: str, body: FollowUpSave):
    """Save an edited draft (explicit user wording, kept verbatim).

    A discarded draft can be replaced by a fresh one; an already-SENT email
    cannot be overwritten (it went out under approval).
    """
    prev = repo.select("followups", where={"customer_name": customer},
                       order_by="created_at", desc=True, limit=1)
    prev_type = prev[0].get("draft_type") if prev else "overdue_reminder"
    if prev and prev[0].get("status") == "sent":
        raise HTTPException(400, "this follow-up was already sent")
    item = build_action_item(repo, customer)
    row = repo.insert("followups", [{
        "customer_name": customer,
        "draft_type": body.draft_type or prev_type,
        "subject": body.subject,
        "body": body.body,
        "status": "edited",
        "context": _ctx(item),
    }])[0]
    return _clean(row)


@router.post("/{followup_id}/approve-send")
def approve_send(followup_id: str, body: FollowUpApprove):
    """Record explicit human approval; send only if that is enabled."""
    rows = repo.select("followups", where={"id": followup_id})
    if not rows:
        raise HTTPException(404, "follow-up not found")
    followup = rows[0]
    item = build_action_item(repo, followup["customer_name"])
    result = send_approved(followup, item)
    if body.send is False:
        repo.update("followups", followup_id, {"status": "approved"})
        return {"approved": True, "sent": False,
                "message": "Approval recorded. Nothing sent (send flag false)."}
    return result


@router.post("/{followup_id}/copy")
def copy_followup(followup_id: str):
    rows = repo.select("followups", where={"id": followup_id})
    if not rows:
        raise HTTPException(404, "follow-up not found")
    repo.update("followups", followup_id, {"status": "copied"})
    return {"status": "copied"}


@router.post("/{followup_id}/discard")
def discard_followup(followup_id: str):
    rows = repo.select("followups", where={"id": followup_id})
    if not rows:
        raise HTTPException(404, "follow-up not found")
    repo.update("followups", followup_id, {"status": "discarded"})
    return {"status": "discarded"}