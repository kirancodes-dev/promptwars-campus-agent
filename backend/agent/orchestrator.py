from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import contextvars
from datetime import datetime
import logging
import os
from typing import Any, Callable
import uuid

from agent.executor import execute_tool
from agent.planner import PlannerError, plan_goal, plan_goal_with_gemini
from agent.router import get_tool, tool_mutates
from agent.workflow import validate_plan_dependencies, verify_tool_execution
from models.agent import (
    AgentExecutionResult,
    AgentPlan,
    AgentTask,
    ExecutionStatus,
    ToolCall,
    ToolResult,
    UserGoal,
)
from models.workflow import WorkflowRecord, WorkflowStep
from services.audit import AuditService
from services.identity import current_user_id

logger = logging.getLogger(__name__)

APPROVAL_REQUIRED_ERROR = "Approval required to execute this tool."
MAX_READ_ATTEMPTS = 2
FALLBACK_NOTE = (
    "AI planning was unavailable or returned an unusable plan, "
    "so CampusPilot's built-in planner was used instead."
)
FALLBACK_NOTES = {
    "unavailable": (
        "AI planning is unavailable right now (the AI service did not respond in time or rejected the request), "
        "so CampusPilot's built-in planner was used instead."
    ),
    "invalid_output": (
        "The AI's plan failed CampusPilot's safety checks, so it was discarded and the built-in planner was used instead."
    ),
}


def _tool_timeout_seconds() -> float:
    try:
        return max(1.0, float(os.getenv("TOOL_TIMEOUT_SECONDS", "15")))
    except ValueError:
        return 15.0


