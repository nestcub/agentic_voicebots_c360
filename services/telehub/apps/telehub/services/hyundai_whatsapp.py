"""
Hyundai POC WhatsApp automation — see docs/hyundai-whatsapp-automation-plan.md.

Hyundai-specific on purpose: the template rules below are hardcoded for the
Hyundai inbound agent, not a general rule engine (that comes later). An agent
opts in with OmnichannelConfig.auto_send; each template key ("T1"/"T2"/"T3")
has its own pasted curl in OmnichannelConfig.whatsapp_curls.

When an inbound call completes, pick_template() chooses at most one template
(first match wins):

  1. T1 — full appointment captured (date, time and place all present)
  2. T2 — caller said they'll call back (callback_status == "required")
  3. T1 — partial capture: any main variable present; empty T1 params are sent as FILL_TEXT
  4. T3 — none of the main variables captured

on_call_completed() records a pending WhatsAppSend; run_scheduler's tick sends
it via process_due_sends(), retrying network errors / 5xx up to
len(RETRY_DELAYS_MINUTES) times. Like the rest of services/, nothing here
raises into the webhook handler or the scheduler loop.
"""
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import WhatsAppSend
from . import whatsapp

logger = logging.getLogger(__name__)

TEMPLATE_T1 = "T1"
TEMPLATE_T2 = "T2"
TEMPLATE_T3 = "T3"
TEMPLATE_KEYS = (TEMPLATE_T1, TEMPLATE_T2, TEMPLATE_T3)

# T1's variable params — also what "nothing captured" (T3) is judged on.
MAIN_VARIABLES = ("customer_name", "model_name", "appointment_place", "appointment_date", "appointment_time")
APPOINTMENT_VARIABLES = ("appointment_date", "appointment_time", "appointment_place")

# Sent in place of an empty T1 param (partial captures).
FILL_TEXT = "unspecified"

# Newer voicebot payloads send the model as model_of_interest; read it as
# model_name when model_name itself is empty.
VARIABLE_FALLBACKS = {"model_name": "model_of_interest"}

# Wait before retry 1, 2, 3 of a transient failure; then the send is failed.
RETRY_DELAYS_MINUTES = (2, 10, 30)


def _is_empty(value) -> bool:
    return value is None or str(value).strip() == ""


def effective_variables(execution) -> dict:
    variables = dict(execution.variables or {})
    for name, fallback in VARIABLE_FALLBACKS.items():
        if _is_empty(variables.get(name)) and not _is_empty(variables.get(fallback)):
            variables[name] = variables[fallback]
    return variables


def is_test_call(variables: dict) -> bool:
    value = variables.get("is_test")
    return value is True or str(value).strip().lower() in ("true", "1", "yes")


def _callback_requested(variables: dict) -> bool:
    """T2's condition: the voicebot set callback_status to "required" (case/whitespace-insensitive)."""
    return str(variables.get("callback_status") or "").strip().lower() == "required"


def pick_template(execution):
    """The template the rules choose for this call ("T1"/"T2"/"T3"); never None for a completed call."""
    variables = effective_variables(execution)
    if all(not _is_empty(variables.get(name)) for name in APPOINTMENT_VARIABLES):
        return TEMPLATE_T1
    if _callback_requested(variables):
        return TEMPLATE_T2
    if any(not _is_empty(variables.get(name)) for name in MAIN_VARIABLES):
        return TEMPLATE_T1
    return TEMPLATE_T3


def _config(process_agent):
    return getattr(process_agent, "omnichannel", None)


def template_curl(process_agent, template_key: str) -> str:
    """This agent's curl for a template key; T1 falls back to the pre-POC single whatsapp_curl."""
    config = _config(process_agent)
    if config is None:
        return ""
    curl = (config.whatsapp_curls or {}).get(template_key) or ""
    if not curl.strip() and template_key == TEMPLATE_T1:
        curl = config.whatsapp_curl or ""
    return curl


def _missing_fill(template_key: str):
    return FILL_TEXT if template_key == TEMPLATE_T1 else None


