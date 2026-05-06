"""Topic resolution helpers shared by sync commands."""

from __future__ import annotations

from pathlib import Path

import click

from obris.api.topics import create_topic, get_topic

from .state import SyncState

_MAX_ANCESTOR_DEPTH = 64


def resolve_targets(sync_dir: Path, topic_id: str | None, *, no_create: bool = False) -> list[tuple]:
    """Determine which topic(s) to sync.

    Returns a list of ``(SyncState | None, topic_id, topic_name)``
    tuples. When no explicit topic is given and no state exists, a
    new root topic named after the directory is created automatically.
    Pass ``no_create=True`` to error instead of bootstrapping — the
    safety net for AI agents and scripts that don't want surprises.
    """
    if topic_id:
        state = SyncState.load(topic_id, sync_dir)
        topic = get_topic(topic_id)
        return [(state, topic_id, topic.name)]

    states = SyncState.find_all_for_path(sync_dir)

    if states:
        targets = []
        for state, tid in states:
            topic = get_topic(tid)
            targets.append((state, tid, topic.name))
        return targets

    if no_create:
        raise SystemExit(
            f"No synced topic for {sync_dir}/. "
            f"Run without --no-create to create one, or pass --topic <id> to link an existing topic."
        )

    topic_name = sync_dir.name
    topic = create_topic(topic_name)
    click.echo(f'Created topic "{topic_name}" ({topic.id}).')
    return [(None, topic.id, topic_name)]


def find_root(topic_id: str, topic=None):
    """Walk up parent_id pointers to find the root topic.

    Cycle-safe: visited set + depth cap. Raises SystemExit on cycle or
    when the depth cap is exceeded (which only happens on corrupt data).
    """
    if topic is None:
        topic = get_topic(topic_id)
    visited = {topic_id}
    depth = 0
    while topic.parent_id:
        depth += 1
        if depth > _MAX_ANCESTOR_DEPTH:
            raise SystemExit(f"Topic ancestor chain exceeds depth {_MAX_ANCESTOR_DEPTH} starting at {topic_id}")
        parent_id = topic.parent_id
        if parent_id in visited:
            raise SystemExit(f"Topic ancestor cycle detected walking up from {topic_id}")
        visited.add(parent_id)
        topic = get_topic(parent_id)
    return topic


def find_root_id(topic_id: str, topic=None) -> str:
    return find_root(topic_id, topic).id


def assert_all_roots(targets, sync_dir: Path) -> None:
    """Raise ``SystemExit`` if any target isn't a root topic."""
    for _state, tid, name in targets:
        root = find_root(tid)
        if root.id != tid:
            raise SystemExit(
                f'"{name}" is a subtopic of "{root.name}". '
                f"Sync from the root topic instead:\n"
                f"  obris sync --topic {root.id} --path {sync_dir}"
            )