class AgentOrchestrator:
    """
    Central coordination layer between Planner, Router, and Executor.
    Manages the lifecycle of user goals through plan generation,
    approval gating, dependency-aware execution, verification, and audit.
    """

    def __init__(
        self,
        gemini_service: Any | None = None,
        planner_func: Callable[[UserGoal], AgentPlan] | None = None,
        executor_func: Callable[..., ToolResult] | None = None,
        planner: Callable[[UserGoal], AgentPlan] | None = None,
        executor: Callable[..., ToolResult] | None = None,
        audit_service: AuditService | None = None,
    ):
        self.gemini_service = gemini_service
        self.planner_func = planner_func or planner
        self.executor_func = executor_func or executor or execute_tool
        self._audit_service = audit_service
        self.last_planner_mode = "deterministic"
        self.last_planner_note: str | None = None

    # ------------------------------------------------------------------ planning

    def _plan_goal(self, goal: UserGoal) -> AgentPlan:
        """Plan with the injected planner, Gemini, or the deterministic planner (with fallback)."""
        self.last_planner_note = None
        if self.planner_func is not None:
            self.last_planner_mode = "custom"
            return self.planner_func(goal)

        if self.gemini_service is not None:
            try:
                plan = plan_goal_with_gemini(goal, self.gemini_service)
                valid, _ = validate_plan_dependencies(plan)
                if not valid:
                    raise PlannerError("Gemini plan failed dependency validation.", reason="invalid_output")
                self.last_planner_mode = "gemini"
                return plan
            except (PlannerError, ValueError, TypeError, KeyError) as e:
                # Model output is untrusted: never surface it, fall back deterministically.
                reason = getattr(e, "reason", "invalid_output")
                logger.warning("Gemini planning fallback (%s, %s); using deterministic planner.", reason, type(e).__name__)
                self.last_planner_mode = "deterministic_fallback"
                self.last_planner_note = FALLBACK_NOTES.get(reason, FALLBACK_NOTE)
                return plan_goal(goal)

        self.last_planner_mode = "deterministic"
        return plan_goal(goal)

    def plan(self, goal: UserGoal) -> AgentPlan:
        """
        Plan the user goal without executing any tools.
        Validates dependencies and execution ordering.
        """
        goal = self._coerce_goal(goal)
        plan = self._plan_goal(goal)
        valid, err = validate_plan_dependencies(plan)
        if not valid:
            raise ValueError(f"Plan validation failed: {err}")
        return plan

    @staticmethod
    def _coerce_goal(goal: UserGoal | str) -> UserGoal:
        if isinstance(goal, str):
            goal = UserGoal(goal=goal)
        if not goal or not isinstance(goal, UserGoal) or not goal.goal or not goal.goal.strip():
            raise ValueError("Goal must contain meaningful text.")
        return goal

    # ------------------------------------------------------------------ policy

    @staticmethod
    def step_requires_approval(task: AgentTask) -> bool:
        """
        Server-side approval policy. A step needs approval when the plan says so,
        when the tool is registered as approval-required, or when the tool changes
        stored data. Planner or model output can add approval, never remove it.
        """
        if not task.tool:
            return False
        if task.requires_approval or bool(task.parameters.get("requires_approval", False)):
            return True
        try:
            if get_tool(task.tool).requires_approval:
                return True
        except Exception:
            return True
        return tool_mutates(task.tool)

    def _requires_approval(self, plan: AgentPlan) -> bool:
        if plan.requires_approval:
            return True
        return any(self.step_requires_approval(t) for t in plan.tasks)

    def _has_clarification(self, plan: AgentPlan) -> tuple[bool, str | None]:
        """Detect if the plan indicates clarification is needed, returning question if so."""
        for task in plan.tasks:
            if task.tool is None:
                title_lower = task.title.lower()
                desc_lower = (task.description or "").lower()
                if "clarif" in title_lower or "clarif" in desc_lower:
                    return True, task.description or plan.summary
        if "clarif" in plan.summary.lower():
            return True, plan.summary
        return False, None

    # ------------------------------------------------------------------ workflow

    def build_workflow(self, goal_text: str, plan: AgentPlan) -> WorkflowRecord:
        steps = []
        for i, task in enumerate(plan.tasks):
            if not task.tool:
                kind = "reasoning"
            elif tool_mutates(task.tool):
                kind = "write"
            else:
                kind = "read"
            steps.append(
                WorkflowStep(
                    step_id=task.id,
                    order=i,
                    title=task.title,
                    description=task.description,
                    kind=kind,
                    tool=task.tool,
                    parameters=dict(task.parameters),
                    depends_on=list(task.depends_on),
                    requires_approval=self.step_requires_approval(task),
                    retry_eligible=(kind == "read"),
                )
            )
        return WorkflowRecord(
            workflow_id=f"wf_{uuid.uuid4().hex[:12]}",
            goal=goal_text,
            planner_mode=self.last_planner_mode,
            planner_note=self.last_planner_note,
            steps=steps,
            summary=plan.summary,
        )

    def _audit(self) -> AuditService:
        return self._audit_service or AuditService()

    def log_event(self, events: list[dict], event_type: str, wf: WorkflowRecord, step: WorkflowStep | None = None, detail: str | None = None, status: str | None = None) -> None:
        events.append(
            {
                "event_type": event_type,
                "workflow_id": wf.workflow_id,
                "step_id": step.step_id if step else None,
                "tool": step.tool if step else None,
                "status": status or (step.status if step else wf.status),
                "detail": detail,
                "goal": wf.goal,
            }
        )

    def flush_events(self, events: list[dict], user_id: str | None = None) -> bool:
        """Write buffered audit events. Audit failures never break the workflow."""
        if not events:
            return True
        try:
            self._audit().record_events(events, user_id=user_id)
            return True
        except Exception as e:
            logger.warning("Audit logging failed (%s); workflow result unaffected.", type(e).__name__)
            return False

    def _call_executor(self, tool_call: ToolCall, approved: bool) -> ToolResult:
        """Run one tool call with a timeout. The user context is propagated to the worker thread."""
        ctx = contextvars.copy_context()
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(ctx.run, self.executor_func, tool_call, approved=approved)
            return future.result(timeout=_tool_timeout_seconds())
        except FutureTimeout:
            raise TimeoutError(f"Tool '{tool_call.tool_name}' timed out.")
        finally:
            pool.shutdown(wait=False)

    def _run_step(self, task: AgentTask, step: WorkflowStep, approved: bool) -> ToolResult:
        tool_call = ToolCall(
            tool_name=task.tool,
            parameters=task.parameters,
            requires_approval=step.requires_approval,
        )
        max_attempts = MAX_READ_ATTEMPTS if step.retry_eligible else 1
        step.attempts = 0  # attempts are counted per execution pass, so retries are visible honestly
        res: ToolResult | None = None
        for _ in range(max_attempts):
            step.attempts += 1
            try:
                res = self._call_executor(tool_call, approved)
            except TimeoutError:
                msg = (
                    f"'{task.title}' timed out. "
                    + (
                        "The change may or may not have been saved; it was not retried to avoid duplicates."
                        if step.kind == "write"
                        else "The read was not completed."
                    )
                )
                res = ToolResult(tool_name=task.tool, success=False, result=None, error=msg)
            except Exception as e:
                res = ToolResult(tool_name=task.tool, success=False, result=None, error=str(e))
            if res.error == APPROVAL_REQUIRED_ERROR:
                step.attempts = 0  # a refusal by the approval gate is not an execution attempt
                break
            if res.success:
                break
        return res

    def run_workflow(
        self,
        plan: AgentPlan,
        workflow: WorkflowRecord,
        approved: bool = False,
        user_id: str | None = None,
        events: list[dict] | None = None,
    ) -> list[ToolResult]:
        """
        Execute a plan step by step in plan order (sequentially).
        - A step runs only when every dependency completed successfully.
        - Approval-required steps never run unless approved=True.
        - Read steps may be retried once; write steps are never retried.
        - Write steps that already completed in this workflow are not re-executed (idempotent resume).
        - Successful writes are verified by reading the resulting state back.
        """
        user_id = user_id or current_user_id()
        events = events if events is not None else []
        results: list[ToolResult] = []
        steps_by_id = {s.step_id: s for s in workflow.steps}
        workflow.status = "running"

        for task in plan.tasks:
            step = steps_by_id.get(task.id)
            if step is None:
                continue
            pending_dep, failed_dep = self._dependency_gate(task, steps_by_id)
            if failed_dep is not None:
                self._block(task, step, steps_by_id.get(failed_dep), failed_dep, results, workflow, events)
            elif not task.tool:
                # Reasoning step: completes once its prerequisites are done.
                step.status = "planned" if pending_dep else "completed"
            elif step.kind == "write" and step.status == "completed":
                # Idempotent resume: never repeat a write that already succeeded.
                results.append(ToolResult(tool_name=task.tool, success=True, result=step.result))
            elif pending_dep is not None and not approved:
                results.append(self._wait(task, step))
            else:
                results.append(self._execute(task, step, approved, user_id, workflow, events))

        workflow.status = self._workflow_status(workflow)
        workflow.next_action = self._next_action(workflow)
        workflow.updated_at = datetime.now()
        return results

    @staticmethod
    def _dependency_gate(task: AgentTask, steps_by_id: dict[str, WorkflowStep]) -> tuple[str | None, str | None]:
        """Return (pending dependency, failed dependency). A failed or unknown dependency wins."""
        pending = None
        for dep_id in task.depends_on:
            dep = steps_by_id.get(dep_id)
            if dep is None or dep.status not in ("completed", "waiting_approval", "planned"):
                return pending, dep_id
            if dep.status != "completed":
                pending = dep_id
        return pending, None

    def _block(self, task: AgentTask, step: WorkflowStep, dep: WorkflowStep | None, dep_id: str,
               results: list[ToolResult], workflow: WorkflowRecord, events: list[dict]) -> None:
        step.status = "blocked"
        step.error = f"Prerequisite step '{dep.title if dep else dep_id}' did not complete. Aborting execution of dependent task."
        if task.tool:
            results.append(ToolResult(tool_name=task.tool, success=False, result=None, error=step.error))
        self.log_event(events, "step_blocked", workflow, step, detail=step.error)

    @staticmethod
    def _wait(task: AgentTask, step: WorkflowStep) -> ToolResult:
        # Only protected steps "need approval"; others simply wait for them.
        if step.requires_approval:
            step.status = "waiting_approval"
            return ToolResult(tool_name=task.tool, success=False, result={"requires_approval": True}, error=APPROVAL_REQUIRED_ERROR)
        step.status = "planned"
        return ToolResult(tool_name=task.tool, success=False, result=None, error="Waiting for an approved prerequisite step.")

    def _execute(self, task: AgentTask, step: WorkflowStep, approved: bool, user_id: str,
                 workflow: WorkflowRecord, events: list[dict]) -> ToolResult:
        step.status = "running"
        step.started_at = datetime.now()
        self.log_event(events, "step_started", workflow, step)
        res = self._run_step(task, step, approved)

        if step.requires_approval and not approved:
            # Defense in depth: whatever the executor answered, an unapproved
            # protected step is reported as waiting, never as done.
            if res.success:
                logger.error("Executor reported success for an unapproved protected step '%s'.", task.tool)
            step.status = "waiting_approval"
            step.finished_at = None
            self.log_event(events, "approval_requested", workflow, step)
            return ToolResult(tool_name=task.tool, success=False, result={"requires_approval": True}, error=APPROVAL_REQUIRED_ERROR)

        if res.success and step.kind == "write":
            res = self._verify(task, step, res, user_id, workflow, events)

        step.finished_at = datetime.now()
        step.result = res.result
        step.error = res.error
        step.status = "completed" if res.success else "failed"
        self.log_event(events, "tool_succeeded" if res.success else "tool_failed", workflow, step,
                       detail=None if res.success else res.error)
        return res

    def _verify(self, task: AgentTask, step: WorkflowStep, res: ToolResult, user_id: str,
                workflow: WorkflowRecord, events: list[dict]) -> ToolResult:
        verified, v_err = verify_tool_execution(task.tool, task.parameters, res, user_id=user_id)
        step.verification.checked = True
        step.verification.passed = verified
        step.verification.detail = None if verified else (v_err or "Verification failed.")
        self.log_event(events, "verification_succeeded" if verified else "verification_failed", workflow, step,
                       detail=step.verification.detail)
        if verified:
            return res
        return ToolResult(tool_name=task.tool, success=False, result=res.result, error=v_err or "Verification failed.")

    @staticmethod
    def _workflow_status(wf: WorkflowRecord) -> str:
        statuses = [s.status for s in wf.steps]
        if any(s == "waiting_approval" for s in statuses):
            return "waiting_approval"
        tool_steps = [s for s in wf.steps if s.tool]
        if not tool_steps:
            return "completed"
        done = [s for s in tool_steps if s.status == "completed"]
        bad = [s for s in tool_steps if s.status in ("failed", "blocked", "skipped")]
        if not bad:
            return "completed"
        return "partially_completed" if done else "failed"

    @staticmethod
    def _next_action(wf: WorkflowRecord) -> str:
        status = wf.status
        if status == "waiting_approval":
            n = sum(1 for s in wf.steps if s.status == "waiting_approval" and s.requires_approval)
            return f"Review the {n} proposed change(s) and approve or reject them. Nothing has been changed yet."
        if status == "completed":
            writes = [s for s in wf.steps if s.kind == "write"]
            if writes:
                return "All steps finished and every change was read back and verified."
            return "All steps finished. No data was changed."
        if status == "partially_completed":
            return (
                "Some steps did not complete. Changes that succeeded were kept and verified; failed "
                "changes were not retried automatically. Review the failed steps, then run the goal again if needed."
            )
        if status == "rejected":
            return "You rejected the proposed changes. Nothing was changed."
        return "No step completed. Review the error details and try again."

    # ------------------------------------------------------------------ public execution API

    def execute_plan(
        self,
        plan: AgentPlan,
        approved: bool = False,
        workflow: WorkflowRecord | None = None,
        user_id: str | None = None,
    ) -> list[ToolResult]:
        """
        Execute an already-generated plan.
        Never executes approval-required tools when approved is False.
        """
        wf = workflow or self.build_workflow(plan.goal, plan)
        events: list[dict] = []
        results = self.run_workflow(plan, wf, approved=approved, user_id=user_id, events=events)
        self.flush_events(events, user_id=user_id)
        return results

    @staticmethod
    def classify_results(workflow: WorkflowRecord) -> tuple[list[str], list[str], list[str], list[str]]:
        succeeded, failed, unresolved, skipped = [], [], [], []
        for s in workflow.steps:
            if not s.tool:
                continue
            if s.status == "completed":
                succeeded.append(s.tool)
            elif s.status == "failed":
                failed.append(s.tool)
            elif s.status == "blocked":
                unresolved.append(s.tool)
            elif s.status in ("skipped", "rejected"):
                skipped.append(s.tool)
        return succeeded, failed, unresolved, skipped

    def build_result(
        self,
        goal_text: str,
        plan: AgentPlan,
        workflow: WorkflowRecord,
        results: list[ToolResult],
        requires_approval: bool,
    ) -> AgentExecutionResult:
        succeeded, failed, unresolved, skipped = self.classify_results(workflow)
        if workflow.status == "waiting_approval":
            status: ExecutionStatus = "waiting_approval"
        elif workflow.status == "needs_clarification":
            status = "needs_clarification"
        elif all(r.success for r in results):
            status = "completed"
        else:
            status = "failed"
        return AgentExecutionResult(
            goal=goal_text,
            plan=plan,
            results=results,
            status=status,
            requires_approval=requires_approval,
            succeeded_actions=succeeded,
            failed_actions=failed,
            unresolved_actions=unresolved,
            skipped_actions=skipped,
            verified=status == "completed" and all(
                s.verification.passed is not False for s in workflow.steps
            ),
            workflow=workflow,
            planner_mode=workflow.planner_mode,
            planner_note=workflow.planner_note,
        )

    def run(
        self,
        goal: UserGoal,
        approved: bool = False,
        user_id: str | None = None,
    ) -> AgentExecutionResult:
        """
        Execute the full coordination lifecycle for a user goal:
        1. Plan goal (Gemini when configured, deterministic otherwise or on failure).
        2. Validate plan dependencies and read-before-write policy.
        3. Clarification -> needs_clarification, nothing executes.
        4. Run read-only steps; protected writes wait for approval unless approved=True.
        5. Verify writes and record an audit trail.

        `approved=True` is for trusted in-process callers (tests, the approval
        endpoint after server-side checks). The HTTP API never forwards a
        client-supplied approval flag here.
        """
        goal = self._coerce_goal(goal)
        user_id = user_id or current_user_id()
        events: list[dict] = []

        plan = self._plan_goal(goal)
        workflow = self.build_workflow(goal.goal, plan)
        self.log_event(events, "workflow_started", workflow, detail=f"planner={workflow.planner_mode}")

        valid, err = validate_plan_dependencies(plan)
        if not valid:
            res = ToolResult(tool_name="dependency_validation", success=False, error=err)
            workflow.status = "failed"
            workflow.next_action = "The plan was rejected before anything ran. Try rephrasing your goal."
            self.log_event(events, "workflow_failed", workflow, detail=err)
            self.flush_events(events, user_id)
            result = AgentExecutionResult(
                goal=goal.goal,
                plan=plan,
                results=[res],
                status="failed",
                requires_approval=False,
                failed_actions=["Plan validation"],
                verified=False,
                workflow=workflow,
                planner_mode=workflow.planner_mode,
                planner_note=workflow.planner_note,
            )
            return result

        needs_clarification, question = self._has_clarification(plan)
        if needs_clarification:
            workflow.status = "needs_clarification"
            workflow.next_action = "Answer the question by adding the missing detail to your goal, then run it again."
            for s in workflow.steps:
                s.status = "skipped"
            self.log_event(events, "clarification_requested", workflow, detail=question)
            self.flush_events(events, user_id)
            return AgentExecutionResult(
                goal=goal.goal,
                plan=plan,
                results=[],
                status="needs_clarification",
                requires_approval=False,
                clarification_question=question,
                workflow=workflow,
                planner_mode=workflow.planner_mode,
                planner_note=workflow.planner_note,
            )

        plan_requires_approval = self._requires_approval(plan)
        results = self.run_workflow(plan, workflow, approved=approved, user_id=user_id, events=events)
        terminal = {
            "completed": "workflow_completed",
            "partially_completed": "workflow_partially_completed",
            "failed": "workflow_failed",
        }
        if workflow.status in terminal:
            self.log_event(events, terminal[workflow.status], workflow)
        self.flush_events(events, user_id)

        result = self.build_result(goal.goal, plan, workflow, results, plan_requires_approval)

        try:
            self._audit().record_execution(
                goal=goal.goal,
                plan=plan,
                approval_status=(
                    "waiting_approval" if result.status == "waiting_approval"
                    else ("approved" if approved and plan_requires_approval else "not_required")
                ),
                results=results,
                execution_status=result.status,
                error=next((r.error for r in results if not r.success and r.error != APPROVAL_REQUIRED_ERROR), None),
                user_id=user_id,
                workflow_id=workflow.workflow_id,
            )
        except Exception as e:
            logger.warning("Audit summary failed (%s).", type(e).__name__)

        return result
