"""Plan builders for single-action intents (tasks, notes, schedule entries, listings, preferences)."""

from datetime import datetime, timedelta
import re
import uuid

from agent.planning.common import PlannerError
from agent.planning.preferences_text import extract_preference_updates
from agent.router import route_tool
from models.agent import AgentPlan, AgentTask, UserGoal


def build_task_creation_plan(goal: UserGoal) -> AgentPlan:
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


def build_schedule_creation_plan(goal: UserGoal) -> AgentPlan:
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


def build_note_creation_plan(goal: UserGoal) -> AgentPlan:
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


def build_listing_plan(goal: UserGoal, intent: str) -> AgentPlan:
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


def build_search_plan(goal: UserGoal) -> AgentPlan:
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


def build_general_plan(goal: UserGoal) -> AgentPlan:
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


def build_preference_update_plan(goal: UserGoal) -> AgentPlan:
    """Build plan to update student preferences with approval."""
    updates = extract_preference_updates(goal.goal)
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


def build_preference_listing_plan(goal: UserGoal) -> AgentPlan:
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


def build_preference_reset_plan(goal: UserGoal) -> AgentPlan:
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
