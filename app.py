"""Chat360 Intelligence Fabric — Streamlit UI.

Two tabs:
  Tab 1 — Workflow Intelligence: 5-step flow (upload → transcribe → questions → plan → patch)
  Tab 2 — Agentic AI: placeholder for tomorrow's build
"""

import json
import os
import tempfile
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# ── Page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="Chat360 Intelligence Fabric",
    page_icon="🎙️",
    layout="wide",
)

# ── Environment and DB setup ──────────────────────────────────────────────────
load_dotenv()
DB_PATH = os.getenv("DB_PATH", "intelligence_fabric.db")

# Initialise DB; surface warning if env is missing but don't crash
try:
    from shared.db import (
        init_db, get_plans, get_plan, get_patches,
        get_transcripts, get_insight_by_transcript, get_insights_by_transcript,
        save_session, load_session,
        get_transcript_by_filename, get_turns,
    )
    init_db(DB_PATH)
    _db_ready = True
except Exception as _db_err:
    _db_ready = False
    _db_err_msg = str(_db_err)


# ── Lazy engine loader ────────────────────────────────────────────────────────
def _load_engines():
    """Lazy-load TranscriptionEngine and WorkflowDesigner; return (ok, error_msg).

    Deferred so a missing API key shows a warning rather than crashing on import.
    """
    try:
        from transcription.engine import TranscriptionEngine  # noqa: F401
        from intelligence.designer import WorkflowDesigner    # noqa: F401
        return True, ""
    except Exception as e:
        return False, str(e)


