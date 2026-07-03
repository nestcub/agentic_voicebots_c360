# humanvoice_engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone `humanvoice_engine/` package that turns a folder of best-agent call recordings into a single Human-Voice Parameter Sheet (JSON + Markdown) for authoring human-like voice-agent system prompts.

**Architecture:** A CLI pipeline in 4 stages per call — transcribe (Deepgram nova-3, direct SDK call, no DB writes) → prosody (librosa + parselmouth over AGENT-only audio slices) → gold_extract (one Anthropic LLM call, full behavioral+delivery schema) → cache. Then one deterministic aggregate stage collapses all cached calls into `data/parameter_sheet.{json,md}`. Fully isolated from the existing `transcription/`+`intelligence/`+`app.py` pipeline; reuses only two pure, DB-free helper functions.

**Tech Stack:** Python 3, Deepgram SDK v7 (installed), librosa + praat-parselmouth + soundfile (to install), ffmpeg (system-wide, present), Anthropic via `shared/llm_client.py`.

**Spec:** `docs/superpowers/specs/2026-07-03-humanvoice-engine-design.md`

## Global Constraints

- **Do NOT modify** `transcription/engine.py`, `intelligence/designer.py`, or `app.py`. Import only pure helpers from engine.py.
- **No DB writes, no new Neon/Postgres tables.** 100% file-based output.
- **Do NOT use the `TranscriptionEngine` class** (it writes to Neon + runs an unused insights LLM call). Call Deepgram directly.
- LLM access **only** via `shared/llm_client.py::LLMClient`; provider `anthropic`; model comes from env (`ANTHROPIC_MODEL`), never hardcoded.
- API keys from `.env` only (`DEEPGRAM_API_KEY`, `ANTHROPIC_API_KEY`).
- Input language: Hindi (`hi`). Input folder: `data/av_sales_call_recos/` (user-supplied, gitignored). Output: `data/parameter_sheet.{json,md}`.
- Commit messages: single line, no `Co-Authored-By`.
- Run all work on branch `feat/humanvoice-engine` (already checked out).
- Tests: pytest 9.1.0 is installed; run via `./venv/bin/pytest`. Tests must not hit the network — mock Deepgram/LLM, synthesize audio.

---

## File Structure

```
humanvoice_engine/
  __init__.py         # empty package marker
  audio_io.py         # load_waveform(): ffmpeg-decode any format -> (numpy y, sr)
  transcribe.py       # Deepgram direct dual-transcribe (smart + raw), parallel
  prosody.py          # per-segment acoustic features over AGENT audio slices
  gold_extract.py     # one LLM call/transcript -> full gold-behavior schema
  aggregate.py        # collapse all per-call results -> Parameter Sheet json + md
  run.py              # CLI: orchestrate stages, cache per file, resume, write sheet
tests/
  test_humanvoice_prosody.py
  test_humanvoice_transcribe.py
  test_humanvoice_gold_extract.py
  test_humanvoice_aggregate.py
  test_humanvoice_run.py
requirements.txt      # + librosa, praat-parselmouth, soundfile
```

---

### Task 1: Package scaffold, dependencies, and audio_io helper

**Files:**
- Create: `humanvoice_engine/__init__.py`
- Create: `humanvoice_engine/audio_io.py`
- Modify: `requirements.txt` (append audio deps)
- Test: `tests/test_humanvoice_prosody.py` (created here, extended in Task 3)

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `load_waveform(path: str, sr: int = 16000) -> tuple[np.ndarray, int]` — decodes any audio (incl. `.aac`) to mono float32 at `sr` Hz via ffmpeg, returns `(y, sr)`.

- [ ] **Step 1: Add dependencies to requirements.txt**

Append to `requirements.txt`:

```
# Human-voice engine (acoustic prosody)
librosa>=0.10.0
praat-parselmouth>=0.4.3
soundfile>=0.12.0
```

- [ ] **Step 2: Install the new dependencies**

Run: `./venv/bin/pip install "librosa>=0.10.0" "praat-parselmouth>=0.4.3" "soundfile>=0.12.0"`
Expected: installs successfully; `./venv/bin/python -c "import librosa, parselmouth, soundfile; print('ok')"` prints `ok`.

- [ ] **Step 3: Create the package marker**

Create `humanvoice_engine/__init__.py`:

