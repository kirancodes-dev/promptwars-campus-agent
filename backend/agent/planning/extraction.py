"""
Extract planning facts from a student's goal.

Only facts the student actually stated are extracted. Nothing here invents meetings,
deadlines, durations or preferences; missing information is reported so the planner
can ask a focused question or state its assumption.
"""

from dataclasses import dataclass, field
from datetime import date, time, timedelta
import re

_DURATION_UNIT = r"(hours?|hrs?|minutes?|mins?)"
_REQ_FORWARD = re.compile(r"(\d+(?:\.\d+)?)\s*" + _DURATION_UNIT + r"\s+(?:of\s+)?([a-z][a-z0-9+#&\-]*)", re.IGNORECASE)
_REQ_BACKWARD = re.compile(r"\b([a-z][a-z0-9+#&\-]*)\s+for\s+(\d+(?:\.\d+)?)\s*" + _DURATION_UNIT, re.IGNORECASE)
_NON_SUBJECT_WORDS = {
    "study", "studying", "revision", "revise", "the", "my", "a", "an", "meeting", "meetings",
    "break", "breaks", "sleep", "free", "time", "each", "per", "and", "of", "for", "to",
    "prep", "preparation", "work", "rest", "session", "sessions", "focus", "focused", "total",
    "class", "classes", "lecture", "lectures", "it", "that", "this", "me", "i", "be", "is",
    "exam", "exams", "test", "tests", "quiz", "every", "daily", "today", "tomorrow", "on", "in",
}
MAX_STUDY_REQUIREMENTS = 6

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_MONTH_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
_EXAM_RE = re.compile(r"\b(exam|exams|test|quiz|midterm|mid-term|final|finals|viva)\b")
_AMBIGUOUS_DATE = re.compile(r"\b(next week|this week|next month|this month|soon|later|sometime|some day|someday|weekend|in a few days)\b")
_CLAUSE_SPLIT = re.compile(r"[.;,]|\band\b|\bbut\b|\bthen\b")
_SUBJECT_STOP = {"my", "the", "an", "a", "final", "finals", "big", "next", "this", "our", "his", "her", "their", "mid", "semester"}


@dataclass
class Requirement:
    subject: str
    minutes: int


@dataclass
class GoalFacts:
    requirements: list[Requirement] = field(default_factory=list)
    target_date: date | None = None          # explicit date for a single-day plan
    target_date_phrase: str | None = None
    meeting: time | None = None
    meeting_date: date | None = None
    explicit_times: dict[str, time] = field(default_factory=dict)
    exams: dict[str, date] = field(default_factory=dict)
    exam_phrases: dict[str, str] = field(default_factory=dict)
    priorities: dict[str, str] = field(default_factory=dict)  # subject -> "high" | "low"
    ambiguous_dates: list[str] = field(default_factory=list)
    mentioned_subjects: list[str] = field(default_factory=list)


def subject_label(word: str) -> str:
    """'dbms' -> 'DBMS', 'physics' -> 'Physics'."""
    return word.upper() if len(word) <= 4 else word.capitalize()


def _to_minutes(amount: str, unit: str) -> int:
    value = float(amount)
    return int(round(value * 60)) if unit.lower().startswith("h") else int(round(value))


def parse_study_requirements(text: str) -> list[tuple[str, int]]:
    """Explicitly requested (subject, minutes) pairs: "2 hours of DBMS", "DAA for 90 minutes"."""
    found: list[tuple[int, str, int]] = []
    for m in _REQ_FORWARD.finditer(text):
        if m.group(3).lower() not in _NON_SUBJECT_WORDS:
            found.append((m.start(), subject_label(m.group(3)), _to_minutes(m.group(1), m.group(2))))
    for m in _REQ_BACKWARD.finditer(text):
        if m.group(1).lower() not in _NON_SUBJECT_WORDS:
            found.append((m.start(), subject_label(m.group(1)), _to_minutes(m.group(2), m.group(3))))
    found.sort(key=lambda x: x[0])
    reqs: list[tuple[str, int]] = []
    seen: set[str] = set()
    for _, subj, mins in found:
        if subj in seen or not (15 <= mins <= 1200):
            continue
        seen.add(subj)
        reqs.append((subj, mins))
    return reqs[:MAX_STUDY_REQUIREMENTS]


def parse_clock(hour: str, minute: str | None, meridiem: str | None, assume_pm_below: int = 7) -> time | None:
    h = int(hour)
    mn = int(minute or 0)
    if meridiem:
        meridiem = meridiem.lower()
        if meridiem == "pm" and h < 12:
            h += 12
        elif meridiem == "am" and h == 12:
            h = 0
    elif h < assume_pm_below:
        h += 12
    if not (0 <= h <= 23 and 0 <= mn <= 59):
        return None
    return time(h, mn)


