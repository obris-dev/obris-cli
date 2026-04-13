from pathlib import Path

import click

from obris.api.topics import create_topic, fetch_subtree, get_topic
from obris.output import as_json, is_json
from obris.sync.commands import add_file, link_file
from obris.sync.engine import run_sync
from obris.sync.state import SyncState


@click.group("sync", invoke_without_command=True)
@click.option("--path", "-p", default=".", help="Local directory to sync (defaults to current directory)")
@click.option("--topic", "-t", "topic_id", default=None, help="Root topic ID to sync")
@click.option("--item", "-i", "item_ids", multiple=True, help="Specific item IDs to sync (repeatable)")
@click.option(
    "--include",
    "include_patterns",
    multiple=True,
    help="Glob pattern for subtopics to include. Repeatable; patterns are OR'd together. "
    "Supports ** for any depth, * ? [abc] within a segment. Example: 'Projects/**' or '**/skill-*'",
)
@click.option("--dry-run", is_flag=True, help="Preview changes without modifying anything")
@click.option("-y", "--yes", is_flag=True, help="Auto-confirm prompts")
@click.pass_context
def sync(ctx, path, topic_id, item_ids, include_patterns, dry_run, yes):
    """Sync a local directory with an Obris root topic and its subtopics.

    On first sync, provide --topic <id> to link to an existing root topic,
    or omit it to create a new root topic named after the directory.
    Subsequent syncs auto-detect the linked topic from state.

    Only root topics (topics with no parent) can be sync targets. Child
    topics appear as subdirectories of their root. If you pass a child
    topic ID, the command will tell you the root to use instead.

    Use --include to sync only matching subtopics. Patterns OR together.
    Use --item to sync specific items only.
    """
    ctx.ensure_object(dict)
    ctx.obj["path"] = path
    ctx.obj["topic_id"] = topic_id

    if ctx.invoked_subcommand is not None:
        return

    sync_dir = Path(path).resolve()
    patterns = list(include_patterns) if include_patterns else None

    targets = _resolve_targets(sync_dir, topic_id, yes)

    total_pulled, total_pushed, total_conflicts, total_errors = 0, 0, 0, 0

    if dry_run:
        click.echo("  (dry run — no changes will be made)")

    for state, tid, topic_name in targets:
        # Root-only enforcement: fetch the topic and check parent_id.
        topic = get_topic(tid)
        if topic.parent_id:
            root = _find_root(tid)
            raise SystemExit(
                f'"{topic_name}" is a subtopic of "{root.name}". '
                f"Sync from the root topic instead:\n"
                f"  obris sync --topic {root.id} --path {sync_dir}"
            )

        click.echo(f'Syncing "{topic_name}" \u2194 {sync_dir}/')

        try:
            subtree = fetch_subtree(tid)
        except Exception as e:
            click.echo(f"  Error fetching subtree: {type(e).__name__}: {e}", err=True)
            total_errors += 1
            continue

        pulled, pushed, conflicts, errors = run_sync(
            tid,
            str(sync_dir),
            state=state,
            subtree=subtree,
            item_ids=item_ids or None,
            include_patterns=patterns,
            dry_run=dry_run,
        )
        total_pulled += pulled
        total_pushed += pushed
        total_conflicts += conflicts
        total_errors += errors

        if not pulled and not pushed and not conflicts and not errors:
            click.echo("  Everything up to date.")
        else:
            parts = []
            if pushed:
                parts.append(f"{pushed} pushed")
            if pulled:
                parts.append(f"{pulled} pulled")
            if conflicts:
                parts.append(f"{conflicts} conflicts")
            if errors:
                parts.append(f"{errors} failed")
            click.echo(f"  Done: {', '.join(parts)}")

    if is_json():
        as_json(
            {
                "path": str(sync_dir),
                "pulled": total_pulled,
                "pushed": total_pushed,
                "conflicts": total_conflicts,
                "errors": total_errors,
            }
        )

    if total_errors:
        raise SystemExit(1)


