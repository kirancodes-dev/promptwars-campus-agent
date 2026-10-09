from datetime import date, datetime, time, timedelta
import re
from typing import Any
import uuid

try:
    from agent.router import get_tool, route_tool, tool_mutates, validate_tool_name
    from agent.workflow import validate_plan_dependencies
    from models.agent import AgentPlan, AgentTask, UserGoal
    from services.gemini import build_planning_prompt
    from services.memory import MemoryService
    from services.identity import current_user_id
    from services.persistence import get_persistence
    from tools.schedule import find_available_slots, propose_study_blocks
except ImportError:
    from backend.agent.router import get_tool, route_tool, tool_mutates, validate_tool_name
    from backend.agent.workflow import validate_plan_dependencies
    from backend.models.agent import AgentPlan, AgentTask, UserGoal
    from backend.services.gemini import build_planning_prompt
    from backend.services.memory import MemoryService
    from backend.services.identity import current_user_id
    from backend.services.persistence import get_persistence
    from backend.tools.schedule import find_available_slots, propose_study_blocks


class PlannerError(ValueError):
    """Raised when the planner encounters invalid input or planning failures."""
    pass


VAGUE_GOALS = {
    "help me study",
    "help me",
    "study",
    "prepare",
    "help me prepare",
    "i want to study",
    "assist me",
    "help",
}


def _detect_intent(text: str) -> str:
    """
    Deterministic intent recognition based on goal text.
    Categories:
    - task creation
    - schedule creation
    - note creation
    - task listing
    - schedule listing
    - note search
    - general planning
    """
    text_lower = text.lower().strip()

    if text_lower in VAGUE_GOALS:
        return "vague"

    # Chained preference update and study planning (e.g. "Remember that I prefer evening study sessions, then plan my preparation for tomorrow.")
    if (
        ("remember" in text_lower or "prefer" in text_lower or "preference" in text_lower)
        and (
            "then plan" in text_lower
            or "then prepare" in text_lower
            or "and plan" in text_lower
            or "and prepare" in text_lower
            or ("plan" in text_lower and "tomorrow" in text_lower)
            or ("prepare" in text_lower and "tomorrow" in text_lower)
            or ("preparation" in text_lower and "tomorrow" in text_lower)
        )
    ):
        return "chained preference and study plan"

    # Review schedule and plan revision (e.g. "Review my schedule, identify free time, plan my DBMS revision, and create tasks for the sessions.")
    if (
        ("review" in text_lower or "check" in text_lower or "inspect" in text_lower)
        and "schedule" in text_lower
        and (
            "free time" in text_lower
            or "available" in text_lower
            or "revision" in text_lower
            or "sessions" in text_lower
        )
    ):
        return "review and plan revision"

    # Smart study planning (e.g. "Prepare my study schedule for tomorrow. I need 2 hours of DBMS, 1 hour of DAA, and a project meeting at 4 PM.")
    if any(
        phrase in text_lower
        for phrase in [
            "organize",
            "preparation",
            "prepare",
            "study plan",
            "plan my preparation",
            "prepare my study",
            "plan my study schedule",
            "study schedule for tomorrow",
        ]
    ) and any(
        subj in text_lower
        for subj in ["dbms", "daa", "os", "cn", "hours", "hour", "mins", "minutes", "meeting"]
    ):
        return "smart study planning"

    # Task listing
    if any(
        phrase in text_lower
        for phrase in [
            "show my tasks",
            "list my tasks",
            "get my tasks",
            "view my tasks",
            "show tasks",
            "list tasks",
            "get tasks",
            "what are my tasks",
            "all tasks",
        ]
    ):
        return "task listing"

    # Schedule listing
    if any(
        phrase in text_lower
        for phrase in [
            "what is on my schedule",
            "show my schedule",
            "view my schedule",
            "list my schedule",
            "get my schedule",
            "check my schedule",
            "show schedule",
            "list schedule",
            "view schedule",
            "my schedule tomorrow",
        ]
    ):
        return "schedule listing"

    # Note search
    if "notes" in text_lower or "note" in text_lower:
        if any(
            text_lower.startswith(prefix)
            for prefix in ["find my", "find", "search for", "search", "look for", "look up"]
        ):
            return "note search"

    # Preference listing
    if any(
        phrase in text_lower
        for phrase in [
            "show my preferences",
            "show preferences",
            "get my preferences",
            "view preferences",
            "list preferences",
            "what are my preferences",
            "my study preferences",
            "show memory",
            "view memory",
            "get memory",
        ]
    ):
        return "preference listing"

    # Preference reset
    if any(
        phrase in text_lower
        for phrase in [
            "reset my preferences",
            "reset preferences",
            "clear my preferences",
            "clear preferences",
            "reset memory",
        ]
    ):
        return "preference reset"

    # Preference update (e.g. "Remember that I prefer studying DBMS in the evening and taking a 10-minute break after each study session.")
    if any(kw in text_lower for kw in ["preference", "preferences", "preferred_"]) or (
        any(kw in text_lower for kw in ["prefer", "preferred"])
        and any(kw in text_lower for kw in ["break", "minute", "minutes", "session", "window", "take a", "taking a"])
    ) or (
        any(phrase in text_lower for phrase in ["remember that", "remember:", "note that"])
        and any(kw in text_lower for kw in ["break", "session", "study window"])
    ):
        return "preference update"

    # Study schedule planning (e.g. "Plan my study schedule for tomorrow.")
    if any(
        phrase in text_lower
        for phrase in [
            "plan my study schedule",
            "plan study schedule",
            "study schedule for tomorrow",
            "plan my study for tomorrow",
            "schedule my study for tomorrow",
            "plan my study",
        ]
    ):
        return "study schedule planning"

    # Note creation
    if any(
        phrase in text_lower
        for phrase in [
            "remember that",
            "remember:",
            "take a note",
            "create a note",
            "add a note",
            "make a note",
            "save note",
            "note that",
        ]
    ):
        return "note creation"

    # Schedule creation (e.g. Schedule DBMS study tomorrow at 6 PM)
    if text_lower.startswith("schedule ") or "schedule a " in text_lower or "schedule an " in text_lower:
        return "schedule creation"

    # Task creation (e.g. Create a task to study DBMS)
    if any(
        phrase in text_lower
        for phrase in [
            "create a task",
            "create task",
            "add a task",
            "add task",
            "new task",
            "remind me to",
            "task to",
        ]
    ):
        return "task creation"

    # General planning
    if any(
        phrase in text_lower
        for phrase in [
            "organize",
            "preparation",
            "plan",
            "help me organize",
            "prepare for",
        ]
    ):
        return "general planning"

    return "general planning"


