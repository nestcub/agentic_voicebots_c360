"""Orchestrator domain models — CRM-independent execution state + commitments.

These dataclasses are the single source of truth for table shapes. The dashboard's
TypeScript `types.ts` mirrors them. Stored as plain dicts via the Store layer so they
map cleanly onto both an in-memory dict store and Supabase rows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum


def new_id() -> str:
    """Generate a short unique id."""
    return uuid.uuid4().hex


def now_iso() -> str:
    """Current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ── enums (stored as their .value strings) ──────────────────────────────────────

class FocusType(str, Enum):
    SERVICE = "service"
    PRODUCT = "product"


class AssignmentState(str, Enum):
    PENDING = "pending"
    CALLING = "calling"
    DONE    = "done"
    FAILED  = "failed"


class CommitmentState(str, Enum):
    PENDING        = "pending"        # awaiting its due time / in retry cycle
    DONE           = "done"           # fulfilled (reached + resolved)
    NOT_INTERESTED = "not_interested" # explicit decline
    EXHAUSTED      = "exhausted"      # max retries hit
    CANCELLED      = "cancelled"      # explicitly cancelled (NOT by goal change)


class CallStatus(str, Enum):
    COMPLETED = "completed"
    NO_ANSWER = "no_answer"
    BUSY      = "busy"
    FAILED    = "failed"


# ── table name constants ────────────────────────────────────────────────────────

T_ACCOUNTS     = "accounts"
T_GOALS        = "goals"
T_TARGETS      = "targets"
T_LEADS        = "leads"
T_ASSIGNMENTS  = "assignments"
T_COMMITMENTS  = "commitments"
T_CALL_OUTCOMES = "call_outcomes"
T_ROLLUPS      = "rollups"

ALL_TABLES = [
    T_ACCOUNTS, T_GOALS, T_TARGETS, T_LEADS,
    T_ASSIGNMENTS, T_COMMITMENTS, T_CALL_OUTCOMES, T_ROLLUPS,
]


# ── models ──────────────────────────────────────────────────────────────────────

@dataclass
class Account:
    """A dealership tenant (e.g. Autovista). Regions/branches live on leads/assignments."""
    name: str
    brand: str = "Autovista"
    id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=now_iso)


@dataclass
class Goal:
    """The active monthly focus. focus_type=what kind, focus_detail=specifics."""
    account_id: str
    month: str                       # "YYYY-MM"
    focus_type: str                  # FocusType value
    focus_detail: str                # e.g. "Monsoon AC service package"
    script_version: str = "v1"       # voice-bot system-prompt version this goal maps to
    set_by: str = "human"
    active: bool = True
    id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=now_iso)

    def context(self) -> dict:
        """Compact goal_context stamped on every call/commitment for attribution."""
        return {
            "goal_id": self.id,
            "month": self.month,
            "focus_type": self.focus_type,
            "focus_detail": self.focus_detail,
        }


@dataclass
class Target:
    """How many to reach out / close / follow up for a period — drives progress bars."""
    account_id: str
    period: str                      # "YYYY-MM"
    reach_out: int = 0
    close: int = 0
    follow_up: int = 0
    id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=now_iso)


@dataclass
class Lead:
    """Demo CRM lead (the SupabaseCRMAdapter reads these). Real CRMs supply their own."""
    account_id: str
    name: str
    phone: str
    vehicle_model: str = ""
    service_due_date: str = ""
    source: str = "Direct"
    region: str = ""
    branch: str = ""
    status: str = "pending"
    lead_score: int | None = None
    id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=now_iso)


@dataclass
class Assignment:
    """A lead queued/dispatched under a goal, on a DID."""
    account_id: str
    lead_id: str
    region: str
    branch: str
    goal_context: dict
    did: str = ""
    execution_id: str = ""
    state: str = AssignmentState.PENDING.value
    id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=now_iso)


@dataclass
class Commitment:
    """A durable follow-up promise — the heart of Pain A. Never dropped by goal change."""
    account_id: str
    lead_id: str
    region: str
    branch: str
    due_at: str                      # ISO; scheduler fires when due_at <= now
    goal_context: dict               # the goal this follow-up belongs to (preserved)
    note: str = ""
    sla_hours: float = 24.0          # how late before it's "breached"
    retries: int = 0
    max_retries: int = 4
    state: str = CommitmentState.PENDING.value
    last_execution_id: str = ""
    id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)


@dataclass
class CallOutcome:
    """Result of a dispatched call, correlated by execution_id (== Chat360 dlr_id)."""
    account_id: str
    execution_id: str
    lead_id: str
    goal_context: dict
    call_status: str = CallStatus.COMPLETED.value
    outcome: str = ""                # interested|not_interested|callback_requested|booked|...
    duration_sec: int = 0
    callback_at: str = ""            # set when outcome == callback_requested
    transcript_ref: str = ""
    recording_url: str = ""
    extracted: dict = field(default_factory=dict)
    region: str = ""
    branch: str = ""
    id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=now_iso)


@dataclass
class Rollup:
    """Pre-aggregated metrics for a scope+period, refreshed by the orchestrator."""
    account_id: str
    scope_level: str                 # all|region|branch
    scope_value: str                 # "" for all, region name, or branch name
    period: str
    payload: dict
    narrative: str = ""
    id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=now_iso)


def to_row(obj) -> dict:
    """Serialize a dataclass model to a store row (dict)."""
    return asdict(obj)
