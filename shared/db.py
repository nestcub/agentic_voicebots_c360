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

        CREATE TABLE IF NOT EXISTS workflow_sessions (
            client_id  TEXT PRIMARY KEY,
            questions  TEXT NOT NULL DEFAULT '[]',
            answers    TEXT NOT NULL DEFAULT '{}',
            plan_id    TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS conversation_turns (
            id         TEXT PRIMARY KEY,
            client_id  TEXT NOT NULL,
            role       TEXT NOT NULL,
            content    TEXT NOT NULL,
            mode       TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS platform_knowledge (
            id         TEXT PRIMARY KEY,
            topic      TEXT NOT NULL,
            fact       TEXT NOT NULL,
            source     TEXT,
            status     TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        );
    """)
    conn.commit()
    try:
        conn.execute("ALTER TABLE workflow_sessions ADD COLUMN plan_id TEXT")
        conn.commit()
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE workflow_sessions ADD COLUMN use_case TEXT")
        conn.commit()
    except Exception:
        pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS conversation_turns_client_idx ON conversation_turns(client_id, created_at)")
        conn.commit()
    except Exception:
        pass
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


def get_insights_by_transcript(transcript_id: str, path: str = DB_PATH) -> list:
    """Return all insight rows for a transcript, oldest-first (preserves history)."""
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM insights WHERE transcript_id=? ORDER BY created_at ASC",
        (transcript_id,),
    )
    rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
    conn.close()
    json_fields = ["objection_patterns", "qualification_signals", "escalation_signals", "kb_gaps", "raw_insights_json"]
    for r in rows:
        for f in json_fields:
            if r.get(f):
                r[f] = json.loads(r[f])
    return rows


def get_insight_by_transcript(transcript_id: str, path: str = DB_PATH) -> dict | None:
    """Return the latest insight row for a given transcript_id, or None."""
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM insights WHERE transcript_id=? ORDER BY created_at DESC LIMIT 1",
        (transcript_id,),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    d = _row_to_dict(cur, row)
    for f in ["objection_patterns", "qualification_signals", "escalation_signals", "kb_gaps", "raw_insights_json"]:
        if d.get(f):
            d[f] = json.loads(d[f])
    return d


def update_transcript_text(transcript_id: str, transcript_text: str, path: str = DB_PATH) -> None:
    """Update the transcript_text field for an existing transcript row."""
    conn = sqlite3.connect(path)
    conn.execute("UPDATE transcripts SET transcript_text=? WHERE id=?", (transcript_text, transcript_id))
    conn.commit()
    conn.close()


def delete_insights_for_transcript(transcript_id: str, path: str = DB_PATH) -> None:
    """Delete all insight rows linked to a transcript (used before re-analysis)."""
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM insights WHERE transcript_id=?", (transcript_id,))
    conn.commit()
    conn.close()


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


# ── Workflow sessions ─────────────────────────────────────────────────────────

def save_session(client_id: str, questions: list, answers: dict, plan_id: str = None, use_case: str = None, path: str = DB_PATH) -> None:
    """Upsert the Q&A session for a client (one row per client_id)."""
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT OR REPLACE INTO workflow_sessions "
        "(client_id, questions, answers, plan_id, use_case, updated_at) VALUES (?,?,?,?,?,?)",
        (client_id, json.dumps(questions), json.dumps(answers), plan_id, use_case, _now()),
    )
    conn.commit()
    conn.close()


def load_session(client_id: str, path: str = DB_PATH) -> dict:
    """Return saved questions + answers for a client, or empty defaults."""
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute(
        "SELECT questions, answers, plan_id, use_case FROM workflow_sessions WHERE client_id=?",
        (client_id,),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        return {"questions": [], "answers": {}, "plan_id": None, "use_case": ""}
    return {
        "questions": json.loads(row[0]) if row[0] else [],
        "answers":   json.loads(row[1]) if row[1] else {},
        "plan_id":   row[2],
        "use_case":  row[3] or "",
    }


def get_transcript_by_filename(client_id: str, filename: str, path: str = DB_PATH) -> dict | None:
    """Return the most recent transcript for (client_id, filename), or None. Deserializes segments."""
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM transcripts WHERE client_id=? AND filename=? ORDER BY created_at DESC LIMIT 1",
        (client_id, filename),
    )
    row = cur.fetchone()
    if row is None:
        conn.close()
        return None
    d = _row_to_dict(cur, row)
    conn.close()
    if d.get("segments"):
        d["segments"] = json.loads(d["segments"])
    return d


def save_turn(client_id: str, role: str, content: str, mode: str = None, path: str = DB_PATH) -> str:
    """Append a conversation turn; returns the row id."""
    row_id = str(uuid.uuid4())
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO conversation_turns (id, client_id, role, content, mode, created_at) VALUES (?,?,?,?,?,?)",
        (row_id, client_id, role, content, mode, _now()),
    )
    conn.commit()
    conn.close()
    return row_id


def get_turns(client_id: str, limit: int = None, path: str = DB_PATH) -> list:
    """Return conversation turns for a client oldest-first; if limit, return the most recent `limit`."""
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM conversation_turns WHERE client_id=? ORDER BY created_at ASC",
        (client_id,),
    )
    rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
    conn.close()
    return rows[-limit:] if limit else rows


# ── Platform knowledge ────────────────────────────────────────────────────────

def add_knowledge(topic: str, fact: str, source: str = None, status: str = "active", path: str = DB_PATH) -> str:
    """Insert a platform knowledge row; returns the generated id."""
    row_id = str(uuid.uuid4())
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO platform_knowledge (id, topic, fact, source, status, created_at) VALUES (?,?,?,?,?,?)",
        (row_id, topic, fact, source, status, _now()),
    )
    conn.commit()
    conn.close()
    return row_id


def get_knowledge(status: str = "active", path: str = DB_PATH) -> list:
    """Return platform knowledge rows filtered by status, ordered by created_at ASC.
    If status is None, return ALL rows (admin panel needs active + pending + archived).
    """
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    if status is None:
        cur.execute("SELECT * FROM platform_knowledge ORDER BY created_at ASC")
    else:
        cur.execute("SELECT * FROM platform_knowledge WHERE status=? ORDER BY created_at ASC", (status,))
    rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
    conn.close()
    return rows


def set_knowledge_status(knowledge_id: str, status: str, path: str = DB_PATH) -> None:
    """Update the status of a platform knowledge row."""
    conn = sqlite3.connect(path)
    conn.execute("UPDATE platform_knowledge SET status=? WHERE id=?", (status, knowledge_id))
    conn.commit()
    conn.close()


def delete_knowledge(knowledge_id: str, path: str = DB_PATH) -> None:
    """Delete a platform knowledge row by id."""
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM platform_knowledge WHERE id=?", (knowledge_id,))
    conn.commit()
    conn.close()
