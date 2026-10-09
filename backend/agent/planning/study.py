"""
Study planning: turn a goal plus saved preferences into a read-before-write workflow.

Single-day plans place each requested subject on one day. When the goal names exam dates,
study sessions are spread over the days before each exam, earliest exam first.
Every fact used is reported with its source; every assumption is stated.
"""

from datetime import date, datetime, time, timedelta
from typing import Any

from agent.planning.common import clarification_plan, duration_label, duration_text, fmt_day, fmt_time, new_step_id
from agent.planning.extraction import GoalFacts, parse_goal
from agent.planning.preferences_text import extract_preference_updates
from agent.planning.scheduling import (
    MAX_BLOCKS,
    AllocationError,
    Block,
    Calendar,
    StudyWindow,
    allocate_single_day,
    allocate_until_deadlines,
)
from agent.router import route_tool
from models.agent import AgentPlan, AgentTask, PlanFact, UserGoal
from models.memory import StudentPreferences
from services.identity import current_user_id
from services.memory import MemoryService
from services.persistence import get_persistence

_PRIORITY_RANK = {"high": 0, None: 1, "low": 2}
_DEFAULT_PREFS = StudentPreferences()


class _Context:
    """Everything one planning call needs, gathered once."""

    def __init__(self, goal: UserGoal, pref: StudentPreferences | None, stated_pref_fields: set[str], now: datetime):
        self.goal = goal
        self.now = now
        self.today = now.date()
        self.pref = pref or StudentPreferences()
        self.stated = stated_pref_fields
        self.facts: GoalFacts = parse_goal(goal.goal, self.today)
        self.understanding: list[PlanFact] = []
        self.horizon: tuple[datetime, datetime] | None = None
        self.assumptions: list[str] = []
        try:
            start = time.fromisoformat(self.pref.preferred_study_start)
            end = time.fromisoformat(self.pref.preferred_study_end)
        except (TypeError, ValueError):
            start, end = time(9, 0), time(21, 0)
        self.window = StudyWindow(start, end, int(self.pref.preferred_break_minutes or 0), tuple(self.pref.preferred_study_days))

    def source(self, field: str) -> str:
        if field in self.stated:
            return "you said"
        return "saved preference" if getattr(self.pref, field) != getattr(_DEFAULT_PREFS, field) else "default"

    def fact(self, label: str, value: str, source: str) -> None:
        self.understanding.append(PlanFact(label=label, value=value, source=source))

    def window_text(self) -> str:
        return f"{self.window.start.strftime('%H:%M')}–{self.window.end.strftime('%H:%M')}"

    def day_text(self, day: date) -> str:
        if day == self.today:
            return "today"
        if day == self.today + timedelta(days=1):
            return "tomorrow"
        return f"on {fmt_day(day)}"

    def clarify(self, title: str, question: str) -> AgentPlan:
        return clarification_plan(self.goal, title, question, understanding=self.understanding, assumptions=self.assumptions)


def _load_preferences() -> StudentPreferences | None:
    try:
        return MemoryService().get_preferences()
    except Exception:
        return None


def _existing_busy(ctx: "_Context", first_day: date, last_day: date) -> list[tuple[datetime, datetime, str]]:
    """Events overlapping the planning horizon (a range read, not the whole schedule)."""
    ctx.horizon = (datetime.combine(first_day, time(0, 0)), datetime.combine(last_day + timedelta(days=1), time(0, 0)))
    try:
        events = get_persistence().get_events_overlapping(*ctx.horizon, user_id=current_user_id())
    except Exception:
        ctx.assumptions.append(
            "I couldn't read your saved schedule while planning. The 'Check existing schedule' step must succeed "
            "before anything is saved, so nothing will overwrite your events."
        )
        return []
    return [(e.start_time, e.end_time, e.title) for e in events if e.status != "cancelled"]