def _build_task_creation_plan(goal: UserGoal) -> AgentPlan:
    """Build plan for creating a task."""
    raw = goal.goal.strip()
    prefixes = [
        "create a task to ",
        "create a task: ",
        "create a task ",
        "create task to ",
        "create task: ",
        "create task ",
        "add a task to ",
        "add a task ",
        "add task to ",
        "add task ",
        "new task: ",
        "new task ",
        "remind me to ",
    ]
    title = raw
    raw_lower = raw.lower()
    for prefix in prefixes:
        if raw_lower.startswith(prefix):
            title = raw[len(prefix):].strip()
            break

    if not title:
        title = raw

    tool_call = route_tool("create_task", {"title": title, "priority": goal.priority or "medium"})

    task = AgentTask(
        id=f"plan_task_{uuid.uuid4().hex[:8]}",
        title=f"Create task: {title}",
        description=f"Add task '{title}' to task management list",
        status="pending",
        priority=goal.priority or "medium",
        tool=tool_call.tool_name,
        parameters=tool_call.parameters,
        requires_approval=tool_call.requires_approval,
    )

    return AgentPlan(
        goal=goal.goal,
        summary=f"Plan to create task: '{title}'",
        tasks=[task],
        requires_approval=task.requires_approval,
    )


def _build_schedule_creation_plan(goal: UserGoal) -> AgentPlan:
    """Build plan for creating a schedule entry."""
    raw = goal.goal.strip()
    raw_lower = raw.lower()

    # Title extraction
    title = raw
    if raw_lower.startswith("schedule "):
        title = raw[9:].strip()

    # Extract time cues if present (e.g. tomorrow at 6 PM)
    now = datetime.now()
    has_tomorrow = "tomorrow" in raw_lower
    target_date = now + timedelta(days=1) if has_tomorrow else now

    time_match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", raw, re.IGNORECASE)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        meridiem = time_match.group(3).lower()
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        start_time = target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        end_time = start_time + timedelta(hours=1)

        # Clean title before time tokens
        split_match = re.split(r"\s+(?:tomorrow|at|\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b)", title, flags=re.IGNORECASE)
        clean_title = split_match[0].strip() if split_match and split_match[0].strip() else title

        tool_call = route_tool(
            "create_schedule",
            {
                "title": clean_title,
                "start_time": start_time,
                "end_time": end_time,
            },
        )

        task = AgentTask(
            id=f"plan_task_{uuid.uuid4().hex[:8]}",
            title=f"Schedule event: {clean_title}",
            description=f"Schedule '{clean_title}' from {start_time.strftime('%Y-%m-%d %H:%M')} to {end_time.strftime('%H:%M')}",
            status="pending",
            tool=tool_call.tool_name,
            parameters=tool_call.parameters,
            requires_approval=tool_call.requires_approval,
        )

        return AgentPlan(
            goal=goal.goal,
            summary=f"Plan to schedule event: '{clean_title}'",
            tasks=[task],
            requires_approval=task.requires_approval,
        )
    else:
        # No concrete time supplied: produce clarification task without tool execution
        task = AgentTask(
            id=f"plan_task_{uuid.uuid4().hex[:8]}",
            title="Clarify schedule time",
            description=f"Clarify time and duration for '{title}'.",
            status="pending",
            tool=None,
            parameters={},
            requires_approval=False,
        )
        return AgentPlan(
            goal=goal.goal,
            summary=f"Schedule clarification needed for '{title}'",
            tasks=[task],
            requires_approval=False,
        )


def _build_note_creation_plan(goal: UserGoal) -> AgentPlan:
    """Build plan for creating a note."""
    raw = goal.goal.strip()
    raw_lower = raw.lower()

    content = raw
    prefixes = [
        "remember that ",
        "remember: ",
        "remember ",
        "take a note that ",
        "take a note: ",
        "create a note: ",
        "create a note that ",
        "create a note ",
        "add a note: ",
        "add a note ",
        "note that ",
    ]
    for prefix in prefixes:
        if raw_lower.startswith(prefix):
            content = raw[len(prefix):].strip()
            break

    title = content[:40] + ("..." if len(content) > 40 else "")
    tool_call = route_tool("create_note", {"title": title, "content": content, "category": "notes"})

    task = AgentTask(
        id=f"plan_task_{uuid.uuid4().hex[:8]}",
        title=f"Create note: {title}",
        description=f"Save note: '{content}'",
        status="pending",
        tool=tool_call.tool_name,
        parameters=tool_call.parameters,
        requires_approval=tool_call.requires_approval,
    )

    return AgentPlan(
        goal=goal.goal,
        summary=f"Plan to save note: '{title}'",
        tasks=[task],
        requires_approval=task.requires_approval,
    )


def _build_listing_plan(goal: UserGoal, intent: str) -> AgentPlan:
    """Build plan for listing tasks or schedule."""
    if intent == "task listing":
        tool_call = route_tool("get_tasks", {})
        task = AgentTask(
            id=f"plan_task_{uuid.uuid4().hex[:8]}",
            title="Retrieve tasks",
            description="Fetch existing tasks",
            status="pending",
            tool=tool_call.tool_name,
            parameters=tool_call.parameters,
            requires_approval=tool_call.requires_approval,
        )
        return AgentPlan(
            goal=goal.goal,
            summary="Plan to retrieve user tasks",
            tasks=[task],
            requires_approval=False,
        )
    else:
        tool_call = route_tool("get_schedule", {})
        task = AgentTask(
            id=f"plan_task_{uuid.uuid4().hex[:8]}",
            title="Retrieve schedule",
            description="Fetch scheduled events",
            status="pending",
            tool=tool_call.tool_name,
            parameters=tool_call.parameters,
            requires_approval=tool_call.requires_approval,
        )
        return AgentPlan(
            goal=goal.goal,
            summary="Plan to retrieve scheduled events",
            tasks=[task],
            requires_approval=False,
        )


def _build_search_plan(goal: UserGoal) -> AgentPlan:
    """Build plan for searching notes."""
    raw = goal.goal.strip()
    raw_lower = raw.lower()

    # Extract search query
    query = raw
    prefixes = ["find my ", "find ", "search for my ", "search for ", "search ", "look for ", "look up "]
    for prefix in prefixes:
        if raw_lower.startswith(prefix):
            query = raw[len(prefix):].strip()
            break

    if query.lower().endswith(" notes"):
        query = query[:-6].strip()
    elif query.lower().endswith(" note"):
        query = query[:-5].strip()

    if not query:
        query = raw

    tool_call = route_tool("search_notes", {"query": query})

    task = AgentTask(
        id=f"plan_task_{uuid.uuid4().hex[:8]}",
        title=f"Search notes: '{query}'",
        description=f"Search notes matching '{query}'",
        status="pending",
        tool=tool_call.tool_name,
        parameters=tool_call.parameters,
        requires_approval=tool_call.requires_approval,
    )

    return AgentPlan(
        goal=goal.goal,
        summary=f"Plan to search notes matching '{query}'",
        tasks=[task],
        requires_approval=False,
    )


