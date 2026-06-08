# SPEC: Conversational Workflow Designer (one box, remembered use case)

> Build target. Self-contained — an implementer (e.g. Sonnet) can build from this file alone.
> Scope: the **intelligence plane only** (`app.py` Tab 1, `intelligence/designer.py`, `shared/db.py`).
> The orchestrator, dashboard, and `transcription/engine.py` are **out of scope / unchanged**.

---

## 1. Goal
Replace the multi-step Tab 1 flow (separate use-case field, clarifying-question widgets, generate-plan button, patch box) with **ONE conversational command box**. The use case is entered once, **remembered**, and never retyped. Every message is intent-routed by a single method `WorkflowDesigner.converse()`.

It must deliver, all through the one box:
1. **First message** → set the use case (remembered) and draft an initial plan (or ask clarifying questions inline).
2. **Patches / changes** → "add a VOICE_WEBHOOK at the start", "here is system prompt X, patch mine".
3. **Open-ended questions** → "the bot fails to recognise speech, what to do?" → advice only, no plan change.
4. **Rescan** → after uploading more recordings, "check the new recordings for insights/patterns" → fold new insights into the plan as a delta, without retyping the use case.
5. **Token discipline** — when a plan already exists, emit only the changed keys (delta), never rebuild the whole plan.

---

## 2. Architecture
```
ONE command box (st.text_area + Send)
        │ message
        ▼
app.py submit handler
  1. transcribe any NEW uploaded files (dedup) → insights land in DB
  2. result = designer.converse(client_id, message)
  3. render: reply panel · remembered use-case chip · plan below
        │
        ▼
WorkflowDesigner.converse()  ← the brain (1 cached LLM call)
  loads use_case + active plan + ALL insights + recent turns
  routes intent → set use_case / create plan / patch / advice / rescan
  persists use_case, plan changes (version + patch row), and the turn
```
Existing helpers are reused as building blocks: `_canvas_system()`, `_aggregate_insights()`, `generate_plan()`, `apply_patch()` internals, `save_plan/update_plan/save_patch/get_plan/get_patches`, `_render_plan()`. Prompt caching is already in `shared/llm_client.py` (system prompt cached), so each turn's large canvas system is billed cheaply after the first.

---

## 3. `intelligence/designer.py` — add `converse()`

### 3.1 Signature & return
```python
def converse(self, client_id: str, message: str) -> dict:
    """One conversational turn. Routes intent, updates remembered use case + plan, returns a reply.

    Returns:
      {
        "reply":        str,            # text to show the user (advice / clarifying questions / what-changed)
        "use_case":     str,            # current remembered use case (possibly updated this turn)
        "mode":         str,            # "use_case" | "plan" | "patch" | "advice" | "rescan"
        "plan":         dict | None,    # full current plan after this turn (for rendering)
        "plan_id":      str | None,
        "plan_changed": bool,
        "diff":         dict | None,    # {key: {"before":..., "after":...}} when a patch applied
        "version":      int | None,     # new plan version when patched/created
      }
    """
```

### 3.2 Internal steps
1. `sess = load_session(client_id)` → `use_case` (may be `""`), `plan_id`.
2. `current_plan = get_plan(plan_id)["plan"] if plan_id else None`; `current_version = get_plan(...)["version"]` if present.
3. `insights = _aggregate_insights(client_id, self._db)` (already merges ALL DB insights — old + newly transcribed).
4. `recent = get_turns(client_id, limit=6)` (for light conversational context).
5. **One LLM call**, `system=_canvas_system()` (cached), `complete_json(..., max_tokens=16000)`. User prompt = §3.3. It must return the JSON in §3.4.
6. **Apply** per `plan_action`:
   - `create` → `plan_id = save_plan({"client_id":client_id, "plan":full_plan})`; `current_plan=full_plan`; `plan_changed=True`; `mode="plan"`; `version=1`.
   - `patch` (only if `current_plan` exists and `patch` non-empty) → `new_plan = {**current_plan, **patch}`; `update_plan(plan_id, new_plan)`; `save_patch({"plan_id":plan_id, "version":current_version+1, "admin_request":message, "patch":patch, "llm_reasoning":reply})`; build `diff`; `plan_changed=True`; `version=current_version+1`; `mode = intent` (`"patch"` or `"rescan"`).
   - else → advice; **no** plan write, **no** version bump; `mode="advice"`; `plan_changed=False`.
7. **Persist always:** `save_session(client_id, questions=sess.get("questions",[]), answers=sess.get("answers",{}), plan_id=plan_id, use_case=returned_use_case)`; `save_turn(client_id, "user", message)`; `save_turn(client_id, "assistant", reply, mode=mode)`.
8. Return the dict in §3.1.

**Intent → action mapping** (the LLM sets `intent`; the code maps to `plan_action`):
- `use_case` (first/refined intent, no plan yet) → `create` if the model is confident, else advice (it asks clarifying questions in `reply`).
- `plan` / `rescan` with no current plan → `create`. With a current plan → `patch` (delta from new insights/answers).
- `patch` → `patch`.
- `advice` → none.

