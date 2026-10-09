"""Read-back verification for every write tool: success, missing entity, and field mismatch."""

from datetime import datetime, timedelta
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.workflow import verify_tool_execution
from models.agent import ToolResult
from services.in_memory import InMemoryPersistence
from services.memory import MemoryService
from services.persistence import reset_persistence, set_persistence
from tools.notes import create_note, update_note
from tools.schedule import create_schedule, update_schedule
from tools.tasks import create_task, update_task

START = datetime(2026, 10, 10, 9, 0)


def ok(tool, payload=None):
    return ToolResult(tool_name=tool, success=True, result=payload or {})


class TestVerification(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryPersistence()
        set_persistence(self.store, mode="memory")

    def tearDown(self):
        reset_persistence()

    def assertVerified(self, tool, params, result):
        self.assertEqual(verify_tool_execution(tool, params, result), (True, None))

    def assertRejected(self, tool, params, result, fragment):
        verified, err = verify_tool_execution(tool, params, result)
        self.assertFalse(verified)
        self.assertIn(fragment, err)

    def test_failed_tool_result_is_never_verified(self):
        res = ToolResult(tool_name="create_task", success=False, error="boom")
        self.assertEqual(verify_tool_execution("create_task", {}, res), (False, "boom"))

    def test_create_schedule(self):
        params = {"title": "DBMS", "start_time": START, "end_time": START + timedelta(hours=2)}
        ev = create_schedule(**params)
        self.assertVerified("create_schedule", params, ok("create_schedule", {"id": ev.id}))
        self.assertVerified("create_schedule", {**params, "start_time": START.isoformat()}, ok("create_schedule", {"id": ev.id}))
        self.assertRejected("create_schedule", params, ok("create_schedule"), "did not return an event ID")
        self.assertRejected("create_schedule", params, ok("create_schedule", {"id": "event_missing"}), "was not found")
        self.assertRejected("create_schedule", {**params, "title": "Other"}, ok("create_schedule", {"id": ev.id}), "field 'title' does not match")
        self.assertRejected("create_schedule", {**params, "start_time": "not-a-date"}, ok("create_schedule", {"id": ev.id}), "field 'start_time'")

    def test_create_task_and_note(self):
        task = create_task(title="Revise")
        self.assertVerified("create_task", {"title": "Revise"}, ok("create_task", {"id": task.id}))
        self.assertRejected("create_task", {"title": "Revise"}, ok("create_task"), "did not return a task ID")
        self.assertRejected("create_task", {"title": "Changed"}, ok("create_task", {"id": task.id}), "does not match")
        note = create_note(title="N", content="C")
        self.assertVerified("create_note", {"title": "N", "content": "C"}, ok("create_note", {"id": note.id}))
        self.assertRejected("create_note", {}, ok("create_note"), "did not return a note ID")
        self.assertRejected("create_note", {}, ok("create_note", {"id": "note_missing"}), "was not found")

    def test_updates(self):
        ev = create_schedule(title="DBMS", start_time=START, end_time=START + timedelta(hours=1))
        update_schedule(ev.id, title="DBMS revision")
        self.assertVerified("update_schedule", {"event_id": ev.id, "title": "DBMS revision"}, ok("update_schedule"))
        self.assertRejected("update_schedule", {"event_id": ev.id, "title": "Something else"}, ok("update_schedule"), "was not updated")
        self.assertRejected("update_schedule", {"event_id": "event_missing"}, ok("update_schedule"), "Updated event 'event_missing' not found")
        task = create_task(title="T")
        update_task(task.id, status="completed")
        self.assertVerified("update_task", {"task_id": task.id, "status": "completed"}, ok("update_task"))
        self.assertRejected("update_task", {"task_id": task.id, "status": "failed"}, ok("update_task"), "field 'status' was not updated")
        note = create_note(title="N", content="C")
        update_note(note.id, content="C2")
        self.assertVerified("update_note", {"note_id": note.id, "content": "C2"}, ok("update_note"))
        self.assertRejected("update_note", {"note_id": note.id, "content": "C3"}, ok("update_note"), "field 'content'")

    def test_deletes(self):
        ev = create_schedule(title="X", start_time=START, end_time=START + timedelta(hours=1))
        task, note = create_task(title="T"), create_note(title="N", content="C")
        self.assertRejected("delete_schedule", {"event_id": ev.id}, ok("delete_schedule"), "is still present")
        self.assertRejected("delete_task", {"task_id": task.id}, ok("delete_task"), "is still present")
        self.assertRejected("delete_note", {"note_id": note.id}, ok("delete_note"), "is still present")
        self.store.delete_event(ev.id); self.store.delete_task(task.id); self.store.delete_note(note.id)
        self.assertVerified("delete_schedule", {"event_id": ev.id}, ok("delete_schedule"))
        self.assertVerified("delete_task", {"task_id": task.id}, ok("delete_task"))
        self.assertVerified("delete_note", {"note_id": note.id}, ok("delete_note"))

    def test_preferences(self):
        params = {"preferred_break_minutes": 15, "subject_time_preferences": {"DBMS": "evening"}, "planning_notes": ["no late nights"]}
        self.assertRejected("update_student_preferences", params, ok("update_student_preferences"), "preference 'preferred_break_minutes'")
        MemoryService().update_preferences({"preferred_break_minutes": 15})
        self.assertRejected("update_student_preferences", params, ok("update_student_preferences"), "timing preference for 'DBMS'")
        MemoryService().update_preferences({"subject_time_preferences": {"DBMS": "evening"}})
        self.assertRejected("update_student_preferences", params, ok("update_student_preferences"), "planning note")
        MemoryService().update_preferences({"planning_notes": ["no late nights"]})
        self.assertVerified("update_student_preferences", params, ok("update_student_preferences"))
        self.assertRejected("reset_student_preferences", {"confirmation": True}, ok("reset_student_preferences"), "not reset")
        MemoryService().reset_preferences(confirmation=True)
        self.assertVerified("reset_student_preferences", {"confirmation": True}, ok("reset_student_preferences"))

    def test_storage_error_during_read_back_is_a_failure_not_a_crash(self):
        broken = MagicMock(wraps=self.store)
        broken.get_task.side_effect = RuntimeError("storage down")
        set_persistence(broken, mode="firestore")
        verified, err = verify_tool_execution("create_task", {"title": "T"}, ok("create_task", {"id": "task_1"}))
        self.assertFalse(verified)
        self.assertEqual(err, "Verification error: RuntimeError")

    def test_read_only_tools_need_no_read_back(self):
        self.assertVerified("get_tasks", {}, ok("get_tasks"))


if __name__ == "__main__":
    unittest.main()
