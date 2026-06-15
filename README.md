# Chat360 Intelligence Fabric

An AI system that **designs production-grade Chat360 voice bots** from real call recordings, and an
**orchestrator** that runs the resulting outbound operation — dispatching calls, guaranteeing follow-ups,
and adapting to goal changes — with a live **dashboard** for visibility.

One mono-repo, **three planes**, one database. Each plane owns one job and talks to the others only
through durable stores and typed interfaces; any plane can be swapped or productized independently.

| Plane | Job | Stack | Entry |
|---|---|---|---|
| **Intelligence** | Calls → insights → voice-bot plans | Python, Anthropic, pgvector RAG | [intelligence/](intelligence/), [transcription/](transcription/) |
| **Orchestrator** | Run the outbound op (dispatch, follow-ups, goals, CRM) | Python, FastAPI, APScheduler | [orchestrator/](orchestrator/) |
| **Dashboard** | Real-time visibility & reporting | Next.js 16, Tailwind v4 | [dashboard/](dashboard/) |

**Single store: Neon Postgres + pgvector.** Intelligence tables are typed + vector-indexed.
Orchestrator tables live in a generic `orch_kv (tbl, id, data JSONB)` table on the same instance.
No SQLite, no Supabase.

---

## Architecture

```
┌─ INTELLIGENCE PLANE ─ Python ─ :8001 ─────────────────────────────────────────┐
│  audio → Sarvam STT (diarized segments)                                         │
│        → chunk_segments → embed → transcript_chunks  ← per-client call-RAG     │
│        → LLM insight extraction → insights (agent_score, sentiment,             │
│            objection_patterns, kb_gaps, bot_failure_modes, suggested_fixes)     │
│                                                                                  │
│  generate_plan / converse / apply_patch  ← intelligence/designer.py             │
│    prompt layers:                                                                │
│      CACHE  — platform knowledge (always-on rules + Adani pitfalls)             │
│      RAG    — top-8 bot examples + reference_system_prompt/reference_intent     │
│      RAG    — top-5 verbatim call moments for THIS client                       │
│      DUMP   — per-client aggregated insights + bot_failure_modes                │
│                                                                                  │
│  Neon tables: transcripts, insights, plans, plan_patches, workflow_sessions,    │
│    conversation_turns, platform_knowledge, bot_examples, transcript_chunks      │
│  All embeddings: pgvector HNSW, cosine, EMBEDDING_DIM=768 (Gemini default)     │
│                                                                                  │
│  FastAPI — intelligence/api.py                                                   │
│    /transcribe  /converse  /plans  /knowledge  (x-api-key auth)                 │
└─────────────────────────────────────────────────────────────────────────────────┘
                │
                │  Goal/Target read/write via Orchestrator API (no direct DB link)
                ▼
┌─ ORCHESTRATOR PLANE ─ Python / FastAPI ─ :8000 ───────────────────────────────┐
│  Deterministic engines — no LLM, plain Python over Store protocol:              │
│                                                                                  │
│   Dispatch        — pull/prioritize leads, DID pool, confirm gate               │
│   FollowupEngine  — Commitment Ledger: durable row per promised follow-up,      │
│                     closed ONLY by terminal state (never by elapsed time)       │
│                     retry/backoff (FOLLOWUP_BACKOFF_HOURS), max → exhausted     │
│   GoalAdaptation  — on goal flip: split capacity between new-goal outreach      │
│                     and honoring prior commitments (FOLLOWUP_CAPACITY_RESERVE)  │
│                                                                                  │
│  Adapters:                                                                       │
│   VoiceDispatch — Chat360VoiceDispatcher (real) | SimulationVoiceDispatcher    │
│   CRM           — RestCRMAdapter (httpx generic) | StoreCRMAdapter (test)      │
│                                                                                  │
│  Store: PostgresStore (Neon orch_kv) | MemoryStore (in-process tests only)     │
│  Tables: accounts, goals, targets, leads, assignments, commitments,             │
│          call_outcomes, rollups, crm_connections  (all as JSONB rows in orch_kv)│
│                                                                                  │
│  Scheduler: APScheduler polls due commitments every SCHEDULER_INTERVAL_SEC     │
│                                                                                  │
│  Routes (21 total):                                                              │
│    GET  /orchestrator/accounts|kpis|targets/progress|leads|commitments          │
│    GET  /orchestrator/call-outcomes|report|goal                                  │
│    POST /orchestrator/goal                                                       │
│    GET|POST /orchestrator/crm/connections                                        │
│    POST /orchestrator/crm/connections/{id}/test                                  │
│    POST /orchestrator/dispatch|confirm-dispatch                                  │
│    POST /orchestrator/webhook/chat360/outcome                                    │
└──────────────────────────────┬────────────────┬───────────────────────────────┘
   Chat360VoiceDispatcher       │                │ POST /webhook/chat360/outcome
   → POST CHAT360_OUTBOUND_URL  │                │
                                ▼                ▼
                   ┌────────────────────────────────────────┐
                   │  DASHBOARD ─ Next.js ─ :3000           │
                   │  scope: ALL / region / branch          │
                   │  DataSource factory:                    │
                   │    mode=api  → ApiDataSource (live)    │
                   │    mode=mock → MockDataSource (demo)   │
                   │                                         │
                   │  Pages: Home/KPIs, Follow-ups,          │
                   │    Analytics, Leads, Goal & Target,     │
                   │    Orchestrator, Intelligence,           │
                   │    Settings → Integrations (CRM)        │
                   └────────────────────────────────────────┘

                         ONE Neon Postgres instance
                    ┌────────────────────────────────┐
                    │  intelligence tables (typed)    │
                    │  orch_kv (JSONB, tbl+id PK)    │
                    │  pgvector HNSW indexes          │
                    └────────────────────────────────┘
```

