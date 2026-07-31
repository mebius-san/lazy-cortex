"""
Externally-sourced working directories of a runtime checkout.

A repository whose working directories are partly untracked — bulk data, an inbox,
secrets — declares those repo-relative paths in the tracked `external_dirs.paths`
list, and each checkout names the absolute source they are linked to in its own
gitignored overlay under `external_dirs.root`. This module reports the state of
every declared path and repairs the mechanically repairable ones. Operator content
found in a declared slot is always reported, never touched.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import os
from pathlib import Path

from constants import (
  ExternalDirAction,
  ExternalDirFindingKey,
  ExternalDirsKey,
  ExternalDirStatus,
  SettingsFile,
  SettingsKey,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


def _section(repo: Path) -> dict:
  """
  Return the effective `external_dirs` section of a repository.

  Args:
    repo: Repository root whose settings are read.

  Returns:
    The merged section dict — tracked layer with the local overlay applied.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from lazy_settings import load_section
  return load_section(repo / SettingsFile.REL, SettingsKey.EXTERNAL_DIRS)


def _is_contained(rel: str) -> bool:
  """
  Report whether one declared path stays inside the repository it is declared in.

  Args:
    rel: Declared path with surrounding slashes already stripped.

  Returns:
    True when the path resolves inside the repository; False when it climbs out of it.
  """
  norm = os.path.normpath(rel)
  # guard: an absolute entry names a location of its own, not a slot in the repository
  if os.path.isabs(norm):
    return False
  return norm != os.pardir and not norm.startswith(os.pardir + os.sep)


def declared_paths(repo: Path | str) -> list[str]:
  """
  List the repo-relative paths a repository sources from outside itself.

  Notes:
    - A declared entry that climbs out of the repository is dropped rather than reported.
      The declaration travels with every clone, and repair creates directories and plants
      symlinks, so a path the repository does not contain is never acted on.

  Args:
    repo: Repository root whose declaration is read.

  Returns:
    The declared paths with surrounding slashes stripped, in declaration order;
    empty when the repository declares none.
  """
  raw = _section(Path(repo)).get(ExternalDirsKey.PATHS) or []
  stripped = [str(p).strip("/") for p in raw if str(p).strip("/")]
  return [rel for rel in stripped if _is_contained(rel)]


def is_declared(repo: Path | str, rel: str) -> bool:
  """
  Report whether one repo-relative path is declared as externally sourced.

  Args:
    repo: Repository root whose declaration is read.
    rel: Repo-relative path to look up.

  Returns:
    True when the path appears in the declaration.
  """
  return str(rel).strip("/") in declared_paths(repo)


def source_root(repo: Path | str) -> Path | None:
  """
  Return the absolute source root recorded for this checkout.

  Args:
    repo: Repository root whose overlay is read.

  Returns:
    The expanded absolute path, or None when no source root is on record. A relative value
    is anchored to the repository, never to the working directory of the reading process.
  """
  repo = Path(repo)
  raw = _section(repo).get(ExternalDirsKey.ROOT)
  # guard: no source root on record — this checkout is unconfigured
  if not raw:
    return None
  expanded = Path(os.path.expandvars(str(raw))).expanduser()
  # guard: a relative root would otherwise resolve against the process cwd, so the daemon and an
  # interactive install would disagree on where the same declaration points
  if not expanded.is_absolute():
    return repo / expanded
  return expanded


