from datetime import date, datetime, time, timedelta
import os
import sys
from typing import Any
import unittest
from unittest.mock import patch

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.orchestrator import AgentOrchestrator
from models.agent import AgentTask, Note, ScheduleEvent, UserGoal
from services.firestore import FirestorePersistence, init_firestore
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


class FakeDocumentSnapshot:
    """Mock Firestore DocumentSnapshot."""

    def __init__(self, doc_id: str, data: dict | None, exists: bool = True, reference: Any | None = None):
        self.id = doc_id
        self._data = dict(data) if data else None
        self.exists = exists
        self.reference = reference

    def to_dict(self):
        return dict(self._data) if self._data else {}


class FakeDocRef:
    """Mock Firestore DocumentReference."""

    def __init__(self, doc_id: str, collection: "FakeCollection", client: "FakeFirestoreClient"):
        self.id = doc_id
        self._collection = collection
        self.client = client

    def collection(self, sub_name: str):
        sub_path = f"{self._collection.name}/{self.id}/{sub_name}"
        return self.client._get_or_create_collection(sub_path)

    def set(self, data: dict):
        self._collection.docs[self.id] = dict(data)

    def get(self):
        if self.id in self._collection.docs:
            return FakeDocumentSnapshot(self.id, self._collection.docs[self.id], exists=True, reference=self)
        return FakeDocumentSnapshot(self.id, None, exists=False, reference=self)

    def delete(self):
        self._collection.docs.pop(self.id, None)


class FakeCollection:
    """Mock Firestore CollectionReference."""

    def __init__(self, name: str, client: "FakeFirestoreClient"):
        self.name = name
        self.client = client
        self.docs: dict[str, dict] = {}

    def document(self, doc_id: str):
        return FakeDocRef(doc_id, self, self.client)

    def where(self, *args, **kwargs):
        return FakeQuery(self).where(*args, **kwargs)

    def order_by(self, *args, **kwargs):
        return FakeQuery(self).order_by(*args, **kwargs)

    def limit(self, n):
        return FakeQuery(self).limit(n)

    def stream(self):
        return [
            FakeDocumentSnapshot(
                doc_id,
                data,
                exists=True,
                reference=FakeDocRef(doc_id, self, self.client),
            )
            for doc_id, data in self.docs.items()
        ]


class FakeQuery:
    """Minimal query support: where (FieldFilter), order_by, limit, stream."""

    def __init__(self, collection, filters=None, order=None, limit_n=None):
        self.collection, self.filters, self.order, self.limit_n = collection, list(filters or []), order, limit_n

    def where(self, field_path=None, op_string=None, value=None, filter=None):
        f = filter or type("F", (), {"field_path": field_path, "op_string": op_string, "value": value})()
        return FakeQuery(self.collection, self.filters + [f], self.order, self.limit_n)

    def order_by(self, field, direction="ASCENDING"):
        return FakeQuery(self.collection, self.filters, (field, direction), self.limit_n)

    def limit(self, n):
        return FakeQuery(self.collection, self.filters, self.order, n)

    def stream(self):
        ops = {">=": lambda a, b: a >= b, "<": lambda a, b: a < b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b, "==": lambda a, b: a == b}
        rows = [(i, d) for i, d in self.collection.docs.items()
                if all(f.field_path in d and ops[f.op_string](d[f.field_path], f.value) for f in self.filters)]
        if self.order:
            field, direction = self.order
            rows = [r for r in rows if field in r[1]]
            rows.sort(key=lambda r: r[1][field], reverse=direction == "DESCENDING")
        if self.limit_n is not None:
            rows = rows[: self.limit_n]
        self.collection.client.docs_read += len(rows)
        return [FakeDocumentSnapshot(i, d, exists=True, reference=FakeDocRef(i, self.collection, self.collection.client)) for i, d in rows]


class FakeBatch:
    def __init__(self, client):
        self.client, self.ops = client, []

    def set(self, doc_ref, data):
        self.ops.append((doc_ref, data))

    def commit(self):
        self.client.batch_commits += 1
        for ref, data in self.ops:
            ref.set(data)


class FakeFirestoreClient:
    """Mock Firestore Client simulating collection/document hierarchy."""

    def __init__(self):
        self._collections: dict[str, FakeCollection] = {}
        self.docs_read = 0
        self.batch_commits = 0

    def batch(self):
        return FakeBatch(self)

    def collection(self, name: str):
        return self._get_or_create_collection(name)

    def _get_or_create_collection(self, path: str):
        if path not in self._collections:
            self._collections[path] = FakeCollection(path, self)
        return self._collections[path]


