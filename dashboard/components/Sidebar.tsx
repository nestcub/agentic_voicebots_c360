"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { domainConfig } from "@/lib/domainConfig";

const NAV = [
  { href: "/", label: "Dashboard", icon: "▣" },
  { href: "/leads", label: "Leads", icon: "☰" },
  { href: "/follow-ups", label: "Follow-ups", icon: "↻" },
  { href: "/analytics", label: "Analytics", icon: "▤" },
  { href: "/goal-target", label: "Goal & Target", icon: "◎" },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="fixed top-0 left-0 w-60 h-full bg-primary text-white flex flex-col">
      <div className="h-16 flex items-center px-6 border-b border-white/10">
        <span className="font-bold text-lg tracking-tight">{domainConfig.brand}</span>
      </div>
      <nav className="flex-1 px-3 py-4 space-y-1">
        {NAV.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                active ? "bg-white/15 font-semibold" : "text-white/70 hover:bg-white/10"
              }`}
            >
              <span className="w-4 text-center">{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="px-6 py-4 text-xs text-white/40 border-t border-white/10">
        AI Orchestrator · live
      </div>
    </aside>
  );
}
