import type { Metadata } from "next";
import "./globals.css";
import { AccountProvider } from "@/context/AccountContext";
import { LayoutShell } from "@/components/LayoutShell";

export const metadata: Metadata = {
  title: "Autovista AI Orchestrator",
  description: "Outbound lead operations — dispatch, follow-up reliability, live analytics.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AccountProvider>
          <LayoutShell>{children}</LayoutShell>
        </AccountProvider>
      </body>
    </html>
  );
}
