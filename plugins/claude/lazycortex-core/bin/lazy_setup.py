#!/usr/bin/env python3
"""
Discovery primitive for the `lazy-core.setup` install chain and its headless twin `lazy-core.autosetup`.

    lazy_setup.py discover <repo-root> [--home <dir>]
    lazy_setup.py guard <repo-root> [--ignore <prefix>]... [--snapshot <file>]
    lazy_setup.py snapshot <repo-root> [--snapshot <file>]
    lazy_setup.py verify <repo-root> [--snapshot <file>]
    lazy_setup.py plugin-root <plugin> [--repo <root>] [--home <dir>]

`discover` prints one JSON object describing the chain a repo needs, resolved against that repo alone:

- `dev_mode` — whether the repo authors plugins itself (`plugins/claude/*/.claude-plugin/plugin.json`);
  in dev-mode an enabled plugin's in-repo sources outrank its cached copy.
- `plugins` — every enabled plugin name mapped to the source root the chain reads it from.
- `skills` — the ordered chain: `dispatch` (`<plugin>:<ns>.<name>`), `phase`, `path`,
  `plugin`, `live_session` (the skill declares `requires_live_session: true`, so a headless
  executor skips it), and `last` (the skill declares `lazy_setup_last: true`). Order is pre-install,
  then per-plugin with `lazy-core.install` first, then post-install; alphabetical inside each band,
  except that the one skill of a band declaring `lazy_setup_last: true` closes it. Two such skills in
  one band are an error, never a tie.
- `skipped` — enabled plugins the machine has no sources for, with the reason.

Enablement is the union of `enabledPlugins` in `.claude/settings.json` and
`.claude/settings.local.json` under the repo; `installed_plugins.json` under the home directory
resolves an install path only, never enablement, and only from records made for this repo's main
checkout or for the whole user.

`guard` judges a dirty working tree before a headless run writes anything. Every dirty path is
sorted into one of three buckets: `conflicts` — under a root the install chain writes to (its write
scope: the fixed roots of `WRITE_SCOPE` plus the spec content root, `spec.vault_root` in the repo's
`.claude/lazy.settings.json`, `specs` when unset or unreadable; the report lists it as `write_scope`),
so running would overwrite the operator's work; `ignored` — under a prefix the
caller declared with `--ignore`, the operator's own work-in-progress the run must leave alone;
`outside` — anywhere else, none of the chain's business. The verdict is `conflict` when the
first bucket is non-empty, `clean` when nothing is dirty, and `dirty-allowed` otherwise — the
run may proceed, but only its own writes may reach the commit.
The guard also records a content fingerprint of every non-conflicting dirty path in a snapshot
file (default `<repo>/.runtime/lazy-setup-guard.json`) for `verify`.

`snapshot` records the same file for an interactive run that refuses nothing: every dirty path is
fingerprinted, under the chain's write scope or not, and the report names the file and the paths.

`verify` runs after the writes and judges only paths under the same write scope: it re-reads the tree,
reports as `touched` every dirty path there the snapshot did not know (the run's own writes, `new`
marking the untracked ones — the commit pathspec), and as `violations` every snapshot path there
whose fingerprint changed (the run wrote into the operator's work). Paths outside the write scope
that changed or appeared since the snapshot are the operator working alongside the run: they are
listed as `outside`, never committed and never blocking. The verdict is `ok` only when there are
no violations; a caller commits nothing otherwise.

`plugin-root` prints the one directory a plugin's sources are read from, resolved by the shared plugin
locator in the order every skill must follow and none may reorder: the `$LAZYCORTEX_PLUGIN_DIRS` entry for
the plugin, then the dev-vault sibling beside core's own plugin tree, then the current checkout's own
`plugins/claude/<plugin>/`, and last the install `installed_plugins.json` records for this repo's main
checkout or for the whole user. The plugin name may carry its `@<marketplace>` suffix. The verb exits 1 with
an `error:` line naming every searched stage when no stage resolves.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from frontmatter_parser import parse_frontmatter  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import plugin_locator  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# waiver: external Claude Code filesystem locations, not reusable domain keys
_SETTINGS_FILES = (".claude/settings.json", ".claude/settings.local.json")
# waiver: external Claude Code manifest field names, not internal keys
_ENABLED_PLUGINS = "enabledPlugins"
# waiver: repo layout of a plugin-authoring vault, not a reusable domain key
_DEV_ROOT, _DEV_MANIFEST = "plugins/claude", ".claude-plugin/plugin.json"
# waiver: plugin layout, not a reusable domain key
_SKILLS_DIR, _SKILL_FILE = "skills", "SKILL.md"
# waiver: setup-phases contract vocabulary (lazy-core.setup-phases-contract.md)
_PHASES = ("pre-install", "per-plugin", "post-install")
# waiver: setup-phases contract vocabulary (lazy-core.setup-phases-contract.md)
_PHASE_KEY = "lazy_setup_phase"
# waiver: setup-phases contract vocabulary (lazy-core.setup-phases-contract.md)
_LIVE_KEY = "requires_live_session"
# waiver: setup-phases contract vocabulary (lazy-core.setup-phases-contract.md)
_LAST_KEY = "lazy_setup_last"
# waiver: install-skill naming convention, not a reusable domain key
_INSTALL_SUFFIX = ".install"
# waiver: the one installer every chain runs first — it seeds what the others read
_FIRST_INSTALL = "lazy-core.install"
# waiver: report vocabulary shared with the skill and the agent
_NOT_INSTALLED = "plugin not installed for this repo or the user"
# waiver: JSON report keys read by the skill and the agent
_K_DISPATCH, _K_PHASE, _K_LAST = "dispatch", "phase", "last"

# Decision: the prefixes the install chain and the checkup repairs write to are fixed here, not
# derived per run — a headless agent needs the verdict BEFORE any installer runs, and every
# installer documents its writes under these roots (`.claude/` mirrors and settings, the
# plugin-authoring tree, Obsidian and git-hook bootstraps, run logs, daemon state, tracked
# migration stamps, the Python runner wrappers, `pyproject.toml` and guideline overlays, the
# git and lazy ignore/attribute files). The one root an operator can move, the spec content
# root, is read from the repo's settings on every call and added to these.

# waiver: repo-relative roots the install chain owns, not reusable domain keys
WRITE_SCOPE = (
    ".claude/", "plugins/claude/", ".obsidian/", ".githooks/", ".experts/", ".logs/", ".runtime/", ".state/",
    "cli/", "docs/guidelines/", ".gitignore", ".gitattributes", ".lazyignore", "pyproject.toml")
# waiver: the lazycortex settings file and the spec plugin's content-root key (lazycortex-specs `spec_paths`)
_LAZY_SETTINGS_REL, _SPEC_SECTION, _SPEC_ROOT_KEY = ".claude/lazy.settings.json", "spec", "vault_root"
# waiver: the spec plugin's default content root (lazycortex-specs `spec_paths.DEFAULT_VAULT_ROOT`)
_DEFAULT_SPEC_ROOT = "specs"
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
# waiver: argparse sub-command name, a surface string rather than a domain key
_VERB_SNAPSHOT = "snapshot"
# The directory holding core's own plugin tree; in a dev vault its other children are the sibling plugins
_SIBLING_BASE = Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> dict:
  """
  Load a JSON object from disk, treating an absent or unparseable file as empty.

  Args:
    path: File to read.

  Returns:
    The parsed object, or an empty dict when the file is missing, not UTF-8 text, or does not hold a JSON object.
  """
  try:
    # waiver: stdlib encoding idiom
    data = json.loads(path.read_text(encoding = "utf-8"))
  except (OSError, UnicodeDecodeError, json.JSONDecodeError):
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


def find_dev_plugins(repo: Path) -> dict[str, Path]:
  """
  Find the plugins a repo authors itself and map them to their in-repo source root.

  Args:
    repo: Repo root.

  Returns:
    Plugin directory name to `<repo>/plugins/claude/<name>`; empty when the repo authors no plugin.
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
      "plugin": plugin, "live_session": fm.get(_LIVE_KEY) is True, _K_LAST: fm.get(_LAST_KEY) is True,
  }


