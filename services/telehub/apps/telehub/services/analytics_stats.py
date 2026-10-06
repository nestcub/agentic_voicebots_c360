"""
Overview tab "Performance" stat cards (dashboard/app/process-agents/[id]/page.tsx)
— computed from Execution/QAResult rows already in the DB, no new tracking
needed. "Connected" mirrors the same heuristic a real, working Chat360
webhook integration (voicebot_webhook.php) uses to decide a call was actually
answered: a positive duration, a recording, or an outcome in a known-answered
set — Execution.duration (the model column) is never populated by
outcome_routing.py, so this reads the webhook-supplied duration out of
execution.variables instead.
"""
from ..models import QAResult

CONNECTED_OUTCOMES = {"answered", "completed", "success"}


def _variable_duration(execution) -> float | None:
    variables = execution.variables or {}
    for key in ("duration", "call_duration"):
        raw = variables.get(key)
        if raw in (None, ""):
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def _is_connected(execution) -> bool:
    variables = execution.variables or {}
    duration = _variable_duration(execution)
    if duration is not None and duration > 0:
        return True
    if variables.get("recording_url"):
        return True
    outcome = str(variables.get("outcome", "")).strip().lower()
    return outcome in CONNECTED_OUTCOMES


def compute_process_agent_stats(process_agent) -> dict:
    """
    Returns {"calls", "connected", "avg_duration_seconds", "qa_score",
    "hot_leads", "callback_requests"}. Every field is None when there's no
    data to compute it from (0 calls, or no QAResult ever scored a lead/
    compliance number) rather than a fabricated 0 — the frontend renders
    None as "—", same as an unscored process today.
    """
    executions = list(process_agent.executions.all())
    calls = len(executions)

    connected_executions = [e for e in executions if _is_connected(e)]
    connected = len(connected_executions)

    durations = [d for e in connected_executions if (d := _variable_duration(e)) is not None]
    avg_duration_seconds = sum(durations) / len(durations) if durations else None

    qa_results = QAResult.objects.filter(execution__process_agent=process_agent)
    scored = [qa.lead_score for qa in qa_results if qa.lead_score is not None]
    qa_score = sum(scored) / len(scored) if scored else None
    hot_leads = qa_results.filter(hot_lead=True).count()

    callback_requests = process_agent.executions.filter(
        status="callback_scheduled"
    ).count()

    return {
        "calls": calls,
        "connected": connected,
        "avg_duration_seconds": avg_duration_seconds,
        "qa_score": qa_score,
        "hot_leads": hot_leads,
        "callback_requests": callback_requests,
    }
