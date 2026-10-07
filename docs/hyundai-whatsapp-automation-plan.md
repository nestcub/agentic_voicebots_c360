# Hyundai WhatsApp automation (POC) — plan

Status: implemented on `feat/revision` · 2026-10-07 (migration 0009 to apply)

**Scope: Hyundai proof of concept only.** The rules below are Hyundai-specific and are written
in code for the Hyundai inbound process agent. A general rule engine and WhatsApp/omnichannel
handling for every agent will be designed and built later. This POC deliberately doesn't build
that.

Phase 1 (shipped on `feat/revision`): inbound calls land in telehub via the post-call webhook
(`services/inbound.py`), show up in the process agent's **Calls** tab, and a person clicks
**Send** to push the WhatsApp template in `OmnichannelConfig.whatsapp_curl`, filled per row by
`services/whatsapp.py`.

This POC: when an inbound call completes, telehub picks one of three templates (T1/T2/T3) from
the call's variables and sends it automatically. The manual **Send** button stays.

---

## 1. Decisions so far

| # | Question | Decision |
|---|---|---|
| 1 | T1 condition | T1 = today's `hyundai_agentic_temp` (appointment + brochure). Sent when the appointment details are captured, **regardless of `call_status`**, so a `DROP_OFF` call that captured an appointment still gets T1 |
| 2 | Appointment *and* callback on the same call | Not a case to handle specially: if appointment details are present, T1 is sent |
| 3 | T3's "main variables" | Exactly the variable params of T1 (listed in section 2) |
| 4 | Very short / barely connected calls | Get T3 like any other call with nothing captured |
| 5 | T2 / T3 templates | T2 = `hyundai_agentic_callback`, T3 = `hyundai_agentic_sorry_followup`: both MARKETING, English, text-only with **no variables** and a static call button. Curls get pasted in the Settings UI, not committed or shared in chat |
| 6 | API key | Stays inside each pasted curl for now |
| 7 | Delay | None, sent as soon as the call is processed |
| 8 | Safeguards | All proposed ones **except** per-number cooldown and dry-run mode |
| 9 | Outbound / other agents | No. Hyundai inbound POC only |
| 10 | Per-model brochure | No. Only T1 has a PDF, and it keeps sending its fixed `link` |
| 11 | Business hours | Not applied in the POC; messages go out at any hour |
| 12 | Partial captures | Get **T1**, with each empty param filled with `"unspecified"` (a T4 for partial captures may come later) |
| 13 | Scheduler | `run_scheduler` runs continuously alongside `runserver` |

---

## 2. Templates and when they fire

T1's variable params, which are also T3's "main variables":
`customer_name`, `model_name`, `appointment_place`, `appointment_date`, `appointment_time`.
`link` is a fixed value, not a variable.

Rules are checked **in this order and the first match wins**, so each call gets **at most one**
automatic template:

| Order | Template | Sent when | Status |
|---|---|---|---|
| 1 | **T1** Appointment confirmation + brochure | `appointment_date`, `appointment_time` and `appointment_place` are all non-empty | Ready (curl exists) |
| 2 | **T2** Callback (`hyundai_agentic_callback`) | `callback_status` is `"required"` (case-insensitive) | Ready once its curl is pasted |
| 3 | **T1, partial** | At least one main variable captured, but not a full appointment and not a callback. Empty params are sent as `"unspecified"` | Ready |
| 4 | **T3** Sorry follow-up (`hyundai_agentic_sorry_followup`) | **All five** main variables are empty | Ready once its curl is pasted |

Every completed, non-test call now matches exactly one row, so there's no "no message" case.

Partial T1 is checked *after* T2 on purpose. A caller who gave only a name or model and said
"I'll call back" gets the callback message, not an appointment confirmation full of
"unspecified". A **full** appointment still wins over a callback (decision 2).

"Empty" means missing, `null`, an empty string, or whitespace only.

For the POC these conditions live **in code** (`services/hyundai_whatsapp.py`), not in a
configurable rule editor. When T2's variable is known, it's a small code change there.

---

## 3. How different templates are sent when each has its own curl

Each template has **its own pasted curl**, stored separately: T1, T2 and T3 each get one curl
box in Settings → Omnichannel (section 6). The rule only decides *which* template. The curl
decides *what* is sent.

When a call completes:

1. `hyundai_whatsapp.pick_template(execution)` runs the three checks in section 2 against the
   call's variables and returns `"T1"`, `"T2"`, `"T3"` or nothing.
