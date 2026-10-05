"""Spec layout roots — settings-root vs content-root resolution.

The settings-root holds `.claude/lazy.settings.json`; the content-root holds the
subsystem folders and the `requests/` inbox, and is `settings-root/<vault_root>`
(default `specs`). Bin code reads config from the settings-root but joins spec
content under the content-root.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


DEFAULT_VAULT_ROOT = "specs"
_SETTINGS_REL = Path(".claude") / "lazy.settings.json"
_SPEC_SECTION = "spec"
_VAULT_ROOT_KEY = "vault_root"
# waiver: sibling-plugin CLI env contract per dev.plugin-boundaries § 1c
_ENV_PLUGIN_DIRS = "LAZYCORTEX_PLUGIN_DIRS"
_BIN_DIR = "bin"
_TMP_SUFFIX = ".tmp"
_ENCODING = "utf-8"
_WRITE_MODE = "w"
# the mode a plain `open()` would give a new file before the umask is applied
_NEW_FILE_MODE = 0o666
_LF = "\n"
_CRLF = "\r\n"
_CR = "\r"
_CRLF_BYTES = b"\r\n"
_LF_BYTES = b"\n"
_MD = ".md"
_SEP = "/"


def find_settings_root(start: Path) -> Path:
  """
  Walk up from `start` to the nearest dir holding `.claude/lazy.settings.json`.

  Args:
    start: Directory to begin the upward search from.

  Returns:
    The first ancestor (inclusive) containing the settings file; `start`
    resolved when none is found.
  """
  cur = start.resolve()
  for cand in [ cur, *cur.parents ]:
    # guard: first dir carrying the settings file is the settings-root
    if (cand / _SETTINGS_REL).is_file():
      return cand
  return cur


def _vault_root_value(settings_root: Path) -> str:
  """
  Read `spec.vault_root` from settings, defaulting to `specs`.

  Args:
    settings_root: Dir holding `.claude/lazy.settings.json`.

  Returns:
    The configured vault-root segment, or `specs` when unset/malformed.
  """
  path = settings_root / _SETTINGS_REL

  # guard: no settings file — use the default root
  if not path.is_file():
    return DEFAULT_VAULT_ROOT
  data = json.loads(path.read_text(encoding = "utf-8"))
  spec = data.get(_SPEC_SECTION)

  # guard: missing/malformed spec section — default
  if not isinstance(spec, dict):
    return DEFAULT_VAULT_ROOT
  value = spec.get(_VAULT_ROOT_KEY)

  # guard: only a non-empty string overrides the default
  if isinstance(value, str) and value:
    return value
  return DEFAULT_VAULT_ROOT


def spec_content_root(settings_root: Path) -> Path:
  """
  Resolve the spec content-root under a settings-root.

  Args:
    settings_root: Dir holding `.claude/lazy.settings.json`.

  Returns:
    `settings_root / <spec.vault_root>` (default `specs`).
  """

  # Domain(spec.config):
  # # Settings and content live at two different roots
  # A checkout keeps its configuration and its actual spec content at two different roots on
  # purpose: the settings-root is wherever the project's own configuration already lives, while
  # the content-root is a separate, configurable location underneath it that holds nothing but
  # the spec catalog itself. Keeping them apart lets the spec catalog occupy its own named
  # location in a project that organizes its other content differently, without the project's
  # own configuration having to move to make room for it.

  return settings_root / _vault_root_value(settings_root)


def _version_sort_key(name: str) -> tuple[int, ...]:
  """
  Build a numeric sort key for a plugin-cache version directory name.

  Args:
    name: Version directory name as it appears in the plugin cache.

  Returns:
    A tuple of integers so `10.0.0` ranks above `9.1.1`; digit-free components contribute `0`.
  """
  out: list[int] = []
  for part in name.split("."):
    digits = "".join(c for c in part if c.isdigit())
    out.append(int(digits) if digits else 0)
  return tuple(out)


def _cached_sibling_root(name: str) -> Path | None:
  """
  Locate a sibling plugin's newest cached install next to this plugin's own cached install.

  A cached install lives at `<cache>/<registry>/<plugin>/<version>/`, so when this file runs from
  one, the cache root is four levels above `bin/` and every sibling's versions sit under it. A dev
  source tree has no version level above `bin/`, so the walk finds nothing there — the dev layout
  is served by the daemon's env export and each caller's own dev fallback.

  Args:
    name: Sibling plugin name, which is also its cache directory and CLI name.

  Returns:
    The sibling's highest cached version directory, or None outside a cached install or when no
    version of the sibling is cached.
  """
  own = Path(__file__).resolve()

  # guard: not a cached install — a dev checkout has no version directory above bin/
  if not own.parents[1].name.replace(".", "").isdigit():
    return None

  # the cache root sits four levels above bin/: cache/<registry>/<plugin>/<version>/bin
  try:
    cache = own.parents[4]
  except IndexError:
    return None
  versions = [
    version
    for registry in cache.iterdir() if (registry / name).is_dir()
    for version in (registry / name).iterdir()
    if version.is_dir() and version.name.replace(".", "").isdigit()
  ]
  return max(versions, key = lambda v: _version_sort_key(v.name)) if versions else None


def resolve_plugin_cli(name: str) -> Path | None:
  """
  Locate a sibling plugin's CLI binary by name.

  Lets a plugin's bin script reach another plugin's published CLI without assuming a fixed
  install layout; each caller applies its own error handling to a missing result. The plugin-dirs
  environment (exported by the daemon) is walked first; outside the daemon, a cached install falls
  back to the sibling's newest version in the same plugin cache.

  Guarantees:
    - When both the plugin-dirs environment and the plugin cache carry a matching CLI, the
      plugin-dirs environment's copy is returned.

  Args:
    name: Name of the CLI binary to look for under each plugin directory's `bin/` folder.

  Returns:
    The resolved binary path, or None when neither the plugin-dirs environment nor the plugin
    cache carries the named CLI.
  """

  # Contract:
  # When both the plugin-dirs environment and the plugin cache carry a matching CLI,
  # the plugin-dirs environment's copy is returned.

  raw = os.environ.get(_ENV_PLUGIN_DIRS, "")
  for entry in raw.split(os.pathsep):
    # guard: empty path segment (trailing/double pathsep) — skip it
    if not entry:
      continue
    cli = Path(entry) / _BIN_DIR / name
    if cli.is_file():
      return cli

  # plugin-cache fallback — a session (hook, skill) has no daemon export to walk
  root = _cached_sibling_root(name)

  # guard: no cached sibling — nothing further to try
  if root is None:
    return None
  cli = root / _BIN_DIR / name
  return cli if cli.is_file() else None


def spec_roots(start: Path) -> tuple[Path, Path]:
  """
  Resolve both spec layout roots from a starting directory.

  Args:
    start: Directory to resolve roots from (cwd or a content path).

  Returns:
    `(settings_root, content_root)`.
  """
  settings_root = find_settings_root(start)
  return settings_root, spec_content_root(settings_root)


def build_wikilink_target(path: Path, settings_root: Path) -> str:
  """
  Build the wikilink target that resolves to the given spec document.

  The target is the document's path from the content-root, without `.md`, when no vault-root file
  and no other spec document under the content-root shares that short form; otherwise it is the
  document's full path from the vault root (the settings-root), which Obsidian matches exactly. A
  document sitting directly at the content-root, whose short form has no folder segment, always gets
  the full vault path, even when its name is unique.

  Guarantees:
    - The returned target is either the short content-root form, returned only when no vault-root file
      has that path and no other spec document under the content-root shares it as a tail, or the
      document's full path from the vault root; in both cases `resolve_wikilink` maps it back to
      the same document.

  Args:
    path: The linked document.
    settings_root: Dir holding `.claude/lazy.settings.json` — the vault root.

  Returns:
    The suffix-free target, e.g. `core/vision` or `specs/vision`.

  Raises:
    ValueError: When `path` lies outside the spec content-root.
  """

  # Contract:
  # The returned target is either the short content-root form, returned only when no vault-root file
  # has that path and no other spec document under the content-root shares it as a tail, or the
  # document's full path from the vault root; in both cases `resolve_wikilink` maps it back to
  # the same document.

  # Domain(unfiled):
  # # Catalog links name one document and nothing else
  # A link to a spec document uses its path from the content-root, without extension, as long as
  # that short form names the document alone. Obsidian matches a link by path suffix, so the short
  # form stops being unique in three cases. It has no folder segment, because the document sits
  # at the content-root itself. It also names a file reached from the vault root, which Obsidian
  # resolves first. Or it is the tail of another spec document's path. In each case the link
  # carries the document's full path from the vault root instead, which Obsidian matches exactly.

  root = settings_root.resolve()
  doc = path.resolve()
  short = doc.relative_to(spec_content_root(root).resolve()).with_suffix("").as_posix()

  # the catalog's usual short link when it names this document alone, the full vault path otherwise
  unique = _SEP in short and not (root / f"{short}{_MD}").exists() and not _has_shared_tail(short, doc)
  return short if unique else doc.relative_to(root).with_suffix("").as_posix()


def _has_shared_tail(short: str, doc: Path) -> bool:
  """
  Tell whether another spec document's path ends with the same short form as `doc`'s.

  Args:
    short: The document's suffix-free content-root path.
    doc: The resolved document path.

  Returns:
    True when a second document under the content-root carries `short` as its path tail.
  """
  tail = f"{_SEP}{short}{_MD}"
  name = Path(short).name + _MD

  # limit: only the content-root is walked, not the whole Obsidian vault — a same-tailed note
  # outside the catalog still collides; walk the settings-root if one ever appears
  for dirpath, _dirs, files in os.walk(spec_content_root(find_settings_root(doc.parent))):
    if name in files and (cand := Path(dirpath) / name) != doc and cand.as_posix().endswith(tail):
      return True
  return False


def resolve_wikilink(target: str, settings_root: Path) -> Path:
  """
  Resolve a suffix-free wikilink target to the file it names, in the order Obsidian does.

  Args:
    target: The wikilink target, without `|display` or `#anchor`.
    settings_root: Dir holding `.claude/lazy.settings.json` — the vault root.

  Returns:
    `<settings_root>/<target>.md` when that file exists, else `<content-root>/<target>.md`.
  """
  vault_path = settings_root / f"{target}{_MD}"
  return vault_path if vault_path.is_file() else spec_content_root(settings_root) / f"{target}{_MD}"


def read_text(path: Path) -> str:
  """
  Read a text file with `\\n` line endings.

  Notes:
    - Performs file I/O.

  Args:
    path: The file to read, followed through any symlink to its real target.

  Returns:
    The file's text with every `\\r\\n` turned into `\\n`.

  Raises:
    OSError: If the file cannot be read.
  """
  with open(path, encoding = _ENCODING, newline = "") as handle:
    raw = handle.read()
  return raw.replace(_CRLF, _LF)


def _disk_ending(target: Path) -> str:
  """
  Read the line ending a file on disk uses now: the one its first line break carries.

  Args:
    target: The resolved file to inspect.

  Returns:
    `\\r\\n` when the file's first line break is CRLF; `\\n` otherwise, including for a file
    that does not exist or carries no line break.
  """
  try:
    raw = target.read_bytes()
  except FileNotFoundError:
    return _LF
  first = raw.find(_LF_BYTES)
  return _CRLF if first > 0 and raw[first - 1:first + 1] == _CRLF_BYTES else _LF


def write_text_atomic(path: Path, text: str, newline: str | None = None) -> None:
  """
  Replace a file's content in one step, so a reader never sees it half-written.

  Guarantees:
    - Writes through a symlink to its real target rather than replacing the symlink itself.
    - Writes the line ending the target on disk uses at write time — CRLF when its first line
      break is CRLF — and LF for a new file, unless `newline` names the ending explicitly.
    - An existing target keeps its own permission mode; a new file gets the mode a plain write
      would give it under the current umask.
    - On any failure, the temp file is removed and the exception re-raised, leaving the target
      untouched.

  Notes:
    - Performs file I/O.
    - For a new file, briefly sets and restores the process umask to read it — not thread-safe.
    - A mixed-ending file is written back with its first line break's ending throughout.

  Args:
    path: The file to write, followed through any symlink to its real target.
    text: The full text to write, its lines ended by `\\n`.
    newline: The line ending to write, overriding the one detected on disk; None detects it.

  Raises:
    OSError: If the write, chmod, or rename into place fails for any reason.
  """
  target = path.resolve()

  # the ending comes from the caller or from the file as it is on disk now, never from an earlier read
  if (newline or _disk_ending(target)) == _CRLF:
    text = text.replace(_CRLF, _LF).replace(_LF, _CRLF)

  # a replaced file keeps its own mode; a new one gets what a plain write would have given it
  try:
    mode = stat.S_IMODE(target.stat().st_mode)
  except FileNotFoundError:
    umask = os.umask(0)
    os.umask(umask)
    mode = _NEW_FILE_MODE & ~umask

  # the temp file sits beside the target so the final rename never crosses a filesystem
  fd, tmp_name = tempfile.mkstemp(prefix = f".{target.name}.", suffix = _TMP_SUFFIX, dir = target.parent)
  try:
    with os.fdopen(fd, _WRITE_MODE, encoding = _ENCODING, newline = "") as handle:
      handle.write(text)
      handle.flush()
      os.fsync(handle.fileno())
    os.chmod(tmp_name, mode)
    os.replace(tmp_name, target)
  # waiver: broad catch -- an interrupt mid-write must remove the temp file too; the error is re-raised
  except BaseException:
    Path(tmp_name).unlink(missing_ok = True)
    raise
