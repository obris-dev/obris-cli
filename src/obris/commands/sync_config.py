"""Per-checkout sync configuration subcommands.

Hosts ``exclude`` / ``include`` / ``untrack`` — commands that modify
state-file metadata for a synced directory. Kept out of
``commands.sync`` so the sync group definition + invocation logic
stays under the 300-line cap and these subcommands stay together
because they share the ``_states_for_current_dir`` resolver.
"""

from __future__ import annotations

from pathlib import Path

import click

from obris.sync.state import SyncState


def _states_for_current_dir(path):
    """Return ``(sync_dir, states)`` for ``path``, exiting cleanly if unsynced."""
    sync_dir = Path(path).resolve()
    states = SyncState.find_all_for_path(sync_dir)
    if not states:
        raise SystemExit(f"No synced topic found for {sync_dir}/. Run 'obris sync --topic <id>' first.")
    return sync_dir, states


def register(sync):
    """Attach the config subcommands to the given Click group."""

    @sync.command("exclude")
    @click.argument("patterns", nargs=-1)
    @click.option("--path", "-p", default=".", help="Sync directory (defaults to current directory)")
    @click.option("--list", "list_only", is_flag=True, help="Print current exclude patterns and exit")
    def sync_exclude(patterns, path, list_only):
        """Add file patterns to skip during sync.

        Patterns use gitignore-style syntax. Examples:

        \b
          obris sync exclude '*.draft.md'      # any markdown draft
          obris sync exclude scratch/          # entire directory
          obris sync exclude notes/private.md  # specific file
          obris sync exclude --list            # show current patterns

        Patterns apply to all topics syncing this directory. Idempotent —
        adding a pattern twice is a no-op. Remove patterns with
        'obris sync include <pattern>'.
        """
        sync_dir, states = _states_for_current_dir(path)

        if list_only:
            if patterns:
                raise click.UsageError("Cannot combine --list with patterns.")
            for state, tid in states:
                current = state.exclude_patterns
                header = f"Excludes for {tid}:" if len(states) > 1 else "Current excludes:"
                click.echo(header)
                if not current:
                    click.echo("  (none)")
                else:
                    for p in current:
                        click.echo(f"  {p}")
            return

        if not patterns:
            raise click.UsageError("Provide one or more patterns, or use --list.")

        added_total = []
        for state, _tid in states:
            added = state.add_excludes(patterns)
            if added:
                state.save()
                added_total.extend(added)

        unique_added = sorted(set(added_total))
        skipped = sorted(set(patterns) - set(unique_added))
        if unique_added:
            click.echo(f"Added {len(unique_added)} pattern(s): {', '.join(unique_added)}")
            click.echo(f"  Excludes apply on next 'obris sync' in {sync_dir}/.")
        if skipped:
            click.echo(f"Already present: {', '.join(skipped)}")

    @sync.command("include")
    @click.argument("patterns", nargs=-1, required=True)
    @click.option("--path", "-p", default=".", help="Sync directory (defaults to current directory)")
    def sync_include(patterns, path):
        """Remove file patterns from the exclude list (re-enable syncing).

        Inverse of 'obris sync exclude'. Idempotent — removing a pattern
        that isn't present is a no-op with a notice.

          obris sync include '*.draft.md'
        """
        sync_dir, states = _states_for_current_dir(path)

        removed_total = []
        for state, _tid in states:
            removed = state.remove_excludes(patterns)
            if removed:
                state.save()
                removed_total.extend(removed)

        unique_removed = sorted(set(removed_total))
        not_present = sorted(set(patterns) - set(unique_removed))
        if unique_removed:
            click.echo(f"Removed {len(unique_removed)} pattern(s): {', '.join(unique_removed)}")
            click.echo(f"  Will sync on next 'obris sync' in {sync_dir}/.")
        if not_present:
            click.echo(f"Not in exclude list: {', '.join(not_present)}")

    @sync.command("untrack")
    @click.argument("targets", nargs=-1, required=True)
    @click.option("--path", "-p", default=".", help="Sync directory (defaults to current directory)")
    def sync_untrack(targets, path):
        """Stop syncing items without deleting either side.

        Each TARGET is a knowledge ID or a tracked filename (basename).
        Removes the sync link; both the local file and the remote item stay
        in place. Subsequent 'obris sync' calls will not re-pull these items.

        \b
          obris sync untrack abc123
          obris sync untrack notes.md draft.md

        Re-link later with 'obris sync link <file> -i <id>' or 'obris sync add'.
        Permanently delete the remote with 'obris knowledge delete <id>'.
        """
        sync_dir, states = _states_for_current_dir(path)

        untracked = []
        not_found = []
        for target in targets:
            matches = _resolve_target(target, states)
            if not matches:
                not_found.append(target)
                continue
            if len(matches) > 1:
                click.echo(f"Ambiguous: '{target}' matches multiple tracked items:")
                for state, kid in matches:
                    entry = state.get(kid)
                    click.echo(f"  {kid}  ({entry.filename})")
                click.echo("  Re-run with the specific knowledge ID.")
                raise SystemExit(1)
            state, kid = matches[0]
            entry = state.get(kid)
            state.untrack(kid)
            state.mark_unlinked(kid)
            state.save()
            untracked.append((kid, entry.filename))

        if untracked:
            click.echo(f"Untracked {len(untracked)} item(s):")
            for kid, name in untracked:
                click.echo(f"  {name}  ({kid})")
            click.echo(f"  Local files and remote items unchanged in {sync_dir}/.")
        if not_found:
            click.echo(f"Not tracked: {', '.join(not_found)}", err=True)
            raise SystemExit(1)


def _resolve_target(target, states):
    """Resolve ``target`` (kid or filename) to a list of (state, kid) matches.

    Filename lookup is by basename only (matches TrackedItem.filename).
    Returns a list because the same filename can exist under different
    topics in the same dir; the caller decides whether to error on
    ambiguity.
    """
    matches = []
    for state, _tid in states:
        if state.is_tracked(target):
            matches.append((state, target))
            continue
        kid, _entry = state.find_by_filename(target)
        if kid:
            matches.append((state, kid))
    return matches
