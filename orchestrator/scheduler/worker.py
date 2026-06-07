"""Scheduler worker — drives the Follow-up Reliability Engine on a fixed interval.

This is the always-on loop that makes promised follow-ups never get missed: every
`SCHEDULER_INTERVAL_SEC` it calls `engine.process_due()`, which dispatches a call for
every due commitment (with retry/backoff) and exhausts the ones past max_retries.
"""

from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler

from .. import config
from ..adapters.simulation import SimulationVoiceDispatcher, StoreCRMAdapter
from ..engines.followup import FollowupEngine
from ..store import get_store


def build_followup_engine(voice=None) -> FollowupEngine:
    """Assemble a FollowupEngine over the configured store.

    The Chat360 dispatcher gets wired in a later wave; until then `voice` defaults to
    the simulation dispatcher seeded from the configured DID pool.
    """
    store = get_store()
    if voice is None:
        voice = SimulationVoiceDispatcher(config.DID_POOL or None)
    crm = StoreCRMAdapter(store)
    return FollowupEngine(store, voice, crm)


def tick() -> dict:
    """Run one dispatch cycle and return the engine's result summary."""
    engine = build_followup_engine()
    r = engine.process_due()
    print(f"[followup] dispatched={r['dispatched']} exhausted={r['exhausted']}")
    return r


def run(interval=None) -> None:
    """Start the blocking scheduler loop, firing `tick` every `interval` seconds."""
    if interval is None:
        interval = config.SCHEDULER_INTERVAL_SEC

    scheduler = BlockingScheduler()
    scheduler.add_job(
        tick,
        "interval",
        seconds=interval,
        id="followup_tick",
        max_instances=1,
        coalesce=True,
    )
    print(f"[scheduler] follow-up tick every {interval}s — Ctrl+C to stop")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        print("[scheduler] stopped")


if __name__ == "__main__":
    run()
