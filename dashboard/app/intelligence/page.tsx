"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const INTEL_URL = process.env.NEXT_PUBLIC_INTEL_API_URL ?? "http://localhost:8001";
const INTEL_KEY = process.env.NEXT_PUBLIC_INTEL_API_KEY ?? "";

const apiHeaders = () => ({ "x-api-key": INTEL_KEY });

interface Bot {
  client_id: string;
  status: "draft" | "transcribed" | "built";
  bot_name: string;
  updated_at: string;
}

function relativeDate(iso: string): string {
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const secs = Math.floor(diff / 1000);
    if (secs < 60) return "just now";
    const mins = Math.floor(secs / 60);
    if (mins < 60) return `${mins} minute${mins === 1 ? "" : "s"} ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs} hour${hrs === 1 ? "" : "s"} ago`;
    const days = Math.floor(hrs / 24);
    if (days < 30) return `${days} day${days === 1 ? "" : "s"} ago`;
    return new Date(iso).toLocaleDateString();
  } catch {
    return iso;
  }
}

const STATUS_CHIP: Record<string, string> = {
  draft: "bg-gray-100 text-gray-600",
  transcribed: "bg-amber-100 text-amber-700",
  built: "bg-green-100 text-green-700",
};

function SkeletonCard() {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 animate-pulse">
      <div className="h-4 bg-gray-200 rounded w-2/3 mb-3" />
      <div className="h-3 bg-gray-100 rounded w-1/4 mb-4" />
      <div className="h-3 bg-gray-100 rounded w-1/3" />
    </div>
  );
}

export default function IntelligencePage() {
  const router = useRouter();
  const [bots, setBots] = useState<Bot[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${INTEL_URL}/bots`, { headers: apiHeaders() })
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json();
      })
      .then((data) => {
        setBots(data.bots ?? []);
        setLoading(false);
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
  }, []);

  async function handleCreate() {
    setCreating(true);
    try {
      const res = await fetch(`${INTEL_URL}/bots`, {
        method: "POST",
        headers: { ...apiHeaders(), "Content-Type": "application/json" },
      });
      if (!res.ok) throw new Error(`${res.status}`);
      const data = await res.json();
      router.push(`/intelligence/wizard?client_id=${data.client_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create bot");
      setCreating(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-gray-800">Bots</h1>
          <p className="text-xs text-gray-400 mt-0.5">All your intelligence bots</p>
        </div>
        <button
          onClick={handleCreate}
          disabled={creating}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-60 transition-colors"
        >
          {creating ? (
            <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
          ) : (
            <span className="text-base leading-none">+</span>
          )}
          Create new bot
        </button>
      </div>

      {/* Error banner */}
      {error && (
        <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-2">
          {error}
        </div>
      )}

      {/* Loading skeletons */}
      {loading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => <SkeletonCard key={i} />)}
        </div>
      )}

      {/* Empty state */}
      {!loading && bots.length === 0 && !error && (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <p className="text-gray-400 text-sm mb-3">No bots yet. Create your first bot</p>
          <button
            onClick={handleCreate}
            disabled={creating}
            className="text-blue-600 text-sm font-medium hover:underline disabled:opacity-60"
          >
            Create your first bot →
          </button>
        </div>
      )}

      {/* Bot grid */}
      {!loading && bots.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {bots.map((bot) => (
            <button
              key={bot.client_id}
              onClick={() => router.push(`/intelligence/bot?client_id=${bot.client_id}`)}
              className="text-left bg-white border border-gray-200 rounded-xl p-5 hover:shadow-md hover:border-gray-300 transition-all cursor-pointer"
            >
              <div className="flex items-start justify-between gap-2 mb-2">
                <p className="text-sm font-semibold text-gray-800 truncate">{bot.bot_name || bot.client_id}</p>
                <span
                  className={`shrink-0 text-xs font-medium px-2 py-0.5 rounded-full ${STATUS_CHIP[bot.status] ?? "bg-gray-100 text-gray-600"}`}
                >
                  {bot.status}
                </span>
              </div>
              <p className="text-xs text-gray-400">{bot.updated_at ? relativeDate(bot.updated_at) : "—"}</p>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
