"""Sync state persistence and manipulation.

State is stored under ~/.obris/sync/, one file per (root topic, local path).
State is keyed by knowledge_id (the remote item's primary key), not by
filename. Renames on either side are metadata updates, not create+delete.

Subtopic support: one state file per *root* topic covers the entire
subtree. topic_dirs maps topic_id -> relative directory (POSIX-style)
under local_path. The CLI only syncs root topics (parent_id = NULL);
child topics are not valid sync targets on their own.
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
    """Manages the sync state for a single (root topic, local path) pairing."""

    def __init__(self, topic_id, local_path, data=None):
        self.topic_id = topic_id
        self.local_path = str(Path(local_path).resolve())
        raw = data.get("items", {}) if data else {}
        self._items = {kid: TrackedItem.from_dict(entry) for kid, entry in raw.items()}
        self._topic_dirs = dict(data.get("topic_dirs", {})) if data else {}
        self._include_patterns = list(data.get("include_patterns", [])) if data else []
        self._exclude_patterns = list(data.get("exclude_patterns", [])) if data else []
        self._unlinked_ids = list(data.get("unlinked_ids", [])) if data else []
        self._conflicts = dict(data.get("conflicts", {})) if data else {}
        # Per-target ETag cache: topic_id -> root_hash from the last
        # successful sync-state response. Lets the next sync send
        # If-None-Match and short-circuit on 304 when the subtree
        # hasn't changed remotely.
        self._last_seen_root_hash = dict(data.get("last_seen_root_hash", {})) if data else {}

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
            "topic_dirs": self._topic_dirs,
            "include_patterns": self._include_patterns,
            "exclude_patterns": self._exclude_patterns,
            "unlinked_ids": self._unlinked_ids,
            "conflicts": self._conflicts,
            "last_seen_root_hash": self._last_seen_root_hash,
            "items": {kid: item.to_dict() for kid, item in self._items.items()},
        }
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        tmp.rename(path)

    # -- Topic directory map --

    @property
    def topic_dirs(self) -> dict[str, str]:
        return self._topic_dirs

    def set_topic_dir(self, topic_id, relative_dir):
        self._topic_dirs[topic_id] = relative_dir

    def drop_topic_dir(self, topic_id):
        self._topic_dirs.pop(topic_id, None)

    def get_topic_dir(self, topic_id) -> str | None:
        return self._topic_dirs.get(topic_id)

    # -- Include patterns --

    @property
    def include_patterns(self) -> list[str]:
        return list(self._include_patterns)

    def set_include_patterns(self, patterns: list[str]):
        self._include_patterns = list(patterns)

    # -- Exclude patterns --

    @property
    def exclude_patterns(self) -> list[str]:
        return list(self._exclude_patterns)

    def add_excludes(self, patterns) -> list[str]:
        """Add patterns; return the subset that was actually new (idempotent)."""
        added = []
        for p in patterns:
            if p and p not in self._exclude_patterns:
                self._exclude_patterns.append(p)
                added.append(p)
        return added

    def remove_excludes(self, patterns) -> list[str]:
        """Remove patterns; return the subset that was actually present (idempotent)."""
        removed = []
        for p in patterns:
            if p in self._exclude_patterns:
                self._exclude_patterns.remove(p)
                removed.append(p)
        return removed

    # -- Item tracking --

    @property
    def items(self):
        return self._items

    def get(self, knowledge_id) -> TrackedItem | None:
        """Get the tracked entry for a knowledge_id, or None."""
        return self._items.get(knowledge_id)

    def track(
        self,
        knowledge_id,
        filename,
        *,
        topic_id="",
        last_seen_revision=0,
        last_seen_content_hash="",
        mtime_at_last_sync=0.0,
    ):
        """Add or update a tracked item.

        Clears any "do-not-auto-re-pull" marker for this id — re-tracking
        means the user wants the item synced again.
        """
        self._items[knowledge_id] = TrackedItem(
            filename=filename,
            topic_id=topic_id,
            last_seen_revision=last_seen_revision,
            last_seen_content_hash=last_seen_content_hash,
            mtime_at_last_sync=mtime_at_last_sync,
        )
        if knowledge_id in self._unlinked_ids:
            self._unlinked_ids.remove(knowledge_id)

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

    # -- Unlinked (do-not-auto-re-pull) markers --

    @property
    def unlinked_ids(self) -> list[str]:
        return list(self._unlinked_ids)

    def mark_unlinked(self, knowledge_id):
        """Record that ``knowledge_id`` should not be auto-re-pulled.

        Used by ``obris sync untrack`` so subsequent syncs don't yank
        the remote copy back down. Cleared automatically by ``track``.
        """
        if knowledge_id and knowledge_id not in self._unlinked_ids:
            self._unlinked_ids.append(knowledge_id)

    def is_unlinked(self, knowledge_id) -> bool:
        return knowledge_id in self._unlinked_ids

    # -- Conflict markers --

    @property
    def conflicts(self) -> dict[str, dict]:
        return {kid: dict(meta) for kid, meta in self._conflicts.items()}

    def mark_conflict(self, knowledge_id, *, detected_at, remote_updated_at, local_hash):
        """Record that ``knowledge_id`` is in conflict.

        Subsequent syncs skip the item for both push and pull until
        ``clear_conflict`` is called (typically by ``obris sync
        conflicts resolve``).
        """
        self._conflicts[knowledge_id] = {
            "detected_at": detected_at,
            "remote_updated_at": remote_updated_at,
            "local_hash_at_conflict": local_hash,
        }

    def clear_conflict(self, knowledge_id):
        self._conflicts.pop(knowledge_id, None)

    def get_conflict(self, knowledge_id) -> dict | None:
        meta = self._conflicts.get(knowledge_id)
        return dict(meta) if meta else None

    def is_conflicted(self, knowledge_id) -> bool:
        return knowledge_id in self._conflicts

    # -- Per-target root-hash cache (sync-state ETag) --

    def get_root_hash(self, topic_id) -> str | None:
        return self._last_seen_root_hash.get(topic_id)

    def set_root_hash(self, topic_id, root_hash):
        if root_hash:
            self._last_seen_root_hash[topic_id] = root_hash
        else:
            self._last_seen_root_hash.pop(topic_id, None)
