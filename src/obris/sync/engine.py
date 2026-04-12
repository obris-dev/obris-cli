"""Bidirectional sync engine.

Syncs knowledge items from an Obris topic to a local directory.
State is keyed by knowledge_id — filenames are mutable labels,
the remote item's PK is the stable anchor.

The engine only manages files it tracks. Untracked local files
are invisible to sync. Adding files is an explicit action via
add_file(). Relinking after a local rename is via link_file().
"""

from pathlib import Path

import click

from obris.api.topics import iter_knowledge

from .constants import CONFLICT, PULLED, PUSHED
from .io import pull_item, push_file
from .mapping import (
    compute_filename,
    conflict_filename,
    hash_bytes,
    hash_file,
    now_iso,
    parse_timestamp,
    unique_filename,
)
from .models import RemoteItem
from .state import SyncState


def run_sync(topic_id, sync_dir, *, state=None, item_ids=None, dry_run=False):
    """Run a sync cycle. Returns (pulled, pushed, conflicts, errors).

    If item_ids is given, only those items are synced (pulled if new,
    synced if tracked). Other tracked items and remote items are skipped.
    If item_ids is None, all tracked items are synced and all new remote
    items are pulled.

    If dry_run is True, reports what would happen without modifying
    any files, remote state, or sync state.
    """
    sync_dir = Path(sync_dir)
    if not dry_run:
        sync_dir.mkdir(parents=True, exist_ok=True)

    if state is None:
        state = SyncState.load(topic_id, sync_dir)
    if not state:
        state = SyncState(topic_id, sync_dir)

    filter_ids = set(item_ids) if item_ids else None
    pulled, pushed, conflicts, errors = 0, 0, 0, 0

    # Stream remote items page by page. For each item we either sync
    # it against its tracked entry or pull it as new. After the stream
    # is exhausted, any tracked items we didn't see were deleted remotely.
    seen_ids = set()

    for raw in iter_knowledge(topic_id):
        item = RemoteItem.from_api(raw)
        seen_ids.add(item.id)

        # When filtering, skip items not in the requested set.
        if filter_ids and item.id not in filter_ids:
            continue

        if state.is_tracked(item.id):
            if not item.is_ready:
                continue  # processing — skip, don't untrack

            entry = state.get(item.id)
            try:
                result = _sync_tracked_item(topic_id, item, entry, state, sync_dir, dry_run=dry_run)
                if result == PUSHED:
                    pushed += 1
                elif result == PULLED:
                    pulled += 1
                elif result == CONFLICT:
                    conflicts += 1
            except Exception as e:
                click.echo(f"  Error syncing {entry.filename}: {type(e).__name__}: {e}", err=True)
                errors += 1
        else:
            if not item.is_ready:
                continue

            original_name = compute_filename(item)
            if not original_name:
                continue
            filename = unique_filename(sync_dir, original_name)
            renamed = filename != original_name

            if dry_run:
                msg = f"  Would pull {filename} (new)"
                if renamed:
                    msg += f" (renamed from {original_name}, file already exists)"
                click.echo(msg)
                pulled += 1
                continue

            try:
                new_hash = _safe_pull(item, sync_dir, filename)
                state.track(item.id, filename, new_hash, item.best_timestamp or now_iso())
                if renamed:
                    click.echo(f"  Pulled {filename} (new, {original_name} already exists)")
                else:
                    click.echo(f"  Pulled {filename} (new)")
                pulled += 1
            except Exception as e:
                click.echo(f"  Error pulling {filename}: {type(e).__name__}: {e}", err=True)
                errors += 1

    # Tracked items we never saw in the stream were deleted remotely.
    # Only applies when not filtering (filtering skips items intentionally).
    if not filter_ids:
        for kid in state.tracked_ids() - seen_ids:
            entry = state.get(kid)
            if dry_run:
                click.echo(f"  Would untrack {entry.filename} (remote deleted)")
            else:
                click.echo(f"  Remote deleted: {entry.filename} (local file kept)")
                state.untrack(kid)

    # Report any filtered item IDs that weren't found in the topic.
    if filter_ids:
        for kid in filter_ids - seen_ids:
            click.echo(f"  Item {kid} not found in topic", err=True)
            errors += 1

    if not dry_run:
        state.save()

    return pulled, pushed, conflicts, errors


