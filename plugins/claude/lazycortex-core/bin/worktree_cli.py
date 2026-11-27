from __future__ import annotations

from typing import TypedDict

import argparse
import json
from enum import StrEnum
from pathlib import PurePosixPath

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from constants import (  # pylint: disable=import-error
  DaemonKey, GitConfigKey, JobConfigKey, SettingsKey, WorkspaceMode,
)
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from lazy_settings import load_section, load_tracked_section, save_section  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from settings_cli import ConfirmKey, resolve_settings_path  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from worktree_tasks import WorktreeTaskManager  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from pathlib import Path


# Help text of the `--cwd` flag both verbs carry.
_CWD_HELP = "Repository root (default: $LAZY_REPO_ROOT or cwd)"


# ----------------------------------------------------------------------------------------
class LinkOutcome(StrEnum):
  """
  Outcome words reported in the `status` field of a verb's JSON line.

  Attributes:
    ADDED: The path was appended to the list.
    PRESENT: The path was listed already, so nothing was written.
    ERROR: The call was refused, so nothing was written.
  """

  # The path was appended to the list.
  ADDED = "added"
  # The path was listed already; nothing was written.
  PRESENT = "present"
  # The call was refused; nothing was written.
  ERROR = "error"


# ----------------------------------------------------------------------------------------
class WorktreeEnvRecord(TypedDict):
  """
  Record of the worktree environment check: who runs in job worktrees and whether they get any environment.

  Attributes:
    branch_experts: Names of the experts whose jobs run in a worktree, in name order.
    worktree_links: Configured repo-relative paths every worktree carries as links.
    worktree_bootstrap_cmd: Configured bootstrap command, or nothing when none is set.
    gap: Whether branch experts exist while no link and no bootstrap command is configured.
  """

  # Names of the experts whose jobs run in a worktree, in name order.
  branch_experts: list[str]
  # Configured repo-relative paths every worktree carries as links.
  worktree_links: list[str]
  # Configured bootstrap command, or nothing when none is set.
  worktree_bootstrap_cmd: str | None
  # Whether branch experts exist while no link and no bootstrap command is configured.
  gap: bool


# ----------------------------------------------------------------------------------------


def _to_normal_form(rel: str) -> str:
  """
  Return the one spelling a repo-relative path is listed and compared under.

  Args:
    rel: A repo-relative path.

  Returns:
    The path with `.` segments and a trailing slash dropped, in forward-slash form.
  """
  return PurePosixPath(rel).as_posix()


def add_worktree_link(rel: str, *, cwd: Path | str | None = None) -> LinkOutcome:
  """
  Add one repo-relative path to `daemon.git.worktree_links` in the tracked settings file.

  Guarantees:
    - A path already listed, in any spelling that names the same path, leaves the file byte for byte as it is.
    - Every other section, key and list entry keeps its value and its place; the new path joins the end of the list.

  Args:
    rel: The repo-relative path to add.
    cwd: Directory inside the repository, or `None` for `LAZY_REPO_ROOT`, else the process working directory; the
      settings file is the `.claude/lazy.settings.json` at the root of the checkout that directory sits in, where
      the daemon reads it.

  Returns:
    `LinkOutcome.ADDED` when the path was appended, `LinkOutcome.PRESENT` when it was already listed.

  Raises:
    ValueError: If the path does not name a location inside the repository, the settings file is not valid
      JSON, `daemon.git` is present and not an object (an empty list, `false` or an empty string included; only an
      absent or null block starts empty), or its `worktree_links` value is not a list.
    OSError: If the settings file cannot be written.
  """

  # Contract:
  # A path already listed, in any spelling that names the same path, leaves the file byte for byte as it is.

  # Contract:
  # Every other section, key and list entry keeps its value and its place; the new path joins the end of the list.

  # guard: a path outside the repository can never be carried into a worktree
  if refusal := WorktreeTaskManager.validate_link(rel):
    raise ValueError(refusal)

  # the tracked layer only, so the write never leaks the local overlay into the shared file
  path = resolve_settings_path(cwd, section = SettingsKey.DAEMON)
  daemon = load_tracked_section(path, SettingsKey.DAEMON)

  # only an absent or null git block starts empty; any other value of the wrong shape stays the operator's
  git = daemon.get(DaemonKey.GIT)
  git = {} if git is None else git
  links = git.get(GitConfigKey.WORKTREE_LINKS, []) if isinstance(git, dict) else None

  # guard: a value of another shape is the operator's, never replaced to make room
  if not isinstance(git, dict) or not isinstance(links, list):
    raise ValueError(f"{path}: daemon.git.worktree_links is not a list inside a daemon.git object")

  # a path listed already is the present outcome — nothing to write
  if any(isinstance(entry, str) and _to_normal_form(entry) == _to_normal_form(rel) for entry in links):
    return LinkOutcome.PRESENT

  # the path joins the end of the list; the block keeps its place in the section
  links.append(_to_normal_form(rel))
  git[GitConfigKey.WORKTREE_LINKS] = links
  daemon[DaemonKey.GIT] = git
  save_section(path, SettingsKey.DAEMON, daemon)
  return LinkOutcome.ADDED


