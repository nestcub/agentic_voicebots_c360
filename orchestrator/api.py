"""FastAPI surface for the orchestrator.

Single backend the dashboard talks to. Exposes:
  - the dispatch confirm-gate flow (preview -> confirm -> dispatch);
  - the Chat360 post-call outcome webhook (records a durable CallOutcome, mirrors it
    onto the CRM lead, closes the assignment, feeds the Follow-up Reliability Engine,
    and spawns a fresh Commitment on a requested callback);
  - dashboard READ endpoints that compute KPIs / target progress / reports server-side
    from store rows (the browser never holds Neon creds, so all reads route through here);
  - goal/target WRITE endpoints (porting the old Streamlit goal editor);
  - CRM connection endpoints (list / create / test).

Thin by design: all real logic lives in the engines/store/adapters/crm helpers. This
module wires shared singletons once at import and maps HTTP requests onto those
interfaces. The scope-filtering + metric helpers below are direct ports of the
dashboard's `lib/sources/compute.ts` so the numbers match exactly.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from . import config
from . import crm as crm_mod
from .adapters.base import CallResult
from .adapters.chat360_voice import Chat360VoiceDispatcher
from .adapters.simulation import SimulationVoiceDispatcher, StoreCRMAdapter
from .engines.dispatch import DispatchEngine
from .engines.followup import FollowupEngine
from .engines.goal_adaptation import GoalAdaptationEngine
from .models import (
    AssignmentState,
    CallOutcome,
    now_iso,
    T_ACCOUNTS,
    T_ASSIGNMENTS,
    T_CALL_OUTCOMES,
    T_COMMITMENTS,
    T_CRM_CONNECTIONS,
    T_LEADS,
    T_TARGETS,
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
    goal_engine = GoalAdaptationEngine(store, followup_engine)
    return {
        "store": store,
        "voice": voice,
        "crm": crm,
        "dispatch_engine": dispatch_engine,
        "followup_engine": followup_engine,
        "goal_engine": goal_engine,
    }


_DEPS = build()
store = _DEPS["store"]
voice = _DEPS["voice"]
crm = _DEPS["crm"]
dispatch_engine = _DEPS["dispatch_engine"]
followup_engine = _DEPS["followup_engine"]
goal_engine = _DEPS["goal_engine"]


# ── scope + compute helpers (ports of dashboard/lib/sources/compute.ts) ──────────

_BOOKED = {"booked", "interested"}


def in_scope(row: dict, region: str | None, branch: str | None) -> bool:
    """Port of `inScope`. Branch wins over region; both empty == "all"."""
    if branch:
        return row.get("branch") == branch
    if region:
        return row.get("region") == region
    return True


def _scope(account_id: str, region: str | None, branch: str | None) -> dict:
    """Build the dashboard `Scope` JSON for the requested filter level."""
    if branch:
        return {"level": "branch", "region": region or "", "branch": branch}
    if region:
        return {"level": "region", "region": region}
    return {"level": "all"}


def compute_kpis(leads: list[dict]) -> dict:
    """Port of `computeKpis`."""
    total = len(leads)
    booked = sum(1 for l in leads if l.get("status") in _BOOKED)
    return {
        "total_leads": total,
        "pending": sum(1 for l in leads if l.get("status") == "pending"),
        "calling": sum(1 for l in leads if l.get("status") == "calling"),
        "booked": booked,
        "not_interested": sum(1 for l in leads if l.get("status") == "not_interested"),
        "follow_up": sum(
            1 for l in leads
            if l.get("status") in ("follow_up", "callback_requested")
        ),
        "conversion_rate": (booked / total) if total else 0,
    }


def compute_target_progress(
    leads: list[dict], commitments: list[dict], target: dict | None
) -> dict:
    """Port of `computeTargetProgress`."""
    reached = sum(1 for l in leads if l.get("status") != "pending")
    closed = sum(1 for l in leads if l.get("status") in _BOOKED)
    active_followups = sum(1 for c in commitments if c.get("state") == "pending")
    t = target or {}
    return {
        "reach_out": {"actual": reached, "target": t.get("reach_out", 0)},
        "close": {"actual": closed, "target": t.get("close", 0)},
        "follow_up": {"actual": active_followups, "target": t.get("follow_up", 0)},
    }


def _breakdown(leads: list[dict], key: str) -> list[dict]:
    """Port of compute.ts `breakdown`: group leads by region/branch."""
    groups: dict[str, list[dict]] = {}
    for l in leads:
        k = l.get(key) or "—"
        groups.setdefault(k, []).append(l)
    out = []
    for name, ls in groups.items():
        booked = sum(1 for l in ls if l.get("status") in _BOOKED)
        out.append({
            "name": name,
            "leads": len(ls),
            "booked": booked,
            "conversion": (booked / len(ls)) if ls else 0,
        })
    out.sort(key=lambda b: b["leads"], reverse=True)
    return out


def _over_time(outcomes: list[dict]) -> list[dict]:
    """Port of compute.ts `overTime`: calls + booked grouped by created_at day."""
    by_day: dict[str, dict] = {}
    for o in outcomes:
        day = (o.get("created_at") or "")[:10] or "—"
        e = by_day.setdefault(day, {"calls": 0, "booked": 0})
        e["calls"] += 1
        if o.get("outcome") in ("booked", "interested"):
            e["booked"] += 1
    points = [{"date": d, "calls": v["calls"], "booked": v["booked"]}
              for d, v in by_day.items()]
    points.sort(key=lambda p: p["date"])
    return points


def compute_report(
    leads: list[dict], outcomes: list[dict], target: dict | None,
    scope: dict, period: str,
) -> dict:
    """Port of `computeReport`."""
    booked = sum(1 for l in leads if l.get("status") in _BOOKED)
    close = (target or {}).get("close") or 0
    return {
        "period": period,
        "scope": scope,
        "by_region": _breakdown(leads, "region"),
        "by_branch": _breakdown(leads, "branch"),
        "outcomes_over_time": _over_time(outcomes),
        "goal_attainment": (booked / close) if close else 0,
    }


def _scoped(table: str, account_id: str, region: str | None, branch: str | None) -> list[dict]:
    """Rows for an account, filtered to the requested scope."""
    rows = store.list(table, where={"account_id": account_id})
    return [r for r in rows if in_scope(r, region, branch)]


def _account_json(row: dict) -> dict:
    """Map a stored account row to the dashboard `Account` shape."""
    return {"id": row.get("id"), "name": row.get("name"), "brand": row.get("brand", "")}


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


class GoalReq(BaseModel):
    """Goal editor payload (ports the deleted Streamlit editor)."""

    account_id: str
    month: str
    focus_type: str
    focus_detail: str
    reach_out: int = 0
    close: int = 0
    follow_up: int = 0


class CrmConnectionReq(BaseModel):
    account_id: str
    name: str
    crm_type: str
    base_url: str
    api_key: str = ""


# ── app ──────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Autovista Orchestrator")

# CORS — the dashboard (browser) calls this API directly via NEXT_PUBLIC_ORCH_API_URL.
_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "db": bool(config.DATABASE_URL)}


# ── dispatch confirm-gate flow ────────────────────────────────────────────────────

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


# ── dashboard READ endpoints ──────────────────────────────────────────────────────

@app.get("/orchestrator/accounts")
def list_accounts() -> list[dict]:
    return [_account_json(r) for r in store.list(T_ACCOUNTS)]


@app.get("/orchestrator/kpis")
def get_kpis(account_id: str, region: str | None = None, branch: str | None = None) -> dict:
    return compute_kpis(_scoped(T_LEADS, account_id, region, branch))


@app.get("/orchestrator/targets/progress")
def get_target_progress(
    account_id: str, region: str | None = None, branch: str | None = None
) -> dict:
    leads = _scoped(T_LEADS, account_id, region, branch)
    commitments = _scoped(T_COMMITMENTS, account_id, region, branch)
    target = _current_target(account_id)
    return compute_target_progress(leads, commitments, target)


@app.get("/orchestrator/leads")
def get_leads(account_id: str, region: str | None = None, branch: str | None = None) -> list[dict]:
    return _scoped(T_LEADS, account_id, region, branch)


@app.get("/orchestrator/commitments")
def get_commitments(
    account_id: str, region: str | None = None, branch: str | None = None
) -> list[dict]:
    return _scoped(T_COMMITMENTS, account_id, region, branch)


@app.get("/orchestrator/call-outcomes")
def get_call_outcomes(
    account_id: str, region: str | None = None, branch: str | None = None
) -> list[dict]:
    return _scoped(T_CALL_OUTCOMES, account_id, region, branch)


@app.get("/orchestrator/report")
def get_report(
    account_id: str,
    region: str | None = None,
    branch: str | None = None,
    period: str | None = None,
) -> dict:
    leads = _scoped(T_LEADS, account_id, region, branch)
    outcomes = _scoped(T_CALL_OUTCOMES, account_id, region, branch)
    target = _current_target(account_id)
    goal = goal_engine.active_goal(account_id)
    period = period or (goal.get("month") if goal else "") or ""
    return compute_report(leads, outcomes, target, _scope(account_id, region, branch), period)


@app.get("/orchestrator/goal")
def get_goal(account_id: str) -> dict:
    goal = goal_engine.active_goal(account_id)
    return {"goal": goal, "target": _current_target(account_id, goal)}


def _current_target(account_id: str, goal: dict | None = None) -> dict | None:
    """The Target whose period matches the active goal's month, else the latest one."""
    targets = store.list(T_TARGETS, where={"account_id": account_id})
    if not targets:
        return None
    goal = goal if goal is not None else goal_engine.active_goal(account_id)
    if goal:
        for t in targets:
            if t.get("period") == goal.get("month"):
                return t
    targets.sort(key=lambda t: t.get("period") or "", reverse=True)
    return targets[0]


