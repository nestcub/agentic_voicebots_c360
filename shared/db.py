"""Postgres persistence layer (Neon + pgvector) — schema init and CRUD helpers.

Provider: psycopg3 connection pool via DATABASE_URL.
All existing public function signatures are preserved (path arg kept as no-op).
JSON columns stored as JSONB; psycopg3 deserializes them automatically.
"""

import os
import uuid
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

_DATABASE_URL = os.getenv("DATABASE_URL", "")
_EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))

DB_PATH = os.getenv("DB_PATH", "")  # deprecated no-op; all persistence is Neon Postgres via DATABASE_URL

_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        if not _DATABASE_URL:
            raise RuntimeError("DATABASE_URL environment variable is not set.")
        _pool = ConnectionPool(
            _DATABASE_URL,
            kwargs={"row_factory": dict_row, "prepare_threshold": None},
            open=True,
        )
    return _pool


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def init_db(path: str = DB_PATH) -> None:
    """Create all tables and indexes if they don't exist. path arg is ignored."""
    dim = _EMBEDDING_DIM
    ddl_statements = [
        "CREATE EXTENSION IF NOT EXISTS vector",
        """CREATE TABLE IF NOT EXISTS transcripts (
            id              TEXT PRIMARY KEY,
            client_id       TEXT NOT NULL,
            filename        TEXT NOT NULL,
            transcript_text TEXT NOT NULL,
            segments        JSONB NOT NULL DEFAULT '[]',
            duration        REAL NOT NULL,
            created_at      TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS insights (
            id                    TEXT PRIMARY KEY,
            transcript_id         TEXT NOT NULL,
            client_id             TEXT NOT NULL,
            agent_score           INTEGER CHECK(agent_score BETWEEN 1 AND 10),
            sentiment             TEXT CHECK(sentiment IN ('positive','neutral','negative')),
            objection_patterns    JSONB,
            qualification_signals JSONB,
            escalation_signals    JSONB,
            kb_gaps               JSONB,
            raw_insights_json     JSONB,
            created_at            TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS plans (
            id         TEXT PRIMARY KEY,
            client_id  TEXT NOT NULL,
            version    INTEGER NOT NULL DEFAULT 1,
            plan       JSONB NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS plan_patches (
            id            TEXT PRIMARY KEY,
            plan_id       TEXT NOT NULL,
            version       INTEGER NOT NULL,
            admin_request TEXT NOT NULL,
            patch         JSONB NOT NULL,
            llm_reasoning TEXT NOT NULL,
            created_at    TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS workflow_sessions (
            client_id  TEXT PRIMARY KEY,
            questions  JSONB NOT NULL DEFAULT '[]',
            answers    JSONB NOT NULL DEFAULT '{}',
            plan_id    TEXT,
            use_case   TEXT,
            updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS conversation_turns (
            id         TEXT PRIMARY KEY,
            client_id  TEXT NOT NULL,
            role       TEXT NOT NULL,
            content    TEXT NOT NULL,
            mode       TEXT,
            created_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS platform_knowledge (
            id         TEXT PRIMARY KEY,
            topic      TEXT NOT NULL,
            fact       TEXT NOT NULL,
            source     TEXT,
            status     TEXT NOT NULL DEFAULT 'active',
            embedding  vector({dim}),
            created_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS bot_examples (
            id         TEXT PRIMARY KEY,
            unit_type  TEXT NOT NULL,
            name       TEXT NOT NULL,
            use_case   TEXT NOT NULL,
            content    JSONB NOT NULL,
            embedding  vector({dim}),
            created_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS transcript_chunks (
            id            TEXT PRIMARY KEY,
            transcript_id TEXT NOT NULL,
            client_id     TEXT NOT NULL,
            chunk_index   INTEGER NOT NULL,
            role_sequence TEXT,
            start_sec     REAL,
            end_sec       REAL,
            text          TEXT NOT NULL,
            embedding     vector({dim}),
            created_at    TEXT NOT NULL
        )""",
        """CREATE INDEX IF NOT EXISTS conversation_turns_client_idx
            ON conversation_turns(client_id, created_at)""",
        """CREATE INDEX IF NOT EXISTS bot_examples_embedding_idx
            ON bot_examples USING hnsw (embedding vector_cosine_ops)""",
        """CREATE INDEX IF NOT EXISTS platform_knowledge_embedding_idx
            ON platform_knowledge USING hnsw (embedding vector_cosine_ops)""",
        """CREATE INDEX IF NOT EXISTS transcript_chunks_client_idx
            ON transcript_chunks(client_id)""",
        """CREATE INDEX IF NOT EXISTS transcript_chunks_embedding_idx
            ON transcript_chunks USING hnsw (embedding vector_cosine_ops)""",
        """CREATE TABLE IF NOT EXISTS transcription_batches (
            id          TEXT PRIMARY KEY,
            client_id   TEXT NOT NULL,
            provider    TEXT NOT NULL,
            total       INTEGER NOT NULL DEFAULT 0,
            completed   INTEGER NOT NULL DEFAULT 0,
            failed      INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS transcription_batch_items (
            id            TEXT PRIMARY KEY,
            batch_id      TEXT NOT NULL,
            filename      TEXT NOT NULL,
            status        TEXT NOT NULL DEFAULT 'pending',
            transcript_id TEXT,
            error         TEXT,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        )""",
        """CREATE INDEX IF NOT EXISTS batch_items_batch_idx
            ON transcription_batch_items(batch_id)""",
    ]
    with _get_pool().connection() as conn:
        for stmt in ddl_statements:
            conn.execute(stmt)


