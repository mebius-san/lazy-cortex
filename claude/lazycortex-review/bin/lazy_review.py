"""Main CLI for lazy-review (dispatched by the `lazycortex-review` shim).

Subcommands:

- `process-file <path>` — drive the state-machine for ONE file. The
                 routine entrypoint at runtime: the daemon's md-scan
                 routine spawns `lazycortex-review process-file
                 <absolute-path>` per matching file, with PID-based
                 dedup.
- `status`   — delegate to :mod:`status`.
- `start`    — delegate to :mod:`start`.
- `submit`   — delegate to :mod:`submit` (skip opening writer round).
- `stop`     — delegate to :mod:`stop`.
- `finalize` — delegate to :mod:`finalize`.

The CLI writes per-tick logs to
`<repo>/.logs/lazy-review/runs/<UTC-timestamp>.jsonl` (one JSON line
per file processed) per `lazy-log.logging`.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
from keys import JobKey  # noqa: E402


def _file_has_uncommitted_edits(repo: Path, file_path: Path) -> bool:
  """
  Return True when the given file carries staged or unstaged modifications in the repo.

  Closes the race-window between the daemon's iteration-level `_check_working_tree` (clean at
  iteration start) and the per-routine subprocess exec (operator may have edited the file in
  the interim). Without this re-check the subprocess would read the dirty FS, generate output
  from the operator's WIP, and stage-and-commit it under the bot's identity — silently
  mis-attributing operator content to a mechanical commit.

  Mirrors the daemon's `_check_working_tree` in `lazycortex-core/bin/runtime_daemon.py`, but
  scoped to a single path (cheaper and avoids tripping on unrelated dirt in the worktree).

  Args:
    repo: Repository root path.
    file_path: The fixture path to inspect.

  Returns:
    True when `git status --porcelain -- <file>` yields any non-empty output. False on clean
    state, on a git-invocation failure (best-effort), or when git is unavailable.
  """
  try:
    result = subprocess.run(
      [ "git", "--no-optional-locks", "status", "--porcelain", "--", str(file_path) ],
      cwd = str(repo), capture_output = True, text = True, check = False,
    )
  except FileNotFoundError:
    return False
  # guard: git invocation failed — best-effort, do not block work on a failed probe
  if result.returncode != 0:
    return False
  return bool(result.stdout.strip())


def _log_tick(repo: Path, result: dict) -> None:
  # waiver: filesystem path idiom
  log_dir = repo / ".logs" / "lazy-review" / "runs"
  log_dir.mkdir(parents=True, exist_ok=True)
  ts = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
  log_file = log_dir / f"{ts}.jsonl"
  # waiver: stdlib encoding/mode idiom
  with log_file.open("a") as fh:
    for action in result.get(JobKey.ACTIONS, []):
      fh.write(json.dumps(action) + "\n")


def cmd_process_file(args: argparse.Namespace) -> int:
  """
  Run the state-machine on a single file.

  The `command:` payload of the md-scan routine — invoked once per matching file per tick by the
  daemon. The file path comes from the routine appending `str(file)` to the command's argv.

  Exit code policy (lazy-core errors spec, GAP B closure): a summary that carries an `error` key
  is a routine-tick failure. The CLI surfaces it via a non-zero exit + the error text on stderr so
  the core daemon's emit-#4 captures `routine_error` in the ledger. Without this, exit=0 makes the
  failure invisible to the ledger — exactly Bug-77 class 4.

  Args:
    args: Parsed namespace with `file`, `repo`, and `quiet` attributes.

  Returns:
    0 on success, 1 if the dispatcher summary carries an error.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
  import dispatcher  # type: ignore
  repo = Path(args.repo).resolve()
  file_path = Path(args.file).resolve()
  # guard: operator edited this file in the race window between the daemon's iteration-level
  # dirty-tree check (clean) and this subprocess exec — silent skip mirrors the daemon-level
  # behavior so the next tick after the operator commits picks up the work cleanly
  if _file_has_uncommitted_edits(repo, file_path):
    skip_summary = { JobKey.OUTCOME: "skipped-operator-edit-in-flight",
                     JobKey.FILE:    str(file_path) }
    if not args.quiet:
      print(json.dumps(skip_summary, indent = 2))
    _log_tick(repo, { JobKey.ACTIONS: [ skip_summary ] })
    return 0
  summary = dispatcher.process_one_file(repo, file_path)
  if not args.quiet:
    print(json.dumps(summary, indent=2))
  _log_tick(repo, {JobKey.ACTIONS: [summary]})
  err = summary.get(JobKey.ERROR)
  if err:
      # guard: surface the error text so the daemon's classifier (`_classify_routine_error`)
      # can map `compute_inputs_failed` / `config_violation:` to the halt-class cause
    print(f"lazy-review: {err}", file=sys.stderr)
    return 1
  return 0


