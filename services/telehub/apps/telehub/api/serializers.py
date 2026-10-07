from rest_framework import serializers

from ..services.ngrok import get_public_base_url
from ..services import hyundai_whatsapp
from ..services.whatsapp import parse_curl
from ..models import (
    BotJourney,
    Department,
    Execution,
    Integration,
    LeadSource,
    NodeConnection,
    NodeInstance,
    NodeTemplate,
    OmnichannelConfig,
    ProcessAgent,
    ProcessIntegration,
    QAResult,
    Variable,
    VoiceBot,
    WebhookDefinition,
)


class DepartmentSerializer(serializers.ModelSerializer):
    process_agent_count = serializers.SerializerMethodField()

    class Meta:
        model = Department
        fields = [
            "id",
            "name",
            "description",
            "icon",
            "color",
            "is_active",
            "created_at",
            "updated_at",
            "process_agent_count",
        ]

    def get_process_agent_count(self, obj):
        return obj.process_agents.count()


class DepartmentNestedProcessAgentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProcessAgent
        fields = ["id", "name", "status", "is_active", "version"]


class DepartmentDetailSerializer(DepartmentSerializer):
    process_agents = DepartmentNestedProcessAgentSerializer(many=True, read_only=True)

    class Meta(DepartmentSerializer.Meta):
        fields = DepartmentSerializer.Meta.fields + ["process_agents"]


class IntegrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Integration
        fields = ["id", "name", "type", "configuration", "status", "created_at"]


class NodeTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = NodeTemplate
        fields = [
            "id",
            "type",
            "category",
            "display_name",
            "description",
            "icon",
            "color",
            "default_config",
            "schema",
        ]


class ProcessAgentListSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True)

    class Meta:
        model = ProcessAgent
        fields = [
            "id",
            "department",
            "department_name",
            "name",
            "description",
            "status",
            "version",
            "is_active",
            "created_at",
            "updated_at",
        ]


class LeadSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeadSource
        fields = ["id", "type", "configuration", "field_mapping", "created_at"]


class VariableSerializer(serializers.ModelSerializer):
    class Meta:
        model = Variable
        fields = ["id", "key", "type", "default_value", "label", "required", "source"]


class WebhookDefinitionSerializer(serializers.ModelSerializer):
    # Computed fresh on every read (never stored) so it reflects whatever ngrok
    # tunnel is currently running, not whatever was running when the Process was
    # created — ngrok URLs change on every tunnel restart. None when ngrok isn't
    # running locally; `url` (the stable relative path) is always present as a
    # fallback the frontend can show instead.
    public_url = serializers.SerializerMethodField()

    class Meta:
        model = WebhookDefinition
        fields = ["id", "name", "url", "public_url", "secret", "schema", "status"]

    def get_public_url(self, obj):
        base = get_public_base_url()
        return f"{base}{obj.url}" if base else None


class ProcessAgentIntegrationSerializer(serializers.ModelSerializer):
    integration_name = serializers.CharField(
        source="integration.name", read_only=True
    )
    integration_type = serializers.CharField(
        source="integration.type", read_only=True
    )

    class Meta:
        model = ProcessIntegration
        fields = ["id", "integration", "integration_name", "integration_type"]


class VoiceBotSerializer(serializers.ModelSerializer):
    class Meta:
        model = VoiceBot
        fields = [
            "id",
            "label",
            "communication_type",
            "bot_name",
            "bot_id",
            "dids",
            "api_url",
            "script",
            "webhook_schema",
            "created_at",
        ]


class BotJourneySerializer(serializers.ModelSerializer):
    voice_bot = VoiceBotSerializer(read_only=True)

    class Meta:
        model = BotJourney
        fields = ["id", "name", "order", "voice_bot", "created_at"]


class OmnichannelConfigSerializer(serializers.ModelSerializer):
    # What each template's curl parses to (no headers — those carry the API
    # key), so Settings can show whether a pasted curl is usable.
    whatsapp_templates = serializers.SerializerMethodField()

    class Meta:
        model = OmnichannelConfig
        fields = [
            "channel",
            "variables",
            "whatsapp_template",
            "whatsapp_curl",
            "whatsapp_curls",
            "auto_send",
            "whatsapp_templates",
        ]

    def get_whatsapp_templates(self, obj):
        summaries = {}
        for key in hyundai_whatsapp.TEMPLATE_KEYS:
            curl = hyundai_whatsapp.template_curl(obj.process_agent, key)
            summary = {"configured": bool(curl.strip()), "url": "", "template_title": "", "params": [], "error": None}
            if summary["configured"]:
                try:
                    url, _, body = parse_curl(curl)
                    summary["url"] = url
                    for task in body.get("task_body") or []:
                        template_data = (task or {}).get("template_data") or {}
                        summary["template_title"] = template_data.get("template_title", "")
                        summary["params"] = list((template_data.get("param_data") or {}).keys())
                except Exception as exc:
                    summary["error"] = str(exc)
            summaries[key] = summary
        return summaries


class ProcessAgentDetailSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True)
    lead_sources = LeadSourceSerializer(many=True, read_only=True)
    variables = VariableSerializer(many=True, read_only=True)
    webhooks = WebhookDefinitionSerializer(many=True, read_only=True)
    integrations = ProcessAgentIntegrationSerializer(
        source="process_integrations", many=True, read_only=True
    )
    # OneToOneField — absent unless the wizard's Omnichannel step was filled in.
    omnichannel = OmnichannelConfigSerializer(read_only=True)
    bot_journeys = BotJourneySerializer(many=True, read_only=True)

    class Meta:
        model = ProcessAgent
        fields = [
            "id",
            "department",
            "department_name",
            "name",
            "description",
            "status",
            "version",
            "is_active",
            "analytics_stats",
            "created_at",
            "updated_at",
            "lead_sources",
            "variables",
            "webhooks",
            "integrations",
            "omnichannel",
            "bot_journeys",
        ]


class ProcessAgentUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProcessAgent
        fields = ["name", "description", "status", "is_active"]


class NodeInstanceJourneySerializer(serializers.ModelSerializer):
    node_template_type = serializers.CharField(
        source="node_template.type", read_only=True
    )

    class Meta:
        model = NodeInstance
        fields = [
            "id",
            "bot_journey",
            "node_template_type",
            "name",
            "config",
            "position_x",
            "position_y",
            "enabled",
        ]


class NodeConnectionJourneySerializer(serializers.ModelSerializer):
    class Meta:
        model = NodeConnection
        fields = ["id", "source_node", "target_node", "condition", "priority"]


class ExecutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Execution
        fields = [
            "id",
            "lead_id",
            "status",
            "started_at",
            "ended_at",
            "duration",
            "current_node",
        ]


class CallRowSerializer(serializers.ModelSerializer):
    """
    Calls tab row. Expects the queryset to prefetch WhatsApp events into
    `whatsapp_events` (newest first) — see ProcessAgentViewSet.calls.
    """

    whatsapp = serializers.SerializerMethodField()
    suggested_template = serializers.SerializerMethodField()

    class Meta:
        model = Execution
        fields = [
            "id",
            "lead_id",
            "status",
            "campaign_id",
            "duration",
            "current_node",
            "variables",
            "created_at",
            "whatsapp",
            "suggested_template",
        ]

    def get_whatsapp(self, obj):
        """Latest WhatsAppSend (pending/sent/failed/skipped, which template, auto or manual)."""
        sends = list(obj.whatsapp_sends.all())
        if sends:
            latest = sends[0]
            return {
                "status": latest.status,
                "template_key": latest.template_key,
                "trigger": latest.trigger,
                "error": latest.last_error or None,
                "at": (latest.sent_at or latest.updated_at).isoformat(),
                "count": sum(1 for s in sends if s.status == "sent"),
            }
        events = getattr(obj, "whatsapp_events", None) or []
        if not events:
            return None
        latest = events[0]
        return {
            "status": "sent" if latest.event_type == "whatsapp_sent" else "failed",
            "template_key": (latest.payload or {}).get("template_key") or None,
            "trigger": "manual",
            "error": (latest.payload or {}).get("error"),
            "at": latest.created_at.isoformat(),
            "count": sum(1 for e in events if e.event_type == "whatsapp_sent"),
        }

    def get_suggested_template(self, obj):
        return hyundai_whatsapp.pick_template(obj)


class CampaignLeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Execution
        fields = [
            "id",
            "lead_id",
            "status",
            "current_node",
            "variables",
            "created_at",
        ]


class QAResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = QAResult
        fields = [
            "id",
            "execution",
            "summary",
            "sentiment",
            "hallucination_score",
            "lead_score",
            "compliance_score",
            "bot_failure",
            "hot_lead",
            "recommendation",
            "missing_variables",
            "raw_result",
        ]
