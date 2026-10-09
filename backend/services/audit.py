import re
import uuid
from datetime import datetime
from typing import Any

try:
    from models.agent import AgentPlan, ToolResult
    from models.audit import AuditLogEntry
    from services.identity import current_user_id
    from services.persistence import DEFAULT_USER_ID, BasePersistence, get_persistence
except ImportError:
    from backend.models.agent import AgentPlan, ToolResult
    from backend.models.audit import AuditLogEntry
    from backend.services.identity import current_user_id
    from backend.services.persistence import DEFAULT_USER_ID, BasePersistence, get_persistence

_SENSITIVE_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z-_]{35}"),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----.*?-----END [A-Z ]+PRIVATE KEY-----", re.DOTALL),
    re.compile(r"(?:api_?key|token|password|secret|bearer)\s*[:=]\s*['\"]?[a-zA-Z0-9_\-\.]{8,}['\"]?", re.IGNORECASE),
]


def sanitize_text(text: str | None) -> str | None:
    """Sanitize strings by redacting API keys, private keys, and sensitive tokens."""
    if not text:
        return text
    sanitized = text
    for pattern in _SENSITIVE_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    return sanitized


class AuditService:
    """
    Lightweight, secure audit history service using existing persistence architecture.
    Records plan summaries, approval states, tool executions, and sanitized outcomes.
    Never stores credentials, secrets, or arbitrary code.
    """

    def __init__(self, persistence: BasePersistence | None = None) -> None:
        self.persistence = persistence or get_persistence()

    def record_execution(
        self,
        goal: str,
        plan: AgentPlan | None,
        approval_status: str,
        results: list[ToolResult] | None = None,
        execution_status: str = "completed",
        error: str | None = None,
        user_id: str | None = None,
        workflow_id: str | None = None,
    ) -> AuditLogEntry:
        """Record an execution summary in the audit trail."""
        user_id = user_id or current_user_id()
        plan_steps = [t.title for t in plan.tasks] if plan else []
        tools_executed = [r.tool_name for r in results] if results else []

        entry = AuditLogEntry(
            id=f"audit_{uuid.uuid4().hex[:12]}",
            goal=sanitize_text(goal) or "Unknown goal",
            plan_steps=[sanitize_text(s) or "" for s in plan_steps],
            approval_status=approval_status,
            tools_executed=tools_executed,
            execution_status=execution_status,
            error_summary=sanitize_text(error),
            timestamp=datetime.now(),
            user_id=user_id,
            workflow_id=workflow_id,
        )
        return self.persistence.record_audit_log(entry, user_id=user_id)

    def record_event(
        self,
        event_type: str,
        workflow_id: str | None = None,
        step_id: str | None = None,
        tool: str | None = None,
        status: str | None = None,
        detail: str | None = None,
        goal: str | None = None,
        user_id: str | None = None,
    ) -> AuditLogEntry:
        """
        Record a single workflow lifecycle event (workflow_started, step_started,
        approval_granted, tool_failed, verification_succeeded, ...).
        Only safe metadata is stored: no tool parameters, no credentials.
        """
        user_id = user_id or current_user_id()
        entry = AuditLogEntry(
            id=f"audit_{uuid.uuid4().hex[:12]}",
            goal=(sanitize_text(goal) or "")[:300] or "Workflow event",
            approval_status=status or "n/a",
            tools_executed=[tool] if tool else [],
            execution_status=status or "n/a",
            error_summary=(sanitize_text(detail) or None) and sanitize_text(detail)[:500],
            timestamp=datetime.now(),
            user_id=user_id,
            event_type=event_type,
            workflow_id=workflow_id,
            step_id=step_id,
            tool=tool,
        )
        return self.persistence.record_audit_log(entry, user_id=user_id)

    def get_logs(
        self, limit: int = 50, user_id: str | None = None
    ) -> list[AuditLogEntry]:
        """Retrieve recent audit log entries for a scoped user."""
        return self.persistence.get_audit_logs(limit=limit, user_id=user_id or current_user_id())