def preview(execution, template_key: str) -> dict:
    result = whatsapp.preview(
        execution,
        template_curl(execution.process_agent, template_key),
        _missing_fill(template_key),
        effective_variables(execution),
    )
    result["template_key"] = template_key
    return result


def _send(execution, template_key: str) -> dict:
    return whatsapp.send_whatsapp(
        execution,
        template_curl(execution.process_agent, template_key),
        _missing_fill(template_key),
        effective_variables(execution),
        template_key=template_key,
    )


def send_manual(execution, template_key: str) -> dict:
    """The Calls tab's Send button: sends now, synchronously, and records a manual WhatsAppSend."""
    result = _send(execution, template_key)
    try:
        WhatsAppSend.objects.create(
            execution=execution,
            template_key=template_key,
            trigger=WhatsAppSend.TRIGGER_MANUAL,
            status=WhatsAppSend.STATUS_SENT if result["success"] else WhatsAppSend.STATUS_FAILED,
            attempts=1,
            last_error=result["error"] or "",
            sent_at=timezone.now() if result["success"] else None,
        )
    except Exception:
        logger.exception("could not record manual WhatsAppSend for execution=%s", execution.id)
    result["template_key"] = template_key
    return result


def on_call_completed(execution) -> None:
    """
    Queues this call's automatic message if the agent has auto_send on. The
    row is "skipped" (with the reason) for a test call or a template with no
    curl configured, so the Calls tab shows why nothing went out. A second
    call for the same Execution (a resent webhook) hits the unique constraint
    and is ignored.
    """
    try:
        config = _config(execution.process_agent)
        if config is None or not config.auto_send:
            return

        template_key = pick_template(execution)
        status, reason = WhatsAppSend.STATUS_PENDING, ""
        if is_test_call(execution.variables or {}):
            status, reason = WhatsAppSend.STATUS_SKIPPED, "test call"
        elif not template_curl(execution.process_agent, template_key).strip():
            status, reason = WhatsAppSend.STATUS_SKIPPED, f"{template_key} not configured"

        with transaction.atomic():
            WhatsAppSend.objects.create(
                execution=execution,
                template_key=template_key,
                trigger=WhatsAppSend.TRIGGER_AUTO,
                status=status,
                last_error=reason,
                next_attempt_at=timezone.now() if status == WhatsAppSend.STATUS_PENDING else None,
            )
    except IntegrityError:
        return
    except Exception:
        logger.exception("could not queue WhatsApp for execution=%s", execution.id)


def process_due_sends(now=None) -> int:
    """run_scheduler step: sends every pending automatic WhatsAppSend that's due. Returns how many were attempted."""
    now = now or timezone.now()
    try:
        due = list(
            WhatsAppSend.objects.filter(
                trigger=WhatsAppSend.TRIGGER_AUTO,
                status=WhatsAppSend.STATUS_PENDING,
                next_attempt_at__lte=now,
            )
            .select_related("execution__process_agent__omnichannel")
            .order_by("next_attempt_at")
        )
    except Exception:
        # e.g. the migration isn't applied yet — never take outbound dispatch down with it.
        logger.exception("could not load due WhatsApp sends")
        return 0
    attempted = 0
    for send in due:
        try:
            result = _send(send.execution, send.template_key)
            send.attempts += 1
            attempted += 1
            if result["success"]:
                send.status = WhatsAppSend.STATUS_SENT
                send.sent_at = timezone.now()
                send.next_attempt_at = None
                send.last_error = ""
            elif result["retryable"] and send.attempts <= len(RETRY_DELAYS_MINUTES):
                send.next_attempt_at = timezone.now() + timedelta(
                    minutes=RETRY_DELAYS_MINUTES[send.attempts - 1]
                )
                send.last_error = result["error"] or ""
            else:
                send.status = WhatsAppSend.STATUS_FAILED
                send.next_attempt_at = None
                send.last_error = result["error"] or ""
            send.save()
        except Exception:
            logger.exception("WhatsApp send %s crashed", send.id)
    return attempted
