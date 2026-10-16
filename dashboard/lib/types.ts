// Shared typed contracts for the dashboard. The lead/campaign shapes below are used by the
// XLSX upload route and lead views; the Telehub section mirrors the Django serializers.

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

export interface ProgressPair {
  actual: number;
  target: number;
}

// ── Campaign types ──────────────────────────────────────────

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
  /** Legacy — no longer part of uniqueness; one row per key. */
  source: "business_rules" | "analytics";
  /** Ticked for the QA missing-variables check. */
  use_in_qa: boolean;
  /** Ticked for the Analytics tab. */
  use_in_analytics: boolean;
  /** Created automatically from a webhook payload rather than declared by hand. */
  discovered: boolean;
  last_seen_at: string | null;
  /** Latest non-empty value seen, shown as a hint when ticking. */
  sample_value: string;
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
/** One DID of a voice bot. A number belongs to exactly one bot, across all organisations. */
export interface PhoneNumber {
  id: number;
  did: string;
}

export interface VoiceBot {
  id: number;
  label: string;
  communication_type: string;
  bot_name: string;
  bot_id: string;
  dids: string[];
  /** The same numbers as `dids`, as rows a stage can select from. */
  numbers: PhoneNumber[];
  api_url: string;
  script: string;
  webhook_schema: Record<string, unknown>;
  created_at: string;
}

/** A voicebot stage of a process agent. */
export interface BotJourney {
  id: number;
  name: string;
  order: number;
  voice_bot: VoiceBot | null;
  /** Numbers explicitly chosen for this stage; empty = it uses all of its bot's numbers. */
  numbers: PhoneNumber[];
  /** The DIDs the stage effectively uses (first = outbound caller ID; inbound calls must dial one). */
  active_dids: string[];
  created_at: string;
}

/** "When a call in `from_journey` ends and the checks pass, hand the lead to `to_journey`." */
export interface JourneyTransition {
  id: number;
  from_journey: number;
  from_name: string;
  to_journey: number;
  to_name: string;
  on: "completed" | "retries_exhausted";
  priority: number;
  match: "all" | "any";
  checks: ChannelRuleCheck[];
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
    // Hyundai POC: one curl per template key (T1/T2/T3) + automatic sending.
    whatsapp_curls: Record<string, string>;
    auto_send: boolean;
    whatsapp_templates: Record<string, WhatsAppTemplateSummary>;
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
    // The one PhoneNumber of that bot the stage uses; omitted = automatic.
    numbers?: number[];
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
// What a pasted template curl parses to (see OmnichannelConfigSerializer).
export interface WhatsAppTemplateSummary {
  configured: boolean;
  url: string;
  template_title: string;
  params: string[];
  error: string | null;
}

export interface CallRow {
  id: number;
  lead_id: string;
  status: string;
  campaign_id: string;
  duration: number | null;
  current_node: string;
  variables: Record<string, unknown>;
  created_at: string;
  // Latest WhatsApp send for this call (automatic or manual).
  whatsapp: {
    /** Null for sends from before WhatsAppSend existed (read off events). */
    id: number | null;
    status: "pending" | "sent" | "failed" | "skipped" | "blocked";
    /** Blocked sends only: variable names still waiting for a value. */
    missing: string[];
    template_key: string | null;
    trigger: "auto" | "manual";
    error: string | null;
    at: string;
    count: number;
  } | null;
  /** Template the rules pick for this call; null when a skip rule wins or none match. */
  suggested_template: string | null;
}

// ── Omnichannel templates + rules (services/telehub/.../services/channel_config.py) ──

/** One placeholder in a template's curl, e.g. {key: "customer_name", placeholder: "customer_name"}. */
export interface ChannelTemplateParam {
  key: string;
  placeholder: string;
}

/** Where a param's value comes from. No entry = matched by the curl's own placeholder text. */
export type ChannelParamEntry = { variable: string; fallback?: string } | { fixed: string };

export interface ChannelTemplate {
  id: number;
  name: string;
  channel: string;
  is_active: boolean;
  /** Sent in place of an empty variable; blank = an empty variable blocks the send. */
  missing_fill: string;
  param_map: Record<string, ChannelParamEntry>;
  configured: boolean;
  url: string;
  template_title: string;
  params: ChannelTemplateParam[];
  error: string | null;
  /** Variables this template reads — what the customer's message can contain. */
  variables_sent: string[];
}

export interface ChannelTemplateList {
  templates: ChannelTemplate[];
  variables_sent: string[];
}

export type ChannelCheckOp = "exists" | "not_exists" | "equals" | "truthy";

export interface ChannelRuleCheck {
  variable: string;
  op: ChannelCheckOp;
  value?: string;
}

export interface ChannelRule {
  id: number;
  priority: number;
  action: "send" | "skip";
  template: number | null;
  template_name: string | null;
  match: "all" | "any";
  checks: ChannelRuleCheck[];
  reason: string;
}

export interface WhatsAppPreview {
  execution_id: number;
  template_key: string;
  receiver_number: string;
  template_title: string;
  params: Record<string, string>;
  /** Param keys with no value. */
  missing: string[];
  /** The variable names behind them — what to fill in. */
  missing_variables: string[];
  error: string | null;
}

export interface WhatsAppSendResult {
  execution_id: number;
  template_key: string;
  success: boolean;
  status_code: number | null;
  error: string | null;
  /** True when nothing was sent because mapped variables are empty; `missing` names them. */
  blocked?: boolean;
  missing?: string[];
  send_id?: number;
}

export interface WhatsAppFillResult extends WhatsAppSendResult {
  send_id: number;
  status: "pending" | "sent" | "failed" | "blocked";
  missing: string[];
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
