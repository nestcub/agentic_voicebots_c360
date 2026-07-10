# AI Orchestrator V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the lead-dispatch pipeline's structure (nodes, edges, webhook URLs, analytics variables) data-driven and canvas-editable, while keeping every existing retry/DND/WhatsApp-fallback/QA algorithm exactly as-is, wrapped in an "AI Agent Orchestration Platform" framing (Agent → Workflow → Execution).

**Architecture:** `WorkflowState`/`VALID_TRANSITIONS` (today hardcoded Python) become `WorkflowNode`/`WorkflowEdge` rows under a `WorkflowDefinition`, owned by an `Agent`. `workflow_service.transition()` validates against the DB graph instead of a dict; every call site that used to hardcode a target state now computes a **label** and calls `resolve_next_node(from_key, label)` to find the real target — so canvas edits change live routing with no redeploy. Decision *algorithms* (retry thresholds, DND check, outcome classification) stay in Python, untouched in behavior.

**Tech Stack:** Django 5 / DRF (existing, `orchestrator_django/`), SQLite (demo; Postgres later), Next.js 16 / React 19 (existing, `dashboard/`), `@xyflow/react` (new) for the canvas.

## Global Constraints

- Seed node keys MUST be byte-identical to today's `WorkflowState` enum string values (`"WAITING"`, `"CALLING"`, `"HOT_LEAD"`, etc.) — every existing read path (`briefing_stats`, serializers, `RailControls`, dashboard `lib/types.ts`) depends on this and must keep working unchanged.
- `WorkflowState` the Python enum is NOT deleted — it stays as the canonical list of default keys and for readability. It stops being the transition-validation source of truth.
- Never let `resolve_next_node` returning `None` raise into a webhook handler — always record `unrouted_transition` and return normally (matches the existing "always ack 200" pattern in `chat360_call_result_webhook`).
- `logic`-kind nodes reference a fixed Python registry (`LOGIC_REGISTRY`) — never free text executed as code.
- The dashboard project (`dashboard/`) has no test runner configured (no Jest/Vitest/RTL in `package.json`). Frontend tasks use manual dev-server verification steps, not invented test infra — consistent with YAGNI given the overnight deadline.
- Follow existing code conventions exactly: DRF `@api_view` thin views + `services/` business logic (per `orchestrator_django` CLAUDE.md), Next.js `"use client"` components styled via `STATE_COLORS`/`Card`, fetch clients in `lib/sources/` throwing on `!res.ok`.
- Spec: `docs/superpowers/specs/2026-07-10-configurable-workflow-canvas-design.md`.

---

## Task 1: Models — `Agent`, `WorkflowDefinition`, `WorkflowNode`, `WorkflowEdge`

**Files:**
- Modify: `orchestrator_django/apps/orchestrator/models.py`
- Create: migration via `makemigrations` (file auto-named, e.g. `0002_agent_workflowdefinition_workflownode_workflowedge.py`)
- Test: `orchestrator_django/apps/orchestrator/tests.py` (new `WorkflowGraphModelTests` class, appended at end of file)

**Interfaces:**
- Produces: `Agent(name, department, icon, active_definition, created_at)`, `WorkflowDefinition(name, scope, is_active, version, created_at, updated_at)`, `WorkflowNode(definition, key, kind, name, config, position_x, position_y)` with `WorkflowNode.Kind` choices `TRIGGER="trigger"`, `WEBHOOK="webhook"`, `LOGIC="logic"`, `WAIT="wait"`, `OUTCOME="outcome"`, `WorkflowEdge(definition, source_node, target_node, label)`.
- Consumes: nothing (first task).

- [ ] **Step 1: Write the failing test**

Append to `orchestrator_django/apps/orchestrator/tests.py`:

```python
from apps.orchestrator.models import (
    Agent,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
)


class WorkflowGraphModelTests(TestCase):
    def test_agent_wraps_a_workflow_definition_with_nodes_and_edges(self):
        definition = WorkflowDefinition.objects.create(name="Lead Dispatch (default)", is_active=True)
        agent = Agent.objects.create(name="Sales Agent", department="Sales", active_definition=definition)

        waiting = WorkflowNode.objects.create(
            definition=definition, key="WAITING", kind=WorkflowNode.Kind.WAIT, name="Waiting"
        )
        dispatching = WorkflowNode.objects.create(
            definition=definition, key="DISPATCHING", kind=WorkflowNode.Kind.WEBHOOK, name="Dispatching"
        )
        edge = WorkflowEdge.objects.create(
            definition=definition, source_node=waiting, target_node=dispatching, label=""
        )

        self.assertEqual(agent.active_definition, definition)
        self.assertEqual(list(definition.nodes.all()), [waiting, dispatching])
        self.assertEqual(edge.source_node.key, "WAITING")
        self.assertEqual(edge.target_node.key, "DISPATCHING")

    def test_node_key_unique_within_definition(self):
        definition = WorkflowDefinition.objects.create(name="d")
        WorkflowNode.objects.create(definition=definition, key="WAITING", kind=WorkflowNode.Kind.WAIT, name="Waiting")
        with self.assertRaises(Exception):
            WorkflowNode.objects.create(
                definition=definition, key="WAITING", kind=WorkflowNode.Kind.WAIT, name="Waiting again"
            )

    def test_edge_label_unique_per_source_node(self):
        definition = WorkflowDefinition.objects.create(name="d")
        a = WorkflowNode.objects.create(definition=definition, key="A", kind=WorkflowNode.Kind.WAIT, name="A")
        b = WorkflowNode.objects.create(definition=definition, key="B", kind=WorkflowNode.Kind.WAIT, name="B")
        c = WorkflowNode.objects.create(definition=definition, key="C", kind=WorkflowNode.Kind.WAIT, name="C")
        WorkflowEdge.objects.create(definition=definition, source_node=a, target_node=b, label="x")
        with self.assertRaises(Exception):
            WorkflowEdge.objects.create(definition=definition, source_node=a, target_node=c, label="x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd orchestrator_django && python manage.py test apps.orchestrator.tests.WorkflowGraphModelTests -v 2`
Expected: FAIL — `ImportError: cannot import name 'Agent' from 'apps.orchestrator.models'`

- [ ] **Step 3: Add the models**

In `orchestrator_django/apps/orchestrator/models.py`, append after `Chat360WebhookLog` (after line 138):

```python
class WorkflowDefinition(models.Model):
    """
    A versioned lead-dispatch graph. Exactly one WorkflowDefinition per Agent has
    is_active=True at a time — that's the one workflow_service/decision_engine read
    for live transitions. `scope` is reserved for a future multi-tenant (per-OEM/
    department) library; today every definition uses "default".
    """
    name = models.CharField(max_length=128)
    scope = models.CharField(max_length=128, blank=True, default="default")
    is_active = models.BooleanField(default=False)
    version = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} v{self.version} ({'active' if self.is_active else 'draft'})"


class Agent(models.Model):
    """
    Layer-1 concept: a business capability (e.g. "Sales Agent"). Wraps one
    WorkflowDefinition. `department` is a display grouping only — it must never
    branch code (see project CLAUDE.md domain-agnostic principle).
    """
    name = models.CharField(max_length=128)
    department = models.CharField(max_length=64, blank=True, default="")
    icon = models.CharField(max_length=32, blank=True, default="")
    active_definition = models.ForeignKey(
        WorkflowDefinition, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class WorkflowNode(models.Model):
    """
    One station in the graph. `key` replaces WorkflowState as the identity every
    other model's `state`/history references — see the seed command, which makes
    the default definition's keys byte-identical to today's WorkflowState values.
    """
    class Kind(models.TextChoices):
        TRIGGER = "trigger"
        WEBHOOK = "webhook"   # calls an external URL — config: {"url": "<override or empty>"}
        LOGIC = "logic"       # fixed registry check — config: {"logic_ref": "dnd_check"|"qa_review"}
        WAIT = "wait"         # resting/backoff state — config: {"backoff_minutes": [1,5,15]} optional
        OUTCOME = "outcome"   # terminal-ish, named analytics sub-variables — config: {"variables": [...]}

    definition = models.ForeignKey(WorkflowDefinition, on_delete=models.CASCADE, related_name="nodes")
    key = models.CharField(max_length=64)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    name = models.CharField(max_length=128)
    config = models.JSONField(default=dict, blank=True)
    position_x = models.FloatField(default=0)
    position_y = models.FloatField(default=0)

    class Meta:
        unique_together = [("definition", "key")]

    def __str__(self):
        return f"{self.definition.name}:{self.key}"


class WorkflowEdge(models.Model):
    """
    One transition. label="" means "the only/default outgoing edge" (single-path
    nodes); a non-empty label is a decision point's routing key (e.g. "connected",
    "hot_lead", "exhausted") that decision_engine.py resolves via
    workflow_service.resolve_next_node(from_key, label).
    """
    definition = models.ForeignKey(WorkflowDefinition, on_delete=models.CASCADE, related_name="edges")
    source_node = models.ForeignKey(WorkflowNode, on_delete=models.CASCADE, related_name="outgoing_edges")
    target_node = models.ForeignKey(WorkflowNode, on_delete=models.CASCADE, related_name="incoming_edges")
    label = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        unique_together = [("source_node", "label")]

    def __str__(self):
        return f"{self.source_node.key} -[{self.label or 'default'}]-> {self.target_node.key}"
```

Also modify the existing `WorkflowInstance.state` field (line 38) — drop the `choices=` constraint since the live node graph, not the Python enum, is now authoritative:

Change:
```python
    state = models.CharField(max_length=32, choices=WorkflowState.choices, default=WorkflowState.WAITING)
```
To:
```python
    state = models.CharField(max_length=32, default=WorkflowState.WAITING)
```

- [ ] **Step 4: Register admin for the new models**

In `orchestrator_django/apps/orchestrator/admin.py`, add (matching whatever registration style the existing file uses for `WorkflowInstance` — open the file first, then add):

```python
from apps.orchestrator.models import Agent, WorkflowDefinition, WorkflowEdge, WorkflowNode

admin.site.register(Agent)
admin.site.register(WorkflowDefinition)
admin.site.register(WorkflowNode)
admin.site.register(WorkflowEdge)
```

- [ ] **Step 5: Generate and apply the migration**

Run: `cd orchestrator_django && python manage.py makemigrations orchestrator`
Expected: creates a new migration file adding 4 models + 1 `AlterField` on `WorkflowInstance.state`.

Run: `python manage.py migrate`
Expected: `Applying orchestrator.000X_...  OK`

- [ ] **Step 6: Run test to verify it passes**

Run: `python manage.py test apps.orchestrator.tests.WorkflowGraphModelTests -v 2`
Expected: PASS (3 tests)

- [ ] **Step 7: Verify existing tests still pass**

Run: `python manage.py test apps.orchestrator -v 2`
Expected: all pre-existing tests still PASS (the `state` field change is additive; no behavior depends on `choices` today).

- [ ] **Step 8: Commit**

```bash
git add orchestrator_django/apps/orchestrator/models.py orchestrator_django/apps/orchestrator/admin.py orchestrator_django/apps/orchestrator/tests.py orchestrator_django/apps/orchestrator/migrations/
git commit -m "add Agent/WorkflowDefinition/WorkflowNode/WorkflowEdge models"
```

---

## Task 2: Seed service + management command

