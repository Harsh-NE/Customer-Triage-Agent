// Typed client for the backend in triage/api (see docs/BACKEND.md). All paths are under /api (proxied to :8000 in development).

export type Role = "customer" | "engineer";
export interface User { id: number; username: string; role: Role }
export type Status = "active" | "resolved" | "escalated" | "declined";
export type Priority = "P1" | "P2" | "P3" | "P4";

export interface Source { id: string; title: string; url: string; tier: string; official: boolean; source_tier?: string | null; license?: string | null; trust_tier?: string | null }
export interface Step { text: string; evidence_ids: string[] }
export interface Message {
  id: number; role: "customer" | "agent" | "engineer" | "system"; kind: string; content: string;
  payload: Record<string, any>; created_at: string; author?: string | null; // eslint-disable-line @typescript-eslint/no-explicit-any
}

export interface ConversationSummary {
  id: string; title: string; status: Status; escalated: boolean; created_at: string; updated_at: string;
  closed_at: string | null; duration_s: number; rating: number | null; helpful: boolean | null; resolved_by: string | null;
}
export interface Feedback { rating: number | null; helpful: boolean | null; comment: string | null }
export interface ConversationView extends ConversationSummary { can_reply: boolean; feedback: Feedback; assigned: boolean; messages: Message[] }

export interface CaseRow extends ConversationSummary { priority: Priority | null; reason: string | null; assigned_to: string | null; age_minutes: number }
export interface Hypothesis { label: string; issue?: string; weight: number; grounding?: number; missing_terms?: string[] }
export interface Attempt { attempt_no: number; tier: string; diagnosis?: string; steps: Step[]; sources?: { id: string; title: string; url: string; tier: string }[]; customer_reply?: string | null; reply_label?: string | null }
export interface EvidenceRow { id: string; tier: string; url: string; score: number | null; issue?: string | null; trust?: number | null; license?: string | null; snippet: string }
export interface ActivityStep { ts: string; event: string; label: string; level: "ok" | "warn" | "error"; latency_ms: number | null }
export interface Usage { input_tokens: number; output_tokens: number; cost_usd: number; llm_calls: number; unpriced_calls: number }
export interface CaseDetail extends CaseRow {
  customer: string; resolution_text: string | null; promote_to_kb: boolean; feedback: Feedback; messages: Message[];
  agent: {
    signature: Record<string, any> | null; hypotheses: Hypothesis[]; entities?: { id: string; name: string; type: string }[]; confidence: number | null; // eslint-disable-line @typescript-eslint/no-explicit-any
    clarifier: { status?: string; reason?: string; p_top?: number; margin?: number; uncovered_terms?: string[]; questions_asked?: number };
    gate: { confidence?: number; strong?: boolean; top?: number; margin?: number; agreement?: number; completeness?: number; reasons?: string[]; tier?: string } | null;
    gate_decision: string | null; cache_status: string | null; attempts: Attempt[]; evidence: EvidenceRow[];
    escalation: { reason_code: string; priority: string; summary_md: string; suggested_next_checks: string[]; detail?: string } | null;
    error: string | null;
  };
  activity: ActivityStep[]; usage: Usage;
  notes: { id: number; author: string; body: string; created_at: string }[];
  actions: { actor: string; action: string; data: Record<string, unknown>; created_at: string }[]; // eslint-disable-line @typescript-eslint/no-explicit-any
}

