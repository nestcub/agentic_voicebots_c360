from rest_framework import serializers

from ..models import (
    Department,
    Execution,
    Integration,
    LeadSource,
    NodeConnection,
    NodeInstance,
    NodeTemplate,
    ProcessAgent,
    ProcessIntegration,
    QAResult,
    Variable,
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
        fields = ["id", "key", "type", "default_value", "required"]


class WebhookDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookDefinition
        fields = ["id", "name", "url", "secret", "schema", "status"]


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


class ProcessAgentDetailSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True)
    lead_sources = LeadSourceSerializer(many=True, read_only=True)
    variables = VariableSerializer(many=True, read_only=True)
    webhooks = WebhookDefinitionSerializer(many=True, read_only=True)
    integrations = ProcessAgentIntegrationSerializer(
        source="process_integrations", many=True, read_only=True
    )

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
            "lead_sources",
            "variables",
            "webhooks",
            "integrations",
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
        ]
