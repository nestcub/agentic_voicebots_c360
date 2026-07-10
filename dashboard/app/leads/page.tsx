"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Card, CardHeader } from "@/components/Card";
import { UploadCampaignModal } from "@/components/leads/UploadCampaignModal";
import {
  listDepartments,
  listProcessAgents,
  listCampaigns,
  listCampaignLeads,
} from "@/lib/telehubApi";
import type { Department, ProcessAgentSummary, CampaignSummary, CampaignLead } from "@/lib/types";

const POLL_MS = 2500;

// Execution.status is a free string (currently only ever "pending" — no dispatch
// engine exists yet). It doesn't belong to the shared lead-status vocabulary in
// lib/domainConfig.ts (StatusBadge), so — same judgment call as ProcessStatusPill
// in app/departments/[id]/page.tsx — this is a small local, component-scoped pill
// instead of forcing a mismatch with that vocabulary.
type Tone = "ok" | "warn" | "bad" | "muted";

const TONE_CLASSES: Record<Tone, string> = {
  ok: "bg-ok/10 text-ok border border-ok/20",
  warn: "bg-warn/10 text-warn border border-warn/20",
  bad: "bg-bad/10 text-bad border border-bad/20",
  muted: "bg-surface-container text-text-muted border border-border",
};

function executionStatusTone(status: string): Tone {
  const s = status.toLowerCase();
  if (s === "completed" || s === "connected" || s === "booked") return "ok";
  if (s === "calling" || s === "dispatching" || s === "retry_pending") return "warn";
  if (s === "failed") return "bad";
  return "muted";
}

