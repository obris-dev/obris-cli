"""Shared one-pass sync runner used by both the single-shot command and
the foreground/background watch loops.

Kept out of ``obris.commands.sync`` so that (a) the watch loop and the
command share the exact same per-iteration behavior and (b) the command
file stays under the 300-line cap.
"""

from __future__ import annotations

from pathlib import Path

import click

from obris.api.topics import fetch_subtree, get_topic
from obris.sync.engine import run_sync
from obris.sync.resolver import SubtopicTargetError, find_root


def run_sync_pass(
    sync_dir: Path,
    targets,
    item_ids,
    patterns,
    *,
    dry_run: bool,
    quiet_if_clean: bool,
) -> dict:
    """Run one sync pass over every target; returns aggregate totals.

    ``quiet_if_clean`` suppresses the per-target "Syncing ↔ /" header and
    "Everything up to date" line when nothing changed — used by the watch
    loop to keep steady-state polling silent.
    """
    totals = {"pulled": 0, "pushed": 0, "conflicts": 0, "errors": 0}

    if dry_run:
        click.echo("  (dry run — no changes will be made)")

    for state, tid, topic_name in targets:
        topic = get_topic(tid)
        if topic.parent_id:
            root = find_root(tid)
            raise SubtopicTargetError(
                f'"{topic_name}" is a subtopic of "{root.name}". '
                f"Sync from the root topic instead:\n"
                f"  obris sync --topic {root.id} --path {sync_dir}"
            )

        try:
            subtree = fetch_subtree(tid)
        except Exception as e:
            click.echo(f'Syncing "{topic_name}" \u2194 {sync_dir}/')
            click.echo(f"  Error fetching subtree: {type(e).__name__}: {e}", err=True)
            totals["errors"] += 1
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
        totals["pulled"] += pulled
        totals["pushed"] += pushed
        totals["conflicts"] += conflicts
        totals["errors"] += errors

        clean = not (pulled or pushed or conflicts or errors)
        if clean and quiet_if_clean:
            continue

        click.echo(f'Syncing "{topic_name}" \u2194 {sync_dir}/')
        if clean:
            click.echo("  Everything up to date.")
            continue
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

    return totals
