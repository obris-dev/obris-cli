"""Subtree path helpers and directory reconciliation for sync.

All functions here are pure-logic or filesystem-only — they don't hit
the API except ``fetch_topic_items``, which delegates to the topics API
client.
"""

from __future__ import annotations

from pathlib import Path

import click

from obris.api.topics import iter_knowledge
from obris.sync.models import RemoteTopic

MAX_WALK_DEPTH = 64


def compute_name_paths(subtree: list[RemoteTopic], root_topic_id: str) -> dict[str, list[str]]:
    """Return ``{topic_id: [name, ...]}`` for every topic reachable from the root.

    The root itself maps to []. Topics orphaned from the root or whose
    parent chain exceeds the depth cap are skipped.
    """
    by_id = {node.id: node for node in subtree}
    out: dict[str, list[str]] = {}
    for tid in by_id:
        segments: list[str] = []
        visited: set[str] = set()
        cur: str | None = tid
        while cur and cur != root_topic_id:
            if cur in visited or len(visited) > MAX_WALK_DEPTH:
                segments = []
                break
            visited.add(cur)
            node = by_id.get(cur)
            if not node:
                segments = []
                break
            segments.append(node.name)
            cur = node.parent_id
        if cur == root_topic_id:
            out[tid] = list(reversed(segments))
    return out


def ancestors_of(topic_ids: set[str], subtree: list[RemoteTopic], root_topic_id: str) -> set[str]:
    """Return ``topic_ids`` plus every ancestor up to (and including) the root."""
    by_id = {node.id: node for node in subtree}
    result: set[str] = set()
    for tid in topic_ids:
        cur: str | None = tid
        visited: set[str] = set()
        while cur and cur not in result:
            if cur in visited or len(visited) > MAX_WALK_DEPTH:
                break
            visited.add(cur)
            result.add(cur)
            if cur == root_topic_id:
                break
            node = by_id.get(cur)
            if not node:
                break
            cur = node.parent_id
    result.add(root_topic_id)
    return result


def reconcile_topic_dirs(state, desired_topic_dirs, path_ids, sync_dir, *, dry_run):
    """Align ``state.topic_dirs`` with the desired map for ``path_ids``.

    - Missing → mkdir + record.
    - Differs → os.rename the directory and update the record.
    - Orphaned (in state but no longer in path_ids) → drop from state,
      leave the directory on disk as a soft-delete.

    Known gap: directory swaps (``A/B`` and ``A/C`` swap names in a single
    remote rename pair) fail when the first rename's target still holds
    the second source's old name. Staging colliding sources through
    ``{slug}.obris-tmp-{n}`` intermediates before landing them would fix
    it, but the real-world scenario (a user literally swaps two sibling
    topic names on the server between syncs) is rare and the failure is
    loud rather than silently wrong. Deferred to a follow-up.
    """
    current = dict(state.topic_dirs)

    for tid in list(current.keys()):
        if tid not in path_ids:
            if dry_run:
                click.echo(f"  Would forget directory for topic {tid}")
            else:
                state.drop_topic_dir(tid)

    # Process shallowest-first so parents get created / renamed before
    # their children. ``"".split("/")`` returns ``[""]`` (length 1), which
    # would rank the root alongside depth-1 children — wrong, even if the
    # existing mkdir(parents=True) masks the bug. Use the slash count:
    # root ("") is depth 0, "A" is depth 1, "A/B" is depth 2, etc.
    def _dir_depth(tid: str) -> int:
        rel = desired_topic_dirs.get(tid, "")
        return 0 if not rel else rel.count("/") + 1

    for tid in sorted(path_ids, key=_dir_depth):
        if tid not in desired_topic_dirs:
            continue
        desired = desired_topic_dirs[tid]
        existing = current.get(tid)
        if existing == desired:
            continue
        if existing is None:
            target = sync_dir / desired if desired else sync_dir
            if dry_run:
                if desired:
                    click.echo(f"  Would create directory {desired}/")
            else:
                target.mkdir(parents=True, exist_ok=True)
                state.set_topic_dir(tid, desired)
        else:
            src = sync_dir / existing
            dst = sync_dir / desired
            if dry_run:
                click.echo(f"  Would move directory {existing}/ -> {desired}/")
            else:
                if src.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    src.rename(dst)
                else:
                    dst.mkdir(parents=True, exist_ok=True)
                state.set_topic_dir(tid, desired)
                click.echo(f"  Moved directory {existing}/ -> {desired}/")


def fetch_topic_items(root_topic_id, target_topic_id, *, use_recursive):
    """Yield raw knowledge dicts for ``target_topic_id``.

    When ``use_recursive`` is True and ``target_topic_id`` is the root,
    we fetch the whole subtree in one paginated stream via
    ``?recursive=true``. Otherwise we fetch just the one topic's items.
    """
    if use_recursive and target_topic_id == root_topic_id:
        yield from iter_knowledge(root_topic_id, recursive=True)
    else:
        yield from iter_knowledge(target_topic_id, recursive=False)


def display_path(relative_dir: str, filename: str) -> str:
    if relative_dir:
        return f"{relative_dir}/{filename}"
    return filename


def safe_pull(pull_fn, target_dir, filename):
    """Pull to a temp file via ``pull_fn(tmp_path)``, then atomic rename."""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / filename
    tmp = target_dir / f".{filename}.obris-tmp"
    try:
        new_hash = pull_fn(tmp)
        tmp.rename(dest)
        return new_hash
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
