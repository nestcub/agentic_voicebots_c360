"""Pain-B regression test — goal adaptation honors prior follow-ups, new goal on fresh leads.

When the monthly goal flips (service-X -> product-Y), prior-goal follow-up commitments are
HONORED (serviced, never dropped) under THEIR OWN goal_context, while new-goal outreach
proceeds under the NEW goal context. This is a pytest-free assert script: each test prints
"PASS <name>", and "ALL PASS" at the end. Non-zero exit on any failure.
"""

from __future__ import annotations

import os
import sys

# Make the repo root importable when run directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator.store import MemoryStore
from orchestrator.adapters.simulation import SimulationVoiceDispatcher, StoreCRMAdapter
from orchestrator.engines.followup import FollowupEngine
from orchestrator.engines.dispatch import DispatchEngine
from orchestrator.engines.goal_adaptation import GoalAdaptationEngine
from orchestrator.models import (
    Lead,
    T_LEADS,
    T_COMMITMENTS,
    T_ASSIGNMENTS,
    to_row,
    now_iso,
)

DIDS = ["+910000000001", "+910000000002"]


def _build():
    """Fresh store + the full engine stack wired exactly as the orchestrator wires it."""
    store = MemoryStore()
    voice = SimulationVoiceDispatcher(DIDS)
    crm = StoreCRMAdapter(store)
    followup = FollowupEngine(store, voice, crm)
    dispatch = DispatchEngine(store, voice, crm)
    ga = GoalAdaptationEngine(store, followup, dispatch)
    return store, voice, crm, followup, dispatch, ga


def _past_iso() -> str:
    """An ISO timestamp well in the past so commitments are immediately due."""
    return "2000-01-01T00:00:00+00:00"


# ── shared fixture: a store carried through the whole Pain-B flow ─────────────────

def _seed_old_commitment():
    """Set goal A (service), seed a lead, create a past-due commitment under goal A,
    then flip to goal B (product). Returns the live state for the chained assertions."""
    store, voice, crm, followup, dispatch, ga = _build()

    gA = ga.set_goal("a", month="2026-06", focus_type="service", focus_detail="Service-X")

    lead = Lead(account_id="a", name="Old Lead", phone="+919000000001",
                region="West", branch="Andheri", status="pending")
    store.insert(T_LEADS, to_row(lead))

    followup.create_commitment(
        account_id="a",
        lead_id=lead.id,
        region="West",
        branch="Andheri",
        due_at=_past_iso(),
        goal_context=ga._goal_context(gA),
        note="promised under Service-X",
    )

    gB = ga.set_goal("a", month="2026-07", focus_type="product", focus_detail="Product-Y")

    return store, voice, crm, followup, dispatch, ga, gA, gB, lead


# ── tests ─────────────────────────────────────────────────────────────────────────

def test_goal_switch_preserves_commitments():
    """Flipping the goal must NOT touch the existing commitment's context or state."""
    store, voice, crm, followup, dispatch, ga, gA, gB, lead = _seed_old_commitment()

    commitments = store.list(T_COMMITMENTS)
    assert len(commitments) == 1, f"expected exactly 1 commitment, got {len(commitments)}"

    c = commitments[0]
    assert c["goal_context"]["focus_detail"] == "Service-X", (
        f"commitment goal_context was overwritten: {c['goal_context']!r}"
    )
    assert c["state"] == "pending", f"commitment state changed to {c['state']!r}"

    # Sanity: the active goal really did flip to the new one.
    assert ga.active_goal("a")["focus_detail"] == "Product-Y"
    print("PASS test_goal_switch_preserves_commitments")


def test_old_followups_serviced_after_switch():
    """After the switch, the OLD due commitment is still dispatched, under ITS OWN context."""
    store, voice, crm, followup, dispatch, ga, gA, gB, lead = _seed_old_commitment()

    voice.dispatched.clear()
    result = ga.run_cycle("a", total_capacity=10)

    assert result["followups_processed"]["dispatched"] == 1, (
        f"old commitment was not serviced: {result['followups_processed']!r}"
    )
    assert len(voice.dispatched) == 1, (
        f"expected 1 dispatched call, got {len(voice.dispatched)}"
    )

    req = voice.dispatched[0]
    assert req.lead_id == lead.id, f"dispatched wrong lead: {req.lead_id!r}"
    assert req.goal_context["focus_detail"] == "Service-X", (
        f"old follow-up not honored under its own goal: {req.goal_context!r}"
    )
    print("PASS test_old_followups_serviced_after_switch")


