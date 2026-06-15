// ApiDataSource — reads orchestration data through the orchestrator's REST API.
// The browser cannot hold Neon Postgres credentials, so the dashboard talks to the
// orchestrator (which normalizes any CRM) instead of querying the store directly.

import type { DataSource } from "../dataSource";
import type {
  Scope, Account, Goal, Target, Lead, Commitment, CallOutcome, Kpis, TargetProgress, Report,
} from "../types";

const BASE = process.env.NEXT_PUBLIC_ORCH_API_URL || "http://localhost:8000";

// Turn a Scope into the orchestrator's region/branch query params.
// "all" carries neither; values absent for the level are omitted.
function scopeParams(scope: Scope): Record<string, string | undefined> {
  return {
    region: scope.level === "region" ? scope.region : undefined,
    branch: scope.level === "branch" ? scope.branch : undefined,
  };
}

export class ApiDataSource implements DataSource {
  private async get<T>(path: string, params?: Record<string, string | undefined>): Promise<T> {
    const qs = new URLSearchParams();
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        if (v !== undefined) qs.set(k, v);
      }
    }
    const res = await fetch(`${BASE}${path}?${qs.toString()}`);
    if (!res.ok) {
      throw new Error(`ApiDataSource GET ${path} failed: ${res.status} ${res.statusText}`);
    }
    return (await res.json()) as T;
  }

  async getAccounts(): Promise<Account[]> {
    return this.get<Account[]>("/orchestrator/accounts");
  }

  async getKpis(scope: Scope): Promise<Kpis> {
    return this.get<Kpis>("/orchestrator/kpis", scopeParams(scope));
  }

  async getTargetProgress(scope: Scope): Promise<TargetProgress> {
    return this.get<TargetProgress>("/orchestrator/targets/progress", scopeParams(scope));
  }

  async getLeads(scope: Scope): Promise<Lead[]> {
    return this.get<Lead[]>("/orchestrator/leads", scopeParams(scope));
  }

  async getCommitments(scope: Scope): Promise<Commitment[]> {
    return this.get<Commitment[]>("/orchestrator/commitments", scopeParams(scope));
  }

  async getCallOutcomes(scope: Scope): Promise<CallOutcome[]> {
    return this.get<CallOutcome[]>("/orchestrator/call-outcomes", scopeParams(scope));
  }

  async getReport(scope: Scope, period?: string): Promise<Report> {
    return this.get<Report>("/orchestrator/report", { ...scopeParams(scope), period });
  }

  async getGoalAndTarget(scope: Scope): Promise<{ goal: Goal | null; target: Target | null }> {
    return this.get<{ goal: Goal | null; target: Target | null }>(
      "/orchestrator/goal", scopeParams(scope),
    );
  }
}
