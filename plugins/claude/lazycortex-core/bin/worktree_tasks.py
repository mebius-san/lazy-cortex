"""
Lifecycle for job-isolated git worktrees: create-or-reuse, provision, bootstrap, remove, sweep.

An isolated expert job runs on its own branch inside a linked worktree under
`<repo>/<worktree_root>/job-<job_id>/`, so the primary checkout never leaves the base branch and
an agent's dirt or crash cannot touch the operator's tree. The manager creates the worktree off
fresh base (or off the job's existing branch on a continuation), symlinks the gitignored local
config in, runs the operator's bootstrap command, and removes the worktree once the job ends —
the branch always survives; reintegration belongs to the coordinator, never to the runtime.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from lazy_install_phases import ensure_self_ignoring_dir  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


class WorktreeStartError(RuntimeError):
  """
  Raised when a job worktree cannot be created (git failure / directory collision).
  """


class WorktreeTaskManager:
  """
  Owns the linked-worktree lifecycle for isolated expert jobs.

  Each job gets one worktree directory named after its job id, checked out on the job's own
  branch. The manager never merges, never opens pull requests, and never registers state: a
  worktree lives exactly as long as the pump's synchronous run over one job, and anything left
  behind by a crash is an orphan the hourly `sweep` collects. The daemon's main loop is serial
  by contract, so no live worktree exists while `sweep` runs.
  """

  _LOCAL_CONFIG = ( ".claude/settings.local.json", ".claude/lazy.settings.local.json" )
  # The failure a bootstrap returns when git could not list the worktree's untracked paths.
  _LISTING_FAILED = "bootstrap could not list the worktree's untracked paths"
  # The file inside a worktree's private git directory that records the paths its bootstrap created.
  _RECORD = "lazy-bootstrap-paths"
  # The excludes file beside the record that git, run for the job in that worktree, reads as `core.excludesFile`.
  _EXCLUDE = "lazy-bootstrap-exclude"
  # Characters gitignore reads as pattern syntax anywhere in a line, and those it reads so only at the line start.
  _GLOB_CHARS = b"\\*?["
  _LEAD_CHARS = b"!#"

  def __init__(self, repo: Path, base_branch: str, worktree_root: str = ".worktrees") -> None:
    """
    Bind the manager to one repository and its worktree configuration.

    Args:
      repo: Path-like reference to the primary checkout's root.
      base_branch: Branch that fresh job branches fork from.
      worktree_root: Repo-relative directory that holds the per-job worktrees.
    """
    self._repo = Path(repo)
    self._base = base_branch
    self._root = self._repo / worktree_root

  @property
  def repo(self) -> Path:
    """
    Repository root this manager is bound to.
    """
    return self._repo

  def _git(
      self, *args: str, cwd: Path | None = None,
      # waiver: stdlib decode-error mode, not a domain constant
      errors: str = "replace",
  ) -> subprocess.CompletedProcess:
    """
    Run one git subcommand and return its completed process.

    Args:
      *args: git subcommand and arguments (without the leading `git`).
      cwd: Working directory for the invocation; the repository root by default.
      errors: How undecodable output bytes are decoded — replaced by default, kept as surrogate escapes when
        the caller reads paths.

    Returns:
      The completed process, with stdout and stderr captured as text. The caller
      inspects `returncode` — failures are not raised here.
    """
    # the output is taken as bytes and decoded here: text mode would turn a carriage return inside a listed
    # name into a line feed, and a name has to come back exactly as git wrote it
    done = subprocess.run([ "git", *args ], cwd = str(cwd or self._repo), capture_output = True, check = False)
    return subprocess.CompletedProcess(
      done.args, done.returncode,
      done.stdout.decode("utf-8", errors = errors), done.stderr.decode("utf-8", errors = errors),
    )

  def create(self, job_id: str, branch: str) -> tuple[Path, bool]:
    """
    Create and provision a worktree for one job, on a fresh or an existing branch.

    A fresh dispatch names a branch that does not exist yet — it is created off fresh base
    (`origin/<base>` when a remote tracking ref exists, else the local base branch). A
    continuation names the branch a prior dispatch already created and reuses it as-is.

    Guarantees:
      - The worktree root directory gains its own self-ignoring `.gitignore` before any
        worktree is added beneath it.

    Args:
      job_id: Job identifier; names the worktree directory.
      branch: Branch the worktree checks out, created when absent.

    Returns:
      A `(worktree_path, branch_created)` pair; `branch_created` is False on a continuation.

    Raises:
      WorktreeStartError: When the worktree cannot be created.
    """
    wt = self.path_for(job_id)
    # waiver: git CLI vocabulary, not a domain constant
    branch_exists = self._git("rev-parse", "--verify", "--quiet", branch).returncode == 0

    # Contract:
    # The worktree root directory MUST gain its own self-ignoring `.gitignore` before any
    # worktree is added beneath it.

    # the worktree root itself must never reach the primary checkout's tracked tree — each
    # job directory beneath it is its own linked worktree with its own git bookkeeping
    ensure_self_ignoring_dir(self._root)
    if branch_exists:
      # continuation: the branch already carries the job's earlier commits — reuse it
      # waiver: git CLI vocabulary, not a domain constant
      add = self._git("worktree", "add", str(wt), branch)
    else:
      # fresh dispatch: fork off fresh base — prefer origin/<base> when a remote exists
      start_point = f"origin/{self._base}"
      # waiver: git CLI vocabulary, not a domain constant
      if self._git("rev-parse", "--verify", "--quiet", start_point).returncode != 0:
        start_point = self._base
      # waiver: git CLI vocabulary, not a domain constant
      add = self._git("worktree", "add", str(wt), "-b", branch, start_point)

    # guard: worktree add failed (dir collision, branch checked out elsewhere, git error)
    if add.returncode != 0:
      raise WorktreeStartError(f"worktree add {branch}: {add.stderr.strip()[-300:]}")
    self._provision(wt)
    return wt, not branch_exists

  def path_for(self, job_id: str) -> Path:
    """
    Return the worktree directory a given job would occupy.

    Args:
      job_id: Job identifier; names the worktree directory.

    Returns:
      Path to the job's worktree directory, which need not exist.
    """
    return self._root / f"job-{job_id}"

  def _provision(self, wt: Path) -> None:
    """
    Symlink the primary checkout's gitignored local config into a worktree.

    A fresh worktree materialises only tracked files, so the gitignored local
    settings layer is absent and must be linked in so job agents inherit the
    permission and path posture. Only the config layer is linked — the execution
    environment (a venv and the like) is the bootstrap command's business.

    Args:
      wt: Path to the worktree directory to provision.
    """

    # Domain(runtime.job-execution):
    # # Config inheritance for an isolated job worktree
    # A freshly created job worktree materialises only the files git tracks, so the
    # gitignored local configuration layer an ordinary checkout carries is simply absent
    # from it. That layer is linked in explicitly so a job's agents inherit the same
    # permission and path posture as the primary checkout; building the rest of the
    # execution environment a worktree also lacks — installed packages, a virtualenv,
    # anything else gitignored — is left entirely to the isolation's own bootstrap step.

    # waiver: filesystem path idiom, not a domain constant
    ( wt / ".claude" ).mkdir(parents = True, exist_ok = True)
    for rel in self._LOCAL_CONFIG:
      src = self._repo / rel
      dst = wt / rel

      # guard: nothing to link / already linked
      if not src.is_file() or dst.exists() or dst.is_symlink():
        continue
      os.symlink(src.resolve(), dst)

  def _untracked(self, wt: Path) -> set[str] | None:
    """
    Return the untracked and ignored top-level paths git reports for a worktree.

    Paths that an existing ignore rule already excludes are listed alongside the plain untracked ones,
    so a path matching such a rule is still seen.

    Args:
      wt: Path to the worktree directory to inspect.

    Returns:
      One entry per untracked or ignored file or directory, the path as git lists it unquoted,
      undecodable bytes kept as surrogate escapes — an untracked directory reports itself as one
      entry, not the files inside it. None when the listing could not be read.
    """
    status = self._git(
      # waiver: git CLI vocabulary, not a domain constant
      "status", "--porcelain", "-z", "--untracked-files=normal", "--ignored=matching", cwd = wt,
      # waiver: stdlib decode-error mode, not a domain constant
      errors = "surrogateescape",
    )

    # guard: a failed listing answers nothing — it is never read as "no untracked paths"
    if status.returncode != 0:
      return None

    # walk the NUL-separated entries, each `XY<space>path`, keeping the untracked and ignored ones
    found: set[str] = set()
    # waiver: git porcelain record separator, not a domain constant
    entries = iter(status.stdout.split("\0"))
    for entry in entries:
      # a rename or copy entry is followed by its origin path as a separate record — skip it
      # waiver: git porcelain status letters and column width, not domain constants
      if "R" in entry[:2] or "C" in entry[:2]:
        next(entries, None)
      # waiver: git porcelain prefixes and prefix width, not domain constants
      elif entry[:3] in ("?? ", "!! "):
        found.add(entry[3:])
    return found

  def bootstrap(self, wt: Path, cmd: str | None) -> str | None:
    """
    Run the operator's bootstrap command inside a freshly created worktree and keep what it produced out of the
    worktree's untracked paths.

    Rebuilds the gitignored execution environment a worktree does not materialise. Runs on
    every creation — a continuation's worktree was removed after the previous run, so it
    bootstraps anew.

    Guarantees:
      - Whatever new untracked paths the command produces are recorded, exactly as git lists them, in a record
        file inside the worktree's own private git directory, the one git names for that worktree alone. No
        ignore file is ever written: neither a `.gitignore` the repository may track nor an exclude file git
        shares with the main checkout and every other worktree. The record dies with the worktree, and nothing
        is written when the command created nothing untracked.
      - Beside the record, a private excludes file holds the operator's effective global excludes followed by one
        anchored literal line per recorded path, so git run for the job with it as `core.excludesFile` ignores
        exactly those paths and keeps every global rule.
      - The isolated job's dirty check ignores exactly the recorded paths and nothing else, whatever characters
        their names hold, so a sibling a name would match as a pattern still counts as dirt.
      - A produced name containing a newline or a carriage return makes the bootstrap fail with a one-line
        failure naming the path in escaped form; nothing is recorded for that bootstrap, not even the other
        names.
      - When the listing of untracked paths cannot be read, before or after the command, the bootstrap fails
        with a one-line failure and nothing is written; a failed listing is never read as "nothing untracked".

    Notes:
      - No own timeout: bounded by the daemon's per-routine timeout that already bounds the
        pump run this call is part of, the same bound the spawn itself lives under.

    Args:
      wt: Path to the worktree directory to bootstrap.
      cmd: Shell command from `daemon.git.worktree_bootstrap_cmd`, or None to skip.

    Returns:
      None on success or when no command is configured, else a one-line failure description. A failure is
      returned when the command failed, when a produced name holds a newline or a carriage return, when the
      listing of untracked paths could not be read, when the global excludes could not be read, or when the
      record or excludes file could not be resolved or written.
    """

    # Contract:
    # Every new untracked path the bootstrap command produces MUST be recorded, exactly as git lists it, in a
    # record file inside the worktree's own private git directory. No ignore file is EVER written: neither a
    # `.gitignore` the repository may track nor an exclude file git shares with the main checkout and the other
    # worktrees. Nothing is written when the command created nothing untracked.

    # Contract:
    # Beside the record, a private excludes file MUST hold the operator's effective global excludes first, then one
    # anchored, gitignore-escaped line per recorded path, so git run with it as `core.excludesFile` ignores exactly
    # the recorded paths and still applies every global rule.

    # Contract:
    # The isolated job's dirty check ignores exactly the recorded paths and nothing else, whatever characters
    # their names hold, so a sibling that a name would match as a pattern still counts as dirt.

    # Contract:
    # A produced name that contains a newline or a carriage return FAILS the bootstrap: it returns a one-line
    # failure naming the path in escaped form, and NOTHING is recorded for that bootstrap, not even the other
    # names.

    # Contract:
    # When the listing of untracked paths cannot be read, either before or after the command, the bootstrap
    # FAILS with a one-line failure and NOTHING is written. A failed listing is NEVER read as "nothing
    # untracked".

    # Domain(runtime.job-execution):
    # # Bootstrap byproducts declared ignorable
    # Building an isolated job's execution environment is expected to leave new files behind
    # that never existed in the tracked tree — installed packages, caches, generated
    # artifacts. A job that leaves its working copy dirty is judged to have failed, so what the
    # preparation step produced must not count as the job's own dirt. Whatever it creates is
    # therefore recorded in a private list that belongs to this one working copy and disappears
    # with it. No ignore list is touched: the project's own may be tracked, and the version-control
    # tool's exclude list is shared with the main checkout and every other working copy, so a line
    # written there would leak into all of them and outlive the job. The dirty check skips exactly
    # the recorded byproducts and nothing else. So that the job's own agent cannot commit them
    # either, the same working copy also gets a private ignore list — the operator's personal
    # ignore rules followed by one literal line per byproduct — which only the job's agent and the
    # job's own checks are pointed at. A byproduct whose name holds a line break fails the
    # preparation, and nothing is recorded. A listing of byproducts that cannot be read fails the preparation as well; a
    # failed listing is never taken to mean that there are no byproducts.

    # guard: no bootstrap configured — the worktree runs on tracked files alone
    if not cmd:
      return None
    before = self._untracked(wt)

    # guard: without the listing taken before the command, what the command created cannot be told apart
    if before is None:
      return self._LISTING_FAILED
    proc = subprocess.run(
      # waiver: shell invocation idiom shared with the post-push hook, not a domain constant
      [ "sh", "-c", cmd ], cwd = str(wt),
      capture_output = True, text = True, check = False, encoding = "utf-8",
      # waiver: stdlib decode-error mode, not a domain constant
      errors = "replace",
    )

    # guard: bootstrap failed — the caller fails the job rather than spawning into a broken env
    if proc.returncode != 0:
      return f"bootstrap exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()[-300:]}"
    after = self._untracked(wt)

    # guard: without the listing taken after the command, what the command created is unknown
    if after is None:
      return self._LISTING_FAILED
    created = sorted(after - before)

    # guard: the command created nothing untracked — nothing to record
    if not created:
      return None

    # a name holding a line terminator is refused, as it would show up split in a line-based status listing
    # waiver: line terminators, not domain constants
    unlistable = [ path for path in created if "\n" in path or "\r" in path ]

    # guard: a produced name cannot be recorded — the bootstrap fails and nothing is written
    if unlistable:
      # waiver: stdlib codec names and list separator, not domain constants
      escaped = ", ".join(path.encode("unicode_escape").decode("ascii") for path in unlistable)
      return f"bootstrap produced a path no record can hold: {escaped}"

    # the paths go to the worktree's private git directory, never to an ignore file another checkout reads
    return self._write_record(wt, created) or self._write_exclude(wt, created)

  @staticmethod
  def _record_file(wt: Path) -> Path | None:
    """
    Return the bootstrap record file inside a worktree's private git directory.

    Args:
      wt: Path to the worktree directory.

    Returns:
      The record path, which need not exist, or None when git could not name the worktree's git directory.
    """
    done = subprocess.run(
      # waiver: git CLI vocabulary, not a domain constant
      [ "git", "rev-parse", "--git-dir" ], cwd = str(wt), capture_output = True, check = False,
    )

    # guard: git could not name the private git directory
    if done.returncode != 0 or not done.stdout.strip():
      return None

    # git names the directory relative to the worktree unless it lies elsewhere, and a join keeps an absolute answer
    # waiver: line terminator of the git answer, not a domain constant
    return wt / os.fsdecode(done.stdout.rstrip(b"\n")) / WorktreeTaskManager._RECORD

  def _write_record(self, wt: Path, paths: list[str]) -> str | None:
    """
    Write the paths a bootstrap created into the record file of a worktree's private git directory.

    Args:
      wt: Path to the worktree directory.
      paths: Paths relative to the worktree root, as git lists them unquoted.

    Returns:
      None when the record holds the paths, else a one-line failure description when the file cannot be resolved
      or written.
    """
    record = self._record_file(wt)

    # guard: git could not name the private git directory — nothing is written
    if record is None:
      # waiver: one-off human-facing message
      return "bootstrap could not locate the worktree's private git directory"

    # NUL-separated bytes keep every name exactly as git listed it
    try:
      # waiver: NUL record separator, not a domain constant
      record.write_bytes(b"".join(os.fsencode(path) + b"\0" for path in paths))
    except OSError as error:
      return f"bootstrap could not write the worktree's record file: {' '.join(str(error).split())}"
    return None

  def _global_excludes(self, wt: Path) -> bytes | None:
    """
    Return the content of the excludes file git applies in a worktree before any job override.

    Args:
      wt: Path to the worktree directory.

    Returns:
      The file's bytes, empty when no such file exists, or None when the configuration or the file cannot be read.
    """
    # `--path` expands a leading `~` the way git itself does when it reads the key
    # waiver: git CLI vocabulary, not a domain constant
    done = subprocess.run([ "git", "config", "--path", "--get", "core.excludesFile" ],
                          cwd = str(wt), capture_output = True, check = False)

    # a configured file wins; exit 1 with no output means unset, and git falls back to its default location
    if done.returncode == 0 and done.stdout.strip():
      # waiver: line terminator of the git answer, not a domain constant
      source = wt / os.fsdecode(done.stdout.rstrip(b"\n"))
    elif done.returncode == 1:
      # waiver: XDG base-directory variable and git's default excludes location, not domain constants
      xdg = os.environ.get("XDG_CONFIG_HOME")
      # waiver: XDG base-directory default and git's default excludes location, not domain constants
      source = ( Path(xdg) if xdg else Path.home() / ".config" ) / "git" / "ignore"
    else:
      return None

    # git skips an excludes file that does not exist, so its absence contributes no rule
    try:
      return source.read_bytes()
    except FileNotFoundError:
      return b""
    except OSError:
      return None

  @classmethod
  def _ignore_line(cls, path: str) -> bytes:
    """
    Return the anchored gitignore line that matches exactly one path as git lists it.

    Args:
      path: Path relative to the worktree root, a directory carrying its trailing slash.

    Returns:
      The line, terminated by a line feed.
    """
    raw = os.fsencode(path)
    # waiver: gitignore directory marker, not a domain constant
    directory = raw.endswith(b"/")
    body = raw[:-1] if directory else raw

    # every glob character is escaped, a leading negation or comment character too
    escaped = bytearray()
    for index, byte in enumerate(body):
      char = bytes([ byte ])
      if char in cls._GLOB_CHARS or ( index == 0 and char in cls._LEAD_CHARS ):
        # waiver: gitignore escape character, not a domain constant
        escaped += b"\\"
      escaped += char

    # gitignore drops unescaped trailing spaces, so each one is escaped
    # waiver: gitignore escape syntax, not a domain constant
    kept = bytes(escaped).rstrip(b" ")
    # waiver: gitignore escape syntax, not a domain constant
    kept += b"\\ " * ( len(escaped) - len(kept) )

    # the leading slash anchors the line at the worktree root
    # waiver: gitignore anchor, directory marker and line terminator, not domain constants
    return b"/" + kept + ( b"/" if directory else b"" ) + b"\n"

  def _write_exclude(self, wt: Path, paths: list[str]) -> str | None:
    """
    Write the private excludes file of a worktree: the effective global excludes, then one line per path.

    Args:
      wt: Path to the worktree directory.
      paths: Paths relative to the worktree root, as git lists them unquoted.

    Returns:
      None when the file holds the rules, else a one-line failure description.
    """
    record = self._record_file(wt)
    inherited = self._global_excludes(wt)

    # guard: without the private git directory or the global rules the file would hide too much or too little
    if record is None or inherited is None:
      # waiver: one-off human-facing message
      return "bootstrap could not read the excludes git applies in the worktree"

    # the global rules come first and end on a line break, so the first own line starts a line of its own
    # waiver: line terminator, not a domain constant
    if inherited and not inherited.endswith(b"\n"):
      inherited += b"\n"
    try:
      record.with_name(self._EXCLUDE).write_bytes(inherited + b"".join(self._ignore_line(path) for path in paths))
    except OSError as error:
      return f"bootstrap could not write the worktree's excludes file: {' '.join(str(error).split())}"
    return None

  @staticmethod
  def exclude_file(wt: Path) -> Path | None:
    """
    Return the private excludes file the bootstrap of a worktree wrote for git run on the job's behalf.

    Args:
      wt: Path to the worktree directory.

    Returns:
      The excludes file, or None when git cannot name the worktree's git directory or no such file was written.
    """
    record = WorktreeTaskManager._record_file(wt)

    # the file exists only when a bootstrap created something untracked
    exclude = None if record is None else record.with_name(WorktreeTaskManager._EXCLUDE)
    return exclude if exclude is not None and exclude.is_file() else None

  @staticmethod
  def bootstrap_paths(wt: Path) -> set[str]:
    """
    Return the paths the bootstrap of a worktree recorded as its own byproducts.

    Guarantees:
      - Fails closed: a missing git directory, a missing record or an unreadable one answers an empty set, so a
        byproduct is never hidden by a record nobody wrote.

    Args:
      wt: Path to the worktree directory.

    Returns:
      The recorded paths as git lists them unquoted, undecodable bytes kept as surrogate escapes.
    """

    # Contract:
    # `bootstrap_paths` fails closed: a missing git directory, a missing record or an unreadable one answers an
    # empty set, so nothing is ever excused from the dirty check by a record nobody wrote.

    record = WorktreeTaskManager._record_file(wt)

    # guard: no private git directory — nothing is recorded
    if record is None:
      return set()
    try:
      raw = record.read_bytes()
    except OSError:
      return set()

    # the record is NUL-separated; the empty piece after the last separator is dropped
    # waiver: NUL record separator, not a domain constant
    return { os.fsdecode(entry) for entry in raw.split(b"\0") if entry }

  def remove(self, wt: Path) -> None:
    """
    Remove one job worktree, keeping its branch.

    Runs after every job outcome — success and failure alike. The branch survives as the only
    durable product; an agent's uncommitted dirt disappears with the directory. Best-effort:
    a failed removal leaves an orphan the hourly `sweep` collects.

    Guarantees:
      - Never raises, even when the underlying git removal fails; a failed removal is left
        for `sweep` to collect instead of surfacing to the caller.

    Args:
      wt: Path to the worktree directory to remove.
    """

    # Contract:
    # `remove` NEVER raises, even when the underlying git removal fails; a failed removal
    # is left for `sweep` to collect instead of surfacing to the caller.

    # waiver: git CLI vocabulary, not a domain constant
    self._git("worktree", "remove", "--force", str(wt))

  def sweep(self) -> list[str]:
    """
    Prune git's worktree bookkeeping and remove crash-orphaned worktree directories.

    Every directory under the worktree root is an orphan by definition: a live worktree only
    exists inside one synchronous pump run, and the serial main loop never runs `sweep`
    concurrently with it.

    Returns:
      The paths of the orphan worktree directories that were removed.
    """

    # Domain(runtime.job-execution):
    # # Exhaustive orphan sweep
    # Every directory found under the worktree root is treated as an orphan without further
    # inspection: an isolated job's worktree exists only for the length of one synchronous
    # run, and the runtime never starts a second run while a sweep is in progress, so nothing
    # under that root can ever be a worktree still in active use at the moment a sweep walks it.

    # waiver: git CLI vocabulary, not a domain constant
    self._git("worktree", "prune")
    removed: list[str] = []

    # guard: worktree root absent — nothing to sweep
    if not self._root.is_dir():
      return removed
    for child in self._root.iterdir():
      # guard: only directories are worktrees
      if not child.is_dir():
        continue
      # waiver: git CLI vocabulary, not a domain constant
      self._git("worktree", "remove", "--force", str(child))
      removed.append(str(child))
    return removed
