import hashlib
import logging
import os
from datetime import datetime
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

try:
    from agent.orchestrator import AgentOrchestrator
    from agent.planner import PlannerError
    from agent.router import route_tool
    from models.agent import (
        AgentExecutionResult,
        AgentPlan,
        AgentTask,
        ApprovalRequest,
        ApprovalResponse,
        ToolResult,
        UserGoal,
    )
    from models.audit import AuditLogEntry
    from models.memory import StudentPreferences, StudentPreferencesUpdate
    from models.workflow import WorkflowRecord
    from services.approvals import ApprovalError, StagedApproval, approval_store
    from services.audit import AuditService
    from services.identity import current_user_id, get_identity_mode
    from services.memory import MemoryService
    from services.persistence import get_persistence, get_persistence_status
except ImportError:
    from backend.agent.orchestrator import AgentOrchestrator
    from backend.agent.planner import PlannerError
    from backend.agent.router import route_tool
    from backend.models.agent import (
        AgentExecutionResult,
        AgentPlan,
        AgentTask,
        ApprovalRequest,
        ApprovalResponse,
        ToolResult,
        UserGoal,
    )
    from backend.models.audit import AuditLogEntry
    from backend.models.memory import StudentPreferences, StudentPreferencesUpdate
    from backend.models.workflow import WorkflowRecord
    from backend.services.approvals import ApprovalError, StagedApproval, approval_store
    from backend.services.audit import AuditService
    from backend.services.identity import current_user_id, get_identity_mode
    from backend.services.memory import MemoryService
    from backend.services.persistence import get_persistence, get_persistence_status

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_GOAL_CHARS = 1000

# Kept for backward compatibility with tests and tooling that clear approvals.
_PENDING_APPROVALS = approval_store


def clear_pending_approvals() -> None:
    """Clear all pending approvals (tests)."""
    approval_store.clear()


_gemini_cache: dict[tuple[str, str], Any] = {}


def get_gemini_service_safe() -> Any | None:
    """
    Return a GeminiService when GEMINI_API_KEY is configured, otherwise None.
    Never exposes secrets or raises. The client is cached per key/model.
    """
    try:
        try:
            from services.gemini import create_gemini_service
        except ImportError:
            from backend.services.gemini import create_gemini_service
        key = os.getenv("GEMINI_API_KEY", "").strip()
        model = os.getenv("GEMINI_MODEL", "").strip()
        cache_key = (hashlib.sha256(key.encode("utf-8")).hexdigest(), model)
        if cache_key not in _gemini_cache:
            _gemini_cache.clear()
            _gemini_cache[cache_key] = create_gemini_service()
        return _gemini_cache[cache_key]
    except Exception:
        return None


def get_orchestrator() -> AgentOrchestrator:
    """Dependency injection provider for AgentOrchestrator."""
    return AgentOrchestrator(gemini_service=get_gemini_service_safe())


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message[:300])


def _approval_http_error(err: ApprovalError) -> HTTPException:
    return HTTPException(status_code=err.status_code, detail=str(err))


def _save_workflow(workflow: WorkflowRecord, user_id: str) -> bool:
    """Workflow history is informational: a failure is logged, never hidden as success of a write."""
    try:
        get_persistence().save_workflow(workflow, user_id=user_id)
        return True
    except Exception as e:
        logger.warning("Could not save workflow history (%s).", type(e).__name__)
        return False


# --------------------------------------------------------------------------- request models


class PlanRequest(BaseModel):
    goal: str = Field(..., max_length=MAX_GOAL_CHARS, description="The user goal to plan")


class RunRequest(BaseModel):
    goal: str = Field(..., max_length=MAX_GOAL_CHARS, description="The user goal to execute")
    approved: bool = Field(
        default=False,
        description="Deprecated and ignored. Protected actions always require POST /approve.",
    )


class ApprovalActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str | None = Field(default=None, max_length=80, description="ID of the pending approval request")
    goal: str | None = Field(default=None, max_length=MAX_GOAL_CHARS, description="Goal associated with the approval")
    approved: bool = Field(default=True, description="Approval confirmation")
    payload_hash: str | None = Field(
        default=None, max_length=64, description="Hash of the reviewed actions (from the approval request)"
    )
    parameters: dict[str, Any] | None = Field(
        default=None, description="Optional parameters sent by client (rejected if tampered)"
    )


class RejectActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str | None = Field(default=None, max_length=80, description="ID of the pending approval request to reject")
    goal: str | None = Field(default=None, max_length=MAX_GOAL_CHARS, description="Goal associated with the rejection")


class StatusResponse(BaseModel):
    service: str = "CampusPilot AI"
    status: str = "healthy"
    agent: str = "ready"
    planner: str = "deterministic"
    planner_mode: str = "deterministic"
    ai_available: bool = False
    ai_message: str = ""
    persistence_mode: str = "memory"
    persistence_durable: bool = False
    persistence_message: str = ""
    identity_mode: str = "session"
    identity_message: str = ""


# --------------------------------------------------------------------------- helpers


def _fmt_range(start: Any, end: Any) -> str:
    try:
        s = start if isinstance(start, datetime) else datetime.fromisoformat(str(start))
        e = end if isinstance(end, datetime) else datetime.fromisoformat(str(end))
    except ValueError:
        return f"{start} – {end}"
    end_text = e.strftime("%I:%M %p").lstrip("0") if s.date() == e.date() else _fmt_time(e)
    return f"{_fmt_time(s)} – {end_text}"


def _fmt_time(value: Any) -> str:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if isinstance(value, datetime):
        return value.strftime("%a %d %b, ") + value.strftime("%I:%M %p").lstrip("0")
    return str(value)


def describe_action(task: AgentTask) -> str:
    """Plain-language description of a protected action for the approval card."""
    p = task.parameters
    tool = task.tool
    if tool == "create_schedule":
        return f"Add '{p.get('title')}' to your schedule ({_fmt_range(p.get('start_time'), p.get('end_time'))})"
    if tool == "update_schedule":
        return f"Change schedule event {p.get('event_id')}"
    if tool == "delete_schedule":
        return f"Delete schedule event {p.get('event_id')}"
    if tool == "create_task":
        return f"Create task '{p.get('title')}'" + (f" (priority: {p['priority']})" if p.get("priority") else "")
    if tool == "update_task":
        return f"Update task {p.get('task_id')}"
    if tool == "delete_task":
        return f"Delete task {p.get('task_id')}"
    if tool == "create_note":
        return f"Save note '{p.get('title')}'"
    if tool == "update_note":
        return f"Update note {p.get('note_id')}"
    if tool == "delete_note":
        return f"Delete note {p.get('note_id')}"
    if tool == "update_student_preferences":
        fields = [k for k in p if k != "requires_approval"]
        return "Save study preferences: " + ", ".join(f.replace("preferred_", "").replace("_", " ") for f in fields)
    if tool == "reset_student_preferences":
        return "Reset all study preferences to defaults"
    return task.title


def _affected_entities(tasks: list[AgentTask]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"events": [], "tasks": [], "notes": [], "preferences": []}
    for t in tasks:
        label = str(t.parameters.get("title") or t.title)
        if t.tool in ("create_schedule", "update_schedule", "delete_schedule"):
            out["events"].append(label)
        elif t.tool in ("create_task", "update_task", "delete_task"):
            out["tasks"].append(label)
        elif t.tool in ("create_note", "update_note", "delete_note"):
            out["notes"].append(label)
        elif t.tool in ("update_student_preferences", "reset_student_preferences"):
            out["preferences"].append(t.title)
    return {k: v for k, v in out.items() if v}


