"""FastAPI surface for the orchestrator.

Exposes the dispatch confirm-gate flow (preview -> confirm -> dispatch) and the
Chat360 post-call outcome webhook. The webhook ingests a normalized CallResult,
records a durable CallOutcome row, mirrors the outcome onto the CRM lead, closes the
assignment, feeds the Follow-up Reliability Engine, and (on a requested callback)
spawns a fresh Commitment so a promised follow-up is never dropped.

Thin by design: all real logic lives in the engines/store/adapters. This module wires
shared singletons once at import and maps HTTP requests onto those interfaces.
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field

from . import config
from .adapters.base import CallResult
from .adapters.chat360_voice import Chat360VoiceDispatcher
from .adapters.simulation import SimulationVoiceDispatcher, StoreCRMAdapter
from .engines.dispatch import DispatchEngine
from .engines.followup import FollowupEngine
from .models import (
    AssignmentState,
    CallOutcome,
    T_ASSIGNMENTS,
    T_CALL_OUTCOMES,
    to_row,
)
from .store import get_store


# ── shared singletons ────────────────────────────────────────────────────────────

def build() -> dict:
    """Construct the shared store / voice / crm / engine singletons.

    Chat360 is used when an auth cookie is configured, else the credential-free
    simulation dispatcher drives the same pipeline.
    """
    store = get_store()
    voice = (
        Chat360VoiceDispatcher()
        if config.CHAT360_AUTH_COOKIE
        else SimulationVoiceDispatcher(config.DID_POOL or None)
    )
    crm = StoreCRMAdapter(store)
    dispatch_engine = DispatchEngine(store, voice, crm)
    followup_engine = FollowupEngine(store, voice, crm)
    return {
        "store": store,
        "voice": voice,
        "crm": crm,
        "dispatch_engine": dispatch_engine,
        "followup_engine": followup_engine,
    }


_DEPS = build()
store = _DEPS["store"]
voice = _DEPS["voice"]
crm = _DEPS["crm"]
dispatch_engine = _DEPS["dispatch_engine"]
followup_engine = _DEPS["followup_engine"]


# ── request models ───────────────────────────────────────────────────────────────

class PreviewReq(BaseModel):
    account_id: str
    scope: dict | None = None


class ConfirmReq(BaseModel):
    session_id: str


class DispatchReq(BaseModel):
    account_id: str
    session_id: str
    scope: dict | None = None


class OutcomeReq(BaseModel):
    """Permissive Chat360 post-call webhook payload. Maps JSON "from" -> from_."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    dlr_id: str
    from_: str = Field(default="", alias="from")
    to: str = ""
    call_status: str = "completed"
    outcome: str = ""
    duration_sec: int = 0
    callback_at: str = ""
    transcript: str = ""
    recording_url: str = ""
    extracted: dict = Field(default_factory=dict)


# ── app ──────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Autovista Orchestrator")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "store": config.store_backend()}


@app.post("/orchestrator/autodial/preview")
def autodial_preview(req: PreviewReq) -> dict:
    return dispatch_engine.preview(req.account_id, req.scope)


@app.post("/orchestrator/autodial/confirm")
def autodial_confirm(req: ConfirmReq) -> dict:
    return {"confirmed": dispatch_engine.confirm(req.session_id)}


@app.post("/orchestrator/autodial/dispatch")
def autodial_dispatch(req: DispatchReq) -> dict:
    return dispatch_engine.dispatch(req.account_id, req.session_id, req.scope)


@app.post("/orchestrator/webhook/chat360/outcome")
def chat360_outcome(req: OutcomeReq) -> dict:
    result = CallResult(
        execution_id=req.dlr_id,
        call_status=req.call_status,
        outcome=req.outcome,
        duration_sec=req.duration_sec,
        callback_at=req.callback_at,
        transcript_ref=req.transcript,
        recording_url=req.recording_url,
        extracted=req.extracted,
    )

    matches = store.list(T_ASSIGNMENTS, where={"execution_id": req.dlr_id})
    assignment = matches[0] if matches else None

    account_id = assignment["account_id"] if assignment else ""
    lead_id = assignment["lead_id"] if assignment else ""
    goal_context = assignment["goal_context"] if assignment else {}
    region = assignment.get("region", "") if assignment else ""
    branch = assignment.get("branch", "") if assignment else ""

    outcome_row = store.insert(
        T_CALL_OUTCOMES,
        to_row(
            CallOutcome(
                account_id=account_id,
                execution_id=req.dlr_id,
                lead_id=lead_id,
                goal_context=goal_context,
                call_status=req.call_status,
                outcome=req.outcome,
                duration_sec=req.duration_sec,
                callback_at=req.callback_at,
                transcript_ref=req.transcript,
                recording_url=req.recording_url,
                extracted=req.extracted,
                region=region,
                branch=branch,
            )
        ),
    )

    if assignment:
        crm.write_outcome(lead_id, {"outcome": req.outcome, "call_status": req.call_status})
        store.update(T_ASSIGNMENTS, assignment["id"], {"state": AssignmentState.DONE.value})

    followup_engine.record_outcome(req.dlr_id, result)

    if req.outcome == "callback_requested":
        followup_engine.from_call_outcome(outcome_row)

    return {"ok": True, "matched_assignment": bool(matches), "outcome_id": outcome_row["id"]}
