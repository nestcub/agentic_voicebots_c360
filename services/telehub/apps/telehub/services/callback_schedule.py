"""
Schedules a callback for an Execution when any of the process agent's
"Callback" NodeInstance conditions match the execution's variables — see the
wizard's Business Rules > Callback section (dashboard/app/process-agents/new/page.tsx)
and docs/superpowers/plans/gpt_ai_hub_impl_plan.md "Callback" section for the
config shape: {conditions: [{variable, operator, value}], delay_minutes,
time_variable}. Mirrors dispatcher.py's defensive style: never raises,
missing/malformed config just means "no callback scheduled".
"""
from datetime import timedelta

from django.utils import timezone

from ..models import Execution, NodeInstance
from .callback_time import parse_call_back_time

NODE_NAME_CALLBACK = "Callback"

DEFAULT_DELAY_MINUTES = 30


def _get_callback_config(execution: "Execution") -> dict:
    """
    Defensively reads the Callback NodeInstance's config for this Execution's
    process_agent. Treat a missing node (or any lookup error) as an empty
    config rather than raising.
    """
    try:
        return execution.process_agent.nodes.get(name=NODE_NAME_CALLBACK).config or {}
    except NodeInstance.DoesNotExist:
        return {}
    except Exception:
        return {}


def _condition_matches(condition: dict, variables: dict) -> bool:
    """
    Evaluates a single {variable, operator, value} condition against
    execution.variables. Never raises: a condition with an unusable shape
    (missing keys, non-numeric operands for >/<) is simply treated as
    non-matching rather than blowing up the whole evaluation.
    """
    try:
        variable_name = condition.get("variable")
        operator = condition.get("operator")
        expected = condition.get("value")
    except Exception:
        return False

    if not variable_name or not operator:
        return False

    actual = variables.get(variable_name)

    if operator == "==":
        return str(actual) == str(expected)
    if operator == "!=":
        return str(actual) != str(expected)
    if operator == "contains":
        return str(expected) in str(actual if actual is not None else "")
    if operator in (">", "<"):
        try:
            actual_num = float(actual)
            expected_num = float(expected)
        except (TypeError, ValueError):
            return False
        return actual_num > expected_num if operator == ">" else actual_num < expected_num

    return False


def schedule_callback(execution: "Execution") -> bool:
    """
    If ANY of the Callback node's configured conditions match
    execution.variables: resolves the callback time via
    parse_call_back_time(execution.variables.get(config["time_variable"], ""));
    falls back to now() + timedelta(minutes=config.get("delay_minutes", 30))
    when that returns None. Sets next_execution to the resolved time, status
    = "callback_scheduled", saves, returns True. If no condition matches or
    the Callback node/config is missing: returns False, does not modify the
    execution.
    """
    config = _get_callback_config(execution)
    conditions = config.get("conditions") or []
    if not isinstance(conditions, list):
        return False

    variables = execution.variables or {}

    matched = any(
        isinstance(condition, dict) and _condition_matches(condition, variables)
        for condition in conditions
    )
    if not matched:
        return False

    time_variable = config.get("time_variable")
    raw_time = variables.get(time_variable, "") if time_variable else ""
    resolved_time = parse_call_back_time(raw_time)

    if resolved_time is None:
        delay_minutes = _coerce_positive_delay(config.get("delay_minutes"))
        resolved_time = timezone.now() + timedelta(minutes=delay_minutes)

    execution.next_execution = resolved_time
    execution.status = "callback_scheduled"
    execution.save()
    return True


def _coerce_positive_delay(value) -> float:
    try:
        coerced = float(value)
    except (TypeError, ValueError):
        return DEFAULT_DELAY_MINUTES
    return coerced if coerced > 0 else DEFAULT_DELAY_MINUTES
