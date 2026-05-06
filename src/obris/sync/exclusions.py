"""File-level exclusion matcher for sync.

Combines two pattern sources, evaluated in order, gitignore-style
(``pathspec``'s ``gitwildmatch``):

1. **Built-in defaults** — hardcoded in this module. Hides VCS
   metadata, dependency dirs, OS / editor cruft, and credential-shaped
   files.
2. **State-level rules** — set via ``obris sync exclude`` and
   ``obris sync include``. Stored as a list of patterns on each
   ``SyncState``; ``!pattern`` entries are re-includes that override
   the defaults. The CLI is the only writer.

Last match wins (gitignore semantics), so state-level rules can
always override defaults. Users never hand-edit a config file —
state is owned by the CLI.
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
    # Secrets — common files / dirs that hold credentials. Kept narrow
    # to literal known-bad paths instead of a blanket dotfile rule so
    # AI-tool config dirs (.claude/, .cursor/, .github/, etc.) keep
    # syncing. Users can override any default with
    # ``obris sync include <pattern>``.
    ".env",
    ".env.*",
    ".envrc",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".aws/",
    ".gnupg/",
    ".ssh/",
]


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
        for pat in state_excludes or []:
            self._sources.append(("state", pat))
        self._spec = pathspec.PathSpec.from_lines(GitWildMatchPattern, [pat for _, pat in self._sources])

    def excludes(self, rel_path: str) -> bool:
        """Return True if ``rel_path`` (relative to sync_dir, POSIX-style) matches an exclusion."""
        return self._spec.match_file(rel_path)

    def reasons(self, rel_path: str) -> list[tuple[str, str]]:
        """Return ``[(source_label, pattern), ...]`` for every pattern that matches.

        A path can match multiple patterns; this returns all of them in
        source order (defaults → state). Used for diagnostics, not
        for the actual exclude decision.
        """
        matched = []
        for label, pat in self._sources:
            spec = pathspec.PathSpec.from_lines(GitWildMatchPattern, [pat])
            if spec.match_file(rel_path):
                matched.append((label, pat))
        return matched
