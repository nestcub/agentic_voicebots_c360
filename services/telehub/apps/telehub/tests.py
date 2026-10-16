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
    ChannelRule,
    ChannelTemplate,
    Department,
    Execution,
    ExecutionEvent,
    Integration,
    JourneyTransition,
    LeadSource,
    NodeConnection,
    NodeInstance,
    NodeTemplate,
    OmnichannelConfig,
    PhoneNumber,
    ProcessAgent,
    Variable,
    VoiceBot,
    WebhookDefinition,
    WhatsAppSend,
    ProcessIntegration,
    QAResult,
)
from .services import conditions, handoff, omnichannel, omnichannel_seed, outcome_routing
from .services import numbers as numbers_service
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
from .models import Organization


def make_org(slug="excell-autovista", name=None):
    """The org every fixture row lives in unless a test is deliberately cross-tenant."""
    org, _ = Organization.objects.get_or_create(
        slug=slug, defaults={"name": name or slug.replace("-", " ").title()}
    )
    return org


class DepartmentProcessAgentNodeInstanceChainTests(TestCase):
    def test_relationships_resolve(self):
        department = Department.objects.create(organization=make_org(), name="Automobile")
        process_agent = ProcessAgent.objects.create(organization=make_org(),
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
        department = Department.objects.create(organization=make_org(), name="Healthcare")
        process_agent = ProcessAgent.objects.create(organization=make_org(),
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
        department = Department.objects.create(organization=make_org(), name="Automobile")
        process_agent = ProcessAgent.objects.create(organization=make_org(),
            department=department, name="Free Service 1"
        )
        integration = Integration.objects.create(organization=make_org(), name="Chat360", type="crm")
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
        department = Department.objects.create(organization=make_org(), name="Automobile")
        process_agent = ProcessAgent.objects.create(organization=make_org(),
            department=department, name="Insurance Renewal"
        )
        Variable.objects.create(process_agent=process_agent, key="customer_name")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Variable.objects.create(process_agent=process_agent, key="customer_name")


class QAResultOneToOneTests(TestCase):
    def test_second_qa_result_for_same_execution_raises(self):
        department = Department.objects.create(organization=make_org(), name="Automobile")
        process_agent = ProcessAgent.objects.create(organization=make_org(),
            department=department, name="Appointment Reminder"
        )
        execution = Execution.objects.create(organization=make_org(), process_agent=process_agent, lead_id="lead-1")
        QAResult.objects.create(execution=execution)

        self.assertEqual(execution.qa_result.execution, execution)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                QAResult.objects.create(execution=execution)


class JourneyGenerationTests(TestCase):
    def _make_process_agent(self):
        department = Department.objects.create(organization=make_org(), name="Automobile")
        return ProcessAgent.objects.create(organization=make_org(),
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
        voice_bot_id = VoiceBot.objects.create(organization=make_org(),
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
        user = get_user_model().objects.create_user("wizard", password="pw")
        Membership.objects.create(user=user, organization=make_org())
        self.client = APIClient()
        self.client.force_authenticate(user=user)
        self.department = Department.objects.create(organization=make_org(), name="Automobile")

    def test_full_wizard_payload_creates_agent_with_nodes_and_related_rows(self):
        webhook_schema = {"summary": "", "transcript": "", "sentiment": "", "outcome": ""}
        voice_bot = VoiceBot.objects.create(organization=make_org(),
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

    def _bot_with_dids(self, dids):
        from .services.numbers import sync_bot_numbers

        bot = VoiceBot.objects.create(
            organization=self.department.organization, communication_type="voice_inbound", dids=dids
        )
        sync_bot_numbers(bot)
        return bot

    def test_wizard_assigns_the_chosen_number_to_the_first_stage(self):
        bot = self._bot_with_dids(["917965311524", "917965311525"])
        number = bot.numbers.get(did="917965311525")
        payload = {
            "department": self.department.id,
            "name": "X",
            "voice": {"voice_bot_id": bot.id, "numbers": [number.id]},
        }

        response = self.client.post("/api/telehub/process-agents/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        journey = ProcessAgent.objects.get(id=response.data["id"]).bot_journeys.get()
        self.assertEqual([n.id for n in journey.numbers.all()], [number.id])

    def test_wizard_without_numbers_leaves_the_stage_automatic(self):
        bot = self._bot_with_dids(["917965311524"])
        payload = {"department": self.department.id, "name": "X", "voice": {"voice_bot_id": bot.id}}

        response = self.client.post("/api/telehub/process-agents/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(ProcessAgent.objects.get(id=response.data["id"]).bot_journeys.get().numbers.count(), 0)

    def test_wizard_rejects_a_number_of_another_bot_and_creates_nothing(self):
        bot = self._bot_with_dids(["917965311524"])
        other = self._bot_with_dids(["917965311599"])
        payload = {
            "department": self.department.id,
            "name": "X",
            "voice": {"voice_bot_id": bot.id, "numbers": [other.numbers.get().id]},
        }

        response = self.client.post("/api/telehub/process-agents/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertFalse(ProcessAgent.objects.filter(name="X").exists())

    def test_wizard_rejects_more_than_one_number(self):
        bot = self._bot_with_dids(["917965311524", "917965311525"])
        payload = {
            "department": self.department.id,
            "name": "X",
            "voice": {"voice_bot_id": bot.id, "numbers": [n.id for n in bot.numbers.all()]},
        }

        response = self.client.post("/api/telehub/process-agents/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)

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
        self.department = Department.objects.create(organization=make_org(), name="Automobile")

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
        department = Department.objects.create(organization=make_org(), name="Automobile")

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
        self.department = Department.objects.create(organization=make_org(), name="Automobile")

    def _create_agent_with_webhook(self):
        payload = _full_wizard_payload(self.department.id)
        response = self.client.post("/api/telehub/process-agents/", payload, format="json")
        agent_id = response.data["id"]
        webhook = WebhookDefinition.objects.get(process_agent_id=agent_id)
        return agent_id, webhook

    def test_valid_secret_and_dlr_id_routes_outcome(self):
        agent_id, webhook = self._create_agent_with_webhook()
        execution = Execution.objects.create(organization=make_org(), process_agent_id=agent_id, lead_id="lead-1")

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
        execution = Execution.objects.create(organization=make_org(),
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
        Execution.objects.create(organization=make_org(),
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
        self.department = Department.objects.create(organization=make_org(), name="Automobile")
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
        Execution.objects.create(organization=make_org(),
            process_agent_id=self.agent_id,
            lead_id="connected-1",
            variables={"call_duration": "40"},
        )
        Execution.objects.create(organization=make_org(),
            process_agent_id=self.agent_id,
            lead_id="not-connected-1",
            variables={"outcome": "no_answer"},
        )

        response = self.client.get(f"/api/telehub/process-agents/{self.agent_id}/stats/")

        self.assertEqual(response.data["calls"], 2)
        self.assertEqual(response.data["connected"], 1)
        self.assertEqual(response.data["avg_duration_seconds"], 40.0)

    def test_hot_leads_and_callback_requests_counted(self):
        execution = Execution.objects.create(organization=make_org(),
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
        self.department = Department.objects.create(organization=make_org(), name="Automobile")

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
        self.department = Department.objects.create(organization=make_org(), name="Automobile")

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
        LeadSource.objects.create(organization=make_org(),
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
        LeadSource.objects.create(organization=make_org(),
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
        self.department = Department.objects.create(organization=make_org(), name="Automobile")

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
        self.department = Department.objects.create(organization=make_org(), name="Automobile")

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
        agent = ProcessAgent.objects.create(organization=make_org(), department=self.department, name="Bare Agent")

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
        agent = ProcessAgent.objects.create(organization=make_org(), department=self.department, name="Bare Agent")

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
        self.department = Department.objects.create(organization=make_org(), name="Automobile")

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
        agent = ProcessAgent.objects.create(organization=make_org(), department=self.department, name="Bare Agent")

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
        agent = ProcessAgent.objects.create(organization=make_org(), department=self.department, name="Bare Agent")

        response = self.client.patch(
            f"/api/telehub/process-agents/{agent.id}/qa-config/",
            {"missing_variables": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class AnalyticsStatsConfigEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.department = Department.objects.create(organization=make_org(), name="Automobile")

    def test_get_returns_empty_dict_by_default(self):
        agent = ProcessAgent.objects.create(organization=make_org(), department=self.department, name="Bare Agent")

        response = self.client.get(f"/api/telehub/process-agents/{agent.id}/analytics-stats/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {})

    def test_patch_merges_toggles(self):
        agent = ProcessAgent.objects.create(organization=make_org(),
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
        agent = ProcessAgent.objects.create(organization=make_org(), department=self.department, name="Bare Agent")

        response = self.client.patch(
            f"/api/telehub/process-agents/{agent.id}/analytics-stats/",
            {"not_a_real_stat": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class VariableEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.department = Department.objects.create(organization=make_org(), name="Automobile")
        self.agent = ProcessAgent.objects.create(organization=make_org(), department=self.department, name="Bare Agent")

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
        self.department = Department.objects.create(organization=make_org(), name="Automobile")
        self.agent = ProcessAgent.objects.create(organization=make_org(), department=self.department, name="Bare Agent")

    def test_patch_updates_editable_fields_only(self):
        webhook = WebhookDefinition.objects.create(organization=make_org(),
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
        self.department = Department.objects.create(organization=make_org(), name="Automobile")
        self.agent = ProcessAgent.objects.create(organization=make_org(), department=self.department, name="Bare Agent")

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
        self.department = Department.objects.create(organization=make_org(), name="Automobile")
        self.agent = ProcessAgent.objects.create(organization=make_org(), department=self.department, name="Bare Agent")
        self.integration = Integration.objects.create(organization=make_org(), name="CRM X", type="crm")

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
        self.department = Department.objects.create(organization=make_org(), name="Automobile")
        self.agent = ProcessAgent.objects.create(organization=make_org(), department=self.department, name="Bare Agent")

    def test_get_lists_voice_bots(self):
        VoiceBot.objects.create(organization=make_org(), bot_name="Sales Bot")

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
        voice_bot = VoiceBot.objects.create(organization=make_org(), bot_name="Old Name", api_url="https://old/")
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
        voice_bot = VoiceBot.objects.create(organization=make_org(), bot_name="Unused Bot")

        response = self.client.delete(f"/api/telehub/voice-bots/{voice_bot.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(VoiceBot.objects.filter(pk=voice_bot.id).count(), 0)

    def test_delete_rejects_voice_bot_in_use_by_a_journey(self):
        voice_bot = VoiceBot.objects.create(organization=make_org(), bot_name="In Use Bot")
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
        department = Department.objects.create(organization=make_org(), name="Automobile")
        process_agent = ProcessAgent.objects.create(organization=make_org(),
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

        voice_bot = VoiceBot.objects.create(organization=make_org(),
            bot_id=bot_id,
            bot_name=bot_name,
            dids=dids if dids is not None else [],
        )
        bot_journey = process_agent.bot_journeys.get(order=0)
        bot_journey.voice_bot = voice_bot
        bot_journey.save()

        return Execution.objects.create(organization=make_org(),
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
        department = Department.objects.create(organization=make_org(), name="Automobile")
        process_agent = ProcessAgent.objects.create(organization=make_org(),
            department=department, name="Retry Test"
        )
        generate_journey(process_agent)

        if set_retry_node:
            retry_node = process_agent.nodes.get(name="Retry")
            retry_node.config = retry_config if retry_config is not None else {}
            retry_node.save()

        return Execution.objects.create(organization=make_org(),
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
        department = Department.objects.create(organization=make_org(), name="Automobile")
        process_agent = ProcessAgent.objects.create(organization=make_org(),
            department=department, name="Callback Test"
        )
        generate_journey(process_agent)

        callback_node = process_agent.nodes.get(name="Callback")
        callback_node.config = callback_config if callback_config is not None else {}
        callback_node.save()

        return Execution.objects.create(organization=make_org(),
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
        department = Department.objects.create(organization=make_org(), name="Automobile")
        process_agent = ProcessAgent.objects.create(organization=make_org(), department=department, name="Redirect Test")
        generate_journey(process_agent)
        communication_node = process_agent.nodes.get(name="Communication")
        communication_node.config = {"api_url": api_url, "bot_id": "bot-1", "bot_name": "Bot One"}
        communication_node.save()
        return Execution.objects.create(organization=make_org(),
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
        department = Department.objects.create(organization=make_org(), name="Automobile")
        process_agent = ProcessAgent.objects.create(organization=make_org(),
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
        return Execution.objects.create(organization=make_org(),
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
        execution = Execution.objects.create(organization=make_org(),
            process_agent=process_agent,
            lead_id="lead-1",
            variables={"dnd": "true"},
        )

        self.assertTrue(is_suppressed_dnc(execution))

    def test_dnd_not_suppressed_when_node_disabled(self):
        process_agent = self._make_process_agent(dnd_config={"enabled": False})
        execution = Execution.objects.create(organization=make_org(),
            process_agent=process_agent,
            lead_id="lead-1",
            variables={"dnd": "true"},
        )

        self.assertFalse(is_suppressed_dnc(execution))

    def test_dnd_not_suppressed_when_execution_variable_falsy(self):
        process_agent = self._make_process_agent(dnd_config={"enabled": True})
        execution = Execution.objects.create(organization=make_org(),
            process_agent=process_agent,
            lead_id="lead-1",
            variables={"dnd": "no"},
        )

        self.assertFalse(is_suppressed_dnc(execution))

    def test_missing_dnd_config_fails_open(self):
        process_agent = self._make_process_agent(dnd_config={})
        execution = Execution.objects.create(organization=make_org(),
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
        department = Department.objects.create(organization=make_org(), name="Automobile")
        process_agent = ProcessAgent.objects.create(organization=make_org(),
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

        return Execution.objects.create(organization=make_org(),
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
        department = Department.objects.create(organization=make_org(), name="Automobile")
        process_agent = ProcessAgent.objects.create(organization=make_org(),
            department=department, name="Outcome Routing Test"
        )
        generate_journey(process_agent)

        callback_node = process_agent.nodes.get(name="Callback")
        callback_node.config = callback_config if callback_config is not None else {}
        callback_node.save()

        retry_node = process_agent.nodes.get(name="Retry")
        retry_node.config = retry_config if retry_config is not None else {}
        retry_node.save()

        return Execution.objects.create(organization=make_org(),
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
        department = Department.objects.create(organization=make_org(), name="Automobile")
        payload = _full_wizard_payload(department.id)
        client = APIClient()
        create_response = client.post("/api/telehub/process-agents/", payload, format="json")
        agent_id = create_response.data["id"]
        webhook = WebhookDefinition.objects.get(process_agent_id=agent_id)
        execution = Execution.objects.create(organization=make_org(), process_agent_id=agent_id, lead_id="lead-http")

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
        self.department = Department.objects.create(organization=make_org(), name="Automobile")
        voice_bot = VoiceBot.objects.create(organization=make_org(), communication_type="voice_inbound")
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

    def test_session_id_resend_is_ignored_even_when_start_time_differs(self):
        self._post_call({**INBOUND_PAYLOAD, "session_id": "s-1"})
        self._post_call({**INBOUND_PAYLOAD, "session_id": "s-1", "@call_start_time": "2026-10-07 09:00:00"})
        self.assertEqual(Execution.objects.filter(process_agent=self.agent).count(), 1)

    def test_same_start_time_with_different_session_ids_are_two_calls(self):
        self._post_call({**INBOUND_PAYLOAD, "session_id": "s-1"})
        self._post_call({**INBOUND_PAYLOAD, "session_id": "s-2"})
        self.assertEqual(Execution.objects.filter(process_agent=self.agent).count(), 2)


class VariableDiscoveryTests(TestCase):
    def setUp(self):
        department = Department.objects.create(organization=make_org(), name="Automobile")
        voice_bot = VoiceBot.objects.create(organization=make_org(), communication_type="voice_inbound")
        self.client = APIClient()
        response = self.client.post(
            "/api/telehub/process-agents/",
            {"department": department.id, "name": "Inbound", "voice": {"voice_bot_id": voice_bot.id}},
            format="json",
        )
        self.agent = ProcessAgent.objects.get(pk=response.data["id"])
        self.webhook = WebhookDefinition.objects.get(process_agent=self.agent)

    def _post(self, payload):
        return self.client.post(f"/api/telehub/webhooks/{self.webhook.secret}/", payload, format="json")

    def test_webhook_creates_unticked_discovered_variables(self):
        self._post({"complaint_query": "engine noise", "workshop": "Andheri"})

        variable = self.agent.variables.get(key="complaint_query")
        self.assertTrue(variable.discovered)
        self.assertFalse(variable.use_in_qa)
        self.assertFalse(variable.use_in_analytics)
        self.assertEqual(variable.sample_value, "engine noise")
        self.assertIsNotNone(variable.last_seen_at)
        self.assertTrue(self.agent.variables.filter(key="workshop").exists())

    def test_platform_keys_are_not_discovered(self):
        self._post({**INBOUND_PAYLOAD, "session_id": "s-1", "is_test": "False", "date": "14-10-2026"})

        keys = set(self.agent.variables.values_list("key", flat=True))
        self.assertIn("customer_name", keys)  # "@customer_name" is stripped to a plain key
        for ignored in ("session_id", "caller_number", "callee_number", "call_start_time", "call_duration", "is_test", "date"):
            self.assertNotIn(ignored, keys)

    def test_rediscovery_keeps_user_ticks_and_refreshes_sample(self):
        self._post({"complaint_query": "engine noise"})
        variable = self.agent.variables.get(key="complaint_query")
        variable.use_in_qa = True
        variable.save()

        self._post({"complaint_query": "brake issue"})

        variable.refresh_from_db()
        self.assertEqual(self.agent.variables.filter(key="complaint_query").count(), 1)
        self.assertTrue(variable.use_in_qa)
        self.assertEqual(variable.sample_value, "brake issue")

    def test_empty_value_does_not_blank_the_sample(self):
        self._post({"complaint_query": "engine noise"})
        self._post({"complaint_query": ""})

        self.assertEqual(self.agent.variables.get(key="complaint_query").sample_value, "engine noise")

    def test_declared_variable_is_not_marked_discovered(self):
        Variable.objects.create(process_agent=self.agent, key="customer_name", label="Name")
        self._post({"customer_name": "Ravi"})

        variable = self.agent.variables.get(key="customer_name")
        self.assertFalse(variable.discovered)
        self.assertTrue(variable.use_in_qa)
        self.assertEqual(variable.label, "Name")
        self.assertEqual(variable.sample_value, "Ravi")

    def test_non_ascii_values_are_kept(self):
        self._post({"workshop_spoken": "मारुति अंधेरी"})

        self.assertEqual(self.agent.variables.get(key="workshop_spoken").sample_value, "मारुति अंधेरी")

    def test_overlong_sample_is_truncated_and_overlong_key_skipped(self):
        self._post({"note": "x" * 1000, "k" * 100: "v"})

        self.assertEqual(len(self.agent.variables.get(key="note").sample_value), 255)
        self.assertEqual(self.agent.variables.count(), 1)

    def test_analytics_endpoint_lists_only_ticked_variables(self):
        self._post({"complaint_query": "engine noise", "workshop": "Andheri"})
        self.agent.variables.filter(key="workshop").update(use_in_analytics=True)

        response = self.client.get(f"/api/telehub/process-agents/{self.agent.id}/analytics/")

        self.assertEqual(response.data["variable_keys"], ["workshop"])

    def test_qa_missing_variables_only_checks_ticked_variables(self):
        self.agent.variables.create(key="workshop", use_in_qa=True)
        self.agent.variables.create(key="complaint_query", use_in_qa=False)
        execution = Execution.objects.create(
            organization=self.agent.organization, process_agent=self.agent, lead_id="x", variables={}
        )

        self.assertEqual(outcome_routing._missing_variables(execution), ["workshop"])

    def test_patching_ticks_via_api(self):
        self._post({"complaint_query": "engine noise"})
        variable = self.agent.variables.get(key="complaint_query")

        response = self.client.patch(
            f"/api/telehub/process-agents/{self.agent.id}/variables/{variable.id}/",
            {"use_in_qa": True, "use_in_analytics": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        variable.refresh_from_db()
        self.assertTrue(variable.use_in_qa)
        self.assertTrue(variable.use_in_analytics)
        self.assertTrue(response.data["discovered"])


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
        department = Department.objects.create(organization=make_org(), name="Automobile")
        self.agent = ProcessAgent.objects.create(organization=make_org(), department=department, name="Inbound")
        # Pre-POC single curl: still read as T1's.
        OmnichannelConfig.objects.create(
            process_agent=self.agent, channel="whatsapp", whatsapp_curl=INBOUND_WHATSAPP_CURL
        )
        variables = {k.lstrip("@"): v for k, v in INBOUND_PAYLOAD.items()}
        self.execution = Execution.objects.create(organization=make_org(),
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
        self.agent.channel_templates.filter(name="T3").update(curl=_text_only_curl("hyundai_agentic_sorry_followup"))

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
        department = Department.objects.create(organization=make_org(), name="Automobile")
        self.agent = ProcessAgent.objects.create(organization=make_org(), department=department, name="Inbound")
        omnichannel_seed.sync_agent(ChannelTemplate, ChannelRule, self.agent, {})

    def _pick(self, **variables):
        execution = Execution(organization=make_org(), process_agent=self.agent, lead_id="x", variables=variables)
        return omnichannel.pick_template(execution)

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
        department = Department.objects.create(organization=make_org(), name="Automobile")
        voice_bot = VoiceBot.objects.create(organization=make_org(), communication_type="voice_inbound")
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
            count = omnichannel.process_due_sends(now=now)
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
        ChannelTemplate.objects.filter(process_agent=self.agent, name="T3").update(curl="")
        execution = self._post_call({"@caller_number": "+919876543210", "@call_start_time": "10:00:00"})
        send = WhatsAppSend.objects.get(execution=execution)
        self.assertEqual((send.status, send.last_error), ("skipped", "T3 not configured"))

    def test_only_one_automatic_send_per_call(self):
        execution = self._post_call()
        omnichannel.on_call_completed(execution)
        self.assertEqual(WhatsAppSend.objects.filter(execution=execution).count(), 1)

    def test_5xx_retries_then_fails(self):
        execution = self._post_call()
        send = WhatsAppSend.objects.get(execution=execution)

        now = timezone.now()
        for attempt, delay in enumerate(omnichannel.RETRY_DELAYS_MINUTES, start=1):
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
            omnichannel.process_due_sends()
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
        department = Department.objects.create(organization=make_org(), name="Automobile")
        self.agent = ProcessAgent.objects.create(organization=make_org(), department=department, name="Inbound")
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


class ConditionsTests(TestCase):
    def _check(self, op, variables, **extra):
        return conditions.check_passes({"variable": "x", "op": op, **extra}, variables)

    def test_exists_and_not_exists(self):
        self.assertTrue(self._check("exists", {"x": "a"}))
        for blank in (None, "", "   "):
            self.assertFalse(self._check("exists", {"x": blank}))
            self.assertTrue(self._check("not_exists", {"x": blank}))
        self.assertFalse(self._check("exists", {}))
        self.assertTrue(self._check("not_exists", {}))
        self.assertTrue(self._check("exists", {"x": 0}))

    def test_equals_ignores_case_and_whitespace(self):
        self.assertTrue(self._check("equals", {"x": " Required "}, value="required"))
        self.assertFalse(self._check("equals", {"x": "not_required"}, value="required"))
        self.assertFalse(self._check("equals", {}, value="required"))

    def test_truthy_reads_string_false_as_false(self):
        for value in (True, "true", "True", " YES ", "1", 1):
            self.assertTrue(self._check("truthy", {"x": value}), value)
        for value in (False, "False", "false", "0", "no", "", None, "maybe"):
            self.assertFalse(self._check("truthy", {"x": value}), value)

    def test_unknown_op_and_malformed_check_never_match(self):
        self.assertFalse(self._check("greater_than", {"x": 5}))
        self.assertFalse(conditions.check_passes("exists", {"x": 1}))

    def test_all_any_and_empty(self):
        checks = [{"variable": "a", "op": "exists"}, {"variable": "b", "op": "exists"}]
        self.assertFalse(conditions.evaluate("all", checks, {"a": 1}))
        self.assertTrue(conditions.evaluate("any", checks, {"a": 1}))
        self.assertFalse(conditions.evaluate("any", checks, {}))
        self.assertTrue(conditions.evaluate("all", [], {}))
        self.assertTrue(conditions.evaluate("any", [], {}))

    def test_validate_checks(self):
        self.assertEqual(conditions.validate_checks([{"variable": "a", "op": "exists"}]), [])
        self.assertTrue(conditions.validate_checks("nope"))
        self.assertTrue(conditions.validate_checks([{"variable": "a", "op": "bogus"}]))
        self.assertTrue(conditions.validate_checks([{"op": "exists"}]))
        self.assertTrue(conditions.validate_checks([{"variable": "a", "op": "equals"}]))


class ChannelRuleEngineTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        department = Department.objects.create(organization=make_org(), name="Automobile")
        self.agent = ProcessAgent.objects.create(organization=make_org(), department=department, name="Inbound")

    def _execution(self, **variables):
        return Execution(organization=make_org(), process_agent=self.agent, lead_id="x", variables=variables)

    def _template(self, name, curl=INBOUND_WHATSAPP_CURL, **extra):
        return ChannelTemplate.objects.create(process_agent=self.agent, name=name, curl=curl, **extra)

    def _rule(self, priority, template=None, action="send", match="all", checks=(), reason=""):
        return ChannelRule.objects.create(
            process_agent=self.agent,
            priority=priority,
            action=action,
            template=template,
            match=match,
            checks=list(checks),
            reason=reason,
        )

    def test_lowest_priority_matching_rule_wins(self):
        promo, other = self._template("Promo"), self._template("Other")
        self._rule(5, other)
        self._rule(1, promo, checks=[{"variable": "vip", "op": "exists"}])
        self._rule(2, other, checks=[{"variable": "vip", "op": "exists"}])

        self.assertEqual(omnichannel.pick_template(self._execution(vip="y")), "Promo")
        self.assertEqual(omnichannel.pick_template(self._execution()), "Other")

    def test_no_rules_or_no_match_picks_nothing(self):
        self.assertIsNone(omnichannel.pick_template(self._execution()))
        self._rule(1, self._template("Promo"), checks=[{"variable": "vip", "op": "exists"}])
        self.assertIsNone(omnichannel.pick_template(self._execution()))

    def test_skip_rule_picks_no_template(self):
        self._rule(0, action="skip", checks=[{"variable": "is_test", "op": "truthy"}], reason="test call")
        self._rule(1, self._template("Promo"))

        self.assertIsNone(omnichannel.pick_template(self._execution(is_test="true")))
        self.assertEqual(omnichannel.pick_template(self._execution(is_test="False")), "Promo")

    def test_param_map_fallback_feeds_rules(self):
        promo = self._template(
            "Promo", param_map={"model": {"variable": "model_name", "fallback": "model_of_interest"}}
        )
        self._rule(1, promo, checks=[{"variable": "model_name", "op": "exists"}])

        self.assertEqual(omnichannel.pick_template(self._execution(model_of_interest="Creta")), "Promo")
        self.assertIsNone(omnichannel.pick_template(self._execution()))

    def test_custom_rule_queues_custom_template_on_completion(self):
        OmnichannelConfig.objects.create(process_agent=self.agent, channel="whatsapp", auto_send=True)
        ChannelRule.objects.all().delete()
        promo = self._template("Promo")
        self._rule(1, promo, checks=[{"variable": "vip", "op": "exists"}])
        execution = Execution.objects.create(
            organization=make_org(), process_agent=self.agent, lead_id="x", variables={"vip": "y"}
        )

        omnichannel.on_call_completed(execution)

        send = WhatsAppSend.objects.get(execution=execution)
        self.assertEqual((send.status, send.template_key), ("pending", "Promo"))

    def test_skip_rule_records_skipped_with_reason(self):
        OmnichannelConfig.objects.create(process_agent=self.agent, channel="whatsapp", auto_send=True)
        ChannelRule.objects.all().delete()
        self._rule(0, action="skip", reason="vip handled by humans")
        execution = Execution.objects.create(organization=make_org(), process_agent=self.agent, lead_id="x")

        omnichannel.on_call_completed(execution)

        send = WhatsAppSend.objects.get(execution=execution)
        self.assertEqual((send.status, send.last_error), ("skipped", "vip handled by humans"))

    def test_no_matching_rule_records_nothing(self):
        OmnichannelConfig.objects.create(process_agent=self.agent, channel="whatsapp", auto_send=True)
        ChannelRule.objects.all().delete()
        execution = Execution.objects.create(organization=make_org(), process_agent=self.agent, lead_id="x")

        omnichannel.on_call_completed(execution)

        self.assertFalse(WhatsAppSend.objects.exists())

    def test_inactive_template_counts_as_not_configured(self):
        OmnichannelConfig.objects.create(process_agent=self.agent, channel="whatsapp", auto_send=True)
        ChannelRule.objects.all().delete()
        promo = self._template("Promo", is_active=False)
        self._rule(1, promo)
        execution = Execution.objects.create(organization=make_org(), process_agent=self.agent, lead_id="x")

        omnichannel.on_call_completed(execution)

        send = WhatsAppSend.objects.get(execution=execution)
        self.assertEqual((send.status, send.last_error), ("skipped", "Promo not configured"))

    def test_saving_omnichannel_config_creates_default_templates_and_rules(self):
        OmnichannelConfig.objects.create(
            process_agent=self.agent, channel="whatsapp", whatsapp_curls={"T2": "curl t2"}, whatsapp_curl="curl legacy"
        )

        names = list(self.agent.channel_templates.values_list("name", flat=True))
        self.assertEqual(names, ["T1", "T2", "T3"])
        self.assertEqual(self.agent.channel_templates.get(name="T1").curl, "curl legacy")
        self.assertEqual(self.agent.channel_templates.get(name="T2").curl, "curl t2")
        self.assertEqual(self.agent.channel_templates.get(name="T1").missing_fill, "unspecified")
        self.assertEqual(self.agent.channel_rules.count(), len(omnichannel_seed.SEED_RULES))

    def test_resaving_config_does_not_duplicate_or_wipe(self):
        config = OmnichannelConfig.objects.create(
            process_agent=self.agent, channel="whatsapp", whatsapp_curls={"T2": "curl t2"}
        )
        self.agent.channel_templates.filter(name="T3").update(curl="managed directly")

        config.auto_send = True
        config.save()

        self.assertEqual(self.agent.channel_templates.count(), 3)
        self.assertEqual(self.agent.channel_rules.count(), len(omnichannel_seed.SEED_RULES))
        self.assertEqual(self.agent.channel_templates.get(name="T3").curl, "managed directly")

    def test_existing_rules_are_not_replaced_by_sync(self):
        self._rule(0, action="skip", reason="custom")
        OmnichannelConfig.objects.create(process_agent=self.agent, channel="whatsapp")
        self.assertEqual(self.agent.channel_rules.count(), 1)

    def test_data_migration_seeds_agents_that_have_a_config(self):
        import importlib

        from django.apps import apps as django_apps

        OmnichannelConfig.objects.create(
            process_agent=self.agent, channel="whatsapp", whatsapp_curls={"T1": INBOUND_WHATSAPP_CURL}
        )
        self.agent.channel_rules.all().delete()
        self.agent.channel_templates.all().delete()

        migration = importlib.import_module("apps.telehub.migrations.0018_seed_channel_templates")
        migration.seed_channel_templates(django_apps, None)

        self.assertEqual(self.agent.channel_templates.count(), 3)
        self.assertEqual(self.agent.channel_rules.count(), len(omnichannel_seed.SEED_RULES))
        self.assertEqual(self.agent.channel_templates.get(name="T1").curl, INBOUND_WHATSAPP_CURL)

    def test_manual_send_accepts_any_of_the_agents_template_names(self):
        OmnichannelConfig.objects.create(process_agent=self.agent, channel="whatsapp")
        self._template("Promo")
        execution = Execution.objects.create(
            organization=make_org(), process_agent=self.agent, lead_id="x", variables={"caller_number": "9876543210"}
        )
        url = f"/api/telehub/process-agents/{self.agent.id}/whatsapp-preview/"

        ok = self.client.post(url, {"execution_ids": [execution.id], "template_key": "Promo"}, format="json")
        bad = self.client.post(url, {"execution_ids": [execution.id], "template_key": "Nope"}, format="json")

        self.assertEqual(ok.status_code, status.HTTP_200_OK, ok.data)
        self.assertEqual(ok.data[0]["template_key"], "Promo")
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)


class WhatsAppParamMapAndBlockedTests(TestCase):
    """Step 3: param_map drives the sent values; empty mapped values block the send until filled."""

    ALL = {
        "customer_name": "Ravi",
        "model_name": "Creta",
        "appointment_place": "Andheri",
        "appointment_date": "2026-10-20",
        "appointment_time": "11:00",
    }

    def setUp(self):
        self.client = APIClient()
        department = Department.objects.create(organization=make_org(), name="Automobile")
        self.agent = ProcessAgent.objects.create(organization=make_org(), department=department, name="Inbound")
        OmnichannelConfig.objects.create(process_agent=self.agent, channel="whatsapp", auto_send=True)
        self.agent.channel_rules.all().delete()
        self.agent.channel_templates.all().delete()
        self.template = ChannelTemplate.objects.create(
            process_agent=self.agent, name="Promo", curl=INBOUND_WHATSAPP_CURL
        )
        ChannelRule.objects.create(process_agent=self.agent, priority=1, template=self.template)

    def _call(self, **variables):
        return Execution.objects.create(
            organization=make_org(),
            process_agent=self.agent,
            lead_id="x",
            status="completed",
            variables={"caller_number": "+919876543210", **variables},
        )

    def _tick(self, response=(200, "{}", None)):
        with patch("apps.telehub.services.whatsapp._send_once", return_value=response) as mock_send:
            count = omnichannel.process_due_sends()
        return count, mock_send

    def _fill_url(self, send, agent=None):
        return f"/api/telehub/process-agents/{(agent or self.agent).id}/whatsapp-sends/{send.id}/fill/"

    # ── param_map ──────────────────────────────────────────────────────────

    def test_param_map_reads_a_differently_named_variable_and_sends_fixed_text(self):
        self.template.param_map = {
            "customer_name": {"variable": "cust"},
            "link": {"fixed": "https://example.com/brochure.pdf"},
        }
        self.template.save()
        execution = self._call(**{**self.ALL, "cust": "Asha"})

        omnichannel.on_call_completed(execution)
        _, mock_send = self._tick()

        params = json.loads(mock_send.call_args.args[1])["task_body"][0]["template_data"]["param_data"]
        self.assertEqual(params["customer_name"], "Asha")
        self.assertEqual(params["link"], "https://example.com/brochure.pdf")
        self.assertEqual(params["model_name"], "Creta")

    def test_param_map_fallback_variable_is_used_when_primary_is_empty(self):
        self.template.param_map = {"model_name": {"variable": "model_name", "fallback": "model_of_interest"}}
        self.template.save()
        variables = {**self.ALL, "model_of_interest": "Venue"}
        variables.pop("model_name")
        execution = self._call(**variables)

        omnichannel.on_call_completed(execution)
        _, mock_send = self._tick()

        params = json.loads(mock_send.call_args.args[1])["task_body"][0]["template_data"]["param_data"]
        self.assertEqual(params["model_name"], "Venue")

    def test_send_records_the_template(self):
        execution = self._call(**self.ALL)
        omnichannel.on_call_completed(execution)

        send = WhatsAppSend.objects.get(execution=execution)
        self.assertEqual(send.template_id, self.template.id)
        self.assertEqual(send.template_key, "Promo")

    def test_template_names_longer_than_sixteen_characters_work(self):
        long_name = "post_service_feedback_reminder"
        template = ChannelTemplate.objects.create(
            process_agent=self.agent, name=long_name, curl=INBOUND_WHATSAPP_CURL
        )
        self.agent.channel_rules.all().delete()
        ChannelRule.objects.create(process_agent=self.agent, priority=1, template=template)
        execution = self._call(**self.ALL)

        omnichannel.on_call_completed(execution)

        self.assertEqual(WhatsAppSend.objects.get(execution=execution).template_key, long_name)

    # ── blocked ────────────────────────────────────────────────────────────

    def test_empty_mapped_variables_block_the_send_and_nothing_is_sent(self):
        execution = self._call(customer_name="Ravi")
        omnichannel.on_call_completed(execution)

        count, mock_send = self._tick()

        send = WhatsAppSend.objects.get(execution=execution)
        self.assertEqual(count, 1)
        mock_send.assert_not_called()
        self.assertEqual(send.status, "blocked")
        self.assertEqual(send.attempts, 0)
        self.assertIsNone(send.next_attempt_at)
        self.assertEqual(
            sorted(send.missing), ["appointment_date", "appointment_place", "appointment_time", "model_name"]
        )
        self.assertIn("missing values", send.last_error)
        self.assertTrue(ExecutionEvent.objects.filter(execution=execution, event_type="whatsapp_blocked").exists())

    def test_blocked_send_is_left_alone_by_later_ticks(self):
        execution = self._call(customer_name="Ravi")
        omnichannel.on_call_completed(execution)
        self._tick()

        count, mock_send = self._tick()

        self.assertEqual(count, 0)
        mock_send.assert_not_called()
        self.assertEqual(WhatsAppSend.objects.get(execution=execution).status, "blocked")

    def test_missing_list_names_variables_not_param_keys(self):
        self.template.param_map = {"model_name": {"variable": "vehicle"}}
        self.template.save()
        execution = self._call(**{k: v for k, v in self.ALL.items() if k != "model_name"})
        omnichannel.on_call_completed(execution)
        self._tick()

        self.assertEqual(WhatsAppSend.objects.get(execution=execution).missing, ["vehicle"])

    def test_missing_fill_text_means_the_send_is_never_blocked(self):
        self.template.missing_fill = "unspecified"
        self.template.save()
        execution = self._call(customer_name="Ravi")
        omnichannel.on_call_completed(execution)

        _, mock_send = self._tick()

        params = json.loads(mock_send.call_args.args[1])["task_body"][0]["template_data"]["param_data"]
        self.assertEqual(params["model_name"], "unspecified")
        self.assertEqual(WhatsAppSend.objects.get(execution=execution).status, "sent")

    def test_missing_receiver_number_fails_instead_of_blocking(self):
        execution = Execution.objects.create(
            organization=make_org(), process_agent=self.agent, lead_id="x", status="completed", variables=self.ALL
        )
        omnichannel.on_call_completed(execution)

        self._tick()

        send = WhatsAppSend.objects.get(execution=execution)
        self.assertEqual(send.status, "failed")
        self.assertIn("receiver_number", send.last_error)

    def test_manual_send_with_missing_values_records_a_blocked_send(self):
        execution = self._call(customer_name="Ravi")

        with patch("apps.telehub.services.whatsapp._send_once") as mock_send:
            result = omnichannel.send_manual(execution, "Promo")

        mock_send.assert_not_called()
        self.assertFalse(result["success"])
        self.assertTrue(result["blocked"])
        send = WhatsAppSend.objects.get(execution=execution)
        self.assertEqual((send.trigger, send.status), ("manual", "blocked"))
        self.assertEqual(result["send_id"], send.id)
        self.assertIn("model_name", send.missing)

    def test_calls_endpoint_exposes_blocked_send_id_and_missing(self):
        execution = self._call(customer_name="Ravi")
        omnichannel.on_call_completed(execution)
        self._tick()

        row = self.client.get(f"/api/telehub/process-agents/{self.agent.id}/calls/").data[0]

        send = WhatsAppSend.objects.get(execution=execution)
        self.assertEqual(row["whatsapp"]["status"], "blocked")
        self.assertEqual(row["whatsapp"]["id"], send.id)
        self.assertIn("model_name", row["whatsapp"]["missing"])

    # ── fill ───────────────────────────────────────────────────────────────

    def _blocked_send(self, **variables):
        execution = self._call(**variables)
        omnichannel.on_call_completed(execution)
        self._tick()
        return WhatsAppSend.objects.get(execution=execution)

    def test_filling_every_missing_value_sends_immediately(self):
        send = self._blocked_send(customer_name="Ravi")
        values = {name: f"{name}-value" for name in send.missing}

        with patch("apps.telehub.services.whatsapp._send_once", return_value=(200, "{}", None)) as mock_send:
            response = self.client.post(self._fill_url(send), {"values": values}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["status"], "sent")
        send.refresh_from_db()
        self.assertEqual((send.status, send.missing, send.attempts), ("sent", [], 1))
        self.assertIsNotNone(send.sent_at)
        params = json.loads(mock_send.call_args.args[1])["task_body"][0]["template_data"]["param_data"]
        self.assertEqual(params["model_name"], "model_name-value")
        self.assertEqual(params["customer_name"], "Ravi")
        send.execution.refresh_from_db()
        self.assertEqual(send.execution.variables["appointment_date"], "appointment_date-value")
        event = ExecutionEvent.objects.get(execution=send.execution, event_type="whatsapp_filled")
        self.assertEqual(event.payload["send_id"], send.id)

    def test_partial_fill_keeps_the_send_blocked_with_a_shorter_list(self):
        send = self._blocked_send(customer_name="Ravi")

        with patch("apps.telehub.services.whatsapp._send_once") as mock_send:
            response = self.client.post(
                self._fill_url(send), {"values": {"model_name": "Creta"}}, format="json"
            )

        mock_send.assert_not_called()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "blocked")
        self.assertNotIn("model_name", response.data["missing"])
        send.refresh_from_db()
        self.assertEqual(send.status, "blocked")
        self.assertNotIn("model_name", send.missing)

    def test_fill_rejects_unknown_blank_and_empty_values(self):
        send = self._blocked_send(customer_name="Ravi")
        url = self._fill_url(send)

        for body in (
            {"values": {"customer_name": "x"}},  # not missing
            {"values": {"model_name": "   "}},  # blank
            {"values": {}},
            {},
        ):
            response = self.client.post(url, body, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, body)
        send.execution.refresh_from_db()
        self.assertNotIn("model_name", send.execution.variables)

    def test_fill_rejects_a_send_that_is_not_blocked(self):
        execution = self._call(**self.ALL)
        omnichannel.on_call_completed(execution)
        self._tick()
        send = WhatsAppSend.objects.get(execution=execution)

        response = self.client.post(self._fill_url(send), {"values": {"model_name": "x"}}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_fill_404s_for_another_agents_send(self):
        send = self._blocked_send(customer_name="Ravi")
        other = ProcessAgent.objects.create(
            organization=make_org(), department=self.agent.department, name="Other"
        )

        response = self.client.post(
            self._fill_url(send, agent=other), {"values": {"model_name": "x"}}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_fill_then_send_failure_on_auto_send_goes_back_to_retrying(self):
        send = self._blocked_send(customer_name="Ravi")
        values = {name: "v" for name in send.missing}

        with patch("apps.telehub.services.whatsapp._send_once", return_value=(502, "bad gateway", None)):
            self.client.post(self._fill_url(send), {"values": values}, format="json")

        send.refresh_from_db()
        self.assertEqual((send.status, send.attempts), ("pending", 1))
        self.assertGreater(send.next_attempt_at, timezone.now())

    def test_fill_then_send_failure_on_manual_send_is_final(self):
        execution = self._call(customer_name="Ravi")
        with patch("apps.telehub.services.whatsapp._send_once"):
            omnichannel.send_manual(execution, "Promo")
        send = WhatsAppSend.objects.get(execution=execution)
        values = {name: "v" for name in send.missing}

        with patch("apps.telehub.services.whatsapp._send_once", return_value=(502, "bad gateway", None)):
            self.client.post(self._fill_url(send), {"values": values}, format="json")

        send.refresh_from_db()
        self.assertEqual(send.status, "failed")


class ChannelConfigApiTests(TestCase):
    """Step 4: the template / rule endpoints the dashboard's Settings tab uses."""

    def setUp(self):
        self.client = APIClient()
        department = Department.objects.create(organization=make_org(), name="Automobile")
        self.agent = ProcessAgent.objects.create(organization=make_org(), department=department, name="Inbound")
        self.base = f"/api/telehub/process-agents/{self.agent.id}"

    def _create_template(self, name="Promo", **extra):
        return self.client.post(
            f"{self.base}/channel-templates/",
            {"name": name, "curl": INBOUND_WHATSAPP_CURL, **extra},
            format="json",
        )

    def _create_rule(self, **body):
        return self.client.post(f"{self.base}/channel-rules/", body, format="json")

    # ── templates ──────────────────────────────────────────────────────────

    def test_create_template_describes_the_curl_without_exposing_it(self):
        response = self._create_template()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["template_title"], "hyundai_agentic_temp")
        self.assertEqual(
            [p["key"] for p in response.data["params"]],
            ["link", "customer_name", "model_name", "appointment_place", "appointment_date", "appointment_time"],
        )
        self.assertNotIn("curl", response.data)
        self.assertNotIn("test-key", json.dumps(response.data))
        listing = self.client.get(f"{self.base}/channel-templates/")
        self.assertNotIn("test-key", json.dumps(listing.data))
        self.assertNotIn("Authorization", json.dumps(listing.data))

    def test_variables_sent_lists_variable_params_but_not_literal_text(self):
        response = self._create_template(param_map={"link": {"fixed": "https://x.test"}})

        self.assertEqual(
            response.data["variables_sent"],
            ["customer_name", "model_name", "appointment_place", "appointment_date", "appointment_time"],
        )
        listing = self.client.get(f"{self.base}/channel-templates/")
        self.assertEqual(listing.data["variables_sent"], response.data["variables_sent"])

    def test_param_map_variable_replaces_the_default_name_in_variables_sent(self):
        response = self._create_template(param_map={"model_name": {"variable": "vehicle"}})
        self.assertIn("vehicle", response.data["variables_sent"])
        self.assertNotIn("model_name", response.data["variables_sent"])

    def test_create_template_validation(self):
        cases = [
            ({"name": "", "curl": INBOUND_WHATSAPP_CURL}, "name"),
            ({"name": "x" * 65, "curl": INBOUND_WHATSAPP_CURL}, "name"),
            ({"name": "A"}, "curl"),
            ({"name": "A", "curl": "not a curl"}, "curl"),
            ({"name": "A", "curl": INBOUND_WHATSAPP_CURL, "channel": "sms"}, "channel"),
            ({"name": "A", "curl": INBOUND_WHATSAPP_CURL, "param_map": {"nope": {"fixed": "x"}}}, "param_map"),
            ({"name": "A", "curl": INBOUND_WHATSAPP_CURL, "param_map": {"link": {"fixed": "x", "variable": "y"}}}, "param_map"),
            ({"name": "A", "curl": INBOUND_WHATSAPP_CURL, "param_map": {"link": {}}}, "param_map"),
            ({"name": "A", "curl": INBOUND_WHATSAPP_CURL, "param_map": {"link": {"bogus": "x"}}}, "param_map"),
            ({"name": "A", "curl": INBOUND_WHATSAPP_CURL, "param_map": []}, "param_map"),
        ]
        for body, field in cases:
            response = self.client.post(f"{self.base}/channel-templates/", body, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, body)
            self.assertIn(field, response.data["error"], body)
        self.assertEqual(self.agent.channel_templates.count(), 0)

    def test_duplicate_template_name_is_rejected(self):
        self._create_template("Promo")
        response = self._create_template("Promo")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", response.data["error"])

    def test_patch_without_curl_keeps_the_stored_curl(self):
        template_id = self._create_template().data["id"]

        response = self.client.patch(
            f"{self.base}/channel-templates/{template_id}/",
            {"missing_fill": "n/a", "is_active": False, "param_map": {"customer_name": {"variable": "cust"}}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        template = ChannelTemplate.objects.get(pk=template_id)
        self.assertEqual(template.curl, INBOUND_WHATSAPP_CURL)
        self.assertEqual((template.missing_fill, template.is_active), ("n/a", False))
        self.assertEqual(template.param_map, {"customer_name": {"variable": "cust"}})

    def test_patch_with_a_new_curl_replaces_it_and_blank_curl_does_not(self):
        template_id = self._create_template().data["id"]
        new_curl = _text_only_curl("another_template")

        self.client.patch(f"{self.base}/channel-templates/{template_id}/", {"curl": "   "}, format="json")
        self.assertEqual(ChannelTemplate.objects.get(pk=template_id).curl, INBOUND_WHATSAPP_CURL)

        response = self.client.patch(f"{self.base}/channel-templates/{template_id}/", {"curl": new_curl}, format="json")
        self.assertEqual(response.data["template_title"], "another_template")
        self.assertEqual(ChannelTemplate.objects.get(pk=template_id).curl, new_curl)

    def test_patch_param_map_is_checked_against_the_stored_curl(self):
        template_id = self._create_template().data["id"]
        response = self.client.patch(
            f"{self.base}/channel-templates/{template_id}/", {"param_map": {"nope": {"fixed": "x"}}}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rename_to_an_existing_name_is_rejected_but_keeping_own_name_is_fine(self):
        self._create_template("A")
        b = self._create_template("B").data["id"]

        clash = self.client.patch(f"{self.base}/channel-templates/{b}/", {"name": "A"}, format="json")
        same = self.client.patch(f"{self.base}/channel-templates/{b}/", {"name": "B"}, format="json")

        self.assertEqual(clash.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(same.status_code, status.HTTP_200_OK)

    def test_delete_template_is_refused_while_a_rule_uses_it(self):
        template_id = self._create_template().data["id"]
        rule_id = self._create_rule(template=template_id).data["id"]

        refused = self.client.delete(f"{self.base}/channel-templates/{template_id}/")
        self.client.delete(f"{self.base}/channel-rules/{rule_id}/")
        allowed = self.client.delete(f"{self.base}/channel-templates/{template_id}/")

        self.assertEqual(refused.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(allowed.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ChannelTemplate.objects.filter(pk=template_id).exists())

    def test_another_agents_template_is_a_404(self):
        template_id = self._create_template().data["id"]
        other = ProcessAgent.objects.create(organization=make_org(), department=self.agent.department, name="Other")
        url = f"/api/telehub/process-agents/{other.id}/channel-templates/{template_id}/"

        self.assertEqual(self.client.patch(url, {"missing_fill": "x"}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)

    # ── rules ──────────────────────────────────────────────────────────────

    def test_create_send_rule_defaults_to_the_end_of_the_order(self):
        template_id = self._create_template().data["id"]

        first = self._create_rule(template=template_id, checks=[{"variable": "vip", "op": "exists"}])
        second = self._create_rule(template=template_id, match="any")

        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.data)
        self.assertEqual((first.data["priority"], second.data["priority"]), (0, 1))
        self.assertEqual(first.data["template_name"], "Promo")
        self.assertEqual(second.data["match"], "any")

    def test_create_skip_rule_needs_no_template(self):
        response = self._create_rule(
            action="skip", checks=[{"variable": "is_test", "op": "truthy"}], reason="test call"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertIsNone(response.data["template"])

    def test_rule_validation(self):
        template_id = self._create_template().data["id"]
        other_agent = ProcessAgent.objects.create(organization=make_org(), department=self.agent.department, name="O")
        foreign = ChannelTemplate.objects.create(process_agent=other_agent, name="Foreign", curl=INBOUND_WHATSAPP_CURL)
        cases = [
            ({"action": "send"}, "template"),
            ({"action": "send", "template": 99999}, "template"),
            ({"action": "send", "template": foreign.id}, "template"),
            ({"action": "explode", "template": template_id}, "action"),
            ({"template": template_id, "match": "some"}, "match"),
            ({"template": template_id, "checks": "nope"}, "checks"),
            ({"template": template_id, "checks": [{"variable": "a", "op": "bogus"}]}, "checks"),
            ({"template": template_id, "checks": [{"variable": "a", "op": "equals"}]}, "checks"),
            ({"template": template_id, "checks": [{"op": "exists"}]}, "checks"),
            ({"template": template_id, "priority": "first"}, "priority"),
        ]
        for body, field in cases:
            response = self._create_rule(**body)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, body)
            self.assertIn(field, response.data["error"], body)
        self.assertEqual(self.agent.channel_rules.count(), 0)

    def test_checks_are_normalised(self):
        template_id = self._create_template().data["id"]
        response = self._create_rule(
            template=template_id,
            checks=[
                {"variable": " callback_status ", "op": "equals", "value": "required", "junk": 1},
                {"variable": "name", "op": "exists", "value": "ignored"},
            ],
        )
        self.assertEqual(
            response.data["checks"],
            [
                {"variable": "callback_status", "op": "equals", "value": "required"},
                {"variable": "name", "op": "exists"},
            ],
        )

    def test_patch_rule_switching_to_skip_clears_the_template_and_back_requires_one(self):
        template_id = self._create_template().data["id"]
        rule_id = self._create_rule(template=template_id).data["id"]
        url = f"{self.base}/channel-rules/{rule_id}/"

        to_skip = self.client.patch(url, {"action": "skip", "reason": "no thanks"}, format="json")
        back_without = self.client.patch(url, {"action": "send"}, format="json")
        back_with = self.client.patch(url, {"action": "send", "template": template_id}, format="json")

        self.assertEqual((to_skip.status_code, to_skip.data["template"]), (200, None))
        self.assertEqual(back_without.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual((back_with.status_code, back_with.data["template"]), (200, template_id))

    def test_reorder_rules(self):
        template_id = self._create_template().data["id"]
        ids = [self._create_rule(template=template_id).data["id"] for _ in range(3)]

        response = self.client.post(f"{self.base}/channel-rules/reorder/", {"order": ids[::-1]}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual([r["id"] for r in response.data], ids[::-1])
        listing = self.client.get(f"{self.base}/channel-rules/")
        self.assertEqual([r["id"] for r in listing.data], ids[::-1])

    def test_reorder_must_list_every_rule_once(self):
        template_id = self._create_template().data["id"]
        ids = [self._create_rule(template=template_id).data["id"] for _ in range(2)]

        for order in ([ids[0]], [ids[0], ids[0]], [ids[0], 99999], "nope", None):
            response = self.client.post(f"{self.base}/channel-rules/reorder/", {"order": order}, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, order)

    def test_another_agents_rule_is_a_404(self):
        template_id = self._create_template().data["id"]
        rule_id = self._create_rule(template=template_id).data["id"]
        other = ProcessAgent.objects.create(organization=make_org(), department=self.agent.department, name="Other")
        url = f"/api/telehub/process-agents/{other.id}/channel-rules/{rule_id}/"

        self.assertEqual(self.client.patch(url, {"reason": "x"}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)

    # ── end to end + legacy interplay ──────────────────────────────────────

    def test_configured_through_the_api_a_completed_call_sends_the_chosen_template(self):
        template_id = self._create_template(
            "Thanks", param_map={"link": {"fixed": "https://x.test"}}, missing_fill="-"
        ).data["id"]
        self._create_rule(template=template_id, checks=[{"variable": "customer_name", "op": "exists"}])
        self.client.patch(f"{self.base}/omnichannel/", {"channel": "whatsapp", "auto_send": True}, format="json")
        execution = Execution.objects.create(
            organization=make_org(),
            process_agent=self.agent,
            lead_id="x",
            status="completed",
            variables={"caller_number": "+919876543210", "customer_name": "Ravi"},
        )

        omnichannel.on_call_completed(execution)
        with patch("apps.telehub.services.whatsapp._send_once", return_value=(200, "{}", None)) as mock_send:
            omnichannel.process_due_sends()

        send = WhatsAppSend.objects.get(execution=execution)
        self.assertEqual((send.template_key, send.status), ("Thanks", "sent"))
        params = json.loads(mock_send.call_args.args[1])["task_body"][0]["template_data"]["param_data"]
        self.assertEqual((params["link"], params["customer_name"], params["model_name"]), ("https://x.test", "Ravi", "-"))

    def test_enabling_whatsapp_on_a_new_agent_does_not_seed_hyundai_rules(self):
        self.client.patch(f"{self.base}/omnichannel/", {"channel": "whatsapp", "auto_send": True}, format="json")

        self.assertEqual(self.agent.channel_templates.count(), 0)
        self.assertEqual(self.agent.channel_rules.count(), 0)

    def test_sending_legacy_curls_through_the_omnichannel_endpoint_still_seeds(self):
        self.client.patch(
            f"{self.base}/omnichannel/",
            {"channel": "whatsapp", "whatsapp_curls": {"T1": INBOUND_WHATSAPP_CURL}},
            format="json",
        )

        self.assertEqual(self.agent.channel_templates.count(), 3)
        self.assertEqual(self.agent.channel_rules.count(), len(omnichannel_seed.SEED_RULES))

    def test_toggling_auto_send_does_not_overwrite_templates_edited_directly(self):
        self.client.patch(
            f"{self.base}/omnichannel/",
            {"channel": "whatsapp", "whatsapp_curls": {"T1": INBOUND_WHATSAPP_CURL}},
            format="json",
        )
        t1 = self.agent.channel_templates.get(name="T1")
        edited = _text_only_curl("edited_in_the_new_editor")
        self.client.patch(f"{self.base}/channel-templates/{t1.id}/", {"curl": edited}, format="json")

        self.client.patch(f"{self.base}/omnichannel/", {"auto_send": True}, format="json")

        self.assertEqual(self.agent.channel_templates.get(name="T1").curl, edited)


class WizardOmnichannelTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.department = Department.objects.create(organization=make_org(), name="Automobile")

    def _create(self, omnichannel):
        response = self.client.post(
            "/api/telehub/process-agents/",
            {"department": self.department.id, "name": "Wizard agent", "omnichannel": omnichannel},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return ProcessAgent.objects.get(pk=response.data["id"])

    def test_wizard_curl_becomes_one_default_template_with_an_always_rule(self):
        agent = self._create({"channel": "whatsapp", "whatsapp_curl": INBOUND_WHATSAPP_CURL})

        template = agent.channel_templates.get()
        self.assertEqual((template.name, template.curl), ("Default", INBOUND_WHATSAPP_CURL))
        rule = agent.channel_rules.get()
        self.assertEqual((rule.action, rule.template_id, rule.checks), ("send", template.id, []))
        self.assertEqual(agent.omnichannel.whatsapp_curl, "")

    def test_wizard_default_rule_sends_for_any_call(self):
        agent = self._create({"channel": "whatsapp", "whatsapp_curl": INBOUND_WHATSAPP_CURL})
        execution = Execution(organization=make_org(), process_agent=agent, lead_id="x", variables={})

        self.assertEqual(omnichannel.pick_template(execution), "Default")

    def test_wizard_without_a_curl_creates_no_templates_or_rules(self):
        agent = self._create({"channel": "whatsapp"})

        self.assertEqual(agent.channel_templates.count(), 0)
        self.assertEqual(agent.channel_rules.count(), 0)
        self.assertEqual(agent.omnichannel.channel, "whatsapp")


class VoiceBotNumbersTests(TestCase):
    """Step 5: a bot's DIDs are PhoneNumber rows, unique across every organisation."""

    def setUp(self):
        self.client = APIClient()

    def _create_bot(self, dids, **extra):
        return self.client.post("/api/telehub/voice-bots/", {"label": "Bot", "dids": dids, **extra}, format="json")

    def test_dids_become_phone_numbers(self):
        response = self._create_bot(["+917965311524", "7965311525"])

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual([n["did"] for n in response.data["numbers"]], ["+917965311524", "7965311525"])
        bot = VoiceBot.objects.get(pk=response.data["id"])
        self.assertEqual(
            list(bot.numbers.values_list("did_key", flat=True)), ["7965311524", "7965311525"]
        )

    def test_the_same_number_can_be_on_several_bots(self):
        # Calls reach an agent through its own webhook URL, so a DID never has to
        # identify a bot - two bots may list the same number (even in another spelling).
        first = self._create_bot(["+917965311524"])
        second = self._create_bot(["7965311524"])
        other = Organization.objects.create(name="Other", slug="other")
        third = VoiceBot.objects.create(organization=other, label="Theirs")
        PhoneNumber.objects.create(organization=other, voice_bot=third, did="917965311524")

        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.data)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED, second.data)
        self.assertEqual(PhoneNumber.objects.filter(did_key="7965311524").count(), 3)

    def test_invalid_dids_are_rejected(self):
        for bad in ("not a list", ["abc"], ["123"], [None, "12"]):
            response = self._create_bot(bad)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, bad)

    def test_duplicate_and_blank_entries_in_one_list_collapse(self):
        response = self._create_bot(["+917965311524", "", "917965311524"])

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["dids"], ["+917965311524"])
        self.assertEqual(len(response.data["numbers"]), 1)

    def test_editing_dids_adds_removes_and_keeps_the_rest(self):
        created = self._create_bot(["+917965311524", "7965311525"]).data
        kept_id = created["numbers"][0]["id"]

        response = self.client.patch(
            f"/api/telehub/voice-bots/{created['id']}/", {"dids": ["+917965311524", "7965311526"]}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual([n["did"] for n in response.data["numbers"]], ["+917965311524", "7965311526"])
        self.assertEqual(response.data["numbers"][0]["id"], kept_id)
        # The freed number can now be used by another bot.
        self.assertEqual(self._create_bot(["7965311525"]).status_code, status.HTTP_201_CREATED)

    def test_editing_other_fields_leaves_numbers_alone(self):
        created = self._create_bot(["+917965311524"]).data

        response = self.client.patch(f"/api/telehub/voice-bots/{created['id']}/", {"label": "Renamed"}, format="json")

        self.assertEqual(response.data["numbers"], created["numbers"])

    def test_a_bot_can_resubmit_its_own_numbers(self):
        created = self._create_bot(["+917965311524"]).data
        response = self.client.patch(
            f"/api/telehub/voice-bots/{created['id']}/", {"dids": ["917965311524"]}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_a_number_is_unique_within_a_bot_by_digits_not_spelling(self):
        org = make_org()
        bot = VoiceBot.objects.create(organization=org, label="A")
        other_bot = VoiceBot.objects.create(organization=org, label="B")
        PhoneNumber.objects.create(organization=org, voice_bot=bot, did="+91 79653 11524")
        PhoneNumber.objects.create(organization=org, voice_bot=other_bot, did="7965311524")  # another bot: fine
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PhoneNumber.objects.create(organization=org, voice_bot=bot, did="7965311524")

    def test_backfill_migration_registers_every_bots_dids_including_shared_ones(self):
        import importlib

        from django.apps import apps as django_apps

        org = make_org()
        first = VoiceBot.objects.create(organization=org, label="First", dids=["+917965311524", "7965311525"])
        second = VoiceBot.objects.create(organization=org, label="Second", dids=["917965311524", "7965311526"])
        repeated = VoiceBot.objects.create(organization=org, label="Repeated", dids=["917965311524", "+917965311524"])

        migration = importlib.import_module("apps.telehub.migrations.0021_backfill_phone_numbers")
        migration.backfill_phone_numbers(django_apps, None)

        self.assertEqual(sorted(first.numbers.values_list("did_key", flat=True)), ["7965311524", "7965311525"])
        self.assertEqual(sorted(second.numbers.values_list("did_key", flat=True)), ["7965311524", "7965311526"])
        self.assertEqual(list(repeated.numbers.values_list("did_key", flat=True)), ["7965311524"])
        self.assertEqual(second.dids, ["917965311524", "7965311526"])  # the legacy list is untouched

    def test_backfill_migration_is_safe_to_run_twice(self):
        import importlib

        from django.apps import apps as django_apps

        bot = VoiceBot.objects.create(organization=make_org(), label="A", dids=["7965311524"])
        migration = importlib.import_module("apps.telehub.migrations.0021_backfill_phone_numbers")
        migration.backfill_phone_numbers(django_apps, None)
        migration.backfill_phone_numbers(django_apps, None)

        self.assertEqual(bot.numbers.count(), 1)


def _post_bot(client, **body):
    response = client.post("/api/telehub/voice-bots/", body, format="json")
    assert response.status_code == 201, response.data
    return response.data


class StageApiTests(TestCase):
    """Step 5/6: stages (BotJourneys) with their bot and chosen numbers."""

    def setUp(self):
        self.client = APIClient()
        self.department = Department.objects.create(organization=make_org(), name="Automobile")
        self.inbound = _post_bot(
            self.client, label="Inbound", communication_type="voice_inbound", dids=["+917965311524", "+917965311525"]
        )
        self.outbound = _post_bot(
            self.client,
            label="Outbound",
            communication_type="voice_outbound",
            api_url="https://example.com/outbound",
            dids=["+917965314425", "+917965314426"],
        )
        response = self.client.post(
            "/api/telehub/process-agents/",
            {
                "department": self.department.id,
                "name": "Two stage",
                "voice": {"voice_bot_id": self.inbound["id"]},
                "business_rules": {"retry": {"attempts": 5, "interval_minutes": 7}},
            },
            format="json",
        )
        self.agent = ProcessAgent.objects.get(pk=response.data["id"])
        self.base = f"/api/telehub/process-agents/{self.agent.id}"

    def _add_stage(self, **body):
        return self.client.post(f"{self.base}/journeys/", {"name": "Follow-up", **body}, format="json")

    def test_add_stage_wires_the_bot_and_copies_the_first_stages_rules(self):
        response = self._add_stage(voice_bot=self.outbound["id"])

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["order"], 1)
        journey = BotJourney.objects.get(pk=response.data["id"])
        self.assertEqual(journey.nodes.count(), 9)
        self.assertEqual(journey.nodes.get(name="Retry").config, {"attempts": 5, "interval_minutes": 7})
        communication = journey.nodes.get(name="Communication").config
        self.assertEqual(communication["api_url"], "https://example.com/outbound")
        self.assertEqual(communication["communication_type"], "voice_outbound")
        # The first stage's Communication node is untouched.
        first = self.agent.bot_journeys.get(order=0)
        self.assertEqual(first.nodes.get(name="Communication").config["communication_type"], "voice_inbound")

    def test_a_stage_with_no_numbers_selected_uses_all_of_the_bots(self):
        response = self._add_stage(voice_bot=self.outbound["id"])
        self.assertEqual(response.data["numbers"], [])
        self.assertEqual(response.data["active_dids"], ["+917965314425", "+917965314426"])

    def test_a_stage_can_be_assigned_one_of_the_bots_numbers(self):
        second = self.outbound["numbers"][1]["id"]

        response = self._add_stage(voice_bot=self.outbound["id"], numbers=[second])

        self.assertEqual([n["did"] for n in response.data["numbers"]], ["+917965314426"])
        self.assertEqual(response.data["active_dids"], ["+917965314426"])

    def test_a_stage_is_assigned_at_most_one_number(self):
        both = [n["id"] for n in self.outbound["numbers"]]

        response = self._add_stage(voice_bot=self.outbound["id"], numbers=both)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("numbers", response.data["error"])
        self.assertEqual(self.agent.bot_journeys.count(), 1)

    def test_two_stages_may_be_assigned_the_same_number(self):
        number = self.outbound["numbers"][0]["id"]
        first = self._add_stage(name="A", voice_bot=self.outbound["id"], numbers=[number])
        second = self._add_stage(name="B", voice_bot=self.outbound["id"], numbers=[number])

        self.assertEqual((first.status_code, second.status_code), (201, 201))

    def test_stage_validation(self):
        other_bots_number = self.inbound["numbers"][0]["id"]
        cases = [
            ({"voice_bot": None}, "voice_bot"),
            ({"voice_bot": 99999}, "voice_bot"),
            ({"voice_bot": self.outbound["id"], "name": ""}, "name"),
            ({"voice_bot": self.outbound["id"], "numbers": [other_bots_number]}, "numbers"),
            ({"voice_bot": self.outbound["id"], "numbers": "all"}, "numbers"),
            ({"voice_bot": self.outbound["id"], "order": "second"}, "order"),
        ]
        for body, field in cases:
            response = self._add_stage(**body)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, body)
            self.assertIn(field, response.data["error"], body)
        self.assertEqual(self.agent.bot_journeys.count(), 1)

    def test_another_organisations_bot_cannot_be_used(self):
        other = Organization.objects.create(name="Other", slug="other")
        foreign = VoiceBot.objects.create(organization=other, label="Foreign")

        response = self._add_stage(voice_bot=foreign.id)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_switching_the_bot_clears_numbers_and_rewires_dispatch(self):
        stage = self._add_stage(voice_bot=self.outbound["id"], numbers=[self.outbound["numbers"][0]["id"]]).data
        replacement = _post_bot(
            self.client,
            label="Replacement",
            communication_type="voice_outbound",
            api_url="https://example.com/other",
            dids=["+917965314999"],
        )

        response = self.client.patch(
            f"{self.base}/journeys/{stage['id']}/", {"voice_bot": replacement["id"]}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["numbers"], [])
        self.assertEqual(response.data["active_dids"], ["+917965314999"])
        journey = BotJourney.objects.get(pk=stage["id"])
        self.assertEqual(journey.nodes.get(name="Communication").config["api_url"], "https://example.com/other")

    def test_patch_numbers_and_rename(self):
        stage = self._add_stage(voice_bot=self.outbound["id"]).data
        number_id = self.outbound["numbers"][0]["id"]

        response = self.client.patch(
            f"{self.base}/journeys/{stage['id']}/", {"name": "Callbacks", "numbers": [number_id]}, format="json"
        )

        self.assertEqual((response.data["name"], [n["id"] for n in response.data["numbers"]]), ("Callbacks", [number_id]))
        cleared = self.client.patch(f"{self.base}/journeys/{stage['id']}/", {"numbers": []}, format="json")
        self.assertEqual(cleared.data["numbers"], [])

    def test_removing_a_number_from_the_bot_drops_it_from_stages(self):
        stage = self._add_stage(voice_bot=self.outbound["id"], numbers=[self.outbound["numbers"][0]["id"]]).data

        self.client.patch(
            f"/api/telehub/voice-bots/{self.outbound['id']}/", {"dids": ["+917965314426"]}, format="json"
        )

        journey = BotJourney.objects.get(pk=stage["id"])
        self.assertEqual(journey.numbers.count(), 0)
        self.assertEqual(numbers_service.journey_dids(journey), ["+917965314426"])

    def test_delete_stage_cascades_transitions_but_the_last_stage_is_protected(self):
        stage = self._add_stage(voice_bot=self.outbound["id"]).data
        first = self.agent.bot_journeys.get(order=0)
        self.client.post(
            f"{self.base}/journey-transitions/", {"from_journey": first.id, "to_journey": stage["id"]}, format="json"
        )

        self.assertEqual(self.client.delete(f"{self.base}/journeys/{stage['id']}/").status_code, 204)
        self.assertEqual(self.agent.journey_transitions.count(), 0)
        self.assertEqual(self.client.delete(f"{self.base}/journeys/{first.id}/").status_code, 400)

    def test_another_agents_stage_is_a_404(self):
        stage = self._add_stage(voice_bot=self.outbound["id"]).data
        other = ProcessAgent.objects.create(organization=make_org(), department=self.department, name="Other")

        response = self.client.patch(
            f"/api/telehub/process-agents/{other.id}/journeys/{stage['id']}/", {"name": "x"}, format="json"
        )

        self.assertEqual(response.status_code, 404)

    # ── dispatch uses the stage's numbers ──────────────────────────────────

    def _dispatch_from(self, execution):
        with patch("apps.telehub.services.dispatcher.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.getcode.return_value = 200
            mock_urlopen.return_value.__enter__.return_value.read.return_value = b"OK"
            dispatch_execution(execution)
        return json.loads(mock_urlopen.call_args[0][0].data.decode())["from"]

    def test_outbound_dials_from_the_stages_selected_number(self):
        stage = self._add_stage(voice_bot=self.outbound["id"], numbers=[self.outbound["numbers"][1]["id"]]).data
        journey = BotJourney.objects.get(pk=stage["id"])
        execution = Execution.objects.create(
            organization=make_org(),
            process_agent=self.agent,
            lead_id="x",
            current_bot_journey=journey,
            variables={"to_number": "+911234567890"},
        )

        self.assertEqual(self._dispatch_from(execution), "+917965314426")

    def test_outbound_without_a_selection_dials_from_the_bots_first_number(self):
        journey = BotJourney.objects.get(pk=self._add_stage(voice_bot=self.outbound["id"]).data["id"])
        execution = Execution.objects.create(
            organization=make_org(),
            process_agent=self.agent,
            lead_id="x",
            current_bot_journey=journey,
            variables={"to_number": "+911234567890"},
        )

        self.assertEqual(self._dispatch_from(execution), "+917965314425")


class SharedDidAcrossBotsTests(TestCase):
    """Two bots listing the same DID (as in the live database) both keep working."""

    def test_both_bots_dial_from_the_shared_number(self):
        client = APIClient()
        department = Department.objects.create(organization=make_org(), name="Automobile")
        for label in ("Bot one", "Bot two"):
            _post_bot(
                client,
                label=label,
                communication_type="voice_outbound",
                api_url="https://example.com/outbound",
                dids=["917965314458"],
            )
        for bot in VoiceBot.objects.order_by("id"):
            agent = ProcessAgent.objects.create(organization=make_org(), department=department, name=bot.label)
            journey = BotJourney.objects.create(process_agent=agent, voice_bot=bot, name="J", order=0)
            generate_journey(journey)
            push_bot = __import__("apps.telehub.services.stages", fromlist=["x"]).push_bot_to_communication_node
            push_bot(journey)
            execution = Execution.objects.create(
                organization=make_org(),
                process_agent=agent,
                lead_id="x",
                current_bot_journey=journey,
                variables={"to_number": "+911234567890"},
            )
            with patch("apps.telehub.services.dispatcher.urllib.request.urlopen") as mock_urlopen:
                mock_urlopen.return_value.__enter__.return_value.getcode.return_value = 200
                mock_urlopen.return_value.__enter__.return_value.read.return_value = b"OK"
                dispatch_execution(execution)
            self.assertEqual(json.loads(mock_urlopen.call_args[0][0].data.decode())["from"], "917965314458")


class InboundDidVerificationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        department = Department.objects.create(organization=make_org(), name="Automobile")
        self.bot = _post_bot(
            self.client, label="Inbound", communication_type="voice_inbound", dids=["+917965311524", "+917965311525"]
        )
        response = self.client.post(
            "/api/telehub/process-agents/",
            {"department": department.id, "name": "Inbound", "voice": {"voice_bot_id": self.bot["id"]}},
            format="json",
        )
        self.agent = ProcessAgent.objects.get(pk=response.data["id"])
        self.webhook = WebhookDefinition.objects.get(process_agent=self.agent)

    def _call(self, **payload):
        body = {"caller_number": "916359724704", "session_id": f"s-{ExecutionEvent.objects.count()}", **payload}
        self.client.post(f"/api/telehub/webhooks/{self.webhook.secret}/", body, format="json")
        return Execution.objects.filter(process_agent=self.agent).order_by("-id").first()

    def test_dialing_one_of_the_agents_numbers_is_not_flagged(self):
        execution = self._call(callee_number="917965311524")
        self.assertNotIn("did_mismatch", execution.variables)

    def test_the_number_is_compared_by_digits_not_spelling(self):
        for spelling in ("7965311525", "+91 79653 11525", "917965311525"):
            self.assertNotIn("did_mismatch", self._call(callee_number=spelling).variables, spelling)

    def test_dialing_another_number_is_recorded_but_flagged(self):
        execution = self._call(callee_number="919999999999", complaint="engine")

        self.assertIs(execution.variables["did_mismatch"], True)
        self.assertEqual(execution.status, "completed")
        self.assertEqual(execution.variables["complaint"], "engine")
        event = ExecutionEvent.objects.get(execution=execution, event_type="did_mismatch")
        self.assertEqual(event.payload["callee_number"], "919999999999")
        self.assertIn("+917965311524", event.payload["expected"])
        self.assertTrue(hasattr(execution, "qa_result"))

    def test_a_payload_without_a_dialed_number_is_not_flagged(self):
        self.assertNotIn("did_mismatch", self._call().variables)

    def test_a_stage_restricted_to_one_number_rejects_the_others(self):
        journey = self.agent.bot_journeys.get()
        journey.numbers.set([self.bot["numbers"][0]["id"]])

        self.assertNotIn("did_mismatch", self._call(callee_number="917965311524").variables)
        self.assertIs(self._call(callee_number="917965311525").variables["did_mismatch"], True)

    def test_a_bot_with_no_numbers_is_never_flagged(self):
        PhoneNumber.objects.filter(voice_bot_id=self.bot["id"]).delete()
        VoiceBot.objects.filter(pk=self.bot["id"]).update(dids=[])

        self.assertNotIn("did_mismatch", self._call(callee_number="919999999999").variables)

    def test_a_rule_can_skip_whatsapp_for_mismatched_calls(self):
        OmnichannelConfig.objects.create(process_agent=self.agent, channel="whatsapp", auto_send=True)
        template = ChannelTemplate.objects.create(process_agent=self.agent, name="Hi", curl=INBOUND_WHATSAPP_CURL)
        ChannelRule.objects.create(
            process_agent=self.agent,
            priority=0,
            action="skip",
            reason="wrong number dialed",
            checks=[{"variable": "did_mismatch", "op": "truthy"}],
        )
        ChannelRule.objects.create(process_agent=self.agent, priority=1, template=template)

        execution = self._call(callee_number="919999999999")

        send = WhatsAppSend.objects.get(execution=execution)
        self.assertEqual((send.status, send.last_error), ("skipped", "wrong number dialed"))


class HandoffTests(TestCase):
    """Step 6: a finished call's results start the lead's next stage as a new Execution."""

    PAYLOAD = {
        "caller_number": "916359724704",
        "callee_number": "917965311524",
        "call_start_time": "18:19:44",
        "complaint_query": "engine noise",
        "interested": "yes",
    }

    def setUp(self):
        self.client = APIClient()
        department = Department.objects.create(organization=make_org(), name="Automobile")
        self.inbound = _post_bot(
            self.client, label="Inbound", communication_type="voice_inbound", dids=["+917965311524"]
        )
        self.outbound = _post_bot(
            self.client,
            label="Outbound",
            communication_type="voice_outbound",
            api_url="https://example.com/outbound",
            dids=["+917965314425"],
        )
        response = self.client.post(
            "/api/telehub/process-agents/",
            {"department": department.id, "name": "Sales", "voice": {"voice_bot_id": self.inbound["id"]}},
            format="json",
        )
        self.agent = ProcessAgent.objects.get(pk=response.data["id"])
        self.webhook = WebhookDefinition.objects.get(process_agent=self.agent)
        self.base = f"/api/telehub/process-agents/{self.agent.id}"
        self.first = self.agent.bot_journeys.get(order=0)
        self.second = BotJourney.objects.get(
            pk=self.client.post(
                f"{self.base}/journeys/", {"name": "Follow-up", "voice_bot": self.outbound["id"]}, format="json"
            ).data["id"]
        )

    def _transition(self, **body):
        body = {"from_journey": self.first.id, "to_journey": self.second.id, **body}
        response = self.client.post(f"{self.base}/journey-transitions/", body, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response.data

    def _inbound_call(self, **extra):
        payload = {**self.PAYLOAD, "session_id": f"s-{Execution.objects.count()}", **extra}
        self.client.post(f"/api/telehub/webhooks/{self.webhook.secret}/", payload, format="json")
        return Execution.objects.filter(process_agent=self.agent, parent_execution__isnull=True).order_by("-id").first()

    def _outbound_execution(self, journey=None, **variables):
        return Execution.objects.create(
            organization=make_org(),
            process_agent=self.agent,
            lead_id="lead-1",
            status="dispatched",
            current_bot_journey=journey or self.first,
            variables={"to_number": "+916359724704", **variables},
        )

    # ── completed ──────────────────────────────────────────────────────────

    def test_a_completed_call_starts_the_next_stage_as_a_new_execution(self):
        self._transition(checks=[{"variable": "interested", "op": "equals", "value": "yes"}])

        parent = self._inbound_call()

        child = parent.children.get()
        self.assertEqual(child.parent_execution_id, parent.id)
        self.assertEqual(child.current_bot_journey_id, self.second.id)
        self.assertEqual((child.status, child.current_node, child.attempt_count), ("pending", "Lead Received", 0))
        self.assertLessEqual(child.next_execution, timezone.now())
        self.assertEqual(child.organization_id, parent.organization_id)
        self.assertEqual(child.variables["to_number"], "+916359724704")
        self.assertEqual(child.variables["complaint_query"], "engine noise")
        self.assertEqual(child.variables["interested"], "yes")
        for per_call in ("session_id", "call_start_time", "call_duration"):
            self.assertNotIn(per_call, child.variables)
        self.assertEqual(parent.status, "completed")
        self.assertTrue(ExecutionEvent.objects.filter(execution=parent, event_type="handed_off").exists())
        self.assertTrue(ExecutionEvent.objects.filter(execution=child, event_type="created_by_handoff").exists())

    def test_checks_decide_whether_the_lead_is_handed_on(self):
        self._transition(checks=[{"variable": "interested", "op": "equals", "value": "yes"}])

        parent = self._inbound_call(interested="no")

        self.assertFalse(parent.children.exists())

    def test_a_transition_without_checks_always_applies(self):
        self._transition()
        self.assertTrue(self._inbound_call(interested="no").children.exists())

    def test_the_first_matching_transition_by_priority_wins(self):
        third = BotJourney.objects.get(
            pk=self.client.post(
                f"{self.base}/journeys/", {"name": "Escalation", "voice_bot": self.outbound["id"]}, format="json"
            ).data["id"]
        )
        self._transition(to_journey=third.id, priority=1)
        self._transition(to_journey=self.second.id, priority=0)

        parent = self._inbound_call()

        self.assertEqual(parent.children.get().current_bot_journey_id, self.second.id)

    def test_a_resent_webhook_does_not_fork_the_lead(self):
        self._transition()
        payload = {**self.PAYLOAD, "session_id": "same"}
        for _ in range(3):
            self.client.post(f"/api/telehub/webhooks/{self.webhook.secret}/", payload, format="json")

        self.assertEqual(Execution.objects.filter(parent_execution__isnull=False).count(), 1)

    def test_a_lead_is_handed_on_at_most_once_per_execution(self):
        self._transition()
        parent = self._inbound_call()

        self.assertIsNone(handoff.run_completed_transitions(parent))
        self.assertEqual(parent.children.count(), 1)

    def test_each_stage_keeps_its_own_qa_result(self):
        self._transition()
        parent = self._inbound_call()
        child = parent.children.get()

        route_webhook_outcome(child, {"contact_no": "6359724704", "summary": "follow-up done", "outcome": "answered"})

        self.assertEqual(QAResult.objects.filter(execution=parent).count(), 1)
        self.assertEqual(child.qa_result.summary, "follow-up done")
        self.assertNotEqual(parent.qa_result.pk, child.qa_result.pk)

    def test_the_new_stage_is_picked_up_by_the_scheduler(self):
        self._transition()
        child = self._inbound_call().children.get()

        with patch("apps.telehub.services.dispatcher.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.getcode.return_value = 200
            mock_urlopen.return_value.__enter__.return_value.read.return_value = b"OK"
            processed = tick()

        self.assertEqual(processed, 1)
        child.refresh_from_db()
        self.assertEqual(child.status, "dispatched")
        body = json.loads(mock_urlopen.call_args[0][0].data.decode())
        self.assertEqual(body["from"], "+917965314425")
        self.assertEqual(body["to"], "+916359724704")
        self.assertEqual(body["params"]["complaint_query"], "engine noise")

    def test_a_stage_never_hands_back_into_one_it_already_went_through(self):
        self._transition()
        self._transition(from_journey=self.second.id, to_journey=self.first.id)
        child = self._inbound_call().children.get()

        route_webhook_outcome(child, {"contact_no": "6359724704", "outcome": "answered"})

        self.assertFalse(child.children.exists())
        event = ExecutionEvent.objects.get(execution=child, event_type="handoff_blocked")
        self.assertEqual(event.payload["reason"], "loop")

    def test_outbound_results_follow_completed_transitions_too(self):
        self._transition(checks=[{"variable": "interested", "op": "exists"}])
        execution = self._outbound_execution()

        route_webhook_outcome(execution, {"contact_no": "6359724704", "outcome": "answered", "interested": "yes"})

        self.assertEqual(execution.children.get().current_bot_journey_id, self.second.id)

    def test_a_failed_call_that_will_be_retried_is_not_handed_on(self):
        self._transition()
        execution = self._outbound_execution()  # attempt_count 0 of the default 3

        route_webhook_outcome(execution, {"contact_no": "6359724704", "outcome": "no_answer"})

        execution.refresh_from_db()
        self.assertEqual(execution.status, "retry_scheduled")
        self.assertFalse(execution.children.exists())

    def test_a_call_that_schedules_a_callback_is_not_handed_on(self):
        self._transition()
        self.first.nodes.filter(name="Callback").update(
            config={"conditions": [{"variable": "callback_requested", "operator": "equals", "value": "yes"}]}
        )
        execution = self._outbound_execution()

        with patch("apps.telehub.services.outcome_routing.callback_schedule.schedule_callback", return_value=True):
            route_webhook_outcome(execution, {"contact_no": "6359724704", "outcome": "answered"})

        self.assertFalse(execution.children.exists())

    # ── retries exhausted ──────────────────────────────────────────────────

    def _exhausted(self):
        execution = self._outbound_execution()
        execution.attempt_count = 3
        execution.save()
        route_webhook_outcome(execution, {"contact_no": "6359724704", "outcome": "no_answer"})
        execution.refresh_from_db()
        return execution

    def test_exhausted_retries_follow_a_retries_exhausted_transition(self):
        self._transition(on="retries_exhausted")

        execution = self._exhausted()

        self.assertEqual(execution.status, "failed")
        child = execution.children.get()
        self.assertEqual(child.current_bot_journey_id, self.second.id)
        self.assertTrue(ExecutionEvent.objects.filter(execution=execution, event_type="journey_advanced").exists())

    def test_with_retries_exhausted_transitions_configured_only_they_decide(self):
        self._transition(on="retries_exhausted", checks=[{"variable": "vip", "op": "exists"}])

        execution = self._exhausted()

        self.assertFalse(execution.children.exists())

    def test_without_any_transition_exhausted_retries_fall_through_to_the_next_stage_by_order(self):
        execution = self._exhausted()

        child = execution.children.get()
        self.assertEqual(child.current_bot_journey_id, self.second.id)
        self.assertEqual(execution.status, "failed")

    def test_a_completed_transition_does_not_stop_the_exhausted_fallback(self):
        self._transition(on="completed", checks=[{"variable": "vip", "op": "exists"}])

        self.assertTrue(self._exhausted().children.exists())

    def test_the_last_stage_has_nowhere_to_fall_through_to(self):
        execution = self._outbound_execution(journey=self.second)
        execution.attempt_count = 3
        execution.save()

        route_webhook_outcome(execution, {"contact_no": "6359724704", "outcome": "no_answer"})

        self.assertFalse(execution.children.exists())

    # ── transitions API ────────────────────────────────────────────────────

    def test_transitions_api_crud(self):
        created = self._transition(checks=[{"variable": "interested", "op": "equals", "value": "yes"}], match="any")

        self.assertEqual((created["from_name"], created["to_name"], created["on"]), ("Sales Journey", "Follow-up", "completed"))
        listing = self.client.get(f"{self.base}/journey-transitions/")
        self.assertEqual([t["id"] for t in listing.data], [created["id"]])

        patched = self.client.patch(
            f"{self.base}/journey-transitions/{created['id']}/", {"on": "retries_exhausted", "checks": []}, format="json"
        )
        self.assertEqual((patched.data["on"], patched.data["checks"]), ("retries_exhausted", []))

        self.assertEqual(self.client.delete(f"{self.base}/journey-transitions/{created['id']}/").status_code, 204)

    def test_new_transitions_go_to_the_end_of_the_order(self):
        first, second = self._transition(), self._transition()
        self.assertEqual((first["priority"], second["priority"]), (0, 1))

    def test_transition_validation(self):
        other = ProcessAgent.objects.create(organization=make_org(), department=self.agent.department, name="Other")
        foreign = BotJourney.objects.create(process_agent=other, name="Foreign", order=0)
        cases = [
            ({"from_journey": self.first.id, "to_journey": self.first.id}, "to_journey"),
            ({"to_journey": foreign.id}, "to_journey"),
            ({"from_journey": foreign.id}, "from_journey"),
            ({"to_journey": None}, "to_journey"),
            ({"on": "sometimes"}, "on"),
            ({"match": "some"}, "match"),
            ({"checks": [{"variable": "x", "op": "bogus"}]}, "checks"),
            ({"priority": "high"}, "priority"),
        ]
        for body, field in cases:
            body = {"from_journey": self.first.id, "to_journey": self.second.id, **body}
            response = self.client.post(f"{self.base}/journey-transitions/", body, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, body)
            self.assertIn(field, response.data["error"], body)

    def test_another_agents_transition_is_a_404(self):
        created = self._transition()
        other = ProcessAgent.objects.create(organization=make_org(), department=self.agent.department, name="Other")
        url = f"/api/telehub/process-agents/{other.id}/journey-transitions/{created['id']}/"

        self.assertEqual(self.client.patch(url, {"on": "completed"}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)

    def test_check_tenancy_flags_a_transition_between_different_agents_stages(self):
        other = ProcessAgent.objects.create(organization=make_org(), department=self.agent.department, name="Other")
        foreign = BotJourney.objects.create(process_agent=other, name="Foreign", order=0)
        JourneyTransition.objects.create(process_agent=self.agent, from_journey=self.first, to_journey=foreign)

        rules = [rule for rule, _ in find_violations()]

        self.assertIn("JourneyTransition stages belong to a different process agent", rules)


# ---------------------------------------------------------------------------
# Phase 0 — tenancy
# ---------------------------------------------------------------------------

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from .models import Membership
from .services.tenancy import find_violations


def _tenant_fixture(org):
    """One of everything an org owns, all linked consistently."""
    department = Department.objects.create(organization=org, name=f"{org.slug} dept")
    bot = VoiceBot.objects.create(organization=org, label=f"{org.slug} bot")
    integration = Integration.objects.create(organization=org, name=f"{org.slug} crm", type="crm")
    agent = ProcessAgent.objects.create(organization=org, department=department, name=f"{org.slug} agent")
    journey = BotJourney.objects.create(process_agent=agent, voice_bot=bot, name="J", order=0)
    ProcessIntegration.objects.create(process_agent=agent, integration=integration)
    return {
        "department": department, "bot": bot, "integration": integration,
        "agent": agent, "journey": journey,
    }


@override_settings(TELEHUB_AUTH_REQUIRED=True)
class OrgResolutionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.org_a = make_org("org-a")
        self.org_b = make_org("org-b")
        self.one = User.objects.create_user("one", password="pw")
        Membership.objects.create(user=self.one, organization=self.org_a)
        self.two = User.objects.create_user("two", password="pw")
        Membership.objects.create(user=self.two, organization=self.org_a)
        Membership.objects.create(user=self.two, organization=self.org_b)
        self.staff = User.objects.create_user("staff", password="pw", is_staff=True)
        _tenant_fixture(self.org_a)
        _tenant_fixture(self.org_b)

    def _get(self, user, header=None):
        client = APIClient()
        if user is not None:
            client.force_authenticate(user=user)
        extra = {"HTTP_X_ORGANIZATION": header} if header else {}
        return client.get("/api/telehub/departments/", **extra)

    def test_unauthenticated_is_rejected(self):
        self.assertEqual(self._get(None).status_code, 401)

    def test_missing_header_single_membership_ok(self):
        response = self._get(self.one)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)

    def test_missing_header_multiple_memberships_is_400(self):
        self.assertEqual(self._get(self.two).status_code, 400)

    def test_non_member_is_403(self):
        self.assertEqual(self._get(self.one, "org-b").status_code, 403)

    def test_member_with_header_ok(self):
        self.assertEqual(self._get(self.two, "org-b").status_code, 200)

    def test_staff_can_act_in_any_org(self):
        self.assertEqual(self._get(self.staff, "org-b").status_code, 200)

    def test_token_and_me_endpoints(self):
        client = APIClient()
        token = client.post("/api/auth/token/", {"username": "two", "password": "pw"}, format="json")
        self.assertEqual(token.status_code, 200)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.json()['access']}")
        me = client.get("/api/auth/me/").json()
        self.assertEqual(me["username"], "two")
        self.assertEqual({o["slug"] for o in me["organizations"]}, {"org-a", "org-b"})


@override_settings(TELEHUB_AUTH_REQUIRED=True)
class CrossTenantIsolationTests(TestCase):
    ROUTES = [
        ("departments", "department"), ("voice-bots", "bot"),
        ("integrations", "integration"), ("process-agents", "agent"),
    ]

    def setUp(self):
        self.org_a = make_org("org-a")
        self.org_b = make_org("org-b")
        self.a = _tenant_fixture(self.org_a)
        self.b = _tenant_fixture(self.org_b)
        user = get_user_model().objects.create_user("a-user", password="pw")
        Membership.objects.create(user=user, organization=self.org_a)
        self.client = APIClient()
        self.client.force_authenticate(user=user)

    def test_list_excludes_other_org(self):
        for route, key in self.ROUTES:
            ids = {row["id"] for row in self.client.get(f"/api/telehub/{route}/").json()}
            self.assertIn(self.a[key].pk, ids, route)
            self.assertNotIn(self.b[key].pk, ids, route)

    def test_other_org_objects_are_404(self):
        for route, key in self.ROUTES:
            url = f"/api/telehub/{route}/{self.b[key].pk}/"
            self.assertEqual(self.client.get(url).status_code, 404, route)
            self.assertEqual(self.client.patch(url, {"name": "x"}, format="json").status_code, 404, route)
            self.assertEqual(self.client.delete(url).status_code, 404, route)

    def test_agent_actions_on_other_org_agent_are_404(self):
        url = f"/api/telehub/process-agents/{self.b['agent'].pk}/launch-campaign/"
        response = self.client.post(url, {"leads": [{"to_number": "9999999999"}]}, format="json")
        self.assertEqual(response.status_code, 404)

    def test_create_ignores_client_supplied_organization(self):
        response = self.client.post(
            "/api/telehub/departments/", {"name": "New", "organization": self.org_b.pk}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Department.objects.get(pk=response.json()["id"]).organization, self.org_a)

    def test_wizard_rejects_other_org_ids_and_creates_nothing(self):
        before = ProcessAgent.objects.count()
        payloads = [
            {"department": self.b["department"].pk, "name": "X"},
            {"department": self.a["department"].pk, "name": "X",
             "voice": {"voice_bot_id": self.b["bot"].pk}},
            {"department": self.a["department"].pk, "name": "X",
             "integrations": [self.b["integration"].pk]},
        ]
        for payload in payloads:
            response = self.client.post("/api/telehub/process-agents/", payload, format="json")
            self.assertEqual(response.status_code, 400, payload)
        self.assertEqual(ProcessAgent.objects.count(), before)

    def test_wizard_stamps_org_on_created_rows(self):
        response = self.client.post(
            "/api/telehub/process-agents/",
            {"department": self.a["department"].pk, "name": "Ok",
             "voice": {"voice_bot_id": self.a["bot"].pk},
             "lead_source": {"type": "upload"}},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        agent = ProcessAgent.objects.get(pk=response.json()["id"])
        self.assertEqual(agent.organization, self.org_a)
        self.assertEqual({ls.organization for ls in agent.lead_sources.all()}, {self.org_a})

    def test_attach_other_org_integration_is_400(self):
        response = self.client.post(
            f"/api/telehub/process-agents/{self.a['agent'].pk}/integrations/",
            {"integration": self.b["integration"].pk},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_webhook_intake_is_unauthenticated_and_routes_in_webhooks_org(self):
        webhook = WebhookDefinition.objects.create(
            organization=self.org_b, process_agent=self.b["agent"], name="cb", secret="s3cret"
        )
        execution = Execution.objects.create(
            organization=self.org_b, process_agent=self.b["agent"], lead_id="1", status="pending",
            variables={"to_number": "+911234567890"},
        )
        response = APIClient().post(
            f"/api/telehub/webhooks/{webhook.secret}/",
            {"dlr_id": str(execution.id), "marker": "seen"}, format="json",
        )
        self.assertEqual(response.status_code, 200)
        execution.refresh_from_db()
        self.assertEqual(execution.variables.get("marker"), "seen")
        self.assertEqual(execution.organization, self.org_b)

    def test_launch_campaign_stamps_execution_org(self):
        launch_campaign(self.b["agent"], {"campaign_id": "c", "leads": [{"to_number": "9999999999"}]})
        execution = Execution.objects.get(process_agent=self.b["agent"])
        self.assertEqual(execution.organization, self.org_b)

    def test_duplicate_webhook_secret_rejected(self):
        WebhookDefinition.objects.create(
            organization=self.org_a, process_agent=self.a["agent"], name="x", secret="dup"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            WebhookDefinition.objects.create(
                organization=self.org_a, process_agent=self.a["agent"], name="y", secret="dup"
            )
        # blank secrets are exempt
        WebhookDefinition.objects.create(organization=self.org_a, process_agent=self.a["agent"], name="p")
        WebhookDefinition.objects.create(organization=self.org_a, process_agent=self.a["agent"], name="q")


class AuthFlagOffTests(TestCase):
    @override_settings(TELEHUB_AUTH_REQUIRED=False)
    def test_unauthenticated_requests_use_default_org(self):
        default = make_org("excell-autovista")
        other = make_org("org-b")
        mine = Department.objects.create(organization=default, name="mine")
        Department.objects.create(organization=other, name="theirs")
        response = APIClient().get("/api/telehub/departments/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()], [mine.pk])


class TenancyCommandTests(TestCase):
    def setUp(self):
        self.default = make_org("excell-autovista")
        self.a = _tenant_fixture(self.default)

    def _assign(self, dry_run):
        call_command(
            "assign_org", org="hyundai-poc", org_name="", departments=[self.a["department"].pk],
            dry_run=dry_run, stdout=StringIO(),
        )

    def test_check_tenancy_clean(self):
        self.assertEqual(find_violations(), [])

    def test_check_tenancy_detects_mismatched_bot(self):
        other = make_org("org-b")
        foreign_bot = VoiceBot.objects.create(organization=other, label="foreign")
        self.a["journey"].voice_bot = foreign_bot
        self.a["journey"].save()
        rules = [rule for rule, _ in find_violations()]
        self.assertTrue(any(rule.startswith("BotJourney.voice_bot") for rule in rules))
        with self.assertRaises(CommandError):
            call_command("check_tenancy", stdout=StringIO())

    def test_assign_org_moves_whole_tree(self):
        Execution.objects.create(
            organization=self.default, process_agent=self.a["agent"], lead_id="1", status="pending"
        )
        self._assign(dry_run=True)
        self.assertFalse(Organization.objects.filter(slug="hyundai-poc").exists())

        self._assign(dry_run=False)
        hyundai = Organization.objects.get(slug="hyundai-poc")
        for obj in (self.a["department"], self.a["agent"], self.a["bot"], self.a["integration"]):
            obj.refresh_from_db()
            self.assertEqual(obj.organization, hyundai)
        self.assertEqual(Execution.objects.get(process_agent=self.a["agent"]).organization, hyundai)
        self.assertEqual(find_violations(), [])

    def test_assign_org_refuses_bot_shared_with_staying_agent(self):
        staying_dept = Department.objects.create(organization=self.default, name="stay")
        staying_agent = ProcessAgent.objects.create(
            organization=self.default, department=staying_dept, name="stay"
        )
        BotJourney.objects.create(process_agent=staying_agent, voice_bot=self.a["bot"], name="J", order=0)
        with self.assertRaises(CommandError):
            self._assign(dry_run=False)
        self.a["department"].refresh_from_db()
        self.assertEqual(self.a["department"].organization, self.default)