def _common_facts(ctx: _Context, subjects: list[str], multi_day: bool) -> None:
    f = ctx.facts
    for subject, minutes in ((r.subject, r.minutes) for r in f.requirements):
        ctx.fact(f"{subject} study time", duration_text(minutes), "you said")
    for subject, day in f.exams.items():
        ctx.fact(f"{subject} exam", fmt_day(day), "you said")
    for subject, level in f.priorities.items():
        ctx.fact(f"{subject} priority", level, "you said")
    for subject, t in f.explicit_times.items():
        ctx.fact(f"{subject} start time", fmt_time(datetime.combine(ctx.today, t)), "you said")
    ctx.fact("Study window", ctx.window_text(), ctx.source("preferred_study_start"))
    ctx.fact("Break between sessions", f"{ctx.window.break_minutes} min", ctx.source("preferred_break_minutes"))
    if multi_day:
        ctx.fact("Session length", f"{ctx.pref.preferred_session_minutes} min", ctx.source("preferred_session_minutes"))
        if len(ctx.window.study_days) < 7:
            ctx.fact("Study days", ", ".join(d[:3] for d in ctx.window.study_days), ctx.source("preferred_study_days"))
    for subject in subjects:
        timing = ctx.pref.subject_time_preferences.get(subject)
        if timing:
            ctx.fact(f"{subject} time of day", timing, "you said" if "subject_time_preferences" in ctx.stated else "saved preference")


def _error_question(ctx: _Context, err: AllocationError) -> tuple[str, str]:
    if err.kind == "conflict":
        start = err.requested_start
        return "Schedule conflict clarification", (
            f"Schedule conflict detected: Your requested {err.subject} session at {fmt_time(start)} "
            f"conflicts with '{err.clash}'. How would you like to proceed? "
            f"Would you like to reschedule '{err.clash}' or choose another time for {err.subject}?"
        )
    if err.kind == "no_slot":
        day = err.days[0]
        return "Schedule clarification needed", (
            f"No {duration_label(err.minutes)} slot is available {ctx.day_text(day)} for {err.subject} within your study window "
            f"({ctx.window_text()}); only {duration_text(err.free_minutes) if err.free_minutes else 'no time'} is free that day "
            f"after existing commitments. "
            + ("Would you like me to use two 1-hour slots instead?" if err.minutes == 120
               else "Would you like me to split it into shorter sessions or choose another day?")
        )
    if err.kind == "capacity":
        return "Not enough time before the exam", (
            f"{err.subject} needs {duration_text(err.minutes)} before its exam on {fmt_day(err.deadline)}, but only "
            f"{duration_text(err.free_minutes) if err.free_minutes else 'no time'} is free in your study window "
            f"({ctx.window_text()}) across {len(err.days)} study day(s) before it. "
            f"Would you like to reduce the hours, widen your study window, or allow more study days?"
        )
    if err.kind == "no_days":
        return "No study days before the exam", (
            f"There are no study days left before your {err.subject} exam on {fmt_day(err.deadline)} "
            f"(it is too soon, or your preferred study days exclude the days before it). "
            f"Should I schedule it today, or did you mean a later exam date?"
        )
    return "Too many sessions", (
        f"That would need {err.blocks_needed} separate study sessions, and I schedule at most {MAX_BLOCKS} at once. "
        f"Try a longer session length in your preferences, or plan one exam at a time."
    )


