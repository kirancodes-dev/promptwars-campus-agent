"""
Slot finding and study-block allocation. Pure functions over a Calendar of busy intervals;
nothing here reads or writes storage.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
import math

TIME_OF_DAY_WINDOWS = {
    "morning": (time(6, 0), time(12, 0)),
    "afternoon": (time(12, 0), time(17, 0)),
    "evening": (time(17, 0), time(22, 0)),
    "night": (time(19, 0), time(23, 59)),
}
MAX_BLOCKS = 12


@dataclass
class StudyWindow:
    start: time
    end: time
    break_minutes: int = 0
    study_days: tuple[str, ...] = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass
class Block:
    subject: str
    minutes: int
    start: datetime
    end: datetime
    reason: str


@dataclass
class AllocationError:
    kind: str  # "conflict" | "no_slot" | "no_days" | "capacity" | "too_many"
    subject: str = ""
    minutes: int = 0
    clash: str = ""
    requested_start: datetime | None = None
    free_minutes: int = 0
    days: list[date] = field(default_factory=list)
    deadline: date | None = None
    blocks_needed: int = 0


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and a_end > b_start


def first_free_slot(window_start: datetime, window_end: datetime, busy: list[tuple[datetime, datetime]], minutes: int) -> tuple[datetime, datetime] | None:
    cursor = window_start
    for b_start, b_end in sorted(busy):
        if b_end <= cursor:
            continue
        if b_start >= window_end:
            break
        if (b_start - cursor).total_seconds() / 60 >= minutes:
            return cursor, cursor + timedelta(minutes=minutes)
        cursor = max(cursor, b_end)
    if (window_end - cursor).total_seconds() / 60 >= minutes:
        return cursor, cursor + timedelta(minutes=minutes)
    return None


def _round_up(dt: datetime, minutes: int = 15) -> datetime:
    extra = (-dt.minute) % minutes
    rounded = dt.replace(second=0, microsecond=0) + timedelta(minutes=extra)
    return rounded if rounded >= dt else rounded + timedelta(minutes=minutes)


class Calendar:
    """Busy time: existing events, a stated meeting, and study blocks allocated so far."""

    def __init__(self, busy: list[tuple[datetime, datetime, str]], now: datetime, window: StudyWindow) -> None:
        self.busy = list(busy)
        self.now = now
        self.window = window

    def add(self, start: datetime, end: datetime, label: str) -> None:
        self.busy.append((start, end, label))

    def clash(self, start: datetime, end: datetime) -> str | None:
        return next((label for s, e, label in self.busy if overlaps(start, end, s, e)), None)

    def day_bounds(self, day: date) -> tuple[datetime, datetime]:
        start = datetime.combine(day, self.window.start)
        end = datetime.combine(day, self.window.end)
        if day == self.now.date():
            start = max(start, _round_up(self.now))
        return start, end

    def _occupied(self) -> list[tuple[datetime, datetime]]:
        # A break is kept after every planned study block.
        return [
            (s, e + timedelta(minutes=self.window.break_minutes if label.endswith("study block") else 0))
            for s, e, label in self.busy
        ]

    def find_slot(self, day: date, minutes: int, timing: str | None = None) -> tuple[tuple[datetime, datetime], str] | None:
        day_start, day_end = self.day_bounds(day)
        if day_end <= day_start:
            return None
        occupied = self._occupied()
        if timing in TIME_OF_DAY_WINDOWS:
            t_start, t_end = TIME_OF_DAY_WINDOWS[timing]
            pref_start = max(day_start, datetime.combine(day, t_start))
            pref_end = min(day_end, datetime.combine(day, t_end))
            if pref_end > pref_start:
                slot = first_free_slot(pref_start, pref_end, occupied, minutes)
                if slot:
                    return slot, f"your saved {timing} preference"
        slot = first_free_slot(day_start, day_end, occupied, minutes)
        return (slot, "earliest free time in your study window") if slot else None

    def free_minutes(self, day: date) -> int:
        day_start, day_end = self.day_bounds(day)
        if day_end <= day_start:
            return 0
        total, cursor = 0, day_start
        for s, e in sorted(self._occupied()):
            if e <= cursor or s >= day_end:
                continue
            total += max(0, (min(s, day_end) - cursor).total_seconds() / 60)
            cursor = max(cursor, e)
        total += max(0, (day_end - cursor).total_seconds() / 60)
        return int(total)


def allocate_single_day(
    requests: list[tuple[str, int]],
    day: date,
    calendar: Calendar,
    explicit_times: dict[str, time],
    timing: dict[str, str],
) -> tuple[list[Block], AllocationError | None]:
    """Place each (subject, minutes) on one day, in the given order (priority first)."""
    blocks: list[Block] = []
    for subject, minutes in requests:
        if subject in explicit_times:
            start = datetime.combine(day, explicit_times[subject])
            end = start + timedelta(minutes=minutes)
            clash = calendar.clash(start, end)
            if clash:
                return blocks, AllocationError("conflict", subject, minutes, clash=clash, requested_start=start)
            slot, reason = (start, end), "the time you asked for"
        else:
            found = calendar.find_slot(day, minutes, timing.get(subject))
            if not found:
                return blocks, AllocationError("no_slot", subject, minutes, free_minutes=calendar.free_minutes(day), days=[day])
            slot, reason = found
        calendar.add(slot[0], slot[1], f"{subject} study block")
        blocks.append(Block(subject, minutes, slot[0], slot[1], reason))
    return blocks, None


def split_sessions(total_minutes: int, session_minutes: int) -> list[int]:
    """Split a total into sessions of the preferred length; a remainder under 15 min joins the last one."""
    session = max(15, session_minutes)
    chunks = [session] * (total_minutes // session)
    rest = total_minutes % session
    if rest >= 15 or not chunks:
        chunks.append(rest if chunks else total_minutes)
    elif rest:
        chunks[-1] += rest
    return chunks


def allocate_until_deadlines(
    subjects: list[tuple[str, int, date]],
    start_day: date,
    calendar: Calendar,
    session_minutes: int,
    timing: dict[str, str],
) -> tuple[list[Block], AllocationError | None]:
    """
    Earliest-deadline-first: subjects are processed in the given order (deadline, then priority).
    Each subject's total is split into sessions and spread evenly over the study days before its
    exam (never on the exam day), respecting the study window, preferred study days and breaks.
    """
    blocks: list[Block] = []
    needed = sum(len(split_sessions(m, session_minutes)) for _, m, _ in subjects)
    if needed > MAX_BLOCKS:
        return blocks, AllocationError("too_many", blocks_needed=needed)

    for subject, total, deadline in subjects:
        days = [
            start_day + timedelta(days=i)
            for i in range((deadline - start_day).days)
            if (start_day + timedelta(days=i)).strftime("%A") in calendar.window.study_days
        ]
        if not days:
            return blocks, AllocationError("no_days", subject, total, deadline=deadline)
        chunks = split_sessions(total, session_minutes)
        per_day = math.ceil(len(chunks) / len(days))
        placed: list[Block] = []
        for pass_limit in (per_day, len(chunks)):  # spread first, then use any remaining capacity
            for day in days:
                on_day = sum(1 for b in placed if b.start.date() == day)
                while chunks and on_day < pass_limit:
                    found = calendar.find_slot(day, chunks[0], timing.get(subject))
                    if not found:
                        break
                    (s, e), reason = found
                    calendar.add(s, e, f"{subject} study block")
                    placed.append(Block(subject, chunks.pop(0), s, e, reason))
                    on_day += 1
            if not chunks:
                break
        blocks.extend(placed)
        if chunks:
            return blocks, AllocationError(
                "capacity", subject, total,
                # free time that existed for this subject = what is still free + what it already used
                free_minutes=sum(calendar.free_minutes(d) for d in days) + sum(b.minutes for b in placed),
                days=days, deadline=deadline,
            )
    return blocks, None
