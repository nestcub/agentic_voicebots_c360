"""Follow-up Reliability Engine — the deterministic core that guarantees a promised
follow-up is never silently dropped (Pain A).

This is plain Python logic over the Store + a VoiceDispatchAdapter — no LLM. Every
follow-up is a durable Commitment row. A commitment is only ever closed by an explicit
terminal state (done / not_interested / exhausted / cancelled); it is NEVER deleted and
NEVER expires by elapsed time or a goal change. If a post-call outcome webhook never
arrives, the pushed-forward due_at means process_due retries it on the next cycle until
max_retries, after which it becomes 'exhausted' (still recorded for a human to see).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .. import config
from ..adapters.base import (
    CallResult,
    CRMAdapter,
    DispatchRequest,
    VoiceDispatchAdapter,
)
from ..models import (
    Commitment,
    CommitmentState,
    T_COMMITMENTS,
    T_LEADS,
    new_id,
    now_iso,
    to_row,
)
from ..store import Store


def _iso_plus_hours(base_iso: str, hours: float) -> str:
    """Return base_iso shifted forward by `hours`, as an ISO-8601 UTC string.

    Falls back to (now + hours) if base_iso can't be parsed, so a malformed timestamp
    can never strand a commitment with an un-shiftable due_at.
    """
    try:
        base = datetime.fromisoformat(base_iso)
    except (TypeError, ValueError):
        base = datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return (base + timedelta(hours=hours)).isoformat()


class FollowupEngine:
    """Commitment ledger with retry/backoff and a never-drop guarantee."""

    def __init__(self, store: Store, voice: VoiceDispatchAdapter,
                 crm: CRMAdapter | None = None):
        self.store = store
        self.voice = voice
        self.crm = crm
        # round-robin cursor over the voice provider's DID pool
        self._did_idx = 0

    # ── creation ────────────────────────────────────────────────────────────────

    def create_commitment(self, *, account_id, lead_id, region, branch, due_at,
                          goal_context, note="", sla_hours=24.0,
                          max_retries=None) -> dict:
        """Build a Commitment, persist it to T_COMMITMENTS, and return the row."""
        if max_retries is None:
            max_retries = config.FOLLOWUP_MAX_RETRIES
        commitment = Commitment(
            account_id=account_id,
            lead_id=lead_id,
            region=region,
            branch=branch,
            due_at=due_at,
            goal_context=goal_context,
            note=note,
            sla_hours=sla_hours,
            max_retries=max_retries,
        )
        return self.store.insert(T_COMMITMENTS, to_row(commitment))

    # ── scheduling reads ────────────────────────────────────────────────────────

    def due_commitments(self, as_of=None) -> list[dict]:
        """Pending commitments whose due_at <= as_of (defaults to now)."""
        return self.store.commitments_due(as_of)

    # ── dispatch cycle ──────────────────────────────────────────────────────────

    def _next_did(self) -> str:
        """Round-robin a DID from the voice pool; '' if the pool is empty."""
        dids = self.voice.list_dids()
        if not dids:
            return ""
        did = dids[self._did_idx % len(dids)]
        self._did_idx += 1
        return did

    def _backoff_hours(self, retries: int) -> float:
        """Backoff for the given attempt number (1-based), clamped to the table tail."""
        table = config.FOLLOWUP_BACKOFF_HOURS
        return table[min(retries - 1, len(table) - 1)]

    def process_due(self, as_of=None, did_picker=None) -> dict:
        """Dispatch a call for every due commitment, applying retry/backoff.

        Exhausted commitments (retries >= max_retries) are marked terminal and recorded,
        never deleted. Each dispatched commitment has its due_at pushed forward by the
        backoff so it is not re-picked until its outcome arrives or the backoff elapses.
        """
        as_of = as_of or now_iso()
        dispatched = 0
        exhausted = 0
        execution_ids: list[str] = []

        for commitment in self.due_commitments(as_of):
            if commitment.get("state") != CommitmentState.PENDING.value:
                continue

            if commitment.get("retries", 0) >= commitment.get("max_retries",
                                                               config.FOLLOWUP_MAX_RETRIES):
                self.store.update(
                    T_COMMITMENTS, commitment["id"],
                    {"state": CommitmentState.EXHAUSTED.value},
                )
                exhausted += 1
                continue

            did = did_picker(commitment) if did_picker else self._next_did()

            lead = self.store.get(T_LEADS, commitment["lead_id"]) or {}
            phone = lead.get("phone", "") or ""
            name = lead.get("name", "") or ""

            execution_id = new_id()
            req = DispatchRequest(
                lead_id=commitment["lead_id"],
                to_number=phone,
                from_did=did,
                execution_id=execution_id,
                goal_context=commitment["goal_context"],
                customer_name=name,
            )
            self.voice.dispatch_call(req)

            new_retries = commitment.get("retries", 0) + 1
            next_due = _iso_plus_hours(as_of, self._backoff_hours(new_retries))
            self.store.update(
                T_COMMITMENTS, commitment["id"],
                {
                    "retries": new_retries,
                    "last_execution_id": execution_id,
                    "due_at": next_due,
                    "state": CommitmentState.PENDING.value,
                },
            )
            dispatched += 1
            execution_ids.append(execution_id)

        return {
            "dispatched": dispatched,
            "exhausted": exhausted,
            "execution_ids": execution_ids,
        }

    # ── outcome correlation ─────────────────────────────────────────────────────

    def record_outcome(self, execution_id, result: CallResult) -> dict | None:
        """Apply a post-call outcome to the commitment that owns this execution_id.

        Maps the result.outcome to a new state. Terminal outcomes close the commitment;
        a callback reschedules it; transient outcomes leave it pending (process_due has
        already rescheduled it). The commitment is never deleted.
        """
        commitment = None
        for row in self.store.list(T_COMMITMENTS):
            if row.get("last_execution_id") == execution_id:
                commitment = row
                break
        if commitment is None:
            return None

        outcome = result.outcome
        fields: dict = {}
        if outcome in ("booked", "interested", "done"):
            fields["state"] = CommitmentState.DONE.value
        elif outcome == "not_interested":
            fields["state"] = CommitmentState.NOT_INTERESTED.value
        elif outcome == "callback_requested":
            fields["state"] = CommitmentState.PENDING.value
            if result.callback_at:
                fields["due_at"] = result.callback_at
        else:
            # no_answer / busy / empty — stays pending (already rescheduled by process_due)
            fields["state"] = CommitmentState.PENDING.value

        return self.store.update(T_COMMITMENTS, commitment["id"], fields)

    # ── loop closure ────────────────────────────────────────────────────────────

    def from_call_outcome(self, outcome_row) -> dict | None:
        """If a call_outcomes row requested a callback, spawn a fresh commitment for it.

        This closes the loop so a promised callback is never lost, even if it came from a
        call that wasn't itself driven by a commitment. Returns the new row, else None.
        """
        if outcome_row.get("outcome") != "callback_requested":
            return None
        return self.create_commitment(
            account_id=outcome_row.get("account_id", ""),
            lead_id=outcome_row.get("lead_id", ""),
            region=outcome_row.get("region", ""),
            branch=outcome_row.get("branch", ""),
            due_at=outcome_row.get("callback_at") or now_iso(),
            goal_context=outcome_row.get("goal_context", {}),
            note="callback from call",
        )
