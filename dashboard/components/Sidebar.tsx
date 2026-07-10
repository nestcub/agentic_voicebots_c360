"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { domainConfig } from "@/lib/domainConfig";
import { useSidebar } from "@/context/SidebarContext";
import {
  RiHome5Line,
  RiUserLine,
  RiBuildingLine,
  RiBrainLine,
  RiPlugLine,
  RiSettings4Line,
  RiMenuFoldLine,
  RiMenuUnfoldLine,
  RiBookOpenLine,
  RiRobotLine,
  RiArrowDownSLine,
  RiArrowUpSLine,
} from "react-icons/ri";

const NAV_BEFORE_INTELLIGENCE = [
  { href: "/",            label: "Dashboard",    Icon: RiHome5Line },
  { href: "/departments", label: "Departments",  Icon: RiBuildingLine },
  { href: "/leads",       label: "Leads",         Icon: RiUserLine },
];

const NAV_AFTER_INTELLIGENCE = [
  { href: "/integrations", label: "Integrations", Icon: RiPlugLine },
  { href: "/settings",     label: "Settings",     Icon: RiSettings4Line },
];

const INTELLIGENCE_SUB = [
  { href: "/intelligence",           label: "Bots",      Icon: RiRobotLine,    exact: true },
  { href: "/intelligence/knowledge", label: "Knowledge", Icon: RiBookOpenLine, exact: false },
];

export function Sidebar() {
  const pathname = usePathname();
  const { isOpen, toggle } = useSidebar();

  const intelligenceActive = pathname.startsWith("/intelligence");
  const [intelligenceOpen, setIntelligenceOpen] = useState(intelligenceActive);

  // Auto-open when navigating into /intelligence
  useEffect(() => {
    if (intelligenceActive) {
      setIntelligenceOpen(true);
    }
  }, [intelligenceActive]);

  return (
    <aside
      className={`fixed top-0 left-0 h-full bg-sidebar-bg border-r border-sidebar-border text-sidebar-text-muted flex flex-col z-20 transition-all duration-300 ${
        isOpen ? "w-56" : "w-16"
      }`}
    >
      {/* Logo + toggle */}
      <div className="h-16 flex items-center justify-between px-4 border-b border-sidebar-border shrink-0">
        {isOpen && (
          <span className="font-bold text-lg tracking-tight text-sidebar-text whitespace-nowrap">
            Chat<span className="text-primary">360</span>
          </span>
        )}
        <button
          onClick={toggle}
          className={`p-1.5 rounded-lg hover:bg-sidebar-active text-sidebar-text-muted hover:text-sidebar-text transition-colors ${
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
        {/* Items before Intelligence */}
        {NAV_BEFORE_INTELLIGENCE.map(({ href, label, Icon }) => {
          const active = href === "/" ? pathname === href : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              title={!isOpen ? label : undefined}
              className={`flex items-center gap-3 px-3 py-2.5 text-sm transition-colors relative ${
                isOpen ? "" : "justify-center px-2"
              } ${
                active
                  ? "bg-primary text-on-primary rounded-lg font-semibold"
                  : "text-sidebar-text-muted hover:bg-sidebar-active hover:text-sidebar-text rounded-lg"
              }`}
            >
              <Icon className="w-5 h-5 shrink-0" />
              {isOpen && <span className="truncate">{label}</span>}
            </Link>
          );
        })}

        {/* Intelligence expandable group */}
        <div>
          <button
            onClick={() => setIntelligenceOpen((prev) => !prev)}
            title={!isOpen ? "Intelligence" : undefined}
            className={`w-full flex items-center gap-3 px-3 py-2.5 text-sm transition-colors relative ${
              isOpen ? "" : "justify-center px-2"
            } ${
              intelligenceActive
                ? "bg-primary text-on-primary rounded-lg font-semibold"
                : "text-sidebar-text-muted hover:bg-sidebar-active hover:text-sidebar-text rounded-lg"
            }`}
          >
            <RiBrainLine className="w-5 h-5 shrink-0" />
            {isOpen && (
              <>
                <span className="truncate flex-1 text-left">Intelligence</span>
                {intelligenceOpen ? (
                  <RiArrowUpSLine className="w-4 h-4 shrink-0" />
                ) : (
                  <RiArrowDownSLine className="w-4 h-4 shrink-0" />
                )}
              </>
            )}
          </button>

          {/* Sub-items — only when sidebar is open and group is open */}
          {isOpen && intelligenceOpen && (
            <div className="mt-0.5 space-y-0.5">
              {INTELLIGENCE_SUB.map(({ href, label, Icon, exact }) => {
                const active = exact ? pathname === href : pathname.startsWith(href);
                return (
                  <Link
                    key={href}
                    href={href}
                    className={`flex items-center gap-3 pl-9 pr-3 py-2 text-sm transition-colors rounded-lg ${
                      active
                        ? "bg-primary/15 text-sidebar-text font-medium"
                        : "text-sidebar-text-muted hover:bg-sidebar-active"
                    }`}
                  >
                    <Icon className="w-4 h-4 shrink-0" />
                    <span className="truncate">{label}</span>
                  </Link>
                );
              })}
            </div>
          )}
        </div>

        {/* Items after Intelligence */}
        {NAV_AFTER_INTELLIGENCE.map(({ href, label, Icon }) => {
          const active = pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              title={!isOpen ? label : undefined}
              className={`flex items-center gap-3 px-3 py-2.5 text-sm transition-colors relative ${
                isOpen ? "" : "justify-center px-2"
              } ${
                active
                  ? "bg-primary text-on-primary rounded-lg font-semibold"
                  : "text-sidebar-text-muted hover:bg-sidebar-active hover:text-sidebar-text rounded-lg"
              }`}
            >
              <Icon className="w-5 h-5 shrink-0" />
              {isOpen && <span className="truncate">{label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      {isOpen && (
        <div className="px-5 py-4 text-xs text-sidebar-text-muted border-t border-sidebar-border whitespace-nowrap">
          AI Tele-calling Hub · live
        </div>
      )}
    </aside>
  );
}
