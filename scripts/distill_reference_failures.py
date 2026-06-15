"""One-time distillation: extract Adani bot failure modes from real call transcripts
and store as an always-on platform-knowledge guardrail. Run again to refresh.

Usage:
    PYTHONPATH=. venv/bin/python scripts/distill_reference_failures.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from shared.db import init_db, add_knowledge, get_knowledge, delete_knowledge
from shared.llm_client import LLMClient

TRANSCRIPT_PATH = "data/bot_transcripts/adani_bot.md"
ANALYTICS_PATH = "data/analytics_jsons/adani_stage_analytics.json"
TOPIC = "Reference-bot known pitfalls (must fix)"
SOURCE = "distill"

SYSTEM = """You are a voice-bot QA analyst. From the real production transcripts provided, extract concrete,
recurring FAILURE MODES and the specific FIX each generated bot must apply. Be precise and actionable —
each failure must be something a bot builder can directly address in a system prompt, flow routing, or
variable-capture node.

Return a JSON object (no other text):
{
  "failures": [
    {
      "failure": "short label for the failure pattern",
      "evidence": "specific moment or quote from the transcript that proves it",
      "fix": "actionable instruction for every generated/patched bot to prevent this"
    }
  ]
}"""


def distill():
    init_db()

    with open(TRANSCRIPT_PATH, encoding="utf-8") as f:
        transcript = f.read()

    # Analytics zeros out — include for structure but rely on transcript evidence
    with open(ANALYTICS_PATH, encoding="utf-8") as f:
        analytics = json.load(f)

    analytics_signals = {
        "drop_call_metrics": analytics.get("drop_call_metrics"),
        "disposition_analytics": analytics.get("disposition_analytics"),
        "sentiment_analysis": analytics.get("sentiment_analysis"),
        "performance": analytics.get("performance"),
    }

    llm = LLMClient()
    user = f"""## Real Adani Airport Bot Call Transcripts (production failures visible)

{transcript}

## Stage Analytics (provided for context; numeric data may be sparse)

{json.dumps(analytics_signals, ensure_ascii=False, indent=2)}

Carefully read each transcript call (## 1 through ## 5). Identify every recurring failure pattern —
especially language switching failures, name mis-capture, confirmation loops, and any point where the
bot did not advance the conversation. Extract each as a failure/evidence/fix triple."""

    raw = llm.complete_json(SYSTEM, user, max_tokens=4096)
    failures = raw.get("failures") or []

    print(f"\nExtracted {len(failures)} failure modes:")
    for i, item in enumerate(failures, 1):
        print(f"  {i}. [{item.get('failure','?')}] → {item.get('fix','?')[:80]}")

    lines = [
        "These are real failures observed in the production Adani Airport reference bot.",
        "Every generated/patched plan MUST guard against them:\n",
    ]
    for item in failures:
        lines.append(f"• FAILURE: {item.get('failure', '')}")
        lines.append(f"  EVIDENCE: {item.get('evidence', '')}")
        lines.append(f"  FIX: {item.get('fix', '')}")
        lines.append("")
    fact_text = "\n".join(lines)

    # Idempotent: delete any existing distill row first
    existing = get_knowledge(None)
    removed = 0
    for r in existing:
        if r["topic"] == TOPIC and r.get("source") == SOURCE:
            delete_knowledge(r["id"])
            removed += 1
    if removed:
        print(f"  removed {removed} stale distill row(s)")

    kid = add_knowledge(TOPIC, fact_text, source=SOURCE, status="active")
    print(f"Stored '{TOPIC}' → id={kid}\n")


if __name__ == "__main__":
    distill()
