"""The "who should I chase today?" engine.

Turns AR ledger + email-derived facts into ONE recommended next action per
customer: what to do, why, how confident we are, when to follow up, and which
follow-up draft type applies.

Facts come from the database (invoices, signals, promises). The recommendation
is INTERPRETATION layered on top - it is never a payment probability and never
invents amounts/dates/statements. If there isn't enough information to say
something useful, the engine says so instead of guessing.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from services.behavior import enrich_action_item
from services.sync import evaluate_promise

# action code -> human label + which followup draft type to prepare
_ACTION_META: dict[str, dict[str, str]] = {
    "MONITOR_PROMISE": {
        "label": "Monitor payment promise - no email needed yet",
        "draft": "none",
    },
    "FOLLOW_UP_IF_UNPAID": {
        "label": "Follow up today if payment was not received",
        "draft": "payment_date_request",
    },
    "FOLLOW_UP_MISSED_PROMISE": {
        "label": "Follow up on missed payment promise",
        "draft": "missed_promise_followup",
    },
    "INVESTIGATE_DISPUTE": {
        "label": "Investigate dispute (confirm disputed line items)",
        "draft": "dispute_clarification",
    },
    "REQUEST_CORRECTED_PO": {
        "label": "Request corrected PO from customer",
        "draft": "po_correction_request",
    },
    "REQUEST_APPROVAL_STATUS": {
        "label": "Check approval status with customer",
        "draft": "approval_pending_followup",
    },
    "RESEND_INVOICE": {
        "label": "Resend invoice to customer",
        "draft": "missing_invoice_response",
    },
    "PROVIDE_DOCUMENTS": {
        "label": "Prepare / provide requested documents",
        "draft": "documentation_response",
    },
    "FIND_ALTERNATE_CONTACT": {
        "label": "Find alternate contact (email bounced)",
        "draft": "none",
    },
    "VERIFY_PAYMENT": {
        "label": "Verify payment / mark for reconciliation",
        "draft": "none",
    },
    "REPLY_TO_QUESTION": {
        "label": "Review and reply to customer message",
        "draft": "friendly_reminder",
    },
    "CONFIRM_PAYMENT_READINESS": {
        "label": "Confirm payment readiness before the due date",
        "draft": "payment_readiness_confirmation",
    },
    "FOLLOW_UP": {
        "label": "Send follow-up",
        "draft": "overdue_reminder",
    },
    "ESCALATE": {
        "label": "Escalate follow-up",
        "draft": "escalation_notice",
    },
}

_ISSUE_LABELS = {
    "dispute": "disputed charge",
    "missing_invoice": "customer says they did not receive the invoice",
    "wrong_po": "PO mismatch on the invoice",
    "documentation_request": "customer needs documentation before paying",
    "payment_confirmation": "customer reports payment sent",
    "bounced_email": "email to customer bounced",
    "info_question": "customer asked a question",
    "payment_promise": "payment promise",
    "approval_pending": "customer is awaiting internal approval",
}


def _add(reasons: list[str], text: str, weight: int,
         score: list[int], cap: int | None = None) -> None:
    if weight:
        reasons.append(text)
        score[0] += weight


def _band(score: int) -> str:
    if score >= 70:
        return "critical"
    if score >= 48:
        return "high"
    if score >= 28:
        return "medium"
    return "low"


def _first_name(name: str) -> str:
    parts = (name or "").split()
    return parts[0] if parts else "there"


def _money(x: Any) -> float:
    try:
        return round(float(x or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def customer_facts(repo: Any, customer_name: str) -> dict[str, Any]:
    """Aggregate every fact we have about one customer (DB-only, no AI)."""
    today = dt.date.today()
    invoices = repo.select("invoices", where={"customer_name": customer_name})
    # paid invoices are no longer money they owe us - exclude them from risk
    open_invoices = [i for i in invoices if i.get("status") != "paid"]
    signals = repo.select("signals", where={"customer_name": customer_name})

    emails = {inv.get("contact_email", "").lower() for inv in invoices if inv.get("contact_email")}
    messages = repo.select("messages", order_by="received_at", desc=True)
    now = dt.datetime.now(dt.timezone.utc)
    last_msg_at: str | None = None
    for m in messages:
        fe = (m.get("from_email") or "").lower()
        if fe in emails:
            last_msg_at = m.get("received_at") or None
            break
        if fe and "@" in fe:
            dom = fe.split("@")[-1]
            if any(e.split("@")[-1] == dom for e in emails):
                last_msg_at = m.get("received_at") or None
                break

    open_signals = [s for s in signals if not s.get("resolved")]
    promises = [
        s for s in open_signals
        if s.get("signal_type") == "payment_promise" and s.get("promised_date")
    ]
    if promises:
        promises.sort(key=lambda s: s.get("created_at") or "", reverse=True)
    promise = promises[0] if promises else None

    latest_sig: dict | None = None
    if signals:
        latest_sig = max(signals, key=lambda s: s.get("created_at") or "")

    overdue = [i for i in open_invoices if _days_late(i.get("due_date"), today) > 0]
    overdue_amount = round(sum(_money(i.get("amount_outstanding")) for i in overdue), 2)
    max_days = max([_days_late(i.get("due_date"), today) for i in overdue]) if overdue else 0

    due_7 = []
    for i in open_invoices:
        d = i.get("due_date")
        if not d:
            continue
        try:
            gap = (dt.date.fromisoformat(d) - today).days
        except ValueError:
            continue
        if 0 <= gap <= 7:
            due_7.append(i)
    due_7_amount = round(sum(_money(i.get("amount_outstanding")) for i in due_7), 2)

    approaching_due = []
    for i in open_invoices:
        d = i.get("due_date")
        if not d:
            continue
        try:
            gap = (dt.date.fromisoformat(d) - today).days
        except ValueError:
            continue
        if 0 <= gap <= 7:
            approaching_due.append((gap, i))
    approaching_due.sort(key=lambda x: x[0])
    days_to_nearest_due = approaching_due[0][0] if approaching_due else None
    nearest_upcoming_invoice = (
        approaching_due[0][1] if approaching_due else None
    )

    last_response_days: int | None = None
    if latest_sig and latest_sig.get("created_at"):
        try:
            ts = dt.datetime.fromisoformat(str(latest_sig["created_at"]).replace("Z", "+00:00"))
            last_response_days = max(0, (now - ts).days)
        except ValueError:
            pass

    by_type: dict[str, list[dict]] = {}
    for s in open_signals:
        by_type.setdefault(s.get("signal_type", "other"), []).append(s)

    unconfirmed = {
        "total_outstanding": round(sum(_money(i.get("amount_outstanding")) for i in open_invoices), 2),
        "overdue_amount": overdue_amount,
        "max_days_overdue": max_days,
        "overdue_invoice_count": len(overdue),
        "invoice_count": len(open_invoices),
        "due_this_week_amount": due_7_amount,
        "days_to_nearest_due": days_to_nearest_due,
        "nearest_upcoming_invoice": nearest_upcoming_invoice,
        "open_signals": open_signals,
        "signals_by_type": by_type,
        "latest_signal": latest_sig,
        "promise": promise,
        "promise_status": evaluate_promise(promise) if promise else None,
        "promise_days_late": max(0, (dt.date.today() - dt.date.fromisoformat(promise["promised_date"])).days)
        if promise and promise.get("promised_date") else 0,
        "contract_emails": sorted(emails),
        "last_response_days": last_response_days,
    }

    if len(open_invoices) == 1:
        unconfirmed["primary_invoice"] = open_invoices[0]
    elif open_invoices:
        heaviest = max(open_invoices, key=lambda i: _money(i.get("amount_outstanding")))
        unconfirmed["primary_invoice"] = heaviest
    else:
        unconfirmed["primary_invoice"] = None
    return unconfirmed


def _days_late(due: str | None, today: dt.date) -> int:
    if not due:
        return 0
    try:
        return (today - dt.date.fromisoformat(due)).days
    except ValueError:
        return 0


def decide_action(facts: dict[str, Any]) -> dict[str, Any]:
    """Pick the single recommended action from the fact set (deterministic rules)."""
    overdue = facts["overdue_amount"] > 0
    promise = facts["promise"]
    by_type = facts["signals_by_type"]

    def _pick(code: str, reason: str, confidence: float,
              suggested: str | None = None, draft: str | None = None) -> dict:
        meta = _ACTION_META[code]
        return {
            "action": code,
            "action_label": meta["label"],
            "draft_type": draft or meta["draft"],
            "reason": reason,
            "confidence": round(min(0.9, max(0.4, confidence)), 2),
            "suggested_follow_up_date": suggested or dt.date.today().isoformat(),
        }

    if facts.get("promise_status") == "overdue":
        # refunds upward: missed promise is the strongest trigger
        return _pick(
            "FOLLOW_UP_MISSED_PROMISE",
            f"Payment was promised for {facts['promise']['promised_date']} "
            f"({facts['promise_days_late']} day(s) ago) and is still open.",
            confidence=0.85,
            suggested=facts["promise"]["promised_date"],
        )

    if facts.get("promise_status") == "due_today":
        return _pick(
            "FOLLOW_UP_IF_UNPAID",
            "Customer promised to pay today. Confirm receipt or follow up if not received.",
            confidence=0.75,
            suggested=dt.date.today().isoformat(),
        )

    if by_type.get("bounced_email"):
        return _pick(
            "FIND_ALTERNATE_CONTACT",
            "The customer's email bounced - the last message never reached them.",
            confidence=0.9,
            draft="none",
        )

    if by_type.get("dispute"):
        return _pick(
            "INVESTIGATE_DISPUTE",
            "Customer disputes the charge. Confirm which line item and whether "
            "there's an undisputed balance to collect.",
            confidence=0.85,
            draft="dispute_clarification",
        )

    if by_type.get("approval_pending"):
        return _pick(
            "REQUEST_APPROVAL_STATUS",
            "Customer is waiting on internal approval before they can pay - "
            "check where it sits in their approval queue and what is still "
            "needed from us.",
            confidence=0.82,
            draft="approval_pending_followup",
        )

    if by_type.get("wrong_po"):
        return _pick(
            "REQUEST_CORRECTED_PO",
            "Customer flagged a PO mismatch - get the correct PO before payment can process.",
            confidence=0.8,
            draft="po_correction_request",
        )

    if by_type.get("documentation_request"):
        return _pick(
            "PROVIDE_DOCUMENTS",
            "Customer needs documentation before they can pay.",
            confidence=0.8,
            draft="documentation_response",
        )

    if by_type.get("missing_invoice"):
        return _pick(
            "RESEND_INVOICE",
            "Customer says they never received the invoice.",
            confidence=0.85,
            draft="missing_invoice_response",
        )

    if by_type.get("payment_confirmation"):
        return _pick(
            "VERIFY_PAYMENT",
            "Customer reports payment sent - verify against the bank feed and reconcile.",
            confidence=0.8,
            draft="none",
        )

    if by_type.get("info_question"):
        return _pick(
            "REPLY_TO_QUESTION",
            "Customer asked a question - reply with the requested information.",
            confidence=0.7,
            draft="friendly_reminder",
        )

    # pre-due payment readiness: invoices due within the next 7 days where
    # receipt / AP confirmation / approval / PO is still unproven. A short
    # confirmation note is cheaper than a late-discovery after it goes overdue.
    if facts["days_to_nearest_due"] is not None and not facts["overdue_amount"] > 0:
        nearest = facts["nearest_upcoming_invoice"] or {}
        num = nearest.get("invoice_number", "")
        amt = _money(nearest.get("amount_outstanding"))
        return _pick(
            "CONFIRM_PAYMENT_READINESS",
            f"Invoice {num} (${amt:,.2f}) is due in {facts['days_to_nearest_due']} day(s) "
            "with no receipt, AP approval or PO confirmation on file - confirm it is "
            "scheduled for payment before it goes overdue.",
            confidence=0.7,
            suggested=dt.date.today().isoformat(),
            draft="payment_readiness_confirmation",
        )

    if promise and facts["promise_status"] == "upcoming":
        return _pick(
            "MONITOR_PROMISE",
            f"Customer promised to pay by {facts['promise']['promised_date']} - "
            "within the agreed window, no action needed yet.",
            confidence=0.65,
            suggested=facts["promise"]["promised_date"],
            draft="none",
        )

    if overdue:
        respond = facts["last_response_days"]
        days = facts["max_days_overdue"]
        if (respond is not None and respond >= 14) or days >= 45:
            return _pick(
                "ESCALATE",
                f"{days} day(s) overdue" +
                (f" with no customer response for {respond} day(s)" if respond is not None and respond >= 14 else "")
                + " - escalate this account.",
                confidence=0.8,
                draft="escalation_notice",
            )
        if days <= 7:
            return _pick(
                "FOLLOW_UP",
                f"Invoice is {days} day(s) past due. Send a gentle reminder.",
                confidence=0.7,
                draft="friendly_reminder",
            )
        return _pick(
            "FOLLOW_UP",
            f"Invoice is {days} day(s) past due with no firm payment date from the customer.",
            confidence=0.75,
            draft="overdue_reminder",
        )

    if facts["invoice_count"] == 0:
        return _pick("MONITOR_PROMISE", "No open invoices on file for this customer.",
                     confidence=0.4, draft="none")

    # invoices exist but none due yet and nothing actionable
    return _pick(
        "REPLY_TO_QUESTION",
        "No overdue invoices and no open issues - nothing to do right now.",
        confidence=0.5,
        draft="none",
    )


def priority_for(facts: dict[str, Any]) -> dict[str, Any]:
    """Explainable 0-100 priority -> CRITICAL/HIGH/MEDIUM/LOW plus the WHY.

    This is a collections-priority score (who to chase first), NOT a payment
    probability. Weights are simple and transparent on purpose.
    """
    score = [0]
    reasons: list[str] = []

    amount = facts["overdue_amount"]
    if amount > 0:
        w = min(20, round(amount / 1000))
        _add(reasons, f"${amount:,.2f} overdue", w, score)
    else:
        _add(reasons, "No overdue balance", -15, score, cap=0)

    days = facts["max_days_overdue"]
    if days > 0:
        w = min(30, round(days * 0.8))
        _add(reasons, f"Overdue for {days} day(s)", w, score)

    if facts["overdue_invoice_count"] > 1:
        _add(reasons, f"{facts['overdue_invoice_count']} invoices overdue",
             min(10, facts["overdue_invoice_count"] * 3), score)

    if facts["promise_status"] == "overdue":
        _add(reasons, "Missed a promised payment date", 22, score)
    elif facts["promise_status"] == "due_today":
        _add(reasons, "Payment promised today", 6, score)
    elif facts["promise_status"] == "upcoming":
        _add(reasons, f"Active promise to pay on {facts['promise']['promised_date']}",
             -18, score)

    for issue, weight in (("dispute", 25), ("bounced_email", 18),
                          ("missing_invoice", 12), ("wrong_po", 10),
                          ("documentation_request", 8), ("approval_pending", 8)):
        if facts["signals_by_type"].get(issue):
            _add(reasons, f"Open issue: {_ISSUE_LABELS[issue]}", weight, score)

    respond = facts["last_response_days"]
    if facts["overdue_amount"] > 0 and (respond is None or respond > 7):
        _add(reasons, "No customer response within the last week", 12, score)

    if facts["signals_by_type"].get("payment_confirmation"):
        _add(reasons, "Customer recently confirmed payment", -10, score)

    if facts["signals_by_type"].get("info_question"):
        _add(reasons, "Customer reached out with a question", -5, score)

    score[0] = max(0, min(100, score[0]))
    return {"priority": _band(score[0]), "priority_score": score[0],
            "priority_reasons": reasons or ["No strong risk factors found"]}


def build_action_item(repo: Any, customer_name: str,
                      queue_state: dict | None = None) -> dict[str, Any]:
    facts = customer_facts(repo, customer_name)
    decision = decide_action(facts)
    prio = priority_for(facts)
    primary = facts["primary_invoice"]

    latest = facts["latest_signal"]
    latest_signal_view = None
    if latest:
        source_body = ""
        source = {}
        if latest.get("message_id"):
            hits = repo.select("messages", where={"message_id": latest["message_id"]},
                               limit=1)
            if hits:
                source_body = hits[0].get("body", "")
                source = {
                    "subject": hits[0].get("subject", ""),
                    "from_email": hits[0].get("from_email", ""),
                    "from_name": hits[0].get("from_name", ""),
                    "received_at": hits[0].get("received_at"),
                }
        latest_signal_view = {
            "signal_type": latest.get("signal_type", "other"),
            "summary": latest.get("summary", ""),
            "created_at": latest.get("created_at"),
            "priority": latest.get("priority", "medium"),
            "resolved": bool(latest.get("resolved")),
            "source_email_body": source_body,
            "source_email": source,
        }

    item = {
        "customer_name": customer_name,
        "customer_email": facts["contract_emails"][0] if facts["contract_emails"] else "",
        "customer_first": _first_name(customer_name),
        "total_outstanding": facts["total_outstanding"],
        "overdue_amount": facts["overdue_amount"],
        "max_days_overdue": facts["max_days_overdue"],
        "due_this_week_amount": facts["due_this_week_amount"],
        "invoice_count": facts["invoice_count"],
        "overdue_invoice_count": facts["overdue_invoice_count"],
        "primary_invoice_number": primary.get("invoice_number", "") if primary else "",
        "primary_invoice_id": primary.get("id", "") if primary else "",
        "open_signal_count": len(facts["open_signals"]),
        "open_signal_types": sorted({
            s.get("signal_type") for s in facts["open_signals"] if s.get("signal_type")
        }),
        "latest_signal": latest_signal_view,
        "last_response_days": facts["last_response_days"],
        "promise": {
            "promised_date": facts["promise"]["promised_date"] if facts["promise"] else None,
            "promised_amount": facts["promise"].get("promised_amount") if facts["promise"] else None,
            "status": facts["promise_status"],
            "days_late": facts["promise_days_late"],
            "related_invoice": facts["promise"].get("related_invoice", "") if facts["promise"] else "",
        } if facts["promise"] else None,
        # recommendation block (AI interpretation)
        "action": decision["action"],
        "action_label": decision["action_label"],
        "reason": decision["reason"],
        "recommendation_confidence": decision["confidence"],
        "suggested_follow_up_date": decision["suggested_follow_up_date"],
        "draft_type": decision["draft_type"],
        "priority": prio["priority"],
        "priority_score": prio["priority_score"],
        "priority_reasons": prio["priority_reasons"],
        # work-queue state (how the team has handled this account)
        "status": "active",
        "snoozed_until": None,
        "last_contacted_at": None,
        "contact_note": "",
        "owner_override": "",
        "paused": False,
        "paused_until": None,
        "paused_reason": "",
        "next_action_override": "",
    }
    if queue_state:
        item.update({
            "status": queue_state.get("status", "active"),
            "snoozed_until": queue_state.get("snoozed_until"),
            "last_contacted_at": queue_state.get("contacted_at"),
            "contact_note": queue_state.get("note", ""),
            "owner_override": queue_state.get("owner_override", ""),
            "paused": bool(queue_state.get("paused")),
            "paused_until": queue_state.get("paused_until"),
            "paused_reason": queue_state.get("paused_reason", ""),
            "next_action_override": queue_state.get("next_action_override", ""),
        })
    return item


_PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def requires_attention(item: dict) -> bool:
    """Is this customer someone you should act on today?

    A customer "requires attention" if they carry an overdue balance or an
    unresolved issue (mistake on the invoice, a dispute, a bounce, a missed
    promise, etc.). Purely future invoices with nothing wrong - the normal part
    of a ledger - are not chase-worthy and stay out of the Action Queue.
    """
    if item.get("overdue_amount", 0) > 0:
        return True
    if item.get("overdue_invoice_count", 0) > 0:
        return True
    signal_types = set(item.get("open_signal_types") or [])
    issue = {"dispute", "bounced_email", "missing_invoice", "wrong_po",
             "documentation_request", "payment_confirmation", "approval_pending"}
    if signal_types & issue:
        return True
    # invoices approaching due with unproven AP/receipt - confirm before it
    # silently goes overdue (readiness/pre_due are attached by enrich_action_item)
    if item.get("pre_due", {}).get("needed"):
        return True
    if item.get("readiness", {}).get("status") == "blocked":
        return True
    return False


def build_queue(repo: Any) -> dict[str, Any]:
    """The full ACTION REQUIRED workqueue: KPIs + per-customer items."""
    today = dt.date.today()
    invoices = repo.select("invoices")
    qstates = {
        (r.get("customer_name") or ""): r
        for r in repo.select("actions_queue")
    }

    names = sorted({i.get("customer_name") for i in invoices if i.get("customer_name")})
    items = []
    for n in names:
        it = build_action_item(repo, n, qstates.get(n))
        # honor snoozes
        if it["status"] == "snoozed" and it.get("snoozed_until"):
            try:
                if dt.date.fromisoformat(it["snoozed_until"]) > today:
                    it["_hidden_snoozed"] = True
                else:
                    it["status"] = "active"
                    it["snoozed_until"] = None
            except ValueError:
                it["status"] = "active"
                it["snoozed_until"] = None
        # honor pauses (follow-up control center)
        if it.get("paused"):
            unt = it.get("paused_until")
            try:
                if unt:
                    if dt.date.fromisoformat(str(unt)) > today:
                        it["_hidden_paused"] = True
                    else:
                        it["paused"] = False
                        it["paused_until"] = None
                else:
                    it["_hidden_paused"] = True
            except ValueError:
                it["paused"] = False
                it["paused_until"] = None
        enrich_action_item(repo, it)
        items.append(it)

    # prioritisation A-F (decision order) first, then urgency within the step
    _DECISION_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4, "F": 5}
    items.sort(key=lambda i: (
        _DECISION_ORDER.get(i.get("decision_order"), 9),
        _PRIORITY_ORDER.get(i["priority"], 9),
        -i["overdue_amount"],
        i["customer_name"],
    ))

    overdue_amt = sum(i["overdue_amount"] for i in items)
    due_week = sum(i["due_this_week_amount"] for i in items
                   if not i.get("_hidden_snoozed") and not i.get("_hidden_paused"))
    cash_at_risk = sum(i["total_outstanding"] for i in items
                       if not i.get("_hidden_snoozed") and not i.get("_hidden_paused"))
    requiring = sum(1 for i in items if not i.get("_hidden_snoozed")
                    and not i.get("_hidden_paused")
                    and i["priority"] in ("critical", "high"))
    promises_open = sum(1 for i in items if i.get("promise")
                        and i["promise"].get("status") in ("upcoming", "due_today", "overdue"))
    promised_amounts = [
        (i["promise"]["promised_amount"] or i["overdue_amount"], i["promise"]["promised_date"])
        for i in items if i.get("promise") and i["promise"].get("promised_amount")
    ]
    expected = sum(a for a, _ in promised_amounts if a)

    kpis = {
        "cash_at_risk": round(cash_at_risk, 2),
        "total_outstanding": round(sum(i["total_outstanding"] for i in items), 2),
        "overdue": round(overdue_amt, 2),
        "due_this_week": round(due_week, 2),
        "customers_requiring_action": sum(1 for i in items
                                          if not i.get("_hidden_snoozed")
                                          and not i.get("_hidden_paused")
                                          and requires_attention(i)),
        "high_priority_customers": requiring,
        "overdue_promises": sum(1 for i in items if i.get("promise")
                                and i["promise"].get("status") == "overdue"),
        "promises_open": promises_open,
        "expected_from_promises": round(expected, 2),
        "amount_x_days_total": round(sum(
            (float(i.get("overdue_amount") or 0) * float(i.get("max_days_overdue") or 0))
            for i in items
            if not i.get("_hidden_snoozed") and not i.get("_hidden_paused")), 2),
        "pre_due_count": sum(1 for i in items
                             if not i.get("_hidden_snoozed") and not i.get("_hidden_paused")
                             and i.get("pre_due", {}).get("needed")),
        "pre_due_amount": round(sum(
            float(i.get("pre_due", {}).get("amount") or 0)
            for i in items
            if not i.get("_hidden_snoozed") and not i.get("_hidden_paused")
            and i.get("pre_due", {}).get("needed")), 2),
    }
    # internal comparison: plain balance x days vs the intelligent decision
    # order (which fixes blockers, missed promises and pre-due confirmation first).
    visible = [i for i in items
               if not i.get("_hidden_snoozed") and not i.get("_hidden_paused")
               and requires_attention(i)]
    kpis["actions_by_category"] = {}
    kpis["exceptions"] = {}
    for i in visible:
        cat = (i.get("action_category") or {}).get("category") or "process"
        kpis["actions_by_category"][cat] = kpis["actions_by_category"].get(cat, 0) + 1
        ex = i.get("exception_group") or "routine"
        kpis["exceptions"][ex] = kpis["exceptions"].get(ex, 0) + 1
    kpis["exceptions_total"] = sum(
        n for g, n in kpis["exceptions"].items() if g != "routine")
    basic_leader = max(
        visible,
        key=lambda i: (float(i.get("overdue_amount") or 0) * float(i.get("max_days_overdue") or 0)),
    ) if visible else None
    kpis["prioritisation"] = {
        "basic": {
            "customer_name": basic_leader["customer_name"] if basic_leader else "",
            "amount_x_days": round(float(basic_leader.get("overdue_amount") or 0)
                                   * float(basic_leader.get("max_days_overdue") or 0), 2)
            if basic_leader else 0.0,
        },
        "intelligent": {
            "customer_name": visible[0]["customer_name"] if visible else "",
        },
        "note": "Intelligent order tackles blockers, missed promises and pre-due confirmation first - not just the largest balance x days.",
    }
    # --- Feature 2: per-item comparison (amount×days vs agent rank) ----------
    simple_sorted = sorted(visible, key=lambda i: (-i["amount_x_days"], -i["overdue_amount"], i["customer_name"]))
    for idx, item in enumerate(simple_sorted):
        item["simple_priority_rank"] = idx + 1
    for idx, item in enumerate(visible):
        item["agent_rank"] = idx + 1
        diff = item["agent_rank"] - item["simple_priority_rank"]
        if diff < 0:
            item["comparison_reason"] = (
                f"Agent ranks #{item['agent_rank']} (higher) vs simple $×d #{item['simple_priority_rank']}"
                f" — the decision engine promotes this because of a prioritised step"
                f" ({item.get('decision_order_label') or item.get('action', '')})."
            )
        elif diff > 0:
            item["comparison_reason"] = (
                f"Agent ranks #{item['agent_rank']} (lower) vs simple $×d #{item['simple_priority_rank']}"
                f" — larger cash-at-risk exists but is not blocked by a process step"
                f" ({item.get('decision_order_label') or 'routine chase'})."
            )
        else:
            item["comparison_reason"] = (
                f"Both the agent and simple $×d agree on rank #{item['agent_rank']}."
            )
    snoozed = [{k: v for k, v in i.items() if k != "_hidden_snoozed"}
               for i in items if i.get("_hidden_snoozed")]
    paused = [{k: v for k, v in i.items()
               if k not in ("_hidden_snoozed", "_hidden_paused")}
              for i in items if i.get("_hidden_paused")]
    return {"kpis": kpis, "actions": visible, "snoozed": snoozed, "paused": paused}


def needs_email(item: dict) -> bool:
    return item["draft_type"] not in ("none", "")