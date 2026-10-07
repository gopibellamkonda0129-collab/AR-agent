"""Signals: the discovered intents (promises, disputes, bounces, ...)."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException

from database import repo
from models import SignalResolve

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("")
def list_signals(resolved: bool | None = None, type: str | None = None,
                 limit: int = 200):
    where = {}
    if resolved is not None:
        where["resolved"] = resolved
    if type:
        where["signal_type"] = type
    return repo.select("signals", where=where, order_by="created_at", desc=True, limit=limit)


@router.post("/{signal_id}/resolve")
def resolve_signal(signal_id: str, body: SignalResolve):
    rows = repo.select("signals", where={"id": signal_id})
    if not rows:
        raise HTTPException(404, "signal not found")
    repo.update("signals", signal_id, {
        "resolved": body.resolved,
        "resolution_note": body.note or "",
        "resolved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    })
    return repo.select("signals", where={"id": signal_id})[0]