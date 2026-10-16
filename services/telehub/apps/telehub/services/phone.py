"""
Phone-number normalisation shared by models and services. Pure — no model
imports — so models.py can use it without a circular import.
"""
import re


def normalize_digits(raw) -> str:
    """
    Digits only, with a leading India country code ("91") stripped when the
    result is longer than a bare 10-digit number, so "+917965311524",
    "917965311524" and "7965311524" all become "7965311524". The same
    convention outcome_routing._normalize_phone uses for matching leads
    (India-only for now, like the rest of telehub).
    """
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) > 10 and digits.startswith("91"):
        digits = digits[2:]
    return digits
