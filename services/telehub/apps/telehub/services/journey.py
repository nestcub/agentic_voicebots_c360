from ..models import NodeConnection, NodeInstance, ProcessAgent
from .seed_node_templates import seed_node_templates

# The fixed 9-step journey chain, per docs/superpowers/plans/gpt_ai_hub_impl_plan.md
# "Journey" section: Lead -> Business Hours -> DND -> Communication -> Retry ->
# Callback -> QA -> CRM Update -> Completed.
JOURNEY_STEPS = [
    ("Lead Received", "trigger"),
    ("Business Hours", "logic"),
    ("DND Check", "logic"),
    ("Communication", "communication"),
    ("Retry", "retry"),
    ("Callback", "logic"),
    ("QA", "qa"),
    ("CRM Update", "integration"),
    ("Completed", "output"),
]

STEP_X_START = 60
STEP_X_SPACING = 180
STEP_Y = 100


def generate_journey(process_agent: "ProcessAgent") -> None:
    """
    Idempotent: clears and rebuilds this process_agent's NodeInstance/NodeConnection
    rows from a fixed 9-step chain, per docs/superpowers/plans/gpt_ai_hub_impl_plan.md
    "Journey" section: Lead -> Business Hours -> DND -> Communication -> Retry ->
    Callback -> QA -> CRM Update -> Completed. V1 is form-driven only: users view
    this generated chain, they don't hand-edit it (no React Flow yet).
    """
    templates = seed_node_templates()

    # Deleting NodeInstances cascades to NodeConnection (source_node/target_node
    # are both on_delete=CASCADE from NodeInstance), so this alone clears both.
    process_agent.nodes.all().delete()

    nodes = []
    for index, (name, template_type) in enumerate(JOURNEY_STEPS):
        node = NodeInstance.objects.create(
            process_agent=process_agent,
            node_template=templates[template_type],
            name=name,
            config={},
            position_x=STEP_X_START + index * STEP_X_SPACING,
            position_y=STEP_Y,
        )
        nodes.append(node)

    for source, target in zip(nodes, nodes[1:]):
        NodeConnection.objects.create(
            process_agent=process_agent,
            source_node=source,
            target_node=target,
            condition="",
            priority=0,
        )
