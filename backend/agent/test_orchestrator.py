import unittest
from unittest.mock import MagicMock

from agent.orchestrator import AgentOrchestrator
from models.agent import (
    AgentExecutionResult,
    AgentPlan,
    AgentTask,
    ToolResult,
    UserGoal,
)
from tools.notes import _notes
from tools.schedule import _events
from tools.tasks import _tasks, create_task


class TestAgentOrchestrator(unittest.TestCase):
    def setUp(self):
        _tasks.clear()
        _events.clear()
        _notes.clear()

    def test_read_only_plan_executes_successfully(self):
        """1. Read-only plan executes successfully without approval."""
        orchestrator = AgentOrchestrator()
        goal = UserGoal(goal="Show my tasks")
        result = orchestrator.run(goal)

        self.assertIsInstance(result, AgentExecutionResult)
        self.assertEqual(result.status, "completed")
        self.assertFalse(result.requires_approval)
        self.assertIsNone(result.clarification_question)
        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.results[0].tool_name, "get_tasks")
        self.assertTrue(result.results[0].success)

    def test_write_plan_waits_for_approval(self):
        """2. Write plan waits for approval when approved=False."""
        task = AgentTask(
            id="task_1",
            title="Delete a task",
            tool="delete_task",
            parameters={"task_id": "non_existent_id"},
            requires_approval=True,
        )
        plan = AgentPlan(
            goal="Delete old task",
            summary="Delete task safely",
            tasks=[task],
            requires_approval=True,
        )

        orchestrator = AgentOrchestrator(planner_func=lambda g: plan)
        result = orchestrator.run(UserGoal(goal="Delete old task"), approved=False)

        self.assertEqual(result.status, "waiting_approval")
        self.assertTrue(result.requires_approval)
        self.assertEqual(len(result.results), 1)
        self.assertFalse(result.results[0].success)
        self.assertEqual(result.results[0].result, {"requires_approval": True})
        self.assertEqual(result.results[0].error, "Approval required to execute this tool.")

    def test_approved_write_plan_executes_successfully(self):
        """3. Approved write plan executes successfully when approved=True."""
        created = create_task(title="Task to delete")
        task_id = created.id

        task = AgentTask(
            id="task_delete",
            title="Delete task",
            tool="delete_task",
            parameters={"task_id": task_id},
            requires_approval=True,
        )
        plan = AgentPlan(
            goal="Delete created task",
            summary="Plan to delete task",
            tasks=[task],
            requires_approval=True,
        )

        orchestrator = AgentOrchestrator(planner_func=lambda g: plan)
        result = orchestrator.run(UserGoal(goal="Delete created task"), approved=True)

        self.assertEqual(result.status, "completed")
        self.assertTrue(result.requires_approval)
        self.assertEqual(len(result.results), 1)
        self.assertTrue(result.results[0].success)
        self.assertEqual(result.results[0].result, {"success": True, "task_id": task_id})
        self.assertNotIn(task_id, _tasks)

    def test_clarification_plan_does_not_execute(self):
        """4. Clarification plan does not execute any tools."""
        orchestrator = AgentOrchestrator()
        goal = UserGoal(goal="Help me study")
        result = orchestrator.run(goal)

        self.assertEqual(result.status, "needs_clarification")
        self.assertFalse(result.requires_approval)
        self.assertEqual(result.results, [])
        self.assertIsNotNone(result.clarification_question)
        self.assertIn("Clarify", result.clarification_question)

    def test_empty_or_invalid_goal_rejected_safely(self):
        """5. Empty/invalid goal is rejected safely."""
        orchestrator = AgentOrchestrator()
        with self.assertRaises(ValueError):
            orchestrator.run(UserGoal(goal=""))
        with self.assertRaises(ValueError):
            orchestrator.run(UserGoal(goal="   "))
        with self.assertRaises(ValueError):
            orchestrator.plan(UserGoal(goal=""))

    def test_multiple_tool_calls_execute_in_plan_order(self):
        """6. Multiple tool calls execute in exact plan order."""
        t1 = AgentTask(
            id="t1",
            title="Get tasks",
            tool="get_tasks",
            parameters={},
            requires_approval=False,
        )
        t2 = AgentTask(
            id="t2",
            title="Get schedule",
            tool="get_schedule",
            parameters={},
            requires_approval=False,
        )
        t3 = AgentTask(
            id="t3",
            title="Get notes",
            tool="get_notes",
            parameters={},
            requires_approval=False,
        )
        plan = AgentPlan(
            goal="Fetch all campus items",
            summary="Check tasks, schedule, and notes",
            tasks=[t1, t2, t3],
            requires_approval=False,
        )

        orchestrator = AgentOrchestrator(planner_func=lambda g: plan)
        result = orchestrator.run(UserGoal(goal="Fetch all campus items"))

        self.assertEqual(result.status, "completed")
        self.assertEqual(len(result.results), 3)
        self.assertEqual(
            [r.tool_name for r in result.results],
            ["get_tasks", "get_schedule", "get_notes"],
        )
        self.assertTrue(all(r.success for r in result.results))

    def test_one_failed_tool_produces_failed_tool_result(self):
        """7. One failed tool produces a failed ToolResult."""
        task = AgentTask(
            id="t_fail",
            title="Delete non existent task",
            tool="delete_task",
            parameters={"task_id": "non_existent_id"},
            requires_approval=True,
        )
        plan = AgentPlan(
            goal="Fail deletion",
            summary="Attempt delete",
            tasks=[task],
            requires_approval=True,
        )

        orchestrator = AgentOrchestrator(planner_func=lambda g: plan)
        result = orchestrator.run(UserGoal(goal="Fail deletion"), approved=True)

        self.assertEqual(result.status, "failed")
        self.assertEqual(len(result.results), 1)
        self.assertFalse(result.results[0].success)
        self.assertIsNotNone(result.results[0].error)

    def test_previous_successful_results_preserved_after_later_failure(self):
        """8. Previous successful results are preserved after a later failure."""
        t1 = AgentTask(
            id="t1",
            title="Get tasks",
            tool="get_tasks",
            parameters={},
            requires_approval=False,
        )
        t2 = AgentTask(
            id="t2",
            title="Delete non existent task",
            tool="delete_task",
            parameters={"task_id": "non_existent_id"},
            requires_approval=True,
        )
        t3 = AgentTask(
            id="t3",
            title="Get notes",
            tool="get_notes",
            parameters={},
            requires_approval=False,
        )
        plan = AgentPlan(
            goal="Mixed operations",
            summary="Run valid then invalid then valid",
            tasks=[t1, t2, t3],
            requires_approval=True,
        )

        orchestrator = AgentOrchestrator(planner_func=lambda g: plan)
        result = orchestrator.run(UserGoal(goal="Mixed operations"), approved=True)

        self.assertEqual(result.status, "failed")
        self.assertEqual(len(result.results), 3)
        self.assertTrue(result.results[0].success)
        self.assertEqual(result.results[0].tool_name, "get_tasks")
        self.assertFalse(result.results[1].success)
        self.assertEqual(result.results[1].tool_name, "delete_task")
        self.assertTrue(result.results[2].success)
        self.assertEqual(result.results[2].tool_name, "get_notes")

    def test_unknown_tools_cannot_execute(self):
        """9. Unknown tools cannot execute."""
        task = AgentTask(
            id="t_unknown",
            title="Run unknown tool",
            tool="unknown_nonexistent_tool",
            parameters={},
            requires_approval=False,
        )
        plan = AgentPlan(
            goal="Unknown tool test",
            summary="Attempt unknown tool",
            tasks=[task],
            requires_approval=False,
        )

        orchestrator = AgentOrchestrator()
        results = orchestrator.execute_plan(plan, approved=True)

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].success)
        self.assertIn("not registered", results[0].error.lower())

    def test_router_validation_remains_enforced(self):
        """10. Router validation remains enforced (missing required parameter)."""
        task = AgentTask(
            id="t_bad_params",
            title="Create task missing title",
            tool="create_task",
            parameters={"priority": "high"},  # missing required 'title'
            requires_approval=False,
        )
        plan = AgentPlan(
            goal="Invalid params test",
            summary="Attempt invalid params",
            tasks=[task],
            requires_approval=False,
        )

        orchestrator = AgentOrchestrator()
        results = orchestrator.execute_plan(plan, approved=True)

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].success)
        self.assertIn("missing required parameter", results[0].error.lower())

    def test_executor_remains_the_only_execution_path(self):
        """11. Executor remains the only execution path."""
        spy_calls = []

        def custom_executor(tool_call, approved=False):
            spy_calls.append((tool_call.tool_name, approved))
            return ToolResult(
                tool_name=tool_call.tool_name,
                success=True,
                result={"custom": True},
            )

        t1 = AgentTask(
            id="t1",
            title="Fetch tasks",
            tool="get_tasks",
            parameters={},
            requires_approval=False,
        )
        plan = AgentPlan(
            goal="Custom executor test",
            summary="Route through custom executor",
            tasks=[t1],
            requires_approval=False,
        )

        orchestrator = AgentOrchestrator(
            planner_func=lambda g: plan,
            executor_func=custom_executor,
        )
        result = orchestrator.run(UserGoal(goal="Custom executor test"))

        self.assertEqual(len(spy_calls), 1)
        self.assertEqual(spy_calls[0], ("get_tasks", False))
        self.assertEqual(result.results[0].result, {"custom": True})

    def test_orchestrator_never_automatically_approves_tools(self):
        """12. Orchestrator never automatically approves tools."""
        passed_approvals = []

        def spy_executor(tool_call, approved=False):
            passed_approvals.append(approved)
            return ToolResult(
                tool_name=tool_call.tool_name,
                success=False,
                result={"requires_approval": True},
                error="Approval required to execute this tool.",
            )

        task = AgentTask(
            id="t_appr",
            title="Delete task",
            tool="delete_task",
            parameters={"task_id": "123"},
            requires_approval=True,
        )
        plan = AgentPlan(
            goal="Approval test",
            summary="Plan requiring approval",
            tasks=[task],
            requires_approval=True,
        )

        orchestrator = AgentOrchestrator(
            planner_func=lambda g: plan,
            executor_func=spy_executor,
        )
        orchestrator.run(UserGoal(goal="Approval test"), approved=False)

        self.assertTrue(len(passed_approvals) > 0)
        self.assertNotIn(True, passed_approvals)
        self.assertTrue(all(a is False for a in passed_approvals))

    def test_gemini_planner_can_be_injected(self):
        """13. Gemini planner can be injected into the orchestrator."""
        mock_gemini = MagicMock()
        mock_gemini.build_planning_prompt.return_value = "prompt"
        mock_gemini.generate_json.return_value = {
            "summary": "Injected Gemini plan",
            "tasks": [
                {
                    "task_id": "step_1",
                    "description": "Show tasks",
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

        orchestrator = AgentOrchestrator(gemini_service=mock_gemini)
        plan = orchestrator.plan(UserGoal(goal="Show my tasks"))

        self.assertEqual(plan.summary, "Injected Gemini plan")
        self.assertEqual(len(plan.tasks), 1)
        self.assertEqual(plan.tasks[0].tool, "get_tasks")
        mock_gemini.generate_json.assert_called_once()

    def test_deterministic_planner_works_when_gemini_unavailable(self):
        """14. Deterministic planner works when Gemini is unavailable (gemini_service=None)."""
        orchestrator = AgentOrchestrator(gemini_service=None)
        plan = orchestrator.plan(UserGoal(goal="Show my tasks"))

        self.assertIsInstance(plan, AgentPlan)
        self.assertEqual(len(plan.tasks), 1)
        self.assertEqual(plan.tasks[0].tool, "get_tasks")

    def test_returned_object_is_valid_agent_execution_result(self):
        """15. Returned object is a valid AgentExecutionResult model."""
        orchestrator = AgentOrchestrator()
        result = orchestrator.run(UserGoal(goal="Show my tasks"))

        self.assertIsInstance(result, AgentExecutionResult)
        dump = result.model_dump()
        self.assertIn("goal", dump)
        self.assertIn("plan", dump)
        self.assertIn("results", dump)
        self.assertIn("status", dump)
        self.assertIn("requires_approval", dump)
        self.assertIn("clarification_question", dump)
        self.assertEqual(result.goal, "Show my tasks")
        self.assertEqual(result.status, "completed")

    def test_no_eval_used(self):
        """16. No eval() is used in backend/agent/orchestrator.py."""
        import pathlib
        path = pathlib.Path(__file__).parent / "orchestrator.py"
        content = path.read_text()
        self.assertNotIn("eval(", content)

    def test_no_exec_used(self):
        """17. No exec() is used in backend/agent/orchestrator.py."""
        import pathlib
        path = pathlib.Path(__file__).parent / "orchestrator.py"
        content = path.read_text()
        self.assertNotIn("exec(", content)


if __name__ == "__main__":
    unittest.main()
