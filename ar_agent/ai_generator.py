"""AI layer for the AR agent.

Generates the "reason", "recommended action", and "draft email" for each
customer. Uses an LLM when OPENAI_API_KEY is available (or a custom
OPENAI_BASE_URL is set); otherwise falls back to a rule-based generator
so the product is fully functional without any API key.
"""
from __future__ import annotations

import os
import textwrap
from typing import Callable

from ar_engine import CustomerGroup, bucket_date


# ---------------------------------------------------------------------------
# template helpers
# ---------------------------------------------------------------------------

def _invoice_lines(group: CustomerGroup) -> str:
    lines = []
    for inv in group.invoices:
        src = f" [{inv.source}]" if inv.source else ""
        due = f"due {inv.due_date}, " if inv.due_date else ""
        lines.append(
            f"  - Invoice {inv.invoice_number}{src}: ${inv.amount_outstanding:,.2f} outstanding "
            f"({due}{inv.days_overdue} days overdue)"
        )
    return "\n".join(lines) or "  - (see attached statement)"


def _action_for_level(risk: str, amount: float, count: int) -> str:
    if risk == "critical":
        return (
            "Escalate to manager and initiate a phone call today. Require a "
            "written payment plan within 48h; if the customer is unresponsive, "
            "stop further work and route to collections."
        )
    if risk == "high":
        return (
            f"Phone call + personalized email today. Offer a payment plan for "
            f"the ${amount:,.0f} balance and confirm a firm payment date within "
            "7 days."
        )
    if risk == "medium":
        return (
            f"Send a friendly-but-firm email reminder with a clear 7-day "
            "deadline, then follow up by phone in 3 days if no response."
        )
    return (
        f"Send a soft reminder email now. If unpaid within 14 days, "
        "escalate to the standard follow-up sequence."
    )


def _reason_for_level(group: CustomerGroup) -> str:
    parts = []
    risk = group.risk_level
    if group.max_days_overdue > 90:
        parts.append(
            f"oldest invoice is {group.max_days_overdue} days overdue "
            "(well past the 90-day threshold)"
        )
    elif group.max_days_overdue > 60:
        parts.append(
            f"oldest invoice is {group.max_days_overdue} days overdue"
        )
    elif group.max_days_overdue > 0:
        parts.append(
            f"invoice is {group.max_days_overdue} days overdue "
            f"({bucket_date(group.max_days_overdue)})"
        )
    else:
        parts.append("invoices are not yet past due but require attention")

    if group.late_rate >= 70:
        parts.append(f"customer has a history of late payments ({group.late_rate}% of invoices late)")
    elif group.late_rate > 0:
        parts.append(f"{group.late_rate}% of this customer's invoices are already late")

    if group.total_outstanding >= 10000:
        parts.append(f"high exposure of ${group.total_outstanding:,.0f} outstanding")
    elif group.total_outstanding >= 1000:
        parts.append(f"${group.total_outstanding:,.0f} outstanding")

    if group.invoice_count > 1:
        parts.append(f"{group.invoice_count} open invoices on file")

    if risk == "critical":
        preface = "CRITICAL: "
    elif risk == "high":
        preface = ""
    else:
        preface = ""
    return preface + "; ".join(parts).capitalize() + "."


def _recipient_line(group: CustomerGroup) -> str:
    if group.contact_email:
        return f"To: {group.contact_email}"
    return "To: (email on file)"


