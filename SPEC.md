# Chat360 Intelligence Fabric — Build Spec

## What this is
AI harnessing system (NOT model training) that generates
voice bot workflow plans for Chat360 clients.
Uses: prompts, structured JSON state, in-context learning.
No fine-tuning. No RAG in Phase 1.

## Use case for tonight's build
Client: Maruti Suzuki & Excel Autovista(automotive dealership)
Goal: Build a Chat360 intelligence fabric - intelligence plan creates a voice bot workflow within the chat360 canvas with all connections and working at prod grade, orchestrator plane is for client.(please refer to the architecture from /data/chat360-iintelligence-fabric-architecture)
Voice Bot Language: Hinglish
Orchestrator action: Get uploaded campaign, Qualify leads, book test drives, respond to leads on whatsapp and trigger outbout voice calls using chat360 apis
Tonight: we only build transcription engine and workflow designer 

## What I have
- best_bots.json: Chat360's top 10 performing bot workflows
  with performance metrics. This teaches the system what
  Chat360's workflow builder is capable of.
- Human agent recordings from Autovista (automotive client)
  These teach the system how good agents qualify and handle
  objections in real calls.
- Deepgram API key (transcription)
- Anthropic API key (claude-sonnet-4-6)
- Trancription Engine built on Colab, uses whisper oss - .py file attached into /data

## What needs to be built tonight

### 1. Transcription Engine
Input: audio file (wav/mp3/m4a)
Process: Deepgram Nova-3, speaker diarization, Hindi+English
Output: {transcript, segments with speaker labels, duration}
Saves to: SQLite transcripts table

