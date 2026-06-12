"""Seed script: decompose best_bots.json into embeddable units and load into bot_examples table.

Idempotent: truncates bot_examples before re-seeding, so safe to re-run after best_bots.json updates.
Run from project root: python -m seed.seed_bot_examples
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

BOTS_PATH = Path(__file__).parent.parent / "intelligence" / "data" / "best_bots.json"

LIST_KEYS = [
    "bot_examples",                     # the 5 full production bots (richest RAG units)
    "adani_specialist_patterns",
    "adani_intent_routing_examples",
    "adani_conditional_examples",
]

SINGLETON_KEYS = [
    "adani_webhook_pattern",
    "adani_set_variable_examples",
    "adani_multichoice_example",
    "adani_language_preference_example",
]

SKIP_KEYS = {"canvas_grammar", "performance_benchmarks"}


def _unit_text(unit_type: str, name: str, use_case: str, content: dict) -> str:
    return f"{unit_type} | {name} | {use_case}\n{json.dumps(content, ensure_ascii=False)}"


def _extract_name_use_case(item: dict, fallback_name: str) -> tuple[str, str]:
    name = (
        item.get("name")
        or item.get("pattern_name")
        or item.get("example_name")
        or item.get("title")
        or fallback_name
    )
    use_case = (
        item.get("use_case")
        or item.get("purpose")
        or item.get("description")
        or item.get("scenario")
        or name
    )
    return str(name), str(use_case)


def build_units(bots: dict) -> list[dict]:
    """Return list of {unit_type, name, use_case, content} ready for embedding."""
    units = []

    for key in LIST_KEYS:
        items = bots.get(key, [])
        if not isinstance(items, list):
            items = [items]
        for i, item in enumerate(items):
            if not item:
                continue
            name, use_case = _extract_name_use_case(item, f"{key}_{i}")
            units.append({
                "unit_type": key,
                "name": name,
                "use_case": use_case,
                "content": item,
            })

    for key in SINGLETON_KEYS:
        item = bots.get(key)
        if not item:
            continue
        if isinstance(item, list):
            for i, sub in enumerate(item):
                if not sub:
                    continue
                name, use_case = _extract_name_use_case(sub, f"{key}_{i}")
                units.append({"unit_type": key, "name": name, "use_case": use_case, "content": sub})
        else:
            name, use_case = _extract_name_use_case(item, key)
            units.append({"unit_type": key, "name": name, "use_case": use_case, "content": item})

    return units


def seed(truncate: bool = True) -> None:
    from shared.db import add_bot_example, _get_pool
    from shared.embeddings import embed_batch

    with open(BOTS_PATH, encoding="utf-8") as f:
        bots = json.load(f)

    units = build_units(bots)
    if not units:
        print("No units to seed — check best_bots.json structure.")
        return

    print(f"Seeding {len(units)} bot example units...")

    if truncate:
        with _get_pool().connection() as conn:
            conn.execute("TRUNCATE TABLE bot_examples")
        print("Truncated bot_examples table.")

    texts = [_unit_text(u["unit_type"], u["name"], u["use_case"], u["content"]) for u in units]
    embeddings = embed_batch(texts)

    for u, emb in zip(units, embeddings):
        add_bot_example(u["unit_type"], u["name"], u["use_case"], u["content"], emb)

    print(f"Seeded {len(units)} bot examples into bot_examples table.")


if __name__ == "__main__":
    seed(truncate="--no-truncate" not in sys.argv)
