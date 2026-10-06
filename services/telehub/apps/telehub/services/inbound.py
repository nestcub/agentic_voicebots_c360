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

from ..models import Execution
from . import outcome_routing

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
    The inbound payload carries no session_id, so a resend is recognised by
    the same caller_number + call_start_time. Without a call_start_time
    there's nothing reliable to dedupe on, so the call is always recorded.
    """
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
        execution = Execution.objects.create(
            process_agent=process_agent,
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
            variables={**payload, "to_number": caller_number},
            next_execution=None,
        )
        outcome_routing.record_completion(execution, payload)
        return execution
    except Exception:
        return None
