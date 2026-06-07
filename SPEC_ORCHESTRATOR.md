# SPEC: Autovista AI Orchestrator (v2 — dashboard-driven, mono-repo)

> Status: **DRAFT for validation.** Review and polish this before any build begins.
> The orchestrator lives entirely inside `chat360-intelligence-fabric` (mono-repo).

---

## Design summary
- **No hierarchy LLM agents** (no branch/regional/executive agents). Management = **real-time dashboard** aggregating orchestrator tasks + call outcomes (scopes: ALL / region / branch).
- Follow-up reliability = **deterministic scheduler + durable Commitment Ledger** (not LLM memory).
- **Goal + Target** editable in Streamlit (Intelligence Plane); dashboard shows them read-only and **toasts** the human to edit there. Target rendered as live **progress bars**.
- **Mono-repo** — all three planes in this repo.
- **Dashboard** = leaddial UI copied in and converted wholesale to automobile (no industry ternaries); account-switch = dealership/scope switch via `AccountContext` + `domainConfig`.
- **Supabase** = shared orchestration store; **SQLite** stays for intelligence internals.
- Voice dispatch = **Chat360** for this demo (APIs TBD); adapter keeps Bolna/others pluggable.

---

## 1. Context & Goal
Automate Autovista's outbound lead operation into an AI virtual hub. Humans aren't replaced by LLM agents — their **reporting/visibility** is replaced by a clean real-time dashboard; their **follow-up discipline** by a deterministic engine. Two pains to kill:
- **(A) Follow-up leakage (MAJOR):** missed/late follow-ups lose paid customers.
- **(B) Goal-change whiplash:** when monthly goal flips (service-X → product-Y), old-goal follow-ups get dropped.

**Principles:** CRM-agnostic · voice-service-agnostic · goal changes originate in the Intelligence Plane (regenerate script) · concurrency = DID pool (1 DID ≈ 100 concurrent), single bot, not an agent swarm.

---

## 2. Human operation → AI mapping
| Human role | Today | AI replacement |
|---|---|---|
| CRM | Uploads campaign, assigns leads | **CRM Adapter** pulls campaign + leads |
| Telecaller | Calls leads | **Voice Dispatch Adapter** (Chat360) + DID pool, single bot |
| Branch/Regional Mgr | Reports, follow-up discipline, targets | **Deterministic engine** (follow-ups) + **dashboard** (reports, scoped ALL/region/branch) |
| CEO | Reviews audit anytime | **Real-time dashboard** + Target progress; human reviews EOD/anytime |
| Goal/target setting | Manager briefs | **Human edits Goal + Target in Streamlit** → script regenerated |

---

## 3. Architecture — three planes, one repo

