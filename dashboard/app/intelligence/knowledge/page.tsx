"use client";

import { useEffect, useState } from "react";
import { Card, CardHeader } from "@/components/Card";
import { RiCheckLine, RiArchiveLine, RiDeleteBin6Line, RiAddLine } from "react-icons/ri";

type KnowledgeRow = { id: string; topic: string; fact: string; source: string | null; status: string; created_at: string };

export default function KnowledgePage() {
  const [tab, setTab] = useState<"active" | "pending">("active");
  const [rows, setRows] = useState<KnowledgeRow[]>([]);
  const [topic, setTopic] = useState("");
  const [fact, setFact] = useState("");
  const [source, setSource] = useState("");
  const [adding, setAdding] = useState(false);

  useEffect(() => { load(tab); }, [tab]);

  function load(status: string) {
    fetch(`/api/intelligence/knowledge?status=${status}`)
      .then((r) => r.json()).then((d) => setRows(Array.isArray(d) ? d : [])).catch(() => {});
  }

  async function action(id: string, type: "approve" | "archive" | "delete") {
    if (type === "delete") {
      await fetch(`/api/intelligence/knowledge/${id}`, { method: "DELETE" });
    } else {
      await fetch(`/api/intelligence/knowledge/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: type === "approve" ? "active" : "archived" }),
      });
    }
    load(tab);
  }

  async function addFact() {
    if (!topic.trim() || !fact.trim()) return;
    setAdding(true);
    await fetch("/api/intelligence/knowledge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic: topic.trim(), fact: fact.trim(), source: source.trim() || null, status: "active" }),
    });
    setTopic(""); setFact(""); setSource("");
    setAdding(false);
    load(tab);
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-gray-800">Platform Knowledge</h1>
        <p className="text-xs text-gray-400 mt-0.5">Facts the workflow designer uses when generating plans</p>
      </div>

      {/* Add form */}
      <Card className="p-5 space-y-4">
        <CardHeader title="Add knowledge" hint="topic + fact" />
        <div className="grid md:grid-cols-3 gap-3">
          <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="Topic (e.g. Greeting)" className="px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
          <input value={fact} onChange={(e) => setFact(e.target.value)} placeholder="Fact" className="px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
          <input value={source} onChange={(e) => setSource(e.target.value)} placeholder="Source (optional)" className="px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <button onClick={addFact} disabled={adding || !topic.trim() || !fact.trim()} className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 transition-colors">
          <RiAddLine className="w-4 h-4" /> Add
        </button>
      </Card>

      {/* Tabs + table */}
      <Card className="p-0 overflow-hidden">
        <div className="flex border-b border-gray-100">
          {(["active", "pending"] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)} className={`px-5 py-3 text-sm font-medium capitalize transition-colors ${tab === t ? "text-blue-600 border-b-2 border-blue-600" : "text-gray-500 hover:text-gray-700"}`}>{t}</button>
          ))}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                {["Topic", "Fact", "Source", "Added", "Actions"].map((h) => (
                  <th key={h} className="text-left px-5 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.length === 0 && (
                <tr><td colSpan={5} className="px-5 py-8 text-center text-gray-400">No {tab} knowledge facts.</td></tr>
              )}
              {rows.map((r) => (
                <tr key={r.id} className="hover:bg-gray-50">
                  <td className="px-5 py-3 font-medium text-gray-800 max-w-[140px] truncate">{r.topic}</td>
                  <td className="px-5 py-3 text-gray-600 max-w-[280px]">{r.fact}</td>
                  <td className="px-5 py-3 text-gray-400 text-xs">{r.source ?? "—"}</td>
                  <td className="px-5 py-3 text-gray-400 text-xs whitespace-nowrap">{r.created_at?.slice(0, 10)}</td>
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-2">
                      {tab === "pending" && (
                        <button onClick={() => action(r.id, "approve")} title="Approve" className="p-1.5 rounded hover:bg-emerald-100 text-emerald-600 transition-colors"><RiCheckLine className="w-4 h-4" /></button>
                      )}
                      <button onClick={() => action(r.id, "archive")} title="Archive" className="p-1.5 rounded hover:bg-amber-100 text-amber-500 transition-colors"><RiArchiveLine className="w-4 h-4" /></button>
                      <button onClick={() => action(r.id, "delete")} title="Delete" className="p-1.5 rounded hover:bg-red-100 text-red-500 transition-colors"><RiDeleteBin6Line className="w-4 h-4" /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
