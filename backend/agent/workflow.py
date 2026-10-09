from datetime import datetime
from typing import Any

try:
    from models.agent import AgentPlan, AgentTask, ToolResult
    from models.memory import StudentPreferences
    from services.memory import MemoryService
    from services.identity import current_user_id
    from services.persistence import DEFAULT_USER_ID, get_persistence
except ImportError:
    from backend.services.identity import current_user_id
    from backend.models.agent import AgentPlan, AgentTask, ToolResult
    from backend.models.memory import StudentPreferences
    from backend.services.memory import MemoryService
    from backend.services.persistence import DEFAULT_USER_ID, get_persistence

READ_TOOLS = {
    "get_tasks",
    "get_schedule",
    "check_schedule_conflict",
    "get_notes",
    "search_notes",
    "get_student_preferences",
}

WRITE_TOOLS = {
    "create_task",
    "update_task",
    "delete_task",
    "create_schedule",
    "update_schedule",
    "delete_schedule",
    "create_note",
    "update_note",
    "delete_note",
    "update_student_preferences",
    "reset_student_preferences",
}


SCHEDULE_TASK_WRITES = {
    "create_task",
    "update_task",
    "delete_task",
    "create_schedule",
    "update_schedule",
    "delete_schedule",
}


def validate_plan_dependencies(plan: AgentPlan) -> tuple[bool, str | None]:
    """
    Validate plan dependencies and enforce the Read-Before-Write execution policy.
    Checks:
    1. Dependencies reference valid earlier tasks.
    2. No cyclic dependencies.
    3. Read-before-write: Dependent writes cannot execute before prerequisite reads.
    4. If both read and write tools exist for a domain, reads must precede writes.
    """
    if not plan or not plan.tasks:
        return True, None

    task_map: dict[str, AgentTask] = {t.id: t for t in plan.tasks}
    task_order: dict[str, int] = {t.id: i for i, t in enumerate(plan.tasks)}

    if len(task_map) != len(plan.tasks):
        seen: set[str] = set()
        dup = next(t.id for t in plan.tasks if t.id in seen or seen.add(t.id))
        return False, f"Duplicate step ID '{dup}' in plan."

    # 1. Validate dependency existence and acyclicity
    for task in plan.tasks:
        curr_idx = task_order[task.id]
        for dep_id in task.depends_on:
            if dep_id == task.id:
                return False, f"Task '{task.id}' depends on itself."
            if dep_id not in task_map:
                return False, f"Task '{task.id}' depends on non-existent task '{dep_id}'."
            dep_idx = task_order[dep_id]
            if dep_idx >= curr_idx:
                return False, f"Task '{task.id}' has a forward or cyclic dependency on task '{dep_id}'."

    # Cycle detection via DFS
    visited: set[str] = set()
    rec_stack: set[str] = set()

    def has_cycle(tid: str) -> bool:
        visited.add(tid)
        rec_stack.add(tid)
        for dep in task_map[tid].depends_on:
            if dep not in visited:
                if has_cycle(dep):
                    return True
            elif dep in rec_stack:
                return True
        rec_stack.remove(tid)
        return False

    for task in plan.tasks:
        if task.id not in visited:
            if has_cycle(task.id):
                return False, f"Circular dependency detected involving task '{task.id}'."

    # 2. Enforce Read-Before-Write policy
    # If a plan mixes read and write operations for scheduling, reads must occur before writes
    first_write_idx: int | None = None
    last_read_idx: int | None = None

    # Only schedule/task writes must follow schedule/task inspections; e.g. saving a
    # preference before reading the schedule is legitimate.
    for i, t in enumerate(plan.tasks):
        if t.tool in SCHEDULE_TASK_WRITES:
            if first_write_idx is None:
                first_write_idx = i
        elif t.tool in READ_TOOLS:
            last_read_idx = i

    if first_write_idx is not None and last_read_idx is not None:
        if first_write_idx < last_read_idx:
            write_task = plan.tasks[first_write_idx]
            read_task = plan.tasks[last_read_idx]
            # If the read task is a prerequisite inspection (e.g. get_schedule/check_schedule_conflict)
            if read_task.tool in ("get_schedule", "check_schedule_conflict", "get_tasks"):
                return False, (
                    f"Read-before-write violation: Write operation '{write_task.title}' "
                    f"is scheduled before inspection operation '{read_task.title}'."
                )

    return True, None


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, datetime) or isinstance(b, datetime):
        try:
            a_dt = a if isinstance(a, datetime) else datetime.fromisoformat(str(a))
            b_dt = b if isinstance(b, datetime) else datetime.fromisoformat(str(b))
            return a_dt == b_dt
        except ValueError:
            return False
    return a == b


