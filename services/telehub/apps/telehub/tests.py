from datetime import datetime, timedelta
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from .models import (
    Department,
    Execution,
    ExecutionEvent,
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
from .services.callback_time import parse_call_back_time
from .services.campaign_launch import launch_campaign
from .services.journey import JOURNEY_STEPS, generate_journey
from .services.ngrok import get_public_base_url
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

    def test_generate_journey_creates_nine_nodes_and_ten_connections(self):
        process_agent = self._make_process_agent()

        generate_journey(process_agent)

        self.assertEqual(process_agent.nodes.count(), 9)
        self.assertEqual(process_agent.connections.count(), 10)

    def test_main_trunk_runs_lead_to_completed(self):
        process_agent = self._make_process_agent()
        generate_journey(process_agent)
        nodes_by_name = {node.name: node for node in process_agent.nodes.all()}

        def target_of(name):
            edge = nodes_by_name[name].outgoing_connections.get()
            return edge.target_node.name

        self.assertEqual(target_of("Lead Received"), "Business Hours")
        self.assertEqual(target_of("Business Hours"), "DND Check")
        self.assertEqual(target_of("DND Check"), "Communication")
        self.assertEqual(target_of("Communication"), "Completed")

    def test_completed_branches_to_retry_callback_qa_crm_update(self):
        process_agent = self._make_process_agent()
        generate_journey(process_agent)
        nodes_by_name = {node.name: node for node in process_agent.nodes.all()}

        edges = nodes_by_name["Completed"].outgoing_connections.all()
        targets = {edge.target_node.name for edge in edges}
        self.assertEqual(targets, {"Retry", "Callback", "QA", "CRM Update"})

        condition_by_target = {edge.target_node.name: edge.condition for edge in edges}
        self.assertEqual(condition_by_target["Retry"], "failed")
        self.assertEqual(condition_by_target["Callback"], "callback_requested")
        self.assertEqual(condition_by_target["QA"], "")
        self.assertEqual(condition_by_target["CRM Update"], "")

    def test_retry_and_callback_loop_back_to_business_hours(self):
        process_agent = self._make_process_agent()
        generate_journey(process_agent)
        nodes_by_name = {node.name: node for node in process_agent.nodes.all()}

        self.assertEqual(
            nodes_by_name["Retry"].outgoing_connections.get().target_node.name,
            "Business Hours",
        )
        self.assertEqual(
            nodes_by_name["Callback"].outgoing_connections.get().target_node.name,
            "Business Hours",
        )

    def test_qa_and_crm_update_are_terminal(self):
        process_agent = self._make_process_agent()
        generate_journey(process_agent)
        nodes_by_name = {node.name: node for node in process_agent.nodes.all()}

        self.assertFalse(nodes_by_name["QA"].outgoing_connections.exists())
        self.assertFalse(nodes_by_name["CRM Update"].outgoing_connections.exists())

    def test_generate_journey_is_idempotent(self):
        process_agent = self._make_process_agent()

        generate_journey(process_agent)
        generate_journey(process_agent)

        self.assertEqual(process_agent.nodes.count(), 9)
        self.assertEqual(process_agent.connections.count(), 10)

    def test_each_node_instance_uses_expected_node_template_type(self):
        process_agent = self._make_process_agent()

        generate_journey(process_agent)

        nodes_by_name = {node.name: node for node in process_agent.nodes.all()}
        for name, expected_template_type, _x, _y in JOURNEY_STEPS:
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

    def test_journey_endpoint_returns_nine_nodes_and_ten_edges(self):
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
        self.assertEqual(len(response.data["edges"]), 10)

        node_names = {node["id"]: node["name"] for node in response.data["nodes"]}
        expected_names = {name for name, _template_type, _x, _y in JOURNEY_STEPS}
        self.assertEqual(set(node_names.values()), expected_names)

        # Main trunk: Lead Received -> Business Hours -> DND Check -> Communication -> Completed.
        edges_by_source_name = {}
        condition_by_source_target = {}
        for edge in response.data["edges"]:
            source_name = node_names[edge["source_node"]]
            target_name = node_names[edge["target_node"]]
            edges_by_source_name.setdefault(source_name, set()).add(target_name)
            condition_by_source_target[(source_name, target_name)] = edge["condition"]

        self.assertEqual(edges_by_source_name["Lead Received"], {"Business Hours"})
        self.assertEqual(edges_by_source_name["Business Hours"], {"DND Check"})
        self.assertEqual(edges_by_source_name["DND Check"], {"Communication"})
        self.assertEqual(edges_by_source_name["Communication"], {"Completed"})

        # Completed fans out to the 4 outcome branches. Retry and Callback are
        # conditioned on the call outcome; QA and CRM Update always fire.
        self.assertEqual(edges_by_source_name["Completed"], {"Retry", "Callback", "QA", "CRM Update"})
        self.assertEqual(condition_by_source_target[("Completed", "Retry")], "failed")
        self.assertEqual(condition_by_source_target[("Completed", "Callback")], "callback_requested")
        self.assertEqual(condition_by_source_target[("Completed", "QA")], "")
        self.assertEqual(condition_by_source_target[("Completed", "CRM Update")], "")

        # Retry and Callback loop back to Business Hours; QA/CRM Update are terminal.
        self.assertEqual(edges_by_source_name["Retry"], {"Business Hours"})
        self.assertEqual(edges_by_source_name["Callback"], {"Business Hours"})
        self.assertNotIn("QA", edges_by_source_name)
        self.assertNotIn("CRM Update", edges_by_source_name)


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


class CallbackTimeParsingTests(TestCase):
    def test_relative_hindi_minutes(self):
        result = parse_call_back_time("5 मिनट बाद")
        self.assertIsNotNone(result)
        delta = result - timezone.now()
        self.assertTrue(timedelta(minutes=4) < delta < timedelta(minutes=6))

    def test_relative_hinglish_minutes(self):
        result = parse_call_back_time("5 minute baad")
        self.assertIsNotNone(result)
        delta = result - timezone.now()
        self.assertTrue(timedelta(minutes=4) < delta < timedelta(minutes=6))

    def test_relative_hours_english(self):
        result = parse_call_back_time("2 hours")
        self.assertIsNotNone(result)
        delta = result - timezone.now()
        self.assertTrue(timedelta(hours=1, minutes=59) < delta < timedelta(hours=2, minutes=1))

    def test_devanagari_digits_normalized(self):
        result = parse_call_back_time("५ मिनट बाद")
        self.assertIsNotNone(result)
        delta = result - timezone.now()
        self.assertTrue(timedelta(minutes=4) < delta < timedelta(minutes=6))

    def test_absolute_chat360_format(self):
        result = parse_call_back_time("08-07-2026 05:00 PM")
        self.assertIsNotNone(result)
        self.assertEqual((result.day, result.month, result.year, result.hour), (8, 7, 2026, 17))

    def test_unparseable_returns_none(self):
        self.assertIsNone(parse_call_back_time("whenever, maybe tomorrow"))
        self.assertIsNone(parse_call_back_time(""))
        self.assertIsNone(parse_call_back_time(None))


class NgrokPublicBaseUrlTests(TestCase):
    def test_returns_https_tunnel_when_ngrok_running(self):
        fake_response = {
            "tunnels": [
                {"proto": "http", "public_url": "http://abc123.ngrok-free.app"},
                {"proto": "https", "public_url": "https://abc123.ngrok-free.app"},
            ]
        }
        with patch("apps.telehub.services.ngrok.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = (
                __import__("json").dumps(fake_response).encode()
            )
            self.assertEqual(get_public_base_url(), "https://abc123.ngrok-free.app")

    def test_returns_none_when_ngrok_not_running(self):
        with patch("apps.telehub.services.ngrok.urllib.request.urlopen", side_effect=OSError):
            self.assertIsNone(get_public_base_url())


class WebhookIntakeTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.department = Department.objects.create(name="Automobile")

    def _create_agent_with_webhook(self):
        payload = _full_wizard_payload(self.department.id)
        response = self.client.post("/api/telehub/process-agents/", payload, format="json")
        agent_id = response.data["id"]
        webhook = WebhookDefinition.objects.get(process_agent_id=agent_id)
        return agent_id, webhook

    def test_valid_secret_and_dlr_id_records_execution_event(self):
        agent_id, webhook = self._create_agent_with_webhook()
        execution = Execution.objects.create(process_agent_id=agent_id, lead_id="lead-1")

        response = self.client.post(
            f"/api/telehub/webhooks/{webhook.secret}/",
            {"dlr_id": execution.id, "summary": "Call went well"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        event = ExecutionEvent.objects.get(execution=execution)
        self.assertEqual(event.event_type, "webhook_received")
        self.assertEqual(event.payload["summary"], "Call went well")

    def test_unknown_secret_still_acks_200(self):
        response = self.client.post(
            "/api/telehub/webhooks/not-a-real-secret/", {"dlr_id": 1}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_missing_dlr_id_still_acks_200_and_records_nothing(self):
        agent_id, webhook = self._create_agent_with_webhook()

        response = self.client.post(
            f"/api/telehub/webhooks/{webhook.secret}/", {"summary": "no dlr_id"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(ExecutionEvent.objects.exists())


class WebhookPublicUrlSerializationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.department = Department.objects.create(name="Automobile")

    def test_public_url_none_when_ngrok_not_running(self):
        payload = _full_wizard_payload(self.department.id)
        create_response = self.client.post(
            "/api/telehub/process-agents/", payload, format="json"
        )
        agent_id = create_response.data["id"]

        with patch("apps.telehub.api.serializers.get_public_base_url", return_value=None):
            response = self.client.get(f"/api/telehub/process-agents/{agent_id}/")

        webhook = response.data["webhooks"][0]
        self.assertIsNone(webhook["public_url"])
        self.assertTrue(webhook["url"].startswith("/api/telehub/webhooks/"))

    def test_public_url_composed_from_ngrok_base_when_running(self):
        payload = _full_wizard_payload(self.department.id)
        create_response = self.client.post(
            "/api/telehub/process-agents/", payload, format="json"
        )
        agent_id = create_response.data["id"]

        with patch(
            "apps.telehub.api.serializers.get_public_base_url",
            return_value="https://abc123.ngrok-free.app",
        ):
            response = self.client.get(f"/api/telehub/process-agents/{agent_id}/")

        webhook = response.data["webhooks"][0]
        self.assertTrue(webhook["public_url"].startswith("https://abc123.ngrok-free.app/api/telehub/webhooks/"))


class CampaignLaunchServiceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.department = Department.objects.create(name="Automobile")

    def _create_agent(self, name="Free Service 1"):
        payload = _full_wizard_payload(self.department.id, name=name)
        response = self.client.post(
            "/api/telehub/process-agents/", payload, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return ProcessAgent.objects.get(id=response.data["id"])

    def test_launch_campaign_creates_valid_leads_and_skips_missing_to_number(self):
        agent = self._create_agent()

        result = launch_campaign(
            agent,
            {
                "campaign_id": "camp-1",
                "leads": [
                    {"to_number": "+911234567890", "params": {"name": "Alice"}, "lead_id": "lead-a"},
                    {"to_number": "+919876543210", "params": {"name": "Bob"}, "dnd": "19:00-09:00"},
                    {"params": {"name": "NoNumber"}, "lead_id": "lead-c"},
                ],
            },
        )

        self.assertEqual(result["campaign_id"], "camp-1")
        self.assertEqual(result["created_count"], 2)
        self.assertEqual(result["skipped"], ["lead-c"])

        executions = Execution.objects.filter(process_agent=agent, campaign_id="camp-1")
        self.assertEqual(executions.count(), 2)

        alice = executions.get(lead_id="lead-a")
        self.assertEqual(alice.status, "pending")
        self.assertEqual(alice.current_node, "Lead Received")
        self.assertEqual(alice.variables, {"name": "Alice", "to_number": "+911234567890"})

        bob = executions.get(lead_id="camp-1-1")
        self.assertEqual(bob.status, "pending")
        self.assertEqual(bob.current_node, "Lead Received")
        self.assertEqual(
            bob.variables,
            {"name": "Bob", "to_number": "+919876543210", "dnd": "19:00-09:00"},
        )

    def test_missing_to_number_without_lead_id_uses_row_index(self):
        agent = self._create_agent()

        result = launch_campaign(
            agent,
            {
                "campaign_id": "camp-2",
                "leads": [{"params": {}}],
            },
        )

        self.assertEqual(result["created_count"], 0)
        self.assertEqual(result["skipped"], ["row-0"])


class CampaignLaunchApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.department = Department.objects.create(name="Automobile")

    def _create_agent(self, name="Free Service 1"):
        payload = _full_wizard_payload(self.department.id, name=name)
        response = self.client.post(
            "/api/telehub/process-agents/", payload, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response.data["id"]

    def test_launch_campaign_endpoint_returns_created_shape(self):
        agent_id = self._create_agent()

        response = self.client.post(
            f"/api/telehub/process-agents/{agent_id}/launch-campaign/",
            {
                "campaign_id": "camp-x",
                "leads": [
                    {"to_number": "+911111111111", "params": {"@name": "Charlie"}},
                    {"to_number": "+922222222222", "params": {"@name": "Dana"}},
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["campaign_id"], "camp-x")
        self.assertEqual(response.data["created_count"], 2)
        self.assertEqual(response.data["skipped"], [])

    def test_campaigns_endpoint_shows_campaign_with_correct_lead_count(self):
        agent_id = self._create_agent()
        self.client.post(
            f"/api/telehub/process-agents/{agent_id}/launch-campaign/",
            {
                "campaign_id": "camp-y",
                "leads": [
                    {"to_number": "+911111111111", "params": {}},
                    {"to_number": "+922222222222", "params": {}},
                    {"to_number": "+933333333333", "params": {}},
                ],
            },
            format="json",
        )

        response = self.client.get(f"/api/telehub/process-agents/{agent_id}/campaigns/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["campaign_id"], "camp-y")
        self.assertEqual(response.data[0]["lead_count"], 3)
        self.assertIn("created_at", response.data[0])

    def test_campaign_leads_endpoint_returns_executions_with_variables_intact(self):
        agent_id = self._create_agent()
        self.client.post(
            f"/api/telehub/process-agents/{agent_id}/launch-campaign/",
            {
                "campaign_id": "camp-z",
                "leads": [
                    {"to_number": "+911111111111", "params": {"@name": "Eve"}, "lead_id": "lead-eve"},
                ],
            },
            format="json",
        )

        response = self.client.get(
            f"/api/telehub/process-agents/{agent_id}/campaigns/camp-z/leads/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        lead = response.data[0]
        self.assertEqual(lead["lead_id"], "lead-eve")
        self.assertEqual(lead["status"], "pending")
        self.assertEqual(lead["current_node"], "Lead Received")
        self.assertEqual(lead["variables"]["@name"], "Eve")
        self.assertEqual(lead["variables"]["to_number"], "+911111111111")
        self.assertIn("created_at", lead)
        self.assertIn("id", lead)

    def test_two_campaigns_under_same_agent_have_no_cross_contamination(self):
        agent_id = self._create_agent()
        self.client.post(
            f"/api/telehub/process-agents/{agent_id}/launch-campaign/",
            {
                "campaign_id": "camp-alpha",
                "leads": [
                    {"to_number": "+911111111111", "params": {}},
                    {"to_number": "+922222222222", "params": {}},
                ],
            },
            format="json",
        )
        self.client.post(
            f"/api/telehub/process-agents/{agent_id}/launch-campaign/",
            {
                "campaign_id": "camp-beta",
                "leads": [
                    {"to_number": "+933333333333", "params": {}},
                ],
            },
            format="json",
        )

        response = self.client.get(f"/api/telehub/process-agents/{agent_id}/campaigns/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

        by_id = {row["campaign_id"]: row for row in response.data}
        self.assertEqual(by_id["camp-alpha"]["lead_count"], 2)
        self.assertEqual(by_id["camp-beta"]["lead_count"], 1)

        # Most recent campaign (camp-beta, launched second) should come first.
        self.assertEqual(response.data[0]["campaign_id"], "camp-beta")

        alpha_leads = self.client.get(
            f"/api/telehub/process-agents/{agent_id}/campaigns/camp-alpha/leads/"
        )
        beta_leads = self.client.get(
            f"/api/telehub/process-agents/{agent_id}/campaigns/camp-beta/leads/"
        )
        self.assertEqual(len(alpha_leads.data), 2)
        self.assertEqual(len(beta_leads.data), 1)
