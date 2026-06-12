# Build Spec — Call-Recording Segment RAG

> **You are the implementing agent. Read this whole file, then execute it end to end.** This is a self-contained build brief for the Chat360 intelligence-fabric repo. The codebase already runs on Neon Postgres + pgvector with a working RAG pipeline over `bot_examples`; you are adding a **second, parallel RAG corpus over call-transcript chunks**. Reuse the existing patterns named below — do not re-architect, do not swap libraries, do not change the embedding provider. Build in the wave order at the bottom and report the output of each verification step.

---

## Hard constraints (follow exactly)

- **Run everything from the repo root** with `PYTHONPATH=. venv/bin/python ...` — the scripts need the repo on the path (a plain `python scripts/x.py` fails with `ModuleNotFoundError: shared`).
- **Commit each file separately**, single-line message, **NO `Co-Authored-By` line**, no multi-paragraph messages. Verb choices: `add`, `wire`, `index`, `fix`, `update`.
  ```
  git commit -m "$(cat <<'EOF'
  <verb> <module>: <one-line description>
  EOF
  )"
  ```
- **Correctness invariant:** every call-evidence retrieval MUST filter by `client_id`. Call evidence must never leak across clients. This is non-negotiable.
- **Never break transcription:** chunk-indexing runs inside a `try/except` that **logs** on failure (use `print(...)` to stderr or `logging`) — a down embedding API must not fail the transcribe request.
- **Do not touch** `bot_examples`, the migration script, or the dashboard. This is additive.
- After each Python file: `python -c "import ast; ast.parse(open('<file>').read()); print('syntax ok')"` then an import check; report the result.

---

## Runtime prerequisites (already set in `.env` — do not change)

```
DATABASE_URL=<Neon pooled connection string>
GOOGLE_API_KEY=<set>
EMBEDDING_PROVIDER=gemini
EMBEDDING_MODEL=gemini-embedding-001
EMBEDDING_DIM=768
```

---

## Context (why this change)

Call recordings today flow: audio → `transcripts` table (full text + diarized segments) + `insights` table (LLM-extracted patterns) — see `transcription/engine.py`. At plan/patch time, `intelligence/designer.py` calls `_aggregate_insights(client_id)`, which **deduplicates insights into flat string lists** and dumps them into the prompt. The raw transcript dialogue is never sent to the LLM.

That aggregation is lossy: it strips **frequency** (15 of 20 calls hitting the same objection looks identical to a one-off), strips **verbatim context/quotes**, and isn't **scoped to the plan** being built. The goal: ground plan generation in the **actual call dialogue** — retrieve the most relevant verbatim call moments for the use-case being designed — so patterns are precise, specific, and context-rich.

