"""Orchestrator configuration — all from env, never hardcoded."""

import os

from dotenv import load_dotenv

load_dotenv()


# ── Store backend ──────────────────────────────────────────────────────────────
SUPABASE_URL         = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
SUPABASE_ANON_KEY    = os.getenv("SUPABASE_ANON_KEY", "")

# "memory" | "supabase" | "auto". auto = supabase if creds present, else memory.
ORCH_STORE = os.getenv("ORCH_STORE", "auto").lower()


def store_backend() -> str:
    """Resolve which store backend to use."""
    if ORCH_STORE == "memory":
        return "memory"
    if ORCH_STORE == "supabase":
        return "supabase"
    return "supabase" if (SUPABASE_URL and SUPABASE_SERVICE_KEY) else "memory"


# ── Chat360 voice dispatch ──────────────────────────────────────────────────────
CHAT360_OUTBOUND_URL = os.getenv(
    "CHAT360_OUTBOUND_URL", "https://app.chat360.io/api/voicebot/external/outbound"
)
# Demo auth is a csrftoken cookie; production should switch to a stable token.
CHAT360_AUTH_COOKIE  = os.getenv("CHAT360_AUTH_COOKIE", "")

# DID pool — comma-separated caller numbers. Each DID ~100 concurrent calls.
DID_POOL = [d.strip() for d in os.getenv("DID_POOL", "").split(",") if d.strip()]
DID_CONCURRENCY = int(os.getenv("DID_CONCURRENCY", "100"))


# ── Follow-up reliability ───────────────────────────────────────────────────────
SCHEDULER_INTERVAL_SEC = int(os.getenv("SCHEDULER_INTERVAL_SEC", "60"))
FOLLOWUP_MAX_RETRIES   = int(os.getenv("FOLLOWUP_MAX_RETRIES", "4"))
# Backoff (hours) per retry attempt; last value repeats if retries exceed list length.
FOLLOWUP_BACKOFF_HOURS = [
    float(x) for x in os.getenv("FOLLOWUP_BACKOFF_HOURS", "4,24,48,72").split(",")
]

# Capacity split between new-goal outreach and honoring prior-goal commitments (Pain B).
# Fraction of capacity reserved for protected follow-ups; remainder pursues the new goal.
FOLLOWUP_CAPACITY_RESERVE = float(os.getenv("FOLLOWUP_CAPACITY_RESERVE", "0.5"))


# ── Local store path (MemoryStore can persist to disk for the demo) ─────────────
ORCH_DB_PATH = os.getenv("ORCH_DB_PATH", "orchestrator_state.db")
