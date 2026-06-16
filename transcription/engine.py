"""Transcription engine — provider-agnostic (Sarvam Batch API + Deepgram) with speaker diarization and InsightExtractor."""

import json
import os
import tempfile
import wave
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from shared.db import init_db, save_transcript, save_insight, update_transcript_text
from shared.llm_client import LLMClient

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "intelligence_fabric.db")

INSIGHT_SYSTEM = """You are an expert call analyst specialising in Indian human agent quality assessment.
Analyse the provided agent-customer call transcript and return a structured JSON object.

Respond with valid JSON only — no markdown, no explanation.

JSON schema:
{
  "agent_score": <integer 1-10>,
  "sentiment": "<positive|neutral|negative>",
  "objection_patterns": ["<objection 1>", "..."],
  "qualification_signals": ["<signal 1>", "..."],
  "escalation_signals": ["<signal 1>", "..."],
  "kb_gaps": ["<topic the agent couldn't answer 1>", "..."],
  "agent_failure_modes": ["<behaviour or gap that hurt the call 1>", "..."],
  "suggested_fixes": ["<coaching suggestion 1>", "..."],
  "summary": "<2-sentence call summary>"
}

Scoring guide for agent_score:
  9-10: Excellent — clear qualification, objection handled, outcome achieved
  7-8:  Good — mostly effective, minor gaps
  5-6:  Average — partial qualification, some missed signals
  3-4:  Poor — confused flow, objections not handled
  1-2:  Very poor — premature hangup, hostile, or no useful interaction"""


