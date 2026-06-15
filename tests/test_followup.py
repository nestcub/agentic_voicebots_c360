"""Regression tests for the Follow-up Reliability Engine's never-drop guarantee (Pain A).

The single most important property of the FollowupEngine is that a promised follow-up is
NEVER silently lost: a Commitment row is only ever closed by an explicit terminal state
(done / not_interested / exhausted / cancelled) and is NEVER deleted. These tests exercise
the dispatch/reschedule cycle, retry exhaustion, positive resolution, callback loop-closure,
and row-count conservation to prove that guarantee holds.

Plain script — no pytest required. Run:
    python3 tests/test_followup.py
Prints "PASS <name>" per test and "ALL PASS" at the end; exits non-zero on any failure.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

# Make the repo root importable when run as a plain script (python3 tests/test_followup.py).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator.engines.followup import FollowupEngine
from orchestrator.store import MemoryStore
from orchestrator.adapters.simulation import SimulationVoiceDispatcher, StoreCRMAdapter
from orchestrator.adapters.base import CallResult
from orchestrator.models import (
    Lead,
    T_LEADS,
    T_COMMITMENTS,
    CommitmentState,
    to_row,
    now_iso,
)


# ── helpers ──────────────────────────────────────────────────────────────────────

def _fresh_store() -> MemoryStore:
    """A brand-new in-memory store, so every test is fully isolated."""
    return MemoryStore()


def _seed_lead(store: MemoryStore, *, account_id="a", region="Mumbai",
               branch="Andheri") -> str:
    """Insert a Lead into T_LEADS so process_due can resolve a phone; return its id."""
    lead = Lead(
        account_id=account_id,
        name="Test Customer",
        phone="+919999999999",
        region=region,
        branch=branch,
    )
    store.insert(T_LEADS, to_row(lead))
    return lead.id


def _iso_offset(hours: float) -> str:
    """ISO-8601 UTC string `hours` from now (negative = in the past)."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _build():
    """Standard (store, voice, engine, lead_id) wiring shared by the tests."""
    store = _fresh_store()
    voice = SimulationVoiceDispatcher(seed=7)
    StoreCRMAdapter(store)  # exercises the CRM adapter wiring path
    engine = FollowupEngine(store, voice)
    lead_id = _seed_lead(store)
    return store, voice, engine, lead_id


# ── test 1: dispatch + reschedule, commitment survives ───────────────────────────

def test_dispatch_and_reschedule():
    store, voice, engine, lead_id = _build()

    past = _iso_offset(-1)
    row = engine.create_commitment(
        account_id="a", lead_id=lead_id, region="Mumbai", branch="Andheri",
        due_at=past, goal_context={"goal_id": "g1"},
    )
    cid = row["id"]

    as_of = now_iso()
    result = engine.process_due(as_of=as_of)
    assert result["dispatched"] == 1, result

    # Exactly one call placed.
    assert len(voice.dispatched) == 1, len(voice.dispatched)

    # Commitment STILL EXISTS, still pending, retries bumped to 1.
    after = store.get(T_COMMITMENTS, cid)
    assert after is not None, "commitment must never be deleted"
    assert after["state"] == CommitmentState.PENDING.value, after["state"]
    assert after["retries"] == 1, after["retries"]

    # due_at moved into the future relative to the dispatch as_of — no longer due now.
    assert after["due_at"] > as_of, (after["due_at"], as_of)
    assert engine.due_commitments(as_of=as_of) == [], "must not be re-picked at the same as_of"


# ── test 2: never dropped, even through retry exhaustion ──────────────────────────

def test_never_dropped_through_exhaustion():
    store, voice, engine, lead_id = _build()

    engine.create_commitment(
        account_id="a", lead_id=lead_id, region="Mumbai", branch="Andheri",
        due_at=_iso_offset(-1), goal_context={"goal_id": "g1"}, max_retries=2,
    )

    baseline = len(store.list(T_COMMITMENTS))
    assert baseline == 1

    # Advance far into the future repeatedly until exhausted; assert conservation each step.
    state = None
    for step in range(1, 20):
        as_of = _iso_offset(step * 24 * 365)  # leap a year forward each step
        engine.process_due(as_of=as_of)

        rows = store.list(T_COMMITMENTS)
        assert len(rows) == baseline, (
            f"commitment count changed at step {step}: {len(rows)} != {baseline}"
        )
        state = rows[0]["state"]
        if state == CommitmentState.EXHAUSTED.value:
            break

    # Reached the terminal exhausted state, still present, never removed.
    assert state == CommitmentState.EXHAUSTED.value, state
    rows = store.list(T_COMMITMENTS)
    assert len(rows) == baseline, "exhausted commitment must remain in the store"
    assert rows[0]["state"] == CommitmentState.EXHAUSTED.value
    # max_retries=2 → two real dispatches before exhaustion.
    assert len(voice.dispatched) == 2, len(voice.dispatched)


