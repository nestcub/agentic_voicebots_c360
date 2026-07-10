from ..models import NodeConnection, NodeInstance, ProcessAgent
from .seed_node_templates import seed_node_templates

# Per docs/superpowers/plans/gpt_ai_hub_impl_plan.md "Journey" section. Main trunk:
# Lead Received -> Business Hours -> DND Check -> Communication -> Completed.
# Retry, Callback, QA and CRM Update are NOT steps on the way to Completed — they
# are outcome branches evaluated AFTER a call completes (see JOURNEY_EDGES below):
# Retry and Callback loop back to Business Hours to re-attempt the process; QA and
# CRM Update are terminal side effects with no further outgoing edge.
# Each entry: (name, node_template type, position_x, position_y).
JOURNEY_STEPS = [
    ("Lead Received", "trigger", 60, 140),
    ("Business Hours", "logic", 240, 140),
    ("DND Check", "logic", 420, 140),
    ("Communication", "communication", 600, 140),
    ("Completed", "output", 780, 140),
    ("Retry", "retry", 960, 20),
    ("Callback", "logic", 960, 100),
    ("QA", "qa", 960, 180),
    ("CRM Update", "integration", 960, 260),
]

# (source name, target name) — explicit, since the graph branches (Completed fans
# out to 4 nodes) and loops (Retry/Callback back to Business Hours), which a
# simple zip(nodes, nodes[1:]) linear chain can no longer express.
JOURNEY_EDGES = [
    ("Lead Received", "Business Hours"),
    ("Business Hours", "DND Check"),
    ("DND Check", "Communication"),
    ("Communication", "Completed"),
    ("Completed", "Retry"),
    ("Completed", "Callback"),
    ("Completed", "QA"),
    ("Completed", "CRM Update"),
    ("Retry", "Business Hours"),
    ("Callback", "Business Hours"),
]


def generate_journey(process_agent: "ProcessAgent") -> None:
    """
    Idempotent: clears and rebuilds this process_agent's NodeInstance/NodeConnection
    rows from the fixed JOURNEY_STEPS/JOURNEY_EDGES graph (9 nodes, 10 edges). Main
    trunk: Lead Received -> Business Hours -> DND Check -> Communication ->
    Completed. Retry/Callback/QA/CRM Update all branch off Completed; Retry and
    Callback loop back to Business Hours to re-attempt. V1 is form-driven only:
    users view this generated graph, they don't hand-edit it (no React Flow yet).
    """
    templates = seed_node_templates()

    # Deleting NodeInstances cascades to NodeConnection (source_node/target_node
    # are both on_delete=CASCADE from NodeInstance), so this alone clears both.
    process_agent.nodes.all().delete()

    nodes_by_name = {}
    for name, template_type, x, y in JOURNEY_STEPS:
        nodes_by_name[name] = NodeInstance.objects.create(
            process_agent=process_agent,
            node_template=templates[template_type],
            name=name,
            config={},
            position_x=x,
            position_y=y,
        )

    for source_name, target_name in JOURNEY_EDGES:
        NodeConnection.objects.create(
            process_agent=process_agent,
            source_node=nodes_by_name[source_name],
            target_node=nodes_by_name[target_name],
            condition="",
            priority=0,
        )
