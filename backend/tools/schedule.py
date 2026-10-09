from datetime import date, date as dt_date, datetime, datetime as dt_datetime, time, timedelta
from typing import Any
import uuid

from models.agent import ScheduleEvent
from services.identity import current_user_id
from services.persistence import (
    EntityNotFoundError,
    get_persistence,
)


class EventNotFoundError(KeyError):
    """Raised when a schedule event ID is not found."""
    pass


class _EventDictProxy(dict):
    """Transparent dict proxy exposing schedule events from active persistence for backward-compatibility."""

    def __getitem__(self, key: str) -> ScheduleEvent:
        event = get_persistence().get_event(key, user_id=current_user_id())
        if event is None:
            raise KeyError(key)
        return event

    def __setitem__(self, key: str, value: ScheduleEvent) -> None:
        get_persistence().create_event(value, user_id=current_user_id())

    def __delitem__(self, key: str) -> None:
        try:
            get_persistence().delete_event(key, user_id=current_user_id())
        except EntityNotFoundError:
            raise KeyError(key)

    def __contains__(self, key: Any) -> bool:
        if not isinstance(key, str):
            return False
        return get_persistence().get_event(key, user_id=current_user_id()) is not None

    def __len__(self) -> int:
        return len(get_persistence().get_events(user_id=current_user_id()))

    def __iter__(self):
        return iter(e.id for e in get_persistence().get_events(user_id=current_user_id()))

    def values(self):
        return get_persistence().get_events(user_id=current_user_id())

    def keys(self):
        return [e.id for e in get_persistence().get_events(user_id=current_user_id())]

    def items(self):
        return [(e.id, e) for e in get_persistence().get_events(user_id=current_user_id())]

    def get(self, key: str, default: Any = None) -> Any:
        event = get_persistence().get_event(key, user_id=current_user_id())
        return event if event is not None else default

    def clear(self) -> None:
        get_persistence().clear_schedule(user_id=current_user_id())


# In-memory proxy exposing active persistence layer
_events: dict[str, ScheduleEvent] = _EventDictProxy()


def clear_schedule() -> None:
    """Clear all schedule events from active persistence storage."""
    get_persistence().clear_schedule(user_id=current_user_id())


def create_schedule(
    title: str,
    start_time: datetime,
    end_time: datetime,
    description: str | None = None,
    requires_approval: bool = False,
) -> ScheduleEvent:
    """Create a new schedule event after validating start and end times."""
    if end_time <= start_time:
        raise ValueError("end_time must be after start_time")

    event_id = f"event_{uuid.uuid4().hex[:8]}"
    event = ScheduleEvent(
        id=event_id,
        title=title,
        description=description,
        start_time=start_time,
        end_time=end_time,
        status="scheduled",
        requires_approval=requires_approval,
    )
    return get_persistence().create_event(event, user_id=current_user_id())


def get_schedule(
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> list[ScheduleEvent]:
    """Retrieve schedule events within a time range, or all events if range is omitted."""
    if start_time is not None and end_time is not None:
        if end_time <= start_time:
            raise ValueError("end_time must be after start_time")
    return get_persistence().get_events(start_time=start_time, end_time=end_time, user_id=current_user_id())


def get_event(event_id: str) -> ScheduleEvent:
    """Retrieve a single schedule event by ID or raise EventNotFoundError."""
    event = get_persistence().get_event(event_id, user_id=current_user_id())
    if event is None:
        raise EventNotFoundError(f"Schedule event with ID '{event_id}' not found.")
    return event


def update_schedule(
    event_id: str,
    title: str | None = None,
    description: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    status: str | None = None,
) -> ScheduleEvent:
    """Update an existing schedule event by ID."""
    existing_event = get_persistence().get_event(event_id, user_id=current_user_id())
    if existing_event is None:
        raise EventNotFoundError(f"Schedule event with ID '{event_id}' not found.")

    eff_start = start_time if start_time is not None else existing_event.start_time
    eff_end = end_time if end_time is not None else existing_event.end_time
    if eff_end <= eff_start:
        raise ValueError("end_time must be after start_time")


    updates: dict[str, Any] = {}
    if title is not None:
        updates["title"] = title
    if description is not None:
        updates["description"] = description
    if start_time is not None:
        updates["start_time"] = start_time
    if end_time is not None:
        updates["end_time"] = end_time
    if status is not None:
        updates["status"] = status

    # Validate full model representation
    current_dict = existing_event.model_dump()
    current_dict.update(updates)
    ScheduleEvent(**current_dict)

    try:
        return get_persistence().update_event(event_id, updates, user_id=current_user_id())
    except EntityNotFoundError:
        raise EventNotFoundError(f"Schedule event with ID '{event_id}' not found.")


def delete_schedule(event_id: str) -> dict[str, Any]:
    """Delete a schedule event by ID. Raises EventNotFoundError if not found."""
    try:
        get_persistence().delete_event(event_id, user_id=current_user_id())
        return {"success": True, "event_id": event_id}
    except EntityNotFoundError:
        raise EventNotFoundError(f"Schedule event with ID '{event_id}' not found.")


def check_schedule_conflict(
    start_time: datetime | str,
    end_time: datetime | str,
    exclude_event_id: str | None = None,
) -> dict[str, Any]:
    """
    Check whether a requested time interval conflicts with any existing active event.
    Uses strict open-ended interval logic [S1, E1) ∩ [S2, E2) != ∅:
    Two events conflict if start_1 < end_2 and end_1 > start_2.
    Adjacent events (end_1 == start_2 or start_1 == end_2) do NOT conflict.
    """
    if isinstance(start_time, str):
        start_time = datetime.fromisoformat(start_time)
    if isinstance(end_time, str):
        end_time = datetime.fromisoformat(end_time)

    if end_time <= start_time:
        raise ValueError("end_time must be after start_time")

    nearby = get_persistence().get_events_overlapping(start_time, end_time, user_id=current_user_id())
    conflicting_events = [
        event
        for event in nearby
        if (exclude_event_id is None or event.id != exclude_event_id)
        and event.status != "cancelled"
        and event.start_time < end_time
        and event.end_time > start_time
    ]

    return {
        "has_conflict": len(conflicting_events) > 0,
        "conflicting_events": conflicting_events,
        "conflict_count": len(conflicting_events),
    }


DEFAULT_WINDOW = (time(9, 0), time(21, 0))


def _resolve_date(value: datetime | date | str | None) -> date:
    if isinstance(value, dt_datetime):
        return value.date()
    if isinstance(value, dt_date):
        return value
    if isinstance(value, str) and ("T" in value or "-" in value):
        return datetime.fromisoformat(value).date()
    return datetime.now().date()


def _resolve_bound(value: datetime | time | str | None, day: date, default: time) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, time):
        return datetime.combine(day, value)
    if isinstance(value, str):
        return datetime.fromisoformat(value) if "T" in value else datetime.combine(day, time.fromisoformat(value))
    return datetime.combine(day, default)


