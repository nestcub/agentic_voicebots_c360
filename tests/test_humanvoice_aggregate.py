"""Tests for humanvoice_engine.aggregate — pure functions, no network."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _call(fname, filler, count, opening_rate):
    return {
        "filename": fname,
        "prosody": {"pauses": {"count": 1, "mean_ms": 900.0}},
        "gold_extract": {
            "filler_lexicon": [{"filler": filler, "count": count, "position": "mid", "function": "buy-time"}],
            "urgency_tactics": [{"trigger_context": "uncommitted", "verbal_move": "scarcity",
                                 "prosody_signature": "faster+louder", "verbatim": "sirf isi weekend",
                                 "why_it_worked": "scarcity"}],
            "persuasion_moves": [], "objection_handling": [], "empathy_markers": [],
            "guardrails_and_boundaries": [], "qualification_style": {}, "rapport_building": [],
            "turn_taking": [],
            "phase_prosody": {"opening": {"rate": opening_rate, "f0_mean": 180, "f0_range": 40,
                                          "rms": 0.05, "pause_ms": 300}},
            "opening_hook": "Namaste", "closing_commitment": "Kal call", "emotional_arc": "warm->urgent",
        },
    }


def test_aggregate_merges_fillers_and_averages_phase():
    from humanvoice_engine.aggregate import aggregate
    calls = [_call("a.aac", "matlab", 3, 3.0), _call("b.aac", "matlab", 1, 5.0)]
    sheet = aggregate(calls)
    fillers = {f["filler"]: f for f in sheet["filler_lexicon"]}
    assert fillers["matlab"]["count"] == 4          # 3 + 1 merged
    assert abs(sheet["phase_prosody"]["opening"]["rate"] - 4.0) < 0.01  # (3+5)/2
    assert sheet["call_count"] == 2
    assert len(sheet["urgency_tactics"]) == 2       # pooled across calls
    assert "output_mapping" in sheet


def test_render_markdown_has_sections():
    from humanvoice_engine.aggregate import aggregate, render_markdown
    md = render_markdown(aggregate([_call("a.aac", "matlab", 3, 3.0)]))
    assert "# Human-Voice Parameter Sheet" in md
    assert "matlab" in md
    assert "Phase Prosody" in md
