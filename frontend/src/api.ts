const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export type AlertStatus =
  | "open"
  | "investigating"
  | "awaiting_confirmation"
  | "resolved"
  | "rejected"
  | "routed_to_support";

export interface Alert {
  alert_id: string;
  machine_id: string;
  machine_name?: string;
  machine_type?: string;
  org_id: string;
  alert_type: string;
  severity: "low" | "medium" | "high";
  status: AlertStatus;
  created_at: string;
}

export interface AlertStatusResponse {
  alert_id: string;
  status: AlertStatus;
  proposed_fix: string | null;
  confidence: string | null;
  root_cause_summary: string | null;
  confirmation_token: string | null;
}

export interface AuditLogEntry {
  alert_id: string;
  timestamp: string;
  log_id: string;
  actor: "agent" | "human" | "system";
  action: string;
  details: Record<string, unknown>;
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options?.headers ?? {}) },
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}) as { error?: string });
    throw new ApiError(body.error ?? `Request failed: ${resp.status}`, resp.status);
  }
  return (await resp.json()) as T;
}

export function listAlerts(): Promise<{ alerts: Alert[] }> {
  return request("/demo/alerts");
}

export function startInvestigation(alertId: string): Promise<{ alert_id: string; status: string }> {
  return request(`/demo/alerts/${alertId}/investigate`, { method: "POST" });
}

export function getAlertStatus(alertId: string): Promise<AlertStatusResponse> {
  return request(`/demo/alerts/${alertId}/status`);
}

export function confirmFix(
  alertId: string,
  confirmationToken: string,
): Promise<{ alert_id: string; outcome: string }> {
  return request(`/demo/alerts/${alertId}/confirm`, {
    method: "POST",
    body: JSON.stringify({ confirmation_token: confirmationToken }),
  });
}

export function rejectFix(alertId: string, reason?: string): Promise<{ alert_id: string; outcome: string }> {
  return request(`/demo/alerts/${alertId}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function getAuditTrail(alertId: string): Promise<{ audit_trail: AuditLogEntry[] }> {
  return request(`/demo/alerts/${alertId}/audit`);
}
