"""Per-item sync logic for tracked knowledge items.

The public entry point is ``sync_tracked_item`` — the engine loop calls
it once per item after resolving the item's target relative directory.
"""

from __future__ import annotations

from pathlib import Path

import click

from ..constants import CONFLICT, PULLED, PUSHED
from ..io import pull_item, push_file
from ..mapping import (
    conflict_filename,
    hash_bytes,
    hash_file,
    now_iso,
    parse_timestamp,
    unique_filename,
)
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
                # timestamp if they run, but if none do (the body didn't
                # change and the server didn't bump updated_at) this is
                # the only write that reflects the new on-disk location.
                # Without it, a reparent-only sync would leave state
                # pointing at the old path and next sync would keep
                # trying to re-do the move against a non-existent src.
                state.track(
                    item.id,
                    filename,
                    entry.local_hash,
                    entry.last_synced_at,
                    topic_id=item.topic_id,
                    pushed_hash=entry.pushed_hash,
                )
        current_rel = desired_rel

    local_path = sync_dir / current_rel / filename
    local_hash = _hash_if_exists(local_path)

    if local_hash is None:
        remote_name = item.title or filename
        display = display_path(current_rel, filename)
        if dry_run:
            click.echo(f"  Would untrack {display} (file missing)")
        else:
            click.echo(f'  Missing: {display} (was synced to "{remote_name}")')
            click.echo("    This file will no longer sync with its remote item.")
            click.echo(f"    To relink after a rename: obris sync link <new-filename> -i {item.id}")
            state.untrack(item.id)
        return None

    local_changed = local_hash != entry.local_hash
    remote_changed = bool(item.updated_at) and parse_timestamp(item.updated_at) > parse_timestamp(entry.last_synced_at)

    if local_changed and remote_changed:
        display = display_path(current_rel, filename)
        if dry_run:
            click.echo(f"  Would conflict: {display} (remote would win, local saved as conflict)")
            return CONFLICT

        conflict_name = unique_filename(sync_dir, current_rel, conflict_filename(filename))
        backup = sync_dir / current_rel / conflict_name
        local_path.rename(backup)
        try:
            new_hash = safe_pull(lambda tmp: pull_item(item, tmp), sync_dir / current_rel, filename)
        except Exception:
            try:
                backup.rename(local_path)
            except OSError:
                click.echo(
                    f"  Warning: could not restore {display}, your copy is at {conflict_name}",
                    err=True,
                )
            raise
        state.track(
            item.id,
            filename,
            new_hash,
            item.updated_at or now_iso(),
            topic_id=item.topic_id,
        )
        click.echo(f"  Conflict: {display} \u2014 remote kept, local saved as {conflict_name}")
        return CONFLICT

    if local_changed:
        display = display_path(current_rel, filename)
        if dry_run:
            click.echo(f"  Would push {display}")
            return PUSHED

        result = push_file(topic_id, item.id, local_path, item)
        synced_at = result.get("updated_at") or now_iso()
        state.track(
            item.id,
            filename,
            local_hash,
            synced_at,
            topic_id=item.topic_id,
            pushed_hash=local_hash,
        )
        click.echo(f"  Pushed {display}")
        return PUSHED

    if remote_changed:
        if entry.pushed_hash and local_hash == entry.pushed_hash:
            state.track(
                item.id,
                filename,
                local_hash,
                item.updated_at or now_iso(),
                topic_id=item.topic_id,
            )
            return None

        if item.content:
            remote_hash = hash_bytes(item.content)
            if remote_hash == local_hash:
                state.track(
                    item.id,
                    filename,
                    local_hash,
                    item.updated_at or now_iso(),
                    topic_id=item.topic_id,
                )
                return None

        display = display_path(current_rel, filename)
        if dry_run:
            click.echo(f"  Would pull {display}")
            return PULLED

        new_hash = safe_pull(lambda tmp: pull_item(item, tmp), sync_dir / current_rel, filename)
        if new_hash == local_hash:
            state.track(
                item.id,
                filename,
                local_hash,
                item.updated_at or now_iso(),
                topic_id=item.topic_id,
            )
            return None
        state.track(
            item.id,
            filename,
            new_hash,
            item.updated_at or now_iso(),
            topic_id=item.topic_id,
        )
        click.echo(f"  Pulled {display}")
        return PULLED

    # No content change, but make sure topic_id is recorded for older state files.
    if not entry.topic_id and item.topic_id:
        state.track(
            item.id,
            filename,
            local_hash,
            entry.last_synced_at,
            topic_id=item.topic_id,
            pushed_hash=entry.pushed_hash,
        )

    return None


def _hash_if_exists(filepath):
    if Path(filepath).exists():
        return hash_file(filepath)
    return None
