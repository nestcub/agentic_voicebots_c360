"""One-time migration: copy intelligence_fabric.db (SQLite) → Neon Postgres.

Usage (from project root, with venv active and .env set):
    python scripts/migrate_sqlite_to_postgres.py

Prerequisites:
    - DATABASE_URL env var pointing to Neon (pooled connection string)
    - DB_PATH env var pointing to the old SQLite file (default: intelligence_fabric.db)
    - GOOGLE_API_KEY (or OPENAI_API_KEY) for embedding backfill
"""

import json
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import os
DB_PATH_SQLITE = os.getenv("DB_PATH", "intelligence_fabric.db")


def _sqlite_rows(sqlite_path: str, table: str) -> list[dict]:
    """Fetch all rows from a SQLite table as list of dicts."""
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT * FROM {table}")
        rows = [dict(r) for r in cur.fetchall()]
    except sqlite3.OperationalError:
        rows = []  # table may not exist in older DBs
    conn.close()
    return rows


def _parse_json_field(value):
    """Safely parse a TEXT JSON field from SQLite."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


JSON_FIELDS = {
    "transcripts":        ["segments"],
    "insights":           ["objection_patterns", "qualification_signals",
                           "escalation_signals", "kb_gaps", "raw_insights_json"],
    "plans":              ["plan"],
    "plan_patches":       ["patch"],
    "workflow_sessions":  ["questions", "answers"],
    "platform_knowledge": [],
    "conversation_turns": [],
}

# Primary-key column per table (for ON CONFLICT). workflow_sessions keys on client_id.
CONFLICT_KEYS = {
    "workflow_sessions": "client_id",
}


def migrate_table(pool, table: str, sqlite_rows: list[dict], json_fields: list[str], conflict_key: str = "id") -> int:
    """INSERT rows from SQLite into Postgres. Returns count inserted."""
    if not sqlite_rows:
        print(f"  {table}: 0 rows (empty or missing in SQLite)")
        return 0

    from psycopg.types.json import Jsonb

    inserted = 0
    for row in sqlite_rows:
        # Parse TEXT-JSON fields into Python objects, then wrap as Jsonb
        for field in json_fields:
            if field in row:
                row[field] = Jsonb(_parse_json_field(row[field]))

        cols = list(row.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        col_names = ", ".join(cols)
        values = [row[c] for c in cols]

        # One connection (transaction) per row so a single failure can't abort the rest
        try:
            with pool.connection() as conn:
                conn.execute(
                    f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) "
                    f"ON CONFLICT ({conflict_key}) DO NOTHING",
                    values,
                )
            inserted += 1
        except Exception as e:
            print(f"  Warning: skipped row in {table}: {e}")

    print(f"  {table}: {inserted}/{len(sqlite_rows)} rows migrated")
    return inserted


def backfill_knowledge_embeddings(pool) -> None:
    """Embed platform_knowledge facts that have no embedding yet."""
    from shared.embeddings import embed_batch
    from shared.db import set_knowledge_embedding

    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT id, topic, fact FROM platform_knowledge WHERE embedding IS NULL"
        ).fetchall()

    if not rows:
        print("  platform_knowledge: no embeddings to backfill")
        return

    texts = [f"{r['topic']}: {r['fact']}" for r in rows]
    print(f"  platform_knowledge: embedding {len(texts)} facts...")
    embeddings = embed_batch(texts)
    for row, emb in zip(rows, embeddings):
        set_knowledge_embedding(row["id"], emb)
    print(f"  platform_knowledge: {len(texts)} embeddings backfilled")


def main():
    sqlite_path = DB_PATH_SQLITE
    if not Path(sqlite_path).exists():
        print(f"SQLite file not found: {sqlite_path}")
        print("Set DB_PATH env var to the old SQLite file path.")
        sys.exit(1)

    print(f"Source: {sqlite_path}")
    print(f"Target: Neon Postgres (DATABASE_URL)")
    print()

    # Init Postgres schema
    from shared.db import init_db, _get_pool
    print("Initialising Postgres schema...")
    init_db()
    print("Schema ready.")
    print()

    pool = _get_pool()

    # Migrate all tables
    print("Migrating tables...")
    totals = {}
    for table, json_fields in JSON_FIELDS.items():
        rows = _sqlite_rows(sqlite_path, table)
        totals[table] = migrate_table(pool, table, rows, json_fields,
                                      conflict_key=CONFLICT_KEYS.get(table, "id"))

    print()

    # Backfill embeddings on platform_knowledge
    print("Backfilling platform_knowledge embeddings...")
    backfill_knowledge_embeddings(pool)
    print()

    # Seed bot examples RAG corpus
    print("Seeding bot_examples RAG corpus...")
    from seed.seed_bot_examples import seed as seed_bots
    seed_bots(truncate=True)
    print()

    # Summary
    print("=" * 50)
    print("MIGRATION COMPLETE — row counts:")
    for table, count in totals.items():
        print(f"  {table:30s} {count:>6}")
    print("=" * 50)

    # Close the pool cleanly to avoid noisy shutdown warnings on Python 3.14
    pool.close()


if __name__ == "__main__":
    main()
