import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FLAGSHIP_RESULT_DONE, FLAGSHIP_RESULT_WAITING, PREFS, STATUS } from "./fixtures";

vi.mock("../api/agent", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    getAgentStatus: vi.fn(),
    runAgent: vi.fn(),
    approveAgent: vi.fn(),
    rejectAgent: vi.fn(),
    getWorkflows: vi.fn(),
    getAuditLog: vi.fn(),
    getStudentPreferences: vi.fn(),
    savePreferences: vi.fn(),
    resetPreferences: vi.fn(),
  };
});

import * as api from "../api/agent";
import App from "../App";

beforeEach(() => {
  vi.mocked(api.getAgentStatus).mockResolvedValue(STATUS);
  vi.mocked(api.getWorkflows).mockResolvedValue([]);
  vi.mocked(api.getAuditLog).mockResolvedValue([]);
  vi.mocked(api.getStudentPreferences).mockResolvedValue(PREFS);
  vi.mocked(api.runAgent).mockReset();
  vi.mocked(api.approveAgent).mockReset();
  vi.mocked(api.rejectAgent).mockReset();
  vi.mocked(api.savePreferences).mockReset();
  vi.mocked(api.resetPreferences).mockReset();
});

async function renderApp() {
  const result = render(<App />);
  await screen.findByRole("heading", { level: 1 });
  await waitFor(() => {
    expect(api.getAgentStatus).toHaveBeenCalled();
    expect(api.getStudentPreferences).toHaveBeenCalled();
  });
  return result;
}

