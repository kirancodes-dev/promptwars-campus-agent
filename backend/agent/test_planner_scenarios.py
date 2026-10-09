"""
Planner evaluation scenarios: realistic student goals, checked for correct structure, honest
clarifications, no invented facts, preference use, and safe behaviour on failures.
All scenarios use a fixed clock (Wednesday 7 Oct 2026, 10:00) so dates are deterministic.
"""

from datetime import date, datetime, time, timedelta
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.orchestrator import AgentOrchestrator
from agent.planner import plan_goal
from agent.planning.extraction import find_date, parse_goal
from agent.planning.scheduling import split_sessions
from agent.planning.study import build_study_plan
from models.agent import UserGoal
from services.in_memory import InMemoryPersistence
from services.memory import MemoryService
from services.persistence import reset_persistence, set_persistence
from tools.schedule import create_schedule, delete_schedule

NOW = datetime(2026, 10, 7, 10, 0)  # a Wednesday
TODAY = NOW.date()


def plan(text, **kw):
    return build_study_plan(UserGoal(goal=text), now=NOW, **kw)


def blocks(p):
    return [t for t in p.tasks if t.tool == "create_schedule"]


def writes(p):
    return [t for t in p.tasks if t.tool and t.tool.startswith(("create", "update", "delete", "reset"))]


def facts(p):
    return {(f.label, f.value, f.source) for f in p.understanding}


def source_of(p, label):
    return next((f.source for f in p.understanding if f.label == label), None)


