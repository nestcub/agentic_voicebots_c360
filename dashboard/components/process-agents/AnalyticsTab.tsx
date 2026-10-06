import { Card, CardHeader } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
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
    return <div className="h-32 bg-surface-container rounded-xl animate-pulse" />;
  }
  if (error) {
    return <div className="text-sm text-bad bg-bad/10 border border-bad/30 rounded-lg px-4 py-3">{error}</div>;
  }
  if (!data || data.variable_keys.length === 0) {
    return (
      <Card className="p-8 text-center">
        <p className="text-sm text-text-muted">
          No dispositions / variables configured for this process — add some in the wizard&apos;s Analytics
          step.
        </p>
      </Card>
    );
  }
  if (data.rows.length === 0) {
    return (
      <Card className="p-8 text-center">
        <p className="text-sm text-text-muted">
          No executions yet — values populate once Chat360 posts a call outcome back.
        </p>
      </Card>
    );
  }

  // Analytics-source variables carry a display label (the wizard's "label"
  // input on that step); business-rules-source ones don't, so fall back to
  // the raw key.
  const labelByKey = new Map(agent.variables.map((v) => [v.key, v.label || v.key]));

  return (
    <Card className="p-0 overflow-hidden">
      <CardHeader
        title="Dispositions / Variables"
        hint={`${data.variable_keys.length} variable${data.variable_keys.length === 1 ? "" : "s"} · ${
          data.rows.length
        } execution${data.rows.length === 1 ? "" : "s"}`}
      />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-text-muted uppercase tracking-wide border-t border-border">
              <th className="px-5 py-2 font-medium sticky left-0 bg-surface">Lead</th>
              <th className="px-5 py-2 font-medium">Status</th>
              {data.variable_keys.map((key) => (
                <th key={key} className="px-5 py-2 font-medium whitespace-nowrap" title={key}>
                  {labelByKey.get(key) ?? key}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {data.rows.map((row) => (
              <tr key={row.execution_id}>
                <td className="px-5 py-2.5 text-on-surface sticky left-0 bg-surface">{row.lead_id}</td>
                <td className="px-5 py-2.5">
                  <StatusBadge status={row.status} />
                </td>
                {data.variable_keys.map((key) => {
                  const formatted = formatCellValue(row.values[key]);
                  return (
                    <td key={key} className="px-5 py-2.5 whitespace-nowrap">
                      {formatted ? (
                        <span className="text-text-muted">{formatted}</span>
                      ) : (
                        <span className="text-xs px-1.5 py-0.5 rounded-full bg-warn/15 text-warn">missing</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
