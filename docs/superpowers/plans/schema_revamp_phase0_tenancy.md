# Schema Revamp — Phase 0: Tenancy

Status: **planned, not started** (written 2026-10-13)
Scope: `services/telehub/` backend + `dashboard/` auth plumbing.

---

## 1. Where this phase sits

Telehub is being reworked from a single-client POC (Excell Autovista) into a multi-tenant layer on top
of Chat360: connect lead sources to bots, trigger outbound calls, take outcomes in by webhook, run
analytics, and route a contact from one bot/agent to the next. The full revamp, agreed in discussion:

| Phase | What | Depends on |
|---|---|---|
| **0 — Tenancy** (this doc) | `Organization`, `Membership`, API auth, org-scoped queries | — |
| 1 — Contacts & Campaigns | `Contact` (**scoped to a department**, `UNIQUE(department, phone_e164)`), `Campaign` table, org-wide `SuppressionEntry` for DND | 0 |
| 2 — Interactions | `Interaction` table (`direction` = `inbound`/`outbound`, fixed forever; `channel` column, voice only for now) + `VoiceCallDetail` + raw `WebhookDelivery` inbox; bot field/outcome mapping | 1 |
| 3 — Flows | Versioned `FlowVersion.spec` (JSON graph), node-type registry in code, JSONLogic conditions, single-cursor engine; replaces `NodeInstance`/`NodeConnection`/`BotJourney` | 2 |
| 4 — Cleanup | `Execution` → `Enrollment`, `OutboundAction` replaces `WhatsAppSend`, job queue w/ `skip_locked` | 3 |
| Future | User-editable canvas (edits the same Phase 3 spec), WhatsApp/chat bots in `Interaction` | 3 |

Phase 0 goes first because every later table needs an `organization_id`, and today **two clients
(Excell + the Hyundai POC) share one database with nothing keeping their data apart.**

---

## 2. Current state (verified 2026-10-13)

- **No tenant concept.** `Department` is the top-level table ([models.py:5](../../../services/telehub/apps/telehub/models.py)).
  `VoiceBot`, `Integration` are global tables owned by nobody.
- **API is unauthenticated.** `settings.py` has no `REST_FRAMEWORK` block, so DRF falls back to
  `AllowAny`. The dashboard's `request()` in `dashboard/lib/telehubApi.ts` sends no auth header and
  no cookies. Anyone with the Render URL can read and write everything.
- **Viewsets return `.objects.all()`**: `VoiceBotViewSet`, `DepartmentViewSet`,
  `IntegrationViewSet`, `ProcessAgentViewSet` (`api/views.py` ~L99–155).
- **ID lookups taken straight from request data, all unscoped.** Each is a cross-tenant hole once orgs exist:
  - `services/process_agent.py:95` — `department_id=payload["department"]` (wizard create)
  - `services/process_agent.py:111` — `VoiceBot.objects.filter(pk=voice_bot_id)`
  - `services/process_agent.py:156` — `Integration.objects.filter(pk=integration_id)`
  - `api/views.py:412` — `Integration.objects.filter(pk=integration_id)` (attach integration)
  - (`bot_journey_id` lookups at `views.py:544` are already scoped through `agent.bot_journeys` — fine.)
- **Non-request entry points** (no user, so they must not depend on request-scoped tenancy):
  - `webhook_intake` (`views.py:700`) resolves via `WebhookDefinition.secret` → `process_agent`. The
    secret *is* the credential; it stays unauthenticated. **But `secret` has no unique constraint**,
    and that needs fixing.
  - `run_scheduler` processes due executions globally. That's fine; it never trusts user input.
- `dashboard/lib/domainConfig.ts` hardcodes branding/vocabulary per deploy ("Autovista"). This becomes
  org-level config eventually, but **not in this phase.**

---

## 3. Target design

### 3.1 New models

