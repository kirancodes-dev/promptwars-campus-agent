import os
import sys
import unittest

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.router import (
    MissingParameterError,
    ToolDefinition,
    ToolNotFoundError,
    UnknownParameterError,
    get_available_tools,
    get_tool,
    route_tool,
    validate_parameters,
    validate_tool_name,
)
from models.agent import ToolCall
from tools.notes import _notes, clear_notes
from tools.schedule import _events, clear_schedule
from tools.tasks import _tasks, clear_tasks


class TestToolRouter(unittest.TestCase):
    def setUp(self):
        clear_tasks()
        clear_schedule()
        clear_notes()

    def tearDown(self):
        clear_tasks()
        clear_schedule()
        clear_notes()

    def test_all_registered_tools_returned(self):
        """1. All registered tools are returned."""
        tools = get_available_tools()
        self.assertEqual(len(tools), 17)
        tool_names = {tool.name for tool in tools}
        expected_tools = {
            "create_task",
            "get_tasks",
            "update_task",
            "delete_task",
            "create_schedule",
            "get_schedule",
            "update_schedule",
            "delete_schedule",
            "check_schedule_conflict",
            "create_note",
            "get_notes",
            "update_note",
            "delete_note",
            "search_notes",
            "get_student_preferences",
            "update_student_preferences",
            "reset_student_preferences",
        }
        self.assertEqual(tool_names, expected_tools)
        for tool in tools:
            self.assertIsInstance(tool, ToolDefinition)
            self.assertTrue(len(tool.description) > 0)

    def test_existing_tool_names_recognized(self):
        """2. Existing tool names are recognized."""
        self.assertTrue(validate_tool_name("create_task"))
        self.assertTrue(validate_tool_name("create_schedule"))
        self.assertTrue(validate_tool_name("create_note"))
        self.assertTrue(validate_tool_name("delete_task"))

        tool_def = get_tool("create_task")
        self.assertEqual(tool_def.name, "create_task")

    def test_unknown_tool_names_rejected(self):
        """3. Unknown tool names are rejected."""
        self.assertFalse(validate_tool_name("nonexistent_tool"))
        with self.assertRaises(ToolNotFoundError):
            get_tool("nonexistent_tool")
        with self.assertRaises(ToolNotFoundError):
            route_tool("nonexistent_tool", {})

    def test_valid_parameters_accepted(self):
        """4. Valid parameters are accepted."""
        params = {"title": "Study algorithms", "priority": "high"}
        validated = validate_parameters("create_task", params)
        self.assertEqual(validated, params)
        self.assertIs(validated, params)

    def test_missing_required_parameters_rejected(self):
        """5. Missing required parameters are rejected."""
        with self.assertRaises(MissingParameterError):
            validate_parameters("create_task", {})

        with self.assertRaises(MissingParameterError):
            validate_parameters("delete_task", {})

        with self.assertRaises(MissingParameterError):
            validate_parameters("create_schedule", {"title": "Meeting"})

    def test_unknown_parameters_rejected(self):
        """6. Unknown parameters are rejected."""
        with self.assertRaises(UnknownParameterError):
            validate_parameters("create_task", {"title": "Valid Title", "invalid_param": 123})

        with self.assertRaises(UnknownParameterError):
            validate_parameters("get_tasks", {"unsupported": "flag"})

    def test_route_tool_returns_valid_tool_call(self):
        """7. route_tool() returns a valid ToolCall."""
        params = {"title": "Complete project", "priority": "high"}
        tool_call = route_tool("create_task", params)
        self.assertIsInstance(tool_call, ToolCall)
        self.assertEqual(tool_call.tool_name, "create_task")
        self.assertEqual(tool_call.parameters, params)
        self.assertFalse(tool_call.requires_approval)

    def test_requires_approval_correctly_returned(self):
        """8. requires_approval is correctly returned."""
        del_task_call = route_tool("delete_task", {"task_id": "task_123"})
        self.assertTrue(del_task_call.requires_approval)

        del_sched_call = route_tool("delete_schedule", {"event_id": "event_123"})
        self.assertTrue(del_sched_call.requires_approval)

        del_note_call = route_tool("delete_note", {"note_id": "note_123"})
        self.assertTrue(del_note_call.requires_approval)

        get_task_call = route_tool("get_tasks", {})
        self.assertFalse(get_task_call.requires_approval)

        explicit_approval_call = route_tool(
            "create_task",
            {"title": "Important task", "requires_approval": True},
        )
        self.assertTrue(explicit_approval_call.requires_approval)

    def test_no_tool_executed_during_routing(self):
        """9. No tool is executed during routing."""
        self.assertEqual(len(_tasks), 0)
        self.assertEqual(len(_events), 0)
        self.assertEqual(len(_notes), 0)

        route_tool("create_task", {"title": "Task not to create"})
        route_tool("create_note", {"title": "Note not to create", "content": "Content"})

        # Verify storage remains untouched
        self.assertEqual(len(_tasks), 0)
        self.assertEqual(len(_events), 0)
        self.assertEqual(len(_notes), 0)


if __name__ == "__main__":
    unittest.main()
