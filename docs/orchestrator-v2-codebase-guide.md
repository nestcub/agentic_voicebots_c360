# Orchestrator + Dashboard: Codebase Guide

A working reference for the REAL, current backend (`orchestrator_django/`) and frontend
(`dashboard/`), including the new "AI Orchestrator V2" configurable-workflow layer built
on branch `feat/orch-v2`. Written after hands-on verification this session — every claim
here was checked against actual running code, not assumed from other docs.

**Beware stale docs:** the root `README.md` describes a different, older orchestrator
(`orchestrator/`, FastAPI, Neon Postgres, "no SQLite"). That plane exists in the repo but
is **not** what powers the live dashboard today. `orchestrator_django/` (Django + DRF +
SQLite) is the real one — confirmed by tracing the dashboard's actual API calls and by
`dashboard/lib/types.ts`'s own comment (`Orchestrator workflow state machine (Django
orchestrator_django/)`). If a doc contradicts what's in this guide, trust this guide or
re-verify against the code — don't trust the doc.

---

## 1. Quick start

### Start everything

```bash
# Terminal 1 — Django backend (port 8010)
cd orchestrator_django
../venv/bin/python manage.py migrate            # apply any pending migrations
../venv/bin/python manage.py seed_default_workflow   # idempotent — creates/updates "Sales Agent"
../venv/bin/python manage.py runserver 8010

# Terminal 2 — Next.js dashboard (port 3000)
cd dashboard
echo "NEXT_PUBLIC_DJANGO_ORCH_API_URL=http://localhost:8010" > .env.local   # one-time
npm run dev
```

Then open `http://localhost:3000/orchestrator/workflows` (the main live dashboard) or
`http://localhost:3000/orchestrator/agents` (the new Agent canvas, V2).

**Note:** this repo's venv python is at `venv/bin/python`, not the bare `python`/`python3`
on PATH — always invoke it explicitly (`../venv/bin/python` from `orchestrator_django/`,
or `./venv/bin/python` from repo root).

### Run the scheduler manually (there's no background worker running by default)

The scheduler is a plain Python function, not a daemon — nothing dispatches queued leads
until you call it. For a demo/dev loop:

```bash
cd orchestrator_django
../venv/bin/python manage.py shell -c "
from apps.orchestrator.services import scheduler
print('processed:', scheduler.tick())
"
```

Run that repeatedly (a shell `while true; do ...; sleep 5; done` loop works fine for a
demo) — each call picks up any `WAITING`/`CALLBACK_PENDING` lead whose `next_execution`
has passed and pushes it one step through dispatch.

### Run the backend test suite

```bash
cd orchestrator_django
../venv/bin/python manage.py test apps.orchestrator -v 2
```

41 tests as of this session, all passing. `-v 2` gives per-test names; drop it for just
the summary line.

### Type-check the frontend

```bash
cd dashboard
npx tsc --noEmit
```

No Jest/Vitest exists in this project — this is the only "test" for the frontend today.

---

## 2. Inspecting the database

The DB is `orchestrator_django/db.sqlite3` — plain file, easy to poke at directly.

```bash
cd orchestrator_django
../venv/bin/python manage.py dbshell     # easiest — uses Django's own config
```

Then standard SQLite dot-commands:

```sql
.tables                                  -- list every table
.schema orchestrator_workflownode        -- see a table's columns
SELECT key, kind, config FROM orchestrator_workflownode WHERE definition_id=1;
SELECT lead_id, state, attempt_count FROM orchestrator_workflowinstance ORDER BY id DESC LIMIT 10;
SELECT event, payload FROM orchestrator_workflowhistory WHERE workflow_id=<id> ORDER BY timestamp;
```