```python
"""humanvoice_engine — extract a Human-Voice Parameter Sheet from best-agent call recordings.

Standalone pipeline: transcribe -> prosody -> gold_extract -> aggregate.
Isolated from the intelligence/orchestrator planes; no DB writes.
"""
```

- [ ] **Step 4: Write the failing test for load_waveform**

Create `tests/test_humanvoice_prosody.py`:

```python
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
```

- [ ] **Step 5: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_humanvoice_prosody.py::test_load_waveform_returns_mono_float_at_target_sr -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'humanvoice_engine.audio_io'`.

- [ ] **Step 6: Implement audio_io.py**

Create `humanvoice_engine/audio_io.py`:

```python
"""Audio decoding: any format (incl .aac WhatsApp files) -> mono float32 numpy at a target sr.

Uses ffmpeg (present system-wide) to decode to a temp WAV, then soundfile to read it.
soundfile alone cannot read .aac, so the ffmpeg step is required.
"""
import os
import shutil
import subprocess
import tempfile

import numpy as np
import soundfile as sf


def load_waveform(path: str, sr: int = 16000) -> tuple[np.ndarray, int]:
    """Decode `path` to mono float32 at `sr` Hz. Returns (samples, sr)."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH — required to decode audio.")
    fd, wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-y",
             "-i", path, "-ac", "1", "-ar", str(sr), "-f", "wav", wav_path],
            check=True,
        )
        y, out_sr = sf.read(wav_path, dtype="float32")
        if y.ndim > 1:
            y = y.mean(axis=1)
        return y, out_sr
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `./venv/bin/pytest tests/test_humanvoice_prosody.py::test_load_waveform_returns_mono_float_at_target_sr -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add requirements.txt humanvoice_engine/__init__.py humanvoice_engine/audio_io.py tests/test_humanvoice_prosody.py
git commit -m "humanvoice_engine: package scaffold, audio deps, ffmpeg audio_io helper"
```

---

### Task 2: transcribe.py — direct Deepgram dual-transcribe

**Files:**
- Create: `humanvoice_engine/transcribe.py`
- Test: `tests/test_humanvoice_transcribe.py`

**Interfaces:**
- Consumes: `transcription.engine._build_segments_deepgram(response, duration, swap_roles=False) -> list[dict]`, `transcription.engine._get_duration(path) -> float` (pure, no DB).
  - Each segment dict has keys: `speaker, role, start, end, text, confidence`.
- Produces:
  - `transcribe_file(path: str, dg, language: str = "hi") -> dict` returning `{"path", "filename", "duration", "segments", "raw_segments"}`. `segments` = smart_format=True; `raw_segments` = smart_format=False (fillers/disfluencies preserved).
  - `transcribe_paths(paths: list[str], language: str = "hi", max_workers: int = 10, on_done=None) -> dict[str, dict]` keyed by filename; `on_done(filename, result_or_exception)` optional callback.

- [ ] **Step 1: Write the failing test (fake Deepgram, no network)**

Create `tests/test_humanvoice_transcribe.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_humanvoice_transcribe.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'humanvoice_engine.transcribe'`.

- [ ] **Step 3: Implement transcribe.py**

Create `humanvoice_engine/transcribe.py`:

```python
"""Direct Deepgram nova-3 transcription — no TranscriptionEngine, no DB writes.