# ── Transcripts ───────────────────────────────────────────────────────────────

def save_transcript(data: dict, path: str = DB_PATH) -> str:
    row_id = str(uuid.uuid4())
    with _get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO transcripts VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (row_id, data["client_id"], data["filename"], data["transcript_text"],
             Jsonb(data["segments"]), data["duration"], _now()),
        )
    return row_id


def get_transcripts(client_id: str = None, path: str = DB_PATH) -> list:
    with _get_pool().connection() as conn:
        if client_id:
            rows = conn.execute(
                "SELECT * FROM transcripts WHERE client_id=%s ORDER BY created_at DESC",
                (client_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM transcripts ORDER BY created_at DESC"
            ).fetchall()
    return list(rows)


def get_transcript(transcript_id: str, path: str = DB_PATH) -> dict | None:
    with _get_pool().connection() as conn:
        row = conn.execute(
            "SELECT * FROM transcripts WHERE id=%s", (transcript_id,)
        ).fetchone()
    return row


def get_transcript_by_filename(client_id: str, filename: str, path: str = DB_PATH) -> dict | None:
    with _get_pool().connection() as conn:
        row = conn.execute(
            "SELECT * FROM transcripts WHERE client_id=%s AND filename=%s ORDER BY created_at DESC LIMIT 1",
            (client_id, filename),
        ).fetchone()
    return row


def update_transcript_text(transcript_id: str, transcript_text: str, path: str = DB_PATH) -> None:
    with _get_pool().connection() as conn:
        conn.execute(
            "UPDATE transcripts SET transcript_text=%s WHERE id=%s",
            (transcript_text, transcript_id),
        )


# ── Insights ──────────────────────────────────────────────────────────────────

def save_insight(data: dict, path: str = DB_PATH) -> str:
    row_id = str(uuid.uuid4())
    with _get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO insights VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                row_id,
                data["transcript_id"],
                data["client_id"],
                data.get("agent_score"),
                data.get("sentiment"),
                Jsonb(data.get("objection_patterns", [])),
                Jsonb(data.get("qualification_signals", [])),
                Jsonb(data.get("escalation_signals", [])),
                Jsonb(data.get("kb_gaps", [])),
                Jsonb(data.get("raw_insights_json", {})),
                _now(),
            ),
        )
    return row_id


def get_insights_by_transcript(transcript_id: str, path: str = DB_PATH) -> list:
    with _get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT * FROM insights WHERE transcript_id=%s ORDER BY created_at ASC",
            (transcript_id,),
        ).fetchall()
    return list(rows)


def get_insight_by_transcript(transcript_id: str, path: str = DB_PATH) -> dict | None:
    with _get_pool().connection() as conn:
        row = conn.execute(
            "SELECT * FROM insights WHERE transcript_id=%s ORDER BY created_at DESC LIMIT 1",
            (transcript_id,),
        ).fetchone()
    return row


def get_insights(client_id: str, path: str = DB_PATH) -> list:
    with _get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT * FROM insights WHERE client_id=%s ORDER BY created_at DESC",
            (client_id,),
        ).fetchall()
    return list(rows)


def delete_insights_for_transcript(transcript_id: str, path: str = DB_PATH) -> None:
    with _get_pool().connection() as conn:
        conn.execute("DELETE FROM insights WHERE transcript_id=%s", (transcript_id,))


# ── Plans ─────────────────────────────────────────────────────────────────────

def save_plan(data: dict, path: str = DB_PATH) -> str:
    row_id = str(uuid.uuid4())
    now = _now()
    with _get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO plans VALUES (%s,%s,%s,%s,%s,%s)",
            (row_id, data["client_id"], 1, Jsonb(data["plan"]), now, now),
        )
    return row_id


def get_plan(plan_id: str, path: str = DB_PATH) -> dict | None:
    with _get_pool().connection() as conn:
        row = conn.execute(
            "SELECT * FROM plans WHERE id=%s", (plan_id,)
        ).fetchone()
    return row


