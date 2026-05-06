"""Conflict resolution subcommands.

  obris sync conflicts list
  obris sync conflicts resolve <file> --keep-local
  obris sync conflicts resolve <file> --keep-remote

The list/resolve flow is mostly inert until §8 wires the engine to
mark items as conflicted. Until then, ``conflicts list`` returns
empty and ``conflicts resolve`` errors with "no conflict pending."
"""

from __future__ import annotations

from pathlib import Path

import click

from obris.api.knowledge import knowledge_detail
from obris.sync.engine.subtree import display_path, safe_pull
from obris.sync.io import pull_item, push_file
from obris.sync.mapping import conflict_filename, hash_file, unique_filename
from obris.sync.models import RemoteItem
from obris.sync.state import SyncState


def _states_for_current_dir(path):
    sync_dir = Path(path).resolve()
    states = SyncState.find_all_for_path(sync_dir)
    if not states:
        raise SystemExit(f"No synced topic found for {sync_dir}/. Run 'obris sync --topic <id>' first.")
    return sync_dir, states


def _resolve_target(target, states):
    """Find ``(state, kid)`` for a target that's either a knowledge id or a tracked basename."""
    matches = []
    for state, _tid in states:
        if state.is_tracked(target):
            matches.append((state, target))
            continue
        kid, _entry = state.find_by_filename(target)
        if kid:
            matches.append((state, kid))
    return matches


def register(sync):
    """Attach the conflicts subgroup to the given Click group."""

    @sync.group("conflicts")
    def conflicts_group():
        """List and resolve sync conflicts."""

    @conflicts_group.command("list")
    @click.option("--path", "-p", default=".", help="Sync directory (defaults to current directory)")
    def conflicts_list(path):
        """Show items currently flagged as conflicted.

        A conflict means both local and remote changed since the last
        successful sync. The engine pauses sync for the file until you
        run 'obris sync conflicts resolve'.
        """
        _sync_dir, states = _states_for_current_dir(path)

        any_found = False
        for state, _tid in states:
            for kid, meta in state.conflicts.items():
                any_found = True
                entry = state.get(kid)
                rel = state.get_topic_dir(entry.topic_id) if entry and entry.topic_id else ""
                name = entry.filename if entry else "(unknown)"
                click.echo(f"{display_path(rel or '', name)}  (knowledge_id {kid})")
                click.echo(f"  detected:        {meta.get('detected_at', '?')}")
                click.echo(f"  remote modified: {meta.get('remote_updated_at', '?')}")
                click.echo("  Resolve:")
                click.echo(f"    obris sync conflicts resolve {name} --keep-local")
                click.echo(f"    obris sync conflicts resolve {name} --keep-remote")
        if not any_found:
            click.echo("No pending conflicts.")

    @conflicts_group.command("resolve")
    @click.argument("file")
    @click.option("--keep-local", "keep_local", is_flag=True, help="Push local content; clear conflict.")
    @click.option(
        "--keep-remote",
        "keep_remote",
        is_flag=True,
        help="Pull remote content; save local copy as a (conflict <date>) sibling; clear conflict.",
    )
    @click.option("--path", "-p", default=".", help="Sync directory (defaults to current directory)")
    def conflicts_resolve(file, keep_local, keep_remote, path):
        """Resolve a single conflict by choosing local or remote.

        FILE is a tracked basename or a knowledge ID.
        """
        if keep_local == keep_remote:
            raise click.UsageError("Specify exactly one of --keep-local or --keep-remote.")

        sync_dir, states = _states_for_current_dir(path)
        matches = _resolve_target(file, states)
        if not matches:
            raise SystemExit(f"Not tracked: {file}")
        if len(matches) > 1:
            click.echo(f"Ambiguous: '{file}' matches multiple tracked items:")
            for state, kid in matches:
                e = state.get(kid)
                click.echo(f"  {kid}  ({e.filename})")
            click.echo("  Re-run with the specific knowledge ID.")
            raise SystemExit(1)
        state, kid = matches[0]
        if not state.is_conflicted(kid):
            raise SystemExit(f"No conflict pending for {file}.")

        entry = state.get(kid)
        rel = state.get_topic_dir(entry.topic_id) if entry.topic_id else ""
        local_path = sync_dir / (rel or "") / entry.filename

        if keep_local:
            _resolve_keep_local(state, kid, entry, local_path)
        else:
            _resolve_keep_remote(state, kid, entry, local_path, sync_dir, rel or "")


def _resolve_keep_local(state, kid, entry, local_path):
    if not local_path.exists():
        raise SystemExit(f"Local file missing: {local_path}. Cannot --keep-local.")
    detail = knowledge_detail(kid)
    item = RemoteItem.from_api(detail)
    result = push_file(item.topic_id or entry.topic_id, kid, local_path, item)
    new_hash = hash_file(local_path)
    state.track(
        kid,
        entry.filename,
        topic_id=entry.topic_id,
        last_seen_revision=int(result.get("revision") or 0),
        last_seen_content_hash=result.get("content_hash") or new_hash,
        mtime_at_last_sync=local_path.stat().st_mtime,
    )
    state.clear_conflict(kid)
    state.save()
    click.echo(f"Resolved {entry.filename}: pushed local copy.")


def _resolve_keep_remote(state, kid, entry, local_path, sync_dir, rel):
    detail = knowledge_detail(kid)
    item = RemoteItem.from_api(detail)
    if local_path.exists():
        backup_name = unique_filename(sync_dir, rel, conflict_filename(entry.filename))
        backup_path = sync_dir / rel / backup_name
        local_path.rename(backup_path)
        click.echo(f"Saved local copy as {display_path(rel, backup_name)}.")
    new_hash = safe_pull(lambda tmp: pull_item(item, tmp), sync_dir / rel, entry.filename)
    pulled_path = sync_dir / rel / entry.filename
    try:
        mtime = pulled_path.stat().st_mtime
    except OSError:
        mtime = 0.0
    state.track(
        kid,
        entry.filename,
        topic_id=entry.topic_id,
        last_seen_revision=item.revision,
        last_seen_content_hash=item.content_hash or new_hash,
        mtime_at_last_sync=mtime,
    )
    state.clear_conflict(kid)
    state.save()
    click.echo(f"Resolved {entry.filename}: pulled remote copy.")
