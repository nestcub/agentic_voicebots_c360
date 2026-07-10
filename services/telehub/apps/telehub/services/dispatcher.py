"""
Sends the outbound call request for a pending Execution to the Communication
node's configured api_url. Mirrors ngrok.py's stdlib-only HTTP pattern
(urllib.request, no `requests`/`httpx` dependency) and never raises — every
failure mode is caught, recorded as an ExecutionEvent, and returned as a
result dict so a caller (a later scheduler, not built yet) can decide what to
do next.
"""
import json
import os
import urllib.error
import urllib.request

from ..models import Execution, ExecutionEvent, NodeInstance

NODE_NAME_COMMUNICATION = "Communication"

# Truncate stored response bodies so a chatty endpoint never bloats the DB.
RESPONSE_BODY_TRUNCATE_LEN = 500

DISPATCH_TIMEOUT_SEC = 5


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

    execution.attempt_count += 1

    try:
        request = urllib.request.Request(
            api_url,
            data=json.dumps(body).encode(),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=DISPATCH_TIMEOUT_SEC) as response:
            status_code = response.getcode()
            response_body = response.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        # urlopen raises HTTPError (a URLError subclass) for non-2xx status
        # codes instead of returning them normally — handle it first so the
        # real status code/body reach the ExecutionEvent, not just str(exc).
        status_code = exc.code
        try:
            response_body = exc.read().decode(errors="replace")
        except Exception:
            response_body = ""
        error = f"non-2xx status: {status_code}"
        execution.status = "dispatch_failed"
        execution.save()
        ExecutionEvent.objects.create(
            execution=execution,
            event_type="dispatch_failed",
            payload={
                "status_code": status_code,
                "response_body": response_body[:RESPONSE_BODY_TRUNCATE_LEN],
                "error": error,
            },
        )
        return {"success": False, "status_code": status_code, "error": error}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        execution.status = "dispatch_failed"
        execution.save()
        ExecutionEvent.objects.create(
            execution=execution,
            event_type="dispatch_failed",
            payload={"error": str(exc)},
        )
        return {"success": False, "status_code": None, "error": str(exc)}
    except Exception as exc:
        execution.status = "dispatch_failed"
        execution.save()
        ExecutionEvent.objects.create(
            execution=execution,
            event_type="dispatch_failed",
            payload={"error": str(exc)},
        )
        return {"success": False, "status_code": None, "error": str(exc)}

    if 200 <= status_code < 300:
        execution.status = "dispatched"
        execution.save()
        ExecutionEvent.objects.create(
            execution=execution,
            event_type="dispatch_attempted",
            payload={
                "status_code": status_code,
                "response_body": response_body[:RESPONSE_BODY_TRUNCATE_LEN],
            },
        )
        return {"success": True, "status_code": status_code, "error": None}

    error = f"non-2xx status: {status_code}"
    execution.status = "dispatch_failed"
    execution.save()
    ExecutionEvent.objects.create(
        execution=execution,
        event_type="dispatch_failed",
        payload={
            "status_code": status_code,
            "response_body": response_body[:RESPONSE_BODY_TRUNCATE_LEN],
            "error": error,
        },
    )
    return {"success": False, "status_code": status_code, "error": error}
