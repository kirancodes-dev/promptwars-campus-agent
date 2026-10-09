from datetime import datetime
import os
import sys
import time
import unittest

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models.agent import Note
from tools.notes import (
    NoteNotFoundError,
    clear_notes,
    create_note,
    delete_note,
    get_notes,
    search_notes,
    update_note,
)


class TestNotesManagement(unittest.TestCase):
    def setUp(self):
        clear_notes()

    def tearDown(self):
        clear_notes()

    def test_create_note(self):
        """1. Creating a note."""
        note = create_note(
            title="Lecture Notes",
            content="Summary of Operating Systems lecture",
            category="academics",
        )
        self.assertIsInstance(note, Note)
        self.assertTrue(note.id.startswith("note_"))
        self.assertEqual(note.title, "Lecture Notes")
        self.assertEqual(note.content, "Summary of Operating Systems lecture")
        self.assertEqual(note.category, "academics")

    def test_get_all_notes(self):
        """2. Getting all notes."""
        create_note("Note 1", "Content 1", "general")
        create_note("Note 2", "Content 2", "general")
        notes = get_notes()
        self.assertEqual(len(notes), 2)

    def test_filter_by_category(self):
        """3. Filtering by category."""
        n1 = create_note("Study Guide", "Math 101", "academics")
        create_note("Groceries", "Eggs and milk", "personal")

        academic_notes = get_notes(category="academics")
        self.assertEqual(len(academic_notes), 1)
        self.assertEqual(academic_notes[0].id, n1.id)

    def test_update_note(self):
        """4. Updating a note."""
        note = create_note("Old Title", "Old Content", "general")
        updated = update_note(
            note_id=note.id,
            title="New Title",
            content="New Content",
            category="archived",
        )
        self.assertEqual(updated.id, note.id)
        self.assertEqual(updated.title, "New Title")
        self.assertEqual(updated.content, "New Content")
        self.assertEqual(updated.category, "archived")

    def test_delete_note(self):
        """5. Deleting a note."""
        note = create_note("Temp Note", "Will be deleted")
        result = delete_note(note.id)
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("note_id"), note.id)
        self.assertEqual(len(get_notes()), 0)

    def test_search_notes_by_title(self):
        """6. Searching notes by title."""
        n1 = create_note("Quantum Mechanics", "Physics intro", "science")
        create_note("Biology 101", "Cell structure", "science")

        results = search_notes("quantum")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, n1.id)

    def test_search_notes_by_content(self):
        """7. Searching notes by content."""
        create_note("Shopping List", "Apples and bread", "errands")
        n2 = create_note("Dorm Tasks", "Clean the kitchen counter", "chores")

        results = search_notes("counter")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, n2.id)

    def test_handling_invalid_note_id(self):
        """8. Handling an invalid note ID."""
        with self.assertRaises(NoteNotFoundError):
            update_note("nonexistent_id", title="New Title")

        with self.assertRaises(NoteNotFoundError):
            delete_note("nonexistent_id")

    def test_confirming_timestamps_exist(self):
        """9. Confirming timestamps exist."""
        note = create_note("Timestamp Test", "Checking datetime fields")
        self.assertIsInstance(note.created_at, datetime)
        self.assertIsInstance(note.updated_at, datetime)

    def test_confirming_updated_at_changes_after_update(self):
        """10. Confirming updated_at changes after an update."""
        note = create_note("Initial Note", "Initial Content")
        initial_updated_at = note.updated_at

        # Sleep briefly to ensure time difference
        time.sleep(0.01)

        updated = update_note(note.id, content="Updated Content")
        self.assertGreater(updated.updated_at, initial_updated_at)


if __name__ == "__main__":
    unittest.main()
