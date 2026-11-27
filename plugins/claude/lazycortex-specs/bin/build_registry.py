from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_locator  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
import spec_job_markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via
# sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import (  # noqa: E402
    AssetTypeKey, BuildOutcomeKind, BuildRegistryKey, Gate, GateCheckbox, JobMarker, ReleaseKey,
)


# The settings section, block and key that name the daemon's integration base branch.
_DAEMON_SECTION = "daemon"
_GIT_BLOCK = "git"
_BASE_BRANCH = "base_branch"

# The ref namespace of local branches.
_HEADS = "refs/heads/"

# The file name suffix of a release note.
_MD = ".md"

# The build number a release token is checked with; any number gives the same verdict on the token.
_SAMPLE_BUILD = 1

# The JSON types a record's start point may take.
_BRANCH_FROM_TYPES = ( str, type(None) )

# The verb's actions.
_ACTION_OPEN = "open"
_ACTION_GET = "get"
_ACTION_CLOSE = "close"
_ACTION_PRUNE = "prune"
_ACTION_BACKFILL = "backfill"

# The flag that lets `get` backfill a release with no registry before it reads.
_FLAG_BACKFILL = "--backfill"

# The `last_job` outcomes of a job that ended without a result to accept.
_FAILED_JOB_OUTCOMES = ( "error", "dead", "cancelled" )

# The outcomes `close` accepts; `open` is only ever written by `open` and `backfill`.
_CLOSE_OUTCOMES = ( BuildOutcomeKind.ACCEPTED, BuildOutcomeKind.REJECTED, BuildOutcomeKind.FAILED )

# The refusal of an action on a release that has no registry yet; the coordinator recognises it and backfills.
NO_REGISTRY_TEMPLATE = "no build registry for {release}; run build-registry backfill"

# The refusal of a release note whose build counter is present but not a non-negative integer.
BAD_IMPL_BUILD_TEMPLATE = "release note {note} carries {key} {value!r}, which is not a non-negative integer"

# The verb's output keys.
_ERROR = "error"
_DELETED_BRANCHES = "deleted"
_FILE_REMOVED = "file_removed"

# The JSON indent of the registry file.
_INDENT = 2

# The verb's exit codes.
_EXIT_OK = 0
_EXIT_REFUSED = 1


# ----------------------------------------------------------------------------------------
class BuildRegistryRefusedError(Exception):
  """
  Refusal of a build-registry action.

  The message is the refusal text the verb reports to its caller.
  """

  def __init__(self, message: str) -> None:
    """
    Create the refusal with its reason.

    Args:
      message: The refusal text.
    """
    # the exception's own message is the refusal text printed under `error`
    super().__init__(message)


# ----------------------------------------------------------------------------------------
class _Git:
  """
  Git queries and branch deletion for one repository.

  Attributes:
    repo: The repository every git call runs in.
  """

  def __init__(self, repo: Path) -> None:
    # the repository every git call runs in
    self.repo: Path = repo

  def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
    # a git that cannot run at all is a refusal, never an answer
    try:
      return subprocess.run(
          # waiver: git CLI vocabulary, not a domain constant
          [ "git", *args ], cwd = str(self.repo), capture_output = True, text = True, check = False,
          encoding = "utf-8",
          # waiver: stdlib decode-error mode, not a domain constant
          errors = "replace",
      )
    except OSError as error:
      raise BuildRegistryRefusedError(f"git cannot run: {error}") from error

  def _failure(self, args: tuple[str, ...], proc: subprocess.CompletedProcess[str]) -> BuildRegistryRefusedError:
    # the last line git printed names the failure; the exit code stands in when it printed nothing
    lines = (proc.stderr.strip() or proc.stdout.strip()).splitlines()
    reason = lines[-1] if lines else f"exit {proc.returncode}"
    return BuildRegistryRefusedError(f"git {' '.join(args)} failed: {reason}")

  def has_branch(self, branch: str) -> bool:
    """
    Tell whether a local branch exists.

    Args:
      branch: The branch name.

    Returns:
      True when the local branch exists, False when it does not.

    Raises:
      BuildRegistryRefusedError: If git cannot run or fails for any reason other than the branch being absent.
    """
    args = ( "rev-parse", "--verify", "--quiet", f"{_HEADS}{branch}" )
    proc = self._run(*args)

    # guard: exit 1 is git's own answer that no such branch exists; anything else but 0 is a failure
    if proc.returncode not in ( 0, 1 ):
      raise self._failure(args, proc)
    return proc.returncode == 0

  def is_ancestor(self, branch: str, base: str) -> bool:
    """
    Tell whether every commit of a local branch is already on another local branch.

    Args:
      branch: The branch whose commits are checked.
      base: The branch that should already hold them.

    Returns:
      True when `branch` is merged into `base`, False when it holds commits `base` lacks.

    Raises:
      BuildRegistryRefusedError: If git cannot run or fails for any reason other than the branch not being merged.
    """
    args = ( "merge-base", "--is-ancestor", f"{_HEADS}{branch}", f"{_HEADS}{base}" )
    proc = self._run(*args)

    # guard: exit 1 is git's own answer "not an ancestor"; anything else but 0 is a failure
    if proc.returncode not in ( 0, 1 ):
      raise self._failure(args, proc)
    return proc.returncode == 0

  def is_valid_branch(self, branch: str) -> bool:
    """
    Tell whether a name can be the name of a local branch.

    Args:
      branch: The candidate branch name.

    Returns:
      True when git accepts the name as a local branch, False when it does not.

    Raises:
      BuildRegistryRefusedError: If git cannot run or fails for any reason other than the name being invalid.
    """
    args = ( "check-ref-format", f"{_HEADS}{branch}" )
    proc = self._run(*args)

    # guard: exit 1 is git's own answer "not a valid ref name"; anything else but 0 is a failure
    if proc.returncode not in ( 0, 1 ):
      raise self._failure(args, proc)
    return proc.returncode == 0

  def delete_branch(self, branch: str) -> None:
    """
    Delete a local branch whether or not it is merged.

    Args:
      branch: The branch name.

    Raises:
      BuildRegistryRefusedError: If git cannot run or refuses to delete the branch.
    """
    args = ( "branch", "-D", branch )
    proc = self._run(*args)

    # guard: a branch git refused to delete is still there, so the record must not say otherwise
    if proc.returncode != 0:
      raise self._failure(args, proc)


