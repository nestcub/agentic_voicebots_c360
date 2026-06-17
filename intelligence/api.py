"""Chat360 Intelligence API — FastAPI server exposing transcription, workflow design, and knowledge endpoints."""

import asyncio
import os
import shutil
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

from transcription.engine import TranscriptionEngine
from intelligence.designer import WorkflowDesigner
from shared.llm_client import LLMCompletionError
from shared.db import (
    init_db,
    list_bots,
    get_transcripts, get_transcript, get_insight_by_transcript,
    get_plans, get_plan, get_patches,
    get_knowledge, add_knowledge, delete_knowledge, set_knowledge_status,
    create_batch, get_batch, create_batch_item,
    update_batch_item, get_batch_items, refresh_batch_counts,
    load_session, save_session, get_kb, upsert_kb,
)

app = FastAPI(title="Chat360 Intelligence API", version="1.0.0")

# ── CORS ──────────────────────────────────────────────────────────────────────
_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API key auth ──────────────────────────────────────────────────────────────
_API_KEY = os.getenv("INTEL_API_KEY", "")

async def auth(request: Request) -> None:
    """Verify x-api-key header. Skipped when INTEL_API_KEY is unset (local dev)."""
    if not _API_KEY:
        return
    key = request.headers.get("x-api-key", "")
    if key != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key.")

# ── Lazy engine singletons ────────────────────────────────────────────────────
_te: TranscriptionEngine | None = None
_wd: WorkflowDesigner | None = None
_batch_pool = ThreadPoolExecutor(max_workers=4)

def _engine() -> TranscriptionEngine:
    global _te
    if _te is None:
        _te = TranscriptionEngine()
    return _te

def _designer() -> WorkflowDesigner:
    global _wd
    if _wd is None:
        _wd = WorkflowDesigner()
    return _wd

# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    init_db()

# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok"}

# ── Transcription ─────────────────────────────────────────────────────────────
_INSIGHT_PROVIDER_MAP = {"sonnet": "anthropic", "gpt-4.1": "azure"}

@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    client_id: str = Form(...),
    provider: str = Form("sarvam"),
    language_code: str = Form("hi-IN"),
    insight_model: str = Form("sonnet"),
    _: None = Depends(auth),
):
    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    insight_provider = _INSIGHT_PROVIDER_MAP.get(insight_model, "anthropic")
    try:
        return _engine().transcribe(tmp_path, client_id, provider=provider, language_code=language_code, insight_provider=insight_provider)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Transcription failed: {e}")
    finally:
        os.unlink(tmp_path)

# ── Transcripts ───────────────────────────────────────────────────────────────
@app.get("/transcripts")
async def list_transcripts(client_id: str | None = None, _: None = Depends(auth)):
    return get_transcripts(client_id)

@app.get("/transcripts/{transcript_id}")
async def get_one_transcript(transcript_id: str, _: None = Depends(auth)):
    t = get_transcript(transcript_id)
    if not t:
        raise HTTPException(status_code=404, detail="Transcript not found.")
    return t

@app.get("/transcripts/{transcript_id}/insights")
async def get_transcript_insights(transcript_id: str, _: None = Depends(auth)):
    insight = get_insight_by_transcript(transcript_id)
    if not insight:
        raise HTTPException(status_code=404, detail="No insights found.")
    return insight

