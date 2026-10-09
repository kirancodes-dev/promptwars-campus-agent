import os
import sys
import unittest
from pydantic import ValidationError

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models.agent import AgentTask
from tools.tasks import (
    TaskNotFoundError,
    clear_tasks,
    create_task,
    delete_task,
    get_tasks,
    update_task,
)


class TestTaskManagement(unittest.TestCase):
    def setUp(self):
        clear_tasks()

    def tearDown(self):
        clear_tasks()

    def test_create_task(self):
        task = create_task(
            title="Complete CS assignment",
            description="Homework on binary trees",
            priority="high",
            tool="tasks",
            requires_approval=False,
        )
        self.assertIsInstance(task, AgentTask)
        self.assertTrue(task.id.startswith("task_"))
        self.assertEqual(task.title, "Complete CS assignment")
        self.assertEqual(task.description, "Homework on binary trees")
        self.assertEqual(task.status, "pending")
        self.assertEqual(task.priority, "high")
        self.assertEqual(task.tool, "tasks")
        self.assertFalse(task.requires_approval)

    def test_get_tasks(self):
        t1 = create_task(title="Task 1", priority="low")
        t2 = create_task(title="Task 2", priority="high")
        tasks = get_tasks()
        self.assertEqual(len(tasks), 2)
        task_ids = [t.id for t in tasks]
        self.assertIn(t1.id, task_ids)
        self.assertIn(t2.id, task_ids)
        for t in tasks:
            self.assertIsInstance(t, AgentTask)

    def test_filter_tasks_by_status(self):
        t1 = create_task(title="Task 1")
        t2 = create_task(title="Task 2")
        update_task(t2.id, status="completed")

        pending_tasks = get_tasks(status="pending")
        completed_tasks = get_tasks(status="completed")

        self.assertEqual(len(pending_tasks), 1)
        self.assertEqual(pending_tasks[0].id, t1.id)
        self.assertEqual(len(completed_tasks), 1)
        self.assertEqual(completed_tasks[0].id, t2.id)

    def test_update_task(self):
        task = create_task(title="Initial Title", priority="low")
        updated = update_task(
            task_id=task.id,
            title="Updated Title",
            status="in_progress",
            priority="high",
        )
        self.assertIsInstance(updated, AgentTask)
        self.assertEqual(updated.id, task.id)
        self.assertEqual(updated.title, "Updated Title")
        self.assertEqual(updated.status, "in_progress")
        self.assertEqual(updated.priority, "high")

    def test_update_task_invalid_status(self):
        task = create_task(title="Test Task")
        with self.assertRaises(ValidationError):
            update_task(task.id, status="not_a_valid_status")

    def test_delete_task(self):
        task = create_task(title="Task to delete")
        result = delete_task(task.id)
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("task_id"), task.id)
        self.assertEqual(len(get_tasks()), 0)

    def test_invalid_task_ids_produce_clear_error(self):
        with self.assertRaises(TaskNotFoundError) as ctx_update:
            update_task("nonexistent_id", title="New Title")
        self.assertIn("nonexistent_id", str(ctx_update.exception))

        with self.assertRaises(TaskNotFoundError) as ctx_delete:
            delete_task("nonexistent_id")
        self.assertIn("nonexistent_id", str(ctx_delete.exception))

    def test_returned_objects_are_valid_agent_task_models(self):
        created = create_task(title="Model verification task")
        self.assertIsInstance(created, AgentTask)
        self.assertTrue(hasattr(created, "model_dump"))

        retrieved = get_tasks()[0]
        self.assertIsInstance(retrieved, AgentTask)

        updated = update_task(created.id, status="completed")
        self.assertIsInstance(updated, AgentTask)


if __name__ == "__main__":
    unittest.main()
