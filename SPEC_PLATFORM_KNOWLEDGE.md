# SPEC: Platform Knowledge Layer (admin-curated, cached, pluggable gate)

> Build target. Self-contained — an implementer (e.g. Sonnet) can build from this file alone.
> Branch: `feat/conversational-designer`. Builds on the conversational designer (`converse()` already exists).
> Scope: intelligence plane (`shared/`, `intelligence/designer.py`, `app.py`, `seed/`). Orchestrator/dashboard unchanged.

---

## 1. Goal & rationale
Give the intelligence a **global, growable knowledge base** of Chat360 platform facts (call disconnection, latency/filler config, required Azure LLM engine, interruption toggle, …) that is injected into the system prompt like `best_bots.json`, so **every** build by **every** person in prod inherits it. The model is stateless — it does not learn by "nudging weights" (no fine-tuning for Claude 4.x; wrong tool anyway). Learning = a curated store + system-prompt injection, governed by the Chat360 team. Token-aware: inject the (small) knowledge as a **2nd cache breakpoint** after `best_bots` so the 10K canvas stays warm; move to RAG only when the store grows large.

Seeding the four facts below also fixes the user's points 2 & 3: once known, the designer bakes End-Flow disconnection and filler config into every generated plan.

---

## 2. `shared/auth.py` (NEW) — authorization seam (NOT authentication)
```python
"""Authorization seam for global platform-knowledge writes.

Standalone/demo: an admin is any client_id in ADMIN_CLIENT_IDS (env, comma-separated).
Production (embedded in Chat360): rewire is_admin() to read Chat360's authenticated role claim.
This is the SINGLE integration point — do not build a login system here.
"""
import os

def _admin_ids() -> set:
    raw = os.getenv("ADMIN_CLIENT_IDS", "")
    return {x.strip() for x in raw.split(",") if x.strip()}

def is_admin(actor: str) -> bool:
    """True if `actor` may write global platform knowledge."""
    return bool(actor) and actor in _admin_ids()
```
Add `ADMIN_CLIENT_IDS=` to `.env.example` with a comment that prod wires this to the Chat360 role.

---

## 3. `shared/db.py` — knowledge store

### 3.1 Migration (inside `init_db`'s `executescript`, alongside the other tables)
```sql
        CREATE TABLE IF NOT EXISTS platform_knowledge (
            id         TEXT PRIMARY KEY,
            topic      TEXT NOT NULL,
            fact       TEXT NOT NULL,
            source     TEXT,
            status     TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        );
```

### 3.2 Functions (match existing style — `str(uuid.uuid4())`, `_now()`, `_row_to_dict`)
```python
def add_knowledge(topic, fact, source=None, status="active", path=DB_PATH) -> str:
    # INSERT a row; return id.

def get_knowledge(status="active", path=DB_PATH) -> list:
    # SELECT * FROM platform_knowledge WHERE status=? ORDER BY created_at ASC ; return list of dicts.
    # If status is None, return ALL rows (admin panel needs active + pending).

def set_knowledge_status(knowledge_id, status, path=DB_PATH) -> None:
    # UPDATE platform_knowledge SET status=? WHERE id=?

def delete_knowledge(knowledge_id, path=DB_PATH) -> None:
    # DELETE FROM platform_knowledge WHERE id=?
```

---

## 4. `shared/llm_client.py` — multi-block cached system
Today `complete(system: str, ...)` wraps a string system in one `cache_control` block. Extend it so `system` may also be a **list** of `{"text": str, "cache": bool}` blocks.

```python
def complete(self, system, user, max_tokens=4096, cache_system=True) -> str:
    if self.provider == "anthropic":
        if isinstance(system, list):
            system_param = [
                {"type": "text", "text": b["text"],
                 **({"cache_control": {"type": "ephemeral"}} if b.get("cache") else {})}
                for b in system if b.get("text")
            ]
        elif cache_system and system:
            system_param = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        else:
            system_param = system
        response = self._client.messages.create(
            model=self.model, max_tokens=max_tokens,
            system=system_param, messages=[{"role": "user", "content": user}],
        )
        self.last_usage = getattr(response, "usage", None)
        return response.content[0].text
    raise NotImplementedError(...)
```
`complete_json(system, user, max_tokens)` appends the JSON instruction. Make it handle both:
- if `system` is a `str`: `json_system = system + "\n\nRespond with valid JSON only. No markdown fences, no explanation."` (as today).
- if `system` is a `list`: copy it and append the JSON instruction to the **last** block's text (so the cache boundary stays on the knowledge block; the suffix is constant → still cacheable):
  ```python
  json_system = system[:-1] + [{**system[-1], "text": system[-1]["text"] + JSON_SUFFIX}]
  ```
Then call `self.complete(json_system, user, max_tokens)`. Keep the `_extract_json` + one-retry behavior unchanged. Max 4 breakpoints (we use 2) — safe.

---

## 5. `intelligence/designer.py` — platform-aware calls

