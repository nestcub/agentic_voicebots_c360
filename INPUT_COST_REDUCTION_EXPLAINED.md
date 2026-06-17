# Intelligence Fabric — LLM Mental Model, Token Budget & Cost

> Last updated: 2026-06-17 — removed future patterns table; call insights DUMP is final approach; added DUMP growth cap; reframed around output cost; elevated boilerplate→system move; dropped batch API and risky compressions

---

## ⚠️ Read this first: output tokens dominate the bill

This was originally an "input cost" doc, but the real cost split per turn is:

| Turn type | Input cost | Output cost | **Output share** |
|---|---|---|---|
| Patch (warm cache) | ~$0.028 | ~$0.030 | **52%** |
| Plan creation | ~$0.039 | ~$0.090–0.105 | **~70%** |

All caching and RAG trimming below fights over the *smaller* half of the bill. The
single most expensive thing in `converse()` is the model emitting a full plan JSON under
`max_tokens=16000`. **The one optimization that actually controls cost is already in
place:** on patch turns the designer prompt returns only the changed top-level keys
(`patch`), never the full plan. Protect that behavior above all else. See
[Output Token Reduction Plan](#output-token-reduction-plan).

---

## Finalized Mental Model: 11 Components

Every `converse()` call (plan generation or patch) assembles these components in order.
**CACHED** = Anthropic prompt caching (`cache_control: ephemeral`), billed at $0.30/MTok on reads.
Everything else is billed at full input rates ($3/MTok) on every turn.

---

### Component 1 — Canvas Grammar  ✦ CACHED Block 1

**What it is:** The Builder Workflow reference — every Chat360 node type, field schema, and routing pattern. This IS the Builder Workflow definition. Settings and AI Hub will be added here once documented as structured JSON (same format as `canvas_grammar`).

**Source:** `intelligence/data/best_bots.json` → `canvas_grammar` + `performance_benchmarks`
**Loaded by:** `_canvas_system()` in `designer.py`
**Nature:** Static. Changes only when Chat360 ships a new node type or field.

| | |
|---|---|
| Tokens today | ~2,000 |
| Cache write (first call) | $0.0075 |
| Cache read (every subsequent call) | $0.0006 |

---

### Component 2 — Platform Knowledge  ✦ CACHED Block 2

**What it is:** Operational facts about Builder Workflow, Settings, and AI Hub — curated by the Chat360 team via the admin Knowledge UI. These answer *"how should I configure this for best results?"*, not *"does this field exist?"* (that's Canvas Grammar).

**Separation rule (eliminates duplicacy):**
- Schema fact → Canvas Grammar: `"VOICE_GENAI has a silence_handle field with retry_count and retry_prompt"`
- Operational fact → Platform Knowledge: `"Set silence_retry_count=2 for Sarvam STT, else callers hang"`

When Chat360 ships a new feature: add the schema to `best_bots.json` (one-time, versioned), add best-practice tips to Platform Knowledge via the admin UI (ongoing, no code deploy).

**Source:** `platform_knowledge` table in Neon, `status='active'`
**Loaded by:** `_platform_knowledge_block()` in `designer.py`
**Nature:** Semi-static. Changes when admin adds or edits facts.

| | |
|---|---|
| Tokens today | ~300–500 |
| Tokens when fully documented | ~1,000–2,000 |
| Cache write | ~$0.001 (once per edit cycle) |
| Cache read | $0.00009–0.0006 per turn |

---

### Component 3 — Bot Templates (RAG)  ✗ NOT CACHED

**What it is:** Top-k most relevant proven bot examples, retrieved at query time via pgvector similarity search. Grounds the plan in real production patterns and system prompt structures.

**Source:** `bot_examples` table in Neon (seeded from `best_bots.json` via `seed_bot_examples.py`)
**Loaded by:** `_retrieve_examples(query, k=8)` in `designer.py`
**Nature:** Retrieval-time — varies per query, cannot cache.

**Strategy (to implement):**
- First plan creation: `k=8` — need broad coverage
- Patch turns (plan already exists): `k=3` — targeted lookup only, saves ~1,700 tokens

| | |
|---|---|
| Tokens (plan creation, k=8) | ~2,700 |
| Tokens (patch turn, k=3) | ~1,000 |
| Cost at $3/MTok | $0.008 (plan) · $0.003 (patch) |

---

### Component 4 — Call Insights (DUMP)  ✗ NOT CACHED

**What it is:** Aggregated patterns from all of this client's uploaded call recordings — objections, qualification signals, KB gaps, bot failure modes, suggested fixes. Deduplicates across all recordings into flat lists so the designer sees the full picture at breadth.

**Source:** `_aggregate_insights(client_id)` — reads `insights` table, deduplicates each field (objection_patterns, qualification_signals, escalation_signals, kb_gaps, bot_failure_modes, suggested_fixes) into flat lists. This is the final approach — no separate patterns table, no extra LLM call.

**Why not a separate patterns table:**
- `_aggregate_insights` is free (SQL dedup at query time, no LLM call)
- A patterns table would require a separate LLM call to generate (~1,500 token input + generation cost), billed per recording or per refresh
- Call Evidence RAG (Component 5) already provides the grounding and specificity a patterns table was meant to add — at ~250 tokens and no LLM call

**DUMP growth risk and cap:**
With 5–20 recordings the dump is ~350–500 tokens. With 100+ recordings, unique phrasings of the same objection survive deduplication and the dump can reach 1,500+ tokens — negating the savings. Fix: cap each field to 10 items in `_aggregate_insights()`. This bounds the dump at ~500 tokens permanently regardless of recording volume, with no loss of signal (the 11th phrasing of "price too high" adds nothing the first 10 don't already say).

| | |
|---|---|
| Tokens (capped at 10/field) | ~350–500 |
| Cost at $3/MTok | ~$0.001 |

---

### Component 5 — Call Evidence (RAG)  ✗ NOT CACHED

**What it is:** Verbatim moments from this client's call recordings — real customer language, actual objections, specific escalation scenarios. Grounds system prompt wording.

**Source:** `transcript_chunks` table in Neon (pgvector)
**Loaded by:** `_retrieve_call_evidence(client_id, query, k=5)` in `designer.py`

| | |
|---|---|
| Tokens | ~250 |
| Cost at $3/MTok | $0.00075 |

---

### Component 6 — Use Case  ✗ NOT CACHED

**What it is:** The client's bot intent — what they want to build, including answers to clarifying questions gathered before plan generation.

**Source:** Dedicated input field on Build page, saved directly by user before conversation starts, stored in `sessions.use_case`. (The LLM still also updates it from conversation.)

**Why not cache:** Too mutable within a session (user answers questions iteratively). At ~200 tokens, the cache write cost exceeds savings unless sessions run 10+ turns.

**Compression — NOT worth it (rejected):** Summarizing Q&A into 3 sentences would save ~400 tokens (~$0.0012/turn) but costs an extra LLM call (~$0.01) plus latency and a new failure mode. Negative ROI unless sessions run very long. Leave the use case as-is.

| | |
|---|---|
| Tokens | ~150–300 |
| Cost at $3/MTok | $0.0006 |

---

### Component 7 — Bot KB (Knowledge Base)  ✦ CACHED Block 3

**What it is:** The client's own product knowledge — FAQs, pricing tables, scripts, escalation contacts. This is what drives real `system_prompt` and `kb_scaffold` content (not placeholders).

**Source:** Dedicated KB input textarea on Build page, stored in `bot_kb` table per client, fetched and placed in Cache Block 3. (Before this, users pasted KB into the chat, inflating every uncached turn.)

**Why cache it:** Stable for the entire session (hours, only changes if user clicks Save on KB). At <2,000 tokens, put the full KB in Cache Block 3 — pays back on turn 2. If >2,000 tokens, chunk + embed, RAG k=5.

> **This is a capability/quality win, NOT a cost reduction.** It only *reduces* cost if users were already pasting KB into the chat box (where it inflated every uncached turn). If the KB is genuinely new structured input, Block 3 *adds* tokens — but cheaply, and it's what lets the model write a real `system_prompt`/`kb_scaffold` instead of placeholders. Book it as quality, not savings.

| | |
|---|---|
| Tokens | ~500–2,000 |
| Cache write | $0.002–0.0075 (once per session) |
| Cache read | $0.00015–0.0006 per turn |

---

### Component 8 — Current Generated Plan  ✗ NOT CACHED

**What it is:** The full plan JSON — `workflow_blueprint`, `system_prompt`, `qualification_questions`, `objection_handling`, `escalation_rules`, `kb_scaffold`, `build_notes`. Required on patch turns so the LLM can edit against ground truth.

**Source:** `plans` table in Neon
**Nature:** Changes on every patch — cannot cache.

**Strategy:**
- Plan creation turn: nothing sent (LLM generates fresh)
- Patch turns: full plan sent (~4,000–6,000 tokens) — **keep it this way**

> **Input-side plan compression is REJECTED (correctness risk).** Sending only "changed sections + summary" breaks cross-references — a `@variable` defined in `qualification_questions` and consumed in `build_notes` must both be visible for a coherent patch. The safe win is on the *output* side: the model already returns only the changed keys. Pay the input read; never let the model patch a plan it can't fully see.

| | |
|---|---|
| Tokens (simple bot) | ~2,000 |
| Tokens (complex bot like Adani) | ~6,000–8,000 |
| Cost at $3/MTok | $0.006–0.024 |

---

### Component 9 — Recent Conversation Turns  ✗ NOT CACHED

**What it is:** Last 6 assistant/user turn texts (reply only — not full plan JSON). Short-term memory so the LLM doesn't repeat questions already answered.

**Source:** `turns` table in Neon via `get_turns(client_id, limit=6)`

| | |
|---|---|
| Tokens | ~600–800 |
| Cost at $3/MTok | $0.002 |

---

### Component 10 — User Message (this turn)  ✗ NOT CACHED

| | |
|---|---|
| Tokens | ~30–100 |
| Cost at $3/MTok | $0.0001 |

---

### Component 11 — Prompt Boilerplate  ✗ NOT CACHED TODAY → ✦ should be CACHED

**What it is:** The static instructional scaffolding inside the `converse()` user message —
NOT the data, the *instructions*: the `"You are the conversational architect..."` intro, the
section headers, the entire `"Decide the intent... Rules:"` block (~10 bullets), and the full
JSON output schema with key descriptions ([designer.py:352-415](intelligence/designer.py#L352-L415)).
The same scaffolding is duplicated in `generate_plan()` and `apply_patch()`.

**The problem:** ~700 identical tokens shipped in the **uncached** user message every single
turn, billed at full $3/MTok rate.

**The fix (highest-confidence, zero-risk optimization in this whole doc):** These instructions
don't interpolate per-turn data — only the data sections do. Split them:
- **System (cached) →** intro + rules + JSON output schema. Billed at $0.30/MTok and stops being
  re-billed at full rate every turn.
- **User (uncached) →** only the data-bearing sections (use case, insights, plan, etc.)

| | |
|---|---|
| Tokens | ~700 |
| Cost today (uncached) | $0.0021 per turn |
| Cost after move (cached read) | $0.0002 per turn |
| Savings | ~$0.0019 per turn, every turn, permanently |

---

## Caching Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ CACHE BLOCK 1 — Static                                          │
│   Canvas Grammar  (Builder Workflow nodes, schemas, patterns)   │
│   ~2,000 tokens  ·  $0.0006 per read after first call          │
├─────────────────────────────────────────────────────────────────┤
│ CACHE BLOCK 2 — Semi-static (changes on admin knowledge edits)  │
│   Platform Knowledge  (operational facts: Settings, AI Hub, BW) │
│   ~300–2,000 tokens  ·  $0.00009–0.0006 per read               │
├─────────────────────────────────────────────────────────────────┤
│ CACHE BLOCK 3 — Per-client (stable within a session)            │
│   Bot KB  (client's FAQs, scripts, product info)                │
│   ~500–2,000 tokens  ·  $0.00015–0.0006 per read               │
├─────────────────────────────────────────────────────────────────┤
│ CACHE BLOCK 4 — Static instructions                            │
│   Prompt boilerplate (intro + rules + JSON output schema)       │
│   ~700 tokens  ·  $0.0002 per read  (moved out of user message) │
└─────────────────────────────────────────────────────────────────┘

> **Cache TTL caveat:** the default ephemeral cache is **5 minutes**. This is a
> conversational tool — humans read a large plan and think before replying, so >5-min gaps
> between turns are common, and each one re-pays the *write* cost (not the cheap read). The
> "warm cache" patch numbers below assume warmth that won't always hold. If sessions have
> think-time gaps, switch the static blocks (1 and 4) to the **1-hour TTL** (2x write cost,
> but survives the gap and reads cheap all hour). Anthropic allows max 4 cache breakpoints —
> blocks 1–4 above use exactly 4.

USER MESSAGE — rebuilt every turn, never cached:
  Use Case            ~200 tokens   $0.0006
  Call Insights DUMP  ~350–500 tokens $0.001  (capped 10/field; grows unbounded without cap)
  Call Evidence RAG   ~250 tokens   $0.00075
  Bot Templates RAG   ~2,700 tokens $0.008  (k=3 on patches → $0.003)
  Current Plan        ~4,000 tokens $0.012  (future: ~1,500 on patches)
  Recent Turns x6     ~700 tokens   $0.002
  User Message        ~50 tokens    $0.0001
  Prompt boilerplate  ~700 tokens   $0.002  ← MOVE to cached Block 4
  ─────────────────────────────────────────
  Total uncached:     ~8,950 tokens $0.027  (~$0.025 after boilerplate move)
```

---

## Cost Per `converse()` Turn — Sonnet 4.6

**Pricing:** Input $3/MTok · Output $15/MTok · Cache write $3.75/MTok · Cache read $0.30/MTok

### Today (Blocks 1+2 cached, no Bot KB block, k=8 always)

| Scenario | Cache read | Uncached input | Output | **Total** |
|---|---|---|---|---|
| First call — cache write (plan creation) | $0.009 write | $0.030 | $0.105 | **~$0.14** |
| Patch turn — cache warm | $0.0007 | $0.027 | $0.030 | **~$0.058** |
| Patch — complex plan (8k tokens) | $0.0007 | $0.045 | $0.045 | **~$0.091** |

**Typical 5-turn session:** ~$0.14 + (4 × $0.06) = **~$0.38 per bot**

### Future (+ Block 3 Bot KB, k=3 on patches, compressed plan on patches)

| Scenario | Cache read | Uncached input | Output | **Total** |
|---|---|---|---|---|
| First call (cache write) | $0.012 write | $0.026 | $0.105 | **~$0.14** |
| Patch turn — all optimizations | $0.001 | $0.015 | $0.030 | **~$0.046** |

**Savings on patch turns: ~$0.012 (~20%)** — cumulative over many sessions.

---

## Batch API — SKIPPED (recommended)

**What it does:** 50% off input + output, results async (<1h–24h). For 20-recording insight
extraction it would drop ~$0.36 → ~$0.18.

**Why we skip it:**
- The discount is async — results land minutes to 24h later. The transcribe UX wants insights
  promptly after upload; trading that latency for ~$0.18/batch isn't worth it at current volume.
- It adds a polling/job-state code path and a new failure mode for a tiny absolute saving.
- Insight extraction already runs in a background pool concurrently — it's not the bottleneck.

**Revisit only if:** volume grows to hundreds of recordings/day where the absolute saving and
the natural batch cadence both make sense. Until then, keep the synchronous concurrent path.

---

## Output Token Reduction Plan

Output is 50–70% of every turn's cost (see top of doc). These are the levers, in priority order.

### 1. Protect patch-only-changed-keys (already implemented — guard it)
On patch turns the model returns ONLY the changed top-level keys, not the full plan. A simple
patch returns ~300 tokens instead of ~4,000. **This is the single biggest cost control in the
system.** Risk: a prompt regression could make it restate the whole plan. Add a test asserting
that a small edit ("change the greeting") produces a `patch` with 1–2 keys, not a `full_plan`.

### 2. Never regenerate `system_prompt` unless explicitly asked
`system_prompt` is the largest single field (can be 2,000+ tokens). The patch flow already
avoids touching unchanged keys — but reinforce in the prompt that `system_prompt` is only
rewritten when the user's request actually concerns bot behavior/persona, not for unrelated
edits (e.g. changing an escalation number must not re-emit `system_prompt`).

### 3. Lower `max_tokens` from 16000 to a realistic ceiling
`converse()` and `generate_plan()` use `max_tokens=16000`. Real plan creation output is
~6,000 tokens; patches are <2,000. The 16000 ceiling doesn't cost more for normal turns (you
pay per token emitted, not the ceiling) but it removes the guardrail against a runaway
generation billing 16k tokens (~$0.24) on a malformed turn. Set creation to ~8,000 and
patch/converse to ~4,000. Pure tail-risk protection.

### 4. Right-size the model per turn type
Patch turns are mechanical JSON edits — Sonnet is already appropriate; consider Haiku 4.5
($1/$5 vs $3/$15) for trivial patches if quality holds. Plan creation is where intelligence
matters → keep Sonnet, optionally add the Opus advisor (below) only there.

**Estimated impact:** items 1–2 are the difference between a ~$0.03 patch (changed keys only)
and a ~$0.09 patch (full plan re-emit). Items 3–4 are tail-risk + marginal. The headline:
output cost is controlled by *what you ask the model to write back*, and the current
patch-only design is correct — the work is guarding it, not changing it.

---

## Advisor Tool (Beta — `advisor-tool-2026-03-01`)

**What it is:** Pair Sonnet (executor) with Opus (advisor). Advisor sees the full transcript, produces a 400–700 token strategic plan, executor writes the full output. Everything happens inside one `/v1/messages` call — no extra round trips.

**Compatibility:** Sonnet 4.6 executor + Opus 4.8 advisor ✓

**Setup in `llm_client.py`:**
```python
tools = [{
    "type": "advisor_20260301",
    "name": "advisor",
    "model": "claude-opus-4-8",
    "max_tokens": 2048,                          # caps advisor output ~7x vs unset, near-zero truncation
    "caching": {"type": "ephemeral", "ttl": "5m"} # caches advisor's own transcript across calls
}]
# betas=["advisor-tool-2026-03-01"]
```

**When to call advisor in `converse()`:**
1. Before generating the first plan (architectural decision — which nodes, what flow)
2. When user requests a complex redesign ("restructure entire escalation flow")

**Cost per advisor call (Opus 4.8: $5/$25 input/output):**
- Advisor sees full transcript (~3,000 tokens) × $5/MTok = $0.015
- Advisor output (~600 tokens with max_tokens=2048) × $25/MTok = $0.015
- **Per advisor call: ~$0.030**

**Net cost comparison:**

| Scenario | Sonnet only | Sonnet + Opus advisor (1 call) |
|---|---|---|
| First plan | ~$0.14 | ~$0.17 |
| Complex patch | ~$0.09 | ~$0.12 |
| Simple patch (no advisor) | ~$0.06 | ~$0.06 (no change) |

**Verdict:** +$0.03 per advisor call for near-Opus quality on design decisions. Use for plan creation and complex redesigns. Skip for simple patches (k=3 RAG + Sonnet is sufficient).

---

## Token Budget Summary

| # | Component | Tokens | Cached? | Cost/turn (warm) |
|---|---|---|---|---|
| 1 | Canvas Grammar | ~2,000 | ✓ Block 1 | $0.0006 |
| 2 | Platform Knowledge | ~500 | ✓ Block 2 | $0.00015 |
| 3 | Bot KB | ~1,000 | ✓ Block 3 | $0.0003 |
| 4 | Bot Templates RAG | ~2,700 / ~1,000 | ✗ | $0.008 / $0.003 |
| 5 | Call Insights (DUMP) | ~350–500 (cap 10/field) | ✗ | $0.001 |
| 6 | Call Evidence | ~250 | ✗ | $0.00075 |
| 7 | Use Case | ~200 | ✗ | $0.0006 |
| 8 | Current Plan | ~4,000 | ✗ | $0.012 |
| 9 | Recent Turns | ~700 | ✗ | $0.002 |
| 10 | User Message | ~50 | ✗ | $0.00015 |
| 11 | Prompt Boilerplate | ~700 | ✗ today → ✓ Block 4 | $0.0021 → $0.0002 |
| — | Output (patch, changed keys) | ~300–2,000 | — | $0.0045–0.030 |
| — | Output (plan, full) | ~6,000 | — | $0.090 |
| | **TOTAL (patch, warm cache, today)** | | | **~$0.058** |
| | **TOTAL (plan creation, cache write)** | | | **~$0.14** |

### Final recommended changes (do these)
1. **Move boilerplate → cached system Block 4** — zero risk, ~$0.0019/turn, shrinks every turn.
2. **k=8 → k=3 bot templates on patch turns** — zero risk, ~$0.005/turn.
3. **Add a regression test guarding patch-only-changed-keys** — protects the biggest cost lever.
4. **Lower `max_tokens`** (creation 8k, patch/converse 4k) — tail-risk guardrail.
5. **1-hour cache TTL** on static blocks if sessions have think-time gaps.

### Rejected (do NOT do)
- Batch API (async latency not worth it at current volume)
- Input-side plan section compression (breaks cross-references)
- Use-case 3-sentence summarization (negative ROI)
