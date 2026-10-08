# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

An outbound-calling operations platform for Excell Autovista (Maruti Suzuki dealer), built around a
form-driven "Process Agent" concept: a department picks a wizard-configured workflow, launches a
campaign of leads against it, and a scheduler dispatches, retries, and routes outcomes for each lead
automatically. An older, independent "Intelligence" plane (calls → insights → Chat360 bot plans:
`intelligence/`, `shared/`, `transcription/`, `seed/`, `scripts/`, `humanvoice_engine/`) has been
removed from the repo, along with its dashboard pages.

**The live, current backend is `services/telehub/`** (Django + DRF + Postgres — a hosted Supabase
database, read from `TELEHUB_DATABASE_URL` in the repo-root `.env`, with
`TELEHUB_DATABASE_MIGRATE_URL` used instead while `manage.py migrate` runs; it was SQLite early on,
and any doc or comment still saying SQLite is stale). Two earlier orchestrator implementations
(`orchestrator/`, FastAPI/Neon; `orchestrator_django/`) were built, then deleted (see `008b424 remove
orchestrator/, dead dashboard pages, and orchestrator-only deps ahead of telehub rebuild`) in favor
of telehub.

## Repo layout

```
services/telehub/            Live Django backend for the calling platform (see below)
dashboard/                   Next.js 16 dashboard — talks to telehub via dashboard/lib/telehubApi.ts
requirements.txt             Just `-r services/telehub/requirements.txt` (the single source of truth)
deploy.md                    Hosting telehub (Render) + dashboard (Vercel) for the Hyundai POC
docs/superpowers/plans/gpt_ai_hub_impl_plan.md
                              The design doc telehub's journey graph and wizard were built from —
                              read this before changing journey topology or node semantics.
```

## Commands

### Telehub backend (`services/telehub/`)

No venv is committed. First time:
```bash
# from the repo root
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

From `services/telehub/`, always invoke the repo-root venv explicitly (`../../venv/bin/python`, not a
bare `python`/`python3`):
```bash
../../venv/bin/python manage.py migrate                    # apply migrations
../../venv/bin/python manage.py seed_node_templates         # idempotent: seed the 8 system NodeTemplate rows
../../venv/bin/python manage.py runserver                   # :8000 — matches dashboard's default NEXT_PUBLIC_TELEHUB_API_URL
../../venv/bin/python manage.py test apps.telehub -v 2       # full test suite (3000+ lines in tests.py)
../../venv/bin/python manage.py test apps.telehub.tests.SomeTestCase -v 2   # single test case
```

Tests run against a real `test_postgres` database on the same Supabase instance, so they are not
instant (~90s for the suite) and a leftover connection from an interrupted run makes the next one
fail with `database "test_postgres" is being accessed by other users`. Add `--keepdb` (reuses and
migrates the existing test database) and `--noinput` when that happens.

**Never run `manage.py migrate` yourself.** When a model change needs a migration, run
`manage.py makemigrations` (file generation only — it doesn't touch the database) and commit the
resulting migration file, but leave applying it to the user: tell them which migration was created
and give them the exact `../../venv/bin/python manage.py migrate` command to run themselves.

The scheduler is not a daemon — nothing dispatches due `Execution`s until you run it:
```bash
../../venv/bin/python manage.py run_scheduler --once      # one tick, for testing
../../venv/bin/python manage.py run_scheduler              # loops forever, --interval seconds between ticks (default 30)
```

#### On Windows

A venv created on Windows puts its interpreter at `venv\Scripts\python.exe`, not `venv/bin/python`,
so every `../../venv/bin/python` above becomes `..\..\venv\Scripts\python.exe`. Everything else
(the commands, the "never run `migrate` yourself" rule, the shared `.env`) is the same.

First time, from the repo root in PowerShell (use `py -3` if `python` isn't on PATH):
```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

