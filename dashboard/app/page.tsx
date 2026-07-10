"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Card, CardHeader } from "@/components/Card";
import { listDepartments } from "@/lib/telehubApi";
import type { Department } from "@/lib/types";

interface KpiTile {
  label: string;
}

const KPI_TILES: KpiTile[] = [
  { label: "Calls" },
  { label: "Bookings" },
  { label: "Revenue" },
  { label: "Drop-offs" },
  { label: "Hot Leads" },
  { label: "Conversion" },
  { label: "Callback Due" },
  { label: "Bot Success" },
];

export default function DashboardPage() {
  const [departments, setDepartments] = useState<Department[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listDepartments()
      .then((data) => {
        setDepartments(data);
        setSelectedId(data.length > 0 ? data[0].id : null);
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : "Failed to load departments");
        setLoading(false);
      });
  }, []);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-lg font-semibold text-on-surface">Dashboard</h1>
        <p className="text-xs text-text-muted mt-0.5">Department-level overview</p>
      </div>

      {/* Error banner */}
      {error && (
        <div className="text-sm text-bad bg-bad/10 border border-bad/30 rounded-lg px-4 py-2">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && <p className="text-sm text-text-muted">Loading…</p>}

      {/* Empty state — no departments yet */}
      {!loading && !error && departments.length === 0 && (
        <Card className="p-10 flex flex-col items-center justify-center text-center">
          <p className="text-sm text-text-muted mb-3">
            No departments yet. Create one to start building process agents.
          </p>
          <Link
            href="/departments"
            className="px-4 py-2 rounded-lg bg-primary text-on-primary text-sm font-medium hover:bg-primary-container transition-colors"
          >
            + Add Department
          </Link>
        </Card>
      )}

      {/* Main content — only once departments exist */}
      {!loading && !error && departments.length > 0 && (
        <>
          {/* Department selector */}
          <div className="flex items-center gap-2 overflow-x-auto pb-1">
            {departments.map((d) => (
              <button
                key={d.id}
                onClick={() => setSelectedId(d.id)}
                className={`shrink-0 px-4 py-2 rounded-full text-sm font-medium transition-colors border ${
                  selectedId === d.id
                    ? "bg-primary text-on-primary border-primary"
                    : "bg-surface text-on-surface border-border hover:bg-surface-container"
                }`}
              >
                {d.icon ? `${d.icon} ` : ""}
                {d.name}
              </button>
            ))}
          </div>

          {/* KPI row */}
          <div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              {KPI_TILES.map((tile) => (
                <Card key={tile.label} className="p-5">
                  <p className="text-xs font-medium text-text-muted uppercase tracking-wide">
                    {tile.label}
                  </p>
                  <p className="text-3xl font-bold text-on-surface mt-1">—</p>
                </Card>
              ))}
            </div>
            <p className="text-xs text-text-muted mt-2">
              Live metrics appear once your processes start running.
            </p>
          </div>

          {/* AI Recommendations placeholder */}
          <Card className="p-0 overflow-hidden">
            <CardHeader title="AI Recommendations" />
            <div className="px-5 pb-5">
              <p className="text-sm text-text-muted">
                Recommendations will appear here once departments have active processes.
              </p>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