This **augments** the existing insight summary, it does not replace it: the dedup summary gives breadth (what's common), retrieved quotes give grounding (the actual words). Keep `_aggregate_insights` exactly as-is.

**Out of scope (verified — do not change):** bot-example decomposition is correct. Each of the 5 bots embeds at ~370–475 tokens, far under the ~2048-token embedding limit, so nothing truncates. The "scattered adani patterns vs 5 bots" shape is just the source JSON (a list of 10 atomic patterns vs 5 self-contained bots) — the rule is one list-item → one unit in both.

---

## Existing interfaces to reuse (already implemented — do not rebuild)

```python
# shared/embeddings.py
embed(text: str) -> list[float]                  # provider-agnostic, returns EMBEDDING_DIM floats (768)
embed_batch(texts: list[str]) -> list[list[float]]

# shared/db.py — psycopg3 ConnectionPool, dict_row rows, prepare_threshold=None; Jsonb() for JSONB writes
_get_pool() -> ConnectionPool                    # module-level singleton built from DATABASE_URL
init_db(path=...) -> None                         # emits Postgres DDL — ADD the new table here
_EMBEDDING_DIM                                    # int from env; use as vector(<dim>)
add_bot_example(unit_type, name, use_case, content: dict, embedding: list) -> str   # COPY this shape
search_bot_examples(embedding: list, k: int) -> list[dict]                          # COPY this shape
save_transcript / get_transcripts / get_transcript
# Vector-search pattern already in this file — copy it verbatim for chunks:
#   SELECT *, 1 - (embedding <=> %s::vector) AS score
#   FROM <table> WHERE ... ORDER BY embedding <=> %s::vector LIMIT %s
#   bindings: (embedding, embedding, k)

# transcription/engine.py
TranscriptionEngine.transcribe(audio_path, client_id) -> dict
#   segment shape: {"speaker","role","start","end","text"}
#   save_transcript(...) returns transcript_id at ~line 104  ← index chunks immediately after
TranscriptionEngine.rerun_insights(transcript_id, client_id, edited_text)  ← delete + re-index here

# intelligence/designer.py
_aggregate_insights(client_id, db_path) -> dict   # KEEP — this is the summary layer
_retrieve_examples(query_text, k) -> str          # COPY this pattern for call evidence
generate_plan(...) / converse(...)                # both build `_rag_query` already — reuse it
```

---

## Design

- **Retrievable unit = a "call moment":** a window of consecutive diarized segments (a customer objection + the agent's response kept together), preserving speaker role, timestamps, and verbatim text. Per-segment is too granular ("Haan", "OK"); windowing keeps coherent moments.
- **New table `transcript_chunks`** with `embedding vector(<EMBEDDING_DIM>)`, **scoped by `client_id`**.
- **Index at ingest:** chunk + embed + store right after a recording is transcribed (auto-indexes new recordings) + a one-time backfill for existing transcripts.
- **Retrieve at plan time:** `_retrieve_call_evidence(client_id, query, k)` embeds the query, vector-searches `transcript_chunks` filtered by `client_id`, returns top-K verbatim quotes with speaker labels — injected into the prompt alongside the existing insight summary.

---

## WAVE 1 — foundation (the two files are independent)

### 1a. NEW `shared/chunking.py`
Pure function, no I/O.
```python
"""Window diarized transcript segments into coherent 'call moments' for embedding."""

def chunk_segments(segments: list[dict], window: int = 4, overlap: int = 1) -> list[dict]:
    """Group consecutive segments into overlapping windows.

    segments: [{"speaker","role","start","end","text"}, ...]
    Returns: [{"chunk_index","role_sequence","start","end","text"}, ...]
      - text: the windowed segments joined as "ROLE: <text>" lines
      - role_sequence: e.g. "CUSTOMER>AGENT"
      - start/end: from first/last segment in the window
    window = segments per chunk; overlap = shared segments between adjacent chunks
    (overlap keeps an objection and its response together). Skip empty/whitespace text.
    """
```
- Step `window - overlap` each iteration; emit a final partial chunk if segments remain.
- Keep each chunk a coherent ~50–150 words; never exceed the embedding token limit (windows of 4 with these transcripts are well within it).

**Verify:** build a fake `segments` list of ~8 turns, call `chunk_segments`, print the chunks; confirm coherent text + role_sequence + monotonic chunk_index.
**Commit:** `add chunking: window diarized segments into coherent call moments`

### 1b. EDIT `shared/db.py`
Add to `init_db()` (alongside the existing `CREATE TABLE` statements; substitute `_EMBEDDING_DIM` into the f-string exactly like the existing `bot_examples` / `platform_knowledge` tables do):
```sql
CREATE TABLE IF NOT EXISTS transcript_chunks (
    id            TEXT PRIMARY KEY,
    transcript_id TEXT NOT NULL,
    client_id     TEXT NOT NULL,
    chunk_index   INTEGER NOT NULL,
    role_sequence TEXT,
    start_sec     REAL,
    end_sec       REAL,
    text          TEXT NOT NULL,
    embedding     vector({dim}),
    created_at    TEXT NOT NULL
)
```
```sql
CREATE INDEX IF NOT EXISTS transcript_chunks_client_idx ON transcript_chunks(client_id)
CREATE INDEX IF NOT EXISTS transcript_chunks_embedding_idx
    ON transcript_chunks USING hnsw (embedding vector_cosine_ops)
```
Add three helpers (mirror `add_bot_example` / `search_bot_examples` exactly — same pool usage, `Jsonb` not needed here since all columns are scalar/text, embedding passed as a Python list):
```python
def add_transcript_chunk(transcript_id, client_id, chunk_index, role_sequence,
                         start_sec, end_sec, text, embedding) -> str
    # INSERT one row, uuid id, _now() created_at; returns id

def search_transcript_chunks(embedding: list, client_id: str, k: int = 5) -> list[dict]
    # SELECT *, 1 - (embedding <=> %s::vector) AS score
    # FROM transcript_chunks
    # WHERE client_id=%s AND embedding IS NOT NULL
    # ORDER BY embedding <=> %s::vector
    # LIMIT %s
    # bindings: (embedding, client_id, embedding, k)

def delete_transcript_chunks(transcript_id: str) -> None
    # DELETE FROM transcript_chunks WHERE transcript_id=%s   (used before re-index)
```
**Verify:** `PYTHONPATH=. venv/bin/python -c "from shared.db import init_db; init_db(); print('ok')"` then confirm the table exists (`search_transcript_chunks` import works; an empty search returns `[]`).
**Commit:** `add transcript_chunks table and per-client vector search helpers`

---

## WAVE 2 — wiring (after Wave 1)

### 2a. EDIT `transcription/engine.py`
Import `chunk_segments`, `embed_batch`, `add_transcript_chunk`, `delete_transcript_chunks`.
- In `transcribe(...)`, **after** `save_transcript(...)` returns `transcript_id` (~line 104) and before/after insight extraction, add a helper call `self._index_chunks(transcript_id, client_id, segments)`.
- In `rerun_insights(...)`, after saving edited text, re-segment is not available there — re-index from the stored transcript's segments if present; at minimum call `delete_transcript_chunks(transcript_id)` then re-index from the edited segments if you have them. (If `rerun_insights` only has text, skip re-chunk and just delete stale chunks; leave a `# TODO` noting re-chunk needs segments.)
- New method:
```python
def _index_chunks(self, transcript_id, client_id, segments):
    try:
        chunks = chunk_segments(segments)
        if not chunks:
            return
        vecs = embed_batch([c["text"] for c in chunks])
        for c, v in zip(chunks, vecs):
            add_transcript_chunk(transcript_id, client_id, c["chunk_index"],
                                 c["role_sequence"], c["start"], c["end"], c["text"], v)
    except Exception as e:
        print(f"[chunk-index] failed for transcript {transcript_id}: {e}")
```
**Verify:** import check only (no live transcribe needed here): `PYTHONPATH=. venv/bin/python -c "from transcription.engine import TranscriptionEngine; print('import ok')"` (a missing SARVAM key error is fine — that's runtime, not import).
**Commit:** `index transcript chunks at transcribe time for call-evidence RAG`

### 2b. EDIT `intelligence/designer.py`
Add `from shared.db import search_transcript_chunks` to the existing `shared.db` import.
New helper (copy `_retrieve_examples` structure, including the `try/except: return ""` with a log line on failure):
```python
def _retrieve_call_evidence(client_id: str, query_text: str, k: int = 5) -> str:
    """Retrieve top-K verbatim call moments for THIS client, grounded quotes for the prompt."""
    try:
        vec = embed(query_text)
        hits = search_transcript_chunks(vec, client_id, k=k)
        if not hits:
            return ""
        lines = ["## Relevant call evidence (verbatim moments from this client's recordings)\n"]
        for h in hits:
            ts = f"{h.get('start_sec', 0):.0f}s" if h.get('start_sec') is not None else ""
            lines.append(f"### {h.get('role_sequence','')} {ts} (similarity {h.get('score',0):.2f})")
            lines.append(h["text"])
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        print(f"[call-evidence] retrieval failed for {client_id}: {e}")
        return ""
```
Wire into both `generate_plan` and `converse`:
- They already compute `_rag_query` and `_rag_examples` for bot retrieval. Right after, add:
  `_call_evidence = _retrieve_call_evidence(client_id, _rag_query)`
- Inject a `<call_evidence>\n{_call_evidence}\n</call_evidence>` block into the **user** prompt **immediately after** the existing call-insights block (`<call_insights>...` in `generate_plan`; the `CALL INSIGHTS` section in `converse`). Keep `_aggregate_insights` output in place — evidence augments, summary stays.

**Verify:** `PYTHONPATH=. venv/bin/python -c "import os; from intelligence.designer import WorkflowDesigner; print('import ok')"` (DB/API errors at runtime are fine; parse/import errors are not).
**Commit:** `wire call-evidence RAG into plan generation and converse`

---

## WAVE 3 — backfill (after Wave 1+2)

### NEW `scripts/backfill_transcript_chunks.py`
Mirror `scripts/migrate_sqlite_to_postgres.py` structure (dotenv, `_get_pool()`, `pool.close()` at end).
- Load all transcripts via `get_transcripts()` (no client filter). Each has `segments`.
- For each: `delete_transcript_chunks(transcript_id)` then chunk → `embed_batch` → `add_transcript_chunk` per chunk.
- Print per-client chunk counts at the end:
  `SELECT client_id, count(*) FROM transcript_chunks GROUP BY client_id`.
- Run it: `PYTHONPATH=. venv/bin/python scripts/backfill_transcript_chunks.py`.
**Commit:** `add backfill_transcript_chunks: index existing recordings into RAG`

---

## Final verification (run and report output)

1. `PYTHONPATH=. venv/bin/python -c "from shared.db import init_db; init_db()"` — table created.
2. Run the backfill script — report per-client chunk counts (expect several chunks per recording).
3. Retrieval + isolation check:
   ```python
   PYTHONPATH=. venv/bin/python -c "
   from shared.embeddings import embed
   from shared.db import search_transcript_chunks, _get_pool
   q = embed('customer objection about service pricing and surveyor availability')
   for h in search_transcript_chunks(q, 'service_demo', 5):
       print(round(h['score'],3), h['role_sequence'], '|', h['text'][:80])
   _get_pool().close()
   "
   ```
   Confirm: returns **verbatim** call moments, scored, **only for `service_demo`**.
4. Cross-client isolation: repeat with a different `client_id` and confirm no `service_demo` rows appear.
5. Start the server (`PYTHONPATH=. venv/bin/uvicorn intelligence.api:app --port 8001`), `POST /converse` for `service_demo`, and confirm (via a temporary debug print in `converse`) the user prompt now contains a `<call_evidence>` block of real quotes alongside the insight summary. Remove the debug print before the final commit.
6. Regression: confirm transcription still imports and that a new transcribe call would index chunks (the try/except never raises).

Report the output of steps 2–4 back to the user.
