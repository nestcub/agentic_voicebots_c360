"""Tests for humanvoice_engine.transcribe — Deepgram client is faked; no network."""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _FakeUtterance:
    def __init__(self, speaker, transcript, start, end, confidence=0.9):
        self.speaker = speaker
        self.transcript = transcript
        self.start = start
        self.end = end
        self.confidence = confidence


def _fake_response(smart):
    # Two utterances: speaker 0 (AGENT), speaker 1 (CUSTOMER).
    text0 = "Haan ji, namaste." if smart else "haan ji matlab namaste"
    utt = types.SimpleNamespace(
        utterances=[
            _FakeUtterance(0, text0, 0.0, 1.5),
            _FakeUtterance(1, "Boliye.", 1.8, 2.4),
        ]
    )
    return types.SimpleNamespace(results=utt)


class _FakeMedia:
    def transcribe_file(self, request, model, language, diarize, utterances,
                        punctuate, smart_format, filler_words):
        return _fake_response(smart_format)


class _FakeDG:
    def __init__(self):
        self.listen = types.SimpleNamespace(
            v1=types.SimpleNamespace(media=_FakeMedia())
        )


def test_transcribe_file_returns_smart_and_raw(tmp_path, monkeypatch):
    from humanvoice_engine import transcribe
    monkeypatch.setattr(transcribe, "_get_duration", lambda p: 2.4)
    audio = tmp_path / "call.aac"
    audio.write_bytes(b"not-real-audio-bytes")
    result = transcribe.transcribe_file(str(audio), _FakeDG(), language="hi")
    assert result["filename"] == "call.aac"
    assert result["duration"] == 2.4
    assert result["segments"][0]["role"] == "AGENT"
    # raw (smart_format=False) preserves the filler "matlab"
    raw_agent_text = result["raw_segments"][0]["text"]
    assert "matlab" in raw_agent_text
