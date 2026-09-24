"""
Job-queue and routine-registry verbs for the `lazycortex-core` CLI.

This module backs `list-jobs`, the JSON listing the `lazy-expert.list-jobs` skill renders,
and `routines-bootstrap`, the install-time call that registers the built-in routines. Each
listed job is stamped with its age in seconds before the listing is printed. The repository
root follows the dispatcher convention — `LAZY_REPO_ROOT`, then the process working
directory, overridable per call with `--cwd`.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from constants import JobCollectKey, JobMarker  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from expert_runtime import bootstrap_default_routines, list_jobs  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from repo_root import resolve_repo_root  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# a bundle's age is read off the first of these markers that exists, in this order
_AGE_MARKERS = ( JobMarker.DONE, JobMarker.DEAD, JobMarker.READY )
# age of a bundle carrying none of the age markers
_NO_AGE = -1


def _compute_age_sec(jdir: Path, now: float) -> int:
  """
  Compute a bundle's age from its lifecycle markers.

  Guarantees:
    - The age is measured from the first marker present in the order `DONE`, `DEAD`, `READY`; a
      bundle carrying none of them reports `-1`.

  Args:
    jdir: Absolute job-bundle directory.
    now: Reference wall-clock time in epoch seconds.

  Returns:
    Whole seconds since the first present marker among `DONE`, `DEAD`, `READY`, or `-1`
    when the bundle carries none of them.
  """

  # Contract:
  # The age is measured from the first marker present in the order DONE, DEAD, READY, so a finished
  # bundle ages from its completion and a queued one from its readiness; a bundle carrying none of
  # them reports -1. The list-jobs skill renders the value as is.

  # the first marker present decides — a finished bundle ages from DONE, a queued one from READY
  for name in _AGE_MARKERS:
    # guard: the first present marker settles the age
    if (marker := jdir / name).exists():
      return int(now - marker.stat().st_mtime)

  # a bundle with no lifecycle marker at all
  return _NO_AGE


def cmd_list_jobs(argv: list[str]) -> int:
  """
  Run the `list-jobs` subcommand: print the queue listing as a JSON array.

  Args:
    argv: Argument vector after the subcommand name (`--expert`, `--status`, `--cwd`).

  Returns:
    Process exit code: 0 on success.

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
  """
  # the verb's command line: the two listing filters and the repo-root override
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "lazycortex-core list-jobs")
  # waiver: argparse CLI signature and help strings, not domain keys
  parser.add_argument("--expert", default = None, help = "restrict to one expert")
  # waiver: argparse CLI signature and help strings, not domain keys
  parser.add_argument("--status", default = None, help = "restrict to one status value")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")
  args = parser.parse_args(argv)

  # the queue is read once, narrowed by whichever filters were given
  entries = list_jobs(resolve_repo_root(args.cwd), expert = args.expert or None, status = args.status or None)

  # one clock reading for the whole listing so ages are comparable across entries
  now = time.time()
  for entry in entries:
    entry[JobCollectKey.AGE_SEC] = _compute_age_sec(Path(entry[JobCollectKey.PATH]), now)

  # the stamped listing is the verb's whole output
  print(json.dumps(entries))
  return 0


def cmd_routines_bootstrap(argv: list[str]) -> int:
  """
  Run the `routines-bootstrap` subcommand: register the built-in routines when absent.

  Args:
    argv: Argument vector after the subcommand name (`--cwd` only).

  Returns:
    Process exit code: 0 on success (prints `bootstrapped`), 1 when the settings file cannot
    be read or written.

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
  """
  # the verb's command line: the repo-root override alone
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "lazycortex-core routines-bootstrap")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")
  args = parser.parse_args(argv)

  # an unreadable or unwritable settings file is reported as one line, never as a traceback
  try:
    bootstrap_default_routines(resolve_repo_root(args.cwd))
  except (OSError, json.JSONDecodeError) as error:
    print(f"error: {error}")
    return 1

  # the one-word outcome the install skill reads
  # waiver: the one-word outcome the install skill reads, not a reusable domain key
  print("bootstrapped")
  return 0