---

## Directory Structure

```
chat360-intelligence-fabric/
│
├── intelligence/               Intelligence plane
│   ├── api.py                  FastAPI: /transcribe /converse /plans /knowledge
│   ├── designer.py             generate_plan / converse / apply_patch
│   └── data/
│       └── best_bots.json      Curated Chat360 canvas grammar + benchmarks
│
├── transcription/
│   └── engine.py               Sarvam STT → diarize → chunk → embed → insights
│
├── orchestrator/               Orchestrator plane
│   ├── api.py                  FastAPI: 21 routes, CORS, KPI compute, CRM
│   ├── config.py               All env vars (DATABASE_URL, Chat360, follow-up tuning)
│   ├── models.py               Dataclasses + T_* table-name constants
│   ├── store.py                PostgresStore (Neon orch_kv) | MemoryStore (tests)
│   ├── crm.py                  create/list/get/test CRM connections
│   ├── engines/
│   │   ├── dispatch.py         Lead dispatch + confirm gate
│   │   ├── followup.py         Commitment Ledger (Follow-up Reliability Engine)
│   │   └── goal_adaptation.py  Capacity split on goal change
│   ├── adapters/
│   │   ├── base.py             VoiceDispatchAdapter + CRMAdapter Protocols
│   │   ├── chat360_voice.py    Real Chat360 outbound dispatcher
│   │   ├── simulation.py       Credential-free simulation dispatcher (demo/dev)
│   │   └── rest_crm.py         Generic REST CRM adapter (httpx)
│   └── scheduler/
│       └── worker.py           APScheduler: polls due commitments
│
├── shared/                     Cross-plane Python foundation
│   ├── db.py                   Neon pool (psycopg3), init_db DDL, all table helpers
│   ├── embeddings.py           Provider-agnostic embed/embed_batch (Gemini | OpenAI)
│   ├── llm_client.py           Anthropic LLM client (complete_json, stream)
│   ├── chunking.py             chunk_segments — window diarized segments
│   └── auth.py                 is_admin() — client-id based role check
│
├── seed/                       One-time + idempotent seed scripts
│   ├── seed_platform_knowledge.py   10 always-on platform rules → platform_knowledge
│   ├── seed_bot_examples.py         Curated bot patterns → bot_examples RAG
│   └── seed_leads.py               Demo data: account, goal, target, 40 leads
│
├── scripts/                    Maintenance / one-time ingest
│   ├── ingest_reference_prompts.py   Adani SP (38 chunks) + intents (26 chunks) → RAG
│   ├── distill_reference_failures.py  Adani transcript failures → platform_knowledge
│   └── backfill_transcript_chunks.py  Index existing transcripts into transcript_chunks
│
├── tests/
│   ├── test_followup.py        Follow-up engine + Commitment Ledger (MemoryStore)
│   └── test_goal_adaptation.py Goal-adaptation capacity split (MemoryStore)
│
├── dashboard/                  Next.js 16 dashboard
│   ├── app/
│   │   ├── page.tsx                   Home / KPIs
│   │   ├── analytics/page.tsx
│   │   ├── follow-ups/page.tsx
│   │   ├── leads/page.tsx
│   │   ├── goal-target/page.tsx       Read + write via Orchestrator API
│   │   ├── orchestrator/page.tsx
│   │   ├── intelligence/              Transcribe / Design / Plans / Knowledge
│   │   └── settings/integrations/     Excel upload + Connect/test CRM
│   ├── app/api/
│   │   ├── campaigns/upload/          Server-side Excel parse (xlsx)
│   │   ├── intelligence/[...path]/    Proxy to Intelligence API (:8001)
│   │   └── orchestrator/recommendations/
│   ├── components/             Card, LayoutShell, ProgressBar, Sidebar, StatCard, …
│   ├── context/
│   │   ├── AccountContext.tsx   Scope (ALL/region/branch) + domain config
│   │   └── SidebarContext.tsx
│   └── lib/
│       ├── dataSource.ts        Factory: MockDataSource | ApiDataSource
│       ├── types.ts             Scope, Kpis, Lead, Commitment, CallOutcome, …
│       ├── domainConfig.ts      White-label layer (labels, statuses, vehicle types)
│       ├── useScoped.ts         Hook: re-fetch when scope changes
│       └── sources/
│           ├── apiDataSource.ts  Calls Orchestrator API (:8000) — live data
│           ├── mockDataSource.ts Demo data (no backend needed)
│           ├── mockData.ts
│           └── compute.ts        KPI + target-progress computation (shared client logic)
│
├── docs/                       Architecture decision records
│   ├── reference-intelligence-spec.md
│   ├── call-evidence-rag-spec.md
│   └── crm-datasource-integration.md
│
├── Dockerfile
├── requirements.txt
├── .env.example
└── .gitignore                  /data (PII), venv/, *.db, .env
```

