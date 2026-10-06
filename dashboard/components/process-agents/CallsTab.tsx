import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { Card, CardHeader } from "@/components/Card";
import { getProcessAgentCalls, previewWhatsApp, sendWhatsApp } from "@/lib/telehubApi";
import type { CallRow, ProcessAgentDetail, WhatsAppPreview, WhatsAppSendResult } from "@/lib/types";
import { errorMessage, formatDate, formatDuration } from "./shared";

type WhatsAppFilter = "all" | "not_sent" | "sent" | "failed";

function str(v: unknown): string {
  if (v === null || v === undefined) return "";
  return typeof v === "string" ? v : String(v);
}

function isTruthy(v: unknown): boolean {
  return v === true || ["true", "1", "yes"].includes(str(v).trim().toLowerCase());
}

// Inbound rows carry caller_number; outbound rows only to_number.
function phoneOf(row: CallRow): string {
  return str(row.variables.caller_number) || str(row.variables.to_number) || row.lead_id;
}

function WhatsAppBadge({ whatsapp }: { whatsapp: CallRow["whatsapp"] }) {
  if (!whatsapp) return <span className="text-text-muted text-xs">—</span>;
  if (whatsapp.status === "sent") {
    return (
      <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-ok/15 text-ok" title={formatDate(whatsapp.at)}>
        Sent{whatsapp.count > 1 ? ` ×${whatsapp.count}` : ""}
      </span>
    );
  }
  return (
    <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-bad/15 text-bad" title={whatsapp.error ?? ""}>
      Failed
    </span>
  );
}

// ── Preview + confirm modal ─────────────────────────────────────────────

