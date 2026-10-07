"""Raw inbound messages."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from database import repo

router = APIRouter(prefix="/emails", tags=["emails"])


@router.get("/messages")
def list_messages(account_id: str | None = None, limit: int = 100):
    where = {"account_id": account_id} if account_id else None
    return repo.select("messages", where=where, order_by="received_at", desc=True, limit=limit)


@router.get("/messages/{message_id}")
def get_message(message_id: str):
    rows = repo.select("messages", where={"id": message_id})
    if not rows:
        raise HTTPException(404, "message not found")
    return rows[0]