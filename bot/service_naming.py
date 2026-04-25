# -*- coding: utf-8 -*-
"""
Service Naming System
=====================
Helpers for validating, normalising, generating, and deduplicating
service names in the purchase flow.
"""

import random
import re
import string

_NAME_RE = re.compile(r'^[a-z0-9]+$')


# ─────────────────────────── public helpers ───────────────────────────────────

def validate_service_name(name: str) -> bool:
    """Return True if *name* is a valid service name (a-z, 0-9 only)."""
    if not name:
        return False
    return bool(_NAME_RE.match(name))


def normalize_service_name(name: str) -> str:
    """Lowercase + strip.  Does NOT validate — call validate_service_name after."""
    return (name or "").strip().lower()


def generate_random_name(uid: int | None = None, length: int = 6) -> str:
    """
    Generate a random service name.
    If uid is provided, format is: {uid}_{random_suffix}
    Otherwise, format is: {random_alpha}{random_suffix}
    """
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=length))
    if uid is not None:
        return f"{uid}_{suffix}"
    prefix = random.choice(string.ascii_lowercase)
    return prefix + suffix


def parse_bulk_names(text: str, count: int, uid: int | None = None) -> list[str]:
    """
    Parse a newline-separated text of names for bulk purchase.

    Rules:
    - Each line is trimmed and lowercased.
    - Valid lines (matching a-z0-9) are kept.
    - Invalid or empty lines are replaced with a random name.
    - Exactly *count* names are returned regardless of input length:
      * Too many lines → use only the first *count*
      * Too few lines → pad with random names
    """
    lines = text.splitlines() if text else []
    result: list[str] = []

    for line in lines[:count]:
        normalised = normalize_service_name(line)
        if validate_service_name(normalised):
            result.append(normalised)
        else:
            result.append(generate_random_name(uid))

    # Pad to required count
    while len(result) < count:
        result.append(generate_random_name(uid))

    return result


def build_final_name(inbound_remark: str, service_name: str) -> str:
    """
    Build the final name sent to the panel:
        inboundRemark + "-" + service_name

    Example: "V2RAY-ali"
    """
    remark = (inbound_remark or "").strip().upper()
    svc    = (service_name or "").strip()
    if remark:
        return f"{remark}-{svc}"
    return svc


def ensure_unique_name(
    base_name: str,
    try_create_fn,
    max_retries: int = 3,
    uid: int | None = None,
) -> tuple[bool, str, object]:
    """
    Attempt to use *base_name*; on duplicate-name errors, retry with modified names.

    Parameters
    ----------
    base_name       : The desired service name (already validated/normalised).
    try_create_fn   : Callable(name) -> (ok: bool, result: any).
                      Called each attempt.  Should return (True, result) on
                      success and (False, error_str) on failure.
    max_retries     : Maximum number of additional attempts with modified names.
    uid             : User ID — used to seed random fallback names.

    Returns
    -------
    (ok, final_name, result)
    """
    current_name = base_name

    for attempt in range(max_retries + 1):
        ok, result = try_create_fn(current_name)
        if ok:
            return True, current_name, result

        err_str = str(result).lower()
        is_duplicate = any(kw in err_str for kw in [
            "duplicate", "already exists", "email already exists",
            "client email", "exist",
        ])

        if attempt < max_retries:
            if is_duplicate:
                # Add short random suffix: ali → ali-xy
                tail = "".join(random.choices(string.ascii_lowercase + string.digits, k=2))
                current_name = f"{base_name}-{tail}"
            else:
                # Non-duplicate error — fallback to completely random name
                current_name = generate_random_name(uid)
        # else: final attempt failed — fall through

    # All retries exhausted — try one last fully random name
    fallback = generate_random_name(uid)
    ok, result = try_create_fn(fallback)
    if ok:
        return True, fallback, result

    return False, fallback, result