From `services\telehub\`:
```powershell
..\..\venv\Scripts\python.exe manage.py migrate                 # apply migrations (user only — see above)
..\..\venv\Scripts\python.exe manage.py seed_node_templates
..\..\venv\Scripts\python.exe manage.py runserver                # :8000
..\..\venv\Scripts\python.exe manage.py test apps.telehub -v 2
..\..\venv\Scripts\python.exe manage.py run_scheduler --once
..\..\venv\Scripts\python.exe manage.py run_scheduler            # loops forever; run in its own terminal
```

Notes:
- Calling the venv's `python.exe` directly avoids activation entirely. If you do want to activate
  it (`.\venv\Scripts\Activate.ps1`) and PowerShell blocks the script, run
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.
- In Git Bash, the same paths work with forward slashes: `../../venv/Scripts/python.exe`.
- The repo lives under OneDrive; if OneDrive sync locks files in `venv\` or `dashboard\node_modules\`
  (pip/npm "access denied" or `EPERM` errors), pause syncing or exclude those folders.
- Use two terminals for local runs: one for `runserver`, one for `run_scheduler`, plus a third for
  the dashboard below.

Settings load the **repo-root `.env`** (`services/telehub/telehub/settings.py` walks up three
levels) — `CHAT360_OUTBOUND_BEARER_TOKEN` and
`CHAT360_AUTH_COOKIE` come from there, not a telehub-local `.env`. The outbound DID/caller-ID is
**not** an env var — it's per-`VoiceBot` (`VoiceBot.dids`, synced onto each `BotJourney`'s
Communication `NodeInstance.config`), since one `ProcessAgent` can have several `BotJourney`s each
dispatching through a different bot/number.

Inspect the DB directly with `manage.py dbshell` / `manage.py shell`, or the Django admin at
`/admin/` (`manage.py createsuperuser` once). It is a shared hosted database, not a local file —
there is no `db.sqlite3` to poke at, and writes from a shell hit real data.

### Dashboard (`dashboard/`)
```bash
cd dashboard
npm run dev             # :3000
npm run build
npx tsc --noEmit         # the only frontend "test" — no Jest/Vitest in this project
npm run lint
```
Point it at telehub with `NEXT_PUBLIC_TELEHUB_API_URL` (defaults to `http://localhost:8000`) in
`dashboard/.env.local`.

On Windows the dashboard commands are identical in PowerShell or Git Bash (`cd dashboard`,
`npm run dev`, etc.). If PowerShell refuses to run `npm`/`npx` because `npm.ps1` is blocked by the
execution policy, call `npm.cmd` / `npx.cmd` instead, or set the policy as above.

`npm run lint` is known-broken and **not** caused by whatever you just changed: it fails outright
(ESLint 9 with no `eslint.config.js` in the repo). Treat `npx tsc --noEmit` and `npm run build` as
the real signal.

## Telehub architecture — how a lead actually moves

**Core entity: `ProcessAgent`** (one Process == one AI agent), scoped under a `Department`. Everything
else hangs off it: `NodeInstance`/`NodeConnection` (its graph), `LeadSource`, `ProcessIntegration`,
`Variable`, `WebhookDefinition`, and its `Execution`s (one per lead per run).

**The journey graph is fixed, not user-edited (V1).** `services/journey.py`'s
`JOURNEY_STEPS`/`JOURNEY_EDGES` define the one topology every `ProcessAgent` gets, stamped out by
`generate_journey()` when the wizard creates it. The dashboard's Journey tab renders it read-only;
there is no canvas, no draft/active versioning, and no node/edge CRUD API. Changing the shape means
changing those two lists (and writing a data migration for existing agents).

```
Lead Received -> Business Hours -> DND Check -> Communication -> Completed
                                                                     |-- (always) --> QA
                                                                     |-- (always) --> CRM Update
                                                                     |-- (outcome="failed") --> Retry --> back to Business Hours
                                                                     |-- (outcome="callback_requested") --> Callback --> back to Business Hours
```
`condition=""` on an edge means "always fires" (QA/CRM Update are side effects, not further routing);
Retry and Callback are the two outcome-conditioned branches and loop back to re-attempt.

**Node behavior is keyed by the exact `NodeInstance.name` string.** Each module keeps its own
`NODE_NAME_*` constants (`dispatcher.NODE_NAME_COMMUNICATION`, `outcome_routing.NODE_NAME_COMPLETED`,
`NODE_NAME_QA`, `NODE_NAME_CRM_UPDATE`, …) and looks the node up with
`journey_nodes(execution).get(name=...)`. Renaming a step in `JOURNEY_STEPS` therefore breaks every
module that references it — grep for the name across `services/` before touching it.
`Execution.current_node` is a name string too, kept in sync as the lead moves.

**Chaining bot journeys is implicit, by `order`.** When a journey's retry budget is exhausted,
`outcome_routing._advance_to_next_journey()` moves the *same* `Execution` on to the next `BotJourney`
by `order` (e.g. Sales -> Follow-up). There is no explicit, condition-gated hand-off between bots;
this failure-path fallback is the only mechanism.