Reuses only the pure, side-effect-free helpers from transcription/engine.py.
Runs two passes per file: smart_format=True (clean) and smart_format=False
(fillers/disfluencies survive, needed for the Hindi filler lexicon).
"""
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

from transcription.engine import _build_segments_deepgram, _get_duration

load_dotenv()


def _one_pass(dg, audio_bytes, language, smart_format, duration):
    """Run a single Deepgram transcription pass and return normalized segments."""
    response = dg.listen.v1.media.transcribe_file(
        request=audio_bytes,
        model="nova-3",
        language=language,
        diarize=True,
        utterances=True,
        punctuate=True,
        smart_format=smart_format,
        filler_words=True,
    )
    return _build_segments_deepgram(response, duration)


def transcribe_file(path: str, dg, language: str = "hi") -> dict:
    """Transcribe one file twice (smart + raw). Returns segments + raw_segments."""
    duration = _get_duration(path)
    with open(path, "rb") as f:
        audio_bytes = f.read()
    segments = _one_pass(dg, audio_bytes, language, True, duration)
    raw_segments = _one_pass(dg, audio_bytes, language, False, duration)
    return {
        "path": path,
        "filename": Path(path).name,
        "duration": duration,
        "segments": segments,
        "raw_segments": raw_segments,
    }


def transcribe_paths(paths: list[str], language: str = "hi",
                     max_workers: int = 10, on_done=None) -> dict[str, dict]:
    """Transcribe many files in parallel. Returns {filename: result}. One bad file
    is logged via on_done(filename, exception) and skipped, never fatal."""
    from deepgram import DeepgramClient
    key = os.getenv("DEEPGRAM_API_KEY")
    if not key:
        raise ValueError("DEEPGRAM_API_KEY is not set in environment.")
    dg = DeepgramClient(api_key=key)
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(transcribe_file, p, dg, language): p for p in paths}
        for fut in as_completed(futures):
            fname = Path(futures[fut]).name
            try:
                res = fut.result()
                results[fname] = res
                if on_done:
                    on_done(fname, res)
            except Exception as e:  # noqa: BLE001 — one bad file must not kill the batch
                if on_done:
                    on_done(fname, e)
    return results
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./venv/bin/pytest tests/test_humanvoice_transcribe.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add humanvoice_engine/transcribe.py tests/test_humanvoice_transcribe.py
git commit -m "humanvoice_engine: direct Deepgram dual-transcribe (smart+raw), no DB writes"
```

---

### Task 3: prosody.py — per-segment acoustic features

**Files:**
- Create: `humanvoice_engine/prosody.py`
- Test: `tests/test_humanvoice_prosody.py` (extend from Task 1)

**Interfaces:**
- Consumes: `load_waveform(path, sr) -> (y, sr)` from Task 1; segment dicts from Task 2 (`role, start, end, text`).
- Produces:
  - `analyze_segment(y, sr, seg: dict) -> dict` — acoustic features for one segment: `f0_mean, f0_min, f0_max, f0_range, f0_std, rms_mean, rms_max, rms_dynamic_range, speaking_rate, word_count, duration`.
  - `extract_prosody(y, sr, segments: list[dict]) -> dict` — `{"per_segment": [ {role,start,end,text,turn_latency, **features} ], "pauses": {"count", "mean_ms", "median_ms"}}`. `per_segment` contains AGENT segments only; `turn_latency` = seconds from the preceding CUSTOMER segment's end; pauses = gaps between consecutive AGENT segments.

- [ ] **Step 1: Write the failing tests (append to tests/test_humanvoice_prosody.py)**

Append to `tests/test_humanvoice_prosody.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_humanvoice_prosody.py -v`
Expected: the two new tests FAIL — `ModuleNotFoundError: No module named 'humanvoice_engine.prosody'`.

- [ ] **Step 3: Implement prosody.py**

Create `humanvoice_engine/prosody.py`:

```python
"""Acoustic prosody over AGENT-only segments — language-agnostic DSP.

parselmouth (Praat) for F0 (accurate on voiced speech); librosa for RMS energy.
Pitch/energy computed on the audio slice for each AGENT segment; pauses and
turn-taking latency computed from segment timestamps.
"""
import numpy as np
import parselmouth
import librosa


def _f0_stats(y_seg: np.ndarray, sr: int) -> dict:
    """F0 mean/min/max/range/std over voiced frames; zeros mean unvoiced -> dropped."""
    if len(y_seg) < int(0.05 * sr):
        return {"f0_mean": 0.0, "f0_min": 0.0, "f0_max": 0.0, "f0_range": 0.0, "f0_std": 0.0}
    snd = parselmouth.Sound(values=y_seg.astype("float64"), sampling_frequency=sr)
    pitch = snd.to_pitch(pitch_floor=75.0, pitch_ceiling=500.0)
    f0 = pitch.selected_array["frequency"]
    voiced = f0[f0 > 0]
    if voiced.size == 0:
        return {"f0_mean": 0.0, "f0_min": 0.0, "f0_max": 0.0, "f0_range": 0.0, "f0_std": 0.0}
    return {
        "f0_mean": float(np.mean(voiced)),
        "f0_min": float(np.min(voiced)),
        "f0_max": float(np.max(voiced)),
        "f0_range": float(np.max(voiced) - np.min(voiced)),
        "f0_std": float(np.std(voiced)),
    }


def _rms_stats(y_seg: np.ndarray) -> dict:
    """RMS energy mean/max and dynamic range (max-min over frames)."""
    if len(y_seg) == 0:
        return {"rms_mean": 0.0, "rms_max": 0.0, "rms_dynamic_range": 0.0}
    rms = librosa.feature.rms(y=y_seg)[0]
    if rms.size == 0:
        return {"rms_mean": 0.0, "rms_max": 0.0, "rms_dynamic_range": 0.0}
    return {
        "rms_mean": float(np.mean(rms)),
        "rms_max": float(np.max(rms)),
        "rms_dynamic_range": float(np.max(rms) - np.min(rms)),
    }


def _slice(y: np.ndarray, sr: int, start: float, end: float) -> np.ndarray:
    a = max(0, int(start * sr))
    b = min(len(y), int(end * sr))
    return y[a:b] if b > a else np.array([], dtype="float32")


def analyze_segment(y: np.ndarray, sr: int, seg: dict) -> dict:
    """Acoustic features for one segment's audio slice + speaking rate from its text."""
    y_seg = _slice(y, sr, seg["start"], seg["end"])
    duration = max(1e-6, float(seg["end"]) - float(seg["start"]))
    word_count = len(str(seg.get("text", "")).split())
    feats = {"duration": round(duration, 3), "word_count": word_count,
             "speaking_rate": round(word_count / duration, 3)}
    feats.update(_f0_stats(y_seg, sr))
    feats.update(_rms_stats(y_seg))
    return feats


