# AI Orchestrator V2 — Design Spec

**Status:** Draft, pending validation
**Author:** Claude (brainstorming session with Pranav, refined against ChatGPT product-vision feedback)
**Date:** 2026-07-10

## 1. Positioning

This is not a Workflow Builder. It's an **AI Agent Orchestration Platform**. The
customer should think "I am connecting AI Agents," not "I am building a state
machine." The workflow graph from the original design (§Layer 2 below) still exists
and still does all the real work — it's now positioned as the *implementation
detail* of an Agent, not the product's front door.

The engine underneath does not change. `WorkflowDefinition` / `WorkflowNode` /
`WorkflowEdge` / `WorkflowInstance`, "structure is data, algorithms stay code," and
React Flow all stand as designed. What changes is the framing wrapped around them and
one new lightweight model (`Agent`, §3) that gives Layer 1 something to click into.

**Hard deadline unchanged:** working demo tomorrow morning, Django + SQLite. Postgres
+ Redis + Celery is a later, separate build.

## 2. Three Layers

```
Layer 1 — AI Agent Canvas     (business capabilities: Agents, Triggers, Integrations,
                                AI, Routing, Utilities, Outputs)
              ↓ click an Agent
Layer 2 — Agent Workflow       (the WorkflowDefinition graph that IS that agent —
                                exactly the engine already designed)
              ↓ click a running instance
Layer 3 — Runtime Explorer     (one execution: timeline, events, attempts, transcript
                                when available)
```

**Never mix these.** Layer 1/2 is *definition* (what could happen). Layer 3 is
*runtime* (what did happen, for one lead). This is the same distinction the existing
code already respects — `WorkflowDefinition`/`WorkflowNode`/`WorkflowEdge` are
definition; `WorkflowInstance`/`WorkflowHistory`/`WorkflowAttempt` are runtime — the
new layering just gives each side its own dedicated screen instead of one page trying
to show both.

### Domain-agnostic principle (non-negotiable)

Nothing in the engine or the Layer 1 palette may name a domain ("Insurance",
"Service", "Healthcare"). An **Agent is a configuration**, not a node type:

```
Bot → Configuration → Insurance    (today)
Bot → Configuration → Healthcare   (tomorrow, zero new nodes/code)
```

Concretely: `Agent.name` = "Sales Agent" / "Service Agent" / whatever the customer
calls it; `Agent.department` (free text) drives dashboard grouping and nothing else.
The node kinds available on the canvas (§4) are the same regardless of which Agent
you're editing.

## 3. Layer 1 — AI Agent Canvas

New, small model wrapping the existing `WorkflowDefinition`:

```python
class Agent(models.Model):
    name = models.CharField(max_length=128)          # "Sales Agent", "Service Agent", "QA Agent"...
    department = models.CharField(max_length=64, blank=True, default="")  # display grouping only, never branches code
    icon = models.CharField(max_length=32, blank=True, default="")        # e.g. an emoji or icon key for the card
    active_definition = models.ForeignKey(
        "WorkflowDefinition", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
```

Layer 1's canvas shows Agent cards (not a graph you draw edges on — that's Layer 2).
Clicking a card opens that Agent's `active_definition` in the Layer 2 React Flow
editor. Creating a new Agent creates an empty (or cloned-from-template)
`WorkflowDefinition` and points `active_definition` at it.

The palette categories from the product brief become the **display grouping** for
Layer 2's node picker (§4), not new backend concepts:

| Category | Maps to engine `kind` (§4) | Tonight | Later |
|---|---|---|---|
| Triggers | `trigger` | Lead Received | Webhook, Schedule, CRM Event |
| Integrations | `webhook` | Chat360 voice dispatch, WhatsApp send | CRM, SMS, Email, generic REST, DB |
| Routing | `logic` (branching) | DND check | Switch, Intent Router, Load Balancer |
| Utilities | `logic`/`wait` | Retry/backoff | Business Hours, Rate Limiter, Timer, Variable |
| Outputs | `outcome` | Completed/Failed + named analytics variables | CRM Update, structured notifications |
| AI | *(new, stub only)* | not built | Intent Detection, Sentiment, Hallucination Detection, Summary, Classification — each needs real model/LLM integration, out of scope tonight |
| AI Agents (as a callable node) | *(new, stub only)* | not built | one Agent invoking another (e.g. Sales Agent handing off to QA Agent mid-flow) |

