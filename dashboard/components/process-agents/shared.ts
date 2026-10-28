// ── Shared constants/helpers used across process-agent detail tabs ─────────
// Kept in sync manually with the wizard (dashboard/app/process-agents/new/page.tsx)
// — these are display labels for config stored on the Communication/QA
// NodeInstances and ProcessAgent.analytics_stats, not schema.

import type { CallRow } from "@/lib/types";

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

export function str(v: unknown): string {
  if (v === null || v === undefined) return "";
  return typeof v === "string" ? v : String(v);
}

// Inbound rows carry caller_number; outbound rows only to_number.
export function phoneOf(row: CallRow): string {
  return str(row.variables.caller_number) || str(row.variables.to_number) || row.lead_id;
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

/**
 * The readable part of a failed telehubApi call. The client throws
 * "TelehubApi POST /x failed: 400 Bad Request {json body}"; when that body is
 * {"error": "text"} or {"error": {field: "text"}} this returns just the text(s),
 * otherwise the fallback.
 */
export function apiErrorText(e: unknown, fallback: string): string {
  if (!(e instanceof Error)) return fallback;
  const start = e.message.indexOf("{");
  if (start === -1) return fallback;
  try {
    const body = JSON.parse(e.message.slice(start)) as { error?: unknown };
    if (typeof body.error === "string") return body.error;
    if (body.error && typeof body.error === "object") {
      const lines = Object.entries(body.error as Record<string, unknown>).map(([field, msg]) =>
        Array.isArray(msg) ? `${field}: ${msg.join(", ")}` : `${field}: ${String(msg)}`,
      );
      if (lines.length) return lines.join(" · ");
    }
  } catch {
    // not JSON — fall through
  }
  return fallback;
}