@app.patch("/transcripts/{transcript_id}")
async def edit_transcript(transcript_id: str, body: dict, _: None = Depends(auth)):
    """Save human-edited transcript text and rerun insight extraction."""
    text = body.get("text", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required.")
    insight_provider = _INSIGHT_PROVIDER_MAP.get(body.get("insight_model", "sonnet"), "anthropic")
    result = _engine().rerun_insights(transcript_id, "", text, insight_provider=insight_provider)
    return result

# ── Batch transcription ───────────────────────────────────────────────────────
@app.post("/transcribe/batch")
async def transcribe_batch(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    client_id: str = Form(...),
    provider: str = Form("sarvam"),
    language_code: str = Form("hi-IN"),
    insight_model: str = Form("sonnet"),
    swap_roles: bool = Form(False),
    _: None = Depends(auth),
):
    """Accept multiple audio files, return batch_id immediately, process in background."""
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    # Save all uploaded files to a persistent temp directory (not cleaned until job done)
    tmp_dir = tempfile.mkdtemp(prefix="batch_")
    saved_paths = []
    for f in files:
        suffix = Path(f.filename or "audio.wav").suffix or ".wav"
        dest = os.path.join(tmp_dir, f.filename or f"audio{suffix}")
        with open(dest, "wb") as out:
            out.write(await f.read())
        saved_paths.append(dest)

    batch_id = create_batch(client_id, provider, len(files))
    item_ids = {
        Path(p).name: create_batch_item(batch_id, Path(p).name)
        for p in saved_paths
    }

    def _run():
        def on_done(filename, result):
            item_id = item_ids.get(filename)
            if not item_id:
                return
            if isinstance(result, Exception):
                update_batch_item(item_id, "failed", error=str(result))
            else:
                update_batch_item(item_id, "done", transcript_id=result["transcript_id"])
            refresh_batch_counts(batch_id)

        try:
            insight_provider = _INSIGHT_PROVIDER_MAP.get(insight_model, "anthropic")
            _engine().transcribe_many(
                saved_paths, client_id, provider=provider,
                swap_roles=swap_roles, on_file_done=on_done,
                language_code=language_code,
                insight_provider=insight_provider,
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    background_tasks.add_task(_batch_pool.submit, _run)
    return {"batch_id": batch_id, "total_files": len(files)}

@app.get("/batches/{batch_id}/status")
async def batch_status(batch_id: str, _: None = Depends(auth)):
    batch = get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")
    items = get_batch_items(batch_id)
    return {
        "batch_id": batch_id,
        "provider": batch["provider"],
        "total": batch["total"],
        "completed": batch["completed"],
        "failed": batch["failed"],
        "created_at": batch["created_at"],
        "items": [
            {
                "filename": it["filename"],
                "status": it["status"],
                "transcript_id": it["transcript_id"],
                "error": it["error"],
            }
            for it in items
        ],
    }

# ── Conversational designer ───────────────────────────────────────────────────
_INTEL_MODEL_MAP: dict[str, dict] = {
    "sonnet":  {"provider": "anthropic", "model": None},
    "gpt-4.1": {"provider": "azure",     "model": "gpt-4.1"},
    "gpt-5.4": {"provider": "azure",     "model": "gpt-5.4"},
}

# ── Bots ──────────────────────────────────────────────────────────────────────
@app.get("/bots")
async def get_bots(_: None = Depends(auth)):
    return {"bots": list_bots()}

@app.post("/bots")
async def create_bot(_: None = Depends(auth)):
    client_id = str(uuid.uuid4())
    return {"client_id": client_id}

# ── Clarify / Generate / Patch ────────────────────────────────────────────────
@app.post("/clarify")
async def clarify(body: dict, _: None = Depends(auth)):
    client_id = body.get("client_id", "").strip()
    use_case  = body.get("use_case", "").strip()
    if not client_id or not use_case:
        raise HTTPException(status_code=400, detail="client_id and use_case are required.")
    try:
        questions = _designer().generate_clarifying_questions(client_id, use_case)
        return {"questions": questions}
    except LLMCompletionError as exc:
        return JSONResponse(status_code=502, content=exc.to_dict())

@app.post("/generate")
async def generate(body: dict, _: None = Depends(auth)):
    client_id = body.get("client_id", "").strip()
    use_case  = body.get("use_case", "").strip()
    answers   = body.get("answers", [])   # list of {question, answer}
    model_key = body.get("model", "gpt-5.4")
    if not client_id or not use_case:
        raise HTTPException(status_code=400, detail="client_id and use_case are required.")
    cfg = _INTEL_MODEL_MAP.get(model_key, _INTEL_MODEL_MAP["gpt-5.4"])  # noqa: F841
    try:
        plan = _designer().generate_plan(client_id, use_case, answers)
        return plan
    except LLMCompletionError as exc:
        return JSONResponse(status_code=502, content=exc.to_dict())

@app.post("/patch")
async def patch_plan(body: dict, _: None = Depends(auth)):
    plan_id = body.get("plan_id", "").strip()
    request = body.get("request", "").strip()
    section = body.get("section")   # optional snake_case key e.g. "closure"
    if not plan_id or not request:
        raise HTTPException(status_code=400, detail="plan_id and request are required.")
    try:
        result = _designer().apply_patch(plan_id, request, section=section)
        return result
    except LLMCompletionError as exc:
        return JSONResponse(status_code=502, content=exc.to_dict())

@app.post("/converse")
async def converse(body: dict, _: None = Depends(auth)):
    client_id = body.get("client_id", "").strip()
    message = body.get("message", "").strip()
    if not client_id or not message:
        raise HTTPException(status_code=400, detail="client_id and message are required.")
    intent_aware = bool(body.get("intent_aware", True))
    model_key = body.get("model", "sonnet")
    cfg = _INTEL_MODEL_MAP.get(model_key, _INTEL_MODEL_MAP["sonnet"])
    reasoning_effort = body.get("reasoning_effort")  # e.g. "low", "medium", "high" or None
    try:
        return _designer().converse(
            client_id, message,
            intent_aware=intent_aware,
            provider=cfg["provider"],
            model=cfg["model"],
            reasoning_effort=reasoning_effort,
        )
    except LLMCompletionError as exc:
        return JSONResponse(status_code=502, content=exc.to_dict())

# ── Session (use case) ────────────────────────────────────────────────────────
@app.get("/session/{client_id}")
async def get_session(client_id: str, _: None = Depends(auth)):
    sess = load_session(client_id)
    return {"use_case": sess.get("use_case") or "", "plan_id": sess.get("plan_id")}

@app.patch("/session/{client_id}")
async def update_session_use_case(client_id: str, body: dict, _: None = Depends(auth)):
    use_case = body.get("use_case", "").strip()
    if not use_case:
        raise HTTPException(status_code=400, detail="use_case is required.")
    sess = load_session(client_id)
    save_session(
        client_id,
        sess.get("questions", []),
        sess.get("answers", {}),
        plan_id=sess.get("plan_id"),
        use_case=use_case,
    )
    return {"ok": True}

# ── Bot KB ────────────────────────────────────────────────────────────────────
@app.get("/kb/{client_id}")
async def get_bot_kb(client_id: str, _: None = Depends(auth)):
    kb = get_kb(client_id)
    if kb is None:
        return {"content": "", "updated_at": None}
    return kb

@app.post("/kb/{client_id}")
async def upsert_bot_kb(client_id: str, body: dict, _: None = Depends(auth)):
    content = body.get("content", "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required.")
    upsert_kb(client_id, content)
    return {"ok": True}

# ── Plans ─────────────────────────────────────────────────────────────────────
@app.get("/plans")
async def list_plans(client_id: str | None = None, _: None = Depends(auth)):
    return get_plans(client_id)

@app.get("/plans/{plan_id}")
async def get_one_plan(plan_id: str, _: None = Depends(auth)):
    p = get_plan(plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="Plan not found.")
    return p

@app.get("/plans/{plan_id}/patches")
async def list_patches(plan_id: str, _: None = Depends(auth)):
    return get_patches(plan_id)

# ── Platform knowledge ────────────────────────────────────────────────────────
@app.get("/knowledge")
async def list_knowledge(status: str | None = None, _: None = Depends(auth)):
    return get_knowledge(status)

@app.post("/knowledge")
async def create_knowledge(body: dict, _: None = Depends(auth)):
    topic = body.get("topic", "").strip()
    fact = body.get("fact", "").strip()
    if not topic or not fact:
        raise HTTPException(status_code=400, detail="topic and fact are required.")
    kid = add_knowledge(topic, fact, body.get("source"), body.get("status", "active"))
    return {"id": kid}

@app.delete("/knowledge/{knowledge_id}")
async def remove_knowledge(knowledge_id: str, _: None = Depends(auth)):
    delete_knowledge(knowledge_id)
    return {"ok": True}

@app.patch("/knowledge/{knowledge_id}")
async def update_knowledge(knowledge_id: str, body: dict, _: None = Depends(auth)):
    status = body.get("status", "").strip()
    if not status:
        raise HTTPException(status_code=400, detail="status is required.")
    set_knowledge_status(knowledge_id, status)
    return {"ok": True}
