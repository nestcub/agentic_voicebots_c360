"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowRight, CircleCheck, CircleX, Hourglass, ListFilter, Upload, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { UploadCampaignModal } from "@/components/leads/UploadCampaignModal";
import { PageHeader } from "@/components/common/PageHeader";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorAlert } from "@/components/common/ErrorAlert";
import { ExecutionStatusBadge, executionStatusTone } from "@/components/StatusBadge";
import {
  listChannels,
  listProcessAgents,
  listCampaigns,
  listCampaignLeads,
} from "@/lib/telehubApi";
import type { Channel, ProcessAgentSummary, CampaignSummary, CampaignLead } from "@/lib/types";

const POLL_MS = 2500;

// Counts the leads already loaded for the selected campaign — no extra request.
function summarize(leads: CampaignLead[]) {
  let completed = 0;
  let failed = 0;
  for (const l of leads) {
    const tone = executionStatusTone(l.status);
    if (tone === "ok") completed += 1;
    else if (tone === "bad") failed += 1;
  }
  return { total: leads.length, completed, failed, inProgress: leads.length - completed - failed };
}

function SummaryTile({
  label,
  value,
  icon: Icon,
  className,
}: {
  label: string;
  value: number;
  icon: React.ComponentType<{ className?: string }>;
  className: string;
}) {
  return (
    <Card className="p-4 flex-row items-center gap-3">
      <div className={`w-9 h-9 shrink-0 rounded-lg flex items-center justify-center ${className}`}>
        <Icon className="w-4 h-4" />
      </div>
      <div>
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-lg font-bold text-foreground tabular-nums">{value}</p>
      </div>
    </Card>
  );
}

