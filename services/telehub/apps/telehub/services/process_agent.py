import secrets

from django.core.exceptions import ValidationError
from django.db import transaction

from ..models import (
    BotJourney,
    ChannelRule,
    ChannelTemplate,
    Department,
    Integration,
    LeadSource,
    OmnichannelConfig,
    ProcessAgent,
    ProcessIntegration,
    Variable,
    VoiceBot,
    WebhookDefinition,
)
from .journey import generate_journey

DEFAULT_JOURNEY_NAME = "Sales Journey"

NODE_NAME_COMMUNICATION = "Communication"
NODE_NAME_RETRY = "Retry"
NODE_NAME_BUSINESS_HOURS = "Business Hours"
NODE_NAME_DND_CHECK = "DND Check"
NODE_NAME_CALLBACK = "Callback"
NODE_NAME_QA = "QA"
NODE_NAME_CRM_UPDATE = "CRM Update"

# Overlap between VoiceBot fields and Communication NodeInstance.config keys —
# dispatcher.py reads NodeInstance.config, not VoiceBot, so wiring a VoiceBot
# onto a BotJourney (at creation time, or on a later edit) must also push
# these onto its Communication node or the change would silently have no
# effect on real dispatches. `script` has no NodeInstance.config counterpart
# (reference-only, never dispatched).
VOICE_BOT_TO_NODE_CONFIG_FIELDS = (
    "communication_type",
    "bot_name",
    "bot_id",
    "dids",
    "api_url",
    "webhook_schema",
)


def sync_voice_bot_to_communication_nodes(voice_bot: "VoiceBot") -> None:
    """Re-pushes a VoiceBot's dispatch-relevant fields onto every BotJourney
    currently wired to it — called after any VoiceBot edit (see the
    VoiceBotViewSet in api/views.py)."""
    for bot_journey in voice_bot.journeys.all():
        node = bot_journey.nodes.filter(name=NODE_NAME_COMMUNICATION).first()
        if node is None:
            continue
        node.config = {
            **node.config,
            **{field: getattr(voice_bot, field) for field in VOICE_BOT_TO_NODE_CONFIG_FIELDS},
        }
        node.save()


def _apply_wizard_node_configs(
    bot_journey: "BotJourney", communication_config: dict, business_rules: dict, qa: dict, integration_ids: list
) -> None:
    """Pushes wizard config onto the NodeInstance rows of one BotJourney's
    generated graph, matched by name."""
    node_config_by_name = {
        NODE_NAME_COMMUNICATION: communication_config,
        NODE_NAME_RETRY: business_rules.get("retry", {}),
        NODE_NAME_BUSINESS_HOURS: business_rules.get("business_hours", {}),
        NODE_NAME_DND_CHECK: business_rules.get("dnd", {}),
        NODE_NAME_CALLBACK: business_rules.get("callback", {}),
        NODE_NAME_QA: qa,
        NODE_NAME_CRM_UPDATE: {"integration_ids": integration_ids},
    }

    nodes_by_name = {node.name: node for node in bot_journey.nodes.all()}
    for name, config in node_config_by_name.items():
        node = nodes_by_name.get(name)
        if node is None:
            continue
        node.config = config
        node.save()


