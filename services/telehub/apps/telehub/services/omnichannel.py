"""
Post-call WhatsApp messaging, driven by data: an agent's ChannelTemplates
(pasted Chat360 curls) and ChannelRules ("if these checks pass on the call's
variables, send that template — or skip"). Replaces the Hyundai-only
hyundai_whatsapp.py, whose T1/T2/T3 logic now lives in the default rows
written by omnichannel_seed.py.

When a call completes, on_call_completed() evaluates the agent's rules in
priority order (first match wins) and records a pending WhatsAppSend —
"skipped", with the reason, for a skip rule or a template with no curl, so the
Calls tab shows why nothing went out. run_scheduler's tick sends pending rows
via process_due_sends(), retrying network errors / 5xx up to
len(RETRY_DELAYS_MINUTES) times. Like the rest of services/, nothing here
raises into the webhook handler or the scheduler loop.

An agent opts in with OmnichannelConfig.auto_send.
"""
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import ChannelRule, ChannelTemplate, ExecutionEvent, WhatsAppSend
from . import conditions, omnichannel_seed, whatsapp

logger = logging.getLogger(__name__)

# Wait before retry 1, 2, 3 of a transient failure; then the send is failed.
RETRY_DELAYS_MINUTES = (2, 10, 30)


# ── templates ──────────────────────────────────────────────────────────────


def _config(process_agent):
    return getattr(process_agent, "omnichannel", None)


def active_templates(process_agent):
    return process_agent.channel_templates.filter(is_active=True)


def template_names(process_agent) -> list:
    """Names of this agent's active templates — the valid values for a manual send's template_key."""
    return list(active_templates(process_agent).values_list("name", flat=True))


def get_template(process_agent, template_key):
    if not template_key:
        return None
    return active_templates(process_agent).filter(name=template_key).first()


def template_curl(process_agent, template_key: str) -> str:
    template = get_template(process_agent, template_key)
    return template.curl if template is not None else ""


def _missing_fill(template):
    fill = template.missing_fill if template is not None else ""
    return fill or None


# ── variables ──────────────────────────────────────────────────────────────


def effective_variables(execution) -> dict:
    """
    execution.variables with templates' param_map fallbacks applied: an entry
    {"variable": "model_name", "fallback": "model_of_interest"} fills an empty
    model_name from model_of_interest. Applied before rules run, so rules and
    templates see the same values.
    """
    variables = dict(execution.variables or {})
    try:
        for template in active_templates(execution.process_agent):
            for entry in (template.param_map or {}).values():
                if not isinstance(entry, dict):
                    continue
                name, fallback = entry.get("variable"), entry.get("fallback")
                if name and fallback and conditions.is_blank(variables.get(name)) and not conditions.is_blank(
                    variables.get(fallback)
                ):
                    variables[name] = variables[fallback]
    except Exception:
        logger.exception("could not apply template fallbacks for execution=%s", getattr(execution, "id", None))
    return variables


# ── rules ──────────────────────────────────────────────────────────────────


def pick_rule(execution):
    """The first ChannelRule (by priority) whose checks pass for this call, or None."""
    variables = effective_variables(execution)
    rules = execution.process_agent.channel_rules.select_related("template").order_by("priority", "id")
    for rule in rules:
        if conditions.evaluate(rule.match, rule.checks, variables):
            return rule
    return None


def pick_template(execution):
    """Name of the template the rules choose to send, or None (a skip rule won, or nothing matched)."""
    rule = pick_rule(execution)
    if rule is None or rule.action != ChannelRule.ACTION_SEND or rule.template is None:
        return None
    return rule.template.name


def sync_from_legacy_config(config) -> None:
    """
    Brings an OmnichannelConfig's legacy T1/T2/T3 curls across as
    ChannelTemplates (plus the default Hyundai rules when the agent has none).
    Does nothing for a config with no legacy curl at all: an agent set up
    through the template editor must not be handed Hyundai's rules. Never raises.
    """
    try:
        curls = omnichannel_seed.legacy_curls(config)
        if not any(curl.strip() for curl in curls.values()):
            return
        omnichannel_seed.sync_agent(ChannelTemplate, ChannelRule, config.process_agent, curls)
    except Exception:
        logger.exception("could not sync channel templates for agent=%s", config.process_agent_id)


# ── sending ────────────────────────────────────────────────────────────────


def preview(execution, template_key) -> dict:
    template = get_template(execution.process_agent, template_key)
    result = whatsapp.preview(
        execution,
        template.curl if template else "",
        _missing_fill(template),
        effective_variables(execution),
        template.param_map if template else None,
    )
    result["template_key"] = template_key
    return result


def _send(execution, template_key) -> dict:
    template = get_template(execution.process_agent, template_key)
    return whatsapp.send_whatsapp(
        execution,
        template.curl if template else "",
        _missing_fill(template),
        effective_variables(execution),
        template_key=template_key or "",
        param_map=template.param_map if template else None,
    )


