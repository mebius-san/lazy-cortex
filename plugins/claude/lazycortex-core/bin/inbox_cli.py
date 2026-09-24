"""
Shared-inbox collision surface for the `lazycortex-core` CLI.

This module backs the `inbox-check` subcommand: it runs the install-time shared-inbox guard
and prints its findings as JSON, exiting non-zero when another checkout on this host drives
the same physical inbox. The repository root follows the convention every other subcommand
uses: the `LAZY_REPO_ROOT` env var, falling back to the process working directory,
overridable per-call with `--cwd`.
"""
from __future__ import annotations

import argparse
import json

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from inbox_guard import check_inbox_collision_for_install  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from repo_root import resolve_repo_root  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


def cmd_inbox_check(argv: list[str]) -> int:
  """
  Run the `inbox-check` subcommand: print the shared-inbox findings as a JSON list.

  Args:
    argv: Argument vector after the subcommand name (optional `--cwd`).

  Returns:
    Process exit code: 0 when no inbox is contested, 1 when at least one is.

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
  """
  # the verb's command line: the repo-root override alone
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "lazycortex-core inbox-check")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")
  args = parser.parse_args(argv)

  # the guard's findings are the whole report; any finding at all fails the verb
  findings = check_inbox_collision_for_install(resolve_repo_root(args.cwd))
  print(json.dumps(findings, ensure_ascii = False))
  return 1 if findings else 0
