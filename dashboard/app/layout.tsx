import type { Metadata } from "next";
import { Work_Sans } from "next/font/google";
import "./globals.css";
import { AccountProvider } from "@/context/AccountContext";
import { LayoutShell } from "@/components/LayoutShell";

const workSans = Work_Sans({
  subsets: ["latin"],
  variable: "--font-work-sans",
});

export const metadata: Metadata = {
  title: "Autovista AI Orchestrator",
  description: "Outbound lead operations — dispatch, follow-up reliability, live analytics.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={workSans.className}>
        <AccountProvider>
          <LayoutShell>{children}</LayoutShell>
        </AccountProvider>
      </body>
    </html>
  );
}
