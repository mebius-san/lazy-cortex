"""
Deterministic transport primitive for mirroring one path subset of a foreign
git repository into a local destination tree.

Reads `{url, branch?, cache_dir, include[], exclude[], max_bytes?, dest,
mode: "plan"|"sync", skip_fetch?}` from stdin, shallow-clones (or fast-forwards) the
source into `cache_dir`, classifies every included file against `dest`
(added / updated / removed / unchanged / skipped), and — only in `sync`
mode — applies the plan verbatim. There is no merge logic: a synced file's
destination bytes always equal its source bytes.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Plan-item `action` tokens — the closed vocabulary the CLI contract promises.
ACTION_ADDED = "added"
ACTION_UPDATED = "updated"
ACTION_REMOVED = "removed"
ACTION_UNCHANGED = "unchanged"
ACTION_SKIPPED = "skipped"

# Skip-item `reason` tokens — the closed vocabulary for a `skipped` plan item.
REASON_SYMLINK = "symlink"
REASON_TOO_LARGE = "too-large"
REASON_BINARY = "binary"

# Request `mode` tokens — the closed vocabulary the CLI contract promises.
MODE_PLAN = "plan"
MODE_SYNC = "sync"

# Default per-file size ceiling (bytes) above which a file is classified skipped.
DEFAULT_MAX_BYTES = 1_048_576

# Byte window read from a candidate file's head to decide binary vs text.
_BINARY_SNIFF_BYTES = 8192

# Directory whose presence marks a git working copy.
_GIT_DIR = ".git"

# Mode string for a binary-content read probe.
_READ_BINARY = "rb"


class _Key:
  """
  JSON field names of the `remote-mirror` request/response contract.

  Attributes:
    URL: Request field naming the source repository's git URL.
    BRANCH: Request field naming the branch to clone/fetch.
    CACHE_DIR: Request field naming the caller-owned clone directory.
    DEST: Request field naming the destination directory.
    INCLUDE: Request field naming the include-glob list.
    EXCLUDE: Request field naming the exclude-glob list.
    MAX_BYTES: Request field naming the per-file size ceiling.
    MODE: Request field naming the `plan`/`sync` mode.
    SKIP_FETCH: Optional request field; a true value reuses an existing clone without a
      network round-trip. Ignored when no clone exists yet.
    FETCHED_SHA: Response field naming the clone's resolved commit SHA.
    PLAN: Response field naming the classified plan-item list.
    APPLIED: Response field naming whether the plan was applied.
    ERROR: Response field naming an error message when the request could not be completed.
    PATH: Plan-item field naming the classified file's relative POSIX path.
    ACTION: Plan-item field naming the classification token.
    REASON: Plan-item field naming the skip reason (`skipped` items only).
  """

  URL = "url"
  BRANCH = "branch"
  CACHE_DIR = "cache_dir"
  DEST = "dest"
  INCLUDE = "include"
  EXCLUDE = "exclude"
  MAX_BYTES = "max_bytes"
  MODE = "mode"
  SKIP_FETCH = "skip_fetch"
  FETCHED_SHA = "fetched_sha"
  PLAN = "plan"
  APPLIED = "applied"
  ERROR = "error"
  PATH = "path"
  ACTION = "action"
  REASON = "reason"


# ----------------------------------------------------------------------------------------
class GlobMatcher:
  """
  Shell-style glob matcher with path-aware separator semantics.

  Matches repo-relative POSIX paths against glob patterns where a single `*` matches within
  one path component and `**` matches zero or more whole components, so a pattern such as
  `src/*.py` never matches a nested path like `src/sub/a.py`.

  Notes:
    - Repeated matches against an already-seen pattern reuse a cached compiled regex.
  """

  def __init__(self) -> None:
    """
    Create a matcher ready to test paths against glob patterns.
    """
    self._cache: dict[str, re.Pattern] = {}

  def match(self, rel_posix: str, pattern: str) -> bool:
    """
    Return True when `rel_posix` matches `pattern` under shell glob semantics.

    A single `*` matches within one path component and never crosses `/`; `**` matches zero
    or more whole path components.

    Args:
      rel_posix: Repo-relative POSIX path string (no leading `/`).
      pattern: Shell glob pattern; `**` matches zero or more path components.

    Returns:
      True on a match, False otherwise.
    """
    # compile once per pattern — the same globs are re-tested for every walked file
    if pattern not in self._cache:
      self._cache[pattern] = self._compile(pattern)
    return bool(self._cache[pattern].match(rel_posix))

  def _compile(self, pattern: str) -> re.Pattern:
    """
    Compile one glob pattern to a `re.Pattern` with the same `*`/`**` semantics as `match`.

    Args:
      pattern: Shell glob pattern; may or may not contain `**`.

    Returns:
      Compiled regular expression equivalent to the pattern under this class's glob rules.
    """
    # split on ** and escape/translate each non-** segment
    parts = pattern.split("**")
    segs: list[str] = []
    for part in parts:
      escaped = re.escape(part)
      # waiver: re.escape produces raw-string literals; replace back glob chars
      escaped = escaped.replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
      segs.append(escaped)
    regex = ".*".join(segs)
    # normalise /.*/ → zero or more path components (includes bare /)
    regex = regex.replace("/.*/", "(?:/|/.*/)")
    # normalise leading .*/ → optional (handles **/*.md matching top-level files)
    if regex.startswith(".*/"):
      regex = "(?:.*/)?" + regex[3:]
    # normalise trailing /.* → optional trailing slash+anything
    if regex.endswith("/.*"):
      regex = regex[:-3] + "(?:/.*)?"
    return re.compile("^" + regex + "$")


# ----------------------------------------------------------------------------------------
class RemoteMirror:
  """
  Fetch-and-plan engine for one local clone of a foreign git repository.

  Represents a mirroring relationship between one source repository and one destination tree.
  Every synced file's bytes are a verbatim copy of the source; no merge logic applies.

  Responsibilities:
    - Maintains a local clone of the source repository, updating it in place across calls.
    - Classifies destination files against the current source state and applies the
      classified changes on request.

  Guarantees:
    - Running a sync twice against an unchanged source produces an all-`unchanged` plan on
      the second run.
    - A failure never touches the destination tree; an existing clone may be left mid-update
      only if the failure occurs after local objects were fetched but before the working
      copy is reset to them.
  """

  def __init__(
    self, *, url: str, cache_dir: Path | str, dest: Path | str,
    branch: str | None = None, include: list[str] | None = None,
    exclude: list[str] | None = None, max_bytes: int | None = None,
  ) -> None:
    """
    Initialise the engine for one source/destination pair.

    Args:
      url: Git URL (or local path) of the source repository.
      cache_dir: Clone directory; the caller owns its placement (e.g. a
        `.runtime/<owner>/<key>` scratch dir) and its reuse across calls.
      dest: Destination directory the plan classifies against and `sync` writes to.
      branch: Branch to clone/fetch; `None` follows the remote default branch.
      include: Glob patterns selecting source files; empty/`None` selects everything.
      exclude: Glob patterns excluding source files, applied after `include`.
      max_bytes: Per-file size ceiling above which a file is classified skipped;
        `None` falls back to `DEFAULT_MAX_BYTES`.
    """
    self._url = url
    self._branch = branch
    self._cache_dir = Path(cache_dir)
    self._dest = Path(dest)
    self._include = list(include or [])
    self._exclude = list(exclude or [])
    self._max_bytes = max_bytes if max_bytes is not None else DEFAULT_MAX_BYTES
    self._matcher = GlobMatcher()

  def fetch(self) -> str | None:
    """
    Clone the source on first use, or reset the existing clone onto the source's current head.

    Guarantees:
      - A failure never touches the destination tree; an existing clone may be left
        mid-update, with `FETCH_HEAD` already advanced, only when the fetch step succeeded
        and the following reset step then failed.

    Returns:
      `None` on success, or a one-line error message on failure.
    """
    # an existing clone is updated in place; anything else is cloned fresh
    if (self._cache_dir / _GIT_DIR).is_dir():
      steps = [
        [ "git", "fetch", "--depth", "1", "origin", *( [ self._branch ] if self._branch else [] ) ],
        [ "git", "reset", "--hard", "FETCH_HEAD" ],
      ]
      for cmd in steps:
        proc = subprocess.run(
          cmd, cwd = str(self._cache_dir), capture_output = True, text = True, check = False,
        )

        # Contract:
        # A failed step is reported immediately — the destination tree is never touched by a
        # failed fetch, though the clone itself may sit mid-update (FETCH_HEAD advanced by a
        # successful fetch step whose following reset step then failed).

        # guard: a git step failed — report it; the clone is never touched further
        if proc.returncode != 0:
          return f"remote-mirror fetch failed for '{self._url}': {proc.stderr.strip()}"
      return None

    # first fetch — shallow-clone the requested branch into the cache dir
    self._cache_dir.parent.mkdir(parents = True, exist_ok = True)
    cmd = [
      "git", "clone", "--depth", "1", *( [ "--branch", self._branch ] if self._branch else [] ),
      self._url, str(self._cache_dir),
    ]
    proc = subprocess.run(cmd, capture_output = True, text = True, check = False)

    # Contract:
    # A failed clone never touches the destination tree.

    # guard: clone failed — report it and leave everything untouched
    if proc.returncode != 0:
      return f"remote-mirror clone failed for '{self._url}': {proc.stderr.strip()}"
    return None

  def fetched_sha(self) -> str:
    """
    Return the commit SHA the clone currently points at.

    Returns:
      The full hex SHA of the clone's `HEAD`.
    """
    proc = subprocess.run(
      [ "git", "rev-parse", "HEAD" ], cwd = str(self._cache_dir),
      capture_output = True, text = True, check = True,
    )
    return proc.stdout.strip()

  def plan(self) -> list[dict]:
    """
    Classify every included source file against `dest`, without writing.

    Guarantees:
      - A destination file already byte-identical to its source classifies as unchanged, so a
        second `sync` against an unchanged source plans all-unchanged and writes nothing.

    Returns:
      Plan items sorted by path, one per included or removed file. Each item carries the
      file's path and its classification token; a reason accompanies only skipped items.
    """
    filtered = self._filtered_source_files()
    items: list[dict] = []

    # every included source file classifies as skipped, added, updated, or unchanged
    for rel in filtered:
      src_abs = self._cache_dir / rel
      reason = self._skip_reason(src_abs)
      if reason is not None:
        items.append({ _Key.PATH: rel, _Key.ACTION: ACTION_SKIPPED, _Key.REASON: reason })
        continue
      dest_abs = self._dest / rel
      if not dest_abs.is_file():
        items.append({ _Key.PATH: rel, _Key.ACTION: ACTION_ADDED })
      elif src_abs.read_bytes() == dest_abs.read_bytes():

        # Contract:
        # A destination file already byte-identical to its source classifies as unchanged, so
        # a second `sync` against an unchanged source plans all-unchanged and writes nothing.

        # file content matches — nothing for sync to do here
        items.append({ _Key.PATH: rel, _Key.ACTION: ACTION_UNCHANGED })
      else:
        items.append({ _Key.PATH: rel, _Key.ACTION: ACTION_UPDATED })

    # anything under dest the current include/exclude selection no longer names is removed
    expected = set(filtered)
    for rel in self._dest_files():
      if rel not in expected:
        items.append({ _Key.PATH: rel, _Key.ACTION: ACTION_REMOVED })

    # a single deterministic order regardless of how each item's classification branch ran
    items.sort(key = lambda item: item[_Key.PATH])
    return items

  def sync(self) -> list[dict]:
    """
    Compute the current plan and apply it to the destination tree.

    Guarantees:
      - Every `added`/`updated` destination file ends up byte-identical to its source; no
        merge logic ever combines source and destination content.

    Notes:
      - `added`/`updated` items copy the source bytes verbatim, creating parent directories
        as needed.
      - `removed` items delete the destination file.
      - `unchanged`/`skipped` items are left untouched.

    Returns:
      The applied plan, in the same shape as an unapplied plan.
    """
    items = self.plan()
    # apply each classification: added/updated copy source bytes, removed deletes, the rest no-op
    for item in items:
      if item[_Key.ACTION] in ( ACTION_ADDED, ACTION_UPDATED ):
        dest_abs = self._dest / item[_Key.PATH]
        dest_abs.parent.mkdir(parents = True, exist_ok = True)

        # Contract:
        # The destination file's bytes end up identical to the source file's bytes — a
        # verbatim copy, never a merge.

        # the actual write — everything above only prepared the target location
        dest_abs.write_bytes((self._cache_dir / item[_Key.PATH]).read_bytes())
      elif item[_Key.ACTION] == ACTION_REMOVED:
        (self._dest / item[_Key.PATH]).unlink(missing_ok = True)
    return items

  def _filtered_source_files(self) -> list[str]:
    """
    Enumerate the clone's git-tracked files matching `include` minus `exclude`.

    Returns:
      Sorted list of clone-relative POSIX path strings.
    """
    proc = subprocess.run(
      [ "git", "ls-files" ], cwd = str(self._cache_dir),
      capture_output = True, text = True, check = True,
    )
    result: list[str] = []
    for rel in proc.stdout.splitlines():
      # guard: include configured and this tracked file matches none of its patterns — drop it
      if self._include and not any(self._matcher.match(rel, pat) for pat in self._include):
        continue
      # guard: named by an exclude glob
      if any(self._matcher.match(rel, pat) for pat in self._exclude):
        continue
      result.append(rel)
    return sorted(result)

  def _skip_reason(self, path: Path) -> str | None:
    """
    Classify a source file as skip-worthy: symlink, oversized, or binary.

    Args:
      path: Absolute path of the source file inside the clone.

    Returns:
      One of `"symlink"`, `"too-large"`, `"binary"`, or `None` when the file
      is eligible to be synced.
    """
    # guard: a symlinked entry is never dereferenced and copied
    if path.is_symlink():
      return REASON_SYMLINK
    # guard: over the configured per-file ceiling
    if path.stat().st_size > self._max_bytes:
      return REASON_TOO_LARGE
    with path.open(_READ_BINARY) as fh:
      chunk = fh.read(_BINARY_SNIFF_BYTES)
    # guard: a NUL byte in the head window marks the file as non-text
    if b"\x00" in chunk:
      return REASON_BINARY
    return None

  def _dest_files(self) -> list[str]:
    """
    Enumerate the files currently present under `dest`.

    Returns:
      Dest-relative POSIX path strings, unsorted; empty when `dest` does not exist.
    """
    # guard: destination not created yet — nothing to compare against
    if not self._dest.is_dir():
      return []
    result: list[str] = []
    for base, _dirs, files in os.walk(str(self._dest)):
      for fname in files:
        result.append((Path(base) / fname).relative_to(self._dest).as_posix())
    return result


# ----------------------------------------------------------------------------------------
def run(payload: dict) -> dict:
  """
  Execute one `remote-mirror` request against the contract payload.

  Args:
    payload: Parsed request body — `{url, branch?, cache_dir, include[],
      exclude[], max_bytes?, dest, mode, skip_fetch?}`. `mode` must be `"plan"` or `"sync"`.

  Returns:
    `{"fetched_sha", "plan", "applied"}` on success, or `{"error"}` when the fetch step
    failed — the destination tree is untouched in that case, though an existing clone may
    be left mid-update if the failure occurred partway through the update.

  Raises:
    TypeError: `payload` is not a mapping (e.g. valid JSON that decoded to a list or scalar).
    KeyError: A required field (`url`, `cache_dir`, `dest`, `mode`) is missing.
    ValueError: `mode` is neither `"plan"` nor `"sync"`.
    subprocess.CalledProcessError: A git query step (`rev-parse`, `ls-files`) failed after a
      successful fetch — distinct from a fetch/clone failure, which is reported in-band.
    OSError: Reading a source file or writing/deleting a destination file failed.
  """
  mode = payload[_Key.MODE]
  # guard: mode is a closed vocabulary — an unrecognised value is a caller bug, not a fetch error
  if mode not in ( MODE_PLAN, MODE_SYNC ):
    raise ValueError(f"mode must be '{MODE_PLAN}' or '{MODE_SYNC}', got {mode!r}")

  # required fields raise KeyError on the caller's behalf; optional ones fall back inside RemoteMirror
  mirror = RemoteMirror(
    url = payload[_Key.URL], branch = payload.get(_Key.BRANCH),
    cache_dir = payload[_Key.CACHE_DIR], dest = payload[_Key.DEST],
    include = payload.get(_Key.INCLUDE), exclude = payload.get(_Key.EXCLUDE),
    max_bytes = payload.get(_Key.MAX_BYTES),
  )

  # Contract:
  # `skip_fetch` is an optimization, never a correctness switch: it only reuses a clone the
  # caller already fetched this pass, and with no clone on disk the fetch still runs.

  # reuse the caller's already-fetched clone when it vouches for one
  if not (payload.get(_Key.SKIP_FETCH) and (Path(payload[_Key.CACHE_DIR]) / _GIT_DIR).is_dir()):
    error = mirror.fetch()
    # guard: fetch failed — the caller gets just the error, clone/dest stay untouched
    if error is not None:
      return { _Key.ERROR: error }

  # sync applies the plan as a side effect; plan mode only classifies
  plan = mirror.sync() if mode == MODE_SYNC else mirror.plan()
  return { _Key.FETCHED_SHA: mirror.fetched_sha(), _Key.PLAN: plan, _Key.APPLIED: mode == MODE_SYNC }


def main(argv: list[str]) -> int:
  """
  Run the `remote-mirror` CLI subcommand: JSON request on stdin, JSON result on stdout.

  Args:
    argv: Subcommand tail; unused — the whole request travels via stdin.

  Returns:
    `0` on success, `1` on any failure — a parse error, a missing/invalid field, a fetch
    failure, or an underlying git/filesystem error.
  """
  del argv
  try:
    payload = json.loads(sys.stdin.read() or "{}")
  except json.JSONDecodeError as e:
    print(json.dumps({ _Key.ERROR: f"request parse: {e}" }))
    return 1
  try:
    result = run(payload)
  except TypeError as e:
    print(json.dumps({ _Key.ERROR: f"invalid request shape: {e}" }))
    return 1
  except KeyError as e:
    print(json.dumps({ _Key.ERROR: f"missing required field: {e}" }))
    return 1
  except ValueError as e:
    print(json.dumps({ _Key.ERROR: str(e) }))
    return 1
  except ( subprocess.CalledProcessError, OSError ) as e:

    # Contract:
    # Every failure — including a git query or filesystem error past the fetch step — reaches
    # stdout as the same `{"error": ...}` shape; the CLI never emits a raw traceback.

    # same error shape and exit code as every other failure path above
    print(json.dumps({ _Key.ERROR: str(e) }))
    return 1
  print(json.dumps(result, ensure_ascii = False))
  return 1 if _Key.ERROR in result else 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
