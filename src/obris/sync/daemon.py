"""Background watcher daemon for `obris sync --watch --background`.

One watcher per resolved sync directory. Pidfile + log live under
``~/.obris/sync-daemons/<hash>.{pid,log}`` keyed by the resolved path
so multiple independent watchers can run concurrently.

The watcher is spawned via ``subprocess.Popen(start_new_session=True)``
(one fork + exec + setsid) so the shell can be closed without taking
the watcher down. On shutdown (SIGTERM or clean exit) the pidfile is
removed via atexit.
"""

from __future__ import annotations

import atexit
import contextlib
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import click
from filelock import FileLock, Timeout

from obris.config import CONFIG_DIR

from .mapping import now_iso
from .resolver import SubtopicTargetError
from .runner import run_sync_pass
from .state import SyncState

DAEMON_DIR = CONFIG_DIR / "sync-daemons"
_PID_WAIT_SECONDS = 5.0
_PID_POLL_INTERVAL = 0.1


class DaemonError(RuntimeError):
    """Base class for daemon spawn/lifecycle errors."""


class DaemonAlreadyRunning(DaemonError):
    """A watcher is already running for the target directory."""


class DaemonStartupError(DaemonError):
    """The watcher subprocess failed to come up (crash, timeout, race)."""


class _ShutdownSignal(BaseException):
    """Raised from the SIGTERM handler to unwind ``_watch_main`` cleanly.

    Subclasses BaseException so the inner ``except (Exception,
    SystemExit)`` can't swallow it.
    """


def _daemon_key(sync_dir: Path) -> str:
    return hashlib.sha256(str(sync_dir.resolve()).encode()).hexdigest()[:16]


def _pidfile(sync_dir: Path) -> Path:
    return DAEMON_DIR / f"{_daemon_key(sync_dir)}.pid"


def _logfile(sync_dir: Path) -> Path:
    return DAEMON_DIR / f"{_daemon_key(sync_dir)}.log"


