"""
Logic behind the `lazycortex-specs cancel-sweep` verb — applies the cancel cascade to assets an earlier plugin
version cancelled without it.

Such an asset reads `spec_cancelled: true` while its documents still sit at their old stages, with reviews and the
asset's expert job possibly still running. For each one the verb stops the reviews in the asset folder, cancels the
asset's running job and drops its pending wake, moves its staged documents to `cancelled` with the stage each had
recorded, and on a release repaints the members, one commit per asset under the flip-gate bot identity. The
cancellation flag is left as it is. A second run finds nothing left to sweep. A run that refused an asset exits 1,
and each refused entry carries the cancel's per-document reasons. An asset whose sweep failed is named in `failed`
with the reason, and with the job its cancel had already killed when there was one; the run goes on with the assets
after it and exits 2 when any asset failed. A run that fails outside that loop prints a JSON error object and
exits 2.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import asset_uncancel  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_keys import FlipResult  # noqa: E402  # pylint: disable=import-error,wrong-import-position


_MD_SUFFIX = ".md"
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"

# waiver: the result's own wire-shape keys, read by the migration step and the tests
_PENDING_KEY = "pending"
_SWEPT_KEY = "swept"
_REFUSED_KEY = "refused"
_FAILED_KEY = "failed"
_KILLED_JOB_KEY = "killed_job"
_ASSET_KEY = "asset"
_CANCELLED_KEY = "cancelled"
_STOPPED_KEY = "stopped"
_REASON_KEY = "reason"
_ERROR_KEY = "error"

# The exit code of a failed run, told apart from both `--check` answers
_EXIT_FAILED = 2

# The exit code of a sweep that refused at least one asset
_EXIT_REFUSED = 1


def sweep(repo: Path, *, dry_run: bool = False, today: str | None = None) -> dict:
  """
  Apply the cancel cascade to every cancelled asset whose documents were left behind.

  Guarantees:
    - Idempotent: an asset swept once has nothing left behind, so a second run lists it nowhere and writes nothing.
    - A dry run writes nothing and leaves `swept`, `refused` and `failed` empty.
    - A refused asset is named with its reason and the cancel's own per-document `refused` list, writes nothing, and
      does not stop the sweep of the others.
    - The result always carries a `failed` list; an asset whose sweep raises is named in it with its reason, and the
      sweep goes on with the next asset. When the asset's job had tracked running before the sweep was killed, the
      entry also carries `killed_job`, the retired cancelled record.

  Args:
    repo: The repository root, or any directory under the one holding `.claude/lazy.settings.json`.
    dry_run: When True, list the assets left behind and write nothing.
    today: Optional ISO date forwarded into the woken release members' History lines.

  Returns:
    `{"pending", "swept", "refused", "failed"}` — the asset folders left behind, as paths relative to the settings
    root in walk order; one `{"asset", "cancelled", "stopped", "refused"}` entry per asset swept; one
    `{"asset", "reason", "refused"}` entry per asset whose sweep was refused with nothing written, `refused` being
    the cancel's own per-document list; one `{"asset", "reason"[, "killed_job"]}` entry per asset whose sweep
    raised, `killed_job` naming the job that sweep had already killed. A dry run leaves `swept`, `refused` and
    `failed` empty.
  """

  # Contract:
  # The sweep is idempotent: an asset swept once has nothing left behind, so a second run lists it nowhere and
  # writes nothing.

  # Contract:
  # A dry run writes nothing and leaves `swept`, `refused` and `failed` empty.

  # Contract:
  # A refused asset is named with its reason and the cancel's own per-document `refused` list, writes nothing, and
  # does not stop the sweep of the others.

  # Contract:
  # The result always carries a `failed` list. An asset whose sweep raises is named in it as `{"asset", "reason"}`,
  # plus `killed_job`, the retired cancelled record, when the asset's job had tracked running before the sweep
  # was killed, and the sweep goes on with the next asset, so one asset's failure never leaves the others unswept.

  settings_root = spec_paths.require_settings_root(repo)
  result: dict = { _PENDING_KEY: [], _SWEPT_KEY: [], _REFUSED_KEY: [], _FAILED_KEY: [] }

  # every asset folder under the content root whose status note is cancelled and whose documents were left behind
  pending: list[Path] = []
  for dirpath, dirnames, filenames in os.walk(spec_paths.spec_content_root(settings_root)):
    dirnames.sort()
    folder = Path(dirpath)
    if f"{folder.name}{_MD_SUFFIX}" in filenames and asset_uncancel.is_sweep_due(folder):
      pending.append(folder)
  result[_PENDING_KEY] = [ folder.relative_to(settings_root).as_posix() for folder in pending ]

  # a dry run ends at the listing
  if dry_run:
    return result

  # each asset is swept on its own, one commit apiece; a refused or failed one is named and the run goes on
  for folder, rel in zip(pending, result[_PENDING_KEY], strict = True):
    note = folder / f"{folder.name}{_MD_SUFFIX}"
    running = asset_uncancel.read_running_job(note)
    try:
      swept = asset_uncancel.sweep_cancelled(folder, today = today)
    # waiver: one asset's failure must not leave the assets after it unswept; it is named in the result and the
    # run exits as failed
    except Exception as error:  # pylint: disable=broad-exception-caught
      killed = asset_uncancel.find_killed_job(note, running)
      result[_FAILED_KEY].append({ _ASSET_KEY: rel, _REASON_KEY: f"{type(error).__name__}: {error}",
                                   **({ _KILLED_JOB_KEY: killed } if killed is not None else {}) })
      continue
    if swept[FlipResult.STATUS] == FlipResult.REFUSED:
      result[_REFUSED_KEY].append({ _ASSET_KEY: rel, _REASON_KEY: swept.get(_REASON_KEY, ""),
                                    _REFUSED_KEY: swept.get(_REFUSED_KEY, []) })
      continue
    result[_SWEPT_KEY].append({ _ASSET_KEY: rel, _CANCELLED_KEY: swept[_CANCELLED_KEY],
                                _STOPPED_KEY: swept[_STOPPED_KEY], _REFUSED_KEY: swept[_REFUSED_KEY] })
  return result


def _fail(error: BaseException) -> int:
  """
  Report a failed run on stderr and as one JSON error object on stdout.

  Args:
    error: What failed the run.

  Returns:
    The failed-run exit code.
  """
  # a caller reading stdout gets the failure as JSON, an operator reading stderr gets it too
  sys.stderr.write(f"cancel-sweep: {error!r}\n")
  print(json.dumps({ _ERROR_KEY: f"{type(error).__name__}: {error}" }))
  return _EXIT_FAILED


def main(argv: list[str]) -> int:
  """
  Run `sweep` from the command line and print its result as JSON.

  Guarantees:
    - `--dry-run` and `--check` write nothing.
    - `--check` exits 0 when an asset is left behind and 1 when none is.
    - Without `--check`, the run exits 2 when any asset failed, else 1 when any asset was refused, else 0.
    - Any failure, an asset's failed sweep included, exits 2, so no failure is read as a `--check` answer.
    - A failure outside the per-asset loop also prints one JSON object carrying an `error` key on stdout.

  Args:
    argv: Command-line arguments, excluding the program name; `--dry-run` lists without writing, `--check` lists
      without writing and answers through the exit code whether an asset is left behind, `--cwd` names the
      repository root (falling back to the `LAZY_REPO_ROOT` environment variable, then the process working
      directory).

  Returns:
    Exit code: with `--check`, 0 when an asset is left behind and 1 when none is; otherwise 2 when any asset's sweep
    failed, else 1 when any asset was refused, else 0; 2 on a failure of the run as a whole.
  """

  # Contract:
  # `--dry-run` and `--check` write nothing.

  # Contract:
  # `--check` exits 0 when an asset is left behind and 1 when none is; the migration step's `applies_when` reads this
  # answer.

  # Contract:
  # Without `--check`, the run exits 2 when any asset failed, else 1 when any asset was refused, else 0; `--check`
  # keeps its own answer.

  # Contract:
  # Any failure, an asset's failed sweep and a failure outside the per-asset loop alike, exits 2, so no failure is
  # ever read as a `--check` answer.

  # Contract:
  # A failure outside the per-asset loop also prints one JSON object carrying an `error` key on stdout, so a caller
  # that parses stdout never reads a failed run as an empty answer; an asset's failed sweep is named in `failed`
  # of the printed result instead.

  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-specs cancel-sweep")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--dry-run", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--check", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None)
  args = parser.parse_args(argv)

  # the repo root comes from `--cwd`, else the daemon's env var, else the process cwd
  repo = Path(args.cwd or os.environ.get(_ENV_REPO_ROOT) or os.getcwd()).resolve()

  # a check runs dry; any failure exits 2, so no flag ever reads a failure as an answer
  try:
    result = sweep(repo, dry_run = args.dry_run or args.check)
  # waiver: broad catch is the boundary of the migration step's `applies_when` predicate, which reads exit 1 as
  # "nothing to do"; an uncaught error would exit 1 too, so every failure must leave as exit 2
  except Exception as error:  # pylint: disable=broad-exception-caught
    return _fail(error)
  # a refused content root is a `BaseException` the broad catch above lets through; it fails the run the same way
  except spec_paths.VaultRootError as error:
    return _fail(error)

  # the result goes to stdout for the caller to read
  print(json.dumps(result))

  # a check answers through its exit code; a sweep exits 1 when an asset was refused
  if args.check:
    return 0 if result[_PENDING_KEY] else 1
  if result[_FAILED_KEY]:
    return _EXIT_FAILED
  return _EXIT_REFUSED if result[_REFUSED_KEY] else 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
