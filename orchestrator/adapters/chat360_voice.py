"""Chat360 voice dispatch adapter — places outbound voicebot calls via Chat360's API.

This adapter only handles *dispatch* (the immediate accept/reject of an outbound call
request). The post-call OUTCOME (status, transcript, extracted fields, etc.) is NOT
returned here. It arrives asynchronously via the webhook the orchestrator exposes at
``/orchestrator/webhook/chat360/outcome``, correlated by ``dlr_id`` (== execution_id).
"""

from __future__ import annotations

import json

import httpx

from orchestrator import config
from orchestrator.adapters.base import DispatchRequest, DispatchResult


class Chat360VoiceDispatcher:
    """VoiceDispatchAdapter implementation backed by Chat360's outbound call API."""

    def __init__(
        self,
        outbound_url: str | None = None,
        auth_cookie: str | None = None,
        dids: list[str] | None = None,
        timeout: float = 15.0,
    ):
        self._outbound_url = outbound_url if outbound_url is not None else config.CHAT360_OUTBOUND_URL
        self._auth_cookie = auth_cookie if auth_cookie is not None else config.CHAT360_AUTH_COOKIE
        self._dids = list(dids) if dids is not None else list(config.DID_POOL)
        self._client = httpx.Client(timeout=timeout)

    def list_dids(self) -> list[str]:
        """Return the configured DID pool (list of caller numbers)."""
        return list(self._dids)

    def dispatch_call(self, req: DispatchRequest) -> DispatchResult:
        """Place one outbound call. Never raises — always returns a DispatchResult."""
        headers = {
            "Content-Type": "application/json",
            "Cookie": self._auth_cookie,
        }
        body = {
            "From": req.from_did,
            "To": req.to_number,
            "dlr_id": req.execution_id,
            "other_field_1": json.dumps(req.goal_context),
            "other_field_2": req.script_version,
            "other_field_3": req.customer_name,
        }
        try:
            resp = self._client.post(self._outbound_url, headers=headers, json=body)
        except Exception as exc:  # network error, timeout, bad URL, etc.
            return DispatchResult(
                execution_id=req.execution_id,
                accepted=False,
                error=str(exc),
            )

        if resp.status_code < 400:
            return DispatchResult(execution_id=req.execution_id, accepted=True)

        return DispatchResult(
            execution_id=req.execution_id,
            accepted=False,
            error=f"HTTP {resp.status_code}: {resp.text}",
        )
