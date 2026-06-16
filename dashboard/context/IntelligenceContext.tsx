"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useRef,
  useCallback,
  type ReactNode,
} from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PlanRow {
  id: string;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface PlanDetail extends PlanRow {
  plan: Record<string, unknown>;
  client_id: string;
}

export interface StoredTranscript {
  id: string;
  filename: string;
  duration: number;
  created_at: string;
}

export interface KnowledgeFact {
  id: string;
  topic: string;
  fact: string;
  source: string;
  status: string;
  created_at: string;
}

interface IntelligenceContextValue {
  clientId: string;
  setClientId: (id: string) => void;

  // Plans
  plans: PlanRow[];
  latestPlan: PlanDetail | null;
  plansLoading: boolean;
  refreshPlans: () => void;

  // Transcripts
  transcripts: StoredTranscript[];
  transcriptsLoading: boolean;
  refreshTranscripts: () => void;

  // Knowledge
  knowledgeFacts: KnowledgeFact[];
  knowledgeLoading: boolean;
  refreshKnowledge: () => void;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const IntelligenceContext = createContext<IntelligenceContextValue | null>(null);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function IntelligenceProvider({ children }: { children: ReactNode }) {
  const [clientId, _setClientId] = useState<string>("");

  // Read localStorage after mount — avoids SSR/client hydration mismatch
  useEffect(() => {
    const stored = localStorage.getItem("intel_client_id") ?? "";
    if (stored) _setClientId(stored);
  }, []);

  // Plans
  const [plans, setPlans] = useState<PlanRow[]>([]);
  const [latestPlan, setLatestPlan] = useState<PlanDetail | null>(null);
  const [plansLoading, setPlansLoading] = useState(false);

  // Transcripts
  const [transcripts, setTranscripts] = useState<StoredTranscript[]>([]);
  const [transcriptsLoading, setTranscriptsLoading] = useState(false);

  // Knowledge
  const [knowledgeFacts, setKnowledgeFacts] = useState<KnowledgeFact[]>([]);
  const [knowledgeLoading, setKnowledgeLoading] = useState(false);

  // Track which clientId has already been fetched to avoid double-fetching
  const fetchedForRef = useRef<string | null>(null);

  // ---------------------------------------------------------------------------
  // setClientId — persists to localStorage
  // ---------------------------------------------------------------------------

  const setClientId = useCallback((id: string) => {
    if (typeof window !== "undefined") {
      localStorage.setItem("intel_client_id", id);
    }
    _setClientId(id);
  }, []);

  // ---------------------------------------------------------------------------
  // Fetch helpers
  // ---------------------------------------------------------------------------

  const fetchPlans = useCallback(async (id: string) => {
    if (!id) return;
    setPlansLoading(true);
    try {
      const res = await fetch(`/api/intelligence/plans?client_id=${encodeURIComponent(id)}`);
      if (!res.ok) throw new Error("plans fetch failed");
      const rows: PlanRow[] = await res.json();
      setPlans(rows);

      if (rows.length > 0) {
        const detailRes = await fetch(`/api/intelligence/plans/${encodeURIComponent(rows[0].id)}`);
        if (!detailRes.ok) throw new Error("plan detail fetch failed");
        const detail: PlanDetail = await detailRes.json();
        setLatestPlan(detail);
      } else {
        setLatestPlan(null);
      }
    } catch {
      // Silent — pages must not crash on network failure
    } finally {
      setPlansLoading(false);
    }
  }, []);

  const fetchTranscripts = useCallback(async (id: string) => {
    if (!id) return;
    setTranscriptsLoading(true);
    try {
      const res = await fetch(
        `/api/intelligence/transcripts?client_id=${encodeURIComponent(id)}`
      );
      if (!res.ok) throw new Error("transcripts fetch failed");
      const rows: StoredTranscript[] = await res.json();
      setTranscripts(rows);
    } catch {
      // Silent
    } finally {
      setTranscriptsLoading(false);
    }
  }, []);

  const fetchKnowledge = useCallback(async () => {
    setKnowledgeLoading(true);
    try {
      const [activeRes, pendingRes] = await Promise.all([
        fetch("/api/intelligence/knowledge?status=active"),
        fetch("/api/intelligence/knowledge?status=pending"),
      ]);
      const active: KnowledgeFact[] = activeRes.ok ? await activeRes.json() : [];
      const pending: KnowledgeFact[] = pendingRes.ok ? await pendingRes.json() : [];
      setKnowledgeFacts([...active, ...pending]);
    } catch {
      // Silent
    } finally {
      setKnowledgeLoading(false);
    }
  }, []);

  // ---------------------------------------------------------------------------
  // Effect: fetch when clientId changes (and is non-empty); skip if already fetched
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (!clientId) return;
    if (fetchedForRef.current === clientId) return;
    fetchedForRef.current = clientId;

    fetchPlans(clientId);
    fetchTranscripts(clientId);
    fetchKnowledge();
  }, [clientId, fetchPlans, fetchTranscripts, fetchKnowledge]);

  // ---------------------------------------------------------------------------
  // Refresh callbacks — re-trigger fetch unconditionally
  // ---------------------------------------------------------------------------

  const refreshPlans = useCallback(() => {
    if (clientId) fetchPlans(clientId);
  }, [clientId, fetchPlans]);

  const refreshTranscripts = useCallback(() => {
    if (clientId) fetchTranscripts(clientId);
  }, [clientId, fetchTranscripts]);

  const refreshKnowledge = useCallback(() => {
    fetchKnowledge();
  }, [fetchKnowledge]);

  // ---------------------------------------------------------------------------
  // Context value
  // ---------------------------------------------------------------------------

  const value: IntelligenceContextValue = {
    clientId,
    setClientId,
    plans,
    latestPlan,
    plansLoading,
    refreshPlans,
    transcripts,
    transcriptsLoading,
    refreshTranscripts,
    knowledgeFacts,
    knowledgeLoading,
    refreshKnowledge,
  };

  return (
    <IntelligenceContext.Provider value={value}>
      {children}
    </IntelligenceContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

function useIntelligenceContext(): IntelligenceContextValue {
  const ctx = useContext(IntelligenceContext);
  if (!ctx) throw new Error("Intelligence hooks must be used within IntelligenceProvider");
  return ctx;
}

export function useIntelligence(): IntelligenceContextValue {
  return useIntelligenceContext();
}

export function usePlanCache() {
  const { plans, latestPlan, plansLoading, refreshPlans } = useIntelligenceContext();
  return { plans, latestPlan, plansLoading, refreshPlans };
}

export function useTranscriptCache() {
  const { transcripts, transcriptsLoading, refreshTranscripts } = useIntelligenceContext();
  return { transcripts, transcriptsLoading, refreshTranscripts };
}

export function useKnowledgeCache() {
  const { knowledgeFacts, knowledgeLoading, refreshKnowledge } = useIntelligenceContext();
  return { knowledgeFacts, knowledgeLoading, refreshKnowledge };
}
