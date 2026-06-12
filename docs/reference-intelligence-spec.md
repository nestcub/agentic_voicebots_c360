# Build Spec — Reference-Bot Intelligence (learn from proven bots, fix their failures)

> **You are the implementing agent. Read this whole file, then execute it end to end.** Chat360 intelligence-fabric repo, Neon Postgres + pgvector, working RAG over `bot_examples` and (newly) `transcript_chunks`. This adds a **reference-intelligence layer**: the designer learns from the production bots' *recipes* (system prompts, intents, flows) AND their *failures* (from transcripts + analytics), so generated bots keep the proven structure and **fix the known bugs**. Reuse existing patterns; do not re-architect. Build in wave order; commit each unit of work with a single-line message, **no `Co-Authored-By`**.

## Core principle (why this exists)

The production reference bots are **not** gold standards — they have documented failures. The live Adani bot (`data/bot_transcripts/adani_bot.md`) visibly: replies in **English when the user chose Hindi**, mis-captures names ("Mohit"→"Mohi"), and **loops** on airport confirmation without advancing. So: **mirror the reference's structure, but extract its failure modes and engineer fixes into every generated plan.** Mistakes become requirements.

## Hard constraints

- Run everything from repo root with `PYTHONPATH=. venv/bin/python ...`.
- Commit format (no Co-Authored-By): `<verb> <module>: <one-line>` (verbs: add, wire, index, fix, update).
- **PII / data governance:** `/data` is gitignored (customer PII). The ingest scripts read from `/data` locally and send text to the embedding/LLM API. **Never commit anything under `/data`.** Store reference material under clearly-namespaced `unit_type`s so it's distinguishable from real client data. (The user has accepted using this reference data.)
- **Embedding input limit ~2048 tokens** (Gemini). Any chunk whose text exceeds ~1500 tokens must be sub-windowed before embedding, or its vector is silently truncated.
- Reuse: `shared/embeddings.py` (`embed`, `embed_batch`), `shared/db.py` (`add_bot_example`, `search_bot_examples`, `add_knowledge`, `get_knowledge`, `delete_knowledge`, `_get_pool`), `shared/llm_client.py` (`LLMClient().complete_json`), `seed/seed_bot_examples.py` (decomposition pattern). `bot_examples.unit_type` is a free TEXT column — new unit_types need **no schema change** and are retrieved automatically by `designer._retrieve_examples`.

## Source data (in `/data`, gitignored)

| File | What | Use |
|---|---|---|
| `data/system_prompts/adani_bot_sp.md` (129KB) | 6 `## SYSTEM PROMPT – …` sections | Recipe corpus → `reference_system_prompt` units |
| `data/intents_description.jsons/adani_bot_intents.md` (87KB) | 10 `## CATEGORY: …` sections | Recipe corpus → `reference_intent` units |
| `data/bot_transcripts/adani_bot.md` (5.5KB) | live Adani call transcripts (failures visible) | Failure distillation |
| `data/analytics_jsons/*.json` (adani_stage, arka, tvscredit, jp_infra, borosil) | per-bot `performance`, `drop_call_metrics`, `disposition_analytics`, `sentiment_analysis` | Failure distillation + populate `performance` |
| `data/bot_jsons/*.json` (adani 12.8MB, jp 1.6MB, arka, tvs, borosil) | full bot flow exports | Recipe corpus → `reference_bot_flow` units (chunked) |
| Adani filler context | provided below (§Wave 1c) | Recipe corpus → `reference_filler` unit |

---

## WAVE 0 — platform-knowledge rules (already drafted; just run + commit)

`seed/seed_platform_knowledge.py` is already updated with 10 facts (the new latency/async/initial-message/voice/endtool/system-prompt/intent rules + the upsert logic that refreshes seed-owned facts without clobbering frontend ones). Run it and commit.
```
PYTHONPATH=. venv/bin/python seed/seed_platform_knowledge.py
```
Verify: `get_knowledge('active')` lists the new topics. **Commit:** `seed platform knowledge: latency, async, initial message, endtool, system-prompt rules`

