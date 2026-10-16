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
import re

from ..models import Execution, ExecutionEvent, QAResult
from . import callback_schedule, handoff, retry_backoff
from .journey import journey_nodes

FAILURE_OUTCOMES = {"failed", "no_answer", "busy", "not_connected", "voicemail"}

NODE_NAME_COMPLETED = "Completed"
NODE_NAME_QA = "QA"
NODE_NAME_CRM_UPDATE = "CRM Update"
NODE_NAME_LEAD_RECEIVED = "Lead Received"


def _get_node(execution: "Execution", node_name: str):
    """Fail-open: None if the node doesn't exist for this execution's journey."""
    try:
        return journey_nodes(execution).get(name=node_name)
    except Exception:
        return None


def _normalize_phone(raw) -> str:
    """
    Digits-only, with a leading India country code ("91") stripped when the
    result is longer than a bare 10-digit number — mirrors the normalization
    a real, working Chat360 voicebot webhook (voicebot_webhook.php, a live
    client integration) uses to match an inbound contact_no back to a lead.
    Applied to both sides of a comparison (the webhook payload's contact_no
    and an Execution's stored to_number) so "+919876543210", "919876543210"
    and "9876543210" all normalize to the same "9876543210".
    """
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) > 10 and digits.startswith("91"):
        digits = digits[2:]
    return digits


def find_execution_for_payload(process_agent, payload: dict):
    """
    Resolves a webhook payload to the Execution it belongs to. Chat360's real
    post-call webhook for this voicebot integration never includes a dlr_id
    (confirmed against voicebot_webhook.php) — it only ever sends contact_no
    — so dlr_id is tried first (cheap, forward-compatible) and phone number is
    the actual correlation path: the most recently created, not-yet-completed
    Execution for this process_agent whose variables["to_number"] normalizes
    to the same digits as payload["contact_no"]. Returns None (never raises)
    if nothing matches, mirroring the rest of this module's fail-open style.
    """
    try:
        dlr_id = payload.get("dlr_id")
        if dlr_id:
            execution = process_agent.executions.filter(pk=dlr_id).first()
            if execution is not None:
                return execution

        contact_no = _normalize_phone(payload.get("contact_no"))
        if not contact_no:
            return None

        candidates = process_agent.executions.exclude(status="completed").order_by(
            "-created_at"
        )
        for execution in candidates:
            if _normalize_phone(execution.variables.get("to_number")) == contact_no:
                return execution
        return None
    except Exception:
        return None


def _advance_to_next_journey(execution: "Execution") -> bool:
    """
    Called when the current BotJourney's Retry budget is exhausted
    (retry_backoff.schedule_retry returned False, having already set
    execution.status="failed"). Hands the lead to the next stage as a new
    Execution (services/handoff.py): through a "retries_exhausted"
    JourneyTransition if the stage has one, otherwise to the next stage by
    `order` - e.g. a Sales stage's unconverted leads flowing into a Follow-up
    stage with a different VoiceBot. Fail-open: no next stage (the common,
    single-journey case) leaves the execution "failed" exactly as before.
    """
    return handoff.advance_after_retries_exhausted(execution)


def _missing_variables(execution: "Execution") -> list:
    """
    The process agent's Variable keys ticked for QA (Variable.use_in_qa)
    whose value is absent or empty in execution.variables — which at the
    point this is called already has the webhook payload merged in (see
    route_webhook_outcome). Fail-open: any lookup error yields [].
    """
    try:
        expected_keys = list(
            execution.process_agent.variables.filter(use_in_qa=True).values_list("key", flat=True)
        )
        variables = execution.variables or {}
        return [key for key in expected_keys if variables.get(key) in (None, "")]
    except Exception:
        return []


def _run_qa(execution: "Execution", payload: dict) -> None:
    """
    Creates the (at most one) QAResult for this execution. Guards against the
    OneToOne IntegrityError on duplicate webhook deliveries by checking
    hasattr(execution, "qa_result") first and returning early if QA already ran.
    missing_variables is only computed when the wizard's QA step turned that
    check on (QA NodeInstance.config["missing_variables"]) — otherwise it's
    left as [].
    """
    try:
        if hasattr(execution, "qa_result"):
            return
        qa_node = _get_node(execution, NODE_NAME_QA)
        qa_config = qa_node.config if qa_node else {}
        missing_variables = _missing_variables(execution) if qa_config.get("missing_variables") else []
        QAResult.objects.create(
            execution=execution,
            summary=str(payload.get("summary", "")),
            # Inbound bots report it as call_sentiment.
            sentiment=str(payload.get("sentiment") or payload.get("call_sentiment") or ""),
            missing_variables=missing_variables,
            raw_result=payload,
        )
        ExecutionEvent.objects.create(
            execution=execution,
            node_instance=qa_node,
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


def record_completion(execution: "Execution", payload: dict) -> None:
    """
    Completed's unconditional edges: logs call_completed, then QA and CRM
    Update. Shared with inbound.record_inbound_call, which creates its
    Execution already-completed and skips the Callback/Retry branches.
    """
    try:
        ExecutionEvent.objects.create(
            execution=execution,
            node_instance=_get_node(execution, NODE_NAME_COMPLETED),
            event_type="call_completed",
            payload=payload,
        )
    except Exception:
        pass
    _run_qa(execution, payload)
    _run_crm_update(execution)


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

        incoming_session_id = payload.get("session_id")
        if (
            execution.status == "completed"
            and incoming_session_id
            and (execution.variables or {}).get("session_id") == incoming_session_id
        ):
            # Chat360 can resend the same call's webhook — this execution already
            # completed off this exact session_id, so re-running QA/CRM/Retry
            # would duplicate side effects rather than reflect anything new.
            return

        execution.variables = {**(execution.variables or {}), **payload}
        execution.current_node = "Completed"
        execution.status = "completed"
        execution.save()

        record_completion(execution, payload)

        callback_fired = False
        try:
            callback_fired = callback_schedule.schedule_callback(execution)
        except Exception:
            callback_fired = False

        if not callback_fired:
            outcome = str(payload.get("outcome", "")).strip().lower()
            if outcome in FAILURE_OUTCOMES:
                try:
                    retried = retry_backoff.schedule_retry(execution)
                    if not retried:
                        # Retry budget exhausted (status is now "failed") —
                        # see if this process agent has a next journey to
                        # advance the lead into (e.g. Sales -> Follow-up).
                        _advance_to_next_journey(execution)
                except Exception:
                    pass
            else:
                # The call produced a result and nothing is being retried or
                # called back: this stage is done with the lead, so follow a
                # matching "completed" transition into the next stage.
                handoff.run_completed_transitions(execution)
    except Exception:
        return
