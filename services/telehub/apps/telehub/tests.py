from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from .models import (
    Department,
    Execution,
    Integration,
    LeadSource,
    NodeConnection,
    NodeInstance,
    NodeTemplate,
    ProcessAgent,
    Variable,
    WebhookDefinition,
    ProcessIntegration,
    QAResult,
)
from .services.journey import JOURNEY_STEPS, generate_journey
from .services.seed_node_templates import seed_node_templates


class DepartmentProcessAgentNodeInstanceChainTests(TestCase):
    def test_relationships_resolve(self):
        department = Department.objects.create(name="Automobile")
        process_agent = ProcessAgent.objects.create(
            department=department, name="Test Drive"
        )
        node_template = NodeTemplate.objects.create(
            type="communication", category="Communication", display_name="Communication"
        )
        node_instance = NodeInstance.objects.create(
            process_agent=process_agent,
            node_template=node_template,
            name="Send Outbound Message",
        )

        self.assertEqual(department.process_agents.get(), process_agent)
        self.assertEqual(process_agent.nodes.get(), node_instance)
        self.assertEqual(node_instance.process_agent, process_agent)
        self.assertEqual(node_instance.node_template, node_template)


class NodeConnectionTests(TestCase):
    def test_source_and_target_resolve(self):
        department = Department.objects.create(name="Healthcare")
        process_agent = ProcessAgent.objects.create(
            department=department, name="Appointment"
        )
        node_template = NodeTemplate.objects.create(
            type="routing", category="Routing", display_name="Routing"
        )
        source = NodeInstance.objects.create(
            process_agent=process_agent, node_template=node_template, name="Start"
        )
        target = NodeInstance.objects.create(
            process_agent=process_agent, node_template=node_template, name="End"
        )
        connection = NodeConnection.objects.create(
            process_agent=process_agent, source_node=source, target_node=target
        )

        self.assertEqual(connection.source_node, source)
        self.assertEqual(connection.target_node, target)
        self.assertEqual(source.outgoing_connections.get(), connection)
        self.assertEqual(target.incoming_connections.get(), connection)


