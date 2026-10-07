"""Accounts-Receivable agent core.

Calculates days overdue, outstanding amounts, risk levels, and priority
triage for a list of unpaid invoices, then groups them per customer so the
AI layer can generate personalized collection actions.
"""
from __future__ import annotations

import datetime as dt
import io
import math
import re
from dataclasses import dataclass, field

import pandas as pd

EXPECTED_COLUMNS = [
    "customer_name",
    "invoice_number",
    "invoice_date",
    "due_date",
    "amount",
    "amount_paid",
    "status",
    "contact_email",
]

VALID_STATUSES = {"open", "partial", "paid", "overdue", "pending", "sent"}

RISK_TAGS = ["low", "medium", "high", "critical"]


@dataclass
class Invoice:
    customer_name: str
    invoice_number: str
    invoice_date: str
    due_date: str
    amount: float
    amount_paid: float
    status: str
    contact_email: str
    days_overdue: int = 0
    amount_outstanding: float = 0.0
    row_index: int = 0
    errors: list[str] = field(default_factory=list)
    source: str = ""


@dataclass
class CustomerGroup:
    name: str
    contact_email: str
    total_outstanding: float
    max_days_overdue: int
    invoices: list[Invoice]
    invoice_count: int
    late_rate: float  # % of this customer's invoices that are late
    risk_level: str
    priority: str
    score: float
    reason: str = ""
    recommended_action: str = ""
    draft_email: str = ""


def _parse_date(value: str) -> dt.date:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%b %d, %Y", "%m-%d-%Y"):
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date format: {value}")


def _to_money(value: str) -> float:
    value = re.sub(r"[^\d.-]", "", value.strip())
    if not value:
        return 0.0
    return float(value)


def _normalize_status(status: str) -> str:
    s = status.strip().lower()
    if s in {"open", "unpaid"}:
        return "open"
    if s in {"overdue"}:
        return "overdue"
    if s in {"paid", "cleared"}:
        return "paid"
    if s in {"partial", "partially paid", "partial payment"}:
        return "partial"
    if s in {"pending"}:
        return "pending"
    if s in {"sent", "issued"}:
        return "sent"
    return s


def df_to_invoices(df: pd.DataFrame, source: str = "") -> tuple[list[Invoice], list[str]]:
    """Convert a normalized DataFrame (the 8 schema columns) into Invoice records."""
    today = dt.date.today()
    invoices: list[Invoice] = []
    warnings: list[str] = []

    def col(row: dict, name: str) -> str:
        v = row.get(name)
        return "" if v is None else str(v).strip()

    for idx, raw in enumerate(df.to_dict("records"), start=1):
        errors: list[str] = []
        inv = Invoice(
            customer_name=col(raw, "customer_name"),
            invoice_number=col(raw, "invoice_number"),
            invoice_date=col(raw, "invoice_date"),
            due_date=col(raw, "due_date"),
            amount=0.0,
            amount_paid=0.0,
            status="",
            contact_email=col(raw, "contact_email"),
            row_index=idx,
            source=source,
        )

        if not inv.customer_name:
            errors.append("missing customer_name")
        if not inv.invoice_number:
            errors.append("missing invoice_number")

        try:
            inv.invoice_date = str(_parse_date(inv.invoice_date))
        except ValueError:
            pass

        try:
            inv.due_date = str(_parse_date(inv.due_date))
        except ValueError as e:
            errors.append(str(e))

        try:
            inv.amount = _to_money(col(raw, "amount"))
        except ValueError:
            errors.append("invalid amount")

        try:
            inv.amount_paid = _to_money(col(raw, "amount_paid"))
        except ValueError:
            errors.append("invalid amount_paid")

        inv.status = _normalize_status(col(raw, "status"))
        if not inv.status:
            errors.append("missing status")
        elif inv.status not in VALID_STATUSES:
            errors.append(f"unknown status '{inv.status}'")

        inv.amount_outstanding = round(inv.amount - inv.amount_paid, 2)
        if inv.amount_outstanding < 0:
            inv.amount_outstanding = 0.0

        try:
            due = dt.date.fromisoformat(inv.due_date)
            inv.days_overdue = max(0, (today - due).days)
        except Exception:
            pass

        if errors:
            warnings.append(f"row {idx}: {inv.customer_name or '?'} - " + "; ".join(errors))
        if inv.status == "paid":
            continue
        invoices.append(inv)

    if not invoices:
        raise ValueError("No unpaid invoices to work on after parsing the data.")

    return invoices, warnings


