"""
Filesystem scope of the sandbox that confines expert spawns.

A confined spawn is checked against the path the operating system resolves, not the
path the allowlist spells, so an entry reached through a symlink grants nothing: the
directory it names is permitted while the location the data actually lives in is not.
This module derives the resolved locations behind a set of allowlist entries, records
the missing ones in the daemon-owned sandbox settings file, and reports the ones a
checkout is still missing so a drifted symlink surfaces as a finding instead of as a
run of jobs that fail on every write.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import json
import os
from pathlib import Path

from constants import RuntimeFile, SandboxKey, SandboxSyncKey

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# home-relative root of the LazyCortex marketplace's plugin cache; same value as
# runtime_daemon.PLUGIN_CACHE_REL — not imported from there to avoid pulling in the daemon's
# whole dependency graph for one path constant.
_PLUGIN_CACHE_REL = ".claude/plugins/cache"
_PLUGIN_CACHE_REGISTRY = "lazycortex"


def _expand(path: str | Path) -> str:
  """
  Return one allowlist entry in the absolute literal form the sandbox compares against.

  Args:
    path: Allowlist entry as written, optionally carrying `~` or environment variables.

  Returns:
    The expanded absolute path with no trailing separator, and never resolved through
    symlinks — the literal form is what the confinement grants.
  """
  expanded = Path(os.path.expandvars(str(path))).expanduser()
  return os.path.normpath(str(expanded.absolute()))


def _is_covered_by(target: str, entry: str) -> bool:
  """
  Report whether one allowlist entry reaches a location.

  Args:
    target: Expanded absolute location to test.
    entry: Expanded allowlist entry.

  Returns:
    True when the entry names the location itself or a directory above it.
  """
  return target == entry or target.startswith(entry + os.sep)


def _link_targets(base: str) -> list[str]:
  """
  List the locations the symlinks directly inside one directory point at.

  Notes:
    - Only the immediate children are followed. A symlink deeper in the tree is out of
      scope; its own parent is either covered by an entry or reported through one.

  Args:
    base: Expanded absolute path of the directory to scan.

  Returns:
    The resolved target of every immediate symlink child, in listing order; empty when
    the path is not a readable directory or holds no symlinks.
  """
  # guard: only an existing directory has children to scan, and a listing may still be refused
  try:
    names = sorted(os.listdir(base))
  except OSError:
    return []

  # ponytail: immediate children only — a deeper symlink needs its parent declared as its own entry
  return [ os.path.realpath(os.path.join(base, name)) for name in names
           if os.path.islink(os.path.join(base, name)) ]


def _dead_cache_entries(entries: list[str]) -> list[str]:
  """
  List the recorded read entries that name a plugin-cache location no longer on disk.

  Notes:
    - Scoped to the LazyCortex marketplace's own plugin cache: a recorded entry outside it is
      never reported here, however stale its target, since a checkout may have recorded it
      for a reason this module cannot see. A version-pinned cache entry carries no such
      reason — it is only ever a byproduct of a past plugin update.

  Args:
    entries: Recorded read-allowlist entries, in any form.

  Returns:
    The entries (as recorded, not expanded) whose expanded path sits under the plugin cache
    root and does not exist on disk; order-stable, empty when none qualify.
  """

  # Domain(runtime.preflight):
  # # Stale plugin-cache grants are pruned, everything else is left alone
  # A recorded read entry that points inside the LazyCortex plugin cache and no longer exists
  # on disk is a version pin left behind by a plugin update — the checkout moved past that
  # cached version and the old directory is simply gone, so nothing is lost by dropping the
  # entry that named it. The same emptiness anywhere outside the plugin cache is never treated
  # this way and stays recorded exactly as found, because a checkout may hold that entry for
  # a reason this mechanism has no way to see.

  cache_root = _expand(Path.home() / _PLUGIN_CACHE_REL / _PLUGIN_CACHE_REGISTRY)
  return [ e for e in entries
           if _is_covered_by(_expand(e), cache_root) and not os.path.isdir(_expand(e)) ]


def resolve_scope(entries: list[str]) -> list[str]:
  """
  Expand a set of allowlist entries into every location they are meant to reach.

  Notes:
    - Each entry contributes the location it resolves to, and — when it is a directory —
      the location behind each symlink directly inside it. Both are what a confined spawn
      actually touches when it writes through the entry.

  Args:
    entries: Allowlist entries as recorded, in any form.

  Returns:
    The expanded entries followed by the resolved locations they reach, deduplicated and
    order-stable; a location already covered by an entry is dropped.
  """

  # Domain(runtime.preflight):
  # # Sandbox confinement follows the resolved location, not the allowlist spelling
  # A confined spawn is checked by the operating system against the location a path actually
  # resolves to, never against the literal text an allowlist entry spells. An entry reached
  # only through a symlink therefore grants confinement over the link itself while leaving
  # the location its target actually lives at outside the sandbox entirely, so every write
  # through that link fails even though the entry appears to cover it. Each directory an
  # entry reaches through one of its own immediate symlinks earns a resolved entry of its
  # own so the sandbox has something literal to compare against; a location a broader entry
  # already reaches needs no separate one.

  # the entries themselves, in the literal form the confinement compares against
  expanded = [ _expand(e) for e in entries if str(e).strip() ]

  # every location those entries are meant to reach, before removing the ones already covered
  reached: list[str] = []
  for entry in expanded:
    reached.append(os.path.realpath(entry))
    reached.extend(_link_targets(entry))

  # a reached location earns an entry of its own only when nothing already recorded grants it
  scope = list(dict.fromkeys(expanded))
  for target in reached:
    # guard: a location an entry already reaches needs no entry of its own
    if any(_is_covered_by(target, entry) for entry in scope):
      continue
    scope.append(target)

  # the recorded entries first, then what they reach — order the caller records verbatim
  return scope


def missing_paths(entries: list[str]) -> list[str]:
  """
  List the locations a set of allowlist entries is meant to reach but does not grant.

  Args:
    entries: Allowlist entries as recorded, in any form.

  Returns:
    The resolved locations no recorded entry covers, order-stable; empty when the
    recorded entries already reach everything they resolve to.
  """
  expanded = [ _expand(e) for e in entries if str(e).strip() ]
  return [ p for p in resolve_scope(entries) if p not in expanded ]


def settings_path(repo: Path | str) -> Path:
  """
  Return the sandbox settings file of a repository.

  Args:
    repo: Repository root whose runtime directory holds the file.

  Returns:
    Absolute path of `<repo>/.runtime/sandbox.settings.json`, whether or not it exists.
  """
  return Path(repo) / RuntimeFile.SANDBOX_SETTINGS


def _read(path: Path) -> dict:
  """
  Read one sandbox settings file.

  Args:
    path: Absolute path of the settings file.

  Returns:
    The parsed document, or an empty dict when the file is absent or unparseable — an
    unreadable file is replaced rather than merged into, since nothing in it can be trusted.
  """
  # guard: an absent file carries no settings to preserve
  if not path.exists():
    return {}

  # a file that cannot be read or parsed carries nothing worth preserving either
  try:
    # waiver: stdlib encoding idiom
    parsed = json.loads(path.read_text(encoding = "utf-8"))
  except (OSError, json.JSONDecodeError):
    return {}

  # only a JSON object can hold the settings this module reads back
  return parsed if isinstance(parsed, dict) else {}


def _recorded(doc: dict, key: str) -> list[str]:
  """
  Return one allowlist as recorded in a sandbox settings document.

  Args:
    doc: Parsed sandbox settings document.
    key: Allowlist field name from `SandboxKey`.

  Returns:
    The recorded entries as strings, in file order; empty when the document records none.
  """
  sandbox = doc.get(SandboxKey.SANDBOX)
  filesystem = sandbox.get(SandboxKey.FILESYSTEM) if isinstance(sandbox, dict) else None
  raw = filesystem.get(key) if isinstance(filesystem, dict) else None
  return [ str(e) for e in raw if str(e).strip() ] if isinstance(raw, list) else []


def audit(repo: Path | str) -> dict:
  """
  Report which locations the recorded sandbox scope of a repository fails to grant.

  Guarantees:
    - A checkout with no sandbox settings file is reported as absent rather than as a
      set of findings; it runs its spawns unconfined and has nothing to be missing.

  Args:
    repo: Repository root whose sandbox settings are read.

  Returns:
    A result dict carrying `SandboxSyncKey` fields: the file location, whether it exists,
    the recorded confinement switch, and the uncovered read and write locations.
  """

  # Contract:
  # A checkout with no sandbox settings file is reported as absent rather than as a set
  # of findings; a caller must not read an empty missing-read/missing-write list from an
  # absent file as proof of full coverage.

  # what the checkout records today, and whether it records a confinement switch at all
  path = settings_path(repo)
  doc = _read(path)
  sandbox = doc.get(SandboxKey.SANDBOX)
  enabled = sandbox.get(SandboxKey.ENABLED) if isinstance(sandbox, dict) else None
  unsandboxed = sandbox.get(SandboxKey.ALLOW_UNSANDBOXED) if isinstance(sandbox, dict) else None

  # what the caller reports: where the scope lives, what it grants, and what it fails to grant
  return {
    SandboxSyncKey.PATH: str(path),
    SandboxSyncKey.PRESENT: path.exists(),
    SandboxSyncKey.ENABLED: enabled if isinstance(enabled, bool) else None,
    SandboxSyncKey.ALLOW_UNSANDBOXED: unsandboxed if isinstance(unsandboxed, bool) else None,
    SandboxSyncKey.MISSING_READ: missing_paths(_recorded(doc, SandboxKey.ALLOW_READ)),
    SandboxSyncKey.MISSING_WRITE: missing_paths(_recorded(doc, SandboxKey.ALLOW_WRITE)),
  }


def sync(repo: Path | str, *, read: list[str] | None = None, write: list[str] | None = None) -> dict:
  """
  Record the full sandbox scope of a repository, adding every location its entries reach.

  Guarantees:
    - The repository root is always in scope, readable and writable.
    - Whatever is writable is also readable.
    - A recorded allowlist entry is never dropped or reordered, except a recorded read
      entry naming a LazyCortex plugin-cache location that no longer exists on disk.
    - A recorded confinement switch or unsandboxed-retry switch is never overwritten;
      only a switch absent from the file is given its default value.
    - The file is rewritten only when the document to record differs from what is
      already on disk; a pass that changes nothing leaves the file untouched.

  Args:
    repo: Repository root whose sandbox settings are recorded.
    read: Additional paths a confined spawn must be able to read, such as plugin sources.
    write: Additional paths a confined spawn must be able to write.

  Returns:
    A result dict carrying `SandboxSyncKey` fields: the file location, whether it existed,
    the confinement switch after the call, the entries appended to each allowlist, the read
    entries pruned as dead plugin-cache versions, and whether the file was rewritten.
  """

  # Contract:
  # The repository root is always included in both the read and write allowlists,
  # regardless of the `read` / `write` arguments — a spawn confined out of the checkout
  # it works in can do nothing.

  # Contract:
  # Every location included in the write allowlist is also included in the read
  # allowlist.

  # Contract:
  # A recorded allowlist entry is never dropped or reordered, except a recorded read
  # entry naming a LazyCortex plugin-cache location that no longer exists on disk.

  # Contract:
  # A recorded confinement switch or unsandboxed-retry switch is never overwritten;
  # only a switch absent from the file is given its default value.

  # Contract:
  # The settings file is rewritten only when the document to record differs from what
  # is already on disk; a pass that changes nothing leaves the file untouched.

  # what the checkout records today, snapshot before anything is written
  path = settings_path(repo)
  # waiver: read once, but the write below flips it — the result must report the state the caller met
  present = path.exists()
  doc = _read(path)
  root = str(Path(repo).absolute())

  # the full scope each allowlist must grant: what is recorded, what the caller asked for,
  # the checkout itself, and every location those reach through a symlink
  recorded_write = _recorded(doc, SandboxKey.ALLOW_WRITE)
  wanted_write = resolve_scope([ *recorded_write, root, *(write or []) ])
  recorded_read = _recorded(doc, SandboxKey.ALLOW_READ)
  wanted_read = resolve_scope([ *recorded_read, root, *(read or []), *wanted_write ])

  # only entries that are genuinely new are appended, so the recorded order is preserved
  added_write = [ p for p in wanted_write if p not in [ _expand(e) for e in recorded_write ] ]
  added_read = [ p for p in wanted_read if p not in [ _expand(e) for e in recorded_read ] ]

  # rebuild the sandbox block around what the file already carries, replacing nothing but the lists
  sandbox = doc.get(SandboxKey.SANDBOX)
  sandbox = dict(sandbox) if isinstance(sandbox, dict) else {}
  filesystem = sandbox.get(SandboxKey.FILESYSTEM)
  filesystem = dict(filesystem) if isinstance(filesystem, dict) else {}
  # a recorded switch is the checkout's decision; only an unrecorded one is turned on here
  enabled = sandbox.get(SandboxKey.ENABLED)
  sandbox[SandboxKey.ENABLED] = enabled if isinstance(enabled, bool) else True

  # Decision: the unsandboxed retry is closed here, not left to Claude Code's default of open —
  # a command the sandbox blocks is otherwise retried with `dangerouslyDisableSandbox` and passes
  # the permission check a checkout that allows bare `Bash` grants, so `rm -rf` outside the write
  # scope fails once and succeeds on the second try; `dontAsk` has nothing to deny there. Same
  # treatment as `enabled`: only an unrecorded value is written.

  # the retry switch follows the confinement switch: a recorded value stays, an absent one closes
  unsandboxed = sandbox.get(SandboxKey.ALLOW_UNSANDBOXED)
  sandbox[SandboxKey.ALLOW_UNSANDBOXED] = unsandboxed if isinstance(unsandboxed, bool) else False

  # the allowlists are the only fields rebuilt wholesale, from what was recorded plus what is new;
  # a dead plugin-cache version pin is then dropped from the read side only — write is untouched,
  # and a pin still granted through write stays out of read despite the write-implies-read fold-in
  read_list = recorded_read + added_read
  removed_read = _dead_cache_entries(read_list)
  filesystem[SandboxKey.ALLOW_READ] = [ e for e in read_list if e not in removed_read ]
  filesystem[SandboxKey.ALLOW_WRITE] = recorded_write + added_write
  sandbox[SandboxKey.FILESYSTEM] = filesystem
  doc[SandboxKey.SANDBOX] = sandbox

  # a pass that changes nothing the file already records leaves it untouched
  changed = doc != _read(path)
  if changed:
    path.parent.mkdir(parents = True, exist_ok = True)
    # waiver: stdlib encoding idiom
    path.write_text(json.dumps(doc, indent = 2, ensure_ascii = False) + "\n", encoding = "utf-8")

  # what the caller reports: where the scope lives, what it grants now, and what this pass
  # added and pruned
  return {
    SandboxSyncKey.PATH: str(path),
    SandboxSyncKey.PRESENT: present,
    SandboxSyncKey.ENABLED: sandbox[SandboxKey.ENABLED],
    SandboxSyncKey.ALLOW_UNSANDBOXED: sandbox[SandboxKey.ALLOW_UNSANDBOXED],
    SandboxSyncKey.ADDED_READ: added_read,
    SandboxSyncKey.ADDED_WRITE: added_write,
    SandboxSyncKey.REMOVED_READ: removed_read,
    SandboxSyncKey.CHANGED: changed,
  }
