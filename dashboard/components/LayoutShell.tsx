"use client";

import { SidebarProvider, useSidebar } from "@/context/SidebarContext";
import { Sidebar } from "./Sidebar";
import { TopHeader } from "./TopHeader";

function Shell({ children }: { children: React.ReactNode }) {
  const { isOpen } = useSidebar();
  return (
    <>
      <Sidebar />
      <TopHeader />
      <main
        className={`mt-16 p-6 min-h-[calc(100vh-4rem)] transition-all duration-300 ${
          isOpen ? "ml-56" : "ml-16"
        }`}
      >
        {children}
      </main>
    </>
  );
}

export function LayoutShell({ children }: { children: React.ReactNode }) {
  return (
    <SidebarProvider>
      <Shell>{children}</Shell>
    </SidebarProvider>
  );
}
