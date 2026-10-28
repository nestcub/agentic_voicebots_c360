"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import { Car, ChevronDown, Clock, MapPin, PhoneCall, Store } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { TablePagination, usePagination } from "@/components/common/TablePagination";
import { DEALERS, UNMATCHED, matchDealer } from "@/components/process-agents/DealersSection";
import { formatDuration, phoneOf, str } from "@/components/process-agents/shared";
import { domainConfig } from "@/lib/domainConfig";
import type { CallRow } from "@/lib/types";

// Main-dashboard view of customer calls, filtered by location and by the dealer
// named in each call's `assigned_dealer_name` disposition.

const ALL = "all";
const NONE = "__none__"; // calls with no dealer assigned

// Internal flags left out of a call's expanded details (the recording gets its own player).
const HIDDEN_DETAILS = new Set(["recording_url", "is_test", "is_demo"]);

interface Tagged {
  row: CallRow;
  dealerKey: string; // a DEALERS key, UNMATCHED, or NONE
  dealerRaw: string;
  area: string | null;
}

function initials(s: string): string {
  const parts = s.split(/\s+/).filter(Boolean);
  if (parts.length > 1) return (parts[0][0] + parts[1][0]).toUpperCase();
  return /^[+\d]/.test(s) ? s.replace(/\D/g, "").slice(-2) : s.slice(0, 2).toUpperCase();
}

const SENTIMENT_STYLES: { match: RegExp; cls: string; dot: string }[] = [
  { match: /pos|happy|good/i, cls: "bg-emerald-50 text-emerald-700 ring-emerald-600/20", dot: "bg-emerald-500" },
  { match: /neg|angry|bad|unhappy/i, cls: "bg-rose-50 text-rose-700 ring-rose-600/20", dot: "bg-rose-500" },
  { match: /neu/i, cls: "bg-slate-50 text-slate-700 ring-slate-500/20", dot: "bg-slate-400" },
];

