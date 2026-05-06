"""Local-directory scanning + bulk add for initial sync.

Two responsibilities:

1. ``find_untracked`` walks ``sync_dir`` and categorizes every file
   it sees into one of: tracked (already in state), excluded
   (matches ExclusionMatcher), symlink (skipped), or untracked
   (the new files the user might want to upload).

2. ``add_all`` iterates the untracked list and uploads each file,
   creating subtopics on the server to mirror local subdir
   structure when needed. Subtopic creation is the create direction
   of the "auto-mirror local dirs" question — safe because additive.
   Deletion direction (rm -rf foo/ → delete remote subtopic) stays
   deferred. Inline-text items are batched into a single
   ``knowledge/bulk-add`` request; binary files and oversized text
   fall through to per-item upload.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import click

from obris.api.knowledge import knowledge_add, knowledge_bulk_add
from obris.api.topics import create_topic
from obris.sync.constants import MAX_INLINE_TEXT_SIZE
from obris.sync.exclusions import ExclusionMatcher
from obris.sync.mapping import hash_file, read_if_text
from obris.utils.upload import upload_file


@dataclass
class ScanResult:
    """Categorized output of a sync_dir walk.

    All paths are POSIX-style relative to sync_dir.
    """

    untracked: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    symlinks: list[tuple[str, str]] = field(default_factory=list)


def find_untracked(sync_dir: Path, states) -> ScanResult:
    """Walk ``sync_dir`` and bucket every file into ScanResult.

    ``states`` is the list of ``(SyncState, topic_id)`` tuples for
    this dir — used to filter out files already tracked under any of
    them. Excludes are evaluated per-state; if multiple states overlap
    a path, the union of their excludes wins.
    """
    sync_dir = Path(sync_dir)
    matchers = [(state, ExclusionMatcher(sync_dir, state_excludes=state.exclude_patterns)) for state, _ in states]
    tracked_names = set()
    for state, _ in states:
        for entry in state.items.values():
            rel_dir = state.get_topic_dir(entry.topic_id) if entry.topic_id else ""
            tracked_names.add(_join(rel_dir or "", entry.filename))

    result = ScanResult()
    for path in sorted(sync_dir.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(sync_dir).as_posix()
        if path.is_symlink():
            try:
                target = str(path.resolve())
            except OSError:
                target = "<unresolvable>"
            result.symlinks.append((rel, target))
            continue
        if any(matcher.excludes(rel) for _, matcher in matchers):
            result.excluded.append(rel)
            continue
        if rel in tracked_names:
            continue
        result.untracked.append(rel)
    return result


def add_all(
    state,
    root_topic_id: str,
    sync_dir: Path,
    untracked: list[str],
    *,
    allow_subtopics: bool = True,
) -> dict:
    """Bulk-add every path in ``untracked`` under its matching subtopic.

    Returns ``{added, skipped_subdir, errors}`` counts. When
    ``allow_subtopics`` is False, files in subdirs are skipped
    instead of triggering subtopic creation — the safety net for
    users who explicitly opted out via ``--no-subtopics``.

    Inline-text items under ``MAX_INLINE_TEXT_SIZE`` are collected
    into one ``knowledge/bulk-add`` POST; binary files and oversized
    text fall back to per-item create / upload. The state is
    persisted once at the end with every successful row, so a
    crash mid-walk leaves a consistent partial state instead of a
    half-written file.
    """
    sync_dir = Path(sync_dir)
    # Cache: rel_dir (POSIX, "" for root) -> topic_id. Seed from the
    # state's topic_dirs so we reuse subtopics that already exist
    # rather than creating duplicates.
    cache: dict[str, str] = {"": root_topic_id}
    for tid, rel in state.topic_dirs.items():
        if tid != root_topic_id and rel:
            cache[rel] = tid

    counts = {"added": 0, "skipped_subdir": 0, "errors": 0}
    bulk_batch: list[dict] = []
    deferred: list[tuple[str, Path, str]] = []

    for rel in untracked:
        path = sync_dir / rel
        rel_dir = str(PurePosixPath(rel).parent)
        if rel_dir == ".":
            rel_dir = ""
        if rel_dir and not allow_subtopics:
            counts["skipped_subdir"] += 1
            continue
        try:
            target_topic_id = _ensure_subtopic_path(rel_dir, root_topic_id, cache)
        except Exception as e:
            click.echo(f"  Error preparing topic for {rel}: {type(e).__name__}: {e}", err=True)
            counts["errors"] += 1
            continue

        try:
            content, is_text = read_if_text(path)
        except Exception as e:
            click.echo(f"  Error reading {rel}: {type(e).__name__}: {e}", err=True)
            counts["errors"] += 1
            continue

        if is_text and len(content.encode("utf-8")) <= MAX_INLINE_TEXT_SIZE:
            bulk_batch.append(
                {
                    "rel": rel,
                    "path": path,
                    "topic_id": target_topic_id,
                    "content": content,
                    "mtime": path.stat().st_mtime,
                    "file_hash": hash_file(path),
                }
            )
        else:
            deferred.append((target_topic_id, path, rel))

    if bulk_batch:
        _send_bulk_batch(state, root_topic_id, bulk_batch, counts)

    for target_topic_id, path, rel in deferred:
        try:
            _add_one_per_item(state, target_topic_id, path)
            counts["added"] += 1
        except Exception as e:
            click.echo(f"  Error adding {rel}: {type(e).__name__}: {e}", err=True)
            counts["errors"] += 1

    if counts["added"]:
        # Persist the rel_dir → topic_id mappings we discovered or
        # created so subsequent syncs don't try to recreate the same
        # subtopics. The cache is canonical here — we either reused
        # existing entries or just created the topic.
        for rel_dir, tid in cache.items():
            if rel_dir and tid != root_topic_id:
                state.set_topic_dir(tid, rel_dir)
        state.save()

    return counts


def _send_bulk_batch(state, root_topic_id, batch, counts):
    """Send one ``knowledge/bulk-add`` request and merge the response into state.

    Per-row errors come back keyed by their input index in
    ``response.errors``; ``response.created`` lists successes in
    request order, skipping the rows that errored. We zip created
    rows back to their batch entries by walking both lists in order.
    """
    payload = [
        {
            "topic_id": entry["topic_id"],
            "content": entry["content"],
            "title": entry["path"].name,
            "file_name": entry["path"].name,
            "source_type": "cli",
        }
        for entry in batch
    ]
    try:
        resp = knowledge_bulk_add(root_topic_id, payload)
    except Exception as e:
        click.echo(f"  Bulk-add failed: {type(e).__name__}: {e}", err=True)
        counts["errors"] += len(batch)
        return

    err_by_index = {err.get("index"): err for err in resp.get("errors") or [] if err.get("index") is not None}
    created = resp.get("created") or []
    create_pos = 0
    for i, entry in enumerate(batch):
        if i in err_by_index:
            err = err_by_index[i]
            click.echo(f"  Error adding {entry['rel']}: {err.get('error') or err}", err=True)
            counts["errors"] += 1
            continue
        if create_pos >= len(created):
            click.echo(f"  Error adding {entry['rel']}: response missing row", err=True)
            counts["errors"] += 1
            continue
        row = created[create_pos]
        create_pos += 1
        state.track(
            row["id"],
            entry["path"].name,
            topic_id=row.get("topic_id") or entry["topic_id"],
            last_seen_revision=int(row.get("revision") or 0),
            last_seen_content_hash=row.get("content_hash") or entry["file_hash"],
            mtime_at_last_sync=entry["mtime"],
        )
        counts["added"] += 1


def _add_one_per_item(state, target_topic_id, filepath: Path):
    """Per-item create / upload for files that don't fit the bulk-add path.

    Updates ``state`` in place rather than going through
    ``commands.add_file`` — that helper loads and saves its own copy
    of state, which would clobber the in-memory state add_all is
    accumulating into.
    """
    content, is_text = read_if_text(filepath)
    use_inline = is_text and len(content.encode("utf-8")) <= MAX_INLINE_TEXT_SIZE
    if use_inline:
        result = knowledge_add(target_topic_id, filepath.name, content)
    else:
        result = upload_file(target_topic_id, filepath, filepath.name)
    file_hash = hash_file(filepath)
    state.track(
        result["id"],
        filepath.name,
        topic_id=target_topic_id,
        last_seen_revision=int(result.get("revision") or 0),
        last_seen_content_hash=result.get("content_hash") or file_hash,
        mtime_at_last_sync=filepath.stat().st_mtime,
    )


def _ensure_subtopic_path(rel_dir: str, root_topic_id: str, cache: dict[str, str]) -> str:
    """Walk segments under root, creating subtopics as needed.

    Each missing level triggers one ``create_topic(name, parent_id=…)``
    call. Cache entries are added incrementally so the next file
    under the same dir is a cache hit.
    """
    if rel_dir in cache:
        return cache[rel_dir]
    segments = [s for s in rel_dir.split("/") if s]
    parent_id = root_topic_id
    walked = ""
    for seg in segments:
        walked = f"{walked}/{seg}" if walked else seg
        if walked in cache:
            parent_id = cache[walked]
            continue
        topic = create_topic(seg, parent_id=parent_id)
        cache[walked] = topic.id
        parent_id = topic.id
    return parent_id


def _join(rel_dir: str, name: str) -> str:
    return f"{rel_dir}/{name}" if rel_dir else name
