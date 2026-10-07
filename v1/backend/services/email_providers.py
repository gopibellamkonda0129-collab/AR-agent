"""Email provider adapters: Gmail API (production OAuth) and IMAP (local/demo).

Each provider fetches raw emails and yields normalized EmailRecord dicts the
sync service stores in the database.
"""
from __future__ import annotations

import email as email_lib
import imaplib
from email.header import decode_header
from email.utils import parsedate_to_datetime

from models import EmailRecord


class BaseProvider:
    provider: str = "base"

    def fetch(self, since_days: int = 60) -> list[dict]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# IMAP (works with Gmail app passwords locally; production fallback)
# ---------------------------------------------------------------------------

class ImapProvider(BaseProvider):
    provider = "imap"

    def __init__(self, config: dict):
        self.host = config.get("host", "imap.gmail.com")
        self.user = config["email"] or config.get("username", "")
        self.password = config.get("password", config.get("app_password", ""))
        self.port = int(config.get("port", 993))
        self.folder = config.get("folder", "INBOX")

    def fetch(self, since_days: int = 60) -> list[dict]:
        import datetime as dt
        from email.utils import formatdate

        conn = imaplib.IMAP4_SSL(self.host, self.port)
        try:
            conn.login(self.user, self.password)
            conn.select(self.folder)
            since = formatdate((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=since_days)).timestamp(), localtime=False)
            typ, data = conn.search(None, f'(SINCE "{since}" UNSEEN)')
            ids = (data[0] or b"").split()
            out = []
            for mid in ids:
                typ, msg_data = conn.fetch(mid, "(RFC822)")
                if not msg_data or msg_data[0] is None:
                    continue
                raw = msg_data[0][1]
                out.append(_parse_raw_email(raw, self.user))
            return out
        finally:
            try:
                conn.logout()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Gmail API (OAuth). Needs google-api-python-client + a client_secret file.
# Tokens can come from the /gmail/start OAuth flow (stored in provider_config)
# or from a previously saved token_file.
# ---------------------------------------------------------------------------

class GmailProvider(BaseProvider):
    provider = "gmail"

    def __init__(self, config: dict):
        self.credentials_file = config.get("credentials_file", "")
        self.token_file = config.get("token_file", "gmail_token.json")
        self.token = config.get("gmail_token")  # saved Credentials.to_json()
        self.user = config.get("email", "")

    def _service(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
        creds = None
        if self.token:
            import json

            creds = Credentials.from_authorized_user_info(
                json.loads(self.token), scopes
            )
        else:
            try:
                creds = Credentials.from_authorized_user_file(self.token_file, scopes)
            except Exception:
                creds = None
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                self._save_token(creds.to_json())
            else:
                raise RuntimeError(
                    "Gmail not authorized. Run the OAuth flow (Connect inbox -> Gmail)."
                )
        return build("gmail", "v1", credentials=creds)

    def _save_token(self, token_json: str) -> None:
        self.token = token_json
        if self.token_file:
            try:
                with open(self.token_file, "w") as f:
                    f.write(token_json)
            except Exception:
                pass

    def fetch(self, since_days: int = 60) -> list[dict]:
        import base64
        import datetime as dt

        service = self._service()
        q = f"newer_than:{since_days}d"
        resp = service.users().messages().list(userId="me", q=q, maxResults=250).execute()
        out = []
        for msg in resp.get("messages", []):
            full = service.users().messages().get(userId="me", id=msg["id"], format="raw").execute()
            raw_bytes = base64.urlsafe_b64decode(full["raw"])
            rec = _parse_raw_email(raw_bytes, self.user)
            rec["message_id"] = full.get("id", "")
            out.append(rec)
        return out


# ---------------------------------------------------------------------------
# shared raw -> record parsing
# ---------------------------------------------------------------------------

def _decode(s: str | None) -> str:
    if not s:
        return ""
    parts: list[str] = []
    for text, enc in decode_header(s):
        try:
            if isinstance(text, bytes):
                text = text.decode(enc or "utf-8", errors="replace")
            parts.append(str(text))
        except Exception:
            parts.append(str(text))
    return " ".join(p for p in parts if p)


def _parse_raw_email(raw: bytes, account_email: str) -> dict:
    msg = email_lib.message_from_bytes(raw)
    subject = _decode(msg.get("Subject"))
    from_hdr = _decode(msg.get("From"))
    from_email = _extract_email(from_hdr)
    from_name = from_hdr.replace(f"<{from_email}>", "").strip(" <>\"") if from_email else from_hdr
    body = _extract_body(msg)
    received = parsedate_to_datetime(msg.get("Date"))
    if received and received.tzinfo is None:
        received = received.astimezone()
    return EmailRecord(
        subject=subject,
        body=body,
        from_email=from_email or account_email,
        from_name=from_name[:80],
        message_id=msg.get("Message-ID", ""),
        thread_id=msg.get("In-Reply-To", "") or msg.get("Message-ID", ""),
        received_at=received or None,
    ).model_dump()


def _extract_email(addr: str) -> str:
    import re

    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", addr)
    return m.group(0) if m else ""


def _extract_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")[:20000]
                except Exception:
                    continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload is None:
                payload = (msg.get_payload() or "").encode()
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")[:20000]
        except Exception:
            return str(msg.get_payload())[:20000]
    return ""


def get_provider(account: dict) -> BaseProvider:
    provider = account.get("provider", "imap")
    config = account.get("provider_config", {}) or {}
    if provider == "gmail":
        return GmailProvider(config)
    if provider == "outlook":
        # Outlook IMAP works fine through the IMAP provider
        cfg = dict(config)
        cfg.setdefault("host", "outlook.office365.com")
        cfg.setdefault("port", 993)
        return ImapProvider(cfg)
    return ImapProvider(config)