# ── test 3: positive resolution closes the commitment as done ─────────────────────

def test_positive_resolution():
    store, voice, engine, lead_id = _build()

    row = engine.create_commitment(
        account_id="a", lead_id=lead_id, region="Mumbai", branch="Andheri",
        due_at=_iso_offset(-1), goal_context={"goal_id": "g1"},
    )
    cid = row["id"]

    result = engine.process_due(as_of=now_iso())
    execution_id = result["execution_ids"][-1]
    # Cross-check against the recorded dispatch.
    assert execution_id == voice.dispatched[-1].execution_id

    engine.record_outcome(
        execution_id,
        CallResult(execution_id=execution_id, call_status="completed", outcome="booked"),
    )

    after = store.get(T_COMMITMENTS, cid)
    assert after is not None
    assert after["state"] == CommitmentState.DONE.value, after["state"]


# ── test 4: callback loop-closure spawns a fresh commitment ───────────────────────

def test_callback_loop():
    store, voice, engine, lead_id = _build()

    before = len(store.list(T_COMMITMENTS))

    new_row = engine.from_call_outcome({
        "account_id": "a",
        "lead_id": lead_id,
        "region": "Mumbai",
        "branch": "Andheri",
        "goal_context": {"goal_id": "g1"},
        "outcome": "callback_requested",
        "callback_at": now_iso(),
    })

    assert new_row is not None, "callback_requested must spawn a commitment"
    after = len(store.list(T_COMMITMENTS))
    assert after == before + 1, (before, after)

    persisted = store.get(T_COMMITMENTS, new_row["id"])
    assert persisted is not None
    assert persisted["state"] == CommitmentState.PENDING.value, persisted["state"]


# ── test 5: commitment row count is conserved across a full cycle ─────────────────

def test_count_conserved():
    store, voice, engine, lead_id = _build()

    counts: list[int] = []

    def checkpoint(label: str):
        n = len(store.list(T_COMMITMENTS))
        if counts:
            assert n >= counts[-1], (
                f"commitment count DECREASED at '{label}': {n} < {counts[-1]}"
            )
        counts.append(n)
        return n

    # Create 3 commitments, all due in the past.
    rows = [
        engine.create_commitment(
            account_id="a", lead_id=lead_id, region="Mumbai", branch="Andheri",
            due_at=_iso_offset(-1), goal_context={"goal_id": "g1"},
            max_retries=2,
        )
        for _ in range(3)
    ]
    checkpoint("after create x3")
    assert counts[-1] == 3

    # Process several times, leaping forward so retries actually fire.
    for step in range(1, 6):
        engine.process_due(as_of=_iso_offset(step * 24 * 365))
        checkpoint(f"after process step {step}")

    # Resolve one positively.
    target = rows[0]
    persisted = store.get(T_COMMITMENTS, target["id"])
    eid = persisted.get("last_execution_id") or ""
    if eid:
        engine.record_outcome(
            eid, CallResult(execution_id=eid, call_status="completed", outcome="booked")
        )
    else:
        # No dispatch recorded an execution id yet — force a terminal done directly is not
        # part of the public API, so just re-dispatch to obtain one, then resolve.
        engine.process_due(as_of=_iso_offset(10 * 24 * 365))
        persisted = store.get(T_COMMITMENTS, target["id"])
        eid = persisted["last_execution_id"]
        engine.record_outcome(
            eid, CallResult(execution_id=eid, call_status="completed", outcome="booked")
        )
    checkpoint("after resolve one")

    # Exhaust the rest by leaping far enough that retries >= max_retries.
    for step in range(6, 12):
        engine.process_due(as_of=_iso_offset(step * 24 * 365))
        checkpoint(f"after exhaust step {step}")

    final = store.list(T_COMMITMENTS)
    assert len(final) == 3, "all three commitments must still exist (none deleted)"
    states = sorted(r["state"] for r in final)
    # At least one done and at least one exhausted; none missing.
    assert CommitmentState.DONE.value in states, states
    assert CommitmentState.EXHAUSTED.value in states, states
    # Conservation: count never dropped below 3 across all checkpoints.
    assert min(counts) == 3, counts


# ── runner ───────────────────────────────────────────────────────────────────────

TESTS = [
    test_dispatch_and_reschedule,
    test_never_dropped_through_exhaustion,
    test_positive_resolution,
    test_callback_loop,
    test_count_conserved,
]


def main() -> int:
    failed = 0
    for t in TESTS:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001 — surface any unexpected error per-test
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    if failed:
        print(f"{failed} FAILED")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
