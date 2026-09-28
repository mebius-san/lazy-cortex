"""
Detects changes to the daemon's own loaded source so it can restart on update.
"""
from __future__ import annotations

import hashlib
import sys
from importlib.machinery import ModuleSpec, PathFinder
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# ----------------------------------------------------------------------------------------
class _ImportObserver:
  """
  Meta-path observer that records a watched module's source hash at the moment it is imported.

  It never loads anything itself: it looks the module up the way the path finder will, records the
  source it is about to load, and declines, so the regular finders load the module as usual.
  """

  def __init__(self, fingerprint: CodeFingerprint) -> None:
    """
    Create an observer feeding the given fingerprint's import-time baseline.

    Args:
      fingerprint: The tracker whose watched roots and import-time hashes this observer serves.
    """
    self._fp = fingerprint

  def find_spec(self, name: str, path: object = None, target: object = None) -> ModuleSpec | None:
    """
    Record the source hash of a watched module about to be imported, then decline.

    Args:
      name: Fully qualified module name being imported.
      path: The parent package's search path, or None for a top-level import.
      target: The module object being reloaded, if any.

    Returns:
      Always None, so the import proceeds through the remaining finders.
    """
    # a lookup failure here must never break the import it merely observes
    try:
      spec = PathFinder.find_spec(name, path, target)  # type: ignore[arg-type]
    # waiver: broad except — observing an import must never be what makes it fail
    except Exception:  # pylint: disable=broad-except
      return None

    # guard: not a file-backed module — nothing to record
    if spec is None or not spec.has_location or not spec.origin:
      return None
    self._fp.record_import(Path(spec.origin).resolve())
    return None


