"""Follow-up draft generation + sending.

Every draft is built ONLY from facts already in the database (ledger amounts,
invoice numbers, promise dates, the customer's own quoted words). Templates
never invent dollar figures or statements. The result is a *suggested* email
that must be reviewed; V1 never sends without explicit user approval, and even
then only when outgoing email is enabled (AR_ALLOW_SEND=1 + SMTP config).
"""
from __future__ import annotations

import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any

from config import settings
from database import repo

TEMPLATES: dict[str, dict[str, str]] = {
    "friendly_reminder": {
        "subject": "Invoice {invoice} - quick reminder",
        "body": (
            "Hi {first},\n\n"
            "Hope you're doing well. This is a quick reminder that invoice "
            "{invoice_amount} has a due date that has now passed. If it's "
            "already been processed, please disregard this note - and just let "
            "us know if you need anything from us.\n\n"
            "Thanks,\n{sender}"
        ),
    },
    "payment_readiness_confirmation": {
        "subject": "Quick check on invoice {invoice}",
        "body": (
            "Hi {first},\n\n"
            "Quick check on invoice {invoice_amount} - the due date is "
            "coming up. Could you confirm it's been received and is scheduled "
            "for payment? If anything is still needed from us (a PO, approval "
            "details or an invoice copy), just let us know and we'll sort it.\n\n"
            "A quick 'confirmed' reply is all we need. Thanks!\n{sender}"
        ),
    },
    "overdue_reminder": {
        "subject": "Invoice {invoice} - {days} days past due",
        "body": (
            "Hi {first},\n\n"
            "Invoice {invoice_amount} is now {days} day(s) past due. "
            "If payment has already been sent, please reply with the reference "
            "so we can match it on our side. If anything is holding this up, "
            "email us back and we'll sort it out right away.\n\n"
            "Best,\n{sender}"
        ),
    },
    "payment_date_request": {
        "subject": "Re: invoice {invoice} - could you confirm a payment date?",
        "body": (
            "Hi {first},\n\n"
            "Following up on invoice {invoice_amount}, which is now {days} "
            "day(s) past due. {quote}Could you confirm when we can expect "
            "payment? A firm date helps us plan cash flow.\n\n"
            "Thank you,\n{sender}"
        ),
    },
    "missed_promise_followup": {
        "subject": "Payment status for invoice {invoice}",
        "body": (
            "Hi {first},\n\n"
            "You mentioned payment for invoice {invoice_amount} would be sent "
            "{promise}. We don't see it on our side yet. Can you confirm the "
            "status and, if needed, a revised date?\n\n"
            "Thanks,\n{sender}"
        ),
    },
    "missing_invoice_response": {
        "subject": "Resending invoice {invoice}",
        "body": (
            "Hi {first},\n\n"
            "Sorry about that - please find invoice {invoice_amount} attached. "
            "If it still doesn't arrive, let us know and we'll send it another "
            "way.\n\n"
            "Best,\n{sender}"
        ),
    },
    "po_correction_request": {
        "subject": "Re: invoice {invoice} - PO correction",
        "body": (
            "Hi {first},\n\n"
            "Thanks for flagging the PO mismatch on invoice {invoice_amount}. "
            "Could you confirm the correct PO number? We'll update the invoice "
            "and resend it so your team can approve it quickly.\n\n"
            "Thanks,\n{sender}"
        ),
    },
    "dispute_clarification": {
        "subject": "Re: invoice {invoice} - let's get this resolved",
        "body": (
            "Hi {first},\n\n"
            "We'd like to resolve this quickly. On invoice {invoice_amount}, "
            "could you tell us which line item you're disputing? We'll check "
            "against our records and send you the corrected documentation.\n\n"
            "Best,\n{sender}"
        ),
    },
    "approval_pending_followup": {
        "subject": "Re: invoice {invoice} - approval status",
        "body": (
            "Hi {first},\n\n"
            "Thanks for letting us know {quote}invoice {invoice_amount} is "
            "with your team for approval. When it clears, payment should follow "
            "automatically - if you could reply once approved, that helps us "
            "keep our records accurate.\n\n"
            "If anything is still needed from us (a corrected PO, documents or "
            "an updated invoice copy), just say the word.\n\n"
            "Thanks,\n{sender}"
        ),
    },
    "documentation_response": {
        "subject": "Re: invoice {invoice} - documents for your AP team",
        "body": (
            "Hi {first},\n\n"
            "Thanks for the note. We're preparing the documents you requested "
            "for invoice {invoice_amount}. We'll send them shortly so your AP "
            "team can process the payment.\n\n"
            "Thanks,\n{sender}"
        ),
    },
    "escalation_notice": {
        "subject": "Invoice {invoice} - final follow-up",
        "body": (
            "Hi {first},\n\n"
            "This is a final follow-up regarding invoice {invoice_amount}, now "
            "{days} day(s) past due. We need a firm payment date or a cleared "
            "payment reference by {date}. If there's an issue, please reply "
            "now so we can resolve it before this gets escalated.\n\n"
            "Regards,\n{sender}"
        ),
    },
}


