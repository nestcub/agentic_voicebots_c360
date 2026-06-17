"use client";

import { Suspense, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { RiMicLine, RiHammerLine, RiArrowLeftLine } from "react-icons/ri";

// Lazy-load the heavy tab contents via dynamic import to avoid bundle bloat
import dynamic from "next/dynamic";

const TranscribePage = dynamic(
  () => import("../transcribe/page"),
  { loading: () => <TabSkeleton />, ssr: false }
);
const BuildPage = dynamic(
  () => import("../build/page"),
  { loading: () => <TabSkeleton />, ssr: false }
);

function TabSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-6 bg-gray-100 rounded w-1/3" />
      <div className="h-40 bg-gray-100 rounded" />
    </div>
  );
}

const TABS = [
  { key: "transcribe", label: "Transcribe", Icon: RiMicLine },
  { key: "build",      label: "Build",      Icon: RiHammerLine },
] as const;

type TabKey = typeof TABS[number]["key"];

function BotPageInner() {
  const router = useRouter();
  const params = useSearchParams();
  const clientId = params.get("client_id") ?? "";
  const initialTab = params.get("tab") as TabKey | null;
  const [tab, setTab] = useState<TabKey>(
    initialTab && TABS.some(t => t.key === initialTab) ? initialTab : "transcribe"
  );

  // Sync client_id into localStorage so existing Transcribe/Build pages pick it up
  // (both pages read from localStorage("intel_client_id") / IntelligenceContext)
  if (clientId && typeof window !== "undefined") {
    localStorage.setItem("intel_client_id", clientId);
  }

  if (!clientId) {
    return (
      <div className="text-sm text-gray-400 py-20 text-center">
        No bot selected. <button onClick={() => router.push("/intelligence")} className="text-blue-600 hover:underline">Go to Bots</button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Back + tab bar */}
      <div className="flex items-center gap-4">
        <button
          onClick={() => router.push("/intelligence")}
          className="flex items-center gap-1 text-sm text-gray-400 hover:text-gray-700 transition-colors"
        >
          <RiArrowLeftLine className="w-4 h-4" />
          Bots
        </button>
        <p className="text-xs text-gray-300 font-mono truncate max-w-xs">{clientId}</p>
      </div>

      <div className="flex gap-1 border-b border-gray-200">
        {TABS.map(({ key, label, Icon }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px ${
              tab === key
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      {/* Tab content — pass client_id via URL so existing pages work unchanged */}
      <div>
        {tab === "transcribe" && (
          <Suspense fallback={<TabSkeleton />}>
            <TranscribePage />
          </Suspense>
        )}
        {tab === "build" && (
          <Suspense fallback={<TabSkeleton />}>
            <BuildPage />
          </Suspense>
        )}
      </div>
    </div>
  );
}

export default function BotPage() {
  return (
    <Suspense>
      <BotPageInner />
    </Suspense>
  );
}
