"""One LLM call per transcript -> the full Human-Voice gold-behavior schema.

Two-track output: delivery (fillers, phase_prosody, emotional_arc -> TTS control)
and substance (tactics, objections, empathy, guardrails, qualification, rapport
-> LLM behavioral rules + exemplars). The transcript is interleaved with per-segment
prosody numbers so the model grounds phase segmentation and tactics in real acoustics.
"""
from shared.llm_client import LLMClient

# Deepgram does not flag Hindi fillers/backchannels; the LLM detects them via this lexicon.
_HINDI_FILLERS = "matlab, yaani, achha, toh, haan, bas, dekhiye, sahi hai"
_HINDI_BACKCHANNELS = "haan ji, bilkul, ji, sahi hai"

GOLD_SYSTEM = f"""You are a voice-conversation analyst extracting the human qualities that make a
top sales agent sound and act human, so a downstream LLM can author a voice-agent system prompt.

You receive an AGENT/CUSTOMER transcript interleaved with per-segment acoustic prosody
(f0_mean, rms_mean, speaking_rate, turn_latency). Use the prosody as evidence.

Detect Hindi fillers even though STT will not flag them. Known Hindi fillers: {_HINDI_FILLERS}.
Known Hindi backchannels/acknowledgments: {_HINDI_BACKCHANNELS}.

Segment the call yourself into phases: opening, qualification, interest, objection, urgency, close
(not every call has every phase). For phase_prosody, average the per-segment numbers you were given
within each phase.

Return ONLY a JSON object with EXACTLY these keys (use [] / {{}} / "" when absent):
{{
  "filler_lexicon": [{{"filler": "", "count": 0, "position": "turn-initial|mid|pre-answer", "function": "buy-time|soften|acknowledge"}}],
  "urgency_tactics": [{{"trigger_context": "", "verbal_move": "", "prosody_signature": "", "verbatim": "", "why_it_worked": ""}}],
  "persuasion_moves": [{{"technique": "", "verbatim": "", "why_it_worked": ""}}],
  "objection_handling": [{{"objection": "", "agent_move": "", "outcome": "", "verbatim": ""}}],
  "empathy_markers": [{{"cue": "", "verbatim": ""}}],
  "guardrails_and_boundaries": [{{"boundary": "", "how_expressed": "", "verbatim": ""}}],
  "qualification_style": {{"approach": "", "question_sequence": [], "verbatim_probes": []}},
  "rapport_building": [{{"technique": "", "verbatim": ""}}],
  "turn_taking": [{{"interruption_handled_how": "", "backchannel_words": []}}],
  "phase_prosody": {{"opening": {{"rate": 0, "f0_mean": 0, "f0_range": 0, "rms": 0, "pause_ms": 0}}, "qualification": {{}}, "interest": {{}}, "objection": {{}}, "urgency": {{}}, "close": {{}}}},
  "opening_hook": "",
  "closing_commitment": "",
  "emotional_arc": ""
}}"""

_SCHEMA_KEYS = {
    "filler_lexicon": list, "urgency_tactics": list, "persuasion_moves": list,
    "objection_handling": list, "empathy_markers": list, "guardrails_and_boundaries": list,
    "qualification_style": dict, "rapport_building": list, "turn_taking": list,
    "phase_prosody": dict, "opening_hook": str, "closing_commitment": str, "emotional_arc": str,
}


def build_user_prompt(segments: list[dict], prosody: dict) -> str:
    """Role-labeled timestamped transcript with per-AGENT-segment prosody numbers inline."""
    by_start = {round(float(p["start"]), 2): p for p in prosody.get("per_segment", [])}
    lines = []
    for s in segments:
        head = f"[{float(s['start']):.1f}s] {s.get('role', '')}: {s.get('text', '')}"
        p = by_start.get(round(float(s["start"]), 2))
        if p:
            head += (f"   <prosody f0_mean={p.get('f0_mean')} rms_mean={p.get('rms_mean')} "
                     f"rate={p.get('speaking_rate')} turn_latency={p.get('turn_latency')}>")
        lines.append(head)
    pauses = prosody.get("pauses", {})
    return ("Transcript with acoustic evidence:\n\n" + "\n".join(lines) +
            f"\n\nAgent pauses across call: {pauses}")


def extract_gold(segments: list[dict], prosody: dict, llm: "LLMClient | None" = None) -> dict:
    """Run the single extraction call and guarantee every schema key is present."""
    llm = llm or LLMClient(provider="anthropic")
    user = build_user_prompt(segments, prosody)
    raw = llm.complete_json(GOLD_SYSTEM, user, max_tokens=4096)
    out = {}
    for key, typ in _SCHEMA_KEYS.items():
        val = raw.get(key)
        out[key] = val if isinstance(val, typ) else typ()
    return out
