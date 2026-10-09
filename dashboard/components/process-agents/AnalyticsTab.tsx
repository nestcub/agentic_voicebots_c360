import { ChartColumn, Inbox } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorAlert } from "@/components/common/ErrorAlert";
import { TablePagination, usePagination } from "@/components/common/TablePagination";
import { ExecutionStatusBadge, ToneBadge } from "@/components/StatusBadge";
import type { ProcessAgentAnalytics, ProcessAgentDetail } from "@/lib/types";

// Wizard Analytics step's "Dispositions / Variables" — shows the value Chat360's
// post-call webhook actually filled in for each declared variable, per execution.
// One column per key the process declared (agent.variables), one row per
// execution; a blank cell is exactly what the QA tab's Missing Variables check
// (when enabled) flags for that execution.

function formatCellValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export function AnalyticsTab({
  agent,
  data,
  loading,
  error,
}: {
  agent: ProcessAgentDetail;
  data: ProcessAgentAnalytics | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading) {
    return <Skeleton className="h-40 rounded-xl" />;
  }
  if (error) {
    return <ErrorAlert message={error} />;
  }
  if (!data || data.variable_keys.length === 0) {
    return (
      <EmptyState
        icon={ChartColumn}
        title="No dispositions configured"
        description="Add dispositions / variables in the wizard's Analytics step."
      />
    );
  }
  if (data.rows.length === 0) {
    return (
      <EmptyState
        icon={Inbox}
        title="No executions yet"
        description="Values populate once Chat360 posts a call outcome back."
      />
    );
  }

  // Analytics-source variables carry a display label (the wizard's "label"
  // input on that step); business-rules-source ones don't, so fall back to
  // the raw key.
  const labelByKey = new Map(agent.variables.map((v) => [v.key, v.label || v.key]));

  return <AnalyticsTable data={data} labelByKey={labelByKey} />;
}

function AnalyticsTable({
  data,
  labelByKey,
}: {
  data: ProcessAgentAnalytics;
  labelByKey: Map<string, string>;
}) {
  const pagination = usePagination(data.rows);
  return (
    <Card className="gap-0 py-0 overflow-hidden">
      <div className="px-5 py-4 border-b border-border">
        <p className="font-semibold text-foreground">Dispositions / Variables</p>
        <p className="text-xs text-muted-foreground mt-0.5">
          {data.variable_keys.length} variable{data.variable_keys.length === 1 ? "" : "s"} · {data.rows.length}{" "}
          execution{data.rows.length === 1 ? "" : "s"}
        </p>
      </div>
      <Table>
        <TableHeader className="bg-muted">
          <TableRow>
            <TableHead className="px-5 sticky left-0 bg-muted">Lead</TableHead>
            <TableHead>Status</TableHead>
            {data.variable_keys.map((key) => (
              <TableHead key={key} title={key}>
                {labelByKey.get(key) ?? key}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {pagination.pageItems.map((row) => (
            <TableRow key={row.execution_id}>
              <TableCell className="px-5 font-medium sticky left-0 bg-card">{row.lead_id}</TableCell>
              <TableCell>
                <ExecutionStatusBadge status={row.status} />
              </TableCell>
              {data.variable_keys.map((key) => {
                const formatted = formatCellValue(row.values[key]);
                return (
                  <TableCell key={key}>
                    {formatted ? (
                      <span className="text-muted-foreground">{formatted}</span>
                    ) : (
                      <ToneBadge tone="warn" className="normal-case">
                        missing
                      </ToneBadge>
                    )}
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
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
