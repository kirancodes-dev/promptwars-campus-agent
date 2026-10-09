from abc import ABC, abstractmethod
from datetime import datetime
import logging
import os
from typing import Any

try:
    from models.agent import AgentTask, NoteItem, ScheduleEvent
    from models.audit import AuditLogEntry
    from models.memory import StudentPreferences
except ImportError:
    from backend.models.agent import AgentTask, NoteItem, ScheduleEvent
    from backend.models.audit import AuditLogEntry
    from backend.models.memory import StudentPreferences

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "demo-user"


class PersistenceError(Exception):
    """Base exception for persistence failures."""
    pass


class EntityNotFoundError(PersistenceError):
    """Raised when a requested entity does not exist in the persistence store."""
    pass


class BasePersistence(ABC):
    """Abstract persistence interface for CampusPilot AI."""

    mode: str = "base"

    # --- Task Operations ---
    @abstractmethod
    def create_task(self, task: AgentTask, user_id: str = DEFAULT_USER_ID) -> AgentTask:
        """Create and store an AgentTask."""
        pass

    @abstractmethod
    def get_tasks(
        self,
        status: str | None = None,
        user_id: str = DEFAULT_USER_ID,
    ) -> list[AgentTask]:
        """List tasks for a user, optionally filtered by status."""
        pass

    @abstractmethod
    def get_task(
        self,
        task_id: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> AgentTask | None:
        """Get an AgentTask by ID."""
        pass

    @abstractmethod
    def update_task(
        self,
        task_id: str,
        updates: dict[str, Any],
        user_id: str = DEFAULT_USER_ID,
    ) -> AgentTask:
        """Update an existing task."""
        pass

    @abstractmethod
    def delete_task(
        self,
        task_id: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> bool:
        """Delete a task by ID. Raises EntityNotFoundError if not found."""
        pass

    # --- Schedule Operations ---
    @abstractmethod
    def create_event(
        self,
        event: ScheduleEvent,
        user_id: str = DEFAULT_USER_ID,
    ) -> ScheduleEvent:
        """Create and store a ScheduleEvent."""
        pass

    @abstractmethod
    def get_events(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        user_id: str = DEFAULT_USER_ID,
    ) -> list[ScheduleEvent]:
        """List schedule events, optionally filtered by time interval."""
        pass

    @abstractmethod
    def get_event(
        self,
        event_id: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> ScheduleEvent | None:
        """Get a ScheduleEvent by ID."""
        pass

    @abstractmethod
    def update_event(
        self,
        event_id: str,
        updates: dict[str, Any],
        user_id: str = DEFAULT_USER_ID,
    ) -> ScheduleEvent:
        """Update an existing schedule event."""
        pass

    @abstractmethod
    def delete_event(
        self,
        event_id: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> bool:
        """Delete a schedule event by ID. Raises EntityNotFoundError if not found."""
        pass

    # --- Note Operations ---
    @abstractmethod
    def create_note(
        self,
        note: NoteItem,
        user_id: str = DEFAULT_USER_ID,
    ) -> NoteItem:
        """Create and store a NoteItem."""
        pass

    @abstractmethod
    def get_notes(
        self,
        category: str | None = None,
        user_id: str = DEFAULT_USER_ID,
    ) -> list[NoteItem]:
        """List notes, optionally filtered by category."""
        pass

    @abstractmethod
    def get_note(
        self,
        note_id: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> NoteItem | None:
        """Get a NoteItem by ID."""
        pass

    @abstractmethod
    def update_note(
        self,
        note_id: str,
        updates: dict[str, Any],
        user_id: str = DEFAULT_USER_ID,
    ) -> NoteItem:
        """Update an existing note."""
        pass

    @abstractmethod
    def delete_note(
        self,
        note_id: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> bool:
        """Delete a note by ID. Raises EntityNotFoundError if not found."""
        pass

    @abstractmethod
    def search_notes(
        self,
        query: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> list[NoteItem]:
        """Search notes matching query in title or content."""
        pass

    # --- Student Preferences / Memory Operations ---
    @abstractmethod
    def get_preferences(self, user_id: str = DEFAULT_USER_ID) -> StudentPreferences:
        """Retrieve student preferences for a user, or defaults if none exist."""
        pass

    @abstractmethod
    def update_preferences(
        self, preferences: StudentPreferences, user_id: str = DEFAULT_USER_ID
    ) -> StudentPreferences:
        """Save or update student preferences for a user."""
        pass

    @abstractmethod
    def reset_preferences(self, user_id: str = DEFAULT_USER_ID) -> StudentPreferences:
        """Reset student preferences for a user back to defaults."""
        pass

    # --- Audit Trail Operations ---
    @abstractmethod
    def record_audit_log(
        self, entry: AuditLogEntry, user_id: str = DEFAULT_USER_ID
    ) -> AuditLogEntry:
        """Record an audit log entry for user activity."""
        pass

    @abstractmethod
    def get_audit_logs(
        self, limit: int = 50, user_id: str = DEFAULT_USER_ID
    ) -> list[AuditLogEntry]:
        """Retrieve recent audit logs for a user, sorted descending by timestamp."""
        pass

    # --- Workflow History Operations ---
    def save_workflow(self, workflow: Any, user_id: str = DEFAULT_USER_ID) -> Any:
        """Save or replace a WorkflowRecord for a user."""
        raise NotImplementedError

    def get_workflow(self, workflow_id: str, user_id: str = DEFAULT_USER_ID) -> Any | None:
        """Get a WorkflowRecord by ID for a user."""
        raise NotImplementedError

    def list_workflows(self, limit: int = 20, user_id: str = DEFAULT_USER_ID) -> list[Any]:
        """List recent WorkflowRecords for a user, newest first."""
        raise NotImplementedError

    # --- Cleanup / Testing Operations ---
    @abstractmethod
    def clear_tasks(self, user_id: str = DEFAULT_USER_ID) -> None:
        """Clear tasks for a user."""
        pass

    @abstractmethod
    def clear_schedule(self, user_id: str = DEFAULT_USER_ID) -> None:
        """Clear schedule events for a user."""
        pass

    @abstractmethod
    def clear_notes(self, user_id: str = DEFAULT_USER_ID) -> None:
        """Clear notes for a user."""
        pass

    @abstractmethod
    def clear_all(self, user_id: str = DEFAULT_USER_ID) -> None:
        """Clear all tasks, schedule events, and notes for a user."""
        pass


_current_persistence: BasePersistence | None = None
_persistence_mode: str = "memory"
_persistence_fallback_reason: str | None = None


def get_persistence() -> BasePersistence:
    """
    Return the active persistence layer.
    Automatically initializes Firestore if FIRESTORE_ENABLED is true,
    otherwise uses InMemoryPersistence.
    """
    global _current_persistence, _persistence_mode, _persistence_fallback_reason
    if _current_persistence is not None:
        return _current_persistence

    enabled_str = os.getenv("FIRESTORE_ENABLED", "false").strip().lower()
    firestore_requested = enabled_str in ("true", "1", "yes")

    if firestore_requested:
        try:
            try:
                from services.firestore import init_firestore
            except ImportError:
                from backend.services.firestore import init_firestore

            fs_instance = init_firestore()
            if fs_instance is not None:
                _current_persistence = fs_instance
                _persistence_mode = "firestore"
                _persistence_fallback_reason = None
                return _current_persistence
            _persistence_fallback_reason = "Firestore was requested but could not be initialized."
        except Exception as e:
            _persistence_fallback_reason = f"Firestore initialization error ({type(e).__name__})."
            logger.warning(
                "Firestore initialization error (%s). Falling back to in-memory persistence.",
                type(e).__name__,
            )

    try:
        from services.in_memory import InMemoryPersistence
    except ImportError:
        from backend.services.in_memory import InMemoryPersistence

    _current_persistence = InMemoryPersistence()
    # "memory_fallback" tells the UI that durable storage was requested but is NOT active.
    _persistence_mode = "memory_fallback" if firestore_requested else "memory"
    return _current_persistence


def set_persistence(persistence: BasePersistence, mode: str | None = None) -> None:
    """Set the active persistence layer explicitly (useful for testing)."""
    global _current_persistence, _persistence_mode
    _current_persistence = persistence
    _persistence_mode = mode or getattr(persistence, "mode", "memory")


def reset_persistence() -> None:
    """Reset active persistence to None so it can be re-initialized from environment."""
    global _current_persistence, _persistence_mode, _persistence_fallback_reason
    _current_persistence = None
    _persistence_mode = "memory"
    _persistence_fallback_reason = None


def get_persistence_mode() -> str:
    """Return the active persistence mode ('memory' or 'firestore')."""
    global _persistence_mode
    if _current_persistence is None:
        get_persistence()
    return _persistence_mode


def get_persistence_status() -> dict[str, Any]:
    """Describe the active storage honestly for status reporting (no secrets)."""
    mode = get_persistence_mode()
    durable = mode == "firestore"
    if mode == "firestore":
        message = "Data is saved to Google Cloud Firestore."
    elif mode == "memory_fallback":
        message = (
            "Durable storage (Firestore) was requested but is unavailable. "
            "Data is kept in server memory only and will be lost on restart."
        )
    else:
        message = "Demo storage: data is kept in server memory only and is lost when the server restarts."
    return {
        "mode": mode,
        "durable": durable,
        "message": message,
        "fallback_reason": _persistence_fallback_reason,
    }
