"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { domainConfig } from "@/lib/domainConfig";
import { useSidebar } from "@/context/SidebarContext";
import {
  RiHome5Line,
  RiUserLine,
  RiBuildingLine,
  RiPlugLine,
  RiSettings4Line,
  RiMenuFoldLine,
  RiMenuUnfoldLine,
  RiRobotLine,
} from "react-icons/ri";

const NAV_ITEMS = [
  { href: "/",        label: "Dashboard", Icon: RiHome5Line },
  { href: "/channels", label: "Channels",   Icon: RiBuildingLine },
  { href: "/leads",    label: "Leads",     Icon: RiUserLine },
  { href: "/bots",     label: "Bots",      Icon: RiRobotLine },
];

const NAV_SECONDARY = [
  { href: "/integrations", label: "Integrations", Icon: RiPlugLine },
  { href: "/settings",     label: "Settings",     Icon: RiSettings4Line },
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
        {/* Primary nav */}
        {NAV_ITEMS.map(({ href, label, Icon }) => {
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

        {/* Secondary nav (hidden for now) */}
        {/* {NAV_SECONDARY.map(({ href, label, Icon }) => {
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
        })} */}
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
