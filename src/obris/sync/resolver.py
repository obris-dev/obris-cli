"""Topic resolution helpers shared by sync commands.

Kept out of ``obris.commands.sync`` to keep the command file under
the 300-line cap and so other sync commands can reuse the same
resolver logic without a command-layer import.
"""

from __future__ import annotations

from pathlib import Path

import click

from obris.api.topics import create_topic, get_topic

from .state import SyncState

_MAX_ANCESTOR_DEPTH = 64


class SubtopicTargetError(SystemExit):
    """Raised when a sync target is a subtopic rather than a root topic.

    Subclasses ``SystemExit`` so it still exits the process with a
    clean message in single-pass mode, but callers (notably the watch
    loops) can catch it specifically to break out of the iteration
    instead of re-logging the same error forever.
    """


def resolve_targets(sync_dir: Path, topic_id: str | None, yes: bool) -> list[tuple]:
    """Determine which topic(s) to sync.

    Returns a list of ``(SyncState | None, topic_id, topic_name)``
    tuples. When no explicit topic is given and no state exists, the
    user is prompted (or auto-confirmed via ``yes``) to create a new
    root topic named after the directory.
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

    topic_name = sync_dir.name
    if not yes:
        click.confirm(f'Create topic "{topic_name}" and sync to {sync_dir}/?', default=True, abort=True)
    topic = create_topic(topic_name)
    click.echo(f'Created topic "{topic_name}"')
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
    """Raise ``SubtopicTargetError`` if any target isn't a root topic.

    ``targets`` is the list of ``(state, topic_id, topic_name)``
    tuples returned by ``resolve_targets``. Called as a preflight so
    all three sync paths (single-pass, foreground watch, background
    watch) fail fast with the same error before entering their loops.
    """
    for _state, tid, name in targets:
        root = find_root(tid)
        if root.id != tid:
            raise SubtopicTargetError(
                f'"{name}" is a subtopic of "{root.name}". '
                f"Sync from the root topic instead:\n"
                f"  obris sync --topic {root.id} --path {sync_dir}"
            )
