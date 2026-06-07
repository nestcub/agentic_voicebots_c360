// The DataSource interface — the UI mirror of the Python adapter pattern.
// Pages/components depend ONLY on this, never on Supabase directly. Swap the backend
// (Mock today → Supabase → Chat360 API → any CRM) by changing the factory below.

import type {
  Account, Scope, Kpis, TargetProgress, Lead, Commitment, CallOutcome, Report, Goal, Target,
} from "./types";

export interface DataSource {
  getAccounts(): Promise<Account[]>;
  getKpis(scope: Scope): Promise<Kpis>;
  getTargetProgress(scope: Scope): Promise<TargetProgress>;
  getLeads(scope: Scope): Promise<Lead[]>;
  getCommitments(scope: Scope): Promise<Commitment[]>;
  getCallOutcomes(scope: Scope): Promise<CallOutcome[]>;
  getReport(scope: Scope, period?: string): Promise<Report>;
  getGoalAndTarget(scope: Scope): Promise<{ goal: Goal | null; target: Target | null }>;
}

let _source: DataSource | null = null;

// Factory: choose the backend. Defaults to Mock unless a Supabase URL is configured AND
// NEXT_PUBLIC_DATA_SOURCE !== "mock". Async import keeps the unused backend out of the bundle path.
export async function getDataSource(): Promise<DataSource> {
  if (_source) return _source;

  const mode = process.env.NEXT_PUBLIC_DATA_SOURCE;
  const hasSupabase = !!process.env.NEXT_PUBLIC_SUPABASE_URL;

  if (mode !== "mock" && hasSupabase) {
    const { SupabaseDataSource } = await import("./sources/supabaseDataSource");
    _source = new SupabaseDataSource();
  } else {
    const { MockDataSource } = await import("./sources/mockDataSource");
    _source = new MockDataSource();
  }
  return _source;
}