def _amount(inv: dict | None) -> str:
    if not inv:
        return ""
    amount = float(inv.get("amount_outstanding") or 0)
    if amount <= 0:
        return ""
    return f"({invoice_ref(inv)} for ${amount:,.2f})" if invoice_ref(inv) else f"(for ${amount:,.2f})"


def invoice_ref(inv: dict | None) -> str:
    if not inv:
        return ""
    return str(inv.get("invoice_number") or "").strip()


def build_draft(item: dict[str, Any]) -> dict[str, Any]:
    """Generate subject + body for an action item.

    item is the output of next_action_engine.build_action_item. Only known
    facts are inserted; missing facts remove the sentence part instead of
    guessing.
    """
    draft_type = item.get("draft_type") or "overdue_reminder"

    if item.get("draft_type") in (None, "", "none"):
        return {
            "draft_type": "none",
            "subject": "",
            "body": "",
            "note": (
                "No email is needed for this action. "
                + (item.get("action_label") or "")
            ),
        }

    tpl = TEMPLATES.get(draft_type, TEMPLATES["overdue_reminder"])
    first = item.get("customer_first") or "there"
    inv = item.get("primary_invoice_number") or ""
    days = item.get("max_days_overdue") or 0
    promise = None
    p = item.get("promise")
    if p and p.get("promised_date"):
        promise = f"by {p['promised_date']}"
    quote = ""
    if draft_type != "approval_pending_followup":
        sig = item.get("latest_signal")
        if sig and sig.get("summary"):
            s = sig["summary"].strip().rstrip(".")
            quote = f'You mentioned: "{s}." '

    lines = {
        "first": first,
        "invoice": inv or "your invoice",
        "invoice_amount": _amount({"invoice_number": inv, "amount_outstanding": item.get("overdue_amount") or item.get("total_outstanding")}),
        "days": days,
        "promise": promise or "",
        "date": item.get("suggested_follow_up_date") or "",
        "quote": quote,
        "sender": settings.sender_name,
    }
    subject = tpl["subject"].format(**lines)
    body = tpl["body"].format(**lines).replace("\n\n\n", "\n\n")

    # keep quotes to one line and tidy empty-parenthesis artifacts
    body = body.replace(" ()", "").replace("{invoice_amount}", "")

    return {
        "draft_type": draft_type,
        "subject": subject,
        "body": body,
        "note": (
            "AI-suggested draft. Facts come from your ledger and the customer's "
            "own email; amounts and quotes are never invented. Review before sending."
        ),
    }


def _recipient(item: dict[str, Any]) -> str | None:
    em = item.get("customer_email")
    return (em or "").strip() or None


def send_approved(followup: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    """Actually send - ONLY reached after explicit user approval. Records result."""
    recipient = _recipient(item)
    if not settings.allow_send or not settings.smtp_host:
        repo.update("followups", followup["id"], {"status": "approved"})
        return {
            "approved": True,
            "sent": False,
            "message": (
                "Approval recorded. Outgoing email is not enabled on this "
                "workspace yet, so nothing was sent."
            ),
        }
    if not recipient:
        return {
            "approved": False,
            "sent": False,
            "message": "No validated sender email for this customer - cannot send.",
        }
    msg = MIMEText(followup["body"], "plain", "utf-8")
    msg["Subject"] = followup["subject"]
    msg["From"] = formataddr((settings.sender_name, settings.sender_email))
    msg["To"] = recipient
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as s:
            s.starttls()
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
        repo.update("followups", followup["id"],
                    {"status": "sent", "sent_at": _now(), "recipient": recipient})
        return {"approved": True, "sent": True, "message": "Email sent.",
                "recipient": recipient}
    except Exception as exc:  # noqa: BLE001
        repo.update("followups", followup["id"], {"status": "approved"})
        return {"approved": True, "sent": False,
                "message": f"Send failed: {exc}. Approval kept, nothing sent."}


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()