function SentimentPill({ value }: { value: string }) {
  const v = value.trim();
  if (!v) return null;
  const style = SENTIMENT_STYLES.find((s) => s.match.test(v)) ?? {
    cls: "bg-amber-50 text-amber-700 ring-amber-600/20",
    dot: "bg-amber-500",
  };
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2 py-1 rounded-full ring-1 ring-inset capitalize ${style.cls}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${style.dot}`} />
      {v.replace(/_/g, " ").toLowerCase()}
    </span>
  );
}

export function DealerCallsCard({ rows, loading }: { rows: CallRow[]; loading: boolean }) {
  const { field, location } = domainConfig.dealers;
  const [dealer, setDealer] = useState<string>(ALL);
  const [expanded, setExpanded] = useState<number | null>(null);

  const tagged = useMemo<Tagged[]>(
    () =>
      rows.map((row) => {
        const raw = str(row.variables[field]).trim();
        if (!raw) return { row, dealerKey: NONE, dealerRaw: "", area: null };
        const { key, area } = matchDealer(raw);
        return { row, dealerKey: key, dealerRaw: raw, area };
      }),
    [rows, field],
  );

  const counts = useMemo(() => {
    const out = new Map<string, number>();
    for (const t of tagged) out.set(t.dealerKey, (out.get(t.dealerKey) ?? 0) + 1);
    return out;
  }, [tagged]);

  const visible = useMemo(
    () => (dealer === ALL ? tagged : tagged.filter((t) => t.dealerKey === dealer)),
    [tagged, dealer],
  );

  const pagination = usePagination(visible);
  const { setPage } = pagination;
  useEffect(() => {
    setPage(1);
    setExpanded(null);
  }, [dealer, setPage]);

  // Known dealer -> its canonical name (followed by the outlet area when the value names one); otherwise as sent.
  const dealerName = (t: Tagged) => DEALERS.find((d) => d.key === t.dealerKey)?.name ?? t.dealerRaw;

  return (
    <Card className="gap-4">
      <CardHeader className="flex flex-col sm:flex-row sm:items-start gap-3">
        <div className="flex items-start gap-3 flex-1 min-w-0">
          <div className="w-10 h-10 shrink-0 rounded-lg bg-accent flex items-center justify-center">
            <PhoneCall className="w-5 h-5 text-primary" />
          </div>
          <div className="space-y-1">
            <CardTitle>New Car Enquiries</CardTitle>
            <CardDescription>
              {loading ? "Loading…" : `${visible.length} of ${tagged.length} enquir${tagged.length === 1 ? "y" : "ies"}`}
            </CardDescription>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={location} disabled>
            <SelectTrigger className="w-36" aria-label="Location">
              <MapPin className="text-muted-foreground" />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={location}>{location}</SelectItem>
            </SelectContent>
          </Select>
          <Select value={dealer} onValueChange={setDealer}>
            <SelectTrigger className="w-60" aria-label="Dealer">
              <Store className="text-muted-foreground" />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All dealers ({tagged.length})</SelectItem>
              {DEALERS.map((d) => (
                <SelectItem key={d.key} value={d.key}>
                  {d.name} ({counts.get(d.key) ?? 0})
                </SelectItem>
              ))}
              {counts.has(UNMATCHED) && (
                <SelectItem value={UNMATCHED}>Unrecognised dealer ({counts.get(UNMATCHED)})</SelectItem>
              )}
              {counts.has(NONE) && <SelectItem value={NONE}>No dealer assigned ({counts.get(NONE)})</SelectItem>}
            </SelectContent>
          </Select>
        </div>
      </CardHeader>

      <CardContent className="px-0">
        {loading ? (
          <div className="px-6 space-y-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : visible.length === 0 ? (
          <p className="px-6 py-6 text-center text-sm text-muted-foreground">
            {tagged.length === 0 ? "No enquiries yet." : "No enquiries for this dealer yet."}
          </p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-[11px] text-muted-foreground uppercase tracking-wider border-y border-border bg-muted/40">
                    <th className="pl-6 pr-3 py-2.5 font-medium">Customer</th>
                    <th className="px-3 py-2.5 font-medium">Dealer</th>
                    <th className="px-3 py-2.5 font-medium">Location</th>
                    <th className="px-3 py-2.5 font-medium">Model</th>
                    <th className="px-3 py-2.5 font-medium">Sentiment</th>
                    <th className="px-3 py-2.5 font-medium">Duration</th>
                    <th className="pl-3 pr-6 py-2.5 w-8" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {pagination.pageItems.map((t) => {
                    const { row } = t;
                    const v = row.variables;
                    const isOpen = expanded === row.id;
                    const name = str(v.customer_name).trim();
                    const phone = phoneOf(row);
                    const model = str(v.model_of_interest) || str(v.model_name);
                    const details = Object.entries(v).filter(([key, value]) => !HIDDEN_DETAILS.has(key) && str(value).trim());
                    return (
                      <Fragment key={row.id}>
                        <tr
                          className={`group cursor-pointer transition-colors hover:bg-accent/40 ${isOpen ? "bg-accent/40" : ""}`}
                          onClick={() => setExpanded(isOpen ? null : row.id)}
                        >
                          <td className="pl-6 pr-3 py-3">
                            <div className="flex items-center gap-3">
                              <span className="w-9 h-9 shrink-0 rounded-full bg-primary/10 text-primary text-xs font-semibold flex items-center justify-center">
                                {initials(name || phone)}
                              </span>
                              <div className="min-w-0">
                                <p className="font-medium text-foreground truncate">
                                  {name || phone}
                                  {v.is_demo === "true" && (
                                    <span className="ml-2 align-middle text-[10px] font-medium uppercase tracking-wide px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">
                                      Demo
                                    </span>
                                  )}
                                </p>
                                {name && <p className="text-xs text-muted-foreground font-mono">{phone}</p>}
                              </div>
                            </div>
                          </td>
                          <td className="px-3 py-3">
                            {t.dealerKey === NONE ? (
                              <span className="text-xs text-muted-foreground italic">Not assigned</span>
                            ) : (
                              <div className="flex items-start gap-2">
                                <Store className="w-4 h-4 mt-0.5 shrink-0 text-muted-foreground" />
                                <p className="font-medium text-foreground">
                                  {dealerName(t)}
                                  {t.area && `, ${t.area}`}
                                </p>
                              </div>
                            )}
                          </td>
                          <td className="px-3 py-3">
                            <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full bg-muted text-foreground whitespace-nowrap">
                              <MapPin className="w-3 h-3 text-primary" /> {t.area ? `${location}, ${t.area}` : location}
                            </span>
                          </td>
                          <td className="px-3 py-3">
                            {model && (
                              <span className="inline-flex items-center gap-1.5 text-xs font-medium px-2 py-1 rounded-md bg-primary/10 text-primary">
                                <Car className="w-3.5 h-3.5" /> {model}
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-3">
                            <SentimentPill value={str(v.sentiment) || str(v.call_sentiment)} />
                          </td>
                          <td className="px-3 py-3">
                            {row.duration !== null && (
                              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground tabular-nums whitespace-nowrap">
                                <Clock className="w-3.5 h-3.5" /> {formatDuration(row.duration)}
                              </span>
                            )}
                          </td>
                          <td className="pl-3 pr-6 py-3 text-muted-foreground">
                            <ChevronDown
                              className={`w-4 h-4 transition-transform group-hover:text-foreground ${isOpen ? "rotate-180" : ""}`}
                            />
                          </td>
                        </tr>
                        {isOpen && (
                          <tr className="bg-accent/20">
                            <td colSpan={7} className="px-6 py-4">
                              {str(v.recording_url) && (
                                <audio controls preload="none" src={str(v.recording_url)} className="mb-4 w-full max-w-md" />
                              )}
                              <dl className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
                                {details
                                  .sort(([a], [b]) => a.localeCompare(b))
                                  .map(([key, value]) => (
                                    <div key={key} className="rounded-lg border border-border bg-card px-3 py-2">
                                      <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">
                                        {key.replace(/_/g, " ")}
                                      </dt>
                                      <dd className="text-sm text-foreground wrap-break-word">{str(value)}</dd>
                                    </div>
                                  ))}
                              </dl>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <TablePagination
              page={pagination.page}
              pageCount={pagination.pageCount}
              pageSize={pagination.pageSize}
              total={pagination.total}
              start={pagination.start}
              onPageChange={pagination.setPage}
              onPageSizeChange={pagination.setPageSize}
            />
          </>
        )}
      </CardContent>
    </Card>
  );
}
