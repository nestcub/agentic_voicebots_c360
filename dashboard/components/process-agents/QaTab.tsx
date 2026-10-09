import { useState } from "react";
import { ClipboardCheck, Flame, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorAlert } from "@/components/common/ErrorAlert";
import { TablePagination, usePagination } from "@/components/common/TablePagination";
import { ToneBadge } from "@/components/StatusBadge";
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
    return <span className="text-muted-foreground text-xs">—</span>;
  }

  return (
    <div className="space-y-1 min-w-40">
      <div className="flex items-center gap-1.5">
        {ordered.length > 1 && (
          <div className="w-40">
            <NativeSelect
              size="sm"
              value={selectedId}
              onChange={(e) => setSelectedId(e.target.value ? Number(e.target.value) : "")}
              className="text-xs"
            >
              {ordered.map((j) => (
                <NativeSelectOption key={j.id} value={j.id}>
                  {j.name}
                  {j.voice_bot?.bot_name ? ` — ${j.voice_bot.bot_name}` : ""}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </div>
        )}
        <Button size="sm" onClick={handleDispatch} disabled={dispatching || selectedId === ""}>
          {dispatching ? <Spinner /> : <Send />}
          Follow-up
        </Button>
      </div>
      {result && <p className="text-[11px] text-ok">{result}</p>}
      {error && <p className="text-[11px] text-bad">{error}</p>}
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
    return <Skeleton className="h-40 rounded-xl" />;
  }
  if (error) {
    return <ErrorAlert message={error} />;
  }
  if (!qaResults || qaResults.length === 0) {
    return (
      <EmptyState
        icon={ClipboardCheck}
        title="No QA results yet"
        description="Results appear here as calls complete and are scored."
      />
    );
  }

  return <QaTable qaResults={qaResults} botJourneys={botJourneys} onDispatchFollowUp={onDispatchFollowUp} />;
}

function QaTable({
  qaResults,
  botJourneys,
  onDispatchFollowUp,
}: {
  qaResults: QaResult[];
  botJourneys: BotJourney[] | null;
  onDispatchFollowUp: (executionId: number, botJourneyId: number) => Promise<DispatchSingleCallResult>;
}) {
  const pagination = usePagination(qaResults);
  return (
    <Card className="gap-0 py-0 overflow-hidden">
      <div className="px-5 py-4 border-b border-border">
        <p className="font-semibold text-foreground">QA Results</p>
        <p className="text-xs text-muted-foreground mt-0.5">
          {qaResults.length} result{qaResults.length === 1 ? "" : "s"}
        </p>
      </div>
      <Table>
        <TableHeader className="bg-muted">
          <TableRow>
            <TableHead className="px-5">Summary</TableHead>
            <TableHead>Hot Lead</TableHead>
            <TableHead>Missing Variables</TableHead>
            <TableHead className="pr-5">Follow-up Required</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {pagination.pageItems.map((qa) => {
            const missing = emptyPayloadKeys(qa.raw_result || {});
            const appointmentTime = qa.raw_result?.appointment_time;
            const appointmentAddress = qa.raw_result?.appointment_address;
            const hasFollowUp = Boolean(appointmentTime) || Boolean(appointmentAddress);
            return (
              <TableRow key={qa.id} className="align-top">
                <TableCell className="px-5 max-w-xs truncate" title={qa.summary}>
                  {qa.summary || "—"}
                </TableCell>
                <TableCell>
                  {qa.hot_lead ? (
                    <ToneBadge tone="ok" className="normal-case">
                      <Flame /> Hot
                    </ToneBadge>
                  ) : (
                    <span className="text-muted-foreground text-xs">No</span>
                  )}
                </TableCell>
                <TableCell className="max-w-xs whitespace-normal">
                  {missing.length === 0 ? (
                    <span className="text-muted-foreground text-xs">—</span>
                  ) : (
                    <div className="flex flex-wrap gap-1">
                      {missing.map((key) => (
                        <ToneBadge key={key} tone="warn" className="normal-case font-mono text-[10px]">
                          {key}
                        </ToneBadge>
                      ))}
                    </div>
                  )}
                </TableCell>
                <TableCell className="pr-5 max-w-xs whitespace-normal">
                  {hasFollowUp ? (
                    <div className="space-y-2">
                      <div className="space-y-0.5">
                        {Boolean(appointmentTime) && <p className="text-xs text-foreground">{String(appointmentTime)}</p>}
                        {Boolean(appointmentAddress) && (
                          <p className="text-xs text-muted-foreground">{String(appointmentAddress)}</p>
                        )}
                      </div>
                      <FollowUpDispatch
                        executionId={qa.execution}
                        botJourneys={botJourneys ?? []}
                        onDispatchFollowUp={onDispatchFollowUp}
                      />
                    </div>
                  ) : (
                    <span className="text-muted-foreground text-xs">—</span>
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      <TablePagination
        page={pagination.page}
        pageCount={pagination.pageCount}
        pageSize={pagination.pageSize}
        total={pagination.total}
        start={pagination.start}
        onPageChange={pagination.setPage}
        onPageSizeChange={pagination.setPageSize}
      />
    </Card>
  );
}
