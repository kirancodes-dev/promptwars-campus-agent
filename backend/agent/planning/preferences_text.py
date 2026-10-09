"""Extract explicitly stated study preferences from a sentence. Never invents preferences."""

import re
from typing import Any


def extract_preference_updates(text: str) -> dict[str, Any]:
    """
    Extract explicitly stated student preferences from natural language.
    Avoids inventing preferences that were not stated.
    """
    updates: dict[str, Any] = {}
    text_lower = text.lower()

    # 1. Break minutes: e.g. "10-minute break", "15 minute break", "break of 10 minutes"
    break_match = re.search(
        r"(\d+)\s*(?:-|–|\s)?\s*min(?:ute)?s?\s+break|break\s+(?:of\s+)?(\d+)\s*min",
        text_lower,
    )
    if break_match:
        mins = int(break_match.group(1) or break_match.group(2))
        if 0 <= mins <= 120:
            updates["preferred_break_minutes"] = mins

    # 2. Session minutes: e.g. "45-minute session", "session of 60 minutes", "1 hour session"
    session_match = re.search(
        r"(\d+)\s*(?:-|–|\s)?\s*min(?:ute)?s?\s+(?:study\s+|focus\s+)?session",
        text_lower,
    )
    if session_match:
        mins = int(session_match.group(1))
        if 15 <= mins <= 360:
            updates["preferred_session_minutes"] = mins
    elif "1 hour session" in text_lower or "1-hour session" in text_lower:
        updates["preferred_session_minutes"] = 60
    elif "2 hour session" in text_lower or "2-hour session" in text_lower:
        updates["preferred_session_minutes"] = 120

    # 3. Subject time preferences: e.g. "studying DBMS in the evening", "DAA in the morning", "prefer OS at night"
    subject_candidates = ["dbms", "daa", "os", "cn", "math", "dsa", "ai", "ml"]
    time_windows = ["morning", "afternoon", "evening", "night"]
    subj_time: dict[str, str] = {}
    for subj in subject_candidates:
        for tw in time_windows:
            pattern = rf"\b{subj}\b.*?\b(?:in the|during the|at)?\s*{tw}\b|\b{tw}\b.*?\b{subj}\b"
            if re.search(pattern, text_lower):
                subj_time[subj.upper()] = tw
    if subj_time:
        updates["subject_time_preferences"] = subj_time
        updates["preferred_subjects"] = list(subj_time.keys())

    # 4. Study hours window: e.g. "between 08:00 and 20:00", "from 9 am to 9 pm"
    hours_match = re.search(
        r"(?:between|from)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+(?:and|to)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
        text_lower,
    )
    if hours_match:
        def _parse_hhmm(s: str) -> str | None:
            s = s.strip()
            m24 = re.match(r"^(\d{1,2}):(\d{2})$", s)
            if m24:
                return f"{int(m24.group(1)):02d}:{m24.group(2)}"
            m12 = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$", s)
            if m12:
                hr = int(m12.group(1))
                mn = m12.group(2) or "00"
                ampm = m12.group(3)
                if ampm == "pm" and hr < 12:
                    hr += 12
                elif ampm == "am" and hr == 12:
                    hr = 0
                return f"{hr:02d}:{mn}"
            return None

        st = _parse_hhmm(hours_match.group(1))
        et = _parse_hhmm(hours_match.group(2))
        if st and et:
            updates["preferred_study_start"] = st
            updates["preferred_study_end"] = et

    # 4b. Evening / morning study session preferences (e.g. "prefer evening study sessions")
    if "preferred_study_start" not in updates:
        if (
            "evening study" in text_lower
            or "evening session" in text_lower
            or re.search(r"prefer\s+evening", text_lower)
        ):
            updates["preferred_study_start"] = "17:00"
            updates["preferred_study_end"] = "22:00"
        elif (
            "morning study" in text_lower
            or "morning session" in text_lower
            or re.search(r"prefer\s+morning", text_lower)
        ):
            updates["preferred_study_start"] = "08:00"
            updates["preferred_study_end"] = "12:00"

    # 5. Planning notes: clean extracted note
    clean_note = text.strip()

    # If chained request like "Remember that I prefer evening study sessions, then plan my preparation for tomorrow."
    # Strip the chained instruction from the note
    for split_token in [
        ", then plan",
        " then plan",
        ", then prepare",
        " then prepare",
        ", and plan",
        " and plan",
        ", and prepare",
        " and prepare",
    ]:
        if split_token in clean_note.lower():
            idx = clean_note.lower().find(split_token)
            clean_note = clean_note[:idx].strip()
            break

    for prefix in [
        "remember that ",
        "please remember that ",
        "remember: ",
        "note that ",
        "preference: ",
    ]:
        if clean_note.lower().startswith(prefix):
            clean_note = clean_note[len(prefix):].strip()
            break
    if clean_note:
        updates["planning_notes"] = [clean_note]

    return updates
