"""Intelligence Plane — Goal & Target editor.

A human edits the monthly GOAL (what to pursue) and TARGET (how many to reach-out /
close / follow-up). Saving writes to the SAME orchestrator store the orchestrator and
dashboard read, and bumps the voice-bot script_version — the link that tells the human
to regenerate the bot system prompt.

This module exposes a single render function; app.py wires it into a tab.
"""

from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from orchestrator.store import get_store
from orchestrator.engines.followup import FollowupEngine
from orchestrator.engines.goal_adaptation import GoalAdaptationEngine
from orchestrator.adapters.simulation import SimulationVoiceDispatcher, StoreCRMAdapter
from orchestrator.models import T_ACCOUNTS


def _engine():
    store = get_store()
    followup = FollowupEngine(store, SimulationVoiceDispatcher(), StoreCRMAdapter(store))
    return store, GoalAdaptationEngine(store, followup)


def render_goal_target_editor():
    """Render the Goal & Target editor tab. Writes to the orchestrator store."""
    st.subheader("🎯 Goal & Target")
    st.caption("Set the monthly focus and targets. Saving bumps the voice-bot script version — "
               "regenerate the system prompt in the Plan tab and update the bot.")
    store, ga = _engine()

    # Account picker from the orchestrator store; guide the user to seed if none exist.
    accounts = store.list(T_ACCOUNTS)
    if not accounts:
        st.info("No accounts yet. Run `python -m seed.seed_leads` to seed Autovista demo data.")
        return
    labels = {a["name"]: a["id"] for a in accounts}
    name = st.selectbox("Account", list(labels.keys()))
    account_id = labels[name]

    current = ga.active_goal(account_id)
    if current:
        st.markdown(f"**Active goal:** `{current['focus_type']}` — {current['focus_detail']}  "
                    f"· month `{current['month']}` · script `{current['script_version']}`")
    else:
        st.markdown("_No active goal yet._")

    month = st.text_input("Month (YYYY-MM)", value=datetime.now(timezone.utc).strftime("%Y-%m"))
    focus_type = st.selectbox("Focus type", ["service", "product"],
                              index=0 if not current or current["focus_type"] == "service" else 1)
    focus_detail = st.text_input("Focus detail", value=(current["focus_detail"] if current else ""))

    st.markdown("**Target for the period**")
    c1, c2, c3 = st.columns(3)
    reach_out = c1.number_input("Reach out", min_value=0, value=0, step=1)
    close     = c2.number_input("Close",     min_value=0, value=0, step=1)
    follow_up = c3.number_input("Follow up", min_value=0, value=0, step=1)

    if st.button("💾 Save Goal & Target", type="primary"):
        try:
            goal = ga.set_goal(account_id, month=month, focus_type=focus_type, focus_detail=focus_detail)
            ga.set_target(account_id, period=month, reach_out=int(reach_out), close=int(close), follow_up=int(follow_up))
            st.success(f"Saved. Voice-bot script is now {goal['script_version']}.")
            st.toast("Goal updated — regenerate the system prompt in the Plan tab and update the bot.", icon="🎯")
        except Exception as e:
            st.error(f"Save failed: {e}")
