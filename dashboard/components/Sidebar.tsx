"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { domainConfig } from "@/lib/domainConfig";
import { useSidebar } from "@/context/SidebarContext";
import {
  RiHome5Line,
  RiUserLine,
  RiRefreshLine,
  RiBarChart2Line,
  RiRocketLine,
  RiPlugLine,
  RiCrosshair2Line,
  RiMenuFoldLine,
  RiMenuUnfoldLine,
} from "react-icons/ri";

const NAV = [
  { href: "/",            label: "Dashboard",    Icon: RiHome5Line },
  { href: "/leads",       label: "Leads",         Icon: RiUserLine },
  { href: "/follow-ups",  label: "Follow-ups",    Icon: RiRefreshLine },
  { href: "/analytics",            label: "Analytics",    Icon: RiBarChart2Line },
  { href: "/orchestrator",         label: "Orchestrator", Icon: RiRocketLine },
  { href: "/settings/integrations", label: "Integrations", Icon: RiPlugLine },
  { href: "/goal-target",          label: "Goal & Target", Icon: RiCrosshair2Line },
];

export function Sidebar() {
  const pathname = usePathname();
  const { isOpen, toggle } = useSidebar();

  return (
    <aside
      className={`fixed top-0 left-0 h-full bg-[#1a2535] text-white flex flex-col z-20 transition-all duration-300 ${
        isOpen ? "w-56" : "w-16"
      }`}
    >
      {/* Logo + toggle */}
      <div className="h-16 flex items-center justify-between px-4 border-b border-white/10 shrink-0">
        {isOpen && (
          <span className="font-bold text-lg tracking-tight text-white whitespace-nowrap">
            Chat<span className="text-blue-400">360</span>
          </span>
        )}
        <button
          onClick={toggle}
          className={`p-1.5 rounded-lg hover:bg-white/10 text-white/60 hover:text-white transition-colors ${
            isOpen ? "" : "mx-auto"
          }`}
        >
          {isOpen ? (
            <RiMenuFoldLine className="w-5 h-5" />
          ) : (
            <RiMenuUnfoldLine className="w-5 h-5" />
          )}
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-2 py-4 space-y-0.5 overflow-hidden">
        {NAV.map(({ href, label, Icon }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              title={!isOpen ? label : undefined}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors relative ${
                isOpen ? "" : "justify-center px-2"
              } ${
                active
                  ? "bg-white text-gray-800 font-semibold"
                  : "text-white/60 hover:bg-white/10 hover:text-white"
              }`}
            >
              <Icon
                className={`w-5 h-5 shrink-0 ${active ? "text-blue-600" : ""}`}
              />
              {isOpen && <span className="truncate">{label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      {isOpen && (
        <div className="px-5 py-4 text-xs text-white/30 border-t border-white/10 whitespace-nowrap">
          AI Orchestrator · live
        </div>
      )}
    </aside>
  );
}
