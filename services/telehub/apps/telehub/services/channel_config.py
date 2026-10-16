"""
Reading and validating the omnichannel configuration the dashboard edits: an
agent's ChannelTemplates (pasted Chat360 curls plus how their placeholders map
to variables) and ChannelRules (which template to send when).

Everything the API returns about a template is derived from its curl *without*
the headers, which carry the API key — the curl itself is write-only.

validate_* return (cleaned_fields, errors): `errors` is {field: message} and
empty when the payload is fine, so views can answer 400 with all problems at
once. Nothing here touches the database except the uniqueness / ownership
lookups validation needs.
"""
from ..models import ChannelRule, ChannelTemplate
from . import conditions
from .whatsapp import parse_curl

NAME_MAX = ChannelTemplate._meta.get_field("name").max_length
FILL_MAX = ChannelTemplate._meta.get_field("missing_fill").max_length
REASON_MAX = ChannelRule._meta.get_field("reason").max_length
SUPPORTED_CHANNELS = (ChannelTemplate.CHANNEL_WHATSAPP,)
PARAM_ENTRY_KEYS = {"variable", "fallback", "fixed"}


# ── describing a curl ───────────────────────────────────────────────────────


def describe_curl(curl: str) -> dict:
    """What a pasted curl contains, minus its headers: url, template title, and its params."""
    summary = {"configured": bool((curl or "").strip()), "url": "", "template_title": "", "params": [], "error": None}
    if not summary["configured"]:
        return summary
    try:
        url, _, body = parse_curl(curl)
    except Exception as exc:
        summary["error"] = str(exc)
        return summary
    summary["url"] = url
    for task in body.get("task_body") or []:
        template_data = (task or {}).get("template_data") or {}
        summary["template_title"] = template_data.get("template_title", "") or summary["template_title"]
        for key, placeholder in (template_data.get("param_data") or {}).items():
            summary["params"].append({"key": key, "placeholder": placeholder if isinstance(placeholder, str) else ""})
    return summary


def _variables_sent(summary: dict, param_map: dict) -> list:
    """Variable names a template reads: mapped variables, plus unmapped params that resolve by their own name."""
    names = []
    for param in summary["params"]:
        entry = (param_map or {}).get(param["key"])
        entry = entry if isinstance(entry, dict) else {}
        if "fixed" in entry:
            continue
        if entry.get("variable"):
            name = str(entry["variable"])
        else:
            placeholder = param["placeholder"]
            name = placeholder.lstrip("@")
            if not (name == param["key"] or placeholder.startswith("@")):
                continue  # literal text in the curl, not a variable
        if name and name not in names:
            names.append(name)
    return names


def template_to_dict(template: ChannelTemplate) -> dict:
    summary = describe_curl(template.curl)
    return {
        "id": template.id,
        "name": template.name,
        "channel": template.channel,
        "is_active": template.is_active,
        "missing_fill": template.missing_fill,
        "param_map": template.param_map or {},
        "configured": summary["configured"],
        "url": summary["url"],
        "template_title": summary["template_title"],
        "params": summary["params"],
        "error": summary["error"],
        "variables_sent": _variables_sent(summary, template.param_map),
    }


def rule_to_dict(rule: ChannelRule) -> dict:
    return {
        "id": rule.id,
        "priority": rule.priority,
        "action": rule.action,
        "template": rule.template_id,
        "template_name": rule.template.name if rule.template_id else None,
        "match": rule.match,
        "checks": rule.checks or [],
        "reason": rule.reason,
    }


def variables_sent_by_agent(process_agent) -> list:
    """Every variable any active template reads — what the customer's messages can contain."""
    names = []
    for template in process_agent.channel_templates.filter(is_active=True):
        for name in template_to_dict(template)["variables_sent"]:
            if name not in names:
                names.append(name)
    return names


# ── templates ───────────────────────────────────────────────────────────────


def _clean_param_map(raw, known_params) -> tuple:
    if not isinstance(raw, dict):
        return None, "param_map must be an object"
    cleaned = {}
    for key, entry in raw.items():
        if known_params is not None and key not in known_params:
            return None, f"{key!r} is not a param in this template's curl"
        if not isinstance(entry, dict) or set(entry) - PARAM_ENTRY_KEYS:
            return None, f"{key!r}: entry must be an object with variable/fallback or fixed"
        has_fixed, has_variable = "fixed" in entry, bool(str(entry.get("variable") or "").strip())
        if has_fixed == has_variable:
            return None, f"{key!r}: give exactly one of variable or fixed"
        if has_fixed:
            cleaned[key] = {"fixed": str(entry["fixed"])}
        else:
            item = {"variable": str(entry["variable"]).strip()}
            if str(entry.get("fallback") or "").strip():
                item["fallback"] = str(entry["fallback"]).strip()
            cleaned[key] = item
    return cleaned, None