---

## WAVE 1 — recipe corpus (structure to mirror), parallel-safe

Add a reusable helper module, then three ingest passes. All write into `bot_examples` via the existing `add_bot_example(unit_type, name, use_case, content: dict, embedding)`.

**Shared rule for every pass:** build the embed-text as `f"{unit_type} | {name} | {use_case}\n{body}"`; if it exceeds ~1500 tokens (~6000 chars), split the body into overlapping ~1200-token windows and emit one unit per window (name suffixed `#1`, `#2`, …). Store the **full** window text in `content`. Make each pass idempotent: `DELETE FROM bot_examples WHERE unit_type=%s` before re-inserting (add a small helper or inline SQL via `_get_pool()`).

### 1a. NEW `scripts/ingest_reference_prompts.py`
- Read `data/system_prompts/adani_bot_sp.md`; split on lines matching `^## ` → 6 sections. unit_type=`reference_system_prompt`, name=heading text, use_case="Adani — <heading>", body=section text (sub-window if >1500 tok). `embed_batch` → `add_bot_example`.
- Read `data/intents_description.jsons/adani_bot_intents.md`; split on `^## CATEGORY:` → 10 sections. unit_type=`reference_intent`, name=category, use_case="Adani intent — <category>".
- Print counts. **Commit:** `add ingest_reference_prompts: chunk Adani system prompts and intents into RAG`

