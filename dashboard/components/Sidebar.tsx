"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSidebar } from "@/context/SidebarContext";
import {
  LayoutDashboard,
  Bot,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";

// Settings is left out until app/settings/page.tsx is wired to the API —
// today it is a static mock-up whose buttons do nothing.
const NAV_ITEMS = [
  { href: "/",         label: "Dashboard", Icon: LayoutDashboard },
  { href: "/bots",     label: "Voicebots", Icon: Bot },
  { href: "/channels", label: "Channels",  Icon: Network },
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
    </aside>
  );
}
