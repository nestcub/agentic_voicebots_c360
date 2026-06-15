"use client";

import { useRef, useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  RiFileExcel2Line,
  RiDatabase2Line,
  RiCloudLine,
  RiLoaderLine,
  RiServerLine,
} from "react-icons/ri";
import { Card } from "@/components/Card";
import type { UploadResult, Lead } from "@/lib/types";

// TODO: AccountContext only exposes scope, not an account id. Default to "autovista"
// until the real account id is wired through context/auth.
const ACCOUNT_ID = "autovista";

const ORCH = process.env.NEXT_PUBLIC_ORCH_API_URL || "http://localhost:8000";

// Mirrors the orchestrator's CRM connection row (orchestrator/crm/connections).
interface CrmConnection {
  id: string;
  account_id: string;
  name: string;
  crm_type: string;
  base_url: string;
  api_key: string;
  status: string;
  last_tested_at: string | null;
  created_at: string;
  updated_at: string;
}

const CRM_TYPES = ["rest", "hubspot", "zoho", "leadsquared"] as const;

function StatusBadge({ label, variant }: { label: string; variant: "emerald" | "slate" }) {
  const cls =
    variant === "emerald"
      ? "bg-emerald-100 text-emerald-700"
      : "bg-slate-100 text-slate-500";
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${cls}`}>
      {label}
    </span>
  );
}

// Maps a CRM connection status to a colored pill.
function CrmStatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    ok: "bg-emerald-100 text-emerald-700",
    error: "bg-rose-100 text-rose-700",
    configured: "bg-slate-100 text-slate-500",
  };
  const cls = map[status] ?? "bg-slate-100 text-slate-500";
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${cls}`}>
      {status}
    </span>
  );
}

