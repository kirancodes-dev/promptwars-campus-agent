import { describe, expect, it, vi } from "vitest";
import { ApiError, request } from "../api/agent";
import { changedItems, minutesUntil, splitInfluences, stepCounts, validateGoal } from "../lib/format";
import { toUpdates, validatePreferenceForm } from "../lib/preferences";
import { FLAGSHIP_RESULT_DONE } from "./fixtures";

describe("format helpers", () => {
  it("validates goals", () => {
    expect(validateGoal("")).toMatch(/Describe/);
    expect(validateGoal("  ")).toMatch(/Describe/);
    expect(validateGoal("ab")).toMatch(/more detail/);
    expect(validateGoal("x".repeat(1001))).toMatch(/under 1,000/);
    expect(validateGoal("Plan my DBMS study")).toBeNull();
  });

  it("splits preference influences out of the summary", () => {
    const { text, influences } = splitInfluences("Plan text. (Influenced by: A thing; Another)");
    expect(text).toBe("Plan text.");
    expect(influences).toEqual(["A thing", "Another"]);
    expect(splitInfluences("No influences").influences).toEqual([]);
  });

  it("only reports completed writes as saved", () => {
    const items = changedItems(FLAGSHIP_RESULT_DONE.workflow);
    expect(items.map((i) => i.title)).toEqual(["DBMS Study Block", "DBMS Preparation"]);
    expect(items.every((i) => i.verified)).toBe(true);
    const pending = changedItems({ steps: [{ kind: "write", status: "waiting_approval", tool: "create_task", parameters: { title: "x" } }] });
    expect(pending).toEqual([]);
  });

  it("counts step outcomes for tool steps only", () => {
    const counts = stepCounts({ steps: [{ tool: "a", status: "failed" }, { tool: null, status: "completed" }, { tool: "b", status: "completed" }] });
    expect(counts.failed).toBe(1);
    expect(counts.completed).toBe(1);
  });

  it("computes minutes until expiry", () => {
    const now = Date.parse("2026-10-09T10:00:00Z");
    expect(minutesUntil("2026-10-09T10:15:00Z", now)).toBe(15);
    expect(minutesUntil("2026-10-09T09:00:00Z", now)).toBe(0);
  });
});

describe("preference form", () => {
  const base = {
    preferred_study_start: "09:00",
    preferred_study_end: "21:00",
    preferred_session_minutes: "60",
    preferred_break_minutes: "10",
    preferred_study_days: ["Monday"],
    preferred_subjects: "DBMS, DAA ,",
    timings: [{ subject: "DBMS", when: "evening" }],
    planning_notes: "a\n\n b ",
  };

  it("accepts valid input and normalizes it", () => {
    expect(validatePreferenceForm(base)).toEqual({});
    expect(toUpdates(base)).toMatchObject({
      preferred_session_minutes: 60,
      preferred_subjects: ["DBMS", "DAA"],
      subject_time_preferences: { DBMS: "evening" },
      planning_notes: ["a", "b"],
    });
  });

  it("rejects invalid input", () => {
    const errs = validatePreferenceForm({
      ...base,
      preferred_study_end: "08:00",
      preferred_session_minutes: "5",
      preferred_break_minutes: "500",
      preferred_study_days: [],
      timings: [{ subject: " ", when: "evening" }],
    });
    expect(Object.keys(errs).sort()).toEqual(
      ["preferred_break_minutes", "preferred_session_minutes", "preferred_study_days", "preferred_study_end", "timings"].sort(),
    );
  });
});

describe("api client", () => {
  const respond = (status, body) =>
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(body === undefined ? "" : JSON.stringify(body), { status }));

  it("uses same-origin credentials and relative URLs", async () => {
    const spy = respond(200, { ok: true });
    await request("/api/agent/status");
    expect(spy).toHaveBeenCalledWith("/api/agent/status", expect.objectContaining({ credentials: "same-origin" }));
  });

  it("maps HTTP errors to friendly typed errors", async () => {
    respond(410, { detail: "Approval request 'x' has expired." });
    await expect(request("/x")).rejects.toMatchObject({ kind: "expired", status: 410 });

    respond(429, { detail: "Too many" });
    await expect(request("/x")).rejects.toMatchObject({ kind: "rate_limited", message: expect.stringMatching(/wait a moment/) });

    respond(422, { detail: [{ loc: ["body", "goal"], msg: "too long", type: "string_too_long" }] });
    await expect(request("/x")).rejects.toMatchObject({ kind: "validation", message: expect.stringMatching(/1,000/) });

    respond(500, undefined);
    await expect(request("/x")).rejects.toMatchObject({ kind: "server" });
  });

  it("reports network failures without leaking internals", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    const err = await request("/x").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.kind).toBe("network");
    expect(err.message).toMatch(/Can't reach CampusPilot/);
  });
});

describe("more formatting helpers", () => {
  it("formats relative times and ranges", async () => {
    const { relativeTime, formatRange, formatDateTime, toDisplaySteps } = await import("../lib/format");
    const now = Date.parse("2026-10-09T12:00:00");
    expect(relativeTime("2026-10-09T11:59:40", now)).toBe("just now");
    expect(relativeTime("2026-10-09T11:30:00", now)).toBe("30 min ago");
    expect(relativeTime("2026-10-09T09:00:00", now)).toBe("3 h ago");
    expect(relativeTime("not a date", now)).toBe("");
    expect(formatRange("2026-10-10T09:00:00", "2026-10-10T11:00:00")).toMatch(/9:00.*11:00/);
    expect(formatRange(null, "x")).toBe("");
    expect(formatDateTime("not a date")).toBe("not a date");
    const fromPlan = toDisplaySteps({ plan: { tasks: [
      { id: "a", title: "Read", tool: "get_tasks", parameters: {} },
      { id: "b", title: "Write", tool: "create_task", requires_approval: true, parameters: {} },
      { id: "c", title: "Think", tool: null, parameters: {} },
    ] } });
    expect(fromPlan.map((s) => s.kind)).toEqual(["read", "write", "reasoning"]);
    expect(toDisplaySteps(null)).toEqual([]);
  });
});
