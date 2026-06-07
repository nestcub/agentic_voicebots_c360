"""Goal-Adaptation Engine — kills Pain B.

When the monthly goal flips (e.g. service-X -> product-Y), prior-goal follow-up
commitments must be HONORED, never dropped, while new-goal outreach proceeds. This
engine changes the active goal WITHOUT touching any existing commitments, and when
planning capacity it gives due (protected) follow-ups priority over new-goal outreach.

CRITICAL INVARIANT: set_goal never reads, modifies, or deletes a Commitment. Existing
commitments keep their original goal_context, so an in-flight follow-up promised under
the old goal is still serviced after the goal changes. That is what protects Pain B.
"""

from __future__ import annotations

from .. import config
from ..models import (
    Goal,
    Target,
    T_GOALS,
    T_TARGETS,
    to_row,
)


# Auto-bump map for script versions when a goal flips and no version is supplied.
_NEXT_VERSION = {"v1": "v2", "v2": "v3"}


class GoalAdaptationEngine:
    """Switches the active goal without disturbing protected commitments."""

    def __init__(self, store, followup, dispatch=None):
        self.store = store
        self.followup = followup
        self.dispatch = dispatch

    # ── goal context helper ───────────────────────────────────────────────────────

    def _goal_context(self, goal_row) -> dict:
        """Compact goal_context stamped on commitments/calls for attribution."""
        if goal_row is None:
            return {}
        return {
            "goal_id": goal_row["id"],
            "month": goal_row["month"],
            "focus_type": goal_row["focus_type"],
            "focus_detail": goal_row["focus_detail"],
        }

    # ── goal reads ────────────────────────────────────────────────────────────────

    def active_goal(self, account_id) -> dict | None:
        goals = self.store.list(T_GOALS, where={"account_id": account_id, "active": True})
        return goals[0] if goals else None

    # ── goal switch ───────────────────────────────────────────────────────────────

    def set_goal(self, account_id, *, month, focus_type, focus_detail,
                 script_version=None, set_by="human") -> dict:
        """Flip the active goal. Deactivates prior active goals, inserts the new one.

        Does NOT touch commitments — prior-goal follow-ups keep their goal_context and
        are still honored by the follow-up engine after the switch (Pain B).
        """
        prev = self.active_goal(account_id)

        # 1) Deactivate ALL currently-active goals for this account.
        for goal in self.store.list(T_GOALS, where={"account_id": account_id, "active": True}):
            self.store.update(T_GOALS, goal["id"], {"active": False})

        # 2) Resolve the script version (auto-bump from the previous active goal if absent).
        if script_version is None:
            if prev is None:
                script_version = "v1"
            else:
                script_version = _NEXT_VERSION.get(prev.get("script_version", "v1"), "v3")

        # 3) Insert the new active goal and return its row.
        goal = Goal(
            account_id=account_id,
            month=month,
            focus_type=focus_type,
            focus_detail=focus_detail,
            script_version=script_version,
            set_by=set_by,
            active=True,
        )
        return self.store.insert(T_GOALS, to_row(goal))

    # ── targets ───────────────────────────────────────────────────────────────────

    def set_target(self, account_id, *, period, reach_out, close, follow_up) -> dict:
        """Set (or replace) the Target numbers for (account_id, period)."""
        existing = self.store.list(
            T_TARGETS, where={"account_id": account_id, "period": period}
        )
        fields = {"reach_out": reach_out, "close": close, "follow_up": follow_up}
        if existing:
            return self.store.update(T_TARGETS, existing[0]["id"], fields)
        target = Target(
            account_id=account_id,
            period=period,
            reach_out=reach_out,
            close=close,
            follow_up=follow_up,
        )
        return self.store.insert(T_TARGETS, to_row(target))

    # ── capacity planning ─────────────────────────────────────────────────────────

    def plan_capacity(self, account_id, total_capacity=None, as_of=None) -> dict:
        """Split capacity, giving due (protected) follow-ups priority over new outreach."""
        if total_capacity is None:
            total_capacity = config.DID_CONCURRENCY

        due = len(self.followup.due_commitments(as_of))
        followup_cap = min(due, total_capacity)
        new_goal_cap = total_capacity - followup_cap

        return {
            "total": total_capacity,
            "due_commitments": due,
            "followups": followup_cap,
            "new_goal": new_goal_cap,
            "reserve_fraction": config.FOLLOWUP_CAPACITY_RESERVE,
        }

    # ── run cycle ─────────────────────────────────────────────────────────────────

    def run_cycle(self, account_id, total_capacity=None, as_of=None) -> dict:
        """Service PROTECTED commitments first (incl. prior-goal follow-ups), then report.

        process_due honors old commitments regardless of which goal is currently active.
        """
        cap = self.plan_capacity(account_id, total_capacity, as_of)
        processed = self.followup.process_due(as_of)
        return {
            "capacity": cap,
            "followups_processed": processed,
            "active_goal": self.active_goal(account_id),
        }