def _stage(
    goal: str,
    plan: AgentPlan,
    workflow: WorkflowRecord,
    user_id: str,
    kind: str = "workflow",
) -> StagedApproval | None:
    protected_ids = [s.step_id for s in workflow.steps if s.requires_approval and s.status == "waiting_approval"]
    if not protected_ids:
        return None
    by_id = {t.id: t for t in plan.tasks}
    protected_tasks = [by_id[i] for i in protected_ids if i in by_id]
    batch_id = approval_store.new_id()
    summary = [describe_action(t) for t in protected_tasks]
    affected = _affected_entities(protected_tasks)
    requests = [
        ApprovalRequest(
            approval_id=approval_store.new_id(),
            action=describe_action(t),
            tool_name=t.tool,
            parameters=t.parameters,
            status="pending",
            batch_id=batch_id,
            actions_summary=summary,
            affected_entities=affected,
            step_id=t.id,
            title=t.title,
            description=t.description,
        )
        for t in protected_tasks
    ]
    staged = approval_store.stage(
        user_id=user_id,
        goal=goal,
        plan=plan,
        workflow=workflow,
        protected_step_ids=[t.id for t in protected_tasks],
        approval_requests=requests,
        approval_id=batch_id,
        kind=kind,
    )
    for req in requests:
        req.payload_hash = staged.payload_hash
        req.expires_at = staged.expires_at
    workflow.approval_id = batch_id
    return staged


def _resolve_approval(approval_id: str | None, goal: str | None, user_id: str) -> StagedApproval:
    if approval_id:
        return approval_store.get(approval_id, user_id)
    if goal:
        return approval_store.find_pending_by_goal(goal, user_id)
    raise _bad_request("Either 'approval_id' or 'goal' must be provided.")


# --------------------------------------------------------------------------- agent endpoints


@router.post(
    "/plan",
    response_model=AgentPlan,
    summary="Plan a goal",
    description="Generate a structured AgentPlan for a user goal without executing any tools.",
)
def plan_agent(
    payload: PlanRequest,
    orchestrator: AgentOrchestrator = Depends(get_orchestrator),
) -> AgentPlan:
    if not payload.goal or not payload.goal.strip():
        raise _bad_request("Goal cannot be empty.")
    try:
        return orchestrator.plan(UserGoal(goal=payload.goal))
    except (ValueError, PlannerError) as e:
        raise _bad_request(str(e))
    except Exception:
        logger.exception("Planning failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal planning error occurred.",
        )


@router.post(
    "/run",
    response_model=AgentExecutionResult,
    summary="Execute a goal",
    description=(
        "Plan a goal, run read-only steps, and stage every data-changing step for approval. "
        "The 'approved' field is ignored: protected actions only run through POST /approve."
    ),
)
def run_agent(
    payload: RunRequest,
    orchestrator: AgentOrchestrator = Depends(get_orchestrator),
) -> AgentExecutionResult:
    if not payload.goal or not payload.goal.strip():
        raise _bad_request("Goal cannot be empty.")
    user_id = current_user_id()

    try:
        # Never forward a client-supplied approval flag.
        result = orchestrator.run(UserGoal(goal=payload.goal), approved=False, user_id=user_id)
    except (ValueError, PlannerError) as e:
        raise _bad_request(str(e))
    except Exception:
        logger.exception("Run failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal execution error occurred.",
        )

    if result.status == "waiting_approval" and result.workflow is not None:
        staged = _stage(result.goal, result.plan, result.workflow, user_id)
        if staged is not None:
            result = result.model_copy(
                update={"approval_id": staged.approval_id, "approval_requests": staged.approval_requests}
            )
    if result.workflow is not None:
        _save_workflow(result.workflow, user_id)
    return result