# ── goal/target WRITE (ports the old Streamlit editor) ────────────────────────────

@app.post("/orchestrator/goal")
def set_goal(req: GoalReq) -> dict:
    goal = goal_engine.set_goal(
        req.account_id,
        month=req.month,
        focus_type=req.focus_type,
        focus_detail=req.focus_detail,
    )
    target = goal_engine.set_target(
        req.account_id,
        period=req.month,
        reach_out=req.reach_out,
        close=req.close,
        follow_up=req.follow_up,
    )
    return {"goal": goal, "target": target}


# ── CRM connection endpoints ──────────────────────────────────────────────────────

@app.get("/orchestrator/crm/connections")
def list_crm_connections(account_id: str) -> list[dict]:
    return crm_mod.list_connections(store, account_id)


@app.post("/orchestrator/crm/connections")
def create_crm_connection(req: CrmConnectionReq) -> dict:
    return crm_mod.create_connection(
        store,
        req.account_id,
        name=req.name,
        crm_type=req.crm_type,
        base_url=req.base_url,
        api_key=req.api_key,
    )


@app.post("/orchestrator/crm/connections/{conn_id}/test")
def test_crm_connection(conn_id: str) -> dict:
    conn = crm_mod.get_connection(store, conn_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="connection not found")
    result = crm_mod.test_connection(conn)
    store.update(
        T_CRM_CONNECTIONS,
        conn_id,
        {"status": "ok" if result["ok"] else "error", "last_tested_at": now_iso()},
    )
    return result