function SendModal({
  agentId,
  executionIds,
  onClose,
  onSent,
}: {
  agentId: number;
  executionIds: number[];
  onClose: () => void;
  onSent: () => void;
}) {
  const [previews, setPreviews] = useState<WhatsAppPreview[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [results, setResults] = useState<WhatsAppSendResult[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    previewWhatsApp(agentId, executionIds)
      .then((data) => !cancelled && setPreviews(data))
      .catch((e: unknown) => !cancelled && setError(errorMessage(e, "Failed to load preview")));
    return () => {
      cancelled = true;
    };
  }, [agentId, executionIds]);

  const ready = (previews ?? []).filter((p) => !p.error && p.missing.length === 0);
  const blocked = (previews ?? []).length - ready.length;

  async function handleSend() {
    setSending(true);
    setError(null);
    try {
      const res = await sendWhatsApp(
        agentId,
        ready.map((p) => p.execution_id),
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
  const failed = results?.filter((r) => !r.success) ?? [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="bg-white rounded-xl shadow-lg w-full max-w-2xl max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-4 border-b border-border">
          <p className="text-base font-semibold text-on-surface">Send WhatsApp template</p>
          {previews && previews[0]?.template_title && (
            <p className="text-xs text-text-muted mt-0.5">
              Template <span className="font-mono">{previews[0].template_title}</span> · {previews.length} recipient
              {previews.length === 1 ? "" : "s"}
            </p>
          )}
        </div>

        <div className="px-5 py-4 overflow-y-auto space-y-3 flex-1">
          {error && (
            <div className="text-sm text-bad bg-bad/10 border border-bad/30 rounded-lg px-3 py-2">{error}</div>
          )}
          {!previews && !error && <div className="h-24 bg-surface-container rounded-lg animate-pulse" />}

          {results ? (
            <div className="space-y-2 text-sm">
              <p className="text-on-surface">
                {succeeded} sent{failed.length ? `, ${failed.length} failed` : ""}.
              </p>
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
                  <p className="text-sm font-medium text-on-surface font-mono">{p.receiver_number || "no number"}</p>
                  {p.error || p.missing.length ? (
                    <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-bad/15 text-bad">
                      Won&apos;t send
                    </span>
                  ) : (
                    <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-ok/15 text-ok">Ready</span>
                  )}
                </div>
                {p.error ? (
                  <p className="text-xs text-bad">{p.error}</p>
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
            {!results && blocked > 0 && `${blocked} recipient${blocked === 1 ? "" : "s"} with missing values will be skipped.`}
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

// ── Tab ─────────────────────────────────────────────────────────────────

export function CallsTab({ agent }: { agent: ProcessAgentDetail }) {
  const [rows, setRows] = useState<CallRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [hideTests, setHideTests] = useState(true);
  const [whatsAppFilter, setWhatsAppFilter] = useState<WhatsAppFilter>("all");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [expanded, setExpanded] = useState<number | null>(null);
  const [modalIds, setModalIds] = useState<number[] | null>(null);

  const whatsAppConfigured = Boolean(agent.omnichannel?.whatsapp_curl?.trim());

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

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (rows ?? []).filter((row) => {
      if (hideTests && isTruthy(row.variables.is_test)) return false;
      if (whatsAppFilter === "not_sent" && row.whatsapp) return false;
      if (whatsAppFilter === "sent" && row.whatsapp?.status !== "sent") return false;
      if (whatsAppFilter === "failed" && row.whatsapp?.status !== "failed") return false;
      if (q && !`${phoneOf(row)} ${str(row.variables.customer_name)}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [rows, search, hideTests, whatsAppFilter]);

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
    setSelected(allVisibleSelected ? new Set() : new Set(visible.map((r) => r.id)));
  }

  if (loading && !rows) {
    return <div className="h-32 bg-surface-container rounded-xl animate-pulse" />;
  }
  if (error) {
    return <div className="text-sm text-bad bg-bad/10 border border-bad/30 rounded-lg px-4 py-3">{error}</div>;
  }

  const inputCls = "px-2.5 py-1.5 rounded-lg border border-border bg-surface text-sm";

  return (
    <div className="space-y-4">
      {!whatsAppConfigured && (
        <div className="text-sm text-warn bg-warn/10 border border-warn/30 rounded-lg px-4 py-3">
          No WhatsApp curl configured — add one under Settings → Omnichannel to enable sending.
        </div>
      )}

      <Card className="p-0 overflow-hidden">
        <CardHeader title="Calls" hint={`${visible.length} of ${rows?.length ?? 0} call${rows?.length === 1 ? "" : "s"}`} />

        <div className="px-5 pb-3 flex flex-wrap items-center gap-2">
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
            <option value="sent">WhatsApp: sent</option>
            <option value="failed">WhatsApp: failed</option>
          </select>
          <label className="flex items-center gap-1.5 text-sm text-text-muted">
            <input type="checkbox" checked={hideTests} onChange={(e) => setHideTests(e.target.checked)} />
            Hide test calls
          </label>
          <div className="flex-1" />
          <button onClick={load} disabled={loading} className="px-3 py-1.5 rounded-lg text-sm border border-border hover:bg-surface-container disabled:opacity-60">
            {loading ? "Refreshing…" : "Refresh"}
          </button>
          <button
            onClick={() => setModalIds(visibleSelected)}
            disabled={!whatsAppConfigured || visibleSelected.length === 0}
            className="px-3 py-1.5 rounded-lg text-sm font-medium bg-primary text-on-primary hover:bg-primary-container disabled:opacity-60"
          >
            Send WhatsApp{visibleSelected.length ? ` (${visibleSelected.length})` : ""}
          </button>
        </div>

        {visible.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-text-muted border-t border-border">No calls yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-text-muted uppercase tracking-wide border-t border-border">
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
                {visible.map((row) => {
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
                        </td>
                        <td className="px-3 py-2.5 text-xs text-text-muted whitespace-nowrap">
                          {str(v.call_start_time) || formatDate(row.created_at)}
                        </td>
                        <td className="px-3 py-2.5">{str(v.model_name) || "—"}</td>
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
                        <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                          <button
                            onClick={() => setModalIds([row.id])}
                            disabled={!whatsAppConfigured}
                            className="px-2 py-1 rounded text-[11px] font-medium bg-primary text-on-primary hover:bg-primary-container disabled:opacity-60 whitespace-nowrap"
                          >
                            {row.whatsapp?.status === "sent" ? "Resend" : "Send"}
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
      </Card>

      {modalIds && (
        <SendModal
          agentId={agent.id}
          executionIds={modalIds}
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
