"""humanvoice_engine — extract a Human-Voice Parameter Sheet from best-agent call recordings.

Standalone pipeline: transcribe -> prosody -> gold_extract -> aggregate.
Isolated from the intelligence/orchestrator planes; no DB writes.
"""
