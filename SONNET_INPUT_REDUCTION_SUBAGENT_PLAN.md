# Subagent Plan — Input Cost Reduction + Use Case / Bot KB Inputs

> For: Sonnet executor agents. Scope: everything in `INPUT_COST_REDUCTION_EXPLAINED.md`
> that is implementable now. **Output Token Reduction Plan is explicitly OUT OF SCOPE** —
> implement it later in a separate pass.
>
> Reference doc: `INPUT_COST_REDUCTION_EXPLAINED.md` (read it first).

---

## What this plan delivers

| Item | Component in doc | File(s) |
|---|---|---|
| Bot KB table + CRUD | 7 | `shared/db.py` |
| 1-hour TTL support on cache blocks | TTL caveat | `shared/llm_client.py` |
| Boilerplate → cached system Block 4 | 11 | `intelligence/designer.py` |
| Bot KB → cached system Block 3 | 7 | `intelligence/designer.py` |
| Bot Templates k=8 → k=3 on patch turns | 3 | `intelligence/designer.py` |
| Call-insights DUMP cap (10/field) | 4 | `intelligence/designer.py` |
| 1h TTL on static blocks (1 & 4) | TTL caveat | `intelligence/designer.py` |
| Use Case + Bot KB API endpoints | 6, 7 | `intelligence/api.py` |
| Use Case + Bot KB inputs on Build page | 6, 7 | `dashboard/app/intelligence/build/page.tsx` |

**Not in scope (later):** Output Token Reduction Plan (max_tokens lowering, patch-only
regression test, system_prompt regeneration guard, model right-sizing), Advisor Tool,
Batch API (rejected), input-side plan compression (rejected), use-case summarization (rejected).

---

## Global constraints for EVERY subagent

- NO `Co-Authored-By` line in commits.
- Commit ONLY your own file(s), never `git add .`.
- Single-line commit message, verb from: `add, build, wire, fix, update`.
  ```
  git commit -m "$(cat <<'EOF'
  <verb> <module>: <one-line description>
  EOF
  )"
  ```
- Read the existing file fully before editing. Match surrounding style.
- Run a sanity check (python import / `npx tsc --noEmit`) before committing.
- Do NOT touch any file another subagent owns.

---

## Interfaces contract (already exist — do not redefine)

```python
# shared/db.py — existing
init_db(path: str = DB_PATH) -> None
get_insights(client_id: str, path=DB_PATH) -> list[dict]   # fields: objection_patterns,
    # qualification_signals, escalation_signals, kb_gaps, raw_insights_json
    # (=> bot_failure_modes, suggested_fixes), agent_score, sentiment
save_session(client_id, questions: list, answers: dict, plan_id=None, use_case=None, path=DB_PATH) -> None
load_session(client_id, path=DB_PATH) -> dict   # {questions, answers, plan_id, use_case}
get_knowledge(status="active", path=DB_PATH) -> list[dict]

# shared/llm_client.py — existing
LLMClient().complete(system, user, max_tokens=4096, cache_system=True) -> str
LLMClient().complete_json(system, user, max_tokens=4096) -> dict
# system may be a list of {"text": str, "cache": bool} blocks → rendered with cache_control
```

```python
# shared/db.py — NEW (Wave 1, SA-A produces these)
get_kb(client_id: str, path=DB_PATH) -> dict | None   # {"content": str, "updated_at": str} or None
upsert_kb(client_id: str, content: str, path=DB_PATH) -> None
```

---

## WAVE 1 — Foundation (Parallel — no inter-dependencies)

### SA-A — `shared/db.py`
Add the Bot KB table and its two accessors.

1. In `init_db()`, add a `CREATE TABLE IF NOT EXISTS bot_kb` to the DDL list (mirror the
   `workflow_sessions` style — `client_id TEXT PRIMARY KEY`):
   ```sql
   CREATE TABLE IF NOT EXISTS bot_kb (
       client_id  TEXT PRIMARY KEY,
       content    TEXT NOT NULL DEFAULT '',
       updated_at TEXT NOT NULL
   )
   ```
2. Add `get_kb(client_id, path=DB_PATH) -> dict | None` — SELECT content, updated_at;
   return `None` if no row.
