"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getDepartment } from "@/lib/telehubApi";
import type { DepartmentDetail, DepartmentNestedProcessAgent } from "@/lib/types";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";

// Process Agent `status` values (draft/active/…) aren't part of the shared
// lead-status vocabulary in lib/domainConfig.ts, so StatusBadge can't color
// them meaningfully (it'd fall back to grey for both). Mirrors the local
// status-styling pattern already used in app/intelligence/page.tsx for the
// same reason — a component-local vocab that doesn't belong in domainConfig.
type Tone = "ok" | "warn" | "bad" | "muted";

const TONE_CLASSES: Record<Tone, string> = {
  ok: "bg-ok/10 text-ok border border-ok/20",
  warn: "bg-warn/10 text-warn border border-warn/20",
  bad: "bg-bad/10 text-bad border border-bad/20",
  muted: "bg-surface-container text-text-muted border border-border",
};

function processStatusTone(status: string): Tone {
  const s = status.toLowerCase();
  if (s === "active" || s === "published" || s === "live") return "ok";
  if (s === "draft") return "warn";
  if (s === "archived" || s === "disabled" || s === "paused") return "bad";
  return "muted";
}

function ProcessStatusPill({ status }: { status: string }) {
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium capitalize ${TONE_CLASSES[processStatusTone(status)]}`}>
      {status}
    </span>
  );
}

function ActiveDot({ active }: { active: boolean }) {
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${active ? "bg-ok" : "bg-bad"}`}
      title={active ? "Active" : "Inactive"}
    />
  );
}

function SkeletonCard() {
  return (
    <div className="bg-white border border-gray-100 rounded-xl p-5 animate-pulse">
      <div className="h-4 bg-gray-200 rounded w-2/3 mb-3" />
      <div className="h-3 bg-gray-100 rounded w-1/4 mb-4" />
      <div className="h-3 bg-gray-100 rounded w-1/3" />
    </div>
  );
}

export default function DepartmentDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;

  const [department, setDepartment] = useState<DepartmentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    const numericId = Number(id);
    if (Number.isNaN(numericId)) {
      setError("Invalid department id");
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    getDepartment(numericId)
      .then((data) => {
        if (cancelled) return;
        setDepartment(data);
        setLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Failed to load department");
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [id]);

  // Loading state
  if (loading) {
    return (
      <div className="space-y-6">
        <div className="animate-pulse space-y-2">
          <div className="h-3 bg-gray-100 rounded w-24" />
          <div className="h-6 bg-gray-200 rounded w-64" />
          <div className="h-3 bg-gray-100 rounded w-96" />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      </div>
    );
  }

  // Error state (e.g. department not found)
  if (error || !department) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center">
        <p className="text-sm font-semibold text-gray-800 mb-1">Department not found</p>
        <p className="text-xs text-text-muted mb-4 max-w-sm">
          This department may have been deleted, or the link you followed is incorrect.
          {error ? ` (${error})` : ""}
        </p>
        <Link href="/departments" className="text-primary text-sm font-medium hover:underline">
          ← Back to Departments
        </Link>
      </div>
    );
  }

  const processAgents: DepartmentNestedProcessAgent[] = department.process_agents ?? [];

  return (
    <div className="space-y-6">
      {/* Back link */}
      <Link href="/departments" className="text-xs text-text-muted hover:text-primary transition-colors">
        ← Back to Departments
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-lg font-semibold text-gray-800">{department.name}</h1>
            <StatusBadge status={department.is_active ? "active" : "inactive"} />
          </div>
          {department.description && (
            <p className="text-sm text-text-muted mt-1 max-w-2xl">{department.description}</p>
          )}
        </div>
        <Link
          href={`/process-agents/new?department=${department.id}`}
          className="shrink-0 flex items-center gap-1.5 px-4 py-2 rounded-lg bg-primary text-on-primary text-sm font-medium hover:bg-primary-container transition-colors"
        >
          <span className="text-base leading-none">+</span>
          Add Process
        </Link>
      </div>

      {/* Empty state */}
      {processAgents.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-center border border-dashed border-border rounded-xl">
          <p className="text-gray-600 text-sm font-medium mb-1">This department has no processes yet</p>
          <p className="text-xs text-text-muted mb-4 max-w-md">
            e.g. &ldquo;Free Service 1&rdquo;, &ldquo;Test Drive&rdquo;, &ldquo;Insurance Renewal&rdquo;
          </p>
          <Link
            href={`/process-agents/new?department=${department.id}`}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-primary text-on-primary text-sm font-medium hover:bg-primary-container transition-colors"
          >
            <span className="text-base leading-none">+</span>
            Add Process
          </Link>
        </div>
      )}

      {/* Process Agent grid */}
      {processAgents.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {processAgents.map((pa) => (
            <Link key={pa.id} href={`/process-agents/${pa.id}`}>
              <Card className="p-5 hover:shadow-md hover:border-gray-200 transition-all cursor-pointer h-full">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <p className="text-sm font-semibold text-gray-800 truncate">{pa.name}</p>
                  <ActiveDot active={pa.is_active} />
                </div>
                <div className="flex items-center gap-2">
                  <ProcessStatusPill status={pa.status} />
                  <span className="text-xs text-text-muted">v{pa.version}</span>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