def _read_steps(ctx: _Context, blocks: list[Block], meeting: tuple[datetime, datetime] | None, multi_day: bool,
                first_depends_on: list[str]) -> list[AgentTask]:
    """Understand -> read schedule -> check conflicts -> choose slots (no data changes)."""
    f = ctx.facts
    requested = "; ".join(f"{duration_text(r.minutes)} of {r.subject}" for r in f.requirements) or "your subjects"
    exams = "; ".join(f"{s} exam {fmt_day(d)}" for s, d in sorted(f.exams.items(), key=lambda x: x[1]))
    meeting_text = f"; project meeting at {fmt_time(meeting[0])} {ctx.day_text(meeting[0].date())}" if meeting else ""
    understand = AgentTask(
        id=new_step_id(), title="Understand study requirements",
        description=f"Requested: {requested}{('; ' + exams) if exams else ''}{meeting_text}.",
        depends_on=list(first_depends_on),
    )
    read = route_tool("get_schedule", {"start_time": ctx.horizon[0], "end_time": ctx.horizon[1]} if ctx.horizon else {})
    read_step = AgentTask(
        id=new_step_id(), title="Check existing schedule",
        description="Read your existing schedule so new study blocks never overwrite current commitments.",
        tool=read.tool_name, parameters=read.parameters, depends_on=[understand.id],
    )
    c_start, c_end = meeting if meeting else (blocks[0].start, blocks[0].end)
    check = route_tool("check_schedule_conflict", {"start_time": c_start, "end_time": c_end})
    check_step = AgentTask(
        id=new_step_id(), title="Check schedule conflicts",
        description=(f"Check whether anything already overlaps the {fmt_time(c_start)} meeting (treated as busy time)."
                     if meeting else f"Check the first proposed block ({fmt_time(c_start)} – {fmt_time(c_end)}) for overlaps."),
        tool=check.tool_name, parameters=check.parameters, depends_on=[read_step.id],
    )
    why = "Earliest exam first; sessions spread across the days before each exam. " if multi_day else ""
    choose = AgentTask(
        id=new_step_id(), title="Find available study slots",
        description=why + "Chosen free slots: " + "; ".join(
            f"{b.subject} {fmt_day(b.start) + ' ' if multi_day else ''}{fmt_time(b.start)} – {fmt_time(b.end)}" for b in blocks
        ) + ".",
        depends_on=[read_step.id, check_step.id],
    )
    return [understand, read_step, check_step, choose]


def _schedule_steps(blocks: list[Block], multi_day: bool, after: str) -> list[AgentTask]:
    """One approval-gated create_schedule step per study block."""
    steps = []
    for b in blocks:
        dur = duration_text(b.minutes)
        call = route_tool("create_schedule", {
            "title": f"{b.subject} Study Block", "start_time": b.start, "end_time": b.end,
            "description": f"{dur} focused {b.subject} study block.", "requires_approval": True,
        })
        day = f" ({fmt_day(b.start)})" if multi_day else ""
        steps.append(AgentTask(
            id=new_step_id(), title=f"Create {b.subject} study block{day}",
            description=f"Schedule {dur} of {b.subject} ({fmt_day(b.start) + ', ' if multi_day else ''}{fmt_time(b.start)} – {fmt_time(b.end)}) — {b.reason}.",
            tool=call.tool_name, parameters=call.parameters, requires_approval=True, depends_on=[after],
        ))
    return steps


def _task_step(title: str, step_title: str, description: str, priority: str, depends_on: list[str], detail: str) -> AgentTask:
    call = route_tool("create_task", {"title": title, "description": detail, "priority": priority, "requires_approval": True})
    return AgentTask(id=new_step_id(), title=step_title, description=description, tool=call.tool_name,
                     parameters=call.parameters, requires_approval=True, depends_on=depends_on)


def _task_steps(ctx: _Context, blocks: list[Block], block_steps: list[AgentTask], multi_day: bool) -> list[AgentTask]:
    """To-do items: one per exam subject (multi-day) or one combined task (single day)."""
    f = ctx.facts
    if not multi_day:
        subjects = " & ".join(dict.fromkeys(b.subject for b in blocks))
        priority = "high" if not f.priorities or "high" in f.priorities.values() else "medium"
        detail = "Complete " + ", ".join(f"{b.subject} ({fmt_time(b.start)} – {fmt_time(b.end)})" for b in blocks) + "."
        return [_task_step(f"{subjects} Preparation", "Create corresponding tasks",
                           f"Add a to-do item for {subjects} preparation.", priority, [s.id for s in block_steps], detail)]
    steps = []
    for subject in dict.fromkeys(b.subject for b in blocks):
        mine = [s for s, b in zip(block_steps, blocks) if b.subject == subject]
        deadline = f.exams.get(subject)
        soon = deadline is not None and (deadline - ctx.today).days <= 3
        level = f.priorities.get(subject)
        priority = "high" if level == "high" or soon else ("low" if level == "low" else "medium")
        title = f"Prepare for {subject} exam ({fmt_day(deadline)})" if deadline else f"Study {subject}"
        steps.append(_task_step(title, f"Create {subject} preparation task",
                                f"Add '{title}' ({priority} priority) to your tasks.", priority,
                                [s.id for s in mine], f"{len(mine)} study session(s) scheduled."))
    return steps


