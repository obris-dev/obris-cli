from pathlib import Path

import click

from obris.api.topics import get_topic
from obris.output import as_json, is_json
from obris.sync.commands import add_file, link_file
from obris.sync.daemon import (
    DaemonError,
    run_watcher_from_config,
    spawn_background_watcher,
)
from obris.sync.daemon_control import daemon_info, read_daemon_log_tail, stop_daemon
from obris.sync.resolver import SubtopicTargetError, assert_all_roots, find_root_id, resolve_targets
from obris.sync.runner import run_sync_pass
from obris.sync.state import SyncState
from obris.sync.watch import run_watch_loop


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
@click.option(
    "--watch",
    "watch",
    is_flag=True,
    help="Keep syncing on an interval until interrupted (Ctrl-C).",
)
@click.option(
    "--interval",
    "interval",
    type=click.IntRange(min=5),
    default=30,
    show_default=True,
    help="Seconds between watch iterations. Minimum 5.",
)
@click.option(
    "--background",
    "background",
    is_flag=True,
    help="With --watch, detach and run as a background daemon. Manage with 'obris sync status' and 'obris sync stop'.",
)
@click.pass_context
def sync(ctx, path, topic_id, item_ids, include_patterns, dry_run, yes, watch, interval, background):
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

    if background and not watch:
        raise click.UsageError("--background requires --watch.")
    if dry_run and watch:
        raise click.UsageError("--dry-run cannot be combined with --watch.")

    sync_dir = Path(path).resolve()
    patterns = list(include_patterns) if include_patterns else None

    targets = resolve_targets(sync_dir, topic_id, yes)
    # Preflight subtopic check for all three paths (single-pass,
    # foreground watch, background watch). Without this, the foreground
    # watch would log the same "subtopic" error every iteration forever,
    # and the background watcher would silently start but never progress.
    assert_all_roots(targets, sync_dir)

    if background:
        try:
            info = spawn_background_watcher(
                sync_dir=sync_dir,
                targets=[(tid, name) for _state, tid, name in targets],
                item_ids=list(item_ids) if item_ids else None,
                include_patterns=patterns,
                interval=interval,
            )
        except DaemonError as e:
            raise SystemExit(str(e)) from e
        click.echo(f"Watching {sync_dir}/ every {interval}s in background (pid {info['pid']}).")
        click.echo(f"  Log:  {info['log']}")
        click.echo(f"  Stop: obris sync stop -p {sync_dir}")
        return

    if watch:
        click.echo(f"Watching {sync_dir}/ every {interval}s. Press Ctrl-C to stop.")
        try:
            run_watch_loop(
                run_once=lambda: run_sync_pass(
                    sync_dir,
                    targets,
                    item_ids,
                    patterns,
                    dry_run=False,
                    quiet_if_clean=True,
                ),
                interval=interval,
            )
        except KeyboardInterrupt:
            click.echo("\nStopped.")
        except SubtopicTargetError as e:
            # Mid-watch reparent: exit cleanly with the same message
            # format as the preflight, instead of spinning.
            raise SystemExit(str(e)) from None
        return

    totals = run_sync_pass(
        sync_dir,
        targets,
        item_ids,
        patterns,
        dry_run=dry_run,
        quiet_if_clean=False,
    )

    if is_json():
        as_json(
            {
                "path": str(sync_dir),
                "pulled": totals["pulled"],
                "pushed": totals["pushed"],
                "conflicts": totals["conflicts"],
                "errors": totals["errors"],
            }
        )

    if totals["errors"]:
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
        root_id = find_root_id(topic_id, target_topic)
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
        root_id = find_root_id(topic_id, target_topic)
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


@sync.command("status")
@click.option("--path", "-p", default=".", help="Local directory to check (defaults to current directory)")
@click.option("--log-lines", "log_lines", type=int, default=10, show_default=True, help="Tail of log lines to print.")
def sync_status(path, log_lines):
    """Show background watcher status for a synced directory."""
    sync_dir = Path(path).resolve()
    info = daemon_info(sync_dir)
    if info is None:
        click.echo(f"No background watcher for {sync_dir}/.")
        return
    click.echo(f"Watcher for {sync_dir}/")
    click.echo(f"  PID:      {info['pid']} ({'running' if info['alive'] else 'dead — stale pidfile'})")
    click.echo(f"  Started:  {info.get('started_at', '?')}")
    click.echo(f"  Interval: {info.get('interval', '?')}s")
    topics = info.get("topics") or []
    if topics:
        click.echo("  Topics:")
        for t in topics:
            click.echo(f"    {t['name']} ({t['id']})")
    click.echo(f"  Log:      {info['log']}")
    if log_lines:
        tail = read_daemon_log_tail(sync_dir, log_lines)
        if tail:
            click.echo("  Last log:")
            for line in tail:
                click.echo(f"    {line}")


@sync.command("stop")
@click.option("--path", "-p", default=".", help="Local directory whose watcher to stop")
def sync_stop(path):
    """Stop a background sync watcher."""
    sync_dir = Path(path).resolve()
    stopped = stop_daemon(sync_dir)
    if stopped is None:
        click.echo(f"No background watcher for {sync_dir}/.")
        return
    click.echo(f"Stopped watcher (pid {stopped}) for {sync_dir}/.")


@sync.command("_watcher", hidden=True)
@click.argument("config_path")
def sync_watcher_entry(config_path):
    """Internal entry point launched by `--background`. Do not call directly."""
    run_watcher_from_config(Path(config_path))
