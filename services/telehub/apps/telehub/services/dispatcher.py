"""
Sends the outbound call request for a pending Execution to the Communication
node's configured api_url. Mirrors ngrok.py's stdlib-only HTTP pattern
(urllib.request, no `requests`/`httpx` dependency) and never raises — every
failure mode is caught, recorded as an ExecutionEvent, and returned as a
result dict so a caller (a later scheduler, not built yet) can decide what to
do next.
"""
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

from ..models import Execution, ExecutionEvent, NodeInstance

logger = logging.getLogger(__name__)

NODE_NAME_COMMUNICATION = "Communication"

# Truncate stored response bodies so a chatty endpoint never bloats the DB.
RESPONSE_BODY_TRUNCATE_LEN = 500

DISPATCH_TIMEOUT_SEC = 5

# Python's urllib deliberately does NOT auto-follow 307/308 redirects for POST
# requests (it only auto-follows those for GET/HEAD — resending a POST body
# without the caller's say-so is a correctness/side-effect risk the stdlib
# won't take on its own). Chat360's outbound endpoint 307-redirects
# non-trailing-slash paths to the trailing-slash form, so we follow it
# ourselves — we control the body and know it's safe to resend unchanged.
# Capped so a redirect loop can't hang a dispatch forever.
MAX_REDIRECTS = 3


def _get_communication_config(execution: "Execution") -> dict:
    """
    Defensively reads the Communication NodeInstance's config for this
    Execution's process_agent. generate_journey always creates this node, but
    never trust it blindly — treat a missing node (or any lookup error) as an
    empty config rather than raising.
    """
    try:
        return execution.process_agent.nodes.get(name=NODE_NAME_COMMUNICATION).config or {}
    except NodeInstance.DoesNotExist:
        return {}
    except Exception:
        return {}


def _send_once(url: str, body_bytes: bytes, headers: dict):
    """
    One raw POST attempt. Returns (status_code, response_body, location) —
    urllib raises HTTPError instead of returning non-2xx responses normally,
    so both paths are unified into the same return shape here rather than
    handled separately by every caller.
    """
    request = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=DISPATCH_TIMEOUT_SEC) as response:
            return (
                response.getcode(),
                response.read().decode(errors="replace"),
                response.headers.get("Location"),
            )
    except urllib.error.HTTPError as exc:
        try:
            response_body = exc.read().decode(errors="replace")
        except Exception:
            response_body = ""
        location = exc.headers.get("Location") if exc.headers else None
        return exc.code, response_body, location


def dispatch_execution(execution: "Execution") -> dict:
    """
    Sends the outbound call request for a pending Execution to the Communication
    node's configured api_url. Never raises — catches every exception, always
    records an ExecutionEvent describing what happened, and returns a result dict
    so a caller (a later scheduler, not built yet) can decide what to do next.

    Returns: {"success": bool, "status_code": int | None, "error": str | None}
    """
    communication_config = _get_communication_config(execution)
    api_url = communication_config.get("api_url", "")

    if not api_url:
        execution.attempt_count += 1
        execution.status = "dispatch_failed"
        execution.save()
        ExecutionEvent.objects.create(
            execution=execution,
            event_type="dispatch_skipped",
            payload={"error": "no api_url configured on Communication node"},
        )
        return {
            "success": False,
            "status_code": None,
            "error": "no api_url configured on Communication node",
        }

    headers = {
        "Authorization": f"Bearer {os.environ.get('CHAT360_OUTBOUND_BEARER_TOKEN', '')}",
        "Content-Type": "application/json",
        "Cookie": os.environ.get("CHAT360_AUTH_COOKIE", ""),
    }

    body = {
        **execution.variables,
        "To": execution.variables.get("to_number", ""),
        "dlr_id": execution.id,
        "bot_id": communication_config.get("bot_id", ""),
        "bot_name": communication_config.get("bot_name", ""),
    }
    body_bytes = json.dumps(body).encode()

    execution.attempt_count += 1

    logger.info(
        "dispatch attempt: execution=%s POST %s bot_id=%s auth_header_set=%s cookie_set=%s body_keys=%s",
        execution.id,
        api_url,
        body.get("bot_id") or "(none)",
        bool(os.environ.get("CHAT360_OUTBOUND_BEARER_TOKEN")),
        bool(os.environ.get("CHAT360_AUTH_COOKIE")),
        sorted(body.keys()),
    )

    current_url = api_url
    try:
        for hop in range(MAX_REDIRECTS + 1):
            status_code, response_body, location = _send_once(current_url, body_bytes, headers)
            if status_code in (307, 308) and location and hop < MAX_REDIRECTS:
                current_url = urllib.parse.urljoin(current_url, location)
                logger.info(
                    "dispatch redirect: execution=%s %s -> %s (hop %d/%d)",
                    execution.id, status_code, current_url, hop + 1, MAX_REDIRECTS,
                )
                continue
            break
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.error("dispatch failed: execution=%s network error: %s", execution.id, exc)
        execution.status = "dispatch_failed"
        execution.save()
        ExecutionEvent.objects.create(
            execution=execution,
            event_type="dispatch_failed",
            payload={"error": str(exc)},
        )
        return {"success": False, "status_code": None, "error": str(exc)}
    except Exception as exc:
        logger.error("dispatch failed: execution=%s unexpected error: %s", execution.id, exc)
        execution.status = "dispatch_failed"
        execution.save()
        ExecutionEvent.objects.create(
            execution=execution,
            event_type="dispatch_failed",
            payload={"error": str(exc)},
        )
        return {"success": False, "status_code": None, "error": str(exc)}

    if 200 <= status_code < 300:
        logger.info("dispatch succeeded: execution=%s status=%s url=%s", execution.id, status_code, current_url)
        execution.status = "dispatched"
        execution.save()
        ExecutionEvent.objects.create(
            execution=execution,
            event_type="dispatch_attempted",
            payload={
                "status_code": status_code,
                "final_url": current_url,
                "response_body": response_body[:RESPONSE_BODY_TRUNCATE_LEN],
            },
        )
        return {"success": True, "status_code": status_code, "error": None}

    error = f"non-2xx status: {status_code}" + (f" (redirects to {location})" if location else "")
    logger.error(
        "dispatch failed: execution=%s status=%s location=%s body=%s",
        execution.id, status_code, location, response_body[:RESPONSE_BODY_TRUNCATE_LEN],
    )
    execution.status = "dispatch_failed"
    execution.save()
    ExecutionEvent.objects.create(
        execution=execution,
        event_type="dispatch_failed",
        payload={
            "status_code": status_code,
            "location": location,
            "final_url": current_url,
            "response_body": response_body[:RESPONSE_BODY_TRUNCATE_LEN],
            "error": error,
        },
    )
    return {"success": False, "status_code": status_code, "error": error}