def cmd_status(args: argparse.Namespace) -> int:
  """
  Delegate the `status` subcommand to the status module.

  Args:
    args: Parsed namespace with a `file` attribute.

  Returns:
    Exit code from the status module.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
  import status  # type: ignore
  return status.main([args.file])


def cmd_start(args: argparse.Namespace) -> int:
  """
  Delegate the `start` subcommand to the start module.

  Args:
    args: Parsed namespace with `file` and optional `expert` attributes.

  Returns:
    Exit code from the start module.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
  import start  # type: ignore
  forward: list[str] = [args.file]
  if args.expert:
    forward.extend(["--expert", args.expert])
  return start.main(forward)


def cmd_submit(args: argparse.Namespace) -> int:
  """
  Delegate the `submit` subcommand to the submit module.

  Args:
    args: Parsed namespace with `file` and optional `expert` attributes.

  Returns:
    Exit code from the submit module.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
  import submit  # type: ignore
  forward: list[str] = [args.file]
  if args.expert:
    forward.extend(["--expert", args.expert])
  return submit.main(forward)


def cmd_stop(args: argparse.Namespace) -> int:
  """
  Delegate the `stop` subcommand to the stop module.

  Args:
    args: Parsed namespace with a `file` attribute.

  Returns:
    Exit code from the stop module.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
  import stop  # type: ignore
  return stop.main([args.file])


def cmd_finalize(args: argparse.Namespace) -> int:
  """
  Delegate the `finalize` subcommand to the finalize module.

  Args:
    args: Parsed namespace with a `file` attribute.

  Returns:
    Exit code from the finalize module.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  # waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
  import finalize  # type: ignore
  return finalize.main([args.file])


def build_parser() -> argparse.ArgumentParser:
  """
  Build and return the top-level argument parser for the lazy-review CLI.

  Returns:
    Configured argument parser with all subcommands registered.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog="lazy-review")
  # waiver: argparse CLI signature, not a domain key
  sub = parser.add_subparsers(dest="cmd", required=True)

  # waiver: argparse CLI signature, not a domain key
  p_pf = sub.add_parser("process-file", help="state-machine for one file")
  # waiver: argparse CLI signature, not a domain key
  p_pf.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_pf.add_argument("--repo", default=".")
  # waiver: argparse CLI signature, not a domain key
  p_pf.add_argument("--quiet", action="store_true")
  p_pf.set_defaults(func=cmd_process_file)

  # waiver: argparse CLI signature, not a domain key
  p_status = sub.add_parser("status", help="introspect one file")
  # waiver: argparse CLI signature, not a domain key
  p_status.add_argument("file")
  p_status.set_defaults(func=cmd_status)

  # waiver: argparse CLI signature, not a domain key
  p_start = sub.add_parser("start", help="opt a file into review")
  # waiver: argparse CLI signature, not a domain key
  p_start.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_start.add_argument("--expert", default=None)
  p_start.set_defaults(func=cmd_start)

  p_submit = sub.add_parser(
      # waiver: argparse CLI signature, not a domain key
      "submit", help="opt a file into review skipping the opening writer round")
  # waiver: argparse CLI signature, not a domain key
  p_submit.add_argument("file")
  # waiver: argparse CLI signature, not a domain key
  p_submit.add_argument("--expert", default=None)
  p_submit.set_defaults(func=cmd_submit)

  # waiver: argparse CLI signature, not a domain key
  p_stop = sub.add_parser("stop", help="opt a file out of review")
  # waiver: argparse CLI signature, not a domain key
  p_stop.add_argument("file")
  p_stop.set_defaults(func=cmd_stop)

  # waiver: argparse CLI signature, not a domain key
  p_final = sub.add_parser("finalize", help="finalize a fully-approved doc")
  # waiver: argparse CLI signature, not a domain key
  p_final.add_argument("file")
  p_final.set_defaults(func=cmd_finalize)

  return parser


def main(argv: list[str]) -> int:
  """
  Parse arguments and dispatch to the appropriate subcommand handler.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code from the dispatched subcommand.
  """
  parser = build_parser()
  args = parser.parse_args(argv)
  return args.func(args)


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
