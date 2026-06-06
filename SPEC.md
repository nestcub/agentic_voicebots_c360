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