2. A send record is created for that call and template (section 4).
3. The send runs the existing `whatsapp.build_request()` on **that template's curl**. For
   T2/T3 there are no variable params, so only `receiver_number` changes:
   - The URL, the `Authorization: Api-Key …` header and the body are taken from that curl as-is.
     So each template brings its own `template_title`, `template_code`, `client_number` and
     fixed values (T1's PDF `link`).
   - `receiver_number` is overwritten with the caller's number.
   - Each `param_data` value that names a variable (`"customer_name":"customer_name"`) is
     replaced with the call's value, and fixed values are sent unchanged.

The only change to `whatsapp.py` is that it takes the curl to use as an argument, instead of
always reading `OmnichannelConfig.whatsapp_curl`.

---

## 4. Data model (one migration)

**`OmnichannelConfig`** gains:
- `auto_send` bool, default `False`. Automation runs only for an agent with this switched on,
  so in practice just the Hyundai inbound agent.
- `whatsapp_curls` JSON: `{"T1": "<curl>", "T2": "<curl>", "T3": "<curl>"}`. The migration
  copies today's `whatsapp_curl` into `"T1"`. The old field is kept until the UI no longer reads
  it.

**`WhatsAppSend`**, one row per automatic send attempt-chain:
- `execution` FK, `template_key` (`T1`/`T2`/`T3`), `trigger` (`auto` / `manual`)
- `status`: `pending` | `sent` | `failed` | `skipped`
- `attempts`, `next_attempt_at`, `last_error`, `sent_at`
- **Unique constraint on `execution` for `trigger="auto"`**, so one automatic message per call
  no matter how often Chat360 resends the webhook.

Manual sends keep logging `whatsapp_sent` / `whatsapp_failed` `ExecutionEvent`s as today, and
every automatic attempt logs the same events, so the Calls tab history stays in one place.

---

## 5. Flow

```
Chat360 post-call webhook
   └─ webhook_intake → inbound.record_inbound_call
        └─ outcome_routing.record_completion          (QA, CRM Update — unchanged)
             └─ hyundai_whatsapp.on_call_completed     NEW: if auto_send is on,
                  pick_template → create WhatsAppSend(pending, next_attempt_at=now)

run_scheduler tick
   ├─ existing: dispatch due outbound calls
   └─ NEW: send pending WhatsAppSends whose next_attempt_at <= now
             → whatsapp.send_whatsapp(execution, curl=whatsapp_curls[template_key])
             → sent / failed / retry later
```

**"Immediately" in practice means the next scheduler tick.** The webhook handler only writes a
row. It doesn't call Chat360 itself, because a send takes about 4 s and retries need somewhere to
live. With `run_scheduler --interval 10` the message leaves at most about 10 s after the webhook
arrives. That's small next to the minutes WhatsApp itself took in the Phase 1 test.
`run_scheduler` runs continuously alongside `runserver` (decision 13).

---

## 6. Safeguards

Included:

- **One automatic template per call** (first matching rule + the unique constraint), so a
  duplicate webhook delivery never sends twice.
- **Skip test calls:** `is_test` truthy (`"True"`, `"true"`, `true`, `"1"`) → `skipped`. Chat360
  sends this as the *string* `"False"`/`"True"`.
- **Missing values:** for **T1**, an empty variable param is filled with `"unspecified"` (the
  partial-capture rule), for automatic and manual sends alike. For any other template, the
  existing rule still applies: an empty placeholder blocks the send. T2 and T3 have no
  placeholders, so this never triggers for them. A missing **receiver number** always blocks.
- **Retries only for transient failures:** network errors and 5xx are retried up to 3 times
  (+2 min, +10 min, +30 min). A 4xx or missing values means the request itself is wrong, so it
  fails immediately with no retry.
- **Off by default:** nothing is sent automatically until `auto_send` is switched on for the
  agent.

Excluded by decision:

- **Per-number cooldown.** A repeat caller gets a message per call. WhatsApp's own
  marketing-template frequency limit (error **131049**) may silently drop some of these on
  Meta's side. Chat360 still answers "sent", so telehub can't see it.
- **Dry-run mode.**
- **Business-hours gating.** Messages go out at any hour.

---

## 7. UI

**Settings → Omnichannel**, Hyundai POC section:
- **Auto-send WhatsApp** toggle.
- Three curl boxes: **T1 – Appointment confirmation**, **T2 – Callback**, **T3 – Fallback**.
  Each shows what was extracted from it (URL, `template_title`, params found). An empty box means
  that template is never sent automatically; the call's row shows `skipped (T2 not configured)`.
- A read-only note describing when each template fires (section 2). The conditions themselves
  aren't editable in the POC.

**Calls tab**, WhatsApp column:
- `Sent · T1`, `Failed · T3 (reason)`, `Pending · T2`, `Skipped (test call)`
- The manual **Send** button gets a T1/T2/T3 picker, defaulting to the template the rules
  would pick. It still works after an automatic send, since it's an explicit human action.

---

## 8. Build order

1. Migration: `auto_send`, `whatsapp_curls` (copy the existing curl into T1), `WhatsAppSend`.
   `whatsapp.build_request` / `send_whatsapp` take a curl argument.
2. `services/hyundai_whatsapp.py`: `pick_template` (T1 / T3 now, with T2 as a stub that never
   matches until its variable is known) and `on_call_completed`, called from `record_completion`.
3. Scheduler step: send pending rows, with retries.
4. API + Settings → Omnichannel UI (toggle, three curls), then the Calls tab column and the manual
   template picker.
5. Switch `auto_send` on for the Hyundai inbound agent, place test calls covering T1 and T3
   (and T2 once ready), and check the Calls tab and the phones.

T1 is usable end to end after step 3, with the toggle set in Django admin. T2 and T3 start working
as soon as their curls are pasted in, and T2 also needs its condition filled in.

---

## Open questions

1. **Fill text.** `"unspecified"` vs `"did not mention"`: it appears in the customer's message
   (e.g. "your appointment at unspecified on unspecified"). The plan uses `"unspecified"`, set as
   one constant so it's easy to change.

Resolved since the last draft: partial captures (→ T1 with fill text), T3 placeholders (T3 has
none), keeping the scheduler running (yes), partial appointments (→ partial T1), T2 condition (`callback_status == "required"`).
