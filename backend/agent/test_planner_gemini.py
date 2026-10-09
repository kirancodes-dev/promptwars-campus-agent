from datetime import datetime
import os
import sys
import unittest
from unittest.mock import MagicMock

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.planner import (
    PlannerError,
    plan_goal,
    plan_goal_smart,
    plan_goal_with_gemini,
)
from models.agent import AgentPlan, UserGoal
from services.gemini import GeminiResponseError, GeminiServiceError
from tools.notes import _notes, clear_notes
from tools.schedule import _events, clear_schedule
from tools.tasks import _tasks, clear_tasks


class TestPlannerGemini(unittest.TestCase):
    def setUp(self):
        clear_tasks()
        clear_schedule()
        clear_notes()

    def tearDown(self):
        clear_tasks()
        clear_schedule()
        clear_notes()

    def test_gemini_produces_valid_task_creation_plan(self):
        """1. Gemini produces a valid task creation plan."""
        mock_gemini = MagicMock()
        mock_gemini.generate_json.return_value = {
            "summary": "Create a task to study DBMS",
            "tasks": [
                {
                    "task_id": "step_1",
                    "description": "Study DBMS for 2 hours",
                    "status": "pending",
                }
            ],
            "tool_calls": [
                {
                    "tool_name": "create_task",
                    "parameters": {
                        "title": "Study DBMS",
                        "description": "Study DBMS for 2 hours",
                    },
                }
            ],
            "needs_clarification": False,
            "clarification_question": None,
        }

        goal = UserGoal(goal="Create a task to study DBMS")
        plan = plan_goal_with_gemini(goal, mock_gemini)

        self.assertIsInstance(plan, AgentPlan)
        self.assertEqual(plan.summary, "Create a task to study DBMS")
        self.assertEqual(len(plan.tasks), 1)
        self.assertEqual(plan.tasks[0].tool, "create_task")
        self.assertEqual(plan.tasks[0].parameters["title"], "Study DBMS")
        self.assertEqual(plan.tasks[0].parameters["description"], "Study DBMS for 2 hours")

    def test_gemini_produces_valid_schedule_creation_plan(self):
        """2. Gemini produces a valid schedule creation plan."""
        mock_gemini = MagicMock()
        mock_gemini.generate_json.return_value = {
            "summary": "Schedule DBMS Study session",
            "tasks": [
                {
                    "task_id": "step_1",
                    "description": "Create calendar block for DBMS study",
                    "status": "pending",
                }
            ],
            "tool_calls": [
                {
                    "tool_name": "create_schedule",
                    "parameters": {
                        "title": "DBMS Study",
                        "start_time": "2026-10-09T18:00:00",
                        "end_time": "2026-10-09T20:00:00",
                    },
                }
            ],
            "needs_clarification": False,
            "clarification_question": None,
        }

        goal = UserGoal(goal="Schedule DBMS Study on Oct 9 from 6 PM to 8 PM")
        plan = plan_goal_with_gemini(goal, mock_gemini)

        self.assertIsInstance(plan, AgentPlan)
        self.assertEqual(len(plan.tasks), 1)
        self.assertEqual(plan.tasks[0].tool, "create_schedule")
        self.assertIsInstance(plan.tasks[0].parameters["start_time"], datetime)
        self.assertIsInstance(plan.tasks[0].parameters["end_time"], datetime)

    def test_gemini_produces_valid_note_creation_plan(self):
        """3. Gemini produces a valid note creation plan."""
        mock_gemini = MagicMock()
        mock_gemini.generate_json.return_value = {
            "summary": "Save preference note",
            "tasks": [
                {
                    "task_id": "step_1",
                    "description": "Save note in preferences",
                    "status": "pending",
                }
            ],
            "tool_calls": [
                {
                    "tool_name": "create_note",
                    "parameters": {
                        "title": "Study preference",
                        "content": "I prefer studying in the evening",
                    },
                }
            ],
            "needs_clarification": False,
            "clarification_question": None,
        }

        goal = UserGoal(goal="Remember that I prefer studying in the evening")
        plan = plan_goal_with_gemini(goal, mock_gemini)

        self.assertIsInstance(plan, AgentPlan)
        self.assertEqual(len(plan.tasks), 1)
        self.assertEqual(plan.tasks[0].tool, "create_note")
        self.assertEqual(plan.tasks[0].parameters["content"], "I prefer studying in the evening")

    def test_gemini_produces_valid_task_listing_plan(self):
        """4. Gemini produces a valid task listing plan."""
        mock_gemini = MagicMock()
        mock_gemini.generate_json.return_value = {
            "summary": "Retrieve existing tasks",
            "tasks": [
                {
                    "task_id": "step_1",
                    "description": "Fetch tasks list",
                    "status": "pending",
                }
            ],
            "tool_calls": [
                {
                    "tool_name": "get_tasks",
                    "parameters": {},
                }
            ],
            "needs_clarification": False,
            "clarification_question": None,
        }

        goal = UserGoal(goal="Show my tasks")
        plan = plan_goal_with_gemini(goal, mock_gemini)

        self.assertIsInstance(plan, AgentPlan)
        self.assertEqual(len(plan.tasks), 1)
        self.assertEqual(plan.tasks[0].tool, "get_tasks")

    def test_gemini_produces_clarification_request(self):
        """5. Gemini produces a clarification request."""
        mock_gemini = MagicMock()
        mock_gemini.generate_json.return_value = {
            "summary": "Request is ambiguous",
            "tasks": [],
            "tool_calls": [],
            "needs_clarification": True,
            "clarification_question": "What subject, date and preferred time should I schedule?",
        }

        goal = UserGoal(goal="Schedule my study")
        plan = plan_goal_with_gemini(goal, mock_gemini)

        self.assertIsInstance(plan, AgentPlan)
        self.assertEqual(len(plan.tasks), 1)
        self.assertIn("What subject", plan.tasks[0].description)

    def test_clarification_request_creates_no_unsafe_tool_calls(self):
        """6. Clarification request creates no unsafe tool calls."""
        mock_gemini = MagicMock()
        mock_gemini.generate_json.return_value = {
            "summary": "Missing details",
            "tasks": [],
            "tool_calls": [],
            "needs_clarification": True,
            "clarification_question": "Could you clarify the timing?",
        }

        goal = UserGoal(goal="Schedule study session")
        plan = plan_goal_with_gemini(goal, mock_gemini)

        # Confirm no tool is attached to any task
        for task in plan.tasks:
            self.assertIsNone(task.tool)
            self.assertEqual(task.parameters, {})

    def test_unknown_gemini_tool_is_rejected(self):
        """7. Unknown Gemini tool is rejected."""
        mock_gemini = MagicMock()
        mock_gemini.generate_json.return_value = {
            "summary": "Invoke unregistered tool",
            "tasks": [{"task_id": "step_1", "description": "Run shell", "status": "pending"}],
            "tool_calls": [
                {
                    "tool_name": "run_shell_command",
                    "parameters": {"command": "echo test"},
                }
            ],
            "needs_clarification": False,
            "clarification_question": None,
        }

        goal = UserGoal(goal="Run system command")
        with self.assertRaises(PlannerError):
            plan_goal_with_gemini(goal, mock_gemini)

    def test_missing_required_tool_parameters_are_rejected(self):
        """8. Missing required tool parameters are rejected."""
        mock_gemini = MagicMock()
        mock_gemini.generate_json.return_value = {
            "summary": "Create task without title",
            "tasks": [{"task_id": "step_1", "description": "Empty task", "status": "pending"}],
            "tool_calls": [
                {
                    "tool_name": "create_task",
                    "parameters": {},  # missing 'title'
                }
            ],
            "needs_clarification": False,
            "clarification_question": None,
        }

        goal = UserGoal(goal="Create a task")
        with self.assertRaises(PlannerError):
            plan_goal_with_gemini(goal, mock_gemini)

    def test_unknown_tool_parameters_are_rejected(self):
        """9. Unknown tool parameters are rejected."""
        mock_gemini = MagicMock()
        mock_gemini.generate_json.return_value = {
            "summary": "Create task with injected parameter",
            "tasks": [{"task_id": "step_1", "description": "Task", "status": "pending"}],
            "tool_calls": [
                {
                    "tool_name": "create_task",
                    "parameters": {
                        "title": "Valid title",
                        "unsupported_key": "injected",
                    },
                }
            ],
            "needs_clarification": False,
            "clarification_question": None,
        }

        goal = UserGoal(goal="Create a task")
        with self.assertRaises(PlannerError):
            plan_goal_with_gemini(goal, mock_gemini)

    def test_malformed_gemini_json_handled_safely(self):
        """10. Malformed Gemini JSON is handled safely."""
        mock_gemini = MagicMock()
        mock_gemini.generate_json.side_effect = GeminiResponseError("Malformed JSON returned")

        goal = UserGoal(goal="Study Math")
        with self.assertRaises(PlannerError):
            plan_goal_with_gemini(goal, mock_gemini)

    def test_gemini_service_errors_become_controlled_planner_error(self):
        """11. Gemini service errors become controlled PlannerError."""
        mock_gemini = MagicMock()
        mock_gemini.generate_json.side_effect = GeminiServiceError("API network failure")

        goal = UserGoal(goal="Study Physics")
        with self.assertRaises(PlannerError):
            plan_goal_with_gemini(goal, mock_gemini)

    def test_gemini_planner_never_executes_tools(self):
        """12. Gemini planner never executes tools."""
        self.assertEqual(len(_tasks), 0)
        self.assertEqual(len(_events), 0)
        self.assertEqual(len(_notes), 0)

        mock_gemini = MagicMock()
        mock_gemini.generate_json.return_value = {
            "summary": "Create task",
            "tasks": [{"task_id": "t1", "description": "Task", "status": "pending"}],
            "tool_calls": [{"tool_name": "create_task", "parameters": {"title": "Math Task"}}],
            "needs_clarification": False,
            "clarification_question": None,
        }

        goal = UserGoal(goal="Create task")
        plan_goal_with_gemini(goal, mock_gemini)

        # Storage must remain untouched
        self.assertEqual(len(_tasks), 0)
        self.assertEqual(len(_events), 0)
        self.assertEqual(len(_notes), 0)

    def test_all_generated_plans_are_valid_agent_plan_models(self):
        """13. All generated plans are valid AgentPlan models."""
        mock_gemini = MagicMock()
        mock_gemini.generate_json.return_value = {
            "summary": "Search notes",
            "tasks": [{"task_id": "s1", "description": "Search DBMS", "status": "pending"}],
            "tool_calls": [{"tool_name": "search_notes", "parameters": {"query": "DBMS"}}],
            "needs_clarification": False,
            "clarification_question": None,
        }

        goal = UserGoal(goal="Find DBMS notes")
        plan = plan_goal_with_gemini(goal, mock_gemini)
        self.assertIsInstance(plan, AgentPlan)
        dump = plan.model_dump()
        self.assertIn("goal", dump)
        self.assertIn("summary", dump)
        self.assertIn("tasks", dump)
        self.assertIn("requires_approval", dump)

    def test_plan_goal_smart_uses_deterministic_fallback_when_gemini_service_is_none(self):
        """14. plan_goal_smart uses deterministic fallback when Gemini service is None."""
        goal = UserGoal(goal="Show my tasks")
        plan = plan_goal_smart(goal, gemini_service=None)

        self.assertIsInstance(plan, AgentPlan)
        self.assertEqual(plan.tasks[0].tool, "get_tasks")

    def test_deterministic_plan_goal_still_passes_all_existing_tests(self):
        """15. Deterministic plan_goal() still passes all existing tests."""
        goal = UserGoal(goal="Create a task to study DBMS")
        plan = plan_goal(goal)
        self.assertEqual(plan.tasks[0].tool, "create_task")
        self.assertEqual(plan.tasks[0].parameters["title"], "study DBMS")

    def test_no_eval_used(self):
        """16. No eval() is used."""
        planner_path = os.path.join(os.path.dirname(__file__), "planner.py")
        with open(planner_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("eval(", content)

    def test_no_exec_used(self):
        """17. No exec() is used."""
        planner_path = os.path.join(os.path.dirname(__file__), "planner.py")
        with open(planner_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("exec(", content)


if __name__ == "__main__":
    unittest.main()
