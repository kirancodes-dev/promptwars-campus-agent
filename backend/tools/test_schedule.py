from datetime import datetime, timedelta
import os
import sys
import unittest
from pydantic import ValidationError

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models.agent import ScheduleEvent
from tools.schedule import (
    EventNotFoundError,
    check_schedule_conflict,
    clear_schedule,
    create_schedule,
    delete_schedule,
    get_schedule,
    update_schedule,
)


class TestScheduleManagement(unittest.TestCase):
    def setUp(self):
        clear_schedule()
        self.base_time = datetime(2026, 10, 10, 10, 0, 0)

    def tearDown(self):
        clear_schedule()

    def test_create_schedule(self):
        """1. Creating an event."""
        start = self.base_time
        end = start + timedelta(hours=1)
        event = create_schedule(
            title="CS Lecture",
            start_time=start,
            end_time=end,
            description="Room 101",
            requires_approval=True,
        )
        self.assertIsInstance(event, ScheduleEvent)
        self.assertTrue(event.id.startswith("event_"))
        self.assertEqual(event.title, "CS Lecture")
        self.assertEqual(event.description, "Room 101")
        self.assertEqual(event.start_time, start)
        self.assertEqual(event.end_time, end)
        self.assertEqual(event.status, "scheduled")
        self.assertTrue(event.requires_approval)

    def test_get_all_events(self):
        """2. Getting all events."""
        t1 = self.base_time
        create_schedule("Event 1", t1, t1 + timedelta(hours=1))
        create_schedule("Event 2", t1 + timedelta(hours=2), t1 + timedelta(hours=3))
        events = get_schedule()
        self.assertEqual(len(events), 2)

    def test_get_events_within_time_range(self):
        """3. Getting events within a time range."""
        t1 = self.base_time
        e1 = create_schedule("Morning Class", t1, t1 + timedelta(hours=1))
        create_schedule("Afternoon Lab", t1 + timedelta(hours=4), t1 + timedelta(hours=5))

        # Query range covering only morning
        morning_events = get_schedule(
            start_time=t1 - timedelta(minutes=30),
            end_time=t1 + timedelta(hours=2),
        )
        self.assertEqual(len(morning_events), 1)
        self.assertEqual(morning_events[0].id, e1.id)

    def test_update_schedule(self):
        """4. Updating an event."""
        start = self.base_time
        end = start + timedelta(hours=1)
        event = create_schedule("Initial Title", start, end)

        new_start = start + timedelta(hours=2)
        new_end = end + timedelta(hours=2)
        updated = update_schedule(
            event_id=event.id,
            title="Updated Title",
            description="Updated Description",
            start_time=new_start,
            end_time=new_end,
            status="completed",
        )
        self.assertEqual(updated.id, event.id)
        self.assertEqual(updated.title, "Updated Title")
        self.assertEqual(updated.description, "Updated Description")
        self.assertEqual(updated.start_time, new_start)
        self.assertEqual(updated.end_time, new_end)
        self.assertEqual(updated.status, "completed")

    def test_delete_schedule(self):
        """5. Deleting an event."""
        event = create_schedule("Temp Event", self.base_time, self.base_time + timedelta(hours=1))
        result = delete_schedule(event.id)
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("event_id"), event.id)
        self.assertEqual(len(get_schedule()), 0)

    def test_detecting_conflict(self):
        """6. Detecting a conflict."""
        start = self.base_time
        end = start + timedelta(hours=1)
        event = create_schedule("Existing Meeting", start, end)

        # Overlapping time (10:30 - 11:30)
        conflict_res = check_schedule_conflict(
            start_time=start + timedelta(minutes=30),
            end_time=end + timedelta(minutes=30),
        )
        self.assertTrue(conflict_res["has_conflict"])
        self.assertEqual(len(conflict_res["conflicting_events"]), 1)
        self.assertEqual(conflict_res["conflicting_events"][0].id, event.id)

    def test_no_conflict_for_non_overlapping_events(self):
        """7. Confirming no conflict for non-overlapping events."""
        start = self.base_time
        end = start + timedelta(hours=1)
        create_schedule("Existing Meeting", start, end)

        # Adjacent non-overlapping meeting (11:00 - 12:00)
        back_to_back = check_schedule_conflict(
            start_time=end,
            end_time=end + timedelta(hours=1),
        )
        self.assertFalse(back_to_back["has_conflict"])
        self.assertEqual(len(back_to_back["conflicting_events"]), 0)

        # Completely separate meeting later
        later_res = check_schedule_conflict(
            start_time=start + timedelta(hours=3),
            end_time=start + timedelta(hours=4),
        )
        self.assertFalse(later_res["has_conflict"])
        self.assertEqual(len(later_res["conflicting_events"]), 0)

    def test_rejecting_invalid_time_range(self):
        """8. Rejecting an invalid time range."""
        start = self.base_time
        end = start - timedelta(hours=1)  # end before start

        with self.assertRaises(ValueError):
            create_schedule("Bad Event", start, end)

        with self.assertRaises(ValueError):
            check_schedule_conflict(start, end)

        event = create_schedule("Valid Event", self.base_time, self.base_time + timedelta(hours=1))
        with self.assertRaises((ValueError, ValidationError)):
            update_schedule(event.id, end_time=self.base_time - timedelta(minutes=10))

    def test_rejecting_invalid_event_ids(self):
        """9. Rejecting invalid event IDs."""
        with self.assertRaises(EventNotFoundError):
            update_schedule("nonexistent_event_id", title="New Title")

        with self.assertRaises(EventNotFoundError):
            delete_schedule("nonexistent_event_id")

    def test_rejecting_invalid_status_values(self):
        """10. Rejecting invalid status values."""
        event = create_schedule("Event", self.base_time, self.base_time + timedelta(hours=1))
        with self.assertRaises(ValidationError):
            update_schedule(event.id, status="invalid_status")


if __name__ == "__main__":
    unittest.main()