```
┌─ INTELLIGENCE PLANE  (Streamlit, EXISTING)  ──────────────────────────┐
│  Transcribe → insights → generate/patch voice scripts.                 │
│  NEW: Goal + Target editor → writes active_goal/target/script_version  │
│       to Supabase; goal change regenerates the voice-bot system prompt. │
└───────────────┬───────────────────────────────────────────────────────┘
                │ (Supabase: goals, targets, script_version)
┌─ ORCHESTRATION PLANE  (NEW Python: engines + adapters + scheduler) ────┐
│  Deterministic engines — NO hierarchy LLM agents:                      │
│   • Follow-up Reliability (Commitment Ledger + scheduler)  ← Pain A     │
│   • Goal-Adaptation (capacity split, honor old commitments) ← Pain B    │
│   • Assignment/Dispatch (DID pool, single bot, confirm gate)           │
│  Writes assignments, commitments, call_outcomes, daily rollups → Supabase│
└───────┬───────────────────────────────┬───────────────────────────────┘
        │ CRMAdapter                     │ VoiceDispatchAdapter
┌───────▼─────────┐            ┌─────────▼──────────────────────────────┐
│ CRM (pluggable) │            │ Chat360 (demo) / Bolna — DID pool      │
└─────────────────┘            └────────────────────────────────────────┘
                ▲ Supabase (shared orchestration store)
┌─ DASHBOARD  (NEW Next.js + Supabase, copied from leaddial) ──────────────┐
│  Real-time dashboard: scopes ALL / Mumbai / Pune / branch.             │
│  Reports & analytics, follow-up SLA health, Goal+Target (read-only,     │
│  click → toast "edit in Intelligence Studio"). Reads Supabase live.     │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Core engines (deterministic — reliability over cleverness)

### 4.1 Follow-up Reliability Engine — *kills Pain (A)*
- **Commitment Ledger** (Supabase `commitments`): each promised follow-up = durable row `{lead_ref, due_at, goal_context, sla, retries, state}`.
- **Scheduler worker** (APScheduler): polls `due_at <= now`, dispatches via Voice Adapter, backoff retries on no-answer/busy, escalates after max retries.
- **Never-drop guarantee:** closed only by explicit outcome (done / not-interested / retries-exhausted) — never by goal change or elapsed time.
- Dashboard surfaces **overdue/at-risk commitments** loudly.

### 4.2 Goal-Adaptation Engine — *kills Pain (B)*
- `goals` row: `{month, focus_type: service|product, focus_detail, script_version, active}`; `targets` row: `{reach_out, close, follow_up}`.
- **Change flow:** human edits Goal+Target in Streamlit → fabric patches voice-bot system prompt (existing patch flow) → writes new `active_goal`+`script_version` to Supabase → orchestrator reads it.
- **Capacity split:** allocate DID/call capacity between (i) new-goal outreach on fresh leads and (ii) honoring prior-goal commitments from the Ledger. Old follow-ups protected; new outreach proceeds in parallel. Every call stamped with `goal_context` for correct attribution.

### 4.3 Assignment / Dispatch Engine
- Pull leads via CRM Adapter; prioritize (due follow-ups, fresh, interested, high-score).
- **DID pool manager:** configurable pool, ~100 concurrent/DID, single bot config.
- **Confirmation gate** retained (no accidental mass-dial).

---

## 5. Adapter interfaces (portability core)
```python
class CRMAdapter(Protocol):
    def get_campaigns(account_id) -> list[Campaign]
    def get_leads(campaign_id, filters) -> list[Lead]
    def update_lead(lead_id, fields) -> None
    def write_outcome(lead_id, outcome) -> None

class VoiceDispatchAdapter(Protocol):
    def dispatch_call(lead, script_version, goal_context, did) -> ExecutionId
    def get_result(execution_id) -> CallResult     # webhook or poll
    def list_dids() -> list[DID]
