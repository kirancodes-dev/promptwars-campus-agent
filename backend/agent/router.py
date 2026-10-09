from datetime import datetime, timedelta
import re
from typing import Any
from pydantic import BaseModel, Field

from models.agent import ToolCall


class ToolDefinition(BaseModel):
    name: str = Field(..., description="Unique name of the tool")
    description: str = Field(..., description="Description of the tool functionality")
    requires_approval: bool = Field(default=False, description="Whether the tool requires approval by default")
    parameter_names: list[str] = Field(default_factory=list, description="Allowed parameter names for the tool")
    required_parameters: list[str] = Field(default_factory=list, description="Required parameter names for the tool")
    mutates: bool = Field(default=False, description="Whether the tool changes stored user data (always approval-gated by the agent pipeline)")


class ToolNotFoundError(KeyError, ValueError):
    """Raised when a requested tool name is not registered."""
    pass


class MissingParameterError(ValueError):
    """Raised when required parameters are missing for a tool."""
    pass


class UnknownParameterError(ValueError):
    """Raised when unknown parameters are passed to a tool."""
    pass


class InvalidParameterError(ValueError):
    """Raised when a parameter value has the wrong type, format, or size."""
    pass


_MAX_TEXT = {"title": 200, "description": 2000, "content": 10000, "query": 200, "category": 50, "status": 30}
_ID_FIELDS = ("task_id", "event_id", "note_id")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_TIME_FIELDS = ("start_time", "end_time")
MAX_EVENT_DURATION = timedelta(hours=24)


