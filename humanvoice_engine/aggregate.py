"""Collapse all per-call gold-extract results into one Human-Voice Parameter Sheet.

Deterministic — no LLM. Equal weight per call (no outcome labels in this MVP).
"""
import json
import statistics

_PHASES = ["opening", "qualification", "interest", "objection", "urgency", "close"]
_PHASE_METRICS = ["rate", "f0_mean", "f0_range", "rms", "pause_ms"]
_SUBSTANCE_LISTS = ["urgency_tactics", "persuasion_moves", "objection_handling",
                    "empathy_markers", "guardrails_and_boundaries", "rapport_building",
                    "turn_taking"]


def _merge_fillers(calls: list[dict]) -> list[dict]:
    """Sum counts per filler word; collect distinct positions/functions."""
    agg: dict[str, dict] = {}
    for c in calls:
        for f in c["gold_extract"].get("filler_lexicon", []):
            word = str(f.get("filler", "")).strip().lower()
            if not word:
                continue
            e = agg.setdefault(word, {"filler": word, "count": 0, "positions": set(), "functions": set()})
            e["count"] += int(f.get("count", 0) or 0)
            if f.get("position"):
                e["positions"].add(f["position"])
            if f.get("function"):
                e["functions"].add(f["function"])
    out = []
    for e in sorted(agg.values(), key=lambda x: -x["count"]):
        out.append({"filler": e["filler"], "count": e["count"],
                    "positions": sorted(e["positions"]), "functions": sorted(e["functions"])})
    return out


def _avg_phase_prosody(calls: list[dict]) -> dict:
    """Average each phase metric across calls that reported that phase."""
    buckets = {p: {m: [] for m in _PHASE_METRICS} for p in _PHASES}
    for c in calls:
        pp = c["gold_extract"].get("phase_prosody", {}) or {}
        for phase in _PHASES:
            metrics = pp.get(phase) or {}
            for m in _PHASE_METRICS:
                v = metrics.get(m)
                if isinstance(v, (int, float)) and v:
                    buckets[phase][m].append(float(v))
    result = {}
    for phase in _PHASES:
        vals = {m: (round(statistics.mean(buckets[phase][m]), 2) if buckets[phase][m] else 0.0)
                for m in _PHASE_METRICS}
        if any(vals.values()):
            result[phase] = vals
    return result


def _output_mapping(phase_prosody: dict) -> dict:
    """Section E: per-phase speed/volume ratios vs the mean across phases (baseline=1.0)."""
    rates = [p["rate"] for p in phase_prosody.values() if p.get("rate")]
    rmss = [p["rms"] for p in phase_prosody.values() if p.get("rms")]
    base_rate = statistics.mean(rates) if rates else 0.0
    base_rms = statistics.mean(rmss) if rmss else 0.0
    mapping = {}
    for phase, p in phase_prosody.items():
        mapping[phase] = {
            "speed_ratio": round(p["rate"] / base_rate, 2) if base_rate and p.get("rate") else 1.0,
            "volume_ratio": round(p["rms"] / base_rms, 2) if base_rms and p.get("rms") else 1.0,
            "pause_ms": p.get("pause_ms", 0.0),
        }
    return mapping


def aggregate(calls: list[dict]) -> dict:
    """Build the Parameter Sheet dict from all per-call results."""
    phase_prosody = _avg_phase_prosody(calls)
    sheet = {
        "call_count": len(calls),
        "filler_lexicon": _merge_fillers(calls),
        "phase_prosody": phase_prosody,
        "output_mapping": _output_mapping(phase_prosody),
        "opening_hooks": [c["gold_extract"].get("opening_hook", "") for c in calls
                          if c["gold_extract"].get("opening_hook")],
        "closing_commitments": [c["gold_extract"].get("closing_commitment", "") for c in calls
                                if c["gold_extract"].get("closing_commitment")],
        "emotional_arcs": [c["gold_extract"].get("emotional_arc", "") for c in calls
                           if c["gold_extract"].get("emotional_arc")],
        "qualification_styles": [c["gold_extract"].get("qualification_style", {}) for c in calls
                                 if c["gold_extract"].get("qualification_style")],
    }
    for key in _SUBSTANCE_LISTS:
        pooled = []
        for c in calls:
            pooled.extend(c["gold_extract"].get(key, []) or [])
        sheet[key] = pooled
    return sheet


def render_markdown(sheet: dict) -> str:
    """Render the Parameter Sheet as the paste-into-Claude Markdown deliverable."""
    L = ["# Human-Voice Parameter Sheet",
         f"\n_Aggregated from {sheet['call_count']} best-agent call(s)._\n",
         "## A. Filler Lexicon"]
    for f in sheet["filler_lexicon"]:
        L.append(f"- **{f['filler']}** — count {f['count']}; "
                 f"positions {', '.join(f['positions']) or 'n/a'}; "
                 f"functions {', '.join(f['functions']) or 'n/a'}")
    L.append("\n## B. Phase Prosody (averaged)")
    for phase, m in sheet["phase_prosody"].items():
        L.append(f"- **{phase}** — rate {m['rate']} w/s, f0_mean {m['f0_mean']} Hz, "
                 f"f0_range {m['f0_range']} Hz, rms {m['rms']}, pause {m['pause_ms']} ms")
    L.append("\n## E. Output Mapping (per-phase TTS ratios, baseline 1.0)")
    for phase, m in sheet["output_mapping"].items():
        L.append(f"- **{phase}** — speed x{m['speed_ratio']}, volume x{m['volume_ratio']}, "
                 f"pause {m['pause_ms']} ms")
    def _section(title, items, fmt):
        L.append(f"\n## {title}")
        if not items:
            L.append("_none observed_")
        for it in items:
            L.append(fmt(it))
    _section("D1. Urgency Tactics", sheet["urgency_tactics"],
             lambda i: f"- {i.get('verbal_move','')} — \"{i.get('verbatim','')}\" (why: {i.get('why_it_worked','')})")
    _section("D2. Persuasion Moves", sheet["persuasion_moves"],
             lambda i: f"- {i.get('technique','')} — \"{i.get('verbatim','')}\" (why: {i.get('why_it_worked','')})")
    _section("D3. Objection Handling", sheet["objection_handling"],
             lambda i: f"- {i.get('objection','')}: {i.get('agent_move','')} -> {i.get('outcome','')} — \"{i.get('verbatim','')}\"")
    _section("D4. Empathy Markers", sheet["empathy_markers"],
             lambda i: f"- {i.get('cue','')} — \"{i.get('verbatim','')}\"")
    _section("D5. Guardrails & Boundaries", sheet["guardrails_and_boundaries"],
             lambda i: f"- {i.get('boundary','')} — {i.get('how_expressed','')} — \"{i.get('verbatim','')}\"")
    _section("D6. Rapport Building", sheet["rapport_building"],
             lambda i: f"- {i.get('technique','')} — \"{i.get('verbatim','')}\"")
    L.append("\n## C. Opening Hooks")
    L.extend(f"- \"{h}\"" for h in sheet["opening_hooks"])
    L.append("\n## C. Closing Commitments")
    L.extend(f"- \"{c}\"" for c in sheet["closing_commitments"])
    return "\n".join(L) + "\n"