@router.post(
    "/approve",
    response_model=ApprovalResponse,
    summary="Approve a pending action",
    description=(
        "Approve and execute exactly the actions that were staged and reviewed. "
        "Approvals are single-use, expire, and belong to the session that created them."
    ),
)
def approve_action(
    payload: ApprovalActionRequest,
    orchestrator: AgentOrchestrator = Depends(get_orchestrator),
) -> ApprovalResponse:
    if not payload.approved:
        raise _bad_request("'approved' must be true to approve an action. Use /reject to reject.")
    user_id = current_user_id()

    try:
        staged = _resolve_approval(payload.approval_id, payload.goal, user_id)
        approval_store.claim(
            staged,
            "executing",
            expected_hash=payload.payload_hash,
            client_parameters=payload.parameters,
        )
    except ApprovalError as e:
        raise _approval_http_error(e)

    workflow = staged.workflow
    events: list[dict] = []
    orchestrator._event(events, "approval_granted", workflow, detail=f"{len(staged.protected_step_ids)} action(s)")
    try:
        results = orchestrator.run_workflow(staged.plan, workflow, approved=True, user_id=user_id, events=events)
    except Exception:
        logger.exception("Approved workflow crashed")
        results = [ToolResult(tool_name="workflow", success=False, error="Execution stopped unexpectedly. Check your schedule before retrying.")]
        workflow.status = "failed"
        workflow.next_action = "Execution stopped unexpectedly. Some changes may have been saved; review your data before retrying."
    approval_store.finish(staged, "approved")

    terminal = {
        "completed": "workflow_completed",
        "partially_completed": "workflow_partially_completed",
        "failed": "workflow_failed",
    }
    if workflow.status in terminal:
        orchestrator._event(events, terminal[workflow.status], workflow)
    orchestrator.flush_events(events, user_id)
    _save_workflow(workflow, user_id)

    approved_requests = [r.model_copy(update={"status": "approved"}) for r in staged.approval_requests]
    exec_result = orchestrator.build_result(staged.goal, staged.plan, workflow, results, True).model_copy(
        update={"approval_id": staged.approval_id, "approval_requests": approved_requests}
    )

    try:
        AuditService().record_execution(
            goal=staged.goal,
            plan=staged.plan,
            approval_status="approved",
            results=results,
            execution_status=exec_result.status,
            error=next((r.error for r in results if not r.success), None),
            user_id=user_id,
            workflow_id=workflow.workflow_id,
        )
    except Exception as e:
        logger.warning("Audit summary failed (%s).", type(e).__name__)

    protected_tools = {t.id: t.tool for t in staged.plan.tasks if t.id in staged.protected_step_ids}
    protected_results = [r for r in results if r.tool_name in protected_tools.values()]
    primary_res = next((r for r in results if not r.success), None) or (protected_results[0] if protected_results else (results[0] if results else None))
    primary_req = staged.approval_requests[0] if staged.approval_requests else None

    return ApprovalResponse(
        approval_id=staged.approval_id,
        status="approved",
        action=primary_req.action if primary_req else "Batch execution",
        tool_name=primary_req.tool_name if primary_req else (primary_res.tool_name if primary_res else "batch"),
        success=exec_result.status == "completed",
        tool_result=primary_res,
        result=primary_res.result if primary_res else None,
        execution_result=exec_result,
    )


@router.post(
    "/reject",
    response_model=ApprovalResponse,
    summary="Reject a pending action",
    description="Reject staged actions without executing them.",
)
def reject_action(payload: RejectActionRequest) -> ApprovalResponse:
    user_id = current_user_id()
    try:
        staged = _resolve_approval(payload.approval_id, payload.goal, user_id)
        approval_store.claim(staged, "rejected")
    except ApprovalError as e:
        raise _approval_http_error(e)

    workflow = staged.workflow
    for step in workflow.steps:
        if step.status in ("waiting_approval", "planned"):
            step.status = "rejected" if step.requires_approval else "skipped"
    workflow.status = "rejected"
    workflow.next_action = "You rejected the proposed changes. Nothing was changed."
    workflow.updated_at = datetime.now()

    orchestrator = AgentOrchestrator()
    events: list[dict] = []
    orchestrator._event(events, "approval_rejected", workflow, status="rejected")
    orchestrator.flush_events(events, user_id)
    _save_workflow(workflow, user_id)

    rejected_requests = [r.model_copy(update={"status": "rejected"}) for r in staged.approval_requests]
    rejected_tools = [r.tool_name for r in staged.approval_requests]
    exec_result = AgentExecutionResult(
        goal=staged.goal,
        plan=staged.plan,
        results=[],
        status="rejected",
        requires_approval=True,
        approval_id=staged.approval_id,
        approval_requests=rejected_requests,
        skipped_actions=rejected_tools,
        verified=False,
        workflow=workflow,
        planner_mode=workflow.planner_mode,
        planner_note=workflow.planner_note,
    )

    try:
        AuditService().record_execution(
            goal=staged.goal,
            plan=staged.plan,
            approval_status="rejected",
            results=[],
            execution_status="rejected",
            user_id=user_id,
            workflow_id=workflow.workflow_id,
        )
    except Exception as e:
        logger.warning("Audit summary failed (%s).", type(e).__name__)

    primary_req = staged.approval_requests[0] if staged.approval_requests else None
    return ApprovalResponse(
        approval_id=staged.approval_id,
        status="rejected",
        action=primary_req.action if primary_req else "Batch action",
        tool_name=primary_req.tool_name if primary_req else "batch",
        success=False,
        tool_result=None,
        result=None,
        execution_result=exec_result,
    )


