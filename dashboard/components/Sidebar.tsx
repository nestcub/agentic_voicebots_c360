"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { domainConfig } from "@/lib/domainConfig";
import {
  RiHome5Line,
  RiUserLine,
  RiRefreshLine,
  RiBarChart2Line,
  RiCrosshair2Line,
} from "react-icons/ri";

const NAV = [
  { href: "/",            label: "Dashboard",    Icon: RiHome5Line },
  { href: "/leads",       label: "Leads",         Icon: RiUserLine },
  { href: "/follow-ups",  label: "Follow-ups",    Icon: RiRefreshLine },
  { href: "/analytics",   label: "Analytics",     Icon: RiBarChart2Line },
  { href: "/goal-target", label: "Goal & Target", Icon: RiCrosshair2Line },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="fixed top-0 left-0 w-56 h-full bg-sidebar-bg text-white flex flex-col z-20">
      {/* Logo */}
      <div className="h-16 flex items-center px-5 border-b border-white/10">
        <span className="font-bold text-lg tracking-tight text-white">
          Chat<span className="text-blue-400">360</span>
        </span>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {NAV.map(({ href, label, Icon }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors relative ${
                active
                  ? "bg-sidebar-active text-white font-medium"
                  : "text-white/60 hover:bg-white/5 hover:text-white"
              }`}
            >
              {active && (
                <span className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-6 bg-blue-400 rounded-r" />
              )}
              <Icon className="w-5 h-5 shrink-0" />
              <span>{label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 text-xs text-white/30 border-t border-white/10">
        AI Orchestrator · live
      </div>
    </aside>
  );
}
