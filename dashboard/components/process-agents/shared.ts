// ── Shared constants/helpers used across process-agent detail tabs ─────────
// Kept in sync manually with the wizard (dashboard/app/process-agents/new/page.tsx)
// — these are display labels for config stored on the Communication/QA
// NodeInstances and ProcessAgent.analytics_stats, not schema.

export type TabKey = "overview" | "journey" | "runs" | "calls" | "qa" | "analytics" | "settings";

export const TABS: { key: TabKey; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "journey", label: "Journey" },
  { key: "runs", label: "Runs" },
  { key: "calls", label: "Calls" },
  { key: "qa", label: "QA" },
  { key: "analytics", label: "Analytics" },
  { key: "settings", label: "Settings" },
];

// Hyundai POC WhatsApp templates — the rules live in
// services/telehub/apps/telehub/services/hyundai_whatsapp.py; `when` is only
// the description shown in Settings.
export const WHATSAPP_TEMPLATES: { key: string; label: string; when: string }[] = [
  {
    key: "T1",
    label: "T1 – Appointment confirmation",
    when: "Appointment date, time and place captured — or a partial capture (empty fields are sent as \"unspecified\").",
  },
  { key: "T2", label: "T2 – Callback", when: "Caller said they'll call back (callback_status is \"required\")." },
  { key: "T3", label: "T3 – Sorry follow-up", when: "None of name, model or appointment details were captured." },
];

export const COMMUNICATION_TYPE_LABELS: Record<string, string> = {
  voice_outbound: "Voice Outbound",
  voice_inbound: "Voice Inbound",
  whatsapp: "WhatsApp",
  sms: "SMS",
  email: "Email",
};

export const QA_FIELDS: { key: string; label: string; hint: string }[] = [
  {
    key: "missing_variables",
    label: "Missing Variables",
    hint: "Flag executions where expected variables weren't captured.",
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

export const STAT_FIELDS: { key: string; label: string }[] = [
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

export function getConfigStr(config: Record<string, unknown> | undefined, key: string): string {
  const v = config?.[key];
  if (typeof v === "string") return v;
  if (typeof v === "number") return String(v);
  return "";
}

export function getConfigBool(config: Record<string, unknown> | undefined, key: string): boolean {
  return config?.[key] === true;
}

export function getConfigStrArray(config: Record<string, unknown> | undefined, key: string): string[] {
  const v = config?.[key];
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function errorMessage(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}
