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

with tab1:
    st.title("Chat360 Workflow Intelligence")
    st.caption(
        "Upload call recordings → auto-transcribe → generate a production-grade voice bot plan."
    )

    # ── Sidebar — existing plans + DB stats ──────────────────────────────────
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

    # ── STEP 1 — Input panel ──────────────────────────────────────────────────
    st.subheader("Step 1 — Upload & Describe")

    uploaded_files = st.file_uploader(
        "Upload call recordings",
        type=["wav", "mp3", "m4a", "aac"],
        accept_multiple_files=True,
        help="Multi-file upload. Each recording will be transcribed and analysed independently.",
    )

    use_case_text = st.text_area(
        "Describe your use case and what you need",
        height=120,
        placeholder=(
            "e.g. Maruti Suzuki outbound campaign to qualify test drive leads "
            "from Facebook ads, Hinglish, tier-2 cities"
        ),
    )

    # Client ID in main area — stays in sync with sidebar
    client_id = st.text_input(
        "Client ID",
        value=st.session_state["client_id"],
        key="main_client_id",
    )
    st.session_state["client_id"] = client_id

    transcribe_btn = st.button(
        "🎙️ Transcribe & Analyse",
        type="primary",
        disabled=not bool(uploaded_files),
    )

    # ── STEP 2 — Transcription + insights ────────────────────────────────────
    if transcribe_btn and uploaded_files:
        engines_ok, engines_err = _load_engines()
        if not engines_ok:
            st.error(
                f"Engine import failed — check your .env and dependencies.\n\n{engines_err}"
            )
        else:
            from transcription.engine import TranscriptionEngine

            engine      = TranscriptionEngine(DB_PATH)
            new_results = []
            total       = len(uploaded_files)
            progress_bar = st.progress(0, text="Starting transcription…")

            for idx, uploaded_file in enumerate(uploaded_files):
                progress_bar.progress(
                    idx / total,
                    text=f"Transcribing {uploaded_file.name} ({idx + 1}/{total})…",
                )
                # Write uploaded bytes to a temp file so the engine can read it
                suffix  = Path(uploaded_file.name).suffix
                tmp_path = None
                try:
                    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                        tmp.write(uploaded_file.read())
                        tmp_path = tmp.name

                    result = engine.transcribe(tmp_path, client_id)
                    result["filename"] = uploaded_file.name
                    new_results.append(result)
                except Exception as e:
                    st.error(f"Transcription failed for {uploaded_file.name}: {e}")
                finally:
                    # Always clean up the temp file after transcription
                    if tmp_path:
                        try:
                            os.unlink(tmp_path)
                        except Exception:
                            pass

            progress_bar.progress(1.0, text="Transcription complete ✓")
            st.session_state["transcripts"] = new_results
            st.success(f"Transcribed {len(new_results)} file(s) successfully.")

    # ── STEP 2 — Review, Edit & Re-analyse ───────────────────────────────────
    if _db_ready:
        try:
            db_transcripts = get_transcripts(client_id, path=DB_PATH)
        except Exception:
            db_transcripts = []

        if db_transcripts:
            st.subheader("Step 2 — Review & Approve Transcripts")
            st.caption(
                f"{len(db_transcripts)} recording(s) in DB for **{client_id}**. "
                "Edit the text if needed, then hit **Save & Re-analyse** to refresh insights."
            )

            for tr in db_transcripts:
                tid   = tr["id"]
                fname = tr.get("filename", tid)
                dur   = tr.get("duration", 0.0)
                created = tr.get("created_at", "")[:16]

                with st.expander(f"📄 {fname}  ·  {dur:.0f}s  ·  {created}", expanded=False):
                    # Editable transcript text
                    edited = st.text_area(
                        "Transcript (edit if needed)",
                        value=tr["transcript_text"],
                        height=320,
                        key=f"edit_{tid}",
                    )

                    btn_col, _ = st.columns([2, 6])
                    if btn_col.button("💾 Save & Re-analyse", key=f"reanalyse_{tid}"):
                        engines_ok, engines_err = _load_engines()
                        if not engines_ok:
                            st.error(f"Engine import failed: {engines_err}")
                        else:
                            from transcription.engine import TranscriptionEngine
                            with st.spinner("Saving and re-analysing…"):
                                try:
                                    eng = TranscriptionEngine(DB_PATH)
                                    eng.rerun_insights(tid, client_id, edited)
                                    st.success("Transcript saved. Insights updated.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Re-analysis failed: {e}")

                    st.divider()

                    # Load all insights for this transcript from DB
                    if _db_ready:
                        try:
                            all_ins = get_insights_by_transcript(tid, path=DB_PATH)
                        except Exception:
                            all_ins = []

                        if not all_ins:
                            st.info("No insights yet — hit Save & Re-analyse to generate.")
                        else:
                            latest = all_ins[-1]
                            st.markdown("**Current Insights:**")
                            _render_insight(latest)

                            # Comparison expander — only shown when >1 insight versions exist
                            if len(all_ins) > 1:
                                prev = all_ins[-2]
                                with st.expander(
                                    f"📊 Compare with previous analysis  "
                                    f"(v{len(all_ins) - 1} → v{len(all_ins)})",
                                    expanded=False,
                                ):
                                    _render_insight_comparison(prev, latest)

    # ── STEP 3 — Clarifying questions ────────────────────────────────────────
    st.subheader("Step 3 — Clarifying Questions")

    # Enable as soon as this client has any transcripts in DB
    if _db_ready:
        try:
            _has_transcripts = bool(get_transcripts(client_id, path=DB_PATH))
        except Exception:
            _has_transcripts = False
    else:
        _has_transcripts = False

    if _has_transcripts:
        gen_q_btn = st.button("💬 Generate Questions")

        if gen_q_btn:
            if not use_case_text.strip():
                st.toast("Add a use case description above before generating questions.", icon="⚠️")
                st.warning("Please describe your use case in the text field above, then click Generate Questions again.")
            else:
                engines_ok, engines_err = _load_engines()
                if not engines_ok:
                    st.error(f"Engine import failed: {engines_err}")
                else:
                    from intelligence.designer import WorkflowDesigner

                    with st.spinner("Generating clarifying questions…"):
                        try:
                            designer  = WorkflowDesigner(DB_PATH)
                            questions = designer.generate_clarifying_questions(
                                client_id, use_case_text
                            )
                            st.session_state["questions"] = (
                                questions if isinstance(questions, list) else []
                            )
                            # Persist questions immediately; reset answers since questions changed
                            if _db_ready:
                                try:
                                    save_session(client_id, st.session_state["questions"], {}, path=DB_PATH)
                                    st.session_state["answers"] = {}
                                except Exception:
                                    pass
                        except Exception as e:
                            st.error(f"Question generation failed: {e}")

        # Render questions as freetext areas for admin answers
        if st.session_state["questions"]:
            st.markdown(
                "**Answer each question to help the AI generate a precise plan:**"
            )
            for q in st.session_state["questions"]:
                qid   = q.get("id", "q")
                qtext = q.get("question", "")
                why   = q.get("why", "")
                answer = st.text_area(
                    qtext,
                    key=f"q_{qid}",
                    help=why,
                    height=80,
                )
                # Persist each answer in session state by question id
                st.session_state["answers"][qid] = answer

            if _db_ready and st.button("💾 Save Answers", key="save_answers_btn"):
                try:
                    save_session(
                        client_id,
                        st.session_state["questions"],
                        st.session_state["answers"],
                        plan_id=st.session_state.get("plan_id"),
                        path=DB_PATH,
                    )
                    st.toast("Answers saved.", icon="✅")
                except Exception as e:
                    st.error(f"Save failed: {e}")
    else:
        st.info("Upload and transcribe at least one recording first, then generate clarifying questions.")

    # ── STEP 4 — Plan generation ──────────────────────────────────────────────
    st.subheader("Step 4 — Generate Workflow Plan")

    plan_btn = st.button(
        "📋 Generate Workflow Plan",
        type="primary",
        disabled=not use_case_text.strip(),
    )

    if plan_btn and use_case_text.strip():
        engines_ok, engines_err = _load_engines()
        if not engines_ok:
            st.error(f"Engine import failed: {engines_err}")
        else:
            from intelligence.designer import WorkflowDesigner

            # Build answers list from session state for LLM context
            answers_list = [
                {
                    "question": q.get("question", ""),
                    "answer":   st.session_state["answers"].get(q.get("id", ""), ""),
                }
                for q in st.session_state["questions"]
            ]

            # Persist answers before the LLM call so a refresh doesn't lose them
            if _db_ready:
                try:
                    save_session(
                        client_id,
                        st.session_state["questions"],
                        st.session_state["answers"],
                        path=DB_PATH,
                    )
                except Exception:
                    pass

            with st.spinner("Generating plan… this may take 15–30 seconds."):
                try:
                    designer = WorkflowDesigner(DB_PATH)
                    plan     = designer.generate_plan(client_id, use_case_text, answers_list)
                    st.session_state["plan_id"]      = plan.get("plan_id")
                    st.session_state["current_plan"] = plan
                    if _db_ready:
                        try:
                            save_session(
                                client_id,
                                st.session_state["questions"],
                                st.session_state["answers"],
                                plan_id=plan.get("plan_id"),
                                path=DB_PATH,
                            )
                        except Exception:
                            pass
                    st.success("Plan generated and saved.")
                except Exception as e:
                    st.error(f"Plan generation failed: {e}")

    # Render the current plan if available in session state
    if st.session_state["current_plan"]:
        _render_plan(st.session_state["current_plan"])

    # ── STEP 5 — Patch loop ───────────────────────────────────────────────────
    if st.session_state["plan_id"]:
        st.subheader("Step 5 — Refine the Plan")

        patch_request = st.text_area(
            "Request a change…",
            placeholder=(
                "e.g. Add a VOICE_WEBHOOK node at the start to fetch lead CRM data "
                "by @caller_number before the qualification conversation begins."
            ),
            height=100,
            key="patch_request_input",
        )

        patch_btn = st.button(
            "🔧 Apply Patch",
            disabled=not patch_request.strip(),
        )

        if patch_btn and patch_request.strip():
            engines_ok, engines_err = _load_engines()
            if not engines_ok:
                st.error(f"Engine import failed: {engines_err}")
            else:
                from intelligence.designer import WorkflowDesigner

                with st.spinner("Applying patch…"):
                    try:
                        designer     = WorkflowDesigner(DB_PATH)
                        patch_result = designer.apply_patch(
                            st.session_state["plan_id"], patch_request
                        )
                        # Update session state to reflect patched plan
                        st.session_state["current_plan"] = patch_result["new_plan"]
                        st.success(
                            f"Patch applied — now at version {patch_result['version']}."
                        )

                        # Show LLM reasoning for the patch
                        st.info(patch_result.get("reasoning", ""))

                        # Show before/after diff per changed key
                        diff = patch_result.get("diff", {})
                        if diff:
                            st.markdown("**Changes:**")
                            for key, change in diff.items():
                                dcol1, dcol2 = st.columns(2)
                                with dcol1:
                                    st.markdown(f"**Before — `{key}`**")
                                    st.json(change.get("before") or {})
                                with dcol2:
                                    st.markdown(f"**After — `{key}`**")
                                    st.json(change.get("after") or {})

                        # Re-render the full updated plan
                        _render_plan(st.session_state["current_plan"])

                    except Exception as e:
                        st.error(f"Patch failed: {e}")

        # Version history — all patches for this plan
        if _db_ready and st.session_state["plan_id"]:
            try:
                patches = get_patches(st.session_state["plan_id"], path=DB_PATH)
            except Exception:
                patches = []

            if patches:
                with st.expander("📜 Version History", expanded=False):
                    for p in patches:
                        vcol1, vcol2, vcol3 = st.columns([1, 4, 2])
                        vcol1.markdown(f"**v{p['version']}**")
                        vcol2.markdown(p.get("admin_request", ""))
                        vcol3.markdown(p.get("created_at", "")[:16])


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