def _block_steps(ctx: _Context, blocks: list[Block], meeting: tuple[datetime, datetime] | None, multi_day: bool,
                 first_depends_on: list[str]) -> list[AgentTask]:
    """Read-before-write workflow: reads, then approval-gated schedule blocks and tasks, then a report."""
    reads = _read_steps(ctx, blocks, meeting, multi_day, first_depends_on)
    schedule = _schedule_steps(blocks, multi_day, after=reads[-1].id)
    tasks = _task_steps(ctx, blocks, schedule, multi_day)
    report = AgentTask(id=new_step_id(), title="Report completed schedule",
                       description="Report the verified schedule and tasks back to you.", depends_on=[t.id for t in tasks])
    return [*reads, *schedule, *tasks, report]


def _influences(ctx: _Context) -> str:
    pref = ctx.pref
    if not (pref.subject_time_preferences or pref.planning_notes):
        return ""
    try:
        influences = MemoryService().identify_influencing_preferences(ctx.goal.goal, pref)
    except Exception:
        influences = []
    return f" (Influenced by: {'; '.join(influences)})" if influences else ""


def _single_day(ctx: _Context, requests: list[tuple[str, int]]) -> AgentPlan:
    f = ctx.facts
    if f.target_date is not None:
        day = f.target_date
        ctx.fact("Planning day", fmt_day(day), "you said")
    else:
        day = ctx.today + timedelta(days=1)
        ctx.fact("Planning day", f"{fmt_day(day)} (tomorrow)", "default")
        ctx.assumptions.append("No day was given, so I planned for tomorrow.")
    if day < ctx.today:
        return ctx.clarify("Date clarification", f"{fmt_day(day)} is in the past. Which day should I plan for?")

    calendar = Calendar(_existing_busy(ctx, day, max(day, f.meeting_date or day)), ctx.now, ctx.window)
    meeting = None
    if f.meeting is not None:
        m_day = f.meeting_date or day
        start = datetime.combine(m_day, f.meeting)
        meeting = (start, start + timedelta(hours=1))
        calendar.add(*meeting, "project meeting")
        ctx.fact("Meeting", f"{fmt_time(start)} {ctx.day_text(m_day)}", "you said")
        ctx.assumptions.append("Your meeting length wasn't given, so I kept 1 hour free for it.")

    ordered = sorted(requests, key=lambda r: _PRIORITY_RANK.get(f.priorities.get(r[0])))
    timing = {s: ctx.pref.subject_time_preferences.get(s, "") for s, _ in ordered}
    _common_facts(ctx, [s for s, _ in ordered], multi_day=False)
    blocks, err = allocate_single_day(ordered, day, calendar, f.explicit_times, timing)
    if err:
        return ctx.clarify(*_error_question(ctx, err))

    tasks = _block_steps(ctx, blocks, meeting, multi_day=False, first_depends_on=[])
    summary = f"Study plan for {ctx.day_text(day)}: " + "; ".join(
        f"{b.subject} {fmt_time(b.start)}–{fmt_time(b.end)}" for b in blocks) + "."
    if meeting:
        summary += f" Your {fmt_time(meeting[0])} meeting is kept free."
    if f.priorities:
        summary += " Higher-priority subjects were placed first."
    overrode = any(s in f.explicit_times and ctx.pref.subject_time_preferences.get(s) for s, _ in ordered)
    if overrode:
        summary += " (Note: used your explicitly requested time, overriding a saved timing preference.)"
    else:
        summary += _influences(ctx)
    return AgentPlan(goal=ctx.goal.goal, summary=summary, tasks=tasks, requires_approval=True,
                     understanding=ctx.understanding, assumptions=ctx.assumptions)