class TranscriptionEngine:
    """Transcribes audio with Sarvam Batch API or Deepgram, diarizes speakers, and extracts call insights."""

    def __init__(self, db_path: str = DB_PATH):
        """Initialise provider API keys, LLM client, and ensure DB tables exist."""
        self._sarvam_key = os.getenv("SARVAM_API_KEY")
        self._deepgram_key = os.getenv("DEEPGRAM_API_KEY")
        self._llm = LLMClient()
        self._db = db_path
        init_db(db_path)

    def transcribe(self, audio_path: str, client_id: str, provider: str = None, swap_roles: bool = False, language_code: str = "hi-IN", insight_provider: str = None) -> dict:
        """Transcribe audio file, diarise speakers, extract insights, save both to DB.

        provider: "sarvam" or "deepgram". Defaults to TRANSCRIPTION_PROVIDER env var, then "sarvam".
        swap_roles: if True, swap AGENT<->CUSTOMER labels in all segments.
        Returns dict with keys: transcript_id, transcript, segments, duration, insight_id, insights.
        """
        if provider is None:
            provider = os.getenv("TRANSCRIPTION_PROVIDER", "sarvam")

        audio_path = str(Path(audio_path).resolve())
        filename = Path(audio_path).name
        duration = _get_duration(audio_path)

        # ── Dispatch to provider ──────────────────────────────────────────────
        if provider == "deepgram":
            segments = self._transcribe_deepgram(audio_path, duration, swap_roles=swap_roles, language_code=language_code)
        else:
            segments = self._transcribe_sarvam(audio_path, duration, swap_roles=swap_roles, language_code=language_code)

        # ── Full transcript text ──────────────────────────────────────────────
        transcript_text = "\n".join(
            f"[{s['start']:.1f}s] {s['role']}: {s['text']}" for s in segments
        )

        # ── Save transcript ───────────────────────────────────────────────────
        transcript_id = save_transcript(
            {
                "client_id": client_id,
                "filename": filename,
                "transcript_text": transcript_text,
                "segments": segments,
                "duration": duration,
            },
            path=self._db,
        )

        # ── Extract insights via LLM ──────────────────────────────────────────
        insight_data = self._extract_insights(transcript_id, client_id, transcript_text, insight_provider=insight_provider)

        return {
            "transcript_id": transcript_id,
            "transcript": transcript_text,
            "segments": segments,
            "duration": duration,
            "insight_id": insight_data["insight_id"],
            "insights": insight_data,
        }

    def transcribe_many(
        self,
        file_paths: list,
        client_id: str,
        provider: str = None,
        swap_roles: bool = False,
        on_file_done=None,
        language_code: str = "hi-IN",
        insight_provider: str = None,
    ) -> None:
        """Transcribe multiple files with optimized parallelism.

        Sarvam: short files (<=25s) go directly to sync API; longer files are grouped
        into batches of <=20 and submitted as Sarvam batch jobs simultaneously.
        Deepgram: fires all files in parallel via ThreadPoolExecutor(max_workers=10).

        on_file_done(filename: str, result: dict | Exception) called per file.
        """
        if provider is None:
            provider = os.getenv("TRANSCRIPTION_PROVIDER", "sarvam")

        if provider == "deepgram":
            self._transcribe_many_deepgram(file_paths, client_id, swap_roles, on_file_done, language_code, insight_provider)
        else:
            self._transcribe_many_sarvam(file_paths, client_id, swap_roles, on_file_done, language_code, insight_provider)

    def _transcribe_sarvam_sync(self, audio_path: str, duration: float, swap_roles: bool = False, language_code: str = "hi-IN") -> list:
        """Transcribe a short file (<=25s) using Sarvam's synchronous STT API. Much faster than batch for short clips."""
        if not self._sarvam_key:
            raise ValueError("SARVAM_API_KEY is not set in environment.")

        from sarvamai import SarvamAI

        sarvam = SarvamAI(api_subscription_key=self._sarvam_key)
        mime = _mime_type(audio_path)
        filename = Path(audio_path).name

        with open(audio_path, "rb") as f:
            response = sarvam.speech_to_text.transcribe(
                file=(filename, f, mime),
                model="saarika:v2.5",
                language_code=language_code,
                with_diarization=True,
                with_timestamps=True,
            )

        # response may be a pydantic model or dict — normalise to dict
        if hasattr(response, "model_dump"):
            result = response.model_dump()
        elif hasattr(response, "__dict__"):
            result = vars(response)
        else:
            result = dict(response)

        return _build_segments(result, duration, swap_roles=swap_roles)

    def _transcribe_sarvam(self, audio_path: str, duration: float, swap_roles: bool = False, language_code: str = "hi-IN") -> list:
        """Transcribe using Sarvam. Routes to sync API for <=25s files, batch API for longer ones."""
        SYNC_THRESHOLD = 25.0
        if duration > 0 and duration <= SYNC_THRESHOLD:
            return self._transcribe_sarvam_sync(audio_path, duration, swap_roles=swap_roles, language_code=language_code)

        # Batch path (unchanged) for longer files or unknown duration
        if not self._sarvam_key:
            raise ValueError("SARVAM_API_KEY is not set in environment.")

        from sarvamai import SarvamAI

        sarvam = SarvamAI(api_subscription_key=self._sarvam_key)
        job = sarvam.speech_to_text_job.create_job(
            model="saarika:v2.5",
            language_code=language_code,
            with_diarization=True,
            with_timestamps=True,
        )
        job.upload_files([audio_path])
        job.start()
        status = job.wait_until_complete(poll_interval=5, timeout=600)

        if status.job_state.lower() == "failed":
            raise RuntimeError(f"Sarvam batch job failed: {status.error_message}")

        with tempfile.TemporaryDirectory() as tmpdir:
            job.download_outputs(tmpdir)
            result_path = Path(tmpdir) / f"{Path(audio_path).name}.json"
            with open(result_path) as f:
                result = json.load(f)

        return _build_segments(result, duration, swap_roles=swap_roles)

    def _transcribe_deepgram(self, audio_path: str, duration: float, swap_roles: bool = False, language_code: str = "hi-IN") -> list:
        """Transcribe using Deepgram nova-3 with diarization. Returns normalised segment list."""
        if not self._deepgram_key:
            raise ValueError("DEEPGRAM_API_KEY is not set in environment.")

        from deepgram import DeepgramClient

        dg = DeepgramClient(api_key=self._deepgram_key)
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        # Deepgram uses BCP-47 base tag only (e.g. "hi" from "hi-IN")
        dg_lang = language_code.split("-")[0]
        response = dg.listen.v1.media.transcribe_file(
            request=audio_bytes,
            model="nova-3",
            language=dg_lang,
            diarize=True,
            utterances=True,
            punctuate=True,
            smart_format=True,
        )
        return _build_segments_deepgram(response, duration, swap_roles=swap_roles)

    def _transcribe_many_sarvam(self, file_paths: list, client_id: str, swap_roles: bool, on_file_done, language_code: str = "hi-IN", insight_provider: str = None) -> None:
        """Submit files in groups of 20 as Sarvam batch jobs; short files (<=25s) use sync API directly."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from sarvamai import SarvamAI

        if not self._sarvam_key:
            raise ValueError("SARVAM_API_KEY is not set.")

        SYNC_THRESHOLD = 25.0
        CHUNK = 20

        # Measure durations and split into short (sync) vs long (batch)
        short_paths = []
        long_paths = []
        for p in file_paths:
            d = _get_duration(p)
            if d > 0 and d <= SYNC_THRESHOLD:
                short_paths.append(p)
            else:
                long_paths.append(p)

        def _process_single_sync(path: str) -> tuple:
            """Handle one short file via sync Sarvam API."""
            fname = Path(path).name
            try:
                duration = _get_duration(path)
                segments = self._transcribe_sarvam_sync(path, duration, swap_roles=swap_roles, language_code=language_code)
                transcript_text = "\n".join(
                    f"[{s['start']:.1f}s] {s['role']}: {s['text']}" for s in segments
                )
                transcript_id = save_transcript({
                    "client_id": client_id,
                    "filename": fname,
                    "transcript_text": transcript_text,
                    "segments": segments,
                    "duration": duration,
                }, path=self._db)
                insight_data = self._extract_insights(transcript_id, client_id, transcript_text, insight_provider=insight_provider)
                return path, {
                    "transcript_id": transcript_id,
                    "transcript": transcript_text,
                    "segments": segments,
                    "duration": duration,
                    "insight_id": insight_data["insight_id"],
                    "insights": insight_data,
                }
            except Exception as e:
                return path, e

        def _run_batch_group(paths: list) -> list:
            """Submit one Sarvam batch job for a group of long files."""
            sarvam = SarvamAI(api_subscription_key=self._sarvam_key)
            job = sarvam.speech_to_text_job.create_job(
                model="saarika:v2.5",
                language_code=language_code,
                with_diarization=True,
                with_timestamps=True,
            )
            job.upload_files(paths)
            job.start()
            status = job.wait_until_complete(poll_interval=5, timeout=600)

            results = []
            if status.job_state.lower() == "failed":
                exc = RuntimeError(f"Sarvam batch job failed: {status.error_message}")
                for p in paths:
                    results.append((p, exc))
                return results

            with tempfile.TemporaryDirectory() as tmpdir:
                job.download_outputs(tmpdir)
                for path in paths:
                    fname = Path(path).name
                    result_path = Path(tmpdir) / f"{fname}.json"
                    try:
                        with open(result_path) as f:
                            raw = json.load(f)
                        duration = _get_duration(path)
                        segments = _build_segments(raw, duration, swap_roles=swap_roles)
                        transcript_text = "\n".join(
                            f"[{s['start']:.1f}s] {s['role']}: {s['text']}" for s in segments
                        )
                        transcript_id = save_transcript({
                            "client_id": client_id,
                            "filename": fname,
                            "transcript_text": transcript_text,
                            "segments": segments,
                            "duration": duration,
                        }, path=self._db)
                        insight_data = self._extract_insights(transcript_id, client_id, transcript_text, insight_provider=insight_provider)
                        results.append((path, {
                            "transcript_id": transcript_id,
                            "transcript": transcript_text,
                            "segments": segments,
                            "duration": duration,
                            "insight_id": insight_data["insight_id"],
                            "insights": insight_data,
                        }))
                    except Exception as e:
                        results.append((path, e))
            return results

        # Build futures: one per short file + one per batch group of long files
        groups = [long_paths[i:i + CHUNK] for i in range(0, len(long_paths), CHUNK)]
        max_workers = len(short_paths) + len(groups)
        if max_workers == 0:
            return

        with ThreadPoolExecutor(max_workers=max(max_workers, 1)) as pool:
            futures = {}
            for p in short_paths:
                futures[pool.submit(_process_single_sync, p)] = "sync"
            for g in groups:
                futures[pool.submit(_run_batch_group, g)] = "batch"

            for fut in as_completed(futures):
                kind = futures[fut]
                if kind == "sync":
                    path, result = fut.result()
                    if on_file_done:
                        on_file_done(Path(path).name, result)
                else:
                    for path, result in fut.result():
                        if on_file_done:
                            on_file_done(Path(path).name, result)

    def _transcribe_many_deepgram(self, file_paths: list, client_id: str, swap_roles: bool, on_file_done, language_code: str = "hi-IN", insight_provider: str = None) -> None:
        """Transcribe all files in parallel via ThreadPoolExecutor."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _one(path: str):
            fname = Path(path).name
            try:
                result = self.transcribe(path, client_id, provider="deepgram", swap_roles=swap_roles, language_code=language_code, insight_provider=insight_provider)
                return fname, result
            except Exception as e:
                return fname, e

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(_one, p) for p in file_paths]
            for fut in as_completed(futures):
                fname, result = fut.result()
                if on_file_done:
                    on_file_done(fname, result)

    def rerun_insights(self, transcript_id: str, client_id: str, edited_text: str, insight_provider: str = None) -> dict:
        """Save edited transcript text and append a fresh insight row.

        Previous insight rows are preserved so the caller can diff before vs after.
        Returns the new insight dict.
        """
        update_transcript_text(transcript_id, edited_text, path=self._db)
        return self._extract_insights(transcript_id, client_id, edited_text, insight_provider=insight_provider)

    def _extract_insights(self, transcript_id: str, client_id: str, transcript_text: str, insight_provider: str = None) -> dict:
        """Run second LLM call to extract structured insights from transcript."""
        llm = LLMClient(provider=insight_provider) if insight_provider else self._llm
        user_prompt = f"Analyse this call transcript:\n\n{transcript_text}"
        try:
            raw = llm.complete_json(INSIGHT_SYSTEM, user_prompt, max_tokens=1024)
        except Exception as e:
            raw = {
                "agent_score": None,
                "sentiment": "neutral",
                "objection_patterns": [],
                "qualification_signals": [],
                "escalation_signals": [],
                "kb_gaps": [],
                "summary": f"Insight extraction failed: {e}",
            }

        insight_id = save_insight(
            {
                "transcript_id": transcript_id,
                "client_id": client_id,
                "agent_score": raw.get("agent_score"),
                "sentiment": raw.get("sentiment", "neutral"),
                "objection_patterns": raw.get("objection_patterns", []),
                "qualification_signals": raw.get("qualification_signals", []),
                "escalation_signals": raw.get("escalation_signals", []),
                "kb_gaps": raw.get("kb_gaps", []),
                "raw_insights_json": raw,
            },
            path=self._db,
        )
        return {**raw, "insight_id": insight_id}


