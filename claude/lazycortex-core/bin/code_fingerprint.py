"""
Detects changes to the daemon's own loaded source so it can restart on update.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# ----------------------------------------------------------------------------------------
class CodeFingerprint:
  """
  Snapshots the hashes of the daemon's loaded `.py` files and reports a change
  only once it is stable across two consecutive observations (so an in-flight
  half-written update does not trigger a premature restart).
  """

  def __init__(self, *, roots: list[Path] | None = None, paths: list[Path] | None = None) -> None:
    self._roots = [ Path(r).resolve() for r in ( roots or [] ) ]
    self._explicit = [ Path(p) for p in paths ] if paths is not None else None
    self._base: dict[str, str] = {}
    self._pending: dict[str, str] | None = None

  def _tracked_paths(self) -> list[Path]:
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
      # guard: module not under a watched plugin root
      if any(str(p).startswith(str(r)) for r in self._roots):
        out.append(p)
    return out

  def _hashes(self) -> dict[str, str]:
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

    Returns:
      True if the same change was observed on both this and the previous call; False otherwise.
    """
    now = self._hashes()
    # guard: identical to the accepted baseline — no change
    if now == self._base:
      self._pending = None
      return False
    # require the same diff twice in a row (stability) before declaring a change
    if self._pending == now:
      return True
    self._pending = now
    return False
