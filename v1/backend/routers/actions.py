"""ACTION REQUIRED queue - the primary worklist.

GET /actions returns "who should I chase today" with an explainable priority,
recommended next action and reasons. POST endpoints record how the team handled
an account (Mark Contacted / Snooze) - state that survives the next refresh.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException

from database import repo
from models import MarkContacted, NextActionRequest, OwnerRequest, PauseRequest, SnoozeRequest
from services.next_action_engine import build_queue

router = APIRouter(prefix="/actions", tags=["actions"])


@router.get("")
def action_queue():
    return build_queue(repo)


def _get_state(customer: str) -> dict | None:
    rows = repo.select("actions_queue", where={"customer_name": customer}, limit=1)
    return rows[0] if rows else None


def _ensure_state(customer: str) -> dict:
    st = _get_state(customer)
    if not st:
        st = repo.insert("actions_queue", [{
            "customer_name": customer,
            "status": "active",
            "note": "",
        }])[0]
    return st


@router.post("/{customer}/contacted")
def mark_contacted(customer: str, body: MarkContacted):
    st = _ensure_state(customer)
    repo.update("actions_queue", st["id"], {
        "status": "contacted",
        "contacted_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "note": body.note,
    })
    return {"customer": customer, "status": "contacted"}


@router.post("/{customer}/snooze")
def snooze(customer: str, body: SnoozeRequest):
    try:
        dt.date.fromisoformat(body.until)
    except ValueError:
        raise HTTPException(400, "until must be an ISO date (YYYY-MM-DD)")
    st = _ensure_state(customer)
    repo.update("actions_queue", st["id"], {
        "status": "snoozed",
        "snoozed_until": body.until,
    })
    return {"customer": customer, "status": "snoozed", "until": body.until}


@router.post("/{customer}/owner")
def set_owner(customer: str, body: OwnerRequest):
    """Manually assign the account owner for this customer.

    Overrides the engine's action-based owner until cleared (owner=""). The
    override is surfaced on queue items with ownership.manual = true.
    """
    owner = (body.owner or "").strip()
    st = _ensure_state(customer)
    repo.update("actions_queue", st["id"], {"owner_override": owner})
    return {"customer": customer, "owner": owner,
            "manual": bool(owner), "status": "ok"}


@router.post("/{customer}/reactivate")
def reactivate(customer: str):
    st = _ensure_state(customer)
    repo.update("actions_queue", st["id"], {"status": "active", "snoozed_until": None})
    return {"customer": customer, "status": "active"}


# ---------------------------------------------------------------------------
# Follow-up Control Center: pause / resume / cancel-chase / next-action override
# ---------------------------------------------------------------------------

@router.post("/{customer}/pause")
def pause(customer: str, body: PauseRequest):
    """Pause chasing for a customer until a date (or indefinitely).

    Paused customers leave the Action Queue (like snoozed) and appear in the
    `paused` list with the reason. A date in the past/empty-means-indefinite.
    """
    until = (body.until or "").strip()
    if until:
        try:
            dt.date.fromisoformat(until)
        except ValueError:
            raise HTTPException(400, "until must be an ISO date (YYYY-MM-DD)")
    st = _ensure_state(customer)
    repo.update("actions_queue", st["id"], {
        "paused": True,
        "paused_until": until or None,
        "paused_reason": body.reason.strip(),
    })
    return {"customer": customer, "paused": True, "until": until or None,
            "reason": body.reason.strip()}


@router.post("/{customer}/resume")
def resume(customer: str):
    st = _ensure_state(customer)
    repo.update("actions_queue", st["id"], {
        "paused": False,
        "paused_until": None,
        "paused_reason": "",
    })
    return {"customer": customer, "paused": False, "status": "ok"}


@router.post("/{customer}/cancel-chase")
def cancel_chase(customer: str, body: PauseRequest):
    """Cancel the scheduled chase for this customer (recorded as a pause)."""
    st = _ensure_state(customer)
    repo.update("actions_queue", st["id"], {
        "paused": True,
        "paused_until": None,
        "paused_reason": (body.reason or "Chase cancelled by the team").strip(),
    })
    return {"customer": customer, "paused": True, "cancelled": True,
            "reason": (body.reason or "Chase cancelled by the team").strip()}


@router.post("/{customer}/next-action")
def set_next_action(customer: str, body: NextActionRequest):
    """Override the recommended next action (team decision, shown as manual)."""
    action = (body.action or "").strip()
    st = _ensure_state(customer)
    repo.update("actions_queue", st["id"], {"next_action_override": action})
    return {"customer": customer, "action": action,
            "manual": bool(action), "status": "ok"}


@router.get("/paused")
def paused_customers():
    """Customers currently paused in the follow-up control center."""
    out = []
    today = dt.datetime.now(dt.timezone.utc)
    for c in repo.select("invoices"):
        name = c.get("customer_name")
        if not name or any(o.get("customer_name") == name for o in out):
            continue
        rows = repo.select("actions_queue", where={"customer_name": name}, limit=1)
        if rows and rows[0].get("paused"):
            st = rows[0]
            unt = st.get("paused_until")
            if unt:
                try:
                    if dt.date.fromisoformat(str(unt)) <= today.date():
                        continue
                except ValueError:
                    continue
            out.append({"customer_name": name, "paused_until": unt,
                        "paused_reason": st.get("paused_reason", "")})
    out.sort(key=lambda c: c["customer_name"].lower())
    return {"paused": out, "count": len(out)}