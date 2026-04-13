"""Read-side and stop-side helpers for the sync background watcher.

Split from ``daemon.py`` so the spawner module (which owns fork/spawn
and the ``_watch_main`` loop) stays under the 300-line file cap.
"""

from __future__ import annotations

import contextlib
import os
import signal
import time
from pathlib import Path

import click

from .daemon import _logfile, _pid_alive, _pidfile, _read_pidfile


def daemon_info(sync_dir: Path) -> dict | None:
    """Return metadata about a watcher for ``sync_dir``, or None."""
    info = _read_pidfile(_pidfile(sync_dir))
    if not info:
        return None
    pid = int(info.get("pid", 0))
    info["alive"] = _pid_alive(pid) if pid else False
    info.setdefault("log", str(_logfile(sync_dir)))
    return info


def read_daemon_log_tail(sync_dir: Path, n_lines: int) -> list[str]:
    log = _logfile(sync_dir)
    if not log.exists():
        return []
    try:
        lines = log.read_text().splitlines()
    except OSError:
        return []
    return lines[-n_lines:]


def stop_daemon(sync_dir: Path) -> int | None:
    """Stop the watcher for ``sync_dir``. Returns the killed pid, or None.

    Sends SIGTERM, waits briefly for the process to exit (the daemon's
    atexit handler clears the pidfile). Falls back to SIGKILL if the
    process ignores SIGTERM. A stale pidfile is removed quietly.
    """
    pidfile = _pidfile(sync_dir)
    info = _read_pidfile(pidfile)
    if not info:
        return None
    pid = int(info.get("pid", 0))
    if not pid or not _pid_alive(pid):
        pidfile.unlink(missing_ok=True)
        return None

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pidfile.unlink(missing_ok=True)
        return pid

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            break
        time.sleep(0.1)
    else:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
        click.echo(f"Watcher {pid} did not exit on SIGTERM; sent SIGKILL.", err=True)

    pidfile.unlink(missing_ok=True)
    return pid