**A campaign launch → dispatch → outcome cycle, traced through the code:**

1. `POST /api/telehub/process-agents/{id}/launch-campaign/` → `services/campaign_launch.py`:
   bulk-creates one `Execution` per lead (`status="pending"`, `current_node="Lead Received"`,
   `next_execution=now()` — a lead with `next_execution=NULL` is invisible to the scheduler's
   `next_execution__lte=now()` filter, so this must always be set on creation).
2. `manage.py run_scheduler`'s `tick()` polls `Execution`s with `next_execution <= now()` and
   `status` in `pending`/`retry_scheduled`/`callback_scheduled`. It does not walk the graph — the
   front half's shape is hardcoded control flow: `gating.is_within_business_hours()` (outside hours,
   `next_execution` is left as-is so the next tick retries rather than drifting the due time), then
   `gating.is_suppressed_dnc()` (sets `status="suppressed_dnc"`, `next_execution=None`), then
   `dispatcher.dispatch_execution()`. Both gates fail open on missing/malformed config; DND needs
   the node config AND the execution's own `variables["dnd"]` to be truthy.
3. `services/dispatcher.py`'s `dispatch_execution()` POSTs to the `"Communication"` `NodeInstance`'s
   configured `api_url` (Chat360's outbound endpoint) — stdlib `urllib` only, no `requests`/`httpx`.
   Never raises; every outcome (success, non-2xx, network error, missing config) is caught and
   recorded as an `ExecutionEvent`. Body shape is `{"from", "to", "params", "dlr_id"}` — this was
   reverse-engineered against a real successful call and earlier guessed fields (`bot_id`, flat
   top-level vars) were removed; don't reintroduce them without re-confirming against Chat360.
   `dlr_id` **must** be sent as a string (`str(execution.id)`) — Chat360's Go struct field is typed
   `string` and 400s on a bare int. Manually follows 307/308 redirects (`urllib` won't, for POST) up
   to `MAX_REDIRECTS`. Indian 10-digit numbers with no country code are normalized to `+91...` before
   sending — Chat360 accepts a bare 10-digit number with 200 OK but silently never dials it.
4. Chat360 posts the outcome back to `POST /api/telehub/webhooks/<secret>/` → `views.webhook_intake`
   looks up the `WebhookDefinition` by secret and correlates the payload to an `Execution` via
   `outcome_routing.find_execution_for_payload()` — `dlr_id` if present, but the real-world path is a
   normalized `contact_no` match against the execution's `variables["to_number"]`, since Chat360's
   actual post-call payload for this integration carries no `dlr_id`. It then calls
   `route_webhook_outcome()`: merges the payload into `execution.variables` verbatim, moves the
   execution to the `Completed` node, and fires that node's edges in a fixed order — QA
   (`QAResult`, deduped via `hasattr(execution, "qa_result")`) and CRM Update always run as
   unconditional side effects, then Callback (`callback_schedule.schedule_callback()`, data-driven
   against the Callback node's own wizard-declared conditions rather than a hardcoded label), and
   only if Callback did *not* fire is `payload["outcome"]` checked against `FAILURE_OUTCOMES` to
   decide on `retry_backoff.schedule_retry()`. A resend carrying a `session_id` this execution
   already completed on returns early, so duplicate deliveries don't re-run the side effects. The
   webhook endpoint always acks 200 regardless of whether anything resolved — never raises.

   `VoiceBot.webhook_schema` is synced onto the `WebhookDefinition` and the Communication node, but
   nothing reads it at runtime — it is a field declaration for the UI, not an inbound key mapping.
   Whatever keys Chat360 posts land in `variables` under those exact names, and `dispatcher.py`
   forwards `variables` back out as Chat360 `params`.

**Defensive pattern used throughout `services/`:** every node-config lookup
(`_get_node_config`/`_get_node`) treats a missing `NodeInstance`, missing config key, or any
exception as an empty/False default rather than raising — a misconfigured or not-yet-wizard-completed
`ProcessAgent` degrades to "allow" (gating) or "no-op" (dispatch/outcome routing), never a hard
failure. Preserve this fail-open style when touching these modules.

**Two generations of "how a workflow is defined" don't exist here** — unlike the deleted
`orchestrator_django`, telehub has only one era: everything is `NodeInstance`/`NodeConnection` rows
generated from `JOURNEY_STEPS`/`JOURNEY_EDGES`. The `NODE_NAME_*` constants scattered across
`services/` are duplicated copies of the same strings, not a layer of indirection — keep them in
sync by hand.