# ── helpers ───────────────────────────────────────────────────────────────────

def _mime_type(filename: str) -> str:
    """Return MIME type based on audio file extension."""
    ext = Path(filename).suffix.lower().lstrip(".")
    return {
        "wav": "audio/wav", "mp3": "audio/mpeg",
        "m4a": "audio/mp4", "mp4": "audio/mp4",
        "aac": "audio/aac", "mpeg": "video/mpeg", "mpg": "video/mpeg",
    }.get(ext, "audio/wav")


def _get_duration(audio_path: str) -> float:
    """Return audio duration in seconds. Uses wave for WAV, mutagen for everything else."""
    path = audio_path.lower()
    try:
        if path.endswith(".wav"):
            import wave
            with wave.open(audio_path, "rb") as wf:
                return round(wf.getnframes() / wf.getframerate(), 2)
        else:
            from mutagen import File as MutagenFile
            audio = MutagenFile(audio_path)
            if audio is not None and audio.info is not None:
                return round(float(audio.info.length), 2)
    except Exception:
        pass
    return 0.0


def _assign_role(speaker_id: str, speaker_order: list) -> str:
    """First speaker = AGENT (outbound caller always speaks first), second = CUSTOMER."""
    if len(speaker_order) <= 2:
        return "AGENT" if speaker_order.index(speaker_id) == 0 else "CUSTOMER"
    return speaker_id  # 3+ speakers — keep raw labels


