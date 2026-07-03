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
