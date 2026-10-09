"use client";

import { useEffect, useState } from "react";
import { Calendar } from "lucide-react";
import { domainConfig } from "@/lib/domainConfig";
import { useSidebar } from "@/context/SidebarContext";

export function TopHeader() {
  const { isOpen } = useSidebar();

  // Formatted client-side only, so the server-rendered markup never disagrees
  // with the browser's date/locale.
  const [today, setToday] = useState<string | null>(null);
  useEffect(() => {
    setToday(new Date().toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }));
  }, []);

  return (
    <header
      className={`fixed top-0 right-0 h-16 bg-surface border-b border-border flex items-center justify-between px-6 z-10 transition-all duration-300 ${
        isOpen ? "left-56" : "left-16"
      }`}
    >
      {/* Greeting */}
      <div className="min-w-0">
        <p className="text-base font-semibold text-on-surface truncate">Hello, {domainConfig.brand}</p>
        <p className="text-xs text-text-muted truncate">
          Here&apos;s what&apos;s happening with your agentic voicebots today.
        </p>
      </div>

      {/* Right side */}
      {today && (
        <div className="hidden sm:flex items-center gap-2 text-sm text-on-surface shrink-0">
          <Calendar className="w-4 h-4 text-text-muted" />
          <span>{today}</span>
        </div>
      )}
    </header>
  );
}
