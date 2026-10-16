"""
Sends a Chat360 WhatsApp template to one Execution's lead, using a pasted curl
command (one per template, see omnichannel.template_curl) as the request
template — URL, headers and JSON body are all taken from it verbatim, then
filled in per lead:

- every task_body[].receiver_number is replaced with the lead's number
  (caller_number for inbound calls, to_number for outbound), as bare 10 digits
  since the curl carries country_code separately;
- every template_data.param_data value that names a variable ("customer_name":
  "customer_name", or "@customer_name") is replaced with that variable's value
  from execution.variables; anything else (e.g. a fixed "link") is sent as-is.

A placeholder whose variable is missing/empty blocks the send rather than
sending the literal placeholder name to the customer — unless the caller
passes missing_fill, in which case that text is sent in its place.

Stdlib-only and never raises, like dispatcher.py; every send attempt is
recorded as a whatsapp_sent / whatsapp_failed ExecutionEvent with the full
request/response (the Calls tab's status column reads WhatsAppSend instead).
"""
import json
import logging
import shlex

from ..models import Execution, ExecutionEvent
from .dispatcher import _send_once
from .outcome_routing import _normalize_phone

logger = logging.getLogger(__name__)

RESPONSE_BODY_TRUNCATE_LEN = 500

EVENT_SENT = "whatsapp_sent"
EVENT_FAILED = "whatsapp_failed"
EVENT_BLOCKED = "whatsapp_blocked"

_HEADER_FLAGS = {"-H", "--header"}
_DATA_FLAGS = {"-d", "--data", "--data-raw", "--data-binary"}
_METHOD_FLAGS = {"-X", "--request"}
_URL_FLAGS = {"--url"}
_IGNORED_VALUE_FLAGS = {"-u", "--user", "-o", "--output", "-m", "--max-time"}


