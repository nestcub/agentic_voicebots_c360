"""Chat360 Intelligence API — FastAPI server exposing transcription, workflow design, and knowledge endpoints."""

import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from transcription.engine import TranscriptionEngine
from intelligence.designer import WorkflowDesigner
from shared.db import (
    get_transcripts, get_transcript,
    get_plans, get_plan, get_patches,
    get_knowledge, add_knowledge, delete_knowledge, set_knowledge_status,
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

# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok"}

# ── Transcription ─────────────────────────────────────────────────────────────
@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    client_id: str = Form(...),
    _: None = Depends(auth),
):
    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        return _engine().transcribe(tmp_path, client_id)
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

# ── Conversational designer ───────────────────────────────────────────────────
@app.post("/converse")
async def converse(body: dict, _: None = Depends(auth)):
    client_id = body.get("client_id", "").strip()
    message = body.get("message", "").strip()
    if not client_id or not message:
        raise HTTPException(status_code=400, detail="client_id and message are required.")
    return _designer().converse(client_id, message)

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
