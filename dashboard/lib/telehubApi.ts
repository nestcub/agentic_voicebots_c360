// TelehubApi — talks directly to the Telehub Django/DRF service (services/telehub/),
// which owns Channels (backend: Departments), Process Agents, their journeys/executions/QA,
// Integrations and Node Templates. Mirrors the fetch conventions of lib/sources/apiDataSource.ts:
// same base-URL-env-var pattern, same `!res.ok` -> throw Error(...) handling.
//
// Frontend uses "Channel" terminology; backend uses "Department". The adapter layer below
// transparently maps between them. See CHANNEL_MIGRATION.md for context.

import type {
  Channel,
  ChannelDetail,
  ProcessAgentSummary,
  ProcessAgentDetail,
  ProcessAgentWizardPayload,
  JourneyNode,
  JourneyEdge,
  Integration,
  NodeTemplate,
  Execution,
  QaResult,
  ProcessAgentStats,
  ProcessAgentAnalytics,
  LeadSource,
  LaunchCampaignPayload,
  LaunchCampaignResult,
  CampaignSummary,
  CampaignLead,
  ProcessAgentVariable,
  WebhookDefinition,
  ProcessAgentIntegration,
  BotJourney,
  VoiceBot,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_TELEHUB_API_URL || "http://localhost:8000";
const API = `${BASE}/api/telehub`;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`TelehubApi ${init?.method ?? "GET"} ${path} failed: ${res.status} ${res.statusText} ${body}`);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

function get<T>(path: string): Promise<T> {
  return request<T>(path);
}

function post<T>(path: string, data: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body: JSON.stringify(data) });
}

function patch<T>(path: string, data: unknown): Promise<T> {
  return request<T>(path, { method: "PATCH", body: JSON.stringify(data) });
}

function del(path: string): Promise<void> {
  return request<void>(path, { method: "DELETE" });
}

// ── Adapter layer: map frontend "Channel" terminology to backend "Department" ──
// This allows the frontend to use "channel" while keeping the backend unchanged.
// See CHANNEL_MIGRATION.md for rationale.

function mapChannelToBackend(data: any): any {
  if (data && typeof data === "object") {
    const copy = { ...data };
    if ("channelId" in copy) {
      copy.department = copy.channelId;
      delete copy.channelId;
    }
    return copy;
  }
  return data;
}

function mapBackendToChannel(data: any): any {
  if (!data) return data;
  if (Array.isArray(data)) {
    return data.map(mapBackendToChannel);
  }
  if (typeof data === "object") {
    const copy = { ...data };
    if ("department" in copy && "department_name" in copy) {
      copy.channel = copy.department;
      copy.channel_name = copy.department_name;
      delete copy.department;
      delete copy.department_name;
    }
    return copy;
  }
  return data;
}

// ── Channels (backend: Departments) ──────────────────────────────────────

export function listChannels(): Promise<Channel[]> {
  return get<any>("/departments/").then(mapBackendToChannel);
}

export function getChannel(id: number): Promise<ChannelDetail> {
  return get<any>(`/departments/${id}/`).then(mapBackendToChannel);
}

export function createChannel(data: {
  name: string;
  description?: string;
  icon?: string;
  color?: string;
}): Promise<Channel> {
  return post<any>("/departments/", data).then(mapBackendToChannel);
}

export function updateChannel(
  id: number,
  data: Partial<{ name: string; description: string; icon: string; color: string; is_active: boolean }>,
): Promise<Channel> {
  return patch<any>(`/departments/${id}/`, data).then(mapBackendToChannel);
}

export function deleteChannel(id: number): Promise<void> {
  return del(`/departments/${id}/`);
}

// ── Process Agents ───────────────────────────────────────────────────────

export function listProcessAgents(channelId?: number): Promise<ProcessAgentSummary[]> {
  const qs = channelId !== undefined ? `?department=${channelId}` : "";
  return get<any>(`/process-agents/${qs}`).then(mapBackendToChannel);
}

export function getProcessAgent(id: number): Promise<ProcessAgentDetail> {
  return get<any>(`/process-agents/${id}/`).then(mapBackendToChannel);
}

export function createProcessAgent(payload: ProcessAgentWizardPayload): Promise<ProcessAgentDetail> {
  const backendPayload = mapChannelToBackend(payload);
  return post<any>("/process-agents/", backendPayload).then(mapBackendToChannel);
}

