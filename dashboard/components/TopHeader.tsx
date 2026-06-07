"use client";

import { domainConfig } from "@/lib/domainConfig";
import { ScopeSwitcher } from "./ScopeSwitcher";

export function TopHeader() {
  return (
    <header className="fixed top-0 left-60 right-0 h-16 bg-white border-b border-slate-200 flex items-center justify-between px-6 z-10">
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold text-slate-800">{domainConfig.brand}</span>
        <span className="text-xs text-slate-400">/ {domainConfig.product}</span>
      </div>
      <ScopeSwitcher />
    </header>
  );
}
