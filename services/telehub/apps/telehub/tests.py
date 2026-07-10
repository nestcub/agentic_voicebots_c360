import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

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
from .services.callback_schedule import schedule_callback
from .services.callback_time import parse_call_back_time
from .services.campaign_launch import launch_campaign
from .services.dispatcher import dispatch_execution
from .services.gating import is_suppressed_dnc, is_within_business_hours
from .services.journey import JOURNEY_STEPS, generate_journey
from .services.ngrok import get_public_base_url
from .services.outcome_routing import route_webhook_outcome
from .services.retry_backoff import schedule_retry
from .services.seed_node_templates import seed_node_templates
from .management.commands.run_scheduler import tick


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

    def test_valid_secret_and_dlr_id_routes_outcome(self):
        agent_id, webhook = self._create_agent_with_webhook()
        execution = Execution.objects.create(process_agent_id=agent_id, lead_id="lead-1")

        response = self.client.post(
            f"/api/telehub/webhooks/{webhook.secret}/",
            {"dlr_id": execution.id, "summary": "Call went well"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        execution.refresh_from_db()
        self.assertEqual(execution.status, "completed")
        self.assertEqual(execution.current_node, "Completed")
        completed_event = ExecutionEvent.objects.get(
            execution=execution, event_type="call_completed"
        )
        self.assertEqual(completed_event.payload["summary"], "Call went well")
        self.assertEqual(execution.qa_result.summary, "Call went well")

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

    def test_launched_leads_have_next_execution_set_so_scheduler_picks_them_up(self):
        # Regression: a NULL next_execution never matches run_scheduler.tick()'s
        # next_execution__lte=now() filter, so a launched lead with no
        # next_execution would sit forever and never get dispatched.
        agent = self._create_agent()

        launch_campaign(
            agent,
            {"campaign_id": "camp-2", "leads": [{"to_number": "+911111111111"}]},
        )

        execution = Execution.objects.get(process_agent=agent, campaign_id="camp-2")
        self.assertIsNotNone(execution.next_execution)
        self.assertLessEqual(execution.next_execution, timezone.now())

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


class DispatcherTests(TestCase):
    def _make_execution(
        self,
        api_url="https://example.com/outbound",
        bot_id="bot-1",
        bot_name="Bot One",
        variables=None,
    ):
        department = Department.objects.create(name="Automobile")
        process_agent = ProcessAgent.objects.create(
            department=department, name="Dispatch Test"
        )
        generate_journey(process_agent)
        communication_node = process_agent.nodes.get(name="Communication")
        communication_node.config = {
            "api_url": api_url,
            "bot_id": bot_id,
            "bot_name": bot_name,
        }
        communication_node.save()

        return Execution.objects.create(
            process_agent=process_agent,
            lead_id="lead-1",
            status="pending",
            variables=(
                variables
                if variables is not None
                else {"to_number": "+911234567890", "@name": "Alice"}
            ),
        )

    def test_successful_dispatch_marks_dispatched_and_records_event(self):
        execution = self._make_execution()

        with patch(
            "apps.telehub.services.dispatcher.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.getcode.return_value = 200
            mock_urlopen.return_value.__enter__.return_value.read.return_value = (
                b'{"ok": true}'
            )
            result = dispatch_execution(execution)

        execution.refresh_from_db()
        self.assertEqual(execution.status, "dispatched")
        self.assertEqual(execution.attempt_count, 1)
        self.assertTrue(result["success"])
        self.assertEqual(result["status_code"], 200)
        event = ExecutionEvent.objects.get(
            execution=execution, event_type="dispatch_attempted"
        )
        self.assertEqual(event.payload["status_code"], 200)

    def test_failed_dispatch_network_error_marks_dispatch_failed(self):
        execution = self._make_execution()

        with patch(
            "apps.telehub.services.dispatcher.urllib.request.urlopen",
            side_effect=OSError("connection refused"),
        ):
            result = dispatch_execution(execution)

        execution.refresh_from_db()
        self.assertEqual(execution.status, "dispatch_failed")
        self.assertEqual(execution.attempt_count, 1)
        self.assertFalse(result["success"])
        self.assertTrue(
            ExecutionEvent.objects.filter(
                execution=execution, event_type="dispatch_failed"
            ).exists()
        )

    def test_missing_api_url_skips_http_call(self):
        execution = self._make_execution(api_url="")

        with patch(
            "apps.telehub.services.dispatcher.urllib.request.urlopen"
        ) as mock_urlopen:
            result = dispatch_execution(execution)

        mock_urlopen.assert_not_called()
        execution.refresh_from_db()
        self.assertEqual(execution.status, "dispatch_failed")
        self.assertFalse(result["success"])
        event = ExecutionEvent.objects.get(
            execution=execution, event_type="dispatch_skipped"
        )
        self.assertIn("api_url", event.payload["error"])

    def test_request_headers_and_body_shape(self):
        execution = self._make_execution(
            api_url="https://example.com/outbound",
            bot_id="bot-42",
            bot_name="Bot Forty Two",
            variables={"to_number": "+911234567890", "@name": "Charlie"},
        )

        with patch(
            "apps.telehub.services.dispatcher.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.getcode.return_value = 200
            mock_urlopen.return_value.__enter__.return_value.read.return_value = b"OK"
            dispatch_execution(execution)

        sent_request = mock_urlopen.call_args[0][0]
        self.assertTrue(sent_request.get_header("Authorization").startswith("Bearer"))
        self.assertEqual(sent_request.get_header("Content-type"), "application/json")
        self.assertIsNotNone(sent_request.get_header("Cookie"))

        body = json.loads(sent_request.data.decode())
        self.assertEqual(body["@name"], "Charlie")
        self.assertEqual(body["To"], "+911234567890")
        self.assertEqual(body["dlr_id"], execution.id)
        self.assertEqual(body["bot_id"], "bot-42")
        self.assertEqual(body["bot_name"], "Bot Forty Two")


class RetryBackoffTests(TestCase):
    def _make_execution(self, retry_config=None, attempt_count=0, set_retry_node=True):
        department = Department.objects.create(name="Automobile")
        process_agent = ProcessAgent.objects.create(
            department=department, name="Retry Test"
        )
        generate_journey(process_agent)

        if set_retry_node:
            retry_node = process_agent.nodes.get(name="Retry")
            retry_node.config = retry_config if retry_config is not None else {}
            retry_node.save()

        return Execution.objects.create(
            process_agent=process_agent,
            lead_id="lead-1",
            status="dispatch_failed",
            attempt_count=attempt_count,
        )

    def test_linear_backoff_schedules_next_execution(self):
        execution = self._make_execution(
            retry_config={"attempts": 3, "interval_minutes": 15, "strategy": "linear"},
            attempt_count=1,
        )

        result = schedule_retry(execution)

        execution.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(execution.status, "retry_scheduled")
        self.assertIsNotNone(execution.next_execution)
        delta = execution.next_execution - timezone.now()
        self.assertTrue(timedelta(minutes=14) < delta < timedelta(minutes=16))

    def test_exponential_backoff_grows_with_attempt_count(self):
        execution = self._make_execution(
            retry_config={"attempts": 5, "interval_minutes": 10, "strategy": "exponential"},
            attempt_count=2,
        )

        result = schedule_retry(execution)

        execution.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(execution.status, "retry_scheduled")
        # attempt_count=2 -> exponent = attempt_count-1 = 1 -> 10 * 2**1 = 20 minutes.
        delta = execution.next_execution - timezone.now()
        self.assertTrue(timedelta(minutes=19) < delta < timedelta(minutes=21))

    def test_exponential_backoff_first_attempt_is_one_intervals_worth(self):
        execution = self._make_execution(
            retry_config={"attempts": 5, "interval_minutes": 10, "strategy": "exponential"},
            attempt_count=0,
        )

        schedule_retry(execution)

        execution.refresh_from_db()
        delta = execution.next_execution - timezone.now()
        self.assertTrue(timedelta(minutes=9) < delta < timedelta(minutes=11))

    def test_exhausts_to_failed_after_max_attempts(self):
        execution = self._make_execution(
            retry_config={"attempts": 3, "interval_minutes": 15, "strategy": "linear"},
            attempt_count=3,
        )

        result = schedule_retry(execution)

        execution.refresh_from_db()
        self.assertFalse(result)
        self.assertEqual(execution.status, "failed")
        self.assertIsNone(execution.next_execution)

    def test_missing_retry_config_falls_back_to_defaults(self):
        execution = self._make_execution(retry_config={}, attempt_count=0)

        result = schedule_retry(execution)

        execution.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(execution.status, "retry_scheduled")
        # Defaults: attempts=3, interval_minutes=15, strategy=linear.
        delta = execution.next_execution - timezone.now()
        self.assertTrue(timedelta(minutes=14) < delta < timedelta(minutes=16))

    def test_missing_retry_node_never_raises_and_uses_defaults(self):
        execution = self._make_execution(set_retry_node=False, attempt_count=0)
        # Delete the Retry node entirely to simulate an even more degraded state.
        execution.process_agent.nodes.filter(name="Retry").delete()

        result = schedule_retry(execution)

        execution.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(execution.status, "retry_scheduled")
        delta = execution.next_execution - timezone.now()
        self.assertTrue(timedelta(minutes=14) < delta < timedelta(minutes=16))


class CallbackScheduleTests(TestCase):
    def _make_execution(self, callback_config=None, variables=None):
        department = Department.objects.create(name="Automobile")
        process_agent = ProcessAgent.objects.create(
            department=department, name="Callback Test"
        )
        generate_journey(process_agent)

        callback_node = process_agent.nodes.get(name="Callback")
        callback_node.config = callback_config if callback_config is not None else {}
        callback_node.save()

        return Execution.objects.create(
            process_agent=process_agent,
            lead_id="lead-1",
            status="dispatched",
            variables=variables or {},
        )

    def test_matches_equality_condition_and_resolves_via_regex_parser(self):
        execution = self._make_execution(
            callback_config={
                "conditions": [{"variable": "outcome", "operator": "==", "value": "callback_requested"}],
                "delay_minutes": 30,
                "time_variable": "call_back_time",
            },
            variables={"outcome": "callback_requested", "call_back_time": "5 minutes"},
        )

        result = schedule_callback(execution)

        execution.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(execution.status, "callback_scheduled")
        delta = execution.next_execution - timezone.now()
        self.assertTrue(timedelta(minutes=4) < delta < timedelta(minutes=6))

    def test_falls_back_to_delay_minutes_when_time_unparseable(self):
        execution = self._make_execution(
            callback_config={
                "conditions": [{"variable": "outcome", "operator": "==", "value": "callback_requested"}],
                "delay_minutes": 45,
                "time_variable": "call_back_time",
            },
            variables={"outcome": "callback_requested", "call_back_time": "whenever, maybe"},
        )

        result = schedule_callback(execution)

        execution.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(execution.status, "callback_scheduled")
        delta = execution.next_execution - timezone.now()
        self.assertTrue(timedelta(minutes=44) < delta < timedelta(minutes=46))

    def test_returns_false_when_no_condition_matches(self):
        execution = self._make_execution(
            callback_config={
                "conditions": [{"variable": "outcome", "operator": "==", "value": "callback_requested"}],
                "delay_minutes": 30,
                "time_variable": "call_back_time",
            },
            variables={"outcome": "completed"},
        )

        result = schedule_callback(execution)

        execution.refresh_from_db()
        self.assertFalse(result)
        self.assertEqual(execution.status, "dispatched")
        self.assertIsNone(execution.next_execution)

    def test_missing_callback_node_config_returns_false(self):
        execution = self._make_execution(callback_config={}, variables={"outcome": "callback_requested"})

        result = schedule_callback(execution)

        self.assertFalse(result)

    def test_any_condition_matching_triggers_with_numeric_and_contains_operators(self):
        execution = self._make_execution(
            callback_config={
                "conditions": [
                    {"variable": "score", "operator": ">", "value": "10"},
                    {"variable": "notes", "operator": "contains", "value": "call me"},
                ],
                "delay_minutes": 20,
                "time_variable": "call_back_time",
            },
            variables={"score": "not-a-number", "notes": "please call me back later"},
        )

        result = schedule_callback(execution)

        execution.refresh_from_db()
        # The numeric condition can't be compared (non-numeric score) and is
        # skipped rather than raising; the contains condition matches.
        self.assertTrue(result)
        self.assertEqual(execution.status, "callback_scheduled")


class DispatcherRedirectTests(TestCase):
    def _make_execution(self, api_url="https://example.com/outbound"):
        department = Department.objects.create(name="Automobile")
        process_agent = ProcessAgent.objects.create(department=department, name="Redirect Test")
        generate_journey(process_agent)
        communication_node = process_agent.nodes.get(name="Communication")
        communication_node.config = {"api_url": api_url, "bot_id": "bot-1", "bot_name": "Bot One"}
        communication_node.save()
        return Execution.objects.create(
            process_agent=process_agent,
            lead_id="lead-1",
            status="pending",
            variables={"to_number": "+911234567890"},
        )

    def test_follows_307_redirect_for_post_and_succeeds(self):
        # Regression: urllib does NOT auto-follow 307/308 for POST requests —
        # a real Chat360 trailing-slash redirect surfaced this (status_code=307,
        # dispatch_failed, even though the retried URL would have succeeded).
        execution = self._make_execution(api_url="https://example.com/outbound")

        redirect_response = MagicMock()
        redirect_response.getcode.return_value = 307
        redirect_response.read.return_value = b""
        redirect_response.headers.get.return_value = "/outbound/"

        success_response = MagicMock()
        success_response.getcode.return_value = 200
        success_response.read.return_value = b'{"ok": true}'
        success_response.headers.get.return_value = None

        with patch("apps.telehub.services.dispatcher.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.side_effect = [redirect_response, success_response]
            result = dispatch_execution(execution)

        self.assertTrue(result["success"])
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(mock_urlopen.call_count, 2)
        second_call_request = mock_urlopen.call_args_list[1][0][0]
        self.assertEqual(second_call_request.full_url, "https://example.com/outbound/")
        execution.refresh_from_db()
        self.assertEqual(execution.status, "dispatched")
        self.assertEqual(execution.attempt_count, 1)

    def test_gives_up_after_max_redirects_and_marks_dispatch_failed(self):
        execution = self._make_execution()

        looping_response = MagicMock()
        looping_response.getcode.return_value = 307
        looping_response.read.return_value = b""
        looping_response.headers.get.return_value = "/outbound/"

        with patch("apps.telehub.services.dispatcher.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = looping_response
            result = dispatch_execution(execution)

        self.assertFalse(result["success"])
        self.assertEqual(result["status_code"], 307)
        # MAX_REDIRECTS=3 hops beyond the initial attempt = 4 total requests.
        self.assertEqual(mock_urlopen.call_count, 4)
        execution.refresh_from_db()
        self.assertEqual(execution.status, "dispatch_failed")


class GatingTests(TestCase):
    def _make_process_agent(self, business_hours_config=None, dnd_config=None):
        department = Department.objects.create(name="Automobile")
        process_agent = ProcessAgent.objects.create(
            department=department, name="Gating Test"
        )
        generate_journey(process_agent)

        if business_hours_config is not None:
            node = process_agent.nodes.get(name="Business Hours")
            node.config = business_hours_config
            node.save()

        if dnd_config is not None:
            node = process_agent.nodes.get(name="DND Check")
            node.config = dnd_config
            node.save()

        return process_agent

    def test_within_configured_business_hours_returns_true(self):
        process_agent = self._make_process_agent(
            business_hours_config={
                "timezone": "Asia/Kolkata",
                "start": "09:00",
                "end": "19:00",
                "working_days": [1, 2, 3, 4, 5, 6],
            }
        )
        # Monday 2026-07-06 12:00 IST (06:30 UTC) is within 09:00-19:00 IST.
        at = datetime(2026, 7, 6, 6, 30, tzinfo=ZoneInfo("UTC"))

        self.assertTrue(is_within_business_hours(process_agent, at=at))

    def test_outside_configured_business_hours_returns_false(self):
        process_agent = self._make_process_agent(
            business_hours_config={
                "timezone": "Asia/Kolkata",
                "start": "09:00",
                "end": "19:00",
                "working_days": [1, 2, 3, 4, 5, 6],
            }
        )
        # Monday 2026-07-06 22:00 IST (16:30 UTC) is after the 19:00 IST close.
        at = datetime(2026, 7, 6, 16, 30, tzinfo=ZoneInfo("UTC"))

        self.assertFalse(is_within_business_hours(process_agent, at=at))

    def test_non_working_day_returns_false(self):
        process_agent = self._make_process_agent(
            business_hours_config={
                "timezone": "Asia/Kolkata",
                "start": "09:00",
                "end": "19:00",
                "working_days": [1, 2, 3, 4, 5, 6],
            }
        )
        # Sunday 2026-07-12 12:00 IST — Sunday (7) is not a working day.
        at = datetime(2026, 7, 12, 6, 30, tzinfo=ZoneInfo("UTC"))

        self.assertFalse(is_within_business_hours(process_agent, at=at))

    def test_missing_business_hours_config_fails_open(self):
        process_agent = self._make_process_agent(business_hours_config={})

        self.assertTrue(is_within_business_hours(process_agent))

    def test_dnd_suppressed_only_when_node_enabled_and_execution_variable_truthy(self):
        process_agent = self._make_process_agent(dnd_config={"enabled": True})
        execution = Execution.objects.create(
            process_agent=process_agent,
            lead_id="lead-1",
            variables={"dnd": "true"},
        )

        self.assertTrue(is_suppressed_dnc(execution))

    def test_dnd_not_suppressed_when_node_disabled(self):
        process_agent = self._make_process_agent(dnd_config={"enabled": False})
        execution = Execution.objects.create(
            process_agent=process_agent,
            lead_id="lead-1",
            variables={"dnd": "true"},
        )

        self.assertFalse(is_suppressed_dnc(execution))

    def test_dnd_not_suppressed_when_execution_variable_falsy(self):
        process_agent = self._make_process_agent(dnd_config={"enabled": True})
        execution = Execution.objects.create(
            process_agent=process_agent,
            lead_id="lead-1",
            variables={"dnd": "no"},
        )

        self.assertFalse(is_suppressed_dnc(execution))

    def test_missing_dnd_config_fails_open(self):
        process_agent = self._make_process_agent(dnd_config={})
        execution = Execution.objects.create(
            process_agent=process_agent,
            lead_id="lead-1",
            variables={"dnd": "true"},
        )

        self.assertFalse(is_suppressed_dnc(execution))


class SchedulerTickTests(TestCase):
    def _make_execution(
        self,
        status="pending",
        next_execution=None,
        api_url="https://example.com/outbound",
    ):
        department = Department.objects.create(name="Automobile")
        process_agent = ProcessAgent.objects.create(
            department=department, name="Scheduler Test"
        )
        generate_journey(process_agent)
        communication_node = process_agent.nodes.get(name="Communication")
        communication_node.config = {
            "api_url": api_url,
            "bot_id": "bot-1",
            "bot_name": "Bot One",
        }
        communication_node.save()

        return Execution.objects.create(
            process_agent=process_agent,
            lead_id="lead-1",
            status=status,
            variables={"to_number": "+911234567890", "@name": "Alice"},
            next_execution=(
                timezone.now() - timedelta(minutes=5)
                if next_execution is None
                else next_execution
            ),
        )

    def test_due_execution_within_hours_not_suppressed_is_dispatched(self):
        execution = self._make_execution()

        with patch(
            "apps.telehub.services.gating.is_within_business_hours",
            return_value=True,
        ), patch(
            "apps.telehub.services.gating.is_suppressed_dnc", return_value=False
        ), patch(
            "apps.telehub.services.dispatcher.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.getcode.return_value = 200
            mock_urlopen.return_value.__enter__.return_value.read.return_value = (
                b'{"ok": true}'
            )
            count = tick()

        execution.refresh_from_db()
        self.assertEqual(count, 1)
        self.assertEqual(execution.status, "dispatched")

    def test_outside_business_hours_is_skipped_not_rescheduled(self):
        execution = self._make_execution()
        original_next_execution = execution.next_execution

        with patch(
            "apps.telehub.services.gating.is_within_business_hours",
            return_value=False,
        ), patch(
            "apps.telehub.services.dispatcher.dispatch_execution"
        ) as mock_dispatch:
            count = tick()

        mock_dispatch.assert_not_called()
        execution.refresh_from_db()
        self.assertEqual(count, 0)
        self.assertEqual(execution.next_execution, original_next_execution)

    def test_dnd_suppressed_execution_is_terminated_without_dispatch(self):
        execution = self._make_execution()

        with patch(
            "apps.telehub.services.gating.is_within_business_hours",
            return_value=True,
        ), patch(
            "apps.telehub.services.gating.is_suppressed_dnc", return_value=True
        ), patch(
            "apps.telehub.services.dispatcher.dispatch_execution"
        ) as mock_dispatch:
            count = tick()

        mock_dispatch.assert_not_called()
        execution.refresh_from_db()
        self.assertEqual(count, 0)
        self.assertEqual(execution.status, "suppressed_dnc")
        self.assertIsNone(execution.next_execution)

    def test_future_next_execution_is_not_picked_up(self):
        self._make_execution(next_execution=timezone.now() + timedelta(hours=1))

        with patch(
            "apps.telehub.services.gating.is_within_business_hours",
            return_value=True,
        ), patch(
            "apps.telehub.services.dispatcher.dispatch_execution"
        ) as mock_dispatch:
            count = tick()

        mock_dispatch.assert_not_called()
        self.assertEqual(count, 0)

    def test_non_pollable_status_is_not_picked_up(self):
        self._make_execution(status="dispatched")

        with patch(
            "apps.telehub.services.gating.is_within_business_hours",
            return_value=True,
        ), patch(
            "apps.telehub.services.dispatcher.dispatch_execution"
        ) as mock_dispatch:
            count = tick()

        mock_dispatch.assert_not_called()
        self.assertEqual(count, 0)


class OutcomeRoutingTests(TestCase):
    def _make_execution(self, callback_config=None, retry_config=None, variables=None):
        department = Department.objects.create(name="Automobile")
        process_agent = ProcessAgent.objects.create(
            department=department, name="Outcome Routing Test"
        )
        generate_journey(process_agent)

        callback_node = process_agent.nodes.get(name="Callback")
        callback_node.config = callback_config if callback_config is not None else {}
        callback_node.save()

        retry_node = process_agent.nodes.get(name="Retry")
        retry_node.config = retry_config if retry_config is not None else {}
        retry_node.save()

        return Execution.objects.create(
            process_agent=process_agent,
            lead_id="lead-1",
            status="dispatched",
            variables=variables or {},
        )

    def test_successful_call_completes_runs_qa_and_crm_no_retry_or_callback(self):
        execution = self._make_execution()

        route_webhook_outcome(execution, {"summary": "Great call", "sentiment": "positive"})

        execution.refresh_from_db()
        self.assertEqual(execution.status, "completed")
        self.assertEqual(QAResult.objects.filter(execution=execution).count(), 1)
        self.assertTrue(
            ExecutionEvent.objects.filter(
                execution=execution, event_type="crm_update_triggered"
            ).exists()
        )

    def test_failure_outcome_triggers_retry_qa_and_crm_still_run(self):
        execution = self._make_execution(
            retry_config={"attempts": 3, "interval_minutes": 15, "strategy": "linear"}
        )

        route_webhook_outcome(execution, {"outcome": "no_answer"})

        execution.refresh_from_db()
        self.assertEqual(execution.status, "retry_scheduled")
        self.assertIsNotNone(execution.next_execution)
        self.assertEqual(QAResult.objects.filter(execution=execution).count(), 1)
        self.assertTrue(
            ExecutionEvent.objects.filter(
                execution=execution, event_type="crm_update_triggered"
            ).exists()
        )

    def test_matching_callback_condition_takes_priority_over_retry(self):
        execution = self._make_execution(
            callback_config={
                "conditions": [{"variable": "outcome", "operator": "==", "value": "callback_requested"}],
                "delay_minutes": 30,
            },
            retry_config={"attempts": 3, "interval_minutes": 15, "strategy": "linear"},
            variables={},
        )

        with patch(
            "apps.telehub.services.outcome_routing.retry_backoff.schedule_retry"
        ) as mock_retry:
            route_webhook_outcome(execution, {"outcome": "callback_requested"})

        mock_retry.assert_not_called()
        execution.refresh_from_db()
        self.assertEqual(execution.status, "callback_scheduled")
        self.assertIsNotNone(execution.next_execution)

    def test_duplicate_webhook_delivery_does_not_raise_or_duplicate_qa_result(self):
        execution = self._make_execution()

        route_webhook_outcome(execution, {"summary": "first delivery"})
        route_webhook_outcome(execution, {"summary": "duplicate delivery"})

        self.assertEqual(QAResult.objects.filter(execution=execution).count(), 1)

    def test_full_http_round_trip_creates_qa_result(self):
        department = Department.objects.create(name="Automobile")
        payload = _full_wizard_payload(department.id)
        client = APIClient()
        create_response = client.post("/api/telehub/process-agents/", payload, format="json")
        agent_id = create_response.data["id"]
        webhook = WebhookDefinition.objects.get(process_agent_id=agent_id)
        execution = Execution.objects.create(process_agent_id=agent_id, lead_id="lead-http")

        response = client.post(
            f"/api/telehub/webhooks/{webhook.secret}/",
            {"dlr_id": execution.id, "summary": "HTTP round trip", "sentiment": "neutral"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        execution.refresh_from_db()
        self.assertEqual(execution.qa_result.summary, "HTTP round trip")
        self.assertEqual(execution.qa_result.sentiment, "neutral")
