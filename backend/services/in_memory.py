from datetime import datetime
from typing import Any

try:
    from models.agent import AgentTask, NoteItem, ScheduleEvent
    from models.audit import AuditLogEntry
    from models.memory import StudentPreferences
    from services.persistence import (
        DEFAULT_USER_ID,
        BasePersistence,
        EntityNotFoundError,
    )
except ImportError:
    from backend.models.agent import AgentTask, NoteItem, ScheduleEvent
    from backend.models.audit import AuditLogEntry
    from backend.models.memory import StudentPreferences
    from backend.services.persistence import (
        DEFAULT_USER_ID,
        BasePersistence,
        EntityNotFoundError,
    )


MAX_AUDIT_ENTRIES_PER_USER = 500
MAX_WORKFLOWS_PER_USER = 50


class InMemoryPersistence(BasePersistence):
    """
    In-memory dictionary-backed persistence with multi-user isolation.
    Serves as default local development persistence and offline fallback.
    """

    mode: str = "memory"

    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, AgentTask]] = {}
        self._events: dict[str, dict[str, ScheduleEvent]] = {}
        self._notes: dict[str, dict[str, NoteItem]] = {}
        self._preferences: dict[str, StudentPreferences] = {}
        self._audit_logs: dict[str, list[AuditLogEntry]] = {}
        self._workflows: dict[str, dict[str, Any]] = {}

    def _get_user_tasks(self, user_id: str = DEFAULT_USER_ID) -> dict[str, AgentTask]:
        return self._tasks.setdefault(user_id, {})

    def _get_user_events(self, user_id: str = DEFAULT_USER_ID) -> dict[str, ScheduleEvent]:
        return self._events.setdefault(user_id, {})

    def _get_user_notes(self, user_id: str = DEFAULT_USER_ID) -> dict[str, NoteItem]:
        return self._notes.setdefault(user_id, {})

    # --- Task Operations ---
    def create_task(self, task: AgentTask, user_id: str = DEFAULT_USER_ID) -> AgentTask:
        store = self._get_user_tasks(user_id)
        store[task.id] = task
        return task

    def get_tasks(
        self,
        status: str | None = None,
        user_id: str = DEFAULT_USER_ID,
    ) -> list[AgentTask]:
        store = self._get_user_tasks(user_id)
        if status is not None:
            return [t for t in store.values() if t.status == status]
        return list(store.values())

    def get_task(
        self,
        task_id: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> AgentTask | None:
        return self._get_user_tasks(user_id).get(task_id)

    def update_task(
        self,
        task_id: str,
        updates: dict[str, Any],
        user_id: str = DEFAULT_USER_ID,
    ) -> AgentTask:
        store = self._get_user_tasks(user_id)
        if task_id not in store:
            raise EntityNotFoundError(f"Task with ID '{task_id}' not found.")
        task = store[task_id]
        data = task.model_dump()
        data.update(updates)
        updated_task = AgentTask(**data)
        store[task_id] = updated_task
        return updated_task

    def delete_task(
        self,
        task_id: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> bool:
        store = self._get_user_tasks(user_id)
        if task_id not in store:
            raise EntityNotFoundError(f"Task with ID '{task_id}' not found.")
        del store[task_id]
        return True

    # --- Schedule Operations ---
    def create_event(
        self,
        event: ScheduleEvent,
        user_id: str = DEFAULT_USER_ID,
    ) -> ScheduleEvent:
        store = self._get_user_events(user_id)
        store[event.id] = event
        return event

    def get_events(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        user_id: str = DEFAULT_USER_ID,
    ) -> list[ScheduleEvent]:
        store = self._get_user_events(user_id)
        if start_time is not None and end_time is not None:
            return [
                e
                for e in store.values()
                if e.start_time >= start_time and e.end_time <= end_time
            ]
        return list(store.values())

    def get_event(
        self,
        event_id: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> ScheduleEvent | None:
        return self._get_user_events(user_id).get(event_id)

    def update_event(
        self,
        event_id: str,
        updates: dict[str, Any],
        user_id: str = DEFAULT_USER_ID,
    ) -> ScheduleEvent:
        store = self._get_user_events(user_id)
        if event_id not in store:
            raise EntityNotFoundError(f"Schedule event with ID '{event_id}' not found.")
        ev = store[event_id]
        data = ev.model_dump()
        data.update(updates)
        updated_event = ScheduleEvent(**data)
        store[event_id] = updated_event
        return updated_event

    def delete_event(
        self,
        event_id: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> bool:
        store = self._get_user_events(user_id)
        if event_id not in store:
            raise EntityNotFoundError(f"Schedule event with ID '{event_id}' not found.")
        del store[event_id]
        return True

    # --- Note Operations ---
    def create_note(
        self,
        note: NoteItem,
        user_id: str = DEFAULT_USER_ID,
    ) -> NoteItem:
        store = self._get_user_notes(user_id)
        store[note.id] = note
        return note

    def get_notes(
        self,
        category: str | None = None,
        user_id: str = DEFAULT_USER_ID,
    ) -> list[NoteItem]:
        store = self._get_user_notes(user_id)
        if category is not None:
            return [n for n in store.values() if n.category.lower() == category.lower()]
        return list(store.values())

    def get_note(
        self,
        note_id: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> NoteItem | None:
        return self._get_user_notes(user_id).get(note_id)

    def update_note(
        self,
        note_id: str,
        updates: dict[str, Any],
        user_id: str = DEFAULT_USER_ID,
    ) -> NoteItem:
        store = self._get_user_notes(user_id)
        if note_id not in store:
            raise EntityNotFoundError(f"Note with ID '{note_id}' not found.")
        n = store[note_id]
        data = n.model_dump()
        data.update(updates)
        data["updated_at"] = datetime.now()
        updated_note = NoteItem(**data)
        store[note_id] = updated_note
        return updated_note

    def delete_note(
        self,
        note_id: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> bool:
        store = self._get_user_notes(user_id)
        if note_id not in store:
            raise EntityNotFoundError(f"Note with ID '{note_id}' not found.")
        del store[note_id]
        return True

    def search_notes(
        self,
        query: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> list[NoteItem]:
        store = self._get_user_notes(user_id)
        q = query.lower()
        return [
            n
            for n in store.values()
            if q in n.title.lower() or q in n.content.lower()
        ]

    # --- Student Preferences / Memory Operations ---
    def get_preferences(self, user_id: str = DEFAULT_USER_ID) -> StudentPreferences:
        if user_id not in self._preferences:
            self._preferences[user_id] = StudentPreferences()
        return self._preferences[user_id].model_copy(deep=True)

    def update_preferences(
        self, preferences: StudentPreferences, user_id: str = DEFAULT_USER_ID
    ) -> StudentPreferences:
        self._preferences[user_id] = preferences.model_copy(deep=True)
        return self._preferences[user_id].model_copy(deep=True)

    def reset_preferences(self, user_id: str = DEFAULT_USER_ID) -> StudentPreferences:
        self._preferences[user_id] = StudentPreferences()
        return self._preferences[user_id].model_copy(deep=True)

    # --- Audit Trail Operations ---
    def record_audit_log(
        self, entry: AuditLogEntry, user_id: str = DEFAULT_USER_ID
    ) -> AuditLogEntry:
        logs = self._audit_logs.setdefault(user_id, [])
        entry_copy = entry.model_copy(deep=True)
        logs.insert(0, entry_copy)
        del logs[MAX_AUDIT_ENTRIES_PER_USER:]
        return entry_copy

    def get_audit_logs(
        self, limit: int = 50, user_id: str = DEFAULT_USER_ID
    ) -> list[AuditLogEntry]:
        logs = self._audit_logs.get(user_id, [])
        return [l.model_copy(deep=True) for l in logs[:limit]]

    # --- Workflow History Operations ---
    def save_workflow(self, workflow: Any, user_id: str = DEFAULT_USER_ID) -> Any:
        store = self._workflows.setdefault(user_id, {})
        store.pop(workflow.workflow_id, None)
        store[workflow.workflow_id] = workflow.model_copy(deep=True)
        while len(store) > MAX_WORKFLOWS_PER_USER:
            store.pop(next(iter(store)))
        return workflow

    def get_workflow(self, workflow_id: str, user_id: str = DEFAULT_USER_ID) -> Any | None:
        wf = self._workflows.get(user_id, {}).get(workflow_id)
        return wf.model_copy(deep=True) if wf is not None else None

    def list_workflows(self, limit: int = 20, user_id: str = DEFAULT_USER_ID) -> list[Any]:
        items = list(self._workflows.get(user_id, {}).values())
        items.sort(key=lambda w: w.updated_at, reverse=True)
        return [w.model_copy(deep=True) for w in items[:limit]]

    # --- Cleanup / Testing Operations ---
    def clear_tasks(self, user_id: str = DEFAULT_USER_ID) -> None:
        self._get_user_tasks(user_id).clear()

    def clear_schedule(self, user_id: str = DEFAULT_USER_ID) -> None:
        self._get_user_events(user_id).clear()

    def clear_notes(self, user_id: str = DEFAULT_USER_ID) -> None:
        self._get_user_notes(user_id).clear()

    def clear_all(self, user_id: str = DEFAULT_USER_ID) -> None:
        self.clear_tasks(user_id)
        self.clear_schedule(user_id)
        self.clear_notes(user_id)
        self.reset_preferences(user_id)
        if user_id in self._audit_logs:
            self._audit_logs[user_id].clear()
        self._workflows.pop(user_id, None)
