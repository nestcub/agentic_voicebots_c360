import { Fragment, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeMouseHandler,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { FaWhatsapp } from "react-icons/fa";
import { FiCheckCircle, FiClock, FiDatabase, FiMinusCircle, FiX, FiXCircle, FiZap } from "react-icons/fi";
import { Card, CardHeader } from "@/components/Card";
import { TablePagination, usePagination } from "@/components/common/TablePagination";
import {
  fillWhatsAppSend,
  getProcessAgentCalls,
  listChannelTemplates,
  previewWhatsApp,
  sendWhatsApp,
} from "@/lib/telehubApi";
import type {
  CallRow,
  ChannelTemplate,
  ProcessAgentDetail,
  WhatsAppFillResult,
  WhatsAppPreview,
  WhatsAppSendResult,
} from "@/lib/types";
import { DealersSection } from "./DealersSection";
import { apiErrorText, errorMessage, formatDate, formatDuration, phoneOf, str } from "./shared";

type WhatsAppFilter = "all" | "not_sent" | "pending" | "sent" | "failed";

const POLL_INTERVAL_MS = 15_000;

function isTruthy(v: unknown): boolean {
  return v === true || ["true", "1", "yes"].includes(str(v).trim().toLowerCase());
}

function WhatsAppBadge({ whatsapp }: { whatsapp: CallRow["whatsapp"] }) {
  if (!whatsapp) return <span className="text-text-muted text-xs">—</span>;
  const template = whatsapp.template_key ? ` · ${whatsapp.template_key}` : "";
  const styles: Record<string, { cls: string; label: string }> = {
    sent: { cls: "bg-ok/15 text-ok", label: `Sent${template}${whatsapp.count > 1 ? ` ×${whatsapp.count}` : ""}` },
    failed: { cls: "bg-bad/15 text-bad", label: `Failed${template}` },
    pending: { cls: "bg-primary/15 text-primary", label: `Sending${template}` },
    skipped: { cls: "bg-text-muted/15 text-text-muted", label: `Skipped${template}` },
    blocked: { cls: "bg-bad/15 text-bad", label: `Needs values${template}` },
  };
  const style = styles[whatsapp.status] ?? styles.failed;
  return (
    <span className="inline-flex flex-col items-start gap-0.5">
      <span
        className={`text-xs font-medium px-2 py-0.5 rounded-full whitespace-nowrap ${style.cls}`}
        title={whatsapp.error || formatDate(whatsapp.at)}
      >
        {style.label}
      </span>
      <span className="text-[10px] text-text-muted">
        {whatsapp.trigger === "auto" ? "auto" : "manual"}
        {whatsapp.status === "skipped" && whatsapp.error ? ` · ${whatsapp.error}` : ""}
        {whatsapp.status === "blocked" && whatsapp.missing.length ? ` · missing ${whatsapp.missing.join(", ")}` : ""}
      </span>
    </span>
  );
}

// ── Preview + confirm modal ─────────────────────────────────────────────

function SendModal({
  agentId,
  executionIds,
  templates,
  onClose,
  onSent,
}: {
  agentId: number;
  executionIds: number[];
  templates: ChannelTemplate[];
  onClose: () => void;
  onSent: () => void;
}) {
  const [previews, setPreviews] = useState<WhatsAppPreview[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [results, setResults] = useState<WhatsAppSendResult[] | null>(null);
  // "" = each call gets the template the rules pick.
  const [templateKey, setTemplateKey] = useState("");

  useEffect(() => {
    let cancelled = false;
    setPreviews(null);
    setError(null);
    previewWhatsApp(agentId, executionIds, templateKey || undefined)
      .then((data) => !cancelled && setPreviews(data))
      .catch((e: unknown) => !cancelled && setError(errorMessage(e, "Failed to load preview")));
    return () => {
      cancelled = true;
    };
  }, [agentId, executionIds, templateKey]);

  // Only a broken curl / missing phone number stops a recipient here. Recipients with empty
  // variables are still submitted: the server holds their message ("needs values") instead of
  // sending it, and the values can then be filled in from the Calls table.
  const ready = (previews ?? []).filter((p) => !p.error);
  const unsendable = (previews ?? []).length - ready.length;
  const held = ready.filter((p) => p.missing.length > 0).length;

  async function handleSend() {
    setSending(true);
    setError(null);
    try {
      const res = await sendWhatsApp(
        agentId,
        ready.map((p) => p.execution_id),
        templateKey || undefined,
      );
      setResults(res.results);
      onSent();
    } catch (e) {
      setError(errorMessage(e, "Failed to send"));
    } finally {
      setSending(false);
    }
  }

  const succeeded = results?.filter((r) => r.success).length ?? 0;
  const heldResults = results?.filter((r) => r.blocked) ?? [];
  const failed = results?.filter((r) => !r.success && !r.blocked) ?? [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="bg-white rounded-xl shadow-lg w-full max-w-2xl max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-4 border-b border-border">
          <p className="text-base font-semibold text-on-surface">Send WhatsApp template</p>
          <div className="flex items-center gap-2 mt-2">
            <label className="text-xs text-text-muted">Template</label>
            <select
              value={templateKey}
              onChange={(e) => setTemplateKey(e.target.value)}
              disabled={sending || results !== null}
              className="px-2 py-1 rounded-lg border border-border bg-surface text-sm"
            >
              <option value="">Rule&apos;s pick for each call</option>
              {templates
                .filter((t) => t.is_active)
                .map((t) => (
                  <option key={t.id} value={t.name}>
                    {t.name}
                  </option>
                ))}
            </select>
            {previews && (
              <span className="text-xs text-text-muted">
                {previews.length} recipient{previews.length === 1 ? "" : "s"}
              </span>
            )}
          </div>
        </div>

        <div className="px-5 py-4 overflow-y-auto space-y-3 flex-1">
          {error && (
            <div className="text-sm text-bad bg-bad/10 border border-bad/30 rounded-lg px-3 py-2">{error}</div>
          )}
          {!previews && !error && <div className="h-24 bg-surface-container rounded-lg animate-pulse" />}

          {results ? (
            <div className="space-y-2 text-sm">
              <p className="text-on-surface">
                {succeeded} sent
                {heldResults.length ? `, ${heldResults.length} held for missing values` : ""}
                {failed.length ? `, ${failed.length} failed` : ""}.
              </p>
              {heldResults.map((r) => (
                <p key={r.execution_id} className="text-xs text-text-muted">
                  #{r.execution_id}: waiting on {(r.missing ?? []).join(", ")} — use “Fill values” on the call.
                </p>
              ))}
              {failed.map((r) => (
                <p key={r.execution_id} className="text-xs text-bad">
                  #{r.execution_id}: {r.error}
                </p>
              ))}
            </div>
          ) : (
            previews?.map((p) => (
              <div key={p.execution_id} className="rounded-lg border border-border p-3 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm text-on-surface">
                    <span className="font-medium font-mono">{p.receiver_number || "no number"}</span>
                    <span className="text-xs text-text-muted">
                      {" "}
                      · {p.template_key}
                      {p.template_title ? ` (${p.template_title})` : ""}
                    </span>
                  </p>
                  {p.error ? (
                    <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-bad/15 text-bad">
                      Won&apos;t send
                    </span>
                  ) : p.missing.length ? (
                    <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-warn/15 text-warn">
                      Needs values
                    </span>
                  ) : (
                    <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-ok/15 text-ok">Ready</span>
                  )}
                </div>
                {p.error ? (
                  <p className="text-xs text-bad">{p.error}</p>
                ) : Object.keys(p.params).length === 0 ? (
                  <p className="text-xs text-text-muted">No parameters — fixed text template.</p>
                ) : (
                  <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-xs">
                    {Object.entries(p.params).map(([key, value]) => (
                      <Fragment key={key}>
                        <dt className="font-mono text-text-muted">{key}</dt>
                        <dd className={`break-all ${p.missing.includes(key) ? "text-bad" : "text-on-surface"}`}>
                          {p.missing.includes(key) ? "missing" : value}
                        </dd>
                      </Fragment>
                    ))}
                  </dl>
                )}
              </div>
            ))
          )}
        </div>

        <div className="px-5 py-3 border-t border-border flex items-center justify-between gap-3">
          <p className="text-xs text-text-muted">
            {!results && held > 0 && `${held} will be held until their missing values are filled in. `}
            {!results && unsendable > 0 && `${unsendable} can't be sent (fix the template or phone number).`}
          </p>
          <div className="flex gap-2">
            <button onClick={onClose} className="px-3 py-1.5 rounded-lg text-sm border border-border hover:bg-surface-container">
              {results ? "Close" : "Cancel"}
            </button>
            {!results && (
              <button
                onClick={handleSend}
                disabled={sending || ready.length === 0}
                className="px-3 py-1.5 rounded-lg text-sm font-medium bg-primary text-on-primary hover:bg-primary-container disabled:opacity-60"
              >
                {sending ? "Sending…" : `Send to ${ready.length}`}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Fill a blocked send's missing values ────────────────────────────────

function FillModal({
  agentId,
  row,
  onClose,
  onDone,
}: {
  agentId: number;
  row: CallRow;
  onClose: () => void;
  onDone: () => void;
}) {
  const whatsapp = row.whatsapp;
  const [values, setValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<WhatsAppFillResult | null>(null);

  if (!whatsapp || whatsapp.id === null) return null;
  const sendId = whatsapp.id;
  const missing = result ? result.missing : whatsapp.missing;
  const filledAny = Object.values(values).some((v) => v.trim());

  async function handleSubmit() {
    setSaving(true);
    setError(null);
    try {
      const toSend = Object.fromEntries(
        Object.entries(values)
          .filter(([name]) => missing.includes(name))
          .filter(([, v]) => v.trim())
          .map(([name, v]) => [name, v.trim()]),
      );
      const res = await fillWhatsAppSend(agentId, sendId, toSend);
      setResult(res);
      setValues({});
      onDone();
    } catch (e) {
      setError(apiErrorText(e, "Failed to save values"));
    } finally {
      setSaving(false);
    }
  }

  const sent = result?.status === "sent";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="bg-white rounded-xl shadow-lg w-full max-w-lg max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-4 border-b border-border">
          <p className="text-base font-semibold text-on-surface">Fill in missing values</p>
          <p className="text-xs text-text-muted mt-0.5">
            {phoneOf(row)} · {whatsapp.template_key}. The message is held until these are filled; it sends as soon as
            they are.
          </p>
        </div>
        <div className="px-5 py-4 overflow-y-auto space-y-3 flex-1">
          {error && <div className="text-sm text-bad bg-bad/10 border border-bad/30 rounded-lg px-3 py-2">{error}</div>}
          {sent ? (
            <p className="text-sm text-ok">Sent.</p>
          ) : result && result.status === "failed" ? (
            <p className="text-sm text-bad">Saved, but sending failed: {result.error}</p>
          ) : result && result.status === "pending" ? (
            <p className="text-sm text-text-muted">Saved. Sending hit a temporary error and will be retried.</p>
          ) : (
            <>
              {result && missing.length > 0 && (
                <p className="text-xs text-text-muted">Saved. Still waiting on the values below.</p>
              )}
              {missing.map((name) => (
                <div key={name}>
                  <label className="block text-xs font-mono text-text-muted mb-1">{name}</label>
                  <input
                    value={values[name] ?? ""}
                    onChange={(e) => setValues((v) => ({ ...v, [name]: e.target.value }))}
                    className="w-full px-2.5 py-1.5 rounded-lg border border-border bg-surface text-sm"
                  />
                </div>
              ))}
            </>
          )}
        </div>
        <div className="px-5 py-3 border-t border-border flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1.5 rounded-lg text-sm border border-border hover:bg-surface-container">
            {result && (sent || result.status !== "blocked") ? "Close" : "Cancel"}
          </button>
          {!(result && result.status !== "blocked") && (
            <button
              onClick={handleSubmit}
              disabled={saving || !filledAny}
              className="px-3 py-1.5 rounded-lg text-sm font-medium bg-primary text-on-primary hover:bg-primary-container disabled:opacity-60"
            >
              {saving ? "Saving…" : "Save & send"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Flow canvas ─────────────────────────────────────────────────────────
//
// Webhook intake -> Call data -> WhatsApp send -> one node per send outcome.
// Every node is clickable and opens the calls table in a drawer, pre-filtered
// to what that node represents.

type Tone = "primary" | "accent" | "ok" | "bad" | "warn" | "muted";

const TONES: Record<Tone, { border: string; chip: string; stroke: string }> = {
  primary: { border: "border-primary/40", chip: "bg-primary/15 text-primary", stroke: "var(--color-primary)" },
  accent: { border: "border-teal/40", chip: "bg-teal/15 text-teal", stroke: "var(--color-teal)" },
  ok: { border: "border-ok/40", chip: "bg-ok/15 text-ok", stroke: "var(--color-ok)" },
  bad: { border: "border-bad/40", chip: "bg-bad/15 text-bad", stroke: "var(--color-bad)" },
  warn: { border: "border-warn/40", chip: "bg-warn/15 text-warn", stroke: "var(--color-warn)" },
  muted: { border: "border-border", chip: "bg-text-muted/15 text-text-muted", stroke: "var(--color-text-muted)" },
};

type StepData = {
  kind: string;
  title: string;
  icon: ReactNode;
  stat: string;
  sub?: string;
  action?: string;
  tone: Tone;
  live?: boolean;
  active?: boolean;
  hasIn?: boolean;
  hasOut?: boolean;
};
type StepNodeType = Node<StepData, "step">;

const HANDLE_STYLE = { background: "var(--color-border)", width: 8, height: 8, border: "none" };

function StepNode({ data }: NodeProps<StepNodeType>) {
  const tone = TONES[data.tone];
  return (
    <div
      className={`w-56 rounded-xl border bg-surface px-3.5 py-3 shadow-sm cursor-pointer transition-shadow hover:shadow-md ${
        data.active ? "border-primary ring-2 ring-primary/30" : tone.border
      }`}
    >
      {data.hasIn && <Handle type="target" position={Position.Left} style={HANDLE_STYLE} />}
      <div className="flex items-center gap-2">
        <span className={`h-7 w-7 shrink-0 rounded-lg flex items-center justify-center ${tone.chip}`}>{data.icon}</span>
        <div className="min-w-0">
          <p className="text-[10px] uppercase tracking-wide text-text-muted">{data.kind}</p>
          <p className="text-sm font-semibold text-on-surface truncate">{data.title}</p>
        </div>
        {data.live && (
          <span className="ml-auto relative flex h-2.5 w-2.5" title="Data arrived in the last 5 minutes">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-ok opacity-75" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-ok" />
          </span>
        )}
      </div>
      <p className="mt-2 text-xl font-semibold text-on-surface">{data.stat}</p>
      {data.sub && <p className="text-xs text-text-muted truncate">{data.sub}</p>}
      {data.action && <p className="mt-2 text-[11px] font-medium text-primary">{data.action} →</p>}
      {data.hasOut && <Handle type="source" position={Position.Right} style={HANDLE_STYLE} />}
    </div>
  );
}

// Module-level so React Flow doesn't see a new nodeTypes object every render.
const NODE_TYPES = { step: StepNode };

const LIVE_WINDOW_MS = 5 * 60_000;

const OUTCOMES: { id: Exclude<WhatsAppFilter, "all">; title: string; tone: Tone; icon: ReactNode }[] = [
  { id: "sent", title: "Sent", tone: "ok", icon: <FiCheckCircle /> },
  { id: "pending", title: "Sending", tone: "primary", icon: <FiClock /> },
  { id: "failed", title: "Failed / needs values", tone: "bad", icon: <FiXCircle /> },
  { id: "not_sent", title: "Not sent / skipped", tone: "muted", icon: <FiMinusCircle /> },
];

const FILTER_LABELS: Record<WhatsAppFilter, string> = {
  all: "All call data",
  not_sent: "WhatsApp not sent",
  pending: "WhatsApp sending",
  sent: "WhatsApp sent",
  failed: "WhatsApp failed or waiting on values",
};

interface FlowStats {
  total: number;
  fields: number;
  latest: string | null;
  live: boolean;
  byOutcome: Record<Exclude<WhatsAppFilter, "all">, number>;
}

function computeStats(rows: CallRow[]): FlowStats {
  let latest: string | null = null;
  const fields = new Set<string>();
  const byOutcome = { sent: 0, pending: 0, failed: 0, not_sent: 0 };
  for (const row of rows) {
    if (!latest || row.created_at > latest) latest = row.created_at;
    Object.keys(row.variables).forEach((k) => fields.add(k));
    if (!row.whatsapp || row.whatsapp.status === "skipped") byOutcome.not_sent += 1;
    // A blocked send is waiting on someone to fill values in — count it with the failures, which need attention.
    else byOutcome[row.whatsapp.status === "blocked" ? "failed" : row.whatsapp.status] += 1;
  }
  const live = latest !== null && Date.now() - new Date(latest).getTime() < LIVE_WINDOW_MS;
  return { total: rows.length, fields: fields.size, latest, live, byOutcome };
}

function buildFlow(
  stats: FlowStats,
  agent: ProcessAgentDetail,
  templates: ChannelTemplate[],
  whatsAppConfigured: boolean,
  activeFilter: WhatsAppFilter | null,
): { nodes: StepNodeType[]; edges: Edge[] } {
  const readyTemplates = templates.filter((t) => t.configured && !t.error && t.is_active).length;
  const step = (id: string, x: number, y: number, data: StepData): StepNodeType => ({
    id,
    type: "step",
    position: { x, y },
    data,
  });
  const edge = (source: string, target: string, tone: Tone, opts: Partial<Edge> = {}): Edge => ({
    id: `${source}->${target}`,
    source,
    target,
    style: { stroke: TONES[tone].stroke, strokeWidth: 1.5 },
    markerEnd: { type: MarkerType.ArrowClosed, color: TONES[tone].stroke },
    labelStyle: { fill: "var(--color-on-surface)", fontSize: 11, fontWeight: 600 },
    labelBgStyle: { fill: "var(--color-surface)" },
    labelBgPadding: [6, 3],
    labelBgBorderRadius: 6,
    ...opts,
  });

  const nodes: StepNodeType[] = [
    step("webhook", 0, 150, {
      kind: "Trigger",
      title: "Webhook intake",
      icon: <FiZap />,
      stat: `${stats.total} received`,
      sub: stats.latest ? `Last: ${formatDate(stats.latest)}` : "Waiting for first post",
      tone: "accent",
      live: stats.live,
      hasOut: true,
      active: activeFilter === "all",
    }),
    step("data", 300, 150, {
      kind: "Data",
      title: "Call data",
      icon: <FiDatabase />,
      stat: `${stats.total} record${stats.total === 1 ? "" : "s"}`,
      sub: `${stats.fields} field${stats.fields === 1 ? "" : "s"} captured`,
      action: "Open table",
      tone: "primary",
      hasIn: true,
      hasOut: true,
      active: activeFilter === "all",
    }),
    step("whatsapp", 600, 150, {
      kind: "Action",
      title: "WhatsApp send",
      icon: <FaWhatsapp />,
      stat: whatsAppConfigured ? `Auto-send ${agent.omnichannel?.auto_send ? "on" : "off"}` : "Not configured",
      sub: `${readyTemplates}/${templates.length} template${templates.length === 1 ? "" : "s"} ready`,
      action: "Pick calls to send",
      tone: whatsAppConfigured ? "ok" : "warn",
      hasIn: true,
      hasOut: true,
      active: activeFilter === "not_sent",
    }),
    ...OUTCOMES.map((o, i) =>
      step(`out-${o.id}`, 920, i * 105, {
        kind: "Outcome",
        title: o.title,
        icon: o.icon,
        stat: String(stats.byOutcome[o.id]),
        tone: stats.byOutcome[o.id] ? o.tone : "muted",
        hasIn: true,
        active: activeFilter === o.id,
      }),
    ),
  ];

  const edges: Edge[] = [
    edge("webhook", "data", "accent", { animated: stats.live }),
    edge("data", "whatsapp", "primary", { animated: stats.byOutcome.pending > 0 }),
    ...OUTCOMES.map((o) => {
      const n = stats.byOutcome[o.id];
      return edge("whatsapp", `out-${o.id}`, n ? o.tone : "muted", {
        label: String(n),
        animated: o.id === "pending" && n > 0,
      });
    }),
  ];
  return { nodes, edges };
}

function filterForNode(id: string): WhatsAppFilter {
  if (id === "whatsapp") return "not_sent";
  if (id.startsWith("out-")) return id.slice(4) as WhatsAppFilter;
  return "all";
}

// ── Calls table (rendered inside the data drawer) ───────────────────────

function CallsTable({
  rows,
  whatsAppFilter,
  setWhatsAppFilter,
  whatsAppConfigured,
  selected,
  setSelected,
  onSend,
  onFill,
}: {
  rows: CallRow[];
  whatsAppFilter: WhatsAppFilter;
  setWhatsAppFilter: (f: WhatsAppFilter) => void;
  whatsAppConfigured: boolean;
  selected: Set<number>;
  setSelected: (fn: (s: Set<number>) => Set<number>) => void;
  onSend: (ids: number[]) => void;
  onFill: (row: CallRow) => void;
}) {
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter((row) => {
      if (whatsAppFilter === "not_sent" && row.whatsapp && row.whatsapp.status !== "skipped") return false;
      if (whatsAppFilter === "pending" && row.whatsapp?.status !== "pending") return false;
      if (whatsAppFilter === "sent" && row.whatsapp?.status !== "sent") return false;
      if (whatsAppFilter === "failed" && row.whatsapp?.status !== "failed" && row.whatsapp?.status !== "blocked") {
        return false;
      }
      if (q && !`${phoneOf(row)} ${str(row.variables.customer_name)}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [rows, search, whatsAppFilter]);

  const pagination = usePagination(visible);
  const { setPage } = pagination;
  // Back to page 1 whenever the search or filter changes the result set.
  useEffect(() => {
    setPage(1);
  }, [search, whatsAppFilter, setPage]);

  const visibleSelected = visible.filter((r) => selected.has(r.id)).map((r) => r.id);
  const allVisibleSelected = visible.length > 0 && visibleSelected.length === visible.length;

  function toggle(id: number) {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelected(() => (allVisibleSelected ? new Set() : new Set(visible.map((r) => r.id))));
  }

  const inputCls = "px-2.5 py-1.5 rounded-lg border border-border bg-surface text-sm";

  return (
    <div className="flex flex-col min-h-0 flex-1">
      <div className="px-5 py-3 flex flex-wrap items-center gap-2 border-b border-border">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search phone or name"
          className={`${inputCls} w-56`}
        />
        <select
          value={whatsAppFilter}
          onChange={(e) => setWhatsAppFilter(e.target.value as WhatsAppFilter)}
          className={inputCls}
        >
          <option value="all">WhatsApp: all</option>
          <option value="not_sent">WhatsApp: not sent</option>
          <option value="pending">WhatsApp: sending</option>
          <option value="sent">WhatsApp: sent</option>
          <option value="failed">WhatsApp: failed</option>
        </select>
        <span className="text-xs text-text-muted">
          {visible.length} of {rows.length}
        </span>
        <div className="flex-1" />
        <button
          onClick={() => onSend(visibleSelected)}
          disabled={!whatsAppConfigured || visibleSelected.length === 0}
          className="px-3 py-1.5 rounded-lg text-sm font-medium bg-primary text-on-primary hover:bg-primary-container disabled:opacity-60"
        >
          Send WhatsApp{visibleSelected.length ? ` (${visibleSelected.length})` : ""}
        </button>
      </div>

      {visible.length === 0 ? (
        <p className="px-5 py-8 text-center text-sm text-text-muted">No calls match.</p>
      ) : (
        <div className="overflow-auto flex-1">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface z-10">
              <tr className="text-left text-xs text-text-muted uppercase tracking-wide border-b border-border">
                <th className="px-3 py-2 w-8">
                  <input type="checkbox" checked={allVisibleSelected} onChange={toggleAll} aria-label="Select all" />
                </th>
                <th className="px-3 py-2 font-medium">Caller</th>
                <th className="px-3 py-2 font-medium">Received</th>
                <th className="px-3 py-2 font-medium">Model</th>
                <th className="px-3 py-2 font-medium">Interest</th>
                <th className="px-3 py-2 font-medium">Appointment</th>
                <th className="px-3 py-2 font-medium">Duration</th>
                <th className="px-3 py-2 font-medium">WhatsApp</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {pagination.pageItems.map((row) => {
                const v = row.variables;
                const appointment = [str(v.appointment_date), str(v.appointment_time)].filter(Boolean).join(" ");
                const isOpen = expanded === row.id;
                return (
                  <Fragment key={row.id}>
                    <tr
                      className={`cursor-pointer hover:bg-surface-container/50 ${isOpen ? "bg-surface-container/50" : ""}`}
                      onClick={() => setExpanded(isOpen ? null : row.id)}
                    >
                      <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={selected.has(row.id)}
                          onChange={() => toggle(row.id)}
                          aria-label={`Select ${phoneOf(row)}`}
                        />
                      </td>
                      <td className="px-3 py-2.5">
                        <p className="text-on-surface">{str(v.customer_name) || "—"}</p>
                        <p className="text-xs text-text-muted font-mono">{phoneOf(row)}</p>
                        {isTruthy(v.is_test) && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-warn/15 text-warn">test</span>
                        )}
                        {isTruthy(v.did_mismatch) && (
                          <span
                            className="ml-1 text-[10px] px-1.5 py-0.5 rounded-full bg-bad/15 text-bad"
                            title={`Dialed ${str(v.callee_number) || "a number"} - not one of this agent's inbound numbers`}
                          >
                            wrong number
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-xs text-text-muted whitespace-nowrap">
                        {str(v.call_start_time) || formatDate(row.created_at)}
                      </td>
                      <td className="px-3 py-2.5">{str(v.model_of_interest) || str(v.model_name) || "—"}</td>
                      <td className="px-3 py-2.5">{str(v.interest_type) || "—"}</td>
                      <td className="px-3 py-2.5">
                        {appointment || str(v.appointment_place) ? (
                          <>
                            <p className="text-xs text-on-surface">{appointment || "—"}</p>
                            <p className="text-xs text-text-muted">{str(v.appointment_place)}</p>
                          </>
                        ) : (
                          <span className="text-text-muted text-xs">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-xs whitespace-nowrap">{formatDuration(row.duration)}</td>
                      <td className="px-3 py-2.5">
                        <WhatsAppBadge whatsapp={row.whatsapp} />
                      </td>
                      <td className="px-3 py-2.5 space-x-1" onClick={(e) => e.stopPropagation()}>
                        {row.whatsapp?.status === "blocked" && row.whatsapp.id !== null && (
                          <button
                            onClick={() => onFill(row)}
                            className="px-2 py-1 rounded text-[11px] font-medium bg-bad text-white hover:opacity-90 whitespace-nowrap"
                          >
                            Fill values
                          </button>
                        )}
                        <button
                          onClick={() => onSend([row.id])}
                          disabled={!whatsAppConfigured}
                          className="px-2 py-1 rounded text-[11px] font-medium bg-primary text-on-primary hover:bg-primary-container disabled:opacity-60 whitespace-nowrap"
                        >
                          {row.whatsapp?.status === "sent" ? "Resend" : "Send"}{row.suggested_template ? ` · ${row.suggested_template}` : ""}
                        </button>
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="bg-surface-container/30">
                        <td />
                        <td colSpan={8} className="px-3 py-3">
                          {str(v.recording_url) && (
                            <audio controls preload="none" src={str(v.recording_url)} className="mb-3 w-full max-w-md" />
                          )}
                          <dl className="grid grid-cols-[max-content_1fr] sm:grid-cols-[max-content_1fr_max-content_1fr] gap-x-4 gap-y-1 text-xs">
                            {Object.entries(v)
                              .filter(([key]) => key !== "recording_url")
                              .sort(([a], [b]) => a.localeCompare(b))
                              .map(([key, value]) => (
                                <Fragment key={key}>
                                  <dt className="font-mono text-text-muted">{key}</dt>
                                  <dd className="text-on-surface break-all">{str(value) || "—"}</dd>
                                </Fragment>
                              ))}
                          </dl>
                          {row.whatsapp?.status === "failed" && row.whatsapp.error && (
                            <p className="mt-2 text-xs text-bad">Last WhatsApp error: {row.whatsapp.error}</p>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <TablePagination
        page={pagination.page}
        pageCount={pagination.pageCount}
        pageSize={pagination.pageSize}
        total={pagination.total}
        start={pagination.start}
        onPageChange={pagination.setPage}
        onPageSizeChange={pagination.setPageSize}
      />
    </div>
  );
}

// ── Tab ─────────────────────────────────────────────────────────────────

export function CallsTab({ agent }: { agent: ProcessAgentDetail }) {
  const [rows, setRows] = useState<CallRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [hideTests, setHideTests] = useState(true);
  // null = drawer closed; otherwise the filter the open table is showing.
  const [drawerFilter, setDrawerFilter] = useState<WhatsAppFilter | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [modalIds, setModalIds] = useState<number[] | null>(null);
  const [fillRow, setFillRow] = useState<CallRow | null>(null);
  const [templates, setTemplates] = useState<ChannelTemplate[]>([]);

  useEffect(() => {
    let cancelled = false;
    listChannelTemplates(agent.id)
      .then((data) => !cancelled && setTemplates(data.templates))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [agent.id]);

  const usableTemplates = templates.filter((t) => t.configured && !t.error && t.is_active);
  const whatsAppConfigured = usableTemplates.length > 0;
  const unconfigured = templates.filter((t) => t.is_active && (!t.configured || t.error)).map((t) => t.name);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    getProcessAgentCalls(agent.id)
      .then(setRows)
      .catch((e: unknown) => setError(errorMessage(e, "Failed to load calls")))
      .finally(() => setLoading(false));
  }, [agent.id]);

  useEffect(() => {
    load();
  }, [load]);

  // Background poll: no loading/error state, so the canvas doesn't flicker and a
  // transient failure keeps the last good rows on screen. Paused while the send
  // modal is open or the browser tab is hidden.
  useEffect(() => {
    if (modalIds || fillRow) return;
    let inFlight = false;
    const timer = setInterval(() => {
      if (inFlight || document.visibilityState !== "visible") return;
      inFlight = true;
      getProcessAgentCalls(agent.id)
        .then(setRows)
        .catch(() => {})
        .finally(() => {
          inFlight = false;
        });
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [agent.id, modalIds, fillRow]);

  // Escape closes the drawer (the modal handles its own clicks).
  useEffect(() => {
    if (!drawerFilter || modalIds || fillRow) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawerFilter(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerFilter, modalIds, fillRow]);

  const baseRows = useMemo(
    () => (rows ?? []).filter((row) => !(hideTests && isTruthy(row.variables.is_test))),
    [rows, hideTests],
  );
  const stats = useMemo(() => computeStats(baseRows), [baseRows]);
  const { nodes, edges } = useMemo(
    () => buildFlow(stats, agent, templates, whatsAppConfigured, drawerFilter),
    [stats, agent, templates, whatsAppConfigured, drawerFilter],
  );

  const onNodeClick: NodeMouseHandler<StepNodeType> = useCallback((_, node) => {
    setDrawerFilter(filterForNode(node.id));
  }, []);

  if (loading && !rows) {
    return <div className="h-32 bg-surface-container rounded-xl animate-pulse" />;
  }
  if (error) {
    return <div className="text-sm text-bad bg-bad/10 border border-bad/30 rounded-lg px-4 py-3">{error}</div>;
  }

  return (
    <div className="space-y-4">
      {!whatsAppConfigured ? (
        <div className="text-sm text-warn bg-warn/10 border border-warn/30 rounded-lg px-4 py-3">
          No usable WhatsApp template — add one under Settings → Omnichannel to enable sending.
        </div>
      ) : (
        unconfigured.length > 0 && (
          <p className="text-xs text-text-muted">{unconfigured.join(", ")} need a valid curl (calls using them are skipped)</p>
        )
      )}

      <Card className="p-0 overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 pr-5">
          <div className="flex-1 min-w-0">
            <CardHeader title="Calls flow" hint="Webhook data → WhatsApp send. Click any node to inspect its data." />
          </div>
          <label className="flex items-center gap-1.5 text-sm text-text-muted">
            <input type="checkbox" checked={hideTests} onChange={(e) => setHideTests(e.target.checked)} />
            Hide test calls
          </label>
          <button
            onClick={load}
            disabled={loading}
            className="px-3 py-1.5 rounded-lg text-sm border border-border hover:bg-surface-container disabled:opacity-60"
          >
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
        <div className="h-[480px] border-t border-border bg-background">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            onNodeClick={onNodeClick}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            fitView
            fitViewOptions={{ padding: 0.15 }}
            minZoom={0.4}
            maxZoom={1.5}
          >
            <Background variant={BackgroundVariant.Dots} gap={18} size={1} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
      </Card>

      <DealersSection rows={baseRows} />

      {drawerFilter && (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={() => setDrawerFilter(null)}>
          <div
            className="h-full w-full max-w-5xl bg-surface shadow-xl flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-5 py-4 border-b border-border flex items-center gap-3">
              <span className="h-8 w-8 rounded-lg flex items-center justify-center bg-primary/15 text-primary">
                <FiDatabase />
              </span>
              <div className="flex-1 min-w-0">
                <p className="text-base font-semibold text-on-surface">Call data</p>
                <p className="text-xs text-text-muted">{FILTER_LABELS[drawerFilter]}</p>
              </div>
              <button
                onClick={() => setDrawerFilter(null)}
                aria-label="Close"
                className="p-2 rounded-lg hover:bg-surface-container text-text-muted"
              >
                <FiX />
              </button>
            </div>
            <CallsTable
              rows={baseRows}
              whatsAppFilter={drawerFilter}
              setWhatsAppFilter={setDrawerFilter}
              whatsAppConfigured={whatsAppConfigured}
              selected={selected}
              setSelected={setSelected}
              onSend={setModalIds}
              onFill={setFillRow}
            />
          </div>
        </div>
      )}

      {fillRow && (
        <FillModal agentId={agent.id} row={fillRow} onClose={() => setFillRow(null)} onDone={load} />
      )}

      {modalIds && (
        <SendModal
          agentId={agent.id}
          executionIds={modalIds}
          templates={templates}
          onClose={() => setModalIds(null)}
          onSent={() => {
            setSelected(new Set());
            load();
          }}
        />
      )}
    </div>
  );
}