# ---------------------------------------------------------------------------
# Per-item sync logic
# ---------------------------------------------------------------------------


def _sync_tracked_item(topic_id, item, entry, state, sync_dir, *, dry_run=False):
    """Sync a single tracked item. Returns PUSHED, PULLED, CONFLICT, or None."""
    filename = entry.filename
    local_hash = _hash_if_exists(sync_dir / filename)

    if local_hash is None:
        remote_name = item.title or filename
        if dry_run:
            click.echo(f"  Would untrack {filename} (file missing)")
        else:
            click.echo(f'  Missing: {filename} (was synced to "{remote_name}")')
            click.echo("    This file will no longer sync with its remote item.")
            click.echo(f"    To relink after a rename: obris sync link <new-filename> -i {item.id}")
            state.untrack(item.id)
        return None

    # -- Detect content changes --
    local_changed = local_hash != entry.local_hash

    # Remote is considered changed if its updated_at is newer than
    # the timestamp we recorded on the last successful sync.
    remote_changed = bool(item.updated_at) and parse_timestamp(item.updated_at) > parse_timestamp(entry.last_synced_at)

    # -- Apply content changes --
    if local_changed and remote_changed:
        if dry_run:
            click.echo(f"  Would conflict: {filename} (remote would win, local saved as conflict)")
            return CONFLICT

        conflict_name = unique_filename(sync_dir, conflict_filename(filename))
        original = sync_dir / filename
        backup = sync_dir / conflict_name
        original.rename(backup)
        try:
            new_hash = _safe_pull(item, sync_dir, filename)
        except Exception:
            try:
                backup.rename(original)
            except OSError:
                click.echo(f"  Warning: could not restore {filename}, your copy is at {conflict_name}", err=True)
            raise
        state.track(item.id, filename, new_hash, item.updated_at or now_iso())
        click.echo(f"  Conflict: {filename} \u2014 remote kept, local saved as {conflict_name}")
        return CONFLICT

    if local_changed:
        if dry_run:
            click.echo(f"  Would push {filename}")
            return PUSHED

        result = push_file(topic_id, item.id, sync_dir / filename, item)
        synced_at = result.get("updated_at") or now_iso()
        state.track(item.id, filename, local_hash, synced_at, pushed_hash=local_hash)
        click.echo(f"  Pushed {filename}")
        return PUSHED

    if remote_changed:
        # Check if the remote content actually changed, or if the server
        # just bumped updated_at (e.g. async processing after our push).
        if entry.pushed_hash and local_hash == entry.pushed_hash:
            # We pushed this content and haven't edited since. The server's
            # updated_at advanced from async processing, not a real change.
            state.track(item.id, filename, local_hash, item.updated_at or now_iso())
            return None

        # For text items with inline content, hash without downloading.
        if item.content:
            remote_hash = hash_bytes(item.content)
            if remote_hash == local_hash:
                state.track(item.id, filename, local_hash, item.updated_at or now_iso())
                return None

        if dry_run:
            click.echo(f"  Would pull {filename}")
            return PULLED

        new_hash = _safe_pull(item, sync_dir, filename)
        if new_hash == local_hash:
            # Content identical — just update the timestamp baseline.
            state.track(item.id, filename, local_hash, item.updated_at or now_iso())
            return None
        state.track(item.id, filename, new_hash, item.updated_at or now_iso())
        click.echo(f"  Pulled {filename}")
        return PULLED

    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_pull(item, sync_dir, filename):
    """Pull to a temp file, then atomic rename. Cleans up on failure."""
    dest = sync_dir / filename
    tmp = sync_dir / f".{filename}.obris-tmp"
    try:
        new_hash = pull_item(item, tmp)
        tmp.rename(dest)
        return new_hash
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _hash_if_exists(filepath):
    """Hash a file if it exists, return None otherwise."""
    if Path(filepath).exists():
        return hash_file(filepath)
    return None
