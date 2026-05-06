"""Per-item sync logic for tracked knowledge items.

The public entry point is ``sync_tracked_item`` — the engine loop calls
it once per item after resolving the item's target relative directory.
"""

from __future__ import annotations

import time
from pathlib import Path

import click

# Defer push when the file was modified within this many seconds —
# treats sub-window edits as "still in progress" so we don't push
# half-saved content. 2s is enough to ride out a Save All, not so
# long that interactive workflows feel laggy.
_MTIME_STABILITY_WINDOW = 2.0

from obris.api.client import ConcurrentWriteError

from ..constants import CONFLICT, MISSING, PULLED, PUSHED
from ..io import pull_item, push_file
from ..mapping import hash_file, now_iso, unique_filename
from .subtree import display_path, safe_pull


def sync_tracked_item(topic_id, item, entry, state, sync_dir, desired_rel, *, dry_run=False):
    """Sync a single tracked item. Returns PUSHED, PULLED, CONFLICT, or None."""
    filename = entry.filename
    current_rel = state.get_topic_dir(entry.topic_id) if entry.topic_id else ""
    if current_rel is None:
        current_rel = ""

    # -- File-level move if the item's topic changed or was renamed --
    if current_rel != desired_rel:
        if dry_run:
            click.echo(f"  Would move {display_path(current_rel, filename)} -> {display_path(desired_rel, filename)}")
        else:
            src = sync_dir / current_rel / filename
            if src.exists():
                dst_dir = sync_dir / desired_rel
                dst_dir.mkdir(parents=True, exist_ok=True)
                new_name = unique_filename(sync_dir, desired_rel, filename)
                src.rename(dst_dir / new_name)
                old_display = display_path(current_rel, entry.filename)
                filename = new_name
                new_display = display_path(desired_rel, filename)
                click.echo(f"  Moved {old_display} -> {new_display}")
                # Persist the move immediately. Subsequent content-change
                # branches will overwrite this entry with a fresh hash +
                # revision if they run, but if none do (the body didn't
                # change and the server didn't bump revision) this is the
                # only write that reflects the new on-disk location.
                state.track(
                    item.id,
                    filename,
                    topic_id=item.topic_id,
                    last_seen_revision=entry.last_seen_revision,
                    last_seen_content_hash=entry.last_seen_content_hash,
                    mtime_at_last_sync=entry.mtime_at_last_sync,
                )
        current_rel = desired_rel

    local_path = sync_dir / current_rel / filename
    local_hash = _hash_if_exists(local_path)

    if local_hash is None:
        display = display_path(current_rel, filename)
        if dry_run:
            click.echo(f"  Would warn: {display} missing locally (knowledge_id {item.id})")
            return MISSING
        # Keep the state entry intact and don't pull in this pass. The
        # pull-as-new branch in run.py only fires for untracked ids, so
        # leaving the entry here means a deleted file doesn't silently
        # reappear next sync. Resolution requires explicit user action,
        # surfaced via copy-pasteable commands below.
        click.echo(f"  Missing locally: {display}  (knowledge_id {item.id})")
        click.echo("    Options:")
        click.echo(f"      obris sync link <new-path> -i {item.id}    # moved or renamed")
        click.echo(f"      obris sync untrack {item.id}               # keep both copies, stop syncing")
        click.echo(f"      obris knowledge delete {item.id}           # remove the remote item")
        return MISSING

    local_changed = bool(entry.last_seen_content_hash) and local_hash != entry.last_seen_content_hash
    remote_changed = item.revision > entry.last_seen_revision

    # When both sides diverged the push branch fires first; its
    # If-Match returns 412 and the existing ConcurrentWriteError
    # handler marks the item conflicted. The pull branch never sees
    # the both-changed case because we'd return CONFLICT before
    # reaching it.

    if local_changed:
        display = display_path(current_rel, filename)
        if dry_run:
            click.echo(f"  Would push {display}")
            return PUSHED

        # mtime-stability: if the file was modified less than 2 seconds
        # ago, treat it as mid-edit and defer to the next pass. Cheap
        # guard against pushing a partially-saved file without needing
        # a filesystem watcher.
        try:
            mtime = local_path.stat().st_mtime
            if time.time() - mtime < _MTIME_STABILITY_WINDOW:
                return None
        except OSError:
            # File vanished between the hash check above and now —
            # let the normal flow handle it (next sync sees it missing).
            return None

        try:
            result = push_file(
                topic_id,
                item.id,
                local_path,
                item,
                if_match=entry.last_seen_revision,
            )
        except ConcurrentWriteError as exc:
            # Server's revision moved past entry.last_seen_revision —
            # someone else wrote between our last sync and this push.
            # Keep the local edit, mark conflicted, surface the divergence.
            # Resolution is explicit (sync conflicts resolve), same UX as
            # the local-vs-remote conflict path.
            state.mark_conflict(
                item.id,
                detected_at=now_iso(),
                remote_updated_at=item.updated_at or "",
                local_hash=local_hash,
            )
            click.echo(f"  Conflict (concurrent write): {display}  (knowledge_id {item.id})")
            click.echo(f"    Local hash:      {local_hash[:12]}…")
            click.echo(f"    Server revision: {exc.current_revision}")
            if exc.current_content_hash:
                click.echo(f"    Server hash:     {exc.current_content_hash[:12]}…")
            click.echo("    Resolve:")
            click.echo(f"      obris sync conflicts resolve {filename} --keep-local")
            click.echo(f"      obris sync conflicts resolve {filename} --keep-remote")
            return CONFLICT
        state.track(
            item.id,
            filename,
            topic_id=item.topic_id,
            last_seen_revision=int(result.get("revision") or 0),
            last_seen_content_hash=result.get("content_hash") or local_hash,
            mtime_at_last_sync=mtime,
        )
        click.echo(f"  Pushed {display}")
        return PUSHED

    if remote_changed:
        # Server tells us its current canonical hash; if local already
        # matches, the revision bump didn't change content (a no-op
        # save, a metadata-only edit, or our own previous push echoing
        # back). Just record the new revision and skip the download.
        if item.content_hash and item.content_hash == local_hash:
            state.track(
                item.id,
                filename,
                topic_id=item.topic_id,
                last_seen_revision=item.revision,
                last_seen_content_hash=item.content_hash,
                mtime_at_last_sync=_safe_mtime(local_path),
            )
            return None

        display = display_path(current_rel, filename)
        if dry_run:
            click.echo(f"  Would pull {display}")
            return PULLED

        new_hash = safe_pull(lambda tmp: pull_item(item, tmp), sync_dir / current_rel, filename)
        state.track(
            item.id,
            filename,
            topic_id=item.topic_id,
            last_seen_revision=item.revision,
            last_seen_content_hash=item.content_hash or new_hash,
            mtime_at_last_sync=_safe_mtime(local_path),
        )
        if new_hash != local_hash:
            click.echo(f"  Pulled {display}")
            return PULLED
        return None

    # No content change, but make sure topic_id is recorded for older state files.
    if not entry.topic_id and item.topic_id:
        state.track(
            item.id,
            filename,
            topic_id=item.topic_id,
            last_seen_revision=entry.last_seen_revision,
            last_seen_content_hash=entry.last_seen_content_hash,
            mtime_at_last_sync=entry.mtime_at_last_sync,
        )

    return None


def _hash_if_exists(filepath):
    if Path(filepath).exists():
        return hash_file(filepath)
    return None


def _safe_mtime(filepath) -> float:
    try:
        return Path(filepath).stat().st_mtime
    except OSError:
        return 0.0
