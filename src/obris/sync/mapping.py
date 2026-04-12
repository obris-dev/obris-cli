"""Filename computation, hashing, and file utilities for sync."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

CONFLICT_MARKER = "(conflict "
HASH_CHUNK_SIZE = 64 * 1024


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def hash_file(filepath):
    """SHA-256 hash of a file's contents, streamed in chunks."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(HASH_CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def hash_bytes(data):
    """SHA-256 hash of in-memory bytes or string."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------


def read_if_text(filepath):
    """Read a file and return (content, is_text).

    Returns the text content if the file is valid UTF-8,
    or (None, False) if it's binary. Single pass.
    """
    raw = Path(filepath).read_bytes()
    try:
        return raw.decode("utf-8"), True
    except UnicodeDecodeError:
        return None, False


def compute_filename(item):
    """Determine the local filename for a RemoteItem, or None if unpullable.

    Uses file_name for file-based items, title for text items.
    """
    if item.file_name:
        return sanitize_name(item.file_name)

    if not item.content and not item.file_url:
        return None

    title = sanitize_name(item.title or "untitled")
    if "." not in title:
        title += ".md"
    return title


def sanitize_name(name):
    """Strip path components from a remote name to prevent path traversal."""
    name = Path(name).name
    if not name or name in (".", ".."):
        name = "untitled"
    return name


def conflict_filename(filename, date=None):
    """Generate a conflict filename preserving the original extension."""
    if date is None:
        date = datetime.now(UTC).strftime("%Y-%m-%d")
    stem, _, ext = filename.rpartition(".")
    if not stem:
        # Dotfile (.gitignore) or no extension — append to the whole name.
        return f"{filename} (conflict {date})"
    return f"{stem} (conflict {date}).{ext}"


def unique_filename(sync_dir, filename, exclude=None):
    """Return filename if available, otherwise append (2), (3), etc.

    Follows macOS/Windows convention: CLAUDE.md → CLAUDE (2).md.
    If exclude is given, that name is treated as available.
    """
    path = Path(sync_dir) / filename
    if not path.exists() or filename == exclude:
        return filename
    stem, _, ext = filename.rpartition(".")
    if not stem:
        stem, ext = filename, ""
    for counter in range(2, 1002):
        candidate = f"{stem} ({counter}).{ext}" if ext else f"{stem} ({counter})"
        if not (Path(sync_dir) / candidate).exists() or candidate == exclude:
            return candidate
    raise RuntimeError(f"Could not find available filename for {filename}")


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------


def parse_timestamp(ts):
    """Parse an ISO 8601 timestamp to a datetime for safe comparison."""
    if not ts:
        raise ValueError("Empty timestamp")
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def now_iso():
    return datetime.now(UTC).isoformat()
