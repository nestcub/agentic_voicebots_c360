---
title: humanvoice_engine — Human Voice Parameter Extraction (MVP)
date: 2026-07-03
status: approved
source_goal: ~/Documents/Obsidian Vault/KnowledgeBase/chat360/voice360/GOAL - Human Voice Parameter Extraction (2hr MVP).md
---

# humanvoice_engine — Design Spec

## Purpose

Drop 50+ best-agent call recordings into a folder and get a single **Human-Voice
Parameter Sheet** rich enough to author voicebot system prompts that sound and act
human (urgency, convincing instincts, empathy). The sheet is meant to be pasted or
uploaded directly into Claude web to author/refine system prompts — Markdown is the
primary artifact for that reason, JSON is the structured backing store.

**Consumption model:** the sheet feeds a prompt-generating LLM (Claude/GPT + the bot's
use case → voice-agent system prompt) for a STT → LLM → TTS voicebot. It therefore
carries two parameter tracks: a **delivery track** (prosody → TTS control tags:
`<speed>/<volume>/<emotion>/<break>`, fillers) and a **substance track** (behavioral
tactics → LLM behavioral rules + few-shot exemplars). The substance track is the higher
-leverage one — the voice-agent LLM's quality is dominated by *what* it says; TTS only
renders delivery.

This is a **new, fully separate package** — `humanvoice_engine/` — not a modification
of the existing `transcription/` + `intelligence/` pipeline. That pipeline outputs a
different thing (bot-plan generation from insight scoring) and must not be touched or
reused via its class/DB-writing surface. `humanvoice_engine` will later be deployed as
its own standalone service, hence the "_engine" naming and full isolation now.

## Non-goals (explicit exclusions for this MVP)

- No changes to `transcription/engine.py`, `intelligence/designer.py`, or `app.py`.
- No new Postgres/Neon tables or writes — 100% file-based output.
- No outcome/conversion-weighted aggregation (no labels available yet) — all calls
  weighted equally.
- No UI — CLI only.
- No use of the existing `TranscriptionEngine` class (avoids its baked-in Neon writes
  and unused "insights" LLM call).

## Package layout

```
humanvoice_engine/
  __init__.py
  run.py           # CLI entrypoint: orchestrates all 4 stages end-to-end
  transcribe.py    # Deepgram nova-3 direct call + diarization; reuses only the pure,
                    # DB-free helpers from transcription/engine.py (_build_segments_deepgram,
                    # _get_duration) via import — no TranscriptionEngine, no DB writes
  prosody.py       # librosa + parselmouth over AGENT-only audio segments (sliced by
                    # diarization timestamps) -> per-segment acoustic params
  gold_extract.py  # ONE LLM call per transcript (Anthropic, via shared/llm_client.py):
                    # transcript + per-segment prosody -> full gold-behavior schema
  aggregate.py      # deterministic, no LLM: collapses all per-call results -> Parameter Sheet
data/
  av_sales_call_recos/     # gitignored input folder, user drops recordings here
    _cache/<filename>.json  # per-call cache: segments, raw_segments, prosody, gold_extract
  parameter_sheet.json
  parameter_sheet.md         # <- primary deliverable, paste/upload into Claude web
```

Run: `python -m humanvoice_engine.run --input data/av_sales_call_recos`

## Data flow

### Per call

1. **`transcribe.py`** — two direct Deepgram `nova-3` calls per file (diarize, utterances,
   punctuate, `filler_words=True`): one with `smart_format=True` (clean segments) and one
   with `smart_format=False` (so disfluencies/fillers survive per the goal doc). Both use
   `_build_segments_deepgram` / `_get_duration` imported from `transcription/engine.py` —
   these are pure functions with no DB side effects. `ThreadPoolExecutor(max_workers=10)`
   for parallelism across files, per-file try/except so one bad file doesn't kill the batch.
   Language: Hindi (`hi`), matching the existing fabric's default.

2. **`prosody.py`** — for each AGENT-role segment (from the smart-format transcript), slices
   the decoded waveform (ffmpeg-backed, via librosa/soundfile — handles `.aac` WhatsApp
   recordings directly) to `[start, end]` and computes:
   - F0 mean/range/variability (parselmouth/Praat — more accurate than librosa's pitch
     tracking for voiced speech)
   - RMS/energy mean, dynamic range, emphasis spikes (librosa)
   - Pause gaps between consecutive AGENT segments (count, mean/median duration)
   - Turn-taking latency: gap between preceding CUSTOMER segment end and this AGENT
     segment start
   - Speaking rate: `word_count (from segment text) / segment_duration` — the one hybrid
     STT+audio metric

   Output: a flat list of per-segment acoustic dicts. No phase bucketing here — phases are
   semantic, not acoustic, and are determined in the next stage.

