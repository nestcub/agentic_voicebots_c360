"""
The small condition language shared by ChannelRule (which message to send
after a call) and, later, journey transitions: a list of checks against a
call's variables, combined with "all" or "any".

    {"variable": "appointment_date", "op": "exists"}
    {"variable": "callback_status",  "op": "equals", "value": "required"}

Operators:
  exists      the variable is present and not blank
  not_exists  the variable is missing, None or blank
  equals      case- and whitespace-insensitive string equality with `value`
  truthy      true / "true" / "1" / "yes" (any case) — so the string "False"
              from a voicebot payload is false, not merely "non-empty"

An unknown operator never matches. A list with no checks matches everything.
"""
OP_EXISTS = "exists"
OP_NOT_EXISTS = "not_exists"
OP_EQUALS = "equals"
OP_TRUTHY = "truthy"
OPERATORS = (OP_EXISTS, OP_NOT_EXISTS, OP_EQUALS, OP_TRUTHY)

_TRUE_STRINGS = ("true", "1", "yes")


def is_blank(value) -> bool:
    return value is None or str(value).strip() == ""


def _norm(value) -> str:
    return str(value if value is not None else "").strip().lower()


def check_passes(check, variables: dict) -> bool:
    if not isinstance(check, dict):
        return False
    value = (variables or {}).get(check.get("variable"))
    op = check.get("op")
    if op == OP_EXISTS:
        return not is_blank(value)
    if op == OP_NOT_EXISTS:
        return is_blank(value)
    if op == OP_EQUALS:
        return _norm(value) == _norm(check.get("value"))
    if op == OP_TRUTHY:
        return value is True or _norm(value) in _TRUE_STRINGS
    return False


def evaluate(match: str, checks, variables: dict) -> bool:
    """True if `checks` pass against `variables` under `match` ("all" or "any")."""
    if not checks:
        return True
    results = (check_passes(check, variables) for check in checks)
    return any(results) if match == "any" else all(results)


def validate_checks(checks) -> list:
    """Problems with a checks list as a list of messages; [] means it is well-formed."""
    if not isinstance(checks, list):
        return ["checks must be a list"]
    problems = []
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            problems.append(f"check {index} must be an object")
            continue
        if not str(check.get("variable") or "").strip():
            problems.append(f"check {index} needs a variable")
        if check.get("op") not in OPERATORS:
            problems.append(f"check {index} has unknown op {check.get('op')!r}")
        elif check["op"] == OP_EQUALS and "value" not in check:
            problems.append(f"check {index} (equals) needs a value")
    return problems
