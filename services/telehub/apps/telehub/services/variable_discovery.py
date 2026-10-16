"""
Variable discovery: every key a ProcessAgent's webhook delivers becomes a
Variable row the user can tick for QA / Analytics (Variable.use_in_qa,
use_in_analytics) — instead of having to declare each one by hand first.

New keys are created `discovered=True` with both ticks off. Known keys only
get last_seen_at / sample_value refreshed, so a user's ticks and edits are
never touched. Platform plumbing keys (session id, phone numbers, timing)
are skipped: they stay in execution.variables and remain usable by rules and
templates, they just aren't suggested as results worth tracking.

Called from the webhook handler, which must always ack 200, so nothing here
raises.
"""
import json
import logging

from django.utils import timezone

from ..models import Variable
from .inbound import normalize_payload

logger = logging.getLogger(__name__)

IGNORED_KEYS = frozenset(
    {
        "session_id",
        "dlr_id",
        "caller_number",
        "callee_number",
        "contact_no",
        "call_start_time",
        "call_duration",
        "date",
        "is_test",
        "recording_url",
    }
)

KEY_MAX_LEN = Variable._meta.get_field("key").max_length
SAMPLE_MAX_LEN = Variable._meta.get_field("sample_value").max_length


def _sample(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    return str(value).strip()[:SAMPLE_MAX_LEN]


def discover_variables(process_agent, payload) -> int:
    """Upserts a Variable per payload key. Returns how many new rows were created."""
    try:
        if not isinstance(payload, dict):
            return 0
        values = {}
        for key, value in normalize_payload(payload).items():
            if key and key not in IGNORED_KEYS and len(key) <= KEY_MAX_LEN:
                values[key] = _sample(value)
        if not values:
            return 0

        now = timezone.now()
        existing = {v.key: v for v in Variable.objects.filter(process_agent=process_agent, key__in=values)}

        to_update = []
        for key, sample in values.items():
            variable = existing.get(key)
            if variable is None:
                continue
            variable.last_seen_at = now
            # Keep the last non-empty value so one empty call doesn't blank the UI hint.
            if sample:
                variable.sample_value = sample
            to_update.append(variable)
        if to_update:
            Variable.objects.bulk_update(to_update, ["last_seen_at", "sample_value"])

        new_rows = [
            Variable(
                process_agent=process_agent,
                key=key,
                discovered=True,
                use_in_qa=False,
                use_in_analytics=False,
                last_seen_at=now,
                sample_value=sample,
            )
            for key, sample in values.items()
            if key not in existing
        ]
        if new_rows:
            # ignore_conflicts: two simultaneous deliveries may both see a key as new.
            Variable.objects.bulk_create(new_rows, ignore_conflicts=True)
        return len(new_rows)
    except Exception:
        logger.exception("variable discovery failed for process_agent=%s", getattr(process_agent, "id", None))
        return 0
