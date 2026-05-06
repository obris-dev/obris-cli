"""Local-only dry-run preview for first-time syncs.

Used when the user runs ``obris sync --dry-run`` against a directory
that has no linked topic yet — ``resolve_targets`` returns an empty
target list rather than creating a phantom topic on the server, and
the sync command falls through to this preview helper instead of
the regular ``run_sync_pass``.

Side-effect free: walks the dir using a synthetic ``SyncState`` so
the same exclusion + symlink + tracked-name logic runs as on a real
sync. Reports what ``create_topic``, ``_ensure_subtopic_path``, and
``add_all`` *would* do without touching the server.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import click

from obris.sync.scanner import find_untracked
from obris.sync.state import SyncState


def preview_first_sync(sync_dir: Path, *, add_all_files: bool, allow_subtopics: bool) -> dict:
    """Render a local-only preview of what a first sync would create.

    Output sections (each only emitted when non-empty):

    - the would-be root topic name
    - the subtopic structure that would be mirrored from local subdirs
    - untracked files (gated on ``--add-all`` and ``--no-subtopics``)
    - ignored files (always shown — user explicitly asked for the full picture)
    - symlinks (always shown)

    Returns the same totals dict shape as ``run_sync_pass`` so the
    JSON output stays consistent across both code paths.
    """
    sync_dir = Path(sync_dir).resolve()
    topic_name = sync_dir.name
    click.echo("  (dry run — no changes will be made)")
    click.echo(f'  Would create topic "{topic_name}" at {sync_dir}/')

    synthetic = SyncState("__preview__", str(sync_dir))
    scan = find_untracked(sync_dir, [(synthetic, "__preview__")])

    # Subtopic projection: every directory segment under sync_dir that
    # contains an untracked file would become a subtopic level. Mirrors
    # the cache walk in ``scanner._ensure_subtopic_path``.
    subdirs: set[str] = set()
    skipped_subdir = 0
    if allow_subtopics:
        for rel in scan.untracked:
            rel_dir = str(PurePosixPath(rel).parent)
            if rel_dir == ".":
                continue
            walked = ""
            for seg in rel_dir.split("/"):
                walked = f"{walked}/{seg}" if walked else seg
                subdirs.add(walked)
    else:
        skipped_subdir = sum(1 for rel in scan.untracked if "/" in rel)

    if subdirs:
        click.echo(f"\nWould create {len(subdirs)} subtopic(s):")
        for sd in sorted(subdirs):
            click.echo(f"  {sd}/")

    if scan.untracked:
        if not add_all_files:
            click.echo(f"\n{len(scan.untracked)} untracked file(s) (would NOT add — re-run with --add-all):")
            _print_all(scan.untracked)
        elif not allow_subtopics:
            top_level = [r for r in scan.untracked if "/" not in r]
            click.echo(f"\nWould add {len(top_level)} top-level file(s):")
            _print_all(top_level)
            if skipped_subdir:
                click.echo(f"\nWould skip {skipped_subdir} file(s) in subdirs (--no-subtopics):")
                _print_all([r for r in scan.untracked if "/" in r])
        else:
            click.echo(f"\nWould add {len(scan.untracked)} file(s):")
            _print_all(scan.untracked)

    if scan.excluded:
        click.echo(f"\n{len(scan.excluded)} file(s) matched ignore rules:")
        _print_all(scan.excluded)

    if scan.symlinks:
        click.echo(f"\n{len(scan.symlinks)} symlink(s) skipped:")
        _print_all([f"{p} -> {t}" for p, t in scan.symlinks])

    return {
        "pulled": 0,
        "pushed": 0,
        "conflicts": 0,
        "errors": 0,
        "untracked": list(scan.untracked),
        "excluded_count": len(scan.excluded),
        "symlinks": [{"path": p, "target": t} for p, t in scan.symlinks],
        "conflicts_pending": [],
        "missing_local": [],
        "skipped_by_include": [],
    }


def _print_all(items):
    """Print every item, one per line, indented."""
    for line in items:
        click.echo(f"  {line}")
