import { useMemo, useState } from "react";
import { FiMapPin } from "react-icons/fi";
import { Card, CardHeader } from "@/components/Card";
import { domainConfig } from "@/lib/domainConfig";
import type { CallRow } from "@/lib/types";
import { formatDate, phoneOf, str } from "./shared";

// Calls grouped under the dealer named in their `assigned_dealer_name` disposition.
// Only rendered once some call carries that field, so agents that don't post it never see it.

export const UNMATCHED = "__unmatched__";

// "RAMAA HYUNDAI", "Ramaa Hyundai" and "ramaa" all reduce to "ramaa".
function norm(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]/g, "");
}
function core(s: string): string {
  return norm(s).replace(/hyundai/g, "");
}

export interface Dealer {
  key: string;
  name: string;
  areas: string[];
}

export const DEALERS: Dealer[] = (() => {
  const byKey = new Map<string, Dealer>();
  for (const { area, dealer } of domainConfig.dealers.outlets) {
    const key = core(dealer);
    const entry = byKey.get(key) ?? { key, name: dealer, areas: [] };
    entry.areas.push(area);
    byKey.set(key, entry);
  }
  return [...byKey.values()].sort((a, b) => a.name.localeCompare(b.name));
})();

// Exact match first, then a value that starts with a dealer (e.g. "Koncept Hyundai Okhla").
// The outlet is filled in only when the value also names one of that dealer's areas.
export function matchDealer(value: string): { key: string; area: string | null } {
  const v = core(value);
  const dealer = DEALERS.find((d) => d.key === v) ?? DEALERS.find((d) => v.startsWith(d.key));
  if (!dealer) return { key: UNMATCHED, area: null };
  const area = dealer.areas.find((a) => norm(value).includes(norm(a))) ?? null;
  return { key: dealer.key, area };
}

interface Assigned {
  row: CallRow;
  raw: string;
  area: string | null;
}

export function DealersSection({ rows }: { rows: CallRow[] }) {
  const field = domainConfig.dealers.field;

  const groups = useMemo(() => {
    const out = new Map<string, Assigned[]>();
    for (const row of rows) {
      const raw = str(row.variables[field]).trim();
      if (!raw) continue;
      const { key, area } = matchDealer(raw);
      out.set(key, [...(out.get(key) ?? []), { row, raw, area }]);
    }
    for (const list of out.values()) list.sort((a, b) => b.row.created_at.localeCompare(a.row.created_at));
    return out;
  }, [rows, field]);

  const total = [...groups.values()].reduce((n, list) => n + list.length, 0);
  const firstWithCalls = DEALERS.find((d) => groups.has(d.key))?.key ?? (groups.has(UNMATCHED) ? UNMATCHED : null);
  const [picked, setPicked] = useState<string | null>(null);
  const selected = picked ?? firstWithCalls;

  if (total === 0) return null;

  const entries: { key: string; name: string; sub: string }[] = [
    ...DEALERS.map((d) => ({ key: d.key, name: d.name, sub: d.areas.join(", ") })),
    ...(groups.has(UNMATCHED) ? [{ key: UNMATCHED, name: "Unrecognised dealer", sub: "Not in the Delhi list" }] : []),
  ];
  const list = selected ? groups.get(selected) ?? [] : [];
  const selectedEntry = entries.find((e) => e.key === selected);

  return (
    <Card className="p-0 overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 pr-5">
        <div className="flex-1 min-w-0">
          <CardHeader
            title="Dealers"
            hint={`${total} customer${total === 1 ? "" : "s"} assigned via ${field}. Pick a dealer to see its customers.`}
          />
        </div>
        <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full bg-primary/10 text-primary">
          <FiMapPin /> {domainConfig.dealers.location}
        </span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[18rem_1fr] border-t border-border">
        <ul className="max-h-[420px] overflow-y-auto border-b lg:border-b-0 lg:border-r border-border divide-y divide-border">
          {entries.map((e) => {
            const count = groups.get(e.key)?.length ?? 0;
            const active = e.key === selected;
            return (
              <li key={e.key}>
                <button
                  onClick={() => setPicked(e.key)}
                  className={`w-full text-left px-4 py-2.5 flex items-start gap-2 transition-colors ${
                    active ? "bg-primary/10" : "hover:bg-surface-container/50"
                  }`}
                >
                  <span className="flex-1 min-w-0">
                    <span className={`block text-sm truncate ${active ? "font-semibold text-primary" : "text-on-surface"}`}>
                      {e.name}
                    </span>
                    <span className="block text-[11px] text-text-muted truncate" title={e.sub}>
                      {e.sub}
                    </span>
                  </span>
                  <span
                    className={`shrink-0 text-xs font-medium px-2 py-0.5 rounded-full ${
                      count ? "bg-primary/15 text-primary" : "bg-text-muted/10 text-text-muted"
                    }`}
                  >
                    {count}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>

        <div className="max-h-[420px] overflow-auto">
          {list.length === 0 ? (
            <p className="px-5 py-10 text-center text-sm text-text-muted">
              No customers assigned to {selectedEntry?.name ?? "this dealer"} yet.
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-surface z-10">
                <tr className="text-left text-xs text-text-muted uppercase tracking-wide border-b border-border">
                  <th className="px-3 py-2 font-medium">Customer</th>
                  <th className="px-3 py-2 font-medium">{selected === UNMATCHED ? "Dealer (as sent)" : "Outlet"}</th>
                  <th className="px-3 py-2 font-medium">Model</th>
                  <th className="px-3 py-2 font-medium">Interest</th>
                  <th className="px-3 py-2 font-medium">Appointment</th>
                  <th className="px-3 py-2 font-medium">Received</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {list.map(({ row, raw, area }) => {
                  const v = row.variables;
                  const appointment = [str(v.appointment_date), str(v.appointment_time)].filter(Boolean).join(" ");
                  return (
                    <tr key={row.id}>
                      <td className="px-3 py-2.5">
                        <p className="text-on-surface">{str(v.customer_name) || "—"}</p>
                        <p className="text-xs text-text-muted font-mono">{phoneOf(row)}</p>
                      </td>
                      <td className="px-3 py-2.5 text-xs">
                        {selected === UNMATCHED ? raw : area ?? domainConfig.dealers.location}
                      </td>
                      <td className="px-3 py-2.5">{str(v.model_of_interest) || str(v.model_name) || "—"}</td>
                      <td className="px-3 py-2.5">{str(v.interest_type) || "—"}</td>
                      <td className="px-3 py-2.5">
                        <p className="text-xs text-on-surface">{appointment || "—"}</p>
                        {str(v.appointment_place) && (
                          <p className="text-xs text-text-muted">{str(v.appointment_place)}</p>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-xs text-text-muted whitespace-nowrap">
                        {str(v.call_start_time) || formatDate(row.created_at)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </Card>
  );
}