```
First impls: **Chat360VoiceDispatcher** (demo) + **SupabaseCRMAdapter** (leaddial-style) and/or a simulation adapter for testing. Autovista LMS / Maruti / Bolna added later against the same interfaces. The Intelligence link is just Supabase reads (`active_goal`, `script_version`) — no separate client needed since same repo/store.

### 5.1 Chat360 integration contract (CONFIRMED with their team)

**(a) Outbound dispatch — Chat360 provides:**
```
POST https://app.chat360.io/api/voicebot/external/outbound
Content-Type: application/json
Auth: csrftoken cookie (demo)  ⚠️ confirm stable API token for production
{
  "From": "<DID from our pool, e.g. +917965314309>",
  "To":   "<lead phone, e.g. +919611245205>",
  "dlr_id": "<OUR execution_id — correlation key>",
  "other_field_1": "<goal_context>",
  "other_field_2": "<script_version / customer_name / etc.>"
}
```
`Chat360VoiceDispatcher.dispatch_call()` maps: `From`=chosen DID, `To`=lead.phone, `dlr_id`=our `execution_id`, `other_field_*`=goal/script/personalization. Returns `dlr_id` as the ExecutionId.

**(b) Post-call ingest — WE provide, Chat360 bot calls it automatically (no pull API exists):**
This is the webhook contract to hand to the Chat360 team to configure on the bot:
```
POST  <our-host>/orchestrator/webhook/chat360/outcome
Content-Type: application/json
{
  "dlr_id": "<echoes the execution_id we sent>",   // REQUIRED correlation
  "from": "+917965314309",
  "to":   "+919611245205",
  "call_status": "completed | no_answer | busy | failed",
  "duration_sec": 123,
  "outcome": "interested | not_interested | callback_requested | booked | no_answer",
  "callback_at": "2026-06-09T15:00:00Z",            // optional (if callback requested)
  "transcript": "<full text or URL>",
  "recording_url": "<url, optional>",
  "extracted": { "vehicle_model": "...", "service_type": "...", "budget": "...", "notes": "..." }
}
```
On receipt the orchestrator: matches `dlr_id` → assignment/commitment, writes `call_outcomes`, updates the lead via CRM adapter, and **if `outcome=callback_requested` creates a new Commitment** (closing the loop for Pain A). `get_result()` is therefore webhook-driven, not polled.
*(Fallback: sessions are also viewable manually on the Chat360 platform under View Bots → View Details → Sessions.)*

---

## 6. Data model
**Supabase (shared orchestration store — dashboard + orchestrator + Streamlit goal editor):**
- `accounts` (dealership/scope context for dashboard switching: region, branch)
- `goals` (month, focus_type, focus_detail, script_version, set_by, active)
- `targets` (period, reach_out, close, follow_up)  → progress bars on dashboard
- `assignments` (lead_ref, region, branch, did, goal_context, state)
- `commitments` (follow-up ledger — heart of Pain A)
- `call_outcomes` (execution_id, lead_ref, goal_context, outcome, transcript_ref)
- `rollups` (period+scope aggregates for fast dashboard reads; refreshed by orchestrator)

**SQLite (existing, unchanged):** transcripts, plans, insights, workflow_sessions — intelligence-plane internals.

---

## 7. Dashboard (no-ternary solution)
- **Copy leaddial Next.js app → `dashboard/`.** Remove "Your Properties" (route, sidebar item, `Property` type, `app/api/properties/*`). Keep layout, sidebar, supabase client, lead table, call history, status badges.
- **Convert wholesale to automobile** — one industry here, so **no real-estate/automobile ternaries**. `bhk_type → vehicle_type`; labels via a small `lib/domainConfig.ts` (statuses, vehicle types, metric names).
- **Account/scope switching:** `AccountContext` in `TopHeader` selects ALL / Mumbai / Pune / branch → all Supabase queries filter by scope. Swaps branding + data, not component logic.
- **New pages (read Supabase live, Supabase realtime or 10s poll):**
  - **Dashboard** — KPIs, Target progress bars (reach-out/close/follow-up actual vs target), hot leads.
  - **Follow-ups** — SLA health, overdue/at-risk Commitment Ledger view.
  - **Analytics/Reports** — conversion, goal-attainment, scoped breakdowns (ALL/region/branch), time series.
  - **Goal & Target** — read-only display; click → `toast("Edit in Intelligence Studio (Streamlit)")`.
  - Keep **Leads**, **Call History** (reused).

### 7.1 Dashboard as a standalone product — interface-level design
The analytics/reports/SLA layer is the most productizable piece (LMS & Maruti CRMs lack it). To allow it to be **(i) outsourced to any dealership/CRM** or **(ii) folded into the Chat360 platform** without rewrites, the dashboard reads through a frontend abstraction — the UI mirror of the Python adapter pattern. Three interface-level pieces:

**(a) `DataSource` interface** (`dashboard/lib/dataSource.ts`) — the one structural add-on:
```ts
export interface DataSource {
  getKpis(scope: Scope): Promise<Kpis>;
  getLeads(scope: Scope, filters?: LeadFilters): Promise<Lead[]>;
  getCallHistory(scope: Scope): Promise<CallOutcome[]>;
  getCommitments(scope: Scope): Promise<Commitment[]>;   // follow-up SLA view
  getReport(scope: Scope, period: Period): Promise<Report>;
  getGoalAndTarget(scope: Scope): Promise<{ goal: Goal; target: Target }>;
  subscribe?(scope: Scope, cb: () => void): Unsubscribe;  // realtime; falls back to polling
}
```
Impls: `SupabaseDataSource` (demo, today) → later `Chat360ApiDataSource`, `RestDataSource`, `MarutiDataSource`. Pages/components depend ONLY on `DataSource`, never on Supabase directly. Swap the backend by swapping one provider in a `DataSourceContext`.

**(b) Shared typed contracts** (`dashboard/lib/types.ts`) — single source of truth mirroring the orchestrator's normalized output: `Scope` (all|region|branch + ids), `Kpis`, `Lead`, `CallOutcome`, `Commitment`, `Report`/`Metric`, `Goal`, `Target`. The dashboard renders "any normalized Report," not Supabase rows — so the same UI works over any CRM the orchestrator normalizes.

**(c) `domainConfig.ts`** — white-label/vocabulary layer (labels, statuses, vehicle types, brand colors, metric names). Productizing for a different industry/brand = swap this config, no component edits.

Net effect: the demo ships `SupabaseDataSource`; outsourcing or Chat360-embedding later is a new `DataSource` impl + a `domainConfig`, with zero changes to pages/components.

---

## 8. Streamlit additions (Intelligence Plane)
- **Goal & Target editor** (new section/tab): edit `focus_type`+`focus_detail` and `reach_out/close/follow_up`. Saving a goal triggers the existing **script patch** flow (regenerate system prompt) and writes `active_goal`+`target`+`script_version` to Supabase.

---

## 9. Mono-repo layout (in chat360-intelligence-fabric)
```
chat360-intelligence-fabric/
├── intelligence/, transcription/, shared/, app.py   # EXISTING Streamlit plane (+ Goal/Target editor)
├── orchestrator/                                     # NEW Python
│   ├── engines/        followup.py, goal_adaptation.py, dispatch.py
│   ├── adapters/       crm_base.py, voice_base.py, chat360_voice.py, supabase_crm.py, simulation.py
│   ├── scheduler/      worker.py (APScheduler)
│   ├── api.py          # thin FastAPI: preview/confirm/dispatch + /webhook/chat360/outcome
│   └── db.py           # Supabase client for orchestration tables
├── dashboard/                                          # NEW Next.js (from leaddial, automobile)
│   └── lib/            dataSource.ts (interface + SupabaseDataSource), types.ts, domainConfig.ts
├── seed/               seed_leads.py                  # push mock automobile leads → Supabase
└── migrations/         0001_orchestrator.sql          # orchestration schema (renamed from supabase/ to avoid shadowing the `supabase` pip package on `import supabase`)
```
gitignore `dashboard/node_modules`, build artifacts. Python deps appended to `requirements.txt` (apscheduler, supabase, fastapi, uvicorn).

---

## 10. Build phases (after spec validation — subagent-workflow waves)
- **P0:** New Supabase project + schema + orchestrator data model + adapter interfaces + Supabase/simulation adapters + `seed/seed_leads.py` (mock automobile leads, ~15 Mumbai/Pune branches).
- **P1 (priority):** Follow-up Reliability Engine + scheduler worker (Pain A). Verifiable with simulation adapter.
- **P2:** Assignment/Dispatch + DID pool + **Chat360VoiceDispatcher** + `/webhook/chat360/outcome` ingest + confirm gate.
- **P3:** Goal-Adaptation Engine + Streamlit Goal/Target editor + script-patch link (Pain B).
- **P4:** Dashboard — copy leaddial, strip real-estate, automobile retarget, AccountContext + `DataSource` interface + `SupabaseDataSource` + `types.ts` + `domainConfig`.
- **P5:** Dashboard analytics/reports pages + rollups + realtime + Target progress + Goal/Target toast.

---

## 11. Decisions (RESOLVED)
1. **Chat360 APIs — confirmed.** Outbound dispatch endpoint + WE-provide post-call webhook (see §5.1). Auth = csrftoken cookie for demo; stable token TBD for production.
2. **Demo lead source — mock data seeded into Supabase.** Build a `seed/seed_leads.py` that pushes mock automobile leads (vehicle_model, service_due, region, branch, phone) into Supabase. No live Autovista/Maruti API for the demo.
3. **Regions/branches — Mumbai & Pune, ~15 branches total**, researched from real Maruti/Autovista dealer locations at seed time. Candidate areas (to finalize): *Mumbai* — Andheri, Borivali, Goregaon, Worli, Thane, Vashi/Navi Mumbai, Kharghar, Panvel; *Pune* — Wakad, Hinjewadi, Kothrud, Hadapsar, Baner, Pimpri-Chinchwad, Viman Nagar. Stored in `accounts`/`assignments` for scope filters.
4. **Supabase — NEW dedicated project (recommended & accepted).** All orchestration tables are new; clean separation is easier to hand to the Chat360 team for production. Reuse leaddial's schema *patterns* (copy + adapt `schema.sql`), not its live data. Multi-dealership scoping handled by `account_id` inside the new automobile schema. New env vars: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_ANON_KEY`.

## 12. Verification (once built)
- Seed leads (Supabase/simulation); run dispatch with confirm gate; outcomes written back.
- Create follow-up commitments; advance clock; scheduler auto-dispatches; **Ledger never drops one** (Pain A test).
- Edit Goal+Target in Streamlit → script regenerates → orchestrator picks new goal; confirm **old-goal follow-ups continue while new-goal outreach starts** (Pain B test).
- Dashboard: switch scope ALL→Mumbai→branch; data + branding swap, no auth; Target progress + overdue follow-ups render live; clicking Goal/Target toasts to Streamlit.
