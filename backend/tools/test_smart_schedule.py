import os
import sys
import unittest
from datetime import date, datetime, time, timedelta

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.orchestrator import AgentOrchestrator
from agent.planner import plan_goal
from models.agent import AgentPlan, ScheduleEvent, UserGoal
from tools.notes import clear_notes
from tools.schedule import (
    _events,
    check_schedule_conflict,
    clear_schedule,
    create_schedule,
    find_available_slots,
    propose_study_blocks,
)
from tools.tasks import clear_tasks


class TestSmartSchedule(unittest.TestCase):
    def setUp(self):
        clear_tasks()
        clear_schedule()
        clear_notes()

    def tearDown(self):
        clear_tasks()
        clear_schedule()
        clear_notes()

    def test_1_exact_conflict_detected(self):
        """1. Exact conflict detected: 4:00 PM - 5:00 PM vs 4:00 PM - 5:00 PM."""
        target_day = datetime(2026, 10, 9)
        e1_start = datetime.combine(target_day.date(), time(16, 0))
        e1_end = datetime.combine(target_day.date(), time(17, 0))
        create_schedule(title="Existing Event", start_time=e1_start, end_time=e1_end)

        result = check_schedule_conflict(start_time=e1_start, end_time=e1_end)
        self.assertTrue(result["has_conflict"])
        self.assertEqual(result["conflict_count"], 1)

    def test_2_partial_conflict_detected(self):
        """2. Partial conflict detected: 4:00 PM - 5:00 PM vs 4:30 PM - 5:30 PM."""
        target_day = datetime(2026, 10, 9)
        e1_start = datetime.combine(target_day.date(), time(16, 0))
        e1_end = datetime.combine(target_day.date(), time(17, 0))
        create_schedule(title="Existing Event", start_time=e1_start, end_time=e1_end)

        new_start = datetime.combine(target_day.date(), time(16, 30))
        new_end = datetime.combine(target_day.date(), time(17, 30))
        result = check_schedule_conflict(start_time=new_start, end_time=new_end)
        self.assertTrue(result["has_conflict"])
        self.assertEqual(result["conflict_count"], 1)

    def test_3_containing_conflict_detected(self):
        """3. Containing conflict detected: Existing 4:30 PM - 5:00 PM, New 4:00 PM - 6:00 PM."""
        target_day = datetime(2026, 10, 9)
        e1_start = datetime.combine(target_day.date(), time(16, 30))
        e1_end = datetime.combine(target_day.date(), time(17, 0))
        create_schedule(title="Short Meeting", start_time=e1_start, end_time=e1_end)

        new_start = datetime.combine(target_day.date(), time(16, 0))
        new_end = datetime.combine(target_day.date(), time(18, 0))
        result = check_schedule_conflict(start_time=new_start, end_time=new_end)
        self.assertTrue(result["has_conflict"])
        self.assertEqual(result["conflict_count"], 1)

    def test_4_contained_conflict_detected(self):
        """4. Contained conflict detected: Existing 4:00 PM - 6:00 PM, New 4:30 PM - 5:00 PM."""
        target_day = datetime(2026, 10, 9)
        e1_start = datetime.combine(target_day.date(), time(16, 0))
        e1_end = datetime.combine(target_day.date(), time(18, 0))
        create_schedule(title="Long Session", start_time=e1_start, end_time=e1_end)

        new_start = datetime.combine(target_day.date(), time(16, 30))
        new_end = datetime.combine(target_day.date(), time(17, 0))
        result = check_schedule_conflict(start_time=new_start, end_time=new_end)
        self.assertTrue(result["has_conflict"])
        self.assertEqual(result["conflict_count"], 1)

    def test_5_adjacent_events_do_not_conflict(self):
        """5. Adjacent events do not conflict: 4:00 PM - 5:00 PM vs 5:00 PM - 6:00 PM."""
        target_day = datetime(2026, 10, 9)
        e1_start = datetime.combine(target_day.date(), time(16, 0))
        e1_end = datetime.combine(target_day.date(), time(17, 0))
        create_schedule(title="Existing Event", start_time=e1_start, end_time=e1_end)

        # Right-adjacent
        new_start = datetime.combine(target_day.date(), time(17, 0))
        new_end = datetime.combine(target_day.date(), time(18, 0))
        result_right = check_schedule_conflict(start_time=new_start, end_time=new_end)
        self.assertFalse(result_right["has_conflict"])
        self.assertEqual(result_right["conflict_count"], 0)

        # Left-adjacent
        prev_start = datetime.combine(target_day.date(), time(15, 0))
        prev_end = datetime.combine(target_day.date(), time(16, 0))
        result_left = check_schedule_conflict(start_time=prev_start, end_time=prev_end)
        self.assertFalse(result_left["has_conflict"])
        self.assertEqual(result_left["conflict_count"], 0)

    def test_6_available_slot_detection_works(self):
        """6. Available slot detection works: empty schedule returns window slots."""
        target_day = date(2026, 10, 9)
        slots = find_available_slots(
            date=target_day,
            duration_minutes=60,
            preferred_start=time(9, 0),
            preferred_end=time(12, 0),
        )
        self.assertGreater(len(slots), 0)
        self.assertEqual(slots[0]["start_time"], datetime.combine(target_day, time(9, 0)))
        self.assertEqual(slots[0]["duration_minutes"], 60)

    def test_7_multiple_existing_events_handled(self):
        """7. Multiple existing events handled: correctly finds gaps between events."""
        target_day = date(2026, 10, 9)
        # Event 1: 10:00 - 11:00
        create_schedule(
            title="Lab",
            start_time=datetime.combine(target_day, time(10, 0)),
            end_time=datetime.combine(target_day, time(11, 0)),
        )
        # Event 2: 13:00 - 14:00
        create_schedule(
            title="Lunch",
            start_time=datetime.combine(target_day, time(13, 0)),
            end_time=datetime.combine(target_day, time(14, 0)),
        )

        # Find 60-min slots between 9:00 and 15:00
        slots = find_available_slots(
            date=target_day,
            duration_minutes=60,
            preferred_start=time(9, 0),
            preferred_end=time(15, 0),
        )
        # Expect slots at 09:00, 11:00, 14:00
        slot_starts = [s["start_time"] for s in slots]
        self.assertIn(datetime.combine(target_day, time(9, 0)), slot_starts)
        self.assertIn(datetime.combine(target_day, time(11, 0)), slot_starts)
        self.assertIn(datetime.combine(target_day, time(14, 0)), slot_starts)

    def test_8_two_hour_slot_found_correctly(self):
        """8. Two-hour slot found correctly: Existing 4-5 PM and 7-8 PM, finds 5-7 PM."""
        target_day = date(2026, 10, 9)
        create_schedule(
            title="Project Meeting",
            start_time=datetime.combine(target_day, time(16, 0)),
            end_time=datetime.combine(target_day, time(17, 0)),
        )
        create_schedule(
            title="Dinner",
            start_time=datetime.combine(target_day, time(19, 0)),
            end_time=datetime.combine(target_day, time(20, 0)),
        )

        slots = find_available_slots(
            date=target_day,
            duration_minutes=120,
            preferred_start=time(16, 0),
            preferred_end=time(20, 0),
        )
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0]["start_time"], datetime.combine(target_day, time(17, 0)))
        self.assertEqual(slots[0]["end_time"], datetime.combine(target_day, time(19, 0)))

    def test_9_no_suitable_slot_handled_safely(self):
        """9. No suitable slot handled safely: clarification returned, no auto-execution."""
        tomorrow = datetime.now().date() + timedelta(days=1)
        # Completely fill tomorrow with 1-hour events from 09:00 to 21:00 separated by 30 mins
        # e.g., 09:00-10:00, 10:30-11:30, 12:00-13:00, etc., so no continuous 120-min slot exists
        cur_h = 9
        cur_m = 0
        while cur_h < 21:
            st = datetime.combine(tomorrow, time(cur_h, cur_m))
            et = st + timedelta(minutes=75)
            if et.hour >= 21 and et.minute > 0:
                break
            create_schedule(title="Busy Block", start_time=st, end_time=et)
            next_start = et + timedelta(minutes=15)
            cur_h = next_start.hour
            cur_m = next_start.minute

        goal = UserGoal(
            goal="Organize my preparation for tomorrow. I need 2 hours of DBMS, 1 hour of DAA, and I have a project meeting at 4 PM."
        )
        plan = plan_goal(goal)
        self.assertIsInstance(plan, AgentPlan)
        # Should detect that no 2-hour continuous slot is available and produce clarification
        self.assertIn("No 2-hour slot is available tomorrow", plan.summary)
        self.assertFalse(plan.requires_approval)
        self.assertIsNone(plan.tasks[0].tool)

    def test_10_study_block_proposal_generated(self):
        """10. Study block proposal generated: converts requirements to proposals."""
        target_day = date(2026, 10, 9)
        requirements = [("DBMS", 120), ("DAA", 60)]
        proposals = propose_study_blocks(requirements, target_date=target_day)

        self.assertEqual(len(proposals), 2)
        self.assertEqual(proposals[0].title, "DBMS Study")
        self.assertEqual(proposals[1].title, "DAA Study")
        self.assertTrue(proposals[0].requires_approval)
        self.assertTrue(proposals[1].requires_approval)

    def test_11_study_proposal_does_not_modify_storage(self):
        """11. Study proposal does not immediately modify storage."""
        self.assertEqual(len(_events), 0)
        target_day = date(2026, 10, 9)
        propose_study_blocks([("DBMS", 120), ("DAA", 60)], target_date=target_day)
        # In-memory storage must remain completely untouched
        self.assertEqual(len(_events), 0)

    def test_12_multi_step_plan_preserves_correct_order(self):
        """12. Multi-step plan preserves correct 8-step order."""
        goal = UserGoal(
            goal="Organize my preparation for tomorrow. I need 2 hours of DBMS, 1 hour of DAA, and I have a project meeting at 4 PM."
        )
        plan = plan_goal(goal)

        expected_titles = [
            "Understand study requirements",
            "Check existing schedule",
            "Check schedule conflicts",
            "Find available study slots",
            "Create DBMS study block",
            "Create DAA study block",
            "Create corresponding tasks",
            "Report completed schedule",
        ]
        actual_titles = [task.title for task in plan.tasks]
        self.assertEqual(actual_titles, expected_titles)

    def test_13_read_operations_occur_before_write_operations(self):
        """13. Read operations occur before write operations."""
        goal = UserGoal(
            goal="Organize my preparation for tomorrow. I need 2 hours of DBMS, 1 hour of DAA, and I have a project meeting at 4 PM."
        )
        plan = plan_goal(goal)

        # Step 2: get_schedule (read)
        # Step 3: check_schedule_conflict (read)
        # Step 5: create_schedule (write)
        # Step 6: create_schedule (write)
        # Step 7: create_task (write)
        read_indices = [i for i, t in enumerate(plan.tasks) if t.tool in ("get_schedule", "check_schedule_conflict")]
        write_indices = [i for i, t in enumerate(plan.tasks) if t.tool in ("create_schedule", "create_task")]

        self.assertTrue(len(read_indices) > 0)
        self.assertTrue(len(write_indices) > 0)
        self.assertLess(max(read_indices), min(write_indices))

    def test_14_write_operations_require_approval(self):
        """14. Write operations require approval."""
        goal = UserGoal(
            goal="Organize my preparation for tomorrow. I need 2 hours of DBMS, 1 hour of DAA, and I have a project meeting at 4 PM."
        )
        plan = plan_goal(goal)

        self.assertTrue(plan.requires_approval)
        write_tasks = [t for t in plan.tasks if t.tool in ("create_schedule", "create_task")]
        for task in write_tasks:
            self.assertTrue(task.requires_approval)

    def test_15_no_existing_event_is_overwritten_automatically(self):
        """15. No existing event is overwritten automatically when run without approval."""
        tomorrow = datetime.now().date() + timedelta(days=1)
        meeting_start = datetime.combine(tomorrow, time(16, 0))
        meeting_end = datetime.combine(tomorrow, time(17, 0))
        existing_event = create_schedule(
            title="Important Project Meeting",
            start_time=meeting_start,
            end_time=meeting_end,
        )
        original_event_id = existing_event.id
        original_count = len(_events)

        orchestrator = AgentOrchestrator()
        goal = UserGoal(
            goal="Organize my preparation for tomorrow. I need 2 hours of DBMS, 1 hour of DAA, and I have a project meeting at 4 PM."
        )
        res = orchestrator.run(goal, approved=False)

        # Status must be waiting_approval
        self.assertEqual(res.status, "waiting_approval")
        self.assertTrue(res.requires_approval)

        # Existing event is completely untouched and not overwritten
        self.assertEqual(len(_events), original_count)
        self.assertIn(original_event_id, _events)
        self.assertEqual(_events[original_event_id].title, "Important Project Meeting")
        self.assertEqual(_events[original_event_id].start_time, meeting_start)
        self.assertEqual(_events[original_event_id].end_time, meeting_end)

    def test_16_no_eval_used(self):
        """16. No eval() is used in schedule or planner modules."""
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        for path in [
            os.path.join(backend_dir, "tools", "schedule.py"),
            os.path.join(backend_dir, "agent", "planner.py"),
        ]:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertNotIn("eval(", content, f"eval() found in {path}")

    def test_17_no_exec_used(self):
        """17. No exec() is used in schedule or planner modules."""
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        for path in [
            os.path.join(backend_dir, "tools", "schedule.py"),
            os.path.join(backend_dir, "agent", "planner.py"),
        ]:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertNotIn("exec(", content, f"exec() found in {path}")


if __name__ == "__main__":
    unittest.main()
