import os
import sys
import unittest

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.planner import _detect_intent, plan_goal
from agent.router import validate_parameters, validate_tool_name
from models.agent import AgentPlan, UserGoal
from tools.notes import _notes, clear_notes
from tools.schedule import _events, clear_schedule
from tools.tasks import _tasks, clear_tasks


class TestAgentPlanner(unittest.TestCase):
    def setUp(self):
        clear_tasks()
        clear_schedule()
        clear_notes()

    def tearDown(self):
        clear_tasks()
        clear_schedule()
        clear_notes()

    def test_task_creation_intent_detected(self):
        """1. Task creation intent detected."""
        goal = UserGoal(goal="Create a task to study DBMS")
        self.assertEqual(_detect_intent(goal.goal), "task creation")
        plan = plan_goal(goal)
        self.assertIsInstance(plan, AgentPlan)
        self.assertEqual(len(plan.tasks), 1)
        self.assertEqual(plan.tasks[0].tool, "create_task")
        self.assertEqual(plan.tasks[0].parameters["title"], "study DBMS")

    def test_schedule_creation_intent_detected(self):
        """2. Schedule creation intent detected."""
        goal = UserGoal(goal="Schedule DBMS study tomorrow at 6 PM")
        self.assertEqual(_detect_intent(goal.goal), "schedule creation")
        plan = plan_goal(goal)
        self.assertIsInstance(plan, AgentPlan)
        self.assertEqual(len(plan.tasks), 1)
        self.assertEqual(plan.tasks[0].tool, "create_schedule")
        self.assertEqual(plan.tasks[0].parameters["title"], "DBMS study")
        self.assertIn("start_time", plan.tasks[0].parameters)
        self.assertIn("end_time", plan.tasks[0].parameters)

    def test_note_creation_intent_detected(self):
        """3. Note creation intent detected."""
        goal = UserGoal(goal="Remember that I prefer studying in the evening")
        self.assertEqual(_detect_intent(goal.goal), "note creation")
        plan = plan_goal(goal)
        self.assertIsInstance(plan, AgentPlan)
        self.assertEqual(len(plan.tasks), 1)
        self.assertEqual(plan.tasks[0].tool, "create_note")
        self.assertIn("prefer studying in the evening", plan.tasks[0].parameters["content"])

    def test_task_listing_intent_detected(self):
        """4. Task listing intent detected."""
        goal = UserGoal(goal="Show my tasks")
        self.assertEqual(_detect_intent(goal.goal), "task listing")
        plan = plan_goal(goal)
        self.assertIsInstance(plan, AgentPlan)
        self.assertEqual(len(plan.tasks), 1)
        self.assertEqual(plan.tasks[0].tool, "get_tasks")

    def test_schedule_listing_intent_detected(self):
        """5. Schedule listing intent detected."""
        goal = UserGoal(goal="What is on my schedule tomorrow?")
        self.assertEqual(_detect_intent(goal.goal), "schedule listing")
        plan = plan_goal(goal)
        self.assertIsInstance(plan, AgentPlan)
        self.assertEqual(len(plan.tasks), 1)
        self.assertEqual(plan.tasks[0].tool, "get_schedule")

    def test_note_search_intent_detected(self):
        """6. Note search intent detected."""
        goal = UserGoal(goal="Find my DBMS notes")
        self.assertEqual(_detect_intent(goal.goal), "note search")
        plan = plan_goal(goal)
        self.assertIsInstance(plan, AgentPlan)
        self.assertEqual(len(plan.tasks), 1)
        self.assertEqual(plan.tasks[0].tool, "search_notes")
        self.assertEqual(plan.tasks[0].parameters["query"], "DBMS")

    def test_general_planning_intent_detected(self):
        """7. General planning intent detected."""
        goal = UserGoal(goal="Help me organize my preparation for tomorrow")
        self.assertEqual(_detect_intent(goal.goal), "general planning")
        plan = plan_goal(goal)
        self.assertIsInstance(plan, AgentPlan)
        self.assertGreaterEqual(len(plan.tasks), 2)
        tools = [t.tool for t in plan.tasks]
        self.assertIn("get_schedule", tools)
        self.assertIn("get_tasks", tools)

    def test_empty_goal_rejected(self):
        """8. Empty goal rejected."""
        with self.assertRaises(ValueError):
            plan_goal(UserGoal(goal=""))
        with self.assertRaises(ValueError):
            plan_goal(UserGoal(goal="   "))

    def test_vague_goal_does_not_create_unsafe_tool_calls(self):
        """9. Vague goal does not create unsafe tool calls."""
        goal = UserGoal(goal="Help me study")
        plan = plan_goal(goal)
        self.assertIsInstance(plan, AgentPlan)
        self.assertEqual(len(plan.tasks), 1)
        self.assertIsNone(plan.tasks[0].tool)
        self.assertEqual(plan.tasks[0].parameters, {})
        self.assertIn("Clarify", plan.tasks[0].title)

    def test_planner_never_executes_tools(self):
        """10. Planner never executes tools."""
        self.assertEqual(len(_tasks), 0)
        self.assertEqual(len(_events), 0)
        self.assertEqual(len(_notes), 0)

        plan_goal(UserGoal(goal="Create a task to study DBMS"))
        plan_goal(UserGoal(goal="Schedule DBMS study tomorrow at 6 PM"))
        plan_goal(UserGoal(goal="Remember that I prefer studying in the evening"))
        plan_goal(UserGoal(goal="Show my tasks"))

        # Verify all storage remained completely untouched
        self.assertEqual(len(_tasks), 0)
        self.assertEqual(len(_events), 0)
        self.assertEqual(len(_notes), 0)

    def test_generated_tool_names_are_registered_with_router(self):
        """11. Generated tool names are registered with the router."""
        goals = [
            "Create a task to study DBMS",
            "Schedule DBMS study tomorrow at 6 PM",
            "Remember that I prefer studying in the evening",
            "Show my tasks",
            "What is on my schedule tomorrow?",
            "Find my DBMS notes",
            "Help me organize my preparation for tomorrow",
        ]
        for text in goals:
            plan = plan_goal(UserGoal(goal=text))
            for task in plan.tasks:
                if task.tool is not None:
                    self.assertTrue(validate_tool_name(task.tool))

    def test_generated_plans_are_valid_agent_plan_models(self):
        """12. Generated plans are valid AgentPlan Pydantic models."""
        plan = plan_goal(UserGoal(goal="Show my tasks"))
        self.assertIsInstance(plan, AgentPlan)
        dump = plan.model_dump()
        self.assertIn("goal", dump)
        self.assertIn("summary", dump)
        self.assertIn("tasks", dump)
        self.assertIn("requires_approval", dump)

    def test_tool_calls_contain_valid_parameters(self):
        """13. Tool calls contain valid parameters."""
        goals = [
            "Create a task to study DBMS",
            "Schedule DBMS study tomorrow at 6 PM",
            "Remember that I prefer studying in the evening",
            "Show my tasks",
            "What is on my schedule tomorrow?",
            "Find my DBMS notes",
        ]
        for text in goals:
            plan = plan_goal(UserGoal(goal=text))
            for task in plan.tasks:
                if task.tool is not None:
                    # Validating with router raises if any parameter is unknown or missing
                    validated = validate_parameters(task.tool, task.parameters)
                    self.assertEqual(validated, task.parameters)

    def test_planner_does_not_use_eval_or_exec(self):
        """14. Planner does not use eval or exec."""
        planner_path = os.path.join(os.path.dirname(__file__), "planner.py")
        with open(planner_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("eval(", content)
        self.assertNotIn("exec(", content)


if __name__ == "__main__":
    unittest.main()
