from datetime import date, datetime, time, timedelta
import os
import sys
import unittest

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models.agent import AgentTask, Note, ScheduleEvent, UserGoal
from services.in_memory import InMemoryPersistence
from services.persistence import (
    DEFAULT_USER_ID,
    EntityNotFoundError,
    get_persistence,
    get_persistence_mode,
    reset_persistence,
    set_persistence,
)
from tools.notes import clear_notes, create_note, delete_note, get_notes, search_notes, update_note
from tools.schedule import (
    _events,
    check_schedule_conflict,
    clear_schedule,
    create_schedule,
    find_available_slots,
    get_schedule,
)
from tools.tasks import _tasks, clear_tasks, create_task, delete_task, get_tasks, update_task


class TestPersistence(unittest.TestCase):
    def setUp(self):
        reset_persistence()
        self.persistence = InMemoryPersistence()
        set_persistence(self.persistence)
        clear_tasks()
        clear_schedule()
        clear_notes()

    def tearDown(self):
        clear_tasks()
        clear_schedule()
        clear_notes()
        reset_persistence()

    def test_in_memory_persistence_task_crud(self):
        """1. InMemoryPersistence handles Task create, get, list, update, and delete."""
        task = AgentTask(
            id="t1",
            title="Study DBMS",
            description="Review chapters 1-3",
            status="pending",
            priority="high",
        )
        created = self.persistence.create_task(task)
        self.assertEqual(created.id, "t1")

        # Get
        fetched = self.persistence.get_task("t1")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.title, "Study DBMS")

        # List with filter
        pending = self.persistence.get_tasks(status="pending")
        self.assertEqual(len(pending), 1)
        completed = self.persistence.get_tasks(status="completed")
        self.assertEqual(len(completed), 0)

        # Update
        updated = self.persistence.update_task("t1", {"status": "completed"})
        self.assertEqual(updated.status, "completed")
        self.assertEqual(self.persistence.get_task("t1").status, "completed")

        # Delete
        self.assertTrue(self.persistence.delete_task("t1"))
        self.assertIsNone(self.persistence.get_task("t1"))

    def test_in_memory_persistence_schedule_crud(self):
        """2. InMemoryPersistence handles Schedule create, get, list, update, and delete."""
        start = datetime(2026, 10, 9, 10, 0)
        end = datetime(2026, 10, 9, 12, 0)
        event = ScheduleEvent(
            id="ev1",
            title="DBMS Class",
            start_time=start,
            end_time=end,
            status="scheduled",
        )
        self.persistence.create_event(event)

        # Get
        fetched = self.persistence.get_event("ev1")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.title, "DBMS Class")

        # Range filter
        in_range = self.persistence.get_events(
            start_time=datetime(2026, 10, 9, 9, 0),
            end_time=datetime(2026, 10, 9, 13, 0),
        )
        self.assertEqual(len(in_range), 1)

        out_of_range = self.persistence.get_events(
            start_time=datetime(2026, 10, 9, 13, 0),
            end_time=datetime(2026, 10, 9, 15, 0),
        )
        self.assertEqual(len(out_of_range), 0)

        # Update
        updated = self.persistence.update_event("ev1", {"title": "Advanced DBMS Class"})
        self.assertEqual(updated.title, "Advanced DBMS Class")

        # Delete
        self.assertTrue(self.persistence.delete_event("ev1"))
        self.assertIsNone(self.persistence.get_event("ev1"))

    def test_in_memory_persistence_notes_crud_and_search(self):
        """3. InMemoryPersistence handles Notes create, get, list, search, update, and delete."""
        note = Note(
            id="n1",
            title="SQL Joins Summary",
            content="Inner join vs left join cheat sheet",
            category="dbms",
        )
        self.persistence.create_note(note)

        # Get & List
        self.assertIsNotNone(self.persistence.get_note("n1"))
        self.assertEqual(len(self.persistence.get_notes(category="dbms")), 1)
        self.assertEqual(len(self.persistence.get_notes(category="general")), 0)

        # Search
        results = self.persistence.search_notes("joins")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, "n1")

        # Update
        updated = self.persistence.update_note("n1", {"content": "Updated SQL cheat sheet"})
        self.assertEqual(updated.content, "Updated SQL cheat sheet")

        # Delete
        self.assertTrue(self.persistence.delete_note("n1"))
        self.assertIsNone(self.persistence.get_note("n1"))

    def test_user_isolation(self):
        """4. Verify multi-user isolation using different user IDs."""
        task1 = AgentTask(id="u1_task", title="User 1 Task")
        task2 = AgentTask(id="u2_task", title="User 2 Task")

        self.persistence.create_task(task1, user_id="user-1")
        self.persistence.create_task(task2, user_id="user-2")

        # User 1 cannot see User 2's tasks
        u1_tasks = self.persistence.get_tasks(user_id="user-1")
        u2_tasks = self.persistence.get_tasks(user_id="user-2")

        self.assertEqual(len(u1_tasks), 1)
        self.assertEqual(u1_tasks[0].id, "u1_task")
        self.assertEqual(len(u2_tasks), 1)
        self.assertEqual(u2_tasks[0].id, "u2_task")

        # Schedule isolation
        ev1 = ScheduleEvent(
            id="u1_ev",
            title="User 1 Event",
            start_time=datetime(2026, 10, 9, 10, 0),
            end_time=datetime(2026, 10, 9, 11, 0),
        )
        ev2 = ScheduleEvent(
            id="u2_ev",
            title="User 2 Event",
            start_time=datetime(2026, 10, 9, 10, 0),
            end_time=datetime(2026, 10, 9, 11, 0),
        )
        self.persistence.create_event(ev1, user_id="user-1")
        self.persistence.create_event(ev2, user_id="user-2")

        self.assertIsNotNone(self.persistence.get_event("u1_ev", user_id="user-1"))
        self.assertIsNone(self.persistence.get_event("u2_ev", user_id="user-1"))

    def test_entity_not_found_errors_raised(self):
        """5. Updating or deleting non-existent entities raises EntityNotFoundError."""
        with self.assertRaises(EntityNotFoundError):
            self.persistence.update_task("nonexistent", {"title": "X"})
        with self.assertRaises(EntityNotFoundError):
            self.persistence.delete_task("nonexistent")

        with self.assertRaises(EntityNotFoundError):
            self.persistence.update_event("nonexistent", {"title": "X"})
        with self.assertRaises(EntityNotFoundError):
            self.persistence.delete_event("nonexistent")

        with self.assertRaises(EntityNotFoundError):
            self.persistence.update_note("nonexistent", {"title": "X"})
        with self.assertRaises(EntityNotFoundError):
            self.persistence.delete_note("nonexistent")

    def test_persistence_mode_defaults_to_memory(self):
        """6. Default persistence mode is 'memory' when FIRESTORE_ENABLED is false/unset."""
        reset_persistence()
        mode = get_persistence_mode()
        self.assertEqual(mode, "memory")
        pers = get_persistence()
        self.assertEqual(pers.mode, "memory")

    def test_tools_use_persistence_transparently(self):
        """7. Existing tools transparently use active persistence."""
        task = create_task(title="Persistent Study Task", priority="high")
        self.assertIn(task.id, _tasks)
        self.assertEqual(len(get_tasks()), 1)

        # Verify it went into active persistence
        persisted = self.persistence.get_task(task.id)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.title, "Persistent Study Task")

        # Delete through tool
        delete_task(task.id)
        self.assertEqual(len(get_tasks()), 0)
        self.assertIsNone(self.persistence.get_task(task.id))

    def test_schedule_conflict_detection_with_persistence(self):
        """8. Schedule conflict detection operates accurately through persistence."""
        e_start = datetime(2026, 10, 9, 16, 0)
        e_end = datetime(2026, 10, 9, 17, 0)
        create_schedule(title="Meeting", start_time=e_start, end_time=e_end)

        # Overlapping interval
        conflict = check_schedule_conflict(
            start_time=datetime(2026, 10, 9, 16, 30),
            end_time=datetime(2026, 10, 9, 17, 30),
        )
        self.assertTrue(conflict["has_conflict"])
        self.assertEqual(conflict["conflict_count"], 1)

        # Adjacent non-overlapping interval
        adjacent = check_schedule_conflict(
            start_time=datetime(2026, 10, 9, 17, 0),
            end_time=datetime(2026, 10, 9, 18, 0),
        )
        self.assertFalse(adjacent["has_conflict"])

    def test_available_slots_calculation_with_persistence(self):
        """9. Available slot calculation operates accurately through persistence."""
        target_day = date(2026, 10, 9)
        create_schedule(
            title="Meeting 1",
            start_time=datetime.combine(target_day, time(10, 0)),
            end_time=datetime.combine(target_day, time(11, 0)),
        )
        create_schedule(
            title="Meeting 2",
            start_time=datetime.combine(target_day, time(13, 0)),
            end_time=datetime.combine(target_day, time(14, 0)),
        )

        slots = find_available_slots(
            date=target_day,
            duration_minutes=60,
            preferred_start=time(9, 0),
            preferred_end=time(15, 0),
        )
        slot_starts = [s["start_time"] for s in slots]
        self.assertIn(datetime.combine(target_day, time(9, 0)), slot_starts)
        self.assertIn(datetime.combine(target_day, time(11, 0)), slot_starts)
        self.assertIn(datetime.combine(target_day, time(14, 0)), slot_starts)

    def test_no_eval_or_exec_used(self):
        """10. No eval() or exec() is used in any persistence module."""
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        for filename in ["persistence.py", "in_memory.py", "firestore.py"]:
            file_path = os.path.join(backend_dir, "services", filename)
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.assertNotIn("eval(", content, f"eval() found in {filename}")
                self.assertNotIn("exec(", content, f"exec() found in {filename}")


if __name__ == "__main__":
    unittest.main()