@transaction.atomic
def create_process_agent_from_wizard(payload: dict, organization) -> "ProcessAgent":
    """
    Create a ProcessAgent (and its related rows) from a wizard payload. Every
    nested section is optional — a minimal payload of just
    {"department": <id>, "name": "X"} must succeed.
    """
    voice = payload.get("voice", {}) or {}
    business_rules = payload.get("business_rules", {}) or {}
    qa = payload.get("qa", {}) or {}
    analytics = payload.get("analytics", {}) or {}
    omnichannel = payload.get("omnichannel", {}) or {}
    integration_ids = payload.get("integrations", []) or []

    # Every ID below comes straight from the request, so each is resolved
    # within `organization` — an ID from another org is a validation error,
    # never a cross-tenant link. Checked up front so nothing is half-created.
    department = Department.objects.for_org(organization).filter(pk=payload.get("department")).first()
    if department is None:
        raise ValidationError("A valid department id is required")
    voice_bot_id = voice.get("voice_bot_id")
    voice_bot = None
    if voice_bot_id:
        voice_bot = VoiceBot.objects.for_org(organization).filter(pk=voice_bot_id).first()
        if voice_bot is None:
            raise ValidationError(f"Unknown voice bot id: {voice_bot_id}")
    # The number this stage uses ({"voice": {"numbers": [PhoneNumber id]}}): same
    # rule as the stage API — at most one, and it must be one of the bot's own.
    number_ids = voice.get("numbers") or []
    if number_ids:
        if voice_bot is None:
            raise ValidationError("numbers need a voice bot")
        if not isinstance(number_ids, list) or not all(isinstance(i, int) for i in number_ids):
            raise ValidationError("numbers must be a list of number ids")
        if len(set(number_ids)) > 1:
            raise ValidationError("a stage is assigned one number")
        if voice_bot.numbers.filter(pk__in=number_ids).count() != len(set(number_ids)):
            raise ValidationError("numbers must be numbers of the chosen voice bot")
    valid_integration_ids = []
    for integration_id in integration_ids:
        if not Integration.objects.for_org(organization).filter(pk=integration_id).exists():
            raise ValidationError(f"Unknown integration id: {integration_id}")
        valid_integration_ids.append(integration_id)

    agent = ProcessAgent.objects.create(
        organization=organization,
        department=department,
        name=payload["name"],
        description=payload.get("description", ""),
        status="active",
        analytics_stats=analytics.get("stats", {}) or {},
    )

    # The wizard always creates the agent's one BotJourney ("Sales Journey",
    # order=0) — wired to an existing, globally-managed VoiceBot the wizard's
    # Voice step selected (see dashboard's /bots page), not one created here.
    bot_journey = BotJourney.objects.create(
        process_agent=agent, name=payload.get("journey_name") or DEFAULT_JOURNEY_NAME, order=0
    )
    generate_journey(bot_journey)

    bot_journey.voice_bot = voice_bot
    bot_journey.save()
    if number_ids:
        bot_journey.numbers.set(number_ids)

    communication_config = (
        {field: getattr(voice_bot, field) for field in VOICE_BOT_TO_NODE_CONFIG_FIELDS}
        if voice_bot is not None
        else {}
    )
    _apply_wizard_node_configs(bot_journey, communication_config, business_rules, qa, integration_ids)

    lead_source = payload.get("lead_source", {}) or {}
    if lead_source:
        LeadSource.objects.create(
            organization=organization,
            process_agent=agent,
            type=lead_source.get("type", ""),
            configuration=lead_source.get("configuration", {}),
            field_mapping=lead_source.get("field_mapping", {}),
        )

    # Business Rules variables and Analytics dispositions are visually "the
    # same thing" in the wizard (see VariableRowsEditor's `simple` mode), and a
    # Variable is now unique per (agent, key): a key listed in both steps
    # becomes one row — the business-rules entry wins (real default_value /
    # type), and the analytics entry only contributes its display label
    # (analytics rows use default_value as a free-text label, not a default).
    variables_by_key = {}
    for source, variable in [
        (Variable.SOURCE_BUSINESS_RULES, v) for v in (business_rules.get("variables", []) or [])
    ] + [(Variable.SOURCE_ANALYTICS, v) for v in (analytics.get("custom_variables", []) or [])]:
        key = variable.get("key")
        if not key:
            continue
        row = variables_by_key.setdefault(
            key,
            {"source": source, "type": variable.get("type", "string"), "default_value": "", "label": "", "required": False},
        )
        if source == Variable.SOURCE_BUSINESS_RULES:
            row["source"] = source
            row["type"] = variable.get("type", "string")
            row["default_value"] = variable.get("default_value", "")
        else:
            row["label"] = variable.get("default_value", "")
        row["required"] = row["required"] or bool(variable.get("required", False))
    for key, row in variables_by_key.items():
        Variable.objects.create(process_agent=agent, key=key, **row)

    for integration_id in valid_integration_ids:
        ProcessIntegration.objects.create(
            process_agent=agent, integration_id=integration_id
        )

    if omnichannel.get("channel") or omnichannel.get("variables"):
        # The wizard's single curl becomes one "Default" template plus a rule that
        # always sends it. It is deliberately not stored on the config's legacy
        # whatsapp_curl, which would seed Hyundai's variable-specific T1/T2/T3 rules.
        OmnichannelConfig.objects.create(
            process_agent=agent,
            channel=omnichannel.get("channel", ""),
            variables=omnichannel.get("variables", []) or [],
            whatsapp_template=omnichannel.get("whatsapp_template", ""),
        )
        curl = (omnichannel.get("whatsapp_curl") or "").strip()
        if curl:
            template = ChannelTemplate.objects.create(process_agent=agent, name="Default", curl=curl)
            ChannelRule.objects.create(process_agent=agent, priority=0, template=template)

    communication_type = voice_bot.communication_type if voice_bot else ""
    webhook_schema = voice_bot.webhook_schema if voice_bot else None
    # An inbound bot always needs the webhook: it's the only way its calls
    # reach telehub at all (see services/inbound.py).
    if communication_type == "voice_inbound" or (communication_type.startswith("voice") and webhook_schema):
        secret = secrets.token_hex(16)
        WebhookDefinition.objects.create(
            organization=organization,
            process_agent=agent,
            name=f"{agent.name} Callback",
            # Stable relative path — a real view is mounted at this path (see
            # api/views.py:webhook_intake). The full public URL (with a live ngrok
            # domain prefixed) is computed on read, not stored here, so it never
            # goes stale when the local ngrok tunnel restarts — see
            # ProcessAgentDetailSerializer's webhooks field / services/ngrok.py.
            url=f"/api/telehub/webhooks/{secret}/",
            secret=secret,
            schema=webhook_schema or {},
            status="active",
        )

    return agent
