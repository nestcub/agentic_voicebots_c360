"""Deterministic prompt-packing helpers for the intelligence planner.

This module is intentionally framework-free and side-effect free so it can be
unit-tested with plain Python fixtures. The helpers compact planner context into
stable, bounded shapes before prompt assembly.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
from typing import Any, Iterable, Mapping, Sequence

PACK_MODES = ("create", "patch", "advice", "rescan")

DEFAULT_DYNAMIC_BUDGETS = {
    "create": 10_000,
    "patch": 7_000,
    "advice": 6_000,
    "rescan": 8_500,
}

_INSIGHT_LIMITS = {
    "objection_patterns": 4,
    "qualification_signals": 4,
    "escalation_signals": 4,
    "kb_gaps": 4,
    "bot_failure_modes": 8,
    "suggested_fixes": 8,
}

_EVIDENCE_LIMITS = {
    "create": 2,
    "patch": 0,
    "advice": 2,
    "rescan": 3,
}

_EXAMPLE_LIMITS = {
    "create": 4,
    "patch": 2,
    "advice": 2,
    "rescan": 3,
}

_UNIT_TYPE_PRIORITY = {
    "reference_system_prompt": 0,
    "bot_examples": 1,
    "reference_intent": 2,
}

_PATCH_EVIDENCE_HINTS = (
    "accent",
    "behavior",
    "call flow",
    "hang up",
    "intent",
    "language",
    "misroute",
    "misrout",
    "misunderstand",
    "not understand",
    "pronunciation",
    "recognition",
    "recognise",
    "recognize",
    "route",
    "routing",
    "script",
    "speech",
    "tone",
    "voice",
)

_DESIGN_RELATED_HINTS = (
    "bot",
    "build",
    "call flow",
    "canvas",
    "design",
    "engine",
    "escalat",
    "intent",
    "kb",
    "language",
    "node",
    "objection",
    "plan",
    "prompt",
    "qualif",
    "route",
    "stage",
    "stt",
    "system prompt",
    "tts",
    "variable",
    "workflow",
)

_RESCAN_HINTS = (
    "check new recordings",
    "check new transcripts",
    "fresh recordings",
    "incorporate new recordings",
    "latest recordings",
    "latest transcripts",
    "new calls",
    "new recordings",
    "new transcript",
    "new transcripts",
    "re-scan",
    "recheck recordings",
    "rescan",
    "scan the recordings again",
)

_PATCH_ACTION_HINTS = (
    "add",
    "adjust",
    "change",
    "expand",
    "fix",
    "improve",
    "include",
    "modify",
    "patch",
    "redo",
    "refine",
    "remove",
    "replace",
    "rewrite",
    "route",
    "shift",
    "shorten",
    "swap",
    "update",
)

_PLAN_TARGET_HINTS = (
    "bot",
    "build_notes",
    "call flow",
    "canvas",
    "escalation",
    "flow",
    "kb",
    "node",
    "objection",
    "plan",
    "prompt",
    "qualification",
    "routing",
    "stage",
    "system prompt",
    "workflow",
)

_ADVICE_HINTS = (
    "best way",
    "how do",
    "how should",
    "what do you recommend",
    "what should",
    "why is",
)

_PLAN_SECTION_HINTS = {
    "system_prompt": (
        "instruction",
        "language rule",
        "persona",
        "prompt",
        "response",
        "script",
        "system prompt",
        "tone",
        "wording",
    ),
    "workflow_blueprint": (
        "branch",
        "call flow",
        "conditional",
        "flow",
        "handoff path",
        "node",
        "route",
        "routing",
        "stage",
        "webhook",
        "workflow",
    ),
    "qualification_questions": (
        "ask",
        "capture",
        "collect",
        "lead",
        "qualification",
        "qualify",
        "question",
        "variable",
    ),
    "objection_handling": (
        "busy",
        "cost",
        "expensive",
        "not interested",
        "objection",
        "price",
        "rebuttal",
    ),
    "escalation_rules": (
        "agent",
        "callback",
        "escalat",
        "handoff",
        "human",
        "supervisor",
        "transfer",
    ),
    "kb_scaffold": (
        "answer",
        "faq",
        "info",
        "kb",
        "knowledge",
        "product",
    ),
    "build_notes": (
        "build",
        "config",
        "engine",
        "language",
        "outbound",
        "silence",
        "stt",
        "tts",
    ),
}

_TOP_LEVEL_PLAN_KEYS = (
    "workflow_blueprint",
    "system_prompt",
    "qualification_questions",
    "objection_handling",
    "escalation_rules",
    "kb_scaffold",
    "build_notes",
)

_ELLIPSIS = "..."


@dataclass(frozen=True)
class SectionSpec:
    """A prompt section that can be trimmed or dropped to fit a char budget."""

    name: str
    text: str
    priority: int
    required: bool = False
    min_chars: int = 0


def classify_pack_mode(
    message: str,
    *,
    has_plan: bool = False,
    has_use_case: bool = False,
    has_current_plan: bool | None = None,
) -> str:
    """Classify prompt-packing mode using local deterministic heuristics."""

    if has_current_plan is not None:
        has_plan = has_current_plan
    normalized = _normalize_text(message).lower()
    if _contains_any(normalized, _RESCAN_HINTS):
        return "rescan"

    if not has_plan or not has_use_case:
        return "create"

    if _looks_like_patch_request(normalized):
        return "patch"

    if _looks_like_advice_request(normalized):
        return "advice"

    return "patch"


def compact_insights(insights: Mapping[str, Any] | None) -> str:
    """Render aggregated insights as short, deterministic bullets."""

    payload = insights or {}
    lines = ["Insights:"]

    call_count = payload.get("call_count", 0)
    avg_score = payload.get("avg_agent_score")
    avg_score_text = "n/a" if avg_score is None else str(avg_score)
    lines.append(f"- Calls: {call_count}; avg agent score: {avg_score_text}")

    labels = {
        "objection_patterns": "Objections",
        "qualification_signals": "Qualification signals",
        "escalation_signals": "Escalation signals",
        "kb_gaps": "KB gaps",
        "bot_failure_modes": "Bot failure modes",
        "suggested_fixes": "Suggested fixes",
    }

    for key in (
        "objection_patterns",
        "qualification_signals",
        "escalation_signals",
        "kb_gaps",
        "bot_failure_modes",
        "suggested_fixes",
    ):
        values = _sorted_unique_strings(payload.get(key) or [])
        line = _render_compact_value_line(
            labels[key],
            values,
            limit=_INSIGHT_LIMITS[key],
        )
        if line:
            lines.append(line)

    return "\n".join(lines)


def compact_call_evidence(
    hits: Sequence[Mapping[str, Any]] | None,
    *,
    mode: str,
    request_text: str = "",
    quote_cap: int = 240,
) -> str:
    """Render a bounded evidence block with mode-aware transcript limits."""

    validated_mode = _validate_mode(mode)
    limit = _call_evidence_limit(validated_mode, request_text)
    if limit <= 0 or not hits:
        return ""

    deduped: list[Mapping[str, Any]] = []
    seen_quotes: set[str] = set()
    for hit in sorted(hits, key=_evidence_sort_key):
        quote = _normalize_text(hit.get("text", ""))
        if not quote or quote in seen_quotes:
            continue
        seen_quotes.add(quote)
        deduped.append(hit)
        if len(deduped) >= limit:
            break

    if not deduped:
        return ""

    lines = ["Call evidence:"]
    for hit in deduped:
        role_sequence = _normalize_text(hit.get("role_sequence", "")) or "unknown"
        timestamp = _format_timestamp(hit.get("start_sec"))
        score = _format_similarity(hit.get("score"))
        quote = _truncate(_normalize_text(hit.get("text", "")), quote_cap)
        lines.append(f'- {role_sequence} {timestamp} ({score}) "{quote}"')
    return "\n".join(lines)


def rerank_and_compact_examples(
    examples: Sequence[Mapping[str, Any]] | None,
    *,
    mode: str,
    request_text: str = "",
) -> list[dict[str, Any]]:
    """Re-rank examples with unit-type priority and compact nested content."""

    validated_mode = _validate_mode(mode)
    if not examples:
        return []

    if validated_mode == "advice" and not _is_design_related(request_text):
        return []

    limit = _EXAMPLE_LIMITS[validated_mode]
    ranked = sorted(examples, key=_example_sort_key)
    compacted = [
        _compact_example(example)
        for example in ranked[:limit]
    ]
    return compacted


def render_compact_examples(examples: Sequence[Mapping[str, Any]] | None) -> str:
    """Render compacted examples as stable minified JSON."""

    if not examples:
        return ""
    return "Retrieved examples:\n" + json.dumps(
        list(examples),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def compact_current_plan(
    plan: Mapping[str, Any] | None,
    *,
    mode: str,
    request_text: str = "",
    system_prompt_cap: int = 1_200,
) -> dict[str, Any]:
    """Compact the current plan into a manifest plus relevant sections."""

    validated_mode = _validate_mode(mode)
    if not plan:
        return {"manifest": {}, "selected_sections": [], "sections": {}}

    manifest = build_plan_manifest(plan)
    selected_sections: list[str] = []
    sections: dict[str, Any] = {}

    if validated_mode == "patch":
        selected_sections = select_relevant_plan_sections(request_text)
        if selected_sections:
            for key in selected_sections:
                sections[key] = _compact_plan_section(key, plan.get(key), system_prompt_cap)
        else:
            sections["system_prompt"] = _compact_plan_section(
                "system_prompt",
                plan.get("system_prompt"),
                system_prompt_cap,
            )
            sections["workflow_blueprint"] = _compact_plan_section(
                "workflow_blueprint",
                plan.get("workflow_blueprint"),
                system_prompt_cap,
            )

    return {
        "manifest": manifest,
        "selected_sections": selected_sections,
        "sections": sections,
    }


def build_plan_manifest(plan: Mapping[str, Any] | None) -> dict[str, Any]:
    """Build a deterministic plan manifest with the highest-yield summary fields."""

    payload = plan or {}
    blueprint = payload.get("workflow_blueprint") or {}
    build_notes = payload.get("build_notes") or {}

    stages = [
        {
            "stage_id": stage.get("stage_id"),
            "name": _normalize_text(stage.get("name", "")),
            "node_type": _normalize_text(stage.get("node_type", "")),
            "purpose": _normalize_text(stage.get("purpose", "")),
        }
        for stage in (blueprint.get("stages") or [])[:12]
        if isinstance(stage, Mapping)
    ]

    return {
        "description": _normalize_text(blueprint.get("description", "")),
        "stages": stages,
        "build_summary": {
            "language": _normalize_text(build_notes.get("language", "")),
            "tts_engine": _normalize_text(build_notes.get("tts_engine", "")),
            "stt_engine": _normalize_text(build_notes.get("stt_engine", "")),
            "variables_required": _sorted_unique_strings(
                build_notes.get("variables_required") or []
            )[:12],
            "outbound_params": _sorted_unique_strings(
                build_notes.get("outbound_params") or []
            )[:12],
        },
    }


def select_relevant_plan_sections(
    request_text: str,
    *,
    max_sections: int | None = None,
) -> list[str]:
    """Select top-level plan sections relevant to a patch request."""

    normalized = _normalize_text(request_text).lower()
    matched: list[str] = []
    for key in _TOP_LEVEL_PLAN_KEYS:
        hints = _PLAN_SECTION_HINTS.get(key, ())
        if _contains_any(normalized, hints):
            matched.append(key)
    if max_sections is not None:
        return matched[:max_sections]
    return matched


def render_compact_plan(compacted_plan: Mapping[str, Any] | None) -> str:
    """Render the compact current-plan payload as stable minified JSON."""

    if not compacted_plan:
        return ""
    return "Current plan:\n" + json.dumps(
        compacted_plan,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def compact_recent_turns(
    turns: Sequence[Mapping[str, Any]] | None,
    *,
    max_turns: int = 4,
    turn_cap: int = 180,
) -> str:
    """Render recent turns in one-line bounded form."""

    if not turns:
        return ""

    chosen = list(turns)[-max_turns:]
    lines = ["Recent turns:"]
    for turn in chosen:
        role = _normalize_text(turn.get("role", "")) or "unknown"
        content = _truncate(_normalize_text(turn.get("content", "")), turn_cap)
        lines.append(f"- {role}: {content}")
    return "\n".join(lines)


def fit_prompt_budget(
    sections: Sequence[SectionSpec | Mapping[str, Any]],
    budget_chars: int,
    *,
    separator: str = "\n\n",
) -> dict[str, Any]:
    """Trim and drop low-priority sections until the joined text fits the budget."""

    if budget_chars < 0:
        raise ValueError("budget_chars must be non-negative")

    normalized = [_coerce_section(section) for section in sections]
    if not normalized:
        return {"sections": [], "text": "", "total_chars": 0, "dropped": [], "truncated": []}

    working = [asdict(section) for section in normalized]

    def _joined_text() -> str:
        return separator.join(part["text"] for part in working if part["text"])

    total_chars = len(_joined_text())
    if total_chars <= budget_chars:
        return {
            "sections": working,
            "text": _joined_text(),
            "total_chars": total_chars,
            "dropped": [],
            "truncated": [],
        }

    dropped: list[str] = []
    truncated: list[str] = []
    ordered_indexes = sorted(
        range(len(working)),
        key=lambda idx: (
            working[idx]["priority"],
            idx,
        ),
        reverse=True,
    )

    for idx in ordered_indexes:
        if total_chars <= budget_chars:
            break

        section = working[idx]
        original_text = section["text"]
        if not original_text:
            continue

        min_chars = max(0, int(section.get("min_chars", 0)))
        if len(original_text) > min_chars:
            overflow = total_chars - budget_chars
            target_len = max(min_chars, len(original_text) - overflow)
            trimmed = _truncate(original_text, target_len)
            if trimmed != original_text:
                section["text"] = trimmed
                if section["name"] not in truncated:
                    truncated.append(section["name"])
                total_chars = len(_joined_text())

        if total_chars <= budget_chars:
            break

        if not section["required"]:
            section["text"] = ""
            if section["name"] not in dropped:
                dropped.append(section["name"])
            total_chars = len(_joined_text())

    return {
        "sections": working,
        "text": _joined_text(),
        "total_chars": total_chars,
        "dropped": dropped,
        "truncated": truncated,
    }


def _compact_example(example: Mapping[str, Any]) -> dict[str, Any]:
    content = example.get("content") or {}
    compacted: dict[str, Any] = {
        "unit_type": _normalize_text(example.get("unit_type", "")),
        "name": _normalize_text(example.get("name", "")),
        "use_case": _truncate(_normalize_text(example.get("use_case", "")), 280),
        "similarity": _float_or_none(example.get("score")),
    }

    prompt_text = _extract_system_prompt(content)
    if prompt_text:
        compacted["system_prompt_excerpt"] = _truncate(prompt_text, 1_200)

    blueprint = _extract_workflow_blueprint(content)
    if blueprint:
        stages = blueprint.get("stages") or []
        compacted["workflow_blueprint"] = {
            "description": _normalize_text(blueprint.get("description", "")),
            "stages": [
                {
                    "stage_id": stage.get("stage_id"),
                    "name": _normalize_text(stage.get("name", "")),
                    "node_type": _normalize_text(stage.get("node_type", "")),
                    "purpose": _normalize_text(stage.get("purpose", "")),
                }
                for stage in stages[:6]
                if isinstance(stage, Mapping)
            ],
        }

    questions = content.get("qualification_questions") or []
    if questions:
        compacted["qualification_questions"] = [
            {
                "question": _normalize_text(item.get("question", "")),
                "variable": _normalize_text(item.get("variable", "")),
                "purpose": _normalize_text(item.get("purpose", "")),
            }
            for item in questions[:3]
            if isinstance(item, Mapping)
        ]

    objections = content.get("objection_handling") or {}
    if isinstance(objections, Mapping) and objections:
        compacted["objection_handling"] = {
            key: _normalize_text(objections[key])
            for key in sorted(objections)[:3]
        }

    escalation_rules = content.get("escalation_rules") or []
    if escalation_rules:
        compacted["escalation_rules"] = [
            {
                "trigger": _normalize_text(item.get("trigger", "")),
                "action": _normalize_text(item.get("action", "")),
                "node_type": _normalize_text(item.get("node_type", "")),
            }
            for item in escalation_rules[:3]
            if isinstance(item, Mapping)
        ]

    build_notes = content.get("build_notes") or {}
    if isinstance(build_notes, Mapping) and build_notes:
        compacted["build_notes"] = {
            "language": _normalize_text(build_notes.get("language", "")),
            "tts_engine": _normalize_text(build_notes.get("tts_engine", "")),
            "stt_engine": _normalize_text(build_notes.get("stt_engine", "")),
            "variables_required": _sorted_unique_strings(
                build_notes.get("variables_required") or []
            )[:8],
        }

    return {key: value for key, value in compacted.items() if value not in ("", None, [], {})}


def _extract_system_prompt(content: Mapping[str, Any]) -> str:
    candidates = (
        content.get("reference_system_prompt"),
        content.get("system_prompt"),
        content.get("prompt_excerpt"),
    )
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return _normalize_text(candidate)
    return ""


def _extract_workflow_blueprint(content: Mapping[str, Any]) -> Mapping[str, Any] | None:
    blueprint = content.get("workflow_blueprint")
    if isinstance(blueprint, Mapping):
        return blueprint
    return None


def _compact_plan_section(key: str, value: Any, system_prompt_cap: int) -> Any:
    if key == "system_prompt":
        return _truncate(_normalize_text(value or ""), system_prompt_cap)

    if key == "workflow_blueprint" and isinstance(value, Mapping):
        return {
            "description": _normalize_text(value.get("description", "")),
            "stages": [
                {
                    "stage_id": stage.get("stage_id"),
                    "name": _normalize_text(stage.get("name", "")),
                    "node_type": _normalize_text(stage.get("node_type", "")),
                    "purpose": _normalize_text(stage.get("purpose", "")),
                }
                for stage in (value.get("stages") or [])[:12]
                if isinstance(stage, Mapping)
            ],
        }

    if key == "qualification_questions" and isinstance(value, Sequence):
        return [
            {
                "question": _normalize_text(item.get("question", "")),
                "variable": _normalize_text(item.get("variable", "")),
                "purpose": _normalize_text(item.get("purpose", "")),
            }
            for item in list(value)[:5]
            if isinstance(item, Mapping)
        ]

    if key == "objection_handling" and isinstance(value, Mapping):
        return {
            item_key: _normalize_text(value[item_key])
            for item_key in sorted(value)[:5]
        }

    if key == "escalation_rules" and isinstance(value, Sequence):
        return [
            {
                "trigger": _normalize_text(item.get("trigger", "")),
                "action": _normalize_text(item.get("action", "")),
                "node_type": _normalize_text(item.get("node_type", "")),
            }
            for item in list(value)[:5]
            if isinstance(item, Mapping)
        ]

    if key == "kb_scaffold" and isinstance(value, Mapping):
        return {
            item_key: _truncate(_normalize_text(value[item_key]), 240)
            for item_key in sorted(value)[:5]
        }

    if key == "build_notes" and isinstance(value, Mapping):
        return {
            "language": _normalize_text(value.get("language", "")),
            "tts_engine": _normalize_text(value.get("tts_engine", "")),
            "stt_engine": _normalize_text(value.get("stt_engine", "")),
            "variables_required": _sorted_unique_strings(value.get("variables_required") or [])[:12],
            "outbound_params": _sorted_unique_strings(value.get("outbound_params") or [])[:12],
            "silence_handle_config": value.get("silence_handle_config") or {},
            "canvas_instructions": [
                _truncate(_normalize_text(item), 180)
                for item in (value.get("canvas_instructions") or [])[:5]
                if _normalize_text(item)
            ],
        }

    return value


def _coerce_section(section: SectionSpec | Mapping[str, Any]) -> SectionSpec:
    if isinstance(section, SectionSpec):
        return section
    if not isinstance(section, Mapping):
        raise TypeError("sections must contain SectionSpec or mapping items")
    return SectionSpec(
        name=str(section.get("name", "")),
        text=str(section.get("text", "")),
        priority=int(section.get("priority", 0)),
        required=bool(section.get("required", False)),
        min_chars=max(0, int(section.get("min_chars", 0))),
    )


def _validate_mode(mode: str) -> str:
    if mode not in PACK_MODES:
        raise ValueError(f"Unsupported pack mode: {mode}")
    return mode


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _truncate(text: str, max_chars: int) -> str:
    normalized = _normalize_text(text)
    if max_chars <= 0:
        return ""
    if len(normalized) <= max_chars:
        return normalized
    if max_chars <= len(_ELLIPSIS):
        return normalized[:max_chars]
    return normalized[: max_chars - len(_ELLIPSIS)].rstrip() + _ELLIPSIS


def _sorted_unique_strings(values: Iterable[Any]) -> list[str]:
    normalized = {_normalize_text(value) for value in values if _normalize_text(value)}
    return sorted(normalized)


def _render_compact_value_line(label: str, values: Sequence[str], *, limit: int) -> str:
    if not values:
        return ""
    head = list(values[:limit])
    tail_count = max(0, len(values) - len(head))
    joined = " | ".join(head)
    if tail_count:
        joined = f"{joined} | +{tail_count} more"
    return f"- {label}: {joined}"


def _contains_any(text: str, hints: Iterable[str]) -> bool:
    return any(hint in text for hint in hints)


def _looks_like_patch_request(normalized: str) -> bool:
    return _contains_any(normalized, _PATCH_ACTION_HINTS) and _contains_any(
        normalized,
        _PLAN_TARGET_HINTS,
    )


def _looks_like_advice_request(normalized: str) -> bool:
    if normalized.endswith("?"):
        return True
    return _contains_any(normalized, _ADVICE_HINTS)


def _call_evidence_limit(mode: str, request_text: str) -> int:
    if mode != "patch":
        return _EVIDENCE_LIMITS[mode]
    normalized = _normalize_text(request_text).lower()
    if _contains_any(normalized, _PATCH_EVIDENCE_HINTS):
        return 2
    return 0


def _is_design_related(request_text: str) -> bool:
    normalized = _normalize_text(request_text).lower()
    if not normalized:
        return True
    return _contains_any(normalized, _DESIGN_RELATED_HINTS)


def _evidence_sort_key(hit: Mapping[str, Any]) -> tuple[Any, ...]:
    score = _float_or_none(hit.get("score"))
    score_key = 0.0 if score is None else -score
    start = hit.get("start_sec")
    start_key = float("inf") if start is None else float(start)
    role_sequence = _normalize_text(hit.get("role_sequence", ""))
    text = _normalize_text(hit.get("text", ""))
    return (score_key, start_key, role_sequence, text)


def _example_sort_key(example: Mapping[str, Any]) -> tuple[Any, ...]:
    unit_type = _normalize_text(example.get("unit_type", ""))
    priority = _UNIT_TYPE_PRIORITY.get(unit_type, 99)
    score = _float_or_none(example.get("score"))
    score_key = 0.0 if score is None else -score
    name = _normalize_text(example.get("name", ""))
    use_case = _normalize_text(example.get("use_case", ""))
    return (priority, score_key, name, use_case)


def _format_timestamp(start_sec: Any) -> str:
    if start_sec is None:
        return "@?"
    try:
        return f"@{round(float(start_sec))}s"
    except (TypeError, ValueError):
        return "@?"


def _format_similarity(score: Any) -> str:
    value = _float_or_none(score)
    if value is None:
        return "similarity n/a"
    return f"similarity {value:.2f}"


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "DEFAULT_DYNAMIC_BUDGETS",
    "PACK_MODES",
    "SectionSpec",
    "build_plan_manifest",
    "classify_mode",
    "classify_pack_mode",
    "compact_examples",
    "compact_call_evidence",
    "compact_current_plan",
    "compact_insights",
    "compact_recent_turns",
    "fit_prompt_budget",
    "fit_sections_to_budget",
    "render_compact_examples",
    "render_compact_plan",
    "rerank_and_compact_examples",
    "select_relevant_sections",
    "select_relevant_plan_sections",
    "truncate_recent_turns",
]


def classify_mode(message: str, has_current_plan: bool = False) -> str:
    """Compatibility wrapper used by tests and lightweight callers."""

    return classify_pack_mode(
        message,
        has_plan=has_current_plan,
        has_use_case=has_current_plan,
        has_current_plan=has_current_plan,
    )


def select_relevant_sections(
    plan: Mapping[str, Any] | None,
    request: str,
    max_sections: int = 7,
) -> list[str]:
    """Compatibility wrapper that keeps only plan keys that actually exist."""

    selected = select_relevant_plan_sections(request, max_sections=max_sections)
    if not plan:
        return selected
    return [key for key in selected if key in plan]


def fit_sections_to_budget(
    sections: Sequence[Mapping[str, Any]],
    budget_chars: int,
) -> list[dict[str, Any]]:
    """Compatibility wrapper returning trimmed content blocks only."""

    normalized = [
        {
            "name": section.get("name", ""),
            "text": section.get("content", section.get("text", "")),
            "priority": section.get("priority", 0),
            "required": section.get("must_keep", section.get("required", False)),
            "min_chars": section.get("min_chars", 0),
        }
        for section in sections
    ]
    result = fit_prompt_budget(normalized, budget_chars)
    packed: list[dict[str, Any]] = []
    for section in result["sections"]:
        if not section["text"]:
            continue
        packed.append(
            {
                "name": section["name"],
                "content": section["text"],
                "must_keep": section["required"],
                "priority": section["priority"],
            }
        )
    return packed


def compact_examples(
    examples: Sequence[Mapping[str, Any]] | None,
    *,
    max_examples: int = 2,
    max_chars: int = 1_200,
) -> list[dict[str, Any]]:
    """Compatibility wrapper for bounded example content."""

    if not examples:
        return []
    compacted: list[dict[str, Any]] = []
    total_chars = 0
    for example in list(examples)[:max_examples]:
        name = _normalize_text(example.get("name", "")) or "example"
        source = example.get("content", example)
        if isinstance(source, str):
            content = _truncate(source, max_chars)
        else:
            content = _truncate(
                json.dumps(source, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
                max_chars,
            )
        compacted.append({"name": name, "content": content})
        total_chars += len(content)
        if total_chars >= max_chars:
            break
    while compacted and sum(len(item["content"]) for item in compacted) > max_chars:
        last = compacted[-1]
        overflow = sum(len(item["content"]) for item in compacted) - max_chars
        last["content"] = _truncate(last["content"], max(1, len(last["content"]) - overflow))
        if not last["content"]:
            compacted.pop()
    return compacted


def truncate_recent_turns(
    turns: Sequence[Mapping[str, Any]] | None,
    *,
    max_turns: int = 4,
    max_chars: int = 480,
) -> list[dict[str, str]]:
    """Compatibility wrapper returning bounded turn dicts."""

    if not turns:
        return []
    chosen = list(turns)[-max_turns:]
    packed: list[dict[str, str]] = []
    used = 0
    remaining_turns = len(chosen)
    for turn in chosen:
        remaining_turns -= 1
        remaining_budget = max_chars - used
        if remaining_budget <= 0:
            break
        reserve = max(0, remaining_turns * 12)
        turn_budget = max(1, remaining_budget - reserve)
        content = _truncate(_normalize_text(turn.get("content", "")), turn_budget)
        packed.append({
            "role": _normalize_text(turn.get("role", "")) or "unknown",
            "content": content,
        })
        used += len(content)
    return packed
