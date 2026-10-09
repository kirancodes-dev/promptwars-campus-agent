from typing import Any
import uuid

from models.agent import AgentTask
from services.identity import current_user_id
from services.persistence import (
    EntityNotFoundError,
    get_persistence,
)


class TaskNotFoundError(KeyError):
    """Raised when a requested task ID is not found."""
    pass


class _TaskDictProxy(dict):
    """Transparent dict proxy exposing tasks from active persistence for backward-compatibility."""

    def __getitem__(self, key: str) -> AgentTask:
        task = get_persistence().get_task(key, user_id=current_user_id())
        if task is None:
            raise KeyError(key)
        return task

    def __setitem__(self, key: str, value: AgentTask) -> None:
        get_persistence().create_task(value, user_id=current_user_id())

    def __delitem__(self, key: str) -> None:
        try:
            get_persistence().delete_task(key, user_id=current_user_id())
        except EntityNotFoundError:
            raise KeyError(key)

    def __contains__(self, key: Any) -> bool:
        if not isinstance(key, str):
            return False
        return get_persistence().get_task(key, user_id=current_user_id()) is not None

    def __len__(self) -> int:
        return len(get_persistence().get_tasks(user_id=current_user_id()))

    def __iter__(self):
        return iter(t.id for t in get_persistence().get_tasks(user_id=current_user_id()))

    def values(self):
        return get_persistence().get_tasks(user_id=current_user_id())

    def keys(self):
        return [t.id for t in get_persistence().get_tasks(user_id=current_user_id())]

    def items(self):
        return [(t.id, t) for t in get_persistence().get_tasks(user_id=current_user_id())]

    def get(self, key: str, default: Any = None) -> Any:
        task = get_persistence().get_task(key, user_id=current_user_id())
        return task if task is not None else default

    def clear(self) -> None:
        get_persistence().clear_tasks(user_id=current_user_id())


# In-memory proxy exposing active persistence layer
_tasks: dict[str, AgentTask] = _TaskDictProxy()


def clear_tasks() -> None:
    """Clear all tasks from active storage."""
    get_persistence().clear_tasks(user_id=current_user_id())


def create_task(
    title: str,
    description: str | None = None,
    priority: str = "medium",
    tool: str | None = None,
    requires_approval: bool = False,
    parameters: dict[str, Any] | None = None,
) -> AgentTask:
    """Create a new task, persist it, and return the AgentTask."""
    if priority not in ("low", "medium", "high"):
        raise ValueError(f"Invalid task priority: '{priority}'")

    task_id = f"task_{uuid.uuid4().hex[:8]}"
    task = AgentTask(
        id=task_id,
        title=title,
        description=description,
        status="pending",
        priority=priority,
        tool=tool,
        parameters=parameters or {},
        requires_approval=requires_approval,
    )
    return get_persistence().create_task(task, user_id=current_user_id())


def get_tasks(status: str | None = None) -> list[AgentTask]:
    """Retrieve all tasks from persistence, optionally filtered by status."""
    return get_persistence().get_tasks(status=status, user_id=current_user_id())


def get_task(task_id: str) -> AgentTask:
    """Retrieve an existing task by ID or raise TaskNotFoundError."""
    task = get_persistence().get_task(task_id, user_id=current_user_id())
    if task is None:
        raise TaskNotFoundError(f"Task with ID '{task_id}' not found.")
    return task


def update_task(
    task_id: str,
    status: str | None = None,
    title: str | None = None,
    priority: str | None = None,
    description: str | None = None,
) -> AgentTask:
    """Update an existing task by ID and validate changes using AgentTask."""
    existing = get_persistence().get_task(task_id, user_id=current_user_id())
    if existing is None:
        raise TaskNotFoundError(f"Task with ID '{task_id}' not found.")

    updates: dict[str, Any] = {}
    if status is not None:
        updates["status"] = status
    if title is not None:
        updates["title"] = title
    if priority is not None:
        updates["priority"] = priority
    if description is not None:
        updates["description"] = description

    # Validate full model representation before storing
    current_dict = existing.model_dump()
    current_dict.update(updates)
    AgentTask(**current_dict)

    try:
        return get_persistence().update_task(task_id, updates, user_id=current_user_id())
    except EntityNotFoundError:
        raise TaskNotFoundError(f"Task with ID '{task_id}' not found.")


def delete_task(task_id: str) -> dict[str, Any]:
    """Delete a task by ID. Raises TaskNotFoundError if not found."""
    try:
        get_persistence().delete_task(task_id, user_id=current_user_id())
        return {"success": True, "task_id": task_id}
    except EntityNotFoundError:
        raise TaskNotFoundError(f"Task with ID '{task_id}' not found.")
