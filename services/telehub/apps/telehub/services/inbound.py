"""
Inbound voicebot calls: the customer dials the Chat360 bot, so there is no
pre-existing Execution for the post-call webhook to correlate to (that's the
outbound path in outcome_routing.find_execution_for_payload). Instead, the
webhook itself creates the Execution — already "completed", with the payload
as its variables — and runs Completed's QA/CRM Update side effects.

Callback/Retry are deliberately NOT run for inbound: both reschedule the
Execution for run_scheduler, which would dispatch an *outbound* call through a
bot that has no outbound api_url. The scheduler never touches these rows
(status "completed", next_execution NULL).

Fail-open like the rest of services/: called from a webhook handler that must
always ack 200, so nothing here raises.
"""
from django.utils import timezone

from ..models import Execution, ExecutionEvent
from . import handoff, numbers, omnichannel, outcome_routing

INBOUND_COMMUNICATION_TYPE = "voice_inbound"
INBOUND_CAMPAIGN_ID = "inbound"


def is_inbound_agent(process_agent) -> bool:
    """True if any of this agent's BotJourneys is wired to a voice_inbound VoiceBot."""
    try:
        return process_agent.bot_journeys.filter(
            voice_bot__communication_type=INBOUND_COMMUNICATION_TYPE
        ).exists()
    except Exception:
        return False


def normalize_payload(payload: dict) -> dict:
    """
    Chat360's variable names are written "@customer_name" in its UI — strip a
    leading "@" so they're stored (and shown/forwarded) as plain keys. Also
    unwraps single-item lists, which is what dict(QueryDict) yields for a
    form-encoded post.
    """
    normalized = {}
    for key, value in (payload or {}).items():
        if isinstance(value, list) and len(value) == 1:
            value = value[0]
        normalized[str(key).lstrip("@")] = value
    return normalized


def _is_duplicate(process_agent, payload: dict) -> bool:
    """
    A resend is recognised by session_id when the payload carries one (real
    inbound payloads do). Older payloads without it fall back to the same
    caller_number + call_start_time — a time with no date, so it can collide
    across days, which is why session_id is preferred. Without either there's
    nothing reliable to dedupe on, so the call is always recorded.
    """
    session_id = payload.get("session_id")
    if session_id:
        return process_agent.executions.filter(variables__session_id=session_id).exists()

    caller_number = payload.get("caller_number")
    call_start_time = payload.get("call_start_time")
    if not caller_number or not call_start_time:
        return False
    return process_agent.executions.filter(
        variables__caller_number=caller_number,
        variables__call_start_time=call_start_time,
    ).exists()


def _parse_duration(raw):
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def record_inbound_call(process_agent, payload: dict):
    """Creates the completed Execution for one inbound call. Returns it, or None if skipped/failed."""
    try:
        payload = normalize_payload(payload)
        if _is_duplicate(process_agent, payload):
            return None

        caller_number = str(payload.get("caller_number") or "")
        now = timezone.now()
        # Customers dial a specific DID; one that isn't among this agent's inbound
        # numbers is still recorded, but flagged so rules and the Calls tab can see it.
        callee_check = numbers.check_callee(process_agent, payload)
        extra_variables = {"did_mismatch": True} if callee_check["mismatch"] else {}
        execution = Execution.objects.create(
            process_agent=process_agent,
            organization=process_agent.organization,
            current_bot_journey=process_agent.bot_journeys.order_by("order", "id").first(),
            lead_id=caller_number or "inbound",
            campaign_id=INBOUND_CAMPAIGN_ID,
            status="completed",
            current_node=outcome_routing.NODE_NAME_COMPLETED,
            started_at=now,
            ended_at=now,
            duration=_parse_duration(payload.get("call_duration")),
            # to_number mirrors the outbound convention so anything that
            # re-contacts the lead (WhatsApp, a follow-up dial) finds it there.
            variables={**payload, **extra_variables, "to_number": caller_number},
            next_execution=None,
        )
        if callee_check["mismatch"]:
            ExecutionEvent.objects.create(
                execution=execution,
                event_type="did_mismatch",
                payload={"callee_number": callee_check["callee"], "expected": callee_check["expected"]},
            )
        outcome_routing.record_completion(execution, payload)
        omnichannel.on_call_completed(execution)
        handoff.run_completed_transitions(execution)
        return execution
    except Exception:
        return None
