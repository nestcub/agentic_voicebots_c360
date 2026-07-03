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