def validate_template(process_agent, data, instance=None) -> tuple:
    """Fields to save for a ChannelTemplate create (instance None) or partial update, and any errors."""
    errors, cleaned = {}, {}
    data = data if isinstance(data, dict) else {}

    if instance is None or "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            errors["name"] = "name is required"
        elif len(name) > NAME_MAX:
            errors["name"] = f"name must be at most {NAME_MAX} characters"
        else:
            taken = process_agent.channel_templates.filter(name=name)
            if instance is not None:
                taken = taken.exclude(pk=instance.pk)
            if taken.exists():
                errors["name"] = "a template with this name already exists"
            cleaned["name"] = name

    if "channel" in data and data["channel"] not in SUPPORTED_CHANNELS:
        errors["channel"] = "only whatsapp is supported"

    curl = data.get("curl")
    curl = curl.strip() if isinstance(curl, str) else ""
    if instance is None and not curl:
        errors["curl"] = "paste the template's curl command"
    if curl:
        try:
            parse_curl(curl)
            cleaned["curl"] = curl
        except Exception as exc:
            errors["curl"] = f"could not read this curl: {exc}"

    if "missing_fill" in data:
        fill = str(data["missing_fill"] or "")
        if len(fill) > FILL_MAX:
            errors["missing_fill"] = f"must be at most {FILL_MAX} characters"
        cleaned["missing_fill"] = fill

    if "is_active" in data:
        cleaned["is_active"] = bool(data["is_active"])

    if "param_map" in data:
        effective_curl = cleaned.get("curl") or (instance.curl if instance is not None else "")
        summary = describe_curl(effective_curl)
        known = {p["key"] for p in summary["params"]} if summary["configured"] and not summary["error"] else None
        param_map, problem = _clean_param_map(data["param_map"], known)
        if problem:
            errors["param_map"] = problem
        else:
            cleaned["param_map"] = param_map

    return cleaned, errors


# ── rules ───────────────────────────────────────────────────────────────────


def clean_checks(raw) -> tuple:
    problems = conditions.validate_checks(raw)
    if problems:
        return None, "; ".join(problems)
    cleaned = []
    for check in raw:
        item = {"variable": str(check["variable"]).strip(), "op": check["op"]}
        if check["op"] == conditions.OP_EQUALS:
            item["value"] = str(check["value"])
        cleaned.append(item)
    return cleaned, None


def validate_rule(process_agent, data, instance=None) -> tuple:
    """Fields to save for a ChannelRule create (instance None) or partial update, and any errors."""
    errors, cleaned = {}, {}
    data = data if isinstance(data, dict) else {}

    action = data.get("action", instance.action if instance is not None else ChannelRule.ACTION_SEND)
    if action not in (ChannelRule.ACTION_SEND, ChannelRule.ACTION_SKIP):
        errors["action"] = "action must be send or skip"
    else:
        cleaned["action"] = action

    if "match" in data:
        if data["match"] not in (ChannelRule.MATCH_ALL, ChannelRule.MATCH_ANY):
            errors["match"] = "match must be all or any"
        else:
            cleaned["match"] = data["match"]

    if "checks" in data:
        checks, problem = clean_checks(data["checks"])
        if problem:
            errors["checks"] = problem
        else:
            cleaned["checks"] = checks

    if "reason" in data:
        reason = str(data["reason"] or "")
        if len(reason) > REASON_MAX:
            errors["reason"] = f"must be at most {REASON_MAX} characters"
        cleaned["reason"] = reason

    if "priority" in data:
        try:
            cleaned["priority"] = int(data["priority"])
        except (TypeError, ValueError):
            errors["priority"] = "priority must be a whole number"

    if action == ChannelRule.ACTION_SKIP:
        cleaned["template"] = None
    elif "template" in data or instance is None:
        template = None
        if data.get("template") not in (None, ""):
            template = process_agent.channel_templates.filter(pk=data["template"]).first() if str(
                data["template"]
            ).isdigit() else None
        if template is None:
            errors["template"] = "choose one of this agent's templates"
        else:
            cleaned["template"] = template
    elif instance is not None and instance.template_id is None:
        errors["template"] = "choose one of this agent's templates"

    return cleaned, errors


def next_priority(process_agent) -> int:
    last = process_agent.channel_rules.order_by("-priority").values_list("priority", flat=True).first()
    return 0 if last is None else last + 1


def reorder_rules(process_agent, ordered_ids) -> str:
    """Renumbers the agent's rules 0..n-1 in the given order. Returns an error message, or ""."""
    if not isinstance(ordered_ids, list) or not all(isinstance(i, int) for i in ordered_ids):
        return "order must be a list of rule ids"
    existing = set(process_agent.channel_rules.values_list("id", flat=True))
    if len(ordered_ids) != len(set(ordered_ids)) or set(ordered_ids) != existing:
        return "order must list every one of this agent's rules exactly once"
    for position, rule_id in enumerate(ordered_ids):
        process_agent.channel_rules.filter(pk=rule_id).update(priority=position)
    return ""
