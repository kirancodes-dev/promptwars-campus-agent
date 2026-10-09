from datetime import datetime
from typing import Any
import uuid

try:
    from models.agent import Note
    from services.identity import current_user_id
    from services.persistence import (
        DEFAULT_USER_ID,
        EntityNotFoundError,
        get_persistence,
    )
except ImportError:
    from backend.models.agent import Note
    from backend.services.identity import current_user_id
    from backend.services.persistence import (
        DEFAULT_USER_ID,
        EntityNotFoundError,
        get_persistence,
    )


class NoteNotFoundError(KeyError):
    """Raised when a note ID is not found."""
    pass


class _NoteDictProxy(dict):
    """Transparent dict proxy exposing notes from active persistence for backward-compatibility."""

    def __getitem__(self, key: str) -> Note:
        note = get_persistence().get_note(key, user_id=current_user_id())
        if note is None:
            raise KeyError(key)
        return note

    def __setitem__(self, key: str, value: Note) -> None:
        get_persistence().create_note(value, user_id=current_user_id())

    def __delitem__(self, key: str) -> None:
        try:
            get_persistence().delete_note(key, user_id=current_user_id())
        except EntityNotFoundError:
            raise KeyError(key)

    def __contains__(self, key: Any) -> bool:
        if not isinstance(key, str):
            return False
        return get_persistence().get_note(key, user_id=current_user_id()) is not None

    def __len__(self) -> int:
        return len(get_persistence().get_notes(user_id=current_user_id()))

    def __iter__(self):
        return iter(n.id for n in get_persistence().get_notes(user_id=current_user_id()))

    def values(self):
        return get_persistence().get_notes(user_id=current_user_id())

    def keys(self):
        return [n.id for n in get_persistence().get_notes(user_id=current_user_id())]

    def items(self):
        return [(n.id, n) for n in get_persistence().get_notes(user_id=current_user_id())]

    def get(self, key: str, default: Any = None) -> Any:
        note = get_persistence().get_note(key, user_id=current_user_id())
        return note if note is not None else default

    def clear(self) -> None:
        get_persistence().clear_notes(user_id=current_user_id())


# In-memory proxy exposing active persistence layer
_notes: dict[str, Note] = _NoteDictProxy()


def clear_notes() -> None:
    """Clear all notes from active persistence storage."""
    get_persistence().clear_notes(user_id=current_user_id())


def create_note(
    title: str,
    content: str,
    category: str = "general",
) -> Note:
    """Create a new note with timestamps and store it in active persistence."""
    note_id = f"note_{uuid.uuid4().hex[:8]}"
    now = datetime.now()
    note = Note(
        id=note_id,
        title=title,
        content=content,
        category=category,
        created_at=now,
        updated_at=now,
    )
    return get_persistence().create_note(note, user_id=current_user_id())


def get_notes(category: str | None = None) -> list[Note]:
    """Retrieve all notes from active persistence, optionally filtered by category."""
    return get_persistence().get_notes(category=category, user_id=current_user_id())


def get_note(note_id: str) -> Note:
    """Retrieve a single note by ID or raise NoteNotFoundError."""
    note = get_persistence().get_note(note_id, user_id=current_user_id())
    if note is None:
        raise NoteNotFoundError(f"Note with ID '{note_id}' not found.")
    return note


def update_note(
    note_id: str,
    title: str | None = None,
    content: str | None = None,
    category: str | None = None,
) -> Note:
    """Update a note by ID, updating its updated_at timestamp."""
    existing = get_persistence().get_note(note_id, user_id=current_user_id())
    if existing is None:
        raise NoteNotFoundError(f"Note with ID '{note_id}' not found.")

    updates: dict[str, Any] = {}
    if title is not None:
        updates["title"] = title
    if content is not None:
        updates["content"] = content
    if category is not None:
        updates["category"] = category

    try:
        return get_persistence().update_note(note_id, updates, user_id=current_user_id())
    except EntityNotFoundError:
        raise NoteNotFoundError(f"Note with ID '{note_id}' not found.")


def delete_note(note_id: str) -> dict[str, Any]:
    """Delete a note by ID. Raises NoteNotFoundError if not found."""
    try:
        get_persistence().delete_note(note_id, user_id=current_user_id())
        return {"success": True, "note_id": note_id}
    except EntityNotFoundError:
        raise NoteNotFoundError(f"Note with ID '{note_id}' not found.")


def search_notes(query: str) -> list[Note]:
    """Search notes where query matches title or content (case-insensitive)."""
    return get_persistence().search_notes(query=query, user_id=current_user_id())