def send_manual(execution, template_key) -> dict:
    """The Calls tab's Send button: sends now, synchronously, and records a manual WhatsAppSend."""
    result = _send(execution, template_key)
    try:
        send = WhatsAppSend(
            execution=execution,
            template_key=template_key or "",
            template=get_template(execution.process_agent, template_key),
            trigger=WhatsAppSend.TRIGGER_MANUAL,
        )
        _apply_result(send, result)
        send.save()
        result["send_id"] = send.id
    except Exception:
        logger.exception("could not record manual WhatsAppSend for execution=%s", execution.id)
    result["template_key"] = template_key
    return result


def _apply_result(send, result) -> None:
    """
    Records one delivery attempt's outcome on a WhatsAppSend (not saved):
      success      -> sent
      blocked      -> blocked, with the variables to fill in `missing` (not an
                      attempt: nothing was tried, so it doesn't use up a retry)
      5xx/network  -> pending again with a growing delay, for automatic sends
                      only (manual sends are one-shot), until the retries run out
      anything else-> failed
    """
    if result.get("blocked"):
        send.status = WhatsAppSend.STATUS_BLOCKED
        send.missing = result.get("missing") or []
        send.next_attempt_at = None
        send.last_error = result["error"] or ""
        return

    send.attempts += 1
    send.missing = []
    if result["success"]:
        send.status = WhatsAppSend.STATUS_SENT
        send.sent_at = timezone.now()
        send.next_attempt_at = None
        send.last_error = ""
    elif (
        result["retryable"]
        and send.trigger == WhatsAppSend.TRIGGER_AUTO
        and send.attempts <= len(RETRY_DELAYS_MINUTES)
    ):
        send.status = WhatsAppSend.STATUS_PENDING
        send.next_attempt_at = timezone.now() + timedelta(minutes=RETRY_DELAYS_MINUTES[send.attempts - 1])
        send.last_error = result["error"] or ""
    else:
        send.status = WhatsAppSend.STATUS_FAILED
        send.next_attempt_at = None
        send.last_error = result["error"] or ""


class FillError(ValueError):
    """The values handed to fill_blocked_send can't be applied (message is user-facing)."""


def fill_blocked_send(send, values) -> dict:
    """
    Unblocks a blocked WhatsAppSend: writes `values` ({variable name: text})
    into the call's variables — the same place the voicebot's own results
    live, recorded as a "whatsapp_filled" event — and tries the send again
    right away. Returns the delivery result. If other values are still
    missing the send stays blocked with the shorter list. Raises FillError for
    a send that isn't blocked, a name that isn't one of its missing variables,
    or a blank value.
    """
    if send.status != WhatsAppSend.STATUS_BLOCKED:
        raise FillError("this send is not blocked")
    if not isinstance(values, dict) or not values:
        raise FillError("values must be a non-empty object of variable name -> text")
    unknown = sorted(set(values) - set(send.missing or []))
    if unknown:
        raise FillError("not missing on this send: " + ", ".join(unknown))
    cleaned = {name: str(value).strip() for name, value in values.items() if value is not None}
    blank = sorted(name for name in values if not cleaned.get(name))
    if blank:
        raise FillError("values cannot be blank: " + ", ".join(blank))

    execution = send.execution
    execution.variables = {**(execution.variables or {}), **cleaned}
    execution.save(update_fields=["variables"])
    ExecutionEvent.objects.create(
        execution=execution,
        event_type="whatsapp_filled",
        payload={"send_id": send.id, "values": cleaned},
    )

    result = _send(execution, send.template_key)
    _apply_result(send, result)
    send.save()
    return result


def on_call_completed(execution) -> None:
    """
    Queues this call's automatic message if the agent has auto_send on and a
    rule matches. A second call for the same Execution (a resent webhook) hits
    the unique constraint and is ignored.
    """
    try:
        config = _config(execution.process_agent)
        if config is None or not config.auto_send:
            return

        rule = pick_rule(execution)
        if rule is None:
            return

        template_key = rule.template.name if rule.template is not None else ""
        status, reason = WhatsAppSend.STATUS_PENDING, ""
        if rule.action == ChannelRule.ACTION_SKIP:
            status, reason = WhatsAppSend.STATUS_SKIPPED, rule.reason or "skipped by rule"
        elif rule.template is None:
            status, reason = WhatsAppSend.STATUS_SKIPPED, "rule has no template"
        elif not template_curl(execution.process_agent, template_key).strip():
            status, reason = WhatsAppSend.STATUS_SKIPPED, f"{template_key} not configured"

        with transaction.atomic():
            WhatsAppSend.objects.create(
                execution=execution,
                template_key=template_key,
                template=rule.template,
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
            _apply_result(send, _send(send.execution, send.template_key))
            send.save()
            attempted += 1
        except Exception:
            logger.exception("WhatsApp send %s crashed", send.id)
    return attempted
