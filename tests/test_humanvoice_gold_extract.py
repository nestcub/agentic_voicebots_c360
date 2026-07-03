"""Tests for humanvoice_engine.gold_extract — LLM is faked; no network."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _FakeLLM:
    def __init__(self, payload):
        self._payload = payload
        self.last_user = None

    def complete_json(self, system, user, max_tokens=4096):
        self.last_user = user
        return self._payload


def _segments():
    return [
        {"role": "AGENT", "start": 0.0, "end": 1.0, "text": "Namaste ji, main Autovista se."},
        {"role": "CUSTOMER", "start": 1.2, "end": 2.0, "text": "Haan boliye."},
        {"role": "AGENT", "start": 2.3, "end": 4.0, "text": "Sirf isi weekend offer hai."},
    ]


def _prosody():
    return {"per_segment": [
        {"role": "AGENT", "start": 0.0, "end": 1.0, "f0_mean": 180.0, "rms_mean": 0.05,
         "speaking_rate": 3.0, "turn_latency": None, "text": "Namaste ji"},
        {"role": "AGENT", "start": 2.3, "end": 4.0, "f0_mean": 210.0, "rms_mean": 0.08,
         "speaking_rate": 3.5, "turn_latency": 0.3, "text": "Sirf isi weekend offer hai"},
    ], "pauses": {"count": 1, "mean_ms": 1300.0, "median_ms": 1300.0}}


def test_build_user_prompt_interleaves_prosody():
    from humanvoice_engine.gold_extract import build_user_prompt
    prompt = build_user_prompt(_segments(), _prosody())
    assert "AGENT" in prompt and "CUSTOMER" in prompt
    assert "f0_mean" in prompt          # prosody numbers are present as evidence
    assert "weekend" in prompt


def test_extract_gold_returns_full_schema():
    from humanvoice_engine.gold_extract import extract_gold
    payload = {"filler_lexicon": [{"filler": "matlab", "count": 2, "position": "mid",
                                    "function": "buy-time"}]}
    llm = _FakeLLM(payload)
    out = extract_gold(_segments(), _prosody(), llm=llm)
    for key in ["filler_lexicon", "urgency_tactics", "persuasion_moves",
                "objection_handling", "empathy_markers", "guardrails_and_boundaries",
                "qualification_style", "rapport_building", "turn_taking",
                "phase_prosody", "opening_hook", "closing_commitment", "emotional_arc"]:
        assert key in out
    assert out["filler_lexicon"][0]["filler"] == "matlab"  # LLM value preserved
