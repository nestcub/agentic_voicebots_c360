"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, ArrowRight, Check, Pencil, Plus, Sparkles, Workflow } from "lucide-react";
import { Card, CardHeader } from "@/components/Card";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { PageHeader } from "@/components/common/PageHeader";
import { ErrorAlert } from "@/components/common/ErrorAlert";
// listIntegrations/Integration are unused while the Integrations step is disabled — see STEPS above.
import { listChannels, listVoiceBots, createProcessAgent } from "@/lib/telehubApi";
import type {
  Channel,
  // Integration,
  ProcessAgentWizardPayload,
  ProcessAgentWizardVariable,
  VoiceBot,
} from "@/lib/types";

// ── Constants ────────────────────────────────────────────────────────────

// Business Rules and Integrations are out of the wizard — their blocks below
// stay commented out until the later cleanup. Retry / business hours / callback
// are set in the agent's Settings tab. Variables are not asked for here at all:
// they are discovered from the first webhook payloads, then ticked for QA /
// analytics (schema_revamp_phase1_simple_flow.md §4.1).
type StepKey = "basic" | "voicebot" | "lead_source" | "whatsapp" | "review";

const STEP_META: Record<StepKey, { label: string; hint: string }> = {
  basic: { label: "Basics", hint: "Name the agent and place it under a channel." },
  voicebot: { label: "Voicebot", hint: "Pick the bot this agent runs on, and the number it uses." },
  lead_source: { label: "Lead Source", hint: "Where leads for this agent's outbound calls come from." },
  whatsapp: { label: "WhatsApp", hint: "Optionally send a WhatsApp message after each call." },
  review: { label: "Review", hint: "Confirm everything below, then create the agent." },
};

// The Lead Source step only applies to bots that dial out.
function stepsFor(bot: VoiceBot | undefined): StepKey[] {
  const inbound = bot?.communication_type === "voice_inbound";
  return inbound
    ? ["basic", "voicebot", "whatsapp", "review"]
    : ["basic", "voicebot", "lead_source", "whatsapp", "review"];
}

const COMMUNICATION_TYPES = [
  { value: "voice_outbound", label: "Voice Outbound" },
  { value: "voice_inbound", label: "Voice Inbound" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "sms", label: "SMS" },
  { value: "email", label: "Email" },
];

const LEAD_SOURCE_TYPES = [
  { value: "webhook", label: "Webhook" },
  { value: "crm", label: "CRM" },
  { value: "google_sheet", label: "Google Sheet" },
  { value: "rest_api", label: "REST API" },
  { value: "csv", label: "CSV" },
  { value: "single_source", label: "Single Source" },
];

// Unused while the Business Rules step is disabled — see STEPS above.
// const RETRY_STRATEGIES = [
//   { value: "linear", label: "Linear" },
//   { value: "exponential", label: "Exponential" },
// ];

// const CALLBACK_OPERATORS = ["==", "!=", ">", "<", "contains"];

const QA_FIELDS: { key: string; label: string; hint: string }[] = [
  {
    key: "missing_variables",
    label: "Missing Variables",
    hint: "Flag executions where expected variables weren't captured — shown on the channel detail page.",
  },
  {
    key: "incorrect_variables",
    label: "Incorrect Variables",
    hint: "Flag executions where captured variables don't match the expected format or values.",
  },
  {
    key: "end_call_misfiring",
    label: "End Call Misfiring",
    hint: "Detect premature or incorrect call terminations. Requires LLM credits.",
  },
  {
    key: "drop_off_analysis",
    label: "Drop-off Analysis",
    hint: "Analyze where callers disengage during the conversation. Requires LLM credits.",
  },
];

// Campaign-level stat tiles surfaced on the dashboard, computed from execution
// data already in the DB (call attempts, pickups, durations, cost…) — this
// just toggles which ones this process shows.
const STAT_FIELDS: { key: string; label: string }[] = [
  { key: "initiated_calls", label: "Initiated Calls" },
  { key: "total_call_attempts", label: "Total Call Attempts" },
  { key: "picked_up_count", label: "Picked Up Count" },
  { key: "first_response_count", label: "First Response Count" },
  { key: "unanswered_calls", label: "Unanswered Calls" },
  { key: "drop_off_count", label: "Drop Off Count" },
  { key: "completed_calls", label: "Completed Calls" },
  { key: "failed_calls", label: "Failed Calls" },
  { key: "voicemail", label: "Voicemail" },
  { key: "not_connected_calls", label: "Not Connected Calls" },
  { key: "picked_up_call_rate", label: "Picked Up Call Rate (%)" },
  { key: "average_call_duration", label: "Average Call Duration" },
  { key: "completion_rate", label: "Completion Rate" },
  { key: "total_cost_of_campaign", label: "Total Cost of Campaign" },
];

// ── Small typed accessors for the loosely-typed Record<string, unknown> sections ──

function getStr(obj: Record<string, unknown> | undefined, key: string): string {
  const v = obj?.[key];
  if (typeof v === "string") return v;
  if (typeof v === "number") return String(v);
  return "";
}

function getNum(obj: Record<string, unknown> | undefined, key: string): number | "" {
  const v = obj?.[key];
  return typeof v === "number" ? v : "";
}

function getBool(obj: Record<string, unknown> | undefined, key: string): boolean {
  return obj?.[key] === true;
}

function toNumOrUndefined(raw: string): number | undefined {
  if (raw.trim() === "") return undefined;
  const n = Number(raw);
  return Number.isNaN(n) ? undefined : n;
}

