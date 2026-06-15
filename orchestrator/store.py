"""Store layer — one interface, two backends.

  PostgresStore — Neon Postgres-backed generic JSON store (the sole production
                  backend; the dashboard reads the same orchestration data).
  MemoryStore   — pure in-RAM dict store used by the test suite. No file, no DB.

Engines depend ONLY on the Store protocol, never on a concrete backend.
"""

from __future__ import annotations

import copy
from typing import Protocol

from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

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


def _apply_filters(rows: list[dict], where: dict | None,
                   order_by: str | None, desc: bool) -> list[dict]:
    """Python-side `where`/`order_by` semantics shared by both backends."""
    if where:
        rows = [r for r in rows if all(r.get(k) == v for k, v in where.items())]
    if order_by:
        rows.sort(key=lambda r: r.get(order_by) or "", reverse=desc)
    return rows


# ── PostgresStore (Neon, generic JSONB rows) ────────────────────────────────────

class PostgresStore:
    """Generic store: a single `orch_kv(tbl, id, data)` table holds JSONB rows per logical table."""

    _pool: ConnectionPool | None = None

    def __init__(self):
        self._init()

    def _get_pool(self) -> ConnectionPool:
        if PostgresStore._pool is None:
            if not config.DATABASE_URL:
                raise RuntimeError(
                    "DATABASE_URL is not set; PostgresStore requires a Neon connection string."
                )
            PostgresStore._pool = ConnectionPool(
                config.DATABASE_URL,
                kwargs={"row_factory": dict_row, "prepare_threshold": None},
                open=True,
            )
        return PostgresStore._pool

    def _init(self) -> None:
        with self._get_pool().connection() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS orch_kv ("
                "  tbl text NOT NULL, id text NOT NULL, data jsonb NOT NULL,"
                "  PRIMARY KEY (tbl, id))"
            )

    def insert(self, table: str, row: dict) -> dict:
        with self._get_pool().connection() as conn:
            conn.execute(
                "INSERT INTO orch_kv (tbl,id,data) VALUES (%s,%s,%s) "
                "ON CONFLICT (tbl,id) DO UPDATE SET data=EXCLUDED.data",
                (table, row["id"], Jsonb(row)),
            )
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
        with self._get_pool().connection() as conn:
            r = conn.execute(
                "SELECT data FROM orch_kv WHERE tbl=%s AND id=%s", (table, row_id)
            ).fetchone()
        return r["data"] if r else None

    def list(self, table: str, where: dict | None = None,
             order_by: str | None = None, desc: bool = False) -> list[dict]:
        with self._get_pool().connection() as conn:
            rows = conn.execute(
                "SELECT data FROM orch_kv WHERE tbl=%s", (table,)
            ).fetchall()
        data = [r["data"] for r in rows]
        return _apply_filters(data, where, order_by, desc)

    def commitments_due(self, as_of: str | None = None) -> list[dict]:
        as_of = as_of or now_iso()
        pending = self.list(T_COMMITMENTS, where={"state": CommitmentState.PENDING.value})
        return [c for c in pending if c.get("due_at", "") <= as_of]


# ── MemoryStore (pure in-RAM dict, for tests) ───────────────────────────────────

class MemoryStore:
    """In-memory store: `{table: {id: row}}`. Deep-copies on every read/write so
    callers cannot mutate stored state by reference (matches old JSON-serialized store)."""

    def __init__(self):
        self._db: dict[str, dict[str, dict]] = {}

    def insert(self, table: str, row: dict) -> dict:
        self._db.setdefault(table, {})[row["id"]] = copy.deepcopy(row)
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
        row = self._db.get(table, {}).get(row_id)
        return copy.deepcopy(row) if row is not None else None

    def list(self, table: str, where: dict | None = None,
             order_by: str | None = None, desc: bool = False) -> list[dict]:
        rows = [copy.deepcopy(r) for r in self._db.get(table, {}).values()]
        return _apply_filters(rows, where, order_by, desc)

    def commitments_due(self, as_of: str | None = None) -> list[dict]:
        as_of = as_of or now_iso()
        pending = self.list(T_COMMITMENTS, where={"state": CommitmentState.PENDING.value})
        return [c for c in pending if c.get("due_at", "") <= as_of]


# ── factory ─────────────────────────────────────────────────────────────────────

_STORE: Store | None = None


def get_store() -> Store:
    """Return the Neon PostgresStore singleton (lazily built)."""
    global _STORE
    if _STORE is None:
        _STORE = PostgresStore()
    return _STORE


def reset_store(store: Store | None = None) -> None:
    """Override the singleton (tests pass a MemoryStore)."""
    global _STORE
    _STORE = store