# ----------------------------------------------------------------------------------------
class BuildRegistry:
  """
  Build registry of one release.

  Answers which branch each build of the release runs on, where it started from, how it ended and which build
  branches are safe to delete.

  Responsibilities:
    - Record each build of the release in its tracked registry file.
    - Delete the build branches that hold no unique work.

  Attributes:
    repo: The root of the checkout the release lives in, where git and the job markers work; its settings hold the
      base branch.
    settings_root: The directory whose settings name the release's product and its state corner.
    note: The release note whose folder names the release.
    product: The key of the product that owns the release.
    release: The release folder name.
    path: The registry file of the release.
    git: The git wrapper of the repository.
  """

  # limit: calls on one release are assumed serialized by the spec coordinator, which is the only caller and works on
  # one release at a time, so a load-modify-save takes no lock; when a second writer appears, wrap each action's
  # load-modify-save in an exclusive file lock beside the registry file, as the decisions registry does for numbering

  def __init__(self, repo: Path, note: Path, product: str, *, settings_root: Path) -> None:
    # the checkout, the settings root that configures the release, the release note and the product that owns it
    self.repo: Path = repo
    self.settings_root: Path = settings_root
    self.note: Path = note
    self.product: str = product

    # the release folder name, which names the registry file and every build branch
    self.release: str = note.parent.name

    # the registry file of this one release under the tracked state corner
    self.path: Path = spec_paths.state_file(
        settings_root, BuildRegistryKey.FILE_TEMPLATE.format(product = product, release = self.release),
    )

    # git in the repository
    self.git: _Git = _Git(repo)

    # opt: the base branch is read from the settings and checked in git once per object; the settings and the base
    # branch do not change while one verb call runs, and every call builds a fresh registry object
    self._base: str | None = None

  @classmethod
  def for_path(cls, repo: Path, path: str) -> BuildRegistry:
    """
    Create the registry of the release that a path belongs to.

    Notes:
      - The owning product is looked up in the nearest settings above the release note within the checkout.

    Args:
      repo: The root of the checkout the release note lies in.
      path: A release folder or a document inside one, absolute or relative to the current directory.

    Returns:
      The build registry of that release.

    Raises:
      BuildRegistryRefusedError: If the folder has no release note of its own, the note lies outside the repository,
        the note cannot be read or is not a release note, the note's folder is not inside a `releases` folder or its
        `archive` subfolder, no product owns it, or the release folder name cannot be part of a branch name.
    """
    target = (Path.cwd() / path).resolve()

    # a document names its release by the folder it sits in; a folder names itself
    folder = target if target.is_dir() else target.parent
    note = folder / f"{folder.name}{_MD}"

    # guard: a folder without its own note is no release folder
    if not note.is_file():
      raise BuildRegistryRefusedError(f"no release note at {note}")

    # guard: a note outside the repository has no product and no registry here
    try:
      rel = note.relative_to(repo).as_posix()
    except ValueError as error:
      raise BuildRegistryRefusedError(f"{note} lies outside the repository {repo}") from error

    # guard: only a release note carries builds
    if read_note(note).get(AssetTypeKey.TYPE) != ReleaseKey.ASSET_TYPE:
      raise BuildRegistryRefusedError(f"{rel} is not a release note")

    # guard: a release lives in the product's releases folder, or in its archive once closed
    container = folder.parent
    if not (container.name == ReleaseKey.FOLDER
            or (container.name == ReleaseKey.ARCHIVE and container.parent.name == ReleaseKey.FOLDER)):
      raise BuildRegistryRefusedError(f"{rel} does not lie in a {ReleaseKey.FOLDER} folder")

    # the product that owns the note, looked up in the settings nearest to the note's own folder
    settings_root = spec_locator.query_settings_root(folder)
    key, _record = resolve_product.resolve_product_by_path(settings_root, note.relative_to(settings_root).as_posix())

    # guard: the branch name needs the product key, so a release no product owns in the note's own settings is refused
    if key is None:
      raise BuildRegistryRefusedError(f"no product owns {rel}")

    # guard: a release folder name that cannot be part of a ref would yield branches git refuses
    registry = cls(repo, note, key, settings_root = settings_root)
    if not registry.git.is_valid_branch(registry.branch_name(_SAMPLE_BUILD)):
      raise BuildRegistryRefusedError(f"release folder name {folder.name!r} cannot be part of a branch name")
    return registry

  def branch_name(self, build: int) -> str:
    """
    Return the branch name of a build of this release.

    Args:
      build: The build number.

    Returns:
      The name of the branch the build runs on.
    """
    # the branch name rule, the release's own token plus the build number
    return BuildRegistryKey.BRANCH_TEMPLATE.format(product = self.product, release = self.release, build = build)

  def read_base(self) -> str:
    """
    Return the integration base branch that builds are merged into.

    Notes:
      - Reads the merged settings view of the checkout's toplevel, which holds the daemon section.

    Returns:
      The name of the configured base branch.

    Raises:
      BuildRegistryRefusedError: If the settings cannot be read, name no base branch, or name a branch git does not
        have.
    """
    # a base branch already read this run is answered from memory
    if self._base is not None:
      return self._base

    # the daemon's base branch from the merged settings view of the checkout's toplevel, where the daemon section lives
    try:
      daemon = spec_paths.read_merged_sections(self.repo, _DAEMON_SECTION)[_DAEMON_SECTION]
    except ValueError as error:
      raise BuildRegistryRefusedError(str(error)) from error
    git_block = daemon.get(_GIT_BLOCK)
    base = git_block.get(_BASE_BRANCH) if isinstance(git_block, dict) else None

    # guard: without a base branch no build can be told merged or unmerged
    if not isinstance(base, str) or not base:
      raise BuildRegistryRefusedError(f"{_DAEMON_SECTION}.{_GIT_BLOCK}.{_BASE_BRANCH} is not configured")

    # guard: a base branch git does not have answers no ancestry question
    if not self.git.has_branch(base):
      raise BuildRegistryRefusedError(f"base branch {base} does not exist")
    self._base = base
    return base

  def _merged(self, branch: str) -> bool | None:
    # a branch git does not have is neither merged nor unmerged; None says so
    if not self.git.has_branch(branch):
      return None
    return self.git.is_ancestor(branch, self.read_base())

  def _load(self) -> list[dict] | None:
    # guard: no file means no registry, which only `open` and `backfill` may create
    if not self.path.is_file():
      return None

    # guard: a file that is not the registry's JSON is refused by name, never overwritten
    try:
      data = json.loads(spec_paths.read_text(self.path))
    except (OSError, ValueError) as error:
      raise BuildRegistryRefusedError(f"build registry {self.path} cannot be read: {error}") from error
    builds = data.get(BuildRegistryKey.BUILDS) if isinstance(data, dict) else None
    if not isinstance(builds, list) or not all(isinstance(record, dict) and _is_record(record) for record in builds):
      raise BuildRegistryRefusedError(f"build registry {self.path} is malformed: expected an object whose "
                                      f"{BuildRegistryKey.BUILDS} list holds only well-formed build records")
    return builds

  def _require(self) -> list[dict]:
    builds = self._load()

    # guard: a release without a registry has to be backfilled before anything reads or changes it
    if builds is None:
      raise BuildRegistryRefusedError(NO_REGISTRY_TEMPLATE.format(release = self.release))
    return builds

  def _save(self, builds: list[dict]) -> None:
    # the whole file is rewritten, keys in a fixed order, so equal registries give equal bytes
    data = { BuildRegistryKey.PRODUCT: self.product, BuildRegistryKey.RELEASE: self.release,
             BuildRegistryKey.BUILDS: builds }
    try:
      self.path.parent.mkdir(parents = True, exist_ok = True)
      spec_paths.write_text_atomic(self.path, json.dumps(data, indent = _INDENT, ensure_ascii = False) + "\n")
    except OSError as error:
      raise BuildRegistryRefusedError(f"build registry {self.path} cannot be written: {error}") from error

  def _record(self, build: int, branch_from: str | None, outcome: str, *, deleted: bool = False) -> dict:
    # one build's record, keys in the order the file carries them
    return { BuildRegistryKey.BUILD: build, BuildRegistryKey.BRANCH: self.branch_name(build),
             BuildRegistryKey.BRANCH_FROM: branch_from, BuildRegistryKey.OUTCOME: outcome,
             BuildRegistryKey.DELETED: deleted, BuildRegistryKey.MERGED: False }

  @staticmethod
  def _find(builds: list[dict], build: int) -> dict | None:
    # the record of one build number, when the registry holds it
    return next((record for record in builds if record.get(BuildRegistryKey.BUILD) == build), None)

  def _start_point(self, builds: list[dict]) -> str | None:

    # Domain(spec.lifecycle):
    # # A new build starts from the previous build's branch while that branch is unmerged
    # A build starts on top of the latest earlier build that did not fail, whatever else its outcome,
    # when that build's work is still only on its own branch: the branch has not reached the base
    # branch yet. A build that failed does not count as the one before; its branch is abandoned and
    # the build before it is looked at instead. An unfinished earlier build is not meant to be there
    # at the moment a new build opens, but the registry does not enforce it; the spec coordinator's
    # rules do. It dispatches nothing while the asset has a job in flight, and it closes the earlier
    # build, the build of a failed continuation included through the rejection of its report, before
    # the next build opens. Were those rules skipped, an unfinished earlier build would be treated
    # like any other build that did not fail, and the new build would start from its unmerged
    # branch. In every other case — no earlier build, the earlier branch
    # already merged, or the branch gone from git — the new build starts from the base branch.

    # the latest build that did not fail is the only candidate start point
    previous = next((record for record in reversed(builds)
                     if record.get(BuildRegistryKey.OUTCOME) != BuildOutcomeKind.FAILED), None)

    # guard: with no such build the new one starts from the base branch
    if previous is None:
      return None

    # the candidate's branch is the start point only while it holds work the base branch lacks
    branch = previous.get(BuildRegistryKey.BRANCH)
    return branch if isinstance(branch, str) and self._merged(branch) is False else None

  def open(self, build: int) -> dict:
    """
    Record the start of a build and return its record.

    Guarantees:
      - Opening a build the registry already holds never changes its record: the call returns that record
        unchanged, or refuses when the release note cannot be read or is malformed, so a repeated call for the
        same build never moves its start point.

    Notes:
      - Creates the registry file when the release has none, and rewrites it when a new record is added.
      - A release with no registry file gets one only for its first build; a later build is refused while the release
        note already records an implementation build (`spec_impl_build` of 1 or more), because only a backfill
        recovers the earlier builds' start points. An absent `spec_impl_build` reads as 0.
      - Reads the release note's `spec_impl_build` on every call, for any build number and whether or not the
        registry exists, and refuses a value that is present but not a non-negative integer.

    Args:
      build: The build number, which must be above every build already recorded.

    Returns:
      The build's record.

    Raises:
      BuildRegistryRefusedError: If the release note cannot be read, or carries a `spec_impl_build` that is present
        but not a non-negative integer (for any build number, with or without a registry), the release has no
        registry while the build is above 1 and the release note already records an implementation build (the
        registry must be backfilled first), the build number is below 1 or does not follow the last recorded
        build, the registry cannot be read, is malformed or cannot be written, or git cannot be read.
    """

    # Contract:
    # Opening a build the registry already holds never changes its record: the call returns that
    # record unchanged, or refuses when the release note cannot be read or is malformed, so a
    # repeated call for the same build never moves its start point.

    # the release's last implementation build is read on every call, so a malformed value is always refused
    impl_build = self._impl_build()
    loaded = self._load()

    # guard: a release that built before its registry existed must be backfilled, or its start point is lost
    if loaded is None and build > 1 and impl_build >= 1:
      raise BuildRegistryRefusedError(NO_REGISTRY_TEMPLATE.format(release = self.release))
    builds = loaded or []
    existing = self._find(builds, build)

    # guard: a build already recorded keeps its record, start point included
    if existing is not None:
      return existing

    # guard: build numbers only grow, so a number at or below the last one is a mistake
    last = max((record.get(BuildRegistryKey.BUILD, 0) for record in builds), default = 0)
    if build < 1 or build <= last:
      raise BuildRegistryRefusedError(f"build {build} does not follow the last recorded build {last}")

    # the new record, started from the rule's start point, appended and written
    record = self._record(build, self._start_point(builds), BuildOutcomeKind.OPEN)
    self._save([ *builds, record ])
    return record

  def _impl_build(self) -> int:
    # the release note's last implementation build, the only kind that has a branch; zero when the key is absent
    raw = read_note(self.note).get(ReleaseKey.IMPL_BUILD)
    if raw is None:
      return 0

    # guard: a value that is not a non-negative integer would silently hide earlier builds
    count = isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0
    if not (count or isinstance(raw, str) and raw.isascii() and raw.isdecimal()):
      raise BuildRegistryRefusedError(
          BAD_IMPL_BUILD_TEMPLATE.format(note = self.note, key = ReleaseKey.IMPL_BUILD, value = raw),
      )
    return int(raw)

  def read_current(self, *, backfill: bool = False) -> dict:
    """
    Return the record of the release's current build.

    Guarantees:
      - With `backfill`, only a release that has no registry file is backfilled, with the same records `backfill`
        writes, before the read.
      - An existing registry, malformed or not, is never rewritten.
      - Every refusal other than a missing registry stays a refusal: a malformed or unreadable registry, an empty
        registry, and a refused backfill.

    Args:
      backfill: When True, a release with no registry gets one created first, as `backfill` creates it.

    Returns:
      The record of the latest recorded build.

    Raises:
      BuildRegistryRefusedError: If the release has no registry and `backfill` is False, the registry cannot be read
        or is malformed, it holds no builds, or the backfill asked for is refused.
    """

    # Contract:
    # With `backfill`, only a release that has no registry file is backfilled, with the same records `backfill`
    # writes, before the read. An existing registry, malformed or not, is never rewritten, and every refusal other
    # than a missing registry stays a refusal: a malformed or unreadable registry, an empty registry, and a refused
    # backfill.

    # a release without a registry gets one first when the caller asks for it; an existing one is never rewritten
    if backfill and self._load() is None:
      self.backfill()
    builds = self._require()

    # guard: an empty registry has no current build
    if not builds:
      raise BuildRegistryRefusedError(f"build registry for {self.release} holds no builds")
    return builds[-1]

  def close(self, build: int, outcome: str) -> dict:
    """
    Record the outcome of a build and return its record.

    Notes:
      - Rewrites the registry file.

    Args:
      build: The number of a recorded build.
      outcome: The outcome to record for it.

    Returns:
      The build's record with the new outcome.

    Raises:
      BuildRegistryRefusedError: If the release has no registry, the registry cannot be read or is malformed, it
        holds no such build, or it cannot be written.
    """
    builds = self._require()
    record = self._require_record(builds, build)

    # the outcome is written onto the record and the whole file rewritten
    record[BuildRegistryKey.OUTCOME] = outcome
    self._save(builds)
    return record

  def read_record(self, build: int) -> dict:
    """
    Return the record of one recorded build.

    Notes:
      - Never writes the registry file.

    Args:
      build: The number of a recorded build.

    Returns:
      The build's record as the registry holds it.

    Raises:
      BuildRegistryRefusedError: If the release has no registry, the registry cannot be read or is malformed, or it
        holds no such build.
    """
    # the same lookup and the same refusals as the outcome write, with nothing written
    return self._require_record(self._require(), build)

  def _require_record(self, builds: list[dict], build: int) -> dict:
    record = self._find(builds, build)

    # guard: only a recorded build can be read or ended
    if record is None:
      raise BuildRegistryRefusedError(f"build registry for {self.release} holds no build {build}")
    return record

  @staticmethod
  def _later(builds: list[dict], index: int) -> list[int]:
    # the positions of every build numbered after this one, wherever the file lists them
    number = builds[index][BuildRegistryKey.BUILD]
    return [ later for later, record in enumerate(builds) if record[BuildRegistryKey.BUILD] > number ]

  def _successor(self, builds: list[dict], index: int) -> int | None:
    # the lowest-numbered later build that did not fail is the one that replaced this build
    candidates = [ later for later in self._later(builds, index)
                   if builds[later][BuildRegistryKey.OUTCOME] != BuildOutcomeKind.FAILED ]
    return min(candidates, key = lambda later: builds[later][BuildRegistryKey.BUILD], default = None)

  @staticmethod
  def _proven_merged(builds: list[dict], merged: list[bool | None], index: int) -> bool:
    # a live branch proves a merge by being an ancestor of the base; a deleted one only by its merged marker
    record = builds[index]
    return merged[index] is True or (record[BuildRegistryKey.DELETED] and record[BuildRegistryKey.MERGED])

  def _prunable(self, builds: list[dict], merged: list[bool | None], index: int) -> bool:

    # Domain(spec.lifecycle):
    # # A build branch is deleted only when it is not the one copy of its code
    # A build's branch may go in three cases: it has been merged into the base branch; the build
    # was rejected and the build that replaced it is proven merged; or the build failed and a
    # later build has already been started. A replacement is proven merged when its branch
    # reaches the base branch, or when its branch was deleted for exactly that reason; a
    # replacement whose branch simply vanished from git proves nothing. A branch gone from git
    # is recorded as deleted unless its build is still open, since an open build's branch may
    # simply not exist yet, and such a record is never counted as merged. In every other case
    # the branch stays, because it holds the only copy of that build's code.

    record = builds[index]
    outcome = record.get(BuildRegistryKey.OUTCOME)

    # a merged branch, or a missing one of a build that is no longer open, has nothing left to protect
    if merged[index] is True or (merged[index] is None and outcome != BuildOutcomeKind.OPEN):
      return True

    # a failed build is abandoned as soon as any later build exists
    if outcome == BuildOutcomeKind.FAILED:
      return bool(self._later(builds, index))

    # any other outcome that is not rejected keeps its branch, since only a rejected build is replaced by a successor
    if outcome != BuildOutcomeKind.REJECTED:
      return False

    # a rejected build with no replacement yet holds the only copy of its code, so it stays
    successor = self._successor(builds, index)
    if successor is None:
      return False

    # a rejected build goes once its replacement is proven merged; a replacement merely gone from git proves nothing
    return self._proven_merged(builds, merged, successor)

  def prune(self) -> dict:
    """
    Delete the build branches that hold no code of their own and mark each deletion, and its reason, in the registry.

    Guarantees:
      - Never deletes the branch of an open or accepted build that is not merged into the base branch, nor of a
        rejected build whose replacement is unmerged: such a branch holds the only copy of that build's code.

    Notes:
      - A rejected build's branch is deleted only once its replacement is proven merged: the replacement's branch is
        live and merged into the base branch, or was already deleted with the merged mark.
      - Deletes local git branches and rewrites the registry file, which keeps the deletions made so far when git
        fails partway.
      - Removes the registry file once the release is released or cancelled and every build branch is deleted.

    Returns:
      A mapping of `deleted`, the names of the branches deleted by this call, and `file_removed`, whether the
      registry file was removed.

    Raises:
      BuildRegistryRefusedError: If the release has no registry, the registry cannot be read, is malformed or cannot
        be written or removed, the release note cannot be read, the base branch is not usable, or git fails.
    """

    # Contract:
    # Prune never deletes the branch of an open or accepted build that is not merged into the base
    # branch, nor of a rejected build whose replacement is unmerged: such a branch holds the only
    # copy of that build's code.

    builds = self._require()

    # every live branch's merge state is read before anything is deleted, so one pass sees one picture
    merged = [ None if record.get(BuildRegistryKey.DELETED) else self._merged(record[BuildRegistryKey.BRANCH])
               for record in builds ]

    # every decision is taken on that picture before any record changes, so neither the file's order nor the
    # order of deletions within the pass can sway one
    eligible = [ not record[BuildRegistryKey.DELETED] and self._prunable(builds, merged, index)
                 for index, record in enumerate(builds) ]

    # each eligible branch is deleted and its record marked; a git failure keeps what was done so far
    deleted: list[str] = []
    try:
      for index, record in enumerate(builds):
        # guard: a record that is not eligible keeps its branch and its marks
        if not eligible[index]:
          continue
        if merged[index] is not None:
          self.git.delete_branch(record[BuildRegistryKey.BRANCH])
          deleted.append(record[BuildRegistryKey.BRANCH])
        record[BuildRegistryKey.DELETED] = True
        record[BuildRegistryKey.MERGED] = merged[index] is True
    finally:
      self._save(builds)

    # a closed release whose branches are all gone needs no registry any more
    values = read_note(self.note)
    closed = flip_gate.is_true(values, Gate.RELEASED) or flip_gate.is_true(values, Gate.SPEC_CANCELLED)
    removed = closed and all(record.get(BuildRegistryKey.DELETED) for record in builds)
    if removed:
      try:
        os.remove(self.path)
      except OSError as error:
        raise BuildRegistryRefusedError(f"build registry {self.path} cannot be removed: {error}") from error
    return { _DELETED_BRANCHES: deleted, _FILE_REMOVED: removed }

  def backfill(self) -> list[dict]:
    """
    Create the registry of a release that was built before registries existed.

    Notes:
      - Writes the registry file only when the release has none.
      - Each past build gets its outcome derived: a build whose branch is merged into the base branch is accepted,
        and a build whose branch has vanished from git counts as accepted.
      - Only the last build can be open, while its branch holds unmerged work; an earlier build whose branch holds
        unmerged work is rejected.
      - The last build is failed when the release's last retired job is the `Build` job that the release note's
        `spec_build_job` names and that job ended `error`, `dead` or `cancelled`, or its result never landed.
      - Reads the specs job markers of the release note.

    Returns:
      The release's build records, oldest first; an existing registry is returned as it is.

    Raises:
      BuildRegistryRefusedError: If an existing registry cannot be read or is malformed, the release note cannot be
        read or carries a `spec_impl_build` that is present but not a non-negative integer, the job markers of the
        release note cannot be read, the registry cannot be written, the base branch is not usable, or git fails.
    """
    existing = self._load()

    # guard: a registry already in place is the record of truth and is left as it is
    if existing is not None:
      return existing

    # Domain(spec.lifecycle):
    # # A release built before the registry existed gets one record per past build
    # Every build from the first to the release's last implementation build gets a record with
    # its branch by the naming rule. A build whose branch has been merged into the base branch
    # counts as accepted. The release remembers only its last build, so only the last one can
    # still be open: it failed when the release's last build job is that build's own job and
    # ended without a result to accept, and is open otherwise while its branch holds unmerged
    # work. An earlier build whose branch still holds unmerged work was replaced without being
    # accepted, so it counts as rejected. A build whose branch is gone from git counts as
    # accepted, unless it is the last build and failed. No start point is known for these
    # builds, so none is recorded.

    # the release's last implementation build, zero when it never built, and whether its own job failed
    last = self._impl_build()
    last_failed = last >= 1 and self._last_build_job_failed()

    # one record per past build, its outcome read from the branch's state in git and the release's last job
    builds = []
    for build in range(1, last + 1):
      merged = self._merged(self.branch_name(build))
      builds.append(self._record(
          build, None, self._past_outcome(merged, is_last = build == last, last_failed = last_failed),
          deleted = merged is None,
      ))
    self._save(builds)
    return builds

  @staticmethod
  def _past_outcome(merged: bool | None, *, is_last: bool, last_failed: bool) -> str:
    # a merged branch is an accepted build, whatever else is known
    if merged is True:
      return BuildOutcomeKind.ACCEPTED

    # the last build failed when its own job did
    if is_last and last_failed:
      return BuildOutcomeKind.FAILED

    # a vanished branch is taken as accepted; an unmerged one is open when last and was replaced otherwise
    if merged is None:
      return BuildOutcomeKind.ACCEPTED
    return BuildOutcomeKind.OPEN if is_last else BuildOutcomeKind.REJECTED

  def _last_build_job_failed(self) -> bool:
    # the release's last retired job, as the specs job markers keep it for the release note
    try:
      last_job = spec_job_markers.read(self.repo, self.note)[JobMarker.LAST_JOB]
    except OSError as error:
      raise BuildRegistryRefusedError(f"the job markers of {self.note} cannot be read: {error}") from error

    # guard: only the release's last `Build` job, the one its note names, speaks for the last build
    build_job = read_note(self.note).get(ReleaseKey.BUILD_JOB)
    if (not isinstance(last_job, dict) or last_job.get(JobMarker.CHECKBOX) != GateCheckbox.BUILD
        or not build_job or last_job.get(JobMarker.JOB_ID) != build_job):
      return False

    # that job failed when it ended without a result to accept, or its result never landed
    return (last_job.get(JobMarker.OUTCOME) in _FAILED_JOB_OUTCOMES
            or spec_job_markers.is_unlanded_record(last_job))


