"""
Runtime garbage collection for the specs plugin's per-note sidecars, plus the `runtime-gc` verb that runs it.

Two sidecars under `.runtime/` keep one row per note and are never pruned by the workers that write them: the
dispatch cursors and the stage-lag record. A note that is deleted or moved leaves its row behind for good. This
sweep drops every row whose note no longer exists and journals each drop as one JSON line under
`.logs/lazy-spec/runtime-gc.jsonl`. The job-marker sidecar is not touched — `gate-tick` owns those markers.

A failure on one sidecar is recorded in the summary and never stops the other; the verb then exits 1, so the
daemon records the routine as failed.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Callable


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import coordinator_dispatch  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_job_markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# The journal every drop is appended to, relative to the repository root.
_JOURNAL = Path(".logs") / "lazy-spec" / "runtime-gc.jsonl"

# waiver: the summary's and the journal line's own wire-shape keys, read by the operator and the tests
_DRY_RUN_KEY = "dry_run"
_SIDECARS_KEY = "sidecars"
_DROPPED_KEY = "dropped"
_ERROR_KEY = "error"
_TIME_KEY = "time"
_SIDECAR_KEY = "sidecar"
_KEY_KEY = "key"

# The journal's time stamp precision and the file mode that appends to it.
_TIMESPEC = "seconds"
_APPEND_MODE = "a"


def journal_path(repo: Path) -> Path:
  """
  Locate the runtime-gc journal.

  Args:
    repo: The repository root.

  Returns:
    The path of `<repo>/.logs/lazy-spec/runtime-gc.jsonl`, whether or not it exists.
  """
  return repo / _JOURNAL


def sweep(repo: Path, *, dry_run: bool = False) -> dict:
  """
  Drop every sidecar row whose note no longer exists, and report what was dropped per sidecar.

  Guarantees:
    - A failure on one sidecar never stops the sweep of the other.
    - A dry run writes nothing — no sidecar and no journal.

  Args:
    repo: The repository root.
    dry_run: When True, report the rows that would be dropped and write nothing.

  Returns:
    `{"dry_run": <bool>, "sidecars": {<sidecar file name>: {"dropped": [<note key>, ...]}}}`, one entry per
    swept sidecar; an entry whose sidecar failed also carries `"error": "<text>"`.
  """

  # Contract:
  # A failure on one sidecar never stops the sweep of the other, and a dry run writes nothing.

  # each owner prunes its own store; the call goes through the module attribute at call time
  pruners: list[tuple[Path, Callable[[], list[str]]]] = [
    (
      coordinator_dispatch.cursor_store_path(repo),
      lambda: coordinator_dispatch.prune_dispatch_cursors(repo, _vanished(repo), dry_run = dry_run),
    ),
    (
      spec_job_markers.stage_lag_path(repo),
      lambda: spec_job_markers.prune_stage_lag(repo, _vanished(repo), dry_run = dry_run),
    ),
  ]

  # one sidecar at a time; a failure is recorded in its own entry and the next sidecar still runs
  sidecars: dict[str, dict] = {}
  for path, prune in pruners:
    entry: dict[str, list[str] | str] = { _DROPPED_KEY: [] }
    sidecars[path.name] = entry
    try:
      dropped = prune()
      entry[_DROPPED_KEY] = dropped
      if not dry_run:
        _journal(repo, path.name, dropped)
    # waiver: this sweep's per-sidecar error boundary — one failing sidecar must not stop the other
    except Exception as error:  # pylint: disable=broad-exception-caught
      entry[_ERROR_KEY] = f"{type(error).__name__}: {error}"
  return { _DRY_RUN_KEY: dry_run, _SIDECARS_KEY: sidecars }


def _vanished(repo: Path) -> Callable[[str], bool]:
  """
  Build the predicate that selects a sidecar row whose note no longer exists.

  Args:
    repo: The repository root the note keys are relative to.

  Returns:
    A predicate that is True for a note key naming no existing path under `repo`.
  """
  return lambda key: not (repo / key).exists()


def _journal(repo: Path, sidecar: str, keys: list[str]) -> None:
  """
  Append one journal line per dropped row.

  Args:
    repo: The repository root.
    sidecar: The sidecar file name the rows were dropped from.
    keys: The dropped note keys.

  Raises:
    OSError: The journal could not be created or appended to.
  """
  # guard: nothing dropped leaves the journal untouched, not even created
  if not keys:
    return

  # one JSON object per line, all stamped with the same UTC time
  path = journal_path(repo)
  path.parent.mkdir(parents = True, exist_ok = True)
  now = datetime.now(UTC).isoformat(timespec = _TIMESPEC)
  with path.open(_APPEND_MODE, encoding = "utf-8") as handle:
    for key in keys:
      handle.write(json.dumps({ _TIME_KEY: now, _SIDECAR_KEY: sidecar, _KEY_KEY: key }) + "\n")


def main(argv: list[str]) -> int:
  """
  Run `sweep` from the command line and print its summary as JSON.

  Args:
    argv: Command-line arguments, excluding the program name; `--dry-run` reports without writing, `--repo` names
      the repository root.

  Returns:
    Exit code: `1` when a sidecar failed, `0` otherwise.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-specs runtime-gc")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--dry-run", action = "store_true")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--repo", default = ".")
  args = parser.parse_args(argv)

  # the whole summary goes to stdout; a failed sidecar turns the exit code red
  summary = sweep(Path(args.repo).resolve(), dry_run = args.dry_run)
  print(json.dumps(summary))
  return 1 if any(_ERROR_KEY in entry for entry in summary[_SIDECARS_KEY].values()) else 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
