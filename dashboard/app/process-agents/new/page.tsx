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

// Business Rules and Integrations steps are temporarily disabled — see step
// content blocks and the Review section below, both commented out in tandem.
// Re-enable by uncommenting these two entries (and restoring the original
// step-index numbering throughout this file) alongside them.
const STEPS = [
  "Basic",
  "Voice",
  "Lead Source",
  // "Business Rules",
  // "Integrations",
  "QA",
  "Analytics",
  "Omnichannel",
  "Review",
] as const;

const STEP_HINTS: Record<(typeof STEPS)[number], string> = {
  Basic: "Name the process and place it under a channel.",
  Voice: "Select the bot this process dispatches calls through.",
  "Lead Source": "Where leads for this process come from.",
  // "Business Rules": "Retry, business hours, callback and DND behaviour.",
  // Integrations: "Attach existing integrations to this process (optional).",
  QA: "Automated quality checks to run after every execution.",
  Analytics: "Variables tracked and dashboard stats shown for this process (optional).",
  Omnichannel: "Send captured variables to another channel after the call.",
  Review: "Confirm everything below, then generate the process.",
};

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

// Variables selectable in Omnichannel's "variables to send" picker.
const VARIABLE_LIST = [
  "model_name",
  "alternate_model",
  "model_reject_reason",
  "location",
  "location_spoken",
  "location_raw",
  "location_reject_reason",
  "matched_showroom",
  "showroom_location",
  "showroom_match_reason",
  "awaiting_showroom_choice",
  "awaiting_area_detail",
  "purchase_timeline",
  "finance_needed",
  "exchange_car",
  "interest_type",
  "lead_status",
  "appointment_time",
  "appointment_time_precision",
  "appointment_address",
  "date_time",
  "date_time_precision",
  "close_quality",
  "name",
  "preferred_showroom",
  "pending_location",
  "pending_purchase_timeline",
  "pending_finance_needed",
  "pending_exchange_car",
  "pending_interest_type",
  "pending_showroom_preference",
  "skip_filler",
  "end_call",
  "exit_call",
  "disconnect",
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

function StepIndicator({ current, onJump }: { current: number; onJump: (idx: number) => void }) {
  return (
    <div className="flex items-center gap-0 mb-6 overflow-x-auto pb-1">
      {STEPS.map((label, idx) => {
        const isCompleted = idx < current;
        const isCurrent = idx === current;
        const isLast = idx === STEPS.length - 1;
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

// ── Checkbox picker over VARIABLE_LIST, plus freeform rows for names not on the list (Omnichannel) ──

function VariableChecklist({
  selected,
  onChange,
}: {
  selected: string[];
  onChange: (selected: string[]) => void;
}) {
  // Original `selected` index, not the filtered position — keeps rows stable
  // when values are blank or duplicated.
  const extra = selected.map((v, i) => ({ value: v, index: i })).filter((e) => !VARIABLE_LIST.includes(e.value));

  function toggle(name: string) {
    onChange(selected.includes(name) ? selected.filter((v) => v !== name) : [...selected, name]);
  }
  function updateExtra(originalIdx: number, value: string) {
    onChange(selected.map((v, i) => (i === originalIdx ? value : v)));
  }
  function removeExtra(originalIdx: number) {
    onChange(selected.filter((_, i) => i !== originalIdx));
  }
  function addExtra() {
    onChange([...selected, ""]);
  }

  return (
    <div className="space-y-3">
      <div className="grid sm:grid-cols-2 gap-2 max-h-72 overflow-y-auto pr-1">
        {VARIABLE_LIST.map((name) => (
          <label
            key={name}
            className="flex items-center gap-2 px-2.5 py-1.5 rounded-md border border-border bg-muted/50 cursor-pointer text-sm text-on-surface"
          >
            <input
              type="checkbox"
              checked={selected.includes(name)}
              onChange={() => toggle(name)}
              className="accent-primary"
            />
            <span className="font-mono text-xs">{name}</span>
          </label>
        ))}
      </div>
      <div>
        <p className="text-xs font-medium text-text-muted mb-1.5">Not on the list</p>
        <div className="space-y-2">
          {extra.map(({ value, index }) => (
            <div key={index} className="flex items-center gap-2 p-2.5 rounded-lg border border-border bg-muted/50">
              <input
                type="text"
                value={value}
                onChange={(e) => updateExtra(index, e.target.value)}
                placeholder="variable name"
                className="flex-1 px-2.5 py-1.5 rounded-md border border-border bg-surface text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary"
              />
              <button
                type="button"
                onClick={() => removeExtra(index)}
                className="text-xs text-bad hover:underline whitespace-nowrap"
              >
                Remove
              </button>
            </div>
          ))}
          <Button type="button" variant="outline" size="sm" onClick={addExtra}>
            <Plus /> Add variable
          </Button>
        </div>
      </div>
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

  const [step, setStep] = useState(0);
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

  function setVoiceBotId(voiceBotId: number | undefined) {
    setPayload((p) => ({ ...p, voice: { voice_bot_id: voiceBotId } }));
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
  function setCustomVariables(rows: ProcessAgentWizardVariable[]) {
    setPayload((p) => ({ ...p, analytics: { ...p.analytics, custom_variables: rows } }));
  }
  function toggleStat(key: string) {
    setPayload((p) => ({
      ...p,
      analytics: { ...p.analytics, stats: { ...(p.analytics?.stats ?? {}), [key]: !getBool(p.analytics?.stats, key) } },
    }));
  }
  function updateOmnichannel(patch: Partial<NonNullable<ProcessAgentWizardPayload["omnichannel"]>>) {
    setPayload((p) => ({ ...p, omnichannel: { ...p.omnichannel, ...patch } }));
  }
  function setOmnichannelVariables(values: string[]) {
    updateOmnichannel({ variables: values });
  }

  // ── Validation (only Basic requires fields) ──

  const canProceed = step === 0 ? payload.channelId > 0 && payload.name.trim() !== "" : true;

  function goNext() {
    if (!canProceed) return;
    setStep((s) => Math.min(s + 1, STEPS.length - 1));
  }
  function goBack() {
    setStep((s) => Math.max(s - 1, 0));
  }

  // ── Submission ──

  function buildFinalPayload(): ProcessAgentWizardPayload {
    const cleanedBusinessVars = (payload.business_rules?.variables ?? []).filter((v) => v.key.trim() !== "");
    const cleanedCustomVars = (payload.analytics?.custom_variables ?? []).filter((v) => v.key.trim() !== "");
    const cleanedOmnichannelVars = (payload.omnichannel?.variables ?? []).filter((v) => v.trim() !== "");
    return {
      ...payload,
      name: payload.name.trim(),
      description: payload.description?.trim() || undefined,
      voice: payload.voice?.voice_bot_id ? payload.voice : undefined,
      business_rules: payload.business_rules
        ? { ...payload.business_rules, variables: cleanedBusinessVars.length ? cleanedBusinessVars : undefined }
        : undefined,
      analytics: payload.analytics
        ? { ...payload.analytics, custom_variables: cleanedCustomVars.length ? cleanedCustomVars : undefined }
        : undefined,
      integrations: payload.integrations && payload.integrations.length > 0 ? payload.integrations : undefined,
      omnichannel: payload.omnichannel
        ? { ...payload.omnichannel, variables: cleanedOmnichannelVars.length ? cleanedOmnichannelVars : undefined }
        : undefined,
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
  const selectedVoiceBot = voiceBots.find((b) => b.id === payload.voice?.voice_bot_id);
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
        description={STEP_HINTS[STEPS[step]]}
      />

      <StepIndicator current={step} onJump={setStep} />

      <Card className="p-6">
        {/* ── Step 0: Basic ── */}
        {step === 0 && (
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

        {/* ── Step 1: Voice ── */}
        {step === 1 && (
          <div className="space-y-4">
            <CardHeader title="Voice" hint="Pick the bot this process dispatches calls through." />
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
              <div className="rounded-lg border border-border bg-muted/50 p-3 space-y-0.5 text-xs text-text-muted">
                {selectedVoiceBot.communication_type && (
                  <p>
                    {COMMUNICATION_TYPES.find((c) => c.value === selectedVoiceBot.communication_type)?.label ??
                      selectedVoiceBot.communication_type}
                  </p>
                )}
                <p>
                  {selectedVoiceBot.bot_name || "—"}
                  {selectedVoiceBot.bot_id && <span className="ml-1">({selectedVoiceBot.bot_id})</span>}
                </p>
                {selectedVoiceBot.dids.length > 0 && <p>DIDs: {selectedVoiceBot.dids.join(", ")}</p>}
                {selectedVoiceBot.api_url && <p className="font-mono break-all">{selectedVoiceBot.api_url}</p>}
              </div>
            )}
          </div>
        )}

        {/* ── Step 2: Lead Source ── */}
        {step === 2 && (
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

        {/* ── Step 3: QA ── */}
        {step === 3 && (
          <div className="space-y-4">
            <CardHeader title="QA" hint="Automated checks run against every execution's transcript." />
            <div className="space-y-2">
              {QA_FIELDS.map((f) => (
                <label
                  key={f.key}
                  className="flex items-center gap-3 p-3 rounded-lg border border-border bg-muted/50 cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={getBool(payload.qa, f.key)}
                    onChange={() => toggleQa(f.key)}
                    className="accent-primary"
                  />
                  <div>
                    <p className="text-sm font-medium text-on-surface">{f.label}</p>
                    <p className="text-xs text-text-muted">{f.hint}</p>
                  </div>
                </label>
              ))}
            </div>
          </div>
        )}

        {/* ── Step 4: Analytics ── */}
        {step === 4 && (
          <div className="space-y-6">
            <CardHeader title="Analytics" hint="Variables tracked and dashboard stats shown for this process. Optional." />

            <div>
              <p className="text-sm font-semibold text-on-surface mb-2">
                Dispositions / Variables{" "}
                <span className="font-normal text-text-muted">— same thing on the main platform</span>
              </p>
              <VariableRowsEditor
                rows={payload.analytics?.custom_variables ?? []}
                onChange={setCustomVariables}
                simple
              />
            </div>

            <div>
              <p className="text-sm font-semibold text-on-surface mb-2">Stats &amp; Summaries</p>
              <p className="text-xs text-text-muted mb-2">
                Dashboard stat tiles for this process, computed from call data already in the database.
              </p>
              <div className="grid sm:grid-cols-2 gap-2">
                {STAT_FIELDS.map((f) => (
                  <label
                    key={f.key}
                    className="flex items-center gap-2 px-2.5 py-1.5 rounded-md border border-border bg-muted/50 cursor-pointer text-sm text-on-surface"
                  >
                    <input
                      type="checkbox"
                      checked={getBool(payload.analytics?.stats, f.key)}
                      onChange={() => toggleStat(f.key)}
                      className="accent-primary"
                    />
                    {f.label}
                  </label>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ── Step 5: Omnichannel ── */}
        {step === 5 && (
          <div className="space-y-4">
            <CardHeader
              title="Omnichannel"
              hint="Send captured variables from this process to another channel after each call."
            />
            <Field label="Channel">
              <select
                value={payload.omnichannel?.channel ?? ""}
                onChange={(e) => updateOmnichannel({ channel: e.target.value })}
                className={inputCls}
              >
                <option value="">— select —</option>
                {COMMUNICATION_TYPES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </Field>

            <div>
              <p className="text-sm font-semibold text-on-surface mb-2">Variables to send</p>
              <VariableChecklist
                selected={payload.omnichannel?.variables ?? []}
                onChange={setOmnichannelVariables}
              />
            </div>

            {payload.omnichannel?.channel === "whatsapp" && (
              <div className="space-y-4 pt-2 border-t border-border">
                <p className="text-sm font-semibold text-on-surface">WhatsApp</p>
                <Field label="Template" hint="Template name or ID to send.">
                  <input
                    type="text"
                    value={payload.omnichannel?.whatsapp_template ?? ""}
                    onChange={(e) => updateOmnichannel({ whatsapp_template: e.target.value })}
                    placeholder="e.g. appointment_confirmation"
                    className={inputCls}
                  />
                </Field>
                <Field label="curl template" hint="Paste the curl command used to call the WhatsApp integration.">
                  <textarea
                    value={payload.omnichannel?.whatsapp_curl ?? ""}
                    onChange={(e) => updateOmnichannel({ whatsapp_curl: e.target.value })}
                    rows={6}
                    placeholder={"curl -X POST https://... \\\n  -H 'Authorization: Bearer ...' \\\n  -d '{...}'"}
                    spellCheck={false}
                    className={`${inputCls} font-mono`}
                  />
                </Field>
              </div>
            )}
          </div>
        )}

        {/* ── Step 6: Review ── */}
        {step === 6 && (
          <div className="space-y-5">
            <CardHeader title="Review" hint="Confirm the configuration, then generate the process." />

            <ReviewSection title="Basic" onEdit={() => setStep(0)}>
              <ReviewRow label="Channel" value={selectedChannel?.name ?? String(payload.channelId || "—")} />
              <ReviewRow label="Name" value={payload.name || "—"} />
              <ReviewRow label="Description" value={payload.description || "—"} />
            </ReviewSection>

            <ReviewSection title="Voice" onEdit={() => setStep(1)}>
              <ReviewRow
                label="Bot"
                value={selectedVoiceBot ? selectedVoiceBot.label || selectedVoiceBot.bot_name || `Voice Bot ${selectedVoiceBot.id}` : "—"}
              />
            </ReviewSection>

            <ReviewSection title="Lead Source" onEdit={() => setStep(2)}>
              <ReviewRow label="Type" value={payload.lead_source?.type || "—"} />
              {payload.lead_source?.type === "single_source" ? (
                <ReviewRow label="Number" value={getStr(payload.lead_source?.configuration, "number") || "—"} />
              ) : (
                <ReviewRow label="Notes" value={getStr(payload.lead_source?.configuration, "notes") || "—"} />
              )}
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

            <ReviewSection title="QA" onEdit={() => setStep(3)}>
              <ReviewRow
                label="Enabled checks"
                value={
                  QA_FIELDS.filter((f) => getBool(payload.qa, f.key))
                    .map((f) => f.label)
                    .join(", ") || "None"
                }
              />
            </ReviewSection>

            <ReviewSection title="Analytics" onEdit={() => setStep(4)}>
              <ReviewRow
                label="Dispositions / Variables"
                value={
                  (payload.analytics?.custom_variables ?? []).filter((v) => v.key.trim()).length > 0
                    ? (payload.analytics?.custom_variables ?? [])
                        .filter((v) => v.key.trim())
                        .map((v) => v.key)
                        .join(", ")
                    : "—"
                }
              />
              <ReviewRow
                label="Stats & Summaries"
                value={
                  STAT_FIELDS.filter((f) => getBool(payload.analytics?.stats, f.key))
                    .map((f) => f.label)
                    .join(", ") || "None"
                }
              />
            </ReviewSection>

            <ReviewSection title="Omnichannel" onEdit={() => setStep(5)}>
              <ReviewRow
                label="Channel"
                value={
                  COMMUNICATION_TYPES.find((c) => c.value === payload.omnichannel?.channel)?.label ??
                  payload.omnichannel?.channel ??
                  "—"
                }
              />
              <ReviewRow
                label="Variables to send"
                value={
                  (payload.omnichannel?.variables ?? []).filter((v) => v.trim()).length > 0
                    ? (payload.omnichannel?.variables ?? []).filter((v) => v.trim()).join(", ")
                    : "—"
                }
              />
              {payload.omnichannel?.channel === "whatsapp" && (
                <>
                  <ReviewRow label="WhatsApp Template" value={payload.omnichannel?.whatsapp_template || "—"} />
                  <ReviewRow label="curl template" value={payload.omnichannel?.whatsapp_curl ? "Set" : "—"} />
                </>
              )}
            </ReviewSection>

            {submitError && <ErrorAlert message={submitError} />}

            <div className="flex justify-end">
              <Button type="button" size="lg" onClick={handleGenerate} disabled={submitting}>
                {submitting ? <Spinner /> : <Sparkles />}
                {submitting ? "Generating…" : "Generate Process"}
              </Button>
            </div>
          </div>
        )}

        {/* ── Back / Next (all steps except Review, which has its own submit button) ── */}
        {step !== 6 && (
          <div className="flex items-center justify-between pt-6 mt-6 border-t border-border">
            <Button type="button" variant="ghost" onClick={goBack} disabled={step === 0}>
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
