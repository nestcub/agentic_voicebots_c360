"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { listDepartments, createDepartment } from "@/lib/telehubApi";
import type { Department } from "@/lib/types";

const COLOR_SWATCHES = [
  "#3366f0", // primary
  "#2fb6a8", // accent
  "#1ca674", // ok
  "#f0883e", // warn
  "#e2574c", // bad
  "#0f1b2e", // sidebar-bg
];

interface NewDepartmentForm {
  name: string;
  description: string;
  icon: string;
  color: string;
}

const EMPTY_FORM: NewDepartmentForm = {
  name: "",
  description: "",
  icon: "",
  color: COLOR_SWATCHES[0],
};

export default function DepartmentsPage() {
  const [departments, setDepartments] = useState<Department[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<NewDepartmentForm>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  function loadDepartments() {
    setLoading(true);
    setError(null);
    return listDepartments()
      .then((data) => {
        setDepartments(data);
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : "Failed to load departments");
        setLoading(false);
      });
  }

  useEffect(() => {
    loadDepartments();
  }, []);

  function openForm() {
    setForm(EMPTY_FORM);
    setFormError(null);
    setFormOpen(true);
  }

  function closeForm() {
    setFormOpen(false);
    setFormError(null);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) {
      setFormError("Name is required.");
      return;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      await createDepartment({
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        icon: form.icon.trim() || undefined,
        color: form.color || undefined,
      });
      await loadDepartments();
      setFormOpen(false);
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Failed to create department");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-on-surface">Departments</h1>
          <p className="text-xs text-text-muted mt-0.5">Organize process agents by department</p>
        </div>
        <button
          onClick={openForm}
          className="px-4 py-2 rounded-lg bg-primary text-on-primary text-sm font-medium hover:bg-primary-container transition-colors"
        >
          + Add Department
        </button>
      </div>

      {/* Inline add-department form */}
      {formOpen && (
        <Card className="p-5">
          <form onSubmit={handleSubmit} className="space-y-4">
            <p className="text-sm font-semibold text-on-surface">New Department</p>

            {formError && (
              <div className="text-sm text-bad bg-bad/10 border border-bad/30 rounded-lg px-4 py-2">
                {formError}
              </div>
            )}

            <div className="grid sm:grid-cols-2 gap-4">
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-text-muted">Name *</span>
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  className="px-3 py-2 rounded-lg border border-border bg-surface text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary"
                  placeholder="e.g. Sales"
                  required
                />
              </label>

              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-text-muted">Icon</span>
                <input
                  type="text"
                  value={form.icon}
                  onChange={(e) => setForm((f) => ({ ...f, icon: e.target.value }))}
                  className="px-3 py-2 rounded-lg border border-border bg-surface text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary"
                  placeholder="e.g. 🏢"
                />
              </label>
            </div>

            <label className="flex flex-col gap-1">
              <span className="text-xs font-medium text-text-muted">Description</span>
              <textarea
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                className="px-3 py-2 rounded-lg border border-border bg-surface text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary"
                rows={2}
                placeholder="Short description of this department"
              />
            </label>

            <div className="flex flex-col gap-1">
              <span className="text-xs font-medium text-text-muted">Color</span>
              <div className="flex items-center gap-2">
                {COLOR_SWATCHES.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setForm((f) => ({ ...f, color: c }))}
                    className={`w-7 h-7 rounded-full border-2 transition-transform ${
                      form.color === c ? "border-on-surface scale-110" : "border-border"
                    }`}
                    style={{ backgroundColor: c }}
                    aria-label={`Use color ${c}`}
                  />
                ))}
                <input
                  type="color"
                  value={form.color}
                  onChange={(e) => setForm((f) => ({ ...f, color: e.target.value }))}
                  className="w-8 h-8 rounded border border-border bg-surface cursor-pointer"
                />
              </div>
            </div>

            <div className="flex items-center gap-2 pt-1">
              <button
                type="submit"
                disabled={submitting}
                className="px-4 py-2 rounded-lg bg-primary text-on-primary text-sm font-medium hover:bg-primary-container disabled:opacity-60 transition-colors"
              >
                {submitting ? "Creating…" : "Create Department"}
              </button>
              <button
                type="button"
                onClick={closeForm}
                disabled={submitting}
                className="px-4 py-2 rounded-lg border border-border text-on-surface text-sm font-medium hover:bg-surface-container disabled:opacity-60 transition-colors"
              >
                Cancel
              </button>
            </div>
          </form>
        </Card>
      )}

      {/* Error banner */}
      {error && (
        <div className="text-sm text-bad bg-bad/10 border border-bad/30 rounded-lg px-4 py-2">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && <p className="text-sm text-text-muted">Loading…</p>}

      {/* Empty state */}
      {!loading && !error && departments.length === 0 && (
        <Card className="p-10 flex flex-col items-center justify-center text-center">
          <p className="text-sm text-text-muted mb-3">
            No departments yet. Create your first department to start building process agents.
          </p>
          <button
            onClick={openForm}
            className="px-4 py-2 rounded-lg bg-primary text-on-primary text-sm font-medium hover:bg-primary-container transition-colors"
          >
            + Add Department
          </button>
        </Card>
      )}

      {/* Department grid */}
      {!loading && !error && departments.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {departments.map((d) => (
            <Link key={d.id} href={`/departments/${d.id}`}>
              <Card className="p-5 h-full hover:shadow-md hover:border-primary/40 transition-all cursor-pointer">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <span
                      className="w-9 h-9 rounded-lg flex items-center justify-center text-lg shrink-0"
                      style={{ backgroundColor: `${d.color || "#3366f0"}22` }}
                    >
                      {d.icon || "🗂️"}
                    </span>
                    <p className="text-sm font-semibold text-on-surface truncate">{d.name}</p>
                  </div>
                  <StatusBadge status={d.is_active ? "active" : "inactive"} />
                </div>
                <p className="text-xs text-text-muted line-clamp-2 min-h-[2rem]">
                  {d.description || "No description."}
                </p>
                <p className="text-xs text-text-muted mt-3">
                  {d.process_agent_count} process agent{d.process_agent_count === 1 ? "" : "s"}
                </p>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
