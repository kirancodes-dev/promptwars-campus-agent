from datetime import datetime
import logging
import re
from typing import Any

from models.memory import StudentPreferences, StudentPreferencesUpdate
from services.identity import current_user_id
from services.persistence import get_persistence

logger = logging.getLogger(__name__)


class MemoryService:
    """
    Core memory service for student study preferences.
    Interacts with the active persistence layer (InMemory or Firestore)
    under isolated user keys.
    """

    def __init__(self, persistence: Any | None = None) -> None:
        self._persistence = persistence

    @property
    def persistence(self) -> Any:
        return self._persistence or get_persistence()

    def get_preferences(self, user_id: str | None = None) -> StudentPreferences:
        """Retrieve student preferences for a given user."""
        return self.persistence.get_preferences(user_id=user_id or current_user_id())

    def update_preferences(
        self,
        updates: dict[str, Any] | StudentPreferencesUpdate,
        user_id: str | None = None,
        merge_collections: bool = True,
    ) -> StudentPreferences:
        """
        Apply partial updates to existing student preferences.
        Validates values against the StudentPreferences Pydantic schema.
        merge_collections=True (agent "remember ..." requests) appends notes/subjects and merges
        subject timings; False (the preferences form) replaces them with exactly what was submitted.
        """
        existing = self.get_preferences(user_id=user_id or current_user_id())
        current_data = existing.model_dump()

        if isinstance(updates, StudentPreferencesUpdate):
            update_dict = updates.model_dump(exclude_unset=True)
        elif isinstance(updates, dict):
            update_dict = {k: v for k, v in updates.items() if v is not None}
        else:
            raise ValueError("Updates must be a dictionary or StudentPreferencesUpdate.")

        # Merge dictionary fields (e.g. subject_time_preferences)
        if merge_collections and "subject_time_preferences" in update_dict and isinstance(
            update_dict["subject_time_preferences"], dict
        ):
            merged_times = dict(current_data.get("subject_time_preferences") or {})
            merged_times.update(update_dict["subject_time_preferences"])
            update_dict["subject_time_preferences"] = merged_times

        # Merge list fields (e.g. planning_notes)
        if merge_collections and "planning_notes" in update_dict and isinstance(
            update_dict["planning_notes"], list
        ):
            merged_notes = list(current_data.get("planning_notes") or [])
            for note in update_dict["planning_notes"]:
                if note and note not in merged_notes:
                    merged_notes.append(note)
            update_dict["planning_notes"] = merged_notes

        # Merge unique preferred subjects
        if merge_collections and "preferred_subjects" in update_dict and isinstance(
            update_dict["preferred_subjects"], list
        ):
            merged_subjs = list(current_data.get("preferred_subjects") or [])
            for s in update_dict["preferred_subjects"]:
                if s and s not in merged_subjs:
                    merged_subjs.append(s)
            update_dict["preferred_subjects"] = merged_subjs

        current_data.update(update_dict)
        current_data["updated_at"] = datetime.now()

        # Validate with Pydantic
        new_preferences = StudentPreferences(**current_data)
        return self.persistence.update_preferences(new_preferences, user_id=user_id or current_user_id())

    def reset_preferences(
        self,
        confirmation: bool = False,
        user_id: str | None = None,
    ) -> StudentPreferences:
        """
        Reset student preferences to defaults.
        Requires explicit confirmation=True to prevent accidental resets.
        """
        if not confirmation:
            raise ValueError(
                "Explicit confirmation is required to reset student preferences. Pass confirmation=True."
            )
        return self.persistence.reset_preferences(user_id=user_id or current_user_id())

    def get_memory_summary(self, user_id: str | None = None, preferences: StudentPreferences | None = None) -> str:
        """
        Return a concise, readable summary of the user's active preferences and memory.
        """
        pref = preferences or self.get_preferences(user_id=user_id or current_user_id())
        lines = [
            f"Study Window: {pref.preferred_study_start} - {pref.preferred_study_end}",
            f"Session Duration: {pref.preferred_session_minutes} mins (Break: {pref.preferred_break_minutes} mins)",
            f"Active Days: {', '.join(pref.preferred_study_days)}",
        ]
        if pref.preferred_subjects:
            lines.append(f"Preferred Subjects: {', '.join(pref.preferred_subjects)}")
        if pref.subject_time_preferences:
            sub_times = [f"{s} ({t})" for s, t in pref.subject_time_preferences.items()]
            lines.append(f"Subject Timing: {', '.join(sub_times)}")
        if pref.planning_notes:
            lines.append(f"Planning Notes: {'; '.join(pref.planning_notes)}")

        return " | ".join(lines)

    def identify_influencing_preferences(
        self,
        goal_text: str,
        preferences: StudentPreferences | None = None,
        user_id: str | None = None,
    ) -> list[str]:
        """
        Determine which saved preferences directly influence a plan for the given goal.
        Never invents preferences that were not explicitly saved.
        """
        pref = preferences or self.get_preferences(user_id=user_id or current_user_id())
        goal_lower = goal_text.lower()
        influences: list[str] = []

        # Check subject timing preferences
        for subj, time_pref in pref.subject_time_preferences.items():
            if subj.lower() in goal_lower:
                influences.append(
                    f"Scheduled {subj} during your preferred {time_pref} study window."
                )

        # Check break minutes
        if pref.preferred_break_minutes > 0:
            influences.append(
                f"Applied preferred {pref.preferred_break_minutes}-minute break between sessions."
            )

        # Check session duration
        influences.append(
            f"Target focus session duration set to {pref.preferred_session_minutes} minutes."
        )

        # Check planning notes
        for note in pref.planning_notes:
            note_words = set(re.findall(r"\w+", note.lower())) - {
                "i", "a", "the", "in", "after", "and", "that", "prefer", "to", "my"
            }
            if any(w in goal_lower for w in note_words):
                influences.append(f"Constraint respected: {note}")

        return influences
