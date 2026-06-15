"""Transcription engine — Sarvam STT (saaras:v2) with speaker diarization and InsightExtractor."""

import os
import wave
import uuid
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

from shared.db import init_db, save_transcript, save_insight, update_transcript_text, add_transcript_chunk, delete_transcript_chunks
from shared.llm_client import LLMClient
from shared.chunking import chunk_segments
from shared.embeddings import embed_batch

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "intelligence_fabric.db")
SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"

INSIGHT_SYSTEM = """You are an expert call analyst specialising in Indian voice bot quality assessment.
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
  "bot_failure_modes": ["<specific bot behaviour that failed or frustrated the customer>", "..."],
  "suggested_fixes": ["<actionable fix for the bot builder to address each failure>", "..."],
  "summary": "<2-sentence call summary>"
}

bot_failure_modes: list the specific ways the bot itself (not the agent) failed — wrong language, stuck
in a loop, missed intent, repeated a question already answered, didn't advance after confirmation, etc.
suggested_fixes: one concrete fix per failure (e.g. 'enforce @bot_language at every node', 'add
confirmation logic that advances after first Yes').

Scoring guide for agent_score:
  9-10: Excellent — clear qualification, objection handled, outcome achieved
  7-8:  Good — mostly effective, minor gaps
  5-6:  Average — partial qualification, some failed intents
  3-4:  Poor — confused flow, bot loops, language failures
  1-2:  Very poor — premature hangup, hostile, or no useful interaction"""


class TranscriptionEngine:
    """Transcribes audio with Sarvam STT (saaras:v2), diarizes speakers, and extracts call insights."""

    def __init__(self, db_path: str = DB_PATH):
        """Initialise Sarvam API key, LLM client, and ensure DB tables exist."""
        api_key = os.getenv("SARVAM_API_KEY")
        if not api_key:
            raise ValueError("SARVAM_API_KEY is not set in environment.")
        self._api_key = api_key
        self._llm = LLMClient()
        self._db = db_path
        init_db(db_path)

    def transcribe(self, audio_path: str, client_id: str) -> dict:
        """Transcribe audio file, diarise speakers, extract insights, save both to DB.

        Returns dict with keys: transcript_id, transcript, segments, duration, insight_id, insights.
        """
        audio_path = str(Path(audio_path).resolve())
        filename = Path(audio_path).name

        # ── Sarvam STT transcription ──────────────────────────────────────────
        duration = _get_duration(audio_path)

        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        response = httpx.post(
            SARVAM_STT_URL,
            headers={"api-subscription-key": self._api_key},
            files={"file": (filename, audio_bytes, _mime_type(filename))},
            data={
                "model": "saaras:v2",
                "language_code": "hi-IN",
                "with_timestamps": "true",
                "with_diarization": "true",
            },
            timeout=120.0,
        )
        response.raise_for_status()
        result = response.json()

        # ── Build speaker-labeled segments ───────────────────────────────────
        segments = _build_segments(result, duration)

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

        # ── Index chunks for RAG ──────────────────────────────────────────────
        self._index_chunks(transcript_id, client_id, segments)

        # ── Extract insights via LLM ──────────────────────────────────────────
        insight_data = self._extract_insights(transcript_id, client_id, transcript_text)

        return {
            "transcript_id": transcript_id,
            "transcript": transcript_text,
            "segments": segments,
            "duration": duration,
            "insight_id": insight_data["insight_id"],
            "insights": insight_data,
        }

    def _index_chunks(self, transcript_id, client_id, segments):
        try:
            chunks = chunk_segments(segments)
            if not chunks:
                return
            vecs = embed_batch([c["text"] for c in chunks])
            for c, v in zip(chunks, vecs):
                add_transcript_chunk(transcript_id, client_id, c["chunk_index"],
                                     c["role_sequence"], c["start"], c["end"], c["text"], v)
        except Exception as e:
            print(f"[chunk-index] failed for transcript {transcript_id}: {e}", flush=True)

    def rerun_insights(self, transcript_id: str, client_id: str, edited_text: str) -> dict:
        """Save edited transcript text and append a fresh insight row.

        Previous insight rows are preserved so the caller can diff before vs after.
        Returns the new insight dict.
        """
        update_transcript_text(transcript_id, edited_text, path=self._db)
        delete_transcript_chunks(transcript_id)
        # TODO: re-chunk needs segments; only deleting stale chunks here
        return self._extract_insights(transcript_id, client_id, edited_text)

    def _extract_insights(self, transcript_id: str, client_id: str, transcript_text: str) -> dict:
        """Run second LLM call to extract structured insights from transcript."""
        user_prompt = f"Analyse this call transcript:\n\n{transcript_text}"
        try:
            raw = self._llm.complete_json(INSIGHT_SYSTEM, user_prompt, max_tokens=1024)
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
    return {"wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4", "aac": "audio/aac"}.get(
        ext, "audio/wav"
    )


def _get_duration(audio_path: str) -> float:
    """Return audio duration in seconds. Supports WAV natively; returns 0.0 for other formats."""
    try:
        if audio_path.lower().endswith(".wav"):
            with wave.open(audio_path, "rb") as wf:
                return round(wf.getnframes() / wf.getframerate(), 2)
    except Exception:
        pass
    return 0.0


def _assign_role(speaker_id: str, speaker_order: list) -> str:
    """First speaker = AGENT (outbound caller always speaks first), second = CUSTOMER."""
    if len(speaker_order) <= 2:
        return "AGENT" if speaker_order.index(speaker_id) == 0 else "CUSTOMER"
    return speaker_id  # 3+ speakers — keep raw labels


def _build_segments(result: dict, duration: float) -> list:
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
        return segments

    # No diarization — single block with full transcript
    return [
        {
            "speaker": "SPEAKER_00",
            "role": "AGENT",
            "start": 0.0,
            "end": duration,
            "text": str(result.get("transcript", "")).strip(),
            "confidence": None,
        }
    ]