def _build_segments(result: dict, duration: float, swap_roles: bool = False) -> list:
    """Convert Sarvam diarized_transcript entries into speaker-labeled segment dicts.

    Falls back to a single AGENT block if diarization is absent from the response.
    """
    entries = []
    try:
        entries = result.get("diarized_transcript", {}).get("entries", []) or []
    except Exception:
        pass

    if entries:
        speaker_order: list = []
        segments = []
        for entry in entries:
            speaker_id = f"SPEAKER_{int(entry.get('speaker_id', 0)):02d}"
            if speaker_id not in speaker_order:
                speaker_order.append(speaker_id)
            segments.append(
                {
                    "speaker": speaker_id,
                    "role": _assign_role(speaker_id, speaker_order),
                    "start": round(float(entry.get("start", 0.0)), 2),
                    "end": round(float(entry.get("end", 0.0)), 2),
                    "text": str(entry.get("transcript", "")).strip(),
                    "confidence": None,
                }
            )
        if swap_roles:
            role_map = {"AGENT": "CUSTOMER", "CUSTOMER": "AGENT"}
            for s in segments:
                s["role"] = role_map.get(s["role"], s["role"])
        return segments

    # No diarization — single block with full transcript
    segments = [
        {
            "speaker": "SPEAKER_00",
            "role": "AGENT",
            "start": 0.0,
            "end": duration,
            "text": str(result.get("transcript", "")).strip(),
            "confidence": None,
        }
    ]
    if swap_roles:
        role_map = {"AGENT": "CUSTOMER", "CUSTOMER": "AGENT"}
        for s in segments:
            s["role"] = role_map.get(s["role"], s["role"])
    return segments