function ExecutionStatusPill({ status }: { status: string }) {
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium capitalize ${TONE_CLASSES[executionStatusTone(status)]}`}>
      {status}
    </span>
  );
}

export default function LeadsPage() {
  // Departments
  const [departments, setDepartments] = useState<Department[]>([]);
  const [departmentsLoading, setDepartmentsLoading] = useState(true);
  const [departmentsError, setDepartmentsError] = useState<string | null>(null);
  const [selectedDepartmentId, setSelectedDepartmentId] = useState<number | null>(null);

  // Process Agents (scoped to selected department)
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

  // ── Load departments on mount ───────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    setDepartmentsLoading(true);
    setDepartmentsError(null);
    listDepartments()
      .then((data) => {
        if (cancelled) return;
        setDepartments(data);
      })
      .catch((e) => {
        if (cancelled) return;
        setDepartmentsError(e instanceof Error ? e.message : "Failed to load departments");
      })
      .finally(() => {
        if (cancelled) return;
        setDepartmentsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // ── Load process agents whenever the selected department changes ───────
  useEffect(() => {
    setSelectedProcessAgentId(null);
    setProcessAgents([]);
    setProcessAgentsError(null);

    if (selectedDepartmentId === null) {
      setProcessAgentsLoading(false);
      return;
    }

    let cancelled = false;
    setProcessAgentsLoading(true);
    listProcessAgents(selectedDepartmentId)
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
  }, [selectedDepartmentId]);

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
      setSelectedDepartmentId((prev) => prev); // department selector stays as-is; only process changes
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

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-on-surface">Leads</h1>
        <p className="text-xs text-text-muted mt-0.5">Upload campaigns and track leads through a process</p>
      </div>

      {/* Department / Process Agent selectors */}
      <Card className="p-4">
        <div className="flex flex-wrap items-end gap-4">
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-text-muted">Department</span>
            <select
              value={selectedDepartmentId ?? ""}
              onChange={(e) => setSelectedDepartmentId(e.target.value ? Number(e.target.value) : null)}
              disabled={departmentsLoading}
              className="min-w-50 px-3 py-2 rounded-lg border border-border bg-surface text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-60"
            >
              <option value="">{departmentsLoading ? "Loading…" : "Select a department"}</option>
              {departments.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-text-muted">Process</span>
            <select
              value={selectedProcessAgentId ?? ""}
              onChange={(e) => setSelectedProcessAgentId(e.target.value ? Number(e.target.value) : null)}
              disabled={selectedDepartmentId === null || processAgentsLoading}
              className="min-w-55 px-3 py-2 rounded-lg border border-border bg-surface text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-60"
            >
              <option value="">
                {selectedDepartmentId === null
                  ? "Select a department first"
                  : processAgentsLoading
                    ? "Loading…"
                    : "Select a process"}
              </option>
              {processAgents.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        {departmentsError && <p className="text-xs text-bad mt-2">{departmentsError}</p>}
        {processAgentsError && <p className="text-xs text-bad mt-2">{processAgentsError}</p>}
      </Card>

      {/* Nothing selected yet */}
      {selectedProcessAgentId === null && (
        <Card className="p-10 flex flex-col items-center justify-center text-center">
          <p className="text-sm text-text-muted">
            Select a department and process above to view its campaigns and leads.
          </p>
        </Card>
      )}

      {selectedProcessAgentId !== null && (
        <>
          {/* Header row: process name, upload button, view process link */}
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <p className="text-sm font-semibold text-on-surface">
              {selectedProcessAgent?.name ?? `Process #${selectedProcessAgentId}`}
            </p>
            <div className="flex items-center gap-3">
              <Link
                href={`/process-agents/${selectedProcessAgentId}`}
                className="text-sm font-medium text-primary hover:underline"
              >
                View Process →
              </Link>
              <button
                onClick={() => setModalOpen(true)}
                className="px-4 py-2 rounded-lg bg-primary text-on-primary text-sm font-medium hover:bg-primary-container transition-colors"
              >
                + Upload Campaign
              </button>
            </div>
          </div>

          {campaignsLoading && <p className="text-sm text-text-muted">Loading campaigns…</p>}

          {campaignsError && (
            <Card className="p-4 border-bad/40 bg-bad/5">
              <p className="text-sm text-bad font-medium">{campaignsError}</p>
              <button
                onClick={() => loadCampaigns(selectedProcessAgentId)}
                className="text-xs text-bad underline mt-1"
              >
                Retry
              </button>
            </Card>
          )}

          {!campaignsLoading && !campaignsError && campaigns.length === 0 && (
            <Card className="p-10 flex flex-col items-center justify-center text-center">
              <p className="text-sm text-text-muted mb-3">Upload a campaign to see leads here.</p>
              <button
                onClick={() => setModalOpen(true)}
                className="px-4 py-2 rounded-lg bg-primary text-on-primary text-sm font-medium hover:bg-primary-container transition-colors"
              >
                + Upload Campaign
              </button>
            </Card>
          )}

          {!campaignsLoading && !campaignsError && campaigns.length > 0 && (
            <div className="flex items-center gap-2">
              <label className="text-xs font-medium text-text-muted uppercase tracking-wide">Campaign</label>
              <select
                value={selectedCampaignId ?? ""}
                onChange={(e) => setSelectedCampaignId(e.target.value || null)}
                className="text-sm border border-border rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-primary bg-surface text-on-surface"
              >
                {campaigns.map((c) => (
                  <option key={c.campaign_id} value={c.campaign_id}>
                    {c.campaign_id} ({c.lead_count} leads)
                  </option>
                ))}
              </select>
            </div>
          )}

          {selectedCampaignId && (
            <Card className="p-0 overflow-hidden">
              <CardHeader title="Campaign Leads" hint={`${leads.length} leads`} />
              <div className="overflow-x-auto">
                {leadsLoading ? (
                  <p className="px-5 py-8 text-center text-text-muted text-sm">Loading…</p>
                ) : leadsError ? (
                  <p className="px-5 py-8 text-center text-bad text-sm">{leadsError}</p>
                ) : (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs uppercase tracking-wide text-text-muted border-y border-border">
                        <th className="px-5 py-2.5 font-medium">Lead ID</th>
                        <th className="px-5 py-2.5 font-medium">To Number</th>
                        {variableKeys.map((key) => (
                          <th key={key} className="px-5 py-2.5 font-medium">{key}</th>
                        ))}
                        <th className="px-5 py-2.5 font-medium">Status</th>
                        <th className="px-5 py-2.5 font-medium">Current Node</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {leads.map((l) => (
                        <tr key={l.id} className="hover:bg-surface-container">
                          <td className="px-5 py-2.5 font-medium text-on-surface">{l.lead_id}</td>
                          <td className="px-5 py-2.5 text-on-surface">
                            {typeof l.variables?.to_number === "string" || typeof l.variables?.to_number === "number"
                              ? String(l.variables.to_number)
                              : "—"}
                          </td>
                          {variableKeys.map((key) => (
                            <td key={key} className="px-5 py-2.5 text-text-muted">
                              {l.variables?.[key] !== undefined && l.variables?.[key] !== null
                                ? String(l.variables[key])
                                : "—"}
                            </td>
                          ))}
                          <td className="px-5 py-2.5"><ExecutionStatusPill status={l.status} /></td>
                          <td className="px-5 py-2.5 text-text-muted">{l.current_node || "—"}</td>
                        </tr>
                      ))}
                      {leads.length === 0 && (
                        <tr>
                          <td colSpan={4 + variableKeys.length} className="px-5 py-8 text-center text-text-muted">
                            No leads found for this campaign.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                )}
              </div>
            </Card>
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