def extract_prosody(y: np.ndarray, sr: int, segments: list[dict]) -> dict:
    """Per-AGENT-segment acoustics + pauses + turn-taking latency."""
    per_segment = []
    prev_customer_end = None
    prev_agent_end = None
    pause_gaps_ms = []
    for seg in segments:
        role = seg.get("role")
        if role == "CUSTOMER":
            prev_customer_end = float(seg["end"])
            continue
        if role != "AGENT":
            continue
        feats = analyze_segment(y, sr, seg)
        start = float(seg["start"])
        latency = None
        if prev_customer_end is not None and start >= prev_customer_end:
            latency = round(start - prev_customer_end, 3)
        if prev_agent_end is not None and start > prev_agent_end:
            pause_gaps_ms.append((start - prev_agent_end) * 1000.0)
        per_segment.append({
            "role": "AGENT",
            "start": start,
            "end": float(seg["end"]),
            "text": seg.get("text", ""),
            "turn_latency": latency,
            **feats,
        })
        prev_agent_end = float(seg["end"])
    pauses = {"count": len(pause_gaps_ms),
              "mean_ms": round(float(np.mean(pause_gaps_ms)), 1) if pause_gaps_ms else 0.0,
              "median_ms": round(float(np.median(pause_gaps_ms)), 1) if pause_gaps_ms else 0.0}
    return {"per_segment": per_segment, "pauses": pauses}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_humanvoice_prosody.py -v`
Expected: all three tests PASS.

- [ ] **Step 5: Commit**

```bash
git add humanvoice_engine/prosody.py tests/test_humanvoice_prosody.py
git commit -m "humanvoice_engine: per-segment prosody (F0, RMS, rate, pauses, turn latency)"
```

---

### Task 4: gold_extract.py — one LLM call per transcript

**Files:**
- Create: `humanvoice_engine/gold_extract.py`
- Test: `tests/test_humanvoice_gold_extract.py`

**Interfaces:**
- Consumes: smart-format `segments` (Task 2), `prosody` dict (Task 3); `shared/llm_client.py::LLMClient` with `.complete_json(system, user, max_tokens) -> dict`.
- Produces:
  - `build_user_prompt(segments: list[dict], prosody: dict) -> str` — role-labeled timestamped transcript interleaved with per-segment prosody numbers.
  - `extract_gold(segments, prosody, llm=None) -> dict` — full schema (all keys below always present, defaulting to `[]`/`{}`/`""`). `llm` injectable for tests.
  - `GOLD_SYSTEM: str` — system prompt embedding the full schema + Hindi filler/backchannel lexicon.

- [ ] **Step 1: Write the failing test (fake LLM, no network)**

Create `tests/test_humanvoice_gold_extract.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_humanvoice_gold_extract.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'humanvoice_engine.gold_extract'`.

- [ ] **Step 3: Implement gold_extract.py**

Create `humanvoice_engine/gold_extract.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_humanvoice_gold_extract.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add humanvoice_engine/gold_extract.py tests/test_humanvoice_gold_extract.py
git commit -m "humanvoice_engine: gold_extract single LLM call, full two-track schema"
```

---

### Task 5: aggregate.py — collapse calls into the Parameter Sheet

**Files:**
- Create: `humanvoice_engine/aggregate.py`
- Test: `tests/test_humanvoice_aggregate.py`

**Interfaces:**
- Consumes: a list of per-call dicts, each `{"filename", "prosody", "gold_extract"}` (gold_extract shape from Task 4).
- Produces:
  - `aggregate(calls: list[dict]) -> dict` — the Parameter Sheet: merged `filler_lexicon` (word -> total count + positions), pooled substance lists, averaged `phase_prosody` per phase, and a Section-E `output_mapping` (per-phase speed/volume ratios vs baseline). Equal weight per call (no outcome labels).
  - `render_markdown(sheet: dict) -> str` — the human-readable Markdown deliverable.

- [ ] **Step 1: Write the failing test**

Create `tests/test_humanvoice_aggregate.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/pytest tests/test_humanvoice_aggregate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'humanvoice_engine.aggregate'`.

- [ ] **Step 3: Implement aggregate.py**

Create `humanvoice_engine/aggregate.py`:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./venv/bin/pytest tests/test_humanvoice_aggregate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add humanvoice_engine/aggregate.py tests/test_humanvoice_aggregate.py
git commit -m "humanvoice_engine: aggregate per-call results into Parameter Sheet json+md"
```