---

## 1. Intelligence Plane

**Goal:** learn from real agent/bot calls and the best production bots, then produce a complete Chat360
voice-bot **plan** (workflow blueprint, system prompt, objection handling, build notes) an admin can
build on the canvas. No manual curation loop — every transcribed call feeds the next plan.

### Pipeline

1. **Transcribe** — [transcription/engine.py](transcription/engine.py): Sarvam STT (`saaras:v2`) with
   speaker diarization → labeled segments → `transcripts` table. Each call is also **chunked** into
   "call moments" (windows of 4 consecutive segments, overlap 1) and embedded into `transcript_chunks`
   (per-client RAG) at ingest time.
2. **Insights** — second LLM pass extracts `agent_score`, sentiment, `objection_patterns`, `kb_gaps`,
   **`bot_failure_modes`** (specific bot behaviours that frustrated the customer), and **`suggested_fixes`**
   (one concrete fix per failure) → `insights` table.
3. **Design** — [intelligence/designer.py](intelligence/designer.py): `generate_plan()` / `converse()` /
   `apply_patch()`. Builds the prompt from four layers and returns a strict-JSON plan.

### What feeds the designer (the four prompt layers)

| Layer | What | Delivery |
|---|---|---|
| **CACHE** | All active platform knowledge rules + Adani "known pitfalls" (must-fix guardrail) | Cached system block, every call |
| **RAG (bots)** | Top-8 proven bot examples + Adani `reference_system_prompt` / `reference_intent` chunks | `search_bot_examples`, k=8 |
| **RAG (calls)** | Top-5 verbatim call moments for **this client only** | `search_transcript_chunks(client_id)`, k=5 |
| **DUMP** | Per-client aggregated insights + observed `bot_failure_modes` | `_aggregate_insights` into user prompt |

