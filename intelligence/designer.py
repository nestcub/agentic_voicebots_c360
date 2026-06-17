"""Workflow Designer Engine — clarifying questions, plan generation, and patch-based refinement."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from shared.db import (
    get_insights, get_plan, get_plans, get_patches,
    save_plan, save_patch, update_plan, init_db,
    load_session, save_session, save_turn, get_turns,
    add_knowledge, get_knowledge, search_bot_examples,
    search_transcript_chunks, get_kb,
)
from shared.auth import is_admin
from shared.llm_client import LLMClient
from shared.embeddings import embed

load_dotenv()

DB_PATH   = os.getenv("DB_PATH", "")  # deprecated no-op; persistence is Neon Postgres via DATABASE_URL
BOTS_PATH = Path(__file__).parent / "data" / "best_bots.json"
TWELVE_POINTS_PATH = Path(__file__).parent.parent / "data" / "system_prompts" / "12_points_prompt_template.md"


_CONVERSE_INSTRUCTIONS = """Decide the intent and respond. Rules:
- If there is no use case yet, treat the message as the use case (store it in "use_case") and either
  draft a first plan OR ask 2-4 clarifying questions inside "reply" if key facts are missing.
- If a plan already exists and the user asks for a change, return ONLY the top-level keys that change in
  "patch" — never restate unchanged keys (saves tokens). Put a one-paragraph what-changed in "reply".