@sync.command("add")
@click.argument("file")
@click.option("--topic", "-t", "topic_id", default=None, help="Target topic ID (root or subtopic)")
def sync_add(file, topic_id):
    """Add a local file to a synced topic.

    FILE is the path to the file to add.

    If the directory is synced to exactly one root topic, that root is
    used automatically. Provide --topic to specify a subtopic of that
    root to place the item under.
    """
    filepath = Path(file).resolve()
    if not filepath.exists():
        raise SystemExit(f"File not found: {filepath}")

    sync_dir = filepath.parent
    states = SyncState.find_all_for_path(sync_dir)

    if not states and not topic_id:
        raise SystemExit(f"No synced topic found for {sync_dir}/. Run 'obris sync --topic <id>' first.")

    # Determine the root topic (state key). Explicit topic_id may be a root
    # OR a subtopic under one of the known roots.
    if states and topic_id:
        # User passed an explicit topic — figure out which root it belongs to.
        target_topic = get_topic(topic_id)
        root_id = _find_root_id(topic_id, target_topic)
        root_state_match = next(((s, rid) for s, rid in states if rid == root_id), None)
        if root_state_match is None:
            raise SystemExit(f"Topic {topic_id} is under root {root_id}, which is not synced at {sync_dir}/.")
        _root_state, root_id = root_state_match
        target_topic_id = topic_id
        topic_name = target_topic.name
    elif states:
        if len(states) > 1:
            click.echo(f"Multiple root topics sync to {sync_dir}/. Specify which with --topic <id>:")
            for _state, tid in states:
                topic = get_topic(tid)
                click.echo(f"  {topic.name} ({tid})")
            raise SystemExit(1)
        _root_state, root_id = states[0]
        target_topic_id = root_id
        topic_name = get_topic(root_id).name
    else:
        # No existing sync state but user passed --topic. Must be a root.
        target_topic = get_topic(topic_id)
        if target_topic.parent_id:
            raise SystemExit(
                f"\"{target_topic.name}\" is a subtopic. Run 'obris sync --topic <root-id>' first to set up the sync."
            )
        root_id = topic_id
        target_topic_id = topic_id
        topic_name = target_topic.name

    item = add_file(root_id, str(sync_dir), str(filepath), target_topic_id=target_topic_id)

    if is_json():
        as_json(item)
    else:
        click.echo(f'Added "{filepath.name}" to "{topic_name}"')


@sync.command("link")
@click.argument("file")
@click.option("--item", "-i", "item_id", required=True, help="Knowledge item ID to link to")
@click.option("--topic", "-t", "topic_id", default=None, help="Target topic ID (root or subtopic)")
def sync_link(file, item_id, topic_id):
    """Link a local file to an existing remote item.

    Use after renaming a file locally to reattach it to its remote item.
    """
    filepath = Path(file).resolve()
    if not filepath.exists():
        raise SystemExit(f"File not found: {filepath}")

    sync_dir = filepath.parent
    states = SyncState.find_all_for_path(sync_dir)

    if not states:
        raise SystemExit(f"No synced topic found for {sync_dir}/. Run 'obris sync -t <id>' first.")

    if topic_id:
        target_topic = get_topic(topic_id)
        root_id = _find_root_id(topic_id, target_topic)
        match = next(((s, rid) for s, rid in states if rid == root_id), None)
        if match is None:
            raise SystemExit(f"Topic {topic_id} is under root {root_id}, which is not synced at {sync_dir}/.")
        _, root_id = match
        target_topic_id = topic_id
    else:
        if len(states) > 1:
            click.echo(f"Multiple root topics sync to {sync_dir}/. Specify which with -t <id>:")
            for _state, tid in states:
                topic = get_topic(tid)
                click.echo(f"  {topic.name} ({tid})")
            raise SystemExit(1)
        _, root_id = states[0]
        target_topic_id = root_id

    link_file(root_id, str(sync_dir), str(filepath), item_id, target_topic_id=target_topic_id)
    click.echo(f'Linked "{filepath.name}" to item {item_id}')


def _resolve_targets(sync_dir, topic_id, yes):
    """Determine which topic(s) to sync.

    Returns list of (SyncState | None, topic_id, topic_name) tuples.
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


def _find_root(topic_id, topic=None):
    """Walk up parent_id pointers to find the root topic.

    Cycle-safe: visited set + depth cap. Raises SystemExit on cycle.
    """
    if topic is None:
        topic = get_topic(topic_id)
    visited = {topic_id}
    depth = 0
    while topic.parent_id:
        depth += 1
        if depth > 64:
            raise SystemExit(f"Topic ancestor chain exceeds depth 64 starting at {topic_id}")
        parent_id = topic.parent_id
        if parent_id in visited:
            raise SystemExit(f"Topic ancestor cycle detected walking up from {topic_id}")
        visited.add(parent_id)
        topic = get_topic(parent_id)
    return topic


def _find_root_id(topic_id, topic=None):
    return _find_root(topic_id, topic).id
