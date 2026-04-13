"""Foreground watch loop used by `obris sync --watch`.

Runs a supplied ``run_once`` callable on an interval. Transient errors
from a single iteration are logged and swallowed so a flaky network
doesn't kill the loop.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import click

from .resolver import SubtopicTargetError


def run_watch_loop(*, run_once: Callable[[], dict], interval: int) -> None:
    """Loop ``run_once`` every ``interval`` seconds until interrupted.

    ``run_once`` is expected to return a totals dict (unused here) or
    raise. KeyboardInterrupt and SubtopicTargetError propagate so the
    caller can print a clean message and exit — the latter would
    otherwise fail every iteration forever (e.g. if a target gets
    reparented mid-watch).
    """
    while True:
        try:
            run_once()
        except (KeyboardInterrupt, SubtopicTargetError):
            raise
        except (Exception, SystemExit) as e:
            # SystemExit is how the CLI signals recoverable errors
            # (auth refresh failure, state corruption, ...). Swallow it
            # here so the watch loop matches the daemon's behavior —
            # one bad iteration shouldn't kill the watcher.
            click.echo(f"  Watch iteration failed: {type(e).__name__}: {e}", err=True)
        time.sleep(interval)