### 5.1 Knowledge block
```python
def _platform_knowledge_block(db_path: str) -> str:
    """Render active platform knowledge as a system-prompt section (empty string if none)."""
    rows = get_knowledge("active", path=db_path)   # import get_knowledge from shared.db
    if not rows:
        return ""
    lines = "\n".join(f"- [{r['topic']}] {r['fact']}" for r in rows)
    return ("## Learned Chat360 Platform Knowledge\n"
            "Apply these platform facts to every design unless the user overrides them.\n" + lines)
```

### 5.2 Two-block system at every LLM call site
In `converse`, `generate_plan`, and `apply_patch`, replace `system = _canvas_system()` with:
```python
system = [
    {"text": _canvas_system(), "cache": True},
    {"text": _platform_knowledge_block(self._db), "cache": True},
]
```
(`_canvas_system()` still returns the canvas string; the knowledge is block 2. `complete_json` accepts the list.)

### 5.3 `converse()` — teach + auto-propose
Import `is_admin` from `shared.auth` and `add_knowledge` from `shared.db`.

Add to the converse user-prompt rules:
```
- If the user is teaching a DURABLE Chat360 PLATFORM fact (applies to ALL bots, not just this client —
  e.g. an engine requirement, a how-to-configure rule, a disconnection/latency technique), set
  intent="teach" and put it in "proposed_knowledge". If you merely NOTICE such a generalizable platform
  fact during another request, also add it to "proposed_knowledge" (do not change intent for that).
  Client-specific project details belong in use_case, NOT in proposed_knowledge.
```
Add to the required JSON shape: `"proposed_knowledge": [ {"topic": "...", "fact": "..."} ]` (default `[]`).

Apply logic (after the LLM call, before persisting the turn): for each item in `proposed_knowledge`:
```python
admin = is_admin(client_id)
status = "active" if (intent == "teach" and admin) else "pending"
add_knowledge(item["topic"], item["fact"], source=client_id, status=status, path=self._db)
```
- `intent=="teach"` + admin → fact goes **live** (`active`); reflect in `reply`.
- `intent=="teach"` + non-admin → store as `pending` and the `reply` should say platform knowledge is curated by the Chat360 team (the LLM is told this via a rule; also enforce in code by forcing `pending`).
- auto-noticed (intent≠teach) → `pending` for admin review; `reply` notes it was flagged.

Return dict is unchanged except `mode` may be `"teach"` when a teach was applied.

---

## 6. `app.py` — admin-only knowledge panel
Import `is_admin` from `shared.auth` and `get_knowledge, set_knowledge_status, delete_knowledge` from `shared.db`.

In Tab 1, render ONLY when `is_admin(st.session_state["client_id"])`:
```python
if is_admin(client_id):
    with st.expander("🛠 Platform knowledge (Chat360 team)", expanded=False):
        # Active facts
        for k in get_knowledge("active", path=DB_PATH):
            c1, c2 = st.columns([8, 1])
            c1.markdown(f"**[{k['topic']}]** {k['fact']}  \n<small>{k['source']} · {k['created_at'][:16]}</small>",
                        unsafe_allow_html=True)
            if c2.button("🗑", key=f"del_{k['id']}"):
                delete_knowledge(k["id"], path=DB_PATH); st.rerun()
        # Pending queue
        pending = get_knowledge("pending", path=DB_PATH)
        if pending:
            st.markdown("**Pending review**")
            for k in pending:
                c1, c2, c3 = st.columns([6, 1, 1])
                c1.markdown(f"**[{k['topic']}]** {k['fact']}")
                if c2.button("✓", key=f"ok_{k['id']}"):
                    set_knowledge_status(k["id"], "active", path=DB_PATH); st.rerun()
                if c3.button("✕", key=f"no_{k['id']}"):
                    set_knowledge_status(k["id"], "archived", path=DB_PATH); st.rerun()
        # Manual add
        with st.form("add_knowledge"):
            t = st.text_input("Topic"); f = st.text_area("Fact")
            if st.form_submit_button("Add to platform knowledge") and t and f:
                add_knowledge(t, f, source=client_id, status="active", path=DB_PATH); st.rerun()
```
Non-admins never see this panel; they inherit the knowledge through the system prompt. (`converse` replies already surface auto-propose notes to everyone.)

---

## 7. `seed/seed_platform_knowledge.py` (NEW, idempotent)
Skip insert if a row with the same `topic` already exists (`get_knowledge(None)` → check topics). Insert each as `status="active"`, `source="seed"`:

1. **topic: "LLM engine"** — `fact:` "The bot's LLM engine MUST always be Azure with model GPT-4.1, selected in bot settings (LLM Engine → Azure → Model: GPT-4.1). If the engine is misconfigured, the bot must reply: 'Please could you allow me a moment, I'm facing some trouble processing that.' This is a settings toggle — no flow change."

2. **topic: "Call disconnection"** — `fact:` "To make the voice bot hang up, add an End Flow component (PREFERRED) at every terminal branch — booking confirmed, not interested, wrong number, and max-retries-exhausted — and route each terminal stage into it. Optionally also instruct termination in the system prompt, but the End Flow node is what actually disconnects. Every generated plan must include End Flow terminal nodes in workflow_blueprint and a build_notes.canvas_instructions step to wire them."

