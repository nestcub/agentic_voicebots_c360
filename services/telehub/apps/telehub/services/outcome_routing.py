"""
Phase D: routes a webhook-delivered call outcome to Completed's four branches.
Called once an Execution's webhook payload has arrived (post-call outcome).
Merges the payload into execution.variables, moves current_node to "Completed",
then fires Completed's edges per journey.py's topology: QA and CRM Update
(condition="" edges) always run as side effects; Callback and Retry are the
two conditioned alternatives, with Callback taking priority since it's the
data-driven one (callback_schedule.schedule_callback evaluates the wizard's
own Callback conditions against execution.variables) — only if callback did
NOT fire do we fall back to checking payload["outcome"] against
FAILURE_OUTCOMES to decide whether to schedule a retry. Mirrors
dispatcher.py/callback_schedule.py's defensive style: this is invoked from a
webhook handler that must always ack 200, so it never raises.
"""
from ..models import Execution, ExecutionEvent, NodeInstance, QAResult
from . import callback_schedule, retry_backoff

NODE_NAME_COMPLETED = "Completed"
NODE_NAME_QA = "QA"
NODE_NAME_CRM_UPDATE = "CRM Update"

FAILURE_OUTCOMES = {"failed", "no_answer", "busy", "not_connected", "voicemail"}


def _get_node(execution: "Execution", name: str):
    try:
        return execution.process_agent.nodes.filter(name=name).first()
    except Exception:
        return None


def _run_qa(execution: "Execution", payload: dict) -> None:
    """
    Creates the (at most one) QAResult for this execution. Guards against the
    OneToOne IntegrityError on duplicate webhook deliveries by checking
    hasattr(execution, "qa_result") first and returning early if QA already ran.
    """
    try:
        if hasattr(execution, "qa_result"):
            return
        QAResult.objects.create(
            execution=execution,
            summary=str(payload.get("summary", "")),
            sentiment=str(payload.get("sentiment", "")),
            raw_result=payload,
        )
        ExecutionEvent.objects.create(
            execution=execution,
            node_instance=_get_node(execution, NODE_NAME_QA),
            event_type="qa_completed",
            payload={},
        )
    except Exception:
        return


def _run_crm_update(execution: "Execution") -> None:
    """
    Records a crm_update_triggered ExecutionEvent for the CRM Update node's
    configured integration_ids. No dedupe key exists for V1 — on a true
    duplicate webhook delivery this may log a second event, which is
    acceptable.
    """
    try:
        crm_node = _get_node(execution, NODE_NAME_CRM_UPDATE)
        integration_ids = (
            crm_node.config.get("integration_ids", []) if crm_node else []
        )
        ExecutionEvent.objects.create(
            execution=execution,
            node_instance=crm_node,
            event_type="crm_update_triggered",
            payload={"integration_ids": integration_ids},
        )
    except Exception:
        return


def route_webhook_outcome(execution: "Execution", payload: dict) -> None:
    """
    Called once an Execution's webhook payload has arrived (post-call outcome).
    Merges payload into execution.variables, moves it to Completed, then fires
    Completed's edges: QA and CRM Update ALWAYS run (condition="" edges — side
    effects, don't move current_node further); Callback and Retry are the two
    conditioned alternatives — Callback takes priority (data-driven: it fires
    only if callback_schedule.schedule_callback's own condition evaluation
    against execution.variables matches, using whatever conditions the wizard's
    Callback config declared — NOT a hardcoded label), and only if callback
    did NOT fire do we check payload.get("outcome") against FAILURE_OUTCOMES to
    decide whether to call retry_backoff.schedule_retry. Idempotent against
    duplicate webhook deliveries for the same execution (QA never creates a
    second QAResult; safe to call more than once without crashing, though CRM
    Update may log more than one ExecutionEvent on true duplicates — acceptable
    for V1, no dedupe key exists yet).
    """
    try:
        payload = payload if isinstance(payload, dict) else {}

        execution.variables = {**(execution.variables or {}), **payload}
        execution.current_node = NODE_NAME_COMPLETED
        execution.status = "completed"
        execution.save()

        ExecutionEvent.objects.create(
            execution=execution,
            node_instance=_get_node(execution, NODE_NAME_COMPLETED),
            event_type="call_completed",
            payload=payload,
        )

        _run_qa(execution, payload)
        _run_crm_update(execution)

        callback_fired = False
        try:
            callback_fired = callback_schedule.schedule_callback(execution)
        except Exception:
            callback_fired = False

        if not callback_fired:
            outcome = str(payload.get("outcome", "")).strip().lower()
            if outcome in FAILURE_OUTCOMES:
                try:
                    retry_backoff.schedule_retry(execution)
                except Exception:
                    pass
    except Exception:
        return
