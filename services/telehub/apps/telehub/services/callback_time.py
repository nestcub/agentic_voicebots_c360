"""
Resolves the raw call_back_time string a voice bot posts back in its outcome
webhook (e.g. Chat360's @call_back_time) into an absolute datetime.

Ported as-is from the original algorithm proven on real Chat360 traffic
(orchestrator_django/apps/orchestrator/services/workflow_service.py on branch
feat/orch-v2, commit history predating this branch's telehub rebuild) — the
regexes and format list are not guesses, they reflect actual payload shapes
seen in production transcripts. Not yet called from anywhere in telehub (V1
has no webhook-intake/execution engine wired up yet); this is the utility the
future execution/webhook handler calls per-Execution for any variable a
Process Agent's callback.time_variable config names (see
services/process_agent.py and the wizard's Callback section).
"""
import re
from datetime import datetime, timedelta

from django.utils import timezone

# Chat360's documented absolute format is DD-MM-YYYY HH:MM AM/PM (matches @appointment_time
# in real transcripts, e.g. "08-07-2026 05:00 PM"); a couple of fallbacks included since
# this is untrusted external input and formats can drift.
CALL_BACK_TIME_FORMATS = [
    "%d-%m-%Y %I:%M %p",
    "%d-%m-%Y %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
]

# In real traffic, call_back_time is often NOT the absolute format above — it's the
# bot's verbatim capture of a spoken relative request, e.g. "5 मिनट बाद" ("in 5
# minutes") or "5 minute baad". These resolve relative to now (call time), not as a
# calendar date. Devanagari digits are normalized to ASCII first since payloads can
# use either script.
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
RELATIVE_CALL_BACK_PATTERNS = [
    (re.compile(r"(\d+)\s*(?:मिनट|min(?:ute)?s?)", re.IGNORECASE), "minutes"),
    (re.compile(r"(\d+)\s*(?:घंटे|घंटा|घंटों|hours?|hrs?)", re.IGNORECASE), "hours"),
]


def parse_call_back_time(raw: str):
    """
    Best-effort parse of a voice bot's call_back_time string. Tries relative
    phrases first (RELATIVE_CALL_BACK_PATTERNS, resolved against timezone.now()),
    then falls back to the absolute CALL_BACK_TIME_FORMATS. Returns an aware
    datetime in Django's configured current timezone, or None if unparseable —
    callers should skip scheduling entirely rather than guess on malformed
    external input.
    """
    if not raw or not raw.strip():
        return None
    text = raw.strip().translate(_DEVANAGARI_DIGITS)

    for pattern, unit in RELATIVE_CALL_BACK_PATTERNS:
        match = pattern.search(text)
        if match:
            amount = int(match.group(1))
            delta = timedelta(minutes=amount) if unit == "minutes" else timedelta(hours=amount)
            return timezone.now() + delta

    for fmt in CALL_BACK_TIME_FORMATS:
        try:
            naive = datetime.strptime(text, fmt)
            return timezone.make_aware(naive, timezone.get_current_timezone())
        except ValueError:
            continue
    return None