def get_plans(client_id: str = None, path: str = DB_PATH) -> list:
    with _get_pool().connection() as conn:
        if client_id:
            rows = conn.execute(
                "SELECT * FROM plans WHERE client_id=%s ORDER BY updated_at DESC",
                (client_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM plans ORDER BY updated_at DESC"
            ).fetchall()
    return list(rows)


def update_plan(plan_id: str, plan: dict, path: str = DB_PATH) -> None:
    with _get_pool().connection() as conn:
        conn.execute(
            "UPDATE plans SET plan=%s, version=version+1, updated_at=%s WHERE id=%s",
            (Jsonb(plan), _now(), plan_id),
        )


# ── Plan patches ──────────────────────────────────────────────────────────────

def save_patch(data: dict, path: str = DB_PATH) -> str:
    row_id = str(uuid.uuid4())
    with _get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO plan_patches VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                row_id,
                data["plan_id"],
                data["version"],
                data["admin_request"],
                Jsonb(data["patch"]),
                data["llm_reasoning"],
                _now(),
            ),
        )
    return row_id


def get_patches(plan_id: str, path: str = DB_PATH) -> list:
    with _get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT * FROM plan_patches WHERE plan_id=%s ORDER BY version ASC",
            (plan_id,),
        ).fetchall()
    return list(rows)


# ── Workflow sessions ─────────────────────────────────────────────────────────

def save_session(client_id: str, questions: list, answers: dict,
                 plan_id: str = None, use_case: str = None, path: str = DB_PATH) -> None:
    with _get_pool().connection() as conn:
        conn.execute(
            """INSERT INTO workflow_sessions (client_id, questions, answers, plan_id, use_case, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (client_id) DO UPDATE SET
                 questions=%s, answers=%s, plan_id=%s, use_case=%s, updated_at=%s""",
            (
                client_id, Jsonb(questions), Jsonb(answers), plan_id, use_case, _now(),
                Jsonb(questions), Jsonb(answers), plan_id, use_case, _now(),
            ),
        )


def load_session(client_id: str, path: str = DB_PATH) -> dict:
    with _get_pool().connection() as conn:
        row = conn.execute(
            "SELECT questions, answers, plan_id, use_case FROM workflow_sessions WHERE client_id=%s",
            (client_id,),
        ).fetchone()
    if row is None:
        return {"questions": [], "answers": {}, "plan_id": None, "use_case": ""}
    return {
        "questions": row["questions"] or [],
        "answers":   row["answers"] or {},
        "plan_id":   row["plan_id"],
        "use_case":  row["use_case"] or "",
    }


# ── Conversation turns ────────────────────────────────────────────────────────

def save_turn(client_id: str, role: str, content: str, mode: str = None, path: str = DB_PATH) -> str:
    row_id = str(uuid.uuid4())
    with _get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO conversation_turns (id,client_id,role,content,mode,created_at) VALUES (%s,%s,%s,%s,%s,%s)",
            (row_id, client_id, role, content, mode, _now()),
        )
    return row_id


def get_turns(client_id: str, limit: int = None, path: str = DB_PATH) -> list:
    with _get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT * FROM conversation_turns WHERE client_id=%s ORDER BY created_at ASC",
            (client_id,),
        ).fetchall()
    rows = list(rows)
    return rows[-limit:] if limit else rows


# ── Platform knowledge ────────────────────────────────────────────────────────

def add_knowledge(topic: str, fact: str, source: str = None, status: str = "active", path: str = DB_PATH) -> str:
    row_id = str(uuid.uuid4())
    with _get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO platform_knowledge (id,topic,fact,source,status,created_at) VALUES (%s,%s,%s,%s,%s,%s)",
            (row_id, topic, fact, source, status, _now()),
        )
    return row_id


def get_knowledge(status: str = "active", path: str = DB_PATH) -> list:
    with _get_pool().connection() as conn:
        if status is None:
            rows = conn.execute(
                "SELECT * FROM platform_knowledge ORDER BY created_at ASC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM platform_knowledge WHERE status=%s ORDER BY created_at ASC",
                (status,),
            ).fetchall()
    return list(rows)


def set_knowledge_status(knowledge_id: str, status: str, path: str = DB_PATH) -> None:
    with _get_pool().connection() as conn:
        conn.execute(
            "UPDATE platform_knowledge SET status=%s WHERE id=%s",
            (status, knowledge_id),
        )


def delete_knowledge(knowledge_id: str, path: str = DB_PATH) -> None:
    with _get_pool().connection() as conn:
        conn.execute("DELETE FROM platform_knowledge WHERE id=%s", (knowledge_id,))


