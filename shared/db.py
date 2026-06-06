"""SQLite persistence layer — schema init and CRUD helpers for all four tables."""

import json
import sqlite3
import uuid
from datetime import datetime

DB_PATH = "intelligence_fabric.db"


def _now() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.utcnow().isoformat() + "Z"


def _row_to_dict(cursor: sqlite3.Cursor, row: tuple) -> dict:
    """Convert a sqlite3 row tuple to a dict using cursor description."""
    return {col[0]: val for col, val in zip(cursor.description, row)}


def init_db(path: str = DB_PATH) -> None:
    """Create all four tables if they don't exist."""
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS transcripts (
            id              TEXT PRIMARY KEY,
            client_id       TEXT NOT NULL,
            filename        TEXT NOT NULL,
            transcript_text TEXT NOT NULL,
            segments        TEXT NOT NULL,
            duration        REAL NOT NULL,
            created_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS insights (
            id                    TEXT PRIMARY KEY,
            transcript_id         TEXT NOT NULL REFERENCES transcripts(id),
            client_id             TEXT NOT NULL,
            agent_score           INTEGER CHECK(agent_score BETWEEN 1 AND 10),
            sentiment             TEXT CHECK(sentiment IN ('positive','neutral','negative')),
            objection_patterns    TEXT,
            qualification_signals TEXT,
            escalation_signals    TEXT,
            kb_gaps               TEXT,
            raw_insights_json     TEXT,
            created_at            TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS plans (
            id         TEXT PRIMARY KEY,
            client_id  TEXT NOT NULL,
            version    INTEGER NOT NULL DEFAULT 1,
            plan       TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS plan_patches (
            id            TEXT PRIMARY KEY,
            plan_id       TEXT NOT NULL REFERENCES plans(id),
            version       INTEGER NOT NULL,
            admin_request TEXT NOT NULL,
            patch         TEXT NOT NULL,
            llm_reasoning TEXT NOT NULL,
            created_at    TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()


# ── Transcripts ──────────────────────────────────────────────────────────────

def save_transcript(data: dict, path: str = DB_PATH) -> str:
    """Insert a transcript row; returns the generated id."""
    row_id = str(uuid.uuid4())
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO transcripts VALUES (?,?,?,?,?,?,?)",
        (
            row_id,
            data["client_id"],
            data["filename"],
            data["transcript_text"],
            json.dumps(data["segments"]),
            data["duration"],
            _now(),
        ),
    )
    conn.commit()
    conn.close()
    return row_id


def get_transcripts(client_id: str = None, path: str = DB_PATH) -> list:
    """Return all transcripts, optionally filtered by client_id."""
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    if client_id:
        cur.execute("SELECT * FROM transcripts WHERE client_id=? ORDER BY created_at DESC", (client_id,))
    else:
        cur.execute("SELECT * FROM transcripts ORDER BY created_at DESC")
    rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        r["segments"] = json.loads(r["segments"])
    return rows


def get_transcript(transcript_id: str, path: str = DB_PATH) -> dict | None:
    """Return a single transcript by id, or None if not found."""
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM transcripts WHERE id=?", (transcript_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    d = _row_to_dict(cur, row)
    d["segments"] = json.loads(d["segments"])
    return d


# ── Insights ─────────────────────────────────────────────────────────────────

def save_insight(data: dict, path: str = DB_PATH) -> str:
    """Insert an insight row; returns the generated id."""
    row_id = str(uuid.uuid4())
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO insights VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            row_id,
            data["transcript_id"],
            data["client_id"],
            data.get("agent_score"),
            data.get("sentiment"),
            json.dumps(data.get("objection_patterns", [])),
            json.dumps(data.get("qualification_signals", [])),
            json.dumps(data.get("escalation_signals", [])),
            json.dumps(data.get("kb_gaps", [])),
            json.dumps(data.get("raw_insights_json", {})),
            _now(),
        ),
    )
    conn.commit()
    conn.close()
    return row_id


def get_insights(client_id: str, path: str = DB_PATH) -> list:
    """Return all insights for a client_id with JSON fields deserialized."""
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM insights WHERE client_id=? ORDER BY created_at DESC", (client_id,))
    rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
    conn.close()
    json_fields = ["objection_patterns", "qualification_signals", "escalation_signals", "kb_gaps", "raw_insights_json"]
    for r in rows:
        for f in json_fields:
            if r.get(f):
                r[f] = json.loads(r[f])
    return rows


# ── Plans ─────────────────────────────────────────────────────────────────────

def save_plan(data: dict, path: str = DB_PATH) -> str:
    """Insert a plan row at version 1; returns the generated id."""
    row_id = str(uuid.uuid4())
    now = _now()
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO plans VALUES (?,?,?,?,?,?)",
        (row_id, data["client_id"], 1, json.dumps(data["plan"]), now, now),
    )
    conn.commit()
    conn.close()
    return row_id


def get_plan(plan_id: str, path: str = DB_PATH) -> dict | None:
    """Return a plan by id with the plan field deserialized, or None."""
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM plans WHERE id=?", (plan_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    d = _row_to_dict(cur, row)
    d["plan"] = json.loads(d["plan"])
    return d


def get_plans(client_id: str = None, path: str = DB_PATH) -> list:
    """Return all plans, optionally filtered by client_id, with plan deserialized."""
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    if client_id:
        cur.execute("SELECT * FROM plans WHERE client_id=? ORDER BY updated_at DESC", (client_id,))
    else:
        cur.execute("SELECT * FROM plans ORDER BY updated_at DESC")
    rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        r["plan"] = json.loads(r["plan"])
    return rows


def update_plan(plan_id: str, plan: dict, path: str = DB_PATH) -> None:
    """Replace plan JSON, increment version, and update updated_at."""
    conn = sqlite3.connect(path)
    conn.execute(
        "UPDATE plans SET plan=?, version=version+1, updated_at=? WHERE id=?",
        (json.dumps(plan), _now(), plan_id),
    )
    conn.commit()
    conn.close()


# ── Plan patches ──────────────────────────────────────────────────────────────

def save_patch(data: dict, path: str = DB_PATH) -> str:
    """Insert a patch row; returns the generated id."""
    row_id = str(uuid.uuid4())
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO plan_patches VALUES (?,?,?,?,?,?,?)",
        (
            row_id,
            data["plan_id"],
            data["version"],
            data["admin_request"],
            json.dumps(data["patch"]),
            data["llm_reasoning"],
            _now(),
        ),
    )
    conn.commit()
    conn.close()
    return row_id


def get_patches(plan_id: str, path: str = DB_PATH) -> list:
    """Return all patches for a plan_id ordered by version ascending."""
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM plan_patches WHERE plan_id=? ORDER BY version ASC",
        (plan_id,),
    )
    rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        r["patch"] = json.loads(r["patch"])
    return rows
