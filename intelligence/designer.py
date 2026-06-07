"""Workflow Designer Engine — clarifying questions, plan generation, and patch-based refinement."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from shared.db import (
    get_insights, get_plan, get_plans, get_patches,
    save_plan, save_patch, update_plan, init_db,
)
from shared.llm_client import LLMClient

load_dotenv()

DB_PATH   = os.getenv("DB_PATH", "intelligence_fabric.db")
BOTS_PATH = Path(__file__).parent / "data" / "best_bots.json"


# ── system prompt builder ─────────────────────────────────────────────────────

def _canvas_system() -> str:
    """Load best_bots.json and return the Chat360 canvas system prompt."""
    with open(BOTS_PATH, encoding="utf-8") as f:
        bots = json.load(f)
    return (
        "You are an expert Chat360 voice bot architect. "
        "You design production-grade voice bot workflows that run on the Chat360 canvas.\n\n"
        "## Chat360 Canvas Reference\n\n"
        + json.dumps(bots, ensure_ascii=False)
        + "\n\n"
        "Always ground your output in the node types, field schemas, routing patterns, "
        "and prompt conventions shown above. Never invent node types or fields that "
        "are not in the reference."
    )


# ── insight aggregation ───────────────────────────────────────────────────────

def _aggregate_insights(client_id: str, db_path: str) -> dict:
    """Merge all insights for a client into deduplicated signal lists."""
    rows = get_insights(client_id, path=db_path)
    objections, qual_signals, esc_signals, kb_gaps = set(), set(), set(), set()
    scores, sentiments = [], []

    for r in rows:
        objections.update(r.get("objection_patterns") or [])
        qual_signals.update(r.get("qualification_signals") or [])
        esc_signals.update(r.get("escalation_signals") or [])
        kb_gaps.update(r.get("kb_gaps") or [])
        if r.get("agent_score"):
            scores.append(r["agent_score"])
        if r.get("sentiment"):
            sentiments.append(r["sentiment"])

    avg_score = round(sum(scores) / len(scores), 1) if scores else None
    return {
        "call_count": len(rows),
        "avg_agent_score": avg_score,
        "objection_patterns": sorted(objections),
        "qualification_signals": sorted(qual_signals),
        "escalation_signals": sorted(esc_signals),
        "kb_gaps": sorted(kb_gaps),
    }


# ── WorkflowDesigner ──────────────────────────────────────────────────────────

class WorkflowDesigner:
    """Generates Chat360 voice bot workflow plans from transcripts and admin input."""

    def __init__(self, db_path: str = DB_PATH):
        """Initialise LLM client and DB path; ensure DB tables exist."""
        self._llm = LLMClient()
        self._db  = db_path
        init_db(db_path)

    # ── clarifying questions ──────────────────────────────────────────────────

    def generate_clarifying_questions(self, client_id: str, use_case_text: str) -> list:
        """Generate LLM-driven clarifying questions grounded in call insights and use case.

        Returns list of dicts: [{id, question, why}]
        """
        insights = _aggregate_insights(client_id, self._db)
        system   = _canvas_system()

        user = f"""A client wants to build a Chat360 voice bot. Here is their use case:

<use_case>
{use_case_text}
</use_case>

Here are patterns extracted from their real agent call recordings:

<insights>
{json.dumps(insights, ensure_ascii=False, indent=2)}
</insights>

Based on the use case and insights, generate targeted clarifying questions to fill gaps the recordings could not answer.

Rules:
- Do NOT ask about things already clear from the use case or insights
- Focus on: CRM variable names, API availability, escalation team setup, language preferences, specific qualification thresholds, campaign parameters
- 4–10 questions maximum
- Each question should directly improve the quality of the workflow plan

Return JSON array:
[
  {{
    "id": "q1",
    "question": "...",
    "why": "one sentence explaining what this unlocks in the plan"
  }}
]"""

        return self._llm.complete_json(system, user, max_tokens=1024)

    # ── plan generation ───────────────────────────────────────────────────────

    def generate_plan(
        self,
        client_id: str,
        use_case_text: str,
        answers: list,
    ) -> dict:
        """Generate a full workflow plan JSON from use case, insights, and QnA answers.

        answers: list of {question, answer}
        Returns: plan dict saved to DB; includes plan_id key.
        """
        insights = _aggregate_insights(client_id, self._db)
        system   = _canvas_system()

        qa_text = "\n".join(
            f"Q: {a['question']}\nA: {a['answer']}" for a in answers
        )

        user = f"""Design a production-grade Chat360 voice bot workflow plan.

<use_case>
{use_case_text}
</use_case>

<call_insights>
{json.dumps(insights, ensure_ascii=False, indent=2)}
</call_insights>

<clarifying_answers>
{qa_text}
</clarifying_answers>

Return a single JSON object with exactly these keys:

{{
  "workflow_blueprint": {{
    "description": "Human-readable 2-3 sentence flow narrative",
    "stages": [
      {{
        "stage_id": 1,
        "name": "Stage name",
        "node_type": "VOICE_GENAI|VOICE_INTENT|VOICE_CONDITIONAL|...",
        "purpose": "What this stage achieves",
        "chat360_config": {{
          "initial_message": "...",
          "routing_table": {{"default": "<next_stage_node_id_placeholder>"}},
          "any_other_key_fields": "..."
        }}
      }}
    ]
  }},
  "system_prompt": "Full LLM system prompt for the primary VOICE_GENAI node(s). Must include @bot_language rule.",
  "qualification_questions": [
    {{"question": "...", "variable": "@variable_name", "purpose": "..."}}
  ],
  "objection_handling": {{
    "<objection in caller's language>": "<bot response>",
    "...": "..."
  }},
  "escalation_rules": [
    {{"trigger": "...", "action": "...", "node_type": "VOICE_MESSAGE|VOICE_WEBHOOK"}}
  ],
  "kb_scaffold": {{
    "<topic>": "<content or data the bot needs to answer this topic>"
  }},
  "build_notes": {{
    "canvas_instructions": [
      "Step-by-step instructions for an admin to build this flow in the Chat360 canvas UI"
    ],
    "variables_required": ["@var1", "@var2"],
    "tts_engine": "elevenlabs|azure",
    "stt_engine": "azure|deepgram",
    "language": "hinglish|hindi|english",
    "outbound_params": ["@var1", "@var2"],
    "silence_handle_config": {{
      "retry_count": 2,
      "retry_prompt": "..."
    }}
  }}
}}

Ground every stage in real Chat360 node types from the canvas reference.
build_notes.canvas_instructions must be specific enough for an admin to build without guessing."""

        plan = self._llm.complete_json(system, user, max_tokens=16000)
        plan_id = save_plan({"client_id": client_id, "plan": plan}, path=self._db)
        plan["plan_id"] = plan_id
        return plan

    # ── patch-based refinement ────────────────────────────────────────────────

    def apply_patch(self, plan_id: str, admin_request: str) -> dict:
        """Apply an LLM-generated patch to a plan. Never regenerates the full plan.

        Returns dict: {new_plan, patch, diff, reasoning, version}
        """
        plan_row = get_plan(plan_id, path=self._db)
        if not plan_row:
            raise ValueError(f"Plan {plan_id} not found.")

        current_plan = plan_row["plan"]
        current_version = plan_row["version"]
        system = _canvas_system()

        user = f"""You are patching an existing Chat360 voice bot workflow plan.

<current_plan>
{json.dumps(current_plan, ensure_ascii=False, indent=2)}
</current_plan>

<admin_request>
{admin_request}
</admin_request>

Rules:
- ONLY modify the keys that need to change
- Do NOT regenerate or touch keys that are unaffected
- Preserve all existing content in unchanged keys

Return JSON with exactly these keys:
{{
  "patch": {{
    "<top_level_key>": <new_value_for_that_key_only>
  }},
  "reasoning": "One paragraph explaining what changed, why, and what was deliberately left untouched."
}}"""

        result = self._llm.complete_json(system, user, max_tokens=16000)
        patch     = result.get("patch", {})
        reasoning = result.get("reasoning", "")

        # Apply patch to current plan
        new_plan = {**current_plan, **patch}

        # Build human-readable diff
        diff = {}
        for key, new_val in patch.items():
            diff[key] = {
                "before": current_plan.get(key),
                "after": new_val,
            }

        # Persist
        update_plan(plan_id, new_plan, path=self._db)
        patch_id = save_patch(
            {
                "plan_id": plan_id,
                "version": current_version + 1,
                "admin_request": admin_request,
                "patch": patch,
                "llm_reasoning": reasoning,
            },
            path=self._db,
        )

        return {
            "new_plan": new_plan,
            "patch": patch,
            "diff": diff,
            "reasoning": reasoning,
            "version": current_version + 1,
            "patch_id": patch_id,
        }

    # ── plan history ──────────────────────────────────────────────────────────

    def get_plan_history(self, plan_id: str) -> dict:
        """Return plan with all patches ordered by version."""
        plan_row = get_plan(plan_id, path=self._db)
        if not plan_row:
            return {}
        patches = get_patches(plan_id, path=self._db)
        return {"plan": plan_row, "patches": patches}

    def list_plans(self, client_id: str = None) -> list:
        """Return all plans, optionally filtered by client_id."""
        return get_plans(client_id, path=self._db)

    # ── bot synthesis validation ──────────────────────────────────────────────

    def validate_synthesis(self, synthesis_path: str = str(BOTS_PATH)) -> dict:
        """Ask LLM to review best_bots.json synthesis for gaps or inaccuracies.

        Returns {feedback, suggested_additions} for admin review before applying.
        """
        with open(synthesis_path, encoding="utf-8") as f:
            synthesis = json.load(f)

        system = (
            "You are a Chat360 platform expert reviewing a knowledge synthesis document "
            "that will be used as system prompt context for an AI workflow designer."
        )
        user = f"""Review this Chat360 canvas synthesis document for completeness and accuracy.

<synthesis>
{json.dumps(synthesis, ensure_ascii=False, indent=2)}
</synthesis>

Identify:
1. Missing node types or fields that a Chat360 admin would need
2. Incorrect or misleading rules
3. Missing prompt patterns or variable conventions
4. Any gaps that would cause the AI to hallucinate canvas instructions

Return JSON:
{{
  "overall_quality": "excellent|good|needs_improvement",
  "missing_items": ["..."],
  "incorrect_items": ["..."],
  "suggested_additions": {{
    "<section>": "<what to add>"
  }},
  "summary": "2-sentence assessment"
}}"""

        return self._llm.complete_json(system, user, max_tokens=2048)