### Self-improvement loops

- **Loop A — reference (Adani), manual/one-time:**
  [scripts/ingest_reference_prompts.py](scripts/ingest_reference_prompts.py) loads Adani system prompts
  (38 chunks) + intents (26 chunks) into `bot_examples` RAG;
  [scripts/distill_reference_failures.py](scripts/distill_reference_failures.py) distills real transcript
  failures → one always-on `platform_knowledge` guardrail ("Reference-bot known pitfalls").
- **Loop B — own bots, automatic:** every `/transcribe` writes `insights` (summary) + `transcript_chunks`
  (verbatim). `bot_failure_modes` flow straight into the next plan/patch. No manual step.

### Neon Postgres tables — [shared/db.py](shared/db.py)

`transcripts`, `insights`, `plans`, `plan_patches`, `workflow_sessions`, `conversation_turns`,
`platform_knowledge` (vector), `bot_examples` (vector, global RAG, ~101 units),
`transcript_chunks` (vector, per-client RAG).

All vector columns are `vector(768)` HNSW indexes (cosine). Embedding provider is
[shared/embeddings.py](shared/embeddings.py): Gemini `gemini-embedding-001` (default); switch to OpenAI
by flipping `EMBEDDING_PROVIDER / EMBEDDING_MODEL / EMBEDDING_DIM` and re-running seeds.

### FastAPI surface — [intelligence/api.py](intelligence/api.py)

`POST /transcribe` · `POST /converse` · `GET /plans` · `GET|POST /knowledge`  
`x-api-key` auth when `INTEL_API_KEY` is set. CORS controlled by `ALLOWED_ORIGINS`.

---

## 2. Orchestrator Plane

**Goal:** run Autovista's outbound lead operation as a virtual hub. Humans aren't replaced by LLM agents —
their **reporting** is replaced by the dashboard, their **follow-up discipline** by a deterministic engine.
Reliability over cleverness: every engine here is plain Python over a Store, **no LLM**.

### Engines — [orchestrator/engines/](orchestrator/engines/)

- **Dispatch** [dispatch.py](orchestrator/engines/dispatch.py) — pull/prioritize leads, DID pool (~100
  concurrent/DID), preview → confirm → dispatch (confirm gate prevents accidental mass-dial).
- **Follow-up Reliability** [followup.py](orchestrator/engines/followup.py) — **kills follow-up leakage.**
  Each promised follow-up is a durable **Commitment** row. Closed ONLY by an explicit terminal state
  (done / not_interested / exhausted / cancelled) — **never** by elapsed time or a goal change.
  Retry/backoff (`FOLLOWUP_BACKOFF_HOURS=4,24,48,72`), max-retries → `exhausted` (still recorded, never dropped).
- **Goal-Adaptation** [goal_adaptation.py](orchestrator/engines/goal_adaptation.py) — **kills goal whiplash.**
  When the monthly goal flips, splits capacity (`FOLLOWUP_CAPACITY_RESERVE`) between new-goal outreach and
  honoring prior-goal commitments. Every call stamped with `goal_context` for correct attribution.

### Adapters — [orchestrator/adapters/](orchestrator/adapters/)

- **VoiceDispatch** — `Chat360VoiceDispatcher` ([chat360_voice.py](orchestrator/adapters/chat360_voice.py):
  real outbound) or `SimulationVoiceDispatcher` ([simulation.py](orchestrator/adapters/simulation.py):
  credential-free demo) — chosen automatically by whether `CHAT360_AUTH_COOKIE` is set.
