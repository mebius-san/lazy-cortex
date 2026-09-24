"""
Migrations for the lazycortex-core runtime sections of `lazy.settings.json`
(`daemon`, `routines`, `experts`, `git`, `repos`).

Empty — this module is not a section key anyone reads. Per-section ladders live
in the correctly-keyed sibling modules: `routines.py` owns the
`frontmatter_filter` → `filter.frontmatter` rewrite, and `daemon.py` owns the
`git.branch` → `git.base_branch` rename. Add a `MIGRATIONS` entry here only if a
section keyed `lazy-core.runtime` is ever introduced and read.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Callable


MIGRATIONS: dict[int, Callable[[dict], dict]] = {}