class ProcessIntegrationUniqueTogetherTests(TestCase):
    def test_duplicate_process_integration_raises(self):
        department = Department.objects.create(name="Automobile")
        process_agent = ProcessAgent.objects.create(
            department=department, name="Free Service 1"
        )
        integration = Integration.objects.create(name="Chat360", type="crm")
        ProcessIntegration.objects.create(
            process_agent=process_agent, integration=integration
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProcessIntegration.objects.create(
                    process_agent=process_agent, integration=integration
                )


class VariableUniqueTogetherTests(TestCase):
    def test_duplicate_variable_key_per_process_agent_raises(self):
        department = Department.objects.create(name="Automobile")
        process_agent = ProcessAgent.objects.create(
            department=department, name="Insurance Renewal"
        )
        Variable.objects.create(process_agent=process_agent, key="customer_name")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Variable.objects.create(process_agent=process_agent, key="customer_name")


class QAResultOneToOneTests(TestCase):
    def test_second_qa_result_for_same_execution_raises(self):
        department = Department.objects.create(name="Automobile")
        process_agent = ProcessAgent.objects.create(
            department=department, name="Appointment Reminder"
        )
        execution = Execution.objects.create(process_agent=process_agent, lead_id="lead-1")
        QAResult.objects.create(execution=execution)

        self.assertEqual(execution.qa_result.execution, execution)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                QAResult.objects.create(execution=execution)


class JourneyGenerationTests(TestCase):
    def _make_process_agent(self):
        department = Department.objects.create(name="Automobile")
        return ProcessAgent.objects.create(
            department=department, name="Free Service Reminder"
        )

    def test_generate_journey_creates_nine_nodes_and_eight_connections_in_order(self):
        process_agent = self._make_process_agent()

        generate_journey(process_agent)

        self.assertEqual(process_agent.nodes.count(), 9)
        self.assertEqual(process_agent.connections.count(), 8)

        # Walk the chain from the node with no incoming connection (the head)
        # and confirm the name sequence matches the fixed journey order.
        nodes_by_name = {node.name: node for node in process_agent.nodes.all()}
        head = next(
            node
            for node in nodes_by_name.values()
            if not node.incoming_connections.exists()
        )

        ordered_names = []
        current = head
        while current is not None:
            ordered_names.append(current.name)
            outgoing = current.outgoing_connections.first()
            current = outgoing.target_node if outgoing else None

        expected_names = [name for name, _template_type in JOURNEY_STEPS]
        self.assertEqual(ordered_names, expected_names)

    def test_generate_journey_is_idempotent(self):
        process_agent = self._make_process_agent()

        generate_journey(process_agent)
        generate_journey(process_agent)

        self.assertEqual(process_agent.nodes.count(), 9)
        self.assertEqual(process_agent.connections.count(), 8)

    def test_each_node_instance_uses_expected_node_template_type(self):
        process_agent = self._make_process_agent()

        generate_journey(process_agent)

        nodes_by_name = {node.name: node for node in process_agent.nodes.all()}
        for name, expected_template_type in JOURNEY_STEPS:
            self.assertEqual(
                nodes_by_name[name].node_template.type, expected_template_type
            )


def _full_wizard_payload(department_id, name="Free Service 1"):
    return {
        "department": department_id,
        "name": name,
        "description": "",
        "voice": {
            "communication_type": "voice_outbound",
            "bot_name": "",
            "bot_id": "",
            "api_url": "",
            "webhook_schema": {
                "summary": "",
                "transcript": "",
                "sentiment": "",
                "outcome": "",
            },
        },
        "lead_source": {"type": "webhook", "configuration": {}, "field_mapping": {}},
        "business_rules": {
            "retry": {"attempts": 3, "interval_minutes": 30, "strategy": "linear"},
            "business_hours": {
                "timezone": "Asia/Kolkata",
                "start": "09:00",
                "end": "19:00",
                "working_days": [1, 2, 3, 4, 5, 6],
            },
            "callback": {
                "variable": "outcome",
                "operator": "==",
                "value": "callback_requested",
                "delay_minutes": 30,
            },
            "dnd": {"enabled": True},
            "variables": [
                {
                    "key": "customer_name",
                    "type": "string",
                    "default_value": "",
                    "required": True,
                }
            ],
        },
        "integrations": [],
        "qa": {
            "summary": True,
            "sentiment": True,
            "hallucination": True,
            "lead_score": True,
            "compliance": True,
            "hot_lead_detection": True,
        },
        "analytics": {
            "custom_variables": [],
            "outcome_mapping": {},
            "dashboard_events": [],
        },
    }


class ProcessAgentWizardCreateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.department = Department.objects.create(name="Automobile")

    def test_full_wizard_payload_creates_agent_with_nodes_and_related_rows(self):
        payload = _full_wizard_payload(self.department.id)

        response = self.client.post(
            "/api/telehub/process-agents/", payload, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        agent = ProcessAgent.objects.get(id=response.data["id"])

        self.assertEqual(agent.nodes.count(), 9)

        communication_node = agent.nodes.get(name="Communication")
        self.assertEqual(communication_node.config, payload["voice"])

        retry_node = agent.nodes.get(name="Retry")
        self.assertEqual(retry_node.config, payload["business_rules"]["retry"])

        self.assertEqual(agent.lead_sources.count(), 1)
        lead_source = agent.lead_sources.get()
        self.assertEqual(lead_source.type, "webhook")

        self.assertEqual(agent.webhooks.count(), 1)
        webhook = agent.webhooks.get()
        self.assertEqual(webhook.schema, payload["voice"]["webhook_schema"])

        self.assertEqual(agent.variables.count(), 1)
        variable = agent.variables.get()
        self.assertEqual(variable.key, "customer_name")
        self.assertTrue(variable.required)

    def test_minimal_payload_still_creates_nine_nodes_with_no_related_rows(self):
        payload = {"department": self.department.id, "name": "X"}

        response = self.client.post(
            "/api/telehub/process-agents/", payload, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        agent = ProcessAgent.objects.get(id=response.data["id"])

        self.assertEqual(agent.nodes.count(), 9)
        self.assertEqual(LeadSource.objects.filter(process_agent=agent).count(), 0)
        self.assertEqual(
            WebhookDefinition.objects.filter(process_agent=agent).count(), 0
        )
        self.assertEqual(Variable.objects.filter(process_agent=agent).count(), 0)


class ProcessAgentJourneyEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.department = Department.objects.create(name="Automobile")

    def test_journey_endpoint_returns_nine_nodes_and_eight_edges_in_order(self):
        payload = _full_wizard_payload(self.department.id)
        create_response = self.client.post(
            "/api/telehub/process-agents/", payload, format="json"
        )
        agent_id = create_response.data["id"]

        response = self.client.get(
            f"/api/telehub/process-agents/{agent_id}/journey/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["nodes"]), 9)
        self.assertEqual(len(response.data["edges"]), 8)

        nodes_by_id = {node["id"]: node for node in response.data["nodes"]}
        expected_names = [name for name, _template_type in JOURNEY_STEPS]

        # Walk edges from the node with no incoming edge to reconstruct order.
        incoming_targets = {edge["target_node"] for edge in response.data["edges"]}
        head_id = next(
            node["id"] for node in response.data["nodes"] if node["id"] not in incoming_targets
        )
        edges_by_source = {edge["source_node"]: edge for edge in response.data["edges"]}

        ordered_names = []
        current_id = head_id
        while current_id is not None:
            ordered_names.append(nodes_by_id[current_id]["name"])
            edge = edges_by_source.get(current_id)
            current_id = edge["target_node"] if edge else None

        self.assertEqual(ordered_names, expected_names)


class DepartmentApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_list_create_retrieve(self):
        create_response = self.client.post(
            "/api/telehub/departments/", {"name": "Healthcare"}, format="json"
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        department_id = create_response.data["id"]

        list_response = self.client.get("/api/telehub/departments/")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)

        retrieve_response = self.client.get(
            f"/api/telehub/departments/{department_id}/"
        )
        self.assertEqual(retrieve_response.status_code, status.HTTP_200_OK)
        self.assertEqual(retrieve_response.data["process_agent_count"], 0)
        self.assertEqual(retrieve_response.data["process_agents"], [])

    def test_retrieve_includes_nested_process_agents_with_correct_count(self):
        department = Department.objects.create(name="Automobile")

        for name in ("Free Service 1", "Free Service 2"):
            payload = _full_wizard_payload(department.id, name=name)
            response = self.client.post(
                "/api/telehub/process-agents/", payload, format="json"
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        retrieve_response = self.client.get(
            f"/api/telehub/departments/{department.id}/"
        )

        self.assertEqual(retrieve_response.status_code, status.HTTP_200_OK)
        self.assertEqual(retrieve_response.data["process_agent_count"], 2)
        self.assertEqual(len(retrieve_response.data["process_agents"]), 2)


class IntegrationApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_crud_round_trip(self):
        create_response = self.client.post(
            "/api/telehub/integrations/",
            {"name": "Chat360", "type": "crm", "configuration": {}},
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        integration_id = create_response.data["id"]

        list_response = self.client.get("/api/telehub/integrations/")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        names = [item["name"] for item in list_response.data]
        self.assertIn("Chat360", names)

        update_response = self.client.patch(
            f"/api/telehub/integrations/{integration_id}/",
            {"status": "inactive"},
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertEqual(update_response.data["status"], "inactive")

        delete_response = self.client.delete(
            f"/api/telehub/integrations/{integration_id}/"
        )
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Integration.objects.filter(id=integration_id).exists())


class NodeTemplateApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        seed_node_templates()

    def test_list_returns_eight_seeded_templates_with_expected_types(self):
        response = self.client.get("/api/telehub/node-templates/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 8)

        expected_types = {
            "trigger",
            "logic",
            "communication",
            "retry",
            "routing",
            "integration",
            "qa",
            "output",
        }
        actual_types = {item["type"] for item in response.data}
        self.assertEqual(actual_types, expected_types)