def test_new_outreach_uses_new_goal():
    """New-goal outreach on fresh pending leads must stamp the NEW goal (Product-Y)."""
    store, voice, crm, followup, dispatch, ga, gA, gB, lead = _seed_old_commitment()

    # Active goal is now gB (Product-Y). Seed two fresh pending leads in a fresh region.
    # We scope dispatch to that region so the old-goal lead (still 'pending', awaiting its
    # follow-up) is not swept into the new-goal mass-dial.
    for i in range(2):
        fresh = Lead(account_id="a", name=f"Fresh {i}", phone=f"+91900000010{i}",
                     region="South", branch="Koramangala", status="pending")
        store.insert(T_LEADS, to_row(fresh))

    scope = {"region": "South"}
    p = dispatch.preview("a", scope)
    assert p["count"] == 2, f"preview should see only the 2 fresh leads, saw {p['count']}"
    assert dispatch.confirm(p["session_id"]) is True
    r = dispatch.dispatch("a", p["session_id"], scope)

    assert r["dispatched"] == 2, f"expected 2 new dispatches, got {r['dispatched']!r}"

    assignments = store.list(T_ASSIGNMENTS, order_by="created_at", desc=True)
    assert len(assignments) == 2, f"expected 2 assignments, got {len(assignments)}"
    for a in assignments:
        assert a["goal_context"]["focus_detail"] == "Product-Y", (
            f"new assignment used the wrong goal: {a['goal_context']!r}"
        )
    print("PASS test_new_outreach_uses_new_goal")


def test_both_goals_coexist_nothing_dropped():
    """End to end: nothing is deleted; a Service-X commitment context and a Product-Y
    assignment context exist in the store SIMULTANEOUSLY."""
    store, voice, crm, followup, dispatch, ga, gA, gB, lead = _seed_old_commitment()

    count_before = len(store.list(T_COMMITMENTS))

    # 1) Service the old commitment (prior-goal follow-up).
    voice.dispatched.clear()
    ga.run_cycle("a", total_capacity=10)

    # 2) Run new-goal outreach on fresh leads in the same store, scoped to the new region
    #    so the old-goal lead (kept pending for its follow-up) is left untouched.
    for i in range(2):
        fresh = Lead(account_id="a", name=f"Fresh {i}", phone=f"+91900000020{i}",
                     region="South", branch="Koramangala", status="pending")
        store.insert(T_LEADS, to_row(fresh))
    scope = {"region": "South"}
    p = dispatch.preview("a", scope)
    dispatch.confirm(p["session_id"])
    dispatch.dispatch("a", p["session_id"], scope)

    # Commitments never dropped (count conserved / non-decreasing).
    commitments = store.list(T_COMMITMENTS)
    assert len(commitments) >= count_before, (
        f"commitments were dropped: {len(commitments)} < {count_before}"
    )
    assert len(commitments) == 1, f"unexpected commitment count: {len(commitments)}"

    # Both goal contexts coexist in the store at once.
    commitment_details = {c["goal_context"].get("focus_detail") for c in commitments}
    assignment_details = {
        a["goal_context"].get("focus_detail") for a in store.list(T_ASSIGNMENTS)
    }
    assert "Service-X" in commitment_details, (
        f"old Service-X commitment context vanished: {commitment_details!r}"
    )
    assert "Product-Y" in assignment_details, (
        f"new Product-Y assignment context missing: {assignment_details!r}"
    )
    print("PASS test_both_goals_coexist_nothing_dropped")


# ── runner ──────────────────────────────────────────────────────────────────────

def main() -> int:
    tests = [
        test_goal_switch_preserves_commitments,
        test_old_followups_serviced_after_switch,
        test_new_outreach_uses_new_goal,
        test_both_goals_coexist_nothing_dropped,
    ]
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
            return 1
        except Exception as e:  # noqa: BLE001 - surface any wiring error as a failure
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
            return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
