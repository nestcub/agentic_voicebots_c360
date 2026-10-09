import { useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  Bot,
  Braces,
  ChartColumn,
  ClipboardCheck,
  Inbox,
  MessageSquare,
  Pencil,
  Plug,
  Plus,
  Webhook,
  type LucideIcon,
} from "lucide-react";
import { Card } from "@/components/Card";
import { Button, buttonVariants } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { ActiveBadge } from "@/components/StatusBadge";
import type { Integration, JourneyEdge, JourneyNode, ProcessAgentDetail, ProcessAgentVariable } from "@/lib/types";
import {
  attachProcessAgentIntegration,
  createProcessAgentVariable,
  deleteProcessAgentVariable,
  detachProcessAgentIntegration,
  listIntegrations,
  updateProcessAgentAnalyticsStats,
  updateProcessAgentOmnichannel,
  updateProcessAgentQaConfig,
  updateProcessAgentVariable,
  updateProcessAgentWebhook,
  type OmnichannelConfigWrite,
  type ProcessAgentVariableWrite,
} from "@/lib/telehubApi";
import {
  COMMUNICATION_TYPE_LABELS,
  QA_FIELDS,
  STAT_FIELDS,
  errorMessage,
  getConfigBool,
  WHATSAPP_TEMPLATES,
} from "./shared";

function SettingsRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start gap-2 text-sm">
      <span className="text-muted-foreground min-w-40">{label}</span>
      <span className="text-foreground break-words">{value}</span>
    </div>
  );
}

function SettingsSection({
  title,
  hint,
  icon: Icon,
  actions,
  children,
}: {
  title: string;
  hint?: string;
  icon?: LucideIcon;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card className="p-5 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          {Icon && (
            <span className="w-9 h-9 shrink-0 rounded-lg bg-accent text-primary flex items-center justify-center">
              <Icon className="w-4 h-4" />
            </span>
          )}
          <div className="min-w-0">
            <p className="text-base font-semibold text-foreground">{title}</p>
            {hint && <p className="text-xs text-muted-foreground mt-0.5">{hint}</p>}
          </div>
        </div>
        {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
      </div>
      <div className="space-y-2">{children}</div>
    </Card>
  );
}

function EmptySection({ label }: { label: string }) {
  return <p className="text-sm text-muted-foreground">{label}</p>;
}

function EditButton({ onClick }: { onClick: () => void }) {
  return (
    <Button variant="outline" size="sm" onClick={onClick}>
      <Pencil /> Edit
    </Button>
  );
}

function SaveCancelButtons({
  onSave,
  onCancel,
  saving,
}: {
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
}) {
  return (
    <>
      <Button variant="outline" size="sm" onClick={onCancel} disabled={saving}>
        Cancel
      </Button>
      <Button size="sm" onClick={onSave} disabled={saving}>
        {saving && <Spinner />}
        Save
      </Button>
    </>
  );
}

// ── Voice bot (read-only — managed on the global /bots page) ────────────

function VoiceBotSection({ agent }: { agent: ProcessAgentDetail }) {
  const bot = agent.bot_journeys[0]?.voice_bot ?? null;

  return (
    <SettingsSection
      icon={Bot}
      title="Voice"
      hint="Managed on the Voicebots page"
      actions={
        <Link href="/bots" className={buttonVariants({ variant: "outline", size: "sm" })}>
          Manage bots <ArrowRight />
        </Link>
      }
    >
      {bot ? (
        <div className="rounded-lg border border-border p-3">
          <p className="text-sm font-medium text-foreground">{bot.label || bot.bot_name || `Voice Bot ${bot.id}`}</p>
          <div className="mt-1 space-y-0.5 text-xs text-muted-foreground">
            {bot.communication_type && (
              <p>{COMMUNICATION_TYPE_LABELS[bot.communication_type] || bot.communication_type}</p>
            )}
            <p>
              {bot.bot_name || "—"}
              {bot.bot_id && <span className="ml-1">({bot.bot_id})</span>}
            </p>
            {bot.dids.length > 0 && <p>DIDs: {bot.dids.join(", ")}</p>}
            {bot.api_url && <p className="font-mono break-all">{bot.api_url}</p>}
          </div>
        </div>
      ) : (
        <EmptySection label="No voice bot attached to this agent." />
      )}
    </SettingsSection>
  );
}

