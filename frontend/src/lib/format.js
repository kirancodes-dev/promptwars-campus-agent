/** Presentation helpers shared by the UI. Pure functions, unit-tested. */

export const STEP_STATUS = {
  planned: { label: "Planned", tone: "neutral" },
  waiting_approval: { label: "Needs your approval", tone: "warning" },
  running: { label: "Running", tone: "info" },
  completed: { label: "Done", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
  blocked: { label: "Blocked", tone: "danger" },
  skipped: { label: "Skipped", tone: "neutral" },
  rejected: { label: "Rejected", tone: "neutral" },
};

export const WORKFLOW_STATUS = {
  waiting_approval: {
    label: "Waiting for your approval",
    tone: "warning",
    headline: "Review the plan before anything changes",
  },
  completed: { label: "Completed", tone: "success", headline: "All done" },
  partially_completed: { label: "Partly completed", tone: "warning", headline: "Some steps did not finish" },
  failed: { label: "Failed", tone: "danger", headline: "This plan could not be completed" },
  rejected: { label: "Rejected", tone: "neutral", headline: "You rejected these changes" },
  needs_clarification: { label: "Needs a detail", tone: "info", headline: "One detail needed" },
  running: { label: "Running", tone: "info", headline: "Working on it" },
  planned: { label: "Planned", tone: "neutral", headline: "Plan ready" },
};

export const KIND_LABEL = {
  read: "Reads your data",
  write: "Changes your data",
  reasoning: "Planning step",
};

const TOOL_LABEL = {
  get_tasks: "Task list",
  create_task: "Tasks",
  update_task: "Tasks",
  delete_task: "Tasks",
  get_schedule: "Schedule",
  check_schedule_conflict: "Conflict check",
  create_schedule: "Schedule",
  update_schedule: "Schedule",
  delete_schedule: "Schedule",
  get_notes: "Notes",
  search_notes: "Notes search",
  create_note: "Notes",
  update_note: "Notes",
  delete_note: "Notes",
  get_student_preferences: "Preferences",
  update_student_preferences: "Preferences",
  reset_student_preferences: "Preferences",
};

export function toolLabel(tool) {
  return TOOL_LABEL[tool] || tool || "";
}

export function formatTime(value) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export function formatDateTime(value) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

export function formatRange(start, end) {
  if (!start || !end) return "";
  const s = new Date(start);
  const e = new Date(end);
  if (Number.isNaN(s.getTime()) || Number.isNaN(e.getTime())) return "";
  const day = s.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
  return `${day}, ${formatTime(start)} – ${formatTime(end)}`;
}

export function relativeTime(value, now = Date.now()) {
  const d = new Date(value).getTime();
  if (Number.isNaN(d)) return "";
  const diff = Math.round((now - d) / 1000);
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`;
  return new Date(value).toLocaleDateString([], { day: "numeric", month: "short" });
}

export function minutesUntil(value, now = Date.now()) {
  const d = new Date(value).getTime();
  if (Number.isNaN(d)) return null;
  return Math.max(0, Math.round((d - now) / 60000));
}

/** Split "Plan text. (Influenced by: a; b)" into the plain summary and the influence list. */
export function splitInfluences(summary = "") {
  const match = summary.match(/\(Influenced by: (.+)\)\s*$/);
  if (!match) return { text: summary, influences: [] };
  return {
    text: summary.slice(0, match.index).trim(),
    influences: match[1].split(";").map((s) => s.trim()).filter(Boolean),
  };
}

/** Human summary of what a completed workflow actually changed (only verified, completed writes). */
export function changedItems(workflow) {
  if (!workflow?.steps) return [];
  return workflow.steps
    .filter((s) => s.kind === "write" && s.status === "completed")
    .map((s) => {
      const p = s.parameters || {};
      if (s.tool === "create_schedule") return { type: "event", title: p.title, detail: formatRange(p.start_time, p.end_time), verified: s.verification?.passed === true };
      if (s.tool === "create_task") return { type: "task", title: p.title, detail: p.priority ? `${p.priority} priority` : "", verified: s.verification?.passed === true };
      if (s.tool?.includes("preferences")) return { type: "preferences", title: s.title, detail: "", verified: s.verification?.passed === true };
      return { type: "other", title: s.title, detail: "", verified: s.verification?.passed === true };
    });
}

export function stepCounts(workflow) {
  const counts = { completed: 0, failed: 0, blocked: 0, waiting_approval: 0, skipped: 0, rejected: 0 };
  for (const s of workflow?.steps || []) {
    if (!s.tool) continue;
    if (counts[s.status] !== undefined) counts[s.status] += 1;
  }
  return counts;
}

export const MAX_GOAL_CHARS = 1000;

export function validateGoal(goal) {
  const clean = (goal || "").trim();
  if (!clean) return "Describe what you want to get done first.";
  if (clean.length < 3) return "Add a little more detail so CampusPilot can plan it.";
  if (clean.length > MAX_GOAL_CHARS) return `Please keep your goal under ${MAX_GOAL_CHARS.toLocaleString()} characters.`;
  return null;
}

/** Builds display steps from the workflow record, falling back to raw plan tasks. */
export function toDisplaySteps(executionResult) {
  const wf = executionResult?.workflow;
  if (wf?.steps?.length) return wf.steps;
  return (executionResult?.plan?.tasks || []).map((t, i) => ({
    step_id: t.id,
    order: i,
    title: t.title,
    description: t.description,
    kind: !t.tool ? "reasoning" : t.requires_approval ? "write" : "read",
    tool: t.tool,
    parameters: t.parameters,
    depends_on: t.depends_on,
    status: "planned",
  }));
}