The "AI" and "AI Agents" rows are listed in the palette for product completeness (so
the canvas *looks* like the target platform) but their nodes are disabled/"coming
soon" tonight — wiring a fake button is fine, wiring fake sentiment analysis is not.

## 4. Layer 2 — Agent Workflow (the execution engine)

This is the original technical design, unchanged, now scoped as "what's inside one
Agent" rather than "the product."

### 4.1 Architecture Principle: Structure Is Data, Algorithms Stay Code

`workflow_service.py`/`decision_engine.py` is real, tested logic currently handling
live leads (retry/backoff timing, DND suppression, WhatsApp fallback, Chat360 webhook
correlation, callback scheduling). Rewriting it as a generic rules engine overnight is
not an acceptable risk.

Instead:
- `WorkflowState` (today a hardcoded Python enum) becomes rows in a `WorkflowNode`
  table: key, kind, name, config, canvas position.
- `VALID_TRANSITIONS` (today a hardcoded dict) becomes rows in a `WorkflowEdge` table:
  source node, target node, label.
- Where Python code today transitions directly to a named state (e.g.
  `classify_connected_outcome` returning `WorkflowState.HOT_LEAD`), it instead returns
  a **label** (e.g. `"hot_lead"`). A resolver, `resolve_next_node(from_key, label)`,
  looks up the matching `WorkflowEdge` and returns the real target node key.
  `workflow_service.transition()` validates against `WorkflowEdge` rows instead of the
  hardcoded dict.

This makes editing the canvas **genuinely live**: renaming/repositioning nodes,
rewiring which label routes where, changing a webhook URL, or deleting an edge (e.g.
disabling the WhatsApp fallback branch) changes real routing on the next scheduler
tick or webhook — no redeploy. What stays code is the *decision* (which label to
return), never the *map* (where a label leads).

**Hard constraint on the seed data:** the default Agent's node keys must be
byte-identical to today's `WorkflowState` string values (`"WAITING"`, `"CALLING"`,
`"HOT_LEAD"`, etc.). Every read path that compares against these strings today —
`briefing_stats`, serializers, `RailControls`, the dashboard's `lib/types.ts`
`WorkflowState` union — keeps working unchanged. `WorkflowState` the Python enum is
**not deleted**; it remains the canonical list of default keys used by the seed
command, but stops being the transition-validation source of truth.

### 4.2 Data Model

```python
class WorkflowDefinition(models.Model):
    name = models.CharField(max_length=128)
    scope = models.CharField(max_length=128, blank=True, default="default")  # reserved for future multi-tenant use
    is_active = models.BooleanField(default=False)  # exactly one active definition per Agent drives live execution
    version = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class WorkflowNode(models.Model):
    class Kind(models.TextChoices):
        TRIGGER = "trigger"
        WEBHOOK = "webhook"   # "Integrations" in the Layer 1 palette
        LOGIC = "logic"       # "Routing" / "Utilities" in the Layer 1 palette
        WAIT = "wait"         # "Utilities" in the Layer 1 palette
        OUTCOME = "outcome"   # "Outputs" in the Layer 1 palette

    definition = models.ForeignKey(WorkflowDefinition, on_delete=models.CASCADE, related_name="nodes")
    key = models.CharField(max_length=64)          # stable slug, e.g. "WAITING" — replaces WorkflowState choices
    kind = models.CharField(max_length=16, choices=Kind.choices)
    name = models.CharField(max_length=128)         # display label
    config = models.JSONField(default=dict, blank=True)
    position_x = models.FloatField(default=0)
    position_y = models.FloatField(default=0)

    class Meta:
        unique_together = [("definition", "key")]


class WorkflowEdge(models.Model):
    definition = models.ForeignKey(WorkflowDefinition, on_delete=models.CASCADE, related_name="edges")
    source_node = models.ForeignKey(WorkflowNode, on_delete=models.CASCADE, related_name="outgoing_edges")
    target_node = models.ForeignKey(WorkflowNode, on_delete=models.CASCADE, related_name="incoming_edges")
    label = models.CharField(max_length=64, blank=True, default="")  # "" for single-path; a decision label otherwise

    class Meta:
        unique_together = [("source_node", "label")]
```

