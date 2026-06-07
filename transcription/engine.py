"""Transcription engine — Deepgram Nova-3 with speaker diarization and InsightExtractor."""

import os
import json
import uuid
from datetime import datetime
from pathlib import Path

from deepgram import DeepgramClient, PrerecordedOptions
from dotenv import load_dotenv

from shared.db import init_db, save_transcript, save_insight
from shared.llm_client import LLMClient

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "intelligence_fabric.db")

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
  "summary": "<2-sentence call summary>"
}

Scoring guide for agent_score:
  9-10: Excellent — clear qualification, objection handled, outcome achieved
  7-8:  Good — mostly effective, minor gaps
  5-6:  Average — partial qualification, some missed signals
  3-4:  Poor — confused flow, objections not handled
  1-2:  Very poor — premature hangup, hostile, or no useful interaction"""


class TranscriptionEngine:
    """Transcribes audio with Deepgram Nova-3, diarizes speakers, and extracts call insights."""

    def __init__(self, db_path: str = DB_PATH):
        """Initialise Deepgram client, LLM client, and ensure DB tables exist."""
        api_key = os.getenv("DEEPGRAM_API_KEY")
        if not api_key:
            raise ValueError("DEEPGRAM_API_KEY is not set in environment.")
        self._dg = DeepgramClient(api_key)
        self._llm = LLMClient()
        self._db = db_path
        init_db(db_path)

    def transcribe(self, audio_path: str, client_id: str) -> dict:
        """Transcribe audio file, diarise speakers, extract insights, save both to DB.

        Returns dict with keys: transcript_id, transcript, segments, duration, insight_id, insights.
        """
        audio_path = str(Path(audio_path).resolve())
        filename = Path(audio_path).name

        # ── Deepgram transcription ────────────────────────────────────────────
        options = PrerecordedOptions(
            model="nova-3",
            language="hi",
            diarize=True,
            punctuate=True,
            utterances=True,
            smart_format=True,
        )

        with open(audio_path, "rb") as f:
            audio_data = f.read()

        response = self._dg.listen.prerecorded.v("1").transcribe_file(
            {"buffer": audio_data, "mimetype": _mime_type(filename)},
            options,
        )

        result = response.results
        duration = response.metadata.duration if response.metadata else 0.0

        # ── Build speaker-labeled segments ───────────────────────────────────
        segments = _build_segments(result)

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
        insight_data = self._extract_insights(transcript_id, client_id, transcript_text)

        return {
            "transcript_id": transcript_id,
            "transcript": transcript_text,
            "segments": segments,
            "duration": duration,
            "insight_id": insight_data["insight_id"],
            "insights": insight_data,
        }

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
    ext = Path(filename).suffix.lower()
    return {"wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4", "aac": "audio/aac"}.get(
        ext.lstrip("."), "audio/wav"
    )


def _build_segments(result) -> list:
    """Convert Deepgram utterances into speaker-labeled segment dicts."""
    segments = []
    speaker_order = []

    utterances = getattr(result, "utterances", None) or []
    for utt in utterances:
        speaker_id = f"SPEAKER_{utt.speaker:02d}"
        if speaker_id not in speaker_order:
            speaker_order.append(speaker_id)
        segments.append(
            {
                "speaker": speaker_id,
                "role": _assign_role(speaker_id, speaker_order),
                "start": round(utt.start, 2),
                "end": round(utt.end, 2),
                "text": utt.transcript.strip(),
                "confidence": round(utt.confidence, 3) if utt.confidence else None,
            }
        )

    # Fallback to words if no utterances
    if not segments:
        segments = _segments_from_words(result, speaker_order)

    return segments


def _assign_role(speaker_id: str, speaker_order: list) -> str:
    """First speaker = AGENT (outbound caller always speaks first), second = CUSTOMER."""
    if len(speaker_order) <= 2:
        return "AGENT" if speaker_order.index(speaker_id) == 0 else "CUSTOMER"
    return speaker_id  # 3+ speakers — keep raw labels


def _segments_from_words(result, speaker_order: list) -> list:
    """Build segments from word-level diarization when utterances are unavailable."""
    words = []
    try:
        words = result.channels[0].alternatives[0].words or []
    except (AttributeError, IndexError):
        return []

    segments, current_speaker, current_words = [], None, []
    for w in words:
        spk = f"SPEAKER_{w.speaker:02d}" if hasattr(w, "speaker") else "SPEAKER_00"
        if spk not in speaker_order:
            speaker_order.append(spk)
        if spk != current_speaker:
            if current_words:
                segments.append(_make_segment(current_speaker, current_words, speaker_order))
            current_speaker, current_words = spk, [w]
        else:
            current_words.append(w)
    if current_words:
        segments.append(_make_segment(current_speaker, current_words, speaker_order))
    return segments


def _make_segment(speaker_id: str, words: list, speaker_order: list) -> dict:
    """Build a single segment dict from a list of word objects."""
    text = " ".join(getattr(w, "punctuated_word", w.word) for w in words)
    return {
        "speaker": speaker_id,
        "role": _assign_role(speaker_id, speaker_order),
        "start": round(words[0].start, 2),
        "end": round(words[-1].end, 2),
        "text": text.strip(),
        "confidence": None,
    }