@router.get(
    "/audit",
    response_model=list[AuditLogEntry],
    summary="Get execution audit history",
    description="Retrieve this session's sanitized audit log entries, newest first.",
)
def get_audit_trail(limit: int = Query(default=50, ge=1, le=200)) -> list[AuditLogEntry]:
    try:
        return AuditService().get_logs(limit=limit)
    except Exception:
        raise HTTPException(status_code=503, detail="Audit history is temporarily unavailable.")


@router.get(
    "/workflows",
    response_model=list[WorkflowRecord],
    summary="Recent workflows",
    description="This session's recent workflows with per-step status, newest first.",
)
def list_workflows(limit: int = Query(default=10, ge=1, le=50)) -> list[WorkflowRecord]:
    try:
        return get_persistence().list_workflows(limit=limit, user_id=current_user_id())
    except Exception:
        raise HTTPException(status_code=503, detail="Workflow history is temporarily unavailable.")


@router.get(
    "/workflows/{workflow_id}",
    response_model=WorkflowRecord,
    summary="Get one workflow",
)
def get_workflow(workflow_id: str) -> WorkflowRecord:
    if len(workflow_id) > 64:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    wf = get_persistence().get_workflow(workflow_id, user_id=current_user_id())
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return wf


@router.get(
    "/status",
    response_model=StatusResponse,
    summary="Get agent status",
    description="Operational health, planner mode, storage durability, and identity mode. Never includes secrets.",
)
def get_status() -> StatusResponse:
    ai = get_gemini_service_safe() is not None
    planner_mode = "gemini" if ai else "deterministic"
    storage = get_persistence_status()
    identity = get_identity_mode()
    return StatusResponse(
        planner=planner_mode,
        planner_mode=planner_mode,
        ai_available=ai,
        ai_message=(
            "Gemini AI planning is configured. If a request fails, the built-in planner is used instead."
            if ai
            else "AI planning is not configured. CampusPilot uses its built-in rule-based planner."
        ),
        persistence_mode=storage["mode"],
        persistence_durable=storage["durable"],
        persistence_message=storage["message"],
        identity_mode=identity,
        identity_message=(
            "Private anonymous session: your data is only visible to this browser."
            if identity == "session"
            else "Shared demo mode: all visitors share one demo user. Local development only."
        ),
    )


# --------------------------------------------------------------------------- memory & preferences


class MemoryResponse(BaseModel):
    preferences: dict[str, Any] = Field(..., description="Active student study preferences")
    summary: str = Field(..., description="Human-readable memory summary")
    status: str = Field(default="ok")
    durable: bool = Field(default=False, description="True only when saved to durable storage")
    storage_message: str = Field(default="")
    verified: bool | None = Field(default=None, description="Set on writes: saved values were read back and matched")


class MemoryProposeRequest(BaseModel):
    updates: dict[str, Any] = Field(..., description="Proposed updates to student preferences")


