from typing import Any

try:
    from services.memory import MemoryService
    from services.identity import current_user_id
except ImportError:
    from backend.services.memory import MemoryService
    from backend.services.identity import current_user_id

_memory_service = MemoryService()


def get_memory_service() -> MemoryService:
    return _memory_service


def get_student_preferences() -> dict[str, Any]:
    """Retrieve saved student preferences and summary."""
    service = get_memory_service()
    user_id = current_user_id()
    pref = service.get_preferences(user_id=user_id)
    summary = service.get_memory_summary(user_id=user_id)
    return {
        "preferences": pref.model_dump(),
        "summary": summary,
    }


def update_student_preferences(
    preferred_study_start: str | None = None,
    preferred_study_end: str | None = None,
    preferred_session_minutes: int | None = None,
    preferred_break_minutes: int | None = None,
    preferred_study_days: list[str] | None = None,
    preferred_subjects: list[str] | None = None,
    subject_time_preferences: dict[str, str] | None = None,
    planning_notes: list[str] | None = None,
    requires_approval: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Update student study preferences.
    Requires approval when executed via Agent Router/Executor.
    """
    updates: dict[str, Any] = {}
    if preferred_study_start is not None:
        updates["preferred_study_start"] = preferred_study_start
    if preferred_study_end is not None:
        updates["preferred_study_end"] = preferred_study_end
    if preferred_session_minutes is not None:
        updates["preferred_session_minutes"] = preferred_session_minutes
    if preferred_break_minutes is not None:
        updates["preferred_break_minutes"] = preferred_break_minutes
    if preferred_study_days is not None:
        updates["preferred_study_days"] = preferred_study_days
    if preferred_subjects is not None:
        updates["preferred_subjects"] = preferred_subjects
    if subject_time_preferences is not None:
        updates["subject_time_preferences"] = subject_time_preferences
    if planning_notes is not None:
        updates["planning_notes"] = planning_notes

    service = get_memory_service()
    user_id = current_user_id()
    updated = service.update_preferences(updates, user_id=user_id)
    summary = service.get_memory_summary(user_id=user_id)
    return {
        "success": True,
        "preferences": updated.model_dump(),
        "summary": summary,
        "updated_fields": list(updates.keys()),
    }


def reset_student_preferences(
    confirmation: bool = False,
    requires_approval: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Reset student preferences to defaults.
    Requires explicit confirmation=True and approval.
    """
    service = get_memory_service()
    user_id = current_user_id()
    reset_pref = service.reset_preferences(confirmation=confirmation, user_id=user_id)
    summary = service.get_memory_summary(user_id=user_id)
    return {
        "success": True,
        "message": "Student preferences successfully reset to defaults.",
        "preferences": reset_pref.model_dump(),
        "summary": summary,
    }
