# Schema Revamp — Phase 1: Simple Flow (Omnichannel first)

Status: **planned, not started** (written 2026-10-15)
Scope: `services/telehub/` backend + `dashboard/` wizard. Campaign code/tables/tabs are **untouched**.
Builds on: [Phase 0 tenancy](schema_revamp_phase0_tenancy.md) (done — Organization, Membership, org FKs).

## 1. Goal

One simple, end-to-end flow a user can configure without code:

1. Create a **process agent** (under a department) and attach a **voicebot** — outbound = curl + DID, inbound = DID only.
2. Customers call (or we dial); results arrive by **webhook**.
3. The platform **discovers the variables** in the webhook payloads; the user **ticks** which feed QA and analytics.
4. The user picks an **omnichannel** (WhatsApp only), adds **template curls**, and **rules** that choose which template goes out.
5. Which variables reach the customer is **driven by the curl's own placeholders**.
6. A call's results can be passed on to **the next voicebot of the same process agent** (hand-off) — step 6 below.

Non-negotiable and unchanged: `Organization`, `Membership`/auth, `Department`.

## 2. Hierarchy

```
Organization
├─ Membership (user, role)
├─ VoiceBot                              org-level, reused by many agents
│   └─ PhoneNumber[] (DIDs)              one bot has many DIDs; a DID belongs to one bot
├─ Integration, SuppressionEntry
└─ Department
    └─ ProcessAgent                      a "campaign" = running this agent with lead sources
        ├─ LeadSource[]                  facebook / whatsapp / csv / api — attached to the agent
        ├─ BotJourney[] (ordered stages) each = one VoiceBot (+ which of its DIDs)
        │    └─ JourneyTransition[]      step 6: outcome -> next stage (same agent only)
        ├─ Variable[]            discovered from webhooks; flags: QA / analytics
        ├─ ChannelTemplate[]     WhatsApp curls + param mapping
        ├─ ChannelRule[]         ordered conditions -> template (or skip)
        └─ Execution -> QAResult, WhatsAppSend
```

There is no org-level campaign entity (see §6.1). Not in this phase: the node/graph tables
(`NodeInstance`, `NodeConnection`, `NodeTemplate`) and the `Contact`/`Interaction` split. They keep
working as-is.

## 3. What is wrong today (verified 2026-10-15)

- `services/hyundai_whatsapp.py` hardcodes the template choice: variable names (`appointment_date`,
  `appointment_time`, `appointment_place`, …), `callback_status == "required"`, `FILL_TEXT`, the
  `model_of_interest` fallback, and the `is_test` skip.
- Exactly three template slots (`OmnichannelConfig.whatsapp_curls` keys `T1/T2/T3`, plus the legacy
  `whatsapp_curl`).
- `OmnichannelConfig.variables` is stored but **never read**; what gets sent is whatever placeholders
  the pasted curl contains (`services/whatsapp.py` `build_request`).
- `Variable` is user-declared by hand, unique on `(process_agent, key, source)`, so one key can be two rows.
- `VoiceBot.webhook_schema` is "a field declaration for the UI" that nothing reads.

## 4. Target design

### 4.1 `Variable` — discovered, with two flags

Changes to the existing model (additive first):

| Field | Purpose |
|---|---|
| `use_in_qa` bool | Included in QA (e.g. missing-variable check, QA summary) |
| `use_in_analytics` bool | Shown in analytics/dispositions |
| `discovered` bool | Created automatically from a webhook payload |
| `last_seen_at` datetime | Last payload that carried this key |
| `sample_value` (short text) | Latest non-empty value, shown in the tick UI |

There is **no `send_to_customer` flag**: "sent" = referenced by a template's `param_map` (§4.2).

Discovery: after `inbound.normalize_payload` / `route_webhook_outcome` merge a payload, upsert one
`Variable` per key not yet known for that agent (`discovered=True`, both flags `False`), and bump
`last_seen_at`/`sample_value` for known ones. Never raises (fail-open like the rest of `services/`).
Skip obviously internal keys (a small deny-list: `dlr_id`, `session_id`, `recording_url`, …).

