"""Store layer — one interface, two backends.

  LocalStore    — SQLite-backed generic JSON store. Multi-process safe (file-based),
                  needs no credentials. Used for tests and the creds-free demo.
  SupabaseStore — the shared orchestration store the dashboard reads in production.

Engines depend ONLY on the Store protocol, never on a concrete backend.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Protocol

from . import config
from .models import now_iso, T_COMMITMENTS, CommitmentState


class Store(Protocol):
    """Backend-agnostic persistence interface used by all engines."""

    def insert(self, table: str, row: dict) -> dict: ...
    def update(self, table: str, row_id: str, fields: dict) -> dict | None: ...
    def get(self, table: str, row_id: str) -> dict | None: ...
    def list(self, table: str, where: dict | None = None,
             order_by: str | None = None, desc: bool = False) -> list[dict]: ...
    def commitments_due(self, as_of: str | None = None) -> list[dict]: ...


# ── LocalStore (SQLite, generic JSON rows) ──────────────────────────────────────

class LocalStore:
    """Generic store: a single `kv(tbl, id, data)` table holds JSON rows per logical table."""

    def __init__(self, path: str | None = None):
        self._path = path or config.ORCH_DB_PATH
        self._init()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)

    def _init(self) -> None:
        conn = self._conn()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS kv ("
            "  tbl TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL,"
            "  PRIMARY KEY (tbl, id))"
        )
        conn.commit()
        conn.close()

    def insert(self, table: str, row: dict) -> dict:
        conn = self._conn()
        conn.execute(
            "INSERT OR REPLACE INTO kv (tbl, id, data) VALUES (?,?,?)",
            (table, row["id"], json.dumps(row)),
        )
        conn.commit()
        conn.close()
        return row

    def update(self, table: str, row_id: str, fields: dict) -> dict | None:
        current = self.get(table, row_id)
        if current is None:
            return None
        current.update(fields)
        if "updated_at" in current:
            current["updated_at"] = now_iso()
        return self.insert(table, current)

    def get(self, table: str, row_id: str) -> dict | None:
        conn = self._conn()
        cur = conn.execute("SELECT data FROM kv WHERE tbl=? AND id=?", (table, row_id))
        r = cur.fetchone()
        conn.close()
        return json.loads(r[0]) if r else None

    def list(self, table: str, where: dict | None = None,
             order_by: str | None = None, desc: bool = False) -> list[dict]:
        conn = self._conn()
        cur = conn.execute("SELECT data FROM kv WHERE tbl=?", (table,))
        rows = [json.loads(r[0]) for r in cur.fetchall()]
        conn.close()
        if where:
            rows = [r for r in rows if all(r.get(k) == v for k, v in where.items())]
        if order_by:
            rows.sort(key=lambda r: r.get(order_by) or "", reverse=desc)
        return rows

    def commitments_due(self, as_of: str | None = None) -> list[dict]:
        as_of = as_of or now_iso()
        pending = self.list(T_COMMITMENTS, where={"state": CommitmentState.PENDING.value})
        return [c for c in pending if c.get("due_at", "") <= as_of]


# ── SupabaseStore ───────────────────────────────────────────────────────────────

class SupabaseStore:
    """Shared orchestration store backed by Supabase (the dashboard reads the same tables)."""

    def __init__(self, url: str | None = None, key: str | None = None):
        from supabase import create_client  # imported lazily so demo needs no dep
        self._c = create_client(url or config.SUPABASE_URL, key or config.SUPABASE_SERVICE_KEY)

    def insert(self, table: str, row: dict) -> dict:
        resp = self._c.table(table).upsert(row).execute()
        return (resp.data or [row])[0]

    def update(self, table: str, row_id: str, fields: dict) -> dict | None:
        if "updated_at" in fields or True:
            fields = {**fields}
        resp = self._c.table(table).update(fields).eq("id", row_id).execute()
        return (resp.data or [None])[0]

    def get(self, table: str, row_id: str) -> dict | None:
        resp = self._c.table(table).select("*").eq("id", row_id).limit(1).execute()
        return (resp.data or [None])[0]

    def list(self, table: str, where: dict | None = None,
             order_by: str | None = None, desc: bool = False) -> list[dict]:
        q = self._c.table(table).select("*")
        for k, v in (where or {}).items():
            q = q.eq(k, v)
        if order_by:
            q = q.order(order_by, desc=desc)
        return q.execute().data or []

    def commitments_due(self, as_of: str | None = None) -> list[dict]:
        as_of = as_of or now_iso()
        return (
            self._c.table(T_COMMITMENTS).select("*")
            .eq("state", CommitmentState.PENDING.value)
            .lte("due_at", as_of)
            .execute().data
        ) or []


# ── factory ─────────────────────────────────────────────────────────────────────

_STORE: Store | None = None


def get_store() -> Store:
    """Return the configured store singleton (Supabase if creds present, else Local)."""
    global _STORE
    if _STORE is None:
        _STORE = SupabaseStore() if config.store_backend() == "supabase" else LocalStore()
    return _STORE


def reset_store(store: Store | None = None) -> None:
    """Override the singleton (used by tests)."""
    global _STORE
    _STORE = store
