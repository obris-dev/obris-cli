"""Filename computation, hashing, and file utilities for sync."""

import hashlib
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

UTC = timezone.utc

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


def unique_filename(sync_dir, relative_dir, filename, exclude=None):
    """Return filename if available in sync_dir/relative_dir, otherwise append (2), (3), etc.

    Collisions are scoped to a single directory — two items in sibling
    topics can both be "notes.md" without colliding. Follows macOS/Windows
    convention: CLAUDE.md → CLAUDE (2).md.
    If exclude is given, that name is treated as available.
    """
    target_dir = Path(sync_dir) / relative_dir
    path = target_dir / filename
    if not path.exists() or filename == exclude:
        return filename
    stem, _, ext = filename.rpartition(".")
    if not stem:
        stem, ext = filename, ""
    for counter in range(2, 1002):
        candidate = f"{stem} ({counter}).{ext}" if ext else f"{stem} ({counter})"
        if not (target_dir / candidate).exists() or candidate == exclude:
            return candidate
    raise RuntimeError(f"Could not find available filename for {filename}")


# ---------------------------------------------------------------------------
# Topic path / slug helpers
# ---------------------------------------------------------------------------


_PATH_SEP_TRANSLATE = str.maketrans({"/": "-", "\\": "-"})


def slugify_topic_name(name: str) -> str:
    """Convert a topic name into a safe directory component.

    Translates path separators to dashes — actual traversal defense, not
    aesthetics — and bottoms out at "untitled" when the name leaves
    nothing safe to use (empty, ``.``, or ``..``). Otherwise the topic
    name passes through unchanged: leading dots, trailing dots, leading
    or trailing whitespace, unicode, case — all preserved.

    Why so minimal: if a topic was created with a particular name (via
    the CLI itself, the web app, or an MCP tool), that name *is* the
    user's intent. Stripping leading dots silently renames ``.claude/``
    to ``claude/`` on first sync; stripping trailing dots breaks
    ``foo./``; trimming whitespace breaks ``"  intentional  "``.
    Cross-platform pain (Windows-hostile trailing dots, APFS case
    folding) is addressed when it actually comes up, not pre-emptively
    at the cost of common AI-tool config dirs.
    """
    name = name or ""
    name = name.translate(_PATH_SEP_TRANSLATE)
    name = Path(name).name  # blocks `.` and leftover `/foo` traversal
    # ``Path("..").name`` keeps ``..`` verbatim (POSIX quirk: it's a
    # legal path component, just dangerous as a directory name).
    # Catch it explicitly so a topic named ``..`` doesn't materialize
    # as the parent directory at sync time.
    if name == "..":
        name = ""
    return name or "untitled"


def build_topic_dirs(
    subtree,
    root_topic_id: str,
) -> dict[str, str]:
    """Build {topic_id: relative_dir} from a flat subtree list.

    Accepts a list of ``RemoteTopic`` DTOs (preferred) or raw dicts;
    attribute access via ``getattr`` falls back to dict lookups so the
    old call sites keep working while we finish the migration.

    - Walks parent_id chains to construct each topic's path from the root.
    - Root topic maps to "" (sync_dir itself).
    - Slugifies each name with slugify_topic_name.
    - Resolves sibling slug collisions by appending (2), (3), ... so the
      same two topics always land in the same directory.
    - Raises TopicCycleError if the parent chain reaches the depth cap or
      revisits a topic (defense against bad server data).

    Returns an empty dict if the root isn't in the subtree.
    """
    by_id = {node.id: node for node in subtree}
    if root_topic_id not in by_id:
        return {}

    # Precompute each topic's ancestor name path, walking upward with a
    # visited set for cycle safety.
    depth_cap = 64
    topic_names: dict[str, list[str]] = {}
    for tid in by_id:
        segments: list[str] = []
        visited: set[str] = set()
        cur: str | None = tid
        while cur and cur != root_topic_id:
            if cur in visited:
                raise TopicCycleError(f"Cycle detected walking ancestors of topic {tid} at {cur}")
            visited.add(cur)
            if len(visited) > depth_cap:
                raise TopicCycleError(f"Ancestor chain for topic {tid} exceeded depth {depth_cap}")
            node = by_id.get(cur)
            if not node:
                break  # ancestor missing from subtree (shouldn't happen in a consistent tree)
            segments.append(node.name)
            cur = node.parent_id
        if cur != root_topic_id:
            # topic isn't under the root — skip (malformed subtree)
            topic_names[tid] = []
            continue
        topic_names[tid] = list(reversed(segments))

    # Assign directories. Walk in BFS order from the root so parents are
    # assigned before children — sibling collisions resolve against
    # already-chosen sibling paths.
    topic_dirs: dict[str, str] = {root_topic_id: ""}
    children: dict[str, list[str]] = {}
    for node in subtree:
        if node.parent_id:
            children.setdefault(node.parent_id, []).append(node.id)

    queue: list[str] = [root_topic_id]
    while queue:
        parent = queue.pop(0)
        parent_dir = topic_dirs[parent]
        # Track slugs chosen among this parent's children so we can dedupe.
        used: set[str] = set()
        # Sort children by id before iterating: two siblings that slugify
        # to the same name (e.g. "Notes" and "Notes ") must deterministically
        # get the same (2)-suffix assignment across runs, otherwise the
        # reconcile step in run.py would rename them on every sync. The
        # server already ORDER BYs id in the subtree CTE, but sorting here
        # too means the CLI's output doesn't depend on server row order.
        for child_id in sorted(children.get(parent, [])):
            node = by_id[child_id]
            slug = slugify_topic_name(node.name)
            candidate = slug
            counter = 2
            while candidate in used:
                candidate = f"{slug} ({counter})"
                counter += 1
                if counter > 1000:
                    raise RuntimeError(f"Could not find unique slug for topic {child_id}")
            used.add(candidate)
            child_rel = str(PurePosixPath(parent_dir) / candidate) if parent_dir else candidate
            topic_dirs[child_id] = child_rel
            queue.append(child_id)

    return topic_dirs


class TopicCycleError(Exception):
    """Raised when an ancestor walk detects a cycle or exceeds depth."""


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
