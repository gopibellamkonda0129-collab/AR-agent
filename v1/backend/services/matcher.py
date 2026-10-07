"""Match an inbound sender to a known AR customer and their open invoices."""
from __future__ import annotations

import re
from typing import Any

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
# Return-path senders of delivery-failure notifications; never real customers,
# so when one of these arrives we fall back to searching the message body.
_BOUNCE_SENDERS = {"mailer-daemon", "postmaster", "mdaemon", "root"}


def match_customer(email: str, name: str, repo: Any, body: str = "") -> dict[str, Any]:
    """Return a customer dict with enriched invoice hints, or an empty dict.

    Priority:
      1. exact contact_email match against invoices table (sender, then any
         address found in the body - e.g. bounces carry the recipient inside)
      2. domain match (same @domain) against invoices table
      3. name substring match against customer_name
    """
    if not email and not body:
        return {}

    invoices = repo.select(
        "invoices", order_by="amount_outstanding", desc=True, limit=500
    )
    name_key = (name or "").lower().strip()
    candidates = _candidate_emails(email, body)
    for cand in candidates:
        hit = _by_email(cand, invoices)
        if hit:
            return hit

    if name_key:
        for inv in invoices:
            cn = (inv.get("customer_name") or "").lower().strip()
            if cn and (name_key in cn or cn in name_key):
                return _assemble(inv.get("contact_email") or "", inv, invoices)

    return {}


def _candidate_emails(email: str, body: str) -> list[str]:
    """Sender first, then unique addresses mentioned in the message body.

    Delivery-failure notices are sent FROM mailer-daemon/postmaster; the real
    customer only appears inside the body ("<ap@acme-digital.com>: host not
    found"). Those body addresses are what we actually match on.
    """
    found: list[str] = []
    if email:
        found.append(email)
    body_hits = [m.group(0) for m in _EMAIL_RE.finditer(body or "")]
    is_bounce = (email or "").split("@")[0].lower() in _BOUNCE_SENDERS
    if is_bounce:
        found = body_hits + found
    else:
        found = found + body_hits
    out = []
    for addr in found:
        key = addr.lower().strip()
        if key and key not in [x.lower() for x in out]:
            out.append(addr)
    return out


def _by_email(addr: str, invoices: list[dict]) -> dict | None:
    key = (addr or "").lower().strip()
    if not key:
        return None
    domain = key.split("@")[-1] if "@" in key else ""
    for inv in invoices:
        ce = (inv.get("contact_email") or "").lower().strip()
        if ce and ce == key:
            return _assemble(ce, inv, invoices)
    if domain:
        for inv in invoices:
            ce = (inv.get("contact_email") or "").lower().strip()
            if ce and ce.split("@")[-1] == domain:
                return _assemble(ce, inv, invoices)
    return None


def _assemble(contact_email: str, inv: dict, invoices: list[dict]) -> dict:
    cname = inv.get("customer_name") or ""
    related = [x for x in invoices if (x.get("customer_name") or "") == cname]
    totals = sum(float(x.get("amount_outstanding") or 0) for x in related)
    return {
        "customer_name": cname,
        "contact_email": contact_email,
        "invoice_count": len(related),
        "total_outstanding": round(totals, 2),
        "matched_invoice": inv.get("invoice_number") or "",
        "hint": _hint(cname),
    }


def _hint(cname: str) -> str:
    return f"Matched to {cname or 'customer'} in the AR ledger"