"""Simulation adapters — drive the full pipeline with no external calls or credentials.

Used for tests and the offline demo. SimulationVoiceDispatcher records dispatches and can
synthesize deterministic outcomes; SupabaseCRMAdapter / LocalCRMAdapter read leads from the Store.
"""

from __future__ import annotations

import random

from ..store import Store, get_store
from ..models import T_LEADS, CallStatus
from .base import DispatchRequest, DispatchResult, CallResult


class StoreCRMAdapter:
    """CRM adapter backed by the orchestrator Store's `leads` table.

    Doubles as the demo SupabaseCRMAdapter when the Store is SupabaseStore, and as a
    local CRM when the Store is LocalStore — same code, backend chosen by the Store.
    """

    def __init__(self, store: Store | None = None):
        self._store = store or get_store()

    def get_campaigns(self, account_id: str) -> list[dict]:
        # Demo: one implicit campaign == all leads for the account.
        return [{"id": f"campaign-{account_id}", "account_id": account_id}]

    def get_leads(self, account_id: str, filters: dict | None = None) -> list[dict]:
        where = {"account_id": account_id}
        if filters:
            where.update(filters)
        return self._store.list(T_LEADS, where=where)

    def update_lead(self, lead_id: str, fields: dict) -> None:
        self._store.update(T_LEADS, lead_id, fields)

    def write_outcome(self, lead_id: str, outcome: dict) -> None:
        # Mirror the business outcome onto the lead's status for CRM-side visibility.
        status = outcome.get("outcome") or outcome.get("call_status")
        if status:
            self._store.update(T_LEADS, lead_id, {"status": status})


class SimulationVoiceDispatcher:
    """Records dispatches; can synthesize outcomes for deterministic tests/demo."""

    def __init__(self, dids: list[str] | None = None, seed: int | None = None):
        self._dids = dids or ["+910000000001", "+910000000002"]
        self.dispatched: list[DispatchRequest] = []
        self._rng = random.Random(seed)

    def list_dids(self) -> list[str]:
        return list(self._dids)

    def dispatch_call(self, req: DispatchRequest) -> DispatchResult:
        self.dispatched.append(req)
        return DispatchResult(execution_id=req.execution_id, accepted=True)

    def synthesize_result(self, req: DispatchRequest, outcome: str | None = None) -> CallResult:
        """Produce a plausible post-call result for a prior dispatch (test helper)."""
        if outcome is None:
            outcome = self._rng.choice(
                ["interested", "not_interested", "callback_requested", "booked", "no_answer"]
            )
        status = (
            CallStatus.NO_ANSWER.value if outcome == "no_answer" else CallStatus.COMPLETED.value
        )
        return CallResult(
            execution_id=req.execution_id,
            call_status=status,
            outcome=outcome,
            duration_sec=0 if outcome == "no_answer" else self._rng.randint(30, 240),
        )