def _build_general_plan(goal: UserGoal) -> AgentPlan:
    """Build structured multi-step plan for general goals."""
    t1_call = route_tool("get_schedule", {})
    t1 = AgentTask(
        id=f"plan_task_{uuid.uuid4().hex[:8]}",
        title="Check current schedule",
        description="Review schedule for upcoming commitments",
        status="pending",
        tool=t1_call.tool_name,
        parameters=t1_call.parameters,
        requires_approval=False,
    )

    t2_call = route_tool("get_tasks", {})
    t2 = AgentTask(
        id=f"plan_task_{uuid.uuid4().hex[:8]}",
        title="Check existing tasks",
        description="Review pending tasks related to preparation",
        status="pending",
        tool=t2_call.tool_name,
        parameters=t2_call.parameters,
        requires_approval=False,
    )

    t3 = AgentTask(
        id=f"plan_task_{uuid.uuid4().hex[:8]}",
        title="Formulate preparation timeline",
        description=f"Synthesize schedule and tasks into an organized plan for '{goal.goal.strip()}'",
        status="pending",
        tool=None,
        parameters={},
        requires_approval=False,
    )

    return AgentPlan(
        goal=goal.goal,
        summary="Structured plan combining schedule and task review with timeline formulation",
        tasks=[t1, t2, t3],
        requires_approval=False,
    )


def _extract_preference_updates(text: str) -> dict[str, Any]:
    """
    Extract explicitly stated student preferences from natural language.
    Avoids inventing preferences that were not stated.
    """
    updates: dict[str, Any] = {}
    text_lower = text.lower()

    # 1. Break minutes: e.g. "10-minute break", "15 minute break", "break of 10 minutes"
    break_match = re.search(
        r"(\d+)\s*(?:-|–|\s)?\s*min(?:ute)?s?\s+break|break\s+(?:of\s+)?(\d+)\s*min",
        text_lower,
    )
    if break_match:
        mins = int(break_match.group(1) or break_match.group(2))
        if 0 <= mins <= 120:
            updates["preferred_break_minutes"] = mins

    # 2. Session minutes: e.g. "45-minute session", "session of 60 minutes", "1 hour session"
    session_match = re.search(
        r"(\d+)\s*(?:-|–|\s)?\s*min(?:ute)?s?\s+(?:study\s+|focus\s+)?session",
        text_lower,
    )
    if session_match:
        mins = int(session_match.group(1))
        if 15 <= mins <= 360:
            updates["preferred_session_minutes"] = mins
    elif "1 hour session" in text_lower or "1-hour session" in text_lower:
        updates["preferred_session_minutes"] = 60
    elif "2 hour session" in text_lower or "2-hour session" in text_lower:
        updates["preferred_session_minutes"] = 120

    # 3. Subject time preferences: e.g. "studying DBMS in the evening", "DAA in the morning", "prefer OS at night"
    subject_candidates = ["dbms", "daa", "os", "cn", "math", "dsa", "ai", "ml"]
    time_windows = ["morning", "afternoon", "evening", "night"]
    subj_time: dict[str, str] = {}
    for subj in subject_candidates:
        for tw in time_windows:
            pattern = rf"\b{subj}\b.*?\b(?:in the|during the|at)?\s*{tw}\b|\b{tw}\b.*?\b{subj}\b"
            if re.search(pattern, text_lower):
                subj_time[subj.upper()] = tw
    if subj_time:
        updates["subject_time_preferences"] = subj_time
        updates["preferred_subjects"] = list(subj_time.keys())

    # 4. Study hours window: e.g. "between 08:00 and 20:00", "from 9 am to 9 pm"
    hours_match = re.search(
        r"(?:between|from)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+(?:and|to)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
        text_lower,
    )
    if hours_match:
        def _parse_hhmm(s: str) -> str | None:
            s = s.strip()
            m24 = re.match(r"^(\d{1,2}):(\d{2})$", s)
            if m24:
                return f"{int(m24.group(1)):02d}:{m24.group(2)}"
            m12 = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$", s)
            if m12:
                hr = int(m12.group(1))
                mn = m12.group(2) or "00"
                ampm = m12.group(3)
                if ampm == "pm" and hr < 12:
                    hr += 12
                elif ampm == "am" and hr == 12:
                    hr = 0
                return f"{hr:02d}:{mn}"
            return None

        st = _parse_hhmm(hours_match.group(1))
        et = _parse_hhmm(hours_match.group(2))
        if st and et:
            updates["preferred_study_start"] = st
            updates["preferred_study_end"] = et

    # 4b. Evening / morning study session preferences (e.g. "prefer evening study sessions")
    if "preferred_study_start" not in updates:
        if (
            "evening study" in text_lower
            or "evening session" in text_lower
            or re.search(r"prefer\s+evening", text_lower)
        ):
            updates["preferred_study_start"] = "17:00"
            updates["preferred_study_end"] = "22:00"
        elif (
            "morning study" in text_lower
            or "morning session" in text_lower
            or re.search(r"prefer\s+morning", text_lower)
        ):
            updates["preferred_study_start"] = "08:00"
            updates["preferred_study_end"] = "12:00"

    # 5. Planning notes: clean extracted note
    clean_note = text.strip()

    # If chained request like "Remember that I prefer evening study sessions, then plan my preparation for tomorrow."
    # Strip the chained instruction from the note
    for split_token in [
        ", then plan",
        " then plan",
        ", then prepare",
        " then prepare",
        ", and plan",
        " and plan",
        ", and prepare",
        " and prepare",
    ]:
        if split_token in clean_note.lower():
            idx = clean_note.lower().find(split_token)
            clean_note = clean_note[:idx].strip()
            break

    for prefix in [
        "remember that ",
        "please remember that ",
        "remember: ",
        "note that ",
        "preference: ",
    ]:
        if clean_note.lower().startswith(prefix):
            clean_note = clean_note[len(prefix):].strip()
            break
    if clean_note:
        updates["planning_notes"] = [clean_note]

    return updates


def _build_preference_update_plan(goal: UserGoal) -> AgentPlan:
    """Build plan to update student preferences with approval."""
    updates = _extract_preference_updates(goal.goal)
    if not updates:
        raise PlannerError("Could not extract any valid preferences from your request.")

    tool_call = route_tool("update_student_preferences", updates)

    desc_items = []
    if "subject_time_preferences" in updates:
        for s, t in updates["subject_time_preferences"].items():
            desc_items.append(f"{s} in the {t}")
    if "preferred_break_minutes" in updates:
        desc_items.append(f"{updates['preferred_break_minutes']}-min break")
    if "preferred_session_minutes" in updates:
        desc_items.append(f"{updates['preferred_session_minutes']}-min sessions")
    if "preferred_study_start" in updates and "preferred_study_end" in updates:
        desc_items.append(f"hours {updates['preferred_study_start']}-{updates['preferred_study_end']}")

    summary_desc = ", ".join(desc_items) if desc_items else "student study preferences"

    task = AgentTask(
        id=f"plan_task_{uuid.uuid4().hex[:8]}",
        title=f"Update study preferences ({summary_desc})",
        description=f"Save preference updates: {summary_desc}",
        status="pending",
        tool=tool_call.tool_name,
        parameters=tool_call.parameters,
        requires_approval=True,
    )

    return AgentPlan(
        goal=goal.goal,
        summary=f"Plan to update preferences: {summary_desc}. Requires approval before saving to memory.",
        tasks=[task],
        requires_approval=True,
    )