def read_worktree_env(*, cwd: Path | str | None = None) -> WorktreeEnvRecord:
  """
  Tell whether experts that run in job worktrees get neither carried links nor a bootstrap command there.

  Args:
    cwd: Directory inside the repository, or `None` for `LAZY_REPO_ROOT`, else the process working directory; the
      settings file is the `.claude/lazy.settings.json` at the root of the checkout that directory sits in, where
      the daemon reads it.

  Returns:
    An answer naming the experts with `workspace: branch`, the configured links and bootstrap command, and
    whether those experts' worktrees get no execution environment at all. Link entries that are not strings and a
    bootstrap command that is not a non-empty string are left out of the answer.

  Raises:
    ValueError: If the tracked or the local settings file is not valid JSON or not a JSON object.
    OSError: If a settings file cannot be opened.
  """

  # Domain(runtime.job-execution):
  # # A worktree job without any environment
  # An expert that runs its jobs in an isolated working copy starts from tracked files alone. Its
  # environment reaches that copy only through the paths the operator shares as links or through the
  # preparation command; with neither configured, every gitignored tool the job needs is missing there.

  # the effective view, as the pump reads both layers
  path = resolve_settings_path(cwd, section = SettingsKey.DAEMON)
  experts = load_section(path, SettingsKey.EXPERTS)
  daemon = load_section(path, SettingsKey.DAEMON)

  # the git block's links, keeping only string entries; a block that is no object configures none
  git = daemon.get(DaemonKey.GIT)
  git = git if isinstance(git, dict) else {}
  links = git.get(GitConfigKey.WORKTREE_LINKS)
  links = [ entry for entry in links if isinstance(entry, str) ] if isinstance(links, list) else []

  # the bootstrap command, kept only when it is a non-empty string
  cmd = git.get(GitConfigKey.WORKTREE_BOOTSTRAP_CMD)
  cmd = cmd if isinstance(cmd, str) and cmd else None

  # the experts whose jobs run in a worktree, in name order
  branch = sorted(
    name for name, entry in experts.items()
    if isinstance(entry, dict) and entry.get(JobConfigKey.WORKSPACE) == WorkspaceMode.BRANCH
  )
  return WorktreeEnvRecord(
    branch_experts = branch, worktree_links = links, worktree_bootstrap_cmd = cmd,
    gap = bool(branch) and not links and not cmd,
  )


def cmd_worktree_links_add(argv: list[str]) -> int:
  """
  Run the `worktree-links-add` subcommand: add one path to `daemon.git.worktree_links` and print the outcome.

  Args:
    argv: Argument vector after the subcommand name (the path, then an optional `--cwd`).

  Returns:
    Process exit code: 0 when the path was added or already listed, 1 when the call was refused.
  """
  # one path and the repository it belongs to
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-core worktree-links-add")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("path")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None, help = _CWD_HELP)
  args = parser.parse_args(argv)

  # a refusal is one JSON line, never a traceback
  try:
    status = add_worktree_link(args.path, cwd = args.cwd)
  except ( ValueError, OSError ) as error:
    print(json.dumps({
      ConfirmKey.STATUS: LinkOutcome.ERROR, ConfirmKey.PATH: args.path, ConfirmKey.MESSAGE: str(error),
    }))
    return 1

  # the outcome word and the path as it is listed
  print(json.dumps({ ConfirmKey.STATUS: status, ConfirmKey.PATH: _to_normal_form(args.path) }))
  return 0


def cmd_worktree_env_check(argv: list[str]) -> int:
  """
  Run the `worktree-env-check` subcommand: print whether branch experts' worktrees get no environment.

  Args:
    argv: Argument vector after the subcommand name (an optional `--cwd`).

  Returns:
    Process exit code: 0 with the answer printed, 1 when a settings file is unreadable or invalid, reported as one
    JSON line.
  """
  # only the repository is named
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-core worktree-env-check")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None, help = _CWD_HELP)
  args = parser.parse_args(argv)

  # an unreadable settings file is reported as one JSON line
  try:
    answer = read_worktree_env(cwd = args.cwd)
  except ( ValueError, OSError ) as error:
    print(json.dumps({ ConfirmKey.STATUS: LinkOutcome.ERROR, ConfirmKey.MESSAGE: str(error) }))
    return 1

  # the answer the audit maps onto its finding
  print(json.dumps(answer))
  return 0
