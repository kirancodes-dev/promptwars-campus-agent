from datetime import datetime, timedelta
import logging
import os
from typing import Any

from models.agent import AgentTask, NoteItem, ScheduleEvent
from models.audit import AuditLogEntry
from models.memory import StudentPreferences
from services.persistence import (
    DEFAULT_USER_ID,
    BasePersistence,
    EntityNotFoundError,
    PersistenceError,
)

logger = logging.getLogger(__name__)

try:
    from google.cloud.firestore_v1.base_query import FieldFilter
except ImportError:  # pragma: no cover - the SDK is a declared dependency
    class FieldFilter:  # minimal stand-in with the same attributes
        def __init__(self, field_path: str, op_string: str, value: Any) -> None:
            self.field_path, self.op_string, self.value = field_path, op_string, value

_DESCENDING = "DESCENDING"
_BATCH_LIMIT = 450  # Firestore allows 500 writes per batch


def _to_datetime(val: Any) -> datetime | None:
    """Safely convert Firestore timestamp, string, or datetime to Python datetime."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if hasattr(val, "to_datetime"):
        return val.to_datetime()
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val)
        except Exception:
            return None
    return None


def _serialize_task(task: AgentTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "tool": task.tool,
        "parameters": task.parameters,
        "requires_approval": task.requires_approval,
    }


def _deserialize_task(data: dict[str, Any]) -> AgentTask:
    d = dict(data)
    return AgentTask(**d)


def _serialize_event(event: ScheduleEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "start_time": event.start_time.isoformat() if hasattr(event.start_time, "isoformat") else str(event.start_time),
        "end_time": event.end_time.isoformat() if hasattr(event.end_time, "isoformat") else str(event.end_time),
        "status": event.status,
        "requires_approval": event.requires_approval,
    }


def _deserialize_event(data: dict[str, Any]) -> ScheduleEvent:
    d = dict(data)
    for f in ("start_time", "end_time"):
        if f in d:
            dt = _to_datetime(d[f])
            if dt is not None:
                d[f] = dt
    return ScheduleEvent(**d)


def _serialize_note(note: NoteItem) -> dict[str, Any]:
    return {
        "id": note.id,
        "title": note.title,
        "content": note.content,
        "category": note.category,
        "created_at": note.created_at.isoformat() if hasattr(note.created_at, "isoformat") else str(note.created_at),
        "updated_at": note.updated_at.isoformat() if hasattr(note.updated_at, "isoformat") else str(note.updated_at),
    }


def _deserialize_note(data: dict[str, Any]) -> NoteItem:
    d = dict(data)
    for f in ("created_at", "updated_at"):
        if f in d:
            dt = _to_datetime(d[f])
            if dt is not None:
                d[f] = dt
    return NoteItem(**d)


def _serialize_preferences(pref: StudentPreferences) -> dict[str, Any]:
    return {
        "preferred_study_start": pref.preferred_study_start,
        "preferred_study_end": pref.preferred_study_end,
        "preferred_session_minutes": pref.preferred_session_minutes,
        "preferred_break_minutes": pref.preferred_break_minutes,
        "preferred_study_days": pref.preferred_study_days,
        "preferred_subjects": pref.preferred_subjects,
        "subject_time_preferences": pref.subject_time_preferences,
        "planning_notes": pref.planning_notes,
        "updated_at": pref.updated_at.isoformat() if pref.updated_at else None,
    }


def _deserialize_preferences(data: dict[str, Any]) -> StudentPreferences:
    d = dict(data)
    if "updated_at" in d and d["updated_at"]:
        d["updated_at"] = _to_datetime(d["updated_at"])
    return StudentPreferences(**d)


def _serialize_audit_log(entry: AuditLogEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "goal": entry.goal,
        "plan_steps": entry.plan_steps,
        "approval_status": entry.approval_status,
        "tools_executed": entry.tools_executed,
        "execution_status": entry.execution_status,
        "error_summary": entry.error_summary,
        "timestamp": entry.timestamp.isoformat() if isinstance(entry.timestamp, datetime) else str(entry.timestamp),
        "user_id": entry.user_id,
        "event_type": entry.event_type,
        "workflow_id": entry.workflow_id,
        "step_id": entry.step_id,
        "tool": entry.tool,
    }


def _deserialize_audit_log(data: dict[str, Any]) -> AuditLogEntry:
    d = dict(data)
    ts = _to_datetime(d.get("timestamp")) or datetime.now()
    return AuditLogEntry(
        id=str(d.get("id", "")),
        goal=str(d.get("goal", "")),
        plan_steps=list(d.get("plan_steps", [])),
        approval_status=str(d.get("approval_status", "")),
        tools_executed=list(d.get("tools_executed", [])),
        execution_status=str(d.get("execution_status", "")),
        error_summary=d.get("error_summary"),
        timestamp=ts,
        user_id=str(d.get("user_id", DEFAULT_USER_ID)),
        event_type=str(d.get("event_type") or "execution_summary"),
        workflow_id=d.get("workflow_id"),
        step_id=d.get("step_id"),
        tool=d.get("tool"),
    )


class FirestorePersistence(BasePersistence):
    """
    Firebase Firestore implementation of BasePersistence.
    Uses document hierarchy:
    users/{user_id}/tasks/{task_id}
    users/{user_id}/schedule/{event_id}
    users/{user_id}/notes/{note_id}
    """

    mode: str = "firestore"

    def __init__(
        self,
        client: Any | None = None,
        project_id: str | None = None,
        database: str | None = None,
    ) -> None:
        if client is not None:
            self.client = client
        else:
            try:
                from google.cloud import firestore

                kwargs: dict[str, Any] = {}
                if project_id:
                    kwargs["project"] = project_id
                if database and database != "(default)":
                    kwargs["database"] = database
                self.client = firestore.Client(**kwargs)
            except Exception as e:
                raise PersistenceError(f"Failed to initialize Google Cloud Firestore: {type(e).__name__}") from None

    def _user_ref(self, user_id: str):
        return self.client.collection("users").document(user_id)

    # --- Task Operations ---
    def create_task(self, task: AgentTask, user_id: str = DEFAULT_USER_ID) -> AgentTask:
        doc_ref = self._user_ref(user_id).collection("tasks").document(task.id)
        doc_ref.set(_serialize_task(task))
        return task

    def get_tasks(
        self,
        status: str | None = None,
        user_id: str = DEFAULT_USER_ID,
    ) -> list[AgentTask]:
        coll = self._user_ref(user_id).collection("tasks")
        docs = coll.stream()
        tasks = [_deserialize_task(doc.to_dict()) for doc in docs if doc.to_dict()]
        if status is not None:
            tasks = [t for t in tasks if t.status == status]
        return tasks

    def get_task(
        self,
        task_id: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> AgentTask | None:
        doc = self._user_ref(user_id).collection("tasks").document(task_id).get()
        if not getattr(doc, "exists", False):
            return None
        return _deserialize_task(doc.to_dict())

    def update_task(
        self,
        task_id: str,
        updates: dict[str, Any],
        user_id: str = DEFAULT_USER_ID,
    ) -> AgentTask:
        doc_ref = self._user_ref(user_id).collection("tasks").document(task_id)
        doc = doc_ref.get()
        if not getattr(doc, "exists", False):
            raise EntityNotFoundError(f"Task with ID '{task_id}' not found.")
        current = doc.to_dict()
        current.update(updates)
        doc_ref.set(current)
        return _deserialize_task(current)

    def delete_task(
        self,
        task_id: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> bool:
        doc_ref = self._user_ref(user_id).collection("tasks").document(task_id)
        doc = doc_ref.get()
        if not getattr(doc, "exists", False):
            raise EntityNotFoundError(f"Task with ID '{task_id}' not found.")
        doc_ref.delete()
        return True

    # --- Schedule Operations ---
    def create_event(
        self,
        event: ScheduleEvent,
        user_id: str = DEFAULT_USER_ID,
    ) -> ScheduleEvent:
        doc_ref = self._user_ref(user_id).collection("schedule").document(event.id)
        doc_ref.set(_serialize_event(event))
        return event

    def get_events(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        user_id: str = DEFAULT_USER_ID,
    ) -> list[ScheduleEvent]:
        coll = self._user_ref(user_id).collection("schedule")
        docs = coll.stream()
        events = [_deserialize_event(doc.to_dict()) for doc in docs if doc.to_dict()]
        if start_time is not None and end_time is not None:
            events = [
                e
                for e in events
                if e.start_time >= start_time and e.end_time <= end_time
            ]
        return events

    def get_events_overlapping(
        self, start_time: datetime, end_time: datetime, user_id: str = DEFAULT_USER_ID
    ) -> list[ScheduleEvent]:
        """
        Indexed range query instead of reading every event. Events are at most 24 hours long
        (enforced by the router), so anything overlapping [start, end) starts after start - 24h.
        """
        coll = self._user_ref(user_id).collection("schedule")
        lower = (start_time - timedelta(hours=24)).isoformat()
        query = coll.where(filter=FieldFilter("start_time", ">=", lower)).where(
            filter=FieldFilter("start_time", "<", end_time.isoformat())
        )
        events = [_deserialize_event(doc.to_dict()) for doc in query.stream() if doc.to_dict()]
        return [e for e in events if e.start_time < end_time and e.end_time > start_time]

    def get_event(
        self,
        event_id: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> ScheduleEvent | None:
        doc = self._user_ref(user_id).collection("schedule").document(event_id).get()
        if not getattr(doc, "exists", False):
            return None
        return _deserialize_event(doc.to_dict())

    def update_event(
        self,
        event_id: str,
        updates: dict[str, Any],
        user_id: str = DEFAULT_USER_ID,
    ) -> ScheduleEvent:
        doc_ref = self._user_ref(user_id).collection("schedule").document(event_id)
        doc = doc_ref.get()
        if not getattr(doc, "exists", False):
            raise EntityNotFoundError(f"Schedule event with ID '{event_id}' not found.")
        current = doc.to_dict()
        for k, v in updates.items():
            if isinstance(v, datetime):
                current[k] = v.isoformat()
            else:
                current[k] = v
        doc_ref.set(current)
        return _deserialize_event(current)

    def delete_event(
        self,
        event_id: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> bool:
        doc_ref = self._user_ref(user_id).collection("schedule").document(event_id)
        doc = doc_ref.get()
        if not getattr(doc, "exists", False):
            raise EntityNotFoundError(f"Schedule event with ID '{event_id}' not found.")
        doc_ref.delete()
        return True

    # --- Note Operations ---
    def create_note(
        self,
        note: NoteItem,
        user_id: str = DEFAULT_USER_ID,
    ) -> NoteItem:
        doc_ref = self._user_ref(user_id).collection("notes").document(note.id)
        doc_ref.set(_serialize_note(note))
        return note

    def get_notes(
        self,
        category: str | None = None,
        user_id: str = DEFAULT_USER_ID,
    ) -> list[NoteItem]:
        coll = self._user_ref(user_id).collection("notes")
        docs = coll.stream()
        notes = [_deserialize_note(doc.to_dict()) for doc in docs if doc.to_dict()]
        if category is not None:
            notes = [n for n in notes if n.category.lower() == category.lower()]
        return notes

    def get_note(
        self,
        note_id: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> NoteItem | None:
        doc = self._user_ref(user_id).collection("notes").document(note_id).get()
        if not getattr(doc, "exists", False):
            return None
        return _deserialize_note(doc.to_dict())

    def update_note(
        self,
        note_id: str,
        updates: dict[str, Any],
        user_id: str = DEFAULT_USER_ID,
    ) -> NoteItem:
        doc_ref = self._user_ref(user_id).collection("notes").document(note_id)
        doc = doc_ref.get()
        if not getattr(doc, "exists", False):
            raise EntityNotFoundError(f"Note with ID '{note_id}' not found.")
        current = doc.to_dict()
        current.update(updates)
        current["updated_at"] = datetime.now().isoformat()
        doc_ref.set(current)
        return _deserialize_note(current)

    def delete_note(
        self,
        note_id: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> bool:
        doc_ref = self._user_ref(user_id).collection("notes").document(note_id)
        doc = doc_ref.get()
        if not getattr(doc, "exists", False):
            raise EntityNotFoundError(f"Note with ID '{note_id}' not found.")
        doc_ref.delete()
        return True

    def search_notes(
        self,
        query: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> list[NoteItem]:
        notes = self.get_notes(user_id=user_id)
        q = query.lower()
        return [
            n
            for n in notes
            if q in n.title.lower() or q in n.content.lower()
        ]

    # --- Student Preferences / Memory Operations ---
    def _pref_ref(self, user_id: str = DEFAULT_USER_ID) -> Any:
        return self._user_ref(user_id).collection("preferences").document("default")

    def get_preferences(self, user_id: str = DEFAULT_USER_ID) -> StudentPreferences:
        doc = self._pref_ref(user_id).get()
        if not doc.exists:
            return StudentPreferences()
        data = doc.to_dict() or {}
        return _deserialize_preferences(data)

    def update_preferences(
        self, preferences: StudentPreferences, user_id: str = DEFAULT_USER_ID
    ) -> StudentPreferences:
        data = _serialize_preferences(preferences)
        self._pref_ref(user_id).set(data)
        return preferences.model_copy(deep=True)

    def reset_preferences(self, user_id: str = DEFAULT_USER_ID) -> StudentPreferences:
        default_pref = StudentPreferences()
        self._pref_ref(user_id).set(_serialize_preferences(default_pref))
        return default_pref

    # --- Audit Trail Operations ---
    def record_audit_log(
        self, entry: AuditLogEntry, user_id: str = DEFAULT_USER_ID
    ) -> AuditLogEntry:
        coll = self._user_ref(user_id).collection("audit_logs")
        data = _serialize_audit_log(entry)
        coll.document(entry.id).set(data)
        return entry.model_copy(deep=True)

    def record_audit_logs(
        self, entries: list[AuditLogEntry], user_id: str = DEFAULT_USER_ID
    ) -> list[AuditLogEntry]:
        """Write a workflow's audit events in one atomic batch (one round trip; billing is per document)."""
        coll = self._user_ref(user_id).collection("audit_logs")
        for start in range(0, len(entries), _BATCH_LIMIT):
            batch = self.client.batch()
            for entry in entries[start:start + _BATCH_LIMIT]:
                batch.set(coll.document(entry.id), _serialize_audit_log(entry))
            batch.commit()
        return [e.model_copy(deep=True) for e in entries]

    def get_audit_logs(
        self, limit: int = 50, user_id: str = DEFAULT_USER_ID
    ) -> list[AuditLogEntry]:
        # Newest first, read only `limit` documents (single-field index on timestamp).
        coll = self._user_ref(user_id).collection("audit_logs")
        query = coll.order_by("timestamp", direction=_DESCENDING).limit(limit)
        return [_deserialize_audit_log(doc.to_dict() or {}) for doc in query.stream()]

    # --- Workflow History Operations ---
    def save_workflow(self, workflow: Any, user_id: str = DEFAULT_USER_ID) -> Any:
        doc_ref = self._user_ref(user_id).collection("workflows").document(workflow.workflow_id)
        doc_ref.set(workflow.model_dump(mode="json"))
        return workflow

    def get_workflow(self, workflow_id: str, user_id: str = DEFAULT_USER_ID) -> Any | None:
        from models.workflow import WorkflowRecord
        doc = self._user_ref(user_id).collection("workflows").document(workflow_id).get()
        if not getattr(doc, "exists", False):
            return None
        return WorkflowRecord.model_validate(doc.to_dict())

    def list_workflows(self, limit: int = 20, user_id: str = DEFAULT_USER_ID) -> list[Any]:
        from models.workflow import WorkflowRecord
        coll = self._user_ref(user_id).collection("workflows")
        query = coll.order_by("updated_at", direction=_DESCENDING).limit(limit)
        return [WorkflowRecord.model_validate(doc.to_dict()) for doc in query.stream() if doc.to_dict()]

    # --- Cleanup / Testing Operations ---
    def clear_tasks(self, user_id: str = DEFAULT_USER_ID) -> None:
        coll = self._user_ref(user_id).collection("tasks")
        for doc in coll.stream():
            if hasattr(doc, "reference"):
                doc.reference.delete()

    def clear_schedule(self, user_id: str = DEFAULT_USER_ID) -> None:
        coll = self._user_ref(user_id).collection("schedule")
        for doc in coll.stream():
            if hasattr(doc, "reference"):
                doc.reference.delete()

    def clear_notes(self, user_id: str = DEFAULT_USER_ID) -> None:
        coll = self._user_ref(user_id).collection("notes")
        for doc in coll.stream():
            if hasattr(doc, "reference"):
                doc.reference.delete()

    def clear_all(self, user_id: str = DEFAULT_USER_ID) -> None:
        self.clear_tasks(user_id)
        self.clear_schedule(user_id)
        self.clear_notes(user_id)
        self.reset_preferences(user_id)
        coll = self._user_ref(user_id).collection("audit_logs")
        for doc in coll.stream():
            if hasattr(doc, "reference"):
                doc.reference.delete()


def init_firestore(
    client: Any | None = None,
    project_id: str | None = None,
) -> FirestorePersistence | None:
    """
    Initialize FirestorePersistence safely if FIRESTORE_ENABLED is true.
    Handles configuration errors cleanly and returns None on failure.
    Never exposes or logs credential contents or private keys.
    """
    enabled_str = os.getenv("FIRESTORE_ENABLED", "false").strip().lower()
    if enabled_str not in ("true", "1", "yes"):
        return None

    try:
        resolved_project = project_id or os.getenv("FIRESTORE_PROJECT_ID") or None
        return FirestorePersistence(client=client, project_id=resolved_project)
    except Exception as e:
        logger.warning(
            "Firestore initialization failed (%s). Falling back to in-memory persistence.",
            type(e).__name__,
        )
        return None
