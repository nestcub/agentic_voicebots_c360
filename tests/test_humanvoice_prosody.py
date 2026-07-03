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
