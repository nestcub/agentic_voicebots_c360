"""
The default WhatsApp templates and rules every agent migrated from the old
fixed T1/T2/T3 setup gets — Hyundai's selection logic, now expressed as data
(ChannelTemplate / ChannelRule rows) instead of code:

  0  skip   when is_test is truthy                         ("test call")
  1  send T1 when appointment date, time and place exist   (full appointment)
  2  send T2 when callback_status equals "required"
  3  send T1 when any main variable exists                 (partial capture)
  4  send T3 otherwise

Pure functions that take the model classes as arguments so the same code runs
in a data migration (historical models) and at runtime (real models) — keep
this module free of model imports.
"""
TEMPLATE_KEYS = ("T1", "T2", "T3")

MAIN_VARIABLES = ("customer_name", "model_name", "appointment_place", "appointment_date", "appointment_time")
APPOINTMENT_VARIABLES = ("appointment_date", "appointment_time", "appointment_place")

# Sent in place of an empty T1 param (partial captures).
FILL_TEXT = "unspecified"

# Newer voicebot payloads send the model as model_of_interest.
T1_PARAM_MAP = {"model_name": {"variable": "model_name", "fallback": "model_of_interest"}}

SEED_TEMPLATES = (
    {"name": "T1", "missing_fill": FILL_TEXT, "param_map": T1_PARAM_MAP},
    {"name": "T2", "missing_fill": "", "param_map": {}},
    {"name": "T3", "missing_fill": "", "param_map": {}},
)


def _exists(*names):
    return [{"variable": name, "op": "exists"} for name in names]


SEED_RULES = (
    {
        "priority": 0,
        "action": "skip",
        "template": None,
        "match": "all",
        "checks": [{"variable": "is_test", "op": "truthy"}],
        "reason": "test call",
    },
    {"priority": 1, "action": "send", "template": "T1", "match": "all", "checks": _exists(*APPOINTMENT_VARIABLES), "reason": ""},
    {
        "priority": 2,
        "action": "send",
        "template": "T2",
        "match": "all",
        "checks": [{"variable": "callback_status", "op": "equals", "value": "required"}],
        "reason": "",
    },
    {"priority": 3, "action": "send", "template": "T1", "match": "any", "checks": _exists(*MAIN_VARIABLES), "reason": ""},
    {"priority": 4, "action": "send", "template": "T3", "match": "all", "checks": [], "reason": ""},
)


def legacy_curls(config) -> dict:
    """The T1/T2/T3 curls on an OmnichannelConfig; T1 falls back to the pre-POC single whatsapp_curl."""
    curls = {key: ((config.whatsapp_curls or {}).get(key) or "") for key in TEMPLATE_KEYS}
    if not curls["T1"].strip():
        curls["T1"] = config.whatsapp_curl or ""
    return curls


def sync_agent(ChannelTemplate, ChannelRule, process_agent, curls: dict) -> None:
    """
    Makes sure `process_agent` has the T1/T2/T3 templates and, if it has no
    rules at all, the default rules. A legacy curl only ever overwrites a
    template's curl when it is non-empty, so templates managed directly
    (blank legacy field) are never wiped by a stale config save.
    """
    templates = {}
    for spec in SEED_TEMPLATES:
        curl = curls.get(spec["name"]) or ""
        template, created = ChannelTemplate.objects.get_or_create(
            process_agent=process_agent,
            name=spec["name"],
            defaults={
                "channel": "whatsapp",
                "curl": curl,
                "missing_fill": spec["missing_fill"],
                "param_map": spec["param_map"],
            },
        )
        if not created and curl.strip() and template.curl != curl:
            template.curl = curl
            template.save(update_fields=["curl"])
        templates[spec["name"]] = template

    if not ChannelRule.objects.filter(process_agent=process_agent).exists():
        for spec in SEED_RULES:
            ChannelRule.objects.create(
                process_agent=process_agent,
                priority=spec["priority"],
                action=spec["action"],
                template=templates[spec["template"]] if spec["template"] else None,
                match=spec["match"],
                checks=spec["checks"],
                reason=spec["reason"],
            )