```python
class Organization(models.Model):
    name       = CharField(max_length=128)
    slug       = SlugField(unique=True)          # "excell-autovista", "hyundai-poc"
    is_active  = BooleanField(default=True)
    created_at / updated_at

class Membership(models.Model):
    ROLE_ADMIN, ROLE_MEMBER = "admin", "member"  # keep it to two roles for now (see §7)
    user         = FK(settings.AUTH_USER_MODEL, CASCADE, related_name="memberships")
    organization = FK(Organization, CASCADE, related_name="memberships")
    role         = CharField(choices=..., default=ROLE_MEMBER)
    created_at
    class Meta: unique_together = [("user", "organization")]
```

A user can belong to several orgs (Chat360 staff will). Django `is_staff`/`is_superuser` users are
**platform staff**: they can act in any org and are the only ones who can create orgs.

### 3.2 Which tables get `organization_id`

Rule: a table gets its own `organization` FK if it's **queried on its own by the API, high-volume,
or survives the revamp**. Child tables that are only reached through a scoped parent *and* are retired
in Phases 3–4 inherit their scope from the parent, so there's no point backfilling a column that's
about to be dropped.

| Gets `organization` FK | Scoped through parent (no column) | Global (no tenant) |
|---|---|---|
| `Department` | `BotJourney`, `NodeInstance`, `NodeConnection` (→ ProcessAgent; retired Ph3) | `NodeTemplate` (system-owned; retired Ph3) |
| `ProcessAgent` (denormalized; must equal `department.organization`) | `Variable`, `OmnichannelConfig`, `ProcessIntegration` (→ ProcessAgent) | |
| `VoiceBot` | `ExecutionEvent`, `QAResult`, `AnalyticsEvent`, `WhatsAppSend` (→ Execution) | |
| `Integration` | | |
| `LeadSource` | | |
| `WebhookDefinition` | | |
| `Execution` (high volume; indexed `(organization, status, next_execution)` later) | | |

All FKs: `on_delete=PROTECT` (deleting an org should be a deliberate, scripted operation), `db_index=True`.

### 3.3 Consistency rules (same org across relations)

The DB can't enforce "these two FKs point into the same org" without composite FKs, so this phase
enforces it in code, plus a checker:

- `ProcessAgent.organization == ProcessAgent.department.organization`
- `BotJourney.voice_bot.organization == BotJourney.process_agent.organization`
- `ProcessIntegration.integration.organization == process_agent.organization`
- `Execution.organization == Execution.process_agent.organization`
- `LeadSource` / `WebhookDefinition` org == their `process_agent`'s org

Where it's enforced:
1. Services that create these rows take `organization` as an explicit argument and scope every
   ID lookup with it (see §3.5).
2. A `manage.py check_tenancy` command that reports any row breaking the rules. Run it after the
   backfill and in CI later.

### 3.4 Authentication

**Recommendation: DRF + `djangorestframework-simplejwt`.** Short-lived access token plus refresh token,
sent as `Authorization: Bearer ...`.

- Why not session cookies: the dashboard (Vercel) and the API (Render) are on different sites, so
  cookies would need `SameSite=None; Secure` + CSRF across sites, which is more fragile.
- It should stay swappable for Chat360 SSO later. The dashboard keeps all token handling in one
  module (`dashboard/lib/auth.ts`) so the mechanism can change without touching call sites.
- Endpoints: `POST /api/auth/token/`, `POST /api/auth/token/refresh/`, `GET /api/auth/me/`
  (returns the user + memberships so the dashboard can render an org switcher).

`REST_FRAMEWORK` settings:
```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework_simplejwt.authentication.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
}
```
`webhook_intake` explicitly sets `authentication_classes = []` / `permission_classes = [AllowAny]`.

### 3.5 Resolving and enforcing the org per request

**Org selection:** an `X-Organization` header carrying the org slug.
- If it's missing and the user has exactly one membership, use that org.
- If it's missing and the user has several memberships, return 400.
- If the user isn't a member of that org (and isn't staff), return 403.
- Implemented as a DRF permission/mixin (not Django middleware), because JWT auth only runs
  inside DRF, so a middleware wouldn't see the user yet.

**Scoping is explicit, not magic.** No thread-local "current org" and no default manager that
filters itself. The scheduler, webhooks and management commands run with no request, and an implicit
filter would silently return nothing (or everything) there. Instead:

```python
class TenantQuerySet(models.QuerySet):
    def for_org(self, org): return self.filter(organization=org)

class OrgScopedViewSetMixin:
    permission_classes = [IsAuthenticated, HasOrgAccess]   # HasOrgAccess sets request.organization
    def get_queryset(self):
        return super().get_queryset().filter(**{self.org_lookup: self.request.organization})
    def perform_create(self, serializer):
        serializer.save(organization=self.request.organization)
```
`org_lookup` defaults to `"organization"`.

Every viewset in `api/views.py` except `NodeTemplateViewSet` (global) uses the mixin. Objects in
another org return **404, not 403**, so their existence isn't revealed.

**ID fields coming from the request** (the holes listed in §2) get scoped:
- `create_process_agent_from_wizard(payload)` → `create_process_agent_from_wizard(payload, organization)`;
  `department`, `voice_bot_id` and `integration_id` are looked up with `.for_org(organization)`, and
  an ID that doesn't resolve is a validation error (400).
- The `integrations` action (`views.py:403`) does the same.
- Serializer `PrimaryKeyRelatedField`s get their `queryset` narrowed to the request org in
  `get_fields()` / `__init__` (one small helper, reused).

### 3.6 Webhook secret hardening

- Add a partial unique constraint: `UniqueConstraint(fields=["secret"], condition=~Q(secret=""), name="unique_webhook_secret")`.
- Check first whether any duplicate secrets exist (`check_tenancy` reports them). If they do,
  regenerate the duplicates before adding the constraint.
- Nothing else changes: the org comes from `webhook.process_agent.organization`.

---

## 4. Backfill strategy

The data migration can't know which existing rows belong to Hyundai, so it's done in two steps:

1. **Data migration (automatic):** create one org, `Excell Autovista` (`excell-autovista`), and
   assign **every** existing row to it. Create a `Membership(role=admin)` for every existing user
   (only admin/superusers exist today).
2. **Management command (run by you, reviewed output):**
   ```
   manage.py assign_org --org hyundai-poc --department <id> [--department <id> ...] [--dry-run]
   ```
   - Creates the org if it doesn't exist, then moves those departments to it, along with their
     process agents, executions, lead sources and webhooks.
   - Moves each `VoiceBot`/`Integration` to the org whose agents use it. If one is used by agents
     in **both** orgs, the command **stops and reports it**, so you decide (duplicate it or pick one).
   - `--dry-run` prints the plan without writing. Run that first.
   - Then run `check_tenancy`. It should report zero violations.

---

## 5. Implementation steps (each is one PR and deploys on its own)