def parse_meeting(text_lower: str) -> time | None:
    m = re.search(r"meeting\s+(?:is\s+)?(?:at|from)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text_lower)
    if not m:
        m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s+(?:project\s+|team\s+|group\s+)?meeting", text_lower)
    if not m:
        return None
    return parse_clock(m.group(1), m.group(2), m.group(3))


def explicit_subject_time(text_lower: str, subject: str) -> time | None:
    """Only an explicit '<subject> at 6 PM' in the same clause counts as a requested start time."""
    s = re.escape(subject.lower())
    m = re.search(
        rf"\b{s}\b\s+(?:study\s+|session\s+|revision\s+|block\s+)?(?:at|from)\s+(\d{{1,2}})(?::(\d{{2}}))?\s*(am|pm)?",
        text_lower,
    )
    if not m:
        m = re.search(rf"\bat\s+(\d{{1,2}})(?::(\d{{2}}))?\s*(am|pm)\s+(?:for\s+)?{s}\b", text_lower)
    if not m:
        return None
    return parse_clock(m.group(1), m.group(2), m.group(3))


def _next_weekday(today: date, weekday: int) -> date:
    """The next date with that weekday, strictly after today ("on Friday" said on a Friday means next Friday)."""
    days = (weekday - today.weekday()) % 7
    return today + timedelta(days=days or 7)


def _month_day(month_token: str, day: int, today: date) -> date | None:
    month = _MONTHS.index(month_token[:3]) + 1
    try:
        d = date(today.year, month, day)
    except ValueError:
        return None
    if d < today - timedelta(days=30):  # e.g. "5 Jan" said in December means next year
        try:
            d = date(today.year + 1, month, day)
        except ValueError:
            return None
    return d


def find_date(text_lower: str, today: date) -> tuple[date, str] | None:
    """First concrete date mentioned in the text, with the phrase that produced it."""
    candidates: list[tuple[int, date, str]] = []
    for pat, resolver in (
        (r"\bday after tomorrow\b", lambda m: today + timedelta(days=2)),
        (r"\btomorrow\b", lambda m: today + timedelta(days=1)),
        (r"\b(?:today|tonight)\b", lambda m: today),
        (r"\bin (\d{1,2}) days?\b", lambda m: today + timedelta(days=int(m.group(1)))),
        (r"\b(\d{4})-(\d{2})-(\d{2})\b", lambda m: date(int(m.group(1)), int(m.group(2)), int(m.group(3)))),
        (rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH_RE}\b", lambda m: _month_day(m.group(2), int(m.group(1)), today)),
        (rf"\b{_MONTH_RE}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", lambda m: _month_day(m.group(1), int(m.group(2)), today)),
        (r"\b(?:on\s+|this\s+|next\s+|coming\s+)?(" + "|".join(_WEEKDAYS) + r")\b", lambda m: _next_weekday(today, _WEEKDAYS.index(m.group(1)))),
    ):
        for m in re.finditer(pat, text_lower):
            try:
                d = resolver(m)
            except ValueError:
                d = None
            if d is not None:
                candidates.append((m.start(), d, m.group(0).strip()))
    if not candidates:
        return None
    # "day after tomorrow" also contains "tomorrow": prefer the longest phrase at the earliest position.
    candidates.sort(key=lambda c: (c[0], -len(c[2])))
    _, d, phrase = candidates[0]
    return d, phrase


def _clauses(text_lower: str) -> list[str]:
    return [c.strip() for c in _CLAUSE_SPLIT.split(text_lower) if c.strip()]


def _exam_subject(clause: str) -> str | None:
    m = _EXAM_RE.search(clause)
    if not m:
        return None
    before = re.findall(r"[a-z][a-z0-9+#&\-]*", clause[: m.start()])
    while before and before[-1] in _SUBJECT_STOP:
        before.pop()
    if before and before[-1] not in _NON_SUBJECT_WORDS:
        return subject_label(before[-1])
    after = re.match(r"\s*(?:for|of|in|on)\s+([a-z][a-z0-9+#&\-]*)", clause[m.end():])
    if after and after.group(1) not in _NON_SUBJECT_WORDS and after.group(1) not in _WEEKDAYS:
        return subject_label(after.group(1))
    return None


def parse_goal(text: str, today: date) -> GoalFacts:
    t = text.lower()
    facts = GoalFacts()
    facts.requirements = [Requirement(s, m) for s, m in parse_study_requirements(text)]
    req_subjects = {r.subject for r in facts.requirements}

    for clause in _clauses(t):
        subj = _exam_subject(clause)
        found = find_date(clause, today)
        if subj and found:
            facts.exams.setdefault(subj, found[0])
            facts.exam_phrases.setdefault(subj, found[1])
        elif found and "meeting" in clause:
            facts.meeting_date = found[0]
        elif found and facts.target_date is None:
            facts.target_date, facts.target_date_phrase = found
        # Priorities stated in the same clause as a subject.
        for subject in req_subjects | set(facts.exams):
            if re.search(rf"\b{re.escape(subject.lower())}\b", clause):
                if re.search(r"\b(high priority|top priority|most important|urgent|priority|first)\b", clause) and not re.search(r"\blow priority\b", clause):
                    facts.priorities[subject] = "high"
                elif re.search(r"\b(low priority|optional|if time permits|if i have time)\b", clause):
                    facts.priorities[subject] = "low"
        m = re.search(r"\bprioriti[sz]e\s+([a-z][a-z0-9+#&\-]*)", clause)
        if m:
            facts.priorities[subject_label(m.group(1))] = "high"

    if facts.target_date is None and not facts.exams:
        facts.ambiguous_dates = sorted(set(_AMBIGUOUS_DATE.findall(t)))
    elif facts.exams:
        # Exams without a concrete date stay ambiguous ("DBMS exam next week").
        for clause in _clauses(t):
            if _exam_subject(clause) and not find_date(clause, today):
                facts.ambiguous_dates.extend(_AMBIGUOUS_DATE.findall(clause))

    facts.meeting = parse_meeting(t)
    for r in facts.requirements:
        explicit = explicit_subject_time(t, r.subject)
        if explicit is not None:
            facts.explicit_times[r.subject] = explicit
    facts.mentioned_subjects = [
        subject_label(s) for s in ("dbms", "daa", "os", "cn", "dsa", "math", "ai", "ml") if re.search(rf"\b{s}\b", t)
    ]
    return facts
