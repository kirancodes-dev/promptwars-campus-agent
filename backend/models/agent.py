from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator

from .workflow import WorkflowRecord

TaskStatus = Literal["pending", "in_progress", "completed", "failed", "rejected"]
ApprovalStatus = Literal["pending", "approved", "rejected"]
ScheduleStatus = Literal["scheduled", "completed", "cancelled"]
ExecutionStatus = Literal[
    "planned",
    "waiting_approval",
    "executing",
    "completed",
    "failed",
    "needs_clarification",
    "rejected",
]


class UserGoal(BaseModel):
    goal: str = Field(..., description="The objective or request specified by the user")
    context: str | None = Field(default=None, description="Optional additional context or constraints")
    priority: str | None = Field(default=None, description="Optional priority level")
    requested_at: datetime | None = Field(default=None, description="Timestamp when the goal was requested")


class AgentTask(BaseModel):
    id: str = Field(..., description="Unique identifier for the task")
    title: str = Field(..., description="Short title describing the task")
    description: str | None = Field(default=None, description="Detailed explanation of the task")
    status: TaskStatus = Field(default="pending", description="Current status of the task")
    priority: str = Field(default="medium", description="Priority level of the task")
    tool: str | None = Field(default=None, description="Name of the tool needed to execute the task")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Parameters passed to the tool")
    requires_approval: bool = Field(default=False, description="Whether execution requires human approval")
    depends_on: list[str] = Field(default_factory=list, description="IDs of tasks that must execute before this task")


class AgentPlan(BaseModel):
    goal: str = Field(..., description="User goal this plan aims to achieve")
    summary: str = Field(..., description="High-level summary of the execution plan")
    tasks: list[AgentTask] = Field(default_factory=list, description="Ordered list of agent tasks")
    requires_approval: bool = Field(default=False, description="Whether any task in the plan requires human approval")


class ToolCall(BaseModel):
    tool_name: str = Field(..., description="Name of the tool to invoke")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Parameters to pass to the tool")
    requires_approval: bool = Field(default=False, description="Whether this invocation requires approval")


class ToolResult(BaseModel):
    tool_name: str = Field(..., description="Name of the tool that was executed")
    success: bool = Field(..., description="Whether the tool execution was successful")
    result: dict[str, Any] | None = Field(default=None, description="Result payload if execution succeeded")
    error: str | None = Field(default=None, description="Error message if execution failed")


class ApprovalRequest(BaseModel):
    approval_id: str = Field(..., description="Unique identifier for the approval request")
    action: str = Field(..., description="Description of the action requiring approval")
    tool_name: str = Field(..., description="Name of the tool associated with the action")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Parameters associated with the action")
    status: ApprovalStatus = Field(default="pending", description="Current status of the approval request")
    batch_id: str | None = Field(default=None, description="Batch identifier for multi-step approval")
    actions_summary: list[str] = Field(default_factory=list, description="Summary descriptions of all actions in the batch")
    affected_entities: dict[str, list[str]] = Field(default_factory=dict, description="Categorized affected entities (e.g. tasks, events, preferences)")
    step_id: str | None = Field(default=None, description="Workflow step this approval covers")
    title: str | None = Field(default=None, description="Human-readable step title")
    description: str | None = Field(default=None, description="Human-readable explanation of the change")
    payload_hash: str | None = Field(default=None, description="SHA-256 of the exact reviewed actions; binds the approval to them")
    expires_at: datetime | None = Field(default=None, description="When this approval stops being valid")


class ScheduleEvent(BaseModel):
    id: str = Field(..., description="Unique identifier for the schedule event")
    title: str = Field(..., description="Title of the schedule event")
    description: str | None = Field(default=None, description="Optional description of the schedule event")
    start_time: datetime = Field(..., description="Start timestamp of the event")
    end_time: datetime = Field(..., description="End timestamp of the event")
    status: ScheduleStatus = Field(default="scheduled", description="Status of the scheduled event")
    requires_approval: bool = Field(default=False, description="Whether the event requires human approval")

    @property
    def event_id(self) -> str:
        """Alias property for compatibility with event_id naming."""
        return self.id

    @model_validator(mode="after")
    def validate_time_range(self) -> "ScheduleEvent":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class Note(BaseModel):
    id: str = Field(..., description="Unique identifier for the note")
    title: str = Field(..., description="Title of the note")
    content: str = Field(..., description="Text content of the note")
    category: str = Field(default="general", description="Category of the note")
    created_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when the note was created",
    )
    updated_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when the note was last updated",
    )


# Alias NoteItem for Note
NoteItem = Note


class AgentExecutionResult(BaseModel):
    goal: str = Field(..., description="The user goal that was processed")
    plan: AgentPlan = Field(..., description="The generated plan for the goal")
    results: list[ToolResult] = Field(
        default_factory=list, description="Tool execution results"
    )
    status: ExecutionStatus = Field(
        ..., description="Current status of the agent execution"
    )
    requires_approval: bool = Field(
        default=False, description="Whether execution requires human approval"
    )
    clarification_question: str | None = Field(
        default=None,
        description="Clarification question if the goal needs more information",
    )
    approval_id: str | None = Field(
        default=None,
        description="Approval ID for pending approval action",
    )
    approval_requests: list[ApprovalRequest] = Field(
        default_factory=list,
        description="Pending approval requests if waiting for approval",
    )
    verified: bool = Field(
        default=True,
        description="Whether state was verified post-execution",
    )
    succeeded_actions: list[str] = Field(
        default_factory=list,
        description="List of successfully executed and verified action descriptions or tool names",
    )
    failed_actions: list[str] = Field(
        default_factory=list,
        description="List of failed action descriptions or tool names",
    )
    unresolved_actions: list[str] = Field(
        default_factory=list,
        description="List of actions that could not execute due to prerequisite failures",
    )
    skipped_actions: list[str] = Field(
        default_factory=list,
        description="Actions that were intentionally not executed (e.g. rejected)",
    )
    workflow: WorkflowRecord | None = Field(
        default=None,
        description="Structured step-by-step workflow record with statuses, verification and next action",
    )
    planner_mode: str | None = Field(
        default=None,
        description="Planner used: gemini, deterministic, deterministic_fallback, or custom",
    )
    planner_note: str | None = Field(
        default=None,
        description="User-facing explanation when a fallback planner was used",
    )


class ApprovalResponse(BaseModel):
    approval_id: str = Field(..., description="The approval request ID")
    status: str = Field(..., description="Approval status (e.g. approved, rejected)")
    action: str = Field(..., description="Description of the action")
    tool_name: str = Field(..., description="Tool name for the action")
    success: bool = Field(default=True, description="Whether the approval action succeeded")
    tool_result: ToolResult | None = Field(
        default=None, description="Result of executing the approved tool"
    )
    result: dict[str, Any] | None = Field(
        default=None, description="Result payload if executed"
    )
    execution_result: AgentExecutionResult | None = Field(
        default=None, description="Updated execution result"
    )
