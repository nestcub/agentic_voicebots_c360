"""Authorization seam for global platform-knowledge writes.

Standalone/demo: an admin is any client_id in ADMIN_CLIENT_IDS (env, comma-separated).
Production (embedded in Chat360): rewire is_admin() to read Chat360's authenticated role claim.
This is the SINGLE integration point — do not build a login system here.
"""
import os

def _admin_ids() -> set:
    raw = os.getenv("ADMIN_CLIENT_IDS", "")
    return {x.strip() for x in raw.split(",") if x.strip()}

def is_admin(actor: str) -> bool:
    """True if `actor` may write global platform knowledge."""
    return bool(actor) and actor in _admin_ids()
