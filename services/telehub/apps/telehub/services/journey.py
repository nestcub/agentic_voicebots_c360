from ..models import BotJourney, NodeConnection, NodeInstance, ProcessAgent
from .seed_node_templates import seed_node_templates

# Per docs/superpowers/plans/gpt_ai_hub_impl_plan.md "Journey" section. Main trunk:
# Lead Received -> Business Hours -> DND Check -> Communication -> Completed.
# Retry, Callback, QA and CRM Update are NOT steps on the way to Completed — they
# are outcome branches evaluated AFTER a call completes (see JOURNEY_EDGES below):
# Retry and Callback loop back to Business Hours to re-attempt the process; QA and
# CRM Update are terminal side effects with no further outgoing edge.
#
# Completed's 4 outgoing edges are not all equal: Completed->Retry only fires on
# condition "failed" and Completed->Callback only fires on condition
# "callback_requested"; Completed->QA and Completed->CRM Update always fire
# (condition ""). A later phase's outcome router reads these condition strings.
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

# (source name, target name, condition) — explicit, since the graph branches
# (Completed fans out to 4 nodes) and loops (Retry/Callback back to Business
# Hours), which a simple zip(nodes, nodes[1:]) linear chain can no longer
# express. condition="" means "always fires"; Completed->Retry and
# Completed->Callback are gated on the call outcome (see comment above).
JOURNEY_EDGES = [
    ("Lead Received", "Business Hours", ""),
    ("Business Hours", "DND Check", ""),
    ("DND Check", "Communication", ""),
    ("Communication", "Completed", ""),
    ("Completed", "Retry", "failed"),
    ("Completed", "Callback", "callback_requested"),
    ("Completed", "QA", ""),
    ("Completed", "CRM Update", ""),
    ("Retry", "Business Hours", ""),
    ("Callback", "Business Hours", ""),
]


def generate_journey(target) -> None:
    """
    Idempotent: clears and rebuilds one BotJourney's NodeInstance/NodeConnection
    rows from the fixed JOURNEY_STEPS/JOURNEY_EDGES graph (9 nodes, 10 edges). Main
    trunk: Lead Received -> Business Hours -> DND Check -> Communication ->
    Completed. Retry/Callback/QA/CRM Update all branch off Completed; Retry and
    Callback loop back to Business Hours to re-attempt. V1 is form-driven only:
    users view this generated graph, they don't hand-edit it (no React Flow yet).

    `target` is either a BotJourney (the normal, multi-journey-aware path — its
    own complete 9-node subgraph, independent of any other journey on the same
    ProcessAgent so node-name lookups like nodes.get(name="Communication") stay
    unambiguous per journey) or a bare ProcessAgent (legacy call shape, kept so
    existing single-journey callers/tests don't need to change): in that case a
    single default BotJourney (order=0, name="Sales Journey") is get-or-created
    for it and used as the target, exactly matching pre-multi-journey behaviour
    when a ProcessAgent only ever has one journey.
    """
    if isinstance(target, ProcessAgent):
        bot_journey, _ = BotJourney.objects.get_or_create(
            process_agent=target, order=0, defaults={"name": "Sales Journey"}
        )
    else:
        bot_journey = target

    process_agent = bot_journey.process_agent
    templates = seed_node_templates()

    # Deleting NodeInstances cascades to NodeConnection (source_node/target_node
    # are both on_delete=CASCADE from NodeInstance), so this alone clears both.
    bot_journey.nodes.all().delete()

    nodes_by_name = {}
    for name, template_type, x, y in JOURNEY_STEPS:
        nodes_by_name[name] = NodeInstance.objects.create(
            process_agent=process_agent,
            bot_journey=bot_journey,
            node_template=templates[template_type],
            name=name,
            config={},
            position_x=x,
            position_y=y,
        )

    for source_name, target_name, condition in JOURNEY_EDGES:
        NodeConnection.objects.create(
            process_agent=process_agent,
            source_node=nodes_by_name[source_name],
            target_node=nodes_by_name[target_name],
            condition=condition,
            priority=0,
        )


def journey_nodes(execution: "Execution"):
    """
    The NodeInstance queryset to resolve fixed-node lookups (by name — "Retry",
    "Communication", "Business Hours", ...) against for a given Execution.
    Scoped to execution.current_bot_journey when set, so multi-journey
    ProcessAgents (whose journeys each have their own same-named nodes) don't
    collide; falls back to the process agent's full node set for
    pre-multi-journey Executions that never had current_bot_journey populated
    (safe as long as that process agent still only has one journey — the
    common case, and the only case before this field existed).
    """
    if execution.current_bot_journey_id:
        return execution.current_bot_journey.nodes
    return execution.process_agent.nodes
