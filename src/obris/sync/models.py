"""Data transfer objects for sync."""

from dataclasses import dataclass

from .constants import STATUS_READY


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
    pushed_hash: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "TrackedItem":
        return cls(
            filename=data["filename"],
            local_hash=data["local_hash"],
            last_synced_at=data["last_synced_at"],
            pushed_hash=data.get("pushed_hash", ""),
        )

    def to_dict(self) -> dict:
        d = {
            "filename": self.filename,
            "local_hash": self.local_hash,
            "last_synced_at": self.last_synced_at,
        }
        if self.pushed_hash:
            d["pushed_hash"] = self.pushed_hash
        return d
