import os
import sys
import unittest

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.executor import (
    approve_and_execute,
    approve_request,
    create_approval_request,
    execute_tool,
    reject_approval,
)
from models.agent import ApprovalRequest, ToolCall, ToolResult
from tools.notes import clear_notes
from tools.schedule import clear_schedule
from tools.tasks import clear_tasks, create_task, get_tasks


class TestToolExecutor(unittest.TestCase):
    def setUp(self):
        clear_tasks()
        clear_schedule()
        clear_notes()

    def tearDown(self):
        clear_tasks()
        clear_schedule()
        clear_notes()

    def test_non_approval_create_task_executes_successfully(self):
        """1. Non-approval create_task executes successfully."""
        tool_call = ToolCall(
            tool_name="create_task",
            parameters={"title": "Submit assignment"},
            requires_approval=False,
        )
        result = execute_tool(tool_call, approved=False)
        self.assertTrue(result.success)
        self.assertIsNone(result.error)
        self.assertEqual(result.tool_name, "create_task")
        self.assertEqual(result.result["title"], "Submit assignment")
        self.assertEqual(len(get_tasks()), 1)

    def test_non_approval_get_tasks_executes_successfully(self):
        """2. Non-approval get_tasks executes successfully."""
        create_task("Existing task 1")
        tool_call = ToolCall(
            tool_name="get_tasks",
            parameters={},
            requires_approval=False,
        )
        result = execute_tool(tool_call, approved=False)
        self.assertTrue(result.success)
        self.assertIsNone(result.error)
        self.assertEqual(len(result.result["tasks"]), 1)

    def test_approval_required_create_task_does_not_execute_without_approval(self):
        """3. Approval-required create_task does not execute without approval."""
        tool_call = ToolCall(
            tool_name="create_task",
            parameters={"title": "Drop course", "requires_approval": True},
            requires_approval=True,
        )
        result = execute_tool(tool_call, approved=False)
        self.assertFalse(result.success)
        self.assertIn("Approval required", result.error)
        self.assertEqual(len(get_tasks()), 0)

    def test_approval_required_create_task_executes_with_approval(self):
        """4. Approval-required create_task executes with approval."""
        tool_call = ToolCall(
            tool_name="create_task",
            parameters={"title": "Drop course", "requires_approval": True},
            requires_approval=True,
        )
        result = execute_tool(tool_call, approved=True)
        self.assertTrue(result.success)
        self.assertIsNone(result.error)
        self.assertEqual(len(get_tasks()), 1)

    def test_approval_request_created_correctly(self):
        """5. Approval request is created correctly."""
        tool_call = ToolCall(
            tool_name="delete_task",
            parameters={"task_id": "123"},
            requires_approval=True,
        )
        req = create_approval_request(tool_call)
        self.assertIsInstance(req, ApprovalRequest)
        self.assertTrue(req.approval_id.startswith("appr_"))
        self.assertEqual(req.tool_name, "delete_task")
        self.assertEqual(req.parameters, {"task_id": "123"})
        self.assertEqual(req.status, "pending")

    def test_approval_request_can_be_approved(self):
        """6. Approval request can be approved."""
        task = create_task("Task to delete")
        tool_call = ToolCall(
            tool_name="delete_task",
            parameters={"task_id": task.id},
            requires_approval=True,
        )
        req = create_approval_request(tool_call)
        approved_req = approve_request(req)
        self.assertEqual(approved_req.status, "approved")

        result = approve_and_execute(approved_req)
        self.assertTrue(result.success)
        self.assertEqual(len(get_tasks()), 0)

    def test_approval_request_can_be_rejected(self):
        """7. Approval request can be rejected."""
        tool_call = ToolCall(
            tool_name="delete_task",
            parameters={"task_id": "any_id"},
            requires_approval=True,
        )
        req = create_approval_request(tool_call)
        rejected_req = reject_approval(req)
        self.assertEqual(rejected_req.status, "rejected")

    def test_rejected_approval_never_executes_tool(self):
        """8. Rejected approval never executes the tool."""
        task = create_task("Keep this task")
        tool_call = ToolCall(
            tool_name="delete_task",
            parameters={"task_id": task.id},
            requires_approval=True,
        )
        req = create_approval_request(tool_call)
        rejected_req = reject_approval(req)

        result = approve_and_execute(rejected_req)
        self.assertFalse(result.success)
        self.assertIn("rejected", result.error)
        self.assertEqual(len(get_tasks()), 1)

    def test_unknown_tool_rejected(self):
        """9. Unknown tool is rejected."""
        tool_call = ToolCall(
            tool_name="unknown_tool",
            parameters={},
            requires_approval=False,
        )
        result = execute_tool(tool_call)
        self.assertFalse(result.success)
        self.assertIn("unknown_tool", result.error)

    def test_invalid_parameters_rejected(self):
        """10. Invalid parameters are rejected."""
        tool_call = ToolCall(
            tool_name="create_task",
            parameters={"wrong_parameter": "value"},
            requires_approval=False,
        )
        result = execute_tool(tool_call)
        self.assertFalse(result.success)
        self.assertIn("missing", result.error.lower())

    def test_tool_exceptions_become_failed_tool_results(self):
        """11. Tool exceptions become failed ToolResult objects."""
        tool_call = ToolCall(
            tool_name="update_task",
            parameters={"task_id": "nonexistent_task_id", "title": "New Title"},
            requires_approval=False,
        )
        result = execute_tool(tool_call)
        self.assertIsInstance(result, ToolResult)
        self.assertFalse(result.success)
        self.assertIn("not found", result.error.lower())

    def test_no_eval_or_exec_used(self):
        """12. No eval or exec is used."""
        executor_path = os.path.join(os.path.dirname(__file__), "executor.py")
        router_path = os.path.join(os.path.dirname(__file__), "router.py")

        for file_path in (executor_path, router_path):
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertNotIn("eval(", content)
            self.assertNotIn("exec(", content)

    def test_tool_result_objects_follow_pydantic_model(self):
        """13. All ToolResult objects follow the existing Pydantic model."""
        good_call = ToolCall(tool_name="get_tasks", parameters={}, requires_approval=False)
        good_result = execute_tool(good_call)
        self.assertIsInstance(good_result, ToolResult)
        dump_good = good_result.model_dump()
        self.assertIn("tool_name", dump_good)
        self.assertIn("success", dump_good)
        self.assertIn("result", dump_good)
        self.assertIn("error", dump_good)

        bad_call = ToolCall(tool_name="delete_task", parameters={}, requires_approval=False)
        bad_result = execute_tool(bad_call)
        self.assertIsInstance(bad_result, ToolResult)
        dump_bad = bad_result.model_dump()
        self.assertIn("tool_name", dump_bad)
        self.assertIn("success", dump_bad)
        self.assertIn("result", dump_bad)
        self.assertIn("error", dump_bad)


if __name__ == "__main__":
    unittest.main()
