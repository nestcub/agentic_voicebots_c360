import secrets

from ..models import (
    Integration,
    LeadSource,
    ProcessAgent,
    ProcessIntegration,
    Variable,
    WebhookDefinition,
)
from .journey import generate_journey

# Fixed node names produced by journey.generate_journey — wizard config gets
# pushed onto the NodeInstance rows that match these names.
NODE_NAME_COMMUNICATION = "Communication"
NODE_NAME_RETRY = "Retry"
NODE_NAME_BUSINESS_HOURS = "Business Hours"
NODE_NAME_DND_CHECK = "DND Check"
NODE_NAME_CALLBACK = "Callback"
NODE_NAME_QA = "QA"
NODE_NAME_CRM_UPDATE = "CRM Update"


def create_process_agent_from_wizard(payload: dict) -> "ProcessAgent":
    """
    Create a ProcessAgent (and its related rows) from a wizard payload. Every
    nested section is optional — a minimal payload of just
    {"department": <id>, "name": "X"} must succeed.
    """
    agent = ProcessAgent.objects.create(
        department_id=payload["department"],
        name=payload["name"],
        description=payload.get("description", ""),
        status="active",
    )

    generate_journey(agent)

    voice = payload.get("voice", {}) or {}
    business_rules = payload.get("business_rules", {}) or {}
    qa = payload.get("qa", {}) or {}
    analytics = payload.get("analytics", {}) or {}
    integration_ids = payload.get("integrations", []) or []

    node_config_by_name = {
        NODE_NAME_COMMUNICATION: voice,
        NODE_NAME_RETRY: business_rules.get("retry", {}),
        NODE_NAME_BUSINESS_HOURS: business_rules.get("business_hours", {}),
        NODE_NAME_DND_CHECK: business_rules.get("dnd", {}),
        NODE_NAME_CALLBACK: business_rules.get("callback", {}),
        NODE_NAME_QA: qa,
        NODE_NAME_CRM_UPDATE: {"integration_ids": integration_ids},
    }

    nodes_by_name = {node.name: node for node in agent.nodes.all()}
    for name, config in node_config_by_name.items():
        node = nodes_by_name.get(name)
        if node is None:
            continue
        node.config = config
        node.save()

    lead_source = payload.get("lead_source", {}) or {}
    if lead_source:
        LeadSource.objects.create(
            process_agent=agent,
            type=lead_source.get("type", ""),
            configuration=lead_source.get("configuration", {}),
            field_mapping=lead_source.get("field_mapping", {}),
        )

    variables = list(business_rules.get("variables", []) or [])
    variables += list(analytics.get("custom_variables", []) or [])
    variables_by_key = {}
    for variable in variables:
        key = variable.get("key")
        if not key:
            continue
        variables_by_key[key] = variable
    for key, variable in variables_by_key.items():
        Variable.objects.create(
            process_agent=agent,
            key=key,
            type=variable.get("type", "string"),
            default_value=variable.get("default_value", ""),
            required=variable.get("required", False),
        )

    for integration_id in integration_ids:
        if not Integration.objects.filter(pk=integration_id).exists():
            continue
        ProcessIntegration.objects.create(
            process_agent=agent, integration_id=integration_id
        )

    communication_type = voice.get("communication_type", "")
    webhook_schema = voice.get("webhook_schema")
    if communication_type.startswith("voice") and webhook_schema:
        secret = secrets.token_hex(16)
        WebhookDefinition.objects.create(
            process_agent=agent,
            name=f"{agent.name} Callback",
            # Stable relative path — a real view is mounted at this path (see
            # api/views.py:webhook_intake). The full public URL (with a live ngrok
            # domain prefixed) is computed on read, not stored here, so it never
            # goes stale when the local ngrok tunnel restarts — see
            # ProcessAgentDetailSerializer's webhooks field / services/ngrok.py.
            url=f"/api/telehub/webhooks/{secret}/",
            secret=secret,
            schema=webhook_schema,
            status="active",
        )

    return agent
