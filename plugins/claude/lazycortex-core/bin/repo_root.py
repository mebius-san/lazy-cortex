"""
Repository-root resolution shared by the `lazycortex-core` CLI verbs.

Every subcommand resolves its repository root the same way: an explicit `--cwd` wins,
otherwise the dispatcher's `LAZY_REPO_ROOT` environment variable, and finally the process
working directory. This module holds that one convention so no verb carries its own copy.
It also widens that root to its git toplevel for the verbs that write under the checkout's `.claude/`.
"""
from __future__ import annotations

import os
import subprocess
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


def resolve_git_toplevel(cwd: Path | str | None) -> Path:
  """
  Resolve the git toplevel above the conventional repository root.

  Notes:
    - Runs a `git` subprocess in the starting directory.

  Args:
    cwd: Explicit starting directory, or `None` to fall back to the `LAZY_REPO_ROOT`
      environment variable and then the process working directory.

  Returns:
    The git toplevel above the starting directory, or the starting directory itself when
    git cannot name one.
  """
  # the starting directory follows the dispatcher convention: explicit --cwd, then LAZY_REPO_ROOT, then cwd
  start = resolve_repo_root(cwd)

  # git names the toplevel; a git binary that cannot be spawned leaves the starting directory in charge
  try:
    done = subprocess.run([ "git", "rev-parse", "--show-toplevel" ], cwd = start,
                          capture_output = True, text = True, check = False, encoding = "utf-8")
  except OSError:
    return start

  # a start outside any checkout also falls back to itself
  return Path(done.stdout.strip()) if done.returncode == 0 and done.stdout.strip() else start
