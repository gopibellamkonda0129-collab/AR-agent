"""Import your real AR ledgers (CSV/XLSX/XLS/DOCX/PDF/TXT/images) into V1.

Reuses the V0 `ar_agent` parsing pipeline (normalize.read_records ->
ar_engine.df_to_invoices) so PDF key-value extraction, synonym header
detection and multi-invoice splitting all carry over.
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from config import settings
from database import repo

_LOADED = False


def _load_v0() -> None:
    global _LOADED
    if _LOADED:
        return
    v0 = Path(settings.v0_dir).resolve()
    if not v0.is_dir():
        raise RuntimeError(
            f"V0 ar_agent package not found at {v0} - set AR_V0_DIR to point at it."
        )
    if str(v0) not in sys.path:
        sys.path.insert(0, str(v0))
    try:
        import ar_engine  # noqa: F401
        import normalize  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "V0 parser deps are missing (pandas/pdfplumber/python-docx/openpyxl). "
            f"Install them or fix AR_V0_DIR. ({exc})"
        ) from exc
    _LOADED = True


def _save_temp(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix or ".txt"
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


def import_file_bytes(filename: str, data: bytes,
                      repo_any: Any = None) -> dict:
    """Parse one uploaded file and insert its unpaid invoices.

    Returns {imported, skipped, warnings, customers}. Duplicate invoice
    numbers are skipped (idempotent re-uploads).
    """
    _load_v0()
    from normalize import read_records

    store = repo if repo_any is None else repo_any
    existing = {inv.get("invoice_number", "").strip() or str(inv.get("id", ""))
                for inv in store.select("invoices")}
    existing = {x for x in existing if x}

    path = _save_temp(filename, data)
    try:
        df, warnings = read_records(path)
    finally:
        os.remove(path)

    from ar_engine import df_to_invoices

    invoices, engine_warnings = df_to_invoices(df, source=filename)
    warnings = list(warnings) + list(engine_warnings)

    rows: list[dict] = []
    imported = 0
    skipped = 0
    for inv in invoices:
        key = (inv.invoice_number or "").strip()
        if not key:
            warnings.append(f"{inv.customer_name}: invoice missing a number - skipped")
            skipped += 1
            continue
        if key in existing:
            skipped += 1
            continue
        existing.add(key)
        rows.append({
            "customer_name": inv.customer_name or "Unknown",
            "contact_email": inv.contact_email or "",
            "invoice_number": key,
            "invoice_date": inv.invoice_date or None,
            "due_date": inv.due_date or None,
            "amount_outstanding": inv.amount_outstanding,
            "status": inv.status or "overdue",
            "source": filename[:80],
        })
        imported += 1

    if rows:
        store.insert("invoices", rows)

    customers = {
        r["customer_name"]
        for r in store.select("invoices")
    }
    return {
        "imported": imported,
        "skipped": skipped,
        "warnings": warnings[:50],
        "customers": sorted(customers),
    }


def clear_invoices(repo_any: Any = None) -> dict:
    store = repo if repo_any is None else repo_any
    ids = [r["id"] for r in store.select("invoices")]
    for rid in ids:
        store.delete("invoices", rid)
    return {"removed": len(ids)}