---

### Task 6: run.py — CLI orchestration, caching, resume

**Files:**
- Create: `humanvoice_engine/run.py`
- Test: `tests/test_humanvoice_run.py`

**Interfaces:**
- Consumes: `transcribe.transcribe_paths` (Task 2), `audio_io.load_waveform` (Task 1), `prosody.extract_prosody` (Task 3), `gold_extract.extract_gold` (Task 4), `aggregate.aggregate` + `render_markdown` (Task 5).
- Produces:
  - `process_file(path, cache_dir, language="hi") -> dict` — transcribe→prosody→gold_extract for one file, writes/reads `<cache_dir>/<filename>.json`, resumes from cache if complete.
  - `run(input_dir, output_dir="data", language="hi") -> dict` — process every audio file in `input_dir`, aggregate, write `output_dir/parameter_sheet.{json,md}`, return the sheet.
  - CLI: `python -m humanvoice_engine.run --input data/av_sales_call_recos [--output-dir data]`.

- [ ] **Step 1: Write the failing test (stages monkeypatched, no network)**

Create `tests/test_humanvoice_run.py`:

```python
"""Tests for humanvoice_engine.run — stages are monkeypatched; no network/audio."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _patch_stages(monkeypatch):
    from humanvoice_engine import run as runmod
    monkeypatch.setattr(runmod, "transcribe_file",
                        lambda path, dg, language="hi": {
                            "path": path, "filename": os.path.basename(path), "duration": 2.0,
                            "segments": [{"role": "AGENT", "start": 0.0, "end": 1.0, "text": "namaste"}],
                            "raw_segments": []})
    monkeypatch.setattr(runmod, "_dg_client", lambda: object())
    monkeypatch.setattr(runmod, "load_waveform", lambda p, sr=16000: (b"", 16000))
    monkeypatch.setattr(runmod, "extract_prosody",
                        lambda y, sr, segs: {"per_segment": [], "pauses": {"count": 0}})
    monkeypatch.setattr(runmod, "extract_gold",
                        lambda segs, pros: {"filler_lexicon": [{"filler": "matlab", "count": 1,
                                                                "position": "mid", "function": "buy-time"}],
                                            "phase_prosody": {}, "opening_hook": "hi",
                                            "urgency_tactics": [], "persuasion_moves": [],
                                            "objection_handling": [], "empathy_markers": [],
                                            "guardrails_and_boundaries": [], "qualification_style": {},
                                            "rapport_building": [], "turn_taking": [],
                                            "closing_commitment": "", "emotional_arc": ""})


def test_process_file_caches_and_resumes(tmp_path, monkeypatch):
    _patch_stages(monkeypatch)
    from humanvoice_engine import run as runmod
    cache_dir = tmp_path / "_cache"
    cache_dir.mkdir()
    audio = tmp_path / "call.aac"
    audio.write_bytes(b"x")
    r1 = runmod.process_file(str(audio), str(cache_dir))
    cache_file = cache_dir / "call.aac.json"
    assert cache_file.exists()
    # Second call must resume from cache: break the stage so any re-run would raise.
    monkeypatch.setattr(runmod, "transcribe_file",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not re-transcribe")))
    r2 = runmod.process_file(str(audio), str(cache_dir))
    assert r2["gold_extract"]["filler_lexicon"][0]["filler"] == "matlab"


def test_run_writes_parameter_sheet(tmp_path, monkeypatch):
    _patch_stages(monkeypatch)
    from humanvoice_engine import run as runmod
    indir = tmp_path / "recos"
    indir.mkdir()
    (indir / "call.aac").write_bytes(b"x")
    outdir = tmp_path / "out"
    sheet = runmod.run(str(indir), output_dir=str(outdir))
    assert (outdir / "parameter_sheet.json").exists()
    assert (outdir / "parameter_sheet.md").exists()
    assert sheet["call_count"] == 1
    loaded = json.loads((outdir / "parameter_sheet.json").read_text())
    assert loaded["filler_lexicon"][0]["filler"] == "matlab"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/pytest tests/test_humanvoice_run.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'humanvoice_engine.run'`.

