// Settings → Omnichannel: pick the channel (WhatsApp for now), add the template
// curls, and write the rules that choose which template a finished call sends.
// Backed by the /channel-templates/ and /channel-rules/ endpoints
// (services/telehub/apps/telehub/services/channel_config.py).
import { useCallback, useEffect, useState } from "react";
import { ArrowDown, ArrowUp, MessageSquare, Pencil, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import type {
  ChannelParamEntry,
  ChannelRule,
  ChannelRuleCheck,
  ChannelTemplate,
  ProcessAgentDetail,
} from "@/lib/types";
import {
  createChannelRule,
  createChannelTemplate,
  deleteChannelRule,
  deleteChannelTemplate,
  listChannelRules,
  listChannelTemplates,
  reorderChannelRules,
  updateChannelRule,
  updateChannelTemplate,
  updateProcessAgentOmnichannel,
} from "@/lib/telehubApi";
import { ChecksEditor, cleanChecks, describeChecks } from "./ChecksEditor";
import { EmptySection, INPUT_CLASS, SaveCancelButtons, SettingsSection } from "./SettingsPrimitives";
import { apiErrorText } from "./shared";

const VARIABLE_LIST_ID = "omnichannel-variable-keys";

function Badge({ tone, children }: { tone: "ok" | "bad" | "muted"; children: React.ReactNode }) {
  const cls =
    tone === "ok" ? "bg-ok/15 text-ok" : tone === "bad" ? "bg-bad/15 text-bad" : "bg-text-muted/15 text-muted-foreground";
  return <span className={`text-[11px] px-2 py-0.5 rounded-full whitespace-nowrap ${cls}`}>{children}</span>;
}

// ── Template form (add / edit + placeholder mapping) ─────────────────────

type ParamSource = { mode: "default" | "variable" | "fixed"; variable: string; fallback: string; fixed: string };

function sourceFromEntry(entry: ChannelParamEntry | undefined): ParamSource {
  if (entry && "fixed" in entry) return { mode: "fixed", variable: "", fallback: "", fixed: entry.fixed };
  if (entry && "variable" in entry) {
    return { mode: "variable", variable: entry.variable, fallback: entry.fallback ?? "", fixed: "" };
  }
  return { mode: "default", variable: "", fallback: "", fixed: "" };
}

function TemplateForm({
  agentId,
  template,
  onSaved,
  onCancel,
}: {
  agentId: number;
  template: ChannelTemplate | null;
  onSaved: (saved: ChannelTemplate, wasNew: boolean) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(template?.name ?? "");
  const [curl, setCurl] = useState("");
  const [missingFill, setMissingFill] = useState(template?.missing_fill ?? "");
  const [isActive, setIsActive] = useState(template?.is_active ?? true);
  const [sources, setSources] = useState<Record<string, ParamSource>>(() =>
    Object.fromEntries((template?.params ?? []).map((p) => [p.key, sourceFromEntry(template?.param_map?.[p.key])])),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function setSource(key: string, patch: Partial<ParamSource>) {
    setSources((s) => ({ ...s, [key]: { ...s[key], ...patch } }));
  }

  async function handleSave() {
    const paramMap: Record<string, ChannelParamEntry> = {};
    for (const [key, source] of Object.entries(sources)) {
      if (source.mode === "variable") {
        if (!source.variable.trim()) {
          setError(`Choose a variable for "${key}", or set it back to "Match by name".`);
          return;
        }
        paramMap[key] = {
          variable: source.variable.trim(),
          ...(source.fallback.trim() ? { fallback: source.fallback.trim() } : {}),
        };
      } else if (source.mode === "fixed") {
        paramMap[key] = { fixed: source.fixed };
      }
    }
    setSaving(true);
    setError(null);
    try {
      const body = {
        name: name.trim(),
        missing_fill: missingFill,
        is_active: isActive,
        ...(curl.trim() ? { curl: curl.trim() } : {}),
        ...(template ? { param_map: paramMap } : {}),
      };
      const saved = template
        ? await updateChannelTemplate(agentId, template.id, body)
        : await createChannelTemplate(agentId, body);
      onSaved(saved, !template);
    } catch (e) {
      setError(apiErrorText(e, "Failed to save template"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-lg border border-primary/40 p-3 space-y-3">
      {error && <p className="text-xs text-bad">{error}</p>}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Template name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="appointment_confirmation"
            maxLength={64}
            className={INPUT_CLASS}
          />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">
            If a variable is empty, send this instead
          </label>
          <input
            value={missingFill}
            onChange={(e) => setMissingFill(e.target.value)}
            placeholder="leave blank to hold the message until someone fills it in"
            maxLength={64}
            className={INPUT_CLASS}
          />
        </div>
      </div>
      <div>
        <label className="block text-xs text-muted-foreground mb-1">
          Template curl{template ? " (hidden for security — paste a new one only to replace it)" : ""}
        </label>
        <textarea
          value={curl}
          onChange={(e) => setCurl(e.target.value)}
          rows={4}
          placeholder="Paste the template's curl command"
          spellCheck={false}
          className={`${INPUT_CLASS} text-xs font-mono`}
        />
      </div>

      {template && template.params.length > 0 && (
        <div>
          <p className="text-xs font-medium text-foreground mb-1">Placeholders</p>
          <p className="text-[11px] text-muted-foreground mb-2">
            Decide where each placeholder in the curl gets its value. Only the variables used here are sent to the
            customer.
          </p>
          <div className="space-y-2">
            {template.params.map((p) => {
              const source = sources[p.key] ?? sourceFromEntry(undefined);
              return (
                <div key={p.key} className="grid grid-cols-1 sm:grid-cols-[10rem_11rem_1fr] gap-2 items-center">
                  <span className="text-xs font-mono text-foreground break-all">{p.key}</span>
                  <select
                    value={source.mode}
                    onChange={(e) => setSource(p.key, { mode: e.target.value as ParamSource["mode"] })}
                    className={INPUT_CLASS}
                  >
                    <option value="default">Match by name{p.placeholder ? ` (${p.placeholder})` : ""}</option>
                    <option value="variable">A variable</option>
                    <option value="fixed">Fixed text</option>
                  </select>
                  {source.mode === "variable" && (
                    <div className="flex gap-2">
                      <input
                        list={VARIABLE_LIST_ID}
                        value={source.variable}
                        onChange={(e) => setSource(p.key, { variable: e.target.value })}
                        placeholder="variable"
                        className={`${INPUT_CLASS} font-mono text-xs`}
                      />
                      <input
                        list={VARIABLE_LIST_ID}
                        value={source.fallback}
                        onChange={(e) => setSource(p.key, { fallback: e.target.value })}
                        placeholder="else use…"
                        className={`${INPUT_CLASS} font-mono text-xs`}
                      />
                    </div>
                  )}
                  {source.mode === "fixed" && (
                    <input
                      value={source.fixed}
                      onChange={(e) => setSource(p.key, { fixed: e.target.value })}
                      placeholder="text sent for every customer"
                      className={INPUT_CLASS}
                    />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
      {!template && (
        <p className="text-[11px] text-muted-foreground">
          After saving you can map each placeholder in the curl to a variable.
        </p>
      )}

      <label className="flex items-center gap-2 text-sm text-foreground">
        <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} className="h-4 w-4 accent-primary" />
        Active (inactive templates are never sent)
      </label>
      <div className="flex items-center gap-2">
        <SaveCancelButtons onSave={handleSave} onCancel={onCancel} saving={saving} />
      </div>
    </div>
  );
}

function TemplateCard({
  template,
  onEdit,
  onDelete,
}: {
  template: ChannelTemplate;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <div className="rounded-lg border border-border px-3 py-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <p className="text-sm font-medium text-foreground truncate">{template.name}</p>
          {!template.is_active && <Badge tone="muted">Inactive</Badge>}
          {template.error ? (
            <Badge tone="bad">Invalid curl</Badge>
          ) : template.configured ? (
            <Badge tone="ok">Ready</Badge>
          ) : (
            <Badge tone="muted">No curl</Badge>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <Button variant="outline" size="sm" onClick={onEdit}>
            <Pencil /> Edit
          </Button>
          <Button variant="outline" size="sm" onClick={onDelete} aria-label={`Delete ${template.name}`}>
            <Trash2 />
          </Button>
        </div>
      </div>
      {template.error ? (
        <p className="text-xs text-bad mt-1">{template.error}</p>
      ) : template.configured ? (
        <div className="mt-1 space-y-0.5">
          <p className="text-xs text-foreground">
            <span className="font-mono">{template.template_title || "—"}</span>
          </p>
          {template.params.length > 0 && (
            <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-[11px]">
              {template.params.map((p) => {
                const entry = template.param_map[p.key];
                const source =
                  entry && "fixed" in entry
                    ? `“${entry.fixed}”`
                    : entry && "variable" in entry
                      ? `${entry.variable}${entry.fallback ? ` (else ${entry.fallback})` : ""}`
                      : p.placeholder.replace(/^@/, "") === p.key || p.placeholder.startsWith("@")
                        ? p.placeholder.replace(/^@/, "")
                        : `fixed in curl: ${p.placeholder}`;
                return (
                  <div key={p.key} className="contents">
                    <dt className="font-mono text-muted-foreground">{p.key}</dt>
                    <dd className="text-foreground break-all">{source}</dd>
                  </div>
                );
              })}
            </dl>
          )}
          {template.missing_fill && (
            <p className="text-[11px] text-muted-foreground">Empty variables are sent as “{template.missing_fill}”.</p>
          )}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground mt-1">Paste a curl to make this template usable.</p>
      )}
    </div>
  );
}

// ── Rule form ────────────────────────────────────────────────────────────

function RuleForm({
  agentId,
  rule,
  templates,
  onSaved,
  onCancel,
}: {
  agentId: number;
  rule: ChannelRule | null;
  templates: ChannelTemplate[];
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [action, setAction] = useState<"send" | "skip">(rule?.action ?? "send");
  const [templateId, setTemplateId] = useState<number | "">(rule?.template ?? templates[0]?.id ?? "");
  const [match, setMatch] = useState<"all" | "any">(rule?.match ?? "all");
  const [checks, setChecks] = useState<ChannelRuleCheck[]>(rule?.checks ?? []);
  const [reason, setReason] = useState(rule?.reason ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    const cleaned = cleanChecks(checks);
    if (action === "send" && templateId === "") {
      setError("Choose which template to send.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const body = {
        action,
        template: action === "send" ? Number(templateId) : null,
        match,
        checks: cleaned,
        reason,
      };
      if (rule) await updateChannelRule(agentId, rule.id, body);
      else await createChannelRule(agentId, body);
      onSaved();
    } catch (e) {
      setError(apiErrorText(e, "Failed to save rule"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-lg border border-primary/40 p-3 space-y-3">
      {error && <p className="text-xs text-bad">{error}</p>}

      <ChecksEditor
        checks={checks}
        match={match}
        onChecks={setChecks}
        onMatch={setMatch}
        variableListId={VARIABLE_LIST_ID}
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Then</label>
          <select value={action} onChange={(e) => setAction(e.target.value as "send" | "skip")} className={INPUT_CLASS}>
            <option value="send">Send a template</option>
            <option value="skip">Send nothing (skip)</option>
          </select>
        </div>
        {action === "send" ? (
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Template</label>
            <select
              value={templateId}
              onChange={(e) => setTemplateId(e.target.value ? Number(e.target.value) : "")}
              className={INPUT_CLASS}
            >
              {templates.length === 0 && <option value="">Add a template first</option>}
              {templates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                  {t.is_active ? "" : " (inactive)"}
                </option>
              ))}
            </select>
          </div>
        ) : (
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Reason shown on the call</label>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="test call"
              maxLength={128}
              className={INPUT_CLASS}
            />
          </div>
        )}
      </div>
      <div className="flex items-center gap-2">
        <SaveCancelButtons onSave={handleSave} onCancel={onCancel} saving={saving} />
      </div>
    </div>
  );
}

// ── Section ──────────────────────────────────────────────────────────────

export function OmnichannelSection({ agent, onSaved }: { agent: ProcessAgentDetail; onSaved: () => void }) {
  const agentId = agent.id;
  const channel = agent.omnichannel?.channel ?? "";
  const autoSend = agent.omnichannel?.auto_send ?? false;
  const variableKeys = agent.variables.map((v) => v.key);

  const [templates, setTemplates] = useState<ChannelTemplate[] | null>(null);
  const [variablesSent, setVariablesSent] = useState<string[]>([]);
  const [rules, setRules] = useState<ChannelRule[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Which editor is open: a template id, "new-template", a rule id, "new-rule", or nothing.
  const [editingTemplate, setEditingTemplate] = useState<number | "new" | null>(null);
  const [editingRule, setEditingRule] = useState<number | "new" | null>(null);
  const [pendingDeleteTemplate, setPendingDeleteTemplate] = useState<ChannelTemplate | null>(null);
  const [pendingDeleteRule, setPendingDeleteRule] = useState<ChannelRule | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [templateList, ruleList] = await Promise.all([listChannelTemplates(agentId), listChannelRules(agentId)]);
      setTemplates(templateList.templates);
      setVariablesSent(templateList.variables_sent);
      setRules(ruleList);
    } catch (e) {
      setError(apiErrorText(e, "Failed to load templates and rules"));
    }
  }, [agentId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function saveHeader(patch: { channel?: string; auto_send?: boolean }) {
    setBusy(true);
    setError(null);
    try {
      await updateProcessAgentOmnichannel(agentId, patch);
      onSaved();
    } catch (e) {
      setError(apiErrorText(e, "Failed to save omnichannel settings"));
    } finally {
      setBusy(false);
    }
  }

  async function confirmDeleteTemplate() {
    const target = pendingDeleteTemplate;
    if (!target) return;
    setBusy(true);
    setError(null);
    try {
      await deleteChannelTemplate(agentId, target.id);
      await refresh();
    } catch (e) {
      setError(apiErrorText(e, "Failed to delete template"));
    } finally {
      setBusy(false);
      setPendingDeleteTemplate(null);
    }
  }

  async function confirmDeleteRule() {
    const target = pendingDeleteRule;
    if (!target) return;
    setBusy(true);
    setError(null);
    try {
      await deleteChannelRule(agentId, target.id);
      await refresh();
    } catch (e) {
      setError(apiErrorText(e, "Failed to delete rule"));
    } finally {
      setBusy(false);
      setPendingDeleteRule(null);
    }
  }

  async function moveRule(index: number, direction: -1 | 1) {
    if (!rules) return;
    const order = rules.map((r) => r.id);
    const target = index + direction;
    if (target < 0 || target >= order.length) return;
    [order[index], order[target]] = [order[target], order[index]];
    setBusy(true);
    setError(null);
    try {
      setRules(await reorderChannelRules(agentId, order));
    } catch (e) {
      setError(apiErrorText(e, "Failed to reorder rules"));
    } finally {
      setBusy(false);
    }
  }

  const isWhatsApp = channel === "whatsapp";
  const loading = templates === null || rules === null;

  return (
    <SettingsSection
      icon={MessageSquare}
      title="Omnichannel"
      hint="Message the customer after a call"
    >
      <datalist id={VARIABLE_LIST_ID}>
        {variableKeys.map((key) => (
          <option key={key} value={key} />
        ))}
      </datalist>
      {error && <p className="text-xs text-bad">{error}</p>}

      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <div className="flex items-center gap-2">
          <label className="text-xs text-muted-foreground">Channel</label>
          <select
            value={channel}
            disabled={busy}
            onChange={(e) => saveHeader({ channel: e.target.value })}
            className={`${INPUT_CLASS} w-auto`}
          >
            <option value="">None</option>
            <option value="whatsapp">WhatsApp</option>
            {channel && channel !== "whatsapp" && <option value={channel}>{channel} (not supported yet)</option>}
          </select>
        </div>
        {isWhatsApp && (
          <label className="flex items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              checked={autoSend}
              disabled={busy}
              onChange={(e) => saveHeader({ auto_send: e.target.checked })}
              className="h-4 w-4 accent-primary"
            />
            Send automatically after each call
          </label>
        )}
      </div>

      {!isWhatsApp ? (
        <EmptySection label="Choose WhatsApp to add message templates and rules." />
      ) : loading ? (
        <div className="h-24 bg-muted/50 rounded-lg animate-pulse" />
      ) : (
        <div className="space-y-6 pt-2">
          {/* Templates */}
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <div>
                <p className="text-sm font-semibold text-foreground">Templates</p>
                <p className="text-xs text-muted-foreground">
                  {variablesSent.length > 0
                    ? `Variables sent to the customer: ${variablesSent.join(", ")}`
                    : "No variables are sent yet."}
                </p>
              </div>
              {editingTemplate !== "new" && (
                <Button size="sm" onClick={() => setEditingTemplate("new")}>
                  <Plus /> Add template
                </Button>
              )}
            </div>
            {templates.length === 0 && editingTemplate !== "new" && (
              <EmptySection label="No templates yet. Add one by pasting its curl." />
            )}
            {templates.map((t) =>
              editingTemplate === t.id ? (
                <TemplateForm
                  key={t.id}
                  agentId={agentId}
                  template={t}
                  onCancel={() => setEditingTemplate(null)}
                  onSaved={() => {
                    setEditingTemplate(null);
                    refresh();
                  }}
                />
              ) : (
                <TemplateCard
                  key={t.id}
                  template={t}
                  onEdit={() => setEditingTemplate(t.id)}
                  onDelete={() => setPendingDeleteTemplate(t)}
                />
              ),
            )}
            {editingTemplate === "new" && (
              <TemplateForm
                agentId={agentId}
                template={null}
                onCancel={() => setEditingTemplate(null)}
                onSaved={async (saved) => {
                  await refresh();
                  // Straight into the editor so the placeholders can be mapped.
                  setEditingTemplate(saved.params.length > 0 ? saved.id : null);
                }}
              />
            )}
          </div>

          {/* Rules */}
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <div>
                <p className="text-sm font-semibold text-foreground">Rules</p>
                <p className="text-xs text-muted-foreground">
                  After a call, the first rule that matches decides what is sent. If none match, nothing is sent.
                </p>
              </div>
              {editingRule !== "new" && (
                <Button size="sm" onClick={() => setEditingRule("new")}>
                  <Plus /> Add rule
                </Button>
              )}
            </div>
            {autoSend && rules.length === 0 && (
              <p className="text-xs text-warn">Automatic sending is on but there are no rules, so nothing will be sent.</p>
            )}
            {rules.length === 0 && editingRule !== "new" && <EmptySection label="No rules yet." />}
            {rules.map((rule, index) =>
              editingRule === rule.id ? (
                <RuleForm
                  key={rule.id}
                  agentId={agentId}
                  rule={rule}
                  templates={templates}
                  onCancel={() => setEditingRule(null)}
                  onSaved={() => {
                    setEditingRule(null);
                    refresh();
                  }}
                />
              ) : (
                <div key={rule.id} className="flex items-center gap-3 rounded-lg border border-border px-3 py-2">
                  <span className="text-xs font-mono text-muted-foreground w-5 shrink-0">{index + 1}</span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-foreground">
                      <span className="text-muted-foreground">{rule.checks.length === 0 ? "" : "When "}</span>
                      {describeChecks(rule.checks, rule.match)}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {rule.action === "send" ? (
                        <>
                          → Send <span className="font-mono text-foreground">{rule.template_name}</span>
                        </>
                      ) : (
                        <>→ Skip{rule.reason ? ` — ${rule.reason}` : ""}</>
                      )}
                    </p>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <Button variant="outline" size="sm" disabled={busy || index === 0} onClick={() => moveRule(index, -1)} aria-label="Move up">
                      <ArrowUp />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busy || index === rules.length - 1}
                      onClick={() => moveRule(index, 1)}
                      aria-label="Move down"
                    >
                      <ArrowDown />
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => setEditingRule(rule.id)}>
                      <Pencil /> Edit
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => setPendingDeleteRule(rule)} aria-label="Delete rule">
                      <Trash2 />
                    </Button>
                  </div>
                </div>
              ),
            )}
            {editingRule === "new" && (
              <RuleForm
                agentId={agentId}
                rule={null}
                templates={templates}
                onCancel={() => setEditingRule(null)}
                onSaved={() => {
                  setEditingRule(null);
                  refresh();
                }}
              />
            )}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={pendingDeleteTemplate !== null}
        onOpenChange={(o) => !o && setPendingDeleteTemplate(null)}
        title={`Delete template "${pendingDeleteTemplate?.name ?? ""}"?`}
        description="Rules that send it must be removed first. Past sends keep their history."
        busy={busy}
        onConfirm={confirmDeleteTemplate}
      />
      <ConfirmDialog
        open={pendingDeleteRule !== null}
        onOpenChange={(o) => !o && setPendingDeleteRule(null)}
        title="Delete this rule?"
        description="Calls that matched it will fall through to the next rule."
        busy={busy}
        onConfirm={confirmDeleteRule}
      />
    </SettingsSection>
  );
}