class TestFirestorePersistence(unittest.TestCase):
    def setUp(self):
        reset_persistence()
        self.fake_client = FakeFirestoreClient()
        self.firestore_persistence = FirestorePersistence(client=self.fake_client)
        set_persistence(self.firestore_persistence)
        clear_tasks()
        clear_schedule()
        clear_notes()

    def tearDown(self):
        clear_tasks()
        clear_schedule()
        clear_notes()
        reset_persistence()

    def test_firestore_disabled_by_default(self):
        """1. When FIRESTORE_ENABLED is false/unset, init_firestore() returns None."""
        with patch.dict(os.environ, {"FIRESTORE_ENABLED": "false"}):
            instance = init_firestore()
            self.assertIsNone(instance)

        with patch.dict(os.environ, {}, clear=True):
            instance = init_firestore()
            self.assertIsNone(instance)

    def test_firestore_init_handles_configuration_failure_safely(self):
        """2. When Firestore init fails, safe fallback occurs without crashes."""
        with patch.dict(os.environ, {"FIRESTORE_ENABLED": "true"}):
            with patch("google.cloud.firestore.Client", side_effect=RuntimeError("Auth error")):
                instance = init_firestore()
                self.assertIsNone(instance)

        # Persistence provider automatically falls back to in-memory
        reset_persistence()
        with patch.dict(os.environ, {"FIRESTORE_ENABLED": "true"}):
            with patch("google.cloud.firestore.Client", side_effect=RuntimeError("Auth error")):
                active = get_persistence()
                self.assertEqual(active.mode, "memory")

    def test_task_crud_with_firestore(self):
        """3. Firestore persistence supports full Task CRUD operations."""
        task = AgentTask(
            id="fs_t1",
            title="Complete DBMS Assignment",
            status="pending",
            priority="high",
        )
        self.firestore_persistence.create_task(task)

        # Get
        fetched = self.firestore_persistence.get_task("fs_t1")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.title, "Complete DBMS Assignment")

        # List
        tasks = self.firestore_persistence.get_tasks(status="pending")
        self.assertEqual(len(tasks), 1)

        # Update
        updated = self.firestore_persistence.update_task("fs_t1", {"status": "completed"})
        self.assertEqual(updated.status, "completed")
        self.assertEqual(self.firestore_persistence.get_task("fs_t1").status, "completed")

        # Delete
        self.assertTrue(self.firestore_persistence.delete_task("fs_t1"))
        self.assertIsNone(self.firestore_persistence.get_task("fs_t1"))

    def test_schedule_crud_with_firestore(self):
        """4. Firestore persistence supports full Schedule CRUD operations."""
        start = datetime(2026, 10, 9, 14, 0)
        end = datetime(2026, 10, 9, 15, 0)
        event = ScheduleEvent(
            id="fs_ev1",
            title="DAA Lab",
            start_time=start,
            end_time=end,
            status="scheduled",
        )
        self.firestore_persistence.create_event(event)

        # Get
        fetched = self.firestore_persistence.get_event("fs_ev1")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.title, "DAA Lab")

        # List with time filter
        events = self.firestore_persistence.get_events(
            start_time=datetime(2026, 10, 9, 13, 0),
            end_time=datetime(2026, 10, 9, 16, 0),
        )
        self.assertEqual(len(events), 1)

        # Update
        updated = self.firestore_persistence.update_event("fs_ev1", {"title": "DAA Practice Lab"})
        self.assertEqual(updated.title, "DAA Practice Lab")

        # Delete
        self.assertTrue(self.firestore_persistence.delete_event("fs_ev1"))
        self.assertIsNone(self.firestore_persistence.get_event("fs_ev1"))

    def test_notes_crud_and_search_with_firestore(self):
        """5. Firestore persistence supports Notes CRUD and search operations."""
        note = Note(
            id="fs_n1",
            title="DAA Algorithm Notes",
            content="Binary Search time complexity O(log N)",
            category="daa",
        )
        self.firestore_persistence.create_note(note)

        # Get
        fetched = self.firestore_persistence.get_note("fs_n1")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.title, "DAA Algorithm Notes")

        # List
        notes = self.firestore_persistence.get_notes(category="daa")
        self.assertEqual(len(notes), 1)

        # Search
        results = self.firestore_persistence.search_notes("complexity")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, "fs_n1")

        # Update
        updated = self.firestore_persistence.update_note("fs_n1", {"content": "O(log N) optimal search"})
        self.assertIn("optimal search", updated.content)

        # Delete
        self.assertTrue(self.firestore_persistence.delete_note("fs_n1"))
        self.assertIsNone(self.firestore_persistence.get_note("fs_n1"))

    def test_firestore_user_isolation(self):
        """6. Firestore persistence enforces user isolation under users/{user_id}/."""
        task1 = AgentTask(id="t1", title="User 1 Task")
        task2 = AgentTask(id="t2", title="User 2 Task")

        self.firestore_persistence.create_task(task1, user_id="student_alpha")
        self.firestore_persistence.create_task(task2, user_id="student_beta")

        alpha_tasks = self.firestore_persistence.get_tasks(user_id="student_alpha")
        beta_tasks = self.firestore_persistence.get_tasks(user_id="student_beta")

        self.assertEqual(len(alpha_tasks), 1)
        self.assertEqual(alpha_tasks[0].id, "t1")
        self.assertEqual(len(beta_tasks), 1)
        self.assertEqual(beta_tasks[0].id, "t2")

    def test_approval_protection_intact_with_firestore(self):
        """7. Write tools remain approval-protected when Firestore is the active persistence."""
        orchestrator = AgentOrchestrator()
        goal = UserGoal(
            goal="Organize my preparation for tomorrow. I need 2 hours of DBMS, 1 hour of DAA, and I have a project meeting at 4 PM."
        )

        # Running without approval
        result = orchestrator.run(goal, approved=False)
        # Even with Firestore active, approval must be required
        self.assertTrue(result.requires_approval)
        self.assertEqual(result.status, "waiting_approval")
        # Nothing saved in persistence without approval
        self.assertEqual(len(self.firestore_persistence.get_events()), 0)

    def test_conflict_and_available_slots_work_with_firestore(self):
        """8. Schedule conflict detection and available slot finding work through Firestore."""
        target_day = date(2026, 10, 9)
        e1_start = datetime.combine(target_day, time(16, 0))
        e1_end = datetime.combine(target_day, time(17, 0))
        create_schedule(title="Project Meeting", start_time=e1_start, end_time=e1_end)

        # Verify conflict check
        conflict = check_schedule_conflict(start_time=e1_start, end_time=e1_end)
        self.assertTrue(conflict["has_conflict"])

        # Verify available slot search
        slots = find_available_slots(
            date=target_day,
            duration_minutes=120,
            preferred_start=time(16, 0),
            preferred_end=time(20, 0),
        )
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0]["start_time"], datetime.combine(target_day, time(17, 0)))

    def test_no_secrets_exposed_in_string_representations(self):
        """9. No secret fields or credentials appear in string representations."""
        rep = repr(self.firestore_persistence)
        st = str(self.firestore_persistence)
        for forbidden in ["private_key", "client_secret", "BEGIN PRIVATE KEY", "AIza"]:
            self.assertNotIn(forbidden, rep)
            self.assertNotIn(forbidden, st)

    def test_no_credentials_committed_in_repo(self):
        """10. Verify no credential files exist in repository."""
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        for root, dirs, files in os.walk(backend_dir):
            for file in files:
                if file.endswith(".json") and any(
                    k in file.lower() for k in ["service_account", "firebase_secret", "private_key"]
                ):
                    self.fail(f"Potential credential file found: {file}")