### 2. Workflow Designer Engine (Learning + Planning merged)
System prompt: contains best_bots.json as permanent context
User prompt: transcripts + admin QnA answers
Output: structured plan JSON with these exact keys:
  - workflow_blueprint (stages, flow description)
  - system_prompt (the bot's core instruction)
  - qualification_questions (list)
  - objection_handling (objection → response mapping)
  - escalation_rules (list of triggers)
  - kb_scaffold (topic → content)
  - build_notes (specific Chat360 canvas instructions)

Plan refinement: patch-based only (never regenerate full plan)
Each patch stored in DB with admin request + LLM reasoning
**For best Output:** the llm needs to understand the chat360 workflow canvas, its components, components connection capabilites (nodes), components inputs from the bots json from system prompt. If it does not understand it will halluciante of the workflow_blueprint will not be accurate for an admin to build. **Very Important**

### 3. SQLite Database
Tables: plans, plan_patches, transcripts, insights
No Supabase. No pgvector yet. Pure SQLite.

#### insights table schema
```
id                   TEXT PRIMARY KEY
transcript_id        TEXT NOT NULL  REFERENCES transcripts(id)
client_id            TEXT NOT NULL
agent_score          INTEGER        CHECK(agent_score BETWEEN 1 AND 10)
sentiment            TEXT           CHECK(sentiment IN ('positive','neutral','negative'))
objection_patterns   TEXT           -- JSON array of strings
qualification_signals TEXT          -- JSON array of strings
escalation_signals   TEXT           -- JSON array of strings
kb_gaps              TEXT           -- JSON array of strings
raw_insights_json    TEXT           -- full LLM response as JSON string
created_at           TEXT NOT NULL
```

When written: immediately after transcription saves its row, a second LLM call
(InsightExtractor) analyses the full transcript and writes one insights row.
Both happen inside TranscriptionEngine.transcribe() — caller gets both back.

Read by: WorkflowDesigner.generate_clarifying_questions() and
WorkflowDesigner.generate_plan() — queries all insights for client_id,
injects objection_patterns / qualification_signals / escalation_signals /
kb_gaps into the LLM context so the plan is grounded in real call data.

### 4. Streamlit UI

#### Tab 1: Workflow Intelligence — Full Flow

**Step 1 — Input**
- Multi-file audio upload (wav/mp3/m4a)
- Free-text field: "Describe your use case and what you need"
  (natural language, no fixed form — e.g. "Maruti Suzuki outbound
  campaign to qualify test drive leads from Facebook ads, Hinglish,
  target tier-2 cities")
- [Transcribe & Analyse] button

**Step 2 — Background processing (shown as progress)**
a. Deepgram Nova-3 transcribes each file → saves to transcripts table
b. InsightExtractor LLM call → saves to insights table
   (agent_score, sentiment, objection_patterns, qualification_signals,
   escalation_signals, kb_gaps)
c. Transcripts displayed with speaker-labeled segments (AGENT / CUSTOMER)

**Step 3 — LLM-generated clarifying questions**
After transcription + insight extraction, the system generates targeted
questions grounded in:
  - The admin's free-text use case description
  - Objection/qualification/escalation patterns found in the recordings
  - Gaps in kb_scaffold suggested by insights.kb_gaps
  - Adjacent patterns from best_bots.json synthesis
Questions appear as a dynamic form (no fixed set — could be 3 or 10).
The LLM asks only what the recordings could NOT already tell it.
Admin answers each question in free text.

**Step 4 — Generate Plan**
[Generate Plan] button sends:
  - Use case description
  - Transcripts + insights for this client
  - Clarifying question answers
  - best_bots.json as system context
→ Returns structured plan JSON, displayed as expandable sections:
  workflow_blueprint / system_prompt / qualification_questions /
  objection_handling / escalation_rules / kb_scaffold / build_notes

**Step 5 — Iterative refinement**
Admin types a plain-language change request
→ Patch applied (never full regeneration)
→ Diff shown (old value → new value per changed key)
→ Version history visible (all patches listed with timestamps)

#### Tab 2: Agentic AI (placeholder only tonight)

### 5. LLM Client
Provider-agnostic wrapper
Tonight: Anthropic claude-sonnet-4-6 only
Tomorrow: add Azure OpenAI GPT-4.1 support

## What I do NOT want built tonight
- Agentic AI / Orchestrator (tomorrow)
- RAG / pgvector (Phase 2)
- WhatsApp integration (tomorrow)
- Voice bot (after plan is generated)
- Golang anything

## File structure
intelligence-fabric/
  transcription/engine.py
  intelligence/designer.py
  intelligence/data/best_bots.json
  shared/llm_client.py
  shared/db.py
  app.py
  SPEC.md
  .env
  requirements.txt

## Constraints
- All API keys from .env only, never hardcoded
- SQLite DB file: intelligence_fabric.db in repo root
- Every function has a docstring
- Patch-based plan updates: NEVER regenerate full plan
- LLM model is a config value, never hardcoded in logic

---

## Chat360 Canvas — Full Node Type Reference
*(Derived from deep inspection of all 5 bot JSONs, especially adani — 478 nodes, 773 edges)*

### Node types available on the Chat360 canvas

| Node Type | Component Type | Description |
|---|---|---|
| `INIT` | — | Start of flow. One out port. Routes to first real node. |
| `VOICE_GENAI` | voice_genai | LLM-powered conversational node. Thinks + speaks. Core of every flow. |
| `VOICE_CUSTOM_INPUT` | voice_custominput | Speaks TTS then captures caller speech. Used for listen-respond loops. |
| `VOICE_MESSAGE` | voice_message | One-way TTS. No input captured. Confirmations, goodbyes, transfers. |
| `VOICE_INTENT` | voice_intent | Detects a specific intent from caller speech → routes to named output port. |
| `VOICE_SET_VARIABLE` | voice_set_variable | Hardcodes a runtime variable. Tracks conversation state. |
| `VOICE_CONDITIONAL` | voice_conditional | Multi-branch if/else on variable values (EQUALS_TO / CONTAINS). |
| `VOICE_WEBHOOK` | voice_webhook | HTTP API call (GET/POST). Captures response via response_body_schema. |
| `VOICE_MULTI_CHOICE` | voice_multichoice | Spoken menu of options. Stores selection in option_variable. |
| `VOICE_LANGUAGE_PREFERENCE` | voice_language_select | Caller picks language. Sets @bot_language for rest of flow. |

### Key field reference per node type

**VOICE_GENAI key fields:**
- `prompt` — full LLM system instruction (use @bot_language, never hardcode language)
- `initial_message` — opening spoken line on first entry
- `genai_response_variable` — stores LLM output (e.g. @genairesponse)
- `response_variable` — stores caller speech input
- `routing_table` — {default: next_node_uuid}
- `use_tools` — enable function/tool calling
- `rag` — enable retrieval-augmented generation
- `skip_speak` / `skip_listen` — silent processing mode

**VOICE_INTENT key fields:**
- `intents` — array of intent IDs to match
- `routing_table` — {default: fallthrough_node, <intent_id>: specialist_node}
- `portOpt` — named output ports per intent (label = intent name)

**VOICE_CONDITIONAL key fields:**
- `conditions` — array of {variable, value, condition: EQUALS_TO|CONTAINS}
- `routing_table` — {default: node, <value>: node, ...} — one key per condition branch
- `portOpt` — named output port per branch value

**VOICE_WEBHOOK key fields:**
- `url` — API endpoint (use @variables in query params)
- `method` — GET or POST
- `query_params` — JSON string with @variable substitutions
- `body` — POST body
- `capture_response` — true to store response
- `response_body_schema` — maps response fields to @variables
- `routing_table` — {default: next_node}

**VOICE_SET_VARIABLE key fields:**
- `variable` — @variable to set
- `value` — literal value to assign

**VOICE_MULTI_CHOICE key fields:**
- `multichoice_options` — array of option strings
- `option_variable` — @variable to store selection
- `tts_prompt` — spoken prompt before showing options

**VOICE_LANGUAGE_PREFERENCE key fields:**
- `starter_language` — default language
- `allowed_languages` — array of allowed choices
- `fallback_language` — if detection fails
- `tts_prompt` — e.g. "Please let me know your preferred language"

### Adani Airport bot — multi-specialist architecture pattern
*(Production-grade reference for complex flows)*

```
INIT
→ VOICE_WEBHOOK          fetch CRM data by @caller_number before conversation starts
→ VOICE_LANGUAGE_PREF    caller picks Hindi / English → sets @bot_language
→ VOICE_GENAI            "Information Capture" agent — identifies airport + issue category
→ VOICE_SET_VARIABLE     set @category_intent, @subcategory_intent
→ VOICE_INTENT           detect sub-intent → named port → specialist GenAI agent
   └─ VOICE_GENAI [x145] each with own system prompt, RAG + tools enabled
      e.g. Baggage Wrapping / Transit / Duty Free / Lost & Found /
           Pranaam / Car Parking / Flight Info / CISF Feedback /
           Immigration / Out-of-Scope fallback
→ VOICE_CONDITIONAL      branch on @case_status (OC / MC / No Contact / No Case)
→ VOICE_MULTI_CHOICE     airport selection menu (11 airports) → @airport_selected
→ VOICE_CONDITIONAL      route by @airport_selected to city-specific handlers
```

**Key patterns from adani to reuse for Autovista:**
- VOICE_WEBHOOK at flow start → fetch lead data from CRM by phone number
- VOICE_INTENT → route to specialist GenAI per topic (test drive / pricing / objection / callback)
- VOICE_SET_VARIABLE → track @lead_status, @vehicle_interest, @preferred_model
- VOICE_CONDITIONAL → branch on lead quality score or customer intent
- 145 specialist VOICE_GENAI agents all use RAG + tools, each with domain-specific prompt

### best_bots.json extraction spec
What is included in intelligence/data/best_bots.json:
- canvas_grammar: all 10 node types with full field schemas and rules
- adani_specialist_patterns: 10 representative VOICE_GENAI prompt openings + configs
- adani_intent_routing: 5 VOICE_INTENT examples showing intent → specialist routing
- adani_conditional_examples: all 6 VOICE_CONDITIONAL examples (full conditions + routing)
- adani_webhook_pattern: full VOICE_WEBHOOK config for CRM fetch
- adani_variable_state: VOICE_SET_VARIABLE examples for state tracking
- bot_examples: trimmed flow summaries for all 5 bots (tvs_credit, borosil, arka, jp_infra, adani)
- performance_benchmarks: from analytics JSONs
- proven_prompt_patterns: from real VOICE_GENAI system prompts

## Prompt example to intelligence engine for fields Describe your use case and what you need:
Maruti Suzuki dealer Excell Autovista, outbound voice campaign in Hinglish, qualify leads for service. Bot Calls them to remind about their vehicle service and try to book it. Voice bot should also be able to handle questions from customer about service types and kinds, price, insurance (get from insurance agent), sales (when customer wants to purchase a new car), pre-owned cars (when customer says I want to sell my car). 

## Questions quality review: All 8 questions are clean —
 no hallucinations. Every question is grounded either in the use case or directly in call recording insights (Supreme Motors competitor question came from Recording 3's escalation signals; pricing gaps came from KB gaps). Language/tone question unlocked excellent detail. Nothing invented.

---

# How to Run (current state — 2026-06-08)

Mono-repo, three planes. The Python backend runs **creds-free on SQLite** (`ORCH_STORE=memory`) or on **Supabase** (`ORCH_STORE=supabase`). The dashboard runs on **mock data** (no creds) or **live Supabase**.

## 0. Prerequisites
```bash
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
# Node 20+ required for the dashboard
cp .env.example .env   # then fill the keys below
```
`.env` (repo root) keys:
- Intelligence: `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `DEEPGRAM_API_KEY`
- Orchestrator store (live mode): `ORCH_STORE=supabase`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_ANON_KEY`
- Voice dispatch (live calls): `CHAT360_AUTH_COOKIE`; the outbound DID is per-VoiceBot (`VoiceBot.dids`), not an env var
- Note: `SUPABASE_URL` (bare) is for Python; `NEXT_PUBLIC_SUPABASE_URL`/`NEXT_PUBLIC_SUPABASE_ANON_KEY` are for the dashboard.

## 1. Intelligence plane — Streamlit (transcribe · plan · Goal/Target)
```bash
streamlit run app.py          # → http://localhost:8501
```
- **Tab 1 — Workflow Intelligence:** upload recordings → transcribe (Deepgram Nova-3) → insights → clarifying questions → generate plan → patch loop. Plans + Q&A persist in SQLite and survive refresh.
- **Tab 2 — AI Orchestrator:** Goal & Target editor. Saving writes the active goal/target to the orchestrator store and bumps the voice-bot `script_version`.

## 2. Orchestrator — the execution engine (Python)
**Create tables once** (Supabase SQL Editor → paste [migrations/0001_orchestrator.sql](migrations/0001_orchestrator.sql)), then **seed**:
```bash
ORCH_STORE=supabase ./venv/bin/python -m seed.seed_leads --count 40
# (omit ORCH_STORE, or =memory, to run fully offline on SQLite)
```
**Run the API + the follow-up scheduler** (two terminals):
```bash
./venv/bin/uvicorn orchestrator.api:app --reload --port 8000   # dispatch + Chat360 webhook
./venv/bin/python -m orchestrator.scheduler.worker             # auto-fires due follow-ups
```
**Trigger an outbound campaign** (confirm-gated — never dials without an explicit confirm):
```bash
ACC=<account_id from the Supabase 'accounts' table>
curl -s localhost:8000/orchestrator/autodial/preview  -H 'content-type: application/json' -d "{\"account_id\":\"$ACC\"}"
curl -s localhost:8000/orchestrator/autodial/confirm  -H 'content-type: application/json' -d "{\"session_id\":\"<sid from preview>\"}"
curl -s localhost:8000/orchestrator/autodial/dispatch -H 'content-type: application/json' -d "{\"account_id\":\"$ACC\",\"session_id\":\"<sid>\"}"
```
**Post-call ingest** — Chat360's bot calls this automatically (keyed by `dlr_id`); see SPEC_ORCHESTRATOR.md §5.1:
```
POST localhost:8000/orchestrator/webhook/chat360/outcome
```

## 3. Dashboard — monitor (Next.js)
```bash
cd dashboard && npm install
# Mock data (zero creds): just run dev
npm run dev                    # → http://localhost:3000
# Live Supabase: create dashboard/.env.local with
#   NEXT_PUBLIC_SUPABASE_URL=...   NEXT_PUBLIC_SUPABASE_ANON_KEY=...
#   (do NOT set NEXT_PUBLIC_DATA_SOURCE=mock), then restart `npm run dev`
```
Pages: **Dashboard** (KPIs + Target progress), **Leads**, **Follow-ups** (Commitment Ledger SLA — overdue highlighted), **Analytics** (region/branch breakdowns + calls/booked over time), **Goal & Target** (read-only; edits redirect to Streamlit). Scope switcher: ALL / Mumbai / Pune / branch.

## 4. Tests (regression for the two pains)
```bash
./venv/bin/python3 tests/test_followup.py          # Pain A — follow-ups never dropped
./venv/bin/python3 tests/test_goal_adaptation.py   # Pain B — goal switch keeps old commitments
```

## Ports
Streamlit **8501** · Orchestrator API **8000** · Dashboard **3000**

## Who shows what
- **Streamlit** = author (scripts, goals). **Orchestrator API + scheduler** = do the work (watch their console logs). **Dashboard** = view the resulting state (assignments, commitments, outcomes, analytics).



##  what the LLM gathers to generate a plan
SYSTEM PROMPT  (cached — stable across calls, ~90% cheaper on repeats)
 ├─ 1. Canvas grammar + performance_benchmarks      ← best_bots.json structural keys
 └─ 2. ALL active platform knowledge (dumped)        ← platform_knowledge table
        • your 8 rules: latency, async tools, initial message, voice,
          Endtool ending, system-prompt importance, AI-Hub intents, filler
        • "Reference-bot known pitfalls (must fix)"  ← distilled in Wave 2

USER PROMPT  (built fresh every call)
 ├─ 3. Use case (remembered)                         ← workflow_sessions
 ├─ 4. Aggregated call insights (dedup summary)      ← insights table  (dumped)
 ├─ 5. Top-K bot examples (RAG vector search)        ← bot_examples
 │       • 5 compact bots + adani patterns (today)
 │       • + reference_system_prompt, reference_intent, reference_filler  ← Wave 1
 ├─ 6. Top-K call evidence — verbatim quotes (RAG)   ← transcript_chunks (this client only)
 ├─ 7. Current plan + recent conversation turns      ← plans + conversation_turns
 └─ 8. The user's message / answers