def _order_key(entry: dict) -> tuple:
  """
  Sort key placing phases in contract order, a phase's closer at its end, and `lazy-core.install` first
  among installers.

  Args:
    entry: A chain entry from `_skill_entry`.

  Returns:
    The sort tuple.
  """

  return (
      _PHASES.index(entry[_K_PHASE]),
      entry[_K_LAST],
      not (entry[_K_PHASE] == _PHASES[1] and entry[_K_DISPATCH].endswith(":" + _FIRST_INSTALL)),
      entry[_K_DISPATCH],
  )


def discover(repo: Path, home: Path | None = None, *, settings_root: Path | None = None) -> dict:
  """
  Build the install chain for a repo.

  Cached sources count only from installs made for the repo's main checkout or for the whole user.

  Guarantees:
    - `skills` is ordered by phase band, the band's `lazy_setup_last` skill closing it, with
      `lazy-core.install` first among installers and the dispatch string deciding the rest.
    - An enabled plugin's in-repo sources outrank its cached copy.

  Args:
    repo: Repo root the chain targets.
    home: Home directory whose plugin registry resolves cached sources; the default registry when omitted.
    settings_root: Directory whose `.claude/settings.json` and `.claude/settings.local.json` say which plugins are
      enabled; None for the repo root.

  Returns:
    The report described in the module docstring.

  Raises:
    ValueError: Two skills of one phase band declare `lazy_setup_last: true`.
  """

  # Contract:
  # The install chain in `skills` MUST be ordered by phase band, then the band's one `lazy_setup_last`
  # skill after every other skill of the band, then `lazy-core.install` ahead of every other installer,
  # then dispatch string; the setup skill relies on that order verbatim. A band never has two closers.

  # both source kinds, in-repo first
  dev = find_dev_plugins(repo)
  cached = plugin_locator.installed_plugin_roots(repo, home)

  # resolve every enabled plugin to one source root, reporting the ones not installed for this repo or the user
  roots: dict[str, Path] = {}
  skipped: list[dict] = []
  for plugin in sorted(read_enabled_plugins(settings_root or repo)):
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

  # a band has at most one closer; two would leave the end of the band undecided
  for phase in _PHASES:
    # guard: a second closer in one band is an authoring error the caller must see
    if sum(1 for entry in skills if entry[_K_PHASE] == phase and entry[_K_LAST]) > 1:
      raise ValueError(f"two skills claim {_LAST_KEY} in phase {phase}")

  # the report the skill and the agent read
  return {
      # waiver: JSON report keys read by the skill and the agent
      "dev_mode": bool(dev), "plugins": { name: str(root) for name, root in roots.items() },
      "skills": skills, "skipped": skipped,
  }


