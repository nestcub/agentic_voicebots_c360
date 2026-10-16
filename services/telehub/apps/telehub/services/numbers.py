"""
A VoiceBot's DIDs (PhoneNumber rows) and the number a stage is assigned.

  outbound   the stage dials from its assigned number (journey_dids)
  inbound    the number the customer dialed (`callee_number` in the post-call
             payload) must be the stage's number; if not, the call is still
             recorded but flagged (check_callee)

A stage with no number assigned is automatic: it dials from its bot's first
number and, inbound, accepts any of the bot's numbers. A bot with no
PhoneNumber rows at all falls back to its legacy VoiceBot.dids list, so
nothing breaks for data created before PhoneNumber existed.

Everything that runs inside the webhook or the scheduler fails open: a lookup
problem means "no restriction", never an exception.
"""
from django.db import transaction

from ..models import PhoneNumber
from .phone import normalize_digits

INBOUND_COMMUNICATION_TYPE = "voice_inbound"
CALLEE_KEYS = ("callee_number", "called_number")


def clean_dids(raw) -> tuple:
    """
    Validates a dids list from the API. Returns (dids, error): `dids` has
    blanks and duplicate numbers (same digits) removed, original spelling
    kept; `error` is a message when raw isn't a list of usable numbers.
    """
    if raw is None:
        return [], ""
    if not isinstance(raw, list):
        return [], "dids must be a list of phone numbers"
    cleaned, seen = [], set()
    for item in raw:
        did = str(item or "").strip()
        if not did:
            continue
        key = normalize_digits(did)
        if len(key) < 7 or len(did) > 32:
            return [], f"{did!r} is not a valid phone number"
        if key not in seen:
            seen.add(key)
            cleaned.append(did)
    return cleaned, ""


@transaction.atomic
def sync_bot_numbers(voice_bot) -> None:
    """Makes the bot's PhoneNumber rows match voice_bot.dids (adds new, drops removed)."""
    wanted = {}
    for did in voice_bot.dids or []:
        key = normalize_digits(did)
        if key:
            wanted.setdefault(key, str(did).strip())

    existing = {n.did_key: n for n in voice_bot.numbers.all()}
    for key, number in existing.items():
        if key not in wanted:
            number.delete()
    for key, did in wanted.items():
        if key in existing:
            if existing[key].did != did:
                existing[key].did = did
                existing[key].save()
        else:
            PhoneNumber.objects.create(organization=voice_bot.organization, voice_bot=voice_bot, did=did)


def journey_numbers(journey) -> list:
    """PhoneNumber rows this stage uses: its assigned number, else all of its bot's (automatic)."""
    if journey is None or journey.voice_bot_id is None:
        return []
    selected = list(journey.numbers.all())
    return selected or list(journey.voice_bot.numbers.all())


def journey_dids(journey) -> list:
    """DIDs (as strings) this stage uses; the first is the one outbound calls dial from."""
    try:
        numbers = journey_numbers(journey)
        if numbers:
            return [n.did for n in numbers]
        return list(journey.voice_bot.dids or []) if journey and journey.voice_bot else []
    except Exception:
        return []


def callee_in(payload) -> str:
    for key in CALLEE_KEYS:
        value = (payload or {}).get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def check_callee(process_agent, payload) -> dict:
    """
    Did the customer dial one of this agent's inbound numbers? Returns
    {"mismatch": bool, "callee": str, "expected": [dids]}. Never a mismatch
    when the payload has no dialed number or the agent's inbound stages have no
    numbers to compare against (nothing to verify).
    """
    result = {"mismatch": False, "callee": "", "expected": []}
    try:
        callee = callee_in(payload)
        result["callee"] = callee
        expected = []
        for journey in process_agent.bot_journeys.select_related("voice_bot"):
            if journey.voice_bot and journey.voice_bot.communication_type == INBOUND_COMMUNICATION_TYPE:
                expected += journey_dids(journey)
        result["expected"] = expected
        if not callee or not expected:
            return result
        result["mismatch"] = normalize_digits(callee) not in {normalize_digits(d) for d in expected}
    except Exception:
        result["mismatch"] = False
    return result
