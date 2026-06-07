"""Autovista AI Orchestrator — CRM-agnostic, voice-service-agnostic outbound lead engine.

Three deterministic engines (no hierarchy LLM agents):
  - Follow-up Reliability  (Commitment Ledger + scheduler)   — kills follow-up leakage
  - Goal-Adaptation        (capacity split, honor commitments) — kills goal-change whiplash
  - Assignment/Dispatch    (DID pool, single bot, confirm gate)

Backed by a swappable Store (MemoryStore for tests/demo, SupabaseStore for the shared
orchestration store the dashboard reads). Adapters make CRM and voice providers pluggable.
"""