def _read_pidfile(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _config_path(sync_dir: Path) -> Path:
    return DAEMON_DIR / f"{_daemon_key(sync_dir)}.config.json"


def spawn_background_watcher(
    *,
    sync_dir: Path,
    targets: list[tuple[str, str]],
    item_ids: list[str] | None,
    include_patterns: list[str] | None,
    interval: int,
) -> dict:
    """Spawn a detached watcher subprocess for ``sync_dir``.

    We use ``subprocess.Popen(start_new_session=True)`` rather than
    ``os.fork()`` because macOS aborts forked children that touch
    libraries tied to CoreFoundation/ObjC (which httpx + its SSL stack
    pull in). A fresh interpreter via Popen sidesteps that class of
    bug and keeps the watcher independent of the parent's imported
    state.

    Returns ``{"pid": int, "log": str}`` once the child has written
    its pidfile.
    """
    DAEMON_DIR.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        DAEMON_DIR.chmod(0o700)

    pidfile = _pidfile(sync_dir)
    logfile = _logfile(sync_dir)
    configfile = _config_path(sync_dir)
    lock_path = DAEMON_DIR / f"{_daemon_key(sync_dir)}.lock"

    # Advisory file lock serializes the "check → spawn → record"
    # critical section so two concurrent `--background` invocations
    # for the same directory can't both pass the liveness check.
    try:
        with FileLock(str(lock_path), timeout=5):
            existing = _read_pidfile(pidfile)
            if existing and _pid_alive(int(existing.get("pid", 0))):
                raise DaemonAlreadyRunning(
                    f"A background watcher is already running for {sync_dir}/ "
                    f"(pid {existing['pid']}). Stop it with 'obris sync stop -p {sync_dir}'."
                )
            pidfile.unlink(missing_ok=True)

            configfile.write_text(
                json.dumps(
                    {
                        "path": str(sync_dir),
                        "topics": [{"id": tid, "name": name} for tid, name in targets],
                        "item_ids": item_ids or [],
                        "include_patterns": include_patterns or [],
                        "interval": interval,
                    }
                )
            )

            obris_bin = _resolve_obris_bin()
            with open(logfile, "ab", buffering=0) as log_fh, open(os.devnull, "rb") as devnull:
                proc = subprocess.Popen(
                    [*obris_bin, "sync", "_watcher", str(configfile)],
                    stdin=devnull,
                    stdout=log_fh,
                    stderr=log_fh,
                    start_new_session=True,
                    close_fds=True,
                )

            # Record the child's pid immediately. Using the child's pid
            # (not the parent's) keeps the liveness check correct after
            # this parent exits — otherwise a later spawner could read
            # a dead parent pid, think the pidfile is stale, and spawn
            # a duplicate while the original child is still running.
            pidfile.write_text(json.dumps({"pid": proc.pid, "starting": True}))
    except Timeout as e:
        raise DaemonStartupError(f"Another spawner is holding the watcher lock for {sync_dir}/. Try again.") from e

    deadline = time.monotonic() + _PID_WAIT_SECONDS
    while time.monotonic() < deadline:
        info = _read_pidfile(pidfile)
        if info and not info.get("starting"):
            return {"pid": int(info["pid"]), "log": str(logfile)}
        if proc.poll() is not None:
            pidfile.unlink(missing_ok=True)
            raise DaemonStartupError(
                f"Background watcher exited immediately (code {proc.returncode}). Check {logfile} for details."
            )
        time.sleep(_PID_POLL_INTERVAL)

    raise DaemonStartupError(
        f"Background watcher failed to start within {_PID_WAIT_SECONDS:.0f}s. Check {logfile} for details."
    )


def _resolve_obris_bin() -> list[str]:
    """Return the argv prefix that launches the obris CLI as a subprocess."""
    argv0 = sys.argv[0] if sys.argv else ""
    if argv0 and Path(argv0).name in {"obris", "obris.exe"} and Path(argv0).exists():
        return [argv0]
    return [sys.executable, "-m", "obris"]


def run_watcher_from_config(config_path: Path) -> None:
    """Entry point for the detached watcher subprocess.

    Reads the config written by ``spawn_background_watcher``, writes
    the pidfile, installs signal + atexit cleanup, then runs
    ``_watch_main`` until killed.
    """
    config_path = Path(config_path)
    config = json.loads(config_path.read_text())
    sync_dir = Path(config["path"])
    targets = [(t["id"], t["name"]) for t in config["topics"]]
    item_ids = config.get("item_ids") or None
    include_patterns = config.get("include_patterns") or None
    interval = int(config.get("interval", 30))

    pidfile = _pidfile(sync_dir)
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": os.getpid(),
        "path": str(sync_dir),
        "topics": config["topics"],
        "topic_ids": [t["id"] for t in config["topics"]],
        "item_ids": item_ids or [],
        "include_patterns": include_patterns or [],
        "interval": interval,
        "started_at": now_iso(),
        "log": str(_logfile(sync_dir)),
    }
    pidfile.write_text(json.dumps(payload))

    def _cleanup() -> None:
        pidfile.unlink(missing_ok=True)
        config_path.unlink(missing_ok=True)

    atexit.register(_cleanup)

    def _on_sigterm(_signum, _frame):
        raise _ShutdownSignal

    signal.signal(signal.SIGTERM, _on_sigterm)

    try:
        _watch_main(
            sync_dir=sync_dir,
            targets=targets,
            item_ids=item_ids,
            include_patterns=include_patterns,
            interval=interval,
        )
    except _ShutdownSignal:
        _log("watcher stopped (SIGTERM)")


def _watch_main(
    *,
    sync_dir: Path,
    targets: list[tuple[str, str]],
    item_ids: list[str] | None,
    include_patterns: list[str] | None,
    interval: int,
) -> None:
    """Daemon main loop.

    Calls ``run_sync_pass`` each iteration so the daemon and the
    foreground ``--watch`` share exactly one code path — including the
    subtopic-as-target safety check. State is reloaded from disk every
    iteration so the daemon picks up new tracked items without restart.
    """
    _log(f"watcher started: {sync_dir} (every {interval}s)")

    while True:
        started = time.monotonic()
        # Rebuild the (state, tid, name) tuples every iteration so a
        # rename or a newly-tracked item shows up on the next pass.
        target_tuples = [(SyncState.load(tid, sync_dir), tid, name) for tid, name in targets]
        try:
            run_sync_pass(
                sync_dir,
                target_tuples,
                item_ids,
                include_patterns,
                dry_run=False,
                quiet_if_clean=True,
            )
        except SubtopicTargetError as e:
            # Unrecoverable — if a target got reparented mid-watch,
            # logging the same error every interval forever is useless.
            # Break the loop so the daemon exits cleanly.
            _log(f"stopping: {e}")
            return
        except (Exception, SystemExit) as e:
            # Swallow transient failures so one bad iteration doesn't
            # kill the daemon. Shutdown does NOT arrive here — the
            # SIGTERM handler raises _ShutdownSignal, which subclasses
            # BaseException and propagates past this clause.
            _log(f"sync pass failed: {type(e).__name__}: {e}")
        elapsed = time.monotonic() - started
        time.sleep(max(0.0, interval - elapsed))


def _log(message: str) -> None:
    """Write a timestamped line to the daemon's redirected stdout."""
    click.echo(f"[{now_iso()}] {message}")
