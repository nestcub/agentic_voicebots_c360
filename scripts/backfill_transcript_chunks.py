"""Backfill transcript_chunks table from all existing transcripts in Postgres.

Usage (from project root, with venv active and .env set):
    PYTHONPATH=. venv/bin/python scripts/backfill_transcript_chunks.py

This script:
  1. Loads every transcript from the transcripts table.
  2. Deletes any existing chunks for that transcript (idempotent re-run).
  3. Chunks the diarized segments via shared.chunking.chunk_segments.
  4. Embeds all chunk texts in one batch call.
  5. Writes chunks + embeddings to transcript_chunks.
  6. Prints per-client chunk counts at the end.
"""

import os
from dotenv import load_dotenv

load_dotenv()

from shared.db import _get_pool, init_db, get_transcripts, delete_transcript_chunks, add_transcript_chunk
from shared.chunking import chunk_segments
from shared.embeddings import embed_batch


def main():
    init_db()
    pool = _get_pool()

    transcripts = get_transcripts()
    print(f"Found {len(transcripts)} transcripts to backfill")

    for t in transcripts:
        transcript_id = t["id"]
        client_id = t["client_id"]
        segments = t.get("segments") or t.get("diarized_segments") or []

        if not segments:
            print(f"  skip {transcript_id}: no segments")
            continue

        delete_transcript_chunks(transcript_id)
        chunks = chunk_segments(segments)

        if not chunks:
            print(f"  skip {transcript_id}: no chunks produced")
            continue

        vecs = embed_batch([c["text"] for c in chunks])
        for c, v in zip(chunks, vecs):
            add_transcript_chunk(
                transcript_id,
                client_id,
                c["chunk_index"],
                c["role_sequence"],
                c["start"],
                c["end"],
                c["text"],
                v,
            )

        print(f"  indexed {len(chunks)} chunks for transcript {transcript_id} (client: {client_id})")

    # Print per-client chunk counts
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT client_id, count(*) as cnt FROM transcript_chunks GROUP BY client_id"
        ).fetchall()

    print("\nPer-client chunk counts:")
    for row in rows:
        print(f"  {row['client_id']}: {row['cnt']} chunks")

    pool.close()


if __name__ == "__main__":
    main()
