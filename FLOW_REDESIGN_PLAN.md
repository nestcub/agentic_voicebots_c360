# Intelligence Flow Redesign — Plan & Subagent Handoff

> Companion to `INPUT_COST_REDUCTION_EXPLAINED.md`. That doc costed the *old* 11-component
> conversational designer. This doc redesigns the flow around a fixed **12-section system
> prompt**, a **bots-list + create-wizard UI**, and **GPT‑5.4** (Sonnet stays plugged).
> No code is changed by this document — it is the spec the subagents build from.

---

## Part 1 — Simple explanation (read this first)

### What we're building
Today the intelligence engine is one freeform chat box that emits a loose plan JSON. We're
replacing it with a **guided wizard** that produces three clean, fixed-shape artifacts:

1. **Workflow** (with build notes) — the Chat360 canvas flow.
2. **System Prompt** — a strict **12-section** document (the format in
   `data/system_prompts/12_points_prompt_template.md`).
3. **Bot KB** — structured **JSON**.

### The create flow (one bot)
```
set use case → drop call recordings → transcribe + extract insights (LLM call 1)
   → LLM asks a few clarifying questions, Claude-Code style (LLM call 2a)
   → human answers
   → LLM generates the 12 points + Workflow + KB JSON (LLM call 2b)
   → human polishes → land on the Build screen with the 3 outputs
```

### The big decisions we already settled
- **Insights + call evidence are used ONCE, on create.** They are the raw material the 12
  points are built from (especially Conversational Flow, built from the *diarised sequence* of
  the best calls). After create they are baked into the prompt, so **patches never re-send
  them**. They stay in the DB for the UI to display.
- **Canvas grammar, platform knowledge, and the 12-points template are NOT dropped.** They
  are static and bot-independent, so they sit at the *front* of the prompt as a cached prefix
  (≈90% cheaper after the first call on both GPT‑5.4 and Sonnet). Dropping them would only
  save the ~10% you pay on a cache hit while making the Workflow hallucinate node types.
- **Patches always include the Workflow** (cross-reference anchor) + the one section being
  edited. Never edit a section blind to the structure it references.
- **`client_id` = `bot_id`.** No auth; the bots-list page just enumerates distinct
  `client_id`s. No schema migration.
- **GPT‑5.4 caching is automatic + prefix-based** (no `cache_control`, no TTL knobs). The only
  lever is *prompt order*: identical static content first, variable content last. That same
  ordering also satisfies Sonnet's explicit cache blocks — one ordering serves both.
- **reasoning_effort is tiered:** `medium/high` on create (real design work), `low` on
  patch/advice (mechanical). Never `minimal` on a JSON-producing turn (hurts structure).

### What the user sees in the UI
- A **Bots page** listing every bot with status (draft / transcribed / built) + **Create new
  bot** button → the wizard above → Build screen.
- **Build + Transcribe** screens are **per bot**.
- **Knowledge** page is **global** (platform knowledge, applies to all bots) — distinct from
  the per-bot *generated* Bot KB which lives on that bot's Build screen.

---

## Part 2 — The 12-section System-Prompt contract

Each section has a strict "what belongs / what does NOT" rule so the LLM never smears content
across sections and **patches address exactly one section**. Derived from the TVS template.

| # | Section | Belongs here | Does NOT belong |
|---|---|---|---|
| 1 | **Critical Rules** (language & voice) | `@bot_language` enforcement, STT-safe number-in-words rules, "no filler/greetings/thanks", begin-with-content rule | Flow steps, objections |
| 2 | **Roles** | Bot name, persona, company, verb gender | Objectives, tone adjectives |
| 3 | **Objectives** | What a successful call achieves; the call's goal | Step-by-step flow |
| 4 | **Personality** | Tone, warmth, politeness register | Hard rules (those are §1/§5) |
| 5 | **Important Flow Rules** | Hard flow constraints: date validation, "always end with a next-flow question", example-padding ban | The flow itself (§8) |
| 6 | **Guardrails** | Out-of-scope handling, refusals, "steer back to topic" | Safety escalation (§12) |
| 7 | **Instructions** | Formatting (numbers→words, max words, no special chars), tool/function-calling rules | Persona, flow |
| 8 | **Conversational Flow** | The staged script (greet→qualify→pitch→objection→close), built from the **diarised sequence** of best calls | Objection rebuttals (§10) |
| 9 | **Closure** | How to end: `set_variable call_completed`, `end_call`, closing line | Mid-call steps |
| 10 | **Objection Handling** | objection → rebuttal pairs, from insights | Flow steps |
| 11 | **Conversation Example** | 1–3 worked example dialogs from the best calls | New rules (examples are illustrative only) |
| 12 | **Safety Guardrails Once Again** | Restated safety/escalation for recency reinforcement | New content not already stated |

> "Additional points if needed" (e.g. *Reference Pronunciations*, *Tools & Usage*) are allowed
> as extra sections appended after §12; the patch router treats any section by its heading.

---