def _build_preference_listing_plan(goal: UserGoal) -> AgentPlan:
    """Build plan to list student preferences."""
    tool_call = route_tool("get_student_preferences", {})
    task = AgentTask(
        id=f"plan_task_{uuid.uuid4().hex[:8]}",
        title="Retrieve student preferences",
        description="Inspect saved study preferences and memory settings",
        status="pending",
        tool=tool_call.tool_name,
        parameters=tool_call.parameters,
        requires_approval=False,
    )
    return AgentPlan(
        goal=goal.goal,
        summary="Plan to retrieve student study preferences and memory",
        tasks=[task],
        requires_approval=False,
    )


def _build_preference_reset_plan(goal: UserGoal) -> AgentPlan:
    """Build plan to reset student preferences."""
    tool_call = route_tool("reset_student_preferences", {"confirmation": True})
    task = AgentTask(
        id=f"plan_task_{uuid.uuid4().hex[:8]}",
        title="Reset study preferences",
        description="Reset student study preferences to system defaults",
        status="pending",
        tool=tool_call.tool_name,
        parameters=tool_call.parameters,
        requires_approval=True,
    )
    return AgentPlan(
        goal=goal.goal,
        summary="Plan to reset study preferences to defaults. Requires approval.",
        tasks=[task],
        requires_approval=True,
    )


def _build_preference_aware_study_plan(goal: UserGoal) -> AgentPlan:
    """
    Build study plan informed by saved student preferences.
    If essential information is missing, asks for clarification.
    Requires approval before creating schedule blocks or tasks.
    """
    raw = goal.goal.strip()
    raw_lower = raw.lower()

    try:
        pref = MemoryService().get_preferences()
    except Exception:
        pref = None

    # Determine subjects
    candidate_subjects = ["dbms", "daa", "os", "cn", "math", "algorithms", "dsa", "ai", "ml"]
    detected_subjects = [
        s.upper() for s in candidate_subjects if re.search(rf"\b{s}\b", raw_lower)
    ]
    if not detected_subjects and pref and pref.preferred_subjects:
        detected_subjects = list(pref.preferred_subjects)

    if not detected_subjects:
        task = AgentTask(
            id=f"plan_task_{uuid.uuid4().hex[:8]}",
            title="Schedule clarification needed",
            description="Which subjects or topics would you like to schedule for tomorrow?",
            status="pending",
            tool=None,
            parameters={},
            requires_approval=False,
        )
        return AgentPlan(
            goal=goal.goal,
            summary="Clarification required: Which subjects or topics would you like to schedule for tomorrow?",
            tasks=[task],
            requires_approval=False,
        )

    now = datetime.now()
    target_date = now.date() + timedelta(days=1)
    session_mins = pref.preferred_session_minutes if pref else 60

    # Step 1: Check existing schedule
    t1_call = route_tool("get_schedule", {})
    step1 = AgentTask(
        id=f"plan_task_{uuid.uuid4().hex[:8]}",
        title="Check existing schedule",
        description="Inspect existing scheduled commitments for tomorrow.",
        status="pending",
        tool=t1_call.tool_name,
        parameters=t1_call.parameters,
        requires_approval=False,
    )

    available_slots = find_available_slots(target_date, session_mins)
    if not available_slots:
        task = AgentTask(
            id=f"plan_task_{uuid.uuid4().hex[:8]}",
            title="Schedule clarification needed",
            description=f"No available {session_mins}-minute slots found tomorrow. Please adjust your study window or free up time.",
            status="pending",
            tool=None,
            parameters={},
            requires_approval=False,
        )
        return AgentPlan(
            goal=goal.goal,
            summary=f"No available {session_mins}-minute slots found tomorrow.",
            tasks=[task],
            requires_approval=False,
        )

    tasks = [step1]
    scheduled_blocks = []
    used_slots = []
    conflict_tasks = []
    schedule_tasks = []

    for subj in detected_subjects:
        time_pref = pref.subject_time_preferences.get(subj, "").lower() if pref else ""
        chosen_slot = None

        if time_pref == "evening":
            evening_slots = [
                s for s in available_slots if s["start_time"].hour >= 17 and s not in used_slots
            ]
            if evening_slots:
                chosen_slot = evening_slots[0]
        elif time_pref == "morning":
            morning_slots = [
                s for s in available_slots if s["start_time"].hour < 12 and s not in used_slots
            ]
            if morning_slots:
                chosen_slot = morning_slots[0]

        if not chosen_slot:
            remaining = [s for s in available_slots if s not in used_slots]
            if remaining:
                chosen_slot = remaining[0]

        if chosen_slot:
            used_slots.append(chosen_slot)
            start_dt = chosen_slot["start_time"]
            end_dt = chosen_slot["end_time"]

            # Conflict check step (inspection read)
            t_conf = route_tool(
                "check_schedule_conflict",
                {"start_time": start_dt, "end_time": end_dt},
            )
            c_task = AgentTask(
                id=f"plan_task_{uuid.uuid4().hex[:8]}",
                title=f"Check conflicts for {subj}",
                description=f"Verify no overlap for {subj} ({start_dt.strftime('%I:%M %p')} - {end_dt.strftime('%I:%M %p')})",
                status="pending",
                tool=t_conf.tool_name,
                parameters=t_conf.parameters,
                requires_approval=False,
                depends_on=[step1.id],
            )
            conflict_tasks.append(c_task)

            # Schedule creation step (requires approval)
            t_sched = route_tool(
                "create_schedule",
                {
                    "title": f"{subj} Study Session",
                    "start_time": start_dt,
                    "end_time": end_dt,
                    "description": f"{session_mins}-minute focused {subj} study session.",
                    "requires_approval": True,
                },
            )
            s_task = AgentTask(
                id=f"plan_task_{uuid.uuid4().hex[:8]}",
                title=f"Schedule {subj} study session",
                description=f"Create schedule block for {subj} ({start_dt.strftime('%I:%M %p')} - {end_dt.strftime('%I:%M %p')})",
                status="pending",
                tool=t_sched.tool_name,
                parameters=t_sched.parameters,
                requires_approval=True,
                depends_on=[c_task.id],
            )
            schedule_tasks.append(s_task)
            scheduled_blocks.append(subj)

    # Place all inspection reads before mutation writes
    tasks.extend(conflict_tasks)
    tasks.extend(schedule_tasks)

    sched_ids = [t.id for t in schedule_tasks]
    t_task = route_tool(
        "create_task",
        {
            "title": f"Study {' & '.join(scheduled_blocks)}",
            "description": f"Complete preparation for {', '.join(scheduled_blocks)}.",
            "priority": "medium",
            "requires_approval": True,
        },
    )
    task_step = AgentTask(
        id=f"plan_task_{uuid.uuid4().hex[:8]}",
        title="Create study task",
        description=f"Add task for {' & '.join(scheduled_blocks)}",
        status="pending",
        tool=t_task.tool_name,
        parameters=t_task.parameters,
        requires_approval=True,
        depends_on=sched_ids,
    )
    tasks.append(task_step)

    report_step = AgentTask(
        id=f"plan_task_{uuid.uuid4().hex[:8]}",
        title="Report study schedule",
        description="Present personalized study schedule to student.",
        status="pending",
        tool=None,
        parameters={},
        requires_approval=False,
        depends_on=[task_step.id],
    )
    tasks.append(report_step)

    influences = MemoryService().identify_influencing_preferences(goal.goal, pref) if pref else []
    inf_str = f" (Influenced by: {'; '.join(influences)})" if influences else ""
    summary = f"Personalized study plan for {', '.join(scheduled_blocks)} tomorrow.{inf_str}"

    return AgentPlan(
        goal=goal.goal,
        summary=summary,
        tasks=tasks,
        requires_approval=True,
    )