def parse_curl(curl: str):
    """
    Returns (url, headers, body) from a pasted curl command; body is the
    parsed JSON object. Raises ValueError if there is no URL or no JSON body.
    """
    # Shell line continuations, both Unix ("\") and Windows cmd ("^").
    text = curl.replace("\\\r\n", " ").replace("\\\n", " ").replace("^\r\n", " ").replace("^\n", " ")
    tokens = shlex.split(text)
    if tokens and tokens[0] == "curl":
        tokens = tokens[1:]

    url, headers, data = "", {}, None
    i = 0
    while i < len(tokens):
        token = tokens[i]
        value = tokens[i + 1] if i + 1 < len(tokens) else ""
        if token in _HEADER_FLAGS:
            name, _, header_value = value.partition(":")
            headers[name.strip()] = header_value.strip()
            i += 2
        elif token in _DATA_FLAGS:
            data = value
            i += 2
        elif token in _URL_FLAGS:
            url = value
            i += 2
        elif token in _METHOD_FLAGS or token in _IGNORED_VALUE_FLAGS:
            i += 2
        elif token.startswith("-"):
            i += 1
        else:
            url = url or token
            i += 1

    if not url:
        raise ValueError("no URL found in curl")
    if not data:
        raise ValueError("no JSON body (--data-raw / -d) found in curl")
    try:
        body = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ValueError(f"curl body is not valid JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise ValueError("curl body must be a JSON object")
    return url, headers, body


def _receiver_number(execution: "Execution") -> str:
    variables = execution.variables or {}
    return _normalize_phone(variables.get("caller_number") or variables.get("to_number"))


def build_request(
    execution: "Execution", curl: str, missing_fill=None, variables=None, param_map=None
) -> dict:
    """
    Fills `curl` in for this execution. Returns {"url", "headers", "body",
    "receiver_number", "template_title", "params", "missing",
    "missing_variables", "error"} — "error" is set (and the rest may be empty)
    when the curl is empty or unusable. With missing_fill, empty variable
    params are sent as that text and are not reported in "missing". `variables`
    overrides execution.variables (e.g. with aliases applied). Never raises.

    `param_map` ({param key: entry}, ChannelTemplate.param_map) says where a
    param's value comes from: {"variable": name[, "fallback": other_name]}
    reads that variable, {"fixed": text} sends that text. A param with no
    entry is resolved the old way, by the curl's own placeholder text (a bare
    name, "@name", or the param key itself). "missing" lists the empty
    params' keys; "missing_variables" the variable names behind them, which
    is what someone has to fill in to unblock the send.
    """
    result = {
        "url": "",
        "headers": {},
        "body": {},
        "receiver_number": _receiver_number(execution),
        "template_title": "",
        "params": {},
        "missing": [],
        "missing_variables": [],
        "error": None,
    }
    if not (curl or "").strip():
        result["error"] = "no WhatsApp curl configured for this template"
        return result
    try:
        url, headers, body = parse_curl(curl)
    except ValueError as exc:
        result["error"] = f"WhatsApp curl could not be parsed: {exc}"
        return result
    except Exception as exc:
        result["error"] = str(exc)
        return result

    if variables is None:
        variables = execution.variables or {}
    tasks = body.get("task_body") if isinstance(body.get("task_body"), list) else []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task["receiver_number"] = result["receiver_number"]
        template_data = task.get("template_data")
        if not isinstance(template_data, dict):
            continue
        result["template_title"] = template_data.get("template_title", "")
        param_data = template_data.get("param_data")
        if not isinstance(param_data, dict):
            continue
        for key, placeholder in param_data.items():
            entry = (param_map or {}).get(key)
            entry = entry if isinstance(entry, dict) else {}
            if "fixed" in entry:
                param_data[key] = str(entry["fixed"])
                result["params"][key] = param_data[key]
                continue

            fallback = None
            if entry.get("variable"):
                name, is_variable, fallback = str(entry["variable"]), True, entry.get("fallback")
            else:
                name = placeholder.lstrip("@") if isinstance(placeholder, str) else None
                is_variable = name is not None and (
                    name == key or placeholder.startswith("@") or name in variables
                )
            if is_variable:
                value = variables.get(name)
                if (value is None or str(value).strip() == "") and fallback:
                    value = variables.get(fallback)
                if value is None or str(value).strip() == "":
                    if missing_fill is None:
                        result["missing"].append(key)
                        if name not in result["missing_variables"]:
                            result["missing_variables"].append(name)
                        value = ""
                    else:
                        value = missing_fill
                param_data[key] = str(value)
            result["params"][key] = param_data[key]

    if not result["receiver_number"]:
        result["missing"].insert(0, "receiver_number")

    result.update(url=url, headers=headers, body=body)
    return result


def preview(execution: "Execution", curl: str, missing_fill=None, variables=None, param_map=None) -> dict:
    """What a send would deliver — no headers (they carry the API key)."""
    request = build_request(execution, curl, missing_fill, variables, param_map)
    return {
        "execution_id": execution.id,
        "receiver_number": request["receiver_number"],
        "template_title": request["template_title"],
        "params": request["params"],
        "missing": request["missing"],
        "missing_variables": request["missing_variables"],
        "error": request["error"],
    }


def send_whatsapp(
    execution: "Execution",
    curl: str,
    missing_fill=None,
    variables=None,
    template_key: str = "",
    param_map=None,
) -> dict:
    """
    POSTs the filled-in template. Returns {"execution_id", "success",
    "status_code", "error", "retryable", "blocked", "missing"} — retryable is
    True only for a network error or a 5xx (a 4xx or bad curl won't get better
    by resending). "blocked" is True when the only problem is empty variables
    someone can fill in; "missing" then lists those variable names. A missing
    receiver number is a plain failure, not blocked: there is no variable to
    fill. Nothing is sent when blocked. Never raises.
    """
    request = build_request(execution, curl, missing_fill, variables, param_map)
    error = request["error"]
    blocked = False
    if not error and request["missing"]:
        error = "missing values for: " + ", ".join(request["missing"])
        blocked = "receiver_number" not in request["missing"]

    status_code, response_body, retryable = None, "", False
    if not error:
        try:
            headers = {"Content-Type": "application/json", **request["headers"]}
            status_code, response_body, _ = _send_once(
                request["url"], json.dumps(request["body"]).encode(), headers
            )
            if not 200 <= status_code < 300:
                error = f"non-2xx status: {status_code}"
                retryable = status_code >= 500
        except Exception as exc:
            error = str(exc)
            retryable = True

    if blocked:
        logger.info("whatsapp send blocked: execution=%s template=%s %s", execution.id, template_key, error)
    elif error:
        logger.error("whatsapp send failed: execution=%s template=%s %s", execution.id, template_key, error)

    try:
        ExecutionEvent.objects.create(
            execution=execution,
            event_type=EVENT_BLOCKED if blocked else (EVENT_FAILED if error else EVENT_SENT),
            payload={
                "template_key": template_key,
                "receiver_number": request["receiver_number"],
                "template_title": request["template_title"],
                "params": request["params"],
                "status_code": status_code,
                "response_body": response_body[:RESPONSE_BODY_TRUNCATE_LEN],
                "error": error,
            },
        )
    except Exception:
        pass

    return {
        "execution_id": execution.id,
        "success": error is None,
        "status_code": status_code,
        "error": error,
        "retryable": retryable,
        "blocked": blocked,
        "missing": request["missing_variables"] if blocked else [],
    }