3. **topic: "Latency / filler words"** — `fact:` "To cut perceived latency, enable Filler Words in Advanced Settings and attach a filler-generation context so the bot speaks a short natural bridge while the main response generates. Put a build_notes.filler_config in every plan: {enabled: true, rules: [exactly 5-10 words, one sentence, Hinglish in Devanagari script (not pure Hindi, not formal), feminine verb forms, no pricing/features/dates/business specifics, never sound like thinking/checking/delaying (avoid 'मैं देखती हूँ','एक क्षण','रुकिए','hold on'), no hesitation sounds, do not open with 'ठीक है'/'Okay'/'Alright', vary structure/tone across fillers], script: <the AutoVista/Anita filler prompt>}. The AutoVista/Anita filler prompt: \"You generate short conversational filler phrases for Anita, the female voice assistant of AutoVista for Maruti Suzuki, which act as a natural bridge before the main system response. The filler must sound warm, confident, and professional in tone while using natural Hinglish written fully in Devanagari script, avoiding pure Hindi or overly formal language. Each filler must be exactly one short sentence of five to ten words, spoken smoothly as part of a continuous conversation, without sounding scripted or repetitive. Maintain a polite and composed tone using feminine verb forms where applicable, and avoid heavy or complex vocabulary. Do not include any pricing, features, technical details, dates, or business-specific information. The filler must never sound like thinking, checking, or delaying, so avoid phrases like 'मैं देखती हूँ', 'एक क्षण', 'रुकिए', 'hold on', or similar expressions, and do not use hesitation sounds. Do not begin with direct acknowledgement starters such as 'ठीक है', 'Okay', or 'Alright', and avoid repeating sentence structures, opening patterns, or tonal styles from recent fillers. Prefer varied, forward-moving, or subtly validating conversational lines that blend seamlessly into the main response, ensuring the overall interaction feels natural, human, and fluid.\""

4. **topic: "Interruption handling"** — `fact:` "Enable 'Allow Interruption (LLM-based)' in Advanced Settings so the bot can be barged-in on naturally. This is a settings toggle — no flow change."

---

## 8. Reuse map
| Need | Use |
|---|---|
| Canvas system prompt | `intelligence/designer.py::_canvas_system()` |
| Cached LLM call (now multi-block) | `shared/llm_client.py::LLMClient.complete / complete_json` |
| Plan persistence | `shared/db.py::save_plan/get_plan/update_plan/save_patch` |
| Conversation turn router | `intelligence/designer.py::converse()` (extend) |
| Admin check | `shared/auth.py::is_admin` (new) |

## 9. Constraints
- All keys from `.env`; model from `ANTHROPIC_MODEL`.
- Single LLM call per `converse` turn; `proposed_knowledge` is a field on the same call (no extra request).
- Non-admin teach attempts must NOT write `active` knowledge (force `pending`).
- Keep ≤4 cache breakpoints (we use 2).

## 10. Build order (subagent-workflow waves)
- **Wave 1 — `shared/auth.py` + `shared/db.py` + `shared/llm_client.py`** (foundation, no cross-deps beyond db↔llm being independent): auth seam, `platform_knowledge` table + CRUD, multi-block cached system. Sanity: round-trip add/get/status/delete; `complete` accepts a 2-block list (mock or dry construct).
- **Wave 2 — `intelligence/designer.py`** (deps W1): `_platform_knowledge_block`, 2-block system at call sites, `converse` teach/auto-propose. Sanity: injected-fake-LLM test — admin "remember: X" → active row + reply; non-admin "remember: X" → pending only; `proposed_knowledge` on a normal turn → pending row.
- **Wave 3 — `app.py` + `seed/seed_platform_knowledge.py` + `.env.example`** (deps W1–2): admin panel (gated), seed script, env var. Sanity: `ast.parse(app.py)`; `AppTest` loads with no exception; run seed → 4 active rows.

## 11. Acceptance tests
1. **Seed + apply:** run seed; ask the designer (any client) to build a bot → plan includes End Flow terminal nodes + `build_notes.filler_config` (points 2 & 3 fixed) with no one re-typing them.
2. **Admin teach:** `client_id ∈ ADMIN_CLIENT_IDS`, "remember: always set STT to Azure Hindi" → `get_knowledge('active')` gains it; next plan reflects it.
3. **Non-admin blocked:** non-admin "remember: …" → no `active` write (lands `pending`); reply says it's Chat360-team curated.
4. **Auto-propose:** a turn surfacing a durable platform fact → `pending` row + reply note; admin Approves in panel → `active`.
5. **Caching cheap:** after teaching a new fact, the next turn's `designer._llm.last_usage.cache_read_input_tokens` shows the `best_bots` block still cache-read (only the knowledge block re-warms).
6. **Auth seam:** changing `ADMIN_CLIENT_IDS` flips who sees the panel / can teach — the single Chat360 integration point.

## 12. Out of scope
- RAG retrieval (future, when the store grows large — inject only matched facts).
- Real authentication (host/Chat360 provides identity; we only consume `is_admin`).
- Per-fact versioning/history beyond status transitions.
