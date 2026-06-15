"""Ingest Adani reference system prompts and intents into the RAG corpus.

Sections > ~1500 tokens (~6000 chars) are split into overlapping windows so no
embedding is silently truncated. Idempotent: deletes existing rows for each
unit_type before re-inserting.

Usage:
    PYTHONPATH=. venv/bin/python scripts/ingest_reference_prompts.py
"""

import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from shared.db import init_db, add_bot_example, _get_pool
from shared.embeddings import embed_batch

EMBED_DELAY = 5.0  # seconds between calls — Gemini free tier: 15 RPM = 4s minimum


def _embed_with_batching(texts: list[str]) -> list[list[float]]:
    """Embed texts one at a time with delays to stay within Gemini free-tier rate limits."""
    from shared.embeddings import embed
    all_vecs = []
    for i, text in enumerate(texts):
        all_vecs.append(embed(text))
        if i < len(texts) - 1:
            time.sleep(EMBED_DELAY)
        if (i + 1) % 5 == 0:
            print(f"    {i + 1}/{len(texts)} embedded …")
    return all_vecs

SP_PATH     = "data/system_prompts/adani_bot_sp.md"
INTENT_PATH = "data/intents_description.jsons/adani_bot_intents.md"

WINDOW_CHARS = 4800   # ~1200 tokens — safe under Gemini 2048-token limit
STEP_CHARS   = 3600   # 1200-char overlap keeps context across windows
SPLIT_ABOVE  = 6000   # only window bodies larger than this


def _windows(body: str) -> list[str]:
    """Split body into overlapping windows; return as-is if small enough."""
    if len(body) <= SPLIT_ABOVE:
        return [body]
    parts = []
    start = 0
    while start < len(body):
        parts.append(body[start:start + WINDOW_CHARS])
        start += STEP_CHARS
    return parts


def _clear(unit_type: str) -> int:
    with _get_pool().connection() as conn:
        n = conn.execute(
            "DELETE FROM bot_examples WHERE unit_type=%s", (unit_type,)
        ).rowcount
    return n


def ingest_system_prompts() -> int:
    unit_type = "reference_system_prompt"
    removed = _clear(unit_type)
    if removed:
        print(f"  cleared {removed} stale {unit_type} rows")

    with open(SP_PATH, encoding="utf-8") as f:
        raw = f.read()

    # Split on '## ' headers — each section includes its heading
    parts = re.split(r"^(## .+)$", raw, flags=re.MULTILINE)
    # parts: ['', 'heading', 'body', 'heading', 'body', ...]
    sections = []
    i = 1
    while i < len(parts) - 1:
        heading = parts[i].lstrip("# ").strip()
        body    = parts[i + 1].strip()
        if heading and body:
            sections.append((heading, body))
        i += 2

    print(f"\n  System prompts: {len(sections)} sections found")

    units: list[dict] = []
    for heading, body in sections:
        windows = _windows(body)
        for wi, window in enumerate(windows):
            suffix = f" #{wi + 1}" if len(windows) > 1 else ""
            name     = heading[:80] + suffix
            use_case = f"Adani reference — {heading[:60]}{suffix}"
            embed_text = f"{unit_type} | {name} | {use_case}\n{window}"
            units.append({
                "unit_type":   unit_type,
                "name":        name,
                "use_case":    use_case,
                "content":     {"heading": heading, "text": window, "window": wi + 1},
                "embed_text":  embed_text,
            })

    print(f"  Embedding {len(units)} units …")
    vecs = _embed_with_batching([u["embed_text"] for u in units])
    for u, v in zip(units, vecs):
        add_bot_example(u["unit_type"], u["name"], u["use_case"], u["content"], v)
    print(f"  Stored {len(units)} {unit_type} units")
    return len(units)


def ingest_intents() -> int:
    unit_type = "reference_intent"
    removed = _clear(unit_type)
    if removed:
        print(f"  cleared {removed} stale {unit_type} rows")

    with open(INTENT_PATH, encoding="utf-8") as f:
        raw = f.read()

    parts = re.split(r"^(## CATEGORY:.+)$", raw, flags=re.MULTILINE)
    sections = []
    i = 1
    while i < len(parts) - 1:
        heading = parts[i].replace("## CATEGORY:", "").strip()
        body    = parts[i + 1].strip()
        if heading and body:
            sections.append((heading, body))
        i += 2

    print(f"\n  Intents: {len(sections)} categories found")

    units: list[dict] = []
    for heading, body in sections:
        windows = _windows(body)
        for wi, window in enumerate(windows):
            suffix = f" #{wi + 1}" if len(windows) > 1 else ""
            name     = heading[:80] + suffix
            use_case = f"Adani intent — {heading[:60]}{suffix}"
            embed_text = f"{unit_type} | {name} | {use_case}\n{window}"
            units.append({
                "unit_type":   unit_type,
                "name":        name,
                "use_case":    use_case,
                "content":     {"category": heading, "text": window, "window": wi + 1},
                "embed_text":  embed_text,
            })

    print(f"  Embedding {len(units)} units …")
    vecs = _embed_with_batching([u["embed_text"] for u in units])
    for u, v in zip(units, vecs):
        add_bot_example(u["unit_type"], u["name"], u["use_case"], u["content"], v)
    print(f"  Stored {len(units)} {unit_type} units")
    return len(units)


if __name__ == "__main__":
    init_db()
    sp_count     = ingest_system_prompts()
    intent_count = ingest_intents()
    print(f"\nDone: {sp_count} reference_system_prompt + {intent_count} reference_intent units")

    with _get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT unit_type, count(*) as n FROM bot_examples GROUP BY unit_type ORDER BY unit_type"
        ).fetchall()
    print("\nCorpus summary:")
    for r in rows:
        print(f"  {r['unit_type']:40s} {r['n']}")
    _get_pool().close()
