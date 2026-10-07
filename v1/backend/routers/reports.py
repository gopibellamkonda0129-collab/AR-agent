"""Weekly receivables brief + Money Recovered."""
from __future__ import annotations

from fastapi import APIRouter

from database import repo
from services.process_status import ar_process_doc
from services.reports import weekly_brief
from services.recovery import money_recovered

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/weekly")
def weekly(week_start: str | None = None):
    return weekly_brief(repo, week_start)


@router.get("/ar-process")
def ar_process():
    """The documented AR process: observed evidence vs the recommended process."""
    return ar_process_doc(repo)


@router.get("/money-recovered")
def recovered():
    """Money Recovered metric - only reflects recorded payments, never invented."""
    return money_recovered()