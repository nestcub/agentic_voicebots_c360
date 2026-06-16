"use client";

import Link from "next/link";
import { Card, CardHeader } from "@/components/Card";
import { RiMicLine, RiHammerLine, RiBookOpenLine } from "react-icons/ri";
import { useIntelligence } from "@/context/IntelligenceContext";

const SECTIONS = [
  { href: "/intelligence/transcribe", label: "Transcribe", Icon: RiMicLine,      desc: "Upload call recordings and extract insights" },
  { href: "/intelligence/build",      label: "Build",      Icon: RiHammerLine,   desc: "Conversational workflow designer and plan manager" },
  { href: "/intelligence/knowledge",  label: "Knowledge",  Icon: RiBookOpenLine, desc: "Manage platform knowledge facts" },
];

export default function IntelligencePage() {
  const { clientId, setClientId, plans, transcripts } = useIntelligence();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-gray-800">Intelligence</h1>
        <p className="text-xs text-gray-400 mt-0.5">Call analysis, workflow design, and platform knowledge</p>
      </div>

      {/* Client ID */}
      <Card className="p-5">
        <label className="text-sm font-medium text-gray-700">Client ID</label>
        <input
          type="text"
          value={clientId}
          onChange={(e) => setClientId(e.target.value)}
          placeholder="e.g. autovista"
          className="mt-2 w-full max-w-sm px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <p className="text-xs text-gray-400 mt-1">Saved in browser. All sections below filter by this ID.</p>
      </Card>

      {/* Quick nav */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {SECTIONS.map(({ href, label, Icon, desc }) => (
          <Link key={href} href={href}>
            <Card className="p-5 hover:shadow-md transition-shadow cursor-pointer h-full">
              <Icon className="w-6 h-6 text-blue-600 mb-3" />
              <p className="text-sm font-semibold text-gray-800">{label}</p>
              <p className="text-xs text-gray-400 mt-1">{desc}</p>
            </Card>
          </Link>
        ))}
      </div>

      {/* Recent activity */}
      <div className="grid md:grid-cols-2 gap-6">
        <Card className="p-0 overflow-hidden">
          <CardHeader title="Recent Transcripts" hint={clientId ? `for ${clientId}` : "set a client ID above"} />
          <div className="divide-y divide-gray-100">
            {transcripts.length === 0 && (
              <p className="px-5 py-6 text-sm text-gray-400">No transcripts yet.</p>
            )}
            {transcripts.map((t) => (
              <Link key={t.id} href={`/intelligence/transcribe?id=${t.id}`} className="flex items-center justify-between px-5 py-3 hover:bg-gray-50">
                <div>
                  <p className="text-sm font-medium text-gray-800 truncate max-w-[200px]">{t.filename}</p>
                  <p className="text-xs text-gray-400">{t.duration ? `${Math.round(t.duration)}s` : "—"} · {t.created_at?.slice(0, 10)}</p>
                </div>
              </Link>
            ))}
          </div>
        </Card>

        <Card className="p-0 overflow-hidden">
          <CardHeader title="Recent Plans" hint={clientId ? `for ${clientId}` : "set a client ID above"} />
          <div className="divide-y divide-gray-100">
            {plans.length === 0 && (
              <p className="px-5 py-6 text-sm text-gray-400">No plans yet.</p>
            )}
            {plans.map((p) => (
              <Link key={p.id} href="/intelligence/build" className="flex items-center justify-between px-5 py-3 hover:bg-gray-50">
                <div>
                  <p className="text-sm font-medium text-gray-800">v{p.version} plan</p>
                  <p className="text-xs text-gray-400">{p.updated_at?.slice(0, 10) ?? p.created_at?.slice(0, 10)}</p>
                </div>
              </Link>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
