"""Data transfer objects for sync."""

from dataclasses import dataclass

from .constants import STATUS_READY


@dataclass(frozen=True)
class RemoteTopic:
    """A topic from the Obris API.

    Mirrors the pattern used by ``RemoteItem``: the API client wraps
    raw dicts here so callers can do attribute access (and IDE
    completion) instead of ``topic.get("field", default)`` sprinkled
    across the codebase. The ``from_api`` classmethod normalizes a few
    edge cases — an empty-string ``parent_id`` collapses to ``None``
    (same contract the server enforces), and missing optional fields
    get typed defaults.

    Used by both single-topic fetches (``get_topic``) and bulk subtree
    fetches (``fetch_subtree``). The subtree endpoint only returns
    ``id`` / ``parent_id`` / ``name``; unspecified fields fall back to
    their defaults here.
    """

    id: str
    name: str
    parent_id: str | None
    item_count: int = 0
    description: str = ""
    is_system: bool = False
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_api(cls, data: dict) -> "RemoteTopic":
        parent_id = data.get("parent_id")
        return cls(
            id=data["id"],
            name=data.get("name") or "untitled",
            parent_id=parent_id or None,
            item_count=data.get("item_count") or 0,
            description=data.get("description") or "",
            is_system=bool(data.get("is_system")),
            created_at=data.get("created_at") or "",
            updated_at=data.get("updated_at") or "",
        )

    @property
    def is_root(self) -> bool:
        return not self.parent_id


@dataclass(frozen=True)
class RemoteItem:
    """A knowledge item from the Obris API."""

    id: str
    title: str
    status: str
    content: str
    file_url: str | None
    file_name: str
    source_type: str
    updated_at: str
    created_at: str
    topic_id: str
    revision: int = 0
    content_hash: str = ""

    @classmethod
    def from_api(cls, data: dict) -> "RemoteItem":
        return cls(
            id=data["id"],
            title=data.get("title") or "untitled",
            status=data.get("status") or "",
            content=data.get("content") or "",
            file_url=data.get("file_url"),
            file_name=data.get("file_name") or "",
            source_type=data.get("source_type") or "",
            updated_at=data.get("updated_at") or "",
            created_at=data.get("created_at") or "",
            topic_id=data.get("topic_id") or "",
            revision=int(data.get("revision") or 0),
            content_hash=data.get("content_hash") or "",
        )

    @classmethod
    def from_manifest_entry(cls, item_id: str, entry: dict) -> "RemoteItem":
        """Build a metadata-only ``RemoteItem`` from a sync-state manifest row.

        The manifest deliberately omits ``content`` / ``file_url`` to keep
        the response small — the engine only fetches those when it
        actually needs to download the item. Status is set to READY
        because the manifest excludes non-READY items.
        """
        return cls(
            id=item_id,
            title=entry.get("filename") or "untitled",
            status=STATUS_READY,
            content="",
            file_url=None,
            file_name=entry.get("filename") or "",
            source_type=entry.get("source_type") or "",
            updated_at="",
            created_at="",
            topic_id=entry.get("topic_id") or "",
            revision=int(entry.get("revision") or 0),
            content_hash=entry.get("content_hash") or "",
        )

    @property
    def is_ready(self):
        return self.status == STATUS_READY

    @property
    def is_file_source(self):
        return self.source_type == "file"

    @property
    def best_timestamp(self):
        return self.updated_at or self.created_at


@dataclass
class TrackedItem:
    """A locally tracked item from sync state.

    ``last_seen_revision`` is the OCC token sent as ``If-Match`` on writes;
    the server bumps revision on every save so equality with the remote
    means "no remote change since last sync."

    ``last_seen_content_hash`` is the canonical sha256 of the bytes the
    server stored at that revision. Used to detect local edits without a
    server round-trip and to short-circuit no-op pulls when the remote
    bumped its revision but content matches what we already have on disk.

    ``mtime_at_last_sync`` is the local file's stat().st_mtime at the time
    of the last successful sync. Lets the engine skip rehashing when the
    file hasn't been touched.
    """

    filename: str
    topic_id: str = ""
    last_seen_revision: int = 0
    last_seen_content_hash: str = ""
    mtime_at_last_sync: float = 0.0

    @classmethod
    def from_dict(cls, data: dict) -> "TrackedItem":
        return cls(
            filename=data["filename"],
            topic_id=data.get("topic_id", ""),
            last_seen_revision=int(data.get("last_seen_revision") or 0),
            last_seen_content_hash=data.get("last_seen_content_hash", ""),
            mtime_at_last_sync=float(data.get("mtime_at_last_sync") or 0.0),
        )

    def to_dict(self) -> dict:
        d = {"filename": self.filename}
        if self.topic_id:
            d["topic_id"] = self.topic_id
        if self.last_seen_revision:
            d["last_seen_revision"] = self.last_seen_revision
        if self.last_seen_content_hash:
            d["last_seen_content_hash"] = self.last_seen_content_hash
        if self.mtime_at_last_sync:
            d["mtime_at_last_sync"] = self.mtime_at_last_sync
        return d
