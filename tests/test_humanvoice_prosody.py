"""Tests for humanvoice_engine audio + prosody. No network; audio is synthesized."""
import os
import sys
import wave
import struct
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _write_sine_wav(path, freq=200.0, seconds=1.0, sr=16000):
    """Write a mono 16-bit PCM sine wave so tests need no real recordings."""
    n = int(seconds * sr)
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        for i in range(n):
            val = int(32767 * 0.5 * math.sin(2 * math.pi * freq * i / sr))
            w.writeframes(struct.pack("<h", val))


def test_load_waveform_returns_mono_float_at_target_sr(tmp_path):
    from humanvoice_engine.audio_io import load_waveform
    wav = str(tmp_path / "tone.wav")
    _write_sine_wav(wav, freq=200.0, seconds=1.0, sr=16000)
    y, sr = load_waveform(wav, sr=16000)
    assert sr == 16000
    assert y.ndim == 1
    assert 15000 <= len(y) <= 17000  # ~1s at 16kHz
    assert y.dtype.name.startswith("float")


import numpy as np


def _sine(freq, seconds, sr=16000, amp=0.5):
    t = np.arange(int(seconds * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype("float32")


def test_analyze_segment_detects_pitch_near_tone():
    from humanvoice_engine.prosody import analyze_segment
    sr = 16000
    y = _sine(200.0, 2.0, sr)
    seg = {"role": "AGENT", "start": 0.0, "end": 2.0, "text": "ek do teen chaar"}
    feats = analyze_segment(y, sr, seg)
    assert 170 <= feats["f0_mean"] <= 230        # ~200 Hz tone
    assert feats["word_count"] == 4
    assert 1.5 <= feats["speaking_rate"] <= 2.5  # 4 words / 2s = 2.0
    assert feats["rms_mean"] > 0


def test_extract_prosody_agent_only_and_latency():
    from humanvoice_engine.prosody import extract_prosody
    sr = 16000
    y = _sine(180.0, 5.0, sr)
    segments = [
        {"role": "AGENT", "start": 0.0, "end": 1.0, "text": "namaste ji"},
        {"role": "CUSTOMER", "start": 1.2, "end": 2.0, "text": "haan boliye"},
        {"role": "AGENT", "start": 2.5, "end": 3.5, "text": "aaj offer hai"},
    ]
    out = extract_prosody(y, sr, segments)
    assert len(out["per_segment"]) == 2                 # AGENT segments only
    assert out["per_segment"][0]["turn_latency"] is None  # first agent turn
    # second agent turn starts 2.5, prev customer ended 2.0 -> 0.5s latency
    assert abs(out["per_segment"][1]["turn_latency"] - 0.5) < 0.05
    assert out["pauses"]["count"] >= 1
