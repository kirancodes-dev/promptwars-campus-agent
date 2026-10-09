export const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
export const TIMINGS = ["morning", "afternoon", "evening", "night"];

export function toForm(p) {
  return {
    preferred_study_start: p.preferred_study_start,
    preferred_study_end: p.preferred_study_end,
    preferred_session_minutes: String(p.preferred_session_minutes),
    preferred_break_minutes: String(p.preferred_break_minutes),
    preferred_study_days: [...(p.preferred_study_days || [])],
    preferred_subjects: (p.preferred_subjects || []).join(", "),
    timings: Object.entries(p.subject_time_preferences || {}).map(([subject, when]) => ({ subject, when })),
    planning_notes: (p.planning_notes || []).join("\n"),
  };
}

export function validatePreferenceForm(f) {
  const errors = {};
  if (!/^\d{2}:\d{2}$/.test(f.preferred_study_start)) errors.preferred_study_start = "Choose a start time.";
  if (!/^\d{2}:\d{2}$/.test(f.preferred_study_end)) errors.preferred_study_end = "Choose an end time.";
  if (!errors.preferred_study_start && !errors.preferred_study_end && f.preferred_study_end <= f.preferred_study_start) {
    errors.preferred_study_end = "End time must be after the start time.";
  }
  const session = Number(f.preferred_session_minutes);
  if (!Number.isInteger(session) || session < 15 || session > 360) errors.preferred_session_minutes = "Use 15–360 minutes.";
  const brk = Number(f.preferred_break_minutes);
  if (!Number.isInteger(brk) || brk < 0 || brk > 120) errors.preferred_break_minutes = "Use 0–120 minutes.";
  if (!f.preferred_study_days.length) errors.preferred_study_days = "Pick at least one day.";
  if (f.timings.some((t) => !t.subject.trim())) errors.timings = "Every timing row needs a subject.";
  return errors;
}

export function toUpdates(f) {
  return {
    preferred_study_start: f.preferred_study_start,
    preferred_study_end: f.preferred_study_end,
    preferred_session_minutes: Number(f.preferred_session_minutes),
    preferred_break_minutes: Number(f.preferred_break_minutes),
    preferred_study_days: f.preferred_study_days,
    preferred_subjects: f.preferred_subjects.split(",").map((s) => s.trim()).filter(Boolean),
    subject_time_preferences: Object.fromEntries(
      f.timings.filter((t) => t.subject.trim()).map((t) => [t.subject.trim(), t.when]),
    ),
    planning_notes: f.planning_notes.split("\n").map((n) => n.trim()).filter(Boolean),
  };
}
