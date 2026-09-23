#!/usr/bin/env python3
"""
Discovery primitive for the `lazy-core.setup` install chain and its headless twin `lazy-core.autosetup`.

    lazy_setup.py discover <repo-root> [--home <dir>]
    lazy_setup.py guard <repo-root> [--ignore <prefix>]... [--snapshot <file>]
    lazy_setup.py verify <repo-root> [--snapshot <file>]
    lazy_setup.py plugin-root <plugin> [--repo <root>] [--home <dir>]

`discover` prints one JSON object describing the chain a repo needs, resolved against that repo alone:

- `dev_mode` — whether the repo authors plugins itself (`claude/*/.claude-plugin/plugin.json`);
  in dev-mode an enabled plugin's in-repo sources outrank its cached copy.
- `plugins` — every enabled plugin name mapped to the source root the chain reads it from.
- `skills` — the ordered chain: `dispatch` (`<plugin>:<ns>.<name>`), `phase`, `path`,
  `plugin`, and `live_session` (the skill declares `requires_live_session: true`, so a headless
  executor skips it). Order is pre-install, then per-plugin with `lazy-core.install` first,
  then post-install; alphabetical inside each band.
- `skipped` — enabled plugins the machine has no sources for, with the reason.

Enablement is the union of `enabledPlugins` in `.claude/settings.json` and
`.claude/settings.local.json` under the repo; `installed_plugins.json` under the home directory
resolves an install path only, never enablement.

`guard` judges a dirty working tree before a headless run writes anything. Every dirty path is
sorted into one of three buckets: `conflicts` — under a prefix the install chain writes to
(`WRITE_SCOPE`), so running would overwrite the operator's work; `ignored` — under a prefix the
caller declared with `--ignore`, the operator's own work-in-progress the run must leave alone;
`outside` — anywhere else, none of the chain's business. The verdict is `conflict` when the
first bucket is non-empty, `clean` when nothing is dirty, and `dirty-allowed` otherwise — the
run may proceed, but only its own writes may reach the commit.
The guard also records a content fingerprint of every non-conflicting dirty path in a snapshot
file (default `<repo>/.runtime/lazy-setup-guard.json`) for `verify`.

`verify` runs after the writes: it re-reads the tree, reports as `touched` every dirty path the
snapshot did not know (the run's own writes, `new` marking the untracked ones — the commit
pathspec), and as `violations` every snapshot path whose fingerprint changed (the run wrote
into the operator's work). The verdict is `ok` only when there are no violations; a caller
commits nothing otherwise.

`plugin-root` prints the one directory a plugin's sources are read from, resolved in the
order every skill must follow and none may reorder: the repo's own `claude/<plugin>/` when the
repo authors the plugin (the sources in the tree outrank the cached copy, which lags them until
the next publish), then the daemon-exported `$LAZYCORTEX_PLUGIN_DIRS` entry for the plugin,
then the newest cached install. The plugin name may carry its `@<marketplace>` suffix. Exit
status 1 and an `error:` line when no stage resolves.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from frontmatter_parser import parse_frontmatter  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Decision: the skill and the agent call this primitive instead of listing the plugin cache
# themselves — an interactive session may carry no enumeration tool at all, and a listing over
# the whole cache is exactly what a consumer's permission layer may refuse mid-run.

# waiver: external Claude Code filesystem locations, not reusable domain keys
_INSTALLED_PLUGINS_REL = ".claude/plugins/installed_plugins.json"
# waiver: external Claude Code filesystem locations, not reusable domain keys
_SETTINGS_FILES = (".claude/settings.json", ".claude/settings.local.json")
# waiver: external Claude Code manifest field names, not internal keys
_ENABLED_PLUGINS = "enabledPlugins"
# waiver: external Claude Code manifest field names, not internal keys
_INSTALL_PATH = "installPath"
# waiver: external Claude Code manifest field name, not an internal key
_VERSION = "version"
# waiver: repo layout of a plugin-authoring vault, not a reusable domain key
_DEV_ROOT, _DEV_MANIFEST = "claude", ".claude-plugin/plugin.json"
# waiver: plugin layout, not a reusable domain key
_SKILLS_DIR, _SKILL_FILE = "skills", "SKILL.md"
# waiver: setup-phases contract vocabulary (lazy-core.setup-phases-contract.md)
_PHASES = ("pre-install", "per-plugin", "post-install")
# waiver: setup-phases contract vocabulary (lazy-core.setup-phases-contract.md)
_PHASE_KEY = "lazy_setup_phase"
# waiver: setup-phases contract vocabulary (lazy-core.setup-phases-contract.md)
_LIVE_KEY = "requires_live_session"
# waiver: install-skill naming convention, not a reusable domain key
_INSTALL_SUFFIX = ".install"
# waiver: the one installer every chain runs first — it seeds what the others read
_FIRST_INSTALL = "lazy-core.install"
# waiver: report vocabulary shared with the skill and the agent
_NOT_INSTALLED = "plugin not installed on this machine"
# waiver: JSON report keys read by the skill and the agent
_K_DISPATCH, _K_PHASE = "dispatch", "phase"

# Decision: the prefixes the install chain and the checkup repairs write to are fixed here, not
# derived per run — a headless agent needs the verdict BEFORE any installer runs, and every
# installer documents its writes under these roots (`.claude/` mirrors and settings, the
# plugin-authoring tree, Obsidian and git-hook bootstraps, run logs, daemon state, `.gitignore`).

# waiver: repo-relative roots the install chain owns, not reusable domain keys
WRITE_SCOPE = (".claude/", "claude/", ".obsidian/", ".githooks/", ".experts/", ".logs/", ".runtime/", ".gitignore")
# waiver: machine-local daemon state dir, gitignored by lazy-core.install
_SNAPSHOT_REL = ".runtime/lazy-setup-guard.json"
# waiver: guard verdict vocabulary shared with the two headless agents
_V_CLEAN, _V_ALLOWED, _V_CONFLICT, _V_OK, _V_VIOLATED = "clean", "dirty-allowed", "conflict", "ok", "violated"
# waiver: fingerprint markers for a dirty path that is not a regular file
_FP_ABSENT, _FP_DIR = "absent", "dir"
# waiver: JSON keys of the snapshot file, private to guard/verify
_K_DIRTY, _K_FINGERPRINTS = "dirty", "fingerprints"
# waiver: git porcelain status letters whose entry carries a second (source) path
_RENAME_STATUSES = "RC"
# waiver: argparse sub-command names, surface strings rather than domain keys
_VERB_DISCOVER, _VERB_GUARD, _VERB_VERIFY, _VERB_ROOT = "discover", "guard", "verify", "plugin-root"
# waiver: the daemon's plugin-dir export (dev.plugin-boundaries § 1c), an environment name
_PLUGIN_DIRS_ENV = "LAZYCORTEX_PLUGIN_DIRS"
# waiver: provenance words of a resolved plugin root, read by the skills' reports
_SRC_REPO, _SRC_ENV, _SRC_CACHE = "repo", "env", "cache"


def _read_json(path: Path) -> dict:
  """
  Load a JSON object from disk, treating an absent or unparseable file as empty.

  Args:
    path: File to read.

  Returns:
    The parsed object, or an empty dict when the file is missing or not valid JSON.
  """
  try:
    # waiver: stdlib encoding idiom
    data = json.loads(path.read_text(encoding = "utf-8"))
  except (OSError, json.JSONDecodeError):
    return {}
  return data if isinstance(data, dict) else {}


def read_enabled_plugins(repo: Path) -> set[str]:
  """
  Read the plugin names a repo enables from its two settings files.

  Args:
    repo: Repo root holding `.claude/settings.json` and `.claude/settings.local.json`.

  Returns:
    Names (marketplace suffix stripped) whose merged `enabledPlugins` entry is true.
  """

  # Domain(install.reconciliation):
  # # Enablement is the repo's own word, never the machine's
  # A plugin applies to a repo only when that repo's tracked or local settings switch it on; the
  # later file overrides the earlier one key by key. The machine-wide install registry spans
  # every project on the host, so it can say where a plugin's sources live but never whether
  # this repo wants them. In a repo that authors plugins, its own sources outrank a cached copy.

  # merge the tracked and the local map, the local one overriding key by key
  merged: dict = {}
  for rel in _SETTINGS_FILES:
    merged.update(_read_json(repo / rel).get(_ENABLED_PLUGINS) or {})

  # keep the switched-on keys, stripped of their `@<marketplace>` suffix
  return { key.split("@", 1)[0] for key, enabled in merged.items() if enabled }


def read_install_paths(home: Path) -> dict[str, Path]:
  """
  Read the machine's plugin registry into a map of plugin name to cached source root.

  Args:
    home: Home directory holding `.claude/plugins/installed_plugins.json`.

  Returns:
    Plugin name to the `installPath` of its highest recorded version; plugins with no record are absent.
  """
  # the registry nests its map under `plugins` in newer files and is the map itself in older ones
  data = _read_json(home / _INSTALLED_PLUGINS_REL)
  # waiver: external Claude Code manifest field name, not an internal key
  plugins = data.get("plugins", data)

  # the highest recorded version wins — records differ by version, each naming its own cache dir,
  # and the registry keeps a stale record for every project that last installed an older one
  out: dict[str, Path] = {}
  for key, entries in plugins.items():
    records = [ rec for rec in entries or [] if isinstance(rec, dict) and rec.get(_INSTALL_PATH) ]
    if records:
      out[key.split("@", 1)[0]] = Path(str(max(records, key = _version_key)[_INSTALL_PATH]))
  return out


def _version_key(record: dict) -> tuple[int, ...]:
  """
  Order a registry record by its recorded version.

  Args:
    record: One `installed_plugins.json` record.

  Returns:
    The dotted version as integers; a missing or non-numeric segment counts as 0.
  """
  return tuple(int(part) if part.isdigit() else 0 for part in str(record.get(_VERSION, "")).split("."))


def find_dev_plugins(repo: Path) -> dict[str, Path]:
  """
  Find the plugins a repo authors itself and map them to their in-repo source root.

  Args:
    repo: Repo root.

  Returns:
    Plugin directory name to `<repo>/claude/<name>`; empty when the repo authors no plugin.
  """
  return { sub.name: sub for sub in _list_subdirs(repo / _DEV_ROOT) if (sub / _DEV_MANIFEST).is_file() }


def _list_subdirs(base: Path) -> list[Path]:
  """
  List a directory's immediate subdirectories in name order.

  Args:
    base: Directory to list.

  Returns:
    Its subdirectories sorted by name; empty when `base` is not a directory.
  """
  # guard: an absent base has no children to list
  if not base.is_dir():
    return []
  return sorted(child for child in (base / name for name in os.listdir(base)) if child.is_dir())


def _skill_entry(plugin: str, skill_md: Path) -> dict | None:
  """
  Describe one `SKILL.md` as a chain entry, or nothing when it does not participate.

  Args:
    plugin: Plugin the skill ships in.
    skill_md: Path to the skill's `SKILL.md`.

  Returns:
    The chain entry, or `None` when the skill neither declares a phase nor is an installer.
  """
  # a declared phase wins; otherwise the `*.install` naming convention makes it an installer
  name = skill_md.parent.name
  # waiver: stdlib encoding idiom
  fm = parse_frontmatter(skill_md.read_text(encoding = "utf-8"))
  phase = fm.get(_PHASE_KEY)
  if phase not in _PHASES:
    phase = _PHASES[1] if name.endswith(_INSTALL_SUFFIX) else None

  # guard: a skill with neither a phase nor the installer name is not part of the chain
  if phase is None:
    return None

  # the chain entry the skill and the agent read
  return {
      # waiver: JSON report keys read by the skill and the agent
      _K_DISPATCH: f"{plugin}:{name}", _K_PHASE: phase, "path": str(skill_md),
      "plugin": plugin, "live_session": fm.get(_LIVE_KEY) is True,
  }


def _order_key(entry: dict) -> tuple:
  """
  Sort key placing phases in contract order and `lazy-core.install` first among installers.

  Args:
    entry: A chain entry from `_skill_entry`.

  Returns:
    The sort tuple.
  """

  # Contract:
  # The chain order is phase band, then `lazy-core.install` ahead of every other installer, then
  # dispatch string; callers and the setup skill rely on it verbatim.

  return (
      _PHASES.index(entry[_K_PHASE]),
      not (entry[_K_PHASE] == _PHASES[1] and entry[_K_DISPATCH].endswith(":" + _FIRST_INSTALL)),
      entry[_K_DISPATCH],
  )


def discover(repo: Path, home: Path) -> dict:
  """
  Build the install chain for a repo.

  Guarantees:
    - `skills` is ordered by phase band, with `lazy-core.install` first among installers and
      the dispatch string deciding the rest.
    - An enabled plugin's in-repo sources outrank its cached copy.

  Args:
    repo: Repo root the chain targets.
    home: Home directory whose plugin registry resolves cached sources.

  Returns:
    The report described in the module docstring.
  """
  # both source kinds, in-repo first
  dev = find_dev_plugins(repo)
  cached = read_install_paths(home)

  # resolve every enabled plugin to one source root, reporting the ones this machine lacks
  roots: dict[str, Path] = {}
  skipped: list[dict] = []
  for plugin in sorted(read_enabled_plugins(repo)):
    root = dev.get(plugin) or cached.get(plugin)
    if root is None:
      # waiver: JSON report keys read by the skill and the agent
      skipped.append({ "plugin": plugin, "reason": _NOT_INSTALLED })
      continue
    roots[plugin] = root

  # collect the participating skills of every resolved plugin, then order the chain
  skills = [
      entry for plugin, root in roots.items()
      for skill_dir in _list_subdirs(root / _SKILLS_DIR) if (skill_dir / _SKILL_FILE).is_file()
      if (entry := _skill_entry(plugin, skill_dir / _SKILL_FILE)) is not None
  ]
  skills.sort(key = _order_key)

  # the report the skill and the agent read
  return {
      # waiver: JSON report keys read by the skill and the agent
      "dev_mode": bool(dev), "plugins": { name: str(root) for name, root in roots.items() },
      "skills": skills, "skipped": skipped,
  }


def dirty_paths(repo: Path) -> list[str]:
  """
  List the repo-relative paths git reports as modified, added, deleted, renamed, or untracked.

  Args:
    repo: Repo root.

  Returns:
    Sorted repo-relative paths; a rename contributes its new name only. Untracked files are
    listed one by one, never collapsed into their directory.
  """
  # NUL-separated porcelain: `XY path` per entry, a rename carrying the old name as a second field
  out = subprocess.run(
      [ "git", "-C", str(repo), "status", "--porcelain", "-z", "--untracked-files=all" ],
      check = True, capture_output = True, text = True,
  ).stdout
  fields = out.split("\0")
  paths: list[str] = []
  i = 0
  while i < len(fields) and fields[i]:
    entry = fields[i]
    paths.append(entry[3:])
    # a rename or copy status is followed by the source path, which is not a dirty path of its own
    i += 2 if entry[0] in _RENAME_STATUSES else 1
  return sorted(set(paths))


def _under(path: str, prefixes: tuple[str, ...] | list[str]) -> bool:
  """
  Tell whether a repo-relative path falls under any of the prefixes.

  Args:
    path: Repo-relative path.
    prefixes: Directory prefixes ending in `/`, or exact file paths.

  Returns:
    True when the path equals a file prefix or starts with a directory prefix.
  """
  return any(path == p or path.startswith(p if p.endswith("/") else p + "/") for p in prefixes)


def _fingerprint(repo: Path, rel: str) -> str:
  """
  Fingerprint the current content of one repo-relative path.

  Args:
    repo: Repo root.
    rel: Repo-relative path.

  Returns:
    The SHA-256 of a regular file's bytes, `dir` for a directory, `absent` when nothing is there.
  """
  target = repo / rel
  if target.is_dir():
    return _FP_DIR
  if not target.is_file():
    return _FP_ABSENT
  return hashlib.sha256(target.read_bytes()).hexdigest()


def guard(repo: Path, ignore: list[str], snapshot: Path) -> dict:
  """
  Judge the dirty tree against the chain's write scope and record the snapshot `verify` needs.

  Guarantees:
    - A dirty path under an `--ignore` prefix is never a conflict, whatever else covers it.
    - The snapshot fingerprints exactly the `ignored` and `outside` paths; conflicts are not
      recorded because a `conflict` verdict means nothing runs.

  Args:
    repo: Repo root.
    ignore: Repo-relative prefixes the operator declared as their own work-in-progress.
    snapshot: File the snapshot is written to.

  Returns:
    The report described in the module docstring.
  """
  dirty = dirty_paths(repo)
  ignored = [ p for p in dirty if _under(p, ignore) ]
  conflicts = [ p for p in dirty if p not in ignored and _under(p, WRITE_SCOPE) ]
  outside = [ p for p in dirty if p not in ignored and p not in conflicts ]
  verdict = _V_CONFLICT if conflicts else (_V_CLEAN if not dirty else _V_ALLOWED)

  # the snapshot is what lets `verify` prove the run stayed out of the operator's files
  recorded = ignored + outside
  snapshot.parent.mkdir(parents = True, exist_ok = True)
  payload = json.dumps({ _K_DIRTY: recorded, _K_FINGERPRINTS: { p: _fingerprint(repo, p) for p in recorded } },
                       indent = 2)
  # waiver: stdlib encoding idiom
  snapshot.write_text(payload, encoding = "utf-8")

  # the report the agents read; the verdict alone decides whether the chain runs
  return {
      # waiver: JSON report keys read by the two headless agents
      "verdict": verdict, "dirty": dirty, "conflicts": conflicts, "ignored": ignored, "outside": outside,
      "write_scope": list(WRITE_SCOPE), "snapshot": str(snapshot),
  }


def verify(repo: Path, snapshot: Path) -> dict:
  """
  Compare the tree after a run with the guard's snapshot.

  Guarantees:
    - `touched` holds only paths the snapshot did not list, so an operator's dirty file never
      enters the commit pathspec, and the snapshot file itself never does either.
    - `violations` holds every recorded path whose fingerprint changed, including one that a
      revert made clean again.

  Args:
    repo: Repo root.
    snapshot: File `guard` wrote.

  Returns:
    The report described in the module docstring.
  """
  before = _read_json(snapshot)
  recorded: list[str] = list(before.get(_K_DIRTY) or [])
  fingerprints: dict = before.get(_K_FINGERPRINTS) or {}

  # a snapshot kept inside the repo shows up as dirty itself and must never count as a write
  try:
    snapshot_rel = str(snapshot.resolve().relative_to(repo.resolve()))
  except ValueError:
    snapshot_rel = ""

  # the run's own writes are the dirty paths the snapshot did not know; untracked ones need `add -N`
  after = dirty_paths(repo)
  touched = [ p for p in after if p not in recorded and p != snapshot_rel ]
  tracked = set(subprocess.run(
      [ "git", "-C", str(repo), "ls-files", "-z", "--", *touched ],
      check = True, capture_output = True, text = True,
  ).stdout.split("\0")) if touched else set()
  new = [ p for p in touched if p not in tracked ]
  violations = [ p for p in recorded if _fingerprint(repo, p) != fingerprints.get(p) ]

  # the report the agents read; any violation blocks the commit
  return {
      # waiver: JSON report keys read by the two headless agents
      "verdict": _V_VIOLATED if violations else _V_OK, "touched": touched, "new": new, "violations": violations,
  }


def plugin_root(plugin: str, repo: Path, home: Path) -> dict | None:
  """
  Resolve the directory a plugin's sources are read from.

  Guarantees:
    - The repo's own `claude/<plugin>/` wins whenever the repo authors the plugin.
    - Otherwise a `$LAZYCORTEX_PLUGIN_DIRS` entry named after the plugin wins over the cache.

  Args:
    plugin: Plugin name, with or without its `@<marketplace>` suffix.
    repo: Repo root whose authored plugins are checked first.
    home: Home directory whose plugin registry resolves the cached copy.

  Returns:
    `{"plugin", "root", "source"}` with `source` one of `repo` / `env` / `cache`, or None when no
    stage resolves.
  """
  name = plugin.split("@", 1)[0]

  # Contract:
  # The stages run repo, then export, then cache, and the first hit wins; every skill that reads
  # a plugin's sources relies on this order, so no caller may reorder or skip a stage.

  # stage one: the authoring repo's own tree
  dev = find_dev_plugins(repo).get(name)
  if dev is not None:
    return _root_report(name, dev, _SRC_REPO)

  # stage two: the daemon's export, matched on the directory name
  raw = os.environ.get(_PLUGIN_DIRS_ENV, "")
  for entry in filter(None, raw.split(os.pathsep)):
    candidate = Path(entry)
    if candidate.name == name and (candidate / _DEV_MANIFEST).is_file():
      return _root_report(name, candidate, _SRC_ENV)

  # stage three: the newest cached install
  cached = read_install_paths(home).get(name)
  return _root_report(name, cached, _SRC_CACHE) if cached is not None else None


def _root_report(name: str, root: Path, source: str) -> dict:
  """
  Shape one plugin-root resolution as the report the CLI prints.

  Args:
    name: Bare plugin name.
    root: Resolved source directory.
    source: Which stage resolved it.

  Returns:
    The report object.
  """
  # waiver: JSON report keys read by the skills
  return { "plugin": name, "root": str(root.resolve()), "source": source }


def main(argv: list[str] | None = None) -> int:
  """
  Parse the arguments and print the requested report: the chain, a guard verdict, a verify
  verdict, or a plugin root.

  Args:
    argv: Arguments without the program name; defaults to `sys.argv[1:]`.

  Returns:
    Process exit code: 0 on success, 1 when `plugin-root` resolves nothing, 2 on a usage error.
  """
  # waiver: argparse surface strings, not reusable domain keys
  parser = argparse.ArgumentParser(prog = "lazy_setup.py")
  # waiver: argparse surface strings, not reusable domain keys
  sub = parser.add_subparsers(dest = "verb", required = True)
  # waiver: argparse surface strings, not reusable domain keys
  disc = sub.add_parser(_VERB_DISCOVER, help = "print the install chain for a repo as JSON")
  # waiver: argparse surface strings, not reusable domain keys
  disc.add_argument("repo", help = "repo root the chain targets")
  # waiver: argparse surface strings, not reusable domain keys
  disc.add_argument("--home", default = None, help = "home directory (default: the current user's)")
  # waiver: argparse surface strings, not reusable domain keys
  grd = sub.add_parser(_VERB_GUARD, help = "judge a dirty tree against the chain's write scope, record a snapshot")
  # waiver: argparse surface strings, not reusable domain keys
  grd.add_argument("repo", help = "repo root the chain targets")
  # waiver: argparse surface strings, not reusable domain keys
  grd.add_argument("--ignore", action = "append", default = [],
                   help = "repo-relative prefix of operator work-in-progress the run leaves alone (repeatable)")
  # waiver: argparse surface strings, not reusable domain keys
  grd.add_argument("--snapshot", default = None, help = f"snapshot file (default: <repo>/{_SNAPSHOT_REL})")
  # waiver: argparse surface strings, not reusable domain keys
  ver = sub.add_parser(_VERB_VERIFY, help = "compare the tree after a run with the guard's snapshot")
  # waiver: argparse surface strings, not reusable domain keys
  ver.add_argument("repo", help = "repo root the chain targets")
  # waiver: argparse surface strings, not reusable domain keys
  ver.add_argument("--snapshot", default = None, help = f"snapshot file (default: <repo>/{_SNAPSHOT_REL})")
  # waiver: argparse surface strings, not reusable domain keys
  root = sub.add_parser(_VERB_ROOT, help = "print the directory a plugin's sources are read from")
  # waiver: argparse surface strings, not reusable domain keys
  root.add_argument("plugin", help = "plugin name, with or without its @<marketplace> suffix")
  # waiver: argparse surface strings, not reusable domain keys
  root.add_argument("--repo", default = None, help = "repo root checked for authored sources (default: the cwd)")
  # waiver: argparse surface strings, not reusable domain keys
  root.add_argument("--home", default = None, help = "home directory (default: the current user's)")
  args = parser.parse_args(argv)

  # the repo comes from the argument every verb but `plugin-root` requires; that verb falls back to the cwd
  repo = Path(args.repo).resolve() if getattr(args, "repo", None) else Path.cwd().resolve()

  # guard: a repo path that is not a directory is a usage error, not an empty chain
  if not repo.is_dir():
    print(f"error: not a directory: {repo}", file = sys.stderr)
    return 2

  # the home resolves the cached copies; only `discover` and `plugin-root` take it explicitly
  home = Path(args.home).resolve() if getattr(args, "home", None) else Path.home()

  # emit the requested report; `discover` and `plugin-root` resolve against the named home
  if args.verb == _VERB_DISCOVER:
    report: dict | None = discover(repo, home)
  elif args.verb == _VERB_ROOT:
    report = plugin_root(args.plugin, repo, home)
    # guard: an unresolved plugin is a failure the caller must see, not an empty report
    if report is None:
      print(f"error: {args.plugin} not installed: no authored, exported, or cached sources", file = sys.stderr)
      return 1
  else:
    snapshot = Path(args.snapshot).resolve() if args.snapshot else repo / _SNAPSHOT_REL
    report = guard(repo, list(args.ignore), snapshot) if args.verb == _VERB_GUARD else verify(repo, snapshot)
  print(json.dumps(report, indent = 2, ensure_ascii = False))
  return 0


if __name__ == "__main__":
  sys.exit(main())
