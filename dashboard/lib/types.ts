// Shared typed contracts — mirror the orchestrator's normalized output (orchestrator/models.py).
// The dashboard renders these, not raw Supabase rows, so the same UI works over any CRM the
// orchestrator normalizes.

export type ScopeLevel = "all" | "region" | "branch";

export interface Scope {
  level: ScopeLevel;
  region?: string;
  branch?: string;
}

export const ALL_SCOPE: Scope = { level: "all" };

export interface Account {
  id: string;
  name: string;
  brand: string;
}

export interface Goal {
  id: string;
  account_id: string;
  month: string;
  focus_type: "service" | "product";
  focus_detail: string;
  script_version: string;
  active: boolean;
}

export interface Target {
  id: string;
  account_id: string;
  period: string;
  reach_out: number;
  close: number;
  follow_up: number;
}

export interface Lead {
  id: string;
  account_id: string;
  name: string;
  phone: string;
  vehicle_model: string;
  service_due_date: string;
  source: string;
  region: string;
  branch: string;
  status: string;
  lead_score: number | null;
  created_at: string;
}

export interface Commitment {
  id: string;
  account_id: string;
  lead_id: string;
  region: string;
  branch: string;
  due_at: string;
  goal_context: Record<string, unknown>;
  note: string;
  sla_hours: number;
  retries: number;
  max_retries: number;
  state: string;
  created_at: string;
  updated_at: string;
}

export interface CallOutcome {
  id: string;
  account_id: string;
  execution_id: string;
  lead_id: string;
  goal_context: Record<string, unknown>;
  call_status: string;
  outcome: string;
  duration_sec: number;
  callback_at: string;
  region: string;
  branch: string;
  created_at: string;
}

export interface Kpis {
  total_leads: number;
  pending: number;
  calling: number;
  booked: number;
  not_interested: number;
  follow_up: number;
  conversion_rate: number; // booked / total_leads, 0..1
}

export interface ProgressPair {
  actual: number;
  target: number;
}

export interface TargetProgress {
  reach_out: ProgressPair;
  close: ProgressPair;
  follow_up: ProgressPair;
}

export interface ScopeBreakdown {
  name: string;
  leads: number;
  booked: number;
  conversion: number; // 0..1
}

export interface TimePoint {
  date: string;
  calls: number;
  booked: number;
}

export interface Report {
  period: string;
  scope: Scope;
  by_region: ScopeBreakdown[];
  by_branch: ScopeBreakdown[];
  outcomes_over_time: TimePoint[];
  goal_attainment: number; // booked / target.close, 0..1+
}

// ── Campaign & Orchestrator types ──────────────────────────────────────────

export interface Campaign {
  id: string;
  account_id: string;
  name: string;
  source: "xlsx" | "lms" | "zoho" | "hubspot";
  total_leads: number;
  qualified_leads: number;
  status:
    | "uploading"
    | "qualifying"
    | "pending_approval"
    | "scheduled"
    | "dispatching"
    | "done"
    | "cancelled";
  created_at: string;
}

export interface DispatchRecommendation {
  id: string;
  account_id: string;
  campaign_id: string;
  campaign_name: string;
  qualified_count: number;
  estimated_call_minutes: number;
  dids_available: number;
  status:
    | "pending_approval"
    | "scheduled"
    | "approved"
    | "dispatching"
    | "done"
    | "cancelled";
  scheduled_at: string | null;
  approved_at: string | null;
  recommendation_summary: string;
  created_at: string;
}

export interface ConnectorConfig {
  id: string;
  crm_type: "lms" | "zoho" | "hubspot" | "xlsx";
  status: "active" | "error" | "not_configured";
  display_name: string;
  last_synced_at: string | null;
}

export interface UploadResult {
  campaign_id: string;
  campaign_name: string;
  total_leads: number;
  preview_leads: Lead[];
  errors: string[];
}