export default function LeadsPage() {
  // Channels
  const [channels, setChannels] = useState<Channel[]>([]);
  const [channelsLoading, setChannelsLoading] = useState(true);
  const [channelsError, setChannelsError] = useState<string | null>(null);
  const [selectedChannelId, setSelectedChannelId] = useState<number | null>(null);

  // Process Agents (scoped to selected channel)
  const [processAgents, setProcessAgents] = useState<ProcessAgentSummary[]>([]);
  const [processAgentsLoading, setProcessAgentsLoading] = useState(false);
  const [processAgentsError, setProcessAgentsError] = useState<string | null>(null);
  const [selectedProcessAgentId, setSelectedProcessAgentId] = useState<number | null>(null);

  // Campaigns (scoped to selected process agent)
  const [campaigns, setCampaigns] = useState<CampaignSummary[]>([]);
  const [campaignsLoading, setCampaignsLoading] = useState(false);
  const [campaignsError, setCampaignsError] = useState<string | null>(null);
  const [selectedCampaignId, setSelectedCampaignId] = useState<string | null>(null);

  // Leads (scoped to selected campaign, polled)
  const [leads, setLeads] = useState<CampaignLead[]>([]);
  const [leadsLoading, setLeadsLoading] = useState(false);
  const [leadsError, setLeadsError] = useState<string | null>(null);

  const [modalOpen, setModalOpen] = useState(false);

  const requestedCampaignRef = useRef<string | null>(null);

  // ── Load channels on mount ───────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    setChannelsLoading(true);
    setChannelsError(null);
    listChannels()
      .then((data) => {
        if (cancelled) return;
        setChannels(data);
      })
      .catch((e) => {
        if (cancelled) return;
        setChannelsError(e instanceof Error ? e.message : "Failed to load channels");
      })
      .finally(() => {
        if (cancelled) return;
        setChannelsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // ── Load process agents whenever the selected channel changes ───────
  useEffect(() => {
    setSelectedProcessAgentId(null);
    setProcessAgents([]);
    setProcessAgentsError(null);

    if (selectedChannelId === null) {
      setProcessAgentsLoading(false);
      return;
    }

    let cancelled = false;
    setProcessAgentsLoading(true);
    listProcessAgents(selectedChannelId)
      .then((data) => {
        if (cancelled) return;
        setProcessAgents(data);
      })
      .catch((e) => {
        if (cancelled) return;
        setProcessAgentsError(e instanceof Error ? e.message : "Failed to load process agents");
      })
      .finally(() => {
        if (cancelled) return;
        setProcessAgentsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedChannelId]);

  // ── Load campaigns whenever the selected process agent changes ─────────
  function loadCampaigns(processAgentId: number) {
    setCampaignsLoading(true);
    setCampaignsError(null);
    return listCampaigns(processAgentId)
      .then((data) => {
        setCampaigns(data);
        return data;
      })
      .catch((e) => {
        setCampaignsError(e instanceof Error ? e.message : "Failed to load campaigns");
        setCampaigns([]);
        return [] as CampaignSummary[];
      })
      .finally(() => {
        setCampaignsLoading(false);
      });
  }

  useEffect(() => {
    setSelectedCampaignId(null);
    setCampaigns([]);
    setCampaignsError(null);

    if (selectedProcessAgentId === null) {
      setCampaignsLoading(false);
      return;
    }

    loadCampaigns(selectedProcessAgentId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedProcessAgentId]);

  // Auto-select the most-recently-created campaign once the list loads, if
  // nothing is selected yet.
  useEffect(() => {
    if (selectedCampaignId !== null || campaigns.length === 0) return;
    const mostRecent = campaigns.reduce((a, b) => (a.created_at >= b.created_at ? a : b));
    setSelectedCampaignId(mostRecent.campaign_id);
  }, [campaigns, selectedCampaignId]);

  // ── Poll leads for the selected campaign ────────────────────────────────
  useEffect(() => {
    requestedCampaignRef.current = selectedCampaignId;

    if (selectedProcessAgentId === null || selectedCampaignId === null) {
      setLeads([]);
      return;
    }

    const processAgentId = selectedProcessAgentId;
    const campaignId = selectedCampaignId;
    let cancelled = false;

    function poll(isInitial: boolean) {
      if (isInitial) {
        setLeadsLoading(true);
        setLeadsError(null);
      }
      listCampaignLeads(processAgentId, campaignId)
        .then((data) => {
          if (cancelled || requestedCampaignRef.current !== campaignId) return;
          setLeads(data);
        })
        .catch((e) => {
          if (cancelled || requestedCampaignRef.current !== campaignId) return;
          // Background poll failures stay silent (keep showing last known leads);
          // only the initial fetch for a newly selected campaign surfaces an error.
          if (isInitial) {
            setLeadsError(e instanceof Error ? e.message : "Failed to load leads");
            setLeads([]);
          }
        })
        .finally(() => {
          if (cancelled || requestedCampaignRef.current !== campaignId) return;
          if (isInitial) setLeadsLoading(false);
        });
    }

    poll(true);
    const intervalId = setInterval(() => poll(false), POLL_MS);

    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, [selectedProcessAgentId, selectedCampaignId]);

  function handleLaunched(result: { campaignId: string; processAgentId: number }) {
    setModalOpen(false);
    if (result.processAgentId !== selectedProcessAgentId) {
      // Modal launched against a different process agent than the one currently
      // selected here (e.g. it re-asked). Follow the user's new selection.
      setSelectedProcessAgentId(result.processAgentId);
      setSelectedCampaignId(result.campaignId);
      return;
    }
    loadCampaigns(result.processAgentId).then(() => {
      setSelectedCampaignId(result.campaignId);
    });
  }

  const variableKeys = Array.from(
    new Set(leads.flatMap((l) => Object.keys(l.variables ?? {}))),
  ).filter((k) => k !== "to_number");

  const selectedProcessAgent = processAgents.find((p) => p.id === selectedProcessAgentId) ?? null;
  const summary = summarize(leads);

  const uploadButton = (
    <Button onClick={() => setModalOpen(true)}>
      <Upload /> Upload Campaign
    </Button>
  );

  return (
    <div className="space-y-6">
      <PageHeader
        icon={Users}
        title="Leads"
        description="Upload campaigns and track leads through a process"
        actions={uploadButton}
      />

      {/* Channel / Process / Campaign filter bar */}
      <Card className="p-4 gap-3">
        <div className="flex flex-wrap items-end gap-4">
          <ListFilter className="w-4 h-4 text-muted-foreground mb-2.5 hidden sm:block" />
          <div className="space-y-1.5 w-full sm:w-52">
            <Label htmlFor="leads-channel" className="text-xs text-muted-foreground">
              Channel
            </Label>
            <NativeSelect
              id="leads-channel"
              value={selectedChannelId ?? ""}
              onChange={(e) => setSelectedChannelId(e.target.value ? Number(e.target.value) : null)}
              disabled={channelsLoading}
            >
              <NativeSelectOption value="">{channelsLoading ? "Loading…" : "Select a channel"}</NativeSelectOption>
              {channels.map((d) => (
                <NativeSelectOption key={d.id} value={d.id}>
                  {d.name}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </div>

          <div className="space-y-1.5 w-full sm:w-56">
            <Label htmlFor="leads-process" className="text-xs text-muted-foreground">
              Process
            </Label>
            <NativeSelect
              id="leads-process"
              value={selectedProcessAgentId ?? ""}
              onChange={(e) => setSelectedProcessAgentId(e.target.value ? Number(e.target.value) : null)}
              disabled={selectedChannelId === null || processAgentsLoading}
            >
              <NativeSelectOption value="">
                {selectedChannelId === null
                  ? "Select a channel first"
                  : processAgentsLoading
                    ? "Loading…"
                    : "Select an agent"}
              </NativeSelectOption>
              {processAgents.map((p) => (
                <NativeSelectOption key={p.id} value={p.id}>
                  {p.name}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </div>

          <div className="space-y-1.5 w-full sm:w-64">
            <Label htmlFor="leads-campaign" className="text-xs text-muted-foreground">
              Campaign
            </Label>
            <NativeSelect
              id="leads-campaign"
              value={selectedCampaignId ?? ""}
              onChange={(e) => setSelectedCampaignId(e.target.value || null)}
              disabled={campaigns.length === 0}
            >
              {campaigns.length === 0 && (
                <NativeSelectOption value="">
                  {selectedProcessAgentId === null
                    ? "Select a process first"
                    : campaignsLoading
                      ? "Loading…"
                      : "No campaigns yet"}
                </NativeSelectOption>
              )}
              {campaigns.map((c) => (
                <NativeSelectOption key={c.campaign_id} value={c.campaign_id}>
                  {c.campaign_id} ({c.lead_count} leads)
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </div>

          {selectedProcessAgentId !== null && (
            <Button variant="link" asChild className="sm:ml-auto px-0">
              <Link href={`/process-agents/${selectedProcessAgentId}`}>
                View {selectedProcessAgent?.name ?? "Agent"} <ArrowRight />
              </Link>
            </Button>
          )}
        </div>

        {channelsError && <p className="text-xs text-bad">{channelsError}</p>}
        {processAgentsError && <p className="text-xs text-bad">{processAgentsError}</p>}
      </Card>

      {/* Nothing selected yet */}
      {selectedProcessAgentId === null && (
        <EmptyState
          icon={ListFilter}
          title="Pick a process"
          description="Select a channel and process above to view its campaigns and leads."
        />
      )}

      {selectedProcessAgentId !== null && (
        <>
          {campaignsLoading && <Skeleton className="h-40 rounded-xl" />}

          {campaignsError && (
            <ErrorAlert
              message={campaignsError}
              action={
                <Button variant="outline" size="sm" onClick={() => loadCampaigns(selectedProcessAgentId)}>
                  Retry
                </Button>
              }
            />
          )}

          {!campaignsLoading && !campaignsError && campaigns.length === 0 && (
            <EmptyState
              icon={Upload}
              title="No campaigns yet"
              description="Upload a campaign to see leads here."
              action={uploadButton}
            />
          )}

          {selectedCampaignId && (
            <>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                <SummaryTile label="Leads" value={summary.total} icon={Users} className="bg-accent text-primary" />
                <SummaryTile label="In progress" value={summary.inProgress} icon={Hourglass} className="bg-warn/10 text-warn" />
                <SummaryTile label="Completed" value={summary.completed} icon={CircleCheck} className="bg-ok/10 text-ok" />
                <SummaryTile label="Failed / DND" value={summary.failed} icon={CircleX} className="bg-bad/10 text-bad" />
              </div>

              <Card className="gap-0 py-0 overflow-hidden">
                <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-border">
                  <div>
                    <p className="font-semibold text-foreground">Campaign Leads</p>
                    <p className="text-xs text-muted-foreground mt-0.5">{selectedCampaignId}</p>
                  </div>
                  <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <span className="relative flex w-2 h-2">
                      <span className="absolute inline-flex h-full w-full rounded-full bg-ok opacity-60 animate-ping" />
                      <span className="relative inline-flex w-2 h-2 rounded-full bg-ok" />
                    </span>
                    Live
                  </span>
                </div>
                {leadsLoading ? (
                  <div className="p-5 space-y-3">
                    {[0, 1, 2, 3].map((i) => (
                      <Skeleton key={i} className="h-8" />
                    ))}
                  </div>
                ) : leadsError ? (
                  <div className="p-5">
                    <ErrorAlert message={leadsError} />
                  </div>
                ) : (
                  <div className="max-h-[60vh] overflow-auto">
                    <Table>
                      <TableHeader className="sticky top-0 z-10 bg-muted">
                        <TableRow>
                          <TableHead className="px-5">Lead ID</TableHead>
                          <TableHead>To Number</TableHead>
                          {variableKeys.map((key) => (
                            <TableHead key={key}>{key}</TableHead>
                          ))}
                          <TableHead>Status</TableHead>
                          <TableHead className="pr-5">Current Node</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {leads.map((l) => (
                          <TableRow key={l.id}>
                            <TableCell className="px-5 font-medium">{l.lead_id}</TableCell>
                            <TableCell className="font-mono text-xs">
                              {typeof l.variables?.to_number === "string" || typeof l.variables?.to_number === "number"
                                ? String(l.variables.to_number)
                                : "—"}
                            </TableCell>
                            {variableKeys.map((key) => (
                              <TableCell key={key} className="text-muted-foreground">
                                {l.variables?.[key] !== undefined && l.variables?.[key] !== null
                                  ? String(l.variables[key])
                                  : "—"}
                              </TableCell>
                            ))}
                            <TableCell>
                              <ExecutionStatusBadge status={l.status} />
                            </TableCell>
                            <TableCell className="pr-5 text-muted-foreground">{l.current_node || "—"}</TableCell>
                          </TableRow>
                        ))}
                        {leads.length === 0 && (
                          <TableRow>
                            <TableCell colSpan={4 + variableKeys.length} className="py-10 text-center text-muted-foreground">
                              No leads found for this campaign.
                            </TableCell>
                          </TableRow>
                        )}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </Card>
            </>
          )}
        </>
      )}

      <UploadCampaignModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onLaunched={handleLaunched}
        initialProcessAgentId={selectedProcessAgentId ?? undefined}
      />
    </div>
  );
}
