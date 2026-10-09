from datetime import datetime
from typing import Any

from models.agent import AgentPlan, AgentTask, ToolResult
from models.memory import StudentPreferences
from services.memory import MemoryService
from services.identity import current_user_id
from services.persistence import get_persistence

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


# How to read back each kind of entity: (persistence getter, id parameter, noun used in messages).
_ENTITIES = {
    "schedule": ("get_event", "event_id", "event"),
    "task": ("get_task", "task_id", "task"),
    "note": ("get_note", "note_id", "note"),
}
# Fields compared after a write (only those the approved parameters actually set).
_CREATE_FIELDS = {"schedule": ("title", "start_time", "end_time"), "task": ("title",), "note": ()}
_UPDATE_FIELDS = {
    "schedule": ("title", "description", "start_time", "end_time", "status"),
    "task": ("title", "status", "priority"),
    "note": ("title", "content", "category"),
}
_PREFERENCE_SCALARS = ("preferred_study_start", "preferred_study_end", "preferred_session_minutes", "preferred_break_minutes")


def _verify_created(kind: str, tool_name: str, parameters: dict[str, Any], result: ToolResult, persistence: Any, user_id: str) -> tuple[bool, str | None]:
    getter, id_param, noun = _ENTITIES[kind]
    res = result.result or {}
    entity_id = res.get("id") or res.get(id_param)
    if not entity_id:
        article = "an" if noun[0] in "aeiou" else "a"
        return False, f"Verification failed: {tool_name} did not return {article} {noun} ID."
    entity = getattr(persistence, getter)(entity_id, user_id=user_id)
    if not entity:
        return False, f"Verification failed: {noun.capitalize()} '{entity_id}' was not found in persistence store."
    bad = _fields_match(entity, parameters, _CREATE_FIELDS[kind])
    if bad:
        return False, f"Verification failed: saved {noun} field '{bad}' does not match the approved value."
    return True, None


def _verify_updated(kind: str, parameters: dict[str, Any], persistence: Any, user_id: str) -> tuple[bool, str | None]:
    getter, id_param, noun = _ENTITIES[kind]
    entity = getattr(persistence, getter)(parameters.get(id_param), user_id=user_id)
    if not entity:
        return False, f"Verification failed: Updated {noun} '{parameters.get(id_param)}' not found."
    bad = _fields_match(entity, parameters, _UPDATE_FIELDS[kind])
    if bad:
        return False, f"Verification failed: {noun} field '{bad}' was not updated."
    return True, None


def _verify_deleted(kind: str, parameters: dict[str, Any], persistence: Any, user_id: str) -> tuple[bool, str | None]:
    getter, id_param, noun = _ENTITIES[kind]
    if getattr(persistence, getter)(parameters.get(id_param), user_id=user_id) is not None:
        return False, f"Verification failed: Deleted {noun} '{parameters.get(id_param)}' is still present."
    return True, None


def _verify_preferences_updated(parameters: dict[str, Any], persistence: Any, user_id: str) -> tuple[bool, str | None]:
    pref = MemoryService(persistence=persistence).get_preferences(user_id=user_id)
    if not pref:
        return False, "Verification failed: Preferences could not be read back."
    for f in _PREFERENCE_SCALARS:
        if parameters.get(f) is not None and getattr(pref, f) != parameters[f]:
            return False, f"Verification failed: preference '{f}' was not saved."
    for subj, when in (parameters.get("subject_time_preferences") or {}).items():
        if pref.subject_time_preferences.get(subj) != when:
            return False, f"Verification failed: timing preference for '{subj}' was not saved."
    for note in parameters.get("planning_notes") or []:
        if note and note.strip() not in pref.planning_notes:
            return False, "Verification failed: planning note was not saved."
    return True, None


def _verify_preferences_reset(persistence: Any, user_id: str) -> tuple[bool, str | None]:
    pref = MemoryService(persistence=persistence).get_preferences(user_id=user_id)
    if pref.model_dump(exclude={"updated_at"}) != StudentPreferences().model_dump(exclude={"updated_at"}):
        return False, "Verification failed: preferences were not reset to defaults."
    return True, None


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
    action, _, kind = tool_name.partition("_")
    try:
        if tool_name == "update_student_preferences":
            return _verify_preferences_updated(parameters, persistence, user_id)
        if tool_name == "reset_student_preferences":
            return _verify_preferences_reset(persistence, user_id)
        if kind in _ENTITIES:
            if action == "create":
                return _verify_created(kind, tool_name, parameters, result, persistence, user_id)
            if action == "update":
                return _verify_updated(kind, parameters, persistence, user_id)
            if action == "delete":
                return _verify_deleted(kind, parameters, persistence, user_id)
    except Exception as e:
        return False, f"Verification error: {type(e).__name__}"
    return True, None
