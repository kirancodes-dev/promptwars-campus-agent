export const FLAGSHIP_RESULT_WAITING = {
  goal: "Organize my preparation for tomorrow.",
  status: "waiting_approval",
  requires_approval: true,
  approval_id: "appr_batch1",
  planner_mode: "deterministic",
  planner_note: null,
  plan: {
    goal: "Organize my preparation for tomorrow.",
    summary: "Study plan for tomorrow: DBMS 9:00 AM–11:00 AM. (Influenced by: Scheduled DBMS during your preferred evening study window.)",
    tasks: [],
    requires_approval: true,
  },
  results: [],
  approval_requests: [
    {
      approval_id: "appr_a1",
      action: "Add 'DBMS Study Block' to your schedule (Sat 10 Oct, 9:00 AM – 11:00 AM)",
      tool_name: "create_schedule",
      parameters: { title: "DBMS Study Block" },
      status: "pending",
      payload_hash: "hash123",
      expires_at: new Date(Date.now() + 14 * 60000).toISOString(),
    },
    {
      approval_id: "appr_a2",
      action: "Create task 'DBMS Preparation' (priority: high)",
      tool_name: "create_task",
      parameters: { title: "DBMS Preparation" },
      status: "pending",
      payload_hash: "hash123",
    },
  ],
  workflow: {
    workflow_id: "wf_1",
    goal: "Organize my preparation for tomorrow.",
    status: "waiting_approval",
    next_action: "Review the 2 proposed change(s) and approve or reject them. Nothing has been changed yet.",
    steps: [
      { step_id: "s1", order: 0, title: "Check existing schedule", kind: "read", tool: "get_schedule", parameters: {}, status: "completed", result: { events: [] }, verification: {} },
      { step_id: "s2", order: 1, title: "Create DBMS study block", kind: "write", tool: "create_schedule", parameters: { title: "DBMS Study Block" }, requires_approval: true, status: "waiting_approval", verification: {} },
      { step_id: "s3", order: 2, title: "Create corresponding tasks", kind: "write", tool: "create_task", parameters: { title: "DBMS Preparation" }, requires_approval: true, status: "waiting_approval", verification: {} },
    ],
  },
};

export const FLAGSHIP_RESULT_DONE = {
  ...FLAGSHIP_RESULT_WAITING,
  status: "completed",
  workflow: {
    ...FLAGSHIP_RESULT_WAITING.workflow,
    status: "completed",
    next_action: "All steps finished and every change was read back and verified.",
    steps: FLAGSHIP_RESULT_WAITING.workflow.steps.map((s) =>
      s.kind === "write" ? { ...s, status: "completed", verification: { checked: true, passed: true } } : s,
    ),
  },
};

export const PREFS = {
  preferences: {
    preferred_study_start: "09:00",
    preferred_study_end: "21:00",
    preferred_session_minutes: 60,
    preferred_break_minutes: 10,
    preferred_study_days: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    preferred_subjects: [],
    subject_time_preferences: {},
    planning_notes: [],
  },
  summary: "Study Window: 09:00 - 21:00",
  durable: false,
  storage_message: "Demo storage: data is kept in server memory only and is lost when the server restarts.",
};

export const STATUS = {
  status: "healthy",
  ai_available: false,
  ai_message: "AI planning is not configured.",
  persistence_mode: "memory",
  persistence_durable: false,
  persistence_message: "Demo storage",
  identity_mode: "session",
  identity_message: "Private anonymous session",
};