def read_dirty_paths(repo: Path) -> list[str]:
  """
  List the repo-relative paths git reports as modified, added, deleted, renamed, or untracked.

  Args:
    repo: Repo root.

  Returns:
    Sorted repo-relative paths, unquoted with undecodable bytes kept as surrogate escapes; a
    rename or copy, marked in either status column, contributes its new name only. Untracked
    files are listed one by one, never collapsed into their directory.
  """
  # NUL-separated porcelain: `XY path` per entry, a rename carrying the old name as a second field;
  # the listing is captured as bytes and decoded here, so no byte of a name is rewritten on the way
  fields = subprocess.run(
      [ "git", "-C", str(repo), "status", "--porcelain", "-z", "--untracked-files=all" ],
      check = True, capture_output = True,
  ).stdout.decode(
      "utf-8",
      # waiver: stdlib decode-error mode, not a domain constant
      errors = "surrogateescape",
  ).split("\0")
  paths: list[str] = []
  i = 0
  while i < len(fields) and fields[i]:
    entry = fields[i]
    paths.append(entry[3:])
    # a rename or copy status, in either column, is followed by the source path, which is not a dirty
    # path of its own
    i += 2 if set(entry[:2]) & set(_RENAME_STATUSES) else 1
  return sorted(set(paths))


def _is_under(path: str, prefixes: tuple[str, ...] | list[str]) -> bool:
  """
  Tell whether a repo-relative path falls under any of the prefixes.

  Args:
    path: Repo-relative path.
    prefixes: Directory prefixes ending in `/`, or exact file paths.

  Returns:
    True when the path equals a file prefix or starts with a directory prefix.
  """
  return any(path == p or path.startswith(p if p.endswith("/") else p + "/") for p in prefixes)


