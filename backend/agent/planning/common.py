"""Small helpers shared by the planning modules."""

from datetime import datetime
import uuid

from models.agent import AgentPlan, AgentTask, UserGoal


class PlannerError(ValueError):
    """
    Raised when the planner encounters invalid input or planning failures.
    reason: "invalid_input" | "unavailable" (AI service failed) | "invalid_output" (AI plan rejected).
    """

    def __init__(self, message: str = "", reason: str = "invalid_input") -> None:
        super().__init__(message)
        self.reason = reason


def new_step_id() -> str:
    return f"plan_task_{uuid.uuid4().hex[:8]}"


def clarification_plan(goal: UserGoal, title: str, question: str, **plan_fields) -> AgentPlan:
    """A plan with a single question for the student and no tool calls (nothing executes)."""
    task = AgentTask(id=new_step_id(), title=title, description=question, tool=None, parameters={})
    return AgentPlan(goal=goal.goal, summary=question, tasks=[task], requires_approval=False, **plan_fields)


def fmt_time(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def fmt_day(dt) -> str:
    return dt.strftime("%a %d %b").replace(" 0", " ")


def duration_label(minutes: int) -> str:
    """'2-hour' / '90-minute' (used as an adjective in messages)."""
    return f"{minutes // 60}-hour" if minutes % 60 == 0 else f"{minutes}-minute"


def duration_text(minutes: int) -> str:
    """'2 hours' / '1 hour' / '90 minutes'."""
    hours, rest = divmod(minutes, 60)
    hour_text = f"{hours} hour{'s' if hours != 1 else ''}"
    if rest == 0:
        return hour_text
    return f"{hour_text} {rest} minutes" if hours else f"{minutes} minutes"