# ----------------------------------------------------------------------------------------
class CodeFingerprint:
  """
  Snapshots the hashes of the daemon's loaded `.py` files and reports a change
  only once it is stable across two consecutive observations (so an in-flight
  half-written update does not trigger a premature restart).
  """

  def __init__(self, *, roots: list[Path] | None = None, paths: list[Path] | None = None) -> None:
    """
    Create a fingerprint tracker scoped to the given plugin roots or an explicit path list.

    Args:
      roots: Plugin source directories under which loaded `.py` modules are tracked.
      paths: Explicit file list to track instead of discovering modules under `roots`;
        intended for tests.
    """
    self._roots = [ Path(r).resolve() for r in ( roots or [] ) ]
    self._explicit = [ Path(p) for p in paths ] if paths is not None else None
    self._base: dict[str, str] = {}
    self._pending: dict[str, str] | None = None
    # source hashes taken at import time for watched modules imported after construction
    self._imported: dict[str, str] = {}

    # a module imported later is baselined from what it loaded, not from its first sighting
    # ponytail: the observer stays on sys.meta_path for the process lifetime (one per daemon)
    if self._explicit is None and self._roots:
      sys.meta_path.insert(0, _ImportObserver(self))

  def _watched(self, p: Path) -> bool:
    """
    Tell whether a resolved source path lives under a watched plugin root.

    Args:
      p: Resolved absolute source path.

    Returns:
      True when `p` is under one of the watched roots.
    """
    return any(str(p).startswith(str(r)) for r in self._roots)

  def record_import(self, p: Path) -> None:
    """
    Record a watched module's source hash as it is being imported.

    Args:
      p: Resolved absolute source path of the module about to load.
    """
    # guard: outside the watched roots, or already recorded by an earlier import
    if not self._watched(p) or str(p) in self._imported:
      return
    try:
      self._imported[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
      return

  def _tracked_paths(self) -> list[Path]:
    """
    Resolve the current set of source file paths this instance tracks.

    Returns:
      The explicit path list when one was supplied at construction, otherwise every loaded
      module's file path that lives under a watched plugin root.
    """

    # Domain(runtime.self-update):
    # # Scope of a daemon's own code
    # A daemon watching its own source for restart-worthy changes only ever tracks files that
    # live under the directories it was explicitly told are its own plugin sources. Code loaded
    # from elsewhere — a dependency, the interpreter's own standard library — is never in scope,
    # no matter how it was reached at runtime.

    # guard: explicit override (tests) — use it verbatim
    if self._explicit is not None:
      return list(self._explicit)
    out: list[Path] = []
    for mod in list(sys.modules.values()):
      f = getattr(mod, "__file__", None)

      # guard: module has no source file (built-in or frozen)
      if not f:
        continue
      p = Path(f).resolve()

      # only modules living under a watched plugin root are our own code
      if self._watched(p):
        out.append(p)
    return out

  def _hashes(self) -> dict[str, str]:
    """
    Compute the current content hash of every tracked source file.

    Guarantees:
      - A tracked path that cannot be read when this is called is omitted from the result
        rather than raising.

    Returns:
      Mapping from absolute file path string to its SHA-256 hex digest. A tracked path that
      cannot be read is omitted rather than raising.
    """

    # Contract:
    # A tracked path that cannot be read when this is called is silently omitted from the
    # result rather than raising; it never causes the call to fail.

    # hash every tracked path, skipping any that cannot currently be read
    out: dict[str, str] = {}
    for p in self._tracked_paths():
      try:
        out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
      except OSError:
        continue
    return out

  def snapshot(self) -> None:
    """
    Record the current hashes as the accepted baseline.
    """
    self._base = self._hashes()
    self._pending = None

  def changed(self) -> bool:
    """
    Return True only when a hash change is stable across two consecutive observations.

    Comparison on each call is restricted to paths present in both the baseline and the current
    observation. A path seen for the first time joins the baseline immediately with its current
    hash, so the discovery itself never signals a change — a later edit to that path is then
    detected the same way as an edit to a path already present at startup. A path that disappears
    from the current observation (rare — would require a module unload) is excluded from the
    comparison and never by itself signals a change.

    Guarantees:
      - Returns True only once the same difference from the accepted baseline has been
        observed on two consecutive calls in a row.
      - A tracked path discovered for the first time joins the baseline with the hash it had
        when it was imported, when an import was observed, or with its hash at first sighting
        otherwise; either way the discovery never by itself triggers a change, and a later
        edit to that path is then detected under the same two-observation stability rule as a
        path present at startup.
      - A tracked path that disappears between two observations is excluded from the
        comparison and never by itself triggers a change.

    Returns:
      True if the same change was observed on both this and the previous call; False otherwise.
    """

    # Contract:
    # A True verdict is only ever returned once the same difference from the accepted
    # baseline has been observed on two consecutive calls in a row; a difference seen once
    # and then reverted, or replaced by a different difference before the next call, is
    # never reported as a change.

    # observe the current hashes to compare against the accepted baseline
    now = self._hashes()

    # Contract:
    # A tracked path discovered for the first time since the baseline was taken joins the
    # baseline with the hash recorded when it was imported, when an import observer captured
    # one; otherwise it joins with its hash at first sighting. Either way, discovering it never
    # by itself causes this call to return True. A later edit to that same path is then reported
    # once the identical edit has been observed on two consecutive calls, exactly as for a path
    # already present in the baseline.

    # a path seen for the first time joins the baseline with the hash it had when it was imported
    # (its current hash when the import was not observed), so the discovery itself is never a
    # change but an edit made after the import is compared like any startup path
    for path in now.keys() - self._base.keys():
      self._base[path] = self._imported.get(path, now[path])

    # Contract:
    # A tracked path that disappears between two observations is left out of the comparison and
    # never by itself causes a True verdict.

    # restrict the comparison to paths present in both the baseline and the current observation
    shared = self._base.keys() & now.keys()
    now_shared = { k: now[k] for k in shared }
    base_shared = { k: self._base[k] for k in shared }

    # Domain(runtime.self-update):
    # # Self-update change detection
    # A daemon watching its own loaded source treats a change as real only once the exact
    # same difference from the accepted baseline appears on two consecutive checks in a row;
    # a difference seen once and then reverted, or replaced by a different difference before
    # the second check, is never treated as a change. A source file observed for the first
    # time since the baseline was taken joins the baseline carrying the content it had at the
    # moment the daemon loaded it, falling back to its content at first sighting only when
    # that load was never observed — so an edit landing between the load and the next check is
    # still detected, while the discovery itself is never by itself treated as a change. A
    # later edit to that same file is then detected under the identical two-observation
    # stability rule as a file that was already part of the baseline at startup.

    # guard: identical to the accepted baseline on the shared key set — no change
    if now_shared == base_shared:
      self._pending = None
      return False

    # require the same diff twice in a row (stability) before declaring a change; compare the
    # pending snapshot on the SAME shared key set so a lazy-import growing the pending dict
    # between observations does not invalidate stability.
    if self._pending is not None:
      pending_shared = { k: self._pending[k] for k in shared if k in self._pending }
      if pending_shared == now_shared:
        return True
    self._pending = now
    return False