def read_write_scope(repo: Path) -> tuple[str, ...]:
  """
  List the roots the install chain writes to in a repo: the fixed ones and the repo's spec content root.

  Guarantees:
    - The result holds every fixed root of `WRITE_SCOPE` followed by exactly one spec content root, written as a
      `<root>/` prefix strictly below the repo.
    - The call never raises on an absent, unparseable or non-object settings file, nor on an unset or non-string
      value.
    - A value naming the repo root, an absolute path or one containing `..` yields the default `specs/`, so a repo
      whose spec plugin would refuse the value never widens the scope to the whole repo or beyond it.

  Args:
    repo: Repo root holding `.claude/lazy.settings.json`.

  Returns:
    `WRITE_SCOPE` followed by the spec content root as a `<root>/` prefix; the default `specs/` when the settings
    file is absent or unparseable, or the value is unset, not a string, or not a sub-directory of the repo.
  """

  # Contract:
  # The result MUST hold every fixed root of `WRITE_SCOPE` followed by exactly one spec content root, written as a
  # `<root>/` prefix strictly below the repo. The call NEVER raises on an absent, unparseable or non-object settings
  # file, nor on an unset or non-string value. A value naming the repo root, an absolute path or one containing `..`
  # yields the default `specs/`, so a repo whose spec plugin would refuse the value never widens the scope to the
  # whole repo or beyond it.

  # the configured root, when the settings name one
  spec = _read_json(repo / _LAZY_SETTINGS_REL).get(_SPEC_SECTION)
  value = spec.get(_SPEC_ROOT_KEY) if isinstance(spec, dict) else None
  parts = PurePosixPath(value).parts if isinstance(value, str) else ()

  # guard: the spec plugin refuses the repo root, an absolute path and `..`, so it never writes there
  if not parts or PurePosixPath(*parts).is_absolute() or ".." in parts:
    parts = (_DEFAULT_SPEC_ROOT,)

  # the fixed roots, then the spec root in the prefix form `_is_under` reads
  return (*WRITE_SCOPE, PurePosixPath(*parts).as_posix() + "/")


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
    - The snapshot file itself, left behind by an earlier run, is never a dirty path of any bucket.

  Args:
    repo: Repo root.
    ignore: Repo-relative prefixes the operator declared as their own work-in-progress.
    snapshot: File the snapshot is written to.

  Returns:
    The report described in the module docstring.
  """

  # sort every dirty path into its bucket, the ignore prefixes first
  scope = read_write_scope(repo)
  dirty = [ path for path in read_dirty_paths(repo) if path != _relate_snapshot(repo, snapshot) ]
  ignored = [ path for path in dirty if _is_under(path, ignore) ]
  conflicts = [ path for path in dirty if path not in ignored and _is_under(path, scope) ]
  outside = [ p for p in dirty if p not in ignored and p not in conflicts ]
  verdict = _V_CONFLICT if conflicts else (_V_CLEAN if not dirty else _V_ALLOWED)

  # the snapshot is what lets `verify` prove the run stayed out of the operator's files
  _write_snapshot(repo, ignored + outside, snapshot)

  # the report the agents read; the verdict alone decides whether the chain runs
  return {
      # waiver: JSON report keys read by the two headless agents
      "verdict": verdict, "dirty": dirty, "conflicts": conflicts, "ignored": ignored, "outside": outside,
      "write_scope": list(scope), "snapshot": str(snapshot),
  }


def save_snapshot(repo: Path, target: Path) -> dict:
  """
  Record every dirty path of the tree before a run, so `verify` can later tell the run's writes apart.

  Guarantees:
    - Every dirty path but the snapshot file itself is fingerprinted, under the chain's write scope or not, in the
      format `verify` reads, so no operator path is later read as the run's own write.

  Args:
    repo: Repo root.
    target: File the snapshot is written to.

  Returns:
    `{"snapshot": <file>, "dirty": [paths]}`.
  """

  # Contract:
  # Every dirty path but the snapshot file MUST be recorded with its fingerprint, whatever root it sits under.
  # `verify` reads a write-scope path the snapshot does not list as the run's own write, which the callers commit,
  # so a missing one would turn the operator's work into a commit; it lists an outside path only when it differs
  # from its recorded fingerprint, so a missing one would be reported as changed by the run.

  # every dirty path but the snapshot's own file, which the next write replaces
  dirty = [ path for path in read_dirty_paths(repo) if path != _relate_snapshot(repo, target) ]
  _write_snapshot(repo, dirty, target)

  # the report names the file the next skill is handed
  # waiver: JSON report keys read by the setup and migrate skills
  return { "snapshot": str(target), "dirty": dirty }


def _relate_snapshot(repo: Path, snapshot: Path) -> str:
  """
  Express the snapshot file as a repo-relative path, the form dirty paths are listed in.

  Args:
    repo: Repo root.
    snapshot: The snapshot file.

  Returns:
    The repo-relative POSIX path, or an empty string when the snapshot lives outside the repo.
  """
  # a snapshot outside the repo is never among its dirty paths
  try:
    return snapshot.resolve().relative_to(repo.resolve()).as_posix()
  except ValueError:
    return ""


def _write_snapshot(repo: Path, recorded: list[str], target: Path) -> None:
  """
  Write the snapshot file `verify` reads: the recorded paths and the fingerprint of each.

  Args:
    repo: Repo root.
    recorded: The repo-relative paths to record.
    target: File the snapshot is written to.
  """
  target.parent.mkdir(parents = True, exist_ok = True)
  payload = json.dumps({ _K_DIRTY: recorded, _K_FINGERPRINTS: { p: _fingerprint(repo, p) for p in recorded } },
                       indent = 2)
  # waiver: stdlib encoding idiom
  target.write_text(payload, encoding = "utf-8")


def verify(repo: Path, snapshot: Path) -> dict:
  """
  Compare the tree after a run with the guard's snapshot.

  Guarantees:
    - `touched` and `violations` hold only paths under the chain's write scope; a path outside it never
      enters the commit pathspec and never blocks the run.
    - `touched` holds only write-scope paths the snapshot did not list, so an operator's dirty file never
      enters the commit pathspec.
    - `violations` holds every recorded write-scope path whose fingerprint changed, including one that a
      revert made clean again.
    - `outside` holds the paths outside the write scope that changed or appeared since the snapshot; a
      recorded outside path whose fingerprint is unchanged is not listed.
    - The snapshot file itself is never listed anywhere, even when an older snapshot recorded it.

  Args:
    repo: Repo root.
    snapshot: File `guard` wrote.

  Returns:
    The report described in the module docstring.
  """

  # Contract:
  # `touched` and `violations` MUST hold only paths under the write scope. A path outside it, changed or new since
  # the snapshot, is listed in `outside` instead and never enters the commit pathspec or blocks the run.

  # a snapshot kept inside the repo shows up as dirty itself and never counts as a write, nor as a violation when an
  # older snapshot recorded it
  before = _read_json(snapshot)
  snapshot_rel = _relate_snapshot(repo, snapshot)
  recorded: list[str] = [ path for path in before.get(_K_DIRTY) or [] if path != snapshot_rel ]
  fingerprints: dict = before.get(_K_FINGERPRINTS) or {}

  # the run's own writes are the dirty paths the snapshot did not know that fall under the write scope, untracked
  # ones needing `add -N`; a new path outside the scope is the operator's and goes to `outside`
  scope = read_write_scope(repo)
  after = read_dirty_paths(repo)
  appeared = [ p for p in after if p not in recorded and p != snapshot_rel ]
  touched = [ p for p in appeared if _is_under(p, scope) ]
  tracked = set(subprocess.run(
      [ "git", "-C", str(repo), "--literal-pathspecs", "ls-files", "-z", "--", *touched ],
      check = True, capture_output = True,
  ).stdout.decode(
      "utf-8",
      # waiver: stdlib decode-error mode, not a domain constant
      errors = "surrogateescape",
  ).split("\0")) if touched else set()
  new = [ p for p in touched if p not in tracked ]

  # only a recorded path under the write scope can be the run's write into operator work; a change elsewhere is the
  # operator working alongside the run, reported beside the paths that appeared outside the scope
  changed = [ p for p in recorded if _fingerprint(repo, p) != fingerprints.get(p) ]
  violations = [ p for p in changed if _is_under(p, scope) ]
  outside = sorted({ *(p for p in changed if p not in violations), *(p for p in appeared if p not in touched) })

  # the report the agents read; any violation blocks the commit, an outside path never does
  return {
      # waiver: JSON report keys read by the two headless agents
      "verdict": _V_VIOLATED if violations else _V_OK, "touched": touched, "new": new, "violations": violations,
      "outside": outside,
  }


def plugin_root(plugin: str, repo: Path, home: Path | None = None) -> dict:
  """
  Resolve the directory a plugin's sources are read from.

  Guarantees:
    - Stages run in a fixed order: the exported plugin directories, then the dev-vault sibling, then the
      current checkout's own tree, then the install registry. The first hit wins, and no stage is reordered
      or skipped.
    - When no stage finds the plugin, the call raises `plugin_locator.PluginNotFoundError` naming every stage
      searched; it never returns None or a fallback.

  Args:
    plugin: Plugin name, with or without its `@<marketplace>` suffix.
    repo: Any directory of the repo the caller works in: its root, a subdirectory or a worktree.
    home: Home directory whose plugin registry resolves the installed copy; the default registry when omitted.

  Returns:
    `{"plugin", "root", "source"}` with `source` one of `env` / `sibling` / `repo` / `cache`.

  Raises:
    plugin_locator.PluginNotFoundError: No stage resolves the plugin; the message names every stage searched.
  """

  # Contract:
  # The stages run export, then dev-vault sibling, then the current checkout's tree, then the install
  # registry, and the first hit wins; every skill that reads a plugin's sources relies on this order,
  # so no caller may reorder or skip a stage.

  # Contract:
  # When no stage finds the plugin, the call MUST raise `plugin_locator.PluginNotFoundError` naming every
  # stage searched; it NEVER returns None or a fallback, because callers handle exactly that error.

  # the shared locator runs the stages; core's own plugin tree sits beside its dev-vault siblings
  root, source = plugin_locator.plugin_root(plugin, repo, sibling_base = _SIBLING_BASE, home = home)

  # the report the CLI prints and the skills read
  # waiver: JSON report keys read by the skills
  return { "plugin": plugin.split("@", 1)[0], "root": str(root), "source": source }


def main(argv: list[str] | None = None) -> int:
  """
  Parse the arguments and print the requested report: the chain, a guard verdict, a snapshot, a verify
  verdict, or a plugin root.

  Args:
    argv: Arguments without the program name; defaults to `sys.argv[1:]`.

  Returns:
    Process exit code: 0 on success, 1 when `plugin-root` resolves nothing or `discover` finds a phase with
    two closers, 2 on a usage error.
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
  snap = sub.add_parser(_VERB_SNAPSHOT, help = "record every dirty path before an interactive run")
  # waiver: argparse surface strings, not reusable domain keys
  snap.add_argument("repo", help = "repo root the chain targets")
  # waiver: argparse surface strings, not reusable domain keys
  snap.add_argument("--snapshot", default = None, help = f"snapshot file (default: <repo>/{_SNAPSHOT_REL})")
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
  root.add_argument("--repo", default = None, help = "directory inside the repo checked for authored sources "
                    "(default: $LAZY_REPO_ROOT, then the cwd)")
  # waiver: argparse surface strings, not reusable domain keys
  root.add_argument("--home", default = None, help = "home directory (default: the current user's)")
  args = parser.parse_args(argv)

  # the repo is the checkout the argument every verb but `plugin-root` requires sits in; that verb falls back to the
  # dispatcher's environment, then the cwd
  repo = plugin_locator.query_repo_root(getattr(args, "repo", None))

  # guard: a repo path that is not a directory is a usage error, not an empty chain
  if not repo.is_dir():
    print(f"error: not a directory: {repo}", file = sys.stderr)
    return 2

  # the home resolves the cached copies; only `discover` and `plugin-root` take it explicitly
  home = Path(args.home).resolve() if getattr(args, "home", None) else None

  # emit the requested report; `discover` and `plugin-root` resolve against the named home
  if args.verb == _VERB_DISCOVER:
    # guard: a band with two closers is a failure the caller must see, not a chain
    try:
      report = discover(repo, home, settings_root = plugin_locator.query_settings_root(args.repo))
    except ValueError as error:
      print(f"error: {error}", file = sys.stderr)
      return 1
  elif args.verb == _VERB_ROOT:
    # guard: an unresolved plugin is a failure the caller must see, not an empty report
    try:
      report = plugin_root(args.plugin, repo, home)
    except plugin_locator.PluginNotFoundError as error:
      print(f"error: {error}", file = sys.stderr)
      return 1
  else:
    target = Path(args.snapshot).resolve() if args.snapshot else repo / _SNAPSHOT_REL
    if args.verb == _VERB_GUARD:
      report = guard(repo, list(args.ignore), target)
    elif args.verb == _VERB_SNAPSHOT:
      report = save_snapshot(repo, target)
    else:
      report = verify(repo, target)
  print(json.dumps(report, indent = 2, ensure_ascii = True))
  return 0


if __name__ == "__main__":
  sys.exit(main())
