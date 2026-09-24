"""
Protocol-envelope audit surface for the `lazycortex-core` CLI.

This module backs the `protocol-audit` subcommand: it audits every reachable protocol file
against the response envelope through `protocol_envelope.audit` and prints the findings as
JSON. The repository root follows the convention every other subcommand uses: the
`LAZY_REPO_ROOT` env var, falling back to the process working directory, overridable
per-call with `--cwd`.
"""
from __future__ import annotations

import argparse
import json

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from protocol_envelope import audit  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from repo_root import resolve_repo_root  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


def cmd_protocol_audit(argv: list[str]) -> int:
  """
  Run the `protocol-audit` subcommand: print the envelope findings as a JSON list.

  Args:
    argv: Argument vector after the subcommand name (optional `--cwd`).

  Returns:
    Process exit code: 0 on success (findings or not).

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
  """
  # the verb's command line: the repo-root override alone
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "lazycortex-core protocol-audit")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")
  args = parser.parse_args(argv)

  # the audit's findings are printed whole; the verb never fails on them
  print(json.dumps(audit(resolve_repo_root(args.cwd)), ensure_ascii = False))
  return 0
