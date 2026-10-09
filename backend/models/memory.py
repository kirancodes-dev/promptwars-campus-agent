from datetime import datetime
import re
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VALID_DAYS = {
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
}

TIME_OF_DAY = {"morning", "afternoon", "evening", "night"}
MAX_LIST_ITEMS = 20
MAX_SUBJECT_CHARS = 40
MAX_NOTE_CHARS = 300

SENSITIVE_KEYWORDS = [
    "password",
    "passwd",
    "secret",
    "ssn",
    "credit_card",
    "creditcard",
    "token",
    "api_key",
    "apikey",
    "private_key",
]


def _validate_time_format(val: str, field_name: str) -> str:
    val_str = str(val).strip()
    match = re.match(r"^([01]\d|2[0-3]):([0-5]\d)$", val_str)
    if not match:
        raise ValueError(
            f"Invalid time format for '{field_name}': '{val}'. "
            "Must be in 24-hour 'HH:MM' format (e.g. '09:00', '21:30')."
        )
    return val_str


class StudentPreferences(BaseModel):
    """
    Structured model for persistent student preferences and memory.
    Enforces safe bounds, valid time strings, and sensible defaults.
    """

    preferred_study_start: str = Field(
        default="09:00",
        description="Daily preferred earliest study start time in 24h 'HH:MM' format",
    )
    preferred_study_end: str = Field(
        default="21:00",
        description="Daily preferred latest study end time in 24h 'HH:MM' format",
    )
    preferred_session_minutes: int = Field(
        default=60,
        ge=15,
        le=360,
        description="Target focus session duration in minutes (15 - 360)",
    )
    preferred_break_minutes: int = Field(
        default=10,
        ge=0,
        le=120,
        description="Target break duration between focus sessions in minutes (0 - 120)",
    )
    preferred_study_days: list[str] = Field(
        default_factory=lambda: [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ],
        description="Days of the week the student prefers to schedule study sessions",
    )
    preferred_subjects: list[str] = Field(
        default_factory=list,
        description="Academic subjects prioritized by the student",
    )
    subject_time_preferences: dict[str, str] = Field(
        default_factory=dict,
        description="Preferred time of day for specific subjects (e.g. {'DBMS': 'evening'})",
    )
    planning_notes: list[str] = Field(
        default_factory=list,
        description="Explicit user-supplied scheduling constraints or notes",
    )
    updated_at: datetime | None = Field(
        default=None,
        description="Timestamp when preferences were last modified",
    )

    @field_validator("preferred_study_start")
    @classmethod
    def validate_start(cls, v: str) -> str:
        return _validate_time_format(v, "preferred_study_start")

    @field_validator("preferred_study_end")
    @classmethod
    def validate_end(cls, v: str) -> str:
        return _validate_time_format(v, "preferred_study_end")

    @field_validator("preferred_study_days")
    @classmethod
    def validate_days(cls, days: list[str]) -> list[str]:
        validated = []
        for d in days:
            d_clean = str(d).strip().capitalize()
            if d_clean.lower() not in VALID_DAYS:
                raise ValueError(
                    f"Invalid day '{d}'. Must be a valid day of the week (e.g. 'Monday')."
                )
            if d_clean not in validated:
                validated.append(d_clean)
        return validated

    @field_validator("preferred_subjects")
    @classmethod
    def validate_subjects(cls, subjects: list[str]) -> list[str]:
        cleaned: list[str] = []
        for s in subjects:
            s_clean = str(s).strip()
            if not s_clean:
                continue
            if len(s_clean) > MAX_SUBJECT_CHARS:
                raise ValueError(f"Subject names must be at most {MAX_SUBJECT_CHARS} characters.")
            if s_clean not in cleaned:
                cleaned.append(s_clean)
        if len(cleaned) > MAX_LIST_ITEMS:
            raise ValueError(f"At most {MAX_LIST_ITEMS} subjects can be saved.")
        return cleaned

    @field_validator("subject_time_preferences")
    @classmethod
    def validate_subject_times(cls, prefs: dict[str, str]) -> dict[str, str]:
        if len(prefs) > MAX_LIST_ITEMS:
            raise ValueError(f"At most {MAX_LIST_ITEMS} subject timing preferences can be saved.")
        cleaned: dict[str, str] = {}
        for subject, when in prefs.items():
            subject_clean = str(subject).strip()
            when_clean = str(when).strip().lower()
            if not subject_clean or len(subject_clean) > MAX_SUBJECT_CHARS:
                raise ValueError("Each subject timing needs a subject name of at most 40 characters.")
            if when_clean not in TIME_OF_DAY:
                raise ValueError(f"Timing for '{subject_clean}' must be one of: {', '.join(sorted(TIME_OF_DAY))}.")
            cleaned[subject_clean] = when_clean
        return cleaned

    @field_validator("planning_notes")
    @classmethod
    def sanitize_planning_notes(cls, notes: list[str]) -> list[str]:
        if len(notes) > MAX_LIST_ITEMS:
            raise ValueError(f"At most {MAX_LIST_ITEMS} planning notes can be saved.")
        cleaned = []
        for n in notes:
            if len(str(n)) > MAX_NOTE_CHARS:
                raise ValueError(f"Planning notes must be at most {MAX_NOTE_CHARS} characters.")
            n_clean = str(n).strip()
            n_lower = n_clean.lower()
            for kw in SENSITIVE_KEYWORDS:
                if kw in n_lower:
                    raise ValueError(
                        f"Sensitive personal information or credentials cannot be stored in preferences (detected '{kw}')."
                    )
            if n_clean and n_clean not in cleaned:
                cleaned.append(n_clean)
        return cleaned

    @model_validator(mode="after")
    def validate_time_window(self) -> "StudentPreferences":
        start_parts = [int(p) for p in self.preferred_study_start.split(":")]
        end_parts = [int(p) for p in self.preferred_study_end.split(":")]
        start_min = start_parts[0] * 60 + start_parts[1]
        end_min = end_parts[0] * 60 + end_parts[1]
        if end_min <= start_min:
            raise ValueError(
                f"preferred_study_end ('{self.preferred_study_end}') must be strictly "
                f"after preferred_study_start ('{self.preferred_study_start}')."
            )
        return self


class StudentPreferencesUpdate(BaseModel):
    """Payload for partial updates to student preferences."""

    model_config = ConfigDict(extra="forbid")

    preferred_study_start: str | None = None
    preferred_study_end: str | None = None
    preferred_session_minutes: int | None = Field(default=None, ge=15, le=360)
    preferred_break_minutes: int | None = Field(default=None, ge=0, le=120)
    preferred_study_days: list[str] | None = None
    preferred_subjects: list[str] | None = None
    subject_time_preferences: dict[str, str] | None = None
    planning_notes: list[str] | None = None