export default function IntegrationsPage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [creatingCampaign, setCreatingCampaign] = useState(false);

  // ── CRM connection state ──────────────────────────────────────────────────
  const [connections, setConnections] = useState<CrmConnection[]>([]);
  const [crmLoading, setCrmLoading] = useState(false);
  const [crmError, setCrmError] = useState<string | null>(null);
  const [crmForm, setCrmForm] = useState({
    name: "",
    crm_type: "rest",
    base_url: "",
    api_key: "",
  });
  const [savingCrm, setSavingCrm] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testNotes, setTestNotes] = useState<Record<string, string>>({});

  async function loadConnections() {
    setCrmLoading(true);
    setCrmError(null);
    try {
      const res = await fetch(
        `${ORCH}/orchestrator/crm/connections?account_id=${encodeURIComponent(ACCOUNT_ID)}`,
      );
      if (!res.ok) throw new Error(`Failed to load connections (${res.status})`);
      const data: CrmConnection[] = await res.json();
      setConnections(data);
    } catch (err) {
      setCrmError(err instanceof Error ? err.message : "Unknown error loading connections");
    } finally {
      setCrmLoading(false);
    }
  }

  useEffect(() => {
    loadConnections();
  }, []);

  async function handleSaveConnection(e: React.FormEvent) {
    e.preventDefault();
    setSavingCrm(true);
    setSaveError(null);
    try {
      const res = await fetch(`${ORCH}/orchestrator/crm/connections`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_id: ACCOUNT_ID, ...crmForm }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `Save failed (${res.status})`);
      }
      setCrmForm({ name: "", crm_type: "rest", base_url: "", api_key: "" });
      await loadConnections();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Unknown error saving connection");
    } finally {
      setSavingCrm(false);
    }
  }

  async function handleTestConnection(id: string) {
    setTestingId(id);
    setTestNotes((prev) => ({ ...prev, [id]: "" }));
    try {
      const res = await fetch(`${ORCH}/orchestrator/crm/connections/${id}/test`, {
        method: "POST",
      });
      const data: { ok: boolean; status_code: number; message: string } = await res.json();
      setTestNotes((prev) => ({
        ...prev,
        [id]: `${data.ok ? "OK" : "Failed"} (${data.status_code}) — ${data.message}`,
      }));
      // The test endpoint updates the row's status server-side; refresh to reflect it.
      await loadConnections();
    } catch (err) {
      setTestNotes((prev) => ({
        ...prev,
        [id]: err instanceof Error ? err.message : "Test request failed",
      }));
    } finally {
      setTestingId(null);
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0] ?? null;
    setSelectedFile(file);
    setUploadResult(null);
    setUploadError(null);
    if (file) {
      doUpload(file);
    }
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0] ?? null;
    if (file) {
      setSelectedFile(file);
      setUploadResult(null);
      setUploadError(null);
      doUpload(file);
    }
  }

  function handleDragOver(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
  }

  async function doUpload(file: File) {
    setUploading(true);
    setUploadError(null);
    setUploadResult(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch("/api/campaigns/upload", { method: "POST", body: fd });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `Upload failed (${res.status})`);
      }
      const data: UploadResult = await res.json();
      setUploadResult(data);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Unknown upload error");
    } finally {
      setUploading(false);
    }
  }

  async function handleCreateCampaign() {
    if (!uploadResult) return;
    setCreatingCampaign(true);
    try {
      await fetch("/api/orchestrator/recommendations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          campaign_id: uploadResult.campaign_id,
          campaign_name: uploadResult.campaign_name,
          total_leads: uploadResult.total_leads,
        }),
      });
      router.push("/orchestrator");
    } catch {
      setCreatingCampaign(false);
    }
  }

  function handleCancel() {
    setSelectedFile(null);
    setUploadResult(null);
    setUploadError(null);
    setUploading(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function formatBytes(bytes: number) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Integrations</h1>
        <p className="text-sm text-slate-500 mt-1">
          Connect your CRM to sync campaigns and leads automatically
        </p>
      </div>

      {/* Connector Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">

        {/* Card 1 — xlsx Upload (active) */}
        <Card className="p-5 flex flex-col gap-4">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <RiFileExcel2Line className="text-emerald-600 text-2xl shrink-0" />
              <div>
                <p className="text-sm font-semibold text-slate-800">Campaign Spreadsheet</p>
                <p className="text-xs text-slate-500 mt-0.5">
                  Upload an .xlsx or .csv file to import campaign leads
                </p>
              </div>
            </div>
            <StatusBadge label="Ready" variant="emerald" />
          </div>

          {/* File upload zone */}
          <div
            className="border-2 border-dashed border-slate-200 rounded-lg p-6 text-center cursor-pointer hover:border-blue-400 hover:bg-blue-50 transition-colors"
            onClick={() => fileInputRef.current?.click()}
            onDrop={handleDrop}
            onDragOver={handleDragOver}
          >
            {selectedFile ? (
              <div className="space-y-1">
                <p className="text-sm font-medium text-slate-700">{selectedFile.name}</p>
                <p className="text-xs text-slate-400">{formatBytes(selectedFile.size)}</p>
              </div>
            ) : (
              <>
                <p className="text-sm text-slate-500">Drop .xlsx or .csv here</p>
                <p className="text-xs text-slate-400 mt-1">or click to browse</p>
              </>
            )}
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx,.csv"
            className="hidden"
            onChange={handleFileChange}
          />

          {/* Template link */}
          <a
            href="/sample-campaign.csv"
            download
            className="text-xs text-blue-600 hover:underline self-start"
          >
            Download sample template
          </a>
        </Card>

        {/* Card 2 — LMS (coming soon) */}
        <Card className="p-5 flex flex-col gap-4 opacity-60">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <RiDatabase2Line className="text-slate-400 text-2xl shrink-0" />
              <div>
                <p className="text-sm font-semibold text-slate-800">LMS CRM</p>
                <p className="text-xs text-slate-500 mt-0.5">
                  Connect your LMS MySQL database via REST API
                </p>
              </div>
            </div>
            <StatusBadge label="Coming Soon" variant="slate" />
          </div>
        </Card>

        {/* Card 3 — Zoho (coming soon) */}
        <Card className="p-5 flex flex-col gap-4 opacity-60">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <RiCloudLine className="text-slate-400 text-2xl shrink-0" />
              <div>
                <p className="text-sm font-semibold text-slate-800">Zoho CRM</p>
                <p className="text-xs text-slate-500 mt-0.5">
                  OAuth integration with Zoho campaigns and leads
                </p>
              </div>
            </div>
            <StatusBadge label="Coming Soon" variant="slate" />
          </div>
        </Card>
      </div>

      {/* Upload flow — shown only when a file is selected */}
      {selectedFile && (
        <div className="space-y-4">
          {/* Uploading state */}
          {uploading && (
            <Card className="p-5 flex items-center gap-3">
              <RiLoaderLine className="animate-spin text-blue-600 text-xl shrink-0" />
              <span className="text-sm text-slate-600">Uploading...</span>
            </Card>
          )}

          {/* Upload error */}
          {uploadError && !uploading && (
            <div className="bg-rose-50 border border-rose-200 rounded-lg p-3 text-sm text-rose-700">
              {uploadError}
            </div>
          )}

          {/* Upload success — preview */}
          {uploadResult && !uploading && (
            <Card className="p-0 overflow-hidden">
              <div className="px-5 pt-4 pb-2 flex items-baseline gap-3">
                <p className="text-base font-semibold text-gray-800">
                  Preview — {uploadResult.campaign_name}
                </p>
                <span className="text-sm text-slate-500">
                  {uploadResult.total_leads} leads detected
                </span>
              </div>

              {/* Errors warning */}
              {uploadResult.errors.length > 0 && (
                <div className="mx-5 mb-3 bg-amber-50 border border-amber-200 rounded-lg p-3">
                  <ul className="list-disc list-inside space-y-0.5">
                    {uploadResult.errors.map((err: string, i: number) => (
                      <li key={i} className="text-xs text-amber-700">{err}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Preview table */}
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-wide text-slate-500 border-y border-slate-100">
                      <th className="px-5 py-2.5 font-medium">Name</th>
                      <th className="px-5 py-2.5 font-medium">Phone</th>
                      <th className="px-5 py-2.5 font-medium">Region</th>
                      <th className="px-5 py-2.5 font-medium">Branch</th>
                      <th className="px-5 py-2.5 font-medium">Lead Type</th>
                      <th className="px-5 py-2.5 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {uploadResult.preview_leads.slice(0, 5).map((lead: Lead) => (
                      <tr key={lead.id} className="hover:bg-slate-50">
                        <td className="px-5 py-2.5 text-slate-700">{lead.name}</td>
                        <td className="px-5 py-2.5 text-slate-600">{lead.phone}</td>
                        <td className="px-5 py-2.5 text-slate-600">{lead.region || "—"}</td>
                        <td className="px-5 py-2.5 text-slate-600">{lead.branch || "—"}</td>
                        <td className="px-5 py-2.5 text-slate-600">{lead.source || "—"}</td>
                        <td className="px-5 py-2.5 text-slate-600">{lead.status}</td>
                      </tr>
                    ))}
                    {uploadResult.preview_leads.length === 0 && (
                      <tr>
                        <td colSpan={6} className="px-5 py-8 text-center text-slate-400">
                          No preview leads available.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              {/* Action buttons */}
              <div className="px-5 py-4 flex items-center gap-3 border-t border-slate-100">
                <button
                  onClick={handleCreateCampaign}
                  disabled={creatingCampaign}
                  className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-2"
                >
                  {creatingCampaign && (
                    <RiLoaderLine className="animate-spin text-base" />
                  )}
                  Create Campaign &amp; Send to Orchestrator
                </button>
                <button
                  onClick={handleCancel}
                  disabled={creatingCampaign}
                  className="border border-slate-300 text-slate-700 px-4 py-2 rounded-lg text-sm hover:bg-slate-50 disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  Cancel
                </button>
              </div>
            </Card>
          )}
        </div>
      )}

      {/* ── Connect a CRM ──────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Connect form */}
        <Card className="p-5 flex flex-col gap-4">
          <div className="flex items-center gap-3">
            <RiServerLine className="text-blue-600 text-2xl shrink-0" />
            <div>
              <p className="text-sm font-semibold text-slate-800">Connect a CRM</p>
              <p className="text-xs text-slate-500 mt-0.5">
                Register an external CRM connection for this account
              </p>
            </div>
          </div>

          <form onSubmit={handleSaveConnection} className="flex flex-col gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Name</label>
              <input
                type="text"
                required
                value={crmForm.name}
                onChange={(e) => setCrmForm({ ...crmForm, name: e.target.value })}
                placeholder="e.g. Production HubSpot"
                className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">CRM Type</label>
              <select
                value={crmForm.crm_type}
                onChange={(e) => setCrmForm({ ...crmForm, crm_type: e.target.value })}
                className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-400"
              >
                {CRM_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Base URL</label>
              <input
                type="url"
                required
                value={crmForm.base_url}
                onChange={(e) => setCrmForm({ ...crmForm, base_url: e.target.value })}
                placeholder="https://api.example.com"
                className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">API Key</label>
              <input
                type="password"
                required
                value={crmForm.api_key}
                onChange={(e) => setCrmForm({ ...crmForm, api_key: e.target.value })}
                placeholder="••••••••"
                className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
            </div>

            {saveError && (
              <div className="bg-rose-50 border border-rose-200 rounded-lg p-2.5 text-xs text-rose-700">
                {saveError}
              </div>
            )}

            <button
              type="submit"
              disabled={savingCrm}
              className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2 self-start"
            >
              {savingCrm && <RiLoaderLine className="animate-spin text-base" />}
              Save connection
            </button>
          </form>
        </Card>

        {/* Connected CRMs list */}
        <Card className="p-5 flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold text-slate-800">Connected CRMs</p>
            {crmLoading && <RiLoaderLine className="animate-spin text-blue-600 text-lg" />}
          </div>

          {crmError && (
            <div className="bg-rose-50 border border-rose-200 rounded-lg p-2.5 text-xs text-rose-700">
              {crmError}
            </div>
          )}

          {!crmLoading && !crmError && connections.length === 0 && (
            <p className="text-sm text-slate-400">No CRM connections yet.</p>
          )}

          <div className="divide-y divide-slate-100">
            {connections.map((conn) => (
              <div key={conn.id} className="py-3 first:pt-0 flex flex-col gap-1.5">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-slate-800 truncate">{conn.name}</p>
                      <CrmStatusBadge status={conn.status} />
                    </div>
                    <p className="text-xs text-slate-500 mt-0.5">
                      {conn.crm_type} · {conn.base_url}
                    </p>
                  </div>
                  <button
                    onClick={() => handleTestConnection(conn.id)}
                    disabled={testingId === conn.id}
                    className="border border-slate-300 text-slate-700 px-3 py-1.5 rounded-lg text-xs hover:bg-slate-50 disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-1.5 shrink-0"
                  >
                    {testingId === conn.id && <RiLoaderLine className="animate-spin text-sm" />}
                    Test
                  </button>
                </div>
                {testNotes[conn.id] && (
                  <p className="text-xs text-slate-500">{testNotes[conn.id]}</p>
                )}
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