`WorkflowInstance.state` stays a plain `CharField(max_length=64)` — the `choices=`
constraint tying it to the `WorkflowState` enum is dropped, default remains
`"WAITING"`.

### `config` shape per kind
- **trigger**: `{}` (Lead Received has no configurable inbound URL yet).
- **webhook**: `{"url": "<override or empty>"}`. Empty falls back to the existing
  Django setting (`CHAT360_OUTBOUND_URL` for Dispatching, Chat360 task API settings
  for WhatsApp send) — nothing breaks if left unconfigured, but setting a URL here
  takes effect immediately.
- **logic**: `{"logic_ref": "dnd_check"}` — a key into a small fixed Python registry
  (`LOGIC_REGISTRY` in `workflow_service.py`), never free text executed as code.
  Today's registry: `dnd_check` → `is_suppressed_dnc`; `qa_review` (audit-only
  checkpoint, no branching).
- **wait**: `{"backoff_minutes": [1, 5, 15]}` for `RETRY_PENDING`-shaped nodes; `{}`
  for plain waits.
- **outcome**: `{"variables": [{"key": "test_drives", "label": "Test Drives",
  "match_keywords": ["test ride", "test drive"]}, ...]}`. Generalizes today's
  hardcoded `is_test_drive_interest`/`is_showroom_visit_interest` checks into data.

### 4.3 Execution Engine Changes

**`workflow_service.py`:**
- `transition(workflow, to_key, event, payload)`: validates via `WorkflowEdge` lookup
  instead of the `VALID_TRANSITIONS` dict. Same signature, same callers.
- New: `resolve_next_node(from_key, label) -> str | None`. Returns the target key, or
  `None` if no matching edge exists.
- `record_dnd_check`: unchanged decision logic, but the suppress-branch now goes
  through `resolve_next_node("WAITING", "dnd_suppressed")`. Stays a same-transaction
  checkpoint (not a resting state), exactly as today — scheduler's polling set is
  unaffected.

**`decision_engine.py`:** every decided (non-single-path) transition computes a
**label** first, then resolves it:
- `handle_call_outcome`: dispatcher outcomes → labels `"connected"`, `"unanswered"`,
  `"not_connected"`; retry-vs-exhausted (unchanged `attempt_count < MAX_RETRIES`
  check, backoff minutes now read from the `WAIT` node's config) → `"retry"` /
  `"exhausted"`.
- `classify_connected_outcome`: returns `"hot_lead"` / `"completed"` (`"voicemail"`/
  `"other_inquiry"`/`"failed"` reserved and pre-wired as edges, unchanged
  placeholder status).
- `handle_whatsapp_outcome`: `"responded"` / `"no_response"`.

**Unrouted transitions:** if `resolve_next_node` returns `None` (e.g. an edge was
deleted on canvas), never raise into a webhook handler — write a `WorkflowHistory`
event `unrouted_transition`, leave the instance parked, return normally. Same "always
ack 200" pattern as `chat360_call_result_webhook`. Add a parked-instance count to
`briefing_stats` so this is visible, not silent.

**`scheduler.py`:** no structural change — still polls `state__in=[WAITING,
CALLBACK_PENDING]` (stable keys, guaranteed by the seed) and calls into
`workflow_service`/`decision_engine`, which now consult the graph internally.

### 4.4 API (DRF)
- `GET /api/agents/` — list Agent cards for Layer 1.
- `GET /api/agents/<id>/definition/` — the Agent's active definition, nested
  nodes+edges (Layer 2 canvas load).
- `PUT /api/workflow-definitions/<id>/` — replaces nodes/edges/positions in one
  transaction (canvas "Save"). Validates unique keys, edges reference real nodes;
  unreachable-node detection is a warning, not a hard block, for tonight.
- `POST /api/workflow-definitions/<id>/activate/` — flips `is_active` for this
  Agent's definitions (canvas "Publish"). Effective on the next scheduler tick /
  webhook — no restart.
- `GET /api/workflows/<id>/` (exists today) — becomes the Layer 3 Runtime Explorer's
  data source: nested `attempts` + `history`, unchanged shape.

Existing endpoints (`workflows/`, `campaigns/`, `briefing/stats/`,
`webhooks/chat360/call-result/`) keep their shape; only internals consult the graph.

## 5. Layer 3 — Runtime Explorer

Clicking a running `WorkflowInstance` (from the live-token overlay or a leads list)
opens a detail view built from data that **already exists today**:
`WorkflowInstanceSerializer`'s nested `attempts` (channel, status, timestamps,
response code) and `history` (every event + payload, in order). This becomes a
proper timeline UI instead of raw JSON.

