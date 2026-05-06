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
import pathspec
from pathspec.patterns.gitwildmatch import GitWildMatchPattern

from obris.sync.exclusions import ExclusionMatcher
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
    @click.option("--list", "list_only", is_flag=True, help="Print current settings")
    def sync_exclude(patterns, path, list_only):
        """Stop syncing files that match a pattern.

        \b
          obris sync exclude scratch/          # an entire folder
          obris sync exclude notes.draft.md    # a specific file
          obris sync exclude '*.draft.md'      # all drafts
          obris sync exclude --list            # show current settings

        Wins over any prior ``obris sync include`` for the same
        pattern, so the user-facing rule stays simple: "the last
        thing you said is what happens."
        """
        sync_dir, states = _states_for_current_dir(path)

        if list_only:
            if patterns:
                raise click.UsageError("Cannot combine --list with patterns.")
            _list_settings(states)
            return

        if not patterns:
            raise click.UsageError("Provide one or more patterns, or use --list.")

        results = _apply_pattern_action(states, patterns, action="exclude", sync_dir=sync_dir)
        _emit_outcomes(sync_dir, results, action="exclude")

    @sync.command("include")
    @click.argument("patterns", nargs=-1, required=True)
    @click.option("--path", "-p", default=".", help="Sync directory (defaults to current directory)")
    def sync_include(patterns, path):
        """Force a file or pattern to sync, overriding any exclusion.

        Use this whenever ``obris sync`` says a file is being skipped
        and you actually want it. Works whether the file was being
        excluded by a built-in default or by a prior
        ``obris sync exclude``.

        \b
          obris sync include .env.example      # sync this even though
                                                #  .env.* is excluded by default
          obris sync include scratch/draft.md  # sync one file inside an
                                                #  excluded folder
          obris sync include '*.draft.md'      # un-exclude a pattern you
                                                #  previously excluded

        Wins over any prior ``obris sync exclude`` for the same pattern
        — last call wins.
        """
        sync_dir, states = _states_for_current_dir(path)
        results = _apply_pattern_action(states, patterns, action="include", sync_dir=sync_dir)
        _emit_outcomes(sync_dir, results, action="include")

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


def _apply_pattern_action(states, patterns, *, action, sync_dir):
    """Apply ``exclude`` or ``include`` to each pattern across all states.

    Returns ``[(pattern, outcome)]`` where outcome is one of
    ``now_skipped``, ``now_synced``, ``already_skipped``,
    ``already_synced``, or ``no_effect``.

    Strict inverses with last-call-wins semantics *and* exact-cancel:
    when the new action's inverse is already in state we simply remove
    it instead of layering an opposite on top. Net effect per pattern:

    - prior ``foo`` + ``include foo``   → state minus ``foo``
    - prior ``!foo`` + ``exclude foo``  → state minus ``!foo``
    - empty + ``include foo``           → state plus ``!foo`` (only if
                                           the pattern actually matches
                                           a currently-excluded local
                                           file; otherwise ``no_effect``
                                           with no state change)
    - empty + ``exclude foo``           → state plus ``foo``

    Keeps the state at most one entry per pattern, no leftover
    re-include or exclude after a toggle, and no state bloat from
    ``include`` calls that wouldn't have changed anything.
    """
    outcomes = []
    for state, _tid in states:
        for pat in patterns:
            negated = f"!{pat}"
            current = list(state.exclude_patterns)
            if action == "exclude":
                if negated in current:
                    # Cancel a prior include — just remove the override,
                    # don't also add the exclude. Defaults re-cover the
                    # path if the override existed to override one; if
                    # not, both calls were no-ops on observable behavior.
                    state.remove_excludes([negated])
                    state.save()
                    outcomes.append((pat, "now_skipped"))
                elif pat in current:
                    outcomes.append((pat, "already_skipped"))
                else:
                    state.add_excludes([pat])
                    state.save()
                    outcomes.append((pat, "now_skipped"))
            else:
                if pat in current:
                    # Cancel a prior exclude — defaults take over.
                    state.remove_excludes([pat])
                    state.save()
                    outcomes.append((pat, "now_synced"))
                elif negated in current:
                    outcomes.append((pat, "already_synced"))
                elif _include_has_effect(sync_dir, pat, current):
                    state.add_excludes([negated])
                    state.save()
                    outcomes.append((pat, "now_synced"))
                else:
                    # No currently-excluded file matches this pattern;
                    # adding ``!pat`` would be state bloat with zero
                    # observable effect. Warn and leave state alone.
                    outcomes.append((pat, "no_effect"))
    return outcomes


def _include_has_effect(sync_dir: Path, pattern: str, current_excludes: list[str]) -> bool:
    """Return True if any local file currently excluded would match ``pattern``.

    Conservative: only files that physically exist under ``sync_dir``
    count. A pattern aimed at a file that doesn't exist yet is treated
    as no-op — the user can re-run after the file lands. Walks
    ``sync_dir`` once per call; cost is negligible compared to a real
    sync's network round trips.
    """
    matcher = ExclusionMatcher(sync_dir, state_excludes=current_excludes)
    pattern_spec = pathspec.PathSpec.from_lines(GitWildMatchPattern, [pattern])
    for path in Path(sync_dir).rglob("*"):
        if path.is_dir() or path.is_symlink():
            continue
        rel = path.relative_to(sync_dir).as_posix()
        if matcher.excludes(rel) and pattern_spec.match_file(rel):
            return True
    return False


def _emit_outcomes(sync_dir, results, *, action):
    """User-facing summary. No mention of state mechanics or `!pattern`."""
    by_outcome: dict[str, set[str]] = {}
    for pat, outcome in results:
        by_outcome.setdefault(outcome, set()).add(pat)

    changed_any = False
    if action == "exclude":
        if by_outcome.get("now_skipped"):
            click.echo(f"Skipping: {', '.join(sorted(by_outcome['now_skipped']))}")
            changed_any = True
        if by_outcome.get("already_skipped"):
            click.echo(f"Already skipping: {', '.join(sorted(by_outcome['already_skipped']))}")
    else:
        if by_outcome.get("now_synced"):
            click.echo(f"Now syncing: {', '.join(sorted(by_outcome['now_synced']))}")
            changed_any = True
        if by_outcome.get("already_synced"):
            click.echo(f"Already syncing: {', '.join(sorted(by_outcome['already_synced']))}")
        if by_outcome.get("no_effect"):
            pats = sorted(by_outcome["no_effect"])
            click.echo(f"No matching skipped file(s) for: {', '.join(pats)}", err=True)
            click.echo("  Nothing to include. Run again after the file appears, or check spelling.")

    if changed_any:
        click.echo(f"  Takes effect on next 'obris sync' in {sync_dir}/.")


def _list_settings(states):
    """Print currently-configured rules for each state, grouped by intent."""
    for state, tid in states:
        current = state.exclude_patterns
        header = f"Settings for {tid}:" if len(states) > 1 else "Current settings:"
        click.echo(header)
        if not current:
            click.echo("  (none — built-in defaults apply)")
            continue
        skips = [p for p in current if not p.startswith("!")]
        forced_syncs = [p[1:] for p in current if p.startswith("!")]
        if skips:
            click.echo("  Skipping:")
            for p in skips:
                click.echo(f"    {p}")
        if forced_syncs:
            click.echo("  Always syncing:")
            for p in forced_syncs:
                click.echo(f"    {p}")


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