# ── Session state initialisation ──────────────────────────────────────────────
def _init_state():
    """Ensure all session state keys are present; restore Q&A from DB on first load."""
    defaults = {
        "transcripts":   [],
        "plan_id":       None,
        "current_plan":  None,
        "questions":     [],
        "answers":       {},
        "client_id":     "autovista",
        "_session_loaded_for": None,  # tracks which client_id was last restored
        "use_case":      "",
        "last_reply":    "",
        "last_diff":     None,
        "last_version":  None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

    # Restore Q&A + active plan from DB when client_id changes or on first page load
    client_id = st.session_state["client_id"]
    if _db_ready and st.session_state["_session_loaded_for"] != client_id:
        try:
            saved = load_session(client_id, path=DB_PATH)
            if saved["questions"]:
                st.session_state["questions"] = saved["questions"]
            if saved["answers"]:
                st.session_state["answers"] = saved["answers"]
            if saved.get("plan_id") and not st.session_state["plan_id"]:
                row = get_plan(saved["plan_id"], path=DB_PATH)
                if row:
                    st.session_state["plan_id"]      = saved["plan_id"]
                    st.session_state["current_plan"] = row["plan"]
            try:
                st.session_state["use_case"] = saved.get("use_case", "") or st.session_state.get("use_case", "")
                _turns = get_turns(client_id, limit=2, path=DB_PATH)
                _last = next((t["content"] for t in reversed(_turns) if t["role"] == "assistant"), "")
                if _last:
                    st.session_state["last_reply"] = _last
            except Exception:
                pass
        except Exception:
            pass
        st.session_state["_session_loaded_for"] = client_id


_init_state()


# ── Insight renderer ─────────────────────────────────────────────────────────
def _render_insight(ins: dict) -> None:
    """Render a single insight dict (score badge, sentiment, summary, lists)."""
    icol1, icol2 = st.columns(2)
    score     = ins.get("agent_score")
    sentiment = ins.get("sentiment", "neutral")

    if score is not None:
        score_color = "#43A047" if score >= 7 else "#FB8C00" if score >= 5 else "#E53935"
        icol1.markdown(
            f"<span style='background:{score_color};color:white;"
            f"padding:2px 8px;border-radius:4px;font-weight:bold'>"
            f"Agent Score: {score}/10</span>",
            unsafe_allow_html=True,
        )

    sent_color = {"positive": "#43A047", "neutral": "#1E88E5", "negative": "#E53935"}.get(
        sentiment, "#9E9E9E"
    )
    icol2.markdown(
        f"<span style='background:{sent_color};color:white;"
        f"padding:2px 8px;border-radius:4px'>Sentiment: {sentiment}</span>",
        unsafe_allow_html=True,
    )

    for label, key in [
        ("Objection Patterns",    "objection_patterns"),
        ("Qualification Signals", "qualification_signals"),
        ("Escalation Signals",    "escalation_signals"),
        ("KB Gaps",               "kb_gaps"),
    ]:
        items = ins.get(key) or []
        if items:
            st.markdown(f"**{label}:**")
            for item in items:
                st.markdown(f"- {item}")

    summary = ins.get("summary", "")
    if summary:
        st.info(summary)


# ── Insight comparison renderer ───────────────────────────────────────────────
def _render_insight_comparison(old: dict, new: dict) -> None:
    """Side-by-side diff between two insight dicts (previous vs current)."""
    old_dt = old.get("created_at", "")[:16]
    new_dt = new.get("created_at", "")[:16]

    col_old, col_new = st.columns(2)

    # Score
    old_score = old.get("agent_score")
    new_score = new.get("agent_score")
    score_arrow = ""
    if old_score is not None and new_score is not None:
        if new_score > old_score:
            score_arrow = f" ↑ +{new_score - old_score}"
        elif new_score < old_score:
            score_arrow = f" ↓ {new_score - old_score}"

    col_old.markdown(f"**Previous** · {old_dt}")
    col_new.markdown(f"**Current** · {new_dt}")

    col_old.markdown(f"Agent Score: **{old_score}/10**")
    col_new.markdown(f"Agent Score: **{new_score}/10**{score_arrow}")

    col_old.markdown(f"Sentiment: `{old.get('sentiment','—')}`")
    col_new.markdown(f"Sentiment: `{new.get('sentiment','—')}`")

    col_old.markdown("**Summary:**")
    col_old.caption(old.get("summary", "—"))
    col_new.markdown("**Summary:**")
    col_new.caption(new.get("summary", "—"))

    # List field diffs
    for label, key in [
        ("Objection Patterns",    "objection_patterns"),
        ("Qualification Signals", "qualification_signals"),
        ("Escalation Signals",    "escalation_signals"),
        ("KB Gaps",               "kb_gaps"),
    ]:
        old_set = set(old.get(key) or [])
        new_set = set(new.get(key) or [])
        added   = new_set - old_set
        removed = old_set - new_set
        if added or removed:
            st.markdown(f"**{label}**")
            diff_col1, diff_col2 = st.columns(2)
            with diff_col1:
                for item in sorted(removed):
                    st.markdown(f"<span style='color:#E53935'>— {item}</span>", unsafe_allow_html=True)
            with diff_col2:
                for item in sorted(added):
                    st.markdown(f"<span style='color:#43A047'>+ {item}</span>", unsafe_allow_html=True)


# ── Plan renderer — defined here so it can be called from any tab context ─────
def _render_plan(plan: dict) -> None:
    """Render all sections of a workflow plan in collapsible expanders.

    Sections: workflow_blueprint, system_prompt, qualification_questions,
    objection_handling, escalation_rules, kb_scaffold, build_notes.
    """
    st.markdown("---")
    st.markdown("### 📐 Workflow Plan")

    # ── Workflow Blueprint ────────────────────────────────────────────────────
    blueprint = plan.get("workflow_blueprint", {})
    with st.expander("🗺️ Workflow Blueprint", expanded=True):
        if isinstance(blueprint, dict):
            description = blueprint.get("description", "")
            if description:
                st.markdown(description)

            stages = blueprint.get("stages", [])
            if stages:
                for stage in stages:
                    # Each stage rendered as a three-column card row
                    scol1, scol2, scol3 = st.columns([1, 2, 4])
                    scol1.markdown(
                        f"<span style='font-size:1.1em;font-weight:700'>#{stage.get('stage_id','')}</span>",
                        unsafe_allow_html=True,
                    )
                    node_type = stage.get("node_type", "")
                    scol2.markdown(
                        f"<code style='background:#1E3A5F;color:#90CAF9;padding:2px 6px;"
                        f"border-radius:4px'>{node_type}</code>",
                        unsafe_allow_html=True,
                    )
                    scol3.markdown(
                        f"**{stage.get('name', '')}** — {stage.get('purpose', '')}"
                    )
                    st.divider()
        else:
            st.json(blueprint)

    # ── System Prompt ─────────────────────────────────────────────────────────
    with st.expander("🤖 System Prompt"):
        system_prompt = plan.get("system_prompt", "")
        if system_prompt:
            st.code(system_prompt, language="text")
        else:
            st.info("No system prompt in this plan.")

    # ── Qualification Questions ────────────────────────────────────────────────
    with st.expander("❓ Qualification Questions"):
        qual_qs = plan.get("qualification_questions", [])
        if qual_qs:
            for q in qual_qs:
                if isinstance(q, dict):
                    st.markdown(
                        f"- **{q.get('question', '')}** "
                        f"(`{q.get('variable', '')}`) — "
                        f"*{q.get('purpose', '')}*"
                    )
                else:
                    st.markdown(f"- {q}")
        else:
            st.info("No qualification questions defined.")

    # ── Objection Handling ────────────────────────────────────────────────────
    with st.expander("🛡️ Objection Handling"):
        objections = plan.get("objection_handling", {})
        if objections and isinstance(objections, dict):
            oh_col1, oh_col2 = st.columns(2)
            oh_col1.markdown("**Objection**")
            oh_col2.markdown("**Bot Response**")
            st.divider()
            for obj, resp in objections.items():
                oc1, oc2 = st.columns(2)
                oc1.markdown(obj)
                oc2.markdown(resp)
        else:
            st.info("No objection handling defined.")

    # ── Escalation Rules ──────────────────────────────────────────────────────
    with st.expander("🚨 Escalation Rules"):
        esc_rules = plan.get("escalation_rules", [])
        if esc_rules:
            er_c1, er_c2, er_c3 = st.columns(3)
            er_c1.markdown("**Trigger**")
            er_c2.markdown("**Action**")
            er_c3.markdown("**Node Type**")
            st.divider()
            for rule in esc_rules:
                if isinstance(rule, dict):
                    rc1, rc2, rc3 = st.columns(3)
                    rc1.markdown(rule.get("trigger", ""))
                    rc2.markdown(rule.get("action", ""))
                    rc3.markdown(
                        f"<code>{rule.get('node_type', '')}</code>",
                        unsafe_allow_html=True,
                    )
        else:
            st.info("No escalation rules defined.")

    # ── KB Scaffold ───────────────────────────────────────────────────────────
    with st.expander("📚 KB Scaffold"):
        kb = plan.get("kb_scaffold", {})
        if kb and isinstance(kb, dict):
            for topic, content in kb.items():
                st.markdown(f"**{topic}**")
                st.markdown(content)
                st.divider()
        else:
            st.info("No KB scaffold defined.")

    # ── Build Notes (Chat360 Canvas) ──────────────────────────────────────────
    with st.expander("🔨 Build Notes (Chat360 Canvas)"):
        build_notes = plan.get("build_notes", {})
        if build_notes and isinstance(build_notes, dict):
            instructions = build_notes.get("canvas_instructions", [])
            if instructions:
                st.markdown("**Canvas Instructions:**")
                for i, step in enumerate(instructions, 1):
                    st.markdown(f"{i}. {step}")

            variables = build_notes.get("variables_required", [])
            if variables:
                st.markdown("**Variables Required:**")
                st.markdown(", ".join(f"`{v}`" for v in variables))

            # Config summary row
            config_items = {
                "Language":        build_notes.get("language"),
                "TTS Engine":      build_notes.get("tts_engine"),
                "STT Engine":      build_notes.get("stt_engine"),
                "Outbound Params": ", ".join(build_notes.get("outbound_params") or []) or None,
            }
            st.markdown("**Config:**")
            for label, val in config_items.items():
                if val:
                    st.markdown(f"- **{label}:** {val}")

            silence_cfg = build_notes.get("silence_handle_config", {})
            if silence_cfg:
                st.markdown("**Silence Handling:**")
                st.json(silence_cfg)
        else:
            st.info("No build notes defined.")


# ── Top-level warning if DB or env is broken ─────────────────────────────────
if not _db_ready:
    st.warning(f"DB initialisation failed — some features disabled. {_db_err_msg}")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB LAYOUT
# ══════════════════════════════════════════════════════════════════════════════
tab1, tab2 = st.tabs(["🧠 Workflow Intelligence", "🤖 Agentic AI"])


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — WORKFLOW INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════

# ── Sidebar — existing plans + DB stats (renders to sidebar from any context) ─
with st.sidebar:
    st.header("📂 Plans")

    # Client ID input — sidebar drives session state
    sidebar_client = st.text_input(
        "Client ID",
        value=st.session_state["client_id"],
        key="sidebar_client_id",
    )
    st.session_state["client_id"] = sidebar_client

    # Show existing plans for this client in a dropdown
    if _db_ready:
        try:
            existing_plans = get_plans(sidebar_client, path=DB_PATH)
        except Exception as e:
            existing_plans = []
            st.error(f"Could not load plans: {e}")

        if existing_plans:
            plan_labels = {
                f"v{p['version']} — {p['updated_at'][:16]}": p["id"]
                for p in existing_plans
            }
            selected_label = st.selectbox(
                "Load a previous plan",
                ["— select —"] + list(plan_labels.keys()),
            )
            if selected_label != "— select —" and st.button("Load Plan"):
                # Load the selected plan into session state to continue patching
                chosen_id = plan_labels[selected_label]
                try:
                    row = get_plan(chosen_id, path=DB_PATH)
                    if row:
                        st.session_state["plan_id"]      = chosen_id
                        st.session_state["current_plan"] = row["plan"]
                        if _db_ready:
                            try:
                                save_session(
                                    sidebar_client,
                                    st.session_state["questions"],
                                    st.session_state["answers"],
                                    plan_id=chosen_id,
                                    path=DB_PATH,
                                )
                            except Exception:
                                pass
                        st.success(f"Loaded plan {chosen_id[:8]}…")
                except Exception as e:
                    st.error(f"Load failed: {e}")
        else:
            st.info("No plans yet for this client.")

    st.divider()
    st.header("📊 DB Stats")
    if _db_ready:
        try:
            all_transcripts = get_transcripts(sidebar_client, path=DB_PATH)
            all_plans       = get_plans(sidebar_client, path=DB_PATH)
            col_a, col_b = st.columns(2)
            col_a.metric("Transcripts", len(all_transcripts))
            col_b.metric("Plans", len(all_plans))
        except Exception as e:
            st.error(f"Stats error: {e}")


with tab1:
    st.title("Chat360 Workflow Intelligence")
    st.caption(
        "One conversation: describe your use case, refine the plan, ask questions, "
        "or fold in new recordings — the assistant remembers your use case."
    )

    client_id = st.text_input("Client ID", value=st.session_state["client_id"], key="main_client_id")
    st.session_state["client_id"] = client_id

    # ── Attach recordings (transcribed on your next message; already-processed files are skipped) ──
    uploaded_files = st.file_uploader(
        "Attach call recordings (optional)",
        type=["wav", "mp3", "m4a", "aac"],
        accept_multiple_files=True,
        help="New recordings are transcribed + analysed when you send your next message. "
             "Files already processed for this client are skipped.",
    )

    # ── Remembered use case ──────────────────────────────────────────────────
    with st.expander("🎯 Use case (remembered)", expanded=not st.session_state.get("use_case")):
        uc = st.text_area(
            "Your use case", value=st.session_state.get("use_case", ""),
            key="use_case_edit", height=100,
            help="Set once; the assistant remembers it. Edit anytime.",
        )
        if uc != st.session_state.get("use_case", ""):
            st.session_state["use_case"] = uc
            if _db_ready:
                try:
                    _s = load_session(client_id, path=DB_PATH)
                    save_session(client_id, _s.get("questions", []), _s.get("answers", {}),
                                 plan_id=st.session_state.get("plan_id"), use_case=uc, path=DB_PATH)
                except Exception:
                    pass

    # ── The one command box ──────────────────────────────────────────────────
    _placeholder = ("Describe your use case…" if not st.session_state.get("current_plan")
                    else "Ask for a change, ask a question, or say 'check the new recordings for insights'…")
    message = st.text_area("Message", key="cmd_box", placeholder=_placeholder, height=90)
    send = st.button("Send", type="primary", disabled=not message.strip())

    if send and message.strip():
        engines_ok, engines_err = _load_engines()
        if not engines_ok:
            st.error(f"Engine import failed — check your .env and dependencies.\n\n{engines_err}")
        else:
            from transcription.engine import TranscriptionEngine
            from intelligence.designer import WorkflowDesigner

            # 1. Transcribe any NEW uploads (dedup by filename)
            if uploaded_files:
                engine = TranscriptionEngine(DB_PATH)
                for uf in uploaded_files:
                    if get_transcript_by_filename(client_id, uf.name, path=DB_PATH):
                        st.info(f"↺ Skipped (already processed): {uf.name}")
                        continue
                    tmp_path = None
                    try:
                        with tempfile.NamedTemporaryFile(suffix=Path(uf.name).suffix, delete=False) as tmp:
                            tmp.write(uf.read())
                            tmp_path = tmp.name
                        with st.spinner(f"Transcribing {uf.name}…"):
                            engine.transcribe(tmp_path, client_id)
                        st.success(f"Processed {uf.name}")
                    except Exception as e:
                        st.error(f"Transcription failed for {uf.name}: {e}")
                    finally:
                        if tmp_path:
                            try:
                                os.unlink(tmp_path)
                            except Exception:
                                pass

            # 2. One conversational turn
            with st.spinner("Thinking…"):
                try:
                    designer = WorkflowDesigner(DB_PATH)
                    res = designer.converse(client_id, message)
                    st.session_state["use_case"]     = res["use_case"]
                    st.session_state["plan_id"]      = res["plan_id"]
                    st.session_state["current_plan"] = res["plan"]
                    st.session_state["last_reply"]   = res["reply"]
                    st.session_state["last_diff"]    = res["diff"]
                    st.session_state["last_version"] = res["version"]
                    st.rerun()
                except Exception as e:
                    st.error(f"Conversation failed: {e}")

    # ── Assistant reply + what-changed ───────────────────────────────────────
    if st.session_state.get("last_reply"):
        st.markdown("#### 💬 Assistant")
        st.info(st.session_state["last_reply"])
        if st.session_state.get("last_version"):
            st.caption(f"Plan updated → v{st.session_state['last_version']}")
        _diff = st.session_state.get("last_diff")
        if _diff:
            with st.expander("What changed", expanded=False):
                for _k, _ch in _diff.items():
                    _c1, _c2 = st.columns(2)
                    _c1.markdown(f"**Before — `{_k}`**")
                    _c1.json(_ch.get("before") or {})
                    _c2.markdown(f"**After — `{_k}`**")
                    _c2.json(_ch.get("after") or {})

    # ── Transcripts & insights (read-only visibility) ────────────────────────
    if _db_ready:
        try:
            _db_transcripts = get_transcripts(client_id, path=DB_PATH)
        except Exception:
            _db_transcripts = []
        if _db_transcripts:
            with st.expander(f"📄 Transcripts & insights ({len(_db_transcripts)})", expanded=False):
                for _tr in _db_transcripts:
                    _ins = get_insight_by_transcript(_tr["id"], path=DB_PATH)
                    _score = _ins.get("agent_score") if _ins else "—"
                    st.markdown(f"**{_tr['filename']}** · {_tr.get('duration', 0):.0f}s · agent {_score}/10")
                    if _ins and _ins.get("summary"):
                        st.caption(_ins["summary"])

    # ── Plan ─────────────────────────────────────────────────────────────────
    if st.session_state.get("current_plan"):
        _render_plan(st.session_state["current_plan"])

    # ── Version history + rebuild escape hatch ───────────────────────────────
    if st.session_state.get("plan_id"):
        if _db_ready:
            try:
                _patches = get_patches(st.session_state["plan_id"], path=DB_PATH)
            except Exception:
                _patches = []
            if _patches:
                with st.expander("📜 Version History", expanded=False):
                    for _p in _patches:
                        _v1, _v2, _v3 = st.columns([1, 4, 2])
                        _v1.markdown(f"**v{_p['version']}**")
                        _v2.markdown(_p.get("admin_request", ""))
                        _v3.markdown(_p.get("created_at", "")[:16])

        if st.button("🔄 Rebuild plan from scratch"):
            engines_ok, engines_err = _load_engines()
            if not engines_ok:
                st.error(f"Engine import failed: {engines_err}")
            else:
                from intelligence.designer import WorkflowDesigner
                with st.spinner("Rebuilding…"):
                    try:
                        designer = WorkflowDesigner(DB_PATH)
                        plan = designer.generate_plan(client_id, st.session_state.get("use_case", ""), [])
                        st.session_state["plan_id"]      = plan.get("plan_id")
                        st.session_state["current_plan"] = plan
                        st.session_state["last_reply"]   = "Rebuilt the plan from scratch from the current use case and insights."
                        st.session_state["last_diff"]    = None
                        st.session_state["last_version"] = 1
                        st.rerun()
                    except Exception as e:
                        st.error(f"Rebuild failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — AGENTIC AI (placeholder)
# ══════════════════════════════════════════════════════════════════════════════

with tab2:
    st.title("AI Orchestrator")
    st.caption(
        "Set the monthly goal and target here. Changing the goal bumps the voice-bot script version — "
        "regenerate the system prompt in the Workflow Intelligence tab, then update the bot."
    )
    try:
        from intelligence.goal_editor import render_goal_target_editor
        render_goal_target_editor()
    except Exception as e:
        st.error(f"Goal editor unavailable: {e}")

    st.divider()
    st.caption(
        "Dispatch, follow-up reliability, and live analytics run in the orchestrator service "
        "(`orchestrator/`) and the dashboard (`dashboard/`)."
    )
