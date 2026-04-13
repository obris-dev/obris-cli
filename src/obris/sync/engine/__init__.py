"""Bidirectional sync engine package.

Public entry point is ``run_sync``. Internals are split for readability:

- ``run.py``      — main sync loop (fetch + dispatch + reconcile)
- ``subtree.py``  — name-path / ancestor walking and directory reconciliation
- ``tracked.py``  — per-item sync for items already present in state
- ``filters.py``  — glob pattern matching for ``--include``
"""

from .run import run_sync

__all__ = ["run_sync"]
