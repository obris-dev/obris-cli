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
    """A locally tracked item from sync state."""

    filename: str
    local_hash: str
    last_synced_at: str
    topic_id: str = ""
    pushed_hash: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "TrackedItem":
        return cls(
            filename=data["filename"],
            local_hash=data["local_hash"],
            last_synced_at=data["last_synced_at"],
            topic_id=data.get("topic_id", ""),
            pushed_hash=data.get("pushed_hash", ""),
        )

    def to_dict(self) -> dict:
        d = {
            "filename": self.filename,
            "local_hash": self.local_hash,
            "last_synced_at": self.last_synced_at,
        }
        if self.topic_id:
            d["topic_id"] = self.topic_id
        if self.pushed_hash:
            d["pushed_hash"] = self.pushed_hash
        return d
