"""Inline icon repaint for spec bot commits.

Hand it the repo-relative notes a commit is about to carry and it asks the obsidian plugin's
`sync-paths` op to refresh their icon frontmatter, returning the paths that actually changed so
the caller folds them into the same commit. No separate icons commit is born, and no coordinator
reads a repaint as an operator edit.

Two forms: the best-effort one, where a host without the obsidian plugin's CLI or a failing worker
yields an empty list and never raises, and a checked one that raises on a failed repaint so a
caller can report it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_paths import resolve_plugin_cli  # noqa: E402  # pylint: disable=import-error,wrong-import-position


class RepaintFailedError(RuntimeError):
  """
  Failure of an icon repaint that was attempted but did not complete.
  """


def repaint_paths(repo: Path, paths: list[str]) -> list[str]:
  """
  Repaint icon frontmatter for `paths` via the obsidian plugin's `sync-paths` op, best-effort.

  The non-raising form of `repaint_paths_checked`, for callers that do not report a failed repaint.

  Guarantees:
    - Never raises; any failure — the obsidian plugin absent, the environment unset, the
      worker exiting non-zero, or unparseable output — yields an empty list instead.

  Args:
    repo: Absolute path to the repository root.
    paths: Repo-relative POSIX paths of the notes about to be committed.

  Returns:
    Repo-relative paths whose frontmatter the repaint actually changed; empty when the
    repaint was unavailable, failed, or changed nothing.
  """

  # Contract:
  # This call never raises: any failure — the obsidian plugin absent, the environment unset,
  # the worker exiting non-zero, or unparseable output — yields an empty list instead.

  # Domain(plugin.boundaries):
  # # Cosmetic side effects never gate the commit they ride with
  # Refreshing a note's icon is bookkeeping for how the file looks in the vault, never a
  # correctness requirement for the change the note is actually about. Asking a sibling plugin to
  # do that refresh is therefore always best-effort: the sibling being absent, misconfigured, or
  # simply failing this one time must never stop or delay the substantive commit it was meant to
  # ride along with, and produces no partial or retried effect of its own — the note either gets
  # its icon refreshed together with the change, or it does not, silently, until the next change
  # gives the repaint another chance.

  # a failed repaint reads as one that changed nothing
  try:
    return repaint_paths_checked(repo, paths)
  except RepaintFailedError:
    return []


def repaint_paths_checked(repo: Path, paths: list[str]) -> list[str]:
  """
  Repaint icon frontmatter for `paths` via the obsidian plugin's `sync-paths` op, telling a failure apart.

  Asks the obsidian plugin to refresh the icons of the named repo-relative notes and reports which
  of them changed.

  Guarantees:
    - A repaint that was attempted and failed raises `RepaintFailedError`; it never reads as a repaint that
      changed nothing.
    - An unavailable repaint — no paths, no obsidian plugin on this host, or a worker that exits cleanly with no
      output because it stays inert on this vault — is not a failure and yields an empty list.

  Args:
    repo: Absolute path to the repository root.
    paths: Repo-relative POSIX paths of the notes about to be committed.

  Returns:
    Repo-relative paths whose frontmatter the repaint actually changed; empty when the
    repaint was unavailable or changed nothing.

  Raises:
    RepaintFailedError: If the worker could not be started, exited non-zero, or printed output that is not a
      JSON object with a `touched` list.
  """

  # Contract:
  # A repaint that was attempted and failed raises `RepaintFailedError`, never an empty list,
  # so a caller can tell a failure from a repaint that changed nothing.

  # Contract:
  # An unavailable repaint — no paths, no obsidian plugin on this host, or a worker that exits cleanly
  # with no output because it stays inert on this vault — is NOT a failure.

  # guard: nothing to repaint — skip the subprocess entirely
  if not paths:
    return []

  # the obsidian CLI through the shared sibling lookup; absence means no repaint here
  # waiver: sibling plugin's CLI name per dev.plugin-boundaries § 1c, not a domain key
  cli = resolve_plugin_cli("lazycortex-obsidian", dev_repo = repo)

  # guard: no obsidian plugin on this host — repaint unavailable, which is not a failure
  if cli is None:
    return []

  # run the repaint; a worker that cannot start, or whose output cannot be decoded, is a failed repaint
  try:
    proc = subprocess.run(
        # waiver: the obsidian CLI's subcommand vocabulary, owned by lazycortex-obsidian
        [sys.executable, str(cli), "sync-paths", *paths],
        cwd = repo, capture_output = True, text = True, check = False, encoding = "utf-8",
    )
  except OSError as error:
    raise RepaintFailedError(f"worker did not start: {error}") from error
  except ValueError as error:
    raise RepaintFailedError(f"worker output is not UTF-8: {error}") from error

  # guard: a worker that exits non-zero failed the repaint
  if proc.returncode != 0:
    raise RepaintFailedError(f"worker exited {proc.returncode}: {proc.stderr.strip()[-240:]}")

  # guard: a clean exit with no output is a worker that stayed inert on this vault — unavailable, not failed
  if not proc.stdout.strip():
    return []

  # read back which notes actually changed; output that is not JSON is a failed repaint
  try:
    result = json.loads(proc.stdout.strip().splitlines()[-1])
  except (ValueError, IndexError) as error:
    raise RepaintFailedError(f"unparseable worker output: {proc.stdout.strip()[-240:]!r}") from error

  # guard: valid JSON of the wrong shape is as unparseable as garbage
  if not isinstance(result, dict):
    raise RepaintFailedError(f"worker output is not an object: {proc.stdout.strip()[-240:]!r}")

  # read the list of changed notes the worker reported
  # waiver: the obsidian CLI's JSON result vocabulary, owned by lazycortex-obsidian
  touched = result.get("touched", [])

  # guard: a non-list touched value would iterate as characters or raise
  if not isinstance(touched, list):
    raise RepaintFailedError(f"worker `touched` is not a list: {touched!r}")

  # only string paths count as touched notes
  return [p for p in touched if isinstance(p, str)]