- [ ] **Step 3: Implement run.py**

Create `humanvoice_engine/run.py`:

```python
"""CLI orchestrator: transcribe -> prosody -> gold_extract -> cache -> aggregate.

Per-file JSON cache in <input>/_cache makes a partial 50-file run resumable without
re-spending STT/LLM budget. Writes data/parameter_sheet.{json,md}.
"""
import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from humanvoice_engine.transcribe import transcribe_file
from humanvoice_engine.audio_io import load_waveform
from humanvoice_engine.prosody import extract_prosody
from humanvoice_engine.gold_extract import extract_gold
from humanvoice_engine.aggregate import aggregate, render_markdown

load_dotenv()

_AUDIO_EXTS = {".aac", ".wav", ".mp3", ".m4a", ".mp4", ".mpeg", ".mpg"}
_CACHE_COMPLETE_KEYS = {"segments", "prosody", "gold_extract"}


def _dg_client():
    """Build a Deepgram client (indirection point so tests can stub it)."""
    from deepgram import DeepgramClient
    key = os.getenv("DEEPGRAM_API_KEY")
    if not key:
        raise ValueError("DEEPGRAM_API_KEY is not set in environment.")
    return DeepgramClient(api_key=key)


def process_file(path: str, cache_dir: str, language: str = "hi") -> dict:
    """Run all per-call stages for one file, using/writing the JSON cache. Resumable."""
    fname = Path(path).name
    cache_path = Path(cache_dir) / f"{fname}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if _CACHE_COMPLETE_KEYS.issubset(cached.keys()):
            return cached

    t = transcribe_file(path, _dg_client(), language=language)
    y, sr = load_waveform(path)
    prosody = extract_prosody(y, sr, t["segments"])
    gold = extract_gold(t["segments"], prosody)

    record = {
        "filename": fname, "path": path, "duration": t["duration"],
        "segments": t["segments"], "raw_segments": t.get("raw_segments", []),
        "prosody": prosody, "gold_extract": gold,
    }
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    return record


def run(input_dir: str, output_dir: str = "data", language: str = "hi") -> dict:
    """Process every recording in input_dir, aggregate, write parameter_sheet.{json,md}."""
    in_path = Path(input_dir)
    files = sorted(p for p in in_path.iterdir()
                   if p.is_file() and p.suffix.lower() in _AUDIO_EXTS)
    cache_dir = in_path / "_cache"
    calls = []
    for f in files:
        try:
            calls.append(process_file(str(f), str(cache_dir), language=language))
            print(f"[ok] {f.name}", flush=True)
        except Exception as e:  # noqa: BLE001 — one bad file must not sink the batch
            print(f"[skip] {f.name}: {e}", flush=True)

    sheet = aggregate(calls)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "parameter_sheet.json").write_text(json.dumps(sheet, ensure_ascii=False, indent=2))
    (out / "parameter_sheet.md").write_text(render_markdown(sheet))
    print(f"[done] {len(calls)} call(s) -> {out/'parameter_sheet.md'}", flush=True)
    return sheet


def main():
    ap = argparse.ArgumentParser(description="Extract a Human-Voice Parameter Sheet from call recordings.")
    ap.add_argument("--input", required=True, help="folder of recordings (e.g. data/av_sales_call_recos)")
    ap.add_argument("--output-dir", default="data", help="where to write parameter_sheet.{json,md}")
    ap.add_argument("--language", default="hi", help="STT language (default hi)")
    args = ap.parse_args()
    run(args.input, output_dir=args.output_dir, language=args.language)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/pytest tests/test_humanvoice_run.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full test suite for the package**

Run: `./venv/bin/pytest tests/test_humanvoice_*.py -v`
Expected: all tests across all 5 files PASS.

- [ ] **Step 6: Commit**

```bash
git add humanvoice_engine/run.py tests/test_humanvoice_run.py
git commit -m "humanvoice_engine: run.py CLI orchestrator with per-file cache + resume"
```

---

### Task 7: End-to-end smoke test on real recordings (manual gate)

**Files:** none created; this is a manual verification against the 3 existing recordings before the real 50+ run.

**Interfaces:** none — exercises the assembled CLI.

- [ ] **Step 1: Confirm keys are present**

Run: `./venv/bin/python -c "import os; from dotenv import load_dotenv; load_dotenv(); print('DEEPGRAM', bool(os.getenv('DEEPGRAM_API_KEY'))); print('ANTHROPIC', bool(os.getenv('ANTHROPIC_API_KEY')))"`
Expected: both `True`. If either is `False`, stop and set it in `.env`.

- [ ] **Step 2: Run the pipeline against the 3 existing recordings**

Run: `./venv/bin/python -m humanvoice_engine.run --input data/call_recordings_service --output-dir /private/tmp/claude-501/-Users-pranavjakkani-Desktop-chat360-intelligence-fabric/f36f3f83-ac38-478c-83a4-ea44a07ee4f7/scratchpad`
Expected: three `[ok] ...` lines, then `[done] 3 call(s) -> .../parameter_sheet.md`.

- [ ] **Step 3: Eyeball the outputs**

Read the generated `parameter_sheet.md` in the scratchpad dir. Verify:
- Diarization looks sane (AGENT segments are the caller, not the customer). If roles are swapped, note it — the real 50-call run may need role handling revisited.
- `phase_prosody` has non-zero F0/rate numbers (proves prosody + audio decode worked on `.aac`).
- `filler_lexicon` picked up at least some Hindi fillers.

- [ ] **Step 4: Report smoke result to the user**

Summarize: did diarization split cleanly, did prosody produce real numbers, does the sheet look usable? This is the go/no-go gate before pointing at `data/av_sales_call_recos/` with the full 50+ files. Do not commit anything in this task (scratchpad output only).

---

## Self-Review

**Spec coverage:**
- Package layout + isolation (no engine.py/designer.py/app.py edits, no DB) → Global Constraints + Tasks 1-6. ✓
- transcribe via direct Deepgram, dual smart/raw, filler_words → Task 2. ✓
- prosody: F0 (parselmouth), RMS (librosa), speaking rate, pauses, turn latency, AGENT-only → Task 3. ✓
- gold_extract: single LLM call, full two-track schema incl. guardrails/qualification/rapport/why_it_worked, Hindi filler lexicon, phase segmentation → Task 4. ✓
- aggregate: merge fillers, pool substance, average phase_prosody, Section E output mapping, equal weight → Task 5. ✓
- run.py CLI, per-file cache + resume, write parameter_sheet.{json,md} → Task 6. ✓
- Smoke test on 3 existing files first → Task 7. ✓
- Deps (librosa, parselmouth, soundfile) + ffmpeg decode for .aac → Task 1. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code; every test has real assertions. ✓

**Type consistency:** `transcribe_file` signature identical in Tasks 2 & 6; segment dict keys (`role/start/end/text`) consistent across Tasks 2-4; gold_extract schema keys identical in Tasks 4 & 5 (`guardrails_and_boundaries`, `qualification_style`, etc.); `extract_prosody` return shape (`per_segment`, `pauses`) consistent Tasks 3-4; cache record keys (`segments`, `prosody`, `gold_extract`) match `_CACHE_COMPLETE_KEYS` in Task 6. ✓

**Note on run.py testability:** `run.py` imports `transcribe_file`, `load_waveform`, `extract_prosody`, `extract_gold` as module globals precisely so Task 6's tests can monkeypatch them; `_dg_client()` is a separate indirection so the Deepgram client is stubbable. This is intentional and required by the tests as written.
