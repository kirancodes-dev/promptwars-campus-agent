"""
AI Planning Quality Gate: deterministic evaluation set verifying planning quality,
duration constraints, time window constraints, structural validity, approval gating,
persistence isolation, and accurate planner reporting.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.orchestrator import AgentOrchestrator
from agent.workflow import validate_plan_dependencies
from models.agent import UserGoal
from services.approvals import approval_store
from services.in_memory import InMemoryPersistence
from services.persistence import reset_persistence, set_persistence


class TestPlanningQualityGate(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryPersistence()
        set_persistence(self.store, mode="memory")
        approval_store.clear()
        self.orchestrator = AgentOrchestrator()

    def tearDown(self):
        reset_persistence()
        approval_store.clear()

    def test_case_1_two_hours_dbms_tomorrow_evening(self):
        """1. 'Plan two hours of DBMS study tomorrow evening.'"""
        goal = "Plan two hours of DBMS study tomorrow evening."
        res = self.orchestrator.run(UserGoal(goal=goal), approved=False)

        # 1. Output reflects requested intent
        self.assertEqual(res.status, "waiting_approval")
        self.assertEqual(res.planner_mode, "deterministic")

        # 2. Required study blocks are present
        study_blocks = [t for t in res.plan.tasks if t.tool == "create_schedule"]
        self.assertTrue(len(study_blocks) >= 1)

        # 3. Durations and time constraints are respected
        b = study_blocks[0]
        self.assertIn("DBMS", b.parameters["title"])
        start = b.parameters["start_time"]
        end = b.parameters["end_time"]
        duration_minutes = (end - start).total_seconds() / 60
        self.assertEqual(duration_minutes, 120)  # 2 hours
        self.assertGreaterEqual(start.hour, 17)  # evening (>= 5 PM)

        # 4. Plan is structurally valid
        valid, err = validate_plan_dependencies(res.plan)
        self.assertTrue(valid, err)

        # 5. Proposed changes require approval
        self.assertTrue(b.requires_approval)
        self.assertTrue(res.requires_approval)

        # 6. Nothing is saved before approval
        self.assertEqual(len(self.store.get_events()), 0)
        self.assertEqual(len(self.store.get_tasks()), 0)

        # 7. Approval persists the expected records
        appr_res = self.orchestrator.run(UserGoal(goal=goal), approved=True)
        self.assertEqual(appr_res.status, "completed")
        self.assertEqual(len(self.store.get_events()), 1)
        persisted = self.store.get_events()[0]
        self.assertIn("DBMS", persisted.title)

        # 8. Result accurately identifies which planner generated it
        self.assertEqual(res.planner_mode, "deterministic")

    def test_case_2_three_exams_prioritize_earliest(self):
        """2. 'I have three exams next week. Prioritize the earliest exam.'"""
        # A vague date ("next week") without exam subject dates correctly triggers clarification
        goal_ambiguous = "I have three exams next week. Prioritize the earliest exam."
        res_ambiguous = self.orchestrator.plan(UserGoal(goal=goal_ambiguous))
        self.assertFalse(res_ambiguous.requires_approval)
        self.assertIn("clarification", res_ambiguous.tasks[0].title.lower())

        # When concrete exam dates and study needs are provided, earliest exam is prioritized
        goal_concrete = (
            "I have 3 exams next week: DBMS on Monday, DAA on Wednesday, and OS on Friday. "
            "I need 2 hours of DBMS, 2 hours of DAA, and 2 hours of OS. Prioritize the earliest exam."
        )
        res = self.orchestrator.run(UserGoal(goal=goal_concrete), approved=False)
        self.assertEqual(res.status, "waiting_approval")
        self.assertEqual(res.planner_mode, "deterministic")

        # Plan is structurally valid
        valid, err = validate_plan_dependencies(res.plan)
        self.assertTrue(valid, err)

        # Study blocks present and earliest exam (DBMS on Monday) appears first in schedule
        sched_tasks = [t for t in res.plan.tasks if t.tool == "create_schedule"]
        self.assertTrue(len(sched_tasks) >= 3)
        self.assertIn("DBMS", sched_tasks[0].parameters["title"])

        # Nothing saved before approval
        self.assertEqual(len(self.store.get_events()), 0)

    def test_case_3_create_task_and_schedule_study_block(self):
        """3. 'Create a task and schedule a study block from 6 PM to 8 PM.'"""
        goal = "Create a task and schedule a study block from 6 PM to 8 PM."
        res = self.orchestrator.run(UserGoal(goal=goal), approved=False)

        self.assertEqual(res.status, "waiting_approval")
        self.assertTrue(res.requires_approval)

        # Verify task and schedule creation are both present
        task_creation = next((t for t in res.plan.tasks if t.tool == "create_task"), None)
        sched_creation = next((t for t in res.plan.tasks if t.tool == "create_schedule"), None)
        self.assertIsNotNone(task_creation)
        self.assertIsNotNone(sched_creation)

        # Verify 6 PM to 8 PM constraint (18:00 to 20:00)
        start = sched_creation.parameters["start_time"]
        end = sched_creation.parameters["end_time"]
        self.assertEqual(start.hour, 18)
        self.assertEqual(end.hour, 20)
        self.assertEqual((end - start).total_seconds() / 3600, 2.0)

        # Nothing saved before approval
        self.assertEqual(len(self.store.get_tasks()), 0)
        self.assertEqual(len(self.store.get_events()), 0)

        # Approval persists both task and schedule event
        appr_res = self.orchestrator.run(UserGoal(goal=goal), approved=True)
        self.assertEqual(appr_res.status, "completed")
        self.assertEqual(len(self.store.get_tasks()), 1)
        self.assertEqual(len(self.store.get_events()), 1)

    def test_case_4_revision_sessions_for_two_subjects(self):
        """4. 'Plan revision sessions for two subjects, with breaks.'"""
        goal_unspecified = "Plan revision sessions for two subjects, with breaks."
        res = self.orchestrator.plan(UserGoal(goal=goal_unspecified))
        # Clarifies which subjects or plans safely
        self.assertTrue(res.summary)

        goal_specified = "Plan revision sessions for DBMS and DAA tomorrow, with breaks. 1 hour each."
        res2 = self.orchestrator.run(UserGoal(goal=goal_specified), approved=False)
        self.assertEqual(res2.status, "waiting_approval")
        scheds = [t for t in res2.plan.tasks if t.tool == "create_schedule"]
        self.assertEqual(len(scheds), 2)
        # Verify break gap between sessions
        first_end = scheds[0].parameters["end_time"]
        second_start = scheds[1].parameters["start_time"]
        self.assertGreaterEqual(second_start, first_end)

    def test_case_5_schedule_respects_available_hours(self):
        """5. 'Create a schedule that respects my available hours.'"""
        goal = "Plan 2 hours of DBMS study tomorrow that respects my available hours."
        res = self.orchestrator.run(UserGoal(goal=goal), approved=False)
        self.assertEqual(res.status, "waiting_approval")
        block = next(t for t in res.plan.tasks if t.tool == "create_schedule")
        start = block.parameters["start_time"]
        end = block.parameters["end_time"]
        # Default student available hours: 09:00 to 21:00
        self.assertGreaterEqual(start.hour, 9)
        self.assertLessEqual(end.hour, 21)

    def test_case_6_explain_planning_assumptions(self):
        """6. 'Explain the assumptions used to create my study plan.'"""
        goal = "Explain the assumptions used to create my study plan."
        plan = self.orchestrator.plan(UserGoal(goal=goal))
        self.assertFalse(plan.requires_approval)
        self.assertTrue(len(plan.assumptions) >= 3)
        self.assertTrue(any("study window" in a.lower() for a in plan.assumptions))
        self.assertTrue(any("session length" in a.lower() for a in plan.assumptions))


if __name__ == "__main__":
    unittest.main()
