"""
Staging-lock verbs for the `lazycortex-core` CLI.

This module backs the `git-lock` subcommand the `lazy-core.git-status` and
`lazy-core.git-unlock` skills call instead of embedding Python. `git-lock status` prints the
operator-facing report of the staging-window mutex — disabled, dormant under pathspec
discipline, free, or held with liveness and breakability — and `git-lock break` force-deletes
the lock. The repository root follows the dispatcher convention (`LAZY_REPO_ROOT`, then the
process working directory, overridable with `--cwd`) and is then widened to the git toplevel
so a call from a subdirectory still finds `.git/`.
"""
from __future__ import annotations

import argparse
import socket
import time

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import staging_lock  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from repo_root import resolve_git_toplevel  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from pathlib import Path


# waiver: operator-facing owner words of the status report, verbatim from the git-status skill
_OWNER_SELF, _OWNER_PEER = "this session", "peer"


def _print_status(repo: Path) -> None:
  """
  Print the staging-lock report for one repository.

  Args:
    repo: Git toplevel whose lock and guard configuration are reported.
  """
  cfg = staging_lock.load_config(repo)

  # guard: a disabled guard has no lock to report
  if not cfg.enabled:
    # waiver: operator-facing report line, verbatim from the git-status skill
    print("Lock: N/A (git guard disabled for this repo)")
    return

  # guard: pathspec discipline never opens a staging window, so the mutex is dormant
  if cfg.pathspec_enabled:
    # waiver: operator-facing report lines, verbatim from the git-status skill
    print("Lock: N/A (pathspec mode — the guard never opens a staging window)")
    # waiver: operator-facing report lines, verbatim from the git-status skill
    print("      Set git.pathspec_enabled false in .claude/lazy.settings.json for the mutex row.")
    return

  # guard: no lock file means nobody is staging
  if (state := staging_lock.inspect(repo)) is None:
    # waiver: operator-facing report line, verbatim from the git-status skill
    print("Lock: NONE (no staging in progress)")
    return

  # a held lock reports age, index activity, liveness, and whether the auto-break rules would clear it
  now = time.time()
  # waiver: git's own index file location, not a domain key
  index = repo / ".git" / "index"
  # the guard's own break-rule probe, so the report matches what the guard itself would decide
  breakable, reason = staging_lock.evaluate_break(repo, state, cfg, now = now)
  # waiver: operator-facing report lines, verbatim from the git-status skill
  print(f"Lock:        HELD by session {state.session_id} (PID {state.pid})")
  print(f"Branch:      {state.branch}")
  print(f"Held for:    {int(now - state.started_at)}s")
  print(f"Index touched: "
        f"{int(now - max(state.last_index_mtime, index.stat().st_mtime if index.exists() else 0.0))}s ago")
  # waiver: operator-facing report wording, verbatim from the git-status skill
  print(f"Liveness:    PID alive={staging_lock.is_pid_alive(state.pid)}, "
        f"host={'this' if state.host == socket.gethostname() else f'other({state.host})'}")
  # waiver: operator-facing report wording, verbatim from the git-status skill
  print(f"Breakable:   {f'YES ({reason})' if breakable else 'NO (within thresholds)'}")
  # the lock is this session's when it records this host and this session's own process
  own = state.host == socket.gethostname() and state.pid == staging_lock.resolve_holder_pid()
  # waiver: operator-facing report wording, verbatim from the git-status skill
  print(f"Owner:       {_OWNER_SELF if own else _OWNER_PEER}")


def cmd_git_lock(argv: list[str]) -> int:
  """
  Run the `git-lock` subcommand: `status` prints the lock report, `break` force-deletes the lock.

  Args:
    argv: Argument vector after the subcommand name (`status` or `break`, plus optional `--cwd`).

  Returns:
    Process exit code: 0 on success.

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
  """
  # the verb's command line: the action word and the repo-root override
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "lazycortex-core git-lock")
  # waiver: argparse CLI signature — action names are this verb's own vocabulary
  parser.add_argument("action", choices = [ "status", "break" ])
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")
  args = parser.parse_args(argv)
  repo = resolve_git_toplevel(args.cwd)

  # `status` prints the read-only report and never touches the lock file
  if args.action == "status":
    # waiver: the action name above is this verb's own vocabulary, matched against the argparse choices
    _print_status(repo)
    return 0

  # `break` force-deletes the lock and reports whether there was one to delete
  # waiver: CLI outcome tokens read by the git-unlock skill; `manual` is the audit reason it records
  print("broken" if staging_lock.break_lock(repo) else "no-lock")
  return 0
