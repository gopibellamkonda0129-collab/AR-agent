"""AI correspondence analyzer.

Reads an email (subject + body + headers) and produces a structured signal:

    signal_type, priority, confidence, summary, promised_date,
    promised_amount, related_invoice, customer_hint

Default: deterministic close-reading rules (fast, private, works offline).
If OPENAI_API_KEY is set, the same contract is answered by an LLM instead.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from services.promise_dates import extract_promise, resolve_promise_date

# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------

_INVOICE_NO_RE = re.compile(
    r"\b(?:invoice|inv|inv#|invoice\s*#|#)\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9\-/_.]{1,40})"
    r"|\b(?:invoice\s*)?(INV|INV\.|INV#)[\-_.]\s*([A-Za-z0-9][A-Za-z0-9\-/_.]{0,40})",
    re.IGNORECASE,
)

_AMOUNT_RE = re.compile(r"\$?\s*([\d,]+\.\d{2})")


def _lower(text: str) -> str:
    return " ".join(text.lower().split())


def _classify_rules(subject: str, body: str) -> dict[str, Any]:
    full = _lower(f"{subject}\n{body}")
    result: dict[str, Any] = {
        "signal_type": "other",
        "priority": "low",
        "confidence": 0.0,
        "related_invoice": "",
        "promised_amount": None,
        "summary": "",
    }

    # --- bounced / delivery failure -------------------------------------
    bounce_markers = (
        "delivery status notification", "delivery failure", "undelivered mail",
        "mail delivery subsystem", "returned to sender", "message not delivered",
        "550 5.1.1", "permanent failure", "<> (empty envelope)",
    )
    if any(m in full for m in bounce_markers) and re.search(r"\bfail(?:ed|ure)?\b|undeliver", full):
        result["signal_type"] = "bounced_email"
        result["confidence"] = 0.97
        result["priority"] = "critical"
        result["summary"] = "Undeliverable - the customer address bounced the reminder. Verify the contact and follow up by phone."
        _attach_invoice(full, result)
        return result

    # --- wrong PO (must win over the generic 'incorrect' dispute wording) -
    if re.search(r"\b(po\b|p\.?o\.?|purchase order)\b[^\n]{0,60}\b(should\s+be|incorrect|wrong|mismatch|updat\w{0,3}|referenc\w{0,2})\b|\b(should\s+be|incorrect|wrong|mismatch|referenc\w{0,2})\b[^\n]{0,60}\b(po\b|p\.?o\.?|purchase order)\b", full):
        result["signal_type"] = "wrong_po"
        result["priority"] = "high"
        result["confidence"] = 0.85
        result["summary"] = "Customer reports a PO mismatch - reconcile the purchase order reference on the invoice."
        _attach_invoice(full, result)
        return result

    # --- approval pending (a process blocker, not chased) ------------------
    # The customer has the invoice but payment is waiting on THEIR internal
    # approval. This only fires when approval is stated as the remaining step
    # ("once approved we'll pay" / "awaiting approval"); wording that says the
    # invoice is ALREADY approved falls through to the promise classifier.
    if re.search(
        r"\b(awaiting approval|approval (?:is )?pending|pending approval|waiting (?:for|on) (?:our |the )?"
        r"(?:finance|accounts payable|internal )?approval"
        r"|in the approval (?:process|queue|stage|flow)"
        r"|under (?:internal |our )?approval"
        r"|sent (?:for|to) approval"
        r"|needs (?:our |finance )?approval"
        r"|once (?:it|it is|it?s|this is|the invoice is|our finance team approves|"
        r"approved|everything is approved"
        r"|(?:our |the |this )?approval (?:is|comes|comes through|is granted|goes through))"
        r"|when (?:it|it is|it?s|the invoice|everything) (?:gets|is) approved"
        r"|after (?:it is|it?s|everything is|our )?approval"
        r"|upon approval"
        r"|to be approved|for approval"
        r"|before we can (?:pay|release|process)"
        r"|get (?:it|this|the invoice) approved"
        r"|finance (?:team|department)\b.{0,60}\b(?:approv|review|sign.?off)"
        r")\b",
        full,
    ):
        result["signal_type"] = "approval_pending"
        result["priority"] = "medium"
        result["confidence"] = 0.82
        result["summary"] = (
            "Customer is awaiting internal approval before the invoice can "
            "be paid - check the approval status, don't chase payment yet."
        )
        _attach_invoice(full, result)
        _attach_amount(full, result)
        return result

    # --- dispute ---------------------------------------------------------
    if re.search(r"\b(disput[e ed ing]|contested|don.?t owe|never received (the )?(service|invoice|goods)|wrong charge|double.?charged|refund|not our (bill|account|invoice)|duplicat|already paid( it)?|paid (twice|already))\b", full):
        result["signal_type"] = "dispute"
        result["priority"] = "critical"
        result["confidence"] = 0.9
        result["summary"] = "Customer disputes the charge. Investigate before dunning; attach invoice + PO evidence."
        _attach_invoice(full, result)
        _attach_amount(full, result)
        return result

    # --- documentation request -------------------------------------------
    if re.search(r"\b(send us|need|require|request|please provide|attach(ed)?|provide)\b", full) and \
       re.search(r"\b(contract|po\b|purchase order|receipt|proof|tax id|w-?9|certificate|statement|supporting docs?|documentation|invoice copy)\b", full):
        result["signal_type"] = "documentation_request"
        result["priority"] = "medium"
        result["confidence"] = 0.85
        result["summary"] = "Customer needs documentation before they can pay - gather and send the requested items."
        _attach_invoice(full, result)
        return result

    # --- missing invoice -------------------------------------------------
    if re.search(r"\b(invoice)\b", full) and \
       re.search(r"\b(resend|never got|didn.?t get|did not receive|didn.?t receive|did not arrive|never received|missing|haven.?t received|havent received|didn.?t see|didnt see|not arrived|hasn.?t (arrived|shown up))\b", full):
        result["signal_type"] = "missing_invoice"
        result["priority"] = "high"
        result["confidence"] = 0.88
        result["summary"] = "Customer did not receive the invoice - resend the PDF and confirm delivery."
        _attach_invoice(full, result)
        return result

    # --- payment confirmation ---------------------------------------------
    if re.search(r"\b(paid|payment (made|sent|sent out|transferred|processed|confirmed)|wire (sent|scheduled)|check (sent|mailed|in the mail)|auto.?pay)\b", full):
        result["signal_type"] = "payment_confirmation"
        result["priority"] = "medium"
        result["confidence"] = 0.86
        result["summary"] = "Customer says payment was sent. Verify it against the bank feed; reconcile if received."
        _attach_invoice(full, result)
        _attach_amount(full, result)
        return result

    # --- payment promise (the headline feature) ---------------------------
    phrase, raw_date = extract_promise(full)
    if phrase:
        promised = resolve_promise_date(raw_date, date.today())
        result["signal_type"] = "payment_promise"
        result["priority"] = "high"
        result["confidence"] = 0.82
        result["summary"] = (
            f"Customer promised to pay {('by ' + raw_date) if raw_date else ''}."
            + (" Detected promise date: " + promised.isoformat() if promised else "")
        )
        if promised:
            result["promised_date"] = promised.isoformat()
        _attach_invoice(full, result)
        _attach_amount(full, result)
        return result

    # --- payment intent WITHOUT a confirmed date --------------------------
    # "we'll get this sorted next week" is a real signal, but it must NEVER be
    # turned into a specific promise date. We record intent + no date, and the
    # queue treats it as "ask for a confirmed date", not "payment coming".
    if re.search(
        r"\b(get (?:this|it) sorted"
        r"|sort(?:ing)? (?:this|it) out"
        r"|take care of it"
        r"|working on it"
        r"|pay(?:ing)? (?:soon|shortly|next week|this week|this month|in a few days|asap)"
        r"|will (?:be )?paying"
        r"|will pay (?:you|the|this|the balance|the amount|it)"
        r"|payment.{0,40}\b(?:soon|shortly|next week|in\s+\w+)\b"
        r"|settl(?:ing|e this)"
        r"|will (?:wire|send) (?:it|the (?:payment|balance|amount)))\b",
        full,
    ):
        result["signal_type"] = "payment_promise"
        result["priority"] = "medium"
        result["confidence"] = 0.6
        result["summary"] = (
            "Customer intends to pay but gave no confirmed date. "
            "Do not forecast this payment until a date is confirmed."
        )
        _attach_invoice(full, result)
        _attach_amount(full, result)
        return result

    # --- generic question -------------------------------------------------
    if re.search(r"\b(question|when is|where is|what.?s the|how do i|status\?|update on|who do i|what do we|which invoice)\b", full):
        result["signal_type"] = "info_question"
        result["priority"] = "low"
        result["confidence"] = 0.7
        result["summary"] = "Inbound question - reply with the requested info."
        return result

    return result


def _attach_invoice(full: str, result: dict) -> None:
    m = _INVOICE_NO_RE.search(full)
    if m:
        rid = m.group(1)
        if not rid and m.lastindex and m.lastindex >= 2:
            rid = (m.group(2) or "").rstrip(".#") + "-" + (m.group(3) or "")
        rid = (rid or "").strip("# :.-")
        if rid and rid.upper() not in {"DATE", "DETAILS", "NUMBER", "STATUS"}:
            result["related_invoice"] = rid.upper()[:40]


def _attach_amount(full: str, result: dict) -> None:
    matches = [_clean_money(x) for x in _AMOUNT_RE.findall(full)]
    if matches:
        result["promised_amount"] = max(matches)


def _clean_money(raw: str) -> float:
    return float(raw.replace(",", ""))


# ---------------------------------------------------------------------------
# LLM path (optional)
# ---------------------------------------------------------------------------

def _classify_llm(subject: str, body: str) -> dict[str, Any]:
    import json

    from openai import OpenAI

    client = OpenAI()
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are the email analyst inside an accounts-receivable agent. "
                    "Given a customer email, output strict JSON with keys: "
                    "signal_type (one of: payment_promise, dispute, missing_invoice, "
                    "wrong_po, documentation_request, payment_confirmation, "
                    "bounced_email, info_question, other), priority (low/medium/high/"
                    "critical), confidence (0..1), summary (1 sentence), "
                    "related_invoice (invoice number or ''), promised_date (ISO date "
                    "or null) ONLY when they promise to pay, promised_amount (number "
                    "or null). Resolve relative dates like 'next Friday' to the "
                    "actual calendar date assuming today is "
                    + date.today().isoformat()
                    + "."
                ),
            },
            {"role": "user", "content": f"SUBJECT: {subject}\n\nBODY:\n{body}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    try:
        return json.loads(resp.choices[0].message.content)
    except Exception:
        return {"signal_type": "other", "priority": "low", "confidence": 0.0,
                "summary": "", "related_invoice": "", "promised_date": None,
                "promised_amount": None}


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def analyze_email(subject: str, body: str, use_llm: bool) -> dict[str, Any]:
    """Return a signal dict for one inbound email."""
    if use_llm:
        try:
            sig = _classify_llm(subject, body)
        except Exception:
            sig = _classify_rules(subject, body)
    else:
        sig = _classify_rules(subject, body)

    # normalize + enforce defaults
    allowed = {
        "", "payment_promise", "dispute", "missing_invoice", "wrong_po",
        "documentation_request", "payment_confirmation", "bounced_email",
        "info_question", "approval_pending", "other",
    }
    sig["signal_type"] = sig.get("signal_type") or "other"
    if sig["signal_type"] not in allowed:
        sig["signal_type"] = "other"
    sig.setdefault("priority", "medium")
    sig.setdefault("confidence", 0.5)
    sig.setdefault("summary", "")
    sig.setdefault("related_invoice", "")
    sig.setdefault("promised_amount", None)
    sig.setdefault("promised_date", None)
    return sig