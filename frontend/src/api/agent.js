/**
 * CampusPilot API client.
 *
 * By default requests go to the same origin (`/api/...`): in production FastAPI serves
 * the app, and in development Vite proxies /api to the backend. The anonymous session
 * cookie is HttpOnly and handled by the browser; no secrets live in the frontend.
 */
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
const REQUEST_TIMEOUT_MS = 30000;

export class ApiError extends Error {
  constructor(message, { status = 0, kind = "server" } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.kind = kind; // network | timeout | validation | conflict | expired | rate_limited | not_found | server
  }
}

function detailToMessage(detail) {
  if (!detail) return null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0];
    const field = Array.isArray(first.loc) ? first.loc.filter((p) => p !== "body").join(".") : "";
    if (first.type === "string_too_long") return "That goal is too long. Please keep it under 1,000 characters.";
    return field ? `${field}: ${first.msg}` : first.msg;
  }
  return null;
}

function kindForStatus(status) {
  if (status === 400 || status === 422) return "validation";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status === 410) return "expired";
  if (status === 413) return "validation";
  if (status === 429) return "rate_limited";
  return "server";
}

export async function request(path, { method = "GET", body, signal } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  if (signal) signal.addEventListener("abort", () => controller.abort(), { once: true });

  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      credentials: API_BASE_URL ? "include" : "same-origin",
      signal: controller.signal,
    });
  } catch (err) {
    clearTimeout(timer);
    if (err?.name === "AbortError") {
      throw new ApiError("CampusPilot took too long to respond. Please try again.", { kind: "timeout" });
    }
    throw new ApiError("Can't reach CampusPilot. Check your connection and that the server is running.", {
      kind: "network",
    });
  }
  clearTimeout(timer);

  let data = null;
  const text = await response.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }

  if (!response.ok) {
    const kind = kindForStatus(response.status);
    let message;
    if (kind === "rate_limited") {
      message = "You're going a little fast. Please wait a moment and try again.";
    } else if (response.status >= 500) {
      message = typeof data?.detail === "string" ? data.detail : "Something went wrong on our side. Please try again.";
    } else {
      message = detailToMessage(data?.detail) || "The request could not be completed.";
    }
    throw new ApiError(message, { status: response.status, kind });
  }
  return data;
}

export const getAgentStatus = () => request("/api/agent/status");
export const planAgent = (goal) => request("/api/agent/plan", { method: "POST", body: { goal } });
export const runAgent = (goal) => request("/api/agent/run", { method: "POST", body: { goal } });

export const approveAgent = (approvalId, payloadHash) =>
  request("/api/agent/approve", {
    method: "POST",
    body: payloadHash ? { approval_id: approvalId, payload_hash: payloadHash } : { approval_id: approvalId },
  });

export const rejectAgent = (approvalId) =>
  request("/api/agent/reject", { method: "POST", body: { approval_id: approvalId } });

export const getWorkflows = (limit = 10) => request(`/api/agent/workflows?limit=${limit}`);
export const getAuditLog = (limit = 40) => request(`/api/agent/audit?limit=${limit}`);

export const getStudentPreferences = () => request("/api/agent/memory");
export const getMemorySummary = () => request("/api/agent/memory/summary");
export const proposePreferenceUpdate = (updates) =>
  request("/api/agent/memory/propose", { method: "POST", body: { updates } });

/** Apply an edit the student submitted directly in the preferences form. */
export const savePreferences = (updates) =>
  request("/api/agent/memory/update", { method: "POST", body: { updates, approved: true } });

export const resetPreferences = () =>
  request("/api/agent/memory/reset", { method: "POST", body: { confirm: true } });