def _window(day_value, preferred_start, preferred_end) -> tuple[datetime, datetime]:
    day = _resolve_date(day_value)
    return (
        _resolve_bound(preferred_start, day, DEFAULT_WINDOW[0]),
        _resolve_bound(preferred_end, day, DEFAULT_WINDOW[1]),
    )


def _free_gaps(window_start: datetime, window_end: datetime, busy: list[tuple[datetime, datetime]]):
    """Yield (gap_start, gap_end) for every free interval inside the window, in time order."""
    cursor = window_start
    for b_start, b_end in sorted(busy):
        if b_end <= window_start or b_start >= window_end:
            continue
        gap_end = min(b_start, window_end)
        if gap_end > cursor:
            yield cursor, gap_end
        cursor = max(cursor, b_end)
    if window_end > cursor:
        yield cursor, window_end


def _busy_between(window_start: datetime, window_end: datetime) -> list[tuple[datetime, datetime]]:
    events = get_persistence().get_events_overlapping(window_start, window_end, user_id=current_user_id())
    return [(e.start_time, e.end_time) for e in events if e.status != "cancelled"]


def find_available_slots(
    date: datetime | date | str,
    duration_minutes: int,
    preferred_start: datetime | time | str | None = None,
    preferred_end: datetime | time | str | None = None,
) -> list[dict[str, Any]]:
    """
    One slot (at the start of each free gap) for every gap that fits the duration, on the given date
    within the preferred window (default 09:00–21:00). Reads storage; never modifies it.
    """
    if duration_minutes <= 0:
        raise ValueError("duration_minutes must be positive")
    window_start, window_end = _window(date, preferred_start, preferred_end)
    if window_end <= window_start:
        return []
    slots: list[dict[str, Any]] = []
    for gap_start, gap_end in _free_gaps(window_start, window_end, _busy_between(window_start, window_end)):
        gap_minutes = (gap_end - gap_start).total_seconds() / 60
        if gap_minutes >= duration_minutes:
            slots.append({
                "start_time": gap_start,
                "end_time": gap_start + timedelta(minutes=duration_minutes),
                "duration_minutes": duration_minutes,
                "available_duration_minutes": int(gap_minutes),
            })
    return slots


def _normalize_requirements(requirements) -> list[tuple[str, int]]:
    if isinstance(requirements, dict):
        return [(str(k), int(v)) for k, v in requirements.items()]
    normalized: list[tuple[str, int]] = []
    for item in requirements or []:
        if isinstance(item, dict):
            subject = str(item.get("subject") or item.get("title") or "Study")
            normalized.append((subject, int(item.get("duration_minutes") or item.get("duration") or 60)))
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            normalized.append((str(item[0]), int(item[1])))
    return normalized


def propose_study_blocks(
    requirements: list[dict[str, Any]] | list[tuple[str, int]] | dict[str, int],
    target_date: datetime | date | str,
    preferred_start: datetime | time | str | None = None,
    preferred_end: datetime | time | str | None = None,
) -> list[ScheduleEvent]:
    """
    Convert study requirements into schedule proposals in the first free gaps, without overlapping
    each other. Does NOT modify schedule storage; this is purely a proposal stage.
    """
    window_start, window_end = _window(target_date, preferred_start, preferred_end)
    busy = _busy_between(window_start, window_end)
    proposals: list[ScheduleEvent] = []
    for subject, minutes in _normalize_requirements(requirements):
        slot = next(
            ((g_start, g_start + timedelta(minutes=minutes))
             for g_start, g_end in _free_gaps(window_start, window_end, busy)
             if (g_end - g_start).total_seconds() / 60 >= minutes),
            None,
        )
        if slot is None:
            continue
        busy.append(slot)
        proposals.append(ScheduleEvent(
            id=f"prop_{uuid.uuid4().hex[:8]}",
            title=f"{subject} Study",
            description=f"Study {subject} for {minutes} minutes",
            start_time=slot[0],
            end_time=slot[1],
            status="scheduled",
            requires_approval=True,
        ))
    return proposals
