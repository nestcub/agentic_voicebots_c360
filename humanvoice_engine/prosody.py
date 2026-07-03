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
