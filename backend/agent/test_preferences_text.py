"""Preference extraction from a sentence: only what the student actually said is extracted."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.planning.preferences_text import extract_preference_updates as extract


class TestPreferenceExtraction(unittest.TestCase):
    def test_breaks_and_sessions(self):
        self.assertEqual(extract("I like a 15-minute break")["preferred_break_minutes"], 15)
        self.assertEqual(extract("take a break of 20 min")["preferred_break_minutes"], 20)
        self.assertEqual(extract("45 minute study session please")["preferred_session_minutes"], 45)
        self.assertEqual(extract("I prefer a 2-hour session")["preferred_session_minutes"], 120)
        self.assertNotIn("preferred_break_minutes", extract("a 500 minute break"))  # out of range is ignored

    def test_study_window(self):
        u = extract("I study between 8 am and 6 pm")
        self.assertEqual((u["preferred_study_start"], u["preferred_study_end"]), ("08:00", "18:00"))
        u = extract("from 09:30 to 21:00 works for me")
        self.assertEqual((u["preferred_study_start"], u["preferred_study_end"]), ("09:30", "21:00"))
        u = extract("I prefer evening study sessions")
        self.assertEqual((u["preferred_study_start"], u["preferred_study_end"]), ("17:00", "22:00"))
        u = extract("I prefer morning sessions")
        self.assertEqual((u["preferred_study_start"], u["preferred_study_end"]), ("08:00", "12:00"))

    def test_subject_timing_and_notes(self):
        u = extract("Remember that I prefer studying DBMS in the evening, then plan my preparation for tomorrow.")
        self.assertEqual(u["subject_time_preferences"], {"DBMS": "evening"})
        self.assertEqual(u["preferred_subjects"], ["DBMS"])
        self.assertEqual(u["planning_notes"], ["I prefer studying DBMS in the evening"])

    def test_nothing_invented(self):
        u = extract("Remember that I like quiet places")
        self.assertEqual(set(u), {"planning_notes"})
        self.assertEqual(u["planning_notes"], ["I like quiet places"])


if __name__ == "__main__":
    unittest.main()
