// Shared typed contracts — mirror the orchestrator's normalized output (orchestrator/models.py).
// The dashboard renders these, not raw backend rows, so the same UI works over any CRM the
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

// ── Telehub types ────────────────────────────────────────────────────────
// Mirror services/telehub/apps/telehub/api/serializers.py exactly — read that
// file before changing any of these.

export interface Channel {
  id: number;
  name: string;
  description: string;
  icon: string;
  color: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  process_agent_count: number;
}

export interface ProcessAgentSummary {
  id: number;
  channel: number;
  channel_name: string;
  name: string;
  description: string;
  status: string;
  version: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

// ChannelDetailSerializer nests process agents via
// ChannelNestedProcessAgentSerializer, which only exposes this subset of
// ProcessAgentSummary's fields — not the full shape listChannels() returns.
export type ChannelNestedProcessAgent = Pick<
  ProcessAgentSummary,
  "id" | "name" | "status" | "is_active" | "version"
>;

export interface ChannelDetail extends Channel {
  process_agents: ChannelNestedProcessAgent[];
}

export interface LeadSource {
  id: number;
  type: string;
  configuration: Record<string, unknown>;
  field_mapping: Record<string, unknown>;
  created_at: string;
}

export interface ProcessAgentVariable {
  id: number;
  key: string;
  type: string;
  default_value: string;
  label: string;
  required: boolean;
  source: "business_rules" | "analytics";
}

export interface WebhookDefinition {
  id: number;
  name: string;
  url: string;
  // Computed live from the currently running ngrok tunnel — null when ngrok
  // isn't running locally (not stored; never goes stale on tunnel restart).
  public_url: string | null;
  secret: string;
  schema: Record<string, unknown>;
  status: string;
}

export interface ProcessAgentIntegration {
  id: number;
  integration: number;
  integration_name: string;
  integration_type: string;
}

// Mirrors services/telehub/apps/telehub/api/serializers.py's VoiceBotSerializer
// / BotJourneySerializer — see services/telehub/apps/telehub/models.py's
// VoiceBot/BotJourney for the backing tables. VoiceBot is a global, reusable
// bot identity/config managed on the dashboard's /bots page (not owned by any
// one ProcessAgent). A BotJourney is the one calling stage a ProcessAgent is
// wired to a VoiceBot through, created automatically at agent-creation time.
export interface VoiceBot {
  id: number;
  label: string;
  communication_type: string;
  bot_name: string;
  bot_id: string;
  dids: string[];
  api_url: string;
  script: string;
  webhook_schema: Record<string, unknown>;
  created_at: string;
}

export interface BotJourney {
  id: number;
  name: string;
  order: number;
  voice_bot: VoiceBot | null;
  created_at: string;
}

export interface ProcessAgentDetail {
  id: number;
  channel: number;
  channel_name: string;
  name: string;
  description: string;
  status: string;
  version: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  analytics_stats: Record<string, boolean>;
  lead_sources: LeadSource[];
  variables: ProcessAgentVariable[];
  webhooks: WebhookDefinition[];
  integrations: ProcessAgentIntegration[];
  omnichannel: {
    channel: string;
    variables: string[];
    whatsapp_template: string;
    whatsapp_curl: string;
  } | null;
  bot_journeys: BotJourney[];
}

// A single wizard-supplied runtime variable (business_rules.variables and
// analytics.custom_variables both use this shape — see
// services/telehub/apps/telehub/services/process_agent.py).
export interface ProcessAgentWizardVariable {
  key: string;
  type?: string;
  default_value?: string;
  required?: boolean;
}

// POST /process-agents/ body. Every nested section is optional — the backend
// defensively `.get()`s each one and a minimal {channelId, name} payload
// must succeed. Voice/qa config is dumped as-is onto node config, so both
// allow arbitrary extra keys beyond the ones the backend specifically reads.
export interface ProcessAgentWizardPayload {
  channelId: number;
  name: string;
  description?: string;
  voice?: {
    // The globally-managed VoiceBot (dashboard's /bots page) this process
    // agent's one BotJourney dispatches through — see
    // services/telehub/apps/telehub/services/process_agent.py.
    voice_bot_id?: number;
  };
  lead_source?: {
    type?: string;
    configuration?: Record<string, unknown>;
    field_mapping?: Record<string, unknown>;
  };
  business_rules?: {
    retry?: Record<string, unknown>;
    business_hours?: Record<string, unknown>;
    dnd?: Record<string, unknown>;
    callback?: Record<string, unknown>;
    variables?: ProcessAgentWizardVariable[];
  };
  integrations?: number[];
  qa?: Record<string, unknown>;
  analytics?: {
    // Dispositions and monitored variables are the same concept on the main
    // platform — one freeform list, not two.
    custom_variables?: ProcessAgentWizardVariable[];
    // Which dashboard stat tiles (call attempts, pickups, cost…) to show for
    // this process — computed from execution data already in the DB.
    stats?: Record<string, boolean>;
    [key: string]: unknown;
  };
  omnichannel?: {
    channel?: string;
    variables?: string[];
    whatsapp_template?: string;
    whatsapp_curl?: string;
  };
}

export interface JourneyNode {
  id: number;
  bot_journey: number | null;
  node_template_type: string;
  name: string;
  config: Record<string, unknown>;
  position_x: number;
  position_y: number;
  enabled: boolean;
}

export interface JourneyEdge {
  id: number;
  source_node: number;
  target_node: number;
  condition: string;
  priority: number;
}

export interface Integration {
  id: number;
  name: string;
  type: string;
  configuration: Record<string, unknown>;
  status: string;
  created_at: string;
}

export interface NodeTemplate {
  id: number;
  type: string;
  category: string;
  display_name: string;
  description: string;
  icon: string;
  color: string;
  default_config: Record<string, unknown>;
  schema: Record<string, unknown>;
}

export interface Execution {
  id: number;
  lead_id: string;
  status: string;
  started_at: string | null;
  ended_at: string | null;
  duration: number | null;
  current_node: string;
}

// Calls tab row — an Execution with its full variables (for an inbound agent,
// Chat360's post-call payload, "@" stripped from keys) and latest WhatsApp send.
export interface CallRow {
  id: number;
  lead_id: string;
  status: string;
  campaign_id: string;
  duration: number | null;
  current_node: string;
  variables: Record<string, unknown>;
  created_at: string;
  whatsapp: { status: "sent" | "failed"; error: string | null; at: string; count: number } | null;
}

export interface WhatsAppPreview {
  execution_id: number;
  receiver_number: string;
  template_title: string;
  params: Record<string, string>;
  missing: string[];
  error: string | null;
}

export interface WhatsAppSendResult {
  execution_id: number;
  success: boolean;
  status_code: number | null;
  error: string | null;
}

export interface QaResult {
  id: number;
  execution: number;
  summary: string;
  sentiment: string;
  hallucination_score: number | null;
  lead_score: number | null;
  compliance_score: number | null;
  bot_failure: boolean;
  hot_lead: boolean;
  recommendation: string;
  // Populated only when the wizard's QA "Missing Variables" check was on for
  // this process — the declared Variable keys absent/empty in this
  // execution's variables once the webhook payload merged in.
  missing_variables: string[];
  // The exact webhook payload merged in at QA time (outcome_routing.py's
  // _run_qa passes the same payload it received straight through).
  raw_result: Record<string, unknown>;
}

// GET /process-agents/{id}/analytics/ — wizard Analytics step's "Dispositions
// / Variables" values as actually captured per execution, read off
// Execution.variables (services/telehub/apps/telehub/api/views.py).
export interface ProcessAgentAnalyticsRow {
  execution_id: number;
  lead_id: string;
  status: string;
  created_at: string;
  values: Record<string, unknown>;
}

export interface ProcessAgentAnalytics {
  variable_keys: string[];
  rows: ProcessAgentAnalyticsRow[];
}

// GET /process-agents/{id}/stats/ — Overview tab's Performance cards
// (services/telehub/apps/telehub/services/analytics_stats.py). A field is
// null when there's nothing to compute it from yet (0 calls, or no QAResult
// has ever been scored) rather than a fabricated 0.
export interface ProcessAgentStats {
  calls: number;
  connected: number;
  avg_duration_seconds: number | null;
  qa_score: number | null;
  hot_leads: number;
  callback_requests: number;
}

// ── Campaign launch types ────────────────────────────────────────────────

export interface LaunchCampaignLead {
  to_number: string;
  params?: Record<string, string>;
  dnd?: string;
  lead_id?: string;
}

export interface LaunchCampaignPayload {
  campaign_id: string;
  // Omit (or pass []) to relaunch from the ProcessAgent's stored LeadSource
  // instead of uploading a fresh list — see getProcessAgentLeadSource.
  leads?: LaunchCampaignLead[];
}

export interface LaunchCampaignResult {
  campaign_id: string;
  created_count: number;
  skipped: string[];
}

export interface CampaignSummary {
  campaign_id: string;
  lead_count: number;
  created_at: string;
}

export interface CampaignLead {
  id: number;
  lead_id: string;
  status: string;
  current_node: string;
  variables: Record<string, unknown>;
  created_at: string;
}