def _until_exams(ctx: _Context) -> AgentPlan:
    f = ctx.facts
    minutes_by_subject = {r.subject: r.minutes for r in f.requirements}
    missing = [s for s in f.exams if s not in minutes_by_subject]
    _common_facts(ctx, list(dict.fromkeys([*f.exams, *minutes_by_subject])), multi_day=True)
    if missing:
        listed = " and ".join(f"{s} (exam {fmt_day(f.exams[s])})" for s in missing)
        return ctx.clarify("Study time needed", (
            f"How many hours do you want to study for {listed}? I won't guess study time — "
            f"for example: '4 hours of {missing[0]}'."
        ))
    past = [s for s, d in f.exams.items() if d <= ctx.today]
    if past:
        s = past[0]
        return ctx.clarify("Exam date clarification", (
            f"Your {s} exam date ({fmt_day(f.exams[s])}) is today or already past, so there is no time to schedule study "
            f"before it. Did you mean a later date?"
        ))

    last_exam = max(f.exams.values())
    subjects: list[tuple[str, int, date]] = []
    for index, r in enumerate(f.requirements):
        deadline = f.exams.get(r.subject)
        if deadline is None:
            deadline = last_exam
            ctx.assumptions.append(f"{r.subject} has no exam date, so I spread it before your last exam ({fmt_day(last_exam)}).")
        subjects.append((r.subject, r.minutes, deadline, _PRIORITY_RANK.get(f.priorities.get(r.subject)), index))
    subjects.sort(key=lambda x: (x[2], x[3], x[4]))

    nearest = min(f.exams.values())
    start_day = ctx.today if ("today" in ctx.goal.goal.lower() or (nearest - ctx.today).days <= 1) else ctx.today + timedelta(days=1)
    ctx.fact("Study sessions start", fmt_day(start_day), "you said" if "today" in ctx.goal.goal.lower() else "default")
    if "today" not in ctx.goal.goal.lower():
        ctx.assumptions.append(
            "Your first exam is tomorrow, so study starts today (from now)." if start_day == ctx.today
            else "Study sessions start tomorrow; say 'starting today' to include today."
        )
    ctx.assumptions.append("No study is scheduled on an exam day itself.")

    calendar = Calendar(_existing_busy(ctx, start_day, last_exam), ctx.now, ctx.window)
    meeting = None
    if f.meeting is not None:
        m_day = f.meeting_date or f.target_date or start_day
        start = datetime.combine(m_day, f.meeting)
        meeting = (start, start + timedelta(hours=1))
        calendar.add(*meeting, "project meeting")
        ctx.fact("Meeting", f"{fmt_time(start)} {ctx.day_text(m_day)}", "you said")
        ctx.assumptions.append("Your meeting length wasn't given, so I kept 1 hour free for it.")

    timing = {s: ctx.pref.subject_time_preferences.get(s, "") for s, *_ in subjects}
    blocks, err = allocate_until_deadlines(
        [(s, m, d) for s, m, d, *_ in subjects], start_day, calendar, ctx.pref.preferred_session_minutes, timing)
    if err:
        return ctx.clarify(*_error_question(ctx, err))

    tasks = _block_steps(ctx, blocks, meeting, multi_day=True, first_depends_on=[])
    per_subject = []
    for s, m, d, *_ in subjects:
        mine = [b for b in blocks if b.subject == s]
        days = sorted({b.start.date() for b in mine})
        per_subject.append(f"{s}: {len(mine)} session(s) over {len(days)} day(s) before {fmt_day(d)}")
    summary = (f"Study plan for {len(f.exams)} exam(s): " + "; ".join(per_subject) +
               ". Earliest exam first, with sessions spread out so no day is overloaded.")
    if meeting:
        summary += f" Your {fmt_time(meeting[0])} meeting is kept free."
    summary += _influences(ctx)
    return AgentPlan(goal=ctx.goal.goal, summary=summary, tasks=tasks, requires_approval=True,
                     understanding=ctx.understanding, assumptions=ctx.assumptions)


