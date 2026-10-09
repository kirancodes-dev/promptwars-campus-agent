import uuid
from typing import Any, Callable

try:
    from agent.router import ToolNotFoundError, get_tool, validate_parameters
    from models.agent import ApprovalRequest, ToolCall, ToolResult
    from tools.notes import (
        create_note,
        delete_note,
        get_notes,
        search_notes,
        update_note,
    )
    from tools.schedule import (
        check_schedule_conflict,
        create_schedule,
        delete_schedule,
        get_schedule,
        update_schedule,
    )
    from tools.tasks import (
        create_task,
        delete_task,
        get_tasks,
        update_task,
    )
    from tools.memory import (
        get_student_preferences,
        reset_student_preferences,
        update_student_preferences,
    )
except ImportError:
    from backend.agent.router import ToolNotFoundError, get_tool, validate_parameters
    from backend.models.agent import ApprovalRequest, ToolCall, ToolResult
    from backend.tools.notes import (
        create_note,
        delete_note,
        get_notes,
        search_notes,
        update_note,
    )
    from backend.tools.schedule import (
        check_schedule_conflict,
        create_schedule,
        delete_schedule,
        get_schedule,
        update_schedule,
    )
    from backend.tools.tasks import (
        create_task,
        delete_task,
        get_tasks,
        update_task,
    )
    from backend.tools.memory import (
        get_student_preferences,
        reset_student_preferences,
        update_student_preferences,
    )

# Explicit mapping of registered tool names to python functions
_TOOL_FUNCTION_MAP: dict[str, Callable[..., Any]] = {
    # Task tools
    "create_task": create_task,
    "get_tasks": get_tasks,
    "update_task": update_task,
    "delete_task": delete_task,
    # Schedule tools
    "create_schedule": create_schedule,
    "get_schedule": get_schedule,
    "update_schedule": update_schedule,
    "delete_schedule": delete_schedule,
    "check_schedule_conflict": check_schedule_conflict,
    # Note tools
    "create_note": create_note,
    "get_notes": get_notes,
    "update_note": update_note,
    "delete_note": delete_note,
    "search_notes": search_notes,
    # Memory and preference tools
    "get_student_preferences": get_student_preferences,
    "update_student_preferences": update_student_preferences,
    "reset_student_preferences": reset_student_preferences,
}


def _get_tool_function(tool_name: str) -> Callable[..., Any]:
    """Return the registered Python function for the tool or raise ToolNotFoundError."""
    if tool_name not in _TOOL_FUNCTION_MAP:
        raise ToolNotFoundError(f"Tool function for '{tool_name}' not found.")
    return _TOOL_FUNCTION_MAP[tool_name]


def execute_tool(tool_call: ToolCall, approved: bool = False) -> ToolResult:
    """
    Execute a tool safely through the validation and approval layer:
    - Validates tool existence and parameters via the router.
    - Enforces approval constraints if required.
    - Catches all exceptions and converts them into ToolResult.
    - Never exposes raw exceptions to the caller.
    """
    # 1. Validate tool through the router
    try:
        tool_def = get_tool(tool_call.tool_name)
        validated_params = validate_parameters(tool_call.tool_name, tool_call.parameters)
    except Exception as e:
        return ToolResult(
            tool_name=tool_call.tool_name,
            success=False,
            result=None,
            error=str(e),
        )

    # 2. Check approval requirement
    requires_approval = tool_call.requires_approval or tool_def.requires_approval
    if requires_approval and not approved:
        return ToolResult(
            tool_name=tool_call.tool_name,
            success=False,
            result={"requires_approval": True},
            error="Approval required to execute this tool.",
        )

    # 3. Retrieve mapped Python function
    try:
        func = _get_tool_function(tool_call.tool_name)
    except Exception as e:
        return ToolResult(
            tool_name=tool_call.tool_name,
            success=False,
            result=None,
            error=str(e),
        )

    # 4. Safely execute the tool and format output payload
    try:
        raw_result = func(**validated_params)

        if hasattr(raw_result, "model_dump"):
            payload = raw_result.model_dump()
        elif isinstance(raw_result, dict):
            payload = {}
            for k, v in raw_result.items():
                if isinstance(v, list):
                    payload[k] = [
                        item.model_dump() if hasattr(item, "model_dump") else item
                        for item in v
                    ]
                elif hasattr(v, "model_dump"):
                    payload[k] = v.model_dump()
                else:
                    payload[k] = v
        elif isinstance(raw_result, list):
            serialized_items = [
                item.model_dump() if hasattr(item, "model_dump") else item
                for item in raw_result
            ]
            payload = {"items": serialized_items}
            if tool_call.tool_name == "get_tasks":
                payload["tasks"] = serialized_items
            elif tool_call.tool_name == "get_schedule":
                payload["events"] = serialized_items
            elif tool_call.tool_name in ("get_notes", "search_notes"):
                payload["notes"] = serialized_items
        else:
            payload = {"data": raw_result}

        return ToolResult(
            tool_name=tool_call.tool_name,
            success=True,
            result=payload,
            error=None,
        )
    except Exception as e:
        return ToolResult(
            tool_name=tool_call.tool_name,
            success=False,
            result=None,
            error=str(e),
        )


def create_approval_request(tool_call: ToolCall) -> ApprovalRequest:
    """Create an ApprovalRequest model in pending status."""
    approval_id = f"appr_{uuid.uuid4().hex[:8]}"
    action = f"Execute tool '{tool_call.tool_name}'"
    return ApprovalRequest(
        approval_id=approval_id,
        action=action,
        tool_name=tool_call.tool_name,
        parameters=tool_call.parameters,
        status="pending",
    )


def approve_request(approval_request: ApprovalRequest) -> ApprovalRequest:
    """Return an updated ApprovalRequest with status='approved'."""
    return approval_request.model_copy(update={"status": "approved"})


def approve_and_execute(approval_request: ApprovalRequest) -> ToolResult:
    """Execute the approved tool call only if the approval status is 'approved'."""
    if approval_request.status != "approved":
        return ToolResult(
            tool_name=approval_request.tool_name,
            success=False,
            result=None,
            error=f"Cannot execute approval request with status '{approval_request.status}'. Status must be 'approved'.",
        )

    tool_call = ToolCall(
        tool_name=approval_request.tool_name,
        parameters=approval_request.parameters,
        requires_approval=True,
    )
    return execute_tool(tool_call, approved=True)


def reject_approval(approval_request: ApprovalRequest) -> ApprovalRequest:
    """Return an updated ApprovalRequest marked as rejected without executing the tool."""
    return approval_request.model_copy(update={"status": "rejected"})