def parse_csv(contents: str) -> tuple[list[Invoice], list[str]]:
    """Parse raw CSV text into Invoice records. Returns (invoices, warnings)."""
    df = pd.read_csv(io.StringIO(contents), dtype=str)
    if df.empty:
        raise ValueError("CSV is empty")

    return df_to_invoices(df)


def _score(inv: Invoice) -> float:
    """Risk score 0..100 for a single invoice."""
    d = inv.days_overdue
    score = 0.0
    if d <= 0:
        score += 0
    elif d <= 15:
        score += 10
    elif d <= 30:
        score += 25
    elif d <= 60:
        score += 45
    elif d <= 90:
        score += 65
    else:
        score += 85

    # dollar-weight the score so bigger sums get more attention
    outstanding = inv.amount_outstanding
    if outstanding >= 10000:
        score += 15
    elif outstanding >= 5000:
        score += 10
    elif outstanding >= 1000:
        score += 5

    if inv.status in {"overdue", "partial"}:
        score += 0  # already implied by days_overdue
    return min(100.0, score)


def _risk_level(score: float) -> str:
    if score >= 70:
        return "critical"
    if score >= 45:
        return "high"
    if score >= 20:
        return "medium"
    return "low"


def _priority(risk: str) -> str:
    return {"critical": "HIGHEST", "high": "HIGH", "medium": "MEDIUM", "low": "LOW"}[risk]


def _customer_risk(score: float, late_rate: float, count: int) -> tuple[str, str, float]:
    """Combine invoice scores + payment-history signals into (risk, priority, score)."""
    base = score + (late_rate * 100) * 0.05 + min(count, 5) * 2
    score = min(100.0, base)
    risk = _risk_level(score)
    return risk, _priority(risk), score


def group_by_customer(invoices: list[Invoice]) -> list[CustomerGroup]:
    """Aggregate invoices per customer and produce the triage table."""
    by_name: dict[str, list[Invoice]] = {}
    for inv in invoices:
        by_name.setdefault(inv.customer_name, []).append(inv)

    groups: list[CustomerGroup] = []
    for name, invs in by_name.items():
        total = round(sum(i.amount_outstanding for i in invs), 2)
        max_days = max(i.days_overdue for i in invs)
        late = sum(1 for i in invs if i.days_overdue > 0)
        late_rate = late / len(invs)
        avg_score = sum(_score(i) for i in invs) / len(invs)
        risk, priority, score = _customer_risk(avg_score, late_rate, len(invs))

        email = next((i.contact_email for i in invs if i.contact_email), "")
        groups.append(
            CustomerGroup(
                name=name,
                contact_email=email,
                total_outstanding=total,
                max_days_overdue=max_days,
                invoices=invs,
                invoice_count=len(invs),
                late_rate=round(late_rate * 100),
                risk_level=risk,
                priority=priority,
                score=round(score, 1),
            )
        )

    groups.sort(key=lambda g: g.score, reverse=True)
    return groups


def bucket_date(days: int) -> str:
    if days <= 0:
        return "not yet due"
    if days <= 15:
        return "1-15 days late"
    if days <= 30:
        return "16-30 days late"
    if days <= 60:
        return "31-60 days late"
    if days <= 90:
        return "61-90 days late"
    return "90+ days late"