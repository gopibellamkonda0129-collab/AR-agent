"""Invoice-to-payment process status: where each invoice sits, why it's stuck,
the customer's observed AR process, and the documented vs recommended process.

Every status is DERIVED from stored facts (ledger rows, signals, promises,
payments) - never guessed. Three integrity markers are used throughout:

    KNOWN     an explicit stored fact supports this (signal / payment / step)
    INFERRED  a reasonable derivation from a stored fact (e.g. "sent" because
              the invoice is on file, not because delivery was confirmed)
    UNKNOWN   no evidence either way - the engine says so instead of guessing

The engine NEVER invents PO / approval / receipt / intent evidence.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from database import repo
from services.behavior import (
    _BLOCKER_LABELS,
    _PROCESS_BLOCKERS,
    payment_behavior,
    payment_posture,
    stuck_diagnosis,
)

_MONEY = lambda x: round(float(x or 0), 2)  # noqa: E731


def _d(iso: str | None) -> dt.date | None:
    if not iso:
        return None
    try:
        return dt.date.fromisoformat(str(iso)[:10])
    except ValueError:
        return None


_STATUS_LABELS = {
    "draft": "Draft",
    "sent": "Sent",
    "receipt_unknown": "Receipt unknown",
    "received": "Received",
    "po_pending": "PO pending",
    "approval_pending": "Approval pending",
    "disputed": "Disputed",
    "ready_for_payment": "Ready for payment",
    "payment_promised": "Payment promised",
    "payment_overdue": "Payment overdue",
    "paid": "Paid",
    "process_blocked": "Process blocked",
    "unknown": "Unknown",
}

_STAGE_LABELS = {
    "draft": "Created (no dates)",
    "sent": "Sent",
    "receipt_unknown": "Delivery",
    "received": "Received by customer",
    "po_pending": "PO / reference",
    "approval_pending": "Customer approval",
    "disputed": "Dispute resolution",
    "ready_for_payment": "Payment in transit",
    "payment_promised": "Payment commitment",
    "payment_overdue": "Collection",
    "paid": "Payment received",
    "process_blocked": "Process item",
    "unknown": "Unknown",
}


def _open_signals(repo: Any, name: str) -> list[dict[str, Any]]:
    return [s for s in repo.select("signals", where={"customer_name": name})
            if not s.get("resolved")]


def invoice_process_status(repo: Any, invoice: dict[str, Any]) -> dict[str, Any]:
    """Per-invoice process status from stored facts only.

    Statuses follow the invoice-to-payment vocabulary. When there is no proof
    of a step (receipt, PO, approval), the step is UNKNOWN - the invoice is
    never silently "approved" or "received".
    """
    name = invoice.get("customer_name", "")
    num = invoice.get("invoice_number", "")
    due = _d(invoice.get("due_date"))
    today = dt.date.today()
    is_paid = str(invoice.get("status") or "").lower() == "paid" \
        or _MONEY(invoice.get("amount_outstanding")) <= 0

    sigs = _open_signals(repo, name)
    inv_sigs = [s for s in sigs if (s.get("related_invoice") or "") == num]
    cust_sigs = [s for s in sigs if (s.get("related_invoice") or "") != num]
    by_type = {s.get("signal_type") for s in inv_sigs}
    cust_types = {s.get("signal_type") for s in cust_sigs}

    payments = repo.select("payments", where={"invoice_number": num})
    promise = next((s for s in inv_sigs if s.get("signal_type") == "payment_promise"), None)

    facts = {
        "created": {"state": "KNOWN", "note": "invoice row exists in the ledger"},
        "sent": {"state": "INFERRED", "note": "invoice is on file; delivery was never confirmed"},
    }
    receipt_ref = next((s for s in inv_sigs if s.get("signal_type") not in ("bounced_email",)), None)
    if ("missing_invoice" in by_type):
        facts["receipt"] = {"state": "KNOWN", "note": "customer said the invoice was not received"}
    elif receipt_ref or promise or "payment_confirmation" in by_type:
        facts["receipt"] = {"state": "KNOWN", "note": "customer referenced the invoice / committed to it"}
    else:
        facts["receipt"] = {"state": "UNKNOWN", "note": "no proof the customer received it"}
    facts["po"] = (
        {"state": "KNOWN", "note": "PO mismatch flagged by the customer"}
        if "wrong_po" in by_type
        else {"state": "UNKNOWN", "note": "no PO confirmation on file"}
    )
    if "approval_pending" in by_type:
        facts["approval"] = {"state": "KNOWN", "note": "customer is awaiting internal approval"}
    elif promise or "payment_confirmation" in by_type:
        facts["approval"] = {"state": "INFERRED", "note": "commitment / payment on file implies approval"}
    else:
        facts["approval"] = {"state": "UNKNOWN", "note": "no approval evidence on file"}
    facts["promise"] = (
        {"state": "KNOWN", "note": f"open promise for {promise.get('promised_date')}"}
        if promise else {"state": "UNKNOWN", "note": "no open promise on this invoice"}
    )
    facts["paid"] = (
        {"state": "KNOWN" if payments or is_paid else "UNKNOWN",
         "note": f"{len(payments)} recorded payment(s)" if payments else ("marked paid" if is_paid else "no payment recorded")}
    )
    if payments and not is_paid:
        facts["paid"]["note"] = f"{len(payments)} recorded partial payment(s); balance still open"

    evidence = [
        f"{s.get('signal_type')}: {s.get('summary')}".strip()
        for s in inv_sigs if s.get("summary")
    ]

    evidence_items = []
    for s in inv_sigs:
        if s.get("summary"):
            evidence_items.append({
                "source": "email",
                "summary": s["summary"],
                "evidence_status": "KNOWN",
                "date": s.get("created_at"),
            })
    if payments:
        total_paid = round(sum(float(p.get("amount") or 0) for p in payments), 2)
        evidence_items.append({
            "source": "payment",
            "summary": f"{len(payments)} payment(s) totalling ${total_paid:,.2f}",
            "evidence_status": "KNOWN",
            "date": (payments[-1].get("paid_at") if payments else None),
        })
    if promise and promise.get("promised_date"):
        evidence_items.append({
            "source": "promise",
            "summary": f"open promise for {promise['promised_date']}",
            "evidence_status": "KNOWN",
            "date": promise.get("created_at"),
        })
    evidence_items.append({
        "source": "ledger",
        "summary": "invoice exists in the ledger",
        "evidence_status": "KNOWN",
        "date": invoice.get("invoice_date"),
    })

    def _status(status: str, confidence: float,
                evidence_status: str = "KNOWN", blocker: str | None = None,
                evidence_items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {
            "invoice_number": num,
            "status": status,
            "status_label": _STATUS_LABELS[status],
            "stage": _STAGE_LABELS[status],
            "blocker": blocker,
            "evidence_status": evidence_status,
            "confidence": confidence,
            "facts": facts,
            "evidence": evidence,
            "evidence_items": evidence_items or [],
        }

    if is_paid:
        return _status("paid", 1.0, blocker="", evidence_items=evidence_items)
    if "dispute" in by_type:
        return _status("disputed", 0.9, blocker="disputed charge unresolved",
                       evidence_items=evidence_items)
    if "wrong_po" in by_type:
        return _status("po_pending", 0.85, blocker="PO mismatch on the invoice",
                       evidence_items=evidence_items)
    if "approval_pending" in by_type:
        return _status("approval_pending", 0.82, blocker="customer approval pending",
                       evidence_items=evidence_items)
    if "missing_invoice" in by_type:
        return _status("receipt_unknown", 0.88,
                       blocker="customer says the invoice never arrived",
                       evidence_items=evidence_items)
    if by_type & {"documentation_request"}:
        return _status("process_blocked", 0.85, blocker="customer still needs documents",
                       evidence_items=evidence_items)
    if "bounced_email" in cust_types:
        return _status("process_blocked", 0.9, blocker="contact / email unreachable",
                       evidence_items=evidence_items)
    if due and due < today:
        return _status("payment_overdue", 0.9, evidence_items=evidence_items)
    if promise:
        return _status("payment_promised", 0.82, evidence_items=evidence_items)
    if "payment_confirmation" in by_type:
        return _status("ready_for_payment", 0.86, evidence_items=evidence_items)
    if receipt_ref:
        return _status("received", 0.7, evidence_items=evidence_items)
    if invoice.get("invoice_date"):
        return _status("sent", 0.5, evidence_status="INFERRED",
                       evidence_items=evidence_items)
    return _status("unknown", 0.3, evidence_status="UNKNOWN",
                   evidence_items=evidence_items)


# ---------------------------------------------------------------------------
# Invoice lifecycle: the full invoice-to-payment pipeline for one invoice.
# position-based `state` (done/current/upcoming/blocked) + per-stage evidence
# (KNOWN/INFERRED/UNKNOWN) are shown together so nothing is ever silently
# assumed: the bar says WHERE the invoice is, the evidence says WHAT is proven.
# ---------------------------------------------------------------------------

_LIFECYCLE_BLOCKED = {"receipt_unknown", "po_pending", "approval_pending", "process_blocked"}

_LIFECYCLE_CURRENT = {
    "draft": "created",
    "unknown": "reviewed",
    "sent": "sent",
    "receipt_unknown": "received",
    "received": "received",
    "po_pending": "po_matched",
    "approval_pending": "approval",
    "process_blocked": "po_matched",
    "ready_for_payment": "payment_due",
    "payment_promised": "payment_promised",
    "payment_overdue": "overdue",
    "paid": "paid",
}


def invoice_lifecycle(repo: Any, invoice: dict[str, Any],
                      status: dict[str, Any] | None = None,
                      paused: bool = False) -> dict[str, Any]:
    """Lifecycle for one invoice: stages + current position + progress."""
    status = status or invoice_process_status(repo, invoice)
    st = status.get("status", "unknown")
    facts = status.get("facts") or {}
    num = invoice.get("invoice_number", "")
    due = _d(invoice.get("due_date"))
    today = dt.date.today()
    issued = bool(invoice.get("invoice_date"))
    soon = due and due <= today + dt.timedelta(days=7)

    sigs = [s for s in repo.select("signals", where={"customer_name": invoice.get("customer_name", "")})
            if s.get("related_invoice") == num and not s.get("resolved")]
    promise_done = any((s.get("signal_type") or "") == "payment_promise" for s in sigs)

    def _stage(key, label, evidence, note, date, done) -> dict[str, Any]:
        return {"key": key, "label": label, "evidence_status": evidence,
                "note": note, "date": date, "done": bool(done)}

    main: list[dict[str, Any]] = [
        _stage("created", "Created", "KNOWN", "invoice row is in the ledger",
               invoice.get("invoice_date"), True),
        _stage("reviewed", "Reviewed", "INFERRED" if issued else "UNKNOWN",
               "reviewed before issuance (no separate review log)", None, issued),
        _stage("scheduled", "Scheduled", "INFERRED" if issued else "UNKNOWN",
               "issuance implies a schedule (no scheduling log)", None, issued),
        _stage("sent", "Sent", "INFERRED" if issued else "UNKNOWN",
               "invoice is on file; delivery was never confirmed", invoice.get("invoice_date"), issued),
        _stage("delivered", "Delivered", "INFERRED" if issued else "UNKNOWN",
               "delivery is assumed from issuance, not confirmed", None, issued),
        _stage("received", "Received", facts.get("receipt", {}).get("state", "UNKNOWN"),
               facts.get("receipt", {}).get("note", ""), None,
               facts.get("receipt", {}).get("state") == "KNOWN"),
        _stage("po_matched", "PO matched", facts.get("po", {}).get("state", "UNKNOWN"),
               facts.get("po", {}).get("note", ""), None,
               facts.get("po", {}).get("state") == "KNOWN"),
        _stage("approval", "Approval", facts.get("approval", {}).get("state", "UNKNOWN"),
               facts.get("approval", {}).get("note", ""), None,
               facts.get("approval", {}).get("state") in ("KNOWN", "INFERRED")),
        _stage("due_soon", "Due soon", "KNOWN" if soon else "UNKNOWN",
               f"due date is {due}" if due else "no due date set", str(due) if due else None, bool(soon)),
        _stage("payment_due", "Payment due", "KNOWN" if (due and due <= today) else "UNKNOWN",
               f"payment due {due}" if due else "no due date set", str(due) if due else None,
               bool(due and due <= today)),
        _stage("payment_promised", "Payment promised", "KNOWN" if promise_done else "UNKNOWN",
               "an open payment commitment is on file" if promise_done else "no open promise",
               None, promise_done),
        _stage("overdue", "Overdue", "KNOWN" if (due and due < today) else "UNKNOWN",
               f"{(today - due).days}d past due" if (due and due < today) else "not yet overdue",
               None, bool(due and due < today)),
        _stage("paid", "Paid", "KNOWN" if st == "paid" else "UNKNOWN",
               "payment received (or marked paid in the ledger)", None, st == "paid"),
    ]

    terminal = "paid" if st == "paid" else ("paused" if paused else ("disputed" if st == "disputed" else None))

    current_key = _LIFECYCLE_CURRENT.get(st, "reviewed")
    current_idx = next((i for i, s in enumerate(main) if s["key"] == current_key), 1)

    stages: list[dict[str, Any]] = []
    for i, sg in enumerate(main):
        if terminal == "paid":
            state = "done"
        elif terminal == "paused" or terminal == "disputed":
            state = "done" if sg["done"] else "upcoming"
        elif i < current_idx:
            state = "done"
        elif i == current_idx:
            state = "done" if sg["done"] and st not in _LIFECYCLE_BLOCKED else (
                "blocked" if st in _LIFECYCLE_BLOCKED else ("done" if sg["done"] else "current"))
        else:
            state = "done" if sg["done"] else "upcoming"
        out = dict(sg)
        out["state"] = state
        if i == current_idx and st in _LIFECYCLE_BLOCKED:
            out["blocker"] = status.get("blocker")
        stages.append(out)

    python_done_count = sum(1 for s in main[:12] if s["done"])
    progress = 1.0 if terminal == "paid" else round(python_done_count / 12.0, 2)

    if terminal == "paused":
        stages.append({"key": "paused", "label": "Paused", "evidence_status": "KNOWN",
                       "note": "follow-up paused by the AR team", "date": None,
                       "done": False, "state": "blocked",
                       "blocker": status.get("blocker")})
    elif terminal == "disputed":
        stages.append({"key": "disputed", "label": "Disputed", "evidence_status": "KNOWN",
                       "note": "dispute / chargeback unresolved", "date": None,
                       "done": False, "state": "blocked",
                       "blocker": status.get("blocker")})

    return {
        "invoice_number": num,
        "status": st,
        "status_label": _STATUS_LABELS.get(st, st),
        "current_stage": ("paid" if terminal == "paid" else
                          (terminal or current_key)),
        "current_stage_label": ("Paid" if terminal == "paid" else
                                ({"paused": "Paused", "disputed": "Disputed"}.get(terminal or "", "") or
                                 _STAGE_LABELS.get(st, current_key))),
        "progress": progress,
        "terminal": terminal or "",
        "stages": stages,
    }


# ---------------------------------------------------------------------------
# Customer payment process (an AR-process window for one customer)
# ---------------------------------------------------------------------------

def _known_from_history(rows: list[dict[str, Any]], signal_type: str) -> bool:
    return any((s.get("signal_type") or "") == signal_type for s in rows)


def customer_ar_process(repo: Any, name: str,
                        item: dict[str, Any] | None = None,
                        wl: dict[str, Any] | None = None,
                        readiness: dict[str, Any] | None = None,
                        pre_due: dict[str, Any] | None = None) -> dict[str, Any]:
    """Typical behaviour + known requirements + current process + posture."""
    behavior = payment_behavior(repo, name)
    rows = repo.select("signals", where={"customer_name": name})

    invoices = repo.select("invoices", where={"customer_name": name})
    contact = next((i.get("contact_email") or "" for i in invoices if i.get("contact_email")), "")

    open_issues = sorted({s.get("signal_type") for s in rows if not s.get("resolved")}
                         & (_PROCESS_BLOCKERS | {"dispute"}))
    issue_labels = [_BLOCKER_LABELS.get(t, t.replace("_", " ")) for t in open_issues]

    if _known_from_history(rows, "wrong_po"):
        po_required, po_note = "known", "customer flagged a PO mismatch"
        po_evidence = "KNOWN"
    else:
        po_required, po_note, po_evidence = "unknown", "", "UNKNOWN"

    if _known_from_history(rows, "approval_pending"):
        approval, approval_note = "known", "customer needs an internal approval stage"
        approval_evidence = "KNOWN"
    elif _known_from_history(rows, "payment_promise"):
        approval, approval_note = "not evidently blocked", "commitments on file cleared approval before"
        approval_evidence = "INFERRED"
    else:
        approval, approval_note, approval_evidence = "unknown", "", "UNKNOWN"

    if _known_from_history(rows, "documentation_request"):
        docs, docs_note = "known", "customer requested documents in the past"
        docs_evidence = "KNOWN"
    else:
        docs, docs_note, docs_evidence = "unknown", "", "UNKNOWN"

    if item is None:
        from services.behavior import enrich_action_item
        from services.next_action_engine import build_action_item
        item = enrich_action_item(repo, build_action_item(repo, name))
    wl = wl or item.get("why_late") or {}
    readiness = readiness or item.get("readiness") or {}
    pre_due = pre_due or item.get("pre_due") or {}
    stuck = stuck_diagnosis(item, wl, readiness, pre_due)

    return {
        "typical": {
            "avg_delay_days": behavior.get("avg_delay_days"),
            "on_time_percent": behavior.get("on_time_percent"),
            "promises_kept_percent": behavior.get("promises_kept_percent"),
            "promises_count": behavior.get("promises_count"),
            "promises_missed": behavior.get("promises_missed"),
            "partial_payments": behavior.get("partial_payments"),
        },
        "requirements": {
            "po_required": po_required,
            "po_evidence": po_evidence,
            "ap_contact": contact or "unknown",
            "approval_process": approval,
            "approval_evidence": approval_evidence,
            "documentation": docs,
            "documentation_evidence": docs_evidence,
            "known_invoice_issues": issue_labels,
        },
        "current": {
            "current_stage": stuck["current_stage"],
            "blocker": stuck["blocker"],
            "where": stuck["where"],
            "next_action": stuck["next_action"],
            "confidence": stuck["confidence"],
        },
        "posture": payment_posture(repo, item, behavior),
    }


# ---------------------------------------------------------------------------
# The AR process as documented from workspace evidence (Observed vs Recommended)
# ---------------------------------------------------------------------------

def ar_process_doc(repo: Any) -> dict[str, Any]:
    invoices = repo.select("invoices")
    open_inv = [i for i in invoices if str(i.get("status") or "").lower() != "paid"
                and _MONEY(i.get("amount_outstanding")) > 0]
    signals = repo.select("signals")

    num_to_inv = {i.get("invoice_number"): i for i in invoices}
    referenced_nums = {s.get("related_invoice") for s in signals
                       if s.get("related_invoice") and s.get("related_invoice") in num_to_inv}

    open_sigs = [s for s in signals if not s.get("resolved")]
    wrong_po = [s for s in open_sigs if s.get("signal_type") == "wrong_po"]
    approval = [s for s in open_sigs if s.get("signal_type") == "approval_pending"]
    docs = [s for s in open_sigs if s.get("signal_type") == "documentation_request"]
    missing = [s for s in open_sigs if s.get("signal_type") == "missing_invoice"]

    promises = [s for s in signals if s.get("signal_type") == "payment_promise"]
    open_promises = [s for s in promises if not s.get("resolved")]
    missed = [s for s in promises
              if (s.get("resolution_note") or "").upper().startswith("MISSED")
              or (not s.get("resolved") and s.get("promised_date")
                  and _d(s.get("promised_date")) and _d(s.get("promised_date")) < dt.date.today())]

    payments = repo.select("payments")
    overdue = [i for i in open_inv if _d(i.get("due_date"))
               and _d(i.get("due_date")) < dt.date.today()]

    def _step(step: int, key: str, label: str, state: str,
              count: int | None, note: str) -> dict[str, Any]:
        return {"step": step, "key": key, "label": label, "state": state,
                "count": count, "note": note}

    observed = [
        _step(1, "created", "Invoice created", "KNOWN", len(invoices),
              f"{len(invoices)} invoice(s) in the ledger"),
        _step(2, "sent", "Invoice sent / delivered", "INFERRED", len(invoices),
              "delivery is assumed from the invoice being on file - no per-invoice send log"),
        _step(3, "receipt", "Receipt confirmed by customer", "KNOWN" if referenced_nums else "UNKNOWN",
              len(referenced_nums),
              f"{len(referenced_nums)} invoice(s) referenced by the customer" if referenced_nums
              else "no customer message confirms delivery of an invoice"),
        _step(4, "po", "Purchase order / reference matched", "KNOWN" if wrong_po else "UNKNOWN",
              len(wrong_po),
              f"{len(wrong_po)} open PO mismatch(es)" if wrong_po else "no PO evidence on file"),
        _step(5, "approval", "Approval completed", "KNOWN" if approval else "UNKNOWN",
              len(approval),
              f"{len(approval)} invoice(s) waiting on customer approval" if approval
              else "no approval evidence on file"),
        _step(6, "due", "Due date reached", "KNOWN",
              sum(1 for i in invoices if _d(i.get("due_date"))),
              f"{len(overdue)} of {len(open_inv)} open invoices are past due"),
        _step(7, "promise", "Payment promise with a date", "KNOWN", len(open_promises),
              f"{len(open_promises)} open promise(s)"),
        _step(8, "missed_promise", "Promise kept", "KNOWN" if missed else "NOT OBSERVED",
              len(missed),
              f"{len(missed)} missed promise(s) on file" if missed else "no missed promises"),
        _step(9, "payment", "Payment received", "KNOWN", len(payments),
              f"{len(payments)} recorded payment(s) · "
              f"${_MONEY(sum(_MONEY(p.get('amount')) for p in payments)):,.2f} recovered"),
    ]

    recommended = [
        {"step": 1, "label": "Invoice created with correct details (scope, rate, PO reference).",
         "detail": "Errors here force re-issuing and stall everything downstream."},
        {"step": 2, "label": "Invoice sent to the correct AP contact from the ledger.",
         "detail": "A bounced address means the customer never saw the invoice."},
        {"step": 3, "label": "Receipt of the invoice confirmed by the customer.",
         "detail": "The clock on AP processing starts once they have it."},
        {"step": 4, "label": "Purchase order / reference matched before it reaches AP approval.",
         "detail": "Most 'PO mismatch' holds are caught by confirming the reference at issue time."},
        {"step": 5, "label": "Approval completed (customer side) or approval evidence captured.",
         "detail": "Unconfirmed approval is the last silent stage before payment."},
        {"step": 6, "label": "Due date reached and the invoice tracked as cash.",
         "detail": "Confirmed dates feed the forecast; unconfirmed invoices stay out."},
        {"step": 7, "label": "Payment received, or a promise with a confirmed date.",
         "detail": "A promise without a date is intent, not cash."},
        {"step": 8, "label": "Payment matched and reconciled to the ledger.",
         "detail": "Unmatched 'we paid' notes are verified, never trusted at word."},
    ]

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "observed": observed,
        "recommended": recommended,
        "note": (
            "Steps marked KNOWN come from stored facts. INFERRED means a reasonable "
            "derivation (e.g. an invoice on file implies it was issued). UNKNOWN means "
            "the workspace holds no evidence for that step - which is itself useful: "
            "those are the steps to start confirming."
        ),
    }