async function planFlagship(user) {
  vi.mocked(api.runAgent).mockResolvedValue(FLAGSHIP_RESULT_WAITING);
  await renderApp();
  await user.click(screen.getByRole("button", { name: /Plan tomorrow's study \(demo\)/ }));
  await user.click(screen.getByRole("button", { name: /Plan it/ }));
  return screen.findByRole("heading", { name: /Review these 2 changes/ });
}

describe("goal entry", () => {
  it("validates an empty goal without calling the API", async () => {
    const user = userEvent.setup();
    await renderApp();
    await user.click(screen.getByRole("button", { name: /Plan it/ }));
    expect(await screen.findByText(/Describe what you want to get done/)).toBeTruthy();
    expect(api.runAgent).not.toHaveBeenCalled();
  });

  it("example goals fill the box but do not submit", async () => {
    const user = userEvent.setup();
    await renderApp();
    await user.click(screen.getByRole("button", { name: /Plan tomorrow's study \(demo\)/ }));
    expect(screen.getByRole("textbox", { name: /What do you want to get done/ }).value).toMatch(/2 hours of DBMS/);
    expect(api.runAgent).not.toHaveBeenCalled();
  });

  it("shows an actionable error when the API fails", async () => {
    const user = userEvent.setup();
    vi.mocked(api.runAgent).mockRejectedValue(new api.ApiError("Can't reach CampusPilot.", { kind: "network" }));
    await renderApp();
    await user.type(screen.getByRole("textbox", { name: /What do you want to get done/ }), "Show my tasks");
    await user.click(screen.getByRole("button", { name: /Plan it/ }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/Can't reach CampusPilot/);
    expect(within(alert).getByRole("button", { name: /Try again/ })).toBeTruthy();
    expect(screen.getByRole("textbox", { name: /What do you want to get done/ }).value).toBe("Show my tasks");
  });
});

describe("plan and approval", () => {
  it("renders the plan, preference influence and every proposed change", async () => {
    const user = userEvent.setup();
    await planFlagship(user);
    expect(screen.getByText(/Add 'DBMS Study Block' to your schedule/)).toBeTruthy();
    expect(screen.getByText(/Create task 'DBMS Preparation'/)).toBeTruthy();
    expect(screen.getByText(/Your saved preferences shaped this plan/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: /The plan · 3 steps/ })).toBeTruthy();
    expect(screen.getAllByText("Needs your approval").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/What was saved/)).toBeNull();
  });

  it("approves once (no double submit) and shows verified results", async () => {
    const user = userEvent.setup();
    let resolve;
    vi.mocked(api.approveAgent).mockReturnValue(new Promise((r) => (resolve = r)));
    await planFlagship(user);
    const approve = screen.getByRole("button", { name: /Approve 2 changes/ });
    await user.click(approve);
    await user.click(approve);
    expect(api.approveAgent).toHaveBeenCalledTimes(1);
    expect(api.approveAgent).toHaveBeenCalledWith("appr_batch1", "hash123");
    await act(async () => resolve({ success: true, status: "approved", execution_result: FLAGSHIP_RESULT_DONE }));
    expect(await screen.findByText(/What was saved/)).toBeTruthy();
    expect(screen.getAllByText(/read back and verified$/).length).toBe(2);
    expect(screen.queryByRole("button", { name: /Approve/ })).toBeNull();
  });

  it("rejection keeps actions visibly rejected", async () => {
    const user = userEvent.setup();
    vi.mocked(api.rejectAgent).mockResolvedValue({
      status: "rejected",
      execution_result: {
        ...FLAGSHIP_RESULT_WAITING,
        status: "rejected",
        workflow: {
          ...FLAGSHIP_RESULT_WAITING.workflow,
          status: "rejected",
          next_action: "You rejected the proposed changes. Nothing was changed.",
          steps: FLAGSHIP_RESULT_WAITING.workflow.steps.map((s) => (s.kind === "write" ? { ...s, status: "rejected" } : s)),
        },
      },
    });
    await planFlagship(user);
    await user.click(screen.getByRole("button", { name: /Reject all/ }));
    expect(await screen.findByText(/You rejected these changes/)).toBeTruthy();
    expect(screen.getAllByText("Rejected").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/What was saved/)).toBeNull();
  });

  it("explains an expired approval and offers to plan again", async () => {
    const user = userEvent.setup();
    vi.mocked(api.approveAgent).mockRejectedValue(new api.ApiError("expired", { kind: "expired", status: 410 }));
    await planFlagship(user);
    await user.click(screen.getByRole("button", { name: /Approve 2 changes/ }));
    expect(await screen.findByText(/This approval expired, so nothing was saved/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Plan again/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Approve 2 changes/ })).toBeNull();
  });
});

describe("explanations", () => {
  it("shows what the planner understood, with sources and assumptions", async () => {
    const user = userEvent.setup();
    await planFlagship(user);
    const panel = screen.getByText("What I understood").closest("details");
    expect(within(panel).getByText("DBMS study time")).toBeTruthy();
    expect(within(panel).getByText("you said")).toBeTruthy();
    expect(within(panel).getByText("saved preference")).toBeTruthy();
    expect(within(panel).getByText("default")).toBeTruthy();
    expect(within(panel).getByText(/kept 1 hour free/)).toBeTruthy();
    expect(screen.getByText("Built-in planner")).toBeTruthy();
  });

  it("labels an AI fallback honestly", async () => {
    const user = userEvent.setup();
    vi.mocked(api.runAgent).mockResolvedValue({
      ...FLAGSHIP_RESULT_WAITING,
      planner_mode: "deterministic_fallback",
      planner_note: "AI planning is unavailable right now, so CampusPilot's built-in planner was used instead.",
    });
    await renderApp();
    await user.click(screen.getByRole("button", { name: /Plan tomorrow's study \(demo\)/ }));
    await user.click(screen.getByRole("button", { name: /Plan it/ }));
    expect(await screen.findByText("Built-in planner (AI fallback)")).toBeTruthy();
    expect(screen.getByText(/AI planning is unavailable right now/)).toBeTruthy();
  });

  it("has exactly one level-one heading", async () => {
    await renderApp();
    expect(screen.getAllByRole("heading", { level: 1 }).map((h) => h.textContent)).toEqual(["CampusPilot AI"]);
  });
});

describe("preferences", () => {
  it("validates edits client-side before saving", async () => {
    const user = userEvent.setup();
    await renderApp();
    await user.click(await screen.findByRole("button", { name: /^Edit$/ }));
    const end = screen.getByLabelText("Latest end");
    await user.clear(end);
    await user.type(end, "08:00");
    await user.click(screen.getByRole("button", { name: /Save preferences/ }));
    expect(await screen.findByText(/End time must be after the start time/)).toBeTruthy();
    expect(api.savePreferences).not.toHaveBeenCalled();
  });

  it("requires explicit confirmation before resetting", async () => {
    const user = userEvent.setup();
    vi.mocked(api.resetPreferences).mockResolvedValue({ ...PREFS, verified: true });
    await renderApp();
    await user.click(await screen.findByRole("button", { name: /Reset to defaults/ }));
    expect(api.resetPreferences).not.toHaveBeenCalled();
    const dialog = screen.getByRole("alertdialog");
    expect(dialog.textContent).toMatch(/cannot be undone/);
    await user.click(within(dialog).getByRole("button", { name: /Keep my preferences/ }));
    expect(api.resetPreferences).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /Reset to defaults/ }));
    await user.click(screen.getByRole("button", { name: /Yes, reset preferences/ }));
    await waitFor(() => expect(api.resetPreferences).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/reset to defaults and verified/)).toBeTruthy();
  });
});

describe("navigation and status", () => {
  it("bottom navigation switches sections", async () => {
    const user = userEvent.setup();
    await renderApp();
    const nav = screen.getByRole("navigation", { name: "Sections" });
    await user.click(within(nav).getByRole("button", { name: /Activity/ }));
    expect(within(nav).getByRole("button", { name: /Activity/ }).getAttribute("aria-current")).toBe("page");
  });

  it("status panel explains demo storage honestly", async () => {
    const user = userEvent.setup();
    await renderApp();
    await user.click(await screen.findByRole("button", { name: /show system status/ }));
    expect(screen.getByText("Built-in planner")).toBeTruthy();
    expect(screen.getByText("Temporary")).toBeTruthy();
  });
});

describe("history, read results, saving and offline states", () => {
  it("shows workflow history and the audit log", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getWorkflows).mockResolvedValue([{ ...FLAGSHIP_RESULT_DONE.workflow, updated_at: new Date().toISOString() }]);
    vi.mocked(api.getAuditLog).mockResolvedValue([
      { id: "a1", event_type: "approval_granted", timestamp: new Date().toISOString(), tool: null, error_summary: null },
      { id: "a2", event_type: "tool_failed", timestamp: new Date().toISOString(), tool: "create_task", error_summary: "storage down" },
    ]);
    await renderApp();
    const activity = await screen.findByRole("heading", { name: "Activity" });
    const card = activity.closest("section");
    expect(await within(card).findByText(/Organize my preparation/)).toBeTruthy();
    expect(within(card).getByText("3/3 actions done")).toBeTruthy();
    await user.click(within(card).getByText(/Detailed audit log \(2\)/));
    expect(within(card).getByText("You approved changes")).toBeTruthy();
    expect(within(card).getByText("storage down")).toBeTruthy();
  });

  it("shows the data a read-only goal found", async () => {
    const user = userEvent.setup();
    vi.mocked(api.runAgent).mockResolvedValue({
      goal: "Show my tasks", status: "completed", plan: { goal: "Show my tasks", summary: "Plan to retrieve user tasks", tasks: [] },
      results: [], approval_requests: [], planner_mode: "deterministic",
      workflow: { workflow_id: "w2", status: "completed", next_action: "All steps finished. No data was changed.", steps: [
        { step_id: "r1", title: "Retrieve tasks", kind: "read", tool: "get_tasks", status: "completed", verification: {},
          result: { tasks: [{ title: "Submit DAA assignment", status: "pending", priority: "high" }] } },
      ] },
    });
    await renderApp();
    await user.type(screen.getByRole("textbox", { name: /What do you want to get done/ }), "Show my tasks");
    await user.click(screen.getByRole("button", { name: /Plan it/ }));
    expect(await screen.findByText("Submit DAA assignment")).toBeTruthy();
    expect(screen.getByText("pending · high priority")).toBeTruthy();
    expect(screen.queryByText(/What was saved/)).toBeNull();
  });

  it("saves preferences and reports verified, temporary storage honestly", async () => {
    const user = userEvent.setup();
    vi.mocked(api.savePreferences).mockResolvedValue({ ...PREFS, durable: false, verified: true });
    await renderApp();
    await user.click(await screen.findByRole("button", { name: /^Edit$/ }));
    await user.click(screen.getByRole("button", { name: /Save preferences/ }));
    expect(await screen.findByText(/Saved and verified in temporary demo storage/)).toBeTruthy();
    expect(api.savePreferences).toHaveBeenCalledTimes(1);
  });

  it("explains when the server cannot be reached", async () => {
    vi.mocked(api.getAgentStatus).mockRejectedValue(new api.ApiError("down", { kind: "network" }));
    render(<App />);
    expect(await screen.findByText("Can't reach the CampusPilot server")).toBeTruthy();
  });
});
