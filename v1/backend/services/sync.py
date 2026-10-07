"""Pull emails -> analyze -> store signals for one account."""
from __future__ import annotations

import datetime as dt
from typing import Any

from config import settings
from database import repo
from demo.seed import demo_emails
from services import analyzer, matcher

_PROVIDER_FACTORY: dict[str, Any] = {}


def _messages_for(account: dict) -> list[dict]:
    if account.get("provider") == "demo":
        msgs, _ = demo_emails()
        return msgs
    from services.email_providers import get_provider

    provider = get_provider(account)
    return provider.fetch(since_days=90)


def sync_account(account: dict) -> dict:
    messages = _messages_for(account)
    account_id = account["id"]
    use_llm = bool(settings.openai_api_key)

    existing_ids = {
        m["message_id"]
        for m in repo.select("messages", {"account_id": account_id}, order_by="received_at")
        if m.get("message_id")
    }

    fetched = 0
    new_emails = 0
    new_signals = 0
    for m in messages:
        fetched += 1
        mid = (m.get("message_id") or "").strip()
        if mid and mid in existing_ids:
            continue
        new_emails += 1
        row = dict(m)
        row["account_id"] = account_id
        row["analyzed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        if mid:
            existing_ids.add(mid)
        repo.insert("messages", [{k: v for k, v in row.items() if k not in ("account",)}])

        sig = analyzer.analyze_email(row.get("subject", ""), row.get("body", ""), use_llm)
        customer = matcher.match_customer(
            row.get("from_email", ""), row.get("from_name", ""), repo,
            body=row.get("body", ""),
        )

        signal = {
            "account_id": account_id,
            "message_id": row.get("message_id"),
            "from_email": row.get("from_email", ""),
            "customer_name": customer.get("customer_name", ""),
            "customer_email": customer.get("contact_email", ""),
            "signal_type": sig["signal_type"],
            "priority": sig["priority"],
            "confidence": sig["confidence"],
            "summary": sig["summary"],
            "related_invoice": sig.get("related_invoice", ""),
            "promised_date": sig.get("promised_date"),
            "promised_amount": sig.get("promised_amount"),
            "resolved": False,
            "resolution_note": "",
        }
        if signal["signal_type"] != "other":
            repo.insert("signals", [signal])
            new_signals += 1

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    repo.update("email_accounts", account_id, {
        "last_sync_at": now,
        "last_sync_fetched": fetched,
        "last_sync_new_emails": new_emails,
        "last_sync_new_signals": new_signals,
        "last_sync_status": "ok",
    })

    return {
        "account_id": account_id,
        "fetched": fetched,
        "analyzed": len(messages),
        "new_emails": new_emails,
        "new_signals": new_signals,
        "last_sync_at": now,
    }


def evaluate_promise(sig: dict, today: dt.date | None = None) -> str:
    """Status of a payment promise relative to today for the tracker UI."""
    today = today or dt.date.today()
    promised = sig.get("promised_date")
    if not promised:
        return "no_date"
    promised_date = dt.date.fromisoformat(promised)
    if promised_date < today:
        return "overdue"
    if promised_date == today:
        return "due_today"
    return "upcoming"