// ── QA toggles ───────────────────────────────────────────────────────────

function QaSection({
  agentId,
  qaConfig,
  journeyLoading,
  hasJourneyData,
  onSaved,
}: {
  agentId: number;
  qaConfig: Record<string, unknown> | undefined;
  journeyLoading: boolean;
  hasJourneyData: boolean;
  onSaved: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function startEditing() {
    setDraft(Object.fromEntries(QA_FIELDS.map((f) => [f.key, getConfigBool(qaConfig, f.key)])));
    setError(null);
    setEditing(true);
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await updateProcessAgentQaConfig(agentId, draft);
      onSaved();
      setEditing(false);
    } catch (e) {
      setError(errorMessage(e, "Failed to save QA settings"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <SettingsSection
      icon={ClipboardCheck}
      title="QA"
      hint="Automated checks run against every execution's transcript"
      actions={
        journeyLoading && !hasJourneyData ? undefined : editing ? (
          <SaveCancelButtons onSave={handleSave} onCancel={() => setEditing(false)} saving={saving} />
        ) : (
          <EditButton onClick={startEditing} />
        )
      }
    >
      {journeyLoading && !hasJourneyData ? (
        <div className="h-16 bg-muted/50 rounded-lg animate-pulse" />
      ) : (
        <div className="space-y-2">
          {error && <p className="text-xs text-bad">{error}</p>}
          {QA_FIELDS.map((f) => (
            <div
              key={f.key}
              className="flex items-start justify-between gap-3 p-3 rounded-lg border border-border bg-muted/50"
            >
              <div>
                <p className="text-sm font-medium text-foreground">{f.label}</p>
                <p className="text-xs text-muted-foreground">{f.hint}</p>
              </div>
              {editing ? (
                <input
                  type="checkbox"
                  checked={Boolean(draft[f.key])}
                  onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.checked }))}
                  className="shrink-0 mt-0.5 h-4 w-4 accent-primary"
                />
              ) : getConfigBool(qaConfig, f.key) ? (
                <span className="shrink-0 text-xs font-medium px-2 py-0.5 rounded-full bg-ok/15 text-ok">
                  Enabled
                </span>
              ) : (
                <span className="shrink-0 text-muted-foreground text-xs">Off</span>
              )}
            </div>
          ))}
        </div>
      )}
    </SettingsSection>
  );
}

// ── Analytics stat toggles ───────────────────────────────────────────────

function AnalyticsStatsSection({
  agentId,
  analyticsStats,
  onSaved,
}: {
  agentId: number;
  analyticsStats: Record<string, boolean>;
  onSaved: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const enabledStats = STAT_FIELDS.filter((f) => analyticsStats?.[f.key] === true);

  function startEditing() {
    setDraft(Object.fromEntries(STAT_FIELDS.map((f) => [f.key, analyticsStats?.[f.key] === true])));
    setError(null);
    setEditing(true);
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await updateProcessAgentAnalyticsStats(agentId, draft);
      onSaved();
      setEditing(false);
    } catch (e) {
      setError(errorMessage(e, "Failed to save stat tiles"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <SettingsSection
      icon={ChartColumn}
      title="Analytics — Stats & Summaries"
      hint={`${enabledStats.length} of ${STAT_FIELDS.length} enabled`}
      actions={
        editing ? (
          <SaveCancelButtons onSave={handleSave} onCancel={() => setEditing(false)} saving={saving} />
        ) : (
          <EditButton onClick={startEditing} />
        )
      }
    >
      {error && <p className="text-xs text-bad">{error}</p>}
      {editing ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {STAT_FIELDS.map((f) => (
            <label key={f.key} className="flex items-center gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                checked={Boolean(draft[f.key])}
                onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.checked }))}
                className="h-4 w-4 accent-primary"
              />
              {f.label}
            </label>
          ))}
        </div>
      ) : enabledStats.length === 0 ? (
        <EmptySection label="No stat tiles enabled." />
      ) : (
        <div className="flex flex-wrap gap-2">
          {enabledStats.map((f) => (
            <span key={f.key} className="text-xs font-medium px-2.5 py-1 rounded-full bg-primary/10 text-primary">
              {f.label}
            </span>
          ))}
        </div>
      )}
    </SettingsSection>
  );
}