def _fields_match(entity: Any, parameters: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    """Return the first requested field whose stored value differs, or None if all match."""
    for f in fields:
        if f in parameters and parameters[f] is not None:
            if not _same(getattr(entity, f, None), parameters[f]):
                return f
    return None


def verify_tool_execution(
    tool_name: str,
    parameters: dict[str, Any],
    result: ToolResult,
    user_id: str | None = None,
) -> tuple[bool, str | None]:
    """
    Verify actual persistence state after a write tool execution by reading it back.
    Never reports success based only on a planned action or a returned object.
    """
    if not result.success:
        return False, result.error or f"Tool '{tool_name}' failed execution."

    user_id = user_id or current_user_id()
    persistence = get_persistence()
    res_dict = result.result or {}

    try:
        if tool_name == "create_schedule":
            event_id = res_dict.get("id") or res_dict.get("event_id")
            if not event_id:
                return False, "Verification failed: create_schedule did not return an event ID."
            event = persistence.get_event(event_id, user_id=user_id)
            if not event:
                return False, f"Verification failed: Event '{event_id}' was not found in persistence store."
            bad = _fields_match(event, parameters, ("title", "start_time", "end_time"))
            if bad:
                return False, f"Verification failed: saved event field '{bad}' does not match the approved value."
            return True, None

        if tool_name == "update_schedule":
            event = persistence.get_event(parameters.get("event_id"), user_id=user_id)
            if not event:
                return False, f"Verification failed: Updated event '{parameters.get('event_id')}' not found."
            bad = _fields_match(event, parameters, ("title", "description", "start_time", "end_time", "status"))
            if bad:
                return False, f"Verification failed: event field '{bad}' was not updated."
            return True, None

        if tool_name == "delete_schedule":
            if persistence.get_event(parameters.get("event_id"), user_id=user_id) is not None:
                return False, f"Verification failed: Deleted event '{parameters.get('event_id')}' is still present."
            return True, None

        if tool_name == "create_task":
            task_id = res_dict.get("id") or res_dict.get("task_id")
            if not task_id:
                return False, "Verification failed: create_task did not return a task ID."
            task = persistence.get_task(task_id, user_id=user_id)
            if not task:
                return False, f"Verification failed: Task '{task_id}' was not found in persistence store."
            bad = _fields_match(task, parameters, ("title",))
            if bad:
                return False, f"Verification failed: saved task field '{bad}' does not match the approved value."
            return True, None

        if tool_name == "update_task":
            task = persistence.get_task(parameters.get("task_id"), user_id=user_id)
            if not task:
                return False, f"Verification failed: Updated task '{parameters.get('task_id')}' not found."
            bad = _fields_match(task, parameters, ("title", "status", "priority"))
            if bad:
                return False, f"Verification failed: task field '{bad}' was not updated."
            return True, None

        if tool_name == "delete_task":
            if persistence.get_task(parameters.get("task_id"), user_id=user_id) is not None:
                return False, f"Verification failed: Deleted task '{parameters.get('task_id')}' is still present."
            return True, None

        if tool_name == "create_note":
            note_id = res_dict.get("id") or res_dict.get("note_id")
            if not note_id:
                return False, "Verification failed: create_note did not return a note ID."
            if not persistence.get_note(note_id, user_id=user_id):
                return False, f"Verification failed: Note '{note_id}' was not found in persistence store."
            return True, None

        if tool_name == "update_note":
            note = persistence.get_note(parameters.get("note_id"), user_id=user_id)
            if not note:
                return False, f"Verification failed: Updated note '{parameters.get('note_id')}' not found."
            bad = _fields_match(note, parameters, ("title", "content", "category"))
            if bad:
                return False, f"Verification failed: note field '{bad}' was not updated."
            return True, None

        if tool_name == "delete_note":
            if persistence.get_note(parameters.get("note_id"), user_id=user_id) is not None:
                return False, f"Verification failed: Deleted note '{parameters.get('note_id')}' is still present."
            return True, None

        if tool_name == "update_student_preferences":
            pref = MemoryService(persistence=persistence).get_preferences(user_id=user_id)
            if not pref:
                return False, "Verification failed: Preferences could not be read back."
            for f in ("preferred_study_start", "preferred_study_end", "preferred_session_minutes", "preferred_break_minutes"):
                if f in parameters and parameters[f] is not None and getattr(pref, f) != parameters[f]:
                    return False, f"Verification failed: preference '{f}' was not saved."
            for subj, when in (parameters.get("subject_time_preferences") or {}).items():
                if pref.subject_time_preferences.get(subj) != when:
                    return False, f"Verification failed: timing preference for '{subj}' was not saved."
            for note in parameters.get("planning_notes") or []:
                if note and note.strip() not in pref.planning_notes:
                    return False, "Verification failed: planning note was not saved."
            return True, None

        if tool_name == "reset_student_preferences":
            pref = MemoryService(persistence=persistence).get_preferences(user_id=user_id)
            defaults = StudentPreferences()
            if pref.model_dump(exclude={"updated_at"}) != defaults.model_dump(exclude={"updated_at"}):
                return False, "Verification failed: preferences were not reset to defaults."
            return True, None

    except Exception as e:
        return False, f"Verification error: {type(e).__name__}"

    return True, None
