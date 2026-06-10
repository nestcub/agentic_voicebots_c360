"use client";

import { domainConfig } from "@/lib/domainConfig";
import { ScopeSwitcher } from "./ScopeSwitcher";
import { RiSettings3Line } from "react-icons/ri";
import { useSidebar } from "@/context/SidebarContext";

export function TopHeader() {
  const { isOpen } = useSidebar();
  const initial = domainConfig.brand?.[0]?.toUpperCase() ?? "A";

  return (
    <header
      className={`fixed top-0 right-0 h-16 bg-white border-b border-gray-200 flex items-center justify-between px-6 z-10 transition-all duration-300 ${
        isOpen ? "left-56" : "left-16"
      }`}
    >
      {/* Greeting */}
      <p className="text-base font-semibold text-gray-800">
        Hello, {domainConfig.brand}
      </p>

      {/* Right side */}
      <div className="flex items-center gap-4">
        <ScopeSwitcher />
        <button className="p-2 rounded-lg hover:bg-gray-100 text-gray-500 transition-colors">
          <RiSettings3Line className="w-5 h-5" />
        </button>
        <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-white text-sm font-semibold">
          {initial}
        </div>
      </div>
    </header>
  );
}
