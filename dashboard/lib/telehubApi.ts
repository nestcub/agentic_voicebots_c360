// TelehubApi — talks directly to the Telehub Django/DRF service (services/telehub/),
// which owns Departments, Process Agents, their journeys/executions/QA, Integrations
// and Node Templates. Mirrors the fetch conventions of lib/sources/apiDataSource.ts:
// same base-URL-env-var pattern, same `!res.ok` -> throw Error(...) handling.

import type {
  Department,
  DepartmentDetail,
  ProcessAgentSummary,
  ProcessAgentDetail,
  ProcessAgentWizardPayload,
  JourneyNode,
  JourneyEdge,
  Integration,
  NodeTemplate,
  Execution,
  QaResult,
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

// ── Departments ──────────────────────────────────────────────────────────

export function listDepartments(): Promise<Department[]> {
  return get<Department[]>("/departments/");
}

export function getDepartment(id: number): Promise<DepartmentDetail> {
  return get<DepartmentDetail>(`/departments/${id}/`);
}

export function createDepartment(data: {
  name: string;
  description?: string;
  icon?: string;
  color?: string;
}): Promise<Department> {
  return post<Department>("/departments/", data);
}

export function updateDepartment(
  id: number,
  data: Partial<{ name: string; description: string; icon: string; color: string; is_active: boolean }>,
): Promise<Department> {
  return patch<Department>(`/departments/${id}/`, data);
}

export function deleteDepartment(id: number): Promise<void> {
  return del(`/departments/${id}/`);
}

// ── Process Agents ───────────────────────────────────────────────────────

export function listProcessAgents(departmentId?: number): Promise<ProcessAgentSummary[]> {
  const qs = departmentId !== undefined ? `?department=${departmentId}` : "";
  return get<ProcessAgentSummary[]>(`/process-agents/${qs}`);
}

export function getProcessAgent(id: number): Promise<ProcessAgentDetail> {
  return get<ProcessAgentDetail>(`/process-agents/${id}/`);
}

export function createProcessAgent(payload: ProcessAgentWizardPayload): Promise<ProcessAgentDetail> {
  return post<ProcessAgentDetail>("/process-agents/", payload);
}

export function updateProcessAgent(
  id: number,
  data: Partial<{ name: string; description: string; status: string; is_active: boolean }>,
): Promise<ProcessAgentDetail> {
  return patch<ProcessAgentDetail>(`/process-agents/${id}/`, data);
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