def build_study_plan(goal: UserGoal, pref_override: StudentPreferences | None = None,
                     stated_pref_fields: set[str] | None = None, now: datetime | None = None) -> AgentPlan:
    """Plan study sessions for the goal (see module docstring)."""
    pref = pref_override if pref_override is not None else _load_preferences()
    ctx = _Context(goal, pref, stated_pref_fields or set(), now or datetime.now())
    f = ctx.facts

    if f.ambiguous_dates and f.target_date is None:
        # A vague date ("next week") is never silently turned into a specific day.
        phrase = f.ambiguous_dates[0]
        return ctx.clarify("Date clarification", (
            f"When should I plan this? '{phrase}' isn't specific enough — tell me a day like 'tomorrow' or 'Friday', "
            f"or a date like '15 Oct'."
        ))
    if f.exams:
        return _until_exams(ctx)

    requests = [(r.subject, r.minutes) for r in f.requirements]
    if not requests:
        subjects = f.mentioned_subjects or list(ctx.pref.preferred_subjects)
        if not subjects:
            return ctx.clarify("Schedule clarification needed", (
                "I need one clarification: which subjects should I schedule, and for how long? "
                "For example: '2 hours of DBMS and 1 hour of DAA'."
            ))
        session = ctx.pref.preferred_session_minutes
        requests = [(s, session) for s in subjects[:6]]
        source = "your goal" if f.mentioned_subjects else "your saved subjects"
        ctx.assumptions.append(f"No study time was given, so I used your session length ({session} min) for each subject from {source}.")
        if not f.mentioned_subjects:
            ctx.fact("Subjects", ", ".join(subjects[:6]), "saved preference")
    return _single_day(ctx, requests)


def build_chained_preference_and_study_plan(goal: UserGoal) -> AgentPlan:
    """
    "Remember that I prefer DBMS in the evening, then plan …": step 1 saves the stated preference
    (approval required); the study steps depend on it and already use it.
    """
    updates = extract_preference_updates(goal.goal)
    if not updates:
        return build_study_plan(goal)
    current = _load_preferences() or StudentPreferences()
    merged: dict[str, Any] = current.model_dump()
    for k, v in updates.items():
        if k == "subject_time_preferences":
            merged[k] = {**merged.get(k, {}), **v}
        elif k in ("planning_notes", "preferred_subjects"):
            merged[k] = list(dict.fromkeys([*merged.get(k, []), *v]))
        else:
            merged[k] = v
    try:
        projected = StudentPreferences(**merged)
    except ValueError:
        projected = current

    pref_call = route_tool("update_student_preferences", updates)
    notes = updates.get("planning_notes") or []
    pref_step = AgentTask(
        id=new_step_id(), title="Save study preference",
        description=("Remember: " + "; ".join(notes)) if notes else "Save stated study preferences.",
        tool=pref_call.tool_name, parameters=pref_call.parameters, requires_approval=True,
    )
    study_plan = build_study_plan(goal, pref_override=projected, stated_pref_fields=set(updates))
    if not any(t.tool for t in study_plan.tasks):
        return AgentPlan(
            goal=goal.goal,
            summary=("I can save this preference now. To plan study sessions, tell me which subjects "
                     "and how long, e.g. '2 hours of DBMS'."),
            tasks=[pref_step], requires_approval=True,
            understanding=study_plan.understanding, assumptions=study_plan.assumptions,
        )
    study_plan.tasks[0].depends_on = [pref_step.id]
    return study_plan.model_copy(update={
        "summary": "Save your preference first, then: " + study_plan.summary,
        "tasks": [pref_step, *study_plan.tasks],
    })
