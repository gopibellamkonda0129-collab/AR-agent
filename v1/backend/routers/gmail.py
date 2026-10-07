"""Gmail OAuth connection flow.

GET /gmail/start                    -> { auth_url, state }
GET /gmail/callback?code&state      -> exchanges the code, stores the token on
                                       the account, redirects to the dashboard.

Requires a Google Cloud project with the Gmail API enabled and an OAuth
"Desktop" client secret; point GMAIL_CLIENT_SECRET at it.
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from config import settings
from database import repo

router = APIRouter(prefix="/gmail", tags=["gmail"])

_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
# state -> { email, display_name, flow_opts } for pending authorizations
_PENDING: dict[str, dict] = {}


def _flow(state: str, redirect_uri: str):
    from google_auth_oauthlib.flow import InstalledAppFlow

    return InstalledAppFlow.from_client_secrets_file(
        settings.gmail_credentials_file, _SCOPES,
        redirect_uri=redirect_uri, state=state,
    )


@router.get("/start")
def gmail_start(email: str = Query("", description="account email"),
                display_name: str = ""):
    if not settings.gmail_credentials_file or not _secret_exists():
        raise HTTPException(400, "GMAIL_CLIENT_SECRET not configured on the server")
    state = uuid.uuid4().hex
    redirect_uri = settings.base_url.rstrip("/") + "/gmail/callback"
    flow = _flow(state, redirect_uri)
    auth_url, _ = flow.authorization_url(prompt="consent")
    _PENDING[state] = {
        "email": email,
        "display_name": display_name or email,
        "redirect_uri": redirect_uri,
    }
    return {"auth_url": auth_url, "state": state}


@router.get("/callback")
def gmail_callback(code: str, state: str, error: str | None = None):
    pending = _PENDING.pop(state, None)
    if error or not pending:
        raise HTTPException(400, f"Gmail authorization failed: {error or 'state expired'}")
    try:
        flow = _flow(state, pending["redirect_uri"])
        flow.fetch_token(code=code)
        creds = flow.credentials
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Token exchange failed - please try connecting again") from None

    email = pending["email"] or "me"
    account = repo.insert("email_accounts", [{
        "provider": "gmail",
        "email": email,
        "display_name": pending["display_name"] or email,
        "provider_config": {
            "credentials_file": settings.gmail_credentials_file,
            "gmail_token": creds.to_json(),
        },
        "status": "connected",
    }])[0]
    details = {
        "email": email, "display_name": pending["display_name"],
        "token_expiry": (creds.expiry.isoformat() if creds.expiry else None),
    }
    repo.update("email_accounts", account["id"], {
        "provider_config": {**account["provider_config"],
                            "gmail_token": creds.to_json(),
                            "account_details": json.dumps(details)},
    })
    return RedirectResponse(settings.base_url.rstrip("/") + "/")


def _secret_exists() -> bool:
    import os

    return os.path.exists(settings.gmail_credentials_file)