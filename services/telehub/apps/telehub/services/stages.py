"""
Managing a process agent's voicebot stages (BotJourneys) and the transitions
between them, for the Settings tab: add a stage, choose its bot and which of
the bot's numbers it uses, and say when a finished call hands the lead on to
another stage (JourneyTransition, executed by services/handoff.py).

validate_* return (cleaned_fields, errors) like services/channel_config.py.
"""
from django.db import transaction

from ..models import BotJourney, JourneyTransition, VoiceBot
from .channel_config import clean_checks
from .journey import generate_journey
from .process_agent import (
    NODE_NAME_BUSINESS_HOURS,
    NODE_NAME_CALLBACK,
    NODE_NAME_COMMUNICATION,
    NODE_NAME_CRM_UPDATE,
    NODE_NAME_DND_CHECK,
    NODE_NAME_QA,
    NODE_NAME_RETRY,
    VOICE_BOT_TO_NODE_CONFIG_FIELDS,
)

NAME_MAX = BotJourney._meta.get_field("name").max_length

# A new stage starts with the same business rules as the agent's first stage
# (retry budget, business hours, DND, callback, QA, CRM); only the Communication
# node is its own, wired to the stage's bot.
COPIED_NODE_NAMES = (
    NODE_NAME_RETRY,
    NODE_NAME_BUSINESS_HOURS,
    NODE_NAME_DND_CHECK,
    NODE_NAME_CALLBACK,
    NODE_NAME_QA,
    NODE_NAME_CRM_UPDATE,
)


# ── stages ──────────────────────────────────────────────────────────────────


def push_bot_to_communication_node(journey) -> None:
    """Copies the stage's VoiceBot settings onto its Communication node (what dispatch reads)."""
    node = journey.nodes.filter(name=NODE_NAME_COMMUNICATION).first()
    if node is None:
        return
    bot = journey.voice_bot
    fields = {field: getattr(bot, field) for field in VOICE_BOT_TO_NODE_CONFIG_FIELDS} if bot else {}
    node.config = {**node.config, **fields}
    node.save()


def validate_stage(process_agent, organization, data, instance=None) -> tuple:
    errors, cleaned = {}, {}
    data = data if isinstance(data, dict) else {}

    if instance is None or "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            errors["name"] = "name is required"
        elif len(name) > NAME_MAX:
            errors["name"] = f"name must be at most {NAME_MAX} characters"
        else:
            cleaned["name"] = name

    bot = instance.voice_bot if instance is not None else None
    if instance is None or "voice_bot" in data:
        raw = data.get("voice_bot")
        bot = VoiceBot.objects.for_org(organization).filter(pk=raw).first() if str(raw).isdigit() else None
        if bot is None:
            errors["voice_bot"] = "choose one of your voice bots"
        else:
            cleaned["voice_bot"] = bot

    if "order" in data:
        try:
            cleaned["order"] = int(data["order"])
        except (TypeError, ValueError):
            errors["order"] = "order must be a whole number"

    if "numbers" in data:
        raw_ids = data["numbers"]
        if not isinstance(raw_ids, list) or not all(isinstance(i, int) for i in raw_ids):
            errors["numbers"] = "numbers must be a list of number ids"
        elif len(set(raw_ids)) > 1:
            errors["numbers"] = "a stage is assigned one number"
        elif bot is not None:
            valid = set(bot.numbers.filter(pk__in=raw_ids).values_list("id", flat=True))
            if valid != set(raw_ids):
                errors["numbers"] = "numbers must be numbers of this stage's voice bot"
            else:
                cleaned["numbers"] = raw_ids
    elif "voice_bot" in cleaned and instance is not None and cleaned["voice_bot"].pk != instance.voice_bot_id:
        # Switching bots: the old bot's numbers no longer apply.
        cleaned["numbers"] = []

    return cleaned, errors


@transaction.atomic
def create_stage(process_agent, cleaned) -> BotJourney:
    last = process_agent.bot_journeys.order_by("-order").first()
    first = process_agent.bot_journeys.order_by("order", "id").first()
    journey = BotJourney.objects.create(
        process_agent=process_agent,
        name=cleaned["name"],
        voice_bot=cleaned["voice_bot"],
        order=cleaned.get("order", (last.order + 1) if last else 0),
    )
    generate_journey(journey)
    if first is not None:
        source_nodes = {n.name: n for n in first.nodes.all()}
        for node in journey.nodes.filter(name__in=COPIED_NODE_NAMES):
            source = source_nodes.get(node.name)
            if source is not None:
                node.config = dict(source.config)
                node.save()
    push_bot_to_communication_node(journey)
    if cleaned.get("numbers"):
        journey.numbers.set(cleaned["numbers"])
    return journey


@transaction.atomic
def update_stage(journey, cleaned) -> BotJourney:
    bot_changed = "voice_bot" in cleaned and cleaned["voice_bot"].pk != journey.voice_bot_id
    for field in ("name", "voice_bot", "order"):
        if field in cleaned:
            setattr(journey, field, cleaned[field])
    journey.save()
    if "numbers" in cleaned:
        journey.numbers.set(cleaned["numbers"])
    if bot_changed:
        push_bot_to_communication_node(journey)
    return journey


# ── transitions ─────────────────────────────────────────────────────────────


def transition_to_dict(transition: JourneyTransition) -> dict:
    return {
        "id": transition.id,
        "from_journey": transition.from_journey_id,
        "from_name": transition.from_journey.name,
        "to_journey": transition.to_journey_id,
        "to_name": transition.to_journey.name,
        "on": transition.on,
        "priority": transition.priority,
        "match": transition.match,
        "checks": transition.checks or [],
    }


def validate_transition(process_agent, data, instance=None) -> tuple:
    errors, cleaned = {}, {}
    data = data if isinstance(data, dict) else {}

    for field in ("from_journey", "to_journey"):
        if instance is None or field in data:
            raw = data.get(field)
            journey = process_agent.bot_journeys.filter(pk=raw).first() if str(raw).isdigit() else None
            if journey is None:
                errors[field] = "choose one of this agent's stages"
            else:
                cleaned[field] = journey

    source = cleaned.get("from_journey") or (instance.from_journey if instance is not None else None)
    target = cleaned.get("to_journey") or (instance.to_journey if instance is not None else None)
    if source is not None and target is not None and source.pk == target.pk:
        errors["to_journey"] = "a stage can't hand off to itself"

    if "on" in data:
        if data["on"] not in (JourneyTransition.ON_COMPLETED, JourneyTransition.ON_RETRIES_EXHAUSTED):
            errors["on"] = "on must be completed or retries_exhausted"
        else:
            cleaned["on"] = data["on"]

    if "match" in data:
        if data["match"] not in ("all", "any"):
            errors["match"] = "match must be all or any"
        else:
            cleaned["match"] = data["match"]

    if "checks" in data:
        checks, problem = clean_checks(data["checks"])
        if problem:
            errors["checks"] = problem
        else:
            cleaned["checks"] = checks

    if "priority" in data:
        try:
            cleaned["priority"] = int(data["priority"])
        except (TypeError, ValueError):
            errors["priority"] = "priority must be a whole number"

    return cleaned, errors


def next_transition_priority(process_agent) -> int:
    last = process_agent.journey_transitions.order_by("-priority").values_list("priority", flat=True).first()
    return 0 if last is None else last + 1

