"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSidebar } from "@/context/SidebarContext";
import {
  LayoutDashboard,
  Bot,
  Network,
  Users,
  PanelLeftClose,
  PanelLeftOpen,
  ChevronRight,
} from "lucide-react";

// Settings is left out until app/settings/page.tsx is wired to the API —
// today it is a static mock-up whose buttons do nothing.
const NAV_ITEMS = [
  { href: "/",         label: "Dashboard", Icon: LayoutDashboard },
  { href: "/bots",     label: "Voicebots", Icon: Bot },
  { href: "/channels", label: "Channels",  Icon: Network },
  { href: "/leads",    label: "Leads",     Icon: Users },
];

export function Sidebar() {
  const pathname = usePathname();
  const { isOpen, toggle } = useSidebar();

  return (
    <aside
      className={`fixed top-0 left-0 h-full bg-sidebar-bg border-r border-sidebar-border text-sidebar-text-muted flex flex-col z-20 transition-all duration-300 ${
        isOpen ? "w-56" : "w-16"
      }`}
    >
      {/* Logo + toggle */}
      <div className="h-16 flex items-center justify-between px-4 border-b border-sidebar-border shrink-0">
        {isOpen && (
          <Image
            src="/Logo.png"
            alt="Chat360"
            width={120}
            height={32}
            className="h-8 w-auto"
            priority
          />
        )}
        <button
          onClick={toggle}
          aria-label={isOpen ? "Collapse sidebar" : "Expand sidebar"}
          className={`p-1.5 rounded-lg hover:bg-sidebar-active text-sidebar-text-muted hover:text-sidebar-text transition-colors ${
            isOpen ? "" : "mx-auto"
          }`}
        >
          {isOpen ? <PanelLeftClose className="w-5 h-5" /> : <PanelLeftOpen className="w-5 h-5" />}
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-hidden">
        {NAV_ITEMS.map(({ href, label, Icon }) => {
          const active = href === "/" ? pathname === href : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              title={!isOpen ? label : undefined}
              className={`flex items-center gap-3 px-3 py-2.5 text-sm transition-colors rounded-lg ${
                isOpen ? "" : "justify-center px-2"
              } ${
                active
                  ? "bg-primary text-on-primary font-semibold shadow-sm"
                  : "text-sidebar-text-muted hover:bg-sidebar-active hover:text-sidebar-text"
              }`}
            >
              <Icon className="w-5 h-5 shrink-0" />
              {isOpen && <span className="truncate">{label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Footer card */}
      {isOpen && (
        <Link
          href="/bots"
          className="m-3 p-4 rounded-xl border border-sidebar-border bg-surface hover:bg-sidebar-active transition-colors group"
        >
          <div className="flex items-start gap-3">
            <WaveMark className="w-8 h-8 shrink-0 text-primary" />
            <div className="min-w-0">
              <p className="text-sm font-semibold text-sidebar-text">Build. Automate. Scale.</p>
              <p className="text-xs text-sidebar-text-muted mt-1 leading-relaxed">
                Your AI voice agents, working 24/7.
              </p>
            </div>
          </div>
          <div className="flex justify-end mt-1">
            <ChevronRight className="w-4 h-4 text-sidebar-text-muted group-hover:text-sidebar-text transition-colors" />
          </div>
        </Link>
      )}
    </aside>
  );
}

// Small audio-waveform mark inside a soft circle — drawn inline, no asset.
function WaveMark({ className = "" }: { className?: string }) {
  const bars = [6, 12, 18, 10, 16, 8];
  return (
    <span className={`rounded-full bg-sidebar-active flex items-center justify-center ${className}`}>
      <svg viewBox="0 0 24 24" className="w-5 h-5" aria-hidden="true">
        {bars.map((h, i) => (
          <rect key={i} x={2.5 + i * 3.4} y={12 - h / 2} width={1.8} height={h} rx={0.9} fill="currentColor" />
        ))}
      </svg>
    </span>
  );
}
