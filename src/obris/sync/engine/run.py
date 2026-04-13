"""Main sync loop.

Fetches items from the matched topics, dispatches tracked items to
``sync_tracked_item``, pulls new items, and records remote deletions.
Directory reconciliation runs up front via ``reconcile_topic_dirs``.
"""

from __future__ import annotations

from pathlib import Path

import click

from ..constants import CONFLICT, PULLED, PUSHED
from ..io import pull_item
from ..mapping import build_topic_dirs, compute_filename, now_iso, unique_filename
from ..models import RemoteItem, RemoteTopic
from ..state import SyncState
from .filters import any_match
from .subtree import (
    ancestors_of,
    compute_name_paths,
    display_path,
    fetch_topic_items,
    reconcile_topic_dirs,
    safe_pull,
)
from .tracked import sync_tracked_item


def run_sync(
    topic_id,
    sync_dir,
    *,
    state=None,
    subtree=None,
    item_ids=None,
    include_patterns=None,
    dry_run=False,
):
    """Run a sync cycle. Returns (pulled, pushed, conflicts, errors).

    ``topic_id`` must be a root topic — the caller is responsible for
    validating this and providing a fetched ``subtree`` as a list of
    ``RemoteTopic`` DTOs. If ``subtree`` is None, the root is assumed
    to stand alone (single-topic tree) and we synthesize a stub
    ``RemoteTopic`` for it.

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

    # Fall back to a single-node subtree when the caller didn't fetch one.
    # Using the DTO (not a raw dict) keeps the pipeline type-consistent
    # and lets compute_name_paths / build_topic_dirs do attribute access
    # without special-casing this one stub.
    subtree_nodes = subtree or [RemoteTopic(id=topic_id, name="", parent_id=None)]
    desired_topic_dirs = build_topic_dirs(subtree_nodes, topic_id)
    name_paths = compute_name_paths(subtree_nodes, topic_id)

    # Two branches, each with exactly one responsibility: filtered vs
    # unfiltered. any_match no longer carries an "empty patterns = match
    # all" shortcut because that's a policy choice, not a matcher rule —
    # the unfiltered branch owns that decision. ``compute_name_paths``
    # already maps the root topic (its segments are ``[]``), so both
    # branches naturally include it when patterns don't exclude it —
    # no belt-and-suspenders ``.add(topic_id)`` required.
    if patterns:
        # ``**`` against segments=[] correctly matches zero-or-more
        # segments, so the root is still matchable via a broad pattern.
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

    filter_item_ids = set(item_ids) if item_ids else None
    pulled, pushed, conflicts, errors = 0, 0, 0, 0
    seen_ids: set[str] = set()

    # Filtered mode does one non-recursive request per matched topic;
    # unfiltered mode does one recursive request covering the subtree.
    iter_sources = [(tid, False) for tid in sorted(matched_ids)] if patterns else [(topic_id, True)]

    for fetch_tid, use_recursive in iter_sources:
        for raw in fetch_topic_items(topic_id, fetch_tid, use_recursive=use_recursive):
            item = RemoteItem.from_api(raw)
            if patterns and item.topic_id and item.topic_id not in matched_ids:
                continue
            seen_ids.add(item.id)
            if filter_item_ids and item.id not in filter_item_ids:
                continue

            item_rel = state.get_topic_dir(item.topic_id) if item.topic_id else ""
            if item_rel is None:
                item_rel = ""

            if state.is_tracked(item.id):
                if not item.is_ready:
                    continue
                entry = state.get(item.id)
                try:
                    result = sync_tracked_item(topic_id, item, entry, state, sync_dir, item_rel, dry_run=dry_run)
                    if result == PUSHED:
                        pushed += 1
                    elif result == PULLED:
                        pulled += 1
                    elif result == CONFLICT:
                        conflicts += 1
                except Exception as e:
                    click.echo(
                        f"  Error syncing {entry.filename}: {type(e).__name__}: {e}",
                        err=True,
                    )
                    errors += 1
                continue

            if not item.is_ready:
                continue
            original_name = compute_filename(item)
            if not original_name:
                continue
            filename = unique_filename(sync_dir, item_rel, original_name)
            renamed = filename != original_name

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
                state.track(
                    item.id,
                    filename,
                    new_hash,
                    item.best_timestamp or now_iso(),
                    topic_id=item.topic_id,
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

    return pulled, pushed, conflicts, errors
