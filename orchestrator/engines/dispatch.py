"""Assignment / Dispatch engine — the outbound-call entry point.

Pulls pending leads, stamps the active goal context, picks a DID (round-robin),
fires each call through the voice adapter, and records an Assignment per accepted
call. A two-step confirmation gate (preview -> confirm -> dispatch) ensures a
mass-dial can never happen by accident.

NOTE: the confirmation gate is an in-process set on the engine instance. That is
fine for the single-process demo; a multi-process deployment would need to move
this gate into the shared store (or a TTL cache) so confirmations survive across
workers.
"""

from __future__ import annotations

from ..adapters.base import DispatchRequest
from ..models import (
    Assignment,
    AssignmentState,
    T_ASSIGNMENTS,
    T_GOALS,
    new_id,
    to_row,
)


class DispatchEngine:
    def __init__(self, store, voice, crm):
        self._store = store
        self._voice = voice
        self._crm = crm
        # Round-robin index into the DID pool.
        self._did_idx = 0
        # In-process confirmation gate: session_id -> confirmed(bool).
        # A session must be confirmed before dispatch will dial (see note above).
        self._gate: dict[str, bool] = {}

    def active_goal(self, account_id) -> dict | None:
        goals = self._store.list(T_GOALS, where={"account_id": account_id, "active": True})
        return goals[0] if goals else None

    def _goal_context(self, goal_row) -> dict:
        if goal_row is None:
            return {}
        return {
            "goal_id": goal_row["id"],
            "month": goal_row["month"],
            "focus_type": goal_row["focus_type"],
            "focus_detail": goal_row["focus_detail"],
        }

    def preview(self, account_id, scope=None) -> dict:
        pending = self._crm.get_leads(account_id, {"status": "pending", **(scope or {})})
        session_id = new_id()
        self._gate[session_id] = False  # UNCONFIRMED until confirm() is called
        return {
            "session_id": session_id,
            "count": len(pending),
            "sample": [l["name"] for l in pending[:5]],
            "goal": self.active_goal(account_id),
        }

    def confirm(self, session_id) -> bool:
        if session_id not in self._gate:
            return False
        self._gate[session_id] = True
        return True

    def dispatch(self, account_id, session_id, scope=None) -> dict:
        # SAFETY: never dial without an explicit confirmation for this session.
        if not self._gate.get(session_id, False):
            return {"dispatched": 0, "error": "not confirmed", "execution_ids": []}

        goal = self.active_goal(account_id)
        gctx = self._goal_context(goal)
        script_version = goal["script_version"] if goal else "v1"

        pending = self._crm.get_leads(account_id, {"status": "pending", **(scope or {})})
        dids = self._voice.list_dids() or [""]

        execution_ids: list[str] = []
        errors: list[dict] = []
        n_accepted = 0

        for lead in pending:
            did = dids[self._did_idx % len(dids)]
            self._did_idx += 1
            execution_id = new_id()

            req = DispatchRequest(
                lead_id=lead["id"],
                to_number=lead["phone"],
                from_did=did,
                execution_id=execution_id,
                goal_context=gctx,
                script_version=script_version,
                customer_name=lead.get("name", ""),
            )
            res = self._voice.dispatch_call(req)

            if res.accepted:
                assignment = Assignment(
                    account_id=account_id,
                    lead_id=lead["id"],
                    region=lead.get("region", ""),
                    branch=lead.get("branch", ""),
                    goal_context=gctx,
                    did=did,
                    execution_id=execution_id,
                    state=AssignmentState.CALLING.value,
                )
                self._store.insert(T_ASSIGNMENTS, to_row(assignment))
                self._crm.update_lead(lead["id"], {"status": "calling"})
                execution_ids.append(execution_id)
                n_accepted += 1
            else:
                errors.append({"lead_id": lead["id"], "error": res.error})

        # One-shot: consume the session so the same confirmation can't be replayed.
        self._gate.pop(session_id, None)

        return {"dispatched": n_accepted, "execution_ids": execution_ids, "errors": errors}
