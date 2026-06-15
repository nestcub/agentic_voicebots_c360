"""Generic REST CRM adapter — implements the CRMAdapter Protocol over a connection dict.

Talks to a CRM that exposes conventional REST endpoints under the connection's base_url:
  GET    {base_url}/campaigns
  GET    {base_url}/leads
  PATCH  {base_url}/leads/{lead_id}
  POST   {base_url}/leads/{lead_id}/outcomes
CRM-specific shapes (HubSpot/Zoho/LeadSquared) can subclass and override endpoints.
"""

from __future__ import annotations

import httpx

from .. import config


class RestCRMAdapter:
    """CRMAdapter backed by a generic REST CRM described by a connection dict."""

    def __init__(self, conn: dict):
        self.base_url = (conn.get("base_url") or "").rstrip("/")
        self.api_key = conn.get("api_key") or ""
        self.headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def get_campaigns(self, account_id: str) -> list[dict]:
        resp = httpx.get(
            f"{self.base_url}/campaigns",
            headers=self.headers,
            timeout=config.CRM_TIMEOUT_SEC,
        )
        resp.raise_for_status()
        return resp.json() or []

    def get_leads(self, account_id: str, filters: dict | None = None) -> list[dict]:
        resp = httpx.get(
            f"{self.base_url}/leads",
            headers=self.headers,
            params=filters or {},
            timeout=config.CRM_TIMEOUT_SEC,
        )
        resp.raise_for_status()
        return resp.json() or []

    def update_lead(self, lead_id: str, fields: dict) -> None:
        resp = httpx.patch(
            f"{self.base_url}/leads/{lead_id}",
            headers=self.headers,
            json=fields,
            timeout=config.CRM_TIMEOUT_SEC,
        )
        resp.raise_for_status()

    def write_outcome(self, lead_id: str, outcome: dict) -> None:
        resp = httpx.post(
            f"{self.base_url}/leads/{lead_id}/outcomes",
            headers=self.headers,
            json=outcome,
            timeout=config.CRM_TIMEOUT_SEC,
        )
        resp.raise_for_status()