if __name__ == "__main__":
    unittest.main()


class TestFirestoreEfficientQueries(unittest.TestCase):
    """Bounded reads and batched writes on the Firestore adapter (fake client counts documents read)."""

    def setUp(self):
        from models.audit import AuditLogEntry
        from models.workflow import WorkflowRecord

        self.AuditLogEntry, self.WorkflowRecord = AuditLogEntry, WorkflowRecord
        self.client = FakeFirestoreClient()
        self.fs = FirestorePersistence(client=self.client)

    def _event(self, eid, start, hours=1):
        return ScheduleEvent(id=eid, title=eid, start_time=start, end_time=start + timedelta(hours=hours))

    def test_overlap_query_returns_exactly_the_overlapping_events(self):
        day = datetime(2026, 10, 10, 0, 0)
        for e in [
            self._event("before", day - timedelta(days=3)),
            self._event("overnight", day - timedelta(hours=2), hours=4),   # starts the day before, ends inside
            self._event("long-cross", day - timedelta(hours=23), hours=24),  # max length, crosses into the day
            self._event("inside", day + timedelta(hours=9)),
            self._event("after", day + timedelta(days=2)),
        ]:
            self.fs.create_event(e)
        found = {e.id for e in self.fs.get_events_overlapping(day, day + timedelta(days=1))}
        self.assertEqual(found, {"overnight", "long-cross", "inside"})

    def test_audit_log_reads_only_the_newest_limit(self):
        base = datetime(2026, 10, 9, 8, 0)
        entries = [self.AuditLogEntry(id=f"a{i:02d}", goal="g", approval_status="n/a", execution_status="n/a",
                                      timestamp=base + timedelta(minutes=i)) for i in range(60)]
        self.fs.record_audit_logs(entries)
        self.assertEqual(self.client.batch_commits, 1)
        self.client.docs_read = 0
        logs = self.fs.get_audit_logs(limit=10)
        self.assertEqual([l.id for l in logs], [f"a{i:02d}" for i in range(59, 49, -1)])
        self.assertEqual(self.client.docs_read, 10)

    def test_batched_audit_writes_chunk_large_batches(self):
        entries = [self.AuditLogEntry(id=f"b{i}", goal="g", approval_status="n/a", execution_status="n/a") for i in range(1000)]
        self.fs.record_audit_logs(entries)
        self.assertEqual(self.client.batch_commits, 3)  # 450 + 450 + 100
        self.assertEqual(len(self.fs.get_audit_logs(limit=2000)), 1000)

    def test_workflow_history_is_newest_first_and_bounded(self):
        base = datetime(2026, 10, 9, 8, 0)
        for i in range(30):
            self.fs.save_workflow(self.WorkflowRecord(workflow_id=f"wf{i:02d}", goal="g", updated_at=base + timedelta(minutes=i)))
        self.client.docs_read = 0
        items = self.fs.list_workflows(limit=5)
        self.assertEqual([w.workflow_id for w in items], ["wf29", "wf28", "wf27", "wf26", "wf25"])
        self.assertEqual(self.client.docs_read, 5)