class PreferenceChange(BaseModel):
    field: str
    before: Any = None
    after: Any = None


class MemoryProposeResponse(BaseModel):
    proposed_updates: dict[str, Any]
    approval_id: str
    action: str
    requires_approval: bool = True
    status: str = "pending"
    payload_hash: str | None = None
    expires_at: datetime | None = None
    changes: list[PreferenceChange] = Field(default_factory=list)


class MemoryUpdateRequest(BaseModel):
    updates: dict[str, Any] = Field(..., description="Updates to apply to student preferences")
    approved: bool = Field(
        default=False,
        description=(
            "true = the student submitted this edit directly in the preferences form (applied now, "
            "validated and verified). false = stage it as an approval request."
        ),
    )


class MemoryResetRequest(BaseModel):
    confirm: bool = Field(..., description="Explicit confirmation required to reset preferences")


class MemoryResetResponse(BaseModel):
    status: str = "ok"
    message: str
    preferences: dict[str, Any]
    summary: str
    verified: bool = True
    durable: bool = False


def _validated_updates(updates: dict[str, Any]) -> tuple[dict[str, Any], StudentPreferences, StudentPreferences]:
    """Validate a partial update and the merged result. Returns (clean_updates, before, after)."""
    if not updates:
        raise _bad_request("No preference changes were provided.")
    try:
        clean = StudentPreferencesUpdate.model_validate(updates).model_dump(exclude_unset=True, exclude_none=True)
    except ValidationError as e:
        first = e.errors()[0]
        loc = ".".join(str(x) for x in first.get("loc", ())) or "preferences"
        raise _bad_request(f"Invalid preference value for '{loc}': {first.get('msg', 'invalid value')}")
    unknown = sorted(set(updates) - set(StudentPreferencesUpdate.model_fields))
    if unknown:
        raise _bad_request(f"Unknown preference field(s): {', '.join(unknown)}")
    service = MemoryService()
    before = service.get_preferences()
    merged = before.model_dump()
    merged.update(clean)
    try:
        after = StudentPreferences(**merged)
    except ValidationError as e:
        raise _bad_request(f"Invalid preferences: {e.errors()[0].get('msg', 'invalid value')}")
    return clean, before, after


def _changes(before: StudentPreferences, clean: dict[str, Any]) -> list[PreferenceChange]:
    b = before.model_dump()
    return [PreferenceChange(field=k, before=b.get(k), after=v) for k, v in clean.items() if b.get(k) != v]


@router.get(
    "/memory",
    response_model=MemoryResponse,
    summary="Get student preferences",
    description="Retrieve the current saved student study preferences and memory summary.",
)
def get_memory() -> MemoryResponse:
    service = MemoryService()
    try:
        pref = service.get_preferences()
        summary = service.get_memory_summary()
    except Exception:
        raise HTTPException(status_code=503, detail="Preferences could not be loaded. Storage is unavailable.")
    storage = get_persistence_status()
    return MemoryResponse(
        preferences=pref.model_dump(),
        summary=summary,
        status="ok",
        durable=storage["durable"],
        storage_message=storage["message"],
    )


@router.get(
    "/memory/summary",
    summary="Get memory summary",
    description="Retrieve a human-readable summary of student study preferences.",
)
def get_memory_summary_endpoint() -> dict[str, str]:
    try:
        summary = MemoryService().get_memory_summary()
    except Exception:
        raise HTTPException(status_code=503, detail="Preferences could not be loaded. Storage is unavailable.")
    return {"summary": summary, "status": "ok"}


