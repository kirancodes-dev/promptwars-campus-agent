from datetime import datetime
from pydantic import BaseModel, Field


class AuditLogEntry(BaseModel):
    id: str = Field(..., description="Unique identifier for the audit log entry")
    goal: str = Field(..., description="Sanitized summary of the user goal")
    plan_steps: list[str] = Field(
        default_factory=list, description="Titles or summaries of the planned steps"
    )
    approval_status: str = Field(
        ...,
        description="Approval status at conclusion (e.g. approved, rejected, not_required, waiting_approval)",
    )
    tools_executed: list[str] = Field(
        default_factory=list, description="Names of tools that were executed"
    )
    execution_status: str = Field(
        ...,
        description="Final execution status (e.g. completed, failed, needs_clarification)",
    )
    error_summary: str | None = Field(
        default=None, description="Sanitized, safe error message if failure occurred"
    )
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when the execution completed",
    )
    user_id: str = Field(
        default="demo-user",
        description="User identifier for isolation and audit tracking",
    )
    event_type: str = Field(
        default="execution_summary",
        description="Event kind, e.g. workflow_started, step_started, approval_granted, tool_failed, verification_succeeded",
    )
    workflow_id: str | None = Field(default=None, description="Workflow this event belongs to")
    step_id: str | None = Field(default=None, description="Workflow step this event belongs to")
    tool: str | None = Field(default=None, description="Tool involved in this event, if any")