Other ways in:
- **Direct CLI:** `sqlite3 orchestrator_django/db.sqlite3` (same dot-commands, no Django needed).
- **GUI:** [DB Browser for SQLite](https://sqlitebrowser.org) — open `db.sqlite3`, browse/edit visually.
- **Django admin:** `../venv/bin/python manage.py createsuperuser` once, then visit
  `http://localhost:8010/admin/` while `runserver` is running — every model in this guide
  (including the new `Agent`/`WorkflowDefinition`/`WorkflowNode`/`WorkflowEdge`) is registered.
- **ORM shell:** `manage.py shell` then plain Django ORM (`from apps.orchestrator.models
  import WorkflowInstance; WorkflowInstance.objects.filter(state="CALLING")`).

---

## 3. Backend: `orchestrator_django/`

### 3.1 Layout

```
orchestrator_django/
  orchestrator_django/        Django project (settings.py, urls.py)
  apps/orchestrator/
    models.py                 Every DB table (see below)
    admin.py                  Django admin registrations
    tests.py                  ALL tests live in this one file (292 lines pre-V2, ~700 now)
    services/
      workflow_service.py     Transition core — the "how does a lead move" engine
      decision_engine.py      Retry/backoff/outcome-classification DECISIONS
      scheduler.py            tick() — polls due leads, dispatches them
      dispatcher.py           Actual outbound HTTP calls (Chat360 Voice360 + mocked fallback)
      notifications.py        WhatsApp push-notification sender (separate Chat360 API)
      seed.py                 [V2] builds the default "Sales Agent" graph
    api/
      views.py                Thin @api_view functions — all business logic lives in services/
      serializers.py          DRF serializers
      urls.py                 URL routes, all under /api/
    management/commands/
      seed_default_workflow.py   [V2] `manage.py seed_default_workflow`
```

**Convention baked into this codebase** (referenced in comments as "project CLAUDE.md",
though no such file currently exists in the repo — treat the comments as the source of
truth): views stay thin, business logic lives in `services/`; a single guard
function/table for state validation, not scattered `if` checks.

### 3.2 The data model — two eras, one file

`models.py` has two generations of the same idea living side by side:

**Era 1 (original, still the "state" field's storage):**
- `WorkflowState` — a Python `TextChoices` enum: `LEAD_RECEIVED`, `WAITING`,
  `CALLBACK_PENDING`, `SUPPRESSED_DNC`, `DISPATCHING`, `CALLING`, `CONNECTED`,
  `NOT_CONNECTED`, `UNANSWERED`, `RETRY_PENDING`, `WHATSAPP_PENDING`, `COMPLETED`,
  `VOICEMAIL`, `OTHER_INQUIRY`, `FAILED`, `HOT_LEAD`. **Not deleted** — still the
  canonical list of "what states exist," and every `WorkflowInstance.state` value is
  still literally one of these strings.
- `WorkflowInstance` — one row per lead in the pipeline: `lead_id`, `crm`, `campaign_id`,
  `state` (plain string now, see below), `priority`, `attempt_count`, `next_execution`
  (when the scheduler should next touch it).
- `WorkflowAttempt` — one row per dispatch attempt (voice or whatsapp) on an instance.
- `WorkflowHistory` — append-only audit log: every transition, every checkpoint, as
  `{event, payload, timestamp}`. This is what Layer 3 (Runtime Explorer) reads.
- `CampaignLead` — the one place real PII (phone number) lives, linked 1:1 to a
  `WorkflowInstance`. Everything else in the orchestrator is deliberately CRM-agnostic
  and PII-free.
- `Chat360WebhookLog` — every inbound Chat360 post-call webhook, logged unconditionally.

**Era 2 (V2, this session's build) — makes the STRUCTURE editable:**
- `WorkflowDefinition` — a named, versioned graph. `is_active=True` marks the one that's
  live.
- `WorkflowNode` — one row per station (`key`, `kind` ∈ {trigger, webhook, logic, wait,
  outcome}, `name`, `config` JSON, `position_x/y` for the canvas). **The seeded default
  definition's node keys are byte-identical to the `WorkflowState` enum values** — that's
  not a coincidence, it's how old code (that still compares `state == "WAITING"`) and new
  code (that looks up `WorkflowNode.objects.get(key="WAITING")`) stay in sync.
- `WorkflowEdge` — one row per transition (`source_node`, `target_node`, `label`).
  `label=""` means "the only/default path"; a real label (`"connected"`, `"hot_lead"`,
  `"exhausted"`, ...) means "this is where a *decision* in `decision_engine.py` routes
  to."
- `Agent` — Layer-1 concept, wraps one `WorkflowDefinition` (`active_definition` FK).
  Today there's exactly one: "Sales Agent."

**Why both eras coexist:** rewriting the actual dispatch/retry/DND algorithms to be
"graph-driven" in one night was judged too risky for a system handling real phone calls.
Instead, the *algorithms* stayed as tested Python (Era 1's functions), and the *routing
map* they consult became data (Era 2's tables). See §3.4.

### 3.3 A lead's real journey — trace it yourself

```
POST /api/campaigns/  (api/views.py:campaign_list_create)
  → workflow_service.create_workflow()        WorkflowInstance created, state="WAITING"
  → workflow_service.record_dnd_check()        may transition -> SUPPRESSED_DNC (terminal)

scheduler.tick()   [services/scheduler.py — YOU must call this, nothing calls it automatically]
  → resolve_next_node("WAITING", "") -> "DISPATCHING"   (graph lookup)
  → workflow_service.transition(..., "DISPATCHING", event="scheduler_pickup")
  → resolve_next_node("DISPATCHING", "") -> "CALLING"
  → workflow_service.transition(..., "CALLING", event="dispatch_call_start")
  → dispatcher.dispatch_call(workflow)          REAL HTTP POST if a CampaignLead exists,
                                                 else a random mocked outcome
  → decision_engine.handle_call_outcome(workflow, outcome)
      computes a LABEL ("connected"/"dispatched"/"unanswered"/"not_connected")
      → resolve_next_node(current_key, label) -> next state
      → workflow_service.transition(...)
      (retry loop: NOT_CONNECTED/UNANSWERED -> RETRY_PENDING -> WAITING, up to
       MAX_RETRIES=3, backoff minutes from RETRY_BACKOFF_MINUTES or the RETRY_PENDING
       node's config.backoff_minutes if set)
      (exhausted -> WHATSAPP_PENDING -> dispatcher.dispatch_whatsapp() -> COMPLETED/FAILED)

POST /api/webhooks/chat360/call-result/  (api/views.py:chat360_call_result_webhook)
  → the REAL Chat360 post-call webhook (separate from the mocked path above)
  → same resolve_next_node pattern, classify_connected_outcome() -> label -> graph lookup
  → always returns 200, even on a correlation miss or an "unrouted" edge — see §3.5
```

Run this yourself and watch it happen:

```bash
cd orchestrator_django
../venv/bin/python manage.py shell -c "
from apps.orchestrator.models import WorkflowInstance
w = WorkflowInstance.objects.order_by('-id').first()
print(w.lead_id, w.state)
for h in w.history.all(): print(' -', h.event)
"
```

### 3.4 The "structure is data" mechanism, precisely

Two functions in `workflow_service.py` are the whole trick:

```python
def resolve_next_node(from_key: str, label: str = "") -> str | None:
    """Looks up the active definition's edge from_key --label--> ?, returns target key or None."""

def record_unrouted_transition(workflow, from_state, label) -> None:
    """Called when resolve_next_node returns None. NEVER raises — logs an audit event
    and leaves the lead parked. See briefing_stats' unrouted_count."""
```

Every place that used to write `workflow_service.transition(workflow, WorkflowState.X,
...)` with a hardcoded `X` now instead: (1) decides a *label* in Python (unchanged
business logic), (2) calls `resolve_next_node(current_state, label)` to find the *real*
target from the database, (3) checks for `None` and parks gracefully instead of crashing.

**This means:** editing `WorkflowEdge` rows (via the canvas's Save button, or directly in
the DB/admin) changes where a real lead goes next, with zero code deploy. Try it:

```bash
../venv/bin/python manage.py shell -c "
from apps.orchestrator.models import WorkflowDefinition, WorkflowEdge
d = WorkflowDefinition.objects.get(is_active=True)
e = WorkflowEdge.objects.get(definition=d, source_node__key='RETRY_PENDING', label='retry')
print('currently routes retries to:', e.target_node.key)
"
```

**What this mechanism does NOT cover (a known, real gap found during this session's E2E
test):** `WorkflowNode.config.url` on the `DISPATCHING`/`WHATSAPP_PENDING` webhook nodes
is meant to override which URL gets called — but `dispatcher.py`/`notifications.py`
still hardcode `settings.CHAT360_OUTBOUND_URL`/`settings.CHAT360_TASK_API_URL` and never
read the node config. Editing a webhook node's URL on the canvas persists correctly but
has **no runtime effect** yet. If you pick this up: the fix is contained to
`dispatcher.py::_dispatch_real_call` and `notifications.py::_send_whatsapp_task`, each
needs a `WorkflowNode.objects.filter(definition__is_active=True, key=<the node's
key>).first()` lookup with a `config.get("url")` fallback to the existing setting.

### 3.5 Error handling philosophy

External webhooks (`chat360_call_result_webhook`) **always return HTTP 200**, even when:
- The lead can't be correlated (logged to `Chat360WebhookLog` regardless, matched or not).
- A resolved label has no edge (`record_unrouted_transition`, lead parked, visible via
  `briefing_stats.unrouted_count`).

This is deliberate — Chat360 retries aggressively on non-200 responses, so a genuine
correlation miss or a mis-configured graph should never trigger a retry storm.

### 3.6 The two "briefing" concepts

- `GET /api/workflows/` — raw list of `WorkflowInstance` rows, what the live rail/queue
  polls every 2.5s (`dashboard/lib/hooks/useWorkflowFeed.ts`).
- `GET /api/briefing/stats/` — aggregated counts (`hot_leads`, `callback_due`,
  `dnd_check`, `qa_review`, `analytics: {test_drives, showroom_visits, ...}` — this last
  one is config-driven off the `COMPLETED` node's `config.variables`, not hardcoded —
  and `unrouted_count`). Polled every 5s, powers `BriefingKpiRow`/`AiBriefing`.

---

## 4. Frontend: `dashboard/`

Next.js 16 (App Router) + React 19 + Tailwind 4. No test runner. No auth (single-tenant
demo). `NEXT_PUBLIC_DJANGO_ORCH_API_URL` env var points it at the Django backend
(defaults to `http://localhost:8010` if unset).

### 4.1 Layout

```
dashboard/
  lib/
    types.ts                        Every shared TS type — the contract with the backend
    domainConfig.ts                 White-label vocabulary (brand name, status labels)
    sources/orchestratorDjangoSource.ts   Every fetch() call to the Django API lives here
    hooks/useWorkflowFeed.ts        Polls /api/workflows/ every 2.5s
    hooks/useActivityFeed.ts        Derives a "recent activity" feed from the workflow list
  components/orchestrator/
    LiveRail.tsx                    The ORIGINAL hardcoded SVG rail (still used today)
    RailToken.tsx                   Animated pill for one lead; STATE_COLORS map lives here
    RailControls.tsx                OEM/Department/Process selectors + rail-vs-map toggle
    WorkflowDetailPanel.tsx         Layer-3-equivalent: Stepper + Timeline/Details/Actions tabs
    AiBriefing.tsx                  Rule-based recommendation lines from BriefingStats
    canvas/                         [V2] WorkflowNodeCard, NodePalette, NodeConfigPanel
  app/orchestrator/
    workflows/page.tsx              THE main live dashboard (rail + queue + KPIs + briefing)
    agents/page.tsx                 [V2] Layer 1 — Agent card list
    agents/[id]/page.tsx            [V2] Layer 2 — the React Flow canvas
```

### 4.2 Data flow pattern (applies everywhere)

`lib/types.ts` defines a TS interface matching a DRF serializer's output exactly →
`lib/sources/orchestratorDjangoSource.ts` has one `fetchX()`/`saveX()` function per
endpoint, all following the same shape (throw on `!res.ok`, `cache: "no-store"` on
GETs) → a page or hook calls it, usually on a `setInterval` poll (no websockets
anywhere yet).

### 4.3 The V2 canvas specifically

`app/orchestrator/agents/[id]/page.tsx` is the interesting one — built across 3 waves
this session, worth reading in one sitting to see how it fits together:
1. **Render** — `fetchAgentDefinition()` → `@xyflow/react`'s `<ReactFlow>` with custom
   `WorkflowNodeCard` node renderer (colored by `STATE_COLORS`, reused from the old rail)
   and a `NodePalette` sidebar.
2. **Edit** — click a node → `NodeConfigPanel` opens → `handleSave()` builds a
   `{nodes, edges}` payload (edges keyed by `source_key`/`target_key`, NOT the GET
   response's `source_node_id`/`target_node_id` — this asymmetry is real, see the
   comment in `views.py::workflow_definition_update`) → `PUT
   /api/workflow-definitions/<id>/` → `handlePublish()` → `POST .../activate/`.
3. **Live overlay** — `useWorkflowFeed()` (the same hook the old rail uses) + a raw SVG
   layer positioning `RailToken` pills at each node's `(position_x, position_y)`. Known
   limitation: this overlay doesn't track React Flow's pan/zoom transform, so panning
   the canvas desyncs the tokens from the nodes visually — acceptable for a first pass,
   flagged, not fixed.

A TypeScript quirk worth knowing if you touch this file: `WorkflowNodeData` (our type)
has no index signature, so it isn't directly assignable to React Flow's `Node.data:
Record<string, unknown>` constraint. The fix used throughout is a boundary cast
(`as unknown as Node[]` / `as unknown as WorkflowNodeData`) — this is a known, deliberate
pattern in this file, not a mistake to "clean up."

---

## 5. Known gaps (as of this session, branch `feat/orch-v2`)

1. **Webhook URL override not wired** (§3.4) — the biggest one. Structure/routing edits
   are live; the specific "change which URL a webhook node calls" promise isn't yet.
2. **Canvas live-overlay doesn't track pan/zoom** (§4.3) — cosmetic, not correctness.
3. **`dashboard/components/orchestrator/BriefingKpiRow.tsx`** excludes `analytics`/
   `unrouted_count` from its rendered-tile key union (a required, correct TS fix — see
   `.superpowers/sdd/progress.md` for why) but nothing yet displays those two fields as
   their own KPI tiles; they're only surfaced via `AiBriefing`'s text lines today.
4. **`notifications.py`'s `is_test_drive_interest`/`is_showroom_visit_interest`** are now
   dead code — `briefing_stats` reads the same matching logic generically off
   `WorkflowNode.config.variables` instead. Not removed, just unused.
5. Nothing runs the scheduler automatically — see §1's manual-tick note. Production plan
   is Celery Beat + Redis (referenced in `scheduler.py`'s own docstring, not built yet).

Full build history, every task's review findings, and every deliberate design decision:
`.superpowers/sdd/progress.md` (ledger) and `docs/superpowers/plans/2026-07-10-ai-orchestrator-v2.md`
(the full implementation plan, with exact code for everything built).
