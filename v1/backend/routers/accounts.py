"""Accounts: connect an inbox and sync emails into signals."""
from __future__ import annotations

import imaplib
import socket

from fastapi import APIRouter, HTTPException

from database import repo
from models import ConnectRequest
from services.sync import sync_account

router = APIRouter(prefix="/accounts", tags=["accounts"])

_SECRET_KEYS = ("password", "token", "secret")


def _safe_account(account: dict) -> dict:
    """Mask stored secrets (IMAP app password, Gmail OAuth token) before the
    account ever leaves the API. Credentials stay in storage for syncing but
    are never shipped to the browser."""
    out = dict(account)
    cfg = dict(out.get("provider_config") or {})
    for k in list(cfg):
        if any(s in k.lower() for s in _SECRET_KEYS):
            cfg[k] = "***"
    out["provider_config"] = cfg
    return out


def _test_imap(config: dict) -> str | None:
    """Return an error string if the IMAP credentials can't authenticate."""
    host = config.get("host", "imap.gmail.com")
    email = config.get("email", "")
    password = config.get("password", "")
    port = int(config.get("port", 993))
    if not email or not password:
        return "email and password are required for IMAP"
    try:
        conn = imaplib.IMAP4_SSL(host, port, timeout=max(8.0, socket.getdefaulttimeout()))
        try:
            conn.login(email, password)
            status, _ = conn.select("INBOX")
            if status != "OK":
                return "could not open INBOX"
        finally:
            try:
                conn.logout()
            except Exception:
                pass
    except imaplib.IMAP4.error:
        return ("login rejected - check that the app password is correct "
                "and IMAP is enabled for this account")
    except Exception:  # noqa: BLE001
        return "could not connect to the mail server - check the host and port"
    return None


@router.get("")
def list_accounts():
    return [_safe_account(a) for a in repo.select("email_accounts", order_by="created_at", desc=False)]


@router.post("")
def connect(req: ConnectRequest):
    config = req.config
    if req.provider in ("imap", "outlook"):
        err = _test_imap(config)
        if err:
            raise HTTPException(400, err)
        if req.provider == "outlook":
            config = {**config, "host": config.get("host", "outlook.office365.com"),
                      "port": int(config.get("port", 993))}
    account = repo.insert("email_accounts", [
        {
            "provider": req.provider,
            "email": req.email,
            "display_name": req.display_name or req.email,
            "provider_config": config,
            "status": "connected",
        }
    ])[0]
    return _safe_account(account)


@router.post("/{account_id}/sync")
def sync(account_id: str):
    accounts = repo.select("email_accounts", where={"id": account_id})
    if not accounts:
        raise HTTPException(404, "account not found")
    return sync_account(accounts[0])


@router.delete("/{account_id}")
def remove(account_id: str):
    repo.delete("email_accounts", account_id)
    return {"ok": True}