class ScenarioBase(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryPersistence()
        set_persistence(self.store, mode="memory")

    def tearDown(self):
        reset_persistence()

    def assertNoOverlaps(self, p):
        spans = sorted((t.parameters["start_time"], t.parameters["end_time"]) for t in blocks(p))
        for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
            self.assertLessEqual(e1, s2, f"overlap {s1}-{e1} / {s2}-{e2}")

    def assertClarification(self, p, *phrases):
        self.assertFalse(p.requires_approval)
        self.assertEqual(writes(p), [])
        for phrase in phrases:
            self.assertIn(phrase.lower(), p.summary.lower())


class TestDateUnderstanding(unittest.TestCase):
    def test_date_phrases(self):
        cases = {
            "tomorrow": date(2026, 10, 8),
            "day after tomorrow": date(2026, 10, 9),
            "today": TODAY,
            "in 3 days": date(2026, 10, 10),
            "on friday": date(2026, 10, 9),
            "on wednesday": date(2026, 10, 14),  # strictly after today
            "15 oct": date(2026, 10, 15),
            "oct 20th": date(2026, 10, 20),
            "2026-11-02": date(2026, 11, 2),
        }
        for phrase, expected in cases.items():
            self.assertEqual(find_date(f"my exam is {phrase}", TODAY)[0], expected, phrase)
        self.assertIsNone(find_date("sometime next week", TODAY))

    def test_goal_facts(self):
        f = parse_goal("I have a DBMS exam on Friday and a DAA exam on 12 Oct. I need 4 hours of DBMS and 3 hours of DAA. DBMS is high priority.", TODAY)
        self.assertEqual(f.exams, {"DBMS": date(2026, 10, 9), "DAA": date(2026, 10, 12)})
        self.assertEqual([(r.subject, r.minutes) for r in f.requirements], [("DBMS", 240), ("DAA", 180)])
        self.assertEqual(f.priorities, {"DBMS": "high"})
        self.assertIsNone(f.meeting)

    def test_session_splitting(self):
        self.assertEqual(split_sessions(240, 60), [60, 60, 60, 60])
        self.assertEqual(split_sessions(150, 60), [60, 60, 30])
        self.assertEqual(split_sessions(130, 60), [60, 70])  # a 10-minute remainder joins the last session
        self.assertEqual(split_sessions(45, 60), [45])


class TestPlanningScenarios(ScenarioBase):
    def test_multiple_exams_earliest_deadline_first(self):
        p = plan("I have a DBMS exam on Friday and a DAA exam on Monday. I need 4 hours of DBMS and 3 hours of DAA.")
        self.assertTrue(p.requires_approval)
        b = blocks(p)
        dbms = [t for t in b if t.parameters["title"].startswith("DBMS")]
        daa = [t for t in b if t.parameters["title"].startswith("DAA")]
        self.assertEqual(sum((t.parameters["end_time"] - t.parameters["start_time"]).seconds // 60 for t in dbms), 240)
        self.assertEqual(sum((t.parameters["end_time"] - t.parameters["start_time"]).seconds // 60 for t in daa), 180)
        self.assertTrue(all(t.parameters["start_time"].date() < date(2026, 10, 9) for t in dbms))
        self.assertTrue(all(t.parameters["start_time"].date() < date(2026, 10, 12) for t in daa))
        self.assertLess(b.index(dbms[0]), b.index(daa[0]), "earliest exam is planned first")
        self.assertGreater(len({t.parameters["start_time"].date() for t in daa}), 1, "DAA is spread over several days")
        self.assertNoOverlaps(p)
        self.assertIn(("DBMS exam", "Fri 9 Oct", "you said"), facts(p))
        tasks = [t for t in p.tasks if t.tool == "create_task"]
        self.assertEqual([t.parameters["title"] for t in tasks], ["Prepare for DBMS exam (Fri 9 Oct)", "Prepare for DAA exam (Mon 12 Oct)"])
        self.assertEqual(tasks[0].parameters["priority"], "high")  # exam within 3 days

    def test_fixed_meeting_is_kept_free(self):
        p = plan("Organize my preparation for tomorrow. I need 2 hours of DBMS, 1 hour of DAA, and I have a project meeting at 4 PM.")
        meeting = (datetime(2026, 10, 8, 16, 0), datetime(2026, 10, 8, 17, 0))
        for t in blocks(p):
            s, e = t.parameters["start_time"], t.parameters["end_time"]
            self.assertFalse(s < meeting[1] and e > meeting[0])
        self.assertIn("Your meeting length wasn't given, so I kept 1 hour free for it.", p.assumptions)
        self.assertEqual(source_of(p, "Meeting"), "you said")

    def test_priorities_change_the_order(self):
        p = plan("Plan tomorrow: 1 hour of OS and 2 hours of DBMS. DBMS is high priority.")
        first = min(blocks(p), key=lambda t: t.parameters["start_time"])
        self.assertTrue(first.parameters["title"].startswith("DBMS"))
        self.assertIn(("DBMS priority", "high", "you said"), facts(p))
        self.assertIn("Higher-priority subjects were placed first", p.summary)

    def test_impossible_single_day_explains_capacity(self):
        p = plan("Prepare for tomorrow: 8 hours of DBMS and 6 hours of DAA")
        self.assertClarification(p, "No 6-hour slot is available tomorrow for DAA", "is free that day")

    def test_impossible_before_exam_explains_capacity(self):
        p = plan("I have a DBMS exam on Thursday. I need 12 hours of DBMS.")
        self.assertClarification(p, "DBMS needs 12 hours before its exam on Thu 8 Oct", "is free in your study window")

    def test_conflicting_deadlines_same_day(self):
        p = plan("DBMS exam tomorrow and DAA exam tomorrow. I need 6 hours of DBMS and 6 hours of DAA.")
        self.assertClarification(p, "needs 6 hours before its exam on Thu 8 Oct")

    def test_exam_in_the_past(self):
        p = plan("My DBMS exam was on 1 Oct, I need 3 hours of DBMS")
        self.assertClarification(p, "already past")

    def test_ambiguous_dates_are_not_guessed(self):
        for goal in ("Plan 2 hours of DBMS next week", "I have a DBMS exam next week, I need 4 hours of DBMS"):
            p = plan(goal)
            self.assertClarification(p, "isn't specific enough")

    def test_exam_without_study_time_is_not_invented(self):
        p = plan("I have a DBMS exam on Friday, help me prepare")
        self.assertClarification(p, "How many hours do you want to study for DBMS", "won't guess")

    def test_nothing_is_invented(self):
        p = plan("Organize my preparation for tomorrow. I need 2 hours of DBMS")
        self.assertNotIn("meeting", p.summary.lower())
        self.assertIsNone(source_of(p, "Meeting"))
        self.assertEqual([t.parameters["title"] for t in blocks(p)], ["DBMS Study Block"])
        self.assertEqual(source_of(p, "Planning day"), "you said")
        self.assertEqual(source_of(p, "Study window"), "default")

    def test_default_day_is_stated_as_assumption(self):
        p = plan("Prepare: 2 hours of DBMS")
        self.assertEqual(source_of(p, "Planning day"), "default")
        self.assertIn("No day was given, so I planned for tomorrow.", p.assumptions)

    def test_saved_preferences_are_respected_and_labelled(self):
        MemoryService().update_preferences({
            "preferred_study_start": "18:00", "preferred_study_end": "23:00", "preferred_session_minutes": 90,
            "preferred_break_minutes": 15, "subject_time_preferences": {"DBMS": "evening"},
        })
        p = plan("I have a DBMS exam on Saturday. I need 4 hours of DBMS.")
        b = sorted(blocks(p), key=lambda t: t.parameters["start_time"])
        self.assertTrue(b)
        for t in b:
            s, e = t.parameters["start_time"], t.parameters["end_time"]
            self.assertGreaterEqual(s.time(), time(18, 0))
            self.assertLessEqual(e.time(), time(23, 0))
            self.assertLessEqual((e - s).seconds // 60, 90 + 14)
        for x, y in zip(b, b[1:]):
            if x.parameters["start_time"].date() == y.parameters["start_time"].date():
                self.assertGreaterEqual(y.parameters["start_time"] - x.parameters["end_time"], timedelta(minutes=15))
        self.assertEqual(source_of(p, "Study window"), "saved preference")
        self.assertEqual(source_of(p, "Session length"), "saved preference")
        self.assertEqual(source_of(p, "DBMS time of day"), "saved preference")

    def test_explicit_time_overrides_saved_preference(self):
        MemoryService().update_preferences({"subject_time_preferences": {"DBMS": "evening"}})
        p = plan("Plan tomorrow: 2 hours of DBMS. DBMS at 9 AM.")
        self.assertEqual(blocks(p)[0].parameters["start_time"].hour, 9)
        self.assertIn("overriding a saved timing preference", p.summary)


class TestReplanningAndFailures(ScenarioBase):
    GOAL = "Organize my preparation for tomorrow. I need 2 hours of DBMS, 1 hour of DAA."

    def test_replanning_avoids_saved_blocks_and_reuses_freed_time(self):
        orch = AgentOrchestrator()
        first = orch.run(UserGoal(goal=self.GOAL), approved=True)
        self.assertEqual(first.status, "completed")
        saved = self.store.get_events()
        again = plan_goal(UserGoal(goal=self.GOAL))
        for t in blocks(again):
            for e in saved:
                self.assertFalse(t.parameters["start_time"] < e.end_time and t.parameters["end_time"] > e.start_time)
        # The student deletes the DBMS block; the next plan can use that time again.
        dbms = next(e for e in saved if e.title.startswith("DBMS"))
        delete_schedule(dbms.id)
        replanned = plan_goal(UserGoal(goal="Prepare for tomorrow: 2 hours of DBMS"))
        self.assertEqual(blocks(replanned)[0].parameters["start_time"], dbms.start_time)

    def test_storage_unavailable_while_planning_is_disclosed_and_blocks_writes(self):
        broken = MagicMock(wraps=self.store)
        broken.get_events.side_effect = RuntimeError("Firestore unavailable")
        broken.get_events_overlapping.side_effect = RuntimeError("Firestore unavailable")
        set_persistence(broken, mode="firestore")
        p = plan_goal(UserGoal(goal=self.GOAL))
        self.assertTrue(any("couldn't read your saved schedule" in a for a in p.assumptions))
        res = AgentOrchestrator(planner_func=lambda g: p).run(UserGoal(goal=self.GOAL), approved=True)
        self.assertEqual(self.store.get_events(), [])  # nothing saved
        self.assertIn("create_schedule", res.unresolved_actions)

    def test_existing_events_block_time(self):
        tomorrow = TODAY + timedelta(days=1)
        create_schedule("Lab", datetime.combine(tomorrow, time(9)), datetime.combine(tomorrow, time(13)))
        p = plan("Prepare for tomorrow: 2 hours of DBMS")
        self.assertGreaterEqual(blocks(p)[0].parameters["start_time"], datetime.combine(tomorrow, time(13)))

    def test_malformed_or_meaningless_goals_never_produce_writes(self):
        for goal in ("asdfgh qwerty", "2 hours of", "???", "help me", "Plan my study schedule for tomorrow."):
            p = plan_goal(UserGoal(goal=goal))
            self.assertEqual(writes(p), [], goal)

    def test_today_plans_never_start_in_the_past(self):
        p = plan("Plan today: 1 hour of DBMS")
        self.assertGreaterEqual(blocks(p)[0].parameters["start_time"], NOW)


if __name__ == "__main__":
    unittest.main()
