"""
Pure parser for `expert@repo` syntax. No I/O.

Used by expert_runtime (same-plugin import) and duplicated minimally into
lazycortex-review/bin/audit.py — cross-plugin Python imports are forbidden
between sibling plugins; this parser is small and stable enough that
duplication beats a CLI hop.
"""
from __future__ import annotations

import re

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_FLAT_PART_RE = re.compile(r"^[a-z0-9_-]+$")


class ExpertNameError(ValueError):
  """
  Raised when an expert name fails parse or alphabet validation.
  """


def parse(name: str) -> tuple[str, str]:
  """
  Split `expert@repo` into (expert, repo_key).

  No `@` → repo_key = ".".
  Explicit `@.` → repo_key = "." (synonym for bare name).
  Multiple `@` → split on the LAST one.
  Empty input, or empty left or right part → ExpertNameError.

  Returns:
    A two-tuple of (expert, repo_key) where repo_key is `"."` for bare names.

  Raises:
    ExpertNameError: If the name is empty or either side of `@` is empty.
  """
  # guard: empty input is not a valid expert name
  if not name:
    raise ExpertNameError("empty expert name")
  # bare name with no repo qualifier — return canonical "." repo_key
  if "@" not in name:
    return name, "."
  expert, _, repo = name.rpartition("@")
  # guard: both sides of @ must be non-empty
  if not expert or not repo:
    raise ExpertNameError(
      f"malformed expert name {name!r}: both sides of @ must be non-empty"
    )
  return expert, repo


def flatten(name: str) -> str:
  """
  Tag-safe flat form for `#expert/<flat>` tag in section ownership.

  `validator`         → `validator`
  `validator@.`       → `validator`
  `validator@backend` → `validator__backend`

  Validates each part against `^[a-z0-9_-]+$`. Raises on invalid alphabet.

  Returns:
    The flat string form of the expert name, with `__` separating the expert
    and repo parts when a repo qualifier is present.

  Raises:
    ExpertNameError: If any part of the name fails the tag-safe alphabet check.
  """
  expert, repo = parse(name)
  # guard: expert part must match the tag-safe alphabet
  if not _FLAT_PART_RE.match(expert):
    raise ExpertNameError(
      f"expert part {expert!r} fails alphabet ^[a-z0-9_-]+$"
    )
  # bare-name form — no repo suffix needed
  if repo == ".":
    return expert
  # guard: repo part must match the tag-safe alphabet
  if not _FLAT_PART_RE.match(repo):
    raise ExpertNameError(
      f"repo part {repo!r} fails alphabet ^[a-z0-9_-]+$"
    )
  return f"{expert}__{repo}"
