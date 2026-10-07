"""Collections intelligence: payment behaviour, chase strategy, "why late", timeline.

All of this is INTERPRETATION of facts already in the database (ledger rows,
recorded payments, signals, promises, follow-up history) - it never invents
amounts, dates or customer statements. When there isn't enough history to say
something meaningful, the blocks say so instead of guessing.

Entry points used by the routers:
  payment_behavior(repo, name)     -> profile of how a customer pays
  collections_intelligence(...)    -> the "overdue X - Nd, last response..." card
  chase_strategy(repo, item)       -> situation-aware messaging advice
  why_late(repo, item)             -> reason + evidence for the lateness
  collections_timeline(repo, name) -> invoice -> due -> reminder -> payment...
"""
from __future__ import annotations

import datetime as dt
from statistics import mean
from typing import Any

_DATE = dt.date


def _money(x: Any) -> float:
    try:
        return round(float(x or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _d(iso: str | None) -> _DATE | None:
    if not iso:
        return None
    try:
        return _DATE.fromisoformat(str(iso)[:10])
    except ValueError:
        return None


def _mean(xs: list[int]) -> int:
    return round(mean(xs)) if xs else 0


# ---------------------------------------------------------------------------
# Evidence vocabulary. Everything below is fact-grounded: a category is only
# ever produced when a stored fact (a signal type, a promise state, a recorded
# payment, a word in the customer's OWN message) supports it. "Unknown" is the
# default whenever evidence is missing - the engine never infers intent from
# the tone of an email.
# ---------------------------------------------------------------------------

# signal types that mean "the customer literally cannot pay us yet until this
# is fixed" - process blockers, not payment resistance.
_PROCESS_BLOCKERS = {"missing_invoice", "wrong_po", "documentation_request",
                     "bounced_email", "approval_pending"}

_BLOCKER_LABELS = {
    "missing_invoice": "invoice not delivered",
    "wrong_po": "PO mismatch on the invoice",
    "documentation_request": "customer still needs documents",
    "bounced_email": "contact / email unreachable",
    "approval_pending": "customer approval pending",
}

# phrases in the customer's own words that point to payment difficulty. These
# are FACTS they told us, never an interpretation of tone.
_CASH_FLOW_TERMS = (
    "cash flow", "cashflow", "installment", "instalment", "payment plan",
    "financial", "struggl", "hardship", "in arrears", "defer", "slow month",
    "can't pay", "cannot pay", "layoff", "economic", "budget",
)

# new "why is this late?" taxonomy mapped from the existing category codes
# (existing categories stay untouched for backward compatibility).
_GROUP_LABELS = {
    "process_blocked": "Process blocked",
    "unable": "Cash-flow signal",
    "at_risk": "Payment commitment at risk",
    "resistance": "Collection resistance",
    "unknown": "No evidence yet",
    "clear": "Nothing overdue",
}

_GROUP_BY_CATEGORY = {
    "DISPUTE": "process_blocked",
    "MISSING_INVOICE": "process_blocked",
    "PO_ISSUE": "process_blocked",
    "AWAITING_DOCS": "process_blocked",
    "UNREACHABLE": "process_blocked",
    "APPROVAL_PENDING": "process_blocked",
    "MISSED_PROMISE": "at_risk",
    "PROMISE_PENDING": "at_risk",
    "NO_RESPONSE": "resistance",
    "REPEAT_LATE_PAYER": "resistance",
    "INFO_QUESTION": "unknown",
    "CONFIRMED_NOT_MATCHED": "unknown",
    "OVERDUE": "unknown",
}

# A-F decision order (the prioritisation principle): fix blockers first,
# then confirm pre-due readiness, then overdue-with-behaviour, then missed
# promises, then payment-plan conversations, and only as a last resort act
# on insufficient evidence.
_DECISION_LABELS = {
    "A": "Blocker first",
    "B": "Confirm payment readiness",
    "C": "Overdue - evaluate behaviour",
    "D": "Missed promise follow-up",
    "E": "Payment plan / collaboration",
    "F": "Insufficient evidence",
}

_OWNER_BY_ACTION = {
    "REQUEST_CORRECTED_PO": "AR Ops",
    "RESEND_INVOICE": "AR Ops",
    "PROVIDE_DOCUMENTS": "AR Ops",
    "FIND_ALTERNATE_CONTACT": "AR Ops",
    "CONFIRM_PAYMENT_READINESS": "AR Ops",
    "VERIFY_PAYMENT": "AR Ops",
    "REPLY_TO_QUESTION": "AR Ops",
    "MONITOR_PROMISE": "AR Ops",
    "REQUEST_APPROVAL_STATUS": "AR Ops",
    "INVESTIGATE_DISPUTE": "AR Ops + Collections",
    "FOLLOW_UP_MISSED_PROMISE": "Collections",
    "FOLLOW_UP_IF_UNPAID": "Collections",
    "FOLLOW_UP": "Collections",
    "ESCALATE": "Collections",
}

# action-queue actions grouped by what they actually do. Drives the compact
# COLLECTION / PROCESS / PRE-DUE / DISPUTE badge on each queue item.
_ACTION_CATEGORY: dict[str, str] = {
    "INVESTIGATE_DISPUTE": "dispute",
    "CONFIRM_PAYMENT_READINESS": "pre_due",
    "REQUEST_CORRECTED_PO": "process",
    "RESEND_INVOICE": "process",
    "PROVIDE_DOCUMENTS": "process",
    "FIND_ALTERNATE_CONTACT": "process",
    "REQUEST_APPROVAL_STATUS": "process",
    "VERIFY_PAYMENT": "process",
    "REPLY_TO_QUESTION": "process",
    "MONITOR_PROMISE": "process",
    "FOLLOW_UP": "collection",
    "FOLLOW_UP_IF_UNPAID": "collection",
    "FOLLOW_UP_MISSED_PROMISE": "collection",
    "ESCALATE": "collection",
}

_CATEGORY_LABELS = {
    "collection": "COLLECTION",
    "process": "PROCESS",
    "pre_due": "PRE-DUE",
    "dispute": "DISPUTE",
}


def _partial_payments(repo: Any, name: str) -> int:
    """Instalment-style behaviour: more than one recorded payment against the
    same invoice. Counts the payment rows that share an invoice number."""
    counts: dict[str, int] = {}
    for p in repo.select("payments", where={"customer_name": name}):
        num = p.get("invoice_number") or ""
        if num:
            counts[num] = counts.get(num, 0) + 1
    return sum(n for n in counts.values() if n >= 2)


def _cash_flow_hit(repo: Any, name: str) -> str:
    """Return the customer's own wording that mentions payment difficulty, or ''.
    Reads only stored signal summaries (their words), never a tone judgment."""
    hay = " ".join(
        (s.get("summary") or "")
        for s in repo.select("signals",
                             where={"customer_name": name, "resolved": False})
    ).lower()
    for term in _CASH_FLOW_TERMS:
        if term in hay:
            idx = hay.find(term)
            return hay[max(0, idx - 40): idx + len(term) + 40].strip()
    return ""


# ---------------------------------------------------------------------------
# 1. Customer payment behaviour
# ---------------------------------------------------------------------------

def _payment_delays(repo: Any, name: str) -> list[dict[str, Any]]:
    """Each recorded payment paired with its invoice due date -> delay in days."""
    by_number: dict[str, dict] = {
        (i.get("invoice_number") or ""): i
        for i in repo.select("invoices", where={"customer_name": name})
    }
    out: list[dict[str, Any]] = []
    for p in repo.select("payments", where={"customer_name": name}):
        inv = by_number.get(p.get("invoice_number") or "")
        due = _d(inv.get("due_date") if inv else None)
        paid = _d(p.get("paid_at"))
        delay = (paid - due).days if (due and paid) else None
        out.append({
            "invoice_number": p.get("invoice_number", ""),
            "amount": _money(p.get("amount")),
            "paid_at": p.get("paid_at"),
            "due_date": inv.get("due_date") if inv else None,
            "delay_days": delay,
        })
    out.sort(key=lambda r: r.get("paid_at") or "")
    return out


def _promise_outcomes(repo: Any, name: str) -> list[dict[str, Any]]:
    """Every payment promise for this customer -> kept / missed / open.

    Kept = resolved with a keep note (or a payment landed for the promise).
    Missed = explicitly missed, or still open past its promised date.
    """
    today = _DATE.today()
    rows = repo.select("signals", where={"customer_name": name})
    ok_invoices = {
        p.get("invoice_number")
        for p in repo.select("payments", where={"customer_name": name})
    }
    out = []
    for sig in sorted(rows, key=lambda s: s.get("created_at") or ""):
        if sig.get("signal_type") != "payment_promise":
            continue
        promised = _d(sig.get("promised_date"))
        created = _d(sig.get("created_at"))
        note = (sig.get("resolution_note") or "").upper()
        resolved = bool(sig.get("resolved"))
        related = sig.get("related_invoice", "")
        if note.startswith(("KEPT", "PAID")):
            outcome = "kept"
        elif note.startswith("MISSED"):
            outcome = "missed"
        elif related in ok_invoices:
            outcome = "kept"
        elif not resolved and promised and promised < today:
            outcome = "missed"
        elif not resolved:
            outcome = "open"
        else:
            outcome = "resolved"
        out.append({
            "promised_date": sig.get("promised_date"),
            "promised_amount": sig.get("promised_amount"),
            "related_invoice": related,
            "created_at": sig.get("created_at"),
            "outcome": outcome,
            "note": sig.get("resolution_note", ""),
            "created": created,
        })
    return out


def _promise_breakdown(repo: Any, name: str) -> list[dict[str, Any]]:
    """Per-promise kept / missed / open rows for the Promise Kept Rate view."""
    today = _DATE.today()
    paid_by_invoice = {
        p.get("invoice_number"): _d(p.get("paid_at"))
        for p in repo.select("payments", where={"customer_name": name})
        if p.get("invoice_number")
    }
    rows = []
    for o in _promise_outcomes(repo, name):
        promised = _d(o.get("promised_date"))
        paid_on = paid_by_invoice.get(o.get("related_invoice") or "")
        if o["outcome"] == "kept" and paid_on and promised:
            late_days = (paid_on - promised).days
        elif o["outcome"] in ("kept", "missed") and promised:
            late_days = (today - promised).days
        else:
            late_days = None
        rows.append({
            "related_invoice": o.get("related_invoice", ""),
            "promised_date": o.get("promised_date"),
            "promised_amount": o.get("promised_amount"),
            "outcome": o["outcome"],
            "status_label": {"kept": "Kept", "missed": "Missed",
                             "open": "Open", "resolved": "Resolved"}.get(o["outcome"], o["outcome"]),
            "note": o.get("note", ""),
            "late_days": late_days,
        })
    rows.reverse()  # most recent first
    return rows


def _reliability_score(on_time: int, late: int, avg_delay: int,
                       kept: int, missed: int) -> int:
    """Transparent 0-100 score: start at 100 and subtract known behaviour.

    Penalties are per-fact and small so the number stays explainable.
    """
    score = 100.0
    score -= 12 * late
    score -= min(25, avg_delay)
    score -= 10 * missed
    score += min(15, 3 * kept)
    return max(1, min(100, int(round(score))))


def payment_behavior(repo: Any, name: str) -> dict[str, Any]:
    today = _DATE.today()
    delays = _payment_delays(repo, name)
    paid = [d for d in delays if d["delay_days"] is not None]
    late = [d["delay_days"] for d in paid if d["delay_days"] > 0]
    on_time = len(paid) - len(late)
    avg_delay = _mean(late)

    outcomes = _promise_outcomes(repo, name)
    kept = sum(1 for o in outcomes if o["outcome"] == "kept")
    missed = sum(1 for o in outcomes if o["outcome"] == "missed")
    open_p = sum(1 for o in outcomes if o["outcome"] == "open")

    invoices = repo.select("invoices", where={"customer_name": name})
    overdue_amt = round(sum(_money(i.get("amount_outstanding")) for i in invoices
                            if _d(i.get("due_date")) and _d(i.get("due_date")) < today), 2)

    last_payment = paid[-1]["paid_at"] if paid else None
    score = _reliability_score(on_time, len(late), avg_delay, kept, missed)

    def _label(s: int) -> str:
        if s >= 80:
            return "Excellent"
        if s >= 60:
            return "Good"
        if s >= 40:
            return "Average"
        return "Poor"

    return {
        "reliability_score": score if paid else None,
        "reliability_label": _label(score) if paid else "No history",
        "on_time_count": on_time if paid else None,
        "late_count": len(late) if paid else None,
        "total_payments": len(paid) or None,
        "avg_delay_days": avg_delay if paid else None,
        "promises_kept": kept,
        "promises_count": kept + missed,
        "promises_missed": missed,
        "promises_open": open_p,
        "promises_kept_percent": round(100 * kept / (kept + missed)) if (kept + missed) else None,
        "promise_breakdown": _promise_breakdown(repo, name),
        "on_time_percent": round(100 * on_time / len(paid)) if paid else None,
        "partial_payments": _partial_payments(repo, name),
        "last_payment_date": last_payment,
        "current_overdue": overdue_amt,
        "late_payments": [{
            "invoice_number": d["invoice_number"],
            "amount": d["amount"],
            "paid_at": d["paid_at"],
            "due_date": d["due_date"],
            "delay_days": d["delay_days"],
        } for d in paid if d["delay_days"] and d["delay_days"] > 0],
    }


# ---------------------------------------------------------------------------
# 2. Collections intelligence: the "why should I act today" card
# ---------------------------------------------------------------------------

def collections_intelligence(repo: Any, name: str, item: dict[str, Any],
                             behavior: dict[str, Any] | None = None) -> dict[str, Any]:
    behavior = behavior or payment_behavior(repo, name)

    # the most recent promise this customer MISSED (current or historical)
    missed_promise = None
    for o in _promise_outcomes(repo, name):
        if o["outcome"] == "missed":
            missed_promise = o  # last wins (list is chronological)

    open_days = item.get("max_days_overdue", 0)
    last_response = item.get("last_response_days")

    return {
        "overdue_amount": item.get("overdue_amount", 0.0),
        "max_days_overdue": open_days,
        "overdue_invoice_count": item.get("overdue_invoice_count", 0),
        "due_this_week_amount": item.get("due_this_week_amount", 0.0),
        "last_response_days": last_response,
        "last_response_label": (f"{last_response} day(s) ago" if last_response is not None else "none on file"),
        "missed_promise": {
            "promised_date": missed_promise["promised_date"] if missed_promise else None,
            "related_invoice": missed_promise.get("related_invoice", "") if missed_promise else "",
            "promised_amount": missed_promise.get("promised_amount") if missed_promise else None,
        } if missed_promise else None,
        "paid_late_count": behavior["late_count"] or 0,
        "open_issue_types": sorted(item.get("open_signal_types") or []),
        "risk": item.get("priority"),
        "risk_score": item.get("priority_score"),
        "risk_reasons": item.get("priority_reasons", []),
        "recommended_action": item.get("action_label", ""),
        "recommended_reason": item.get("reason", ""),
    }


# ---------------------------------------------------------------------------
# 3. Smart chase strategy (situation-aware messaging)
# ---------------------------------------------------------------------------

_REMINDER_TYPES = {
    "friendly_reminder", "overdue_reminder", "payment_date_request",
    "missed_promise_followup", "escalation_notice",
}


def _follow_up_history(repo: Any, name: str) -> list[dict[str, Any]]:
    """Follow-ups already reviewed/approved for this customer (chronological)."""
    rows = repo.select("followups", where={"customer_name": name},
                       order_by="created_at", desc=False)
    return [
        r for r in rows
        if (r.get("status") in ("approved", "sent", "edited", "copied"))
        and r.get("draft_type") not in (None, "", "none")
    ]


def _stage_label(stage: int, promise_missed: bool) -> str:
    if promise_missed:
        return "Promise follow-up"
    if stage >= 4:
        return f"{stage}th reminder"
    if stage >= 3:
        return "3rd reminder"
    if stage == 2:
        return "2nd reminder"
    return "1st reminder"


def chase_strategy(repo: Any, item: dict[str, Any]) -> dict[str, Any]:
    history = _follow_up_history(repo, item["customer_name"])
    stage = len(history) + 1
    overdue = float(item.get("overdue_amount") or 0) > 0
    last_response = item.get("last_response_days")
    by_type = set(item.get("open_signal_types") or [])
    promise = item.get("promise")
    promise_status = (promise or {}).get("status")
    days = item.get("max_days_overdue") or 0
    large = (_money(item.get("overdue_amount")) >= 15000)

    def _out(stage: int, tone: str, approach: str, steps: list[str],
             avoid: list[str], email: str, stage_label: str | None = None,
             flags: list[str] | None = None) -> dict[str, Any]:
        return {
            "stage": stage,
            "stage_label": stage_label or _stage_label(stage, promise_status == "overdue"),
            "tone": tone,
            "approach": approach,
            "steps": steps,
            "avoid": avoid,
            "email": email,
            "flags": flags or [],
        }

    if by_type & {"dispute"}:
        return _out(
            stage, "collaborative",
            "Don't chase payment while a dispute is open - resolve the line items first.",
            [
                "Confirm exactly which line item / amount is disputed.",
                "Check for an undisputed balance that CAN be collected now.",
                "Offer a short call to close it fast; keep evidence in the reply.",
            ],
            ["Avoid demanding payment while the charge is contested.",
             "Do not present the disputed amount as overdue."],
            "dispute_clarification",
        )

    if by_type & {"bounced_email"}:
        return _out(
            stage, "informational",
            "Find an alternate contact - the last message never reached them.",
            [
                "Look up an alternate email / phone for the customer.",
                "Re-send the invoice once a new address is confirmed.",
            ],
            ["Avoid counting a bounce as a customer response."],
            "none",
        )

    if promise_status == "overdue":
        return _out(
            stage, "firm",
            f"They missed a promise to pay by {promise['promised_date']} - reference it and ask for a revised date.",
            [
                f"Reference the promise: '{promise['promised_date']}' for "
                f"{_money(promise.get('promised_amount')) or 'the invoice'}.",
                f"Ask for a firm revised date (invoice {promise.get('related_invoice') or item.get('primary_invoice_number')}).",
                "If no date is offered, escalate to the decision-maker.",
            ],
            ["Avoid giving another open-ended deadline.",
             "Don't just repeat the reminder template word-for-word."],
            "missed_promise_followup",
            flags=["missed-promise"],
        )

    if promise_status in ("due_today", "upcoming"):
        return _out(
            stage, "patient",
            "Payment is promised - monitor it, don't chase yet.",
            [
                "Check the bank feed for the promised amount today.",
                "Only follow up (asking for confirmation) if it doesn't land.",
            ],
            [],
            "none",
            stage_label="Promise monitor",
        )

    if by_type & {"missing_invoice"}:
        return _out(
            stage, "helpful",
            "Customer says the invoice never arrived - resend it and confirm receipt.",
            [
                "Attach the invoice PDF and confirm the correct address.",
                "Ask them to confirm receipt so the clock restarts cleanly.",
            ],
            [],
            "missing_invoice_response",
        )

    if by_type & {"wrong_po"}:
        return _out(
            stage, "helpful",
            "A PO mismatch is blocking payment - get the corrected PO and resend.",
            [
                "Ask for the correct PO number on the specific invoice.",
                "Update and resend the invoice; confirm it matches their PO.",
            ],
            [],
            "po_correction_request",
        )

    if by_type & {"documentation_request"}:
        return _out(
            stage, "helpful",
            "Customer needs documents before they can pay - get them out today.",
            [
                "Send the requested documents and confirm what's still missing.",
                "Offer a callback so their AP team can process it immediately.",
            ],
            [],
            "documentation_response",
        )

    if by_type & {"approval_pending"}:
        return _out(
            stage, "helpful",
            "The invoice is with the customer's approvers - don't chase payment, confirm the approval status.",
            [
                "Ask when their approval is expected and if anything is needed from us.",
                "Add a target date: get them to commit to payment once approval clears.",
            ],
            ["Avoid sending a payment reminder while it sits in their approval queue."],
            "approval_pending_followup",
        )

    if by_type & {"info_question"}:
        return _out(
            stage, "helpful",
            "They asked a question - answer it first, then confirm a payment date.",
            [
                "Reply with exactly the information they asked for.",
                "Add a one-line ask for a firm payment date once their question is answered.",
            ],
            ["Avoid sending the reminder without addressing their question."],
            "friendly_reminder",
        )

    if by_type & {"payment_confirmation"}:
        return _out(
            stage, "patient",
            "Customer says payment was already sent - verify it before chasing.",
            [
                "Match the transfer against the bank feed and reconcile it.",
                "Confirm with the customer once booked; don't send a reminder.",
            ],
            [],
            "none",
            stage_label="Verify payment",
        )

    if not overdue:
        return _out(
            stage, "patient", "Nothing to chase right now.",
            ["No overdue balance and no open issue - monitor the account."],
            [],
            "none", stage_label="Monitor",
        )

    # overdue with no special blockers -> escalate naturally by stage
    if last_response is not None and last_response >= 14:
        return _out(
            stage, "urgent",
            f"No customer response for {last_response} day(s) - escalate before this ages further.",
            [
                "Send an escalation/notice email with a firm date.",
                "Try an alternate contact or call if the email stays unanswered.",
            ],
            ["Avoid continuing the same polite reminder pattern."],
            "escalation_notice", flags=["unresponsive"],
        )

    if days >= 45:
        return _out(
            stage, "urgent",
            f"{days} day(s) past due - move this to escalation now.",
            [
                "Send a final follow-up with a firm date and clear consequence.",
                "Loop in a senior contact on the customer side.",
            ],
            [],
            "escalation_notice", flags=["long-overdue"],
        )

    if stage == 1:
        steps = ["Ask whether payment has been sent and if anything is holding it up.",
                 "Offer to help resolve any blocker (documents, resend, PO)."]
        avoid: list[str] = []
        if large:
            steps.insert(0, "Personalize it - reference the exact invoice and amount; this is a top-amount account.")
            avoid.append("Don't use a generic template on a large balance.")
        return _out(
            stage, "friendly", "First touch - keep it light, give them every chance to pay.",
            steps, avoid, "friendly_reminder",
            flags=["personalize"] if large else [],
        )

    if stage == 2:
        steps = ["State the invoice and how many days past due.",
                 "Ask for a payment reference if already sent (so it can be matched).",
                 "Name the next step: a firm date or available funds today."]
        if large:
            steps.append("Escalate to a second contact - this is a high-value balance.")
        return _out(
            stage, "firm", "Second touch - be clear there is an amount due and a date expected.",
            steps, [], "overdue_reminder",
            flags=["high-value"] if large else [],
        )

    return _out(
        stage, "urgent", "Multiple follow-ups already sent - escalate with a firm deadline.",
        ["Reference the previous follow-ups and the still-open balance.",
         "Set an explicit date; state what happens if there's no reply.",
         "Offer one last chance to resolve before escalation."],
        ["Avoid repeating the same wording a third time."],
        "escalation_notice", flags=["escalate"],
    )


# ---------------------------------------------------------------------------
# 4. Why is this late? (reason + evidence + recommendation)
# ---------------------------------------------------------------------------

_WHY_LABELS = {
    "DISPUTE": "The amount is disputed",
    "MISSING_INVOICE": "They say the invoice never arrived",
    "PO_ISSUE": "A PO mismatch is blocking payment",
    "AWAITING_DOCS": "They need documents before paying",
    "UNREACHABLE": "We can't reach them (email bounced)",
    "APPROVAL_PENDING": "They are waiting on internal approval",
    "MISSED_PROMISE": "A promised payment date was missed",
    "CONFIRMED_NOT_MATCHED": "They say they paid, but it hasn't matched",
    "INFO_QUESTION": "They asked a question, unanswered",
    "NO_RESPONSE": "No response since the invoice went overdue",
    "REPEAT_LATE_PAYER": "Historically they pay late",
    "PROMISE_PENDING": "They promised a date but haven't paid yet",
    "OVERDUE": "Invoice is past due",
}


def why_late(repo: Any, item: dict[str, Any],
             behavior: dict[str, Any] | None = None) -> dict[str, Any]:
    by_type = set(item.get("open_signal_types") or [])
    promise = item.get("promise")
    promise_status = (promise or {}).get("status")
    latest = item.get("latest_signal") or {}
    last_response = item.get("last_response_days")
    overdue = float(item.get("overdue_amount") or 0) > 0
    behavior = behavior or payment_behavior(repo, item["customer_name"])
    late_hist = behavior.get("late_count") or 0

    evidence = (latest.get("summary") or "").strip()
    evidence_date = latest.get("created_at") or None
    src_email = latest.get("source_email") or {}
    source_subject = src_email.get("subject", "")

    # facts that can flip a "no evidence" case into a cash-flow signal:
    # their own words + recorded installment payments.
    cash_flow_wording = _cash_flow_hit(repo, item["customer_name"])
    has_installments = bool(behavior.get("partial_payments") or 0)

    def _build(category: str, headline: str, recommended: str,
               confirmed_date: bool | None = None) -> dict[str, Any]:
        group = _GROUP_BY_CATEGORY.get(category, "unknown")
        if not overdue and category == "OVERDUE":
            group = "clear"
        elif group in ("resistance", "unknown") and (cash_flow_wording or has_installments):
            group = "unable"
        if group == "unable":
            headline = (
                "The customer's own messages point to cash-flow constraints "
                "and they are paying in instalments."
            )
            recommended = (
                "Work toward a firm instalment plan with dated commitments - "
                "don't repeat standard reminders."
            )
        elif group == "clear":
            headline = "Nothing is currently past due."
            recommended = "Keep monitoring the open balance."
        return {
            "category": category,
            "group": group,
            "group_label": _GROUP_LABELS.get(group, group),
            "label": _WHY_LABELS.get(category, category),
            "headline": headline,
            "evidence": evidence or None,
            "evidence_date": evidence_date,
            "source_subject": source_subject or None,
            "no_confirmed_payment_date": confirmed_date if confirmed_date is not None
            else not bool((promise or {}).get("promised_date")),
            "recommended": recommended,
        }

    if by_type & {"dispute"}:
        return _build(
            "DISPUTE",
            "The customer disputes part of the charge, so they're holding payment.",
            "Resolve the disputed line items first, then collect the undisputed balance.",
        )
    if by_type & {"bounced_email"}:
        return _build(
            "UNREACHABLE",
            "Our email to them bounced - nothing has reached them recently.",
            "Find an alternate contact and re-send the invoice.",
            confirmed_date=True,
        )
    if promise_status == "overdue":
        return _build(
            "MISSED_PROMISE",
            f"They promised to pay by {promise['promised_date']} but no payment has landed.",
            "Reference the missed promise and request a firm revised date.",
        )
    if promise_status == "due_today":
        return _build(
            "PROMISE_PENDING",
            "They promised to pay today - it may simply not have cleared yet.",
            "Check the bank feed; confirm receipt with them if nothing lands.",
            confirmed_date=True,
        )
    if by_type & {"missing_invoice"}:
        return _build(
            "MISSING_INVOICE",
            "They told us the invoice never arrived - likely hasn't been routed to AP yet.",
            "Resend the invoice and confirm receipt so AP can process it.",
        )
    if by_type & {"wrong_po"}:
        return _build(
            "PO_ISSUE",
            "Their PO number doesn't match the invoice - AP can't approve it.",
            "Get the correct PO and resend the corrected invoice.",
        )
    if by_type & {"documentation_request"}:
        return _build(
            "AWAITING_DOCS",
            "They're waiting on documents before payment can be released.",
            "Send the requested documentation and confirm what's still outstanding.",
        )
    if by_type & {"approval_pending"}:
        return _build(
            "APPROVAL_PENDING",
            "They have the invoice but payment is waiting on their internal approval.",
            "Ask for the approval status and when AP expects to release the payment.",
        )
    if by_type & {"info_question"}:
        return _build(
            "INFO_QUESTION",
            "They asked a question and haven't confirmed a payment date since.",
            "Answer their question in the reply, then ask for a firm payment date.",
        )
    if by_type & {"payment_confirmation"}:
        return _build(
            "CONFIRMED_NOT_MATCHED",
            "They report the payment was sent, but it hasn't matched on our side.",
            "Verify against the bank feed and reconcile - no reminder needed.",
            confirmed_date=True,
        )

    if not overdue:
        return _build(
            "OVERDUE", "Not currently late - nothing owed is past due.",
            "Keep monitoring the open balance.",
            confirmed_date=True,
        )

    if last_response is not None and last_response >= 14:
        return _build(
            "NO_RESPONSE",
            f"No customer response for {last_response} day(s) - the reason is unknown to us.",
            "Escalate: try an alternate contact, then send an escalation notice.",
        )
    if late_hist >= 2 and len(behavior.get("late_payments") or []) >= 2:
        return _build(
            "REPEAT_LATE_PAYER",
            f"They've paid late {late_hist} of {behavior.get('total_payments')} recorded payments "
            f"(avg {behavior.get('avg_delay_days')} day(s) late).",
            "Expect the pattern - ask for a firm date and follow up on it.",
        )
    return _build(
        "OVERDUE",
        f"Invoice is {item.get('max_days_overdue', 0)} day(s) past due with no blocker and no confirmed date.",
        "Ask for a firm payment date (or payment reference if already sent).",
    )


# ---------------------------------------------------------------------------
# 5. Collections timeline (invoice -> due -> follow-up -> promise -> payment)
# ---------------------------------------------------------------------------

def collections_timeline(repo: Any, name: str) -> list[dict[str, Any]]:
    today = _DATE.today()
    events: list[dict[str, Any]] = []

    def _ev(date: str, kind: str, title: str, detail: str, topics: list[str]) -> None:
        events.append({"date": date, "kind": kind, "title": title,
                       "detail": detail, "topics": topics})

    for inv in repo.select("invoices", where={"customer_name": name}):
        num = inv.get("invoice_number", "")
        amt = _money(inv.get("amount_outstanding"))
        issued = _d(inv.get("invoice_date"))
        due = _d(inv.get("due_date"))
        if issued:
            _ev(issued.isoformat(), "invoice", f"{num} · invoice issued",
                f"${amt:,.2f} billed" if amt else "", [num, "issue"])
        if due:
            _ev(due.isoformat(), "invoice", f"{num} · payment due",
                f"${amt:,.2f}" if amt else "", [num, "due"])

    open_nums = {
        str(i.get("invoice_number")): i for i in repo.select("invoices", where={"customer_name": name})
        if str(i.get("status") or "").lower() != "paid" and _money(i.get("amount_outstanding")) > 0
    }
    for p in repo.select("payments", where={"customer_name": name},
                         order_by="paid_at", desc=False):
        evn = p.get("invoice_number", "")
        partial = bool(open_nums.get(evn))
        _ev((p.get("paid_at") or "")[:10],
            "partial" if partial else "payment",
            f"{'Partial payment' if partial else 'Payment received'} on {evn}",
            f"${_money(p.get('amount')):,.2f}" + (" · balance open" if partial else ""),
            [evn, "payment"])

    for sig in repo.select("signals", where={"customer_name": name},
                           order_by="created_at", desc=False):
        created = _d(sig.get("created_at"))
        stype = sig.get("signal_type", "")
        num = sig.get("related_invoice") or ""
        summary = (sig.get("summary") or "").strip()
        num_pfx = f"{num} · " if num else ""
        if stype == "payment_promise":
            promised = _d(sig.get("promised_date"))
            amt = _money(sig.get("promised_amount"))
            if created:
                _ev(created.isoformat(), "promise", "Payment promise made",
                    (summary or (f"${amt:,.2f} by {promised.isoformat()}" if promised else "")),
                    [num or "promise", "promise"])
            if promised:
                if promised < today:
                    _ev(promised.isoformat(), "promise", "Promised date passed",
                        f"promised ${amt:,.2f}" if amt else "", [num or "promise", "promise"])
                else:
                    _ev(promised.isoformat(), "promise", "Payment promised",
                        f"${amt:,.2f} expected" if amt else "", [num or "promise", "promise"])
        elif stype in ("approval_pending", "wrong_po", "missing_invoice",
                       "documentation_request", "payment_confirmation", "dispute", "bounced_email"):
            title = {
                "approval_pending": f"{num_pfx}Approval pending",
                "wrong_po": f"{num_pfx}PO mismatch flagged",
                "missing_invoice": f"{num_pfx}Invoice reportedly not received",
                "documentation_request": f"{num_pfx}Documents requested",
                "payment_confirmation": f"{num_pfx}Payment reported sent",
                "dispute": f"{num_pfx}Dispute raised",
                "bounced_email": f"{num_pfx}Email bounced",
            }.get(stype, f"{num_pfx}{stype}")
            kind = {"approval_pending": "approval",
                    "dispute": "dispute",
                    "payment_confirmation": "payment"}.get(stype, "invoice_issue")
            _ev(created.isoformat(), kind, title, summary or stype, [num or "issue", stype])
        elif created:
            kind = "email" if not sig.get("resolved") else "contact"
            _ev(created.isoformat(), kind,
                summary or stype or "signal",
                (f"{stype} · resolved" if sig.get("resolved") else stype),
                [stype or "signal", "email" if not sig.get("resolved") else "contact"])

    for fu in repo.select("followups", where={"customer_name": name},
                          order_by="created_at", desc=False):
        if fu.get("draft_type") in (None, "", "none"):
            continue
        created = _d(fu.get("created_at"))
        if not created:
            continue
        st = fu.get("status", "draft")
        sent = st in ("sent", "approved", "copied")
        is_reminder = ("reminder" in str(fu.get("draft_type", ""))
                       or "overdue" in str(fu.get("draft_type", "")))
        kind = "email" if sent else ("reminder" if is_reminder else "email")
        _ev(created.isoformat(), kind,
            f"{'Follow-up sent' if sent else 'Follow-up prepared'} · {fu.get('draft_type', '')}",
            fu.get("subject", ""),
            ["followup", str(fu.get("draft_type", ""))])

    for st in repo.select("actions_queue", where={"customer_name": name}):
        contacted = _d(st.get("contacted_at"))
        if contacted:
            _ev(contacted.isoformat(), "contact", "Marked contacted",
                (st.get("note") or "team updated the account"), ["contact"])
        created = _d(st.get("created_at"))
        override = (st.get("owner_override") or "").strip()
        if override and created:
            _ev(created.isoformat(), "owner", f"Owner assigned manually · {override}",
                "manual override of the engine-assigned owner", ["owner"])
        pause_at = _d(st.get("created_at")) if st.get("paused") else None
        if pause_at:
            _ev(pause_at.isoformat(), "pause", "Chasing paused",
                (st.get("paused_reason") or "no reason recorded")
                + (f" · until {st.get('paused_until')}" if st.get("paused_until") else " · indefinite"),
                ["pause", "control"])
        next_act = (st.get("next_action_override") or "").strip()
        if next_act and created:
            _ev(created.isoformat(), "action", "Next action changed by the team",
                next_act, ["control", "action"])

    events.sort(key=lambda e: e["date"])
    return events


# ---------------------------------------------------------------------------
# 5.5 Can't-pay vs won't-pay posture + "where is this stuck?" diagnosis
# ---------------------------------------------------------------------------

def payment_posture(repo: Any, item: dict[str, Any],
                    behavior: dict[str, Any] | None = None) -> dict[str, Any]:
    """Can't pay vs won't pay vs a process problem (customer-level).

    Evidence-based only. Every posture carries a confidence (how strongly the
    stored facts support it) and an evidence_status (KNOWN / INFERRED /
    UNKNOWN). Labels state facts, not judgements:
      - 'process_problem' when a fixable blocker is open (PO / approval / docs /
        missing invoice / bounce / dispute) - that is NOT payment resistance.
      - 'unable_to_pay' only from the customer's OWN cash-flow wording or
        recorded instalment behaviour (never from the tone of an email).
      - 'commitment_risk' only from missed promises or accepted-but-ignored
        invoices (repeated missed dates / radio silence).
      - 'collectable' when a dated commitment is on file (facts, not optimism).
      - everything else is 'unable_to_determine'.
    """
    behavior = behavior or payment_behavior(repo, item["customer_name"])
    by_type = set(item.get("open_signal_types") or [])
    promise = item.get("promise") or {}
    overdue = float(item.get("overdue_amount") or 0) > 0
    last_response = item.get("last_response_days")

    process = by_type & (_PROCESS_BLOCKERS | {"dispute"})
    if process:
        labels = [_BLOCKER_LABELS.get(t, t.replace("_", " ")) for t in sorted(process)]
        return {
            "posture": "process_problem",
            "label": "Blocked on a process item",
            "reasons": [f"open blocker: {', '.join(labels)}"],
            "confidence": 0.9,
            "evidence_status": "KNOWN",
        }

    cash = _cash_flow_hit(repo, item["customer_name"])
    instalments = behavior.get("partial_payments") or 0
    if cash or instalments:
        reasons: list[str] = []
        if cash:
            reasons.append(f'their own words: "{cash}"')
        if instalments:
            reasons.append(f"{instalments} invoice(s) paid in instalments")
        return {
            "posture": "unable_to_pay",
            "label": "Cash-flow constrained (their words, not ours)",
            "reasons": reasons,
            "confidence": 0.9 if cash else 0.75,
            "evidence_status": "KNOWN" if cash else "INFERRED",
        }

    missed = behavior.get("promises_missed") or 0
    if missed or (overdue and last_response is not None and last_response >= 14):
        reasons = []
        if missed:
            reasons.append(f"{missed} missed promise(s) on file")
        if overdue and last_response is not None and last_response >= 14:
            reasons.append(f"no response for {last_response} day(s) on an accepted invoice")
        return {
            "posture": "commitment_risk",
            "label": "Commitment at risk (missed dates / radio silence)",
            "reasons": reasons,
            "confidence": 0.8 if missed else 0.55,
            "evidence_status": "KNOWN" if missed else "INFERRED",
        }

    if promise.get("status") in ("upcoming", "due_today"):
        return {
            "posture": "collectable",
            "label": "Committed payment date on file",
            "reasons": [f"open promise for {promise.get('promised_date') or 'a confirmed date'}"],
            "confidence": 0.75,
            "evidence_status": "KNOWN",
        }

    return {
        "posture": "unable_to_determine",
        "label": "Unable to determine",
        "reasons": ["not enough evidence to say can-pay, can't-pay, or unwilling"],
        "confidence": 0.3,
        "evidence_status": "UNKNOWN",
    }


def stuck_diagnosis(item: dict[str, Any], wl: dict[str, Any],
                    readiness: dict[str, Any],
                    pre_due: dict[str, Any]) -> dict[str, Any]:
    """'WHERE IS THIS INVOICE STUCK?' - current stage, blocker, evidence,
    confidence and next action. Each step exists only when a stored fact says
    so; when there's no evidence the answer is 'unknown', never a guess."""
    by_type = set(item.get("open_signal_types") or [])
    promise = item.get("promise") or {}
    p_status = promise.get("status")
    sig = item.get("latest_signal") or {}
    evidence = (sig.get("summary") or "").strip() or None
    evidence_date = sig.get("created_at") or None

    def _out(stage: str, blocker: str | None, where: str, confidence: str,
             next_action: str | None = None) -> dict[str, Any]:
        return {
            "current_stage": stage,
            "blocker": blocker,
            "where": where,
            "evidence": evidence,
            "evidence_date": evidence_date,
            "confidence": confidence,
            "next_action": next_action or item.get("action_label", ""),
        }

    if by_type & {"dispute"}:
        return _out("Dispute resolution", "disputed charge unresolved",
                    "dispute", "high")
    if by_type & {"approval_pending"}:
        return _out("Customer approval", "awaiting internal approval",
                    "approval", "high")
    if by_type & {"wrong_po"}:
        return _out("PO / reference", "PO mismatch on the invoice",
                    "PO mismatch", "high")
    if by_type & {"missing_invoice"}:
        return _out("Delivery", "customer says the invoice never arrived",
                    "invoice not received", "high")
    if by_type & {"documentation_request"}:
        return _out("Documentation", "customer still needs documents",
                    "documents", "high")
    if by_type & {"bounced_email"}:
        return _out("Contact", "email unreachable (bounced)",
                    "wrong contact", "high")
    if p_status == "overdue":
        return _out("Payment commitment", "promised date was missed",
                    "missed promise", "high",
                    next_action="Follow up on the missed promise")
    if by_type & {"payment_confirmation"}:
        return _out("Reconciliation",
                    "customer reports payment sent - not yet matched",
                    "verify payment", "high",
                    next_action="Verify the payment against the bank feed")
    if pre_due.get("needed"):
        return _out("Pre-due readiness",
                    "receipt / PO / approval not confirmed before the due date",
                    "pre-due unconfirmed", "medium",
                    next_action="Confirm payment readiness before it goes overdue")
    if float(item.get("overdue_amount") or 0) > 0:
        respond = item.get("last_response_days")
        if respond is not None and respond >= 14:
            return _out("Collections", f"no customer response for {respond} day(s)",
                        "unresponsive", "medium")
        return _out("Collections", "payment due with no firm date",
                    "payment due", "medium")
    if p_status in ("due_today", "upcoming"):
        return _out("Payment commitment", None, "on track - promised",
                    "high", next_action="Monitor the promise")
    return _out("No known blocker", None, "none known", "low",
                next_action="Monitor the open balance")


def action_category_for(item: dict[str, Any]) -> dict[str, str]:
    cat = _ACTION_CATEGORY.get(item.get("action", ""), "collection")
    return {"category": cat, "label": _CATEGORY_LABELS[cat]}


# ---------------------------------------------------------------------------
# 6. Invoice readiness & collectability (evidence checklist)
# ---------------------------------------------------------------------------

def invoice_readiness(repo: Any, item: dict[str, Any]) -> dict[str, Any]:
    """Is this invoice ready to collect, blocked, or a collection risk?

    Classification is built ONLY from stored evidence - a stated blocker, an
    open dispute, a promise, a payment confirmation. Anything without proof is
    "unknown". The system never deems an invoice uncollectable based on tone.
    """
    by_type = set(item.get("open_signal_types") or [])
    promise = item.get("promise") or {}
    p_status = promise.get("status")
    name = item["customer_name"]

    # proof the customer has actually seen/received an invoice: they quoted an
    # invoice number in a message (a bounce does NOT prove receipt).
    referenced = any(
        (s.get("related_invoice") or "").strip()
        for s in repo.select("signals", where={"customer_name": name, "resolved": False})
        if (s.get("signal_type") or "") != "bounced_email"
    )

    checks: list[dict[str, str]] = []

    def _c(label: str, state: str) -> None:
        checks.append({"label": label, "state": state})

    _c("Invoice sent / delivered", "blocked" if "missing_invoice" in by_type else "ok")
    _c("Contact address works", "blocked" if "bounced_email" in by_type else "ok")
    _c("Invoice receipt confirmed",
       "blocked" if "missing_invoice" in by_type else ("ok" if referenced else "unknown"))
    _c("PO / purchase reference in place",
       "blocked" if "wrong_po" in by_type else "unknown")
    _c("Accepted / approved for payment",
       "blocked" if "dispute" in by_type
       else ("ok" if ("payment_confirmation" in by_type or promise) else "unknown"))
    _c("No dispute open", "blocked" if "dispute" in by_type else "ok")
    _c("No billing / documentation error",
       "blocked" if bool(by_type & {"missing_invoice", "wrong_po",
                                     "documentation_request"}) else "ok")
    _c("Correction requested by customer",
       "ok" if (by_type & {"documentation_request", "wrong_po"}) or "dispute" in by_type
       else "unknown")
    _c("Payment promise on file", "ok" if promise else "unknown")
    _c("Payment reported in transit", "ok" if "payment_confirmation" in by_type else "unknown")

    blocked_by = sorted(by_type & _PROCESS_BLOCKERS)
    if blocked_by:
        status = "blocked"
        label = "Invoice Blocked"
        tone = "red"
        summary = "Payment is being held by a process item: " + ", ".join(
            _BLOCKER_LABELS[b] for b in blocked_by
        ) + "."
    elif "dispute" in by_type or p_status == "overdue":
        status = "risk"
        label = "Collection Risk"
        tone = "amber"
        summary = ("Collection risk - the charge is disputed or a confirmed "
                   "commitment was missed.")
    elif "payment_confirmation" in by_type or p_status in ("due_today", "upcoming"):
        status = "collectable"
        label = "Ready to Collect"
        tone = "green"
        summary = "No blockers and a confirmed commitment on file."
    else:
        status = "unknown"
        label = "Payment Readiness Unknown"
        tone = "blue"
        summary = "No evidence yet about AP receipt, PO or approval."

    return {
        "status": status,
        "label": label,
        "tone": tone,
        "summary": summary,
        "blocker": ", ".join(_BLOCKER_LABELS[b] for b in blocked_by) or None,
        "checks": checks,
    }


def pre_due_readiness(repo: Any, item: dict[str, Any]) -> dict[str, Any]:
    """For invoices approaching the due date with NO proof of receipt / AP /
    approval / PO: recommend a non-aggressive 'confirm payment readiness' note."""
    today = _DATE.today()
    name = item["customer_name"]
    first = (name.split()[0] if name.split() else "there")
    by_type = set(item.get("open_signal_types") or [])
    overdue = float(item.get("overdue_amount") or 0) > 0

    nearest = None
    for inv in repo.select("invoices", where={"customer_name": name}):
        if inv.get("status") == "paid":
            continue
        due = _d(inv.get("due_date"))
        if not due:
            continue
        gap = (due - today).days
        if 0 <= gap <= 7:
            if nearest is None or gap < nearest[0]:
                nearest = (gap, inv)

    needed = bool(
        nearest
        and not overdue
        and "payment_confirmation" not in by_type
        and "dispute" not in by_type
        and not (by_type & _PROCESS_BLOCKERS)
    )
    if not nearest:
        needed = False

    if not needed:
        return {
            "needed": False,
            "invoice_number": "",
            "amount": 0.0,
            "due_in_days": 0,
            "email_example": "",
            "checklist": [],
            "check_label": "",
        }

    gap, inv = nearest
    amt = _money(inv.get("amount_outstanding"))
    num = inv.get("invoice_number", "")

    # KNOWN/UNKNOWN/INFERRED pre-due checklist for the upcoming invoice:
    # each row is only 'ok' (KNOWN) when a stored fact supports it.
    open_sigs = repo.select("signals", where={"customer_name": name, "resolved": False})
    referenced = any(
        (s.get("related_invoice") or "") == num
        and (s.get("signal_type") or "") != "bounced_email"
        for s in open_sigs
    )
    promise = any(
        (s.get("related_invoice") or "") == num
        and s.get("signal_type") == "payment_promise"
        for s in open_sigs
    )
    checklist = [
        {
            "step": "Invoice sent",
            "state": "ok",
            "note": "invoice is on file",
            "kind": "KNOWN",
        },
        {
            "step": "Receipt confirmed",
            "state": "ok" if referenced else "unknown",
            "note": ("customer referenced the invoice" if referenced
                     else "no proof the customer received it"),
            "kind": "KNOWN" if referenced else "UNKNOWN",
        },
        {
            "step": "PO / reference",
            "state": "blocked" if "wrong_po" in by_type else "unknown",
            "note": ("PO mismatch flagged" if "wrong_po" in by_type
                     else "no PO confirmation on file"),
            "kind": "KNOWN" if "wrong_po" in by_type else "UNKNOWN",
        },
        {
            "step": "Approval confirmed",
            "state": (("ok" if ("payment_confirmation" in by_type or promise) else "unknown")),
            "note": ("approved / committed" if ("payment_confirmation" in by_type or promise)
                     else "no approval evidence on file"),
            "kind": "KNOWN" if ("payment_confirmation" in by_type or promise) else "UNKNOWN",
        },
    ]
    if "approval_pending" in by_type:
        checklist[3] = {
            "step": "Approval confirmed",
            "state": "blocked",
            "note": "customer is awaiting internal approval",
            "kind": "KNOWN",
        }
    missing = [c for c in checklist if c["state"] == "unknown"]
    blocked = [c for c in checklist if c["state"] == "blocked"]
    if blocked:
        check_label = "BLOCKED"
    elif missing:
        check_label = "PARTIALLY UNKNOWN"
    else:
        check_label = "READY"

    return {
        "needed": True,
        "invoice_number": num,
        "amount": amt,
        "due_in_days": gap,
        "checklist": checklist,
        "check_label": check_label,
        "email_example": (
            f"Hi {first},\n\n"
            f"Quick check on invoice {num}"
            + (f" for ${amt:,.2f}" if amt else "")
            + f" - it's due on {inv.get('due_date', '')}.\n\n"
            "Could you confirm it's been received and is scheduled for "
            "payment? If anything is still needed from us (a PO, approval "
            "details or an invoice copy), just say the word and we'll sort it.\n\n"
            "A quick 'confirmed' reply is all we need. Thanks!"
        ),
    }


def decision_order_for(item: dict[str, Any], readiness: dict[str, Any],
                       pre_due: dict[str, Any], group: str) -> str:
    """Prioritisation principle A-F."""
    if readiness["status"] == "blocked" or group == "process_blocked":
        return "A"
    if pre_due.get("needed"):
        return "B"
    promise_status = (item.get("promise") or {}).get("status")
    if promise_status == "overdue" or group == "at_risk":
        return "D"
    if group == "unable":
        return "E"
    if float(item.get("overdue_amount") or 0) > 0:
        return "C"
    return "F"


def ownership_for(item: dict[str, Any], readiness: dict[str, Any] | None = None) -> dict[str, Any]:
    """What / who / why / when / evidence for a recommended action - assignable.

    The engine assigns an owner from the action type; the team can override it
    per customer (persisted as owner_override in actions_queue) and the override
    is surfaced as `manual: true` so it is always clear who chose the owner.
    """
    rdn = readiness or item.get("readiness", {})
    override = (item.get("owner_override") or "").strip()
    if override:
        who, manual, why = override, True, "assigned manually by the team"
    else:
        who = _OWNER_BY_ACTION.get(item.get("action", ""), "AR Ops + Collections")
        if rdn.get("status") == "blocked":
            who = "AR Ops (resolve blocker first)"
        manual, why = False, item.get("reason", "")
    latest = item.get("latest_signal") or {}
    return {
        "what": item.get("action_label", ""),
        "who": who,
        "why": why,
        "when": item.get("suggested_follow_up_date", ""),
        "evidence": (latest.get("summary") or "").strip() or item.get("reason", ""),
        "manual": manual,
        "override_value": who if manual else "",
    }


# ---------------------------------------------------------------------------
# 7. Action-item enrichment (cheap blocks for the queue / detail views)
# ---------------------------------------------------------------------------

# Exception-based queue: what makes this account exceptional vs the routine
# norm ("cash is overdue, send reminders"). Groups are listed highest urgency
# first; the queue UI renders them as sections.
_EXCEPTION_ORDER = ["missed_promise", "dispute", "blocked", "verify",
                    "pre_due", "no_response", "overdue", "question", "routine"]

_EXCEPTION_LABELS = {
    "missed_promise": "Missed promise",
    "dispute": "Dispute resolution",
    "blocked": "Blocked in their process",
    "verify": "Verify reported payment",
    "pre_due": "Confirm before due",
    "no_response": "Overdue · no response",
    "overdue": "Overdue cash",
    "question": "Question / info request",
    "routine": "Routine",
}


def exception_group_for(item: dict[str, Any]) -> tuple[str, str]:
    """Classify an account into an exception group (group_key, label)."""
    cat = (item.get("action_category") or {}).get("category")
    promise_status = (item.get("promise") or {}).get("status")
    by_type = set(item.get("open_signal_types") or [])
    if promise_status == "overdue":
        return "missed_promise", _EXCEPTION_LABELS["missed_promise"]
    if cat == "pre_due" or item.get("pre_due", {}).get("needed"):
        return "pre_due", _EXCEPTION_LABELS["pre_due"]
    if cat == "dispute":
        return "dispute", _EXCEPTION_LABELS["dispute"]
    if "payment_confirmation" in by_type:
        return "verify", _EXCEPTION_LABELS["verify"]
    if by_type & {"info_question", "other"}:
        return "question", _EXCEPTION_LABELS["question"]
    if cat == "process":
        return "blocked", _EXCEPTION_LABELS["blocked"]
    if float(item.get("overdue_amount") or 0) > 0:
        lr = item.get("last_response_days")
        if lr is None or lr >= 14:
            return "no_response", _EXCEPTION_LABELS["no_response"]
        return "overdue", _EXCEPTION_LABELS["overdue"]
    return "routine", _EXCEPTION_LABELS["routine"]


def enrich_action_item(repo: Any, item: dict[str, Any]) -> dict[str, Any]:
    """Attach compact blocks to an action-queue item (cheap, fact-based)."""
    behavior = payment_behavior(repo, item["customer_name"])
    intel = collections_intelligence(repo, item["customer_name"], item, behavior)
    strategy = chase_strategy(repo, item)
    item["behavior"] = {
        "reliability_score": behavior["reliability_score"],
        "reliability_label": behavior["reliability_label"],
        "on_time_count": behavior["on_time_count"],
        "late_count": behavior["late_count"],
        "total_payments": behavior["total_payments"],
        "avg_delay_days": behavior["avg_delay_days"],
        "promises_kept": behavior["promises_kept"],
        "promises_count": behavior["promises_count"],
        "promises_kept_percent": behavior["promises_kept_percent"],
        "on_time_percent": behavior["on_time_percent"],
        "partial_payments": behavior["partial_payments"],
        "promise_breakdown": behavior.get("promise_breakdown") or [],
    }
    item["intelligence"] = {
        "max_days_overdue": intel["max_days_overdue"],
        "last_response_days": intel["last_response_days"],
        "paid_late_count": intel["paid_late_count"],
        "open_issue_types": intel["open_issue_types"],
        "risk_reasons": intel["risk_reasons"],
    }
    item["chase"] = {
        "stage": strategy["stage"],
        "stage_label": strategy["stage_label"],
        "tone": strategy["tone"],
        "approach": strategy["approach"],
        "flags": strategy["flags"],
    }
    wl = why_late(repo, item, behavior)
    item["why_late"] = {
        "category": wl["category"],
        "group": wl["group"],
        "group_label": wl["group_label"],
        "label": wl["label"],
        "headline": wl["headline"],
        "recommended": wl["recommended"],
    }
    rdn = invoice_readiness(repo, item)
    pre = pre_due_readiness(repo, item)
    item["readiness"] = rdn
    item["pre_due"] = pre
    item["decision_order"] = decision_order_for(item, rdn, pre, wl["group"])
    item["decision_order_label"] = _DECISION_LABELS.get(item["decision_order"])
    item["action_category"] = action_category_for(item)
    item["posture"] = payment_posture(repo, item, behavior)
    item["stuck"] = stuck_diagnosis(item, wl, rdn, pre)
    item["process"] = {
        "current_stage": item["stuck"]["current_stage"],
        "blocker": item["stuck"]["blocker"],
        "where": item["stuck"]["where"],
        "evidence": item["stuck"]["evidence"],
        "confidence": item["stuck"]["confidence"],
        "next_action": item["stuck"]["next_action"],
    }
    item["ownership"] = ownership_for(item)
    item["amount_x_days"] = round(float(item.get("overdue_amount") or 0)
                                  * float(item.get("max_days_overdue") or 0), 2)
    group, group_label = exception_group_for(item)
    item["exception_group"] = group
    item["exception_label"] = group_label
    return item