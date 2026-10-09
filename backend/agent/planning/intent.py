"""
Deterministic intent recognition.

Rules are checked in order; the first match wins. Each rule is a small predicate so the
ordering (which matters, e.g. "remember … then plan" before "remember that") is explicit.
"""

import re
from typing import Callable

VAGUE_GOALS = {
    "help me study",
    "help me",
    "study",
    "prepare",
    "help me prepare",
    "i want to study",
    "assist me",
    "help",
}

_STUDY_VERBS = (
    "organize", "organise", "preparation", "prepare", "study plan", "plan my study",
    "revise", "revision", "study for"
)
_NUM_WORD = r"(?:\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|half\s*(?:an?|a)|an?)"
_DURATION = re.compile(r"\b" + _NUM_WORD + r"\s*(?:hours?|hrs?|minutes?|mins?)\b", re.IGNORECASE)
_EXAM_WORDS = re.compile(r"\b(?:exam|exams|test|quiz|midterm|mid-term|finals?|viva)\b")
_KNOWN_SUBJECTS = re.compile(r"\b(?:dbms|daa|os|cn|dsa|ml|ai|math|maths|physics|chemistry)\b")


def _has(text: str, *phrases: str) -> bool:
    return any(p in text for p in phrases)


def _is_chained_preference(t: str) -> bool:
    return _has(t, "remember", "prefer", "preference") and (
        _has(t, "then plan", "then prepare", "and plan", "and prepare")
        or ("tomorrow" in t and _has(t, "plan", "prepare", "preparation"))
    )


def _is_review_and_revise(t: str) -> bool:
    return _has(t, "review", "check", "inspect") and "schedule" in t and _has(t, "free time", "available", "revision", "sessions")


def _is_smart_study(t: str) -> bool:
    """A study-planning request with something concrete to plan: durations, exams, a meeting or subjects."""
    if t.startswith(("create a task", "create task", "add a task", "add task", "new task", "remind me to")):
        return False
    if t.startswith("schedule ") and not _has(t, "study schedule", "schedule my study", "schedule revision", "study sessions"):
        return False
    concrete = bool(
        _DURATION.search(t)
        or _EXAM_WORDS.search(t)
        or "meeting" in t
        or _KNOWN_SUBJECTS.search(t)
        or _has(t, "revision session", "revision sessions", "study session", "study sessions", "two subjects", "subjects")
    )
    asks_for_plan = (
        _has(t, *_STUDY_VERBS)
        or bool(re.search(r"\bplan\b.*\b(?:study|revision|prep|session|block|schedule|exam|two|hours?|hrs?)", t))
        or bool(re.search(r"\b(?:study|revision|prep)\b.*\bplan\b", t))
        or ("need" in t and bool(_DURATION.search(t)))
        or (bool(_EXAM_WORDS.search(t)) and any(w in t for w in ("prioritize", "earliest", "prepare", "study", "plan")))
        or _has(t, "revision session", "revision sessions", "study session", "study sessions")
    )
    return asks_for_plan and concrete


def _is_task_and_schedule(t: str) -> bool:
    return bool(_has(t, "task", "to-do") and _has(t, "schedule", "study block", "session") and _has(t, "and", "then"))


def _is_explain_assumptions(t: str) -> bool:
    return bool(_has(t, "explain", "what are", "show", "describe", "list") and _has(t, "assumption", "assumptions"))


def _is_note_search(t: str) -> bool:
    return _has(t, "notes", "note") and t.startswith(("find my", "find", "search for", "search", "look for", "look up"))


def _is_preference_update(t: str) -> bool:
    return (
        _has(t, "preference", "preferences", "preferred_")
        or (_has(t, "prefer", "preferred") and _has(t, "break", "minute", "minutes", "session", "window", "take a", "taking a"))
        or (_has(t, "remember that", "remember:", "note that") and _has(t, "break", "session", "study window"))
    )


_RULES: list[tuple[str, Callable[[str], bool]]] = [
    ("chained preference and study plan", _is_chained_preference),
    ("review and plan revision", _is_review_and_revise),
    ("task and schedule creation", _is_task_and_schedule),
    ("explain assumptions", _is_explain_assumptions),
    ("preference reset", lambda t: _has(t, "reset my preferences", "reset preferences", "clear my preferences",
                                        "clear preferences", "reset memory")),
    ("preference update", _is_preference_update),
    ("preference listing", lambda t: _has(t, "show my preferences", "show preferences", "get my preferences", "view preferences",
                                          "list preferences", "what are my preferences", "my study preferences", "show memory",
                                          "view memory", "get memory")),
    ("task listing", lambda t: _has(t, "show my tasks", "list my tasks", "get my tasks", "view my tasks", "show tasks",
                                    "list tasks", "get tasks", "what are my tasks", "all tasks")),
    ("schedule listing", lambda t: _has(t, "what is on my schedule", "show my schedule", "view my schedule", "list my schedule",
                                        "get my schedule", "check my schedule", "show schedule", "list schedule", "view schedule",
                                        "my schedule tomorrow")),
    ("note search", _is_note_search),
    ("smart study planning", _is_smart_study),
    ("study schedule planning", lambda t: _has(t, "plan my study schedule", "plan study schedule", "study schedule for tomorrow",
                                               "plan my study for tomorrow", "schedule my study for tomorrow", "plan my study",
                                               "create a schedule that respects")),
    ("note creation", lambda t: _has(t, "remember that", "remember:", "take a note", "create a note", "add a note",
                                     "make a note", "save note", "note that")),
    ("schedule creation", lambda t: t.startswith("schedule ") or _has(t, "schedule a ", "schedule an ")),
    ("task creation", lambda t: _has(t, "create a task", "create task", "add a task", "add task", "new task", "remind me to", "task to")),
]


def detect_intent(text: str) -> str:
    """Return the intent name for a goal. Defaults to 'general planning'."""
    t = text.lower().strip()
    if t in VAGUE_GOALS:
        return "vague"
    for name, matches in _RULES:
        if matches(t):
            return name
    return "general planning"
