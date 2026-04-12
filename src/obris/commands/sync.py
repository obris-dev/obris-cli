from pathlib import Path

import click

from obris.api.topics import create_topic, get_topic
from obris.output import as_json, is_json
from obris.sync.commands import add_file, link_file
from obris.sync.engine import run_sync
from obris.sync.state import SyncState


@click.group("sync", invoke_without_command=True)
@click.option("--path", "-p", default=".", help="Local directory to sync (defaults to current directory)")
@click.option("--topic", "-t", "topic_id", default=None, help="Topic ID to sync")
@click.option("--item", "-i", "item_ids", multiple=True, help="Specific item IDs to sync (repeatable)")
@click.option("--dry-run", is_flag=True, help="Preview changes without modifying anything")
@click.option("-y", "--yes", is_flag=True, help="Auto-confirm prompts")
@click.pass_context
def sync(ctx, path, topic_id, item_ids, dry_run, yes):
    """Sync a local directory with an Obris topic.

    On first sync, provide --topic <id> to link to an existing topic,
    or omit it to create a new topic named after the directory.
    Subsequent syncs auto-detect the linked topic(s) from state.

    Use --item to sync specific items only. Can be repeated.
    """
    ctx.ensure_object(dict)
    ctx.obj["path"] = path
    ctx.obj["topic_id"] = topic_id

    if ctx.invoked_subcommand is not None:
        return

    sync_dir = Path(path).resolve()

    # Build list of (state, topic_id, topic_name) to sync.
    targets = _resolve_targets(sync_dir, topic_id, yes)

    total_pulled, total_pushed, total_conflicts, total_errors = 0, 0, 0, 0

    if dry_run:
        click.echo("  (dry run — no changes will be made)")

    for state, tid, topic_name in targets:
        click.echo(f'Syncing "{topic_name}" \u2194 {sync_dir}/')

        pulled, pushed, conflicts, errors = run_sync(
            tid, str(sync_dir), state=state, item_ids=item_ids or None, dry_run=dry_run
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
@click.option("--topic", "-t", "topic_id", default=None, help="Topic ID to add the file to")
def sync_add(file, topic_id):
    """Add a local file to a synced topic.

    FILE is the path to the file to add.

    If the directory is synced to exactly one topic, it's used automatically.
    Otherwise, provide --topic <id> to specify which topic.
    """
    filepath = Path(file).resolve()
    if not filepath.exists():
        raise SystemExit(f"File not found: {filepath}")

    sync_dir = filepath.parent

    if not topic_id:
        states = SyncState.find_all_for_path(sync_dir)
        if not states:
            raise SystemExit(f"No synced topic found for {sync_dir}/. Run 'obris sync --topic <id>' first.")
        if len(states) > 1:
            click.echo(f"Multiple topics sync to {sync_dir}/. Specify which with --topic <id>:")
            for _state, tid in states:
                topic = get_topic(tid)
                click.echo(f"  {topic.get('name', tid)} ({tid})")
            raise SystemExit(1)
        _, topic_id = states[0]

    topic = get_topic(topic_id)
    topic_name = topic.get("name", topic_id)
    item = add_file(topic_id, str(sync_dir), str(filepath))

    if is_json():
        as_json(item)
    else:
        click.echo(f'Added "{filepath.name}" to "{topic_name}"')


@sync.command("link")
@click.argument("file")
@click.option("--item", "-i", "item_id", required=True, help="Knowledge item ID to link to")
@click.option("--topic", "-t", "topic_id", default=None, help="Topic ID (auto-detected if one topic syncs here)")
def sync_link(file, item_id, topic_id):
    """Link a local file to an existing remote item.

    Use after renaming a file locally to reattach it to its remote item.
    """
    filepath = Path(file).resolve()
    if not filepath.exists():
        raise SystemExit(f"File not found: {filepath}")

    sync_dir = filepath.parent

    if not topic_id:
        states = SyncState.find_all_for_path(sync_dir)
        if not states:
            raise SystemExit(f"No synced topic found for {sync_dir}/. Run 'obris sync -t <id>' first.")
        if len(states) > 1:
            click.echo(f"Multiple topics sync to {sync_dir}/. Specify which with -t <id>:")
            for _state, tid in states:
                topic = get_topic(tid)
                click.echo(f"  {topic.get('name', tid)} ({tid})")
            raise SystemExit(1)
        _, topic_id = states[0]

    link_file(topic_id, str(sync_dir), str(filepath), item_id)
    click.echo(f'Linked "{filepath.name}" to item {item_id}')


def _resolve_targets(sync_dir, topic_id, yes):
    """Determine which topic(s) to sync.

    Returns list of (SyncState | None, topic_id, topic_name) tuples.
    """
    if topic_id:
        state = SyncState.load(topic_id, sync_dir)
        topic = get_topic(topic_id)
        return [(state, topic_id, topic.get("name", topic_id))]

    states = SyncState.find_all_for_path(sync_dir)

    if states:
        targets = []
        for state, tid in states:
            topic = get_topic(tid)
            targets.append((state, tid, topic.get("name", tid)))
        return targets

    topic_name = sync_dir.name
    if not yes:
        click.confirm(f'Create topic "{topic_name}" and sync to {sync_dir}/?', default=True, abort=True)
    topic = create_topic(topic_name)
    tid = topic["id"]
    click.echo(f'Created topic "{topic_name}"')
    return [(None, tid, topic_name)]
