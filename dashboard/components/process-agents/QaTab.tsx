import { useState } from "react";
import { Card, CardHeader } from "@/components/Card";
import type { BotJourney, QaResult } from "@/lib/types";
import type { DispatchSingleCallResult } from "@/lib/telehubApi";
import { errorMessage } from "./shared";

// Keys in raw_result (the exact webhook payload) whose value is missing —
// computed client-side straight off the payload rather than off the
// wizard-declared Variable list, so this reflects whatever Chat360 actually
// sent for this call, blank fields included.
function emptyPayloadKeys(rawResult: Record<string, unknown>): string[] {
  return Object.entries(rawResult)
    .filter(([, value]) => value === null || value === undefined || value === "")
    .map(([key]) => key);
}

// ── Follow-up dispatch (bot picker + button) ────────────────────────────

function FollowUpDispatch({
  executionId,
  botJourneys,
  onDispatchFollowUp,
}: {
  executionId: number;
  botJourneys: BotJourney[];
  onDispatchFollowUp: (executionId: number, botJourneyId: number) => Promise<DispatchSingleCallResult>;
}) {
  const ordered = botJourneys.slice().sort((a, b) => a.order - b.order);
  const [selectedId, setSelectedId] = useState<number | "">(ordered[0]?.id ?? "");
  const [dispatching, setDispatching] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleDispatch() {
    if (selectedId === "") return;
    setDispatching(true);
    setError(null);
    setResult(null);
    try {
      const res = await onDispatchFollowUp(executionId, selectedId);
      if (res.success) {
        setResult(`Dispatched (status ${res.status_code}).`);
      } else {
        setError(res.error || `Dispatch failed (status ${res.status_code}).`);
      }
    } catch (e) {
      setError(errorMessage(e, "Failed to dispatch follow-up"));
    } finally {
      setDispatching(false);
    }
  }

  if (ordered.length === 0) {
    return <span className="text-text-muted text-xs">—</span>;
  }

  return (
    <div className="space-y-1 min-w-[160px]">
      <div className="flex items-center gap-1.5">
        {ordered.length > 1 && (
          <select
            value={selectedId}
            onChange={(e) => setSelectedId(e.target.value ? Number(e.target.value) : "")}
            className="px-1.5 py-1 rounded border border-border bg-surface text-[11px]"
          >
            {ordered.map((j) => (
              <option key={j.id} value={j.id}>
                {j.name}
                {j.voice_bot?.bot_name ? ` — ${j.voice_bot.bot_name}` : ""}
              </option>
            ))}
          </select>
        )}
        <button
          onClick={handleDispatch}
          disabled={dispatching || selectedId === ""}
          className="px-2 py-1 rounded text-[11px] font-medium bg-primary text-on-primary hover:bg-primary-container disabled:opacity-60 transition-colors whitespace-nowrap"
        >
          {dispatching ? "Dispatching…" : "Dispatch Follow-up"}
        </button>
      </div>
      {result && <p className="text-[10px] text-ok">{result}</p>}
      {error && <p className="text-[10px] text-bad">{error}</p>}
    </div>
  );
}

export function QaTab({
  qaResults,
  loading,
  error,
  botJourneys,
  onDispatchFollowUp,
}: {
  qaResults: QaResult[] | null;
  loading: boolean;
  error: string | null;
  botJourneys: BotJourney[] | null;
  onDispatchFollowUp: (executionId: number, botJourneyId: number) => Promise<DispatchSingleCallResult>;
}) {
  if (loading) {
    return <div className="h-32 bg-surface-container rounded-xl animate-pulse" />;
  }
  if (error) {
    return <div className="text-sm text-bad bg-bad/10 border border-bad/30 rounded-lg px-4 py-3">{error}</div>;
  }
  if (!qaResults || qaResults.length === 0) {
    return (
      <Card className="p-8 text-center">
        <p className="text-sm text-text-muted">No QA results yet.</p>
      </Card>
    );
  }

  return (
    <Card className="p-0 overflow-hidden">
      <CardHeader title="QA Results" hint={`${qaResults.length} result${qaResults.length === 1 ? "" : "s"}`} />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-text-muted uppercase tracking-wide border-t border-border">
              <th className="px-5 py-2 font-medium">Summary</th>
              <th className="px-5 py-2 font-medium">Hot Lead</th>
              <th className="px-5 py-2 font-medium">Missing Variables</th>
              <th className="px-5 py-2 font-medium">Follow-up Required</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {qaResults.map((qa) => {
              const missing = emptyPayloadKeys(qa.raw_result || {});
              const appointmentTime = qa.raw_result?.appointment_time;
              const appointmentAddress = qa.raw_result?.appointment_address;
              const hasFollowUp = Boolean(appointmentTime) || Boolean(appointmentAddress);
              return (
                <tr key={qa.id}>
                  <td className="px-5 py-2.5 text-on-surface max-w-xs truncate" title={qa.summary}>
                    {qa.summary || "—"}
                  </td>
                  <td className="px-5 py-2.5">
                    {qa.hot_lead ? (
                      <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-ok/15 text-ok">Yes</span>
                    ) : (
                      <span className="text-text-muted text-xs">No</span>
                    )}
                  </td>
                  <td className="px-5 py-2.5 max-w-xs">
                    {missing.length === 0 ? (
                      <span className="text-text-muted text-xs">—</span>
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        {missing.map((key) => (
                          <span
                            key={key}
                            className="text-[10px] font-mono px-1.5 py-0.5 rounded-full bg-warn/15 text-warn"
                          >
                            {key}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="px-5 py-2.5 max-w-xs">
                    {hasFollowUp ? (
                      <div className="space-y-1.5">
                        <div className="space-y-0.5">
                          {Boolean(appointmentTime) && (
                            <p className="text-xs text-on-surface">{String(appointmentTime)}</p>
                          )}
                          {Boolean(appointmentAddress) && (
                            <p className="text-xs text-text-muted">{String(appointmentAddress)}</p>
                          )}
                        </div>
                        <FollowUpDispatch
                          executionId={qa.execution}
                          botJourneys={botJourneys ?? []}
                          onDispatchFollowUp={onDispatchFollowUp}
                        />
                      </div>
                    ) : (
                      <span className="text-text-muted text-xs">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
