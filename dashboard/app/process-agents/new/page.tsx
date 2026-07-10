"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Card, CardHeader } from "@/components/Card";
import { listDepartments, listIntegrations, createProcessAgent } from "@/lib/telehubApi";
import type {
  Department,
  Integration,
  ProcessAgentWizardPayload,
  ProcessAgentWizardVariable,
} from "@/lib/types";

// ── Constants ────────────────────────────────────────────────────────────

const STEPS = [
  "Basic",
  "Voice",
  "Lead Source",
  "Business Rules",
  "Integrations",
  "QA",
  "Analytics",
  "Review",
] as const;

const STEP_HINTS: Record<(typeof STEPS)[number], string> = {
  Basic: "Name the process and place it under a department.",
  Voice: "Choose how leads are contacted and where call events land.",
  "Lead Source": "Where leads for this process come from.",
  "Business Rules": "Retry, business hours, callback and DND behaviour.",
  Integrations: "Attach existing integrations to this process (optional).",
  QA: "Automated quality checks to run after every execution.",
  Analytics: "Custom variables tracked on the dashboard (optional).",
  Review: "Confirm everything below, then generate the process.",
};

const COMMUNICATION_TYPES = [
  { value: "voice_outbound", label: "Voice Outbound" },
  { value: "voice_inbound", label: "Voice Inbound" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "sms", label: "SMS" },
  { value: "email", label: "Email" },
];

const WEBHOOK_SCHEMA_FIELDS = ["summary", "transcript", "sentiment", "outcome"] as const;

const LEAD_SOURCE_TYPES = [
  { value: "webhook", label: "Webhook" },
  { value: "crm", label: "CRM" },
  { value: "google_sheet", label: "Google Sheet" },
  { value: "rest_api", label: "REST API" },
  { value: "csv", label: "CSV" },
];

const RETRY_STRATEGIES = [
  { value: "linear", label: "Linear" },
  { value: "exponential", label: "Exponential" },
];

const CALLBACK_OPERATORS = ["==", "!=", ">", "<", "contains"];

const QA_FIELDS: { key: string; label: string; hint: string }[] = [
  { key: "summary", label: "Summary", hint: "Generate a call summary after each execution." },
  { key: "sentiment", label: "Sentiment", hint: "Detect caller sentiment." },
  { key: "hallucination", label: "Hallucination", hint: "Flag hallucinated / unsupported claims." },
  { key: "lead_score", label: "Lead Score", hint: "Score lead quality from the conversation." },
  { key: "compliance", label: "Compliance", hint: "Check for compliance / script adherence." },
  { key: "hot_lead_detection", label: "Hot Lead Detection", hint: "Flag high-intent leads for fast follow-up." },
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
                    ? "bg-primary text-on-primary"
                    : isCurrent
                    ? "bg-primary text-on-primary ring-4 ring-primary/20"
                    : "bg-surface-container text-text-muted"
                }`}
              >
                {isCompleted ? (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                ) : (
                  idx + 1
                )}
              </div>
              <span
                className={`text-xs font-medium whitespace-nowrap ${
                  isCurrent ? "text-primary" : isCompleted ? "text-on-surface" : "text-text-muted"
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
        <div key={idx} className="flex flex-wrap items-center gap-2 p-3 rounded-lg border border-border bg-surface-container">
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
      <button
        type="button"
        onClick={addRow}
        className="px-3 py-1.5 rounded-lg border border-border text-xs font-medium text-on-surface hover:bg-surface-container transition-colors"
      >
        + Add variable
      </button>
    </div>
  );
}

// ── Field wrapper ────────────────────────────────────────────────────────

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-text-muted">{label}</span>
      {children}
      {hint && <span className="text-xs text-text-muted">{hint}</span>}
    </label>
  );
}

