import type { Metadata } from "next";
import "./globals.css";
import { AccountProvider } from "@/context/AccountContext";
import { Sidebar } from "@/components/Sidebar";
import { TopHeader } from "@/components/TopHeader";

export const metadata: Metadata = {
  title: "Autovista AI Orchestrator",
  description: "Outbound lead operations — dispatch, follow-up reliability, live analytics.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AccountProvider>
          <Sidebar />
          <TopHeader />
          <main className="ml-60 mt-16 p-6 min-h-[calc(100vh-4rem)]">{children}</main>
        </AccountProvider>
      </body>
    </html>
  );
}