@router.post(
    "/memory/propose",
    response_model=MemoryProposeResponse,
    summary="Propose preference updates",
    description="Validate preference changes and stage them as an approval request (nothing is saved yet).",
)
def propose_memory_update(payload: MemoryProposeRequest) -> MemoryProposeResponse:
    clean, before, _ = _validated_updates(payload.updates)
    user_id = current_user_id()
    try:
        tool_call = route_tool("update_student_preferences", clean)
    except ValueError as e:
        raise _bad_request(str(e))

    task = AgentTask(
        id="memory_update",
        title="Update study preferences",
        description="Save the preference changes you reviewed.",
        tool=tool_call.tool_name,
        parameters=tool_call.parameters,
        requires_approval=True,
    )
    plan = AgentPlan(
        goal="Update student study preferences",
        summary="Save reviewed preference changes to memory.",
        tasks=[task],
        requires_approval=True,
    )
    orchestrator = AgentOrchestrator()
    orchestrator.last_planner_mode = "direct"
    workflow = orchestrator.build_workflow(plan.goal, plan)
    workflow.steps[0].status = "waiting_approval"
    workflow.status = "waiting_approval"
    staged = _stage(plan.goal, plan, workflow, user_id, kind="memory")
    _save_workflow(workflow, user_id)

    return MemoryProposeResponse(
        proposed_updates=clean,
        approval_id=staged.approval_id,
        action=staged.approval_requests[0].action,
        requires_approval=True,
        status="pending",
        payload_hash=staged.payload_hash,
        expires_at=staged.expires_at,
        changes=_changes(before, clean),
    )


@router.post(
    "/memory/update",
    summary="Update student preferences",
    description=(
        "approved=false stages the change for approval. approved=true applies an edit the student "
        "submitted directly in the preferences form; it is validated, read back, and audited."
    ),
)
def update_memory_endpoint(payload: MemoryUpdateRequest) -> Any:
    if not payload.approved:
        return propose_memory_update(MemoryProposeRequest(updates=payload.updates))

    clean, _, expected = _validated_updates(payload.updates)
    service = MemoryService()
    try:
        # A form edit replaces lists/maps with exactly what the student submitted.
        updated = service.update_preferences(clean, merge_collections=False)
        saved = service.get_preferences()
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Your preferences could not be saved. No successful save was confirmed.",
        )
    saved_dump = saved.model_dump()
    expected_dump = expected.model_dump()
    verified = all(saved_dump.get(k) == expected_dump.get(k) for k in clean)
    if not verified:
        raise HTTPException(
            status_code=500,
            detail="Your preferences could not be verified after saving. Reload and check them before relying on them.",
        )
    try:
        AuditService().record_event(
            event_type="preferences_edited_by_user",
            status="completed",
            detail="Fields: " + ", ".join(sorted(clean)),
            goal="Edit study preferences",
        )
    except Exception as e:
        logger.warning("Audit event failed (%s).", type(e).__name__)
    storage = get_persistence_status()
    return MemoryResponse(
        preferences=updated.model_dump(),
        summary=service.get_memory_summary(),
        status="ok",
        durable=storage["durable"],
        storage_message=storage["message"],
        verified=True,
    )


@router.post(
    "/memory/reset",
    response_model=MemoryResetResponse,
    summary="Reset student preferences",
    description="Reset student preferences to defaults. Requires explicit confirmation.",
)
def reset_memory_endpoint(payload: MemoryResetRequest) -> MemoryResetResponse:
    if not payload.confirm:
        raise _bad_request("Explicit confirmation (confirm=true) is required to reset preferences.")
    service = MemoryService()
    try:
        reset_pref = service.reset_preferences(confirmation=True)
        saved = service.get_preferences()
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Your preferences could not be reset. No successful reset was confirmed.",
        )
    defaults = StudentPreferences().model_dump(exclude={"updated_at"})
    if saved.model_dump(exclude={"updated_at"}) != defaults:
        raise HTTPException(status_code=500, detail="Reset could not be verified. Reload and check your preferences.")
    try:
        AuditService().record_event(
            event_type="preferences_reset_by_user",
            status="completed",
            goal="Reset study preferences",
        )
    except Exception as e:
        logger.warning("Audit event failed (%s).", type(e).__name__)
    return MemoryResetResponse(
        status="ok",
        message="Student preferences successfully reset to defaults.",
        preferences=reset_pref.model_dump(),
        summary=service.get_memory_summary(),
        verified=True,
        durable=get_persistence_status()["durable"],
    )
