"""Main sync loop.

Drives one sync pass over a root topic. Reads the server's sync-state
manifest (``GET /topics/<id>/sync-state``), short-circuits on a 304
when the subtree is unchanged remotely, and otherwise dispatches each
manifest entry through ``sync_tracked_item``. Directory reconciliation
runs up front via ``reconcile_topic_dirs``; remote-deleted items are
detected by comparing the manifest against ``state.tracked_ids()``.
"""

from __future__ import annotations

from pathlib import Path

import click

from obris.api.topics import fetch_sync_state

from ..constants import CONFLICT, MISSING, PULLED, PUSHED
from ..exclusions import ExclusionMatcher
from ..io import pull_item
from ..mapping import build_topic_dirs, compute_filename, unique_filename
from ..models import RemoteItem
from ..state import SyncState
from .filters import any_match
from .manifest import run_push_only, subtree_from_manifest
from .subtree import (
    ancestors_of,
    compute_name_paths,
    display_path,
    reconcile_topic_dirs,
    safe_pull,
)
from .tracked import sync_tracked_item


def run_sync(
    topic_id,
    sync_dir,
    *,
    state=None,
    item_ids=None,
    include_patterns=None,
    dry_run=False,
):
    """Run a sync cycle. Returns (pulled, pushed, conflicts, errors, missing_local).

    ``topic_id`` must be a root topic — the caller is responsible for
    validating this. The engine fetches its own subtree view via the
    sync-state manifest endpoint; callers no longer pre-fetch a
    subtree.

    If ``item_ids`` is given, only those items are synced.

    If ``include_patterns`` is given, only topics whose name path
    matches at least one pattern contribute items. Intermediate topics
    on the path still get directories created.

    If ``dry_run`` is True, reports what would happen without modifying
    any files, remote state, or sync state.
    """
    sync_dir = Path(sync_dir)
    if not dry_run:
        sync_dir.mkdir(parents=True, exist_ok=True)

    if state is None:
        state = SyncState.load(topic_id, sync_dir)
    if not state:
        state = SyncState(topic_id, sync_dir)

    if include_patterns is not None:
        patterns = list(include_patterns)
        if not dry_run:
            state.set_include_patterns(patterns)
    else:
        patterns = state.include_patterns

    exclusions = ExclusionMatcher(sync_dir, state_excludes=state.exclude_patterns)
    filter_item_ids = set(item_ids) if item_ids else None

    cached_root_hash = state.get_root_hash(topic_id)
    manifest = fetch_sync_state(topic_id, if_none_match=cached_root_hash)

    if manifest is None:
        # 304 short-circuit: subtree unchanged remotely. The only work
        # left is pushing any locally-edited tracked items. Skip topic
        # reconciliation, remote-deleted detection, and new-pull —
        # nothing on the server moved.
        return run_push_only(
            state,
            sync_dir,
            topic_id,
            exclusions,
            filter_item_ids=filter_item_ids,
            dry_run=dry_run,
        )

    if not dry_run:
        state.set_root_hash(topic_id, manifest.get("root_hash") or "")

    subtree_nodes = subtree_from_manifest(manifest, topic_id)
    desired_topic_dirs = build_topic_dirs(subtree_nodes, topic_id)
    name_paths = compute_name_paths(subtree_nodes, topic_id)

    if patterns:
        matched_ids = {tid for tid, segments in name_paths.items() if any_match(segments, patterns)}
    else:
        matched_ids = set(name_paths.keys())

    path_ids = ancestors_of(matched_ids, subtree_nodes, topic_id)
    reconcile_topic_dirs(state, desired_topic_dirs, path_ids, sync_dir, dry_run=dry_run)

    # Persist the reconciled topic_dirs map before the item loop runs.
    # A crash during item pulls would otherwise leave disk with the new
    # directory layout but state still pointing at the old one — next
    # sync's reconcile would try to rename dirs that no longer exist at
    # their source paths.
    if not dry_run:
        state.save()

    pulled, pushed, conflicts, errors = 0, 0, 0, 0
    seen_ids: set[str] = set()
    missing_local: list[dict] = []

    for kid, raw in manifest.get("items", {}).items():
        item = RemoteItem.from_manifest_entry(kid, raw)
        if patterns and item.topic_id and item.topic_id not in matched_ids:
            continue
        seen_ids.add(item.id)
        if state.is_unlinked(item.id):
            # User ran 'obris sync unlink' on this id. Leave the
            # remote alone, don't pull, don't surface — they
            # explicitly opted out of syncing this item.
            continue
        if state.is_conflicted(item.id):
            # Already-pending conflict. Skip both push and pull
            # this pass; the user resolves explicitly via
            # 'obris sync conflicts resolve'. Bump the counter so
            # the summary line still surfaces "1 conflict pending"
            # instead of looking clean.
            conflicts += 1
            continue
        if filter_item_ids and item.id not in filter_item_ids:
            continue

        # On a dry-run pass, ``reconcile_topic_dirs`` deliberately doesn't
        # call ``state.set_topic_dir`` (no side effects on the local state
        # file), so ``state.get_topic_dir`` returns None for any subtopic
        # that the live run would create. Fall back to the desired map
        # the manifest already gave us, otherwise dry-run output prints
        # bare basenames with no parent directory context.
        item_rel = state.get_topic_dir(item.topic_id) if item.topic_id else ""
        if item_rel is None:
            item_rel = desired_topic_dirs.get(item.topic_id, "") if item.topic_id else ""

        if state.is_tracked(item.id):
            entry = state.get(item.id)
            # Skip if the file's *current* on-disk location matches an
            # exclude. Use entry.topic_id (where the item lives in
            # state today) rather than item.topic_id (where the
            # remote moved it to) — sync_tracked_item handles the
            # cross-topic move. Excluding skips both the move and
            # any push/pull, leaving the entry intact so removing
            # the exclude later resumes sync without manual relink.
            current_rel = state.get_topic_dir(entry.topic_id) if entry.topic_id else ""
            if exclusions.excludes(display_path(current_rel or "", entry.filename)):
                continue
            try:
                result = sync_tracked_item(topic_id, item, entry, state, sync_dir, item_rel, dry_run=dry_run)
                if result == PUSHED:
                    pushed += 1
                elif result == PULLED:
                    pulled += 1
                elif result == CONFLICT:
                    conflicts += 1
                elif result == MISSING:
                    missing_local.append(
                        {
                            "file": display_path(current_rel or "", entry.filename),
                            "knowledge_id": item.id,
                        }
                    )
            except Exception as e:
                click.echo(
                    f"  Error syncing {entry.filename}: {type(e).__name__}: {e}",
                    err=True,
                )
                errors += 1
            continue

        original_name = compute_filename(item)
        if not original_name:
            continue
        filename = unique_filename(sync_dir, item_rel, original_name)
        renamed = filename != original_name

        # Skip new-pull if the destination path matches an exclude.
        # Item stays on the remote, just doesn't materialize locally.
        # Not added to state, so removing the exclude later will pull
        # it on the next sync via the same code path.
        if exclusions.excludes(display_path(item_rel, filename)):
            continue

        if dry_run:
            msg = f"  Would pull {display_path(item_rel, filename)} (new)"
            if renamed:
                msg += f" (renamed from {original_name}, file already exists)"
            click.echo(msg)
            pulled += 1
            continue

        try:
            (sync_dir / item_rel).mkdir(parents=True, exist_ok=True)
            new_hash = safe_pull(lambda tmp, it=item: pull_item(it, tmp), sync_dir / item_rel, filename)
            try:
                mtime = (sync_dir / item_rel / filename).stat().st_mtime
            except OSError:
                mtime = 0.0
            state.track(
                item.id,
                filename,
                topic_id=item.topic_id,
                last_seen_revision=item.revision,
                last_seen_content_hash=item.content_hash or new_hash,
                mtime_at_last_sync=mtime,
            )
            display = display_path(item_rel, filename)
            if renamed:
                click.echo(f"  Pulled {display} (new, {original_name} already exists)")
            else:
                click.echo(f"  Pulled {display} (new)")
            pulled += 1
        except Exception as e:
            click.echo(
                f"  Error pulling {filename}: {type(e).__name__}: {e}",
                err=True,
            )
            errors += 1

    if not filter_item_ids:
        for kid in state.tracked_ids() - seen_ids:
            entry = state.get(kid)
            if patterns and entry.topic_id and entry.topic_id not in matched_ids:
                continue
            rel = state.get_topic_dir(entry.topic_id) if entry.topic_id else ""
            display = display_path(rel or "", entry.filename)
            if dry_run:
                click.echo(f"  Would untrack {display} (remote deleted)")
            else:
                click.echo(f"  Remote deleted: {display} (local file kept)")
                state.untrack(kid)

    if filter_item_ids:
        for kid in filter_item_ids - seen_ids:
            click.echo(f"  Item {kid} not found in topic", err=True)
            errors += 1

    if not dry_run:
        state.save()

    return pulled, pushed, conflicts, errors, missing_local