### 3.3 User-prompt skeleton (for the converse LLM call)
```
You are the conversational architect for a Chat360 voice-bot workflow. Hold a running design
session with one human via a single text box. Remember the use case; never ask them to retype it.

REMEMBERED USE CASE:
{use_case or "(none yet — the user's message likely IS the use case)"}

CALL INSIGHTS (aggregated from all their real agent recordings):
{json insights}

CURRENT PLAN:
{json current_plan or "(no plan yet)"}

RECENT TURNS:
{recent turns, role: content}

USER MESSAGE:
{message}

Decide the intent and respond. Rules:
- If there is no use case yet, treat the message as the use case (store it in "use_case") and either
  draft a first plan OR ask 2–4 clarifying questions inside "reply" if key facts are missing.
- If a plan already exists and the user asks for a change, return ONLY the top-level keys that change
  in "patch" — never restate unchanged keys (saves tokens). Put a one-paragraph what-changed in "reply".
- If the user asks an open-ended question or for advice ("the bot fails to recognise speech, what to
  do?"), set intent="advice", patch=null, full_plan=null, and put the guidance in "reply". Do NOT change
  the plan unless they explicitly instruct a change.
- If the user says to incorporate new recordings ("check the new recordings for insights/patterns"),
  set intent="rescan" and fold the newest insight patterns into the plan as a "patch".
- Cross-language: you may draw insight PATTERNS from recordings in any language (Marathi etc.), but only
  build the bot for the languages the user specifies (e.g. keep build_notes.language = Hindi/English).
- Clarifying questions you need answered go in "reply"; the user answers them in the next message, and
  you fold the answer in then — do not repeat questions already answered in RECENT TURNS.
- Plan keys, when creating/patching, are exactly: workflow_blueprint, system_prompt,
  qualification_questions, objection_handling, escalation_rules, kb_scaffold, build_notes.
  Ground everything in the canvas reference in the system prompt; never invent node types.

Return JSON only.
```

### 3.4 Required JSON shape from the LLM
```json
{
  "intent": "use_case | plan | patch | advice | rescan",
  "use_case": "the current (possibly updated) use case text",
  "reply": "what to show the user — advice, clarifying questions, or what-changed summary",
  "plan_action": "none | create | patch",
  "full_plan": { /* full plan object, only when plan_action == create */ } ,
  "patch": { /* changed top-level keys only, only when plan_action == patch */ }
}
```
`complete_json` already strips markdown fences and retries once on parse failure — rely on it.

Keep `generate_plan`, `apply_patch`, `generate_clarifying_questions`, `_aggregate_insights`, `_canvas_system` as-is (converse orchestrates / mirrors them). The `"Rebuild from scratch"` button calls `generate_plan(client_id, use_case, answers=[])`.

---

## 4. `shared/db.py`

### 4.1 Migration (in `init_db`, after the `executescript`)
```sql
CREATE TABLE IF NOT EXISTS conversation_turns (
    id         TEXT PRIMARY KEY,
    client_id  TEXT NOT NULL,
    role       TEXT NOT NULL,          -- 'user' | 'assistant'
    content    TEXT NOT NULL,
    mode       TEXT,                   -- intent/mode for assistant turns
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS conversation_turns_client_idx ON conversation_turns(client_id, created_at);
```
And the safe column add (wrap in try/except like the existing `plan_id` add):
```python
try:
    conn.execute("ALTER TABLE workflow_sessions ADD COLUMN use_case TEXT")
    conn.commit()
except Exception:
    pass
```

### 4.2 Function additions / edits
```python
def get_transcript_by_filename(client_id, filename, path=DB_PATH) -> dict | None:
    # SELECT * FROM transcripts WHERE client_id=? AND filename=? LIMIT 1 ; deserialize segments

# EDIT existing save_session / load_session to carry use_case (named-column INSERT already used):
def save_session(client_id, questions, answers, plan_id=None, use_case=None, path=DB_PATH) -> None
def load_session(client_id, path=DB_PATH) -> dict   # add "use_case": row.use_case (default "")

def save_turn(client_id, role, content, mode=None, path=DB_PATH) -> str   # uuid id, _now() ts
def get_turns(client_id, limit=None, path=DB_PATH) -> list[dict]          # ORDER BY created_at ASC; tail `limit`
```
`load_session` empty default becomes `{"questions": [], "answers": {}, "plan_id": None, "use_case": ""}`.

---

## 5. `app.py` — Tab 1 redesign

### 5.1 session_state keys
`client_id`, `use_case`, `plan_id`, `current_plan`, `last_reply`, `last_diff`, `last_version`, `_session_loaded_for`. (Drop reliance on `questions`/`answers` widgets.)

### 5.2 `_init_state` restore (on first load / client change)
```python
saved = load_session(client_id)
st.session_state["use_case"] = saved["use_case"]
if saved["plan_id"]:
    st.session_state["plan_id"] = saved["plan_id"]
    st.session_state["current_plan"] = get_plan(saved["plan_id"])["plan"]
turns = get_turns(client_id, limit=2)
st.session_state["last_reply"] = next((t["content"] for t in reversed(turns) if t["role"]=="assistant"), "")
```

