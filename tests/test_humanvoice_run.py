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


def test_run_custom_name_writes_named_sheet(tmp_path, monkeypatch):
    _patch_stages(monkeypatch)
    from humanvoice_engine import run as runmod
    indir = tmp_path / "recos"
    indir.mkdir()
    (indir / "call.aac").write_bytes(b"x")
    outdir = tmp_path / "out"
    runmod.run(str(indir), output_dir=str(outdir), name="av_batch1")
    assert (outdir / "av_batch1.json").exists()
    assert (outdir / "av_batch1.md").exists()
    assert not (outdir / "parameter_sheet.json").exists()
    # a passed-in extension is tolerated (stem is used)
    runmod.run(str(indir), output_dir=str(outdir), name="av_batch2.json")
    assert (outdir / "av_batch2.json").exists()
    assert (outdir / "av_batch2.md").exists()