def _draft_email_rule(group: CustomerGroup) -> str:
    """Deterministic, polite collection email generator."""
    name = group.name
    total = f"${group.total_outstanding:,.2f}"
    days = group.max_days_overdue
    invoices = _invoice_lines(group)
    email = group.contact_email or ""

    if group.risk_level == "critical":
        subject = f"Urgent: {total} overdue - action required immediately"
        opener = (
            f"Hi {name} team,\n\n"
            f"Invoices totaling {total} are now {days} days past due. We value "
            "your business and understand situations arise, but we need to "
            "resolve this before it escalates further."
        )
        ask = (
            f"Please make a payment of {total} within the next 5 business days, "
            "or reply with a payment plan proposal within 48 hours so we can "
            "avoid pausing work on your account."
        )
        signoff = "Regards,\nAccounts Receivable\nPaying fast, together."
    elif group.risk_level == "high":
        subject = f"Payment reminder: {total} outstanding"
        opener = (
            f"Hi {name} team,\n\n"
            f"This is a reminder that invoices totaling {total} remain "
            f"outstanding and are {days} days past due."
        )
        ask = (
            f"We'd like to settle this promptly. Please arrange payment of "
            f"{total} within 7 days, or reply to set up a short payment plan "
            "that works for you."
        )
        signoff = "Thanks,\nAccounts Receivable"
    else:
        subject = f"Friendly reminder: {total} invoice balance"
        opener = (
            f"Hi {name} team,\n\n"
            f"Just a quick note to mention {total} in outstanding invoices "
            f"({days} days past due)."
        )
        ask = (
            f"If payment has already been sent, please disregard this message. "
            f"Otherwise, we'd appreciate payment within 14 days or a quick reply "
            "with your expected timeline."
        )
        signoff = "Thanks,\nAccounts Receivable"

    body = (
        f"Subject: {subject}\n"
        f"To: {email}\n\n"
        f"{opener}\n\n"
        "Outstanding items:\n"
        f"{invoices}\n\n"
        f"{ask}\n\n"
        f"{signoff}"
    )
    return body


# ---------------------------------------------------------------------------
# LLM-backed generation (opt-in)
# ---------------------------------------------------------------------------

def _llm_available() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def _llm_generate(group: CustomerGroup) -> tuple[str, str, str]:
    """Generate (reason, recommended_action, draft_email) via the LLM."""
    from openai import OpenAI

    client = OpenAI()
    invoices = "\n".join(
        f"- {inv.invoice_number} | {inv.customer_name} | ${inv.amount_outstanding:,.2f} "
        f"| due {inv.due_date} | {inv.days_overdue} days overdue"
        for inv in group.invoices
    )
    prompt = textwrap.dedent(
        f"""
        You are the collections strategist inside an accounts-receivable agent.
        Analyze this customer and produce a sharp triage recommendation.

        CUSTOMER: {group.name}
        CONTACT: {group.contact_email}
        TOTAL OUTSTANDING: ${group.total_outstanding:,.2f}
        MAX DAYS OVERDUE: {group.max_days_overdue}
        INVOICE COUNT: {group.invoice_count}
        LATE RATE (past-due invoices %): {group.late_rate}%

        INVOICES:
        {invoices}

        Respond as strict JSON with exactly these keys:
        {{
          "reason": string, // why this customer needs attention, 1-2 sentences
          "recommended_action": string, // concrete next step (email, call, payment plan, escalation)
          "draft_email": string // full email: Subject line, To, polite body with amounts and a clear ask
        }}
        """
    )
    resp = client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": "You are an expert AR collections strategist."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    try:
        import json

        data = json.loads(resp.choices[0].message.content)
        return (
            data.get("reason", ""),
            data.get("recommended_action", ""),
            data.get("draft_email", ""),
        )
    except Exception:
        return "", "", ""


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def build_triage(groups: list[CustomerGroup], generator: Callable | None = None) -> list[dict]:
    """Enrich each customer group with reason / recommended_action / draft_email.

    generator(groups) -> list[(reason, action, email)] per group in order.
    """
    if generator is None:
        if _llm_available():
            generator = _llm_batch
        else:
            generator = _rule_batch

    enriched = generator(groups)

    rows = []
    for g, (reason, action, email) in zip(groups, enriched):
        rows.append(
            {
                "customer_name": g.name,
                "contact_email": g.contact_email,
                "total_outstanding": g.total_outstanding,
                "days_overdue": g.max_days_overdue,
                "invoice_count": g.invoice_count,
                "risk_level": g.risk_level,
                "priority": g.priority,
                "score": g.score,
                "reason": reason,
                "recommended_action": action,
                "draft_email": email,
            }
        )
    return rows


def _llm_batch(groups: list[CustomerGroup]) -> list[tuple[str, str, str]]:
    return [_llm_generate(g) for g in groups]


def _rule_batch(groups: list[CustomerGroup]) -> list[tuple[str, str, str]]:
    return [
        (
            _reason_for_level(g),
            _action_for_level(g.risk_level, g.total_outstanding, g.invoice_count),
            _draft_email_rule(g),
        )
        for g in groups
    ]