### 5.3 Layout (top → bottom)
1. **Upload widget** (`st.file_uploader`, multi, type wav/mp3/m4a/aac) — attach recordings.
2. **Remembered use case** — `st.expander("🎯 Use case", expanded=not use_case)`; editable `text_area` bound to `st.session_state["use_case"]`; on change, `save_session(... use_case=...)`.
3. **Command box** — `st.text_area("Message", key="cmd", placeholder=...)` + `st.button("Send", type="primary")`. Placeholder adapts: no plan → "Describe your use case…"; plan exists → "Ask for a change, ask a question, or say 'check the new recordings for insights'…".
4. **Reply panel** — `st.session_state["last_reply"]`; if `last_diff`, show changed keys before/after; if `last_version`, show "v{n}".
5. **Plan** — `if current_plan: _render_plan(current_plan)`.
6. **Version History** expander — `get_patches(plan_id)`.
7. **"🔄 Rebuild plan from scratch"** button → `generate_plan(client_id, use_case, [])`, replace plan (escape hatch vs delta drift).

### 5.4 Send handler
```python
if send and message.strip():
    # 1. dedup-transcribe new uploads
    for f in uploaded_files or []:
        if get_transcript_by_filename(client_id, f.name):
            st.info(f"↺ Skipped (already processed): {f.name}")
            continue
        # write temp file, engine.transcribe(tmp, client_id)  (existing pattern)
    # 2. converse
    res = designer.converse(client_id, message)
    # 3. update session_state
    st.session_state.update(use_case=res["use_case"], plan_id=res["plan_id"],
                            current_plan=res["plan"], last_reply=res["reply"],
                            last_diff=res["diff"], last_version=res["version"])
    st.rerun()
```

---

## 6. Reuse map (do NOT reinvent)
| Need | Use |
|---|---|
| Canvas system prompt (cached) | `intelligence/designer.py::_canvas_system()` |
| Merge all client insights | `_aggregate_insights(client_id, db)` |
| Save / fetch / version plan | `save_plan`, `get_plan`, `update_plan`, `save_patch`, `get_patches` (shared/db.py) |
| Render a plan | `app.py::_render_plan(plan)` |
| LLM call + JSON parse + cache | `shared/llm_client.py::LLMClient.complete_json` (system already cached; check `last_usage`) |
| Transcribe + extract insights | `transcription/engine.py::TranscriptionEngine.transcribe()` (unchanged) |

## 7. Constraints
- All API keys from `.env` only; model from `ANTHROPIC_MODEL` (never hardcoded).
- Single LLM call per turn; rely on prompt caching (don't rebuild/duplicate the system prompt).
- Never emit a full plan when patching — `patch` holds changed top-level keys only.
- Advice turns must not write the plan or bump the version.
- Filename-based dedup is acceptable (content-hash is a future refinement).

## 8. Build order (subagent-workflow waves)
- **Wave 1 — `shared/db.py`** (no deps): `get_transcript_by_filename`; `use_case` column + `save_session`/`load_session` carry; `conversation_turns` table + `save_turn`/`get_turns`. Sanity: import + round-trip a session with use_case + a couple turns.
- **Wave 2 — `intelligence/designer.py`** (deps: Wave 1): add `converse()`. Sanity: with a seeded client, `converse("...use case...")` creates a plan; a follow-up "add a VOICE_WEBHOOK…" returns a patch (changed keys only); a "what should I do about X?" returns advice with empty patch.
- **Wave 3 — `app.py`** (deps: Waves 1–2): Tab 1 one-box redesign + Send handler + restore + rebuild button. Sanity: `python -c "import ast; ast.parse(open('app.py').read())"` and a manual `streamlit run` pass.

## 9. Acceptance tests
1. **Remembered use case:** set once → plan drafts; refresh → use case + plan + last reply persist; never re-prompted for the use case.
2. **Dedup:** re-upload old + 1 new recording + "check new recordings" → only the new file runs the insight LLM ("Skipped" for the rest); plan folds new patterns (delta); version bumps.
3. **Additive questions:** agent asks a clarifying question in its reply; answer in the same box; folded in, not re-asked.
4. **Incremental delta:** with a plan present, a change request emits only changed keys (`designer._llm.last_usage.output_tokens` ≪ a full build); `plan_patches` gains a row.
5. **Auto-classify:** "the bot fails to recognise speech, what to do?" → advice only, no version bump; "add a VOICE_WEBHOOK at the start by @caller_number" → patch + version + diff; "read Marathi recordings for patterns but keep the bot Hindi/English" → advice + a `build_notes.language` patch.
6. **Caching:** `designer._llm.last_usage.cache_read_input_tokens > 0` on the 2nd+ turn in a session.

## 10. Out of scope
- Orchestrator, dashboard, telephony, seeding — unchanged.
- Full chat-thread transcript UI (data is persisted in `conversation_turns`; the thread view is a later/prod addition).
- Content-hash dedup, multi-account isolation beyond `client_id`.
