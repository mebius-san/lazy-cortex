"""
Migrations for the `daemon` section of `lazy.settings.json`.

v1 → v2 (`MIGRATIONS[1]`) renames the daemon's `git.branch` field to
`git.base_branch`, reflecting the move off a perpetual daemon-exclusive branch
onto the operator's base branch. A section without a `git` block, or one whose
`git` block carries no `branch` key, passes through untouched. The section dict
is the daemon block itself, so the transform operates on `data["git"]` directly.
Add `2: lambda data: <transformed>` here when a v2 → v3 migration is needed.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


MIGRATIONS = {
  # v1 → v2: git.branch -> git.base_branch.
  1: lambda data: {
    **data,
    "git": {
      **{ k: v for k, v in data["git"].items() if k != "branch" },
      "base_branch": data["git"]["branch"],
    },
  } if (
    isinstance(data.get("git"), dict)
    and "branch" in data["git"]
  ) else data,
}