// ── Dispositions / Variables (CRUD) ─────────────────────────────────────

const VARIABLE_TYPE_OPTIONS = ["string", "number", "boolean", "date"];

function emptyVariableDraft(): ProcessAgentVariableWrite {
  return { key: "", type: "string", default_value: "", label: "", required: false, source: "business_rules" };
}

function VariableRowForm({
  draft,
  onChange,
}: {
  draft: ProcessAgentVariableWrite;
  onChange: (draft: ProcessAgentVariableWrite) => void;
}) {
  return (
    <tr>
      <td className="py-1.5 pr-4">
        <input
          value={draft.key ?? ""}
          onChange={(e) => onChange({ ...draft, key: e.target.value })}
          placeholder="variable_key"
          className="w-full px-2 py-1 rounded border border-border bg-surface text-xs font-mono"
        />
      </td>
      <td className="py-1.5 pr-4">
        <select
          value={draft.source ?? "business_rules"}
          onChange={(e) => onChange({ ...draft, source: e.target.value as ProcessAgentVariableWrite["source"] })}
          className="w-full px-2 py-1 rounded border border-border bg-surface text-xs"
        >
          <option value="business_rules">Business Rules</option>
          <option value="analytics">Analytics</option>
        </select>
      </td>
      <td className="py-1.5 pr-4">
        <select
          value={draft.type ?? "string"}
          onChange={(e) => onChange({ ...draft, type: e.target.value })}
          className="w-full px-2 py-1 rounded border border-border bg-surface text-xs"
        >
          {VARIABLE_TYPE_OPTIONS.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </td>
      <td className="py-1.5 pr-4">
        <input
          value={draft.default_value ?? ""}
          onChange={(e) => onChange({ ...draft, default_value: e.target.value })}
          className="w-full px-2 py-1 rounded border border-border bg-surface text-xs"
        />
      </td>
      <td className="py-1.5 pr-4">
        <input
          value={draft.label ?? ""}
          onChange={(e) => onChange({ ...draft, label: e.target.value })}
          className="w-full px-2 py-1 rounded border border-border bg-surface text-xs"
        />
      </td>
      <td className="py-1.5 pr-4">
        <input
          type="checkbox"
          checked={Boolean(draft.required)}
          onChange={(e) => onChange({ ...draft, required: e.target.checked })}
          className="h-4 w-4 accent-primary"
        />
      </td>
    </tr>
  );
}

function VariablesSection({
  agentId,
  variables,
  onSaved,
}: {
  agentId: number;
  variables: ProcessAgentVariable[];
  onSaved: () => void;
}) {
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<ProcessAgentVariableWrite>(emptyVariableDraft());
  const [adding, setAdding] = useState(false);
  const [newDraft, setNewDraft] = useState<ProcessAgentVariableWrite>(emptyVariableDraft());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function startEdit(v: ProcessAgentVariable) {
    setError(null);
    setEditingId(v.id);
    setEditDraft({
      key: v.key,
      type: v.type,
      default_value: v.default_value,
      label: v.label,
      required: v.required,
      source: v.source,
    });
  }

  async function saveEdit(id: number) {
    setSaving(true);
    setError(null);
    try {
      await updateProcessAgentVariable(agentId, id, editDraft);
      onSaved();
      setEditingId(null);
    } catch (e) {
      setError(errorMessage(e, "Failed to update variable"));
    } finally {
      setSaving(false);
    }
  }

  const [pendingDelete, setPendingDelete] = useState<ProcessAgentVariable | null>(null);

  function handleDelete(v: ProcessAgentVariable) {
    setPendingDelete(v);
  }

  async function confirmDelete() {
    const v = pendingDelete;
    if (!v) return;
    setSaving(true);
    setError(null);
    try {
      await deleteProcessAgentVariable(agentId, v.id);
      onSaved();
    } catch (e) {
      setError(errorMessage(e, "Failed to remove variable"));
    } finally {
      setSaving(false);
      setPendingDelete(null);
    }
  }

  async function handleCreate() {
    setSaving(true);
    setError(null);
    try {
      await createProcessAgentVariable(agentId, newDraft);
      onSaved();
      setAdding(false);
      setNewDraft(emptyVariableDraft());
    } catch (e) {
      setError(errorMessage(e, "Failed to add variable"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <SettingsSection
      icon={Braces}
      title="Dispositions / Variables"
      hint={`${variables.length} configured`}
      actions={
        !adding && (
          <button
            onClick={() => {
              setError(null);
              setNewDraft(emptyVariableDraft());
              setAdding(true);
            }}
            className={buttonVariants({ size: "sm" })}
          >
            <Plus /> Add variable
          </button>
        )
      }
    >
      {error && <p className="text-xs text-bad">{error}</p>}
      {variables.length === 0 && !adding && <EmptySection label="No variables configured." />}
      {(variables.length > 0 || adding) && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground border-b border-border">
                <th className="py-1.5 pr-4 font-medium">Key</th>
                <th className="py-1.5 pr-4 font-medium">Source</th>
                <th className="py-1.5 pr-4 font-medium">Type</th>
                <th className="py-1.5 pr-4 font-medium">Default</th>
                <th className="py-1.5 pr-4 font-medium">Label</th>
                <th className="py-1.5 pr-4 font-medium">Required</th>
                <th className="py-1.5 pr-4 font-medium" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {variables.map((v) =>
                editingId === v.id ? (
                  <VariableRowForm key={v.id} draft={editDraft} onChange={setEditDraft} />
                ) : (
                  <tr key={v.id}>
                    <td className="py-1.5 pr-4 text-foreground font-mono text-xs">{v.key}</td>
                    <td className="py-1.5 pr-4 text-muted-foreground">
                      {v.source === "analytics" ? "Analytics" : "Business Rules"}
                    </td>
                    <td className="py-1.5 pr-4 text-muted-foreground">{v.type}</td>
                    <td className="py-1.5 pr-4 text-muted-foreground">{v.default_value || "—"}</td>
                    <td className="py-1.5 pr-4 text-muted-foreground">{v.label || "—"}</td>
                    <td className="py-1.5 pr-4 text-muted-foreground">{v.required ? "Yes" : "No"}</td>
                    <td className="py-1.5 pr-4" />
                  </tr>
                )
              )}
              {editingId !== null &&
                (() => {
                  const v = variables.find((row) => row.id === editingId);
                  if (!v) return null;
                  return (
                    <tr>
                      <td colSpan={7} className="pt-1 pb-2">
                        <div className="flex items-center gap-2">
                          <SaveCancelButtons
                            onSave={() => saveEdit(v.id)}
                            onCancel={() => setEditingId(null)}
                            saving={saving}
                          />
                        </div>
                      </td>
                    </tr>
                  );
                })()}
              {adding && (
                <>
                  <VariableRowForm draft={newDraft} onChange={setNewDraft} />
                  <tr>
                    <td colSpan={7} className="pt-1 pb-2">
                      <div className="flex items-center gap-2">
                        <SaveCancelButtons onSave={handleCreate} onCancel={() => setAdding(false)} saving={saving} />
                      </div>
                    </td>
                  </tr>
                </>
              )}
            </tbody>
          </table>
        </div>
      )}
      {!adding && variables.length > 0 && (
        <div className="flex flex-wrap gap-3 pt-1">
          {variables.map((v) =>
            editingId === v.id ? null : (
              <div key={v.id} className="flex items-center gap-1">
                <button onClick={() => startEdit(v)} className="text-xs text-primary hover:underline">
                  Edit {v.key}
                </button>
                <span className="text-muted-foreground">·</span>
                <button onClick={() => handleDelete(v)} className="text-xs text-bad hover:underline">
                  Remove
                </button>
              </div>
            )
          )}
        </div>
      )}
      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(o) => !o && setPendingDelete(null)}
        title={`Remove variable "${pendingDelete?.key ?? ""}"?`}
        description="Executions stop collecting this variable from the next call outcome."
        busy={saving}
        onConfirm={confirmDelete}
      />
    </SettingsSection>
  );
}

// ── Webhooks ─────────────────────────────────────────────────────────────

function WebhookRow({
  agentId,
  webhook,
  onSaved,
}: {
  agentId: number;
  webhook: ProcessAgentDetail["webhooks"][number];
  onSaved: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(webhook.name);
  const [statusValue, setStatusValue] = useState(webhook.status);
  const [schemaText, setSchemaText] = useState(JSON.stringify(webhook.schema, null, 2));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function startEditing() {
    setName(webhook.name);
    setStatusValue(webhook.status);
    setSchemaText(JSON.stringify(webhook.schema, null, 2));
    setError(null);
    setEditing(true);
  }

  async function handleSave() {
    let schema: Record<string, unknown>;
    try {
      schema = schemaText.trim() ? JSON.parse(schemaText) : {};
    } catch {
      setError("Schema must be valid JSON.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await updateProcessAgentWebhook(agentId, webhook.id, { name, status: statusValue, schema });
      onSaved();
      setEditing(false);
    } catch (e) {
      setError(errorMessage(e, "Failed to update webhook"));
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <div className="rounded-lg border border-border p-3">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-medium text-foreground">{webhook.name}</p>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">{webhook.status}</span>
            <EditButton onClick={startEditing} />
          </div>
        </div>
        {webhook.public_url ? (
          <p className="text-xs text-foreground mt-0.5 break-all font-mono">{webhook.public_url}</p>
        ) : (
          <>
            <p className="text-xs text-muted-foreground mt-0.5 break-all font-mono">{webhook.url}</p>
            <p className="text-[11px] text-muted-foreground mt-1">
              No public URL — run <code className="font-mono">ngrok http 8000</code> locally to get one
              for pasting into the voice platform.
            </p>
          </>
        )}
        {webhook.schema && Object.keys(webhook.schema).length > 0 && (
          <details className="mt-2">
            <summary className="cursor-pointer text-[11px] text-primary select-none">webhook schema</summary>
            <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words bg-background rounded p-2 text-[10px] text-muted-foreground">
              {JSON.stringify(webhook.schema, null, 2)}
            </pre>
          </details>
        )}
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border p-3 space-y-2">
      {error && <p className="text-xs text-bad">{error}</p>}
      <div className="flex items-center gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="flex-1 min-w-0 px-2.5 py-1.5 rounded-md border border-input bg-card shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 text-sm"
        />
        <select
          value={statusValue}
          onChange={(e) => setStatusValue(e.target.value)}
          className="px-2.5 py-1.5 rounded-md border border-input bg-card shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 text-sm"
        >
          <option value="active">active</option>
          <option value="disabled">disabled</option>
        </select>
      </div>
      <div>
        <p className="text-xs font-medium text-muted-foreground mb-1">Schema (JSON)</p>
        <textarea
          value={schemaText}
          onChange={(e) => setSchemaText(e.target.value)}
          rows={5}
          className="w-full px-2.5 py-1.5 rounded-md border border-input bg-card shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 text-xs font-mono"
        />
      </div>
      <SaveCancelButtons onSave={handleSave} onCancel={() => setEditing(false)} saving={saving} />
    </div>
  );
}

// ── Omnichannel ──────────────────────────────────────────────────────────

function OmnichannelSection({
  agentId,
  omnichannel,
  onSaved,
}: {
  agentId: number;
  omnichannel: ProcessAgentDetail["omnichannel"];
  onSaved: () => void;
}) {
  // T1 falls back to the pre-POC single curl until it's saved as T1.
  function initialCurls(): Record<string, string> {
    const curls = { ...(omnichannel?.whatsapp_curls ?? {}) };
    if (!curls.T1?.trim() && omnichannel?.whatsapp_curl) curls.T1 = omnichannel.whatsapp_curl;
    return curls;
  }

  const [editing, setEditing] = useState(false);
  const [channel, setChannel] = useState(omnichannel?.channel ?? "");
  const [variablesText, setVariablesText] = useState((omnichannel?.variables ?? []).join(", "));
  const [autoSend, setAutoSend] = useState(omnichannel?.auto_send ?? false);
  const [curls, setCurls] = useState<Record<string, string>>(initialCurls);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function startEditing() {
    setChannel(omnichannel?.channel ?? "");
    setVariablesText((omnichannel?.variables ?? []).join(", "));
    setAutoSend(omnichannel?.auto_send ?? false);
    setCurls(initialCurls());
    setError(null);
    setEditing(true);
  }

  async function handleSave() {
    const data: OmnichannelConfigWrite = {
      channel,
      variables: variablesText
        .split(",")
        .map((v) => v.trim())
        .filter(Boolean),
      auto_send: autoSend,
      whatsapp_curls: Object.fromEntries(WHATSAPP_TEMPLATES.map((t) => [t.key, curls[t.key]?.trim() ?? ""])),
      // Kept in step with T1 so clearing T1 doesn't fall back to a stale curl.
      whatsapp_curl: curls.T1?.trim() ?? "",
    };
    setSaving(true);
    setError(null);
    try {
      await updateProcessAgentOmnichannel(agentId, data);
      onSaved();
      setEditing(false);
    } catch (e) {
      setError(errorMessage(e, "Failed to save omnichannel settings"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <SettingsSection
      icon={MessageSquare}
      title="Omnichannel"
      hint={omnichannel ? undefined : "Not configured"}
      actions={
        editing ? (
          <SaveCancelButtons onSave={handleSave} onCancel={() => setEditing(false)} saving={saving} />
        ) : (
          <EditButton onClick={startEditing} />
        )
      }
    >
      {error && <p className="text-xs text-bad">{error}</p>}
      {editing ? (
        <div className="space-y-3">
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Channel</label>
            <select
              value={channel}
              onChange={(e) => setChannel(e.target.value)}
              className="w-full max-w-xs px-2.5 py-1.5 rounded-md border border-input bg-card shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 text-sm"
            >
              <option value="">None</option>
              <option value="whatsapp">WhatsApp</option>
              <option value="sms">SMS</option>
              <option value="email">Email</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Variables to send (comma-separated)</label>
            <input
              value={variablesText}
              onChange={(e) => setVariablesText(e.target.value)}
              className="w-full px-2.5 py-1.5 rounded-md border border-input bg-card shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 text-sm"
            />
          </div>
          {channel === "whatsapp" && (
            <>
              <label className="flex items-center gap-2 text-sm text-foreground">
                <input type="checkbox" checked={autoSend} onChange={(e) => setAutoSend(e.target.checked)} />
                Auto-send WhatsApp after each inbound call
              </label>
              {WHATSAPP_TEMPLATES.map((t) => (
                <div key={t.key}>
                  <label className="block text-xs font-medium text-foreground">{t.label}</label>
                  <p className="text-[11px] text-muted-foreground mb-1">{t.when}</p>
                  <textarea
                    value={curls[t.key] ?? ""}
                    onChange={(e) => setCurls((c) => ({ ...c, [t.key]: e.target.value }))}
                    rows={4}
                    placeholder="Paste the template's curl command"
                    spellCheck={false}
                    className="w-full px-2.5 py-1.5 rounded-md border border-input bg-card shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 text-xs font-mono"
                  />
                </div>
              ))}
            </>
          )}
        </div>
      ) : !omnichannel ? (
        <EmptySection label="No omnichannel forwarding configured." />
      ) : (
        <div className="space-y-1.5">
          <SettingsRow
            label="Channel"
            value={COMMUNICATION_TYPE_LABELS[omnichannel.channel] || omnichannel.channel || "—"}
          />
          <SettingsRow
            label="Variables to send"
            value={omnichannel.variables.length > 0 ? omnichannel.variables.join(", ") : "—"}
          />
          {omnichannel.channel === "whatsapp" && (
            <>
              <SettingsRow label="Auto-send" value={omnichannel.auto_send ? "On" : "Off"} />
              <div className="space-y-2 pt-1">
                {WHATSAPP_TEMPLATES.map((t) => {
                  const summary = omnichannel.whatsapp_templates?.[t.key];
                  return (
                    <div key={t.key} className="rounded-lg border border-border px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-medium text-foreground">{t.label}</p>
                        {!summary?.configured ? (
                          <span className="text-[11px] px-2 py-0.5 rounded-full bg-text-muted/15 text-muted-foreground">
                            Not configured
                          </span>
                        ) : summary.error ? (
                          <span className="text-[11px] px-2 py-0.5 rounded-full bg-bad/15 text-bad">Invalid curl</span>
                        ) : (
                          <span className="text-[11px] px-2 py-0.5 rounded-full bg-ok/15 text-ok">Ready</span>
                        )}
                      </div>
                      <p className="text-[11px] text-muted-foreground mt-0.5">{t.when}</p>
                      {summary?.configured &&
                        (summary.error ? (
                          <p className="text-xs text-bad mt-1">{summary.error}</p>
                        ) : (
                          <p className="text-xs text-foreground mt-1">
                            <span className="font-mono">{summary.template_title || "—"}</span>
                            {summary.params.length > 0 && (
                              <span className="text-muted-foreground"> · params: {summary.params.join(", ")}</span>
                            )}
                          </p>
                        ))}
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      )}
    </SettingsSection>
  );
}

// ── Integrations ─────────────────────────────────────────────────────────

function IntegrationsSection({
  agentId,
  integrations,
  onSaved,
}: {
  agentId: number;
  integrations: ProcessAgentDetail["integrations"];
  onSaved: () => void;
}) {
  const [attaching, setAttaching] = useState(false);
  const [available, setAvailable] = useState<Integration[] | null>(null);
  const [selectedId, setSelectedId] = useState<number | "">("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function startAttaching() {
    setError(null);
    setAttaching(true);
    try {
      const all = await listIntegrations();
      const attachedIds = new Set(integrations.map((it) => it.integration));
      setAvailable(all.filter((it) => !attachedIds.has(it.id)));
    } catch (e) {
      setError(errorMessage(e, "Failed to load integrations"));
    }
  }

  async function handleAttach() {
    if (!selectedId) return;
    setSaving(true);
    setError(null);
    try {
      await attachProcessAgentIntegration(agentId, selectedId);
      onSaved();
      setAttaching(false);
      setSelectedId("");
    } catch (e) {
      setError(errorMessage(e, "Failed to attach integration"));
    } finally {
      setSaving(false);
    }
  }

  async function handleDetach(processIntegrationId: number) {
    setSaving(true);
    setError(null);
    try {
      await detachProcessAgentIntegration(agentId, processIntegrationId);
      onSaved();
    } catch (e) {
      setError(errorMessage(e, "Failed to remove integration"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <SettingsSection
      icon={Plug}
      title="Integrations"
      hint={`${integrations.length} configured`}
      actions={
        !attaching && (
          <button
            onClick={startAttaching}
            className={buttonVariants({ size: "sm" })}
          >
            <Plus /> Attach
          </button>
        )
      }
    >
      {error && <p className="text-xs text-bad">{error}</p>}
      {attaching && (
        <div className="flex items-center gap-2 p-3 rounded-lg border border-dashed border-border">
          {available === null ? (
            <span className="text-xs text-muted-foreground">Loading integrations…</span>
          ) : available.length === 0 ? (
            <span className="text-xs text-muted-foreground">No other integrations available to attach.</span>
          ) : (
            <select
              value={selectedId}
              onChange={(e) => setSelectedId(e.target.value ? Number(e.target.value) : "")}
              className="flex-1 min-w-0 px-2.5 py-1.5 rounded-md border border-input bg-card shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 text-sm"
            >
              <option value="">Select an integration…</option>
              {available.map((it) => (
                <option key={it.id} value={it.id}>
                  {it.name} ({it.type})
                </option>
              ))}
            </select>
          )}
          <SaveCancelButtons onSave={handleAttach} onCancel={() => setAttaching(false)} saving={saving} />
        </div>
      )}
      {integrations.length === 0 && !attaching && <EmptySection label="No integrations configured." />}
      {integrations.map((it) => (
        <div key={it.id} className="rounded-lg border border-border p-3 flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-foreground">{it.integration_name}</p>
            <span className="text-xs text-muted-foreground">{it.integration_type}</span>
          </div>
          <button
            onClick={() => handleDetach(it.id)}
            disabled={saving}
            className="text-xs text-bad hover:underline disabled:opacity-60"
          >
            Remove
          </button>
        </div>
      ))}
    </SettingsSection>
  );
}

// ── Settings tab ─────────────────────────────────────────────────────────

export function SettingsTab({
  agent,
  journeyData,
  journeyLoading,
  onToggleActive,
  toggling,
  toggleError,
  onAgentChanged,
  onJourneyChanged,
}: {
  agent: ProcessAgentDetail;
  journeyData: { nodes: JourneyNode[]; edges: JourneyEdge[] } | null;
  journeyLoading: boolean;
  onToggleActive: () => void;
  toggling: boolean;
  toggleError: string | null;
  onAgentChanged: () => void;
  onJourneyChanged: () => void;
}) {
  const qaConfig = journeyData?.nodes.find((n) => n.name === "QA")?.config;

  return (
    <div className="space-y-6">
      <Card className="p-5 flex items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <label htmlFor="agent-active" className="text-sm font-semibold text-foreground">
              Agent status
            </label>
            <ActiveBadge active={agent.is_active} />
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            {agent.is_active ? "This agent is active and can run." : "This agent is inactive and won't run."}
          </p>
          {toggleError && <p className="text-xs text-bad mt-1">{toggleError}</p>}
        </div>
        <div className="flex items-center gap-2">
          {toggling && <Spinner className="text-muted-foreground" />}
          <Switch
            id="agent-active"
            checked={agent.is_active}
            onCheckedChange={onToggleActive}
            disabled={toggling}
          />
        </div>
      </Card>

      <VoiceBotSection agent={agent} />

      <SettingsSection icon={Inbox} title="Lead Sources" hint={`${agent.lead_sources.length} configured`}>
        {agent.lead_sources.length === 0 && <EmptySection label="No lead sources configured." />}
        {agent.lead_sources.map((ls) => {
          const leadCount = Array.isArray((ls.configuration as { leads?: unknown[] })?.leads)
            ? (ls.configuration as { leads: unknown[] }).leads.length
            : null;
          return (
            <div key={ls.id} className="rounded-lg border border-border p-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium text-foreground">{ls.type}</p>
                {leadCount !== null && (
                  <span className="text-xs text-muted-foreground">{leadCount} lead{leadCount === 1 ? "" : "s"} stored</span>
                )}
              </div>
              <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-words bg-muted rounded-md p-2 text-[11px] text-muted-foreground font-mono">
                {JSON.stringify(ls.configuration, null, 2)}
              </pre>
            </div>
          );
        })}
        {agent.lead_sources.length > 0 && (
          <p className="text-xs text-muted-foreground">
            Dispatch calls to this lead source from the{" "}
            <span className="font-medium text-foreground">Runs</span> tab.
          </p>
        )}
      </SettingsSection>

      <QaSection
        agentId={agent.id}
        qaConfig={qaConfig}
        journeyLoading={journeyLoading}
        hasJourneyData={Boolean(journeyData)}
        onSaved={onJourneyChanged}
      />

      <AnalyticsStatsSection agentId={agent.id} analyticsStats={agent.analytics_stats} onSaved={onAgentChanged} />

      <VariablesSection agentId={agent.id} variables={agent.variables} onSaved={onAgentChanged} />

      <SettingsSection icon={Webhook} title="Webhooks" hint={`${agent.webhooks.length} configured`}>
        {agent.webhooks.length === 0 && <EmptySection label="No webhooks configured." />}
        {agent.webhooks.map((wh) => (
          <WebhookRow key={wh.id} agentId={agent.id} webhook={wh} onSaved={onAgentChanged} />
        ))}
      </SettingsSection>

      <OmnichannelSection agentId={agent.id} omnichannel={agent.omnichannel} onSaved={onAgentChanged} />

      <IntegrationsSection agentId={agent.id} integrations={agent.integrations} onSaved={onAgentChanged} />
    </div>
  );
}
