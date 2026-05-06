"""File-level exclusion matcher for sync.

Combines three pattern sources, all gitignore-style (``pathspec``'s
``gitwildmatch``):

1. **Built-in defaults** — always applied, hardcoded in this module.
   Hides VCS metadata, dependency dirs, OS / editor cruft.
2. **``.obrisignore``** — user-authored, lives at the sync-dir root.
   The CLI reads it; it never writes to it.
3. **State-level excludes** — per-checkout, set via
   ``obris sync exclude``. Plumbed through ``state_excludes`` so this
   module has no opinion on where they're persisted.

Supports gitignore semantics including ``!pattern`` re-includes.
"""

from __future__ import annotations

from pathlib import Path

import pathspec
from pathspec.patterns.gitwildmatch import GitWildMatchPattern

DEFAULT_EXCLUDES = [
    # VCS
    ".git/",
    ".hg/",
    ".svn/",
    # Python
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    ".venv/",
    "venv/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    # JS / Node
    "node_modules/",
    ".next/",
    "dist/",
    "build/",
    # OS / editor cruft
    ".DS_Store",
    "Thumbs.db",
    ".idea/",
    ".vscode/",
    "*.swp",
    "*.swo",
    "*~",
    # Temp
    "*.tmp",
    "*.bak",
]

OBRISIGNORE = ".obrisignore"


def _read_obrisignore(sync_dir: Path) -> list[str]:
    path = sync_dir / OBRISIGNORE
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [line for line in lines if line.strip() and not line.strip().startswith("#")]


class ExclusionMatcher:
    """Single matcher built once per sync pass, queried per file.

    Sources are kept as ``(label, pattern)`` tuples so ``reasons()``
    can tell the user *why* a path was excluded — useful for the
    initial-sync output that surfaces "N files matched ignore rules."
    """

    def __init__(self, sync_dir: Path, state_excludes: list[str] | None = None):
        self.sync_dir = Path(sync_dir)
        self._sources: list[tuple[str, str]] = []
        for pat in DEFAULT_EXCLUDES:
            self._sources.append(("default", pat))
        for pat in _read_obrisignore(self.sync_dir):
            self._sources.append((OBRISIGNORE, pat))
        for pat in state_excludes or []:
            self._sources.append(("state", pat))
        self._spec = pathspec.PathSpec.from_lines(GitWildMatchPattern, [pat for _, pat in self._sources])

    def excludes(self, rel_path: str) -> bool:
        """Return True if ``rel_path`` (relative to sync_dir, POSIX-style) matches an exclusion."""
        return self._spec.match_file(rel_path)

    def reasons(self, rel_path: str) -> list[tuple[str, str]]:
        """Return ``[(source_label, pattern), ...]`` for every pattern that matches.

        A path can match multiple patterns; this returns all of them in
        source order (defaults → .obrisignore → state). Used for
        diagnostics, not for the actual exclude decision.
        """
        matched = []
        for label, pat in self._sources:
            spec = pathspec.PathSpec.from_lines(GitWildMatchPattern, [pat])
            if spec.match_file(rel_path):
                matched.append((label, pat))
        return matched