_DURATION_UNIT = r"(hours?|hrs?|minutes?|mins?)"
_REQ_FORWARD = re.compile(
    r"(\d+(?:\.\d+)?)\s*" + _DURATION_UNIT + r"\s+(?:of\s+)?([a-z][a-z0-9+#&\-]*)",
    re.IGNORECASE,
)
_REQ_BACKWARD = re.compile(
    r"\b([a-z][a-z0-9+#&\-]*)\s+for\s+(\d+(?:\.\d+)?)\s*" + _DURATION_UNIT,
    re.IGNORECASE,
)
_NON_SUBJECT_WORDS = {
    "study", "studying", "revision", "revise", "the", "my", "a", "an", "meeting", "meetings",
    "break", "breaks", "sleep", "free", "time", "each", "per", "and", "of", "for", "to",
    "prep", "preparation", "work", "rest", "session", "sessions", "focus", "focused", "total",
    "class", "classes", "lecture", "lectures", "it", "that", "this", "me", "i", "be", "is",
}
MAX_STUDY_REQUIREMENTS = 6


def _subject_label(word: str) -> str:
    return word.upper() if len(word) <= 4 else word.capitalize()


def _to_minutes(amount: str, unit: str) -> int:
    value = float(amount)
    return int(round(value * 60)) if unit.lower().startswith("h") else int(round(value))


def _parse_study_requirements(text: str) -> list[tuple[str, int]]:
    """
    Extract explicitly requested (subject, minutes) pairs such as
    "2 hours of DBMS" or "DAA for 90 minutes". Never invents requirements.
    """
    found: list[tuple[int, str, int]] = []
    for m in _REQ_FORWARD.finditer(text):
        word = m.group(3)
        if word.lower() in _NON_SUBJECT_WORDS:
            continue
        found.append((m.start(), _subject_label(word), _to_minutes(m.group(1), m.group(2))))
    for m in _REQ_BACKWARD.finditer(text):
        word = m.group(1)
        if word.lower() in _NON_SUBJECT_WORDS:
            continue
        found.append((m.start(), _subject_label(word), _to_minutes(m.group(2), m.group(3))))
    found.sort(key=lambda x: x[0])
    reqs: list[tuple[str, int]] = []
    seen: set[str] = set()
    for _, subj, mins in found:
        if subj in seen or not (15 <= mins <= 360):
            continue
        seen.add(subj)
        reqs.append((subj, mins))
    return reqs[:MAX_STUDY_REQUIREMENTS]


def _parse_clock(hour: str, minute: str | None, meridiem: str | None, assume_pm_below: int = 7) -> time | None:
    h = int(hour)
    mn = int(minute or 0)
    if meridiem:
        meridiem = meridiem.lower()
        if meridiem == "pm" and h < 12:
            h += 12
        elif meridiem == "am" and h == 12:
            h = 0
    elif h < assume_pm_below:
        h += 12
    if not (0 <= h <= 23 and 0 <= mn <= 59):
        return None
    return time(h, mn)


