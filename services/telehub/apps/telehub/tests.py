from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import (
    Department,
    Execution,
    Integration,
    NodeConnection,
    NodeInstance,
    NodeTemplate,
    ProcessAgent,
    ProcessIntegration,
    QAResult,
    Variable,
)
from .services.journey import JOURNEY_STEPS, generate_journey


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