Uniqueness: move to `UNIQUE(process_agent, key)`. Today's `source` split (business_rules vs analytics)
collapses into the two flags — **data migration must merge rows with the same key**
(`analytics` row → `use_in_analytics=True`; keep the `business_rules` row's type/default/required).
Verify no code depends on `source` before dropping it (`grep -r "source" services/ dashboard/`).

### 4.2 `ChannelTemplate`

```
process_agent FK, channel ("whatsapp"), name, curl (text),
param_map JSON,   # {"customer_name": {"variable": "customer_name"},
                  #  "model":         {"variable": "model_name", "fallback": "model_of_interest"},
                  #  "link":          {"fixed": "https://…"}}
missing_fill (text, blank = block the send), is_active
```

On save the curl is parsed (reuse `whatsapp.parse_curl`) to list `template_data.param_data` keys; the UI
maps each to a variable (picked from the agent's discovered variables), a fixed value, or left to match
by name. `param_map` replaces the `@name`/same-name guessing in `build_request`. The set of variables
"sent to the customer" = union of `param_map` variables across the agent's templates.

Secrets: the curl carries the API key. API responses return the parsed param list and template title,
never the headers (preview already strips them). Encrypting at rest is a follow-up.

### 4.3 `ChannelRule`

```
process_agent FK, priority int, action ("send" | "skip"),
template FK (null when action="skip"),
match ("all" | "any"), checks JSON,  # [{"variable": "appointment_date", "op": "exists"}, …]
reason text                           # shown when skipped, e.g. "test call"
```

First rule (lowest `priority`) whose checks pass wins. Empty `checks` = always matches (the default).
`auto_send` moves onto an agent-level switch (keep `OmnichannelConfig.auto_send` for now).

**Operators (decided):** `exists`, `not_exists`, `equals` (case/whitespace-insensitive; T2 is
`callback_status == "required"`) and `truthy` (`true`/`"true"`/`"1"`/`"yes"`; the `is_test` skip).
The evaluator is one small shared function, also used by `JourneyTransition` (§6).

`is_test` skip becomes the top-priority rule: `action="skip"`, `reason="test call"`,
`checks=[is_test truthy]`.

### 4.4 `WhatsAppSend`

Keep the table and its logic (retries 2/10/30 min, `unique_auto_whatsapp_send_per_execution`). Add a
nullable `template` FK next to `template_key`; the rule engine sets both. Rename to a generic name only
in cleanup.

**Blocked sends (decided).** If any variable mapped by the chosen template is empty and the template has
no `missing_fill`, the send is **blocked**, not failed:
- New status `blocked` plus a `missing` JSON list on `WhatsAppSend`; `process_due_sends` ignores it
  (no retries, no `next_attempt_at`).
- The Calls tab shows "blocked — missing: appointment_date, …" with inputs for those variables.
- Submitting values (`POST .../whatsapp-sends/{id}/fill/`) writes them into `execution.variables`
  (recorded as an `ExecutionEvent` so it's auditable), flips the row to `pending` with
  `next_attempt_at=now`, and the next scheduler tick sends it.
- Today the same case ends as `failed` ("missing values for…"); that path is replaced.

### 4.5 Service layer

`hyundai_whatsapp.py` becomes `omnichannel.py`:
- `pick_rule(execution)` → evaluates `ChannelRule`s; returns the winning rule.
- `on_call_completed`, `process_due_sends`, `send_manual`, `preview` keep their shape and call sites
  (`inbound.record_inbound_call`, `run_scheduler`, the Calls tab endpoints).
- `whatsapp.build_request` takes the template's `param_map` instead of guessing.
- Keep a thin `hyundai_whatsapp.py` re-export until callers/tests are moved.

### 4.6 Seed rules that reproduce Hyundai exactly

For each agent with `auto_send=True`, the data migration creates templates T1/T2/T3 from
`whatsapp_curls` (T1 falls back to legacy `whatsapp_curl`), then rules:

| prio | action | checks | template |
|---|---|---|---|
| 0 | skip ("test call") | `is_test` truthy | — |
| 1 | send | all: `appointment_date`, `appointment_time`, `appointment_place` exist | T1 |
| 2 | send | `callback_status` equals `required` | T2 |
| 3 | send | any: `customer_name`, `model_name`, `appointment_place`, `appointment_date`, `appointment_time` exist | T1 |
| 4 | send | (default) | T3 |

T1 gets `missing_fill="unspecified"` and the `model_name ← model_of_interest` fallback in `param_map`.
Existing `pick_template` tests must pass against the new engine unchanged (they are the regression suite).

## 5. DID and inbound routing (small)

Decided: a voicebot can be attached to **several process agents**, and a voicebot has **several DIDs**.

`PhoneNumber(organization, bot FK, did)` with **`UNIQUE(did)` globally**: a DID belongs to exactly one
bot (so two bots can never claim the same number), and a bot has many. Today `VoiceBot.dids` is a JSON
list with no uniqueness; the migration copies each entry to a row and fails loudly on duplicates.
`VoiceBot.dids` stays (synced) until cleanup.

Which DIDs a stage uses: `BotJourney` gets a many-to-many to `PhoneNumber` (limited to its bot's
numbers). Outbound picks the `from` DID from that set, replacing the DID list currently synced into the
Communication node's config.

**Inbound agent resolution (decided).** Each process agent keeps its **own webhook URL**
(`WebhookDefinition.secret` → agent), configured per agent in Chat360 — as today. The URL picks the
agent; the DID is not used for routing. The inbound payload carries the number the customer dialed, so
the DID is used to **verify**: the dialed number must be one of the DIDs selected for that agent's
inbound stage (`BotJourney` ↔ `PhoneNumber`). On a mismatch the call is still recorded but flagged "DID mismatch" (decided),
and the endpoint acks 200 like every webhook.

The dialed number is `callee_number` (and the customer is `caller_number`). From a sample payload
(2026-10-15) it arrives as `"917965311524"`: digits only, country code included, no `+`. Compare after
normalizing both sides to digits (and tolerate a bare 10-digit stored DID by matching on the last 10
digits), reusing `outcome_routing._normalize_phone`'s conventions rather than a string `==`.

Other things that sample payload shows, which the build should account for:
- `is_test` is the **string** `"False"` — `truthy` must read it as false (only `true`/`"true"`/`"1"`/`"yes"`
  are true), never as a non-empty string.
- It **does** carry a `session_id`. `inbound._is_duplicate` assumes there is none and dedupes on
  `caller_number` + `call_start_time` (a time with no date, so two calls at 18:19:44 on different days
  collide). Dedupe on `session_id` when present and fall back to the old key only when absent.
- `call_duration` is a float string (`"71.660671"`); `escalation_required` is the string `"true"`.
- Values can be Devanagari text — keep everything UTF-8 clean in `Variable.sample_value` and the UI.
- The keys `session_id`, `caller_number`, `callee_number`, `call_start_time`, `call_duration`, `date`,
  `is_test` are platform-level; add them to the variable-discovery deny-list (they stay available to rules
  and templates, they just aren't suggested as QA/analytics ticks by default).

## 6. Hand-off between voicebots of the same agent (after omnichannel)

What I mean by hand-off: after bot A's call finishes, its results (the captured variables) are passed to
bot B as the input for B's call — e.g. Sales bot's "interested" leads go to a Follow-up bot. You've
decided this stays **inside one process agent**, so there is no cross-agent link table.

This already half-exists: `BotJourney.order` chains stages, but only when a stage runs out of retries
(`outcome_routing._advance_to_next_journey`). The change is to make it **condition-driven**:

```
JourneyTransition
  from_journey FK, to_journey FK   (same process agent)
  priority int, match ("all"|"any"), checks JSON   # same evaluator as ChannelRule
  on ("completed" | "retries_exhausted")
```

On completion, the first matching transition (checks run against the call's variables) moves the lead
to `to_journey`. Variables carry over, and `dispatcher.py` already forwards `variables` to the next bot
as Chat360 `params`. With no transition configured, today's behavior (advance by `order` on exhausted
retries) is kept.

**Decided: a new `Execution` per stage**, linked to the previous one by a `parent_execution` FK (null for
the first stage). Moving the same row breaks once stages have their own results: `QAResult` is
one-to-one with `Execution` and the auto WhatsApp send is unique per `Execution`, so stage B's QA and
WhatsApp message would collide with stage A's. The new row inherits the lead's variables and phone number
and gets its own `current_bot_journey`. The in-agent failure fallback (`_advance_to_next_journey`) moves to
the same new-row behaviour.

Inbound caveat: inbound `Execution`s are created already-completed and the scheduler ignores them
(`inbound.py`). A transition from an inbound stage to an outbound stage (e.g. a call-back bot) needs
the new row to be `pending` with `next_execution=now`, so it is only possible with the new-row design.

### 6.1 Campaigns

Decided: a campaign is just a process agent run with lead sources attached — launchable from inside the
agent's UI. So there is **no org-level Campaign entity**. `LeadSource` already hangs off `ProcessAgent`;
`Execution.campaign_id` stays a string batch label. If you later want per-run reporting, add a light
`Campaign(process_agent, name, lead_source, launched_at)` row as a *grouping record*, not a parent
of the agent. Not in this phase; existing campaign code and tabs are untouched.

## 7. Implementation steps (each its own PR; Claude runs `makemigrations` only — you run `migrate`)

1. **Variable reshape + discovery.** Add fields, discovery upsert on webhook intake, data migration to
   merge `source` rows, unique `(process_agent, key)`. Tests: discovery creates/updates, deny-list,
   merge migration keeps the right flags.
2. **ChannelTemplate + ChannelRule + engine.** Models, migration, seed data migration (§4.6),
   `omnichannel.py`, evaluator unit tests for `exists/not_exists/equals/truthy` and priority order; run the
   existing Hyundai tests against it.
3. **WhatsAppSend.template FK, blocked status, fill endpoint** and use `param_map` in `build_request`
   (placeholder-driven restriction). Tests: empty mapped variable → `blocked` (not failed, not retried);
   fill → `pending` → sent on next tick; `missing_fill` templates still send.
4. **API + dashboard.** Template CRUD (paste curl → list params → map), rules editor, variable tick table
   (QA / analytics), blocked-send fill UI on the Calls tab, preview. Org-scope every new viewset like
   Phase 0 (`OrgScopedViewSetMixin`).
5. **PhoneNumber/DID.** Model, backfill, global unique constraint, `BotJourney` ↔ `PhoneNumber` M2M,
   inbound resolution (per §5 / §8 Q1).
6. **JourneyTransition** (condition-driven hand-off between stages of one agent; §6).
7. **Cleanup (later).** Drop `whatsapp_curls`, `whatsapp_curl`, `OmnichannelConfig.variables`,
   `Variable.source`, `VoiceBot.dids`, the `hyundai_whatsapp` shim.

## 8. Open questions

Decided: operators `exists/not_exists/equals/truthy`; blocked-and-fillable sends; hand-off stays inside
one agent; bots shared across agents with many DIDs; campaign = a configured agent run (no org-level
campaign); one webhook URL per agent; DID used to verify inbound / pick outbound `from`; a stage uses a
chosen subset of its bot's DIDs; new `Execution` per stage with `parent_execution`; dialed-number key is
`callee_number`; a DID mismatch is recorded and flagged, not dropped.

Nothing open that blocks Step 1.

## 9. Definition of done (steps 1–4)

- A new inbound agent shows its webhook variables after the first call; ticking QA/analytics changes
  what those tabs use.
- Adding a WhatsApp template and a rule in the UI changes which message the next call triggers, with no
  code change.
- Hyundai's existing agent behaves identically after the data migration (regression tests green).
- No new table is reachable across orgs (cross-tenant sweep test extended to the new viewsets).
