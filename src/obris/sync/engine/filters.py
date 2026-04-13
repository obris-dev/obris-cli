"""Glob-style include-pattern matching for sync.

Patterns match against a topic's name path from the root, slash-joined.
For example, a topic ``Projects/Obris/Sync`` has path segments
``["Projects", "Obris", "Sync"]``.

Semantics:
- ``*``, ``?``, ``[abc]`` are intra-segment wildcards (fnmatch-style).
  They match within a single segment and never cross ``/``.
- ``**`` is the cross-segment wildcard — zero or more segments.
- Matching is case-insensitive.
- A topic matches if *any* of the supplied patterns matches its path.

Examples (root is ``Work``):
- ``Projects/**`` → ``Projects``, ``Projects/Obris``, ``Projects/Obris/Sync``
- ``**/skill-*`` → any topic whose leaf starts with ``skill-``
- ``Archive/2024`` → exact match
- ``Sk*/skill-py*`` → ``Skills/skill-python``
"""

from __future__ import annotations

import fnmatch


def _split_pattern(pattern: str) -> list[str]:
    return [seg for seg in pattern.split("/") if seg != ""]


def _match_segments(path: list[str], pat: list[str]) -> bool:
    """Recursive matcher supporting ``**`` as zero-or-more segments."""
    if not pat:
        return not path
    head, *rest = pat
    if head == "**":
        if _match_segments(path, rest):
            return True
        if not path:
            return False
        return _match_segments(path[1:], pat)
    if not path:
        return False
    if fnmatch.fnmatchcase(path[0].lower(), head.lower()):
        return _match_segments(path[1:], rest)
    return False


def match_path(path_segments: list[str], pattern: str) -> bool:
    """Return True if the topic path matches the single pattern."""
    return _match_segments(list(path_segments), _split_pattern(pattern))


def any_match(path_segments: list[str], patterns: list[str]) -> bool:
    """Return True if any pattern matches the topic path.

    Callers must special-case empty ``patterns`` themselves — an empty
    pattern list means "no filter configured", which is a policy
    decision (match everything) that shouldn't be baked into the
    matcher semantics. Strict semantics: ``any([...])`` is False for
    empty input, and that's what this returns.
    """
    return any(match_path(path_segments, p) for p in patterns)
