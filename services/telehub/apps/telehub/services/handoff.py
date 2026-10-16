"""
Hand-off between the voicebot stages (BotJourneys) of one process agent: a
finished call's results become the starting point of the lead's next stage.

Each stage of a lead is its own Execution, linked to the one before it by
`parent_execution`. The next stage's Execution is created pending with the
parent's variables (minus the identifiers of the finished call itself), so
the next bot is dispatched with that context as its params, and its own call
record, QA and WhatsApp send never collide with the previous stage's.

Two triggers, both configured as JourneyTransitions out of the current stage:

  completed          a call's result has arrived and the lead is not going to
                     be retried or called back (outcome_routing /
                     inbound.record_inbound_call call run_completed_transitions)
  retries_exhausted  the stage gave up on a lead that never connected. If the
                     stage has any such transition they alone decide; if it
                     has none, the lead falls through to the next stage by
                     `order` (the behavior from before transitions existed).

Safety: a lead is handed off at most once per Execution (a resent webhook
can't fork it), never back into a stage it already went through, and at most
MAX_CHAIN_LENGTH stages deep. Like the rest of services/, nothing raises into
the webhook handler or the scheduler.
"""
import logging

from django.db import transaction
from django.utils import timezone

from ..models import Execution, ExecutionEvent, JourneyTransition
from . import conditions
from .phone import normalize_digits

logger = logging.getLogger(__name__)

MAX_CHAIN_LENGTH = 6
NODE_NAME_LEAD_RECEIVED = "Lead Received"

# Describe the call that just finished, not the lead — the next stage's own call
# will bring its own values for these.
PER_CALL_KEYS = frozenset(
    {
        "session_id",
        "dlr_id",
        "recording_url",
        "call_duration",
        "call_start_time",
        "date",
        "outcome",
        "contact_no",
        "did_mismatch",
    }
)


def _ancestry(execution) -> list:
    """The Execution and its parents, newest first (bounded, in case of a bad cycle)."""
    chain, current = [], execution
    while current is not None and len(chain) <= MAX_CHAIN_LENGTH + 1:
        chain.append(current)
        current = current.parent_execution
    return chain


def pick_transition(execution, on):
    """First JourneyTransition out of the execution's current stage, of kind `on`, whose checks pass."""
    journey = execution.current_bot_journey
    if journey is None:
        return None
    variables = execution.variables or {}
    transitions = execution.process_agent.journey_transitions.filter(from_journey=journey, on=on).select_related(
        "to_journey"
    )
    for transition in transitions:
        if conditions.evaluate(transition.match, transition.checks, variables):
            return transition
    return None


def _dialable(raw) -> str:
    """
    A number as the outbound API wants it. Voicebot payloads give numbers with the
    country code but no "+" ("916359724704"); a 10-digit number is left for the
    dispatcher, which adds +91 itself.
    """
    text = str(raw).strip()
    if text.startswith("+"):
        return text
    digits = "".join(ch for ch in text if ch.isdigit())
    return f"+{digits}" if len(digits) > 10 else text


def _event(execution, event_type, payload):
    try:
        ExecutionEvent.objects.create(execution=execution, event_type=event_type, payload=payload)
    except Exception:
        pass


def hand_off(execution, to_journey, reason: str):
    """
    Creates the next stage's Execution for `execution`'s lead. Returns it, or
    None when blocked (already handed off, a loop, too deep, no phone number).
    """
    if execution.children.exists():
        return None

    chain = _ancestry(execution)
    if to_journey.id in {e.current_bot_journey_id for e in chain}:
        _event(execution, "handoff_blocked", {"reason": "loop", "to_journey": to_journey.name})
        return None
    if len(chain) >= MAX_CHAIN_LENGTH:
        _event(execution, "handoff_blocked", {"reason": "too many stages", "to_journey": to_journey.name})
        return None

    variables = {k: v for k, v in (execution.variables or {}).items() if k not in PER_CALL_KEYS}
    # Inbound calls only carry caller_number; outbound dispatch reads to_number.
    number = variables.get("to_number") or variables.get("caller_number")
    if not normalize_digits(number):
        _event(execution, "handoff_blocked", {"reason": "no phone number", "to_journey": to_journey.name})
        return None
    variables["to_number"] = _dialable(number)

    with transaction.atomic():
        child = Execution.objects.create(
            organization=execution.organization,
            process_agent=execution.process_agent,
            parent_execution=execution,
            lead_id=execution.lead_id,
            campaign_id=execution.campaign_id,
            status="pending",
            current_node=NODE_NAME_LEAD_RECEIVED,
            current_bot_journey=to_journey,
            variables=variables,
            attempt_count=0,
            next_execution=timezone.now(),
        )
        _event(
            execution,
            "handed_off",
            {"reason": reason, "to_journey": to_journey.name, "execution_id": child.id},
        )
        _event(child, "created_by_handoff", {"from_execution_id": execution.id, "reason": reason})
    return child


def run_completed_transitions(execution):
    """A call's result arrived and the lead is done with this stage: follow a matching transition, if any."""
    try:
        transition = pick_transition(execution, JourneyTransition.ON_COMPLETED)
        if transition is None:
            return None
        return hand_off(execution, transition.to_journey, JourneyTransition.ON_COMPLETED)
    except Exception:
        logger.exception("handoff failed for execution=%s", getattr(execution, "id", None))
        return None


def advance_after_retries_exhausted(execution) -> bool:
    """
    The stage gave up on this lead. Follows a `retries_exhausted` transition if
    the stage has any; otherwise falls back to the next stage by `order` (and,
    for a legacy execution with no recorded stage, to the second stage if the
    agent has more than one). Returns True if a next-stage Execution was created.
    """
    try:
        process_agent = execution.process_agent
        current = execution.current_bot_journey

        if current is not None and process_agent.journey_transitions.filter(
            from_journey=current, on=JourneyTransition.ON_RETRIES_EXHAUSTED
        ).exists():
            transition = pick_transition(execution, JourneyTransition.ON_RETRIES_EXHAUSTED)
            target = transition.to_journey if transition else None
        elif current is not None:
            target = process_agent.bot_journeys.filter(order__gt=current.order).order_by("order").first()
        else:
            first = process_agent.bot_journeys.order_by("order").first()
            target = first if process_agent.bot_journeys.count() > 1 else None

        if target is None:
            return False
        if current is None:
            # A legacy execution never recorded its stage; pin it so the chain check is meaningful.
            execution.current_bot_journey = process_agent.bot_journeys.order_by("order", "id").first()
            execution.save(update_fields=["current_bot_journey"])
            if execution.current_bot_journey_id == target.id:
                target = process_agent.bot_journeys.order_by("order", "id")[1]
        child = hand_off(execution, target, JourneyTransition.ON_RETRIES_EXHAUSTED)
        if child is not None:
            # Kept for the timeline the Runs tab already knows how to show.
            _event(
                execution,
                "journey_advanced",
                {
                    "from_journey": current.name if current else None,
                    "to_journey": target.name,
                    "execution_id": child.id,
                },
            )
        return child is not None
    except Exception:
        logger.exception("advance after retries failed for execution=%s", getattr(execution, "id", None))
        return False