- **CRM** — `RestCRMAdapter` ([rest_crm.py](orchestrator/adapters/rest_crm.py): generic httpx REST,
  `get_campaigns / get_leads / update_lead / write_outcome`) or `StoreCRMAdapter` (in-memory, tests only).

### CRM connection feature — [orchestrator/crm.py](orchestrator/crm.py)

Connect external CRMs from the dashboard **Settings → Integrations** page. Each connection is a row in
`orch_kv[crm_connections]` with fields: `account_id`, `name`, `crm_type` (rest|hubspot|zoho|leadsquared),
`base_url`, `api_key`, `status`, `last_tested_at`.

API endpoints:
- `GET /orchestrator/crm/connections?account_id=…` — list connections for an account
- `POST /orchestrator/crm/connections` — create a new connection
- `POST /orchestrator/crm/connections/{id}/test` — probe the CRM base URL (httpx GET), returns `{ok, status_code, message}`

The `RestCRMAdapter` is the generic implementation; client-specific adapters (HubSpot, LeadSquared) plug in
via the `CRMAdapter` Protocol in [orchestrator/adapters/base.py](orchestrator/adapters/base.py).

### Store — [orchestrator/store.py](orchestrator/store.py)

`Store` Protocol: `put / get / list / delete / close`. Two implementations:

| Backend | When | Notes |
|---|---|---|
| `PostgresStore` | Production | Neon `orch_kv(tbl TEXT, id TEXT, data JSONB, PK(tbl,id))`. Auto-created on first `init_db()`. Upserts via `ON CONFLICT DO UPDATE`. |
| `MemoryStore` | Tests only | Pure `{table: {id: row}}` dict. Deep-copies on every read/write — no SQLite, no disk. |

`get_store()` returns a lazy `PostgresStore` singleton. `reset_store(store)` for test injection.

### Tables (orch_kv rows, keyed by `tbl`)

`accounts` · `goals` · `targets` · `leads` · `assignments` · `commitments` · `call_outcomes` · `rollups` · `crm_connections`

### Chat360 contract — [orchestrator/api.py](orchestrator/api.py)

- **Outbound:** `Chat360VoiceDispatcher` → `POST CHAT360_OUTBOUND_URL` with `dlr_id` = our `execution_id`
  (correlation key).
- **Ingest (we host):** `POST /orchestrator/webhook/chat360/outcome` — matches `dlr_id` → assignment,
  writes `call_outcomes`, mirrors onto the CRM lead, closes assignment, feeds Follow-up engine, and on
  `callback_requested` **spawns a fresh Commitment** (loop closure).

### Scheduler — [orchestrator/scheduler/worker.py](orchestrator/scheduler/worker.py)

APScheduler polls `commitments_due()` every `SCHEDULER_INTERVAL_SEC` (default 60s) and runs `process_due()`.

---

## 3. Dashboard Plane

**Goal:** replace manager reporting with a real-time, scope-aware view (ALL / region / branch). Reads the
orchestration op; does not drive it. Writes only Goal/Target and CRM connections via the Orchestrator API.

### Pages — [dashboard/app/](dashboard/app/)

| Page | Path | Purpose |
|---|---|---|
| Home / KPIs | `/` | Headline metrics + target progress bars |
| Follow-ups | `/follow-ups` | Commitment Ledger SLA health, overdue/at-risk |
| Analytics | `/analytics` | Conversion, goal attainment, scoped breakdowns |
| Leads | `/leads` | Lead list with status/assignment |
| Goal & Target | `/goal-target` | Read + live-edit goal/target via Orchestrator API |
| Orchestrator | `/orchestrator` | Dispatch view, recommendations |
| Intelligence | `/intelligence` | Transcribe / Design / Plans / Knowledge panel |
| Settings → Integrations | `/settings/integrations` | Upload campaign Excel + Connect/test CRMs |

### Portability layer

- **`DataSource` interface** [dashboard/lib/dataSource.ts](dashboard/lib/dataSource.ts) — factory picks
  `ApiDataSource` (`NEXT_PUBLIC_DATA_SOURCE=api` or `NEXT_PUBLIC_ORCH_API_URL` is set) or `MockDataSource`
  (default). All pages depend only on this interface — add a new data source with zero page changes.
