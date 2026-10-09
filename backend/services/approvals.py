"""
Server-side approval registry.

Each staged approval is bound to:
- the user (session) that requested it,
- one workflow and its exact plan,
- a SHA-256 hash of every protected action (step ID, tool, parameters).

An approval can be claimed exactly once (pending -> executing -> approved/failed),
expires after APPROVAL_TTL_SECONDS, and can only execute the plan stored on the
server. Clients never send the actions to execute; they only reference the ID.

Approvals live in process memory, so pending approvals are lost on restart and the
service must run as a single instance (Cloud Run --max-instances=1) until approvals
are moved to shared storage. Completed results are kept in the workflow history.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
import json
import os
import secrets
import threading
from typing import Any

from models.agent import AgentPlan, ApprovalRequest
from models.workflow import WorkflowRecord

MAX_PENDING_PER_USER = 20


def approval_ttl() -> timedelta:
    try:
        seconds = int(os.getenv("APPROVAL_TTL_SECONDS", "900"))
    except ValueError:
        seconds = 900
    return timedelta(seconds=max(30, seconds))


def _json_default(o: Any) -> str:
    if isinstance(o, datetime):
        return o.isoformat()
    return str(o)


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=_json_default, separators=(",", ":"))


def actions_payload(plan: AgentPlan, protected_step_ids: list[str]) -> list[dict[str, Any]]:
    by_id = {t.id: t for t in plan.tasks}
    return [
        {"step_id": sid, "tool": by_id[sid].tool, "parameters": by_id[sid].parameters}
        for sid in protected_step_ids
        if sid in by_id
    ]


def payload_hash(user_id: str, workflow_id: str, actions: list[dict[str, Any]]) -> str:
    material = canonical({"user": user_id, "workflow": workflow_id, "actions": actions})
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class ApprovalError(Exception):
    """Base class for approval failures (mapped to HTTP errors by the API)."""

    status_code = 400


class ApprovalNotFound(ApprovalError):
    status_code = 404


class ApprovalConflict(ApprovalError):
    status_code = 409


class ApprovalExpired(ApprovalError):
    status_code = 410


class ApprovalTampered(ApprovalError):
    status_code = 400


@dataclass
class StagedApproval:
    approval_id: str
    user_id: str
    goal: str
    plan: AgentPlan
    workflow: WorkflowRecord
    protected_step_ids: list[str]
    payload_hash: str
    approval_requests: list[ApprovalRequest]
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime = field(default_factory=lambda: datetime.now() + approval_ttl())
    status: str = "pending"  # pending | executing | approved | rejected | expired | failed
    kind: str = "workflow"  # workflow | memory

    def actions(self) -> list[dict[str, Any]]:
        return actions_payload(self.plan, self.protected_step_ids)


class ApprovalStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, StagedApproval] = {}
        self._aliases: dict[str, str] = {}

    def clear(self) -> None:
        with self._lock:
            self._by_id.clear()
            self._aliases.clear()

    @staticmethod
    def new_id() -> str:
        return f"appr_{secrets.token_hex(12)}"

    def stage(
        self,
        user_id: str,
        goal: str,
        plan: AgentPlan,
        workflow: WorkflowRecord,
        protected_step_ids: list[str],
        approval_requests: list[ApprovalRequest],
        approval_id: str | None = None,
        kind: str = "workflow",
    ) -> StagedApproval:
        approval_id = approval_id or self.new_id()
        actions = actions_payload(plan, protected_step_ids)
        staged = StagedApproval(
            approval_id=approval_id,
            user_id=user_id,
            goal=goal,
            plan=plan,
            workflow=workflow,
            protected_step_ids=list(protected_step_ids),
            payload_hash=payload_hash(user_id, workflow.workflow_id, actions),
            approval_requests=approval_requests,
            kind=kind,
        )
        with self._lock:
            self._expire_locked()
            pending = [a for a in self._by_id.values() if a.user_id == user_id and a.status == "pending"]
            if len(pending) >= MAX_PENDING_PER_USER:
                oldest = min(pending, key=lambda a: a.created_at)
                oldest.status = "expired"
            self._by_id[approval_id] = staged
            for req in approval_requests:
                if req.approval_id != approval_id:
                    self._aliases[req.approval_id] = approval_id
        return staged

    def _expire_locked(self) -> None:
        now = datetime.now()
        stale = [k for k, a in self._by_id.items() if a.status != "pending" and now - a.created_at > timedelta(hours=2)]
        for k in stale:
            self._by_id.pop(k, None)
        for alias, target in list(self._aliases.items()):
            if target not in self._by_id:
                self._aliases.pop(alias, None)

    def get(self, approval_id: str, user_id: str) -> StagedApproval:
        """Look up an approval owned by user_id. Other users' approvals are reported as not found."""
        with self._lock:
            key = self._aliases.get(approval_id, approval_id)
            staged = self._by_id.get(key)
            if staged is None or staged.user_id != user_id:
                raise ApprovalNotFound(f"Unknown approval ID: '{approval_id}'")
            return staged

    def find_pending_by_goal(self, goal: str, user_id: str) -> StagedApproval:
        g = goal.strip().lower()
        with self._lock:
            matches = [
                a for a in self._by_id.values()
                if a.user_id == user_id and a.status == "pending" and a.goal.strip().lower() == g
            ]
        if not matches:
            raise ApprovalNotFound(f"No pending approval request found for goal: '{goal}'")
        if len(matches) > 1:
            raise ApprovalConflict("More than one pending approval matches this goal; use approval_id.")
        return matches[0]

    def claim(
        self,
        staged: StagedApproval,
        new_status: str,
        expected_hash: str | None = None,
        client_parameters: dict[str, Any] | None = None,
    ) -> None:
        """
        Atomically move a pending approval to `new_status` ("executing" or "rejected").
        Rejects replays, expired approvals and payload substitution.
        """
        with self._lock:
            if staged.status != "pending":
                raise ApprovalConflict(
                    f"Approval request '{staged.approval_id}' has already been {staged.status}."
                )
            if datetime.now() > staged.expires_at:
                staged.status = "expired"
                raise ApprovalExpired(
                    f"Approval request '{staged.approval_id}' has expired. Run the goal again to get a fresh plan."
                )
            current = payload_hash(staged.user_id, staged.workflow.workflow_id, staged.actions())
            if current != staged.payload_hash:
                staged.status = "failed"
                raise ApprovalTampered("The staged actions changed after they were reviewed. Nothing was executed.")
            if expected_hash is not None and not secrets.compare_digest(expected_hash, staged.payload_hash):
                raise ApprovalTampered(
                    "Tampered approval parameters: the approval does not match the reviewed actions."
                )
            if client_parameters is not None:
                staged_params = [canonical(a["parameters"]) for a in staged.actions()]
                if canonical(client_parameters) not in staged_params:
                    raise ApprovalTampered(
                        "Tampered approval parameters: Modification of approved tool parameters is strictly forbidden."
                    )
            staged.status = new_status

    def finish(self, staged: StagedApproval, status: str) -> None:
        with self._lock:
            staged.status = status


approval_store = ApprovalStore()
