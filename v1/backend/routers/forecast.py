"""Expected-cash forecast."""
from __future__ import annotations

from fastapi import APIRouter

from database import repo
from services.expected_cash import build_forecast

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("")
def forecast():
    return build_forecast(repo)