- **`ApiDataSource`** [dashboard/lib/sources/apiDataSource.ts](dashboard/lib/sources/apiDataSource.ts) —
  calls the Orchestrator API at `NEXT_PUBLIC_ORCH_API_URL` (default `http://localhost:8000`). Maps the 8
  `DataSource` methods to REST endpoints.
- **Typed contracts** [dashboard/lib/types.ts](dashboard/lib/types.ts) — `Scope`, `Kpis`, `Lead`,
  `Commitment`, `CallOutcome`, `Report`, `Goal`, `Target`.
- **`domainConfig.ts`** [dashboard/lib/domainConfig.ts](dashboard/lib/domainConfig.ts) — white-label layer
  (labels, statuses, vehicle types, brand). Re-skin for a new industry/brand = swap this one file.
- **Scope switching** — [AccountContext](dashboard/context/AccountContext.tsx) filters every query by
  ALL / region / branch.
- **Intelligence proxy** — [dashboard/app/api/intelligence/](dashboard/app/api/intelligence/) proxies
  browser calls to the Intelligence API (:8001) so `INTEL_API_KEY` never reaches the browser.

---

## Shared Foundation — [shared/](shared/)

| Module | Purpose |
|---|---|
| [shared/db.py](shared/db.py) | Neon pool (psycopg3, `dict_row`, `prepare_threshold=None`). `init_db()` creates all tables + HNSW indexes. |
| [shared/embeddings.py](shared/embeddings.py) | `embed(text)` / `embed_batch(texts)` — provider-agnostic. Gemini `gemini-embedding-001` (768d) default. Switch to OpenAI: flip 3 env vars + re-seed. |
| [shared/llm_client.py](shared/llm_client.py) | Anthropic `claude-sonnet-4-6`. `complete_json` (structured output) + streaming. |
| [shared/chunking.py](shared/chunking.py) | `chunk_segments(segments, window=4, overlap=1)` — windows diarized segments into coherent ~50–150 word call moments. |
| [shared/auth.py](shared/auth.py) | `is_admin(client_id)` — checks `ADMIN_CLIENT_IDS`. Production: rewire to read Chat360's auth role claim. |

**Secret hygiene:** `DATABASE_URL` and all service keys are server-only — never `NEXT_PUBLIC_*`. `/data`
is gitignored (customer PII — audio, transcripts, analytics JSON); the ingest scripts read from it locally
and send only text to the embedding/LLM APIs. **Never commit anything under `/data`.**

---

## Setup

### Prerequisites

- Python 3.11+ with a `venv`
- Node.js 20+
- Neon Postgres project (free tier works) with the `pgvector` extension enabled
- Google AI Studio key (free) for embeddings
- Anthropic API key for the LLM

### Install

```bash
# Python
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Dashboard
cd dashboard && npm install
```

### Environment

```bash
cp .env.example .env
# Fill in: DATABASE_URL, ANTHROPIC_API_KEY, GOOGLE_API_KEY, SARVAM_API_KEY,
#           INTEL_API_KEY, CHAT360_OUTBOUND_URL, CHAT360_AUTH_COOKIE

cp dashboard/.env.local.example dashboard/.env.local
# Fill in: NEXT_PUBLIC_ORCH_API_URL, NEXT_PUBLIC_INTEL_API_URL,
#          NEXT_PUBLIC_INTEL_API_KEY, NEXT_PUBLIC_DATA_SOURCE
```

### Seed

