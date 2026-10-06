"""
Schedules (or exhausts) a retry for a failed Execution, per the process
agent's "Retry" NodeInstance config (attempts, interval_minutes, strategy:
"linear"|"exponential" — set via the wizard's Business Rules > Retry section,
see dashboard/app/process-agents/new/page.tsx). Mirrors dispatcher.py's
defensive style: never raises, missing/malformed config always falls back to
sane defaults rather than blowing up a later scheduler that calls this
per-Execution.
"""
from datetime import timedelta

from django.utils import timezone

from ..models import Execution
from .journey import journey_nodes

NODE_NAME_RETRY = "Retry"
DEFAULT_ATTEMPTS = 3
DEFAULT_INTERVAL_MINUTES = 15
DEFAULT_STRATEGY = "linear"


def _get_retry_config(execution: "Execution") -> dict:
    """Fail-open: {} if the Retry node doesn't exist for this journey."""
    try:
        node = journey_nodes(execution).get(name=NODE_NAME_RETRY)
        return node.config or {}
    except Exception:
        return {}


def _coerce_positive_int(value, default: int) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return default
    return coerced if coerced > 0 else default


def schedule_retry(execution: "Execution") -> bool:
    """
    Reads the "Retry" NodeInstance config. If execution.attempt_count <
    attempts: sets next_execution = now() + backoff (interval_minutes for
    linear; interval_minutes * (2 ** (attempt_count - 1)) for exponential,
    minimum one attempt's worth), status = "retry_scheduled", saves, returns
    True. If attempts are exhausted: status = "failed", next_execution =
    None, saves, returns False. Missing Retry node or missing config keys
    fall back to attempts=3, interval_minutes=15, strategy="linear" — never
    raises on missing/malformed config.
    """
    config = _get_retry_config(execution)

    attempts = _coerce_positive_int(config.get("attempts"), DEFAULT_ATTEMPTS)
    interval_minutes = _coerce_positive_int(
        config.get("interval_minutes"), DEFAULT_INTERVAL_MINUTES
    )
    strategy = config.get("strategy") or DEFAULT_STRATEGY
    if strategy not in ("linear", "exponential"):
        strategy = DEFAULT_STRATEGY

    if execution.attempt_count >= attempts:
        execution.status = "failed"
        execution.next_execution = None
        execution.save()
        return False

    if strategy == "exponential":
        # attempt_count-1 with a floor of 0 so the very first retry (attempt_count
        # may be 0 or 1 depending on the caller) is always at least one interval.
        exponent = max(execution.attempt_count - 1, 0)
        backoff_minutes = interval_minutes * (2 ** exponent)
    else:
        backoff_minutes = interval_minutes

    execution.next_execution = timezone.now() + timedelta(minutes=backoff_minutes)
    execution.status = "retry_scheduled"
    execution.save()
    return True
