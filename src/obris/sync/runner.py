"""One-pass sync runner used by the sync command."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import click

from obris.api.topics import get_topic
from obris.sync.engine import run_sync
from obris.sync.engine.filters import any_match
from obris.sync.resolver import find_root
from obris.sync.scanner import add_all, find_untracked
from obris.sync.state import SyncState

_LIST_PREVIEW = 10


def run_sync_pass(
    sync_dir: Path,
    targets,
    item_ids,
    patterns,
    *,
    dry_run: bool,
    add_all_files: bool = False,
    allow_subtopics: bool = True,
    verbose: bool = False,
) -> dict:
    """Run one sync pass over every target; returns aggregate totals.

    After the remote-iteration pass, scans ``sync_dir`` for untracked
    files and surfaces them. With ``add_all_files=True``, uploads
    each one (creating subtopics for subdirs unless
    ``allow_subtopics=False``).

    Return shape is the dict the JSON output mirrors: counts plus
    ``untracked``, ``excluded_count``, ``symlinks``,
    ``conflicts_pending``, and ``missing_local`` lists.
    """
    totals = {
        "pulled": 0,
        "pushed": 0,
        "conflicts": 0,
        "errors": 0,
        "untracked": [],
        "excluded_count": 0,
        "symlinks": [],
        "conflicts_pending": [],
        "missing_local": [],
        "skipped_by_include": [],
    }

    if dry_run:
        click.echo("  (dry run — no changes will be made)")

    for state, tid, topic_name in targets:
        topic = get_topic(tid)
        if topic.parent_id:
            root = find_root(tid)
            raise SystemExit(
                f'"{topic_name}" is a subtopic of "{root.name}". '
                f"Sync from the root topic instead:\n"
                f"  obris sync --topic {root.id} --path {sync_dir}"
            )

        pulled, pushed, conflicts, errors, missing_local = run_sync(
            tid,
            str(sync_dir),
            state=state,
            item_ids=item_ids or None,
            include_patterns=patterns,
            dry_run=dry_run,
        )
        totals["pulled"] += pulled
        totals["pushed"] += pushed
        totals["conflicts"] += conflicts
        totals["errors"] += errors
        totals["missing_local"].extend(missing_local)

        clean = not (pulled or pushed or conflicts or errors)
        click.echo(f'Syncing "{topic_name}" \u2194 {sync_dir}/')
        if clean:
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

    # Untracked-file scan after remote iteration. Re-load state so
    # we see the freshest view (engine.run_sync calls state.save).
    fresh_states = SyncState.find_all_for_path(sync_dir)
    if not fresh_states:
        return totals
    scan = find_untracked(sync_dir, fresh_states)

    # When --add-all is combined with --include, the bulk-add should
    # honor the same scope the rest of the sync uses — pull, push,
    # tracked-item dispatch, remote-deleted detection all already
    # respect ``patterns``. ``find_untracked`` doesn't see the patterns,
    # so we partition its result here. Files outside the include scope
    # are surfaced separately so the user knows they were skipped on
    # purpose, not silently dropped.
    out_of_include_scope: list[str] = []
    if add_all_files and patterns and scan.untracked:
        in_scope, out_of_include_scope = _partition_by_include(scan.untracked, patterns)
        scan.untracked = in_scope

    totals["untracked"] = list(scan.untracked)
    totals["excluded_count"] = len(scan.excluded)
    totals["symlinks"] = [{"path": p, "target": t} for p, t in scan.symlinks]
    totals["skipped_by_include"] = list(out_of_include_scope)
    for state, _tid in fresh_states:
        for kid, meta in state.conflicts.items():
            entry = state.get(kid)
            if not entry:
                continue
            rel = state.get_topic_dir(entry.topic_id) if entry.topic_id else ""
            totals["conflicts_pending"].append(
                {
                    "file": (f"{rel}/{entry.filename}" if rel else entry.filename),
                    "knowledge_id": kid,
                    "detected_at": meta.get("detected_at"),
                    "remote_updated_at": meta.get("remote_updated_at"),
                }
            )
    _emit_scan(scan, sync_dir, add_all_files, dry_run=dry_run, verbose=verbose)

    if out_of_include_scope:
        cap = None if verbose else _LIST_PREVIEW
        click.echo(f"\nSkipped {len(out_of_include_scope)} untracked file(s) outside --include scope:")
        _print_capped(out_of_include_scope, cap)

    if add_all_files and scan.untracked and not dry_run:
        # All targets share the same sync_dir; bulk-add against the
        # first state's root. Multi-root dirs are an edge case we
        # don't optimize for here.
        first_state, root_id = fresh_states[0]
        counts = add_all(
            first_state,
            root_id,
            sync_dir,
            scan.untracked,
            allow_subtopics=allow_subtopics,
        )
        click.echo(
            f"\nAdded {counts['added']} file(s)"
            + (f", skipped {counts['skipped_subdir']} in subdirs" if counts["skipped_subdir"] else "")
            + (f", {counts['errors']} errors" if counts["errors"] else "")
            + "."
        )
        totals["pushed"] += counts["added"]
        totals["errors"] += counts["errors"]

    return totals


def _emit_scan(scan, sync_dir, add_all_files, *, dry_run=False, verbose=False):
    if not scan.untracked and not scan.symlinks and not (verbose and scan.excluded):
        return
    cap = None if verbose else _LIST_PREVIEW
    if scan.untracked:
        # Output is shaped by the (dry_run, add_all_files) combination so
        # the user always knows whether the listed files would actually
        # be uploaded:
        #   dry-run + --add-all  → preview header ("Would add ...")
        #   dry-run, no --add-all → preview header ("would not add")
        #   live    + --add-all  → silent here (the real add path prints
        #                          its own "Added N file(s)" summary)
        #   live, no --add-all   → the existing "Choose how to proceed"
        #                          prompt with the add/skip recipes.
        if dry_run and add_all_files:
            click.echo(f"\nWould add {len(scan.untracked)} file(s):")
            _print_capped(scan.untracked, cap)
        elif dry_run:
            click.echo(f"\n{len(scan.untracked)} untracked file(s) (would not add — re-run with --add-all):")
            _print_capped(scan.untracked, cap)
        elif not add_all_files:
            click.echo(f"\n{len(scan.untracked)} untracked file(s) in {sync_dir}/:")
            _print_capped(scan.untracked, cap)
            click.echo("  Choose how to proceed:")
            click.echo("    Upload all:   obris sync --add-all")
            click.echo("    Upload some:  obris sync add <file>...")
            click.echo("    Skip some:    obris sync exclude <pattern>...")
    if scan.symlinks:
        click.echo(f"\n{len(scan.symlinks)} symlink(s) skipped:")
        _print_capped([f"{p} -> {t}" for p, t in scan.symlinks], cap)
    if verbose and scan.excluded:
        click.echo(f"\n{len(scan.excluded)} file(s) matched ignore rules:")
        _print_capped(scan.excluded, cap)


def _partition_by_include(rels: list[str], patterns: list[str]) -> tuple[list[str], list[str]]:
    """Split untracked rel-paths by whether their parent dir is in --include scope.

    A file's parent directory becomes (or maps to) a subtopic name path
    when ``--add-all`` runs; we test the same name path against the
    patterns the engine already evaluates against the remote subtree.
    Root-level files (parent is ``"."``) test against an empty segment
    list — patterns like ``Projects/**`` won't match, which mirrors
    the engine's own behaviour where the root topic isn't in
    ``matched_ids`` when patterns are set.
    """
    in_scope: list[str] = []
    out_of_scope: list[str] = []
    for rel in rels:
        rel_dir = str(PurePosixPath(rel).parent)
        segments = [] if rel_dir == "." else [s for s in rel_dir.split("/") if s]
        if any_match(segments, patterns):
            in_scope.append(rel)
        else:
            out_of_scope.append(rel)
    return in_scope, out_of_scope


def _print_capped(items, cap):
    """Print at most ``cap`` items, then a "... N more" line. None = no cap."""
    shown = items if cap is None else items[:cap]
    for line in shown:
        click.echo(f"  {line}")
    if cap is not None and len(items) > cap:
        click.echo(f"  ... ({len(items) - cap} more)")