const inputCls =
  "px-3 py-2 rounded-lg border border-border bg-surface text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary";

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
  const departmentParam = searchParams.get("department");

  const [step, setStep] = useState(0);
  const [payload, setPayload] = useState<ProcessAgentWizardPayload>(() => ({
    department: departmentParam ? Number(departmentParam) : 0,
    name: "",
    description: "",
  }));

  const [departments, setDepartments] = useState<Department[]>([]);
  const [departmentsLoading, setDepartmentsLoading] = useState(true);
  const [departmentsError, setDepartmentsError] = useState<string | null>(null);

  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [integrationsLoading, setIntegrationsLoading] = useState(true);
  const [integrationsError, setIntegrationsError] = useState<string | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    listDepartments()
      .then((data) => setDepartments(data))
      .catch((e) => setDepartmentsError(e instanceof Error ? e.message : "Failed to load departments"))
      .finally(() => setDepartmentsLoading(false));
  }, []);

  useEffect(() => {
    listIntegrations()
      .then((data) => setIntegrations(data))
      .catch((e) => setIntegrationsError(e instanceof Error ? e.message : "Failed to load integrations"))
      .finally(() => setIntegrationsLoading(false));
  }, []);

  // ── Update helpers ──

  function updateVoice(patch: Record<string, unknown>) {
    setPayload((p) => ({ ...p, voice: { ...p.voice, ...patch } }));
  }
  function updateWebhookSchema(key: string, value: string) {
    setPayload((p) => ({
      ...p,
      voice: { ...p.voice, webhook_schema: { ...(p.voice?.webhook_schema ?? {}), [key]: value } },
    }));
  }
  function updateLeadSource(patch: ProcessAgentWizardPayload["lead_source"]) {
    setPayload((p) => ({ ...p, lead_source: { ...p.lead_source, ...patch } }));
  }
  function updateRetry(patch: Record<string, unknown>) {
    setPayload((p) => ({
      ...p,
      business_rules: { ...p.business_rules, retry: { ...(p.business_rules?.retry ?? {}), ...patch } },
    }));
  }
  function updateBusinessHours(patch: Record<string, unknown>) {
    setPayload((p) => ({
      ...p,
      business_rules: {
        ...p.business_rules,
        business_hours: { ...(p.business_rules?.business_hours ?? {}), ...patch },
      },
    }));
  }
  function updateCallback(patch: Record<string, unknown>) {
    setPayload((p) => ({
      ...p,
      business_rules: { ...p.business_rules, callback: { ...(p.business_rules?.callback ?? {}), ...patch } },
    }));
  }
  function updateDnd(patch: Record<string, unknown>) {
    setPayload((p) => ({
      ...p,
      business_rules: { ...p.business_rules, dnd: { ...(p.business_rules?.dnd ?? {}), ...patch } },
    }));
  }
  function setBusinessVariables(rows: ProcessAgentWizardVariable[]) {
    setPayload((p) => ({ ...p, business_rules: { ...p.business_rules, variables: rows } }));
  }
  function toggleIntegration(id: number) {
    setPayload((p) => {
      const current = p.integrations ?? [];
      const next = current.includes(id) ? current.filter((x) => x !== id) : [...current, id];
      return { ...p, integrations: next };
    });
  }
  function toggleQa(key: string) {
    setPayload((p) => ({ ...p, qa: { ...p.qa, [key]: !getBool(p.qa, key) } }));
  }
  function setCustomVariables(rows: ProcessAgentWizardVariable[]) {
    setPayload((p) => ({ ...p, analytics: { ...p.analytics, custom_variables: rows } }));
  }

  // ── Validation (only Basic requires fields) ──

  const canProceed = step === 0 ? payload.department > 0 && payload.name.trim() !== "" : true;

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
    return {
      ...payload,
      name: payload.name.trim(),
      description: payload.description?.trim() || undefined,
      business_rules: payload.business_rules
        ? { ...payload.business_rules, variables: cleanedBusinessVars.length ? cleanedBusinessVars : undefined }
        : undefined,
      analytics: payload.analytics
        ? { ...payload.analytics, custom_variables: cleanedCustomVars.length ? cleanedCustomVars : undefined }
        : undefined,
      integrations: payload.integrations && payload.integrations.length > 0 ? payload.integrations : undefined,
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

  const selectedDepartment = departments.find((d) => d.id === payload.department);
  const selectedIntegrations = integrations.filter((i) => (payload.integrations ?? []).includes(i.id));

  return (
    <div className="space-y-6 max-w-3xl mx-auto">
      <div>
        <Link href="/process-agents" className="text-xs text-text-muted hover:text-primary transition-colors">
          ← Back to Process Agents
        </Link>
        <h1 className="text-lg font-semibold text-on-surface mt-1">New Process Agent</h1>
        <p className="text-xs text-text-muted mt-0.5">{STEP_HINTS[STEPS[step]]}</p>
      </div>

      <StepIndicator current={step} onJump={setStep} />

      <Card className="p-6">
        {/* ── Step 0: Basic ── */}
        {step === 0 && (
          <div className="space-y-4">
            <CardHeader title="Basic" hint="Every process agent belongs to a department." />
            <Field label="Department *">
              {departmentsError ? (
                <p className="text-sm text-bad">{departmentsError}</p>
              ) : (
                <select
                  value={payload.department || ""}
                  onChange={(e) => setPayload((p) => ({ ...p, department: Number(e.target.value) }))}
                  disabled={departmentsLoading}
                  className={inputCls}
                >
                  <option value="">{departmentsLoading ? "Loading…" : "— select a department —"}</option>
                  {departments.map((d) => (
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
            <CardHeader title="Voice" hint="How this process communicates and where call events land." />
            <Field label="Communication Type">
              <select
                value={payload.voice?.communication_type ?? ""}
                onChange={(e) => updateVoice({ communication_type: e.target.value })}
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
            <div className="grid sm:grid-cols-2 gap-4">
              <Field label="Bot Name">
                <input
                  type="text"
                  value={getStr(payload.voice, "bot_name")}
                  onChange={(e) => updateVoice({ bot_name: e.target.value })}
                  className={inputCls}
                />
              </Field>
              <Field label="Bot ID">
                <input
                  type="text"
                  value={getStr(payload.voice, "bot_id")}
                  onChange={(e) => updateVoice({ bot_id: e.target.value })}
                  className={inputCls}
                />
              </Field>
            </div>
            <Field label="API URL">
              <input
                type="text"
                value={getStr(payload.voice, "api_url")}
                onChange={(e) => updateVoice({ api_url: e.target.value })}
                placeholder="https://…"
                className={inputCls}
              />
            </Field>
            <div>
              <p className="text-xs font-medium text-text-muted mb-1.5">
                Webhook Schema <span className="font-normal">— fields the platform expects back from the voice platform</span>
              </p>
              <div className="grid sm:grid-cols-2 gap-3">
                {WEBHOOK_SCHEMA_FIELDS.map((key) => (
                  <label key={key} className="flex flex-col gap-1">
                    <span className="text-xs text-text-muted capitalize">{key}</span>
                    <input
                      type="text"
                      value={getStr(payload.voice?.webhook_schema as Record<string, unknown> | undefined, key)}
                      onChange={(e) => updateWebhookSchema(key, e.target.value)}
                      placeholder={key}
                      className={inputCls}
                    />
                  </label>
                ))}
              </div>
            </div>
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
          </div>
        )}

        {/* ── Step 3: Business Rules ── */}
        {step === 3 && (
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
              <p className="text-sm font-semibold text-on-surface mb-2">Callback</p>
              <div className="grid sm:grid-cols-4 gap-3">
                <Field label="Variable">
                  <input
                    type="text"
                    value={getStr(payload.business_rules?.callback, "variable")}
                    onChange={(e) => updateCallback({ variable: e.target.value })}
                    placeholder="outcome"
                    className={inputCls}
                  />
                </Field>
                <Field label="Operator">
                  <select
                    value={getStr(payload.business_rules?.callback, "operator")}
                    onChange={(e) => updateCallback({ operator: e.target.value })}
                    className={inputCls}
                  >
                    <option value="">— select —</option>
                    {CALLBACK_OPERATORS.map((op) => (
                      <option key={op} value={op}>
                        {op}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Value">
                  <input
                    type="text"
                    value={getStr(payload.business_rules?.callback, "value")}
                    onChange={(e) => updateCallback({ value: e.target.value })}
                    placeholder="Callback Requested"
                    className={inputCls}
                  />
                </Field>
                <Field label="Delay (minutes)">
                  <input
                    type="number"
                    value={getNum(payload.business_rules?.callback, "delay_minutes")}
                    onChange={(e) => updateCallback({ delay_minutes: toNumOrUndefined(e.target.value) })}
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

        {/* ── Step 4: Integrations ── */}
        {step === 4 && (
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
                    className="flex items-center gap-3 p-3 rounded-lg border border-border bg-surface-container cursor-pointer"
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

        {/* ── Step 5: QA ── */}
        {step === 5 && (
          <div className="space-y-4">
            <CardHeader title="QA" hint="Automated checks run against every execution's transcript." />
            <div className="space-y-2">
              {QA_FIELDS.map((f) => (
                <label
                  key={f.key}
                  className="flex items-center gap-3 p-3 rounded-lg border border-border bg-surface-container cursor-pointer"
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

        {/* ── Step 6: Analytics ── */}
        {step === 6 && (
          <div className="space-y-4">
            <CardHeader title="Analytics" hint="Custom variables to surface on the dashboard. Optional." />
            <VariableRowsEditor
              rows={payload.analytics?.custom_variables ?? []}
              onChange={setCustomVariables}
              simple
            />
          </div>
        )}

        {/* ── Step 7: Review ── */}
        {step === 7 && (
          <div className="space-y-5">
            <CardHeader title="Review" hint="Confirm the configuration, then generate the process." />

            <ReviewSection title="Basic" onEdit={() => setStep(0)}>
              <ReviewRow label="Department" value={selectedDepartment?.name ?? String(payload.department || "—")} />
              <ReviewRow label="Name" value={payload.name || "—"} />
              <ReviewRow label="Description" value={payload.description || "—"} />
            </ReviewSection>

            <ReviewSection title="Voice" onEdit={() => setStep(1)}>
              <ReviewRow label="Communication Type" value={payload.voice?.communication_type || "—"} />
              <ReviewRow label="Bot Name" value={getStr(payload.voice, "bot_name") || "—"} />
              <ReviewRow label="Bot ID" value={getStr(payload.voice, "bot_id") || "—"} />
              <ReviewRow label="API URL" value={getStr(payload.voice, "api_url") || "—"} />
            </ReviewSection>

            <ReviewSection title="Lead Source" onEdit={() => setStep(2)}>
              <ReviewRow label="Type" value={payload.lead_source?.type || "—"} />
              <ReviewRow label="Notes" value={getStr(payload.lead_source?.configuration, "notes") || "—"} />
            </ReviewSection>

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
                label="Callback"
                value={
                  payload.business_rules?.callback
                    ? `${getStr(payload.business_rules.callback, "variable") || "—"} ${
                        getStr(payload.business_rules.callback, "operator") || "—"
                      } ${getStr(payload.business_rules.callback, "value") || "—"}, delay ${
                        getStr(payload.business_rules.callback, "delay_minutes") || "—"
                      }m`
                    : "—"
                }
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

            <ReviewSection title="QA" onEdit={() => setStep(5)}>
              <ReviewRow
                label="Enabled checks"
                value={
                  QA_FIELDS.filter((f) => getBool(payload.qa, f.key))
                    .map((f) => f.label)
                    .join(", ") || "None"
                }
              />
            </ReviewSection>

            <ReviewSection title="Analytics" onEdit={() => setStep(6)}>
              <ReviewRow
                label="Custom Variables"
                value={
                  (payload.analytics?.custom_variables ?? []).filter((v) => v.key.trim()).length > 0
                    ? (payload.analytics?.custom_variables ?? [])
                        .filter((v) => v.key.trim())
                        .map((v) => v.key)
                        .join(", ")
                    : "—"
                }
              />
            </ReviewSection>

            {submitError && (
              <div className="text-sm text-bad bg-bad/10 border border-bad/30 rounded-lg px-4 py-2">{submitError}</div>
            )}

            <div className="flex justify-end">
              <button
                type="button"
                onClick={handleGenerate}
                disabled={submitting}
                className="px-5 py-2.5 rounded-lg bg-primary text-on-primary text-sm font-medium hover:bg-primary-container disabled:opacity-60 transition-colors flex items-center gap-2"
              >
                {submitting && (
                  <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                  </svg>
                )}
                {submitting ? "Generating…" : "Generate Process"}
              </button>
            </div>
          </div>
        )}

        {/* ── Back / Next (all steps except Review, which has its own submit button) ── */}
        {step !== 7 && (
          <div className="flex items-center justify-between pt-6 mt-6 border-t border-border">
            <button
              type="button"
              onClick={goBack}
              disabled={step === 0}
              className="text-sm text-text-muted hover:text-on-surface disabled:opacity-40 transition-colors"
            >
              Back
            </button>
            <button
              type="button"
              onClick={goNext}
              disabled={!canProceed}
              className="px-5 py-2 rounded-lg bg-primary text-on-primary text-sm font-medium hover:bg-primary-container disabled:opacity-40 transition-colors"
            >
              Next
            </button>
          </div>
        )}
      </Card>
    </div>
  );
}

// ── Review helpers ───────────────────────────────────────────────────────

function ReviewSection({ title, onEdit, children }: { title: string; onEdit: () => void; children: React.ReactNode }) {
  return (
    <div className="border border-border rounded-lg p-4 bg-surface-container">
      <div className="flex items-center justify-between mb-2">
        <p className="text-sm font-semibold text-on-surface">{title}</p>
        <button type="button" onClick={onEdit} className="text-xs text-primary hover:underline">
          Edit
        </button>
      </div>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function ReviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start gap-2 text-sm">
      <span className="text-text-muted min-w-[140px]">{label}</span>
      <span className="text-on-surface break-words">{value}</span>
    </div>
  );
}