def _build_segments_deepgram(response, duration: float, swap_roles: bool = False) -> list:
    """Convert Deepgram utterances into the same speaker-labeled segment format as Sarvam."""
    utterances = []
    try:
        utterances = response.results.utterances or []
    except Exception:
        pass

    if utterances:
        speaker_order = []
        segments = []
        for u in utterances:
            speaker_id = f"SPEAKER_{int(u.speaker or 0):02d}"
            if speaker_id not in speaker_order:
                speaker_order.append(speaker_id)
            segments.append({
                "speaker": speaker_id,
                "role": _assign_role(speaker_id, speaker_order),
                "start": round(float(u.start or 0.0), 2),
                "end": round(float(u.end or 0.0), 2),
                "text": str(u.transcript or "").strip(),
                "confidence": u.confidence,
            })
        if swap_roles:
            role_map = {"AGENT": "CUSTOMER", "CUSTOMER": "AGENT"}
            for s in segments:
                s["role"] = role_map.get(s["role"], s["role"])
        return segments

    # Fallback: no utterances, try channels[0]
    text = ""
    try:
        text = response.results.channels[0].alternatives[0].transcript or ""
    except Exception:
        pass
    segments = [{"speaker": "SPEAKER_00", "role": "AGENT", "start": 0.0, "end": duration, "text": text.strip(), "confidence": None}]
    if swap_roles:
        role_map = {"AGENT": "CUSTOMER", "CUSTOMER": "AGENT"}
        for s in segments:
            s["role"] = role_map.get(s["role"], s["role"])
    return segments
