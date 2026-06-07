"use client";

// ALL / region / branch switcher — no auth, just a client-side scope change driving every fetch.

import { useAccount } from "@/context/AccountContext";
import { domainConfig } from "@/lib/domainConfig";
import type { Scope } from "@/lib/types";

export function ScopeSwitcher() {
  const { scope, setScope, regions } = useAccount();

  const region = scope.level === "region" ? scope.region : scope.level === "branch" ? scope.region : "";
  const branches = region ? domainConfig.branchesByRegion[region] ?? [] : [];

  function onRegion(value: string) {
    if (!value) setScope({ level: "all" });
    else setScope({ level: "region", region: value });
  }
  function onBranch(value: string) {
    if (!value) setScope({ level: "region", region } as Scope);
    else setScope({ level: "branch", region, branch: value });
  }

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-slate-500">Scope</span>
      <select
        value={region}
        onChange={(e) => onRegion(e.target.value)}
        className="text-sm rounded-lg border border-slate-200 bg-white px-2 py-1"
      >
        <option value="">All Regions</option>
        {regions.map((r) => (
          <option key={r} value={r}>{r}</option>
        ))}
      </select>
      <select
        value={scope.level === "branch" ? scope.branch : ""}
        onChange={(e) => onBranch(e.target.value)}
        disabled={!region}
        className="text-sm rounded-lg border border-slate-200 bg-white px-2 py-1 disabled:opacity-40"
      >
        <option value="">All Branches</option>
        {branches.map((b) => (
          <option key={b} value={b}>{b}</option>
        ))}
      </select>
    </div>
  );
}
