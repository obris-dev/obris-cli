"""Helpers for working with the sync-state manifest response.

The engine fetches one manifest per sync pass via
``GET /topics/<root>/sync-state``. This module owns the small bits of
logic that translate a manifest into engine-shaped inputs (subtree
nodes) and the 304 fast path that runs when the cached root_hash is
still current.
"""

from __future__ import annotations

from pathlib import Path

import click

from ..constants import CONFLICT, MISSING, PULLED, PUSHED, STATUS_READY
from ..models import RemoteItem, RemoteTopic
from .subtree import display_path
from .tracked import sync_tracked_item


def subtree_from_manifest(manifest, root_topic_id):
    """Build a list of ``RemoteTopic`` from the manifest's ``topics`` dict.

    The manifest's per-topic entries carry ``parent_id`` and ``name`` —
    enough to feed ``compute_name_paths`` / ``build_topic_dirs`` /
    ``ancestors_of`` without a separate subtree fetch. The root topic
    is always present in the manifest, but we add a stub if a server
    edge case omits it so downstream code never sees a missing root.
    """
    nodes = []
    seen_root = False
    for tid, info in manifest.get("topics", {}).items():
        if tid == root_topic_id:
            seen_root = True
        nodes.append(
            RemoteTopic(
                id=tid,
                name=info.get("name") or "",
                parent_id=info.get("parent_id") or None,
            )
        )
    if not seen_root:
        nodes.append(RemoteTopic(id=root_topic_id, name="", parent_id=None))
    return nodes


def run_push_only(state, sync_dir, topic_id, exclusions, *, filter_item_ids, dry_run):
    """304 fast path: walk tracked entries, push any locally-edited ones.

    Synthesizes a ``RemoteItem`` from each state entry so
    ``sync_tracked_item`` can run its existing dirty-check + push
    branch unchanged. Because the synthesized revision/content_hash
    match what's already in state, ``remote_changed`` is always false
    and only the push branch can fire. No remote-deleted detection or
    new-pull — those require a fresh manifest.
    """
    sync_dir = Path(sync_dir)
    pulled, pushed, conflicts, errors = 0, 0, 0, 0
    missing_local: list[dict] = []
    for kid in list(state.tracked_ids()):
        entry = state.get(kid)
        if entry is None:
            continue
        if state.is_conflicted(kid):
            conflicts += 1
            continue
        if filter_item_ids and kid not in filter_item_ids:
            continue
        current_rel = state.get_topic_dir(entry.topic_id) if entry.topic_id else ""
        if exclusions.excludes(display_path(current_rel or "", entry.filename)):
            continue
        item = RemoteItem(
            id=kid,
            title=entry.filename,
            status=STATUS_READY,
            content="",
            file_url=None,
            file_name=entry.filename,
            source_type="",
            updated_at="",
            created_at="",
            topic_id=entry.topic_id,
            revision=entry.last_seen_revision,
            content_hash=entry.last_seen_content_hash,
        )
        try:
            result = sync_tracked_item(topic_id, item, entry, state, sync_dir, current_rel or "", dry_run=dry_run)
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
                        "knowledge_id": kid,
                    }
                )
        except Exception as e:
            click.echo(
                f"  Error syncing {entry.filename}: {type(e).__name__}: {e}",
                err=True,
            )
            errors += 1
    if not dry_run:
        state.save()
    return pulled, pushed, conflicts, errors, missing_local
