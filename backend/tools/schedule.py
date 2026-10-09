from datetime import date, date as dt_date, datetime, datetime as dt_datetime, time, time as dt_time, timedelta
from typing import Any
import uuid

try:
    from models.agent import ScheduleEvent, ScheduleStatus
    from services.identity import current_user_id
    from services.persistence import (
        DEFAULT_USER_ID,
        EntityNotFoundError,
        get_persistence,
    )
except ImportError:
    from backend.models.agent import ScheduleEvent, ScheduleStatus
    from backend.services.identity import current_user_id
    from backend.services.persistence import (
        DEFAULT_USER_ID,
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

    conflicting_events = [
        event
        for event in _events.values()
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


def find_available_slots(
    date: datetime | date | str,
    duration_minutes: int,
    preferred_start: datetime | time | str | None = None,
    preferred_end: datetime | time | str | None = None,
) -> list[dict[str, Any]]:
    """
    Locate all available non-conflicting time slots on a given date for the requested duration.
    Calculates gaps between existing non-cancelled events within the preferred time window.
    Does not invent existing events or modify storage.
    """
    if duration_minutes <= 0:
        raise ValueError("duration_minutes must be positive")

    # Resolve target date
    if isinstance(date, str):
        target_date = (
            datetime.fromisoformat(date).date()
            if "T" in date or "-" in date
            else datetime.now().date()
        )
    elif isinstance(date, dt_datetime):
        target_date = date.date()
    elif isinstance(date, dt_date):
        target_date = date
    else:
        target_date = datetime.now().date()

    # Resolve window start
    if preferred_start is None:
        window_start = datetime.combine(target_date, time(9, 0))
    elif isinstance(preferred_start, datetime):
        window_start = preferred_start
    elif isinstance(preferred_start, time):
        window_start = datetime.combine(target_date, preferred_start)
    elif isinstance(preferred_start, str):
        window_start = (
            datetime.fromisoformat(preferred_start)
            if "T" in preferred_start
            else datetime.combine(target_date, time.fromisoformat(preferred_start))
        )
    else:
        window_start = datetime.combine(target_date, time(9, 0))

    # Resolve window end
    if preferred_end is None:
        window_end = datetime.combine(target_date, time(21, 0))
    elif isinstance(preferred_end, datetime):
        window_end = preferred_end
    elif isinstance(preferred_end, time):
        window_end = datetime.combine(target_date, preferred_end)
    elif isinstance(preferred_end, str):
        window_end = (
            datetime.fromisoformat(preferred_end)
            if "T" in preferred_end
            else datetime.combine(target_date, time.fromisoformat(preferred_end))
        )
    else:
        window_end = datetime.combine(target_date, time(21, 0))

    if window_end <= window_start:
        return []

    # Get overlapping active events sorted by start time
    active_events = [
        event
        for event in _events.values()
        if event.status != "cancelled"
        and event.start_time < window_end
        and event.end_time > window_start
    ]
    active_events.sort(key=lambda e: e.start_time)

    available_slots: list[dict[str, Any]] = []
    curr = window_start

    for ev in active_events:
        gap_start = max(curr, window_start)
        gap_end = min(ev.start_time, window_end)
        if gap_end > gap_start:
            gap_minutes = (gap_end - gap_start).total_seconds() / 60
            if gap_minutes >= duration_minutes:
                slot_end = gap_start + timedelta(minutes=duration_minutes)
                available_slots.append(
                    {
                        "start_time": gap_start,
                        "end_time": slot_end,
                        "duration_minutes": duration_minutes,
                        "available_duration_minutes": int(gap_minutes),
                    }
                )
        curr = max(curr, ev.end_time)

    # Check remaining time after last event
    gap_start = max(curr, window_start)
    if window_end > gap_start:
        gap_minutes = (window_end - gap_start).total_seconds() / 60
        if gap_minutes >= duration_minutes:
            slot_end = gap_start + timedelta(minutes=duration_minutes)
            available_slots.append(
                {
                    "start_time": gap_start,
                    "end_time": slot_end,
                    "duration_minutes": duration_minutes,
                    "available_duration_minutes": int(gap_minutes),
                }
            )

    return available_slots


def propose_study_blocks(
    requirements: list[dict[str, Any]] | list[tuple[str, int]] | dict[str, int],
    target_date: datetime | date | str,
    preferred_start: datetime | time | str | None = None,
    preferred_end: datetime | time | str | None = None,
) -> list[ScheduleEvent]:
    """
    Convert study requirements into schedule proposals based on available time slots.
    Does NOT modify schedule storage; this is purely a proposal stage.
    """
    normalized: list[tuple[str, int]] = []
    if isinstance(requirements, dict):
        normalized = [(str(k), int(v)) for k, v in requirements.items()]
    elif isinstance(requirements, list):
        for item in requirements:
            if isinstance(item, dict):
                subject = str(item.get("subject") or item.get("title") or "Study")
                duration = int(item.get("duration_minutes") or item.get("duration") or 60)
                normalized.append((subject, duration))
            elif isinstance(item, (tuple, list)) and len(item) >= 2:
                normalized.append((str(item[0]), int(item[1])))

    proposals: list[ScheduleEvent] = []
    allocated_intervals: list[tuple[datetime, datetime]] = []

    existing_intervals = [
        (e.start_time, e.end_time)
        for e in _events.values()
        if e.status != "cancelled"
    ]

    for subject, duration_mins in normalized:
        blocked = sorted(existing_intervals + allocated_intervals, key=lambda x: x[0])

        if isinstance(target_date, str):
            t_date = (
                datetime.fromisoformat(target_date).date()
                if "T" in target_date or "-" in target_date
                else datetime.now().date()
            )
        elif isinstance(target_date, dt_datetime):
            t_date = target_date.date()
        elif isinstance(target_date, dt_date):
            t_date = target_date
        else:
            t_date = datetime.now().date()

        if preferred_start is None:
            win_start = datetime.combine(t_date, time(9, 0))
        elif isinstance(preferred_start, datetime):
            win_start = preferred_start
        elif isinstance(preferred_start, time):
            win_start = datetime.combine(t_date, preferred_start)
        elif isinstance(preferred_start, str):
            win_start = (
                datetime.fromisoformat(preferred_start)
                if "T" in preferred_start
                else datetime.combine(t_date, time.fromisoformat(preferred_start))
            )
        else:
            win_start = datetime.combine(t_date, time(9, 0))

        if preferred_end is None:
            win_end = datetime.combine(t_date, time(21, 0))
        elif isinstance(preferred_end, datetime):
            win_end = preferred_end
        elif isinstance(preferred_end, time):
            win_end = datetime.combine(t_date, preferred_end)
        elif isinstance(preferred_end, str):
            win_end = (
                datetime.fromisoformat(preferred_end)
                if "T" in preferred_end
                else datetime.combine(t_date, time.fromisoformat(preferred_end))
            )
        else:
            win_end = datetime.combine(t_date, time(21, 0))

        curr = win_start
        found_slot = None

        for b_start, b_end in blocked:
            if b_end <= win_start or b_start >= win_end:
                continue
            gap_start = max(curr, win_start)
            gap_end = min(b_start, win_end)
            if (
                gap_end > gap_start
                and (gap_end - gap_start).total_seconds() / 60 >= duration_mins
            ):
                found_slot = (gap_start, gap_start + timedelta(minutes=duration_mins))
                break
            curr = max(curr, b_end)

        if not found_slot:
            gap_start = max(curr, win_start)
            if (
                win_end > gap_start
                and (win_end - gap_start).total_seconds() / 60 >= duration_mins
            ):
                found_slot = (gap_start, gap_start + timedelta(minutes=duration_mins))

        if found_slot:
            slot_s, slot_e = found_slot
            allocated_intervals.append((slot_s, slot_e))
            proposals.append(
                ScheduleEvent(
                    id=f"prop_{uuid.uuid4().hex[:8]}",
                    title=f"{subject} Study",
                    description=f"Study {subject} for {duration_mins} minutes",
                    start_time=slot_s,
                    end_time=slot_e,
                    status="scheduled",
                    requires_approval=True,
                )
            )

    return proposals
