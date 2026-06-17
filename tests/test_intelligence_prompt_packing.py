"""Regression tests for the forthcoming intelligence.prompt_packing helper module.

This is a plain assert-style script, not a pytest test module. Run:
    python3 tests/test_intelligence_prompt_packing.py

Expected helper API:
    - classify_mode(message, has_current_plan=False) -> "create" | "patch" | "advice" | "rescan"
    - select_relevant_sections(plan, request, max_sections=...) -> list[str]
    - fit_sections_to_budget(sections, budget_chars=...) -> list[dict]
    - compact_examples(examples, max_examples=..., max_chars=...) -> list[dict]
    - truncate_recent_turns(turns, max_turns=..., max_chars=...) -> list[dict]

Each test prints "PASS <name>" and the script prints "ALL PASS" at the end.
"""

from __future__ import annotations

import os
import sys

# Make the repo root importable when run directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intelligence.prompt_packing import (
    classify_mode,
    compact_examples,
    fit_sections_to_budget,
    select_relevant_sections,
    truncate_recent_turns,
)


def _total_chars(items: list[dict], key: str = "content") -> int:
    return sum(len(str(item.get(key, ""))) for item in items)


def test_classify_mode_routes_create_patch_advice_and_rescan():
    assert classify_mode(
        "Build me a new inbound appointment-booking bot for dental clinics.",
        has_current_plan=False,
    ) == "create"

    assert classify_mode(
        "Add a VOICE_WEBHOOK at the start and pass @caller_number into it.",
        has_current_plan=True,
    ) == "patch"

    assert classify_mode(
        "The bot fails to recognise speech in noisy environments. What should I do?",
        has_current_plan=True,
    ) == "advice"

    assert classify_mode(
        "Check the new recordings for patterns and update the plan with what changed.",
        has_current_plan=True,
    ) == "rescan"

    print("PASS test_classify_mode_routes_create_patch_advice_and_rescan")


def test_select_relevant_sections_for_webhook_patch():
    plan = {
        "workflow_blueprint": {
            "nodes": ["START", "LANGUAGE_DETECT", "QUALIFY", "TRANSFER"]
        },
        "system_prompt": "Collect the caller context and follow the routing rules exactly.",
        "qualification_questions": ["What city are you in?", "Which vehicle do you own?"],
        "objection_handling": {"too_busy": "Offer a callback."},
        "escalation_rules": {"angry_customer": "Transfer to a supervisor."},
        "kb_scaffold": {"faqs": ["hours", "pricing"]},
        "build_notes": {
            "variables": ["@caller_number", "@bot_language"],
            "integrations": ["crm_lookup"],
        },
    }

    selected = select_relevant_sections(
        plan,
        "Add a VOICE_WEBHOOK at the start, send @caller_number to it, and keep the rest untouched.",
        max_sections=3,
    )

    assert "workflow_blueprint" in selected, selected
    assert "build_notes" in selected, selected
    assert "system_prompt" in selected, selected
    assert "qualification_questions" not in selected, selected
    assert "objection_handling" not in selected, selected
    assert len(selected) <= 3, selected

    print("PASS test_select_relevant_sections_for_webhook_patch")


def test_fit_sections_to_budget_preserves_must_keep_blocks():
    sections = [
        {
            "name": "system_prompt",
            "content": "S" * 180,
            "must_keep": True,
            "priority": 100,
        },
        {
            "name": "recent_turns",
            "content": "R" * 90,
            "must_keep": True,
            "priority": 90,
        },
        {
            "name": "examples",
            "content": "E" * 140,
            "must_keep": False,
            "priority": 40,
        },
        {
            "name": "call_evidence",
            "content": "C" * 140,
            "must_keep": False,
            "priority": 30,
        },
    ]

    packed = fit_sections_to_budget(sections, budget_chars=320)
    kept_names = [section["name"] for section in packed]

    assert "system_prompt" in kept_names, kept_names
    assert "recent_turns" in kept_names, kept_names
    assert _total_chars(packed) <= 320, _total_chars(packed)
    assert len(packed) < len(sections), packed

    print("PASS test_fit_sections_to_budget_preserves_must_keep_blocks")


def test_compact_examples_stays_within_bounds():
    examples = [
        {"name": "ex-1", "content": "alpha " * 30},
        {"name": "ex-2", "content": "beta " * 28},
        {"name": "ex-3", "content": "gamma " * 26},
        {"name": "ex-4", "content": "delta " * 24},
    ]

    compacted = compact_examples(examples, max_examples=2, max_chars=220)

    assert len(compacted) <= 2, compacted
    assert _total_chars(compacted) <= 220, _total_chars(compacted)
    assert all(example["content"].strip() for example in compacted), compacted
    assert all(example["name"] in {"ex-1", "ex-2", "ex-3", "ex-4"} for example in compacted)

    print("PASS test_compact_examples_stays_within_bounds")


def test_truncate_recent_turns_enforces_tail_and_limits():
    turns = [
        {"role": "user", "content": "turn-1 " + ("a" * 20)},
        {"role": "assistant", "content": "turn-2 " + ("b" * 20)},
        {"role": "user", "content": "turn-3 " + ("c" * 20)},
        {"role": "assistant", "content": "turn-4 " + ("d" * 20)},
        {"role": "user", "content": "turn-5 " + ("e" * 20)},
        {"role": "assistant", "content": "turn-6 " + ("f" * 20)},
    ]

    trimmed = truncate_recent_turns(turns, max_turns=4, max_chars=120)

    assert len(trimmed) <= 4, trimmed
    assert _total_chars(trimmed) <= 120, _total_chars(trimmed)
    assert trimmed[-1]["role"] == "assistant", trimmed
    assert "turn-6" in trimmed[-1]["content"], trimmed[-1]
    assert all("turn-1" not in turn["content"] for turn in trimmed), trimmed
    assert all("turn-2" not in turn["content"] for turn in trimmed), trimmed

    print("PASS test_truncate_recent_turns_enforces_tail_and_limits")


def main() -> int:
    tests = [
        test_classify_mode_routes_create_patch_advice_and_rescan,
        test_select_relevant_sections_for_webhook_patch,
        test_fit_sections_to_budget_preserves_must_keep_blocks,
        test_compact_examples_stays_within_bounds,
        test_truncate_recent_turns_enforces_tail_and_limits,
    ]
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            print(f"FAIL {test.__name__}: {exc}")
            return 1
        except Exception as exc:  # noqa: BLE001 - plain-script regression harness
            print(f"ERROR {test.__name__}: {type(exc).__name__}: {exc}")
            return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
