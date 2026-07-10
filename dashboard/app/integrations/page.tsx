"use client";

import { useEffect, useState } from "react";
import { Card, CardHeader } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { listIntegrations, createIntegration, updateIntegration, deleteIntegration } from "@/lib/telehubApi";
import type { Integration } from "@/lib/types";

const INTEGRATION_TYPES: { value: string; label: string }[] = [
  { value: "crm", label: "CRM" },
  { value: "webhook", label: "Webhook" },
  { value: "rest_api", label: "REST API" },
  { value: "voice_provider", label: "Voice Provider" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "email", label: "Email" },
  { value: "google_sheets", label: "Google Sheets" },
  { value: "meta_leads", label: "Meta Leads" },
];

function typeLabel(value: string): string {
  return INTEGRATION_TYPES.find((t) => t.value === value)?.label ?? value;
}

interface FormState {
  name: string;
  type: string;
  notes: string;
}

const EMPTY_FORM: FormState = { name: "", type: INTEGRATION_TYPES[0].value, notes: "" };

export default function IntegrationsPage() {
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [busyId, setBusyId] = useState<number | null>(null);

  async function fetchIntegrations() {
    setLoading(true);
    setError(null);
    try {
      const data = await listIntegrations();
      setIntegrations(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load integrations.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchIntegrations();
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) {
      setFormError("Name is required.");
      return;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      await createIntegration({
        name: form.name.trim(),
        type: form.type,
        configuration: { notes: form.notes },
      });
      setForm(EMPTY_FORM);
      setShowForm(false);
      await fetchIntegrations();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to create integration.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleToggleStatus(integration: Integration) {
    const nextStatus = integration.status === "active" ? "inactive" : "active";
    setBusyId(integration.id);
    setError(null);
    try {
      await updateIntegration(integration.id, { status: nextStatus });
      await fetchIntegrations();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update integration.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(integration: Integration) {
    setBusyId(integration.id);
    setError(null);
    try {
      await deleteIntegration(integration.id);
      await fetchIntegrations();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete integration.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-on-surface">Integrations</h1>
        <button
          onClick={() => {
            setFormError(null);
            setShowForm((v) => !v);
          }}
          className="px-4 py-2 rounded-lg text-sm font-medium bg-primary text-on-primary hover:bg-primary-container transition-colors"
        >
          {showForm ? "Cancel" : "+ Add Integration"}
        </button>
      </div>

      {error && (
        <Card className="p-4 border-bad/40 bg-bad/5">
          <p className="text-sm text-bad font-medium">{error}</p>
          <button onClick={fetchIntegrations} className="text-xs text-bad underline mt-1">
            Retry
          </button>
        </Card>
      )}

      {showForm && (
        <Card className="p-5">
          <CardHeader title="Add Integration" hint="Basic connection details — per-type configuration comes later." />
          <form onSubmit={handleCreate} className="px-5 pb-5 space-y-4">
            <div>
              <label className="block text-xs font-medium text-text-muted mb-1">Name</label>
              <input
                type="text"
                required
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="e.g. Salesforce CRM"
                className="w-full px-3 py-2 rounded-lg border border-border bg-surface text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/40"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-text-muted mb-1">Type</label>
              <select
                value={form.type}
                onChange={(e) => setForm((f) => ({ ...f, type: e.target.value }))}
                className="w-full px-3 py-2 rounded-lg border border-border bg-surface text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/40"
              >
                {INTEGRATION_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-text-muted mb-1">Configuration notes</label>
              <textarea
                value={form.notes}
                onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
                placeholder="Free-text notes — API keys, endpoints, field mappings…"
                rows={3}
                className="w-full px-3 py-2 rounded-lg border border-border bg-surface text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/40"
              />
            </div>
            {formError && <p className="text-sm text-bad">{formError}</p>}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setShowForm(false);
                  setForm(EMPTY_FORM);
                  setFormError(null);
                }}
                className="px-4 py-2 rounded-lg text-sm font-medium text-text-muted hover:bg-surface-container transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="px-4 py-2 rounded-lg text-sm font-medium bg-primary text-on-primary hover:bg-primary-container transition-colors disabled:opacity-50"
              >
                {submitting ? "Saving…" : "Save Integration"}
              </button>
            </div>
          </form>
        </Card>
      )}

      {loading && (
        <Card className="p-8 text-center">
          <p className="text-sm text-text-muted">Loading integrations…</p>
        </Card>
      )}

      {!loading && !error && integrations.length === 0 && (
        <Card className="p-8 text-center">
          <p className="text-sm text-text-muted">No integrations configured yet. Add one to get started.</p>
        </Card>
      )}

      {!loading && integrations.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {integrations.map((integration) => (
            <Card key={integration.id} className="p-5 flex flex-col gap-3">
              <div className="flex items-start justify-between gap-2">
                <p className="font-semibold text-on-surface">{integration.name}</p>
                <StatusBadge status={integration.status} />
              </div>
              <span className="inline-block w-fit px-2 py-0.5 rounded-full text-xs font-medium bg-surface-container text-text-muted border border-border">
                {typeLabel(integration.type)}
              </span>
              <div className="flex items-center gap-3 mt-auto pt-2 border-t border-border">
                <button
                  onClick={() => handleToggleStatus(integration)}
                  disabled={busyId === integration.id}
                  className="text-xs font-medium text-primary hover:underline disabled:opacity-50"
                >
                  {integration.status === "active" ? "Set Inactive" : "Set Active"}
                </button>
                <button
                  onClick={() => handleDelete(integration)}
                  disabled={busyId === integration.id}
                  className="text-xs font-medium text-bad hover:underline disabled:opacity-50"
                >
                  Delete
                </button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