> Per CLAUDE.md: Claude runs `makemigrations` and commits the files, **never `migrate`**. After each
> step that adds a migration, you run
> `..\..\venv\Scripts\python.exe manage.py migrate` from `services\telehub\` yourself.

**Step 1 — Models + nullable FKs + backfill (no behavior change)**
- Add `Organization`, `Membership`, and `TenantQuerySet`.
- Add **nullable** `organization` FK to the 7 tables in §3.2.
- Migration A: schema. Migration B: data migration from §4.1.
- Register both models in Django admin, with an `organization` list filter on the tenant tables.
- Add the `check_tenancy` and `assign_org` commands.
- ✅ The existing test suite passes unchanged.

**Step 2 — Make FKs non-null; every write path sets the org**
- Make the column `NOT NULL` (migration C).
- Make write paths pass `organization`: the wizard create, `launch_campaign`
  (`Execution.organization = process_agent.organization`), `inbound.record_inbound_call`,
  `outcome_routing._advance_to_next_journey` (same org, so no change), and `VoiceBot`/`Integration` create.
- Update test fixtures to create an org. A `make_org()` helper in `tests.py` keeps this to one line per test.
- Add the webhook secret unique constraint (§3.6, migration D).

**Step 3 — Authentication behind a flag**
- Add `djangorestframework-simplejwt` to `services/telehub/requirements.txt`.
- Add the token endpoints and `/api/auth/me/`.
- New setting `TELEHUB_AUTH_REQUIRED` (env var, default `False`):
  - When `False`: unauthenticated requests go through as before, and `request.organization`
    falls back to the default org (`excell-autovista`). This lets the backend deploy before the dashboard.
  - When `True`: JWT is required and the org is resolved per §3.5.
- Dashboard:
  - A `/login` page and `lib/auth.ts` for storing and refreshing tokens.
  - `telehubApi.request()` attaches `Authorization` and `X-Organization` headers.
  - A 401 redirects to `/login`.
  - An org switcher in `TopHeader.tsx`, shown only when the user has more than one membership.
- Add `CORS_ALLOW_HEADERS` entries for `authorization` and `x-organization`.

**Step 4 — Enforce scoping**
- Apply `OrgScopedViewSetMixin` to all tenant viewsets.
- Scope the ID lookups in §3.5.
- Narrow the serializer FK querysets.
- Add the tests in §6.

**Step 5 — Cut over (an ops step; no new code)**
1. Deploy.
2. Create users and memberships in admin.
3. Run `assign_org --dry-run`, then the real `assign_org` for Hyundai.
4. Run `check_tenancy`.
5. Set `TELEHUB_AUTH_REQUIRED=True` on Render.
6. Confirm Chat360's webhooks still return 200 and still route to the right executions.

---

## 6. Tests to add (in `apps/telehub/tests.py`)

- **Cross-tenant sweep:** two orgs, each with full fixture data. For each viewset in `router.registry`
  (except node-templates), a user from org A gets list results containing no org-B IDs, and gets
  404 on retrieve/update/delete of an org-B object.
- **Header resolution:** missing header with one membership → OK; missing with two → 400;
  non-member → 403; staff → any org.
- **Wizard create with an org-B `department` / `voice_bot_id` / `integration_id`** → 400, nothing created.
- **`perform_create` ignores a client-supplied `organization`** in the body.
- **Webhook intake** still works unauthenticated with `TELEHUB_AUTH_REQUIRED=True`, and the
  execution it routes belongs to the webhook's org.
- **`launch_campaign`** stamps `Execution.organization` from the agent.
- **`check_tenancy`** detects a deliberately mismatched `BotJourney.voice_bot`.
- **`assign_org`** moves a department's whole tree, and refuses when a bot is shared across orgs.
- **Auth flag off** → existing unauthenticated behavior preserved (one smoke test).

Reminder: the suite runs against `test_postgres` on Supabase (~90s). Use `--keepdb --noinput`
after an interrupted run.

---

## 7. Decisions to confirm at the start of the build session

| # | Question | Recommendation |
|---|---|---|
| 1 | Auth mechanism | simplejwt now; Chat360 SSO later behind `lib/auth.ts` |
| 2 | How the dashboard picks an org | `X-Organization` header (slug), not org-in-URL |
| 3 | Roles | `admin` / `member` only; department-level permissions deferred |
| 4 | Which departments are Hyundai's | List them from `/admin/` before running `assign_org` |
| 5 | Bots/integrations shared by both clients today? | `assign_org --dry-run` will tell us; duplicate them if so |
| 6 | Can a user belong to several orgs? | Yes (Chat360 staff); handled by the header + switcher |
| 7 | Who creates orgs | Platform staff only, via Django admin (no self-serve signup) |

## 8. Explicitly out of scope for Phase 0

- `Contact`, `Campaign`, `SuppressionEntry` (Phase 1)
- `Interaction` / direction / channel (Phase 2)
- Flow versioning and the node registry (Phase 3)
- Per-org branding (moving `domainConfig.ts` into `Organization`)
- Postgres row-level security (possible later as defense in depth; the `organization_id` columns
  make it possible)
- Department-level access control
- `organization_id` on `ExecutionEvent` and the other tables scoped through a parent (their
  replacements in Phases 2–4 get it from day one)

## 9. Definition of done

- Every tenant viewset is org-scoped, and the cross-tenant sweep test passes.
- `TELEHUB_AUTH_REQUIRED=True` is live on Render, and the dashboard logs in and works for both
  orgs' users.
- `check_tenancy` reports zero violations on the production database.
- Hyundai's data lives in its own org. Excell users can't see it, and Hyundai users can't see Excell's.
- Chat360 webhooks still resolve and route correctly.
