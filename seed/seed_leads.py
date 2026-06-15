"""Seed the Autovista demo dataset into the orchestrator Store (Neon Postgres).

Seeds a dealership account + an active monthly goal/target and a batch of mock
automobile leads across the Mumbai/Pune branches. All writes go through the
orchestrator `Store` (`get_store()` -> Neon `PostgresStore`); there is no direct
database client access here.

Usage:
    python -m seed.seed_leads [--count N] [--account NAME]
"""

from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from orchestrator.models import (
    Account, Goal, Target, Lead, FocusType,
    T_ACCOUNTS, T_GOALS, T_TARGETS, T_LEADS, to_row,
)
from orchestrator.store import get_store

load_dotenv()

# ~15 Maruti/Autovista dealer areas across the two regions (demo scope filters).
BRANCHES = {
    "Mumbai": [
        "Andheri", "Borivali", "Goregaon", "Worli", "Thane",
        "Vashi", "Kharghar", "Panvel",
    ],
    "Pune": [
        "Wakad", "Hinjewadi", "Kothrud", "Hadapsar", "Baner",
        "Pimpri-Chinchwad", "Viman Nagar",
    ],
}

VEHICLES = ["Swift", "Baleno", "Dzire", "Ertiga", "Brezza", "Fronx", "Grand Vitara", "WagonR"]
SOURCES  = ["Direct", "Facebook", "Website", "Walk-in", "Referral"]
FIRST    = ["Rahul", "Priya", "Amit", "Sneha", "Vikram", "Anjali", "Rohit", "Pooja",
            "Sahil", "Neha", "Arjun", "Kavya", "Manish", "Divya", "Karan", "Meera"]


def _phone(rng: random.Random) -> str:
    return "+9198" + "".join(str(rng.randint(0, 9)) for _ in range(8))


def seed(count: int = 40, account_name: str = "Autovista") -> dict:
    """Create an account + active goal + monthly target + `count` mock leads."""
    store = get_store()
    rng = random.Random(42)

    acct = Account(name=account_name)
    store.insert(T_ACCOUNTS, to_row(acct))

    month = datetime.now(timezone.utc).strftime("%Y-%m")
    goal = Goal(
        account_id=acct.id, month=month,
        focus_type=FocusType.SERVICE.value,
        focus_detail="Monsoon AC & periodic service drive",
        script_version="v1",
    )
    store.insert(T_GOALS, to_row(goal))

    target = Target(account_id=acct.id, period=month, reach_out=count, close=12, follow_up=20)
    store.insert(T_TARGETS, to_row(target))

    leads = []
    for _ in range(count):
        region = rng.choice(list(BRANCHES.keys()))
        branch = rng.choice(BRANCHES[region])
        due = (datetime.now(timezone.utc) + timedelta(days=rng.randint(-5, 20))).date().isoformat()
        lead = Lead(
            account_id=acct.id,
            name=f"{rng.choice(FIRST)} {rng.choice(['S','K','P','M','R'])}.",
            phone=_phone(rng),
            vehicle_model=rng.choice(VEHICLES),
            service_due_date=due,
            source=rng.choice(SOURCES),
            region=region,
            branch=branch,
            status="pending",
            lead_score=rng.randint(3, 10),
        )
        store.insert(T_LEADS, to_row(lead))
        leads.append(lead)

    return {
        "account_id": acct.id,
        "goal_id": goal.id,
        "target_id": target.id,
        "accounts": 1,
        "goals": 1,
        "targets": 1,
        "leads": len(leads),
        "month": month,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=40)
    ap.add_argument("--account", default="Autovista")
    args = ap.parse_args()
    result = seed(args.count, args.account)
    print(
        "Seeded into Neon store: "
        f"{result['accounts']} account, {result['goals']} goal, "
        f"{result['targets']} target, {result['leads']} leads "
        f"(month={result['month']}, account_id={result['account_id']})"
    )