def set_knowledge_embedding(knowledge_id: str, embedding: list, path: str = DB_PATH) -> None:
    with _get_pool().connection() as conn:
        conn.execute(
            "UPDATE platform_knowledge SET embedding=%s WHERE id=%s",
            (embedding, knowledge_id),
        )


# ── Bot examples (RAG corpus) ─────────────────────────────────────────────────

def add_bot_example(unit_type: str, name: str, use_case: str, content: dict, embedding: list) -> str:
    row_id = str(uuid.uuid4())
    with _get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO bot_examples (id,unit_type,name,use_case,content,embedding,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (row_id, unit_type, name, use_case, Jsonb(content), embedding, _now()),
        )
    return row_id


def search_bot_examples(embedding: list, k: int = 5) -> list[dict]:
    with _get_pool().connection() as conn:
        rows = conn.execute(
            """SELECT *, 1 - (embedding <=> %s::vector) AS score
               FROM bot_examples
               WHERE embedding IS NOT NULL
               ORDER BY embedding <=> %s::vector
               LIMIT %s""",
            (embedding, embedding, k),
        ).fetchall()
    return list(rows)


def search_knowledge(embedding: list, k: int = 5) -> list[dict]:
    with _get_pool().connection() as conn:
        rows = conn.execute(
            """SELECT *, 1 - (embedding <=> %s::vector) AS score
               FROM platform_knowledge
               WHERE status='active' AND embedding IS NOT NULL
               ORDER BY embedding <=> %s::vector
               LIMIT %s""",
            (embedding, embedding, k),
        ).fetchall()
    return list(rows)


# ── Transcript chunks (RAG) ───────────────────────────────────────────────────

def add_transcript_chunk(transcript_id: str, client_id: str, chunk_index: int,
                         role_sequence: str, start_sec: float, end_sec: float,
                         text: str, embedding: list) -> str:
    row_id = str(uuid.uuid4())
    with _get_pool().connection() as conn:
        conn.execute(
            """INSERT INTO transcript_chunks
               (id,transcript_id,client_id,chunk_index,role_sequence,start_sec,end_sec,text,embedding,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (row_id, transcript_id, client_id, chunk_index, role_sequence,
             start_sec, end_sec, text, embedding, _now()),
        )
    return row_id


def search_transcript_chunks(embedding: list, client_id: str, k: int = 5) -> list[dict]:
    with _get_pool().connection() as conn:
        rows = conn.execute(
            """SELECT *, 1 - (embedding <=> %s::vector) AS score
               FROM transcript_chunks
               WHERE client_id=%s AND embedding IS NOT NULL
               ORDER BY embedding <=> %s::vector
               LIMIT %s""",
            (embedding, client_id, embedding, k),
        ).fetchall()
    return list(rows)


def delete_transcript_chunks(transcript_id: str) -> None:
    with _get_pool().connection() as conn:
        conn.execute("DELETE FROM transcript_chunks WHERE transcript_id=%s", (transcript_id,))


# ── Transcription batches ─────────────────────────────────────────────────────

def create_batch(client_id: str, provider: str, total_files: int) -> str:
    row_id = str(uuid.uuid4())
    now = _now()
    with _get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO transcription_batches VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (row_id, client_id, provider, total_files, 0, 0, now, now),
        )
    return row_id


def get_batch(batch_id: str) -> dict | None:
    with _get_pool().connection() as conn:
        return conn.execute(
            "SELECT * FROM transcription_batches WHERE id=%s", (batch_id,)
        ).fetchone()


def create_batch_item(batch_id: str, filename: str) -> str:
    row_id = str(uuid.uuid4())
    now = _now()
    with _get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO transcription_batch_items VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (row_id, batch_id, filename, "pending", None, None, now, now),
        )
    return row_id


def update_batch_item(item_id: str, status: str, transcript_id: str = None, error: str = None) -> None:
    with _get_pool().connection() as conn:
        conn.execute(
            "UPDATE transcription_batch_items SET status=%s, transcript_id=%s, error=%s, updated_at=%s WHERE id=%s",
            (status, transcript_id, error, _now(), item_id),
        )


def get_batch_items(batch_id: str) -> list:
    with _get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT * FROM transcription_batch_items WHERE batch_id=%s ORDER BY created_at ASC",
            (batch_id,),
        ).fetchall()
    return list(rows)


def refresh_batch_counts(batch_id: str) -> None:
    """Recompute completed/failed counts from items and update the batch row."""
    with _get_pool().connection() as conn:
        conn.execute(
            """UPDATE transcription_batches SET
               completed = (SELECT COUNT(*) FROM transcription_batch_items WHERE batch_id=%s AND status='done'),
               failed    = (SELECT COUNT(*) FROM transcription_batch_items WHERE batch_id=%s AND status='failed'),
               updated_at = %s
               WHERE id=%s""",
            (batch_id, batch_id, _now(), batch_id),
        )
