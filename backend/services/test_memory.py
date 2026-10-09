from datetime import date, datetime, time, timedelta
import os
import pathlib
import sys
from typing import Any
import unittest

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from main import app
from agent.executor import execute_tool
from agent.orchestrator import AgentOrchestrator
from agent.planner import plan_goal
from agent.router import route_tool
from models.agent import ToolCall, UserGoal
from models.memory import StudentPreferences, StudentPreferencesUpdate
from services.firestore import FirestorePersistence
from services.in_memory import InMemoryPersistence
from services.memory import MemoryService
from services.persistence import (
    DEFAULT_USER_ID,
    get_persistence,
    reset_persistence,
    set_persistence,
)
from services.test_firestore import FakeFirestoreClient
from tools.memory import (
    get_student_preferences,
    reset_student_preferences,
    update_student_preferences,
)
from tools.schedule import check_schedule_conflict, clear_schedule, create_schedule
from tools.tasks import clear_tasks


class TestMemoryAndPreferences(unittest.TestCase):
    def setUp(self):
        set_persistence(InMemoryPersistence(), mode="memory")
        clear_tasks()
        clear_schedule()
        self.service = MemoryService()
        self.service.reset_preferences(confirmation=True)
        self.client = TestClient(app)

    def tearDown(self):
        self.service.reset_preferences(confirmation=True)
        reset_persistence()

    def test_preference_defaults(self):
        """1. Verify default values for student preferences."""
        pref = self.service.get_preferences()
        self.assertEqual(pref.preferred_study_start, "09:00")
        self.assertEqual(pref.preferred_study_end, "21:00")
        self.assertEqual(pref.preferred_session_minutes, 60)
        self.assertEqual(pref.preferred_break_minutes, 10)
        self.assertEqual(len(pref.preferred_study_days), 7)
        self.assertIn("Monday", pref.preferred_study_days)
        self.assertEqual(pref.preferred_subjects, [])
        self.assertEqual(pref.subject_time_preferences, {})
        self.assertEqual(pref.planning_notes, [])

    def test_preference_validation_valid_and_invalid(self):
        """2. Validate valid preferences and reject invalid durations/times/days/secrets."""
        # Valid custom model
        valid_pref = StudentPreferences(
            preferred_study_start="08:00",
            preferred_study_end="22:00",
            preferred_session_minutes=90,
            preferred_break_minutes=15,
            preferred_study_days=["Monday", "Wednesday", "Friday"],
            preferred_subjects=["DBMS", "DAA"],
            subject_time_preferences={"DBMS": "evening"},
            planning_notes=["15-minute break after each session"],
        )
        self.assertEqual(valid_pref.preferred_session_minutes, 90)

        # Invalid start time format
        with self.assertRaises(ValueError):
            StudentPreferences(preferred_study_start="25:00")
        with self.assertRaises(ValueError):
            StudentPreferences(preferred_study_start="9:00")

        # Invalid end time (end before or equal to start)
        with self.assertRaises(ValueError):
            StudentPreferences(preferred_study_start="10:00", preferred_study_end="09:00")
        with self.assertRaises(ValueError):
            StudentPreferences(preferred_study_start="10:00", preferred_study_end="10:00")

        # Invalid session durations
        with self.assertRaises(Exception):
            StudentPreferences(preferred_session_minutes=5)  # < 15
        with self.assertRaises(Exception):
            StudentPreferences(preferred_session_minutes=500)  # > 360

        # Invalid break durations
        with self.assertRaises(Exception):
            StudentPreferences(preferred_break_minutes=-5)
        with self.assertRaises(Exception):
            StudentPreferences(preferred_break_minutes=200)  # > 120

        # Invalid day of week
        with self.assertRaises(ValueError):
            StudentPreferences(preferred_study_days=["Funday"])

        # Rejection of sensitive keywords
        with self.assertRaises(ValueError):
            StudentPreferences(planning_notes=["My password is 12345"])
        with self.assertRaises(ValueError):
            StudentPreferences(planning_notes=["Secret api_key token"])

    def test_partial_updates(self):
        """3. Partial updates modify selected fields without erasing others."""
        self.service.update_preferences({"preferred_break_minutes": 20})
        pref1 = self.service.get_preferences()
        self.assertEqual(pref1.preferred_break_minutes, 20)
        self.assertEqual(pref1.preferred_session_minutes, 60)  # unchanged
        self.assertEqual(pref1.preferred_study_start, "09:00")  # unchanged

        # Update subject timing
        self.service.update_preferences({"subject_time_preferences": {"DBMS": "evening"}})
        pref2 = self.service.get_preferences()
        self.assertEqual(pref2.preferred_break_minutes, 20)
        self.assertEqual(pref2.subject_time_preferences, {"DBMS": "evening"})

    def test_user_isolation(self):
        """4. Verify preferences are isolated by user_id and do not leak."""
        user_a = "student-alice"
        user_b = "student-bob"

        self.service.update_preferences(
            {"preferred_break_minutes": 25, "subject_time_preferences": {"DAA": "morning"}},
            user_id=user_a,
        )

        pref_a = self.service.get_preferences(user_id=user_a)
        pref_b = self.service.get_preferences(user_id=user_b)

        self.assertEqual(pref_a.preferred_break_minutes, 25)
        self.assertEqual(pref_a.subject_time_preferences, {"DAA": "morning"})

        # Bob has default preferences
        self.assertEqual(pref_b.preferred_break_minutes, 10)
        self.assertEqual(pref_b.subject_time_preferences, {})

    def test_memory_summary_accuracy(self):
        """5. Memory summary accurately formats active preferences."""
        self.service.update_preferences(
            {
                "preferred_study_start": "08:30",
                "preferred_study_end": "20:30",
                "preferred_session_minutes": 50,
                "preferred_break_minutes": 10,
                "preferred_subjects": ["DBMS"],
                "subject_time_preferences": {"DBMS": "evening"},
                "planning_notes": ["Prefers quiet morning review"],
            }
        )
        summary = self.service.get_memory_summary()
        self.assertIn("08:30 - 20:30", summary)
        self.assertIn("50 mins", summary)
        self.assertIn("10 mins", summary)
        self.assertIn("DBMS (evening)", summary)
        self.assertIn("Prefers quiet morning review", summary)

    def test_no_invented_preferences(self):
        """6. identify_influencing_preferences only reflects explicit preferences."""
        influences_default = self.service.identify_influencing_preferences(
            "Study for examination tomorrow"
        )
        # Should not claim subject timing that doesn't exist
        for inf in influences_default:
            self.assertNotIn("Scheduled DBMS", inf)

        # Update with specific subject timing
        self.service.update_preferences({"subject_time_preferences": {"DBMS": "evening"}})
        influences_updated = self.service.identify_influencing_preferences(
            "Prepare 2 hours of DBMS tomorrow"
        )
        self.assertTrue(
            any("DBMS during your preferred evening study window" in inf for inf in influences_updated)
        )

    def test_reset_preferences_requires_confirmation(self):
        """7. Reset preferences requires confirmation=True."""
        self.service.update_preferences({"preferred_session_minutes": 90})
        self.assertEqual(self.service.get_preferences().preferred_session_minutes, 90)

        with self.assertRaises(ValueError):
            self.service.reset_preferences(confirmation=False)

        reset_pref = self.service.reset_preferences(confirmation=True)
        self.assertEqual(reset_pref.preferred_session_minutes, 60)
        self.assertEqual(self.service.get_preferences().preferred_session_minutes, 60)

    def test_memory_persistence_in_memory_mode(self):
        """8. InMemoryPersistence supports preference CRUD."""
        persistence = InMemoryPersistence()
        pref = StudentPreferences(preferred_session_minutes=45)
        persistence.update_preferences(pref, user_id="test-user")

        loaded = persistence.get_preferences(user_id="test-user")
        self.assertEqual(loaded.preferred_session_minutes, 45)

        persistence.reset_preferences(user_id="test-user")
        reset_pref = persistence.get_preferences(user_id="test-user")
        self.assertEqual(reset_pref.preferred_session_minutes, 60)

    def test_mocked_firestore_persistence(self):
        """9. Mocked FirestorePersistence stores and retrieves preferences."""
        fake_client = FakeFirestoreClient()
        fs_persistence = FirestorePersistence(client=fake_client, project_id="test-proj")

        pref = StudentPreferences(
            preferred_session_minutes=75,
            preferred_break_minutes=15,
            subject_time_preferences={"OS": "morning"},
        )
        fs_persistence.update_preferences(pref, user_id="demo-user")

        loaded = fs_persistence.get_preferences(user_id="demo-user")
        self.assertEqual(loaded.preferred_session_minutes, 75)
        self.assertEqual(loaded.preferred_break_minutes, 15)
        self.assertEqual(loaded.subject_time_preferences, {"OS": "morning"})

        fs_persistence.reset_preferences(user_id="demo-user")
        reset_loaded = fs_persistence.get_preferences(user_id="demo-user")
        self.assertEqual(reset_loaded.preferred_session_minutes, 60)

    def test_approval_required_for_memory_writes(self):
        """10. Router and Executor enforce approval safety on memory writes."""
        # Read operation: get_student_preferences requires NO approval
        read_call = route_tool("get_student_preferences", {})
        self.assertFalse(read_call.requires_approval)
        read_res = execute_tool(read_call, approved=False)
        self.assertTrue(read_res.success)
        self.assertIn("preferences", read_res.result)

        # Write operation: update_student_preferences requires approval
        write_call = route_tool(
            "update_student_preferences",
            {"preferred_break_minutes": 15},
        )
        self.assertTrue(write_call.requires_approval)

        # Blocked without approval
        blocked_res = execute_tool(write_call, approved=False)
        self.assertFalse(blocked_res.success)
        self.assertIn("Approval required", blocked_res.error)

        # Allowed with explicit approval
        approved_res = execute_tool(write_call, approved=True)
        self.assertTrue(approved_res.success)
        self.assertEqual(
            approved_res.result["preferences"]["preferred_break_minutes"], 15
        )

        # Reset operation also requires approval
        reset_call = route_tool("reset_student_preferences", {"confirmation": True})
        self.assertTrue(reset_call.requires_approval)
        blocked_reset = execute_tool(reset_call, approved=False)
        self.assertFalse(blocked_reset.success)

    def test_planning_integration_with_memory_update_and_recall(self):
        """11. Planner generates approval-gated memory update and utilizes memory later."""
        # Phase 1: User asks to remember a preference
        memory_goal = UserGoal(
            goal="Remember that I prefer studying DBMS in the evening and taking a 10-minute break after each study session."
        )
        plan1 = plan_goal(memory_goal)
        self.assertTrue(plan1.requires_approval)
        self.assertTrue(any(t.tool == "update_student_preferences" for t in plan1.tasks))

        # Orchestrate with approved=False -> waiting approval
        orch = AgentOrchestrator()
        run_res = orch.run(memory_goal.goal, approved=False)
        self.assertEqual(run_res.status, "waiting_approval")
        self.assertTrue(run_res.requires_approval)
        self.assertFalse(run_res.results[0].success)
        self.assertEqual(run_res.results[0].error, "Approval required to execute this tool.")

        # Now execute with approval
        run_approved = orch.run(memory_goal.goal, approved=True)
        self.assertEqual(run_approved.status, "completed")
        self.assertTrue(run_approved.results[0].success)

        # Verify preference is now saved
        saved_pref = self.service.get_preferences()
        self.assertEqual(saved_pref.subject_time_preferences.get("DBMS"), "evening")
        self.assertEqual(saved_pref.preferred_break_minutes, 10)

        # Phase 2: Later planning uses the saved preference
        plan_goal_req = UserGoal(
            goal="Organize my preparation for tomorrow. I need 2 hours of DBMS, 1 hour of DAA, and I have a project meeting at 4 PM."
        )
        plan2 = plan_goal(plan_goal_req)

        # DBMS should be scheduled in the evening slot
        dbms_task = next(t for t in plan2.tasks if "DBMS" in t.title and t.tool == "create_schedule")
        start_time = dbms_task.parameters["start_time"]
        # Meeting is at 4 PM (16:00-17:00). DBMS evening slot should start at or after 17:00
        if isinstance(start_time, str):
            dt = datetime.fromisoformat(start_time)
        else:
            dt = start_time
        self.assertGreaterEqual(dt.hour, 17)
        self.assertIn("evening", plan2.summary.lower())

    def test_missing_info_asks_for_clarification(self):
        """12. General study plan without subjects in goal or memory asks for clarification."""
        goal = UserGoal(goal="Plan my study schedule for tomorrow.")
        plan = plan_goal(goal)
        self.assertIn("clarification", plan.summary.lower())
        self.assertFalse(plan.requires_approval)

    def test_api_memory_endpoints(self):
        """13. Verify FastAPI memory endpoints (/api/agent/memory/*)."""
        # GET /api/agent/memory
        res = self.client.get("/api/agent/memory")
        self.assertEqual(res.status_code, 200)
        self.assertIn("preferences", res.json())
        self.assertIn("summary", res.json())

        # GET /api/agent/memory/summary
        res_sum = self.client.get("/api/agent/memory/summary")
        self.assertEqual(res_sum.status_code, 200)
        self.assertIn("summary", res_sum.json())

        # POST /api/agent/memory/propose
        res_prop = self.client.post(
            "/api/agent/memory/propose",
            json={"updates": {"preferred_break_minutes": 15}},
        )
        self.assertEqual(res_prop.status_code, 200)
        prop_data = res_prop.json()
        self.assertTrue(prop_data["requires_approval"])
        self.assertTrue(prop_data["approval_id"].startswith("appr_"))

        # Approve using standard /api/agent/approve
        appr_res = self.client.post(
            "/api/agent/approve",
            json={"approval_id": prop_data["approval_id"]},
        )
        self.assertEqual(appr_res.status_code, 200)

        # Verify updated
        verify_res = self.client.get("/api/agent/memory")
        self.assertEqual(
            verify_res.json()["preferences"]["preferred_break_minutes"], 15
        )

        # POST /api/agent/memory/reset without confirm -> 400
        res_bad_reset = self.client.post("/api/agent/memory/reset", json={"confirm": False})
        self.assertEqual(res_bad_reset.status_code, 400)

        # POST /api/agent/memory/reset with confirm -> 200
        res_reset = self.client.post("/api/agent/memory/reset", json={"confirm": True})
        self.assertEqual(res_reset.status_code, 200)
        self.assertEqual(
            res_reset.json()["preferences"]["preferred_break_minutes"], 10
        )

    def test_no_eval_or_exec_used(self):
        """14. Confirm no eval() or exec() is used in memory models, service, or tools."""
        files = [
            pathlib.Path(__file__).parent.parent / "models" / "memory.py",
            pathlib.Path(__file__).parent.parent / "services" / "memory.py",
            pathlib.Path(__file__).parent.parent / "tools" / "memory.py",
        ]
        for f in files:
            content = f.read_text()
            self.assertNotIn("eval(", content)
            self.assertNotIn("exec(", content)


if __name__ == "__main__":
    unittest.main()
