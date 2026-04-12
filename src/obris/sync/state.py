"""Sync state persistence and manipulation.

State is stored under ~/.obris/sync/, one file per topic+path pairing.
State is keyed by knowledge_id (the remote item's primary key), not
by filename. This means renames on either side are metadata updates,
not create+delete cycles.

Multiple topics can sync to the same directory. Each topic's state
file is independent — a local file can be tracked by several topics.
"""

import hashlib
import json
from pathlib import Path

from obris.config import CONFIG_DIR

from .mapping import now_iso
from .models import TrackedItem

SYNC_DIR = CONFIG_DIR / "sync"


def _state_key(topic_id, local_path):
    """Deterministic short hash for a (topic_id, local_path) pair."""
    raw = f"{topic_id}:{Path(local_path).resolve()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _state_path(topic_id, local_path):
    return SYNC_DIR / f"{_state_key(topic_id, local_path)}.json"


def _read(path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise SystemExit(f"Corrupted sync state file: {path}\nDelete it to start fresh, or restore from backup.") from e
    except OSError as e:
        raise SystemExit(f"Cannot read sync state {path}: {e}") from e


class SyncState:
    """Manages the sync state for a single topic+path pairing."""

    def __init__(self, topic_id, local_path, data=None):
        self.topic_id = topic_id
        self.local_path = str(Path(local_path).resolve())
        raw = data.get("items", {}) if data else {}
        self._items = {kid: TrackedItem.from_dict(entry) for kid, entry in raw.items()}

    @classmethod
    def load(cls, topic_id, local_path):
        """Load from disk. Returns None if not found or corrupted."""
        data = _read(_state_path(topic_id, local_path))
        if not data:
            return None
        return cls(topic_id, local_path, data)

    @classmethod
    def find_all_for_path(cls, local_path):
        """Find all states for the given local path.

        Returns list of (SyncState, topic_id) tuples.
        """
        resolved = str(Path(local_path).resolve())
        if not SYNC_DIR.exists():
            return []
        results = []
        for f in SYNC_DIR.glob("*.json"):
            data = _read(f)
            if data and data.get("local_path") == resolved:
                topic_id = data.get("topic_id")
                results.append((cls(topic_id, local_path, data), topic_id))
        return results

    def save(self):
        SYNC_DIR.mkdir(parents=True, exist_ok=True)
        path = _state_path(self.topic_id, self.local_path)
        tmp = path.with_suffix(".tmp")
        data = {
            "topic_id": self.topic_id,
            "local_path": self.local_path,
            "last_sync": now_iso(),
            "items": {kid: item.to_dict() for kid, item in self._items.items()},
        }
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        tmp.rename(path)

    # -- Item tracking --

    @property
    def items(self):
        return self._items

    def get(self, knowledge_id) -> TrackedItem | None:
        """Get the tracked entry for a knowledge_id, or None."""
        return self._items.get(knowledge_id)

    def track(self, knowledge_id, filename, local_hash, last_synced_at, *, pushed_hash=""):
        """Add or update a tracked item."""
        self._items[knowledge_id] = TrackedItem(
            filename=filename,
            local_hash=local_hash,
            last_synced_at=last_synced_at,
            pushed_hash=pushed_hash,
        )

    def find_by_filename(self, filename):
        """Find a tracked item by local filename. Returns (knowledge_id, entry) or (None, None)."""
        for kid, entry in self._items.items():
            if entry.filename == filename:
                return kid, entry
        return None, None

    def untrack(self, knowledge_id):
        """Remove an item from tracking."""
        self._items.pop(knowledge_id, None)

    def is_tracked(self, knowledge_id):
        return knowledge_id in self._items

    def tracked_ids(self):
        return set(self._items.keys())