- If the user asks an open-ended question or for advice ("the bot fails to recognise speech, what to
  do?"), set intent="advice", patch=null, full_plan=null, and put the guidance in "reply". Do NOT change
  the plan unless they explicitly instruct a change.
- If the user says to incorporate new recordings ("check the new recordings for insights/patterns"),
  set intent="rescan" and fold the newest insight patterns into the plan as a "patch".
- Cross-language: you may draw insight PATTERNS from recordings in any language (Marathi etc.), but only
  build the bot for the languages the user specifies (e.g. keep build_notes.language = Hindi/English).
- Clarifying questions you need answered go in "reply"; the user answers them in the next message, and you
  fold the answer in then — do not repeat questions already answered in RECENT TURNS.
- If the user is teaching a DURABLE Chat360 PLATFORM fact (applies to ALL bots, not just this client —
  e.g. an engine requirement, a how-to-configure rule, a disconnection/latency technique), set
  intent="teach" and put it in "proposed_knowledge". If you merely NOTICE such a generalizable platform
  fact during another request, also add it to "proposed_knowledge" (do not change intent for that).
  Client-specific project details belong in use_case, NOT in proposed_knowledge.
  Non-admin teach attempts: the platform knowledge store is curated by the Chat360 team; tell the
  user their suggestion has been flagged for review.
- Plan keys, when creating/patching, are exactly: workflow_blueprint, system_prompt,
  qualification_questions, objection_handling, escalation_rules, kb_scaffold, build_notes. Ground
  everything in the canvas reference in the system prompt; never invent node types.
- When writing system_prompt: study every reference_system_prompt section in the retrieved examples
  above and mirror their structure exactly — include a CRITICAL LANGUAGE RULE block, enforce
  @bot_language at every GenAI node, follow tool/RAG usage and response-variable conventions.
  Apply every item in 'Reference-bot known pitfalls' from platform knowledge. Never write a thin
  or generic system prompt.

Return JSON with exactly these keys:
{
  "intent": "use_case | plan | patch | advice | rescan | teach",
  "use_case": "the current (possibly updated) use case text",
  "reply": "what to show the user",
  "plan_action": "none | create | patch",
  "full_plan": {} or null,
  "patch": {} or null,
  "proposed_knowledge": []
}"""


# ── system prompt builder ─────────────────────────────────────────────────────

def _canvas_system() -> str:
    """Load best_bots.json structural reference (grammar + benchmarks) for the cached system block.
    Pattern examples (specialist, intent, conditional) are retrieved via RAG at query time.
    """
    with open(BOTS_PATH, encoding="utf-8") as f:
        bots = json.load(f)
    structural = {
        k: bots[k] for k in ("canvas_grammar", "performance_benchmarks") if k in bots
    }
    return (
        "You are an expert Chat360 voice bot architect. "
        "You design production-grade voice bot workflows that run on the Chat360 canvas.\n\n"
        "## Chat360 Canvas Reference\n\n"
        + json.dumps(structural, ensure_ascii=False)
        + "\n\n"
        "Always ground your output in the node types, field schemas, routing patterns, "
        "and prompt conventions shown above. Never invent node types or fields that "
        "are not in the reference."
    )


def _twelve_points_template() -> str:
    """Load the 12-section system prompt template as a cached system block."""
    with open(TWELVE_POINTS_PATH, encoding="utf-8") as f:
        content = f.read()
    return (
        "## 12-Section System Prompt Template\n\n"
        "The document below is a gold-standard example of the required 12-section system prompt structure. "
        "Mirror this exact section structure for the bot you are building — produce equivalent sections "
        "for THIS bot's use case, domain, language, and call patterns.\n\n"
        + content
    )


def _platform_knowledge_block(db_path: str) -> str:
    """Render active platform knowledge as a system-prompt section (empty string if none)."""
    rows = get_knowledge("active", path=db_path)
    if not rows:
        return ""
    lines = "\n".join(f"- [{r['topic']}] {r['fact']}" for r in rows)
    return ("## Learned Chat360 Platform Knowledge\n"
            "Apply these platform facts to every design unless the user overrides them.\n" + lines)


def _retrieve_examples(query_text: str, k: int = 5) -> str:
    """Embed query_text and retrieve top-K relevant bot examples from the RAG corpus.
    Returns a formatted string ready to inject into the user prompt.
    Returns empty string if corpus is empty or embedding fails.
    """
    try:
        vec = embed(query_text)
        examples = search_bot_examples(vec, k=k)
        if not examples:
            return ""
        lines = ["## Relevant proven bot examples (retrieved for this use case)\n"]
        for ex in examples:
            score = ex.get("score", 0)
            lines.append(f"### {ex['name']} ({ex['unit_type']}, similarity {score:.2f})")
            lines.append(f"Use case: {ex['use_case']}")
            lines.append(json.dumps(ex["content"], ensure_ascii=False, indent=2))
            lines.append("")
        return "\n".join(lines)
    except Exception:
        return ""  # RAG is additive — never break generation if corpus is empty or DB unset


def _retrieve_call_evidence(client_id: str, query_text: str, k: int = 5) -> str:
    """Retrieve top-K verbatim call moments for THIS client, grounded quotes for the prompt."""
    try:
        vec = embed(query_text)
        hits = search_transcript_chunks(vec, client_id, k=k)
        if not hits:
            return ""
        lines = ["## Relevant call evidence (verbatim moments from this client's recordings)\n"]
        for h in hits:
            ts = f"{h.get('start_sec', 0):.0f}s" if h.get('start_sec') is not None else ""
            lines.append(f"### {h.get('role_sequence','')} {ts} (similarity {h.get('score',0):.2f})")
            lines.append(h["text"])
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        print(f"[call-evidence] retrieval failed for {client_id}: {e}", flush=True)
        return ""


# ── insight aggregation ───────────────────────────────────────────────────────

def _aggregate_insights(client_id: str, db_path: str) -> dict:
    """Merge all insights for a client into deduplicated signal lists."""
    rows = get_insights(client_id, path=db_path)
    objections, qual_signals, esc_signals, kb_gaps = set(), set(), set(), set()
    bot_failures, suggested_fixes = set(), set()
    scores, sentiments = [], []

    for r in rows:
        objections.update(r.get("objection_patterns") or [])
        qual_signals.update(r.get("qualification_signals") or [])
        esc_signals.update(r.get("escalation_signals") or [])
        kb_gaps.update(r.get("kb_gaps") or [])
        raw = r.get("raw_insights_json") or {}
        bot_failures.update(raw.get("bot_failure_modes") or [])
        suggested_fixes.update(raw.get("suggested_fixes") or [])
        if r.get("agent_score"):
            scores.append(r["agent_score"])
        if r.get("sentiment"):
            sentiments.append(r["sentiment"])

    avg_score = round(sum(scores) / len(scores), 1) if scores else None
    return {
        "call_count": len(rows),
        "avg_agent_score": avg_score,
        "objection_patterns": sorted(objections)[:10],
        "qualification_signals": sorted(qual_signals)[:10],
        "escalation_signals": sorted(esc_signals)[:10],
        "kb_gaps": sorted(kb_gaps)[:10],
        "bot_failure_modes": sorted(bot_failures)[:10],
        "suggested_fixes": sorted(suggested_fixes)[:10],
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

    def generate_clarifying_questions(self, client_id: str, use_case_text: str, source_client_id: str | None = None, provider: str | None = None, model: str | None = None) -> list:
        """Generate LLM-driven clarifying questions grounded in call insights and use case.

        Returns list of dicts: [{id, question, why}]
        """
        insights = _aggregate_insights(source_client_id or client_id, self._db)
        system = [
            {"text": _canvas_system(), "cache": True},
            {"text": _platform_knowledge_block(self._db), "cache": True},
            {"text": _twelve_points_template(), "cache": True},
        ]

        has_recordings = insights.get("call_count", 0) > 0

        if has_recordings:
            question_guidance = """Based on the use case and insights, generate targeted clarifying questions to fill gaps the recordings could not answer.

Rules:
- Do NOT ask about things already clear from the use case or insights
- Focus on: CRM variable names, API availability, escalation team setup, language preferences, specific qualification thresholds, campaign parameters
- 6 questions maximum
- Each question should directly improve the quality of the workflow plan"""
        else:
            question_guidance = """No call recordings are available. You must ask questions to understand what recordings would normally reveal.

Rules:
- Ask about: caller personas, common objections, conversational tone, language (primary + fallback), typical call flow stages, what a successful call looks like, escalation scenarios, key KB topics
- Also ask about: CRM variable names, API availability, escalation team setup, qualification thresholds, campaign parameters
- 10 questions maximum — be thorough since there are no recordings to learn from
- Prefer multiple-choice questions where you can offer options drawn from domain knowledge
- Each question should directly fill a gap that call recordings would normally answer"""

        insights_block = f"""Here are patterns extracted from their real agent call recordings:

<insights>
{json.dumps(insights, ensure_ascii=False, indent=2)}
</insights>""" if has_recordings else "No call recordings have been uploaded for this bot."

        user = f"""A client wants to build a Chat360 voice bot. Here is their use case:

<use_case>
{use_case_text}
</use_case>

{insights_block}

{question_guidance}

Return JSON array:
[
  {{
    "id": "q1",
    "question": "...",
    "options": ["option A", "option B", "option C"] or null,
    "why": "one sentence explaining what this unlocks in the plan"
  }}
]"""

        _max_tokens = 1024 if has_recordings else 2048
        _llm = LLMClient(provider=provider, model=model) if (provider or model) else self._llm
        return _llm.complete_json(system, user, max_tokens=_max_tokens)

    # ── plan generation ───────────────────────────────────────────────────────

    def generate_plan(
        self,
        client_id: str,
        use_case_text: str,
        answers: list,
        source_client_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> dict:
        """Generate a full workflow plan JSON from use case, insights, and QnA answers.

        answers: list of {question, answer}
        Returns: plan dict saved to DB; includes plan_id key.
        """
        insights = _aggregate_insights(source_client_id or client_id, self._db)
        system = [
            {"text": _canvas_system(), "cache": True},
            {"text": _platform_knowledge_block(self._db), "cache": True},
            {"text": _twelve_points_template(), "cache": True},
        ]

        qa_text = "\n".join(
            f"Q: {a['question']}\nA: {a['answer']}" for a in answers
        )

        _rag_query = f"{use_case_text}\n{qa_text}"
        _rag_examples = _retrieve_examples(_rag_query, k=8)
        _call_evidence = _retrieve_call_evidence(client_id, _rag_query)

        _bot_failures_block = ""
        if insights.get("bot_failure_modes"):
            _bot_failures_block = (
                "\n<bot_failures_to_fix>\n"
                "These failures were observed in THIS client's own bot calls. "
                "The generated plan MUST address every one:\n"
                + "\n".join(f"• {f}" for f in insights["bot_failure_modes"])
                + "\n\nSuggested fixes:\n"
                + "\n".join(f"• {f}" for f in insights.get("suggested_fixes", []))
                + "\n</bot_failures_to_fix>"
            )

        # Get 1-2 best diarised sequences for conversational flow structure
        _diarised_block = ""
        try:
            _all_insights = get_insights(source_client_id or client_id, path=self._db)
            _best = sorted(
                [r for r in _all_insights if r.get("diarised_segments")],
                key=lambda r: r.get("agent_score") or 0,
                reverse=True,
            )[:2]
            if _best:
                _seqs = []
                for i, r in enumerate(_best):
                    segs = r["diarised_segments"]
                    if isinstance(segs, str):
                        import json as _json
                        segs = _json.loads(segs)
                    lines = [f"{s.get('speaker','?')}: {s.get('text','')}" for s in (segs or [])[:40]]
                    _seqs.append(f"Call {i+1} (score {r.get('agent_score','?')}):\n" + "\n".join(lines))
                _diarised_block = "\n\n".join(_seqs)
        except Exception:
            pass

        user = f"""Design a production-grade Chat360 voice bot workflow plan.

<use_case>
{use_case_text}
</use_case>

<call_insights>
{json.dumps(insights, ensure_ascii=False, indent=2)}
</call_insights>
{_bot_failures_block}
<call_evidence>
{_call_evidence}
</call_evidence>

<diarised_best_calls>
{_diarised_block if _diarised_block else "(no call recordings available)"}
</diarised_best_calls>

<clarifying_answers>
{qa_text}
</clarifying_answers>

<retrieved_examples>
{_rag_examples}
</retrieved_examples>

Return a single JSON object with exactly these keys:

{{
  "system_prompt_sections": {{
    "critical_rules": "Full text for section 1 — Critical Rules (language & voice rules). Mirror the structure of the template exactly.",
    "roles": "Full text for section 2 — Roles.",
    "objectives": "Full text for section 3 — Objectives.",
    "personality": "Full text for section 4 — Personality.",
    "important_flow_rules": "Full text for section 5 — Important Flow Rules.",
    "guardrails": "Full text for section 6 — Guardrails.",
    "instructions": "Full text for section 7 — Instructions.",
    "conversational_flow": "Full text for section 8 — Conversational Flow. Build this from the diarised call sequences if available — mirror their stage ordering and flow.",
    "closure": "Full text for section 9 — Closure.",
    "objection_handling": "Full text for section 10 — Objection Handling.",
    "conversation_example": "Full text for section 11 — Conversation Example(s). Draw from real call patterns.",
    "safety_guardrails": "Full text for section 12 — Safety Guardrails (restate key safety rules for recency)."
  }},
  "system_prompt": "The full rendered system prompt: all 12 sections concatenated in order, ready to paste into Chat360.",
  "workflow_blueprint": {{
    "description": "...",
    "stages": [
      {{
        "stage_id": 1,
        "name": "...",
        "node_type": "VOICE_GENAI|VOICE_INTENT|VOICE_CONDITIONAL|...",
        "purpose": "...",
        "chat360_config": {{"initial_message": "...", "routing_table": {{"default": "<next>"}}}}
      }}
    ]
  }},
  "build_notes": {{
    "canvas_instructions": ["Step-by-step instructions for an admin to build in Chat360 canvas UI"],
    "variables_required": ["@var1"],
    "tts_engine": "elevenlabs|azure",
    "stt_engine": "azure|deepgram",
    "language": "hinglish|hindi|english",
    "outbound_params": ["@var1"],
    "silence_handle_config": {{"retry_count": 2, "retry_prompt": "..."}}
  }},
  "bot_kb": {{
    "<LLM-decided key>": "<LLM-decided value — shape varies by domain>"
  }}
}}

bot_kb shape is domain-specific — choose keys that fit this bot's use case (e.g. faqs, pricing, models, dealers, scripts, entities). Do not use a fixed schema.
Ground every stage in real Chat360 node types from the canvas reference.
build_notes.canvas_instructions must be specific enough for an admin to build without guessing."""

        _llm = LLMClient(provider=provider, model=model) if (provider or model) else self._llm
        plan = _llm.complete_json(system, user, max_tokens=32000, reasoning_effort=reasoning_effort)
        plan_id = save_plan({"client_id": client_id, "plan": plan}, path=self._db)
        plan["plan_id"] = plan_id
        return plan

    # ── conversational intent router ──────────────────────────────────────────

    def converse(self, client_id: str, message: str, intent_aware: bool = True, provider: str | None = None, model: str | None = None, reasoning_effort: str | None = None, section: str | None = None) -> dict:
        """One conversational turn: route intent, update remembered use case + plan, return a reply.

        Returns {reply, use_case, mode, plan, plan_id, plan_changed, diff, version}.
        mode in {use_case, plan, patch, advice, rescan}. Advice turns never touch the plan.
        """
        sess     = load_session(client_id, path=self._db)
        use_case = sess.get("use_case") or ""
        plan_id  = sess.get("plan_id")

        current_plan, current_version = None, 0
        if plan_id:
            row = get_plan(plan_id, path=self._db)
            if row:
                current_plan, current_version = row["plan"], row["version"]
            else:
                plan_id = None

        insights = _aggregate_insights(client_id, self._db)
        recent   = get_turns(client_id, limit=6, path=self._db)
        recent_text = "\n".join(f"{t['role']}: {t['content']}" for t in recent) or "(none)"

        # On create turns (no plan yet) include the 12-section template; patch turns skip it
        _include_raw_context = current_plan is None

        system = [
            {"text": _canvas_system(), "cache": True},
            {"text": _platform_knowledge_block(self._db), "cache": True},
        ]
        if _include_raw_context:
            system.append({"text": _twelve_points_template(), "cache": True})
        _kb = get_kb(client_id, path=self._db)
        if _kb and _kb.get("content", "").strip():
            system.append({"text": "## Client Bot Knowledge Base\n" + _kb["content"], "cache": True})
        system.append({"text": _CONVERSE_INSTRUCTIONS, "cache": True})

        _rag_query = f"{use_case or message}\n{message}"
        _k = 3 if current_plan else 8
        _skip_heavy_context = (
            intent_aware
            and current_plan is not None
            and len(message) > 200
            and not any(kw in message.lower() for kw in [
                "change", "update", "fix", "add", "remove", "patch",
                "restructure", "modify", "edit", "revise", "redo",
            ])
        )
        if _skip_heavy_context:
            _rag_examples = ""
            _call_evidence = ""
            _current_plan_for_prompt = None
        else:
            _rag_examples = _retrieve_examples(_rag_query, k=_k)
            _call_evidence = _retrieve_call_evidence(client_id, _rag_query) if _include_raw_context else ""
            _current_plan_for_prompt = current_plan

        _bot_failures_block = ""
        if _include_raw_context and insights.get("bot_failure_modes"):
            _bot_failures_block = (
                "\n<bot_failures_to_fix>\n"
                "Failures observed in THIS client's own bot calls — address in every plan/patch:\n"
                + "\n".join(f"• {f}" for f in insights["bot_failure_modes"])
                + "\n\nSuggested fixes:\n"
                + "\n".join(f"• {f}" for f in insights.get("suggested_fixes", []))
                + "\n</bot_failures_to_fix>"
            )

        # Build the user prompt — insights and call evidence only on create turns
        _insights_section = ""
        _call_evidence_section = ""
        if _include_raw_context:
            _insights_section = f"""
CALL INSIGHTS (aggregated from all their real agent recordings):
{json.dumps(insights, ensure_ascii=False, indent=2)}
{_bot_failures_block}"""
            _call_evidence_section = f"""<call_evidence>
{_call_evidence}
</call_evidence>
"""

        # On patch turns, include workflow_blueprint and build_notes as grounding anchors
        _patch_anchor = ""
        if not _include_raw_context and _current_plan_for_prompt:
            _patch_anchor = f"""<workflow_blueprint>
{json.dumps(_current_plan_for_prompt.get("workflow_blueprint", {}), ensure_ascii=False, indent=2)}
</workflow_blueprint>

<build_notes>
{json.dumps(_current_plan_for_prompt.get("build_notes", {}), ensure_ascii=False, indent=2)}
</build_notes>
"""

        user = f"""You are the conversational architect for a Chat360 voice-bot workflow. Hold a running
design session with one human via a single text box. Remember the use case; never ask them to retype it.

REMEMBERED USE CASE:
{use_case or "(none yet — the user's message likely IS the use case)"}
{_insights_section}
{_call_evidence_section}{_patch_anchor}{_rag_examples}

CURRENT PLAN:
{json.dumps(_current_plan_for_prompt, ensure_ascii=False, indent=2) if _current_plan_for_prompt else "(no plan yet — context pruned for this advice turn)"}

RECENT TURNS:
{recent_text}

USER MESSAGE:
{message}"""

        _llm = LLMClient(provider=provider, model=model) if (provider or model) else self._llm
        result = _llm.complete_json(system, user, max_tokens=16000, reasoning_effort=reasoning_effort)

        # teach / auto-propose: store durable platform facts before continuing
        _proposed = result.get("proposed_knowledge") or []
        _intent_raw = result.get("intent", "advice")
        for _item in _proposed:
            if not isinstance(_item, dict):
                continue
            _topic = (_item.get("topic") or "").strip()
            _fact  = (_item.get("fact") or "").strip()
            if not _topic or not _fact:
                continue
            _admin  = is_admin(client_id)
            _status = "active" if (_intent_raw == "teach" and _admin) else "pending"
            add_knowledge(_topic, _fact, source=client_id, status=_status, path=self._db)

        intent       = result.get("intent", "advice")
        new_use_case = result.get("use_case") or use_case or message
        reply        = result.get("reply", "")
        plan_action  = result.get("plan_action", "none")
        full_plan    = result.get("full_plan")
        patch        = result.get("patch") or {}

        plan_changed, diff, version, mode = False, None, None, intent

        if plan_action == "create" and isinstance(full_plan, dict) and full_plan:
            plan_id = save_plan({"client_id": client_id, "plan": full_plan}, path=self._db)
            current_plan, plan_changed, version, mode = full_plan, True, 1, "plan"
        elif plan_action == "patch" and current_plan and isinstance(patch, dict) and patch:
            new_plan = {**current_plan, **patch}
            update_plan(plan_id, new_plan, path=self._db)
            diff = {k: {"before": current_plan.get(k), "after": v} for k, v in patch.items()}
            save_patch({
                "plan_id": plan_id,
                "version": current_version + 1,
                "admin_request": message,
                "patch": patch,
                "llm_reasoning": reply,
            }, path=self._db)
            current_plan, plan_changed, version = new_plan, True, current_version + 1
            mode = intent if intent in ("patch", "rescan") else "patch"
        else:
            mode = "advice"

        save_session(client_id, sess.get("questions", []), sess.get("answers", {}),
                     plan_id=plan_id, use_case=new_use_case, path=self._db)
        save_turn(client_id, "user", message, path=self._db)
        save_turn(client_id, "assistant", reply, mode=mode, path=self._db)

        return {
            "reply": reply, "use_case": new_use_case, "mode": mode,
            "plan": current_plan, "plan_id": plan_id, "plan_changed": plan_changed,
            "diff": diff, "version": version,
        }

    # ── patch-based refinement ────────────────────────────────────────────────

    def apply_patch(self, plan_id: str, admin_request: str, section: str | None = None) -> dict:
        """Apply an LLM-generated patch to a plan. Never regenerates the full plan.

        Returns dict: {new_plan, patch, diff, reasoning, version}
        """
        plan_row = get_plan(plan_id, path=self._db)
        if not plan_row:
            raise ValueError(f"Plan {plan_id} not found.")

        current_plan = plan_row["plan"]
        current_version = plan_row["version"]
        system = [
            {"text": _canvas_system(), "cache": True},
            {"text": _platform_knowledge_block(self._db), "cache": True},
        ]

        _section_block = ""
        if section and current_plan.get("system_prompt_sections", {}).get(section):
            _section_block = f'\n<target_section name="{section}">{json.dumps(current_plan.get("system_prompt_sections", {}).get(section, ""), ensure_ascii=False, indent=2)}</target_section>'

        user = f"""You are patching an existing Chat360 voice bot workflow plan.

<workflow_blueprint>
{json.dumps(current_plan.get("workflow_blueprint", {}), ensure_ascii=False, indent=2)}
</workflow_blueprint>

<build_notes>
{json.dumps(current_plan.get("build_notes", {}), ensure_ascii=False, indent=2)}
</build_notes>
{_section_block}
<admin_request>
{admin_request}
</admin_request>

Rules:
- ONLY modify the keys that need to change
- Do NOT regenerate or touch keys that are unaffected
- If you change any system_prompt_sections key, also re-render the full system_prompt field
- Preserve all existing content in unchanged keys

Return JSON with exactly these keys:
{{
  "patch": {{
    "<top_level_key>": <new_value>
  }},
  "reasoning": "One paragraph explaining what changed and what was deliberately left untouched."
}}"""

        result = self._llm.complete_json(system, user, max_tokens=16000, reasoning_effort="low")
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
