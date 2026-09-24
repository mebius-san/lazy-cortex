"""
Repository-root resolution shared by the `lazycortex-core` CLI verbs.

Every subcommand resolves its repository root the same way: an explicit `--cwd` wins,
otherwise the dispatcher's `LAZY_REPO_ROOT` environment variable, and finally the process
working directory. This module holds that one convention so no verb carries its own copy.
"""
from __future__ import annotations

import os
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


def resolve_repo_root(cwd: Path | str | None) -> Path:
  """
  Resolve the repository root from an optional explicit working directory.

  Args:
    cwd: Explicit repository root, or `None` to fall back to the `LAZY_REPO_ROOT`
      environment variable and then the process working directory.

  Returns:
    Path to the repository root, as given or as the convention resolves it.
  """
  # pick the repo root: explicit --cwd wins, otherwise the dispatcher's LAZY_REPO_ROOT-or-cwd convention
  # waiver: LAZY_REPO_ROOT is the dispatcher's env contract, not a domain key
  return Path(cwd) if cwd is not None else Path(os.environ.get("LAZY_REPO_ROOT", os.getcwd()))
