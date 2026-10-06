"""
Two "should we act right now" gate checks read off a process agent's fixed
journey nodes: "Business Hours" (is `at` inside the configured working
window?) and "DND Check" (is this specific Execution suppressed?). Both
fail open on missing/malformed config — same defensive pattern as the rest
of this codebase's service modules (callback_time.py, dispatcher.py,
retry_backoff.py) — so a misconfigured or not-yet-set-up process agent never
silently blocks calls.
"""
from zoneinfo import ZoneInfo

from django.utils import timezone

from ..models import Execution
from .journey import journey_nodes

NODE_NAME_BUSINESS_HOURS = "Business Hours"
NODE_NAME_DND_CHECK = "DND Check"

_TRUTHY_STRINGS = {"true", "1", "yes"}


def _is_truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in _TRUTHY_STRINGS
    return bool(value)


def _get_node_config(execution: "Execution", node_name: str) -> dict:
    """
    Fail-open node config lookup: returns {} if the node doesn't exist on
    this execution's journey, or on any other error.
    """
    try:
        node = journey_nodes(execution).get(name=node_name)
        return node.config or {}
    except Exception:
        return {}


def is_within_business_hours(execution: "Execution", at=None) -> bool:
    """
    Reads the "Business Hours" NodeInstance config: {timezone, start, end,
    working_days} (working_days as a list of ISO weekday ints, 1=Monday..
    7=Sunday). `at` defaults to timezone.now(); converted to the configured
    timezone before comparing. Missing/invalid config = always within
    business hours (fail open). Scoped to execution.current_bot_journey (see
    journey_nodes) so multi-journey process agents resolve the right node.
    """
    config = _get_node_config(execution, NODE_NAME_BUSINESS_HOURS)

    tz_name = config.get("timezone")
    start_str = config.get("start")
    end_str = config.get("end")
    working_days = config.get("working_days")

    if not tz_name or not start_str or not end_str or not working_days:
        return True

    try:
        tz = ZoneInfo(tz_name)
        moment = (at or timezone.now()).astimezone(tz)

        start_hour, start_minute = (int(part) for part in start_str.split(":")[:2])
        end_hour, end_minute = (int(part) for part in end_str.split(":")[:2])

        if moment.isoweekday() not in working_days:
            return False

        start_minutes_of_day = start_hour * 60 + start_minute
        end_minutes_of_day = end_hour * 60 + end_minute
        moment_minutes_of_day = moment.hour * 60 + moment.minute

        return start_minutes_of_day <= moment_minutes_of_day <= end_minutes_of_day
    except Exception:
        return True


def is_suppressed_dnc(execution: "Execution") -> bool:
    """
    Reads the "DND Check" NodeInstance's config {enabled: bool} AND
    execution.variables.get("dnd") (a string, from the campaign CSV mapping
    — see services/campaign_launch.py; truthy values are "true"/"1"/"yes"
    case-insensitive). Returns True (suppressed) only if the DND Check
    node's config.enabled is truthy AND the execution's own dnd variable is
    truthy. Missing node/config = not suppressed (fail open).
    """
    try:
        config = _get_node_config(execution, NODE_NAME_DND_CHECK)
        if not _is_truthy(config.get("enabled")):
            return False

        variables = execution.variables or {}
        return _is_truthy(variables.get("dnd"))
    except Exception:
        return False
