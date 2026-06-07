// MockDataSource — implements DataSource over the in-code mock dataset.

import type { DataSource } from "../dataSource";
import type { Scope } from "../types";
import { ACCOUNT, GOAL, TARGET, LEADS, COMMITMENTS, CALL_OUTCOMES } from "./mockData";
import { inScope, computeKpis, computeTargetProgress, computeReport } from "./compute";

export class MockDataSource implements DataSource {
  async getAccounts() {
    return [ACCOUNT];
  }

  async getKpis(scope: Scope) {
    return computeKpis(LEADS.filter((l) => inScope(l, scope)));
  }

  async getTargetProgress(scope: Scope) {
    const leads = LEADS.filter((l) => inScope(l, scope));
    const commitments = COMMITMENTS.filter((c) => inScope(c, scope));
    return computeTargetProgress(leads, commitments, TARGET);
  }

  async getLeads(scope: Scope) {
    return LEADS.filter((l) => inScope(l, scope));
  }

  async getCommitments(scope: Scope) {
    return COMMITMENTS.filter((c) => inScope(c, scope));
  }

  async getCallOutcomes(scope: Scope) {
    return CALL_OUTCOMES.filter((o) => inScope(o, scope));
  }

  async getReport(scope: Scope, period = GOAL.month) {
    const leads = LEADS.filter((l) => inScope(l, scope));
    const outcomes = CALL_OUTCOMES.filter((o) => inScope(o, scope));
    return computeReport(leads, outcomes, TARGET, scope, period);
  }

  async getGoalAndTarget() {
    return { goal: GOAL, target: TARGET };
  }
}