## Part 3 — Output artifact shapes

### Plan JSON (stored as today — one blob per `client_id`)
```jsonc
{
  "system_prompt_sections": {          // the 12 (+extra) sections, addressable by heading
    "critical_rules": "…", "roles": "…", "objectives": "…", "personality": "…",
    "important_flow_rules": "…", "guardrails": "…", "instructions": "…",
    "conversational_flow": "…", "closure": "…", "objection_handling": "…",
    "conversation_example": "…", "safety_guardrails": "…"
  },
  "system_prompt": "…",                // rendered concatenation of the sections (for copy-out)
  "workflow_blueprint": { … },         // unchanged shape (stages, node_types, config)
  "build_notes": { … },                // unchanged (variables_required is the cross-ref registry)
  "bot_kb": { … }                      // see schema below — replaces old kb_scaffold
}
```

### Bot KB JSON schema — **LLM-decided per bot, NOT fixed**
The KB shape is **emergent**: the LLM derives it from the use case + insights + the generated
system prompt. A real-estate bot, an automobile bot, and a feedback-gathering bot each need a
different shape — so we do **not** hardcode keys. Contract instead:
- The LLM returns a single JSON object under `bot_kb` whose keys it chooses to fit the domain.
- We **store it verbatim** (valid-JSON check only — no schema validation against fixed keys).
- We **load it whole** (never RAG'd — small, structured).
- The Build screen renders it with a **generic JSON viewer** (no per-key UI assumptions).
- Patches operate on **whatever keys exist** in that bot's `bot_kb`, discovered at runtime.

Illustrative only (the real keys vary by bot): a feedback bot might emit
`{ "questions": […], "rating_scale": …, "topics": […] }` while an automobile bot emits
`{ "models": […], "pricing": […], "dealers": […] }`.

---

## Part 4 — Prompt assembly (ordering = the only caching lever)

**Create call (2b)** — static prefix first so it caches across every bot:
```
[ canvas grammar ]            ← static, cached
[ platform knowledge ]        ← semi-static, cached
[ 12-points template ]        ← static, cached   (NEW — _twelve_points_template())
─────────────────────────────  cache boundary
[ bot-examples RAG ]          ← variable
[ insights + diarised best-call sequences ]
[ use case ]  [ clarifying answers ]  [ user message ]
```

**Patch call** — no insights, no evidence, no template:
```
[ canvas grammar ] [ platform knowledge ]   ← cached prefix
─────────────────────────────
[ workflow_blueprint + build_notes ]        ← ALWAYS sent (cross-ref anchor)
[ the single target section being edited ]
[ user request ]
```

Anthropic: mark the prefix blocks `cache: True` (existing mechanism). GPT‑5.4: caching is
automatic from the prefix — nothing to mark; just keep the order byte-identical.

---

## Part 5 — Subagent build plan (`/subagent-workflow`)

> Global constraints for EVERY subagent (same as `SONNET_INPUT_REDUCTION_SUBAGENT_PLAN.md`):
> - NO `Co-Authored-By` line. Commit ONLY your own file(s), never `git add .`.
> - Single-line commit, verb from `add, build, wire, fix, update`.
> - Read the file fully before editing; match surrounding style.
> - Sanity check (`python -c "import …"` / `npx tsc --noEmit`) before committing.
> - Do NOT touch a file another subagent owns.

### WAVE 1 — Foundation (parallel, no inter-deps)

**SA-A — `shared/llm_client.py`**
1. Add an optional `reasoning_effort: str | None = None` param to `complete()` / `complete_json()`.
   When set and provider is `openai`/`azure`, pass it through (`reasoning_effort=...`). Anthropic ignores it.
2. In the Azure branch, when `self.model` startswith `gpt-5`, send `max_completion_tokens`
   **directly** (skip the `max_tokens`-then-fallback round-trip — GPT‑5 rejects `max_tokens`).
3. In `_record_completion_metadata`, capture `usage.prompt_tokens_details.cached_tokens`
   (OpenAI/Azure) into `last_completion_metadata["cached_tokens"]` so cache hits are observable.
- Sanity: `python -c "import shared.llm_client"`. Commit: `update llm_client: reasoning_effort + gpt-5 token param + cache hit logging`

**SA-B — `shared/db.py`**
1. Add `list_bots(path=...) -> list[dict]` → distinct `client_id`s with a derived status
   (`built` if a plan row exists, `transcribed` if transcripts but no plan, else `draft`) and
   `updated_at`. Mirror existing accessor style.
2. Confirm `save_plan`/`get_plan` store the plan blob verbatim (they do — `bot_kb` rides along
   with no schema change). No table change unless a status column is cleaner — if so, derive in SQL.
- Sanity: `python -c "import shared.db"`. Commit: `add db: list_bots accessor for bots-list page`

### WAVE 2 — Core engine (depends on Wave 1) — single owner

**SA-C — `intelligence/designer.py`** (the heart; one agent owns this whole file)
1. Add `_twelve_points_template()` — read `data/system_prompts/12_points_prompt_template.md`
   from disk (mirror `_canvas_system()` / `BOTS_PATH`), wrap with an instruction: *"Mirror this
   exact 12-section structure; produce the equivalent sections for THIS bot."* Module-level path const.
2. **Create path** (`generate_plan`): append `_twelve_points_template()` as a third cached
   system block, after canvas grammar + platform knowledge. Change the output schema to
   `system_prompt_sections` (the 12 keys), a rendered `system_prompt`, `workflow_blueprint`,
   `build_notes`, and `bot_kb` (**LLM-decided JSON, Part 3 — store verbatim, valid-JSON check
   only, no fixed-key validation**). Keep insights + a 1–2 best-call **diarised sequence** in
   the user message here (this is the only call that gets them). Tier: `reasoning_effort` high/medium.
3. **Clarifying questions** (`generate_clarifying_questions`): keep, but cap at ≤6 and prefer
   multiple-choice phrasing (options drawn from insights), template-aware. **When recordings
   were skipped → insights are empty**, so this step must compensate: ask broader/deeper
   questions (raise the cap, e.g. ≤10) to recover the signal the calls would have provided.
   Branch on `insights["call_count"] == 0`.
4. **Patch path** (`apply_patch` and the `converse` patch branch): drop insights, call
   evidence, and the template from the prompt. ALWAYS include `workflow_blueprint` +
   `build_notes`. Send only the target `system_prompt_sections` key(s) selected from the
   request (reuse `prompt_packing.select_relevant_plan_sections`, extended for the 12 section
   keys). Output is the changed section(s) only. Tier: `reasoning_effort` low.
5. Thread `provider`/`model`/`reasoning_effort` from `converse` into the LLM calls.
- Sanity: `python -c "import intelligence.designer"`. Commit: `update designer: 12-section prompt, KB json, insight-free patch grounding`

### WAVE 3 — API (depends on Wave 2)

**SA-D — `intelligence/api.py`**
1. `GET /bots` → `list_bots()`.
2. `POST /bots` → mint a new `client_id`, return it (enters the wizard).
3. `POST /clarify` `{client_id, use_case}` → `generate_clarifying_questions`.
4. `POST /generate` `{client_id, use_case, answers, model}` → `generate_plan` (route model via
   existing `_INTEL_MODEL_MAP`, pass `reasoning_effort`).
5. `POST /patch` `{client_id, section?, request, model}` → patch path.
- Sanity: `python -c "import intelligence.api"`. Commit: `add api: bots list, create, clarify, generate, patch`

### WAVE 4 — Frontend (depends on Wave 3; clear page ownership, no shared-file edits)

**SA-E — `dashboard/app/intelligence/page.tsx`** (or a new `bots/page.tsx`): bots-list grid +
status chips + **Create new bot** → routes into the wizard. Reuse existing API-base + `x-api-key` helper.
- Commit: `add bots-page: list all bots with create button`

**SA-F — wizard** (`dashboard/app/intelligence/build/[…]` step components): use case → upload/
transcribe → clarifying questions (Claude-Code-style cards, multiple-choice where given) →
generate → redirect to Build. Resume-on-refresh via existing session persistence. **Recordings
are skippable** — a "Skip recordings" action jumps straight to the clarifying-questions step,
which then runs the deeper QnA branch (SA-C step 3) since insights will be empty.
- Commit: `add wizard: guided create flow for a bot`

**SA-G — Build screen** (`dashboard/app/intelligence/build/page.tsx`): render the 3 outputs
(12-section system prompt with per-section copy, workflow, KB JSON viewer) + a patch box that
posts to `/patch` with the targeted section. Show diarised segments alongside for human
verification of the Conversational Flow.
- Commit: `update build-page: render 12-section prompt, workflow, kb json + section patch`

### Execution order
Wave 1 (SA-A, SA-B) ∥ → Wave 2 (SA-C) → Wave 3 (SA-D) → Wave 4 (SA-E, SA-F, SA-G ∥).
If any subagent fails: pause, report, fix only that one, then continue. Don't start a wave
until the previous is green.

### Post-merge manual verification
1. Restart backend. `GET /bots` returns the list.
2. Create bot → upload recording → transcribe → answer clarifying questions → generate.
3. Build screen shows all 12 sections, a workflow, and KB JSON.
4. Patch one section ("make the closing friendlier") → only `closure` changes; insights NOT in
   the prompt (check logs); `cached_tokens` > 0 on the 2nd GPT‑5.4 call within the cache window.

---

## Resolved decisions
1. **Bot KB JSON schema** — NOT fixed. The LLM derives the shape per bot from use case +
   insights + system prompt; we store verbatim and render generically (Part 3).
2. **Section keys** — the 12 snake_case keys are accepted (Part 2 / Part 3).
3. **Recordings are skippable** — allowed; when skipped, the clarifying-questions step runs a
   deeper QnA branch (insights empty) to recover signal. "For best results" = upload recordings.
