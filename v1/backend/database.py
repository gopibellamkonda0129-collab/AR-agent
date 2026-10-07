"""Persistence: Supabase (Postgres) when configured, in-memory demo store otherwise.

The repository functions are the ONLY way routers touch storage, so swapping in
production Postgres is a config change, not a refactor.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from config import settings


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Supabase backend
# ---------------------------------------------------------------------------

class _SupabaseRepo:
    def __init__(self, url: str, key: str):
        from supabase import create_client

        self.client = create_client(url, key)

    def insert(self, table: str, rows: list[dict]) -> list[dict]:
        resp = self.client.table(table).insert(rows).execute()
        return resp.data

    def update(self, table: str, row_id: str, values: dict) -> list[dict]:
        resp = self.client.table(table).update(values).eq("id", row_id).execute()
        return resp.data

    def select(self, table: str, where: dict | None = None,
               order_by: str | None = None, desc: bool = True,
               limit: int = 500) -> list[dict]:
        q = self.client.table(table).select("*")
        for k, v in (where or {}).items():
            q = q.eq(k, v)
        if order_by:
            q = q.order(order_by, desc=desc)
        resp = q.limit(limit).execute()
        return resp.data

    def delete(self, table: str, row_id: str) -> None:
        self.client.table(table).delete().eq("id", row_id).execute()


# ---------------------------------------------------------------------------
# In-memory fallback (demo / tests / local dev without Supabase)
# ---------------------------------------------------------------------------

class _MemoryRepo:
    def __init__(self):
        self._lock = threading.Lock()
        self._tables: dict[str, list[dict]] = {
            "email_accounts": [],
            "messages": [],
            "signals": [],
            "invoices": [],
            "actions_queue": [],
            "followups": [],
            "payments": [],
        }

    def _push(self, table: str, row: dict) -> None:
        if "id" not in row:
            row["id"] = _uid()
        if "created_at" not in row:
            row["created_at"] = _utcnow()
        self._tables[table].append(row)

    def insert(self, table: str, rows: list[dict]) -> list[dict]:
        with self._lock:
            out = []
            for r in rows:
                self._push(table, r)
                out.append(r)
            return out

    def update(self, table: str, row_id: str, values: dict) -> list[dict]:
        with self._lock:
            for row in self._tables.get(table, []):
                if row["id"] == row_id:
                    row.update(values)
                    return [row]
        return []

    def select(self, table: str, where: dict | None = None,
               order_by: str | None = None, desc: bool = True,
               limit: int = 500) -> list[dict]:
        with self._lock:
            rows = self._tables.get(table, [])
            if where:
                rows = [r for r in rows if all(r.get(k) == v for k, v in where.items())]
            if order_by:
                def _sort_key(r: dict):
                    v = r.get(order_by)
                    if v is None:
                        return (-1,)  # rows missing the column sort together first
                    return (0, v)
                rows = sorted(
                    rows,
                    key=_sort_key,
                    reverse=desc,
                )
            return [dict(r) for r in rows[:limit]]

    def delete(self, table: str, row_id: str) -> None:
        with self._lock:
            self._tables.setdefault(table, [])
            self._tables[table] = [r for r in self._tables[table] if r["id"] != row_id]


def get_repo() -> Any:
    if settings.supabase_url and settings.supabase_key:
        return _SupabaseRepo(settings.supabase_url, settings.supabase_key)
    return _MemoryRepo()


repo = get_repo()