"use client";

import { IntelligenceProvider } from "@/context/IntelligenceContext";

export default function IntelligenceLayout({ children }: { children: React.ReactNode }) {
  return <IntelligenceProvider>{children}</IntelligenceProvider>;
}