```bash
# 1. Create all tables + HNSW indexes
PYTHONPATH=. venv/bin/python -c "from shared.db import init_db; init_db()"

# 2. Platform knowledge (10 always-on rules)
PYTHONPATH=. venv/bin/python seed/seed_platform_knowledge.py

# 3. Bot examples (global RAG corpus)
PYTHONPATH=. venv/bin/python seed/seed_bot_examples.py

# 4. Reference system prompts + intents (Adani, 64 chunks; runs ~6 min due to Gemini 15 RPM)
PYTHONPATH=. venv/bin/python scripts/ingest_reference_prompts.py

# 5. Distill reference failures into platform_knowledge guardrail (one-time)
PYTHONPATH=. venv/bin/python scripts/distill_reference_failures.py

# 6. Orchestrator demo data (account, goal, target, 40 leads)
PYTHONPATH=. venv/bin/python seed/seed_leads.py

# 7. (Optional) Backfill existing recordings into call-evidence RAG
PYTHONPATH=. venv/bin/python scripts/backfill_transcript_chunks.py
```

### Run

```bash
# Intelligence API
PYTHONPATH=. venv/bin/uvicorn intelligence.api:app --reload --port 8001

# Orchestrator API + scheduler
PYTHONPATH=. venv/bin/uvicorn orchestrator.api:app --reload --port 8000

# Dashboard
cd dashboard && npm run dev    # → http://localhost:3000
```

### Tests

```bash
PYTHONPATH=. venv/bin/pytest tests/ -v
# 9 tests: 5 follow-up + 4 goal-adaptation (MemoryStore — no Neon required)
```

---

## Change Map

| You want to change… | Touch |
|---|---|
| How plans are generated / prompt layers | [intelligence/designer.py](intelligence/designer.py) |
| What's extracted from each call | `INSIGHT_SYSTEM` in [transcription/engine.py](transcription/engine.py) |
| Always-on platform rules | [seed/seed_platform_knowledge.py](seed/seed_platform_knowledge.py) (re-run is idempotent) |
| Reference corpus (new bots/intents to learn from) | [seed/seed_bot_examples.py](seed/seed_bot_examples.py), [scripts/ingest_reference_prompts.py](scripts/ingest_reference_prompts.py) |
| Call moment chunking window | `window`/`overlap` in [shared/chunking.py](shared/chunking.py) |
| Switch embedding provider (Gemini → OpenAI) | Flip `EMBEDDING_PROVIDER / EMBEDDING_MODEL / EMBEDDING_DIM` + re-run seeds |
| Follow-up retry/backoff or capacity split | `FOLLOWUP_BACKOFF_HOURS`, `FOLLOWUP_CAPACITY_RESERVE` in [orchestrator/config.py](orchestrator/config.py) |
| Dispatch / follow-up / goal logic | [orchestrator/engines/](orchestrator/engines/) |
| Add a new CRM type (HubSpot, LeadSquared) | New adapter in [orchestrator/adapters/](orchestrator/adapters/) implementing `CRMAdapter` Protocol |
| Add a new voice provider | New adapter in [orchestrator/adapters/](orchestrator/adapters/) implementing `VoiceDispatchAdapter` Protocol |
| Add a new dashboard data backend | New `DataSource` impl in [dashboard/lib/sources/](dashboard/lib/sources/) |
| Re-skin dashboard for a new brand/industry | [dashboard/lib/domainConfig.ts](dashboard/lib/domainConfig.ts) |
| Orchestrator schema / new entity | [orchestrator/models.py](orchestrator/models.py) — add `T_*` constant + dataclass |
| LLM model version | `ANTHROPIC_MODEL` in `.env` (or set per-call in [shared/llm_client.py](shared/llm_client.py)) |

---

## Specs

[docs/reference-intelligence-spec.md](docs/reference-intelligence-spec.md) ·
[docs/call-evidence-rag-spec.md](docs/call-evidence-rag-spec.md) ·
[docs/crm-datasource-integration.md](docs/crm-datasource-integration.md) ·
[SPEC.md](SPEC.md) · [SPEC_ORCHESTRATOR.md](SPEC_ORCHESTRATOR.md) ·
[SPEC_CONVERSATIONAL_DESIGNER.md](SPEC_CONVERSATIONAL_DESIGNER.md) ·
[SPEC_PLATFORM_KNOWLEDGE.md](SPEC_PLATFORM_KNOWLEDGE.md)
