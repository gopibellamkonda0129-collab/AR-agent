"""AI Accounts-Receivable Agent - V1 API.

Run (demo mode, no credentials needed):
    python -m uvicorn app:app --reload --port 8000

Live mode:
    set AR_DEMO=0, SUPABASE_URL/SUPABASE_KEY, OPENAI_API_KEY and connect a
    real inbox (Gmail OAuth or IMAP). A background job polls connected
    inboxes every AR_SYNC_INTERVAL seconds (default 300).

Then open the dashboard at http://localhost:8000 (static build) or the
Next.js dev server on :3000 pointing at this API.
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from database import repo
from demo.seed import seed_demo
from routers import (accounts, actions, customers, emails, followups, forecast,
                     gmail, invoices, reports, signals)
from services.sync import sync_account

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ar.v1")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # An empty workspace never stays empty: any fresh repo gets a clearly-labeled
    # sample workspace so first-time users see the product working, not $0.00.
    # It uses the SAME pipeline as real data (import -> analyze -> match) and can
    # be cleared/replaced any time. Nothing is ever seeded on top of real data.
    if not repo.select("invoices", limit=1):
        log.info("empty workspace: seeding sample receivables workspace")
        _seed_sample_workspace()
    if not settings.demo and (settings.supabase_url and settings.supabase_key):
        log.info("live mode: Supabase persistence active")
    if settings.sync_interval_seconds > 0:
        t = threading.Thread(target=_sync_all_background, daemon=True,
                             name="ar-sync-loop")
        t.start()
        log.info("background inbox sync every %ss", settings.sync_interval_seconds)
    yield


def _seed_sample_workspace() -> None:
    """Seed the sample workspace and run one demo sync for its emails.

    The sync is gated on the MESSAGES table (processed inbox rows), not signals:
    the seed inserts promise/response HISTORY signals, which would otherwise
    mask the live inbox and skip the missed-promise / wrong-PO / dispute /
    approval scenarios entirely on first boot.
    """
    try:
        seed_demo()
        account = repo.select("email_accounts", limit=1)
        if account and not repo.select("messages", limit=1):
            res = sync_account(account[0])
            log.info("sample workspace synced: %s", res)
    except Exception:  # noqa: BLE001
        log.exception("sample workspace seed failed (continuing with empty repo)")


app = FastAPI(title="AR Agent V1", version="1.2.1", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(accounts.router)
app.include_router(emails.router)
app.include_router(signals.router)
app.include_router(customers.router)
app.include_router(invoices.router)
app.include_router(gmail.router)
app.include_router(actions.router)
app.include_router(followups.router)
app.include_router(forecast.router)
app.include_router(reports.router)

_sync_lock = threading.Lock()


def _sync_all_background() -> None:
    """Poll connected (non-demo) inboxes on an interval."""
    interval = settings.sync_interval_seconds
    if interval <= 0:
        return
    while True:
        time.sleep(interval)
        with _sync_lock:
            for account in repo.select("email_accounts"):
                if account.get("provider") == "demo":
                    continue
                try:
                    res = sync_account(account)
                    log.info("auto-sync %s -> %s", account.get("email"), res)
                except Exception:  # noqa: BLE001
                    log.warning("auto-sync failed for %s", account.get("email"), exc_info=True)
                    repo.update("email_accounts", account["id"],
                                {"last_sync_status": "sync failed - try again"})


@app.get("/health")
def health():
    return {"ok": True, "demo": settings.demo,
            "llm": bool(settings.openai_api_key),
            "supabase": bool(settings.supabase_url and settings.supabase_key),
            "sync_interval_seconds": settings.sync_interval_seconds}


@app.post("/demo/seed")
def demo_seed():
    """Load the bundled demo ledger + inbox. Development mode only - NEVER used
    by the product UI (the dashboard has no demo buttons)."""
    if not settings.demo:
        raise HTTPException(403, "demo endpoints are disabled (AR_DEMO=0)")
    seed_demo()
    accounts = repo.select("email_accounts")
    return {"seeded": True,
            "invoices": len(repo.select("invoices")),
            "account": accounts[0]["id"] if accounts else None}


@app.post("/demo/sync")
def demo_sync():
    """Run the demonstration inbox through the full pipeline (opt-in)."""
    if not settings.demo:
        raise HTTPException(400, "demo endpoints only active in AR_DEMO=1")
    accounts = repo.select("email_accounts", limit=1)
    account = accounts[0] if accounts else repo.insert("email_accounts", [{
        "provider": "demo",
        "email": "ar@yourcompany.com",
        "display_name": "AR Inbox (demo)",
        "provider_config": {"mode": "demo"},
        "status": "connected",
    }])[0]
    return sync_account(account)


# serve the built frontend (dashboard) when present
_frontend_dist = Path(__file__).parent.parent / "frontend" / "dashboard" / "out"
if _frontend_dist.exists():
    app.mount("/_next", StaticFiles(directory=_frontend_dist / "_next"), name="next")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        f = _frontend_dist / full_path
        if full_path and f.is_file():
            return FileResponse(f)
        # Static export writes each route to <page>/index.html. For /page/ (or
        # /page), serve that page's index.html — never the root redirect page,
        # which would drop the SPA into a reload loop.
        idx = None
        if full_path:
            if full_path.endswith("/"):
                idx = _frontend_dist / full_path / "index.html"
            elif not full_path.startswith("_next") and (
                (_frontend_dist / full_path).is_dir()
                or (_frontend_dist / f"{full_path}.html").is_file()
            ):
                idx = _frontend_dist / full_path / "index.html"
                if not idx.is_file():
                    idx = _frontend_dist / f"{full_path}.html"
        if idx is not None and idx.is_file():
            return FileResponse(idx)
        return FileResponse(_frontend_dist / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)