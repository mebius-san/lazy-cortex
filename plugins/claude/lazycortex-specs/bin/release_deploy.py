"""
Logic behind the `lazycortex-specs release-deploy <release-note> <staging|production>` verb.

The verb runs one deploy target of the product's `release.deploy` configuration against the repository, keeps the
command's output in a log file, and journals the outcome on the release note. `release-publish` reuses the runner
for the production deploy of a `Publish` tick.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import history_journal  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_explainers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import release_version  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import scaffold_asset  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import HistoryEvent, ReleaseConfigKey  # noqa: E402


_ENCODING = "utf-8"
_ENV_REPO_ROOT = "LAZY_REPO_ROOT"

# The bot identity this verb commits under
DEPLOY_NAME = "lazy-spec.release-deploy"

# The deploy command's wall-clock ceiling, in seconds
TIMEOUT_SECONDS = 1800
# Exit codes the runner reports for failures the command itself never returned
EXIT_TIMEOUT = 124
EXIT_NOT_RUNNABLE = 127
# The deploy logs land in the run-log corner of the repository, under this verb's own name
LOG_DIR = Path(".logs/claude/lazy-spec.release-deploy")
_LOG_SUFFIX = ".log"
_LOG_STAMP = "%Y-%m-%d_%H-%M-%S"
_WRITE_MODE = "w"

# Result keys
_STATUS = "status"
_REASON = "reason"
_STATUS_REFUSED = "refused"
_TARGET = "target"
_OK = "ok"
_EXIT_CODE = "exit_code"
_LOG = "log"
_URL = "url"


# ----------------------------------------------------------------------------------------
@dataclass(frozen = True)
class DeployResult:
  """
  The outcome of one deploy-target run.

  Attributes:
    target: The target name, `staging` or `production`.
    ok: Whether the command exited zero.
    exit_code: The command's exit code, or the runner's own code for a timeout or an unrunnable command.
    log_path: The file holding the command's combined output, or None when no log was written.
    url: The target's declared address, empty when it has none.
  """

  target: str
  ok: bool
  exit_code: int
  log_path: Path | None
  url: str


def find_target_config(record: dict, target: str) -> dict | None:
  """
  Look up one deploy target in a product record.

  Args:
    record: The product's record from `lazy.settings.json`.
    target: The target name, `staging` or `production`.

  Returns:
    The target's object (`command` and optional `url`) when the record declares it with a command, else None.
  """
  release = record.get(ReleaseConfigKey.SECTION)
  deploy = release.get(ReleaseConfigKey.DEPLOY) if isinstance(release, dict) else None
  config = deploy.get(target) if isinstance(deploy, dict) else None

  # guard: a target without a command list is not runnable, so it counts as undeclared
  if not isinstance(config, dict) or not isinstance(config.get(ReleaseConfigKey.COMMAND), list):
    return None
  return config


def run_target(repo: Path, record: dict, target: str, *, log_dir: Path) -> DeployResult:
  """
  Run one deploy target's command inside the repository, capturing its output in a log file.

  Notes:
    - The command receives no input, so a prompt it raises cannot be answered.
    - Blocks until the command ends or the timeout elapses; a timeout stops the command together with every process
      it started.

  Args:
    repo: Repository root, the command's working directory.
    record: The product's record from `lazy.settings.json`.
    target: The target name, `staging` or `production`.
    log_dir: Where the log file is written; created when absent.

  Returns:
    The run's outcome; the log file is named `<target>-<UTC timestamp>.log`.

  Raises:
    ValueError: If the record declares no such target.
  """
  config = find_target_config(record, target)

  # guard: callers check the target first; an undeclared one is a programming error here
  if config is None:
    raise ValueError(f"product declares no deploy target {target!r}")

  # the command's whole output goes to one log file, stderr folded into stdout in order
  log_dir.mkdir(parents = True, exist_ok = True)
  log_path = log_dir / f"{target}-{datetime.now(UTC).strftime(_LOG_STAMP)}{_LOG_SUFFIX}"
  with log_path.open(_WRITE_MODE, encoding = _ENCODING) as log:
    try:
      # no operator answers a prompt, and the command leads its own process group so a timeout reaches its children
      with subprocess.Popen(
          config[ReleaseConfigKey.COMMAND], cwd = str(repo), stdin = subprocess.DEVNULL, stdout = log,
          stderr = subprocess.STDOUT, start_new_session = True,
      ) as process:
        try:
          exit_code = process.wait(timeout = TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
          # the whole group goes, the command's own children included; a group already gone needs no kill
          with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
          process.wait()
          log.write(f"\n[release-deploy] command timed out after {TIMEOUT_SECONDS} s\n")
          exit_code = EXIT_TIMEOUT
    except OSError as error:
      log.write(f"\n[release-deploy] command could not run: {error}\n")
      exit_code = EXIT_NOT_RUNNABLE
  return DeployResult(target, exit_code == 0, exit_code, log_path, str(config.get(ReleaseConfigKey.URL) or ""))


def render_history_line(note: Path, result: DeployResult, log_rel: str) -> str:
  """
  Render the `# History` line a deploy outcome leaves on a release note.

  Args:
    note: The release note the line is written to.
    result: The run's outcome.
    log_rel: The log file's repo-relative path.

  Returns:
    The rendered line tail in the note's authoring language.
  """
  if result.ok:
    return note_explainers.history_line(note, HistoryEvent.DEPLOYED, target = result.target, log = log_rel)
  return note_explainers.history_line(note, HistoryEvent.DEPLOY_FAILED, target = result.target, log = log_rel,
                                      code = str(result.exit_code))


def to_dict(repo: Path, result: DeployResult) -> dict:
  """
  Render a run's outcome as the verb's JSON summary.

  Args:
    repo: Repository root the log path is made relative to.
    result: The run's outcome.

  Returns:
    `{"target", "ok", "exit_code", "log", "url"}` with the log as a repo-relative path, empty when none was written.
  """
  log_rel = result.log_path.relative_to(repo).as_posix() if result.log_path is not None else ""
  return { _TARGET: result.target, _OK: result.ok, _EXIT_CODE: result.exit_code, _LOG: log_rel, _URL: result.url }


def main(argv: list[str]) -> int:
  """
  Run one deploy target of a release's product and journal the outcome on the release note.

  The repository root comes from the `LAZY_REPO_ROOT` environment variable, falling back to the process working
  directory.

  Notes:
    - Prints the JSON summary of `to_dict` on stdout, or a refusal when the product declares no such target.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 when the deploy succeeded, 1 when it failed or the target is undeclared, 2 when the note is missing.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs release-deploy")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("note")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("target", choices = ( ReleaseConfigKey.STAGING, ReleaseConfigKey.PRODUCTION ))
  args = parser.parse_args(argv)
  repo = scaffold_asset.repo_root(Path(os.environ.get(_ENV_REPO_ROOT) or Path.cwd()))
  note = (repo / args.note).resolve()

  # guard: the note names the release; nothing to journal on without it
  if not note.is_file():
    sys.stderr.write(f"no such note: {note}\n")
    return 2

  # guard: a target the product does not declare is refused before anything runs
  _key, record = resolve_product.effective_record_by_path(repo, note.relative_to(repo).as_posix())
  if record is None or find_target_config(record, args.target) is None:
    print(json.dumps({ _STATUS: _STATUS_REFUSED, _REASON: f"product declares no deploy target {args.target!r}" }))
    return 1

  # the run, then its outcome on the release note's journal
  result = run_target(repo, record, args.target, log_dir = repo / LOG_DIR)
  summary = to_dict(repo, result)
  history_journal.append_to_file(note, render_history_line(note, result, summary[_LOG]), repo = repo)
  release_version.commit_paths(
      repo, [ note ], author = DEPLOY_NAME,
      subject = f"{DEPLOY_NAME}: {args.target} of {note.parent.name} {'ok' if result.ok else 'failed'}",
  )
  print(json.dumps(summary))
  return 0 if result.ok else 1


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
