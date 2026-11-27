"""
Recovery primitives for the lazycortex-core runtime daemon halt state.

The lazy-runtime.recover skill walks an operator through cleanup +
resume after a halt. This module is the pure-Python core: read the
halt context, apply the operator-chosen cleanup mode, verify the tree
is clean, then atomically clear the daemon_halted block.

The cleanup modes wrap real git commands. `commit` stages the paths the caller names —
the doctor passes the halt block's own `dirty_paths` with `porcelain = True`, the shape the
block records them in, so a file nobody triaged stays out of the commit — and falls back
to staging every dirty path when the caller names none, which is
the operator's own hatch: they have seen the dirty list and chose the mode for it. The skill
MUST surface the dirty paths to the operator before they pick a mode (so the choice is
informed); this module assumes the choice was already informed.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import error_ledger  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import commit_guard  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import runtime_state  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from runtime_daemon import check_working_tree  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from constants import (  # pylint: disable=import-error
  HaltKey, HaltReason, IncidentActor, IncidentKey, IncidentKind, IncidentPhase,
  IncidentResolution, JobArtifact, JobFile, JobIODir, JobMarker, RecoverMode,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from pathlib import Path


class RecoverError(Exception):
  """
  Recovery failure raised when the daemon halt cannot be cleared.

  Raised when the working tree is still dirty after cleanup, when the
  caller supplies an unknown cleanup mode, or when the commit mode is
  invoked without a non-empty commit message.
  """


VALID_MODES = {
  RecoverMode.COMMIT, RecoverMode.STASH, RecoverMode.DISCARD, RecoverMode.ABORT, RecoverMode.MANUAL_FIX,
}

# Halt reasons where the working tree is presumed already clean and the
# operator's repair happened outside the skill (manual git ops). The skill
# offers `manual-fix` instead of the dirt-cleanup wizard. Source of truth:
# plugins/claude/lazycortex-core/bin/runtime_daemon.py:_halt_daemon callers.
# `rate_limit` rides this path too: there is no dirt to clean, resume simply
# clears the halt early — the pump's own pre-spawn flag check keeps tokens
# safe even when the operator resumes before the window reopens.
MANUAL_FIX_REASONS = {
  "git_pull_diverged",
  "git_push_failed",
  "git_remote_unavailable",
  "git_rebase_not_started",
  "routine_config_invalid",
  "rate_limit",
  "forbidden_commit",
}


def read_halt(repo: Path) -> dict | None:
  """
  Return the active halt context for the given repository.

  Args:
    repo: Absolute path to the repository root.

  Returns:
    The stored `daemon_halted` block describing the halt reason, or None when
    the daemon is not currently halted.
  """
  return runtime_state.get_halted(repo)


# A `git status --porcelain` line opens with the index and worktree status codes and the
# space that separates them from the path, so its path starts at the fourth character.
# Porcelain writes a rename or a copy as `ORIG -> PATH`, under one of these index codes.
_PORCELAIN_PREFIX_WIDTH = 3
_RENAME_ARROW = " -> "
_RENAME_CODES = "RC"
# `runtime_daemon.check_working_tree` writes two kinds of line that name no path at all: the one
# that caps a long dirty list, and the one that stands for a tree it could not read. Both open
# with this prefix and reach here whenever a caller hands the halt block straight over; the
# contract of `check_working_tree` relies on this prefix filtering both.
_TRUNCATION_PREFIX = "..."
# The per-path pathspec magic that makes git take one path as written. A git call that writes or can run
# a hook marks each path with it, because the global `--literal-pathspecs` option reaches the hooks' environment.
_LITERAL_MAGIC = ":(literal)"
# The character that opens a path porcelain spelled quoted; a plain spelling never starts with it.
_QUOTE = '"'
# The exit code of `git ls-files --error-unmatch` for a path git does not track; any other failure is fatal.
_UNMATCHED_EXIT = 1


def _mark_literal(paths: list[str]) -> list[str]:
  """
  Mark each path so git takes it as written and never as a pattern.

  The marking is per path, so hooks that a git call runs inherit no literal-pathspec setting.

  Args:
    paths: Paths relative to the directory git runs in.

  Returns:
    The paths in the order given, each marked as a literal path.
  """
  return [ f"{_LITERAL_MAGIC}{path}" for path in paths ]


def _read_status(repo: Path, *, is_nul_separated: bool) -> str:
  """
  Read the tree's dirty listing as exact paths or as the lines a halt block records.

  Args:
    repo: Absolute path to the repository root.
    is_nul_separated: True for the NUL-separated listing that names every path exactly; False for the line
      listing spelled the way the daemon records it in a halt block.

  Returns:
    The listing as git wrote it, with undecodable bytes kept as surrogate escapes.

  Raises:
    subprocess.CalledProcessError: If the underlying git command exits with a non-zero status.
  """
  # both listings match the one the daemon records in a halt block: an untracked folder is one entry
  if is_nul_separated:
    proc = subprocess.run(
      [ "git", "--no-optional-locks", "-c", "color.status=never", "-c", "core.quotePath=false",
        "status", "--porcelain", "--untracked-files=normal", "-z" ],
      cwd = str(repo), capture_output = True, check = True,
    )
  else:
    proc = subprocess.run(
      [ "git", "--no-optional-locks", "-c", "color.status=never", "-c", "core.quotePath=false",
        "status", "--porcelain", "--untracked-files=normal" ],
      cwd = str(repo), capture_output = True, check = True,
    )

  # the listing is captured as bytes and decoded here, so no byte of a name is rewritten on the way
  return proc.stdout.decode(
    "utf-8",
    # waiver: stdlib decode-error mode, not a domain constant
    errors = "surrogateescape",
  )


def _spell_escaped(spelling: str) -> str:
  """
  Give the spelling a line has for a path when every byte that is not ASCII is written as an escape.

  This is the spelling an older daemon recorded in a halt block.

  Args:
    spelling: The path as a line spells it with such bytes left as they are.

  Returns:
    The path quoted, each byte that is not ASCII written as a backslash and three octal digits; the spelling
    unchanged when it has no such byte.
  """
  # waiver: stdlib codec and decode-error mode names, not domain constants
  raw = spelling.encode("utf-8", "surrogateescape")

  # guard: a path of plain ASCII is spelled the same either way
  if raw.isascii():
    return spelling

  # an already quoted spelling keeps its escapes; the quotes are put back around the result
  body = raw[1:-1] if raw.startswith(b'"') and raw.endswith(b'"') else raw
  # waiver: the top of the ASCII range and the octal escape format, not domain constants
  escaped = "".join(chr(byte) if byte < 128 else f"\\{byte:03o}" for byte in body)
  return f'"{escaped}"'


def _parse_status_entries(listing: str) -> list[list[str]]:
  """
  Split a NUL-separated porcelain listing into the exact paths of each entry.

  Args:
    listing: Output of `git status --porcelain -z`.

  Returns:
    One list per entry, in listing order: the entry's path, followed by its source path when the entry is a
    rename or a copy.
  """
  # each entry is `XY <path>`; a rename or copy entry is followed by its source path as a field of its own
  fields = listing.split("\0")
  entries: list[list[str]] = []
  index = 0
  while index < len(fields):
    entry = fields[index]
    index += 1

    # guard: the listing ends with a NUL, and an entry shorter than its prefix names no path
    if len(entry) <= _PORCELAIN_PREFIX_WIDTH:
      continue
    entries.append([ entry[_PORCELAIN_PREFIX_WIDTH:] ])

    # the source path of a rename or copy carries no status prefix
    if set(entry[:2]) & set(_RENAME_CODES) and index < len(fields):
      entries[-1].append(fields[index])
      index += 1
  return entries


def _read_dirty_spellings(repo: Path) -> dict[str, list[str]]:
  """
  Map each spelling a recorded line may give a dirty entry to the exact paths of that entry.

  The spellings of an entry are the current one and the escaped one that a block of an older daemon recorded.

  Args:
    repo: Absolute path to the repository root.

  Returns:
    Each spelling of a dirty entry's path text, the current one and the escaped one, mapped to the entry's exact
    paths as the NUL-separated listing names them.

  Raises:
    RecoverError: If the tree changed between the two listings, so their entries no longer pair up.
    subprocess.CalledProcessError: If an invoked git command exits with a non-zero status.
  """
  # the NUL-separated listing names each dirty path exactly, never quoted
  entries = _parse_status_entries(_read_status(repo, is_nul_separated = True))

  # the line listing spells the same entries in the same order
  lines = [ line for line in _read_status(repo, is_nul_separated = False).split("\n") if line ]

  # guard: listings of different length were read off a tree that changed in between
  if len(lines) != len(entries):
    raise RecoverError("working tree changed while its dirty paths were read; run the cleanup again")

  # the text after the status prefix is the key, since the status codes may have moved since the halt; a block
  # recorded by an older daemon spells bytes that are not ASCII as escapes, so that spelling is a key as well
  spellings: dict[str, list[str]] = {}
  for line, names in zip(lines, entries, strict = True):
    spelling = line[_PORCELAIN_PREFIX_WIDTH:]
    spellings[spelling] = names
    spellings[_RENAME_ARROW.join(_spell_escaped(side) for side in spelling.split(_RENAME_ARROW))] = names
  return spellings


def _pathspecs_from_dirty(lines: list[str], *, porcelain: bool,
                          spellings: dict[str, list[str]] | None = None) -> list[str]:
  """
  Resolve a path list whose shape the caller declared into the repo-relative paths it names.

  A halt block records its dirty tree as `git status --porcelain` lines, so the doctor hands
  the block over as it stands and says so with `porcelain = True`; an operator naming paths
  by hand passes them bare. The shape comes from the caller and is never sniffed off the
  text: a bare name can open with two status codes and a space by accident (`MD file.md`),
  and truncating such a name to its tail would commit a path nobody asked for.

  Args:
    lines: Porcelain status lines when `porcelain` is true, else bare repo-relative paths.
    porcelain: True when every line carries a `git status --porcelain` status prefix.
    spellings: Exact paths of the tree's dirty entries, keyed by the text a porcelain line gives them; None
      when the tree was not read.

  Returns:
    The repo-relative paths named, in the order given, with lines naming no path dropped. A line the tree still
    lists yields the exact paths git names for that entry, both sides of a rename or copy included; a quoted
    line the tree no longer lists is dropped.
  """

  # bare paths are already the pathspec — no prefix to strip, no escaping to undo
  if not porcelain:
    return [line for line in lines if line]

  # every porcelain line, stripped of its status prefix and resolved to the name on disk
  out: list[str] = []
  for line in lines:
    # guard: the truncation line and the unreadable-tree line are prose about the list, not entries in it;
    # the contract of `check_working_tree` relies on both being passed over here
    if line.startswith(_TRUNCATION_PREFIX):
      continue

    # guard: a line shorter than the prefix plus one character names no path at all
    if len(line) <= _PORCELAIN_PREFIX_WIDTH:
      continue

    # the path follows the status prefix
    path = line[_PORCELAIN_PREFIX_WIDTH:]

    # guard: a line the tree still spells this way names exactly the paths git itself lists for that entry
    if spellings is not None and path in spellings:
      out.extend(spellings[path])
      continue

    # a rename names both sides and both belong in one commit: staging the pair records the
    # new path and the old one's removal together, so no half-applied move is left behind
    parts = path.rsplit(_RENAME_ARROW, 1) if line[0] in _RENAME_CODES else [path]

    # a blank entry is dropped, since it would widen the pathspec to the whole directory; a quoted
    # spelling the tree no longer lists names nothing dirty and is never guessed back into a name
    out.extend(part for part in parts if part and not part.startswith(_QUOTE))
  return out


def _filter_stageable(repo: Path, pathspec: list[str]) -> list[str]:
  """
  Narrow a pathspec to the paths worth staging ahead of a path-limited commit.

  Only a path still present in the worktree is staged. An untracked one has to be, since a
  path-limited commit cannot name content git has never seen; a deleted one must not be,
  because such a commit reads each named path from the index and a staged deletion leaves no
  entry there to read — staging it would drop the removal from the commit instead of
  carrying it. Left alone, the deletion is read off the worktree and lands. A path gone from
  the index as well, the left half of an already-staged rename, matches nothing either way
  and would abort the whole staging call.

  Args:
    repo: Absolute path to the repository root.
    pathspec: Repo-relative paths the commit will carry.

  Returns:
    The subset still present in the worktree.
  """
  return [ path for path in pathspec if (repo / path).exists() ]


def cleanup(repo: Path, mode: str, message: str | None = None, *,
            paths: list[str] | None = None, porcelain: bool = False) -> None:
  """
  Bring the working tree of the given repository into a clean state per the operator's choice.

  Guarantees:
    - With `porcelain` true, each path named by a recorded halt line acts on exactly the file that line named,
      whatever characters its name holds. A quoted line the tree no longer lists is dropped, and if the tree
      changes while it is being read, the call is refused with `RecoverError`.

  Args:
    repo: Absolute path to the repository root.
    mode: One of `commit`, `stash`, `discard`, `abort`, or `manual-fix`. `commit` stages the paths in `paths`
      — or every tracked and untracked change when `paths` is empty or None — and records a commit with
      `message`. `stash` pushes every tracked and untracked change onto the stash with a recovery marker.
      `discard` reverts tracked changes and removes untracked files and directories. `abort` leaves the
      working tree untouched and leaves the halt in place. `manual-fix` leaves the working tree untouched
      because the operator resolved the halt cause externally; a subsequent `resume` call clears the halt
      block.
    message: Commit message to use when `mode` is `commit`. Required and must be non-empty
      in that mode; ignored otherwise.
    paths: Paths the commit is limited to, in the shape `porcelain` declares, taken literally and never as
      patterns. Empty or None stages every change, the operator-hatch shape. Ignored outside `commit` mode.
    porcelain: True when `paths` carries the `git status --porcelain` lines a halt block
      records — the doctor hands the block's `dirty_paths` over as it stands, so its commit
      never publishes dirt it did not classify, and a rename line contributes both of its
      sides so the move lands whole. The recorded lines are resolved against the tree's own listing, so each
      names exactly its file; a quoted line the tree no longer lists is dropped. False, the default, takes
      `paths` as bare repo-relative names, the shape an operator types.

  Raises:
    RecoverError: If `mode` is not recognised, if `mode` is `commit` and `message` is empty,
      if `paths` names entries from which no committable path could be derived, or if the working tree changes
      while its dirty paths are being read.
    subprocess.CalledProcessError: If an invoked git command exits with a non-zero status.
  """

  # Contract:
  # With `porcelain` true, each path named by a recorded halt line acts on exactly the file that line named,
  # whatever characters its name holds. A quoted line the tree no longer lists is dropped and NEVER guessed
  # back into a name. If the tree changes while it is being read, the call is refused with `RecoverError`.

  # guard: reject unrecognised cleanup mode before invoking any git command
  if mode not in VALID_MODES:
    raise RecoverError(f"unknown cleanup mode: {mode!r}")

  # abort + manual-fix are both no-op shapes — nothing to do here
  if mode in { RecoverMode.ABORT, RecoverMode.MANUAL_FIX }:
    return

  # commit mode: preserve the halted work as a real commit
  if mode == RecoverMode.COMMIT:
    # guard: commit mode demands an explicit message — refuse to invent one
    if not message:
      raise RecoverError("commit mode requires a non-empty message")

    # a named path set is the whole footprint; an unnamed one is the operator's capture-all
    named = list(paths or [])

    # porcelain lines may spell a name quoted, so the exact names are read off the tree itself and the
    # lines only select among them
    spellings = _read_dirty_spellings(repo) if porcelain and named else None
    pathspec = _pathspecs_from_dirty(named, porcelain = porcelain, spellings = spellings)

    # guard: the caller named paths but none resolved — refuse rather than widen to capture-all
    if named and not pathspec:
      raise RecoverError(f"no committable path among: {named!r}")

    # the capture-all hatch stages the whole tree; a named set stages only what git can still
    # act on, so a rename's already-staged left side does not abort the call that carries it
    to_stage = _filter_stageable(repo, pathspec) if pathspec else None
    if to_stage is None:
      subprocess.run([ "git", "add", "-A" ],
                     cwd = str(repo), check = True, capture_output = True)
    elif to_stage:
      subprocess.run([ "git", "add", "--", *_mark_literal(to_stage) ],
                     cwd = str(repo), check = True, capture_output = True)

    # the commit carries every named path, staged here or staged before it got here; each is a
    # name read off the tree, so git takes it literally and never as a pattern — marked per path,
    # so the hooks the commit runs inherit no literal-pathspec setting
    commit_cmd = ["git", "commit", "-m", message]
    if pathspec:
      commit_cmd += ["--", *_mark_literal(pathspec)]
    subprocess.run(commit_cmd, cwd = str(repo), check = True, capture_output = True)
    return

  # stash mode: park the halted work where the operator can restore it later
  if mode == RecoverMode.STASH:
    # push everything (including untracked) onto the stash with a recovery marker
    subprocess.run(
      [ "git", "stash", "push", "-u", "-m", "lazycortex-runtime: halt recovery" ],
      cwd = str(repo), check = True, capture_output = True,
    )
    return

  # discard mode: throw the halted work away and return the tree to HEAD
  if mode == RecoverMode.DISCARD:
    # revert tracked file changes, then remove untracked files + directories
    subprocess.run([ "git", "checkout", "--", "." ],
                   cwd = str(repo), check = True, capture_output = True)
    subprocess.run([ "git", "clean", "-fd" ],
                   cwd = str(repo), check = True, capture_output = True)
    return


def resume(repo: Path) -> None:
  """
  Clear the active halt block for the given repository so the daemon can resume work.

  Reason-aware: only `uncommitted_changes` requires a working tree known to be clean (that is the
  halt's root cause and clearing without committing would re-halt immediately). Any
  other halt reason clears unconditionally — if the underlying cause still holds, the
  daemon will re-halt on the next iteration.

  Guarantees:
    - A halt over uncommitted changes is never lifted while the working tree is not known clean: a dirty tree and a
      tree that could not be read both raise `RecoverError` and keep the halt.

  Notes:
    - Resuming a `forbidden_commit` halt also drops the forbidden-commit records that halt listed, releasing their
      publish hold; records it did not list, and any record on resuming another halt, stay.
    - The halt and those records are cleared in one state write.

  Args:
    repo: Absolute path to the repository root.

  Raises:
    RecoverError: If the active halt is `uncommitted_changes` and the working tree
      still has pending changes, or could not be read. For a dirty tree the error message lists the offending
      lines in `git status --porcelain` form; for a tree that could not be read it carries the one line saying so.
  """

  # Domain(runtime.incidents):
  # # Clean-tree gate is reason-specific
  # A halted daemon divides by whether its own cause left the working tree dirty. Only the
  # reason naming uncommitted changes ties clearing the halt to a clean tree, because that is
  # the one halt whose root cause is the dirt itself — clearing it without a clean tree just
  # re-halts on the same condition next tick. Every other halt reason describes trouble that
  # lives outside the working tree — a diverged or rejected push, an unreachable remote, an
  # invalid routine configuration, a closed rate-limit window — so clearing any of those never
  # depends on the tree's state, whatever that state happens to be at the moment.

  # Contract:
  # A halt over uncommitted changes is NEVER lifted while the working tree is not known clean: a dirty tree and a
  # tree that could not be read both raise `RecoverError` and keep the halt.

  halt = runtime_state.get_halted(repo)

  # guard: daemon is not halted — nothing to clear
  if halt is None:
    return
  reason = halt.get(HaltKey.REASON)

  # a dirty-tree halt specifically requires a clean tree before clearing; the tree is read once, and that
  # one reading both decides and names the offending paths, or says that the tree could not be read
  dirt = check_working_tree(repo) if reason == HaltReason.UNCOMMITTED_CHANGES else None

  # guard: a tree that is dirty, or that could not be read, keeps the halt
  if dirt is not None:
    raise RecoverError("working tree still dirty; refusing to resume:\n" + "\n".join(dirt))

  # one write clears the halt and, for a forbidden-commit halt, the records it listed — the operator's verdict on
  # those commits — so nothing can raise the halt again between the two
  runtime_state.update(repo, commit_guard.release)
  error_ledger.resolve(repo, f"halt:{repo.name}", resolution = IncidentResolution.RESUMED,
                       kind = IncidentKind.DAEMON_HALT, actor = IncidentActor.RECOVER)


def cleanup_and_resume(repo: Path, mode: str, message: str | None = None, *,
                       paths: list[str] | None = None, porcelain: bool = False) -> None:
  """
  Apply the chosen cleanup mode and then clear the halt block in a single call.

  Args:
    repo: Absolute path to the repository root.
    mode: Cleanup mode forwarded to `cleanup`.
    message: Commit message forwarded to `cleanup` when `mode` is `commit`.
    paths: Paths forwarded to `cleanup` to limit the commit to; None keeps the operator-hatch
      shape that captures every dirty path.
    porcelain: Shape of `paths`, forwarded to `cleanup`.

  Raises:
    RecoverError: If cleanup or the post-cleanup clean-tree check fails.
    subprocess.CalledProcessError: If an invoked git command exits with a non-zero status.
  """
  cleanup(repo, mode, message, paths = paths, porcelain = porcelain)
  resume(repo)


# ---- doctor primitives (runtime.doctor uses these via Bash) ----

def revert_files(repo: Path, paths: list[str]) -> None:
  """
  Restore the given tracked paths in the repository to their `HEAD` state.

  Untracked files are not affected; the caller is responsible for confirming the
  paths were clean before the failed run began.

  Args:
    repo: Absolute path to the repository root.
    paths: Repository-relative paths to restore, taken literally and never as patterns. An empty list is a
      no-op.

  Raises:
    subprocess.CalledProcessError: If the underlying git command exits with a non-zero status.
  """
  # guard: nothing to revert — skip the subprocess call entirely
  if not paths:
    return
  subprocess.run(
    [ "git", "checkout", "HEAD", "--", *_mark_literal(paths) ],
    cwd = str(repo), check = True, capture_output = True,
  )

  # spec § Emit points #7 — revert resolves the halt; resume after a revert overwrites with
  # `resumed` but either resolution alone yields a closed incident
  error_ledger.resolve(
    repo, f"halt:{repo.name}", resolution = IncidentResolution.REVERTED,
    kind = IncidentKind.DAEMON_HALT, actor = IncidentActor.DOCTOR, detail = f"reverted {len(paths)} path(s)",
  )


def _read_job_scope(repo: Path, jdir: Path) -> list[str]:
  """
  List the repository-relative paths a job is allowed to have created.

  Args:
    repo: Absolute path to the repository root.
    jdir: Absolute path to the job directory.

  Returns:
    Normalized repository-relative roots: the job's `result/` directory, plus the request's `file` target
    when the request names one.
  """

  # Domain(runtime.job-execution):
  # # A job's footprint is its result directory and its named target
  # A job may have created only two things in the repository: its own result directory, and the one target file
  # its request names, when the request names one. Anything else untracked in the tree was not made by this job,
  # whatever else the failed run left dirty. Cleaning up after a dead job deletes untracked paths only inside
  # this footprint, so a file that belongs to the operator or to another job is never removed on the job's account.
  # A request that is unreadable or names no target narrows the footprint to the result directory alone.

  # the job's own result directory is always its footprint
  scope = [ os.path.normpath(os.path.relpath(jdir / JobIODir.RESULT, repo)) ]

  # the request names the target file the job was dispatched to edit, when it names one
  try:
    request = json.loads((jdir / JobFile.REQUEST).read_text(encoding = "utf-8"))
  except (OSError, json.JSONDecodeError):
    request = None
  # waiver: external request-payload field name the doctor already reads as `request_json.file`
  target = request.get("file") if isinstance(request, dict) else None
  if isinstance(target, str) and target:
    scope.append(os.path.normpath(target))
  return scope


def _is_in_scope(path: str, scope: list[str]) -> bool:
  """
  Check whether a path is one of the scope roots or lies beneath one.

  Args:
    path: Repository-relative path to test.
    scope: Normalized repository-relative scope roots.

  Returns:
    True when the path equals a root or sits under a root directory.
  """
  # a path is inside a scope root when it is the root itself or lies beneath it
  norm = os.path.normpath(path)
  return any(norm == root or norm.startswith(root + os.sep) for root in scope)


def _is_untracked(repo: Path, path: str) -> bool | None:
  """
  Tell whether a path is untracked, tracked, or unknown because git could not answer.

  Args:
    repo: Absolute path to the repository root.
    path: Repository-relative path to test.

  Returns:
    True when the path exists in the working tree and git does not track it, False when git tracks it or the path
    is absent, and None when git could not answer.
  """
  # git answers through the exit code: tracked, not tracked, or a failure that answers nothing
  proc = subprocess.run(
    [ "git", "--literal-pathspecs", "ls-files", "--error-unmatch", "--", path ],
    cwd = str(repo), capture_output = True, check = False,
  )

  # guard: git knows the path
  if proc.returncode == 0:
    return False

  # guard: any failure other than "not tracked" leaves the question open
  if proc.returncode != _UNMATCHED_EXIT:
    return None

  # a path present on disk that git has never recorded is untracked
  return (repo / path).exists()


def _find_all_dirty_paths(repo: Path, paths: list[str]) -> list[str]:
  """
  List the named paths that still differ from `HEAD`.

  Args:
    repo: Absolute path to the repository root.
    paths: Repository-relative paths to inspect.

  Returns:
    The subset of the named paths that git reports as modified or untracked, spelled unquoted with
    undecodable bytes kept as surrogate escapes; a renamed or copied path is listed as its new path
    followed by its old one. Empty when all are clean.

  Raises:
    subprocess.CalledProcessError: If the underlying git command exits with a non-zero status.
  """
  # porcelain lists exactly the named paths that still differ from HEAD; the names are taken
  # literally, and the NUL-separated listing spells each one as written, never quoted
  proc = subprocess.run(
    [ "git", "--no-optional-locks", "--literal-pathspecs", "-c", "color.status=never",
      "status", "--porcelain", "-z", "--", *paths ],
    cwd = str(repo), capture_output = True, check = True,
  )

  # each entry is `XY <path>`; a rename or copy entry is followed by its source path as a field of
  # its own, and both sides count as dirty; the listing is captured as bytes and decoded here
  listing = proc.stdout.decode(
    "utf-8",
    # waiver: stdlib decode-error mode, not a domain constant
    errors = "surrogateescape",
  )
  return [ path for entry in _parse_status_entries(listing) for path in entry ]


def revert_and_retry(repo: Path, jdir: Path, paths: list[str], *, remove_untracked: bool = False) -> list[str]:
  """
  Restore a dead job's dirty paths to `HEAD` and re-arm its bundle for retry.

  Untracked paths are deleted only when the caller opts in and only inside the job's own scope: its `result/`
  directory and the target `file` named by its request. The call never commits.

  Guarantees:
    - The bundle is re-armed only when every named path is clean after the restore; otherwise it stays disarmed
      and the still-dirty paths are returned.
    - An untracked path outside the job's own scope is never deleted; a call naming one is refused as a whole
      before any named path is touched.
    - A path is removed as untracked only when git answered that it is untracked; when the lookup fails for any
      other reason, the call is refused with `RecoverError` before anything is touched, and a failed lookup is
      never read as "untracked".

  Args:
    repo: Absolute path to the repository root.
    jdir: Absolute path to the dead job's directory.
    paths: Repository-relative paths the failed run left dirty.
    remove_untracked: Delete the named untracked paths instead of leaving them in place.

  Returns:
    The named paths that are still dirty, in which case the bundle is not re-armed; empty when the bundle
    was re-armed.

  Raises:
    RecoverError: If `remove_untracked` is set and a named untracked path lies outside the job's scope, or if git
      cannot say whether a named path is untracked; nothing is touched in either case.
    subprocess.CalledProcessError: If an invoked git command exits with a non-zero status.
  """

  # Contract:
  # The job's bundle is re-armed only when every named path is clean after the restore; otherwise the bundle
  # stays disarmed and the still-dirty paths are returned.

  # Contract:
  # An untracked path outside the job's own scope is NEVER deleted. A call naming one is refused as a whole
  # before any named path is touched.

  # Contract:
  # A path is removed as untracked only when git answered that it is untracked. When the lookup fails for any
  # other reason, the call is refused with `RecoverError` before anything is touched; a failed lookup is
  # NEVER read as "untracked".

  # with the flag, untracked paths are split off and must all sit inside the job's own scope
  verdicts = { path: _is_untracked(repo, path) for path in paths } if remove_untracked else {}
  unknown = [ path for path, verdict in verdicts.items() if verdict is None ]

  # guard: a path git could not answer for is neither removed nor restored — the whole call is refused
  if unknown:
    raise RecoverError(f"untracked-lookup-failed: {' '.join(unknown)}")
  untracked = [ path for path in paths if verdicts.get(path) ]
  scope = _read_job_scope(repo, jdir)
  outside = [ path for path in untracked if not _is_in_scope(path, scope) ]

  # guard: one untracked path outside the job's scope refuses the whole call before anything is removed
  if outside:
    raise RecoverError(f"outside-job-scope: {' '.join(outside)}")

  # the job's own leftovers go away; every other named path is restored from HEAD
  for path in untracked:
    target = repo / path
    if target.is_dir():
      shutil.rmtree(target)
    else:
      target.unlink()
  revert_files(repo, [ path for path in paths if path not in untracked ])

  # a path that is still dirty means the revert did not take — the job is not re-armed
  if dirty := _find_all_dirty_paths(repo, paths):
    return dirty

  # the tree is back to HEAD on every named path, so the job can run again
  clear_dead_job(jdir)
  return []


def _query_untracked_results(repo: Path) -> list[str]:
  """
  List the untracked, non-ignored files under the repository's top-level `result/` directory.

  Args:
    repo: Absolute path to the repository root.

  Returns:
    Repository-relative posix paths of every such file, at any depth; empty when there are none.

  Raises:
    subprocess.CalledProcessError: If the underlying git command exits with a non-zero status.
  """
  # git names untracked files one by one, never collapsing a directory, and leaves tracked and ignored ones out
  proc = subprocess.run(
    [ "git", "ls-files", "--others", "--exclude-standard", "-z", "--", f"{JobIODir.RESULT}/" ],
    cwd = str(repo), capture_output = True, check = True,
  )

  # the listing is captured as bytes and decoded here, so no byte of a name is rewritten on the way
  listing = proc.stdout.decode(
    "utf-8",
    # waiver: stdlib decode-error mode, not a domain constant
    errors = "surrogateescape",
  )
  return [ path for path in listing.split("\0") if path ]


def _is_identical_copy(copy: Path, original: Path) -> bool:
  """
  Check whether two paths are both regular files with byte-identical content.

  An unreadable file is not a proven copy and yields False instead of raising.

  Args:
    copy: The candidate stray copy.
    original: The file the copy is compared against.

  Returns:
    True when neither path is a symlink, both are regular files, and their bytes match; False otherwise,
    including when either file cannot be read.
  """
  # guard: a link or anything other than a regular file on either side is never a copy
  if copy.is_symlink() or original.is_symlink() or not copy.is_file() or not original.is_file():
    return False

  # the full content decides, never the size or a timestamp; a file that cannot be read is not a proven copy
  try:
    return copy.read_bytes() == original.read_bytes()
  except OSError:
    return False


def _delete_emptied_dirs(repo: Path, removed: list[str]) -> None:
  """
  Remove the directories under the top-level `result/`, and `result/` itself, that the removed files left empty.

  Args:
    repo: Absolute path to the repository root.
    removed: Repository-relative paths of the files just removed.

  Raises:
    OSError: If removing a directory fails.
  """
  # every directory between a removed file and the repository root, `result/` itself included
  dirs: set[Path] = set()
  for path in removed:
    parent = (repo / path).parent
    while parent != repo:
      dirs.add(parent)
      parent = parent.parent

  # deepest first, so a parent is judged after its children went; only a directory holding nothing at all goes
  for directory in sorted(dirs, key = lambda item: len(item.parts), reverse = True):
    if directory.is_dir() and not any(directory.iterdir()):
      directory.rmdir()


def delete_stray_result_copies(repo: Path, jdir: Path) -> list[str]:
  """
  Remove the stray copies of a job's result files that the job left under the repository's top-level `result/`.

  Guarantees:
    - A file is never removed when it is tracked, lies outside the repository's top-level `result/`, is a symlink,
      or differs in bytes from the job's own result file of the same relative path.
    - A directory is removed only when the removals left it empty.

  Notes:
    - Runs git in the repository to list its untracked files.
    - Deletes the matching files, and the directories they left empty, from the working tree.

  Args:
    repo: Absolute path to the repository root.
    jdir: Absolute path to the job directory whose `result/` holds the originals.

  Returns:
    The removed repository-relative file paths, sorted; empty when nothing matched.

  Raises:
    subprocess.CalledProcessError: If the underlying git command exits with a non-zero status.
    OSError: If deleting a copy or removing a directory fails, possibly after some copies were already removed.
  """

  # Contract:
  # A file is NEVER removed when it is tracked, lies outside the repository's top-level `result/`, is a symlink,
  # or differs in bytes from the job's own result file of the same relative path.

  # Contract:
  # A directory is removed only when the removals left it empty; a directory that still holds anything stays.

  # each untracked file under `result/` is a copy only when the job's own result of the same name matches it
  removed = sorted(
    path for path in _query_untracked_results(repo)
    if _is_identical_copy(repo / path, jdir / path)
  )

  # the copies go first, then the directories they alone were keeping alive
  for path in removed:
    (repo / path).unlink()
  _delete_emptied_dirs(repo, removed)
  return removed


def clear_dead_job(jdir: Path) -> None:
  """
  Prepare a failed job directory for retry by removing per-attempt artifacts.

  The bundle is left armed so the next pump tick can re-pick the job.

  Guarantees:
    - The cumulative attempt counter survives the reset untouched, so a job that keeps
      failing is still recognisable as having failed before.

  Args:
    jdir: Absolute path to the job directory to reset.
  """

  # Contract:
  # The job's cumulative attempt counter MUST survive this reset untouched; only the failed
  # attempt's own artifacts are removed.

  # Domain(runtime.job-execution):
  # # Retry resets the attempt, not the history
  # A dead job's retry throws away only what belongs to the failed attempt itself — its dead
  # marker, its process id, its transcript, its recorded error, its response. The cumulative
  # attempt counter belongs to the job as a whole rather than to any one attempt, and survives
  # untouched, so a job that keeps failing is still recognisable as having failed before and a
  # permanent-fail judgment can still act on its true attempt count.

  # iterate the fixed set of retry-resettable artifacts; missing files are expected
  for name in ( JobMarker.DEAD, JobArtifact.DEAD_JSON, JobMarker.PID, JobArtifact.CLAIM_HEAD,
                JobArtifact.TRANSCRIPT, JobArtifact.ERROR_JSON, JobFile.RESPONSE ):
    try:
      (jdir / name).unlink()
    except FileNotFoundError:
      pass

  # Decision: READY is placed rather than merely left alone — retry means the pump can pick the
  # job up, and a bundle whose dispatch died before arming it has no marker to preserve. Without
  # this the caller is told the retry succeeded while the bundle stays invisible to the pump, gets
  # buried again on the next scan, and comes back to the doctor forever. For an armed bundle the
  # touch is a no-op refresh.

  # the bundle leaves this call claimable, which is the whole meaning of a retry
  (jdir / JobMarker.READY).touch()

  # job dirs always live at <repo>/.experts/.jobs/<expert>/<job> — derive the repo root
  # waiver: inline numeric literal (parents-index depth), not a domain constant
  error_ledger.record(jdir.parents[3], {
    IncidentKey.INCIDENT: f"job:{jdir.parent.name}/{jdir.name}", IncidentKey.PHASE: IncidentPhase.TRIAGED,
    IncidentKey.KIND: IncidentKind.JOB_DEAD, IncidentKey.CAUSE: "retry", IncidentKey.ACTOR: IncidentActor.DOCTOR,
    IncidentKey.EXPERT: jdir.parent.name, IncidentKey.JOB_ID: jdir.name,
  })


def permanent_fail(jdir: Path, diagnosis: dict) -> None:
  """
  Mark a job as permanently failed by recording the doctor's diagnosis alongside it.

  The DEAD marker stays in place so pump skips the directory until the operator
  removes it.

  Args:
    jdir: Absolute path to the job directory to mark as permanently failed.
    diagnosis: Doctor-supplied summary of attempts, likely cause, last error excerpt,
      and follow-up actions for the operator.
  """
  (jdir / JobArtifact.DIAGNOSIS_JSON).write_text(json.dumps(diagnosis, indent = 2), encoding = "utf-8")

  # job dirs always live at <repo>/.experts/.jobs/<expert>/<job> — derive the repo root
  # waiver: inline numeric literal (parents-index depth), not a domain constant
  error_ledger.record(jdir.parents[3], {
    IncidentKey.INCIDENT: f"job:{jdir.parent.name}/{jdir.name}", IncidentKey.PHASE: IncidentPhase.TRIAGED,
    IncidentKey.KIND: IncidentKind.JOB_DEAD, IncidentKey.CAUSE: "permanent_fail",
    IncidentKey.ACTOR: IncidentActor.DOCTOR,
    IncidentKey.EXPERT: jdir.parent.name, IncidentKey.JOB_ID: jdir.name,
    IncidentKey.REFS: { "diagnosis_json": str(jdir / JobArtifact.DIAGNOSIS_JSON) },
  })
