# Autovista AI Tele-calling Hub

An outbound (and inbound) calling operations platform for Excell Autovista, built on Chat360 voice
bots. A department picks a wizard-configured **Process Agent**, launches a campaign of leads against
it, and a scheduler dispatches calls, retries failures, schedules callbacks, and routes each call's
outcome (QA, CRM update, WhatsApp follow-up) automatically.

| Piece | Stack | Path |
|---|---|---|
| **Telehub** (API + scheduler) | Django 5.2, DRF, Postgres (Supabase) | [services/telehub/](services/telehub/) |
| **Dashboard** | Next.js 16, Tailwind v4 | [dashboard/](dashboard/) |

For architecture (the fixed journey graph, how a lead moves from launch to dispatch to outcome, and
the conventions the `services/` modules follow), see [CLAUDE.md](CLAUDE.md). The journey and wizard
design source is [docs/superpowers/plans/gpt_ai_hub_impl_plan.md](docs/superpowers/plans/gpt_ai_hub_impl_plan.md).
Deployment is covered in [deploy.md](deploy.md).

```
Dashboard (Next.js, :3000) ──▶ Telehub API (Django, :8000) ──▶ Supabase Postgres
                                     ▲          │
            Chat360 post-call webhook│          │ run_scheduler: dispatch, retries, callbacks
                                     │          ▼
                                   Chat360 (outbound calls, WhatsApp)
```

## Layout

```
services/telehub/
  telehub/settings.py           Loads the repo-root .env
  apps/telehub/models.py        ProcessAgent, NodeInstance/NodeConnection, Execution, VoiceBot, BotJourney, …
  apps/telehub/api/             DRF viewsets: departments, process-agents, integrations,
                                node-templates, voice-bots; webhooks/<secret>/ intake
  apps/telehub/services/        journey, gating, dispatcher, outcome_routing, retry_backoff,
                                callback_schedule, campaign_launch, whatsapp, inbound, …
  apps/telehub/management/commands/
                                run_scheduler, seed_node_templates
  apps/telehub/tests.py         Test suite
dashboard/
  app/                          Pages: / , channels, process-agents, leads, bots, integrations, settings
  lib/telehubApi.ts             The dashboard's only API client
docs/                           Design docs for telehub and the Hyundai WhatsApp POC
```

## Setup

Python 3.11+ and Node 20+.

```bash
# Python (repo-root venv; requirements.txt points at services/telehub/requirements.txt)
python3 -m venv venv
./venv/bin/pip install -r requirements.txt     # Windows: .\venv\Scripts\python.exe -m pip install -r requirements.txt

# Dashboard
cd dashboard && npm install
```

Environment:

```bash
cp .env.example .env                                  # TELEHUB_DATABASE_URL, Chat360 credentials
cp dashboard/.env.local.example dashboard/.env.local  # NEXT_PUBLIC_TELEHUB_API_URL
```

## Run

Three terminals. From `services/telehub/` (on Windows use `..\..\venv\Scripts\python.exe`):

```bash
../../venv/bin/python manage.py seed_node_templates   # once; idempotent
../../venv/bin/python manage.py runserver             # API on :8000
../../venv/bin/python manage.py run_scheduler         # dispatch loop (or --once for a single tick)
```

```bash
cd dashboard && npm run dev                            # :3000
```

Migrations are applied with `manage.py migrate` (it uses `TELEHUB_DATABASE_MIGRATE_URL` when set).
The database is a shared hosted Supabase instance, so writes from a shell or admin hit real data.

## Tests

```bash
cd services/telehub
../../venv/bin/python manage.py test apps.telehub -v 2          # add --keepdb --noinput after an interrupted run
cd ../../dashboard && npx tsc --noEmit                          # the dashboard's only check
```
