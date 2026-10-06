from rest_framework import serializers

from ..services.ngrok import get_public_base_url
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
    class Meta:
        model = OmnichannelConfig
        fields = ["channel", "variables", "whatsapp_template", "whatsapp_curl"]


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
        ]

    def get_whatsapp(self, obj):
        events = getattr(obj, "whatsapp_events", None) or []
        if not events:
            return None
        latest = events[0]
        return {
            "status": "sent" if latest.event_type == "whatsapp_sent" else "failed",
            "error": (latest.payload or {}).get("error"),
            "at": latest.created_at.isoformat(),
            "count": len(events),
        }


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
