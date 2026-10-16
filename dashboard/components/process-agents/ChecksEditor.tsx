// The "when …" condition editor shared by the WhatsApp rules (OmnichannelSection)
// and the hand-offs between stages (StagesSection): a list of checks on call
// variables, combined with all / any. Same language as the backend's
// services/conditions.py.
import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ChannelCheckOp, ChannelRuleCheck } from "@/lib/types";
import { INPUT_CLASS } from "./SettingsPrimitives";

export const OP_LABELS: Record<ChannelCheckOp, string> = {
  exists: "has a value",
  not_exists: "is empty",
  equals: "equals",
  truthy: "is true",
};

/** "customer_name has a value and callback_status equals "required"", or "Always" when empty. */
export function describeChecks(checks: ChannelRuleCheck[], match: "all" | "any"): string {
  if (checks.length === 0) return "Always";
  const parts = checks.map((c) =>
    c.op === "equals" ? `${c.variable} equals "${c.value ?? ""}"` : `${c.variable} ${OP_LABELS[c.op]}`,
  );
  return parts.join(match === "any" ? " or " : " and ");
}

/** Drops blank rows and the value of operators that don't take one, ready to send to the API. */
export function cleanChecks(checks: ChannelRuleCheck[]): ChannelRuleCheck[] {
  return checks
    .filter((c) => c.variable.trim())
    .map((c) => ({
      variable: c.variable.trim(),
      op: c.op,
      ...(c.op === "equals" ? { value: c.value ?? "" } : {}),
    }));
}

export function ChecksEditor({
  checks,
  match,
  onChecks,
  onMatch,
  variableListId,
  heading = "When",
  emptyHint = "No conditions — this always applies.",
}: {
  checks: ChannelRuleCheck[];
  match: "all" | "any";
  onChecks: (checks: ChannelRuleCheck[]) => void;
  onMatch: (match: "all" | "any") => void;
  /** id of a <datalist> of variable names to suggest. */
  variableListId: string;
  heading?: string;
  emptyHint?: string;
}) {
  function setCheck(index: number, patch: Partial<ChannelRuleCheck>) {
    onChecks(checks.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  }

  return (
    <div>
      <p className="text-xs font-medium text-foreground mb-1">{heading}</p>
      {checks.length === 0 && <p className="text-[11px] text-muted-foreground mb-1">{emptyHint}</p>}
      {checks.length > 1 && (
        <select
          value={match}
          onChange={(e) => onMatch(e.target.value as "all" | "any")}
          className={`${INPUT_CLASS} max-w-xs mb-2`}
        >
          <option value="all">All of these are true</option>
          <option value="any">Any of these is true</option>
        </select>
      )}
      <div className="space-y-2">
        {checks.map((check, index) => (
          <div key={index} className="grid grid-cols-1 sm:grid-cols-[1fr_10rem_1fr_auto] gap-2 items-center">
            <input
              list={variableListId}
              value={check.variable}
              onChange={(e) => setCheck(index, { variable: e.target.value })}
              placeholder="variable"
              className={`${INPUT_CLASS} font-mono text-xs`}
            />
            <select
              value={check.op}
              onChange={(e) => setCheck(index, { op: e.target.value as ChannelCheckOp })}
              className={INPUT_CLASS}
            >
              {(Object.keys(OP_LABELS) as ChannelCheckOp[]).map((op) => (
                <option key={op} value={op}>
                  {OP_LABELS[op]}
                </option>
              ))}
            </select>
            {check.op === "equals" ? (
              <input
                value={check.value ?? ""}
                onChange={(e) => setCheck(index, { value: e.target.value })}
                placeholder="value"
                className={INPUT_CLASS}
              />
            ) : (
              <span />
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => onChecks(checks.filter((_, i) => i !== index))}
              aria-label="Remove condition"
            >
              <Trash2 />
            </Button>
          </div>
        ))}
      </div>
      <button
        onClick={() => onChecks([...checks, { variable: "", op: "exists" }])}
        className="mt-2 text-xs text-primary hover:underline"
      >
        + Add condition
      </button>
    </div>
  );
}