3. Add `upsert_kb(client_id, content, path=DB_PATH) -> None` — INSERT ... ON CONFLICT
   (client_id) DO UPDATE (mirror `save_session`'s upsert pattern, use `_now()` for updated_at).

Sanity: `python -c "import shared.db"`.
Commit: `add db: bot_kb table with get_kb/upsert_kb`

### SA-B — `shared/llm_client.py`
Add optional per-block cache TTL so static blocks can use the 1-hour cache.

- In `complete()`, the Anthropic branch currently renders cache blocks as
  `{"cache_control": {"type": "ephemeral"}}`. Extend the list-of-blocks path so a block may
  carry an optional `"ttl"` key:
  ```python
  for b in system if b.get("text"):
      block = {"type": "text", "text": b["text"]}
      if b.get("cache"):
          cc = {"type": "ephemeral"}
          if b.get("ttl"):            # "1h" or "5m"
              cc["ttl"] = b["ttl"]
          block["cache_control"] = cc
  ```
- Keep the single-string `cache_system=True` path unchanged.
- OpenAI/Azure branches already ignore cache blocks — leave them.

Sanity: `python -c "import shared.llm_client"`.
Commit: `update llm_client: optional per-block cache ttl`

---

## WAVE 2 — Backend logic (Parallel — depends on Wave 1)

### SA-C — `intelligence/designer.py`  (the core input-reduction work)
This file owns ALL the per-turn context assembly. Five changes, all in this one file.

**(1) Cap the call-insights DUMP at 10 items/field.**
In `_aggregate_insights()`, before returning, truncate each list field to 10 items
(`sorted(...)[:10]`). Bounds the dump at ~500 tokens regardless of recording volume.

**(2) Move prompt boilerplate → cached system block (Block 4).**
The `converse()` user prompt mixes static instructions with per-turn data. Split it:
- Extract the STATIC text — the `"You are the conversational architect..."` intro, the
  `"Decide the intent and respond. Rules:"` bullet block, and the `"Return JSON with exactly
  these keys:"` schema — into a module-level constant `_CONVERSE_INSTRUCTIONS`.
- Append it to the `system` list as a cached block: `{"text": _CONVERSE_INSTRUCTIONS, "cache": True, "ttl": "1h"}`.
- The `user` string keeps ONLY data-bearing sections (use case, insights, bot failures,
  call evidence, rag examples, current plan, recent turns, user message).
- ⚠️ Constraint: the static text must NOT interpolate any per-turn variable. If any rule
  references the data, keep that one line in the user message.

**(3) Add 1h TTL to the existing static system blocks.**
`_canvas_system()` block → `{"text": _canvas_system(), "cache": True, "ttl": "1h"}`.
Platform Knowledge block stays `"cache": True` WITHOUT ttl (semi-static, default 5m is fine).

**(4) Inject Bot KB as cached Block 3.**
- Import `get_kb` from `shared.db`.
- In `converse()`, fetch `kb = get_kb(client_id)`. If `kb and kb["content"].strip()`, append
  a cached block to `system`: `{"text": "## Client Bot Knowledge Base\n" + kb["content"], "cache": True}`
  (per-client, default 5m TTL — do NOT use 1h; it changes between clients).
- Order the system list: `[canvas (1h), platform_knowledge (5m), bot_kb (5m), instructions (1h)]`.
  (Cache breakpoints: max 4 — this is exactly 4 when KB is present.)

**(5) Bot Templates k=8 → k=3 on patch turns.**
In `converse()`, `_retrieve_examples()` currently uses `k=8`. Use `k=3` when a plan already
exists (`current_plan` is truthy), else `k=8`:
```python
_k = 3 if current_plan else 8
_rag_examples = _retrieve_examples(_rag_query, k=_k)
```

> Do NOT change `generate_plan()` or `apply_patch()` in this pass beyond what's needed — those
> are separate entry points. Keep their behavior; only `converse()` and `_aggregate_insights()`
> change here. (If `_CONVERSE_INSTRUCTIONS` extraction is clean, do not also refactor the other
> two methods' prompts — that's scope creep.)

Sanity: `python -c "import intelligence.designer"`.
Commit: `update designer: cache boilerplate+KB, cap insights, k=3 on patch`

### SA-D — `intelligence/api.py`
Add Use Case and Bot KB endpoints. Mirror existing endpoint style (`Depends(auth)`).

- Import `load_session, save_session, get_kb, upsert_kb` from `shared.db`.
- `GET /session/{client_id}` → return `{use_case, plan_id}` from `load_session`.
- `PATCH /session/{client_id}` body `{use_case: str}` → call `save_session(client_id,
  sess["questions"], sess["answers"], plan_id=sess["plan_id"], use_case=new_use_case)`
  (load existing session first so questions/answers/plan_id are preserved). Return `{ok: True}`.
- `GET /kb/{client_id}` → `get_kb`; return `{content: "", updated_at: null}` if None.
- `POST /kb/{client_id}` body `{content: str}` → `upsert_kb`; return `{ok: True}`.

Sanity: `python -c "import intelligence.api"`.
Commit: `add api: session and bot_kb endpoints`

---

## WAVE 3 — Frontend (depends on Wave 2)

### SA-E — `dashboard/app/intelligence/build/page.tsx`
Add two inputs above/around the chat. Match existing Tailwind + fetch patterns in the file
(reuse the existing API base URL + `x-api-key` header helper already used for `/converse`).

- **Use Case** textarea + Save button, placed above the chat column.
  - On mount: `GET /session/{clientId}` → prefill textarea from `use_case`.
  - Save: `PATCH /session/{clientId}` with `{use_case}`. Show a saved indicator.
- **Knowledge Base** collapsible section (below Use Case), textarea + Save button.
  - On mount: `GET /kb/{clientId}` → prefill from `content`.
  - Save: `POST /kb/{clientId}` with `{content}`. Show a saved indicator.
- Both read `clientId` from the existing IntelligenceContext. No new global state needed.

Sanity: `cd dashboard && npx tsc --noEmit` (clean).
Commit: `add build-page: use case and knowledge base inputs`

---

## Execution order & failure handling

1. Run **Wave 1** (SA-A, SA-B) in parallel. Both must succeed.
2. Run **Wave 2** (SA-C, SA-D) in parallel. Both must succeed.
3. Run **Wave 3** (SA-E).

If any subagent fails: pause, report, fix only that subagent, then continue. Do not start a
wave until the previous wave is fully green.

## Post-merge manual verification
1. Restart backend (tables auto-created via `init_db()` on startup).
2. Build page: type a use case → Save → reload → persists.
3. Build page: type KB → Save → reload → persists.
4. Send a `/converse` message → confirm a plan generates and KB content is reflected.
5. (Optional) Inspect Anthropic usage: 2nd turn within 5 min should show `cache_read_input_tokens`
   covering canvas grammar + instructions blocks.