def is_gitignored(repo: Path | str, rel: str) -> bool:
  """
  Report whether git ignores one repo-relative path in a repository.

  Args:
    repo: Repository root the check runs in.
    rel: Repo-relative path to test against the ignore rules.

  Returns:
    True when git ignores the path, and when the directory is not a git repository at all —
    outside a working tree there is nothing linked content could dirty. False when the path is
    tracked, unmatched, or git is unavailable.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import subprocess
  try:
    # waiver: git plumbing invocation, not a domain constant
    proc = subprocess.run(
      ["git", "check-ignore", "-q", "--", rel],
      cwd = str(repo), capture_output = True, check = False,
    )
  except OSError:
    return False
  # guard: `check-ignore` exits 128 outside a working tree — reporting that as "not ignored" would
  # raise a dirty-tree warning about a tree that does not exist
  # waiver: inline numeric/default literal, not a domain constant
  if proc.returncode == 128:
    return True
  return proc.returncode == 0


def _link_target(link: Path) -> Path:
  """
  Return the absolute path a symlink points at.

  Args:
    link: Path known to be a symlink.

  Returns:
    The link target, resolved against the link's own directory when it is relative.
  """
  raw = Path(os.readlink(link))
  # guard: a relative target resolves against the directory holding the link
  if not raw.is_absolute():
    return link.parent / raw
  return raw


def _status_for(link: Path, source: Path) -> str:
  """
  Diagnose one declared slot against its expected source.

  Args:
    link: Absolute path of the declared slot inside the repository.
    source: Absolute path the slot is expected to point at.

  Returns:
    One token from `ExternalDirStatus`, never `UNCONFIGURED`.
  """
  # guard: a symlink is diagnosed by its target, whatever else is on disk
  if link.is_symlink():
    target = _link_target(link)
    # guard: a broken link is the operational failure regardless of where it aimed
    if not target.exists():
      return ExternalDirStatus.DANGLING
    # guard: a live link aimed somewhere else is repairable by re-pointing
    if target != source:
      return ExternalDirStatus.WRONG_TARGET
    return ExternalDirStatus.OK
  # guard: real content in the declared slot belongs to the operator
  if link.exists():
    return ExternalDirStatus.NOT_A_SYMLINK
  # guard: an empty slot with no source has nothing to link to
  if not source.exists():
    return ExternalDirStatus.SOURCE_MISSING
  return ExternalDirStatus.MISSING


def check(repo: Path | str) -> list[dict]:
  """
  Report the state of every declared external directory of a repository.

  Args:
    repo: Repository root to diagnose.

  Returns:
    One finding dict per declared path, carrying `ExternalDirFindingKey` fields;
    empty when the repository declares no external directories.
  """
  repo = Path(repo)
  root = source_root(repo)
  findings: list[dict] = []
  for rel in declared_paths(repo):
    # guard: without a source root every declared path is unconfigured, not broken
    if root is None:
      findings.append({
        ExternalDirFindingKey.PATH: rel,
        ExternalDirFindingKey.STATUS: ExternalDirStatus.UNCONFIGURED,
        ExternalDirFindingKey.SOURCE: None,
        ExternalDirFindingKey.GITIGNORED: is_gitignored(repo, rel),
      })
      continue
    source = root / rel
    findings.append({
      ExternalDirFindingKey.PATH: rel,
      ExternalDirFindingKey.STATUS: _status_for(repo / rel, source),
      ExternalDirFindingKey.SOURCE: str(source),
      ExternalDirFindingKey.GITIGNORED: is_gitignored(repo, rel),
    })
  return findings


def _record(rel: str, status: str, action: str) -> dict:
  """
  Build one repair record.

  Args:
    rel: Declared repo-relative path the record describes.
    status: Status observed before the repair, followed by the reason when the repair itself
      could not be carried out.
    action: Repair outcome from `ExternalDirAction`.

  Returns:
    A record dict carrying the path, the pre-repair status, and the action taken.
  """
  return {
    ExternalDirFindingKey.PATH: rel,
    ExternalDirFindingKey.STATUS: status,
    ExternalDirFindingKey.ACTION: action,
  }


def apply(repo: Path | str) -> list[dict]:
  """
  Create or re-point the symlinks for every repairable declared external directory.

  Notes:
    - Operator content in a declared slot, an absent source, and a checkout with no
      source root on record are reported as skipped; none of them is ever modified.
    - Only a symlink is ever unlinked, so a real directory cannot be destroyed by a repair.
    - A path whose repair the filesystem refuses is reported as skipped with the reason
      appended to its observed status, and the remaining declared paths are still repaired.

  Args:
    repo: Repository root to repair.

  Returns:
    One repair record per declared path, carrying the pre-repair status and the action taken.
  """
  repo = Path(repo)
  records: list[dict] = []
  for finding in check(repo):
    rel = finding[ExternalDirFindingKey.PATH]
    status = finding[ExternalDirFindingKey.STATUS]
    raw_source = finding[ExternalDirFindingKey.SOURCE]
    # guard: already correct — leave it alone
    if status == ExternalDirStatus.OK:
      records.append(_record(rel, status, ExternalDirAction.UNCHANGED))
      continue
    # guard: operator content and an unconfigured checkout are the operator's call
    if status in (ExternalDirStatus.NOT_A_SYMLINK, ExternalDirStatus.UNCONFIGURED):
      records.append(_record(rel, status, ExternalDirAction.SKIPPED))
      continue
    source = Path(str(raw_source))
    # guard: nothing to point at — repair is impossible, report instead
    if not source.exists():
      records.append(_record(rel, status, ExternalDirAction.SKIPPED))
      continue
    link = repo / rel
    relinked = link.is_symlink()
    try:
      # guard: only a symlink is ever removed — never a real directory
      if relinked:
        link.unlink()
      link.parent.mkdir(parents = True, exist_ok = True)
      os.symlink(str(source), str(link))
    except OSError as e:
      # a refused repair is reported like every other unrepairable state instead of aborting the
      # pass, so the paths after it are still repaired and the operator sees what blocked this one
      # waiver: reporting the type name of an arbitrary value; type(x).__name__ is the right idiom here — no class-system object
      records.append(_record(rel, f"{status}: {type(e).__name__}: {e}", ExternalDirAction.SKIPPED))
      continue
    action = ExternalDirAction.RELINKED if relinked else ExternalDirAction.LINKED
    records.append(_record(rel, status, action))
  return records