def read_note(note: Path) -> dict:
  """
  Read the frontmatter values of a release note.

  Args:
    note: The release note file.

  Returns:
    The note's flat frontmatter values.

  Raises:
    BuildRegistryRefusedError: If the note cannot be read or is not valid UTF-8 text.
  """
  # a note that cannot be read is a refusal naming it, never a traceback
  try:
    text = spec_paths.read_text(note)
  except (OSError, ValueError) as error:
    raise BuildRegistryRefusedError(f"release note {note} cannot be read: {error}") from error

  # the note's flat frontmatter values
  values, _end = flip_gate.parse_frontmatter(text)
  return values


def _is_record(record: dict) -> bool:
  # every field carries its own type; a bool is not a build number even though Python counts it as an int
  build = record.get(BuildRegistryKey.BUILD)
  return (isinstance(build, int) and not isinstance(build, bool)
          and isinstance(record.get(BuildRegistryKey.BRANCH), str)
          and isinstance(record.get(BuildRegistryKey.BRANCH_FROM, False), _BRANCH_FROM_TYPES)
          and record.get(BuildRegistryKey.OUTCOME) in tuple(BuildOutcomeKind)
          and isinstance(record.get(BuildRegistryKey.DELETED), bool)
          and isinstance(record.get(BuildRegistryKey.MERGED), bool))