def _parse_meeting(text_lower: str) -> time | None:
    m = re.search(r"meeting\s+(?:is\s+)?(?:at|from)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text_lower)
    if not m:
        m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s+(?:project\s+|team\s+|group\s+)?meeting", text_lower)
    if not m:
        return None
    return _parse_clock(m.group(1), m.group(2), m.group(3))


def _explicit_subject_time(text_lower: str, subject: str) -> time | None:
    """Only an explicit "<subject> at 6 PM" (same clause) counts as a requested start time."""
    s = re.escape(subject.lower())
    m = re.search(
        rf"\b{s}\b\s+(?:study\s+|session\s+|revision\s+|block\s+)?(?:at|from)\s+(\d{{1,2}})(?::(\d{{2}}))?\s*(am|pm)?",
        text_lower,
    )
    if not m:
        m = re.search(rf"\bat\s+(\d{{1,2}})(?::(\d{{2}}))?\s*(am|pm)\s+(?:for\s+)?{s}\b", text_lower)
    if not m:
        return None
    return _parse_clock(m.group(1), m.group(2), m.group(3))


def _duration_label(minutes: int) -> str:
    if minutes % 60 == 0:
        return f"{minutes // 60}-hour"
    return f"{minutes}-minute"


def _fmt(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and a_end > b_start


def _first_free_slot(
    window_start: datetime,
    window_end: datetime,
    busy: list[tuple[datetime, datetime]],
    minutes: int,
) -> tuple[datetime, datetime] | None:
    cursor = window_start
    for b_start, b_end in sorted(busy):
        if b_end <= cursor:
            continue
        if b_start >= window_end:
            break
        if (b_start - cursor).total_seconds() / 60 >= minutes:
            return cursor, cursor + timedelta(minutes=minutes)
        cursor = max(cursor, b_end)
    if (window_end - cursor).total_seconds() / 60 >= minutes:
        return cursor, cursor + timedelta(minutes=minutes)
    return None


_TIME_OF_DAY_WINDOWS = {
    "morning": (time(6, 0), time(12, 0)),
    "afternoon": (time(12, 0), time(17, 0)),
    "evening": (time(17, 0), time(22, 0)),
    "night": (time(19, 0), time(23, 59)),
}


def _clarification_plan(goal: UserGoal, title: str, question: str) -> AgentPlan:
    task = AgentTask(
        id=f"plan_task_{uuid.uuid4().hex[:8]}",
        title=title,
        description=question,
        status="pending",
        tool=None,
        parameters={},
        requires_approval=False,
    )
    return AgentPlan(goal=goal.goal, summary=question, tasks=[task], requires_approval=False)


def _allocate_study_blocks(
    goal: UserGoal,
    requirements: list[tuple[str, int]],
    target_date: date,
    meeting_start: datetime | None,
    pref: Any,
) -> tuple[list[dict[str, Any]], AgentPlan | None, bool]:
    """
    Choose a non-overlapping slot for every requirement inside the student's study window,
    avoiding existing events, the stated meeting, and each other (plus the preferred break).
    Returns (blocks, clarification_plan_or_None, overrode_preference).
    """
    raw_lower = goal.goal.lower()
    day_label = "today" if target_date == datetime.now().date() else "tomorrow"

    win_start_t = time(9, 0)
    win_end_t = time(21, 0)
    break_minutes = 0
    if pref is not None:
        try:
            win_start_t = time.fromisoformat(pref.preferred_study_start)
            win_end_t = time.fromisoformat(pref.preferred_study_end)
        except (TypeError, ValueError):
            pass
        break_minutes = int(getattr(pref, "preferred_break_minutes", 0) or 0)
    window_start = datetime.combine(target_date, win_start_t)
    window_end = datetime.combine(target_date, win_end_t)

    busy: list[tuple[datetime, datetime, str]] = []
    try:
        for e in get_persistence().get_events(user_id=current_user_id()):
            if e.status != "cancelled" and e.start_time.date() == target_date:
                busy.append((e.start_time, e.end_time, e.title))
    except Exception:
        pass
    if meeting_start is not None:
        busy.append((meeting_start, meeting_start + timedelta(hours=1), "project meeting"))

    blocks: list[dict[str, Any]] = []
    overrode_preference = False

    for subject, minutes in requirements:
        explicit = _explicit_subject_time(raw_lower, subject)
        if explicit is not None:
            start = datetime.combine(target_date, explicit)
            end = start + timedelta(minutes=minutes)
            clash = next((b for b in busy if _overlaps(start, end, b[0], b[1])), None)
            if clash is not None:
                question = (
                    f"Schedule conflict detected: Your requested {subject} session at {_fmt(start)} "
                    f"conflicts with '{clash[2]}'. How would you like to proceed? "
                    f"Would you like to reschedule '{clash[2]}' or choose another time for {subject}?"
                )
                return [], _clarification_plan(goal, "Schedule conflict clarification", question), False
            if pref is not None and pref.subject_time_preferences.get(subject):
                overrode_preference = True
            slot = (start, end)
        else:
            occupied = [(b[0], b[1] + timedelta(minutes=break_minutes if b[2].endswith("study block") else 0)) for b in busy]
            slot = None
            timing = pref.subject_time_preferences.get(subject, "").lower() if pref is not None else ""
            if timing in _TIME_OF_DAY_WINDOWS:
                t_start, t_end = _TIME_OF_DAY_WINDOWS[timing]
                pref_start = max(window_start, datetime.combine(target_date, t_start))
                pref_end = min(window_end, datetime.combine(target_date, t_end))
                if pref_end > pref_start:
                    slot = _first_free_slot(pref_start, pref_end, occupied, minutes)
            if slot is None:
                slot = _first_free_slot(window_start, window_end, occupied, minutes)
            if slot is None:
                question = (
                    f"No {_duration_label(minutes)} slot is available {day_label} for {subject} within your study window "
                    f"({win_start_t.strftime('%H:%M')}–{win_end_t.strftime('%H:%M')}). "
                    + (
                        "Would you like me to use two 1-hour slots instead?"
                        if minutes == 120
                        else "Would you like me to split it into shorter sessions or choose another day?"
                    )
                )
                return [], _clarification_plan(goal, "Schedule clarification needed", question), False
        busy.append((slot[0], slot[1], f"{subject} study block"))
        blocks.append({"subject": subject, "minutes": minutes, "start": slot[0], "end": slot[1], "timing": None if explicit else (pref.subject_time_preferences.get(subject) if pref is not None else None)})

    return blocks, None, overrode_preference


def _study_block_steps(
    blocks: list[dict[str, Any]],
    meeting_start: datetime | None,
    target_date: date,
    first_depends_on: list[str],
) -> list[AgentTask]:
    """Read-before-write study plan steps shared by the study planners."""

    def new_id() -> str:
        return f"plan_task_{uuid.uuid4().hex[:8]}"

    req_text = ", ".join(f"{b['minutes'] // 60 if b['minutes'] % 60 == 0 else b['minutes']}"
                         f"{' hour' + ('s' if b['minutes'] != 60 else '') if b['minutes'] % 60 == 0 else ' minutes'} of {b['subject']}"
                         for b in blocks)
    meeting_text = f" and a project meeting at {_fmt(meeting_start)}" if meeting_start else ""

    step1 = AgentTask(
        id=new_id(),
        title="Understand study requirements",
        description=f"Requested: {req_text}{meeting_text} on {target_date.strftime('%A, %d %b')}.",
        depends_on=list(first_depends_on),
    )
    t2 = route_tool("get_schedule", {})
    step2 = AgentTask(
        id=new_id(),
        title="Check existing schedule",
        description="Read your existing schedule so new study blocks never overwrite current commitments.",
        tool=t2.tool_name,
        parameters=t2.parameters,
        depends_on=[step1.id],
    )
    if meeting_start is not None:
        c_start, c_end = meeting_start, meeting_start + timedelta(hours=1)
        c_desc = f"Check whether anything already overlaps the {_fmt(c_start)} meeting (treated as busy time)."
    else:
        c_start, c_end = blocks[0]["start"], blocks[0]["end"]
        c_desc = f"Check the first proposed block ({_fmt(c_start)} – {_fmt(c_end)}) for overlaps."
    t3 = route_tool("check_schedule_conflict", {"start_time": c_start, "end_time": c_end})
    step3 = AgentTask(
        id=new_id(),
        title="Check schedule conflicts",
        description=c_desc,
        tool=t3.tool_name,
        parameters=t3.parameters,
        depends_on=[step2.id],
    )
    step4 = AgentTask(
        id=new_id(),
        title="Find available study slots",
        description="Chosen free slots: " + "; ".join(
            f"{b['subject']} {_fmt(b['start'])} – {_fmt(b['end'])}" for b in blocks
        ) + ".",
        depends_on=[step2.id, step3.id],
    )
    block_steps = []
    for b in blocks:
        hours = b["minutes"] / 60
        dur = f"{int(hours)} hour{'s' if hours != 1 else ''}" if b["minutes"] % 60 == 0 else f"{b['minutes']} minutes"
        tc = route_tool(
            "create_schedule",
            {
                "title": f"{b['subject']} Study Block",
                "start_time": b["start"],
                "end_time": b["end"],
                "description": f"{dur} focused {b['subject']} study block.",
                "requires_approval": True,
            },
        )
        reason = f" (your saved {b['timing']} preference)" if b.get("timing") else ""
        block_steps.append(
            AgentTask(
                id=new_id(),
                title=f"Create {b['subject']} study block",
                description=f"Schedule {dur} of {b['subject']} ({_fmt(b['start'])} – {_fmt(b['end'])}){reason}.",
                tool=tc.tool_name,
                parameters=tc.parameters,
                requires_approval=True,
                depends_on=[step4.id],
            )
        )
    subjects = [b["subject"] for b in blocks]
    tt = route_tool(
        "create_task",
        {
            "title": f"{' & '.join(subjects)} Preparation",
            "description": "Complete " + ", ".join(
                f"{b['subject']} ({_fmt(b['start'])} – {_fmt(b['end'])})" for b in blocks
            ) + ".",
            "priority": "high",
            "requires_approval": True,
        },
    )
    step_task = AgentTask(
        id=new_id(),
        title="Create corresponding tasks",
        description=f"Add a to-do item for {' & '.join(subjects)} preparation.",
        tool=tt.tool_name,
        parameters=tt.parameters,
        requires_approval=True,
        depends_on=[s.id for s in block_steps],
    )
    step_report = AgentTask(
        id=new_id(),
        title="Report completed schedule",
        description="Report the verified schedule and tasks back to you.",
        depends_on=[step_task.id],
    )
    return [step1, step2, step3, step4, *block_steps, step_task, step_report]


def _resolve_target_date(raw_lower: str) -> date:
    now = datetime.now()
    return now.date() if "today" in raw_lower else now.date() + timedelta(days=1)


def _build_smart_study_plan(goal: UserGoal, pref_override: Any | None = None) -> AgentPlan:
    """
    Multi-step smart study plan with conflict detection and slot allocation:
    1. Understand study requirements (reasoning)
    2. Check existing schedule (read)
    3. Check schedule conflicts (read)
    4. Find available study slots (reasoning)
    5..n. Create <SUBJECT> study block for every requested subject (write, approval)
    n+1. Create corresponding tasks (write, approval)
    n+2. Report completed schedule (reasoning)
    """
    raw_lower = goal.goal.lower()
    target_date = _resolve_target_date(raw_lower)
    meeting_t = _parse_meeting(raw_lower)
    meeting_start = datetime.combine(target_date, meeting_t) if meeting_t else None

    if pref_override is not None:
        pref = pref_override
    else:
        try:
            pref = MemoryService().get_preferences()
        except Exception:
            pref = None

    requirements = _parse_study_requirements(goal.goal)
    if not requirements:
        subjects = [
            s.upper() for s in ["dbms", "daa", "os", "cn", "dsa", "math", "ai", "ml"]
            if re.search(rf"\b{s}\b", raw_lower)
        ]
        if not subjects and pref is not None:
            subjects = list(pref.preferred_subjects)
        if not subjects:
            return _clarification_plan(
                goal,
                "Schedule clarification needed",
                "Which subjects should I schedule, and for how long? For example: '2 hours of DBMS and 1 hour of DAA'.",
            )
        session = pref.preferred_session_minutes if pref is not None else 60
        requirements = [(s, session) for s in subjects[:MAX_STUDY_REQUIREMENTS]]

    blocks, clarification, overrode = _allocate_study_blocks(goal, requirements, target_date, meeting_start, pref)
    if clarification is not None:
        return clarification

    tasks = _study_block_steps(blocks, meeting_start, target_date, [])

    day_label = "today" if target_date == datetime.now().date() else "tomorrow"
    summary = f"Study plan for {day_label}: " + "; ".join(
        f"{b['subject']} {_fmt(b['start'])}–{_fmt(b['end'])}" for b in blocks
    ) + "."
    if meeting_start is not None:
        summary += f" Your {_fmt(meeting_start)} meeting is kept free."
    if overrode:
        summary += " (Note: used your explicitly requested time, overriding a saved timing preference.)"
    elif pref is not None and (pref.subject_time_preferences or pref.planning_notes):
        try:
            influences = MemoryService().identify_influencing_preferences(goal.goal, pref)
        except Exception:
            influences = []
        if influences:
            summary += f" (Influenced by: {'; '.join(influences)})"

    return AgentPlan(goal=goal.goal, summary=summary, tasks=tasks, requires_approval=True)


def _build_review_and_plan_revision_plan(goal: UserGoal) -> AgentPlan:
    """
    "Review my schedule, identify free time, plan my DBMS revision, and create tasks."
    Same read-before-write structure as the smart study plan; durations default to
    the saved session length when not stated.
    """
    return _build_smart_study_plan(goal)


def _build_chained_preference_and_study_plan(goal: UserGoal) -> AgentPlan:
    """
    "Remember that I prefer evening study sessions, then plan my preparation for tomorrow."
    Step 1 saves the stated preference (approval required); the study steps depend on it
    and are planned as if the preference were already saved, so one approval covers both.
    """
    updates = _extract_preference_updates(goal.goal)
    if not updates:
        return _build_smart_study_plan(goal)

    try:
        current = MemoryService().get_preferences()
        merged = current.model_dump()
        for k, v in updates.items():
            if k == "subject_time_preferences":
                merged[k] = {**merged.get(k, {}), **v}
            elif k in ("planning_notes", "preferred_subjects"):
                merged[k] = list(dict.fromkeys([*merged.get(k, []), *v]))
            else:
                merged[k] = v
        projected = type(current)(**merged)
    except Exception:
        projected = None

    pref_call = route_tool("update_student_preferences", updates)
    pref_step = AgentTask(
        id=f"plan_task_{uuid.uuid4().hex[:8]}",
        title="Save study preference",
        description="Remember: " + "; ".join(updates.get("planning_notes", [])) if updates.get("planning_notes") else "Save stated study preferences.",
        tool=pref_call.tool_name,
        parameters=pref_call.parameters,
        requires_approval=True,
    )

    study_plan = _build_smart_study_plan(goal, pref_override=projected)
    if not any(t.tool for t in study_plan.tasks):
        # Study part needs clarification: still offer to save the preference.
        return AgentPlan(
            goal=goal.goal,
            summary=(
                "I can save this preference now. To plan study sessions, tell me which subjects "
                "and how long, e.g. '2 hours of DBMS'."
            ),
            tasks=[pref_step],
            requires_approval=True,
        )

    study_plan.tasks[0].depends_on = [pref_step.id]
    return AgentPlan(
        goal=goal.goal,
        summary="Save your preference first, then: " + study_plan.summary,
        tasks=[pref_step, *study_plan.tasks],
        requires_approval=True,
    )


def plan_goal(goal: UserGoal) -> AgentPlan:
    """
    Produce a validated AgentPlan from a UserGoal.
    Never executes tools, never calls executor.
    """
    if not goal.goal or not goal.goal.strip():
        raise ValueError("Goal must contain meaningful text.")

    intent = _detect_intent(goal.goal)

    if intent == "vague":
        task = AgentTask(
            id=f"plan_task_{uuid.uuid4().hex[:8]}",
            title="Clarify request",
            description="Clarify study goal, subjects, duration and preferred time.",
            status="pending",
            tool=None,
            parameters={},
            requires_approval=False,
        )
        return AgentPlan(
            goal=goal.goal,
            summary="Clarification required before specific actions can be planned.",
            tasks=[task],
            requires_approval=False,
        )

    if intent == "smart study planning":
        return _build_smart_study_plan(goal)
    elif intent == "chained preference and study plan":
        return _build_chained_preference_and_study_plan(goal)
    elif intent == "review and plan revision":
        return _build_review_and_plan_revision_plan(goal)
    elif intent == "preference update":
        return _build_preference_update_plan(goal)
    elif intent == "preference listing":
        return _build_preference_listing_plan(goal)
    elif intent == "preference reset":
        return _build_preference_reset_plan(goal)
    elif intent == "study schedule planning":
        return _build_preference_aware_study_plan(goal)
    elif intent == "task creation":
        return _build_task_creation_plan(goal)
    elif intent == "schedule creation":
        return _build_schedule_creation_plan(goal)
    elif intent == "note creation":
        return _build_note_creation_plan(goal)
    elif intent in ("task listing", "schedule listing"):
        return _build_listing_plan(goal, intent)
    elif intent == "note search":
        return _build_search_plan(goal)
    else:
        return _build_general_plan(goal)


MAX_MODEL_TOOL_CALLS = 12


def _normalize_parameters(tool_name: str, raw_params: dict[str, Any]) -> dict[str, Any]:
    """Normalize and convert parameters (e.g. ISO string dates to datetime objects)."""
    params = dict(raw_params)
    # Approval is decided by the server policy, never by model output.
    params.pop("requires_approval", None)
    if tool_name in ("create_schedule", "update_schedule", "get_schedule", "check_schedule_conflict"):
        for field in ("start_time", "end_time"):
            val = params.get(field)
            if isinstance(val, str):
                try:
                    params[field] = datetime.fromisoformat(val)
                except Exception as e:
                    raise PlannerError(f"Invalid ISO datetime string for '{field}': {val}") from e
    elif tool_name == "create_note":
        if "content" in params and "title" not in params:
            content_str = str(params["content"])
            params["title"] = content_str[:30] + ("..." if len(content_str) > 30 else "")
    return params


def plan_goal_with_gemini(
    goal: UserGoal,
    gemini_service: Any,
) -> AgentPlan:
    """
    Generate an AgentPlan using Gemini:
    - Validates user goal.
    - Prompts Gemini for structured JSON plan.
    - Validates all suggested tool calls with the router.
    - Handles clarification requests safely without creating tool calls.
    - Never executes any tool.
    """
    if not goal.goal or not goal.goal.strip():
        raise ValueError("Goal must contain meaningful text.")

    prompt = build_planning_prompt(goal.goal)

    try:
        data = gemini_service.generate_json(prompt)
    except Exception as e:
        raise PlannerError(f"Gemini planning failed: {e}") from e

    if not isinstance(data, dict):
        raise PlannerError("Gemini response is not a JSON object.")

    summary = str(data.get("summary") or f"Plan for: {goal.goal.strip()}")[:500]
    needs_clarification = bool(data.get("needs_clarification", False))
    clarification_question = data.get("clarification_question")

    # Handle clarification
    if needs_clarification:
        question = str(clarification_question or "Please provide more details about your request.")[:300]
        clarification_task = AgentTask(
            id=f"plan_task_{uuid.uuid4().hex[:8]}",
            title="Clarification required",
            description=question,
            status="pending",
            tool=None,
            parameters={},
            requires_approval=False,
        )
        return AgentPlan(
            goal=goal.goal,
            summary=summary,
            tasks=[clarification_task],
            requires_approval=False,
        )

    # Process and validate tool calls through router
    raw_tool_calls = data.get("tool_calls", [])
    raw_tasks = data.get("tasks", [])

    if not isinstance(raw_tool_calls, list):
        raise PlannerError("'tool_calls' must be a list in Gemini response.")
    if len(raw_tool_calls) > MAX_MODEL_TOOL_CALLS:
        raise PlannerError("Gemini proposed too many steps.")
    if not isinstance(raw_tasks, list):
        raw_tasks = []

    validated_tool_calls = []
    for tc in raw_tool_calls:
        if not isinstance(tc, dict):
            raise PlannerError("Invalid tool call entry in Gemini response.")
        tool_name = tc.get("tool_name")
        if not tool_name:
            raise PlannerError("Gemini tool call missing 'tool_name'.")
        raw_params = tc.get("parameters", {})
        if not isinstance(raw_params, dict):
            raise PlannerError(f"Parameters for tool '{tool_name}' must be a dictionary.")

        norm_params = _normalize_parameters(tool_name, raw_params)

        try:
            routed = route_tool(tool_name, norm_params)
        except Exception as e:
            raise PlannerError(f"Gemini suggested invalid tool call '{tool_name}': {e}") from e

        validated_tool_calls.append(routed)

    # Assemble AgentTasks
    agent_tasks: list[AgentTask] = []
    if validated_tool_calls:
        read_ids: list[str] = []
        for i, tc in enumerate(validated_tool_calls):
            matching_task = raw_tasks[i] if i < len(raw_tasks) and isinstance(raw_tasks[i], dict) else {}
            task_id = str(matching_task.get("task_id") or matching_task.get("id") or f"plan_task_{uuid.uuid4().hex[:8]}")[:64]
            description = str(matching_task.get("description") or f"Execute {tc.tool_name}")[:500]
            title = str(matching_task.get("title") or description[:40])[:120]
            mutates = tool_mutates(tc.tool_name)

            agent_tasks.append(
                AgentTask(
                    id=task_id,
                    title=title,
                    description=description,
                    status="pending",
                    tool=tc.tool_name,
                    parameters=tc.parameters,
                    # Writes always require approval, whatever the model said.
                    requires_approval=tc.requires_approval or mutates,
                    # Writes never run unless every earlier read succeeded.
                    depends_on=list(read_ids) if mutates else [],
                )
            )
            if not mutates:
                read_ids.append(task_id)
    elif raw_tasks and isinstance(raw_tasks, list):
        for i, t_info in enumerate(raw_tasks):
            if isinstance(t_info, dict):
                task_id = str(t_info.get("task_id") or t_info.get("id") or f"plan_task_{uuid.uuid4().hex[:8]}")[:64]
                desc = str(t_info.get("description") or "Execute planned step")[:500]
                title = str(t_info.get("title") or desc[:40])[:120]
                agent_tasks.append(
                    AgentTask(
                        id=task_id,
                        title=title,
                        description=desc,
                        status="pending",
                        tool=None,
                        parameters={},
                        requires_approval=False,
                    )
                )

    if not agent_tasks:
        agent_tasks.append(
            AgentTask(
                id=f"plan_task_{uuid.uuid4().hex[:8]}",
                title="Review plan",
                description=summary,
                status="pending",
                tool=None,
                parameters={},
                requires_approval=False,
            )
        )

    requires_approval = any(t.requires_approval for t in agent_tasks)

    return AgentPlan(
        goal=goal.goal,
        summary=summary,
        tasks=agent_tasks,
        requires_approval=requires_approval,
    )


def plan_goal_smart(
    goal: UserGoal,
    gemini_service: Any | None = None,
) -> AgentPlan:
    """
    Route goal planning to GeminiService if provided, otherwise use deterministic fallback.
    Never creates a real Gemini client in tests or when unprovided.
    """
    if gemini_service is not None:
        try:
            return plan_goal_with_gemini(goal, gemini_service)
        except PlannerError:
            # Untrusted/unavailable model output: fall back to deterministic planning.
            return plan_goal(goal)
    return plan_goal(goal)
