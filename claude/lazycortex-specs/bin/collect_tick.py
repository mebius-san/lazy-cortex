"""Postman sweep for the specs job-marker sidecar: run gate-tick on every note with recorded work.

A finished expert job leaves its terminal marker (`DONE` / `DEAD` / `CANCELLED`) inside
`.experts/.jobs/<expert>/<job_id>/` — a path outside every asset folder, so the md-scan
`lazy-spec.gate-tick` routine (gated on the note's own directory changing) never fires on it: the
note's folder is untouched when a job finishes. This worker is the delivery channel, the specs-side
analog of `lazycortex-review`'s `collect-tick`: each tick it reads the sidecar rows
(`spec_job_markers.entries`) and runs the same per-note `gate_tick` poll in-process for every note
still carrying a marker or a pending wake. gate-tick's own job-done commit is what then wakes
`lazy-spec.coordinator-watch`; this sweep commits nothing itself and dispatches nothing itself.

A row whose note file no longer exists is stale runtime scratch and is skipped silently. One note's
failing poll is logged to stderr and folded into the summary's `error` field without stopping the
rest of the pass (the error-ledger contract — a failed sweep must not report success via exit 0).
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import argparse
import json
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import gate_tick  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_job_markers  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_keys import TickAction  # noqa: E402


# waiver: 'notes'/'ticked'/'error' are this sweep's own wire-shape keys, mirroring the review
# sibling's 'files'/'dispatched'/'error' summary shape
_NOTES_KEY = "notes"
_TICKED_KEY = "ticked"
_ERROR_KEY = "error"


def collect_tick(repo: Path) -> dict:
  """
  Poll every sidecar-recorded note once and report how many polls did work.

  Args:
    repo: Absolute path to the repository root.

  Returns:
    `{"notes": N, "ticked": M}` — N is the number of rows whose note existed and whose poll
    completed, M is how many of those polls reported a non-noop action. Carries an additional
    `"error"` field summarizing the failures when one or more polls raised.
  """
  swept = 0
  ticked = 0
  failed: list[str] = []

  # one gate-tick poll per recorded row; rows exist only while a job or a wake is live, so an
  # idle repo costs one sidecar read and nothing else
  for key in sorted(spec_job_markers.entries(repo)):
    note = repo / key
    # guard: stale row for a deleted note — runtime scratch, skipped silently and uncounted
    if not note.is_file():
      continue
    try:
      result = gate_tick.gate_tick(note)
    # waiver: this sweep's per-note error boundary — one bad note must not stop the rest
    except Exception as error:
      sys.stderr.write(f"collect-tick: {key}: {error}\n")
      failed.append(key)
      continue
    swept += 1
    if result.get(TickAction.ACTION) != TickAction.NOOP:
      ticked += 1

  # the "error" field is additive — a clean sweep's summary stays exactly the two counters
  summary: dict[str, int | str] = { _NOTES_KEY: swept, _TICKED_KEY: ticked }
  if failed:
    summary[_ERROR_KEY] = f"{len(failed)} note(s) failed to tick: {', '.join(failed)}"
  return summary


def main(argv: list[str]) -> int:
  """
  Run `collect_tick` from the command line and print its summary.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: `0` when every poll completed, `1` when at least one note failed to tick.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog = "lazycortex-specs collect-tick")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--repo", default = ".")
  args = parser.parse_args(argv)

  # resolve --repo then run the sweep; only the two counters are printed — the error detail
  # already went to stderr line by line
  repo = Path(args.repo).resolve()
  summary = collect_tick(repo)
  print(json.dumps({ _NOTES_KEY: summary[_NOTES_KEY], _TICKED_KEY: summary[_TICKED_KEY] }))
  return 1 if _ERROR_KEY in summary else 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
