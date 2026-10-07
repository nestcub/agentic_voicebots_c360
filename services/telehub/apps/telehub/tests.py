import json
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from .models import (
    BotJourney,
    Department,
    Execution,
    ExecutionEvent,
    Integration,
    LeadSource,
    NodeConnection,
    NodeInstance,
    NodeTemplate,
    OmnichannelConfig,
    ProcessAgent,
    Variable,
    VoiceBot,
    WebhookDefinition,
    WhatsAppSend,
    ProcessIntegration,
    QAResult,
)
from .services import hyundai_whatsapp
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


def _full_wizard_payload(department_id, name="Free Service 1", voice_bot_id=None):
    if voice_bot_id is None:
        # "Full" payload implies a bot is attached — callers that want no bot
        # attached should build their own minimal payload instead.
        voice_bot_id = VoiceBot.objects.create(
            communication_type="voice_outbound",
            webhook_schema={"summary": "", "transcript": "", "sentiment": "", "outcome": ""},
        ).id
    return {
        "department": department_id,
        "name": name,
        "description": "",
        "voice": {"voice_bot_id": voice_bot_id},
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
        webhook_schema = {"summary": "", "transcript": "", "sentiment": "", "outcome": ""}
        voice_bot = VoiceBot.objects.create(
            communication_type="voice_outbound",
            bot_name="Sales Bot",
            bot_id="bot-1",
            api_url="https://example.com/outbound",
            webhook_schema=webhook_schema,
        )
        payload = _full_wizard_payload(self.department.id, voice_bot_id=voice_bot.id)

        response = self.client.post(
            "/api/telehub/process-agents/", payload, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        agent = ProcessAgent.objects.get(id=response.data["id"])

        self.assertEqual(agent.nodes.count(), 9)

        communication_node = agent.nodes.get(name="Communication")
        self.assertEqual(communication_node.config["bot_name"], "Sales Bot")
        self.assertEqual(communication_node.config["bot_id"], "bot-1")
        self.assertEqual(communication_node.config["api_url"], "https://example.com/outbound")

        bot_journey = agent.bot_journeys.get(order=0)
        self.assertEqual(bot_journey.voice_bot_id, voice_bot.id)

        retry_node = agent.nodes.get(name="Retry")
        self.assertEqual(retry_node.config, payload["business_rules"]["retry"])

        self.assertEqual(agent.lead_sources.count(), 1)
        lead_source = agent.lead_sources.get()
        self.assertEqual(lead_source.type, "webhook")

        self.assertEqual(agent.webhooks.count(), 1)
        webhook = agent.webhooks.get()
        self.assertEqual(webhook.schema, webhook_schema)

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


@patch.dict(os.environ, {"PUBLIC_BASE_URL": ""})
class NgrokPublicBaseUrlTests(TestCase):
    def test_public_base_url_env_takes_precedence_over_ngrok(self):
        with patch.dict(os.environ, {"PUBLIC_BASE_URL": "https://telehub-api.onrender.com/"}), \
                patch("apps.telehub.services.ngrok.urllib.request.urlopen") as mock_urlopen:
            self.assertEqual(get_public_base_url(), "https://telehub-api.onrender.com")
            mock_urlopen.assert_not_called()

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

    def test_no_dlr_id_falls_back_to_contact_no_match(self):
        """
        Mirrors Chat360's real post-call payload for this voicebot integration,
        which never includes dlr_id (confirmed against voicebot_webhook.php) —
        only contact_no, in whatever format the bot captured it.
        """
        agent_id, webhook = self._create_agent_with_webhook()
        execution = Execution.objects.create(
            process_agent_id=agent_id,
            lead_id="lead-1",
            variables={"to_number": "9876543210"},
        )

        response = self.client.post(
            f"/api/telehub/webhooks/{webhook.secret}/",
            {"contact_no": "+919876543210", "summary": "Call went well"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        execution.refresh_from_db()
        self.assertEqual(execution.status, "completed")
        self.assertEqual(execution.qa_result.summary, "Call went well")

    def test_contact_no_match_ignores_already_completed_executions(self):
        agent_id, webhook = self._create_agent_with_webhook()
        Execution.objects.create(
            process_agent_id=agent_id,
            lead_id="lead-1",
            status="completed",
            variables={"to_number": "9876543210"},
        )

        response = self.client.post(
            f"/api/telehub/webhooks/{webhook.secret}/",
            {"contact_no": "9876543210", "summary": "duplicate delivery"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(ExecutionEvent.objects.exists())


class ProcessAgentStatsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.department = Department.objects.create(name="Automobile")
        payload = _full_wizard_payload(self.department.id)
        response = self.client.post("/api/telehub/process-agents/", payload, format="json")
        self.agent_id = response.data["id"]

    def test_no_executions_returns_none_not_zero(self):
        response = self.client.get(f"/api/telehub/process-agents/{self.agent_id}/stats/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["calls"], 0)
        self.assertEqual(response.data["connected"], 0)
        self.assertIsNone(response.data["avg_duration_seconds"])
        self.assertIsNone(response.data["qa_score"])

    def test_connected_and_avg_duration_from_variables(self):
        Execution.objects.create(
            process_agent_id=self.agent_id,
            lead_id="connected-1",
            variables={"call_duration": "40"},
        )
        Execution.objects.create(
            process_agent_id=self.agent_id,
            lead_id="not-connected-1",
            variables={"outcome": "no_answer"},
        )

        response = self.client.get(f"/api/telehub/process-agents/{self.agent_id}/stats/")

        self.assertEqual(response.data["calls"], 2)
        self.assertEqual(response.data["connected"], 1)
        self.assertEqual(response.data["avg_duration_seconds"], 40.0)

    def test_hot_leads_and_callback_requests_counted(self):
        execution = Execution.objects.create(
            process_agent_id=self.agent_id, lead_id="hot-1", status="callback_scheduled"
        )
        QAResult.objects.create(execution=execution, hot_lead=True, lead_score=8)

        response = self.client.get(f"/api/telehub/process-agents/{self.agent_id}/stats/")

        self.assertEqual(response.data["hot_leads"], 1)
        self.assertEqual(response.data["callback_requests"], 1)
        self.assertEqual(response.data["qa_score"], 8.0)


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

    def test_explicit_leads_are_persisted_onto_lead_source(self):
        agent = self._create_agent()

        launch_campaign(
            agent,
            {
                "campaign_id": "camp-3",
                "leads": [{"to_number": "+911111111111", "params": {"name": "Alice"}}],
            },
        )

        lead_source = LeadSource.objects.get(process_agent=agent)
        self.assertEqual(
            lead_source.configuration["leads"],
            [{"to_number": "+911111111111", "params": {"name": "Alice"}}],
        )

    def test_omitted_leads_falls_back_to_stored_lead_source(self):
        agent = self._create_agent()
        LeadSource.objects.create(
            process_agent=agent,
            type="upload",
            configuration={"leads": [{"to_number": "+922222222222", "params": {"name": "Bob"}}]},
        )

        result = launch_campaign(agent, {"campaign_id": "camp-4"})

        self.assertEqual(result["created_count"], 1)
        execution = Execution.objects.get(process_agent=agent, campaign_id="camp-4")
        self.assertEqual(execution.variables["to_number"], "+922222222222")

    def test_omitted_leads_falls_back_to_single_source_number(self):
        agent = self._create_agent()
        LeadSource.objects.create(
            process_agent=agent,
            type="single_source",
            configuration={"number": "+919999999999"},
        )

        result = launch_campaign(agent, {"campaign_id": "camp-5"})

        self.assertEqual(result["created_count"], 1)
        execution = Execution.objects.get(process_agent=agent, campaign_id="camp-5")
        self.assertEqual(execution.variables["to_number"], "+919999999999")
        self.assertEqual(execution.lead_id, "single-source")


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


class LeadSourceEndpointTests(TestCase):
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

    def test_get_returns_the_lead_source_created_by_the_wizard(self):
        agent_id = self._create_agent()

        response = self.client.get(f"/api/telehub/process-agents/{agent_id}/lead-source/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("type", response.data)

    def test_get_returns_empty_object_when_no_lead_source_exists(self):
        agent = ProcessAgent.objects.create(department=self.department, name="Bare Agent")

        response = self.client.get(f"/api/telehub/process-agents/{agent.id}/lead-source/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {})

    def test_patch_updates_existing_lead_source_configuration(self):
        agent_id = self._create_agent()

        response = self.client.patch(
            f"/api/telehub/process-agents/{agent_id}/lead-source/",
            {"configuration": {"leads": [{"to_number": "+911111111111"}]}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["configuration"]["leads"], [{"to_number": "+911111111111"}]
        )
        self.assertEqual(
            LeadSource.objects.filter(process_agent_id=agent_id).count(), 1
        )

    def test_patch_creates_lead_source_when_none_exists(self):
        agent = ProcessAgent.objects.create(department=self.department, name="Bare Agent")

        response = self.client.patch(
            f"/api/telehub/process-agents/{agent.id}/lead-source/",
            {"type": "crm", "configuration": {"endpoint": "https://crm.example/leads"}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["type"], "crm")
        self.assertEqual(LeadSource.objects.filter(process_agent=agent).count(), 1)


class QaConfigEndpointTests(TestCase):
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

    def test_get_returns_qa_node_config(self):
        agent_id = self._create_agent()

        response = self.client.get(f"/api/telehub/process-agents/{agent_id}/qa-config/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_get_returns_empty_object_when_no_journey_exists(self):
        agent = ProcessAgent.objects.create(department=self.department, name="Bare Agent")

        response = self.client.get(f"/api/telehub/process-agents/{agent.id}/qa-config/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {})

    def test_patch_updates_qa_toggles(self):
        agent_id = self._create_agent()

        response = self.client.patch(
            f"/api/telehub/process-agents/{agent_id}/qa-config/",
            {"missing_variables": True, "drop_off_analysis": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["missing_variables"], True)
        self.assertEqual(response.data["drop_off_analysis"], True)

    def test_patch_rejects_unknown_key(self):
        agent_id = self._create_agent()

        response = self.client.patch(
            f"/api/telehub/process-agents/{agent_id}/qa-config/",
            {"not_a_real_field": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_400s_when_no_journey_exists(self):
        agent = ProcessAgent.objects.create(department=self.department, name="Bare Agent")

        response = self.client.patch(
            f"/api/telehub/process-agents/{agent.id}/qa-config/",
            {"missing_variables": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class AnalyticsStatsConfigEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.department = Department.objects.create(name="Automobile")

    def test_get_returns_empty_dict_by_default(self):
        agent = ProcessAgent.objects.create(department=self.department, name="Bare Agent")

        response = self.client.get(f"/api/telehub/process-agents/{agent.id}/analytics-stats/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {})

    def test_patch_merges_toggles(self):
        agent = ProcessAgent.objects.create(
            department=self.department, name="Bare Agent", analytics_stats={"initiated_calls": True}
        )

        response = self.client.patch(
            f"/api/telehub/process-agents/{agent.id}/analytics-stats/",
            {"completed_calls": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["initiated_calls"], True)
        self.assertEqual(response.data["completed_calls"], True)
        agent.refresh_from_db()
        self.assertEqual(agent.analytics_stats["initiated_calls"], True)
        self.assertEqual(agent.analytics_stats["completed_calls"], True)

    def test_patch_rejects_unknown_key(self):
        agent = ProcessAgent.objects.create(department=self.department, name="Bare Agent")

        response = self.client.patch(
            f"/api/telehub/process-agents/{agent.id}/analytics-stats/",
            {"not_a_real_stat": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class VariableEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.department = Department.objects.create(name="Automobile")
        self.agent = ProcessAgent.objects.create(department=self.department, name="Bare Agent")

    def test_get_lists_variables(self):
        Variable.objects.create(process_agent=self.agent, key="customer_name")

        response = self.client.get(f"/api/telehub/process-agents/{self.agent.id}/variables/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_post_creates_variable(self):
        response = self.client.post(
            f"/api/telehub/process-agents/{self.agent.id}/variables/",
            {"key": "customer_name", "type": "string", "required": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(
            Variable.objects.filter(process_agent=self.agent, key="customer_name").count(), 1
        )

    def test_post_rejects_duplicate_key_and_source(self):
        Variable.objects.create(process_agent=self.agent, key="customer_name")

        response = self.client.post(
            f"/api/telehub/process-agents/{self.agent.id}/variables/",
            {"key": "customer_name"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_post_rejects_missing_key(self):
        response = self.client.post(
            f"/api/telehub/process-agents/{self.agent.id}/variables/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_updates_variable(self):
        variable = Variable.objects.create(process_agent=self.agent, key="customer_name")

        response = self.client.patch(
            f"/api/telehub/process-agents/{self.agent.id}/variables/{variable.id}/",
            {"label": "Customer Name"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        variable.refresh_from_db()
        self.assertEqual(variable.label, "Customer Name")

    def test_patch_404s_for_unknown_variable(self):
        response = self.client.patch(
            f"/api/telehub/process-agents/{self.agent.id}/variables/99999/",
            {"label": "x"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_removes_variable(self):
        variable = Variable.objects.create(process_agent=self.agent, key="customer_name")

        response = self.client.delete(
            f"/api/telehub/process-agents/{self.agent.id}/variables/{variable.id}/"
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Variable.objects.filter(pk=variable.id).count(), 0)


class WebhookDetailEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.department = Department.objects.create(name="Automobile")
        self.agent = ProcessAgent.objects.create(department=self.department, name="Bare Agent")

    def test_patch_updates_editable_fields_only(self):
        webhook = WebhookDefinition.objects.create(
            process_agent=self.agent,
            name="Old Name",
            url="/api/telehub/webhooks/abc123/",
            secret="abc123",
            status="active",
        )

        response = self.client.patch(
            f"/api/telehub/process-agents/{self.agent.id}/webhooks/{webhook.id}/",
            {"name": "New Name", "status": "disabled", "url": "/should/not/change/", "secret": "hacked"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        webhook.refresh_from_db()
        self.assertEqual(webhook.name, "New Name")
        self.assertEqual(webhook.status, "disabled")
        self.assertEqual(webhook.url, "/api/telehub/webhooks/abc123/")
        self.assertEqual(webhook.secret, "abc123")

    def test_patch_404s_for_unknown_webhook(self):
        response = self.client.patch(
            f"/api/telehub/process-agents/{self.agent.id}/webhooks/99999/",
            {"name": "x"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class OmnichannelConfigEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.department = Department.objects.create(name="Automobile")
        self.agent = ProcessAgent.objects.create(department=self.department, name="Bare Agent")

    def test_get_returns_empty_object_when_none_exists(self):
        response = self.client.get(f"/api/telehub/process-agents/{self.agent.id}/omnichannel/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {})

    def test_patch_creates_when_none_exists(self):
        response = self.client.patch(
            f"/api/telehub/process-agents/{self.agent.id}/omnichannel/",
            {"channel": "whatsapp", "variables": ["customer_name"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["channel"], "whatsapp")
        self.assertEqual(OmnichannelConfig.objects.filter(process_agent=self.agent).count(), 1)

    def test_patch_updates_existing(self):
        OmnichannelConfig.objects.create(process_agent=self.agent, channel="whatsapp")

        response = self.client.patch(
            f"/api/telehub/process-agents/{self.agent.id}/omnichannel/",
            {"whatsapp_template": "template_1"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            OmnichannelConfig.objects.filter(process_agent=self.agent).count(), 1
        )
        self.assertEqual(response.data["whatsapp_template"], "template_1")


class IntegrationAttachDetachEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.department = Department.objects.create(name="Automobile")
        self.agent = ProcessAgent.objects.create(department=self.department, name="Bare Agent")
        self.integration = Integration.objects.create(name="CRM X", type="crm")

    def test_post_attaches_integration(self):
        response = self.client.post(
            f"/api/telehub/process-agents/{self.agent.id}/integrations/",
            {"integration": self.integration.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(
            ProcessIntegration.objects.filter(
                process_agent=self.agent, integration=self.integration
            ).count(),
            1,
        )

    def test_post_is_idempotent(self):
        self.client.post(
            f"/api/telehub/process-agents/{self.agent.id}/integrations/",
            {"integration": self.integration.id},
            format="json",
        )
        response = self.client.post(
            f"/api/telehub/process-agents/{self.agent.id}/integrations/",
            {"integration": self.integration.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            ProcessIntegration.objects.filter(
                process_agent=self.agent, integration=self.integration
            ).count(),
            1,
        )

    def test_post_rejects_unknown_integration(self):
        response = self.client.post(
            f"/api/telehub/process-agents/{self.agent.id}/integrations/",
            {"integration": 99999},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_removes_link_not_integration(self):
        link = ProcessIntegration.objects.create(
            process_agent=self.agent, integration=self.integration
        )

        response = self.client.delete(
            f"/api/telehub/process-agents/{self.agent.id}/integrations/{link.id}/"
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(ProcessIntegration.objects.filter(pk=link.id).count(), 0)
        self.assertEqual(Integration.objects.filter(pk=self.integration.id).count(), 1)


class VoiceBotEndpointTests(TestCase):
    """VoiceBot is a global library (no process_agent FK) — see
    dashboard's /bots page and services/process_agent.py."""

    def setUp(self):
        self.client = APIClient()
        self.department = Department.objects.create(name="Automobile")
        self.agent = ProcessAgent.objects.create(department=self.department, name="Bare Agent")

    def test_get_lists_voice_bots(self):
        VoiceBot.objects.create(bot_name="Sales Bot")

        response = self.client.get("/api/telehub/voice-bots/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_post_creates_unattached_voice_bot(self):
        response = self.client.post(
            "/api/telehub/voice-bots/",
            {"label": "Follow-up Bot", "bot_name": "Bot Two", "dids": ["+911111111111"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        voice_bot = VoiceBot.objects.get(label="Follow-up Bot")
        self.assertEqual(voice_bot.bot_name, "Bot Two")
        self.assertEqual(voice_bot.dids, ["+911111111111"])
        self.assertIsNone(BotJourney.objects.filter(voice_bot=voice_bot).first())

    def test_patch_updates_voice_bot_and_syncs_attached_journey_node(self):
        voice_bot = VoiceBot.objects.create(bot_name="Old Name", api_url="https://old/")
        bot_journey = BotJourney.objects.create(process_agent=self.agent, name="Sales Journey", order=0)
        generate_journey(bot_journey)
        bot_journey.voice_bot = voice_bot
        bot_journey.save()

        response = self.client.patch(
            f"/api/telehub/voice-bots/{voice_bot.id}/",
            {"bot_name": "New Name", "api_url": "https://new/"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        voice_bot.refresh_from_db()
        self.assertEqual(voice_bot.bot_name, "New Name")

        node = bot_journey.nodes.get(name="Communication")
        self.assertEqual(node.config["bot_name"], "New Name")
        self.assertEqual(node.config["api_url"], "https://new/")

    def test_patch_404s_for_unknown_voice_bot(self):
        response = self.client.patch(
            "/api/telehub/voice-bots/99999/",
            {"bot_name": "x"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_removes_unattached_voice_bot(self):
        voice_bot = VoiceBot.objects.create(bot_name="Unused Bot")

        response = self.client.delete(f"/api/telehub/voice-bots/{voice_bot.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(VoiceBot.objects.filter(pk=voice_bot.id).count(), 0)

    def test_delete_rejects_voice_bot_in_use_by_a_journey(self):
        voice_bot = VoiceBot.objects.create(bot_name="In Use Bot")
        BotJourney.objects.create(
            process_agent=self.agent, voice_bot=voice_bot, name="Sales Journey", order=0
        )

        response = self.client.delete(f"/api/telehub/voice-bots/{voice_bot.id}/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(VoiceBot.objects.filter(pk=voice_bot.id).count(), 1)


class DispatcherTests(TestCase):
    def _make_execution(
        self,
        api_url="https://example.com/outbound",
        bot_id="bot-1",
        bot_name="Bot One",
        dids=None,
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

        voice_bot = VoiceBot.objects.create(
            bot_id=bot_id,
            bot_name=bot_name,
            dids=dids if dids is not None else [],
        )
        bot_journey = process_agent.bot_journeys.get(order=0)
        bot_journey.voice_bot = voice_bot
        bot_journey.save()

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
        # Shape confirmed against a real successful Postman call: custom
        # variables nest under "params", "from"/"to"/"dlr_id" are top-level
        # lowercase keys. bot_id/bot_name are NOT part of the real body (an
        # earlier, unconfirmed guess) and are correctly absent here.
        execution = self._make_execution(
            api_url="https://example.com/outbound",
            dids=["+917965314425", "+919999999999"],
            variables={"to_number": "+911234567890", "dnd": "false", "@name": "Charlie"},
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
        self.assertEqual(body["from"], "+917965314425")
        self.assertEqual(body["to"], "+911234567890")
        # dlr_id must be a string — Chat360's OutboundRequest.dlr_id is a Go
        # string field, sending an int 400s ("cannot unmarshal number into ...").
        self.assertEqual(body["dlr_id"], str(execution.id))
        self.assertEqual(body["params"], {"@name": "Charlie"})
        self.assertNotIn("bot_id", body)
        self.assertNotIn("bot_name", body)
        self.assertNotIn("to_number", body["params"])
        self.assertNotIn("dnd", body["params"])

    def test_bare_ten_digit_number_gets_plus91_prefix(self):
        # Regression: a real dispatch sent "to": "8104130877" (no country
        # code) and Chat360 200'd but never placed the call — bare 10-digit
        # numbers must be normalized before dispatch.
        execution = self._make_execution(
            dids=["+917965314425"], variables={"to_number": "8104130877"}
        )

        with patch(
            "apps.telehub.services.dispatcher.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.getcode.return_value = 200
            mock_urlopen.return_value.__enter__.return_value.read.return_value = b"OK"
            dispatch_execution(execution)

        body = json.loads(mock_urlopen.call_args[0][0].data.decode())
        self.assertEqual(body["to"], "+918104130877")

    def test_number_already_prefixed_is_left_untouched(self):
        execution = self._make_execution(
            dids=["+917965314425"], variables={"to_number": "+919892802815"}
        )

        with patch(
            "apps.telehub.services.dispatcher.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.getcode.return_value = 200
            mock_urlopen.return_value.__enter__.return_value.read.return_value = b"OK"
            dispatch_execution(execution)

        body = json.loads(mock_urlopen.call_args[0][0].data.decode())
        self.assertEqual(body["to"], "+919892802815")

    def test_token_stored_with_bearer_prefix_is_not_doubled(self):
        # Regression: an operator pasting the whole "Bearer <token>" header
        # value into CHAT360_OUTBOUND_BEARER_TOKEN (an easy mistake) must not
        # produce "Bearer Bearer <token>" on the wire.
        execution = self._make_execution()

        with patch.dict(
            os.environ, {"CHAT360_OUTBOUND_BEARER_TOKEN": "Bearer abc123"}
        ), patch("apps.telehub.services.dispatcher.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.getcode.return_value = 200
            mock_urlopen.return_value.__enter__.return_value.read.return_value = b"OK"
            dispatch_execution(execution)

        sent_request = mock_urlopen.call_args[0][0]
        self.assertEqual(sent_request.get_header("Authorization"), "Bearer abc123")


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

    def _make_execution(self, process_agent):
        return Execution.objects.create(
            process_agent=process_agent,
            lead_id="lead-gating",
            current_bot_journey=process_agent.bot_journeys.first(),
        )

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

        self.assertTrue(is_within_business_hours(self._make_execution(process_agent), at=at))

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

        self.assertFalse(is_within_business_hours(self._make_execution(process_agent), at=at))

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

        self.assertFalse(is_within_business_hours(self._make_execution(process_agent), at=at))

    def test_missing_business_hours_config_fails_open(self):
        process_agent = self._make_process_agent(business_hours_config={})

        self.assertTrue(is_within_business_hours(self._make_execution(process_agent)))

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


INBOUND_WHATSAPP_CURL = """curl --location --request POST 'https://app.chat360.io/service/v2/task' \\
--header 'Authorization: Api-Key test-key' \\
--header 'Content-Type: application/json' \\
--data-raw '{"task_name":"whatsapp_push_notification","extra":"","task_body":[{"client_number":"918799952622","receiver_number":"9718066817","country_code":"+91","template_data":{"param_data":{"link":"https://example.com/kb.pdf","customer_name":"customer_name","model_name":"model_name","appointment_place":"appointment_place","appointment_date":"appointment_date","appointment_time":"appointment_time"},"template_title":"hyundai_agentic_temp","template_code":"en","button_param_data":{},"file_name":""}}]}'"""

INBOUND_PAYLOAD = {
    "@caller_number": "+919876543210",
    "@callee_number": "918799952622",
    "@call_start_time": "2026-10-06 10:42:00",
    "@call_duration": "95",
    "@call_sentiment": "positive",
    "@customer_name": "Ravi",
    "@model_name": "Brezza",
    "@appointment_place": "Andheri",
    "@appointment_date": "2026-10-08",
    "@appointment_time": "11:00",
}


class InboundCallTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.department = Department.objects.create(name="Automobile")
        voice_bot = VoiceBot.objects.create(communication_type="voice_inbound")
        response = self.client.post(
            "/api/telehub/process-agents/",
            {"department": self.department.id, "name": "Inbound", "voice": {"voice_bot_id": voice_bot.id}},
            format="json",
        )
        self.agent = ProcessAgent.objects.get(pk=response.data["id"])
        self.webhook = WebhookDefinition.objects.get(process_agent=self.agent)

    def _post_call(self, payload=INBOUND_PAYLOAD):
        return self.client.post(f"/api/telehub/webhooks/{self.webhook.secret}/", payload, format="json")

    def test_inbound_bot_gets_webhook_without_schema(self):
        self.assertEqual(self.webhook.schema, {})

    def test_webhook_creates_completed_execution_with_stripped_keys(self):
        response = self._post_call()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        execution = Execution.objects.get(process_agent=self.agent)
        self.assertEqual(execution.status, "completed")
        self.assertEqual(execution.campaign_id, "inbound")
        self.assertIsNone(execution.next_execution)
        self.assertEqual(execution.duration, 95)
        self.assertEqual(execution.variables["customer_name"], "Ravi")
        self.assertEqual(execution.variables["to_number"], "+919876543210")
        self.assertNotIn("@customer_name", execution.variables)
        self.assertEqual(execution.qa_result.sentiment, "positive")
        self.assertTrue(ExecutionEvent.objects.filter(execution=execution, event_type="call_completed").exists())

    def test_resend_of_same_call_is_ignored(self):
        self._post_call()
        self._post_call()
        self.assertEqual(Execution.objects.filter(process_agent=self.agent).count(), 1)

    def test_each_inbound_call_from_same_number_gets_its_own_row(self):
        self._post_call()
        self._post_call({**INBOUND_PAYLOAD, "@call_start_time": "2026-10-06 12:00:00"})
        self.assertEqual(Execution.objects.filter(process_agent=self.agent).count(), 2)

    def test_calls_endpoint_lists_variables_and_whatsapp_status(self):
        self._post_call()
        response = self.client.get(f"/api/telehub/process-agents/{self.agent.id}/calls/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["variables"]["model_name"], "Brezza")
        self.assertIsNone(response.data[0]["whatsapp"])


def _text_only_curl(template_title):
    """A T2/T3-style curl: text template, no variable params."""
    return INBOUND_WHATSAPP_CURL.split("--data-raw")[0] + "--data-raw '" + json.dumps(
        {
            "task_name": "whatsapp_push_notification",
            "extra": "",
            "task_body": [
                {
                    "client_number": "918799952622",
                    "receiver_number": "9718066817",
                    "country_code": "+91",
                    "template_data": {
                        "param_data": {},
                        "template_title": template_title,
                        "template_code": "en",
                        "button_param_data": {},
                        "file_name": "",
                    },
                }
            ],
        }
    ) + "'"


def _sent_body(mock_send):
    return json.loads(mock_send.call_args.args[1])["task_body"][0]


class WhatsAppSendTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        department = Department.objects.create(name="Automobile")
        self.agent = ProcessAgent.objects.create(department=department, name="Inbound")
        # Pre-POC single curl: still read as T1's.
        OmnichannelConfig.objects.create(
            process_agent=self.agent, channel="whatsapp", whatsapp_curl=INBOUND_WHATSAPP_CURL
        )
        variables = {k.lstrip("@"): v for k, v in INBOUND_PAYLOAD.items()}
        self.execution = Execution.objects.create(
            process_agent=self.agent, lead_id="x", status="completed", variables=variables
        )

    def _send(self, **extra):
        return self.client.post(
            f"/api/telehub/process-agents/{self.agent.id}/send-whatsapp/",
            {"execution_ids": [self.execution.id], **extra},
            format="json",
        )

    def test_send_fills_receiver_and_params_from_variables(self):
        with patch("apps.telehub.services.whatsapp._send_once", return_value=(200, "{}", None)) as mock_send:
            response = self._send()

        result = response.data["results"][0]
        self.assertTrue(result["success"])
        self.assertEqual(result["template_key"], "T1")
        url, body_bytes, headers = mock_send.call_args.args
        self.assertEqual(url, "https://app.chat360.io/service/v2/task")
        self.assertEqual(headers["Authorization"], "Api-Key test-key")
        task = json.loads(body_bytes)["task_body"][0]
        self.assertEqual(task["receiver_number"], "9876543210")
        self.assertEqual(task["client_number"], "918799952622")
        params = task["template_data"]["param_data"]
        self.assertEqual(params["customer_name"], "Ravi")
        self.assertEqual(params["appointment_time"], "11:00")
        self.assertEqual(params["link"], "https://example.com/kb.pdf")
        self.assertTrue(ExecutionEvent.objects.filter(execution=self.execution, event_type="whatsapp_sent").exists())
        send = WhatsAppSend.objects.get(execution=self.execution)
        self.assertEqual((send.trigger, send.status, send.template_key), ("manual", "sent", "T1"))

        calls = self.client.get(f"/api/telehub/process-agents/{self.agent.id}/calls/").data
        self.assertEqual(calls[0]["whatsapp"]["status"], "sent")
        self.assertEqual(calls[0]["whatsapp"]["template_key"], "T1")
        self.assertEqual(calls[0]["suggested_template"], "T1")

    def test_t1_fills_empty_params_with_unspecified(self):
        self.execution.variables = {**self.execution.variables, "appointment_date": "", "appointment_place": None}
        self.execution.save()

        with patch("apps.telehub.services.whatsapp._send_once", return_value=(200, "{}", None)) as mock_send:
            response = self._send()

        self.assertTrue(response.data["results"][0]["success"])
        params = _sent_body(mock_send)["template_data"]["param_data"]
        self.assertEqual(params["appointment_date"], "unspecified")
        self.assertEqual(params["appointment_place"], "unspecified")
        self.assertEqual(params["customer_name"], "Ravi")

    def test_missing_receiver_still_blocks(self):
        self.execution.variables = {"customer_name": "Ravi"}
        self.execution.save()
        with patch("apps.telehub.services.whatsapp._send_once") as mock_send:
            response = self._send()
        mock_send.assert_not_called()
        self.assertIn("receiver_number", response.data["results"][0]["error"])

    def test_explicit_template_key_uses_that_templates_curl(self):
        self.agent.omnichannel.whatsapp_curls = {"T3": _text_only_curl("hyundai_agentic_sorry_followup")}
        self.agent.omnichannel.save()

        with patch("apps.telehub.services.whatsapp._send_once", return_value=(200, "{}", None)) as mock_send:
            self._send(template_key="T3")

        task = _sent_body(mock_send)
        self.assertEqual(task["template_data"]["template_title"], "hyundai_agentic_sorry_followup")
        self.assertEqual(task["receiver_number"], "9876543210")

    def test_preview_reports_template_and_params(self):
        response = self.client.post(
            f"/api/telehub/process-agents/{self.agent.id}/whatsapp-preview/",
            {"execution_ids": [self.execution.id]},
            format="json",
        )

        preview = response.data[0]
        self.assertEqual(preview["template_key"], "T1")
        self.assertEqual(preview["template_title"], "hyundai_agentic_temp")
        self.assertEqual(preview["params"]["model_name"], "Brezza")
        self.assertEqual(preview["missing"], [])
        self.assertNotIn("headers", preview)

    def test_unconfigured_template_reports_error(self):
        with patch("apps.telehub.services.whatsapp._send_once") as mock_send:
            response = self._send(template_key="T2")
        mock_send.assert_not_called()
        self.assertIn("no WhatsApp curl", response.data["results"][0]["error"])

    def test_bad_template_key_400s(self):
        self.assertEqual(self._send(template_key="T9").status_code, status.HTTP_400_BAD_REQUEST)

    def test_empty_execution_ids_400s(self):
        response = self.client.post(
            f"/api/telehub/process-agents/{self.agent.id}/send-whatsapp/", {"execution_ids": []}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class HyundaiTemplatePickTests(TestCase):
    def setUp(self):
        department = Department.objects.create(name="Automobile")
        self.agent = ProcessAgent.objects.create(department=department, name="Inbound")

    def _pick(self, **variables):
        execution = Execution(process_agent=self.agent, lead_id="x", variables=variables)
        return hyundai_whatsapp.pick_template(execution)

    def test_full_appointment_is_t1_even_on_drop_off(self):
        self.assertEqual(
            self._pick(
                appointment_date="2026-10-12", appointment_time="19:00", appointment_place="Khar", call_status="DROP_OFF"
            ),
            "T1",
        )

    def test_partial_capture_is_t1(self):
        self.assertEqual(self._pick(model_name="Creta"), "T1")
        self.assertEqual(self._pick(appointment_date="2026-10-12"), "T1")

    def test_model_of_interest_counts_as_model_name(self):
        self.assertEqual(self._pick(model_of_interest="Creta"), "T1")

    def test_nothing_captured_is_t3(self):
        self.assertEqual(self._pick(), "T3")
        self.assertEqual(self._pick(customer_name="  ", interest_type="test_drive", call_status="DROP_OFF"), "T3")

    def test_callback_status_required_is_t2(self):
        self.assertEqual(self._pick(callback_status="required"), "T2")
        self.assertEqual(self._pick(callback_status=" Required ", model_name="Creta"), "T2")

    def test_other_callback_status_values_are_ignored(self):
        for value in ("not_required", "not required", "False", "", None):
            self.assertEqual(self._pick(callback_status=value), "T3", value)
        self.assertEqual(self._pick(callback_status="", model_name="Creta"), "T1")

    def test_full_appointment_beats_callback_status(self):
        self.assertEqual(
            self._pick(
                callback_status="required", appointment_date="d", appointment_time="t", appointment_place="p"
            ),
            "T1",
        )

    def test_callback_takes_priority_over_partial_but_not_full_appointment(self):
        self.assertEqual(self._pick(model_name="Creta", callback_status="required"), "T2")
        self.assertEqual(
            self._pick(appointment_date="d", appointment_time="t", appointment_place="p", callback_status="required"),
            "T1",
        )


class HyundaiAutoSendTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        department = Department.objects.create(name="Automobile")
        voice_bot = VoiceBot.objects.create(communication_type="voice_inbound")
        response = self.client.post(
            "/api/telehub/process-agents/",
            {"department": department.id, "name": "Hyundai", "voice": {"voice_bot_id": voice_bot.id}},
            format="json",
        )
        self.agent = ProcessAgent.objects.get(pk=response.data["id"])
        self.webhook = WebhookDefinition.objects.get(process_agent=self.agent)
        self.config = OmnichannelConfig.objects.create(
            process_agent=self.agent,
            channel="whatsapp",
            auto_send=True,
            whatsapp_curls={
                "T1": INBOUND_WHATSAPP_CURL,
                "T2": _text_only_curl("hyundai_agentic_callback"),
                "T3": _text_only_curl("hyundai_agentic_sorry_followup"),
            },
        )

    def _post_call(self, payload=INBOUND_PAYLOAD):
        self.client.post(f"/api/telehub/webhooks/{self.webhook.secret}/", payload, format="json")
        return Execution.objects.filter(process_agent=self.agent).order_by("-created_at").first()

    def _tick(self, response=(200, "{}", None), now=None):
        with patch("apps.telehub.services.whatsapp._send_once", return_value=response) as mock_send:
            count = hyundai_whatsapp.process_due_sends(now=now)
        return count, mock_send

    def test_inbound_call_queues_and_scheduler_sends_t1(self):
        execution = self._post_call()
        send = WhatsAppSend.objects.get(execution=execution)
        self.assertEqual((send.trigger, send.status, send.template_key), ("auto", "pending", "T1"))

        count, mock_send = self._tick()

        self.assertEqual(count, 1)
        send.refresh_from_db()
        self.assertEqual(send.status, "sent")
        self.assertIsNotNone(send.sent_at)
        self.assertEqual(_sent_body(mock_send)["template_data"]["param_data"]["customer_name"], "Ravi")

    def test_nothing_captured_sends_t3(self):
        execution = self._post_call(
            {"@caller_number": "+919876543210", "@call_start_time": "10:00:00", "@call_duration": "4"}
        )
        _, mock_send = self._tick()
        self.assertEqual(WhatsAppSend.objects.get(execution=execution).template_key, "T3")
        self.assertEqual(_sent_body(mock_send)["template_data"]["template_title"], "hyundai_agentic_sorry_followup")

    def test_callback_status_required_sends_t2(self):
        execution = self._post_call(
            {"@caller_number": "+919876543210", "@call_start_time": "10:05:00", "@callback_status": "required"}
        )
        _, mock_send = self._tick()
        self.assertEqual(WhatsAppSend.objects.get(execution=execution).template_key, "T2")
        self.assertEqual(_sent_body(mock_send)["template_data"]["template_title"], "hyundai_agentic_callback")

    def test_auto_send_off_queues_nothing(self):
        self.config.auto_send = False
        self.config.save()
        self._post_call()
        self.assertFalse(WhatsAppSend.objects.exists())

    def test_test_call_is_skipped(self):
        execution = self._post_call({**INBOUND_PAYLOAD, "@is_test": "True"})
        send = WhatsAppSend.objects.get(execution=execution)
        self.assertEqual((send.status, send.last_error), ("skipped", "test call"))
        self.assertEqual(self._tick()[0], 0)

    def test_unconfigured_template_is_skipped(self):
        self.config.whatsapp_curls = {"T1": INBOUND_WHATSAPP_CURL}
        self.config.save()
        execution = self._post_call({"@caller_number": "+919876543210", "@call_start_time": "10:00:00"})
        send = WhatsAppSend.objects.get(execution=execution)
        self.assertEqual((send.status, send.last_error), ("skipped", "T3 not configured"))

    def test_only_one_automatic_send_per_call(self):
        execution = self._post_call()
        hyundai_whatsapp.on_call_completed(execution)
        self.assertEqual(WhatsAppSend.objects.filter(execution=execution).count(), 1)

    def test_5xx_retries_then_fails(self):
        execution = self._post_call()
        send = WhatsAppSend.objects.get(execution=execution)

        now = timezone.now()
        for attempt, delay in enumerate(hyundai_whatsapp.RETRY_DELAYS_MINUTES, start=1):
            self._tick(response=(502, "bad gateway", None), now=now)
            send.refresh_from_db()
            self.assertEqual((send.status, send.attempts), ("pending", attempt))
            self.assertGreater(send.next_attempt_at, now)
            now = send.next_attempt_at

        self._tick(response=(502, "bad gateway", None), now=now)
        send.refresh_from_db()
        self.assertEqual((send.status, send.attempts), ("failed", 4))
        self.assertIn("502", send.last_error)

    def test_not_due_yet_is_not_sent(self):
        execution = self._post_call()
        self._tick(response=(502, "", None))
        count, mock_send = self._tick()
        self.assertEqual(count, 0)
        mock_send.assert_not_called()

    def test_4xx_fails_without_retry(self):
        execution = self._post_call()
        self._tick(response=(400, "bad request", None))
        send = WhatsAppSend.objects.get(execution=execution)
        self.assertEqual((send.status, send.attempts), ("failed", 1))

    def test_network_error_is_retried(self):
        execution = self._post_call()
        with patch("apps.telehub.services.whatsapp._send_once", side_effect=OSError("timed out")):
            hyundai_whatsapp.process_due_sends()
        send = WhatsAppSend.objects.get(execution=execution)
        self.assertEqual(send.status, "pending")
        self.assertIn("timed out", send.last_error)

    def test_calls_endpoint_shows_auto_send_status(self):
        self._post_call()
        self._tick()
        row = self.client.get(f"/api/telehub/process-agents/{self.agent.id}/calls/").data[0]
        self.assertEqual(row["whatsapp"]["status"], "sent")
        self.assertEqual(row["whatsapp"]["trigger"], "auto")
        self.assertEqual(row["whatsapp"]["template_key"], "T1")


class OmnichannelTemplatesEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        department = Department.objects.create(name="Automobile")
        self.agent = ProcessAgent.objects.create(department=department, name="Inbound")
        self.url = f"/api/telehub/process-agents/{self.agent.id}/omnichannel/"

    def test_patch_curls_and_auto_send_and_read_back_summary(self):
        response = self.client.patch(
            self.url,
            {"auto_send": True, "whatsapp_curls": {"T1": INBOUND_WHATSAPP_CURL, "T3": "not a curl"}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["auto_send"])
        templates = response.data["whatsapp_templates"]
        self.assertEqual(templates["T1"]["template_title"], "hyundai_agentic_temp")
        self.assertIn("customer_name", templates["T1"]["params"])
        self.assertFalse(templates["T2"]["configured"])
        self.assertIsNotNone(templates["T3"]["error"])

    def test_unknown_template_key_400s(self):
        response = self.client.patch(self.url, {"whatsapp_curls": {"T7": "curl x"}}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