export interface Summary {
  window_days: number; definitions: Record<string, string>;
  totals: { conversations: number; active: number; resolved: number; resolved_by_agent: number; resolved_by_engineer: number; escalated_open: number; declined: number };
  rates: { resolution_rate: number | null; agent_resolution_rate: number | null; escalation_rate: number | null; decline_rate: number | null };
  timing: { avg_time_to_resolution_s: number | null; avg_agent_resolution_s: number | null };
  feedback: { avg_rating: number | null; ratings: number; helpful_rate: number | null; helpful_votes: number };
  agent_behaviour: { avg_questions_per_conversation: number | null; cache_lookups: number; cache_hit_rate: number | null; verify_drop_rate: number | null; avg_gate_confidence: number | null };
  escalation_reasons: Record<string, number>;
  cost: CostBlock;
}
export interface CostBlock {
  input_tokens: number; output_tokens: number; total_tokens: number; llm_calls: number; unpriced_calls: number; total_cost_usd: number;
  avg_cost_per_conversation_usd: number | null; avg_cost_resolved_usd: number | null; avg_cost_escalated_usd: number | null;
}
export interface Bucket { calls: number; input_tokens: number; output_tokens: number; cost_usd: number; unpriced_calls: number }
export interface CostReport { window_days: number; overall: CostBlock; by_model: Record<string, Bucket>; by_node: Record<string, Bucket>; by_day: { date: string; cost_usd: number }[] }
export interface DayPoint { date: string; created: number; resolved: number; escalated: number; declined: number; active: number }

// ---------------------------------------------------------------------------------------------------------------
const TOKEN_KEY = "triage.token";

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
export function setToken(token: string | null): void {
  try { if (token) localStorage.setItem(TOKEN_KEY, token); else localStorage.removeItem(TOKEN_KEY); } catch { /* private mode: stay logged in for this page only */ }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

function detailOf(body: unknown, fallback: string): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((e) => (e as { msg?: string }).msg ?? "invalid input").join("; ");
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(init.headers ?? {}) },
  });
  const body = await res.json().catch(() => null);
  if (res.status === 401 && token) { setToken(null); window.dispatchEvent(new Event("auth:expired")); }
  if (!res.ok) throw new ApiError(res.status, detailOf(body, `${res.status} ${res.statusText}`));
  return body as T;
}

const post = <T,>(path: string, body?: unknown) => request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const qs = (params: Record<string, string | number | undefined>) => {
  const s = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)]));
  return s.size ? `?${s}` : "";
};

export const api = {
  login: (username: string, role: Role, passcode?: string) => post<{ token: string; user: User }>("/auth/login", { username, role, passcode }),
  me: () => request<User>("/me"),
  // customer
  start: (message: string) => post<ConversationView>("/conversations", { message }),
  conversation: (id: string) => request<ConversationView>(`/conversations/${id}`),
  history: () => request<{ conversations: ConversationSummary[] }>("/conversations"),
  send: (id: string, body: { text?: string; action?: "resolved" | "not_fixed" }) => post<ConversationView>(`/conversations/${id}/messages`, body),
  feedback: (id: string, body: { rating?: number; helpful?: boolean; comment?: string }) => post<{ ok: boolean }>(`/conversations/${id}/feedback`, body),
  // engineer
  cases: (p: { status?: string; priority?: string; reason?: string; assigned?: string; q?: string }) =>
    request<{ total: number; cases: CaseRow[] }>(`/cases${qs({ ...p, limit: 100 })}`),
  caseDetail: (id: string) => request<CaseDetail>(`/cases/${id}`),
  reply: (id: string, text: string) => post<CaseDetail>(`/cases/${id}/reply`, { text }),
  assign: (id: string, engineer?: string) => post<CaseDetail>(`/cases/${id}/assign`, { engineer }),
  setPriority: (id: string, priority: Priority) => post<CaseDetail>(`/cases/${id}/priority`, { priority }),
  addNote: (id: string, text: string) => post<CaseDetail>(`/cases/${id}/notes`, { text }),
  resolve: (id: string, resolution: string, promote_to_kb: boolean) => post<CaseDetail>(`/cases/${id}/resolve`, { resolution, promote_to_kb }),
  reopen: (id: string) => post<CaseDetail>(`/cases/${id}/reopen`),
  // analytics
  summary: (days: number) => request<Summary>(`/analytics/summary?days=${days}`),
  timeseries: (days: number) => request<{ days: DayPoint[] }>(`/analytics/timeseries?days=${days}`),
  cost: (days: number) => request<CostReport>(`/analytics/cost?days=${days}`),
};
