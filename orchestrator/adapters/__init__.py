"""Pluggable adapters: CRM (lead source) and Voice (call dispatch).

Every provider (Chat360, Bolna, Leaddial, Autovista LMS, Maruti) implements the same
Protocol, so the orchestrator core never changes when a provider is swapped.
"""
