import type { Metadata } from "next";
import { Work_Sans } from "next/font/google";
import "./globals.css";
import { LayoutShell } from "@/components/LayoutShell";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";

const workSans = Work_Sans({
  subsets: ["latin"],
  variable: "--font-work-sans",
});

export const metadata: Metadata = {
  title: "Chat360",
  description: "Conversational AI.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={workSans.className}>
        <TooltipProvider>
          <LayoutShell>{children}</LayoutShell>
        </TooltipProvider>
        <Toaster position="top-right" richColors />
      </body>
    </html>
  );
}