export function updateProcessAgent(
  id: number,
  data: Partial<{ name: string; description: string; status: string; is_active: boolean }>,
): Promise<ProcessAgentDetail> {
  return patch<any>(`/process-agents/${id}/`, data).then(mapBackendToChannel);
}

export function deleteProcessAgent(id: number): Promise<void> {
  return del(`/process-agents/${id}/`);
}

export function getProcessAgentJourney(id: number): Promise<{ nodes: JourneyNode[]; edges: JourneyEdge[] }> {
  return get<{ nodes: JourneyNode[]; edges: JourneyEdge[] }>(`/process-agents/${id}/journey/`);
}

export function getProcessAgentExecutions(id: number): Promise<Execution[]> {
  return get<Execution[]>(`/process-agents/${id}/executions/`);
}

export function getProcessAgentQaResults(id: number): Promise<QaResult[]> {
  return get<QaResult[]>(`/process-agents/${id}/qa_results/`);
}

export function getProcessAgentStats(id: number): Promise<ProcessAgentStats> {
  return get<ProcessAgentStats>(`/process-agents/${id}/stats/`);
}

export function getProcessAgentAnalytics(id: number): Promise<ProcessAgentAnalytics> {
  return get<ProcessAgentAnalytics>(`/process-agents/${id}/analytics/`);
}

// A ProcessAgent's BotJourney(s), created by the wizard — read-only here.
// Used to resolve bot_journey_id for the Runs/QA tabs' dispatch actions.
export function getProcessAgentBotJourneys(id: number): Promise<BotJourney[]> {
  return get<BotJourney[]>(`/process-agents/${id}/journeys/`);
}

// ── Bots (global VoiceBot library — dashboard's /bots page) ─────────────

export type VoiceBotWrite = Partial<
  Pick<VoiceBot, "label" | "communication_type" | "bot_name" | "bot_id" | "dids" | "api_url" | "script" | "webhook_schema">
>;

export function listVoiceBots(): Promise<VoiceBot[]> {
  return get<VoiceBot[]>("/voice-bots/");
}

export function createVoiceBot(data: VoiceBotWrite): Promise<VoiceBot> {
  return post<VoiceBot>("/voice-bots/", data);
}

export function updateVoiceBot(voiceBotId: number, data: VoiceBotWrite): Promise<VoiceBot> {
  return patch<VoiceBot>(`/voice-bots/${voiceBotId}/`, data);
}

export function deleteVoiceBot(voiceBotId: number): Promise<void> {
  return del(`/voice-bots/${voiceBotId}/`);
}

export function getProcessAgentLeadSource(id: number): Promise<LeadSource | Record<string, never>> {
  return get<LeadSource | Record<string, never>>(`/process-agents/${id}/lead-source/`);
}

export function updateProcessAgentLeadSource(
  id: number,
  data: Partial<Pick<LeadSource, "type" | "configuration" | "field_mapping">>,
): Promise<LeadSource> {
  return patch<LeadSource>(`/process-agents/${id}/lead-source/`, data);
}

// ── Settings tab: QA / Analytics stats / Variables / Webhooks / Omnichannel / Integrations ──

export function getProcessAgentQaConfig(id: number): Promise<Record<string, boolean>> {
  return get<Record<string, boolean>>(`/process-agents/${id}/qa-config/`);
}

export function updateProcessAgentQaConfig(
  id: number,
  data: Partial<Record<string, boolean>>,
): Promise<Record<string, boolean>> {
  return patch<Record<string, boolean>>(`/process-agents/${id}/qa-config/`, data);
}

export function updateProcessAgentAnalyticsStats(
  id: number,
  data: Partial<Record<string, boolean>>,
): Promise<Record<string, boolean>> {
  return patch<Record<string, boolean>>(`/process-agents/${id}/analytics-stats/`, data);
}

export type ProcessAgentVariableWrite = Partial<
  Pick<ProcessAgentVariable, "key" | "type" | "default_value" | "label" | "required" | "source">
>;

export function createProcessAgentVariable(
  id: number,
  data: ProcessAgentVariableWrite,
): Promise<ProcessAgentVariable> {
  return post<ProcessAgentVariable>(`/process-agents/${id}/variables/`, data);
}

