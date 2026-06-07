// SupabaseDataSource — reads the orchestration tables the Python orchestrator writes.
// Fetches raw rows then reuses the shared compute helpers, so metrics match the mock exactly.

import type { DataSource } from "../dataSource";
import type { Scope, Account, Goal, Target, Lead, Commitment, CallOutcome } from "../types";
import { supabase } from "../supabaseClient";
import { inScope, computeKpis, computeTargetProgress, computeReport } from "./compute";

function scopeFilter<T extends { region?: string; branch?: string }>(q: any, scope: Scope) {
  if (scope.level === "region") return q.eq("region", scope.region);
  if (scope.level === "branch") return q.eq("branch", scope.branch);
  return q;
}

export class SupabaseDataSource implements DataSource {
  private async firstAccountId(): Promise<string | null> {
    const { data } = await supabase().from("accounts").select("id").limit(1);
    return data?.[0]?.id ?? null;
  }

  async getAccounts(): Promise<Account[]> {
    const { data } = await supabase().from("accounts").select("*");
    return (data as Account[]) ?? [];
  }

  async getLeads(scope: Scope): Promise<Lead[]> {
    const { data } = await scopeFilter(supabase().from("leads").select("*"), scope);
    return (data as Lead[]) ?? [];
  }

  async getCommitments(scope: Scope): Promise<Commitment[]> {
    const { data } = await scopeFilter(supabase().from("commitments").select("*"), scope);
    return (data as Commitment[]) ?? [];
  }

  async getCallOutcomes(scope: Scope): Promise<CallOutcome[]> {
    const { data } = await scopeFilter(supabase().from("call_outcomes").select("*"), scope);
    return (data as CallOutcome[]) ?? [];
  }

  async getKpis(scope: Scope) {
    return computeKpis(await this.getLeads(scope));
  }

  async getTargetProgress(scope: Scope) {
    const [leads, commitments, gt] = await Promise.all([
      this.getLeads(scope), this.getCommitments(scope), this.getGoalAndTarget(scope),
    ]);
    return computeTargetProgress(leads, commitments, gt.target);
  }

  async getReport(scope: Scope, period?: string) {
    const [leads, outcomes, gt] = await Promise.all([
      this.getLeads(scope), this.getCallOutcomes(scope), this.getGoalAndTarget(scope),
    ]);
    const month = period ?? gt.goal?.month ?? new Date().toISOString().slice(0, 7);
    return computeReport(leads, outcomes, gt.target, scope, month);
  }

  async getGoalAndTarget(_scope: Scope): Promise<{ goal: Goal | null; target: Target | null }> {
    const accountId = await this.firstAccountId();
    if (!accountId) return { goal: null, target: null };
    const { data: goals } = await supabase()
      .from("goals").select("*").eq("account_id", accountId).eq("active", true).limit(1);
    const goal = (goals?.[0] as Goal) ?? null;
    const period = goal?.month ?? new Date().toISOString().slice(0, 7);
    const { data: targets } = await supabase()
      .from("targets").select("*").eq("account_id", accountId).eq("period", period).limit(1);
    return { goal, target: (targets?.[0] as Target) ?? null };
  }
}
