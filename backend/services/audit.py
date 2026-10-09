import re
import uuid
from datetime import datetime

from models.agent import AgentPlan, ToolResult
from models.audit import AuditLogEntry
from services.identity import current_user_id
from services.persistence import BasePersistence, get_persistence

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

    def _event_entry(
        self,
        event_type: str,
        user_id: str,
        workflow_id: str | None = None,
        step_id: str | None = None,
        tool: str | None = None,
        status: str | None = None,
        detail: str | None = None,
        goal: str | None = None,
    ) -> AuditLogEntry:
        """Build one event entry. Only safe metadata is stored: no tool parameters, no credentials."""
        clean_detail = sanitize_text(detail)
        return AuditLogEntry(
            id=f"audit_{uuid.uuid4().hex[:12]}",
            goal=(sanitize_text(goal) or "")[:300] or "Workflow event",
            approval_status=status or "n/a",
            tools_executed=[tool] if tool else [],
            execution_status=status or "n/a",
            error_summary=clean_detail[:500] if clean_detail else None,
            timestamp=datetime.now(),
            user_id=user_id,
            event_type=event_type,
            workflow_id=workflow_id,
            step_id=step_id,
            tool=tool,
        )

    def record_event(self, event_type: str, user_id: str | None = None, **fields) -> AuditLogEntry:
        """Record a single workflow lifecycle event (workflow_started, approval_granted, tool_failed, ...)."""
        user_id = user_id or current_user_id()
        return self.persistence.record_audit_log(self._event_entry(event_type, user_id, **fields), user_id=user_id)

    def record_events(self, events: list[dict], user_id: str | None = None) -> list[AuditLogEntry]:
        """Record several lifecycle events at once, preserving order (one batched write on Firestore)."""
        user_id = user_id or current_user_id()
        entries = [self._event_entry(user_id=user_id, **ev) for ev in events]
        return self.persistence.record_audit_logs(entries, user_id=user_id)

    def get_logs(
        self, limit: int = 50, user_id: str | None = None
    ) -> list[AuditLogEntry]:
        """Retrieve recent audit log entries for a scoped user."""
        return self.persistence.get_audit_logs(limit=limit, user_id=user_id or current_user_id())