export function updateProcessAgentVariable(
  id: number,
  variableId: number,
  data: ProcessAgentVariableWrite,
): Promise<ProcessAgentVariable> {
  return patch<ProcessAgentVariable>(`/process-agents/${id}/variables/${variableId}/`, data);
}

export function deleteProcessAgentVariable(id: number, variableId: number): Promise<void> {
  return del(`/process-agents/${id}/variables/${variableId}/`);
}

export function updateProcessAgentWebhook(
  id: number,
  webhookId: number,
  data: Partial<Pick<WebhookDefinition, "name" | "schema" | "status">>,
): Promise<WebhookDefinition> {
  return patch<WebhookDefinition>(`/process-agents/${id}/webhooks/${webhookId}/`, data);
}

export interface OmnichannelConfigWrite {
  channel?: string;
  variables?: string[];
  whatsapp_template?: string;
  whatsapp_curl?: string;
}

export function updateProcessAgentOmnichannel(
  id: number,
  data: OmnichannelConfigWrite,
): Promise<OmnichannelConfigWrite> {
  return patch<OmnichannelConfigWrite>(`/process-agents/${id}/omnichannel/`, data);
}

export function attachProcessAgentIntegration(
  id: number,
  integrationId: number,
): Promise<ProcessAgentIntegration> {
  return post<ProcessAgentIntegration>(`/process-agents/${id}/integrations/`, { integration: integrationId });
}

export function detachProcessAgentIntegration(id: number, processIntegrationId: number): Promise<void> {
  return del(`/process-agents/${id}/integrations/${processIntegrationId}/`);
}

// ── Integrations ─────────────────────────────────────────────────────────

export function listIntegrations(): Promise<Integration[]> {
  return get<Integration[]>("/integrations/");
}

export function createIntegration(data: {
  name: string;
  type: string;
  configuration?: Record<string, unknown>;
  status?: string;
}): Promise<Integration> {
  return post<Integration>("/integrations/", data);
}

export function updateIntegration(
  id: number,
  data: Partial<{ name: string; type: string; configuration: Record<string, unknown>; status: string }>,
): Promise<Integration> {
  return patch<Integration>(`/integrations/${id}/`, data);
}

export function deleteIntegration(id: number): Promise<void> {
  return del(`/integrations/${id}/`);
}

// ── Node Templates ───────────────────────────────────────────────────────

export function listNodeTemplates(): Promise<NodeTemplate[]> {
  return get<NodeTemplate[]>("/node-templates/");
}

// ── Campaigns ────────────────────────────────────────────────────────────

export function launchCampaign(
  processAgentId: number,
  payload: LaunchCampaignPayload,
): Promise<LaunchCampaignResult> {
  return post<LaunchCampaignResult>(`/process-agents/${processAgentId}/launch-campaign/`, payload);
}

export function listCampaigns(processAgentId: number): Promise<CampaignSummary[]> {
  return get<CampaignSummary[]>(`/process-agents/${processAgentId}/campaigns/`);
}

export function listCampaignLeads(processAgentId: number, campaignId: string): Promise<CampaignLead[]> {
  return get<CampaignLead[]>(
    `/process-agents/${processAgentId}/campaigns/${encodeURIComponent(campaignId)}/leads/`,
  );
}

export interface DispatchSingleCallResult {
  execution_id: number;
  created_count: number;
  success: boolean;
  status_code: number | null;
  error: string | null;
}

export function dispatchSingleCall(
  processAgentId: number,
  params: Record<string, string>,
  botJourneyId?: number,
): Promise<DispatchSingleCallResult> {
  return post<DispatchSingleCallResult>(`/process-agents/${processAgentId}/dispatch-single-call/`, {
    params,
    ...(botJourneyId !== undefined ? { bot_journey_id: botJourneyId } : {}),
  });
}

// QA tab's "Dispatch Follow-up": re-dials the lead from a past Execution
// through a chosen BotJourney — see the dispatch_follow_up action in
// services/telehub/apps/telehub/api/views.py for the full contract.
export function dispatchFollowUp(
  processAgentId: number,
  data: { execution_id: number; bot_journey_id: number; params?: Record<string, string> },
): Promise<DispatchSingleCallResult> {
  return post<DispatchSingleCallResult>(`/process-agents/${processAgentId}/dispatch-follow-up/`, data);
}