### 1b. NEW `scripts/ingest_reference_flows.py`
- For each `data/bot_jsons/*.json`: extract the node configs (walk the JSON; pull each node's `prompt`/`initial_message`/`use_tools`/`rag`/`routing_table`/type where present). unit_type=`reference_bot_flow`, name=`<bot_file> — node <id/type>`, content=the node dict, body=`json.dumps(node)`. One unit per node (sub-window if a node prompt >1500 tok).
- **Size guard:** `adani_bot.json` is 12.8MB — stream/iterate, do not load-and-dump into one string. Process node-by-node, `embed_batch` in batches of ~50. If a bot JSON has no recognizable node array, skip it and log.
- Print per-bot node counts. **Commit:** `add ingest_reference_flows: chunk production bot node configs into RAG`

### 1c. NEW `scripts/ingest_reference_filler.py`
- Store the Adani AVIO filler context (below) as one `reference_filler` unit (name="Adani AVIO filler generator", use_case="filler-word generation context — strict @bot_language lock").
```
ROLE: You are a female filler generator for AVIO, Adani Airport's voice assistant. Your only job is to
produce one short filler phrase that buys a few seconds of airtime while backend systems fetch data...
[FULL TEXT — paste the AVIO filler prompt the user provided verbatim, including LANGUAGE CONTROL
(STRICT), VOICE & TONE, SMOOTHNESS, VARIETY DISCIPLINE, HARD RESTRICTIONS, LENGTH 5-10 words,
STYLE EXAMPLES, OUTPUT RULES]
```
**Commit:** `add ingest_reference_filler: store Adani AVIO filler context in RAG`

> The full AVIO filler text was supplied by the user in the design conversation — paste it verbatim from there. It is a strict-`@bot_language` filler-generation prompt (Devanagari for Hindi, no code-switching, 5–10 words, feminine forms, no factual content).

---

## WAVE 2 — failure distillation (what to FIX), after Wave 1

### NEW `scripts/distill_reference_failures.py`
A **one-time critique** that turns the reference bots' real failures into always-on guardrails.
- Inputs: `data/bot_transcripts/adani_bot.md` (full text) + `data/analytics_jsons/adani_stage_analytics.json` (focus on `drop_call_metrics`, `disposition_analytics`, `sentiment_analysis`, per-stage `performance`).
- Use `LLMClient().complete_json` with a system prompt like: *"You are a voice-bot QA analyst. From these real production transcripts and stage analytics, extract concrete, recurring FAILURE MODES and the FIX each generated bot must apply. Be specific and actionable."* Return JSON: `[{failure, evidence, fix}]`.
- Store the result as a single platform-knowledge fact via `add_knowledge`:
  - topic = `Reference-bot known pitfalls (must fix)`, source = `distill`, status = `active`.
  - fact = a compact bulleted rendering of the `failure → fix` pairs, prefixed: *"These are real failures observed in the production reference bots. Every generated/patched plan MUST guard against them:"*. Expect items like: strict `@bot_language` enforcement at every node (reference replies in English to Hindi users); confirm/repair captured names; routing must advance after confirmation — never re-list the same options (observed 5× loop).
- Idempotent: delete any existing `Reference-bot known pitfalls (must fix)` row (source=`distill`) before inserting.
- Print the extracted failures. **Commit:** `add distill_reference_failures: extract reference failure modes into always-on pitfalls`

This fact is dumped into every plan via `_platform_knowledge_block`, so the designer always engineers around the known bugs.

---

## WAVE 3 — real analytics → populate `performance`, after Wave 1

### NEW `scripts/populate_bot_performance.py`
- Map each `data/analytics_jsons/<x>.json` → the bot in `intelligence/data/best_bots.json` by case-insensitive substring: `arka→Arka`, `tvscredit→TVS`, `adani_stage→Prod_Replicate_Adani`, `jp_infra→JP_Infra`, `borosil→borosill`.
- From each analytics file read the `performance` block (+ pull `drop_call_metrics`/`disposition` summary if useful) and write real numbers into that bot's `performance` field in `best_bots.json` (replace the current nulls/zeros). Keep the existing performance schema keys where they map; add a `stage_analytics_summary` sub-key for the richer fields.
- Then **re-run** `python -m seed.seed_bot_examples` so the bot units are re-embedded with the populated performance in their `content`.
- Print which bots got real numbers. **Commit:** `add populate_bot_performance: fill best_bots performance from real analytics`

---

## WAVE 4 — wire reference retrieval into the designer (after Waves 1–3)

`intelligence/designer.py` already RAGs `bot_examples` via `_retrieve_examples`, so the new `reference_*` units are **already retrieved**. Two small reinforcements:
- In the `generate_plan` and `converse` user prompts, where the system-prompt is being designed, add one instruction line: *"Before writing the system_prompt, study the retrieved `reference_system_prompt` sections and mirror their structure (CRITICAL LANGUAGE RULE block, @bot_language handling, tool/RAG usage). Apply every item in 'Reference-bot known pitfalls'."*
- (Optional, only if retrieval dilutes) bump bot-retrieval `k` from 5 → 8 so reference units have room to surface alongside the proven bots.
**Commit:** `wire reference prompts and pitfalls into plan generation`

---

## Verification (run and report)

1. Wave 0: `get_knowledge('active')` shows the new rule topics + (after Wave 2) `Reference-bot known pitfalls (must fix)`.
2. `SELECT unit_type, count(*) FROM bot_examples GROUP BY unit_type;` → shows `reference_system_prompt` (~6+), `reference_intent` (~10+), `reference_bot_flow` (many), `reference_filler` (1), plus the original units.
3. Retrieval: embed a query like *"hindi voice bot that must not switch to english, airport ticket status"* → `search_bot_examples` returns the Adani reference system-prompt + the language-lock material near the top.
4. `python -c "import json; b=json.load(open('intelligence/data/best_bots.json')); print([(x['name'], x['performance']) for x in b['bot_examples']])"` → real numbers, not zeros.
5. Run `POST /converse` for a Hindi use-case → confirm (temporary debug log) the prompt now contains reference system-prompt chunks + the pitfalls fact, and the generated `system_prompt` includes a strict `@bot_language` lock. Remove debug log before final commit.

Report the output of steps 2–4 to the user.

## Notes / out of scope
- Bot-example decomposition (5 bots = 5 units) is correct and unchanged — verified, no truncation.
- `transcript_chunks` (per-client call-evidence RAG) already exists; this spec is the **reference** corpus (cross-client, namespaced `reference_*`), kept separate from real client evidence.
- If the user later wants the other 4 bots' transcripts distilled too, repeat Wave 2 per bot once their transcripts are in `/data`.
