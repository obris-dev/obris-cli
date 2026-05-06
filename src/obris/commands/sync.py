from pathlib import Path

import click

from obris.api.topics import get_topic
from obris.commands.sync_config import register as _register_config_subcommands
from obris.commands.sync_conflicts import register as _register_conflicts_subgroup
from obris.output import as_json, is_json
from obris.sync.commands import add_file, link_file
from obris.sync.resolver import assert_all_roots, find_root_id, resolve_targets
from obris.sync.runner import preview_first_sync, run_sync_pass
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
@click.option("--add-all", "add_all_files", is_flag=True, help="Upload every untracked local file after syncing.")
@click.option(
    "--no-create",
    "no_create",
    is_flag=True,
    help="Error instead of creating a root topic when the directory has no sync state.",
)
@click.option(
    "--no-subtopics",
    "no_subtopics",
    is_flag=True,
    help="With --add-all, skip files in subdirs instead of creating matching subtopics.",
)
@click.option("-v", "--verbose", "verbose", is_flag=True, help="List every untracked / excluded / symlink path.")
@click.pass_context
def sync(ctx, path, topic_id, item_ids, include_patterns, dry_run, add_all_files, no_create, no_subtopics, verbose):
    """Sync a local directory with an Obris root topic and its subtopics.

    On first sync, provide --topic <id> to link to an existing root topic,
    or omit it to create a new root topic named after the directory.
    Subsequent syncs auto-detect the linked topic from state.

    Only root topics (topics with no parent) can be sync targets. Child
    topics appear as subdirectories of their root. If you pass a child
    topic ID, the command will tell you the root to use instead.

    Use --include to sync only matching subtopics. Patterns OR together.
    Use --item to sync specific items only.

    --add-all uploads every untracked file under the synced directory,
    creating subtopics on the server to mirror local subdir structure.
    """
    ctx.ensure_object(dict)
    ctx.obj["path"] = path
    ctx.obj["topic_id"] = topic_id

    if ctx.invoked_subcommand is not None:
        return

    sync_dir = Path(path).resolve()
    patterns = list(include_patterns) if include_patterns else None

    targets = resolve_targets(sync_dir, topic_id, no_create=no_create, dry_run=dry_run)

    if not targets:
        # dry-run + no state + no --topic: preview the bootstrap +
        # initial-add locally without creating a phantom server topic.
        totals = preview_first_sync(
            sync_dir,
            add_all_files=add_all_files,
            allow_subtopics=not no_subtopics,
        )
    else:
        assert_all_roots(targets, sync_dir)
        totals = run_sync_pass(
            sync_dir,
            targets,
            item_ids,
            patterns,
            dry_run=dry_run,
            add_all_files=add_all_files,
            allow_subtopics=not no_subtopics,
            verbose=verbose,
        )

    if is_json():
        as_json(
            {
                "path": str(sync_dir),
                "pulled": totals["pulled"],
                "pushed": totals["pushed"],
                "conflicts": totals["conflicts"],
                "errors": totals["errors"],
                "untracked": totals["untracked"],
                "excluded_count": totals["excluded_count"],
                "symlinks": totals["symlinks"],
                "conflicts_pending": totals["conflicts_pending"],
                "missing_local": totals["missing_local"],
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


# Per-checkout configuration subcommands (exclude / include / untrack)
# and the conflicts subgroup live in separate modules to keep this
# file under the 300-line cap.
_register_config_subcommands(sync)
_register_conflicts_subgroup(sync)
