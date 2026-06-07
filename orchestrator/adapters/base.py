"""Adapter Protocols + shared value objects — the portability core."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class DispatchRequest:
    """Everything a voice provider needs to place one outbound call."""
    lead_id: str
    to_number: str
    from_did: str
    execution_id: str           # our correlation key (Chat360 dlr_id)
    goal_context: dict
    script_version: str = "v1"
    customer_name: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class DispatchResult:
    """Immediate response from a dispatch call (not the post-call outcome)."""
    execution_id: str
    accepted: bool
    error: str = ""


@dataclass
class CallResult:
    """Normalized post-call outcome (arrives via webhook for Chat360)."""
    execution_id: str
    call_status: str            # completed|no_answer|busy|failed
    outcome: str = ""           # interested|not_interested|callback_requested|booked|...
    duration_sec: int = 0
    callback_at: str = ""
    transcript_ref: str = ""
    recording_url: str = ""
    extracted: dict = field(default_factory=dict)


class CRMAdapter(Protocol):
    """Lead source + outcome sink. Implemented per CRM (Supabase demo / LMS / Maruti)."""

    def get_campaigns(self, account_id: str) -> list[dict]: ...
    def get_leads(self, account_id: str, filters: dict | None = None) -> list[dict]: ...
    def update_lead(self, lead_id: str, fields: dict) -> None: ...
    def write_outcome(self, lead_id: str, outcome: dict) -> None: ...


class VoiceDispatchAdapter(Protocol):
    """Outbound voice provider. Implemented per provider (Chat360 / Bolna / simulation)."""

    def list_dids(self) -> list[str]: ...
    def dispatch_call(self, req: DispatchRequest) -> DispatchResult: ...
    # Outcomes arrive via webhook → orchestrator.api; providers needing polling may
    # additionally implement get_result(execution_id) -> CallResult | None.