def _as_datetime(name: str, value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    raise InvalidParameterError(f"Parameter '{name}' must be an ISO 8601 date-time.")


def _validate_values(tool_name: str, parameters: dict[str, Any]) -> None:
    for name, limit in _MAX_TEXT.items():
        if name in parameters and parameters[name] is not None:
            if not isinstance(parameters[name], str):
                raise InvalidParameterError(f"Parameter '{name}' must be text.")
            if len(parameters[name]) > limit:
                raise InvalidParameterError(f"Parameter '{name}' is too long (max {limit} characters).")
    if "title" in parameters and isinstance(parameters["title"], str) and not parameters["title"].strip():
        raise InvalidParameterError("Parameter 'title' cannot be empty.")
    for name in _ID_FIELDS:
        if name in parameters and not (isinstance(parameters[name], str) and _ID_PATTERN.match(parameters[name])):
            raise InvalidParameterError(f"Parameter '{name}' is not a valid ID.")
    if "priority" in parameters and parameters["priority"] not in ("low", "medium", "high"):
        raise InvalidParameterError("Parameter 'priority' must be low, medium, or high.")
    times = {n: _as_datetime(n, parameters[n]) for n in _TIME_FIELDS if parameters.get(n) is not None}
    if len(times) == 2:
        start, end = times["start_time"], times["end_time"]
        if (start.tzinfo is None) != (end.tzinfo is None):
            raise InvalidParameterError("start_time and end_time must both include or both omit a timezone.")
        if end <= start:
            raise InvalidParameterError("end_time must be after start_time.")
        if tool_name in ("create_schedule", "update_schedule") and end - start > MAX_EVENT_DURATION:
            raise InvalidParameterError("An event cannot be longer than 24 hours.")
    if tool_name == "reset_student_preferences" and parameters.get("confirmation") is not True:
        raise InvalidParameterError("Resetting preferences requires confirmation=true.")


_TOOL_REGISTRY: dict[str, ToolDefinition] = {
    # Task Tools
    "create_task": ToolDefinition(
        name="create_task",
        mutates=True,
        description="Create a new task.",
        requires_approval=False,
        parameter_names=["title", "description", "priority", "tool", "requires_approval"],
        required_parameters=["title"],
    ),
    "get_tasks": ToolDefinition(
        name="get_tasks",
        description="Retrieve existing tasks.",
        requires_approval=False,
        parameter_names=["status"],
        required_parameters=[],
    ),
    "update_task": ToolDefinition(
        name="update_task",
        mutates=True,
        description="Update an existing task.",
        requires_approval=False,
        parameter_names=["task_id", "status", "title", "priority"],
        required_parameters=["task_id"],
    ),
    "delete_task": ToolDefinition(
        name="delete_task",
        mutates=True,
        description="Delete an existing task.",
        requires_approval=True,
        parameter_names=["task_id"],
        required_parameters=["task_id"],
    ),
    # Schedule Tools
    "create_schedule": ToolDefinition(
        name="create_schedule",
        mutates=True,
        description="Create a scheduled event.",
        requires_approval=False,
        parameter_names=["title", "start_time", "end_time", "description", "requires_approval"],
        required_parameters=["title", "start_time", "end_time"],
    ),
    "get_schedule": ToolDefinition(
        name="get_schedule",
        description="Retrieve scheduled events.",
        requires_approval=False,
        parameter_names=["start_time", "end_time"],
        required_parameters=[],
    ),
    "update_schedule": ToolDefinition(
        name="update_schedule",
        mutates=True,
        description="Update an existing scheduled event.",
        requires_approval=False,
        parameter_names=["event_id", "title", "description", "start_time", "end_time", "status"],
        required_parameters=["event_id"],
    ),
    "delete_schedule": ToolDefinition(
        name="delete_schedule",
        mutates=True,
        description="Delete a scheduled event.",
        requires_approval=True,
        parameter_names=["event_id"],
        required_parameters=["event_id"],
    ),
    "check_schedule_conflict": ToolDefinition(
        name="check_schedule_conflict",
        description="Check whether a requested time overlaps an existing scheduled event.",
        requires_approval=False,
        parameter_names=["start_time", "end_time"],
        required_parameters=["start_time", "end_time"],
    ),
    # Note Tools
    "create_note": ToolDefinition(
        name="create_note",
        mutates=True,
        description="Create a note.",
        requires_approval=False,
        parameter_names=["title", "content", "category"],
        required_parameters=["title", "content"],
    ),
    "get_notes": ToolDefinition(
        name="get_notes",
        description="Retrieve notes.",
        requires_approval=False,
        parameter_names=["category"],
        required_parameters=[],
    ),
    "update_note": ToolDefinition(
        name="update_note",
        mutates=True,
        description="Update an existing note.",
        requires_approval=False,
        parameter_names=["note_id", "title", "content", "category"],
        required_parameters=["note_id"],
    ),
    "delete_note": ToolDefinition(
        name="delete_note",
        mutates=True,
        description="Delete a note.",
        requires_approval=True,
        parameter_names=["note_id"],
        required_parameters=["note_id"],
    ),
    "search_notes": ToolDefinition(
        name="search_notes",
        description="Search notes by title or content.",
        requires_approval=False,
        parameter_names=["query"],
        required_parameters=["query"],
    ),
    # Memory and Preference Tools
    "get_student_preferences": ToolDefinition(
        name="get_student_preferences",
        description="Retrieve current student study preferences and memory summary.",
        requires_approval=False,
        parameter_names=[],
        required_parameters=[],
    ),
    "update_student_preferences": ToolDefinition(
        name="update_student_preferences",
        mutates=True,
        description="Update student study preferences, timings, or constraints.",
        requires_approval=True,
        parameter_names=[
            "preferred_study_start",
            "preferred_study_end",
            "preferred_session_minutes",
            "preferred_break_minutes",
            "preferred_study_days",
            "preferred_subjects",
            "subject_time_preferences",
            "planning_notes",
            "requires_approval",
        ],
        required_parameters=[],
    ),
    "reset_student_preferences": ToolDefinition(
        name="reset_student_preferences",
        mutates=True,
        description="Reset student preferences to default settings with confirmation.",
        requires_approval=True,
        parameter_names=["confirmation", "requires_approval"],
        required_parameters=["confirmation"],
    ),
}


def get_available_tools() -> list[ToolDefinition]:
    """Return all registered tool definitions."""
    return list(_TOOL_REGISTRY.values())


def get_tool(tool_name: str) -> ToolDefinition:
    """Return the definition for a tool, or raise ToolNotFoundError."""
    if tool_name not in _TOOL_REGISTRY:
        raise ToolNotFoundError(f"Tool '{tool_name}' is not registered.")
    return _TOOL_REGISTRY[tool_name]


def tool_mutates(tool_name: str) -> bool:
    """Return True if the registered tool changes stored user data. Unknown tools are treated as mutating."""
    tool = _TOOL_REGISTRY.get(tool_name)
    return True if tool is None else tool.mutates


def validate_tool_name(tool_name: str) -> bool:
    """Return True only if the tool exists in registry."""
    return tool_name in _TOOL_REGISTRY


def validate_parameters(tool_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """
    Validate that:
    - The tool exists.
    - Required parameters are present.
    - Unknown parameters are rejected.
    - Parameters are returned unchanged after validation.
    Does not execute the tool.
    """
    tool = get_tool(tool_name)
    if not isinstance(parameters, dict):
        raise InvalidParameterError(f"Parameters for tool '{tool_name}' must be an object.")

    missing = [param for param in tool.required_parameters if param not in parameters]
    if missing:
        raise MissingParameterError(
            f"Tool '{tool_name}' missing required parameter(s): {', '.join(missing)}"
        )

    unknown = [param for param in parameters if param not in tool.parameter_names]
    if unknown:
        raise UnknownParameterError(
            f"Tool '{tool_name}' received unknown parameter(s): {', '.join(unknown)}"
        )

    _validate_values(tool_name, parameters)
    return parameters


def route_tool(tool_name: str, parameters: dict[str, Any]) -> ToolCall:
    """
    Route a tool call without executing:
    - Validate tool name.
    - Validate parameters.
    - Return a ToolCall Pydantic model with tool_name, parameters, requires_approval.
    """
    tool = get_tool(tool_name)
    validated_params = validate_parameters(tool_name, parameters)

    requires_approval = bool(
        validated_params.get("requires_approval", tool.requires_approval)
    )

    return ToolCall(
        tool_name=tool_name,
        parameters=validated_params,
        requires_approval=requires_approval,
    )
