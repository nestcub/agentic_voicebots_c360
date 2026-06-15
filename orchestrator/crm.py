"""CRM connection management — store, list, fetch, and test external CRM connections.

Connection configs are persisted via the Store; the generic REST read/write path lives in
`orchestrator.adapters.rest_crm.RestCRMAdapter`. `test_connection` is a pure probe that never
touches the store, so callers decide whether/how to persist the result.
"""

from __future__ import annotations

import httpx

from . import config
from .models import CrmConnection, T_CRM_CONNECTIONS, now_iso, to_row


def create_connection(
    store,
    account_id: str,
    *,
    name: str,
    crm_type: str,
    base_url: str,
    api_key: str = "",
    **extra,
) -> dict:
    """Build a CrmConnection, persist it, and return the stored row."""
    conn = CrmConnection(
        account_id=account_id,
        name=name,
        crm_type=crm_type,
        base_url=base_url,
        api_key=api_key,
    )
    row = to_row(conn)
    row.update(extra)
    return store.insert(T_CRM_CONNECTIONS, row)


def list_connections(store, account_id: str) -> list[dict]:
    """All CRM connections for an account."""
    return store.list(T_CRM_CONNECTIONS, where={"account_id": account_id})


def get_connection(store, conn_id: str) -> dict | None:
    """A single CRM connection by id, or None."""
    return store.get(T_CRM_CONNECTIONS, conn_id)


def test_connection(conn: dict) -> dict:
    """Probe a CRM connection's reachability without writing to the store.

    GETs the connection's base_url with a Bearer token when an api_key is present.
    Returns {"ok": bool, "status_code": int|None, "message": str}. All exceptions are
    caught and reported rather than raised.
    """
    base_url = (conn.get("base_url") or "").rstrip("/")
    api_key = conn.get("api_key") or ""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        resp = httpx.get(base_url, headers=headers, timeout=config.CRM_TIMEOUT_SEC)
        ok = resp.is_success
        return {
            "ok": ok,
            "status_code": resp.status_code,
            "message": "ok" if ok else f"HTTP {resp.status_code}",
        }
    except Exception as e:  # noqa: BLE001 — surface any failure as a clean result
        return {"ok": False, "status_code": None, "message": str(e)}