def _run(args: argparse.Namespace, repo: Path) -> dict:
  registry = BuildRegistry.for_path(repo, args.path)

  # one action per call, each answering with the record or summary the verb prints
  if args.action == _ACTION_OPEN:
    record = registry.open(args.build)
    return { BuildRegistryKey.BUILD: record[BuildRegistryKey.BUILD],
             BuildRegistryKey.BRANCH: record[BuildRegistryKey.BRANCH],
             BuildRegistryKey.BRANCH_FROM: record[BuildRegistryKey.BRANCH_FROM] }
  if args.action == _ACTION_GET:
    return registry.read_current(backfill = args.backfill)
  if args.action == _ACTION_CLOSE:
    return registry.close(args.build, args.outcome)
  if args.action == _ACTION_PRUNE:
    return registry.prune()
  return { BuildRegistryKey.BUILDS: registry.backfill() }


def main(argv: list[str]) -> int:
  """
  Run the `build-registry` verb: act on a release's build registry and print one JSON line.

  Notes:
    - `open <path> --build N` prints `build`, `branch` and `branch_from`; it refuses a build above 1 when the release
      has no registry yet but its note already records an implementation build, so `backfill` runs first.
    - `open` and `backfill` refuse a release note whose `spec_impl_build` is present but not a non-negative integer.
    - `get <path> [--backfill]` prints the current build's record; with `--backfill`, a release with no registry gets
      one through the same backfill `backfill` runs before the read, and every other refusal stays a refusal.
    - `--backfill` goes with `get` only; any other action given it is an argument error.
    - `close <path> --build N --outcome accepted|rejected|failed` prints the closed build's record.
    - `prune <path>` prints `deleted` and `file_removed`.
    - `backfill <path>` prints `builds`.
    - A refusal prints `error` with the reason; the repository is the root of the checkout `$LAZY_REPO_ROOT`, else
      the current directory, sits in, and the release's product, state corner and base branch come from the nearest
      settings above the release note within that checkout.
    - Never commits.

  Args:
    argv: The command-line arguments after the verb name.

  Returns:
    Exit code 0 on success, 1 when the action was refused.

  Raises:
    SystemExit: With code 2, when an argument is unknown or malformed, or `--backfill` is given with an action
      other than `get`.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs build-registry")
  # waiver: argparse CLI signature -- positional argument names and choices
  parser.add_argument("action", choices = [ _ACTION_OPEN, _ACTION_GET, _ACTION_CLOSE, _ACTION_PRUNE,
                                            _ACTION_BACKFILL ])
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("path")
  # waiver: argparse CLI signature -- option flag + type
  parser.add_argument("--build", type = int, default = None)
  # waiver: argparse CLI signature -- option flag + choices
  parser.add_argument("--outcome", choices = [ str(outcome) for outcome in _CLOSE_OUTCOMES ], default = None)
  # waiver: argparse CLI signature -- option flag
  parser.add_argument(_FLAG_BACKFILL, action = "store_true")
  args = parser.parse_args(argv)

  # guard: only a read backfills on the way; every other action keeps its own refusal
  if args.backfill and args.action != _ACTION_GET:
    parser.error(f"{_FLAG_BACKFILL} goes with {_ACTION_GET} only")

  # guard: `open` and `close` name the build they act on, and `close` its outcome
  if args.action in ( _ACTION_OPEN, _ACTION_CLOSE ) and args.build is None:
    parser.error(f"{args.action} requires --build")
  if args.action == _ACTION_CLOSE and args.outcome is None:
    parser.error("close requires --outcome")

  # one JSON line per call; a refusal is printed under `error` and carried by the exit code
  try:
    out = _run(args, spec_locator.query_repo_root())
  except BuildRegistryRefusedError as refused:
    print(json.dumps({ _ERROR: str(refused) }, ensure_ascii = False))
    return _EXIT_REFUSED
  print(json.dumps(out, ensure_ascii = False))
  return _EXIT_OK


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