**Available tonight:** customer/lead reference, full event timeline, call attempts,
retry count, response codes, DND/QA checkpoint markers (from `WorkflowHistory`
events), unrouted-transition alerts if any.

**Not available tonight (no data captured yet):** transcript, sentiment score,
hallucination flag, bot latency. These require real integrations (Deepgram/STT
already exists in `transcription/engine.py` for the *intelligence* plane, but is not
wired into the *orchestrator* plane's call flow) — flagged as future work, not
faked with placeholder numbers.

## 6. Analytics — Decoupled From Node Type

Analytics must not be hardcoded to a specific node kind. The mechanism: any node can
tag a `WorkflowHistory` event it writes with an `analytics_key` (already-existing
JSONField payload, just a documented convention, e.g. `{"analytics_key":
"test_drives"}`); a generalized `briefing_stats` reads the active definition's
declared analytics keys (from `outcome`-kind node `config.variables`, §4.2) and
aggregates matching `WorkflowHistory`/`Chat360WebhookLog` rows into `{key: count}`.
This is the same mechanism already spec'd in §4.2's `outcome` config — reframed here
explicitly as "workflow emits events, a separate aggregator counts them," so adding a
new analytics variable later never means inventing a new node kind.

Example flow: `Appointment Booked` event emitted by whichever node produced it →
counted by the analytics aggregator → shown on the dashboard. The workflow graph
never needs to know the dashboard exists.

## 7. AI Recommendation Panel

Replaces a plain "Recent Activity" list. Computed entirely from data `briefing_stats`
already returns (or will return per §6) — no new backend risk, this is a frontend
transform tonight:

- 🔥 N Hot Leads detected — from `hot_leads` count (existing field).
- ☎ N callbacks due — from `callback_due` (existing field).
- ⚠ N conversations require QA review — from the `qa_review` checkpoint count
  (existing field), or specifically ones flagged `bot_failures`.
- 🚗 N Test Drive opportunities — from the `test_drives` analytics variable (§6).
- ⚠ N unrouted transitions — new, from §4.3's error-handling addition.

Sentiment/CSAT-trend/STT-confidence recommendations are listed in the product vision
but require data this build doesn't capture (§5) — not built tonight, panel is
designed to add new recommendation rows without a layout change later.

## 8. Lead Tags

Tags travel with the **lead** (`CampaignLead`), not the workflow node — computed, not
a new persisted field tonight, from signals that already exist:
`workflow.state == "HOT_LEAD"` → 🔥 Hot Lead; matched `outcome.variables` keyword
(§4.2) → 🚗 Test Drive / 🏢 Showroom Visit; `state == "CALLBACK_PENDING"` → 📞
Callback Requested; `dnd_flag` at intake → excluded from dispatch entirely (already
true today, no tag needed since these leads never appear in active lists). Rendered
as chips on the leads list and on Layer 3's Runtime Explorer header.

## 9. Migration / Seed

A management command `seed_default_workflow` creates:
- One `Agent(name="Sales Agent", department="Sales")`.
- One `WorkflowDefinition(name="Lead Dispatch (default)", scope="default",
  is_active=True)`, pointed to by that Agent's `active_definition`.
- One `WorkflowNode` per `WorkflowState` enum value, `key` = the exact enum string,
  `kind` per §4.2 (`WAITING`/`RETRY_PENDING`/`CALLBACK_PENDING` = `wait`;
  `DISPATCHING` and `WHATSAPP_PENDING` = `webhook`, since both trigger a real
  outbound call today (`dispatcher.dispatch_call`/`dispatch_whatsapp`);
  `COMPLETED`/`VOICEMAIL`/`OTHER_INQUIRY`/`FAILED`/`HOT_LEAD` = `outcome`; everything
  else = plain pass-through), positions taken directly from `LiveRail.tsx`'s existing
  `STATIONS`/`CHECKPOINTS` coordinates.
- One `WorkflowEdge` per entry in today's `VALID_TRANSITIONS` dict, labeled per §4.3.
- A `DND_CHECK` and `QA_REVIEW` `logic`-kind node each, wired as same-transaction
  checkpoints (not part of the scheduler's resting-state set).

**Deliberately not fabricated:** the richer example graphs in the product brief
("Lead Validation", "Business Hours", "CRM Update", "Feedback Collection", a separate
QA Agent with transcript/sentiment/hallucination nodes) are illustrative of where the
palette is headed, not tonight's seed. Tonight's seed is byte-for-byte today's real,
working pipeline, wrapped as "Sales Agent" — inventing nodes with no backing logic
would make the demo lie about what's real. New palette categories (§3 table) are
visually present and clickable-to-disabled where their backing logic doesn't exist
yet, rather than silently omitted or faked.

This command is idempotent — the only way the demo environment gets its starting
graph.

## 10. Testing

Smoke-level, given the timeline:
- Existing `tests.py` (`CampaignDndLaunchTests`, `CallbackSchedulingTests`,
  `RelativeCallBackTimeTests`, `CallbackDedupTests`) must keep passing unmodified in
  behavior — `setUp` ensures `seed_default_workflow` has run so `transition()` has a
  real graph to validate against.
- New: full happy path (create → DND pass → dispatch → connected → completed)
  asserting the same state sequence as today.
- New: retry-exhaustion path (3x not-connected → WhatsApp fallback → responded)
  asserting the same sequence as today.
- New: `resolve_next_node` returns `None` for a deliberately-missing edge, caller
  records `unrouted_transition` instead of raising.
- Manual: seed → Layer 1 shows one "Sales Agent" card → click in → Layer 2 renders
  the full existing pipeline → edit the Dispatching node's webhook URL → confirm a
  real dispatch call uses it → publish → confirm a live lead still flows through →
  click a running instance → Layer 3 shows its real timeline.

## 11. Tonight vs. Later

**Tonight (demo):**
- Django + SQLite.
- `Agent` / `WorkflowDefinition` / `WorkflowNode` / `WorkflowEdge` models + migration.
- `workflow_service`/`decision_engine` refactor to label + `resolve_next_node`.
- `seed_default_workflow` management command (§9).
- API endpoints (§4.4).
- Layer 1: Agent card list (one card, "Sales Agent") + domain-agnostic palette
  categories (some entries disabled/"coming soon").
- Layer 2: React Flow canvas — palette, config panel, save/publish, live token
  overlay (reusing `RailToken`, positioned by real node coordinates).
- Layer 3: Runtime Explorer built from existing `attempts`/`history` data.
- Analytics as decoupled events (§6) powering the existing KPI cards.
- Recommendation panel (§7) and Lead Tags (§8) — frontend transforms of existing data.
- Smoke tests per §10.

**Later (not part of this build):**
- Postgres; Celery + Redis replacing the manual `scheduler.tick()` loop (already
  anticipated in `scheduler.py`'s own docstring); realtime canvas updates
  (Channels + Redis) replacing 5s polling.
- Real AI capabilities: Intent Detection, Sentiment Analysis, Hallucination
  Detection, Summary, Classification — each needs a real model/LLM integration
  decision, not a stub.
- "AI Agents" as callable nodes (one Agent invoking another) — needs an execution
  semantics decision (sync hand-off vs. async event) not made yet.
- Multi-tenant Agent library beyond the single seeded Agent; new Integrations
  (CRM, SMS, Email, generic REST, Knowledge Base); real DND/NDNC registry; real
  `classify_connected_outcome` rule; Showroom Visit/Price Quotation WhatsApp
  templates — all pre-existing TODOs, unaffected by this change.
- Persisted Lead Tags (currently computed on read, not stored).

## 12. Product Positioning

Not "Workflow Builder." **AI Agent Orchestration Platform** (or "AI Orchestration
Studio"). The workflow graph (Layer 2) is one capability of the platform, not the
product's identity — the platform orchestrates Agents, Integrations, Routing,
Communication, QA, and Analytics across any industry, with domain differences living
entirely in configuration (§2), never in code.
