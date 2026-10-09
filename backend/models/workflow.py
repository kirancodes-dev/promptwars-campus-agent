from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field

StepStatus = Literal[
    "planned",
    "waiting_approval",
    "running",
    "completed",
    "failed",
    "skipped",
    "blocked",
    "rejected",
]

WorkflowStatus = Literal[
    "planned",
    "waiting_approval",
    "running",
    "completed",
    "partially_completed",
    "failed",
    "rejected",
    "needs_clarification",
]

StepKind = Literal["read", "write", "reasoning"]


class StepVerification(BaseModel):
    checked: bool = Field(default=False, description="Whether the resulting state was read back")
    passed: bool | None = Field(default=None, description="Outcome of the read-back check, if performed")
    detail: str | None = Field(default=None, description="Short explanation of the verification outcome")


class WorkflowStep(BaseModel):
    step_id: str = Field(..., description="Plan task ID this step executes")
    order: int = Field(..., ge=0, description="Zero-based position in the plan")
    title: str
    description: str | None = None
    kind: StepKind = Field(..., description="read = inspects data, write = changes data, reasoning = no tool")
    tool: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    status: StepStatus = "planned"
    attempts: int = Field(default=0, ge=0)
    retry_eligible: bool = Field(
        default=False,
        description="Only read-only steps may be retried automatically; writes never are",
    )
    result: dict[str, Any] | None = None
    error: str | None = None
    verification: StepVerification = Field(default_factory=StepVerification)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class WorkflowRecord(BaseModel):
    workflow_id: str
    goal: str
    status: WorkflowStatus = "planned"
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    planner_mode: str = Field(default="deterministic", description="gemini, deterministic, or deterministic_fallback")
    planner_note: str | None = Field(default=None, description="Why a fallback planner was used, if it was")
    approval_id: str | None = None
    steps: list[WorkflowStep] = Field(default_factory=list)
    summary: str | None = None
    next_action: str | None = Field(default=None, description="What the user should do next")

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for step in self.steps:
            out[step.status] = out.get(step.status, 0) + 1
        return out