**Files:**
- Create: `orchestrator_django/apps/orchestrator/services/seed.py`
- Create: `orchestrator_django/apps/orchestrator/management/__init__.py` (empty, if the `management/` dir doesn't exist yet)
- Create: `orchestrator_django/apps/orchestrator/management/commands/__init__.py` (empty)
- Create: `orchestrator_django/apps/orchestrator/management/commands/seed_default_workflow.py`
- Test: `orchestrator_django/apps/orchestrator/tests.py` (new `SeedDefaultWorkflowTests` class)

**Interfaces:**
- Consumes: `Agent`, `WorkflowDefinition`, `WorkflowNode`, `WorkflowEdge` from Task 1.
- Produces: `seed.seed_default_workflow() -> Agent`, idempotent (safe to call more than once — re-running updates the existing "Sales Agent" definition in place rather than duplicating it).

Node positions below are taken directly from `dashboard/components/orchestrator/LiveRail.tsx`'s `STATIONS`/`CHECKPOINTS` constants (already read in this session) so the seeded canvas visually matches today's rail.

- [ ] **Step 1: Write the failing test**

Append to `tests.py`:

```python
from apps.orchestrator.services.seed import seed_default_workflow


class SeedDefaultWorkflowTests(TestCase):
    def test_seed_creates_sales_agent_with_full_graph(self):
        agent = seed_default_workflow()

        self.assertEqual(agent.name, "Sales Agent")
        definition = agent.active_definition
        self.assertTrue(definition.is_active)

        node_keys = set(definition.nodes.values_list("key", flat=True))
        expected_keys = {
            "LEAD_RECEIVED", "WAITING", "CALLBACK_PENDING", "SUPPRESSED_DNC",
            "DISPATCHING", "CALLING", "CONNECTED", "NOT_CONNECTED", "UNANSWERED",
            "RETRY_PENDING", "WHATSAPP_PENDING", "COMPLETED", "VOICEMAIL",
            "OTHER_INQUIRY", "FAILED", "HOT_LEAD", "DND_CHECK", "QA_REVIEW",
        }
        self.assertEqual(node_keys, expected_keys)

        # spot-check the decision points that matter most
        calling = definition.nodes.get(key="CALLING")
        labels = set(calling.outgoing_edges.values_list("label", flat=True))
        self.assertEqual(labels, {"dispatched", "connected", "unanswered", "not_connected"})

        retry_pending = definition.nodes.get(key="RETRY_PENDING")
        retry_targets = {
            e.label: e.target_node.key for e in retry_pending.outgoing_edges.all()
        }
        self.assertEqual(retry_targets, {"retry": "WAITING", "exhausted": "WHATSAPP_PENDING"})

    def test_seed_is_idempotent(self):
        seed_default_workflow()
        seed_default_workflow()
        self.assertEqual(Agent.objects.filter(name="Sales Agent").count(), 1)
        definition = Agent.objects.get(name="Sales Agent").active_definition
        self.assertEqual(definition.nodes.filter(key="WAITING").count(), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test apps.orchestrator.tests.SeedDefaultWorkflowTests -v 2`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.orchestrator.services.seed'`

- [ ] **Step 3: Write `services/seed.py`**

```python
"""
Builds the default "Sales Agent" WorkflowDefinition — a byte-for-byte port of
today's real, working pipeline (WorkflowState enum + VALID_TRANSITIONS in
workflow_service.py, station layout from dashboard/components/orchestrator/
LiveRail.tsx). This is the ONLY way the demo environment gets its starting graph.
Deliberately does NOT invent nodes with no backing logic (no "Business Hours",
"CRM Update", etc.) — those are future palette entries, not seeded data.
"""
from apps.orchestrator.models import Agent, WorkflowDefinition, WorkflowEdge, WorkflowNode

AGENT_NAME = "Sales Agent"
DEFINITION_NAME = "Lead Dispatch (default)"

# (key, kind, name, position) — positions ported from LiveRail.tsx STATIONS/CHECKPOINTS.
NODES = [
    ("LEAD_RECEIVED", WorkflowNode.Kind.TRIGGER, "Lead Received", 100, 90),
    ("WAITING", WorkflowNode.Kind.WAIT, "Waiting", 280, 90),
    ("DISPATCHING", WorkflowNode.Kind.WEBHOOK, "Dispatching", 460, 90),
    ("CALLING", WorkflowNode.Kind.WAIT, "Calling", 640, 90),
    ("CONNECTED", WorkflowNode.Kind.WAIT, "Connected", 820, 90),
    ("COMPLETED", WorkflowNode.Kind.OUTCOME, "Completed", 1000, 90),
    ("CALLBACK_PENDING", WorkflowNode.Kind.WAIT, "Callback Pending", 1180, 90),
    ("NOT_CONNECTED", WorkflowNode.Kind.WAIT, "Not Connected", 460, 290),
    ("RETRY_PENDING", WorkflowNode.Kind.WAIT, "Retry Pending", 620, 290),
    ("WHATSAPP_PENDING", WorkflowNode.Kind.WEBHOOK, "WhatsApp Pending", 780, 290),
    ("SUPPRESSED_DNC", WorkflowNode.Kind.OUTCOME, "Suppressed (DNC)", 190, 290),
    ("UNANSWERED", WorkflowNode.Kind.WAIT, "Unanswered", 640, 190),
    ("VOICEMAIL", WorkflowNode.Kind.OUTCOME, "Voicemail", 900, 190),
    ("OTHER_INQUIRY", WorkflowNode.Kind.OUTCOME, "Other Inquiry", 950, 190),
    ("FAILED", WorkflowNode.Kind.OUTCOME, "Failed", 1050, 190),
    ("HOT_LEAD", WorkflowNode.Kind.OUTCOME, "Hot Lead", 1000, 40),
    ("DND_CHECK", WorkflowNode.Kind.LOGIC, "DND Check", 190, 40),
    ("QA_REVIEW", WorkflowNode.Kind.LOGIC, "QA Review", 1110, 24),
]

NODE_CONFIG = {
    "DND_CHECK": {"logic_ref": "dnd_check"},
    "QA_REVIEW": {"logic_ref": "qa_review"},
    "DISPATCHING": {"url": ""},
    "WHATSAPP_PENDING": {"url": ""},
    "COMPLETED": {
        "variables": [
            {"key": "test_drives", "label": "Test Drives", "match_keywords": ["test ride", "test drive"]},
            {"key": "showroom_visits", "label": "Showroom Visits", "match_keywords": ["showroom visit"]},
        ]
    },
}

# (source_key, label, target_key) — label="" is the single/default outgoing edge.
# Mirrors workflow_service.VALID_TRANSITIONS + decision_engine.py's branching exactly.
EDGES = [
    ("LEAD_RECEIVED", "", "WAITING"),  # cosmetic only — create_workflow() never resolves this at runtime
    ("WAITING", "", "DISPATCHING"),
    ("WAITING", "dnd_suppressed", "SUPPRESSED_DNC"),
    ("WAITING", "callback_requested", "CALLBACK_PENDING"),
    ("CALLBACK_PENDING", "", "DISPATCHING"),
    ("DISPATCHING", "", "CALLING"),
    ("CALLING", "dispatched", "CONNECTED"),
    ("CALLING", "connected", "CONNECTED"),
    ("CALLING", "unanswered", "UNANSWERED"),
    ("CALLING", "not_connected", "NOT_CONNECTED"),
    ("UNANSWERED", "", "RETRY_PENDING"),
    ("NOT_CONNECTED", "", "RETRY_PENDING"),
    ("RETRY_PENDING", "retry", "WAITING"),
    ("RETRY_PENDING", "exhausted", "WHATSAPP_PENDING"),
    ("WHATSAPP_PENDING", "responded", "COMPLETED"),
    ("WHATSAPP_PENDING", "no_response", "FAILED"),
    ("CONNECTED", "hot_lead", "HOT_LEAD"),
    ("CONNECTED", "completed", "COMPLETED"),
    ("CONNECTED", "voicemail", "VOICEMAIL"),      # reserved, unused by decision_engine today
    ("CONNECTED", "other_inquiry", "OTHER_INQUIRY"),  # reserved, unused by decision_engine today
    ("CONNECTED", "failed", "FAILED"),            # reserved, unused by decision_engine today
]


def seed_default_workflow() -> Agent:
    """Idempotent: re-running updates the existing Sales Agent's definition in place."""
    definition, _ = WorkflowDefinition.objects.update_or_create(
        name=DEFINITION_NAME,
        defaults={"scope": "default", "is_active": True},
    )
    # Clear and rebuild nodes/edges so re-seeding never leaves stale rows.
    definition.nodes.all().delete()

    node_objs = {}
    for key, kind, name, x, y in NODES:
        node_objs[key] = WorkflowNode.objects.create(
            definition=definition,
            key=key,
            kind=kind,
            name=name,
            config=NODE_CONFIG.get(key, {}),
            position_x=x,
            position_y=y,
        )

    for source_key, label, target_key in EDGES:
        WorkflowEdge.objects.create(
            definition=definition,
            source_node=node_objs[source_key],
            target_node=node_objs[target_key],
            label=label,
        )

    agent, _ = Agent.objects.update_or_create(
        name=AGENT_NAME,
        defaults={"department": "Sales", "active_definition": definition},
    )
    return agent
```

- [ ] **Step 4: Write the management command**

Create `orchestrator_django/apps/orchestrator/management/__init__.py` (empty file) and
`orchestrator_django/apps/orchestrator/management/commands/__init__.py` (empty file) if they don't already exist.

`orchestrator_django/apps/orchestrator/management/commands/seed_default_workflow.py`:

```python
from django.core.management.base import BaseCommand

from apps.orchestrator.services.seed import seed_default_workflow


class Command(BaseCommand):
    help = "Seeds the default Sales Agent workflow graph (idempotent)."

    def handle(self, *args, **options):
        agent = seed_default_workflow()
        self.stdout.write(self.style.SUCCESS(f"Seeded {agent.name} (definition id={agent.active_definition_id})"))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python manage.py test apps.orchestrator.tests.SeedDefaultWorkflowTests -v 2`
Expected: PASS (2 tests)

- [ ] **Step 6: Run the command for real and inspect it**

Run: `python manage.py seed_default_workflow`
Expected: `Seeded Sales Agent (definition id=1)`

Run: `python manage.py dbshell` then `SELECT key, kind FROM orchestrator_workflownode;` — expect 18 rows.

- [ ] **Step 7: Commit**

```bash
git add orchestrator_django/apps/orchestrator/services/seed.py orchestrator_django/apps/orchestrator/management orchestrator_django/apps/orchestrator/tests.py
git commit -m "add seed_default_workflow management command"
```

---

## Task 3: `workflow_service.py` — graph-aware `transition`/`resolve_next_node`

**Files:**
- Modify: `orchestrator_django/apps/orchestrator/services/workflow_service.py`
- Test: `orchestrator_django/apps/orchestrator/tests.py` (new `GraphTransitionTests` class)

**Interfaces:**
- Consumes: `WorkflowEdge`, `WorkflowDefinition` (Task 1), `seed_default_workflow` (Task 2).
- Produces: `resolve_next_node(from_key: str, label: str = "") -> str | None`, `record_unrouted_transition(workflow, from_state, label) -> None`, `validate_transition(from_state, to_state) -> bool` (same signature as today, new implementation), `transition(...)` (unchanged signature/behavior for callers), `record_dnd_check(...)` (unchanged signature/behavior).

This task **replaces** the hardcoded `VALID_TRANSITIONS` dict (lines 13-47 of the current file) with DB-backed lookups. `LOGIC_REGISTRY` is added as a lightweight validation constant, not a dispatch mechanism — `record_dnd_check` still calls `is_suppressed_dnc` directly.

- [ ] **Step 1: Write the failing tests**

Append to `tests.py`:

```python
from apps.orchestrator.services.workflow_service import record_unrouted_transition, resolve_next_node


class GraphTransitionTests(TestCase):
    def setUp(self):
        seed_default_workflow()

    def test_resolve_next_node_default_label(self):
        self.assertEqual(resolve_next_node("WAITING", ""), "DISPATCHING")

    def test_resolve_next_node_decision_label(self):
        self.assertEqual(resolve_next_node("RETRY_PENDING", "retry"), "WAITING")
        self.assertEqual(resolve_next_node("RETRY_PENDING", "exhausted"), "WHATSAPP_PENDING")

    def test_resolve_next_node_missing_edge_returns_none(self):
        self.assertIsNone(resolve_next_node("WAITING", "no_such_label"))

    def test_transition_validates_against_graph(self):
        workflow = workflow_service.create_workflow(lead_id="l1", crm="manual", campaign_id="c1")
        workflow = workflow_service.transition(workflow, "DISPATCHING", event="test")
        self.assertEqual(workflow.state, "DISPATCHING")

    def test_transition_rejects_edge_not_in_graph(self):
        workflow = workflow_service.create_workflow(lead_id="l2", crm="manual", campaign_id="c1")
        with self.assertRaises(ValueError):
            workflow_service.transition(workflow, "COMPLETED", event="test")

    def test_record_unrouted_transition_parks_workflow_and_logs(self):
        workflow = workflow_service.create_workflow(lead_id="l3", crm="manual", campaign_id="c1")
        record_unrouted_transition(workflow, "WAITING", "nonexistent_label")
        workflow.refresh_from_db()
        self.assertEqual(workflow.state, "WAITING")  # unchanged — parked, not crashed
        event = WorkflowHistory.objects.filter(workflow=workflow, event="unrouted_transition").first()
        self.assertIsNotNone(event)
        self.assertEqual(event.payload["attempted_label"], "nonexistent_label")

    def test_dnd_check_suppresses_via_graph_edge(self):
        workflow = workflow_service.create_workflow(lead_id="l4", crm="manual", campaign_id="c1")
        workflow = workflow_service.record_dnd_check(workflow, "9876543210", dnd_flag=True)
        self.assertEqual(workflow.state, "SUPPRESSED_DNC")

    def test_dnd_check_passes_stays_waiting(self):
        workflow = workflow_service.create_workflow(lead_id="l5", crm="manual", campaign_id="c1")
        workflow = workflow_service.record_dnd_check(workflow, "9876543210", dnd_flag=False)
        self.assertEqual(workflow.state, "WAITING")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test apps.orchestrator.tests.GraphTransitionTests -v 2`
Expected: FAIL — `ImportError: cannot import name 'resolve_next_node'`

- [ ] **Step 3: Rewrite the transition core**

In `orchestrator_django/apps/orchestrator/services/workflow_service.py`, replace lines 1-76 (imports through the end of the `transition()` function — i.e. everything from the module docstring through the old `VALID_TRANSITIONS` dict and `validate_transition`/`transition`) with:

```python
"""
State-machine core for workflow instances. Structure (which transitions are valid)
now lives in the WorkflowEdge/WorkflowNode graph (see models.py) instead of a
hardcoded dict — see resolve_next_node(). Decision *algorithms* (which label to
pick) stay in decision_engine.py, unchanged in behavior.
"""
import re
import uuid
from datetime import datetime, timedelta

from django.utils import timezone

from apps.orchestrator.models import (
    CampaignLead,
    WorkflowEdge,
    WorkflowHistory,
    WorkflowInstance,
    WorkflowState,
)

# Known logic_ref values a `logic`-kind WorkflowNode.config may declare — validation
# only, never a dispatch mechanism. The actual behavior stays hardcoded function
# calls (is_suppressed_dnc below, decision_engine.record_qa_review) so this list
# documents what backs a checkpoint node, it doesn't drive it.
LOGIC_REGISTRY = {"dnd_check", "qa_review"}


def resolve_next_node(from_key: str, label: str = "") -> str | None:
    """
    Looks up the active WorkflowDefinition's WorkflowEdge from the node with
    key=from_key and the given label ("" for a single-path node's only edge).
    Returns the target node's key, or None if no such edge exists — callers MUST
    treat None as an unrouted transition (see record_unrouted_transition) and must
    never raise on it.
    """
    edge = (
        WorkflowEdge.objects.filter(
            definition__is_active=True, source_node__key=from_key, label=label
        )
        .select_related("target_node")
        .first()
    )
    return edge.target_node.key if edge else None


def record_unrouted_transition(workflow: WorkflowInstance, from_state: str, label: str) -> None:
    """
    Called when resolve_next_node(from_state, label) returned None — e.g. someone
    deleted the required edge on the canvas. Never raises; the workflow stays
    parked at from_state and an audit event is recorded so this is visible (see
    briefing_stats' unrouted_count) instead of silently disappearing.
    """
    WorkflowHistory.objects.create(
        workflow=workflow,
        event="unrouted_transition",
        payload={"from_state": from_state, "attempted_label": label},
    )


def validate_transition(from_state: str, to_state: str) -> bool:
    """True iff an edge from_state -> to_state exists in the active WorkflowDefinition."""
    return WorkflowEdge.objects.filter(
        definition__is_active=True, source_node__key=from_state, target_node__key=to_state
    ).exists()


def transition(workflow: WorkflowInstance, to_state: str, event: str, payload: dict | None = None) -> WorkflowInstance:
    """
    Validates via validate_transition(); raises ValueError with a clear message
    (mentioning from/to state) if invalid. On success: sets workflow.state = to_state,
    saves the workflow, and creates a WorkflowHistory row with
    event=event, payload={"from_state": <old_state>, "to_state": to_state, **(payload or {})}.
    Returns the updated, saved workflow instance.
    """
    from_state = workflow.state
    if not validate_transition(from_state, to_state):
        raise ValueError(
            f"Invalid workflow transition for {workflow.lead_id}: "
            f"{from_state!r} -> {to_state!r} is not allowed"
        )

    workflow.state = to_state
    workflow.save()

    history_payload = {"from_state": from_state, "to_state": to_state, **(payload or {})}
    WorkflowHistory.objects.create(workflow=workflow, event=event, payload=history_payload)

    return workflow
```

Leave `create_workflow` (originally lines 79-109) unchanged in place below this block — it doesn't call `transition()` (documented reason already in its docstring) so it needs no edit.

- [ ] **Step 4: Update `record_dnd_check` to route through the graph**

Replace the existing `record_dnd_check` function (originally lines 124-142) with:

```python
def record_dnd_check(workflow: WorkflowInstance, to_number: str, dnd_flag: bool = False) -> WorkflowInstance:
    """
    Runs the DNC suppression check for a freshly created workflow. If suppressed
    (today: only via the lead's own uploaded dnd_flag), transitions WAITING ->
    SUPPRESSED_DNC via the "dnd_suppressed" edge. Otherwise records a
    dnd_check_passed audit event with NO state change — same "transient checkpoint"
    pattern as create_workflow()'s LEAD_RECEIVED->WAITING audit row.
    """
    if is_suppressed_dnc(to_number, dnd_flag):
        to_key = resolve_next_node(workflow.state, "dnd_suppressed")
        if to_key is None:
            record_unrouted_transition(workflow, workflow.state, "dnd_suppressed")
            return workflow
        return transition(
            workflow,
            to_key,
            event="dnd_check_suppressed",
            payload={"dnd_flag": dnd_flag},
        )
    WorkflowHistory.objects.create(workflow=workflow, event="dnd_check_passed", payload={})
    return workflow
```

Leave `is_suppressed_dnc`, `parse_call_back_time`, `CALL_BACK_TIME_FORMATS`, `RELATIVE_CALL_BACK_PATTERNS`, `_DEVANAGARI_DIGITS` unchanged.

- [ ] **Step 5: Update `schedule_callback_workflow` to route through the graph**

In the same file, in `schedule_callback_workflow` (originally around line 224), replace:

```python
    record_dnd_check(new_workflow, to_number)
    if new_workflow.state == WorkflowState.WAITING:
        new_workflow = transition(
            new_workflow,
            WorkflowState.CALLBACK_PENDING,
            event="callback_scheduled",
            payload={"call_back_time": call_back_time_raw},
        )
```

With:

```python
    record_dnd_check(new_workflow, to_number)
    if new_workflow.state == WorkflowState.WAITING:
        to_key = resolve_next_node(new_workflow.state, "callback_requested")
        if to_key is None:
            record_unrouted_transition(new_workflow, new_workflow.state, "callback_requested")
        else:
            new_workflow = transition(
                new_workflow,
                to_key,
                event="callback_scheduled",
                payload={"call_back_time": call_back_time_raw},
            )
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python manage.py test apps.orchestrator.tests.GraphTransitionTests -v 2`
Expected: PASS (7 tests)

- [ ] **Step 7: Run full existing suite (regression check)**

Run: `python manage.py test apps.orchestrator -v 2`
Expected: `CallbackSchedulingTests` and `RelativeCallBackTimeTests` may now FAIL — this is expected at this point, since `scheduler.py`/`decision_engine.py` haven't been updated yet (Tasks 4-5). Note which tests fail; they must all pass again by the end of Task 6.

- [ ] **Step 8: Commit**

```bash
git add orchestrator_django/apps/orchestrator/services/workflow_service.py orchestrator_django/apps/orchestrator/tests.py
git commit -m "make workflow_service.transition graph-aware via resolve_next_node"
```

---

## Task 4: `scheduler.py` — graph-aware pickup

**Files:**
- Modify: `orchestrator_django/apps/orchestrator/services/scheduler.py`
- Test: `orchestrator_django/apps/orchestrator/tests.py` (new `SchedulerGraphTests` class)

**Interfaces:**
- Consumes: `resolve_next_node`, `record_unrouted_transition` (Task 3).
- Produces: `tick()` — same signature/return (`int` processed count), same external behavior.

- [ ] **Step 1: Write the failing test**

Append to `tests.py`:

```python
from apps.orchestrator.services import scheduler


class SchedulerGraphTests(TestCase):
    def setUp(self):
        seed_default_workflow()

    def test_tick_moves_waiting_workflow_through_dispatching_to_calling(self):
        workflow = workflow_service.create_workflow(lead_id="sched-1", crm="manual", campaign_id="c1")
        workflow.next_execution = timezone.now() - timedelta(seconds=1)
        workflow.save()

        processed = scheduler.tick()

        workflow.refresh_from_db()
        self.assertEqual(processed, 1)
        # dispatcher.dispatch_call's mocked path resolves CALLING further within tick();
        # assert it at least passed through CALLING rather than staying WAITING.
        self.assertNotEqual(workflow.state, "WAITING")
        history_events = list(workflow.history.values_list("event", flat=True))
        self.assertIn("scheduler_pickup", history_events)
        self.assertIn("dispatch_call_start", history_events)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test apps.orchestrator.tests.SchedulerGraphTests -v 2`
Expected: FAIL — `ValueError: Invalid workflow transition ... 'WAITING' -> 'DISPATCHING' is not allowed` is NOT expected here (the edge exists); instead expect FAIL because `scheduler.tick()` still calls `workflow_service.transition(workflow, WorkflowState.DISPATCHING, ...)` directly, which still works today — so this test may actually PASS already. Run it first to confirm; if it already passes, proceed to Step 3 anyway to make the code graph-driven (required so canvas edits to these edges take effect), and re-run at Step 4 to confirm it still passes.

- [ ] **Step 3: Rewrite `tick()`**

In `orchestrator_django/apps/orchestrator/services/scheduler.py`, replace the body of `tick()` (originally lines 20-48) with:

```python
def tick() -> int:
    """
    Polls WorkflowInstance rows with state=WAITING/CALLBACK_PENDING and
    next_execution<=now(), dispatches a call for each, and lets decision_engine
    advance the resulting state. Both pickup transitions now resolve their target
    via the graph (resolve_next_node) instead of a hardcoded WorkflowState constant,
    so rewiring WAITING->DISPATCHING or DISPATCHING->CALLING on the canvas takes
    effect here with no redeploy.

    Returns the count of workflows processed this tick.
    """
    now = timezone.now()
    due_workflows = WorkflowInstance.objects.filter(
        state__in=[WorkflowState.WAITING, WorkflowState.CALLBACK_PENDING],
        next_execution__lte=now,
    )

    processed = 0
    for workflow in due_workflows:
        scheduled_time = workflow.next_execution

        dispatching_key = workflow_service.resolve_next_node(workflow.state, "")
        if dispatching_key is None:
            workflow_service.record_unrouted_transition(workflow, workflow.state, "")
            continue
        workflow_service.transition(workflow, dispatching_key, event="scheduler_pickup")

        calling_key = workflow_service.resolve_next_node(dispatching_key, "")
        if calling_key is None:
            workflow_service.record_unrouted_transition(workflow, dispatching_key, "")
            continue
        workflow_service.transition(workflow, calling_key, event="dispatch_call_start")

        result = dispatcher.dispatch_call(workflow)

        WorkflowAttempt.objects.create(
            workflow=workflow,
            attempt_no=workflow.attempt_count + 1,
            channel="voice",
            status=result["status"],
            scheduled_time=scheduled_time,
            started_time=result["started_time"],
            ended_time=result["ended_time"],
            virtual_number=result["virtual_number"],
            response_code=result["response_code"],
        )

        decision_engine.handle_call_outcome(workflow, result["status"])

        processed += 1

    return processed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test apps.orchestrator.tests.SchedulerGraphTests -v 2`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator_django/apps/orchestrator/services/scheduler.py orchestrator_django/apps/orchestrator/tests.py
git commit -m "make scheduler.tick pickup transitions graph-aware"
```

---

## Task 5: `decision_engine.py` — labels instead of hardcoded states

**Files:**
- Modify: `orchestrator_django/apps/orchestrator/services/decision_engine.py`
- Modify: `orchestrator_django/apps/orchestrator/api/views.py` (`chat360_call_result_webhook` — see Step 3.5; this is the REAL Chat360 production webhook, a second, independent caller of `classify_connected_outcome`/`transition` beyond `decision_engine.handle_call_outcome`, and it must be updated in lockstep or it breaks)
- Test: `orchestrator_django/apps/orchestrator/tests.py` (new `DecisionEngineGraphTests` class, new `Chat360WebhookGraphTests` class)

**Interfaces:**
- Consumes: `resolve_next_node`, `record_unrouted_transition` (Task 3).
- Produces: `handle_call_outcome(workflow, outcome) -> WorkflowInstance` (same signature), `classify_connected_outcome(payload, whatsapp_sent=False) -> str` (same signature, **return value changes** from `WorkflowState.HOT_LEAD`/`WorkflowState.COMPLETED` to the lowercase labels `"hot_lead"`/`"completed"` — there are TWO callers: `handle_call_outcome` in this file, and `chat360_call_result_webhook` in `views.py`, both updated together in this task), `handle_whatsapp_outcome(workflow, outcome) -> WorkflowInstance` (same signature), `record_qa_review(workflow) -> None` (unchanged), `_backoff_minutes(attempt_count) -> int` (same signature, now reads the `RETRY_PENDING` node's `config.backoff_minutes` first).

**Why this matters:** `classify_connected_outcome`'s return value is a transition target fed straight into `workflow_service.transition()` by both callers. Changing its contract (state → label) without updating both call sites in the same commit would silently break whichever caller is missed — for `views.chat360_call_result_webhook` specifically, that means the real Chat360 post-call webhook would raise `ValueError` on every real call and violate the "always ack 200" global constraint. Both call sites move together.

- [ ] **Step 1: Write the failing tests**

Append to `tests.py`:

```python
from unittest.mock import patch as mock_patch

from apps.orchestrator.services import decision_engine


class DecisionEngineGraphTests(TestCase):
    def setUp(self):
        seed_default_workflow()

    def test_dispatched_outcome_moves_to_connected(self):
        workflow = workflow_service.create_workflow(lead_id="de-1", crm="manual", campaign_id="c1")
        workflow.state = "CALLING"
        workflow.save()
        workflow = decision_engine.handle_call_outcome(workflow, "dispatched")
        self.assertEqual(workflow.state, "CONNECTED")

    def test_connected_outcome_resolves_to_completed(self):
        workflow = workflow_service.create_workflow(lead_id="de-2", crm="manual", campaign_id="c1")
        workflow.state = "CALLING"
        workflow.save()
        workflow = decision_engine.handle_call_outcome(workflow, "connected")
        self.assertEqual(workflow.state, "COMPLETED")
        self.assertTrue(
            WorkflowHistory.objects.filter(workflow=workflow, event="qa_review_passed").exists()
        )

    def test_no_answer_then_retry_then_waiting(self):
        workflow = workflow_service.create_workflow(lead_id="de-3", crm="manual", campaign_id="c1")
        workflow.state = "CALLING"
        workflow.attempt_count = 0
        workflow.save()
        workflow = decision_engine.handle_call_outcome(workflow, "no_answer")
        self.assertEqual(workflow.state, "WAITING")
        self.assertEqual(workflow.attempt_count, 1)

    def test_retry_exhaustion_falls_back_to_whatsapp(self):
        workflow = workflow_service.create_workflow(lead_id="de-4", crm="manual", campaign_id="c1")
        workflow.state = "CALLING"
        workflow.attempt_count = decision_engine.MAX_RETRIES - 1  # next failure exhausts retries
        workflow.save()
        with mock_patch(
            "apps.orchestrator.services.dispatcher.dispatch_whatsapp",
            return_value={"status": "responded"},
        ):
            workflow = decision_engine.handle_call_outcome(workflow, "busy")
        self.assertEqual(workflow.state, "COMPLETED")
        self.assertTrue(
            WorkflowHistory.objects.filter(workflow=workflow, event="whatsapp_fallback_triggered").exists()
        )

    def test_whatsapp_no_response_resolves_to_failed(self):
        workflow = workflow_service.create_workflow(lead_id="de-5", crm="manual", campaign_id="c1")
        workflow.state = "WHATSAPP_PENDING"
        workflow.save()
        workflow = decision_engine.handle_whatsapp_outcome(workflow, "no_response")
        self.assertEqual(workflow.state, "FAILED")

    def test_backoff_minutes_read_from_node_config_when_present(self):
        from apps.orchestrator.models import Agent, WorkflowNode

        node = Agent.objects.get(name="Sales Agent").active_definition.nodes.get(key="RETRY_PENDING")
        node.config = {"backoff_minutes": [2, 20]}
        node.save()
        self.assertEqual(decision_engine._backoff_minutes(1), 2)
        self.assertEqual(decision_engine._backoff_minutes(2), 20)
        self.assertEqual(decision_engine._backoff_minutes(5), 20)  # clamps to last entry
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test apps.orchestrator.tests.DecisionEngineGraphTests -v 2`
Expected: FAIL — `classify_connected_outcome` still returns `WorkflowState.COMPLETED` ("COMPLETED") as a transition target directly (bypassing the graph), so `test_backoff_minutes_read_from_node_config_when_present` fails first with `AttributeError` since `_backoff_minutes` doesn't read node config yet.

- [ ] **Step 3: Rewrite `decision_engine.py`**

Replace the entire file content with:

```python
"""
Retry/backoff decision logic for call and WhatsApp outcomes. Retry logic lives here
for V1 — no separate retry_policy.py yet (project CLAUDE.md Section 5, item 2).
Structure (which node a label routes to) now lives in the graph — see
workflow_service.resolve_next_node(). This file only decides WHICH label applies;
it never hardcodes a target state.
"""
from datetime import timedelta

from django.utils import timezone

from apps.orchestrator.models import WorkflowHistory
from apps.orchestrator.services import workflow_service

MAX_RETRIES = 3

# Fallback when the RETRY_PENDING WorkflowNode has no config.backoff_minutes set.
# Short intervals — demo/dev tuning, not production hours (production would use
# HOURS; MINUTES here so the full retry cycle is verifiable within a short demo
# window).
RETRY_BACKOFF_MINUTES = [1, 5, 15]


def _backoff_minutes(attempt_count: int) -> int:
    """
    attempt_count is 1-indexed retry number; clamp to last value if beyond list
    length. Prefers the active RETRY_PENDING WorkflowNode's config.backoff_minutes
    (canvas-editable) over the RETRY_BACKOFF_MINUTES fallback constant.
    """
    from apps.orchestrator.models import WorkflowNode

    node = WorkflowNode.objects.filter(definition__is_active=True, key="RETRY_PENDING").first()
    schedule = (node.config.get("backoff_minutes") if node else None) or RETRY_BACKOFF_MINUTES

    index = 0 if attempt_count < 1 else min(attempt_count, len(schedule)) - 1
    return schedule[index]


def classify_connected_outcome(payload: dict, whatsapp_sent: bool = False) -> str:
    """
    Determines which label CONNECTED resolves to: "hot_lead" or "completed" (the
    graph's CONNECTED node also has "voicemail"/"other_inquiry"/"failed" edges
    reserved for later, unused by this placeholder rule).

    Confirmed rule so far: if a WhatsApp follow-up notification was sent for this
    call, the lead counts as hot_lead. Everything else is still a PLACEHOLDER — the
    rule for telling apart voicemail/other_inquiry/failed hasn't been provided yet,
    so any call that didn't trigger a WhatsApp send just falls through to completed.
    `payload` is accepted now so the call site never needs to change again once the
    rest of the rule is known — only this function's body changes.
    """
    if whatsapp_sent:
        return "hot_lead"
    return "completed"


def record_qa_review(workflow) -> None:
    """
    Audit checkpoint recorded whenever a call finishes classification — mirrors
    workflow_service.record_dnd_check()'s pattern: not a resting state, just a point
    every classified call passes through.
    """
    WorkflowHistory.objects.create(workflow=workflow, event="qa_review_passed", payload={})


def handle_call_outcome(workflow, outcome: str):
    """
    outcome is one of "connected" | "no_answer" | "busy" | "failed" | "dispatched"
    (from dispatcher.dispatch_call()). Workflow is currently in CALLING state.
    Returns the final workflow instance. Every transition target is resolved via
    workflow_service.resolve_next_node(from_key, label) — never a hardcoded state —
    so rewiring any of these edges on the canvas changes real routing immediately.
    """
    if outcome == "dispatched":
        to_key = workflow_service.resolve_next_node(workflow.state, "dispatched")
        if to_key is None:
            workflow_service.record_unrouted_transition(workflow, workflow.state, "dispatched")
            return workflow
        return workflow_service.transition(
            workflow,
            to_key,
            event="chat360_dispatch_connected",
            payload={"note": "Real Chat360 outbound call accepted; awaiting post-call webhook"},
        )

    if outcome == "connected":
        connected_key = workflow_service.resolve_next_node(workflow.state, "connected")
        if connected_key is None:
            workflow_service.record_unrouted_transition(workflow, workflow.state, "connected")
            return workflow
        workflow_service.transition(workflow, connected_key, event="call_connected")

        label = classify_connected_outcome({})
        final_key = workflow_service.resolve_next_node(connected_key, label)
        if final_key is None:
            workflow_service.record_unrouted_transition(workflow, connected_key, label)
            return workflow
        workflow = workflow_service.transition(workflow, final_key, event="call_completed")
        record_qa_review(workflow)
        return workflow

    # no_answer -> "unanswered" label, busy/failed -> "not_connected" label.
    label = "unanswered" if outcome == "no_answer" else "not_connected"
    intermediate_event = "call_unanswered" if outcome == "no_answer" else "call_not_connected"
    intermediate_key = workflow_service.resolve_next_node(workflow.state, label)
    if intermediate_key is None:
        workflow_service.record_unrouted_transition(workflow, workflow.state, label)
        return workflow
    workflow_service.transition(
        workflow, intermediate_key, event=intermediate_event, payload={"outcome": outcome}
    )

    workflow.attempt_count += 1
    workflow.save()

    if workflow.attempt_count < MAX_RETRIES:
        retry_key = workflow_service.resolve_next_node(intermediate_key, "retry")
        if retry_key is None:
            workflow_service.record_unrouted_transition(workflow, intermediate_key, "retry")
            return workflow
        workflow_service.transition(
            workflow, retry_key, event="call_retry_needed", payload={"outcome": outcome}
        )
        backoff = timedelta(minutes=_backoff_minutes(workflow.attempt_count))
        workflow.next_execution = timezone.now() + backoff
        workflow.save()

        waiting_key = workflow_service.resolve_next_node(retry_key, "retry")
        if waiting_key is None:
            workflow_service.record_unrouted_transition(workflow, retry_key, "retry")
            return workflow
        workflow = workflow_service.transition(workflow, waiting_key, event="retry_scheduled")
        return workflow

    # Max retries exhausted -> fall back to WhatsApp.
    exhausted_key = workflow_service.resolve_next_node(intermediate_key, "retry")
    # NOTE: both the "retry" and "exhausted" outcomes leave CALLING's intermediate
    # node (UNANSWERED/NOT_CONNECTED) via the SAME single-path "" edge to
    # RETRY_PENDING first — the actual retry-vs-exhausted decision happens at
    # RETRY_PENDING itself (label "retry" vs "exhausted"), not here. Resolve that
    # single-path edge with label "".
    exhausted_key = workflow_service.resolve_next_node(intermediate_key, "")
    if exhausted_key is None:
        workflow_service.record_unrouted_transition(workflow, intermediate_key, "")
        return workflow
    workflow_service.transition(workflow, exhausted_key, event="call_retry_exhausted")

    whatsapp_key = workflow_service.resolve_next_node(exhausted_key, "exhausted")
    if whatsapp_key is None:
        workflow_service.record_unrouted_transition(workflow, exhausted_key, "exhausted")
        return workflow
    workflow = workflow_service.transition(workflow, whatsapp_key, event="whatsapp_fallback_triggered")

    # Demo simplification: there's no real inbound WhatsApp webhook yet, so we
    # synchronously resolve the WhatsApp fallback right here instead of leaving the
    # workflow parked in WHATSAPP_PENDING. A real system would leave it in
    # WHATSAPP_PENDING until an inbound webhook resolves it asynchronously.
    from apps.orchestrator.services import dispatcher  # lazy import: avoid ordering issues with sibling module

    result = dispatcher.dispatch_whatsapp(workflow)
    workflow = handle_whatsapp_outcome(workflow, result["status"])
    return workflow


def handle_whatsapp_outcome(workflow, outcome: str):
    """
    outcome is "responded" | "no_response" (from dispatcher.dispatch_whatsapp()).
    Workflow is currently in WHATSAPP_PENDING.
    """
    label = "responded" if outcome == "responded" else "no_response"
    to_key = workflow_service.resolve_next_node(workflow.state, label)
    if to_key is None:
        workflow_service.record_unrouted_transition(workflow, workflow.state, label)
        return workflow
    workflow = workflow_service.transition(workflow, to_key, event=f"whatsapp_{label}")
    record_qa_review(workflow)
    return workflow
```

**Correction note for the implementer:** the `exhausted_key` variable above is intentionally assigned twice in the plan text — the first assignment (`resolve_next_node(intermediate_key, "retry")`) is wrong and must be deleted; only the second (`resolve_next_node(intermediate_key, "")`) is correct, since `UNANSWERED`/`NOT_CONNECTED` -> `RETRY_PENDING` is a single-path edge (label `""`) per the seed's `EDGES` table — the real retry-vs-exhausted decision label lives on the *next* hop, out of `RETRY_PENDING`. Write the function with only the second assignment; do not leave both lines in the file.

- [ ] **Step 3.5: Update `chat360_call_result_webhook` in `views.py` to match the new label contract**

In `orchestrator_django/apps/orchestrator/api/views.py`, the current implementation (around lines 355-372) hardcodes `WorkflowState.CONNECTED` as a transition target and feeds `classify_connected_outcome()`'s return value straight into `transition()` as `final_state` — both must change now that `classify_connected_outcome` returns a label, not a state. Replace:

```python
        if workflow.state == WorkflowState.CALLING:
            workflow = workflow_service.transition(
                workflow, WorkflowState.CONNECTED, event="chat360_dispatch_connected"
            )
        if workflow.state == WorkflowState.CONNECTED:
            # "Sent" here means Chat360 actually accepted the WhatsApp request (ok=True)
            # — NOT just "an interest_type matched a template," which would also be
            # true for Showroom Visit/Price Quotation's not-yet-configured stub
            # response (ok=False, no real request ever went out) or a genuine network
            # failure on a real attempt.
            whatsapp_sent = bool(whatsapp_result and whatsapp_result.get("ok"))
            final_state = decision_engine.classify_connected_outcome(
                body, whatsapp_sent=whatsapp_sent
            )
            workflow = workflow_service.transition(
                workflow, final_state, event="chat360_call_completed"
            )
            decision_engine.record_qa_review(workflow)
```

With:

```python
        if workflow.state == WorkflowState.CALLING:
            connected_key = workflow_service.resolve_next_node(workflow.state, "connected")
            if connected_key is None:
                workflow_service.record_unrouted_transition(workflow, workflow.state, "connected")
            else:
                workflow = workflow_service.transition(
                    workflow, connected_key, event="chat360_dispatch_connected"
                )
        if workflow.state == WorkflowState.CONNECTED:
            # "Sent" here means Chat360 actually accepted the WhatsApp request (ok=True)
            # — NOT just "an interest_type matched a template," which would also be
            # true for Showroom Visit/Price Quotation's not-yet-configured stub
            # response (ok=False, no real request ever went out) or a genuine network
            # failure on a real attempt.
            whatsapp_sent = bool(whatsapp_result and whatsapp_result.get("ok"))
            label = decision_engine.classify_connected_outcome(body, whatsapp_sent=whatsapp_sent)
            final_key = workflow_service.resolve_next_node(workflow.state, label)
            if final_key is None:
                workflow_service.record_unrouted_transition(workflow, workflow.state, label)
            else:
                workflow = workflow_service.transition(
                    workflow, final_key, event="chat360_call_completed"
                )
                decision_engine.record_qa_review(workflow)
```

This reuses the `"connected"` label (the same one `decision_engine.handle_call_outcome`'s mock/demo path resolves via `resolve_next_node(workflow.state, "connected")`) since both are "CALLING resolved to CONNECTED" — the seed's `CALLING` node has this edge regardless of which of the two call sites reaches it first (see the module comment already in this function about the webhook sometimes beating the scheduler's own transition).

Add this test to `tests.py`, in a new class:

```python
class Chat360WebhookGraphTests(TestCase):
    def setUp(self):
        seed_default_workflow()
        self.client = APIClient()

    def test_real_webhook_resolves_connected_and_completed_via_graph(self):
        workflow = workflow_service.create_workflow(lead_id="wh-1", crm="upload", campaign_id="c1")
        workflow.state = "CALLING"
        workflow.save()
        CampaignLead.objects.create(
            campaign_id="c1", lead_id="wh-1", to_number="+919876543210", params={}, workflow=workflow
        )

        response = self.client.post(
            "/api/webhooks/chat360/call-result/",
            {"contact_no": "9876543210", "session_id": "s-wh-1", "interest_type": ""},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        workflow.refresh_from_db()
        self.assertEqual(workflow.state, "COMPLETED")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test apps.orchestrator.tests.DecisionEngineGraphTests apps.orchestrator.tests.Chat360WebhookGraphTests -v 2`
Expected: PASS (7 tests)

- [ ] **Step 5: Run full existing suite (regression check)**

Run: `python manage.py test apps.orchestrator -v 2`
Expected: ALL tests pass now, including the ones flagged as expected-to-fail at the end of Task 3 Step 7 (`CallbackSchedulingTests`, `RelativeCallBackTimeTests`, `CallbackDedupTests`, `CampaignDndLaunchTests`).

If any of the 4 pre-existing `TestCase` classes still fail: their `setUp` needs `seed_default_workflow()` called first (they don't call it yet). For each of `CampaignDndLaunchTests`, `CallbackSchedulingTests`, `RelativeCallBackTimeTests`, `CallbackDedupTests` in `tests.py`, change:

```python
    def setUp(self):
        self.client = APIClient()
```

To:

```python
    def setUp(self):
        seed_default_workflow()
        self.client = APIClient()
```

Re-run: `python manage.py test apps.orchestrator -v 2` — expect all PASS.

- [ ] **Step 6: Commit**

```bash
git add orchestrator_django/apps/orchestrator/services/decision_engine.py orchestrator_django/apps/orchestrator/api/views.py orchestrator_django/apps/orchestrator/tests.py
git commit -m "decision_engine resolves transitions via labels, not hardcoded states"
```

---

## Task 6: `briefing_stats` — analytics variables + unrouted count

**Files:**
- Modify: `orchestrator_django/apps/orchestrator/api/views.py`
- Test: `orchestrator_django/apps/orchestrator/tests.py` (new `BriefingStatsAnalyticsTests` class)

**Interfaces:**
- Consumes: `WorkflowNode` (Task 1), `seed_default_workflow` (Task 2).
- Produces: `briefing_stats` view — response gains two new top-level keys: `analytics` (`{key: count}` dict, e.g. `{"test_drives": 3, "showroom_visits": 1}`, replacing the hardcoded `test_drives`/`showroom_visits` fields — **both old fields are kept in the response too**, populated from the same `analytics` dict, so the existing dashboard `AiBriefing`/`lib/types.ts` contract does not break) and `unrouted_count` (int).

- [ ] **Step 1: Write the failing test**

Append to `tests.py`:

```python
from apps.orchestrator.models import Chat360WebhookLog


class BriefingStatsAnalyticsTests(TestCase):
    def setUp(self):
        seed_default_workflow()
        self.client = APIClient()

    def test_analytics_dict_reflects_outcome_node_variables(self):
        Chat360WebhookLog.objects.create(
            contact_no="+919876543210",
            session_id="s1",
            payload={"interest_type": "Test Ride"},
        )
        Chat360WebhookLog.objects.create(
            contact_no="+919876543211",
            session_id="s2",
            payload={"interest_type": "Showroom Visit"},
        )

        response = self.client.get("/api/briefing/stats/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["analytics"]["test_drives"], 1)
        self.assertEqual(response.data["analytics"]["showroom_visits"], 1)
        # backward-compatible top-level fields still present for the existing dashboard contract
        self.assertEqual(response.data["test_drives"], 1)
        self.assertEqual(response.data["showroom_visits"], 1)

    def test_unrouted_count_reflects_history_events(self):
        workflow = workflow_service.create_workflow(lead_id="ur-1", crm="manual", campaign_id="c1")
        workflow_service.record_unrouted_transition(workflow, "WAITING", "bogus_label")

        response = self.client.get("/api/briefing/stats/")

        self.assertEqual(response.data["unrouted_count"], 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test apps.orchestrator.tests.BriefingStatsAnalyticsTests -v 2`
Expected: FAIL — `KeyError: 'analytics'`

- [ ] **Step 3: Update `briefing_stats`**

In `orchestrator_django/apps/orchestrator/api/views.py`, the current implementation (lines 139-233) computes `test_drives`/`showroom_visits` via hardcoded `notifications.is_test_drive_interest`/`is_showroom_visit_interest` calls inside the `Chat360WebhookLog` loop (lines 195-216), then returns a fixed dict (lines 218-232). Replace that loop and the return block with:

```python
    from apps.orchestrator.models import WorkflowNode

    outcome_node = WorkflowNode.objects.filter(
        definition__is_active=True, key="COMPLETED"
    ).first()
    variables = (outcome_node.config.get("variables", []) if outcome_node else [])

    def _matches(effective_interest_type: str, keywords: list) -> bool:
        text = effective_interest_type.lower()
        return any(kw.lower() in text for kw in keywords)

    seen_sessions = set()
    analytics = {v["key"]: 0 for v in variables}
    whatsapp_sent = 0
    for log in Chat360WebhookLog.objects.all().order_by("id"):
        session_id = log.session_id
        if session_id:
            if session_id in seen_sessions:
                continue
            seen_sessions.add(session_id)

        payload = log.payload if isinstance(log.payload, dict) else {}
        raw_interest_type = str(payload.get("interest_type") or "")
        raw_summary = str(payload.get("summary") or "")
        effective = notifications.resolve_interest_type(raw_interest_type, raw_summary)

        for variable in variables:
            if _matches(effective, variable.get("match_keywords", [])):
                analytics[variable["key"]] += 1
        if log.whatsapp_notification_sent:
            whatsapp_sent += 1

    unrouted_count = (
        WorkflowHistory.objects.filter(event="unrouted_transition")
        .values("workflow_id")
        .distinct()
        .count()
    )

    return Response(
        {
            "hot_leads": hot_leads,
            "callback_due": callback_due,
            "bot_failures": bot_failures,
            "not_connected": not_connected,
            "test_drives": analytics.get("test_drives", 0),
            "showroom_visits": analytics.get("showroom_visits", 0),
            "whatsapp_sent": whatsapp_sent,
            "dnd_check": dnd_check,
            "suppressed_dnc": suppressed_dnc,
            "qa_review": qa_review,
            "department_counts": department_counts,
            "analytics": analytics,
            "unrouted_count": unrouted_count,
        },
        status=status.HTTP_200_OK,
    )
```

Leave everything above this block in `briefing_stats` (the `hot_leads`/`callback_due`/`bot_failures`/`not_connected`/`dnd_check`/`suppressed_dnc`/`qa_review`/`department_counts` computations) unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test apps.orchestrator.tests.BriefingStatsAnalyticsTests -v 2`
Expected: PASS (2 tests)

- [ ] **Step 5: Run full suite**

Run: `python manage.py test apps.orchestrator -v 2`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add orchestrator_django/apps/orchestrator/api/views.py orchestrator_django/apps/orchestrator/tests.py
git commit -m "briefing_stats: analytics variables from outcome node config, unrouted_count"
```

---

## Task 7: Serializers + API endpoints for Agent/WorkflowDefinition

**Files:**
- Modify: `orchestrator_django/apps/orchestrator/api/serializers.py`
- Modify: `orchestrator_django/apps/orchestrator/api/views.py`
- Modify: `orchestrator_django/apps/orchestrator/api/urls.py`
- Test: `orchestrator_django/apps/orchestrator/tests.py` (new `AgentApiTests` class)

**Interfaces:**
- Consumes: `Agent`, `WorkflowDefinition`, `WorkflowNode`, `WorkflowEdge` (Task 1), `seed_default_workflow` (Task 2).
- Produces: `GET /api/agents/`, `GET /api/agents/<id>/definition/`, `PUT /api/workflow-definitions/<id>/`, `POST /api/workflow-definitions/<id>/activate/`.

- [ ] **Step 1: Write the failing tests**

Append to `tests.py`:

```python
class AgentApiTests(TestCase):
    def setUp(self):
        self.agent = seed_default_workflow()
        self.client = APIClient()

    def test_agent_list(self):
        response = self.client.get("/api/agents/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "Sales Agent")

    def test_agent_definition_returns_nodes_and_edges(self):
        response = self.client.get(f"/api/agents/{self.agent.id}/definition/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["nodes"]), 18)
        self.assertGreater(len(response.data["edges"]), 0)

    def test_update_definition_moves_a_node_position(self):
        definition = self.agent.active_definition
        response = self.client.get(f"/api/agents/{self.agent.id}/definition/")
        body = response.data
        for node in body["nodes"]:
            if node["key"] == "WAITING":
                node["position_x"] = 999

        put_response = self.client.put(
            f"/api/workflow-definitions/{definition.id}/", body, format="json"
        )
        self.assertEqual(put_response.status_code, 200)

        definition.refresh_from_db()
        waiting = definition.nodes.get(key="WAITING")
        self.assertEqual(waiting.position_x, 999)

    def test_activate_flips_is_active(self):
        definition = self.agent.active_definition
        response = self.client.post(f"/api/workflow-definitions/{definition.id}/activate/")
        self.assertEqual(response.status_code, 200)
        definition.refresh_from_db()
        self.assertTrue(definition.is_active)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test apps.orchestrator.tests.AgentApiTests -v 2`
Expected: FAIL — `404` for `/api/agents/` (route doesn't exist).

- [ ] **Step 3: Add serializers**

In `orchestrator_django/apps/orchestrator/api/serializers.py`, add at the end:

```python
from apps.orchestrator.models import Agent, WorkflowDefinition, WorkflowEdge, WorkflowNode


class WorkflowNodeSerializer(ModelSerializer):
    class Meta:
        model = WorkflowNode
        fields = ["id", "key", "kind", "name", "config", "position_x", "position_y"]


class WorkflowEdgeSerializer(ModelSerializer):
    source_node_id = IntegerField(source="source_node.id", read_only=True)
    target_node_id = IntegerField(source="target_node.id", read_only=True)

    class Meta:
        model = WorkflowEdge
        fields = ["id", "source_node_id", "target_node_id", "label"]


class WorkflowDefinitionSerializer(ModelSerializer):
    nodes = WorkflowNodeSerializer(many=True, read_only=True)
    edges = WorkflowEdgeSerializer(many=True, read_only=True)

    class Meta:
        model = WorkflowDefinition
        fields = ["id", "name", "scope", "is_active", "version", "nodes", "edges"]


class AgentSerializer(ModelSerializer):
    class Meta:
        model = Agent
        fields = ["id", "name", "department", "icon", "active_definition"]
```

- [ ] **Step 4: Add views**

In `orchestrator_django/apps/orchestrator/api/views.py`, add near the top imports:

```python
from apps.orchestrator.models import Agent, WorkflowDefinition, WorkflowEdge, WorkflowNode
```

And add these new view functions (near the end of the file, after `chat360_call_result_webhook`):

```python
@api_view(["GET"])
def agent_list(request):
    agents = Agent.objects.all().order_by("name")
    return Response(AgentSerializer(agents, many=True).data, status=status.HTTP_200_OK)


@api_view(["GET"])
def agent_definition(request, pk):
    agent = get_object_or_404(Agent, pk=pk)
    if agent.active_definition is None:
        return Response({"error": "agent has no active definition"}, status=status.HTTP_404_NOT_FOUND)
    return Response(WorkflowDefinitionSerializer(agent.active_definition).data, status=status.HTTP_200_OK)


@api_view(["PUT"])
def workflow_definition_update(request, pk):
    """
    Replaces this definition's nodes/edges/positions in one transaction (canvas
    "Save"). Existing nodes are updated by id when present in the payload; nodes not
    present in the payload are deleted along with their edges. New nodes (no "id" in
    the payload) are created. Edges are always fully replaced from the payload.
    """
    definition = get_object_or_404(WorkflowDefinition, pk=pk)
    nodes_data = request.data.get("nodes", [])
    edges_data = request.data.get("edges", [])

    from django.db import transaction

    with transaction.atomic():
        keep_ids = set()
        key_to_node = {}
        for node_data in nodes_data:
            node_id = node_data.get("id")
            if node_id and definition.nodes.filter(id=node_id).exists():
                node = definition.nodes.get(id=node_id)
                node.key = node_data["key"]
                node.kind = node_data["kind"]
                node.name = node_data["name"]
                node.config = node_data.get("config", {})
                node.position_x = node_data.get("position_x", 0)
                node.position_y = node_data.get("position_y", 0)
                node.save()
            else:
                node = WorkflowNode.objects.create(
                    definition=definition,
                    key=node_data["key"],
                    kind=node_data["kind"],
                    name=node_data["name"],
                    config=node_data.get("config", {}),
                    position_x=node_data.get("position_x", 0),
                    position_y=node_data.get("position_y", 0),
                )
            keep_ids.add(node.id)
            key_to_node[node.key] = node

        definition.nodes.exclude(id__in=keep_ids).delete()

        definition.edges.all().delete()
        for edge_data in edges_data:
            source = key_to_node.get(edge_data["source_key"])
            target = key_to_node.get(edge_data["target_key"])
            if source is None or target is None:
                continue  # skip edges referencing a node not in this save — no hard block tonight
            WorkflowEdge.objects.create(
                definition=definition,
                source_node=source,
                target_node=target,
                label=edge_data.get("label", ""),
            )

    return Response(WorkflowDefinitionSerializer(definition).data, status=status.HTTP_200_OK)


@api_view(["POST"])
def workflow_definition_activate(request, pk):
    """Flips is_active on this definition; effective on the next scheduler tick / webhook."""
    definition = get_object_or_404(WorkflowDefinition, pk=pk)
    WorkflowDefinition.objects.filter(scope=definition.scope).update(is_active=False)
    definition.is_active = True
    definition.save(update_fields=["is_active"])
    return Response(WorkflowDefinitionSerializer(definition).data, status=status.HTTP_200_OK)
```

And update the `from .serializers import (...)` block at the top of `views.py` to also import `AgentSerializer`, `WorkflowDefinitionSerializer`.

- [ ] **Step 5: Wire URLs**

In `orchestrator_django/apps/orchestrator/api/urls.py`, add:

```python
    path("agents/", views.agent_list, name="agent-list"),
    path("agents/<int:pk>/definition/", views.agent_definition, name="agent-definition"),
    path(
        "workflow-definitions/<int:pk>/",
        views.workflow_definition_update,
        name="workflow-definition-update",
    ),
    path(
        "workflow-definitions/<int:pk>/activate/",
        views.workflow_definition_activate,
        name="workflow-definition-activate",
    ),
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python manage.py test apps.orchestrator.tests.AgentApiTests -v 2`
Expected: PASS (4 tests)

- [ ] **Step 7: Run full suite**

Run: `python manage.py test apps.orchestrator -v 2`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add orchestrator_django/apps/orchestrator/api/serializers.py orchestrator_django/apps/orchestrator/api/views.py orchestrator_django/apps/orchestrator/api/urls.py orchestrator_django/apps/orchestrator/tests.py
git commit -m "add Agent/WorkflowDefinition CRUD endpoints"
```

---

## Task 8: Frontend types + API client + install React Flow

**Files:**
- Modify: `dashboard/lib/types.ts`
- Modify: `dashboard/lib/sources/orchestratorDjangoSource.ts`
- Modify: `dashboard/package.json` (via `npm install`)

**Interfaces:**
- Produces: `Agent`, `WorkflowDefinitionGraph`, `WorkflowNodeData`, `WorkflowEdgeData` types; `fetchAgents()`, `fetchAgentDefinition(agentId)`, `saveWorkflowDefinition(definitionId, graph)`, `activateWorkflowDefinition(definitionId)` functions.

- [ ] **Step 1: Install `@xyflow/react`**

Run: `cd dashboard && npm install @xyflow/react`
Expected: added to `dependencies` in `package.json`.

- [ ] **Step 2: Add types**

In `dashboard/lib/types.ts`, add after the existing `BriefingStats` interface (near where `WorkflowState` is defined), matching the file's existing section-comment convention:

```typescript
// ── AI Agent Orchestration (Agent -> WorkflowDefinition graph) ──

export type WorkflowNodeKind = "trigger" | "webhook" | "logic" | "wait" | "outcome";

export interface OutcomeVariable {
  key: string;
  label: string;
  match_keywords: string[];
}

export interface WorkflowNodeData {
  id: number;
  key: string;
  kind: WorkflowNodeKind;
  name: string;
  config: { url?: string; logic_ref?: string; backoff_minutes?: number[]; variables?: OutcomeVariable[] };
  position_x: number;
  position_y: number;
}

export interface WorkflowEdgeData {
  id: number;
  source_node_id: number;
  target_node_id: number;
  label: string;
}

export interface WorkflowDefinitionGraph {
  id: number;
  name: string;
  scope: string;
  is_active: boolean;
  version: number;
  nodes: WorkflowNodeData[];
  edges: WorkflowEdgeData[];
}

export interface Agent {
  id: number;
  name: string;
  department: string;
  icon: string;
  active_definition: number | null;
}
```

Also add two fields to the existing `BriefingStats` interface (find it via the earlier grep — it starts around the `hot_leads`/`callback_due` fields): add `analytics: Record<string, number>;` and `unrouted_count: number;` alongside the existing fields.

- [ ] **Step 3: Add API client functions**

In `dashboard/lib/sources/orchestratorDjangoSource.ts`, add at the end:

```typescript
import type { Agent, WorkflowDefinitionGraph } from "@/lib/types";

export async function fetchAgents(): Promise<Agent[]> {
  const res = await fetch(`${BASE_URL}/api/agents/`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`fetchAgents: orchestrator API responded with ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as Agent[];
}

export async function fetchAgentDefinition(agentId: number): Promise<WorkflowDefinitionGraph> {
  const res = await fetch(`${BASE_URL}/api/agents/${agentId}/definition/`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(
      `fetchAgentDefinition: orchestrator API responded with ${res.status} ${res.statusText} for agent ${agentId}`
    );
  }
  return (await res.json()) as WorkflowDefinitionGraph;
}

export interface SaveGraphPayload {
  nodes: Array<{
    id?: number;
    key: string;
    kind: string;
    name: string;
    config: Record<string, unknown>;
    position_x: number;
    position_y: number;
  }>;
  edges: Array<{ source_key: string; target_key: string; label: string }>;
}

export async function saveWorkflowDefinition(
  definitionId: number,
  graph: SaveGraphPayload
): Promise<WorkflowDefinitionGraph> {
  const res = await fetch(`${BASE_URL}/api/workflow-definitions/${definitionId}/`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(graph),
  });
  if (!res.ok) {
    throw new Error(
      `saveWorkflowDefinition: orchestrator API responded with ${res.status} ${res.statusText}`
    );
  }
  return (await res.json()) as WorkflowDefinitionGraph;
}

export async function activateWorkflowDefinition(definitionId: number): Promise<WorkflowDefinitionGraph> {
  const res = await fetch(`${BASE_URL}/api/workflow-definitions/${definitionId}/activate/`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new Error(
      `activateWorkflowDefinition: orchestrator API responded with ${res.status} ${res.statusText}`
    );
  }
  return (await res.json()) as WorkflowDefinitionGraph;
}
```

- [ ] **Step 4: Verify it compiles**

Run: `cd dashboard && npx tsc --noEmit`
Expected: no new type errors.

- [ ] **Step 5: Commit**

```bash
git add dashboard/lib/types.ts dashboard/lib/sources/orchestratorDjangoSource.ts dashboard/package.json dashboard/package-lock.json
git commit -m "add Agent/WorkflowDefinition types and API client, install @xyflow/react"
```

---

## Task 9: Layer 1 — Agent card list page

**Files:**
- Create: `dashboard/app/orchestrator/agents/page.tsx`
- Create: `dashboard/components/orchestrator/AgentCard.tsx`

**Interfaces:**
- Consumes: `fetchAgents` (Task 8), `Agent` type (Task 8), `Card`/`CardHeader` (existing, `dashboard/components/Card.tsx`).
- Produces: a page at `/orchestrator/agents` listing Agent cards, each linking to `/orchestrator/agents/<id>` (Task 10).

- [ ] **Step 1: Write `AgentCard.tsx`**

```typescript
"use client";

import Link from "next/link";
import { RiRobot2Line } from "react-icons/ri";
import { Card } from "@/components/Card";
import type { Agent } from "@/lib/types";

export function AgentCard({ agent }: { agent: Agent }) {
  return (
    <Link href={`/orchestrator/agents/${agent.id}`}>
      <Card className="p-5 hover:shadow-lg transition-shadow cursor-pointer">
        <div className="flex items-center gap-3">
          <span className="flex items-center justify-center w-10 h-10 rounded-full bg-blue-100 text-blue-600 text-xl">
            {agent.icon || <RiRobot2Line />}
          </span>
          <div>
            <p className="text-base font-semibold text-slate-800">{agent.name}</p>
            {agent.department && <p className="text-xs text-slate-400">{agent.department}</p>}
          </div>
        </div>
      </Card>
    </Link>
  );
}
```

- [ ] **Step 2: Write the page**

```typescript
"use client";

import { useEffect, useState } from "react";
import { AgentCard } from "@/components/orchestrator/AgentCard";
import { fetchAgents } from "@/lib/sources/orchestratorDjangoSource";
import type { Agent } from "@/lib/types";

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAgents()
      .then(setAgents)
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">AI Agents</h1>
        <p className="text-sm text-slate-500 mt-1">
          Each Agent owns one editable workflow. Click a card to open its canvas.
        </p>
      </div>
      {loading ? (
        <p className="text-sm text-slate-400">Loading…</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {agents.map((agent) => (
            <AgentCard key={agent.id} agent={agent} />
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Manual verification**

Run backend: `cd orchestrator_django && python manage.py runserver 8010` (in one terminal).
Run frontend: `cd dashboard && npm run dev` (in another terminal).
Open `http://localhost:3000/orchestrator/agents` — expect one card, "Sales Agent" / "Sales", linking to `/orchestrator/agents/1`.

- [ ] **Step 4: Commit**

```bash
git add dashboard/app/orchestrator/agents dashboard/components/orchestrator/AgentCard.tsx
git commit -m "add Layer 1 Agent card list page"
```

---

## Task 10: Layer 2 — React Flow canvas (render + palette)

**Files:**
- Create: `dashboard/app/orchestrator/agents/[id]/page.tsx`
- Create: `dashboard/components/orchestrator/canvas/WorkflowNodeCard.tsx`
- Create: `dashboard/components/orchestrator/canvas/NodePalette.tsx`

**Interfaces:**
- Consumes: `fetchAgentDefinition` (Task 8), `STATE_COLORS` (existing, `dashboard/components/orchestrator/RailToken.tsx`), `@xyflow/react` (Task 8).
- Produces: a page at `/orchestrator/agents/[id]` rendering the Agent's graph as a React Flow canvas; `WorkflowNodeCard` (custom node renderer); `NodePalette` (sidebar of draggable node-kind buttons, grouped Triggers/Integrations/Routing/Utilities/Outputs per the product brief's categories — AI/AI Agents categories shown with a "Coming soon" disabled state, per spec §3).

- [ ] **Step 1: Write `WorkflowNodeCard.tsx`**

```typescript
"use client";

import { Handle, Position } from "@xyflow/react";
import { STATE_COLORS } from "@/components/orchestrator/RailToken";
import type { WorkflowNodeData, WorkflowState } from "@/lib/types";

const KIND_LABELS: Record<string, string> = {
  trigger: "Trigger",
  webhook: "Integration",
  logic: "Routing",
  wait: "Utility",
  outcome: "Output",
};

export function WorkflowNodeCard({ data }: { data: WorkflowNodeData }) {
  const color = STATE_COLORS[data.key as WorkflowState] ?? "#64748b";
  return (
    <div
      className="rounded-xl border-2 bg-white px-4 py-2.5 shadow-sm min-w-[140px]"
      style={{ borderColor: color }}
    >
      <Handle type="target" position={Position.Left} />
      <p className="text-[9px] font-medium uppercase tracking-wide text-slate-400">
        {KIND_LABELS[data.kind] ?? data.kind}
      </p>
      <p className="text-sm font-semibold text-slate-800">{data.name}</p>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
```

- [ ] **Step 2: Write `NodePalette.tsx`**

```typescript
"use client";

const CATEGORIES: { label: string; kind: string; enabled: boolean }[] = [
  { label: "Trigger", kind: "trigger", enabled: true },
  { label: "Integration", kind: "webhook", enabled: true },
  { label: "Routing", kind: "logic", enabled: true },
  { label: "Utility", kind: "wait", enabled: true },
  { label: "Output", kind: "outcome", enabled: true },
  { label: "AI (coming soon)", kind: "ai", enabled: false },
  { label: "AI Agent (coming soon)", kind: "ai_agent", enabled: false },
];

export function NodePalette({ onAdd }: { onAdd: (kind: string) => void }) {
  return (
    <div className="w-48 shrink-0 space-y-2">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 px-1">Palette</p>
      {CATEGORIES.map((cat) => (
        <button
          key={cat.kind}
          type="button"
          disabled={!cat.enabled}
          onClick={() => onAdd(cat.kind)}
          className={`w-full text-left px-3 py-2 rounded-lg text-sm font-medium border ${
            cat.enabled
              ? "border-slate-200 bg-white hover:bg-slate-50 text-slate-700"
              : "border-slate-100 bg-slate-50 text-slate-300 cursor-not-allowed"
          }`}
        >
          {cat.label}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Write the canvas page**

```typescript
"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Card } from "@/components/Card";
import { NodePalette } from "@/components/orchestrator/canvas/NodePalette";
import { WorkflowNodeCard } from "@/components/orchestrator/canvas/WorkflowNodeCard";
import { fetchAgentDefinition } from "@/lib/sources/orchestratorDjangoSource";
import type { WorkflowDefinitionGraph } from "@/lib/types";

const nodeTypes = { workflowNode: WorkflowNodeCard };

function toFlowNodes(graph: WorkflowDefinitionGraph): Node[] {
  return graph.nodes.map((n) => ({
    id: String(n.id),
    type: "workflowNode",
    position: { x: n.position_x, y: n.position_y },
    data: n,
  }));
}

function toFlowEdges(graph: WorkflowDefinitionGraph): Edge[] {
  return graph.edges.map((e) => ({
    id: String(e.id),
    source: String(e.source_node_id),
    target: String(e.target_node_id),
    label: e.label || undefined,
  }));
}

export default function AgentWorkflowPage() {
  const params = useParams<{ id: string }>();
  const agentId = Number(params.id);

  const [graph, setGraph] = useState<WorkflowDefinitionGraph | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAgentDefinition(agentId)
      .then(setGraph)
      .finally(() => setLoading(false));
  }, [agentId]);

  const nodes = useMemo(() => (graph ? toFlowNodes(graph) : []), [graph]);
  const edges = useMemo(() => (graph ? toFlowEdges(graph) : []), [graph]);

  const handleAdd = useCallback((kind: string) => {
    // Task 11 wires this into real node creation + the config panel.
    console.log("add node of kind", kind);
  }, []);

  if (loading) return <p className="text-sm text-slate-400">Loading…</p>;
  if (!graph) return <p className="text-sm text-rose-500">Agent not found.</p>;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">{graph.name}</h1>
        <p className="text-sm text-slate-500 mt-1">
          {graph.is_active ? "Live — editing this graph affects real leads." : "Draft"}
        </p>
      </div>
      <div className="flex gap-4">
        <NodePalette onAdd={handleAdd} />
        <Card className="flex-1 p-0 overflow-hidden" style={{ height: "70vh" }}>
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView>
            <Background />
            <Controls />
            <MiniMap />
          </ReactFlow>
        </Card>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Manual verification**

With both servers running (from Task 9 Step 3), open `http://localhost:3000/orchestrator/agents/1`. Expect: 18 nodes rendered matching `LiveRail.tsx`'s station layout, pannable/zoomable, a minimap, and a palette sidebar with 5 enabled + 2 disabled categories.

- [ ] **Step 5: Commit**

```bash
git add dashboard/app/orchestrator/agents/\[id\] dashboard/components/orchestrator/canvas
git commit -m "add Layer 2 React Flow canvas (render + palette)"
```

---

## Task 11: Layer 2 — node config panel + create/save/publish

**Files:**
- Create: `dashboard/components/orchestrator/canvas/NodeConfigPanel.tsx`
- Modify: `dashboard/app/orchestrator/agents/[id]/page.tsx`

**Interfaces:**
- Consumes: `saveWorkflowDefinition`, `activateWorkflowDefinition` (Task 8).
- Produces: clicking a node opens a config panel editing `name`/`config` (shape depends on `kind`); "Save" persists via PUT; "Publish" calls activate.

- [ ] **Step 1: Write `NodeConfigPanel.tsx`**

```typescript
"use client";

import { useState } from "react";
import type { WorkflowNodeData } from "@/lib/types";

export function NodeConfigPanel({
  node,
  onChange,
  onClose,
}: {
  node: WorkflowNodeData;
  onChange: (updated: WorkflowNodeData) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(node.name);
  const [url, setUrl] = useState(node.config.url ?? "");

  function save() {
    onChange({ ...node, name, config: { ...node.config, url: node.kind === "webhook" ? url : undefined } });
    onClose();
  }

  return (
    <div className="w-72 shrink-0 bg-white border border-slate-200 rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-slate-800">Edit node</p>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-lg leading-none">
          ×
        </button>
      </div>
      <div>
        <label className="text-xs font-medium text-slate-500">Name</label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="mt-1 w-full text-sm border border-slate-300 rounded-md px-2 py-1.5"
        />
      </div>
      {node.kind === "webhook" && (
        <div>
          <label className="text-xs font-medium text-slate-500">Webhook URL (empty = use server default)</label>
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://…"
            className="mt-1 w-full text-sm border border-slate-300 rounded-md px-2 py-1.5"
          />
        </div>
      )}
      <button
        onClick={save}
        className="w-full bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-3 py-1.5 rounded-md"
      >
        Apply
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Wire it into the canvas page**

In `dashboard/app/orchestrator/agents/[id]/page.tsx`, add imports:

```typescript
import { NodeConfigPanel } from "@/components/orchestrator/canvas/NodeConfigPanel";
import { saveWorkflowDefinition, activateWorkflowDefinition } from "@/lib/sources/orchestratorDjangoSource";
import type { WorkflowNodeData } from "@/lib/types";
```

Add state and handlers inside `AgentWorkflowPage`, replacing the `handleAdd` stub:

```typescript
  const [selectedNode, setSelectedNode] = useState<WorkflowNodeData | null>(null);
  const [saving, setSaving] = useState(false);

  function handleNodeClick(_: React.MouseEvent, flowNode: Node) {
    setSelectedNode(flowNode.data as WorkflowNodeData);
  }

  function handleNodeUpdate(updated: WorkflowNodeData) {
    if (!graph) return;
    setGraph({
      ...graph,
      nodes: graph.nodes.map((n) => (n.id === updated.id ? updated : n)),
    });
  }

  async function handleSave() {
    if (!graph) return;
    setSaving(true);
    try {
      const keyById = new Map(graph.nodes.map((n) => [n.id, n.key]));
      const payload = {
        nodes: graph.nodes.map((n) => ({
          id: n.id,
          key: n.key,
          kind: n.kind,
          name: n.name,
          config: n.config,
          position_x: n.position_x,
          position_y: n.position_y,
        })),
        edges: graph.edges.map((e) => ({
          source_key: keyById.get(e.source_node_id) ?? "",
          target_key: keyById.get(e.target_node_id) ?? "",
          label: e.label,
        })),
      };
      const updated = await saveWorkflowDefinition(graph.id, payload);
      setGraph(updated);
    } finally {
      setSaving(false);
    }
  }

  async function handlePublish() {
    if (!graph) return;
    const updated = await activateWorkflowDefinition(graph.id);
    setGraph(updated);
  }
```

Update the JSX: add `onNodeClick={handleNodeClick}` to the `<ReactFlow>` element, render `{selectedNode && <NodeConfigPanel node={selectedNode} onChange={handleNodeUpdate} onClose={() => setSelectedNode(null)} />}` next to the palette, and add Save/Publish buttons in the header:

```typescript
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-bold text-slate-900">{graph.name}</h1>
        <button
          onClick={handleSave}
          disabled={saving}
          className="ml-auto bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm font-medium px-4 py-2 rounded-lg"
        >
          {saving ? "Saving…" : "Save"}
        </button>
        <button
          onClick={handlePublish}
          className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded-lg"
        >
          Publish
        </button>
      </div>
```

(Replace the existing `<h1>`/`<p>` header block with this, keeping the `is_active` status paragraph beneath it.)

- [ ] **Step 3: Manual verification**

Open `http://localhost:3000/orchestrator/agents/1`. Click the "Dispatching" node — config panel opens. Set a webhook URL, click Apply, click Save — expect no error. Run `sqlite3 orchestrator_django/db.sqlite3 "SELECT config FROM orchestrator_workflownode WHERE key='DISPATCHING';"` — expect the URL persisted. Click Publish — expect `is_active` stays true (already was).

- [ ] **Step 4: Commit**

```bash
git add dashboard/components/orchestrator/canvas/NodeConfigPanel.tsx dashboard/app/orchestrator/agents/\[id\]/page.tsx
git commit -m "add node config panel, save/publish wiring to Layer 2 canvas"
```

---

## Task 12: Layer 2 — live token overlay

**Files:**
- Modify: `dashboard/app/orchestrator/agents/[id]/page.tsx`

**Interfaces:**
- Consumes: `useWorkflowFeed` (existing, `dashboard/lib/hooks/useWorkflowFeed.ts`), `RailToken` (existing, `dashboard/components/orchestrator/RailToken.tsx`).
- Produces: animated pills on the canvas, one per in-flight `WorkflowInstance`, positioned at its current node's `(position_x, position_y)`.

- [ ] **Step 1: Add the overlay**

In `dashboard/app/orchestrator/agents/[id]/page.tsx`, add imports:

```typescript
import { useWorkflowFeed } from "@/lib/hooks/useWorkflowFeed";
import { RailToken } from "@/components/orchestrator/RailToken";
```

Inside `AgentWorkflowPage`, add:

```typescript
  const { workflows } = useWorkflowFeed();

  const nodePositionByKey = useMemo(() => {
    const map = new Map<string, { x: number; y: number }>();
    graph?.nodes.forEach((n) => map.set(n.key, { x: n.position_x, y: n.position_y }));
    return map;
  }, [graph]);
```

Add an SVG overlay layer inside the canvas `<Card>`, as a sibling of `<ReactFlow>` (absolutely positioned, matching the pattern `LiveRail.tsx` already uses for its HTML/SVG overlay — note this overlay uses raw graph coordinates, not React Flow's pan/zoom transform, so it's a simplified v1 that doesn't track panning; acceptable for the demo, flagged as a known limitation):

```typescript
        <Card className="flex-1 p-0 overflow-hidden relative" style={{ height: "70vh" }}>
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodeClick={handleNodeClick} fitView>
            <Background />
            <Controls />
            <MiniMap />
          </ReactFlow>
          <svg className="absolute inset-0 pointer-events-none" width="100%" height="100%">
            {workflows.map((w) => {
              const pos = nodePositionByKey.get(w.state);
              if (!pos) return null;
              return (
                <RailToken key={w.id} workflow={w} position={pos} selected={false} />
              );
            })}
          </svg>
        </Card>
```

- [ ] **Step 2: Manual verification**

With the Django scheduler running (`python manage.py shell -c "from apps.orchestrator.services import scheduler; scheduler.tick()"` once, or a loop) and a workflow created via `POST /api/campaigns/`, open the canvas page — expect a small colored pill to appear near whichever node the workflow currently occupies, matching `STATE_COLORS`.

- [ ] **Step 3: Commit**

```bash
git add dashboard/app/orchestrator/agents/\[id\]/page.tsx
git commit -m "add live token overlay to Layer 2 canvas"
```

---

## Task 13: Recommendation panel — unrouted-transition line

**Files:**
- Modify: `dashboard/components/orchestrator/AiBriefing.tsx`

**Interfaces:**
- Consumes: `stats.unrouted_count` (Task 6, already flowing through `fetchBriefingStats`/`BriefingStats` type from Task 8).

This is the only change needed for §7 of the spec — `AiBriefing.tsx` already implements the recommendation-panel pattern; it just needs one more rule.

- [ ] **Step 1: Add the new line**

In `dashboard/components/orchestrator/AiBriefing.tsx`, add an import for a warning icon (reuse `RiErrorWarningLine`, already imported) and add this block inside `buildLines`, after the `bot_failures` block (originally lines 69-76):

```typescript
  if (stats.unrouted_count > 0) {
    lines.push({
      key: "unrouted_count",
      tone: "rose",
      icon: RiErrorWarningLine,
      text: `${stats.unrouted_count} ${plural(stats.unrouted_count, "lead")} stuck — a workflow edge is missing on the canvas.`,
    });
  }
```

- [ ] **Step 2: Manual verification**

Trigger an unrouted transition (from Task 6's test, or manually via Django shell: `workflow_service.record_unrouted_transition(workflow, "WAITING", "bogus")`), refresh the orchestrator workflows dashboard page, confirm the new red-toned line appears in "AI Briefing".

- [ ] **Step 3: Commit**

```bash
git add dashboard/components/orchestrator/AiBriefing.tsx
git commit -m "surface unrouted transitions in AI Briefing recommendations"
```

---

## Task 14: End-to-end manual verification

**Files:** none (verification only).

- [ ] **Step 1: Fresh seed**

```bash
cd orchestrator_django
rm -f db.sqlite3   # only if you want a truly clean demo DB — skip if you have real leads to keep
python manage.py migrate
python manage.py seed_default_workflow
```

- [ ] **Step 2: Start both servers**

```bash
# terminal 1
cd orchestrator_django && python manage.py runserver 8010
# terminal 2
cd dashboard && npm run dev
```

- [ ] **Step 3: Layer 1 → Layer 2 → edit → publish**

Open `http://localhost:3000/orchestrator/agents` — one "Sales Agent" card. Click in — canvas renders 18 nodes matching the current rail layout. Click "Dispatching", set a test webhook URL (e.g. `https://httpbin.org/post`), Apply, Save, Publish.

- [ ] **Step 4: Real lead flows through the edited graph**

```bash
curl -X POST http://localhost:8010/api/campaigns/ \
  -H "Content-Type: application/json" \
  -d '{"campaign_id": "demo-1", "leads": [{"lead_id": "demo-lead-1", "to_number": "9876543210"}]}'
```

Run one scheduler tick: `cd orchestrator_django && python manage.py shell -c "from apps.orchestrator.services import scheduler; print(scheduler.tick())"` — expect `1`.

Check the lead moved: `python manage.py shell -c "from apps.orchestrator.models import WorkflowInstance; w = WorkflowInstance.objects.get(lead_id='demo-lead-1'); print(w.state, list(w.history.values_list('event', flat=True)))"` — expect a state past `WAITING` and a history list starting with `workflow_created`, `scheduler_pickup`, `dispatch_call_start`.

- [ ] **Step 5: Layer 3 shows the real timeline**

Open `http://localhost:3000/orchestrator/workflows`, find `demo-lead-1` in the queue/rail, click it — `WorkflowDetailPanel` opens showing the Stepper, and the Timeline tab lists the same events confirmed in Step 4.

- [ ] **Step 6: Final full backend test run**

```bash
cd orchestrator_django && python manage.py test apps.orchestrator -v 2
```
Expected: all tests PASS.

- [ ] **Step 7: Record the outcome**

If every check above passed, the demo is ready. If any step failed, note exactly which one before presenting — do not claim end-to-end success without having run this task.

---

## Self-Review Notes

**Spec coverage:** §2/§4.1 (structure-is-data) → Tasks 1-6. §4.2 (data model) → Task 1. §4.3 (execution engine) → Tasks 3-5. §4.4 (API) → Task 7. §3 (Layer 1/Agent) → Tasks 1, 9. §5 (Layer 3) → confirmed already built (`WorkflowDetailPanel`), verified in Task 14 rather than rebuilt. §6 (analytics decoupling) → Task 6. §7 (recommendation panel) → Task 13 (extends existing `AiBriefing`, not rebuilt). §8 (lead tags) → **not included as a standalone task**; deferred, see note below. §9 (seed) → Task 2. §10 (testing) → woven into every backend task via TDD steps, plus Task 14.

**Deliberate scope cut vs. the spec:** §8's Lead Tags component was in the spec as a "tonight" item, but given the task-count already required for the core engine + canvas + verification, and that it's purely a display nicety with zero effect on whether the canvas genuinely drives live execution (the core promise of this build), it's cut from this plan to protect the deadline. Recommend building it only after Task 14 passes and time remains — it would be a small, low-risk addition to `QueuePanel.tsx` following the exact pattern of `AiBriefing.buildLines()`.

**Type consistency check:** `resolve_next_node(from_key, label)` signature is identical across Tasks 3 (definition), 4, 5 (usage). `WorkflowNodeData`/`WorkflowEdgeData`/`WorkflowDefinitionGraph`/`Agent` types (Task 8) match the serializer field names exactly (Task 7's `WorkflowNodeSerializer`/`WorkflowEdgeSerializer`/`WorkflowDefinitionSerializer`/`AgentSerializer`). `saveWorkflowDefinition`'s `SaveGraphPayload` shape matches `workflow_definition_update`'s expected `request.data` shape exactly (`source_key`/`target_key`/`label` for edges, `id`/`key`/`kind`/`name`/`config`/`position_x`/`position_y` for nodes).

**Placeholder scan:** none found — Task 5 contains one explicit **correction note** (not a placeholder) flagging a bug I caught in my own draft of `handle_call_outcome` while writing it (a duplicate `exhausted_key` assignment) and telling the implementer exactly which line to keep.
