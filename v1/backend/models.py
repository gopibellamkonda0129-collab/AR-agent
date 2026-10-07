"""API models."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

SignalType = Literal[
    "payment_promise",
    "dispute",
    "missing_invoice",
    "wrong_po",
    "documentation_request",
    "payment_confirmation",
    "bounced_email",
    "info_question",
    "approval_pending",
    "other",
]

Priority = Literal["low", "medium", "high", "critical"]


class ConnectRequest(BaseModel):
    provider: Literal["gmail", "outlook", "imap"]
    email: str
    display_name: str = ""
    # imap: host + app password; gmail/outlook: OAuth config path
    config: dict = Field(default_factory=dict)


class EmailRecord(BaseModel):
    subject: str
    body: str
    from_email: str
    from_name: str = ""
    message_id: str = ""
    thread_id: str = ""
    received_at: datetime


class SignalCreate(BaseModel):
    account_id: str
    message_id: Optional[str] = None
    customer_name: str = ""
    customer_email: str = ""
    signal_type: SignalType = "other"
    priority: Priority = "medium"
    promised_date: Optional[date] = None
    promised_amount: Optional[float] = None
    related_invoice: str = ""
    confidence: float = 0.0
    summary: str = ""


class SignalResolve(BaseModel):
    resolved: bool = True
    note: str = ""


class SyncResult(BaseModel):
    account_id: str
    fetched: int
    analyzed: int
    new_signals: int


CustomerPriority = Literal["critical", "high", "medium", "low"]


class MarkContacted(BaseModel):
    note: str = ""


class OwnerRequest(BaseModel):
    owner: str = ""


class SnoozeRequest(BaseModel):
    until: str  # ISO date


class PauseRequest(BaseModel):
    """Pause chasing for a customer (follow-up control center)."""
    until: str = ""   # ISO date; empty = pause indefinitely
    reason: str = ""


class NextActionRequest(BaseModel):
    """Team-decided next action that overrides the engine suggestion."""
    action: str = ""


class FollowUpSave(BaseModel):
    draft_type: str = ""
    subject: str
    body: str


class FollowUpApprove(BaseModel):
    """Records explicit human approval for one follow-up email."""
    send: bool = True