// ── Step indicator ──────────────────────────────────────────────────────

function StepIndicator({ steps, current, onJump }: { steps: StepKey[]; current: number; onJump: (idx: number) => void }) {
  return (
    <div className="flex items-center gap-0 mb-6 overflow-x-auto pb-1">
      {steps.map((key, idx) => {
        const label = STEP_META[key].label;
        const isCompleted = idx < current;
        const isCurrent = idx === current;
        const isLast = idx === steps.length - 1;
        const canJump = idx <= current;

        return (
          <div key={label} className="flex items-center flex-1 last:flex-none min-w-[84px]">
            <button
              type="button"
              onClick={() => canJump && onJump(idx)}
              disabled={!canJump}
              className="flex flex-col items-center gap-1.5 disabled:cursor-not-allowed"
            >
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold transition-colors ${
                  isCompleted
                    ? "bg-primary text-primary-foreground"
                    : isCurrent
                    ? "bg-primary text-primary-foreground ring-4 ring-primary/20"
                    : "bg-card border border-border text-muted-foreground"
                }`}
              >
                {isCompleted ? (
                  <Check className="w-4 h-4" strokeWidth={2.5} />
                ) : (
                  idx + 1
                )}
              </div>
              <span
                className={`text-xs font-medium whitespace-nowrap ${
                  isCurrent ? "text-primary" : isCompleted ? "text-foreground" : "text-muted-foreground"
                }`}
              >
                {label}
              </span>
            </button>
            {!isLast && (
              <div className={`flex-1 h-0.5 mx-2 mb-5 transition-colors ${isCompleted ? "bg-primary" : "bg-border"}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Repeatable key/value variable rows (Business Rules variables + Analytics custom_variables) ──

function VariableRowsEditor({
  rows,
  onChange,
  simple = false,
}: {
  rows: ProcessAgentWizardVariable[];
  onChange: (rows: ProcessAgentWizardVariable[]) => void;
  simple?: boolean;
}) {
  function updateRow(idx: number, patch: Partial<ProcessAgentWizardVariable>) {
    onChange(rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  }
  function removeRow(idx: number) {
    onChange(rows.filter((_, i) => i !== idx));
  }
  function addRow() {
    onChange([...rows, { key: "", type: "string", default_value: "", required: false }]);
  }

  return (
    <div className="space-y-2">
      {rows.map((row, idx) => (
        <div key={idx} className="flex flex-wrap items-center gap-2 p-3 rounded-lg border border-border bg-muted/50">
          <input
            type="text"
            value={row.key}
            onChange={(e) => updateRow(idx, { key: e.target.value })}
            placeholder="key"
            className="flex-1 min-w-[100px] px-2.5 py-1.5 rounded-md border border-border bg-surface text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary"
          />
          {simple ? (
            <input
              type="text"
              value={row.default_value ?? ""}
              onChange={(e) => updateRow(idx, { default_value: e.target.value })}
              placeholder="label"
              className="flex-1 min-w-[100px] px-2.5 py-1.5 rounded-md border border-border bg-surface text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary"
            />
          ) : (
            <>
              <input
                type="text"
                value={row.type ?? ""}
                onChange={(e) => updateRow(idx, { type: e.target.value })}
                placeholder="type (string, number…)"
                className="flex-1 min-w-[110px] px-2.5 py-1.5 rounded-md border border-border bg-surface text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary"
              />
              <input
                type="text"
                value={row.default_value ?? ""}
                onChange={(e) => updateRow(idx, { default_value: e.target.value })}
                placeholder="default value"
                className="flex-1 min-w-[110px] px-2.5 py-1.5 rounded-md border border-border bg-surface text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary"
              />
              <label className="flex items-center gap-1.5 text-xs text-text-muted whitespace-nowrap">
                <input
                  type="checkbox"
                  checked={row.required ?? false}
                  onChange={(e) => updateRow(idx, { required: e.target.checked })}
                  className="accent-primary"
                />
                Required
              </label>
            </>
          )}
          <button
            type="button"
            onClick={() => removeRow(idx)}
            className="text-xs text-bad hover:underline whitespace-nowrap"
          >
            Remove
          </button>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" onClick={addRow}>
        <Plus /> Add variable
      </Button>
    </div>
  );
}

// ── Repeatable callback condition rows (variable/operator/value — any of them can fire the callback) ──
// Unused while the Business Rules step is disabled — see STEPS above.

// interface CallbackCondition {
//   variable: string;
//   operator: string;
//   value: string;
// }
//
// function getCallbackConditions(callback: Record<string, unknown> | undefined): CallbackCondition[] {
//   const raw = callback?.conditions;
//   if (!Array.isArray(raw)) return [];
//   return raw.filter((r): r is CallbackCondition => typeof r === "object" && r !== null);
// }
//
// function CallbackConditionRows({
//   rows,
//   onChange,
// }: {
//   rows: CallbackCondition[];
//   onChange: (rows: CallbackCondition[]) => void;
// }) {
//   function updateRow(idx: number, patch: Partial<CallbackCondition>) {
//     onChange(rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
//   }
//   function removeRow(idx: number) {
//     onChange(rows.filter((_, i) => i !== idx));
//   }
//   function addRow() {
//     onChange([...rows, { variable: "", operator: "==", value: "" }]);
//   }
//
//   return (
//     <div className="space-y-2">
//       {rows.map((row, idx) => (
//         <div key={idx} className="flex flex-wrap items-center gap-2 p-3 rounded-lg border border-border bg-muted/50">
//           <input
//             type="text"
//             value={row.variable}
//             onChange={(e) => updateRow(idx, { variable: e.target.value })}
//             placeholder="variable (e.g. call_back)"
//             className="flex-1 min-w-[110px] px-2.5 py-1.5 rounded-md border border-border bg-surface text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary"
//           />
//           <select
//             value={row.operator}
//             onChange={(e) => updateRow(idx, { operator: e.target.value })}
//             className="px-2.5 py-1.5 rounded-md border border-border bg-surface text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary"
//           >
//             {CALLBACK_OPERATORS.map((op) => (
//               <option key={op} value={op}>
//                 {op}
//               </option>
//             ))}
//           </select>
//           <input
//             type="text"
//             value={row.value}
//             onChange={(e) => updateRow(idx, { value: e.target.value })}
//             placeholder="value (e.g. true)"
//             className="flex-1 min-w-[110px] px-2.5 py-1.5 rounded-md border border-border bg-surface text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary"
//           />
//           <button
//             type="button"
//             onClick={() => removeRow(idx)}
//             className="text-xs text-bad hover:underline whitespace-nowrap"
//           >
//             Remove
//           </button>
//         </div>
//       ))}
//       <button
//         type="button"
//         onClick={addRow}
//         className="px-3 py-1.5 rounded-lg border border-border text-xs font-medium text-on-surface hover:bg-muted/50 transition-colors"
//       >
//         + Add condition
//       </button>
//     </div>
//   );
// }

// ── curl placeholder detection ───────────────────────────────────────────
// Light client-side look at a pasted WhatsApp template curl: the keys of its
// template_data.param_data, so the user sees what it will fill in. The server
// (services/whatsapp.py parse_curl) is the real parser and re-parses on save;
// mapping those keys to variables happens in Settings once variables exist.

function collectParamKeys(node: unknown, out: string[]): void {
  if (!node || typeof node !== "object") return;
  for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
    if (key === "param_data" && value && typeof value === "object" && !Array.isArray(value)) {
      out.push(...Object.keys(value as Record<string, unknown>));
    } else {
      collectParamKeys(value, out);
    }
  }
}

function detectCurlParams(curl: string): { params: string[]; error?: string } {
  const text = curl.replace(/\\\r?\n/g, " ").replace(/\^\r?\n/g, " ");
  if (!/^\s*curl\b/i.test(text)) return { params: [], error: "This doesn't look like a curl command." };
  const match = text.match(/(?:--data-raw|--data-binary|--data|-d)\s+(?:\$?'([\s\S]*?)'|"((?:[^"\\]|\\.)*)")/);
  if (!match) return { params: [], error: "No JSON body (-d / --data-raw) found in the curl." };
  const raw = match[1] ?? (match[2] ?? "").replace(/\\"/g, '"');
  try {
    const params: string[] = [];
    collectParamKeys(JSON.parse(raw), params);
    return { params: Array.from(new Set(params)) };
  } catch {
    return { params: [], error: "The curl's body isn't valid JSON." };
  }
}

// ── Field wrapper ────────────────────────────────────────────────────────

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </label>
  );
}

// Matches components/ui/input; kept as a class string because the selects and
// textareas here share it.
const inputCls =
  "min-w-0 px-3 py-2 rounded-md border border-input bg-card text-sm text-foreground shadow-xs outline-none transition-[color,box-shadow] placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50";

// ── Page (Suspense boundary for useSearchParams) ────────────────────────

export default function NewProcessAgentPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-text-muted">Loading…</div>}>
      <NewProcessAgentWizard />
    </Suspense>
  );
}

function NewProcessAgentWizard() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const channelParam = searchParams.get("channel");

  const [stepIdx, setStepIdx] = useState(0);
  const [whatsappEnabled, setWhatsappEnabled] = useState(false);
  const [payload, setPayload] = useState<ProcessAgentWizardPayload>(() => ({
    channelId: channelParam ? Number(channelParam) : 0,
    name: "",
    description: "",
  }));

  const [channels, setChannels] = useState<Channel[]>([]);
  const [channelsLoading, setChannelsLoading] = useState(true);
  const [channelsError, setChannelsError] = useState<string | null>(null);

  const [voiceBots, setVoiceBots] = useState<VoiceBot[]>([]);
  const [voiceBotsLoading, setVoiceBotsLoading] = useState(true);
  const [voiceBotsError, setVoiceBotsError] = useState<string | null>(null);

  // Integrations state is unused while the Integrations step is disabled — see STEPS above.
  // const [integrations, setIntegrations] = useState<Integration[]>([]);
  // const [integrationsLoading, setIntegrationsLoading] = useState(true);
  // const [integrationsError, setIntegrationsError] = useState<string | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    listChannels()
      .then((data) => setChannels(data))
      .catch((e) => setChannelsError(e instanceof Error ? e.message : "Failed to load channels"))
      .finally(() => setChannelsLoading(false));
  }, []);

  useEffect(() => {
    listVoiceBots()
      .then((data) => setVoiceBots(data))
      .catch((e) => setVoiceBotsError(e instanceof Error ? e.message : "Failed to load bots"))
      .finally(() => setVoiceBotsLoading(false));
  }, []);

  // useEffect(() => {
  //   listIntegrations()
  //     .then((data) => setIntegrations(data))
  //     .catch((e) => setIntegrationsError(e instanceof Error ? e.message : "Failed to load integrations"))
  //     .finally(() => setIntegrationsLoading(false));
  // }, []);

  // ── Update helpers ──

  // Changing the bot drops the number choice — numbers belong to one bot.
  function setVoiceBotId(voiceBotId: number | undefined) {
    setPayload((p) => ({ ...p, voice: { voice_bot_id: voiceBotId } }));
  }
  // A stage uses at most one of its bot's numbers; none = automatic.
  function setNumberId(numberId: number | undefined) {
    setPayload((p) => ({ ...p, voice: { ...p.voice, numbers: numberId ? [numberId] : undefined } }));
  }
  function updateLeadSource(patch: ProcessAgentWizardPayload["lead_source"]) {
    setPayload((p) => ({ ...p, lead_source: { ...p.lead_source, ...patch } }));
  }
  // Business Rules / Integrations update helpers are unused while those steps are
  // disabled — see STEPS above.
  // function updateRetry(patch: Record<string, unknown>) {
  //   setPayload((p) => ({
  //     ...p,
  //     business_rules: { ...p.business_rules, retry: { ...(p.business_rules?.retry ?? {}), ...patch } },
  //   }));
  // }
  // function updateBusinessHours(patch: Record<string, unknown>) {
  //   setPayload((p) => ({
  //     ...p,
  //     business_rules: {
  //       ...p.business_rules,
  //       business_hours: { ...(p.business_rules?.business_hours ?? {}), ...patch },
  //     },
  //   }));
  // }
  // function updateCallback(patch: Record<string, unknown>) {
  //   setPayload((p) => ({
  //     ...p,
  //     business_rules: { ...p.business_rules, callback: { ...(p.business_rules?.callback ?? {}), ...patch } },
  //   }));
  // }
  // function setCallbackConditions(rows: CallbackCondition[]) {
  //   updateCallback({ conditions: rows });
  // }
  // function updateDnd(patch: Record<string, unknown>) {
  //   setPayload((p) => ({
  //     ...p,
  //     business_rules: { ...p.business_rules, dnd: { ...(p.business_rules?.dnd ?? {}), ...patch } },
  //   }));
  // }
  // function setBusinessVariables(rows: ProcessAgentWizardVariable[]) {
  //   setPayload((p) => ({ ...p, business_rules: { ...p.business_rules, variables: rows } }));
  // }
  // function toggleIntegration(id: number) {
  //   setPayload((p) => {
  //     const current = p.integrations ?? [];
  //     const next = current.includes(id) ? current.filter((x) => x !== id) : [...current, id];
  //     return { ...p, integrations: next };
  //   });
  // }
  function toggleQa(key: string) {
    setPayload((p) => ({ ...p, qa: { ...p.qa, [key]: !getBool(p.qa, key) } }));
  }
  function setWhatsappCurl(curl: string) {
    setPayload((p) => ({ ...p, omnichannel: { channel: "whatsapp", whatsapp_curl: curl } }));
  }

  // ── Steps (the Lead Source step drops out for inbound bots) ──

  const selectedVoiceBot = voiceBots.find((b) => b.id === payload.voice?.voice_bot_id);
  const steps = stepsFor(selectedVoiceBot);
  const step: StepKey = steps[Math.min(stepIdx, steps.length - 1)];
  const lastIdx = steps.length - 1;
  const isInbound = selectedVoiceBot?.communication_type === "voice_inbound";

  const curlCheck = whatsappEnabled ? detectCurlParams(payload.omnichannel?.whatsapp_curl ?? "") : null;
  const curlBlank = whatsappEnabled && !(payload.omnichannel?.whatsapp_curl ?? "").trim();

  // Only Basics requires fields; a WhatsApp curl, once switched on, must be usable.
  const canProceed =
    step === "basic"
      ? payload.channelId > 0 && payload.name.trim() !== ""
      : step === "whatsapp"
      ? !curlBlank && !curlCheck?.error
      : true;

  const jumpTo = (key: StepKey) => setStepIdx(steps.indexOf(key));
  function goNext() {
    if (!canProceed) return;
    setStepIdx((i) => Math.min(i + 1, lastIdx));
  }
  function goBack() {
    setStepIdx((i) => Math.max(i - 1, 0));
  }

  // ── Submission ──

  function buildFinalPayload(): ProcessAgentWizardPayload {
    const qaOn = QA_FIELDS.some((f) => getBool(payload.qa, f.key));
    const curl = (payload.omnichannel?.whatsapp_curl ?? "").trim();
    // Variables are discovered from webhooks, not declared here. Stat tiles
    // default to all on — they are managed from Settings afterwards.
    return {
      channelId: payload.channelId,
      name: payload.name.trim(),
      description: payload.description?.trim() || undefined,
      voice: payload.voice?.voice_bot_id ? payload.voice : undefined,
      // Inbound bots have no lead source; an untouched/blank one is not sent.
      lead_source: !isInbound && payload.lead_source?.type ? payload.lead_source : undefined,
      qa: qaOn ? payload.qa : undefined,
      analytics: { stats: Object.fromEntries(STAT_FIELDS.map((f) => [f.key, true])) },
      omnichannel: whatsappEnabled && curl ? { channel: "whatsapp", whatsapp_curl: curl } : undefined,
    };
  }

  async function handleGenerate() {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const result = await createProcessAgent(buildFinalPayload());
      router.push(`/process-agents/${result.id}`);
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : "Failed to generate process agent.");
      setSubmitting(false);
    }
  }

  const selectedChannel = channels.find((d) => d.id === payload.channelId);
  const selectedNumber = selectedVoiceBot?.numbers.find((n) => n.id === payload.voice?.numbers?.[0]);
  // const selectedIntegrations = integrations.filter((i) => (payload.integrations ?? []).includes(i.id));

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <PageHeader
        breadcrumbs={[
          { label: "Channels", href: "/channels" },
          ...(selectedChannel ? [{ label: selectedChannel.name, href: `/channels/${selectedChannel.id}` }] : []),
          { label: "New Agent" },
        ]}
        icon={Workflow}
        title="New Agent"
        description={STEP_META[step].hint}
      />

      <StepIndicator steps={steps} current={stepIdx} onJump={setStepIdx} />

      <Card className="p-6">
        {/* ── Basics ── */}
        {step === "basic" && (
          <div className="space-y-4">
            <CardHeader title="Basic" hint="Every process agent belongs to a channel." />
            <Field label="Channel *">
              {channelsError ? (
                <p className="text-sm text-bad">{channelsError}</p>
              ) : (
                <select
                  value={payload.channelId || ""}
                  onChange={(e) => setPayload((p) => ({ ...p, channelId: Number(e.target.value) }))}
                  disabled={channelsLoading}
                  className={inputCls}
                >
                  <option value="">{channelsLoading ? "Loading…" : "— select a channel —"}</option>
                  {channels.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field label="Process Name *">
              <input
                type="text"
                value={payload.name}
                onChange={(e) => setPayload((p) => ({ ...p, name: e.target.value }))}
                placeholder="e.g. Service Reminder Outbound"
                className={inputCls}
              />
            </Field>
            <Field label="Description">
              <textarea
                value={payload.description ?? ""}
                onChange={(e) => setPayload((p) => ({ ...p, description: e.target.value }))}
                rows={3}
                placeholder="What does this process do?"
                className={inputCls}
              />
            </Field>
          </div>
        )}

        {/* ── Voicebot ── */}
        {step === "voicebot" && (
          <div className="space-y-4">
            <CardHeader title="Voicebot" hint="The bot this agent's calls run on, and which of its numbers." />
            <Field label="Bot *">
              {voiceBotsError ? (
                <p className="text-sm text-bad">{voiceBotsError}</p>
              ) : (
                <select
                  value={payload.voice?.voice_bot_id ?? ""}
                  onChange={(e) => setVoiceBotId(e.target.value ? Number(e.target.value) : undefined)}
                  disabled={voiceBotsLoading}
                  className={inputCls}
                >
                  <option value="">{voiceBotsLoading ? "Loading…" : "— select a bot —"}</option>
                  {voiceBots.map((bot) => (
                    <option key={bot.id} value={bot.id}>
                      {bot.label || bot.bot_name || `Voice Bot ${bot.id}`}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            {!voiceBotsLoading && voiceBots.length === 0 && (
              <p className="text-xs text-text-muted">
                No bots yet —{" "}
                <Link href="/bots" className="text-primary hover:underline">
                  create one on the Bots page
                </Link>{" "}
                first.
              </p>
            )}
            {selectedVoiceBot && (
              <>
                <div className="rounded-lg border border-border bg-muted/50 p-3 space-y-0.5 text-xs text-text-muted">
                  <p className="font-medium text-foreground">
                    {COMMUNICATION_TYPES.find((c) => c.value === selectedVoiceBot.communication_type)?.label ??
                      (selectedVoiceBot.communication_type || "Unknown direction")}
                  </p>
                  <p>
                    {selectedVoiceBot.bot_name || "—"}
                    {selectedVoiceBot.bot_id && <span className="ml-1">({selectedVoiceBot.bot_id})</span>}
                  </p>
                  {!isInbound && selectedVoiceBot.api_url && (
                    <p className="font-mono break-all">{selectedVoiceBot.api_url}</p>
                  )}
                </div>

                <Field
                  label="Number"
                  hint={
                    isInbound
                      ? "Inbound calls must have dialed this number; others are still recorded but flagged."
                      : "The caller ID this agent dials from."
                  }
                >
                  <select
                    value={payload.voice?.numbers?.[0] ?? ""}
                    onChange={(e) => setNumberId(e.target.value ? Number(e.target.value) : undefined)}
                    disabled={selectedVoiceBot.numbers.length === 0}
                    className={inputCls}
                  >
                    <option value="">
                      {selectedVoiceBot.numbers.length === 0
                        ? "This bot has no numbers yet"
                        : isInbound
                        ? "Automatic — any of the bot's numbers"
                        : "Automatic — the bot's first number"}
                    </option>
                    {selectedVoiceBot.numbers.map((n) => (
                      <option key={n.id} value={n.id}>
                        {n.did}
                      </option>
                    ))}
                  </select>
                </Field>

                {isInbound && (
                  <p className="text-xs text-text-muted">
                    Inbound results arrive by webhook. This agent gets its own webhook URL once created — paste it
                    into Chat360 for this bot.
                  </p>
                )}
              </>
            )}
          </div>
        )}

        {/* ── Lead Source (outbound bots only) ── */}
        {step === "lead_source" && (
          <div className="space-y-4">
            <CardHeader title="Lead Source" hint="Where leads enter this process." />
            <Field label="Type">
              <select
                value={payload.lead_source?.type ?? ""}
                onChange={(e) => updateLeadSource({ type: e.target.value })}
                className={inputCls}
              >
                <option value="">— select —</option>
                {LEAD_SOURCE_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </Field>
            {payload.lead_source?.type === "single_source" ? (
              <Field label="Number" hint="The single phone number this process should call.">
                <input
                  type="tel"
                  value={getStr(payload.lead_source?.configuration, "number")}
                  onChange={(e) =>
                    updateLeadSource({
                      configuration: { ...(payload.lead_source?.configuration ?? {}), number: e.target.value },
                    })
                  }
                  placeholder="+91XXXXXXXXXX"
                  className={inputCls}
                />
              </Field>
            ) : (
              <Field label="Configuration notes" hint="Freeform notes for this source (endpoint, sheet ID, credentials reference…). Optional.">
                <textarea
                  value={getStr(payload.lead_source?.configuration, "notes")}
                  onChange={(e) =>
                    updateLeadSource({ configuration: { ...(payload.lead_source?.configuration ?? {}), notes: e.target.value } })
                  }
                  rows={3}
                  className={inputCls}
                />
              </Field>
            )}
          </div>
        )}

        {/* ── Business Rules and Integrations steps are disabled — see STEPS above. ──
        {step === "business_rules_disabled" && (
          <div className="space-y-6">
            <CardHeader title="Business Rules" hint="Retry, business hours, callback, DND and process variables." />

            <div>
              <p className="text-sm font-semibold text-on-surface mb-2">Retry</p>
              <div className="grid sm:grid-cols-3 gap-3">
                <Field label="Attempts">
                  <input
                    type="number"
                    value={getNum(payload.business_rules?.retry, "attempts")}
                    onChange={(e) => updateRetry({ attempts: toNumOrUndefined(e.target.value) })}
                    className={inputCls}
                  />
                </Field>
                <Field label="Interval (minutes)">
                  <input
                    type="number"
                    value={getNum(payload.business_rules?.retry, "interval_minutes")}
                    onChange={(e) => updateRetry({ interval_minutes: toNumOrUndefined(e.target.value) })}
                    className={inputCls}
                  />
                </Field>
                <Field label="Strategy">
                  <select
                    value={getStr(payload.business_rules?.retry, "strategy")}
                    onChange={(e) => updateRetry({ strategy: e.target.value })}
                    className={inputCls}
                  >
                    <option value="">— select —</option>
                    {RETRY_STRATEGIES.map((s) => (
                      <option key={s.value} value={s.value}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
            </div>

            <div>
              <p className="text-sm font-semibold text-on-surface mb-2">Business Hours</p>
              <div className="grid sm:grid-cols-3 gap-3">
                <Field label="Timezone">
                  <input
                    type="text"
                    value={payload.business_rules?.business_hours ? getStr(payload.business_rules.business_hours, "timezone") || "Asia/Kolkata" : "Asia/Kolkata"}
                    onChange={(e) => updateBusinessHours({ timezone: e.target.value })}
                    className={inputCls}
                  />
                </Field>
                <Field label="Start">
                  <input
                    type="time"
                    value={getStr(payload.business_rules?.business_hours, "start")}
                    onChange={(e) => updateBusinessHours({ start: e.target.value })}
                    className={inputCls}
                  />
                </Field>
                <Field label="End">
                  <input
                    type="time"
                    value={getStr(payload.business_rules?.business_hours, "end")}
                    onChange={(e) => updateBusinessHours({ end: e.target.value })}
                    className={inputCls}
                  />
                </Field>
              </div>
            </div>

            <div>
              <p className="text-sm font-semibold text-on-surface mb-2">
                Callback <span className="font-normal text-text-muted">— any condition below triggers a callback</span>
              </p>
              <CallbackConditionRows
                rows={getCallbackConditions(payload.business_rules?.callback)}
                onChange={setCallbackConditions}
              />
              <div className="grid sm:grid-cols-3 gap-3 mt-3">
                <Field label="Delay (minutes)" hint="Used when the callback time isn't resolved from a variable (e.g. call_back_time).">
                  <input
                    type="number"
                    value={getNum(payload.business_rules?.callback, "delay_minutes")}
                    onChange={(e) => updateCallback({ delay_minutes: toNumOrUndefined(e.target.value) })}
                    className={inputCls}
                  />
                </Field>
                <Field label="Callback time variable" hint="STT-captured time, e.g. call_back_time — resolved via the same regex parser as feat/orch-v2.">
                  <input
                    type="text"
                    value={getStr(payload.business_rules?.callback, "time_variable")}
                    onChange={(e) => updateCallback({ time_variable: e.target.value })}
                    placeholder="call_back_time"
                    className={inputCls}
                  />
                </Field>
              </div>
            </div>

            <div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={getBool(payload.business_rules?.dnd, "enabled")}
                  onChange={(e) => updateDnd({ enabled: e.target.checked })}
                  className="accent-primary"
                />
                <span className="text-sm font-semibold text-on-surface">DND — respect do-not-disturb windows</span>
              </label>
            </div>

            <div>
              <p className="text-sm font-semibold text-on-surface mb-2">Variables</p>
              <VariableRowsEditor
                rows={payload.business_rules?.variables ?? []}
                onChange={setBusinessVariables}
              />
            </div>
          </div>
        )}

        {step === "integrations_disabled" && (
          <div className="space-y-4">
            <CardHeader title="Integrations" hint="Attach integrations this process should use. Optional." />
            {integrationsLoading && <p className="text-sm text-text-muted">Loading…</p>}
            {integrationsError && <p className="text-sm text-bad">{integrationsError}</p>}
            {!integrationsLoading && !integrationsError && integrations.length === 0 && (
              <p className="text-sm text-text-muted">
                No integrations configured yet — you can add these later from the Integrations page.
              </p>
            )}
            {!integrationsLoading && integrations.length > 0 && (
              <div className="space-y-2">
                {integrations.map((i) => (
                  <label
                    key={i.id}
                    className="flex items-center gap-3 p-3 rounded-lg border border-border bg-muted/50 cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={(payload.integrations ?? []).includes(i.id)}
                      onChange={() => toggleIntegration(i.id)}
                      className="accent-primary"
                    />
                    <div>
                      <p className="text-sm font-medium text-on-surface">{i.name}</p>
                      <p className="text-xs text-text-muted">{i.type}</p>
                    </div>
                  </label>
                ))}
              </div>
            )}
          </div>
        )}
        ── end disabled steps ── */}

        {/* ── WhatsApp follow-up (optional) ── */}
        {step === "whatsapp" && (
          <div className="space-y-4">
            <CardHeader title="WhatsApp follow-up" hint="Send a WhatsApp template to the customer after each call. Optional." />
            <label className="flex items-center gap-3 p-3 rounded-lg border border-border bg-muted/50 cursor-pointer">
              <input
                type="checkbox"
                checked={whatsappEnabled}
                onChange={(e) => setWhatsappEnabled(e.target.checked)}
                className="accent-primary"
              />
              <div>
                <p className="text-sm font-medium text-on-surface">Send a WhatsApp message after each call</p>
                <p className="text-xs text-text-muted">You can skip this and add templates later in Settings.</p>
              </div>
            </label>

            {whatsappEnabled && (
              <>
                <Field
                  label="Template curl *"
                  hint="Paste the curl for the WhatsApp template. What it sends is whatever placeholders the curl itself contains."
                >
                  <textarea
                    value={payload.omnichannel?.whatsapp_curl ?? ""}
                    onChange={(e) => setWhatsappCurl(e.target.value)}
                    rows={7}
                    placeholder={"curl -X POST https://... \\\n  -H 'Authorization: Bearer ...' \\\n  -d '{...}'"}
                    spellCheck={false}
                    className={`${inputCls} font-mono`}
                  />
                </Field>
                {curlCheck?.error && !curlBlank && <p className="text-xs text-bad">{curlCheck.error}</p>}
                {curlCheck && !curlCheck.error && !curlBlank && (
                  <div className="rounded-lg border border-border bg-muted/50 p-3 text-xs text-text-muted space-y-1.5">
                    <p>
                      {curlCheck.params.length > 0
                        ? `Detected ${curlCheck.params.length} placeholder${curlCheck.params.length === 1 ? "" : "s"}:`
                        : "No placeholders detected — the same message will be sent every time."}
                    </p>
                    {curlCheck.params.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {curlCheck.params.map((k) => (
                          <span key={k} className="px-1.5 py-0.5 rounded bg-card border border-border font-mono text-foreground">
                            {k}
                          </span>
                        ))}
                      </div>
                    )}
                    <p>
                      After the first call you&apos;ll map each placeholder to a captured variable, and add rules for
                      choosing between templates, in Settings → Omnichannel. Until then this template is sent after
                      every call.
                    </p>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* ── Review ── */}
        {step === "review" && (
          <div className="space-y-5">
            <CardHeader title="Review" hint="Confirm the configuration, then create the agent." />

            <ReviewSection title="Basics" onEdit={() => jumpTo("basic")}>
              <ReviewRow label="Channel" value={selectedChannel?.name ?? String(payload.channelId || "—")} />
              <ReviewRow label="Name" value={payload.name || "—"} />
              <ReviewRow label="Description" value={payload.description || "—"} />
            </ReviewSection>

            <ReviewSection title="Voicebot" onEdit={() => jumpTo("voicebot")}>
              <ReviewRow
                label="Bot"
                value={
                  selectedVoiceBot
                    ? selectedVoiceBot.label || selectedVoiceBot.bot_name || `Voice Bot ${selectedVoiceBot.id}`
                    : "—"
                }
              />
              <ReviewRow label="Direction" value={isInbound ? "Inbound" : selectedVoiceBot ? "Outbound" : "—"} />
              <ReviewRow label="Number" value={selectedVoiceBot ? selectedNumber?.did ?? "Automatic" : "—"} />
            </ReviewSection>

            {!isInbound && (
              <ReviewSection title="Lead Source" onEdit={() => jumpTo("lead_source")}>
                <ReviewRow label="Type" value={payload.lead_source?.type || "None — add leads when launching a campaign"} />
                {payload.lead_source?.type === "single_source" ? (
                  <ReviewRow label="Number" value={getStr(payload.lead_source?.configuration, "number") || "—"} />
                ) : (
                  payload.lead_source?.type && (
                    <ReviewRow label="Notes" value={getStr(payload.lead_source?.configuration, "notes") || "—"} />
                  )
                )}
              </ReviewSection>
            )}

            <ReviewSection title="WhatsApp follow-up" onEdit={() => jumpTo("whatsapp")}>
              <ReviewRow
                label="Template"
                value={
                  whatsappEnabled && curlCheck && !curlCheck.error
                    ? `Set (${curlCheck.params.length} placeholder${curlCheck.params.length === 1 ? "" : "s"})`
                    : "None"
                }
              />
            </ReviewSection>

            {/* ── Business Rules and Integrations review sections are disabled — see STEPS above. ──
            <ReviewSection title="Business Rules" onEdit={() => setStep(3)}>
              <ReviewRow
                label="Retry"
                value={
                  payload.business_rules?.retry
                    ? `${getStr(payload.business_rules.retry, "attempts") || "—"} attempts, ${
                        getStr(payload.business_rules.retry, "interval_minutes") || "—"
                      } min interval, ${getStr(payload.business_rules.retry, "strategy") || "—"}`
                    : "—"
                }
              />
              <ReviewRow
                label="Business Hours"
                value={
                  payload.business_rules?.business_hours
                    ? `${getStr(payload.business_rules.business_hours, "timezone") || "Asia/Kolkata"} ${
                        getStr(payload.business_rules.business_hours, "start") || "—"
                      }–${getStr(payload.business_rules.business_hours, "end") || "—"}`
                    : "—"
                }
              />
              <ReviewRow
                label="Callback conditions"
                value={
                  getCallbackConditions(payload.business_rules?.callback).length > 0
                    ? getCallbackConditions(payload.business_rules?.callback)
                        .map((c) => `${c.variable || "—"} ${c.operator} ${c.value || "—"}`)
                        .join("; ")
                    : "—"
                }
              />
              <ReviewRow
                label="Callback timing"
                value={`delay ${getStr(payload.business_rules?.callback, "delay_minutes") || "—"}m, time variable: ${
                  getStr(payload.business_rules?.callback, "time_variable") || "—"
                }`}
              />
              <ReviewRow label="DND" value={getBool(payload.business_rules?.dnd, "enabled") ? "Enabled" : "Disabled"} />
              <ReviewRow
                label="Variables"
                value={
                  (payload.business_rules?.variables ?? []).filter((v) => v.key.trim()).length > 0
                    ? (payload.business_rules?.variables ?? [])
                        .filter((v) => v.key.trim())
                        .map((v) => v.key)
                        .join(", ")
                    : "—"
                }
              />
            </ReviewSection>

            <ReviewSection title="Integrations" onEdit={() => setStep(4)}>
              <ReviewRow
                label="Selected"
                value={selectedIntegrations.length > 0 ? selectedIntegrations.map((i) => i.name).join(", ") : "None"}
              />
            </ReviewSection>
            ── end disabled review sections ── */}

            <div className="rounded-lg border border-border bg-muted/50 p-4 space-y-3">
              <div>
                <p className="text-sm font-semibold text-foreground">Quality checks (optional)</p>
                <p className="text-xs text-muted-foreground">
                  Automated checks run against each call. Variable-based QA is set up after the first call, once the
                  variables have been discovered.
                </p>
              </div>
              <div className="grid sm:grid-cols-2 gap-2">
                {QA_FIELDS.filter((f) => f.key === "end_call_misfiring" || f.key === "drop_off_analysis").map((f) => (
                  <label
                    key={f.key}
                    className="flex items-start gap-2 px-2.5 py-2 rounded-md border border-border bg-card cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={getBool(payload.qa, f.key)}
                      onChange={() => toggleQa(f.key)}
                      className="accent-primary mt-0.5"
                    />
                    <span>
                      <span className="block text-sm font-medium text-on-surface">{f.label}</span>
                      <span className="block text-xs text-text-muted">{f.hint}</span>
                    </span>
                  </label>
                ))}
              </div>
            </div>

            <div className="rounded-lg border border-border bg-muted/50 p-4 text-xs text-muted-foreground space-y-1">
              <p className="text-sm font-semibold text-foreground">What happens next</p>
              {isInbound ? (
                <p>
                  You&apos;ll get this agent&apos;s webhook URL to paste into Chat360. Calls and variables appear after
                  the first call.
                </p>
              ) : (
                <p>Add leads and launch a campaign from the agent page. Calls and variables appear after the first call.</p>
              )}
              <p>Tick which discovered variables feed QA and analytics once they show up.</p>
            </div>

            {submitError && <ErrorAlert message={submitError} />}

            <div className="flex justify-end">
              <Button type="button" size="lg" onClick={handleGenerate} disabled={submitting}>
                {submitting ? <Spinner /> : <Sparkles />}
                {submitting ? "Creating…" : "Create Agent"}
              </Button>
            </div>
          </div>
        )}

        {/* ── Back / Next (all steps except Review, which has its own submit button) ── */}
        {step !== "review" && (
          <div className="flex items-center justify-between pt-6 mt-6 border-t border-border">
            <Button type="button" variant="ghost" onClick={goBack} disabled={stepIdx === 0}>
              <ArrowLeft /> Back
            </Button>
            <Button type="button" onClick={goNext} disabled={!canProceed}>
              Next <ArrowRight />
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}

// ── Review helpers ───────────────────────────────────────────────────────

function ReviewSection({ title, onEdit, children }: { title: string; onEdit: () => void; children: React.ReactNode }) {
  return (
    <div className="border border-border rounded-lg p-4 bg-muted/50">
      <div className="flex items-center justify-between mb-2">
        <p className="text-sm font-semibold text-foreground">{title}</p>
        <Button type="button" variant="ghost" size="xs" onClick={onEdit}>
          <Pencil /> Edit
        </Button>
      </div>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function ReviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start gap-2 text-sm">
      <span className="text-muted-foreground min-w-35">{label}</span>
      <span className="text-foreground break-words">{value}</span>
    </div>
  );
}
