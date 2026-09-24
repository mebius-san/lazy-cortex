"""
Reference-resolution surface for the `lazycortex-core` CLI.

This module backs the `resolve-ref` subcommand: it resolves one or more agent / protocol /
aspect references through `reference_resolver.resolve` and reports each outcome as JSON,
never raising. The repository root for bare references follows the convention every other
subcommand uses: the `LAZY_REPO_ROOT` env var, falling back to the process working directory,
overridable per-call with `--cwd`.
"""
from __future__ import annotations

import argparse
import json

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# waiver: the resolver's domain exception deliberately shadows the builtin name; imported as-is
from reference_resolver import ReferenceError, resolve  # pylint: disable=import-error,redefined-builtin
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from repo_root import resolve_repo_root  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from pathlib import Path


# waiver: argparse choice tokens, mirrored from the resolver's category vocabulary
_CATEGORIES = ("agents", "protocols", "aspects")
# waiver: JSON row keys of the CLI wire shape, not domain constants
_REF, _OK, _PATH, _ERROR = "ref", "ok", "path", "error"


def resolve_refs(refs: list[str], *, category: str, cwd: Path | str | None = None) -> list[dict[str, object]]:
  """
  Resolve every reference and report each outcome without raising.

  Guarantees:
    - One row per input reference, in input order; a failed resolution yields a row with
      `ok` false and the error text instead of aborting the batch.

  Args:
    refs: Reference strings in any of the resolver's three forms.
    category: One of `agents`, `protocols`, or `aspects`.
    cwd: Repository root override for bare references.

  Returns:
    Rows of the shape `{"ref", "ok", "path", "error"}`.
  """

  # Contract:
  # Every input reference produces exactly one row, in input order, and a resolution failure
  # is reported inside its row rather than raised — the batch is never aborted midway.

  # every reference resolves against the same root, in input order
  repo = resolve_repo_root(cwd)
  rows: list[dict[str, object]] = []
  for ref in refs:
    # guard: a failed resolution becomes its own row and the batch moves on
    try:
      path = resolve(ref, category = category, repo = repo)
    except ReferenceError as error:
      rows.append({ _REF: ref, _OK: False, _PATH: None, _ERROR: str(error) })
      continue

    # a resolved reference reports its path
    rows.append({ _REF: ref, _OK: True, _PATH: str(path), _ERROR: None })

  # one row per input, in input order
  return rows


def cmd_resolve_ref(argv: list[str]) -> int:
  """
  Run the `resolve-ref` subcommand: print one JSON row per reference to stdout.

  Args:
    argv: Argument vector after the subcommand name (refs, `--category`, optional `--cwd`).

  Returns:
    Process exit code: 0 when every reference resolves, 1 otherwise.

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
  """
  # the verb's command line: the references, their category, and the repo-root override
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "lazycortex-core resolve-ref")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("refs", nargs = "+")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--category", required = True, choices = _CATEGORIES)
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")
  args = parser.parse_args(argv)

  # resolve every reference, print the rows, and fail the exit code when any row failed
  rows = resolve_refs(args.refs, category = args.category, cwd = args.cwd)
  print(json.dumps(rows))
  return 0 if all(row[_OK] for row in rows) else 1