3. **`gold_extract.py`** — one `LLMClient(provider="anthropic").complete_json(...)` call
   per transcript. System prompt encodes the full schema below; user prompt is the
   role-labeled, timestamped transcript **interleaved with the per-segment prosody
   numbers** from step 2 as grounding evidence. The LLM performs phase segmentation
   itself (reading the conversation to identify opening/qualification/interest/
   objection/urgency/close boundaries — there is no clean acoustic signal for this) and
   reports aggregated prosody per phase alongside the behavioral/emotional extraction.

   The schema has two tracks, reflecting how the parameter sheet is consumed
   downstream (STT -> LLM -> TTS voicebot): a **delivery track** (prosody -> TTS
   control tags) and a **substance track** (behavior -> LLM behavioral rules +
   few-shot exemplars). The substance track carries the most leverage for
   human-like response generation, because the voice-agent LLM's job is choosing
   *what to say* — TTS only renders it.

   Full schema (nothing dropped from the goal doc; substance track expanded):
   ```
   # --- delivery track (-> TTS control) ---
   filler_lexicon:      [{filler, count, position, function}]
   phase_prosody:       {opening|qualification|interest|objection|urgency|close: {rate, f0_mean, f0_range, rms, pause_ms}}
   emotional_arc

   # --- substance track (-> LLM behavioral rules + exemplars) ---
   urgency_tactics:     [{trigger_context, verbal_move, prosody_signature, verbatim, why_it_worked}]
   persuasion_moves:    [{technique, verbatim, why_it_worked}]
   objection_handling:  [{objection, agent_move, outcome, verbatim}]
   empathy_markers:     [{cue, verbatim}]
   guardrails_and_boundaries: [{boundary, how_expressed, verbatim}]   # what the agent won't do / how they deflect / stay honest
   qualification_style: {approach, question_sequence, verbatim_probes}
   rapport_building:    [{technique, verbatim}]
   turn_taking:         [{interruption_handled_how, backchannel_words}]
   opening_hook / closing_commitment
   ```

   **`why_it_worked`** on the persuasion/urgency verbatims captures the *mechanism*
   (e.g. "anchored high, then created weekend scarcity"), not just the line — the
   prompt-gen LLM needs the mechanism to generalize, not copy.

   **Guardrails scope note:** this field extracts the *human* agent's guardrail
   behavior (not over-promising, deflecting out-of-scope, staying honest). The
   bot-specific safety guardrails (don't hallucinate, don't answer outside KB,
   handle silence/interruption) are NOT sourced here — they come from the existing
   reference-bot-pitfalls platform knowledge + the bot's use case at prompt-gen time.

4. Each call's combined result (`segments`, `raw_segments`, `prosody`, `gold_extract`) is
   cached to `data/av_sales_call_recos/_cache/<filename>.json` after each stage completes.
   `run.py` checks this cache before repeating any stage per file — a partial 50-file run
   is resumable without re-spending STT/LLM budget. LLM failures on one file are logged
   and skipped, not fatal to the batch.

### Once, across all cached calls

5. **`aggregate.py`** — pure Python, no LLM call. Collapses all cached per-call JSONs:
   - Merges filler lexicons (word → total count, position distribution)
   - Groups substance-track patterns (persuasion, urgency, objection-handling, empathy,
     guardrails, rapport, qualification) by type, pooling verbatim examples and
     why_it_worked mechanisms across calls
   - Averages `phase_prosody` numbers across calls, per phase
   - Computes the Section E output-mapping table (speed/volume/emotion ratios per phase,
     relative to a computed cross-call baseline; allowed filler set + density; tactic +
     trigger-condition rules)
   - Since no outcome labels exist yet, every call is weighted equally (no conversion
     weighting for this MVP — noted as a clean follow-up once labels exist)

   Writes `data/parameter_sheet.json` (structured) and `data/parameter_sheet.md`
   (organized per goal-doc sections A–E, verbatim-backed, meant for direct
   paste/upload into Claude web).

## Dependencies

New additions to `requirements.txt`: `librosa`, `praat-parselmouth`. `ffmpeg` is already
present system-wide (confirmed) — needed for librosa/soundfile to decode `.aac`.

## Testing / smoke test plan

1. Smoke test against the 3 existing files in `data/call_recordings_service/` first —
   verify Deepgram diarization split is clean (first speaker = AGENT) before running
   against the real 50+ files.
2. Verify prosody.py produces sane F0/RMS ranges on a known segment (sanity bounds, not
   golden-value assertions — acoustic output varies by recording).
3. Verify gold_extract.py schema conformance (all 8 top-level keys present) against at
   least one real transcript.
4. Verify aggregate.py resumability: run on 2 cached + 1 new file, confirm only the new
   file re-triggers transcribe/prosody/gold_extract.
5. Full run against whatever is dropped in `data/av_sales_call_recos/`; eyeball
   `data/parameter_sheet.md`.

## Build process note

This will be implemented on a **new git branch** (not `feat/flow-redesign-intelligence`),
via the **subagent-workflow** skill, per user instruction — not inline in the main session.
