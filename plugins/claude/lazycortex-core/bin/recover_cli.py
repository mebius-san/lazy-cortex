"""
Halt-recovery verbs for the `lazycortex-core` CLI.

This module backs the `recover` subcommand family the `lazy-runtime.recover` skill and the
`lazy-runtime.doctor` agent call instead of embedding Python: `recover halt` reads the halt
block, `recover cleanup` applies an operator-chosen cleanup mode, `recover resume` clears the
halt, `recover revert` restores tracked paths to `HEAD`, `recover clear-dead` re-arms a dead
job bundle, and `recover permanent-fail` records a doctor diagnosis beside one.

Every verb prints a one-word outcome or JSON to stdout and never raises a recovery error at
the caller: a `RecoverError` or a failed git command becomes an `error: ...` line (or the
`still-dirty: ...` line `resume` is documented to print) and a non-zero exit. The repository
root follows the dispatcher convention — `LAZY_REPO_ROOT`, then the process working
directory, overridable per call with `--cwd`.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import recover  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from repo_root import resolve_repo_root  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# ----------------------------------------------------------------------------------------
class Verb:
  """
  Sub-verb name tokens of the `recover` subcommand, as spelled on the command line.

  Attributes:
    HALT: Print the halt block.
    CLEANUP: Apply a cleanup mode to the working tree.
    RESUME: Clear the halt block.
    REVERT: Restore tracked paths to `HEAD`.
    CLEAR_DEAD: Re-arm a dead job bundle for retry.
    PERMANENT_FAIL: Record a doctor diagnosis on a dead job bundle.
  """

  HALT = "halt"
  CLEANUP = "cleanup"
  RESUME = "resume"
  REVERT = "revert"
  CLEAR_DEAD = "clear-dead"
  PERMANENT_FAIL = "permanent-fail"



# ----------------------------------------------------------------------------------------
class Outcome:
  """
  One-word outcome tokens the `recover` verbs print on success, which callers branch on.

  Attributes:
    NOT_HALTED: `halt` found no halt block.
    CLEANED: `cleanup` applied its mode.
    RESUMED: `resume` cleared the halt block.
    REVERTED: `revert` restored every named path.
    CLEARED: `clear-dead` re-armed the bundle.
    MARKED: `permanent-fail` wrote the diagnosis.
    ERROR_PREFIX: Prefix of the line printed when a verb fails.
    STILL_DIRTY_PREFIX: Prefix of the line `resume` prints when the tree is still dirty.
  """

  NOT_HALTED = "not_halted"
  CLEANED = "cleaned"
  RESUMED = "resumed"
  REVERTED = "reverted"
  CLEARED = "cleared"
  MARKED = "marked"
  ERROR_PREFIX = "error: "
  STILL_DIRTY_PREFIX = "still-dirty: "



# ----------------------------------------------------------------------------------------
def _resolve_jdir(repo: Path, jdir: str) -> Path | None:
  """
  Resolve a job-bundle directory argument against the repository root.

  Args:
    repo: Absolute repository root.
    jdir: Job directory as the caller spelled it, absolute or repo-relative.

  Returns:
    The absolute job directory, or `None` when no directory exists there.
  """
  # a relative job dir is repo-relative, the shape the doctor's job listing spells it in
  path = Path(jdir) if Path(jdir).is_absolute() else repo / jdir

  # guard: the recover primitives touch files inside the bundle, so a missing dir must be refused here
  if not path.is_dir():
    return None

  # the primitives get an absolute path so a relative spelling never depends on the process cwd
  return path.resolve()


def _build_parser() -> argparse.ArgumentParser:
  """
  Build the `recover` argument parser with one sub-parser per verb.

  Returns:
    The configured parser; each sub-parser sets `verb` to its name.
  """
  # the root parser carries only the repo-root override; every verb hangs off one sub-parser
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(prog = "lazycortex-core recover")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")
  # waiver: argparse CLI signature, not a domain key
  verbs = parser.add_subparsers(dest = "verb", required = True)

  # the read-only verbs take no arguments of their own
  # waiver: argparse CLI signature and help strings, not domain keys
  verbs.add_parser(Verb.HALT, help = "print the halt block as JSON, or `not_halted`")
  # waiver: argparse CLI signature and help strings, not domain keys
  verbs.add_parser(Verb.RESUME, help = "clear the halt block; refuses while the tree is dirty")

  # cleanup mirrors the `recover.cleanup` signature: mode, message, paths and their shape
  # waiver: argparse CLI signature and help strings, not domain keys
  cleanup = verbs.add_parser(Verb.CLEANUP, help = "apply a cleanup mode to the working tree")
  # waiver: argparse CLI signature, not a domain key
  cleanup.add_argument("mode", choices = sorted(recover.VALID_MODES))
  # waiver: argparse CLI signature and help strings, not domain keys
  cleanup.add_argument("--message", default = None, help = "commit message (commit mode)")
  # waiver: argparse CLI signature and help strings, not domain keys
  cleanup.add_argument("--path", action = "append", default = [], help = "commit only this path (repeatable)")
  # waiver: argparse CLI signature and help strings, not domain keys
  cleanup.add_argument("--porcelain", action = "store_true",
                       help = "--path values are `git status --porcelain` lines")

  # revert takes the tracked paths to restore
  # waiver: argparse CLI signature and help strings, not domain keys
  revert = verbs.add_parser(Verb.REVERT, help = "restore tracked paths to HEAD")
  # waiver: argparse CLI signature, not a domain key
  revert.add_argument("path", nargs = "+")

  # the job-bundle verbs take the bundle directory, permanent-fail also the diagnosis
  # waiver: argparse CLI signature and help strings, not domain keys
  clear_dead = verbs.add_parser(Verb.CLEAR_DEAD, help = "re-arm a dead job bundle for retry")
  # waiver: argparse CLI signature, not a domain key
  clear_dead.add_argument("jdir")
  # waiver: argparse CLI signature and help strings, not domain keys
  permanent_fail = verbs.add_parser(Verb.PERMANENT_FAIL, help = "record a doctor diagnosis on a dead bundle")
  # waiver: argparse CLI signature, not a domain key
  permanent_fail.add_argument("jdir")
  # waiver: argparse CLI signature and help strings, not domain keys
  permanent_fail.add_argument("--diagnosis", required = True, help = "diagnosis as a JSON object")

  # the fully wired parser
  return parser


def _run_job_verb(repo: Path, args: argparse.Namespace) -> int:
  """
  Run `clear-dead` or `permanent-fail` against one job bundle.

  Args:
    repo: Absolute repository root.
    args: Parsed arguments carrying `verb`, `jdir`, and (for permanent-fail) `diagnosis`.

  Returns:
    Process exit code: 0 on success, 1 on a missing bundle or a malformed diagnosis.
  """
  # guard: no bundle at the path — nothing to re-arm or diagnose, and a typo never creates a stray one
  if (jdir := _resolve_jdir(repo, args.jdir)) is None:
    print(f"{Outcome.ERROR_PREFIX}no job directory at {args.jdir!r}")
    return 1

  # clear-dead needs nothing beyond the bundle itself, so it is re-armed and done here
  if args.verb == Verb.CLEAR_DEAD:
    recover.clear_dead_job(jdir)
    print(Outcome.CLEARED)
    return 0

  # permanent-fail: the diagnosis must parse as a mapping before anything is written
  try:
    diagnosis = json.loads(args.diagnosis)
  except json.JSONDecodeError as error:
    print(f"{Outcome.ERROR_PREFIX}--diagnosis parse: {error}")
    return 1

  # guard: the diagnosis file is read back as a mapping by the doctor
  if not isinstance(diagnosis, dict):
    print(f"{Outcome.ERROR_PREFIX}--diagnosis must be a JSON object")
    return 1

  # record the diagnosis beside the bundle and report the outcome word
  recover.permanent_fail(jdir, diagnosis)
  print(Outcome.MARKED)
  return 0


def _run_tree_verb(repo: Path, args: argparse.Namespace) -> int:
  """
  Run `cleanup`, `revert`, or `resume` — the verbs that act on the working tree or the halt.

  Guarantees:
    - A recovery or git failure never reaches the caller as an exception: it is printed as one
      `error: ...` line (`still-dirty: ...` for `resume`) and reported through a non-zero exit code.

  Args:
    repo: Absolute repository root.
    args: Parsed arguments carrying `verb` and that verb's own options.

  Returns:
    Process exit code: 0 on success, 1 when recovery refuses or a git command fails.
  """

  # Contract:
  # A recovery or git failure never reaches the caller as an exception; it becomes one printed
  # `error: ...` line (`still-dirty: ...` for resume) and a non-zero exit, which the recover skill
  # and the doctor agent branch on.

  # every verb here surfaces a recovery or git failure as one printed line, never a traceback
  try:
    # cleanup hands its mode, message, and path shape straight through to the primitive
    if args.verb == Verb.CLEANUP:
      recover.cleanup(repo, args.mode, args.message, paths = args.path, porcelain = args.porcelain)
      print(Outcome.CLEANED)
    # revert restores the named tracked paths
    elif args.verb == Verb.REVERT:
      recover.revert_files(repo, args.path)
      print(Outcome.REVERTED)
    # resume is the only verb left, and the primitive refuses it while the tree is dirty
    else:
      recover.resume(repo)
      print(Outcome.RESUMED)
  except recover.RecoverError as error:
    # resume keeps its documented `still-dirty:` prefix so the skill's branch stays readable
    print(f"{Outcome.STILL_DIRTY_PREFIX if args.verb == Verb.RESUME else Outcome.ERROR_PREFIX}{error}")
    return 1
  except subprocess.CalledProcessError as error:
    # git's own stderr is the useful part of a failed command
    # waiver: the standard bytes-decoding error policy name, not a domain key
    stderr = (error.stderr or b"").decode(errors = "replace").strip()
    print(f"{Outcome.ERROR_PREFIX}{' '.join(error.cmd)} exited {error.returncode}: {stderr}")
    return 1

  # the outcome word was printed by the verb's own branch
  return 0


def cmd_recover(argv: list[str]) -> int:
  """
  Run one `recover` verb and print its outcome.

  Printed outcomes: `halt` prints the halt block as indented JSON or `not_halted`;
  `cleanup` prints `cleaned`; `resume` prints `resumed` or `still-dirty: <reason>`;
  `revert` prints `reverted`; `clear-dead` prints `cleared`; `permanent-fail` prints
  `marked`. A recovery or git failure prints `error: <reason>`.

  Args:
    argv: Argument vector after the `recover` subcommand name.

  Returns:
    Process exit code: 0 on success, 1 on a recovery / git failure, a missing job directory,
    or a `permanent-fail` diagnosis that does not parse as a JSON object.

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
  """
  args = _build_parser().parse_args(argv)
  repo = resolve_repo_root(args.cwd).resolve()

  # halt is read-only: it prints the block the skill branches on and is done before any verb acts
  if args.verb == Verb.HALT:
    halt = recover.read_halt(repo)
    print(Outcome.NOT_HALTED if halt is None else json.dumps(halt, indent = 2))
    return 0

  # the remaining verbs split by what they act on: a job bundle, or the tree and halt state
  if args.verb in (Verb.CLEAR_DEAD, Verb.PERMANENT_FAIL):
    return _run_job_verb(repo, args)
  return _run_tree_verb(repo, args)
