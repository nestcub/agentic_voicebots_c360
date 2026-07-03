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
