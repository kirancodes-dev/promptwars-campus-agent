"""
Turn untrusted Gemini output into a validated AgentPlan. Never executes anything.

Defence in depth:
1. The response must match a strict schema (types, allowed fields, bounded sizes).
2. Every tool name must be in the server-side allow-list and every parameter is validated
   by the router, exactly as for the built-in planner.
3. Approval flags from the model are discarded; data-changing tools always require approval.
4. Any failure raises PlannerError so the orchestrator falls back to the deterministic planner.
"""

from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

from agent.planning.common import PlannerError, new_step_id
from agent.router import route_tool, tool_mutates
from models.agent import AgentPlan, AgentTask, UserGoal
from services.gemini import GeminiResponseError, build_planning_prompt

MAX_MODEL_TOOL_CALLS = 12


class ModelTask(BaseModel):
    model_config = ConfigDict(extra="ignore")

    task_id: str | None = Field(default=None, max_length=64, validation_alias=AliasChoices("task_id", "id"))
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=1000)


class ModelToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(..., min_length=1, max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ModelPlan(BaseModel):
    """The only response shape accepted from the model."""

    model_config = ConfigDict(extra="ignore")

    summary: str | None = Field(default=None, max_length=2000)
    needs_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=1000)
    tasks: list[ModelTask] = Field(default_factory=list, max_length=MAX_MODEL_TOOL_CALLS)
    tool_calls: list[ModelToolCall] = Field(default_factory=list, max_length=MAX_MODEL_TOOL_CALLS)


def _normalize_parameters(tool_name: str, raw_params: dict[str, Any]) -> dict[str, Any]:
    """Convert ISO date strings to datetimes and drop model-supplied approval flags."""
    params = dict(raw_params)
    params.pop("requires_approval", None)  # approval is decided by server policy only
    if tool_name in ("create_schedule", "update_schedule", "get_schedule", "check_schedule_conflict"):
        for field in ("start_time", "end_time"):
            val = params.get(field)
            if isinstance(val, str):
                try:
                    params[field] = datetime.fromisoformat(val)
                except ValueError as e:
                    raise PlannerError(f"Invalid ISO datetime string for '{field}': {val[:40]}", reason="invalid_output") from e
    elif tool_name == "create_note" and "content" in params and "title" not in params:
        content = str(params["content"])
        params["title"] = content[:30] + ("..." if len(content) > 30 else "")
    return params


def _parse_response(data: Any) -> ModelPlan:
    if not isinstance(data, dict):
        raise PlannerError("Gemini response is not a JSON object.", reason="invalid_output")
    try:
        return ModelPlan.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(x) for x in first.get("loc", ())) or "response"
        raise PlannerError(f"Gemini response failed schema validation at '{where}'.", reason="invalid_output") from None


def plan_goal_with_gemini(goal: UserGoal, gemini_service: Any) -> AgentPlan:
    """Ask Gemini for a structured plan and validate every part of it. Never executes tools."""
    if not goal.goal or not goal.goal.strip():
        raise ValueError("Goal must contain meaningful text.")

    try:
        data = gemini_service.generate_json(build_planning_prompt(goal.goal))
    except GeminiResponseError as e:
        # The service answered, but with empty or non-JSON output.
        raise PlannerError(f"Gemini returned unusable output: {type(e).__name__}", reason="invalid_output") from e
    except Exception as e:
        # Timeouts, quota (429), authentication and network errors all land here.
        raise PlannerError(f"Gemini planning failed: {type(e).__name__}", reason="unavailable") from e

    plan = _parse_response(data)
    summary = (plan.summary or f"Plan for: {goal.goal.strip()}")[:500]

    if plan.needs_clarification:
        question = (plan.clarification_question or "Please provide more details about your request.")[:300]
        task = AgentTask(id=new_step_id(), title="Clarification required", description=question)
        return AgentPlan(goal=goal.goal, summary=summary, tasks=[task], requires_approval=False)

    routed_calls = []
    for call in plan.tool_calls:
        params = _normalize_parameters(call.tool_name, call.parameters)
        try:
            routed_calls.append(route_tool(call.tool_name, params))
        except Exception as e:
            raise PlannerError(f"Gemini suggested invalid tool call '{call.tool_name[:64]}': {e}", reason="invalid_output") from e

    agent_tasks: list[AgentTask] = []
    read_ids: list[str] = []
    for i, call in enumerate(routed_calls):
        meta = plan.tasks[i] if i < len(plan.tasks) else ModelTask()
        description = (meta.description or f"Execute {call.tool_name}")[:500]
        mutates = tool_mutates(call.tool_name)
        task_id = meta.task_id or new_step_id()
        agent_tasks.append(AgentTask(
            id=task_id,
            title=(meta.title or description[:40])[:120],
            description=description,
            tool=call.tool_name,
            parameters=call.parameters,
            # Writes always require approval and never run unless every earlier read succeeded.
            requires_approval=call.requires_approval or mutates,
            depends_on=list(read_ids) if mutates else [],
        ))
        if not mutates:
            read_ids.append(task_id)

    if not routed_calls:
        for meta in plan.tasks:
            description = (meta.description or "Execute planned step")[:500]
            agent_tasks.append(AgentTask(id=meta.task_id or new_step_id(), title=(meta.title or description[:40])[:120], description=description))
    if not agent_tasks:
        agent_tasks.append(AgentTask(id=new_step_id(), title="Review plan", description=summary))

    return AgentPlan(
        goal=goal.goal,
        summary=summary,
        tasks=agent_tasks,
        requires_approval=any(t.requires_approval for t in agent_tasks),
    )
