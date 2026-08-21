"""
Idempotent union into the repository-wide `tag_axes` — the `ensure-axes` CLI subcommand.

`lazycortex-wiki` has no Python writer of its own settings section — the only
existing writer is the `lazy-wiki.configure` wizard, an interactive LLM skill.
`wiki.install` needs a non-interactive, idempotent way to add the mandatory
`doc-kind` axis to the repository's vocabulary (and `lazy-spec.install` needs the same
for `product` / `category`) without overwriting an operator's own `tag_axes` entries. The write itself goes through `lazycortex-core`'s
`settings-get` / `settings-set` CLI (the §1c cross-plugin contract) rather than
touching `lazy.settings.json` directly, so this module never duplicates core's
atomic-write / version-stamping logic.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import json
import os
import subprocess
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


class _K:
  """
  String constants used by the `ensure-axes` primitive and its CLI wrapper.

  Attributes:
    WIKI_SECTION: Settings section name carrying the axis vocabulary.
    TAG_AXES: Section-level key holding the ordered list of classification axes.
    CORE_PLUGIN_NAME: Name of the `lazycortex-core` plugin/binary.
    BIN_SEGMENT: The `bin` path segment under a plugin root.
    ENV_PLUGIN_DIRS: Env var the daemon exports naming candidate plugin roots.
    SUB_SETTINGS_GET: Core CLI subcommand name for a section read.
    SUB_SETTINGS_SET: Core CLI subcommand name for a section write.
    ARG_CWD: Core CLI flag naming the repository root.
    STATUS: Result-dict key naming one scope's outcome.
    STATUS_ADDED: Outcome value when at least one axis was newly unioned in.
    STATUS_UNCHANGED: Outcome value when every requested axis was already declared.
    STATUS_ERROR: Outcome value when the named scope does not exist.
    ADDED: Result-dict key listing the axes newly added to the vocabulary.
    ADDED_FILTER_KEYS: Result-dict key listing the filter keys newly seeded on a scope.
    ADDED_EXCLUDES: Result-dict key listing the exclude globs newly appended to a scope.
    REASON: Result-dict key naming why an outcome is `error`.
    SCOPES: Key within the `wiki` section holding the per-scope config dict.
    EXCLUDE_PATHS: Per-scope key holding the scope's own exclude globs.
    FILTER: Per-scope key holding the on-the-fly node filter.
    FRONTMATTER: Filter sub-key holding the per-frontmatter-key predicates.
    FOLDER_NOTE: Filter sub-key selecting or rejecting folder notes.
    PLUGIN_CACHE: The Claude Code plugin-cache root, relative to the home directory.
    ERROR: Top-level result key used only for the malformed-`wiki.tag_axes` guard, in place of
      the normal status-keyed result shape.
  """

  WIKI_SECTION = "wiki"
  TAG_AXES = "tag_axes"
  CORE_PLUGIN_NAME = "lazycortex-core"
  BIN_SEGMENT = "bin"
  ENV_PLUGIN_DIRS = "LAZYCORTEX_PLUGIN_DIRS"
  SUB_SETTINGS_GET = "settings-get"
  SUB_SETTINGS_SET = "settings-set"
  ARG_CWD = "--cwd"
  STATUS = "status"
  STATUS_ADDED = "added"
  STATUS_UNCHANGED = "unchanged"
  STATUS_ERROR = "error"
  ADDED = "added_axes"
  ADDED_FILTER_KEYS = "added_filter_keys"
  ADDED_EXCLUDES = "added_excludes"
  REASON = "reason"
  SCOPES = "scopes"
  EXCLUDE_PATHS = "exclude_paths"
  FILTER = "filter"
  FRONTMATTER = "frontmatter"
  FOLDER_NOTE = "folder_note"
  PLUGIN_CACHE = ".claude/plugins/cache"
  ERROR = "error"


def _resolve_core_cli() -> Path:
  """
  Locate the `lazycortex-core` CLI binary this module dispatches settings reads/writes to.

  Three stages, in order: walk `$LAZYCORTEX_PLUGIN_DIRS` — set by the daemon for every
  subprocess routine it spawns, per the inter-plugin boundary contract's § 1c CLI-subprocess
  pattern; fall back to the dev-vault sibling layout (`claude/lazycortex-core/bin/` next to
  this plugin's own `claude/lazycortex-wiki/`), so the resolver also works from a plain shell
  or a test run inside this repo, where the daemon never exported the env var; finally glob the
  Claude Code plugin cache under the home directory for the newest installed version, since a
  plain interactive install-time session (no daemon, no dev-vault checkout) exports neither of
  the first two. Mirrors `mirror.py`'s `_resolve_core_cli` in this same plugin for the first two
  stages, and `coordinator_dispatch.py`'s own `_resolve_core_cli` in `lazycortex-review` for the
  cache-glob stage (same plain-string, not semver-aware, newest-first sort).

  Returns:
    Resolved binary usable as a subprocess argument.

  Raises:
    RuntimeError: When none of the three stages finds one.
  """
  env_dirs = os.environ.get(_K.ENV_PLUGIN_DIRS, "").split(os.pathsep)
  for dir_path in env_dirs:
    # guard: skip an empty segment from a leading/trailing/double path separator
    if not dir_path:
      continue
    cli = Path(dir_path) / _K.BIN_SEGMENT / _K.CORE_PLUGIN_NAME
    if cli.is_file():
      return cli

  # Domain(plugin.boundaries):
  # # Locating a neighbouring plugin's command line
  # A plugin never imports a neighbour's code and never knows the neighbour's layout on disk: it calls the
  # command the neighbour publishes as a separate process, and the exchange goes in JSON. The address of that
  # command is looked up across three sources in turn, from the most precise to the most general: the list of
  # plugin roots the runtime daemon hands to every process it spawns; the layout of the developer's working
  # vault, where plugins lie as neighbouring directories; the cache of installed plugins, from which the
  # freshest version is taken. No single source is mandatory on its own, but when none of them worked, the work
  # stops with an error listing everything that was searched: silently continuing without the neighbour is not
  # allowed.

  # dev-vault fallback — this file sits at claude/lazycortex-wiki/bin/axes.py, so core's own
  # bin/ is two levels up and back down into the sibling plugin tree
  sibling = Path(__file__).resolve().parents[2] / _K.CORE_PLUGIN_NAME / _K.BIN_SEGMENT / _K.CORE_PLUGIN_NAME
  if sibling.is_file():
    return sibling

  # plugin-cache fallback — a real consumer install where neither the daemon env nor the
  # dev-vault checkout applies; pick the newest installed version across every marketplace
  # registry directory under the cache root
  cache = Path.home() / _K.PLUGIN_CACHE
  if cache.is_dir():
    plugin_dirs = [
      registry / _K.CORE_PLUGIN_NAME
      for registry in cache.iterdir()
      if registry.is_dir() and (registry / _K.CORE_PLUGIN_NAME).is_dir()
    ]
    all_versions = [ v for pd in plugin_dirs for v in pd.iterdir() if v.is_dir() ]
    if all_versions:
      latest = sorted(all_versions, key = lambda v: v.name, reverse = True)[0]
      cli = latest / _K.BIN_SEGMENT / _K.CORE_PLUGIN_NAME
      if cli.is_file():
        return cli

  # none of the three stages found a binary — name what was searched so a misconfigured runner
  # is diagnosable
  searched = [ dir_path for dir_path in env_dirs if dir_path ] or [ "<unset>" ]
  raise RuntimeError(
    f"lazycortex-core CLI not resolvable: no {_K.BIN_SEGMENT}/{_K.CORE_PLUGIN_NAME} under any "
    f"directory named by ${_K.ENV_PLUGIN_DIRS} (searched: {', '.join(searched)}), no dev-vault "
    f"sibling at '{sibling}', and no version under '{cache}'."
  )


def _settings_get(repo: Path, section: str) -> dict:
  """
  Read one tracked settings section via `lazycortex-core settings-get`.

  Args:
    repo: Absolute repository root the section is read from.
    section: Top-level settings-section name.

  Returns:
    The section dict (the tracked layer — no local overlay), per `settings-get`'s contract.

  Raises:
    RuntimeError: When the `lazycortex-core` CLI cannot be resolved or exits non-zero.
  """
  cli = _resolve_core_cli()
  proc = subprocess.run(
    [ str(cli), _K.SUB_SETTINGS_GET, section, _K.ARG_CWD, str(repo) ],
    capture_output = True, text = True, check = False,
  )
  # guard: non-zero exit — surface stdout+stderr for diagnosis rather than a bare JSON parse error
  if proc.returncode != 0:
    raise RuntimeError(
      f"lazycortex-core {_K.SUB_SETTINGS_GET} exit={proc.returncode} "
      f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
  return json.loads(proc.stdout)


def _settings_set(repo: Path, section: str, value: dict) -> None:
  """
  Write one settings section via `lazycortex-core settings-set`.

  Args:
    repo: Absolute repository root the section is written to.
    section: Top-level settings-section name.
    value: Full section dict to persist (surrounding sections are untouched by core).

  Raises:
    RuntimeError: When the `lazycortex-core` CLI cannot be resolved or exits non-zero.
  """
  cli = _resolve_core_cli()
  proc = subprocess.run(
    [ str(cli), _K.SUB_SETTINGS_SET, section, _K.ARG_CWD, str(repo) ],
    input = json.dumps(value), capture_output = True, text = True, check = False,
  )
  # guard: non-zero exit — surface stdout+stderr for diagnosis
  if proc.returncode != 0:
    raise RuntimeError(
      f"lazycortex-core {_K.SUB_SETTINGS_SET} exit={proc.returncode} "
      f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )


def ensure_axes(repo: Path, axes: list[str]) -> dict:
  """
  Idempotently union `axes` into the repository-wide `wiki.tag_axes` list.

  Reads the `wiki` settings section (tracked layer only, per `settings-get`'s contract), unions
  the requested axis names into the section-level `tag_axes` list (order preserved, no
  duplicates, an operator's existing axes never dropped), and writes the section back only when
  the list actually changed.

  Guarantees:
    - Axes already declared are never dropped, reordered, or duplicated; missing ones are
      appended in the order requested.
    - The `wiki` section is written at most once per call, and only when `tag_axes` actually
      changed.
    - No scope is read or written; the vocabulary belongs to the repository, and a scope only
      ever narrows it.

  Args:
    repo: Absolute repository root.
    axes: Axis names to ensure are present; order defines the append order when more than one
      is missing.

  Returns:
    `{"status": "added", "added_axes": [...]}` when the list grew, or `{"status": "unchanged"}`
    when every requested axis was already declared. When `wiki.tag_axes` itself is not a list,
    the result is instead the single-key `{"error": "wiki.tag_axes must be a list"}`.
  """
  wiki = _settings_get(repo, _K.WIKI_SECTION)
  declared = wiki.get(_K.TAG_AXES)
  # guard: malformed `wiki.tag_axes` (e.g. an object) — report cleanly instead of unioning into it
  if declared is not None and not isinstance(declared, list):
    return { _K.ERROR: "wiki.tag_axes must be a list" }
  existing: list[str] = list(declared or [])

  # Domain(wiki.taxonomy):
  # # Replenishing the vault's axis vocabulary
  # The vocabulary of classification axes belongs to the operator, so automatic replenishment is always a union
  # and never a replacement: axes already declared keep their former order, the missing ones are appended at the
  # end in the order they were requested, and no repetitions arise. A request where every axis is already
  # declared changes nothing and rewrites nothing, so applying the same setting again is free.
  # The vocabulary is one for the whole vault: replenishing it makes the new axis available everywhere at once,
  # and no area of the vault can gain an axis the vault does not know.

  # Contract:
  # An operator's existing `tag_axes` entries are NEVER dropped or reordered; a requested axis
  # already present is never duplicated, and the missing ones are appended in the order requested.

  # a name repeated inside one request must not append twice — dedupe against what the
  # growing list will hold, not only against what it already held
  missing: list[str] = []
  for axis in axes:
    # guard: already declared, or already collected earlier in this same request
    if axis in existing or axis in missing:
      continue
    missing.append(axis)

  # Contract:
  # The `wiki` section is written at most once per call, and only when `tag_axes` actually
  # changed; a call that adds nothing MUST leave the settings untouched.

  # guard: every requested axis is already declared — no write at all
  if not missing:
    return { _K.STATUS: _K.STATUS_UNCHANGED }

  wiki[_K.TAG_AXES] = [ *existing, *missing ]
  _settings_set(repo, _K.WIKI_SECTION, wiki)
  return { _K.STATUS: _K.STATUS_ADDED, _K.ADDED: missing }


def ensure_scope_config(
  repo: Path,
  scope_id: str,
  *,
  filter_frontmatter: dict | None = None,
  exclude: list[str] | None = None,
) -> dict:
  """
  Idempotently seed filter predicates and exclude globs on one configured scope.

  Reads the `wiki` settings section, appends the requested exclude globs the scope does not
  already list, seeds each requested frontmatter predicate whose key the scope's filter does not
  already carry, and writes the section back only when something actually changed. An operator's
  existing predicate for the same key always wins — the seed never overwrites or merges into it.

  Guarantees:
    - An existing predicate for a requested filter key is never overwritten, merged into, or
      reordered; only absent keys are seeded.
    - An exclude glob already listed is never duplicated; missing ones are appended in the order
      requested.
    - A scope that is not configured is never created; the failure is reported as this call's
      outcome and nothing is written.
    - The `wiki` section is written at most once per call, and only when the scope actually
      changed.

  Args:
    repo: Absolute repository root.
    scope_id: Id of the scope to seed; must already exist under `wiki.scopes`.
    filter_frontmatter: Frontmatter predicates to seed, keyed by frontmatter key; `None` seeds
      none.
    exclude: Exclude globs to append when missing; `None` appends none.

  Returns:
    `{"status": "added", "added_filter_keys": [...], "added_excludes": [...]}` when anything
    changed, `{"status": "unchanged"}` when everything requested was already in place, or
    `{"status": "error", "reason": "no such scope"}` for an unknown `scope_id`. When
    `wiki.scopes` itself is not an object, the result is instead the single-key
    `{"error": "wiki.scopes must be an object"}`.
  """
  wiki = _settings_get(repo, _K.WIKI_SECTION)
  scopes = wiki.get(_K.SCOPES) or {}
  # guard: malformed `wiki.scopes` (e.g. a list) — report cleanly instead of crashing below
  if not isinstance(scopes, dict):
    return { _K.ERROR: "wiki.scopes must be an object" }
  cfg = scopes.get(scope_id)
  # guard: the named scope does not exist — seeding must never create one
  if not isinstance(cfg, dict):
    return { _K.STATUS: _K.STATUS_ERROR, _K.REASON: "no such scope" }

  # Domain(wiki.scope):
  # # Seeding an area's defaults without owning the area
  # A neighbouring subsystem may know what an area of the vault should skip by default — which documents are
  # unfinished, which files are working papers — without owning the area's configuration. Such knowledge lands as
  # a seed: exclusion patterns are appended only when absent, and a filter predicate is planted only for a key the
  # area does not already judge. Whatever the operator has written for the same key stays exactly as written, so
  # repeating the seed is free and an operator's tightening or loosening of it survives every re-run.

  # Contract:
  # An existing filter predicate for a requested key is NEVER overwritten or merged into;
  # only keys the scope's filter does not carry are seeded.

  # collect the exclude globs the scope does not list yet, in request order
  changed_excludes: list[str] = []
  existing_excludes: list[str] = list(cfg.get(_K.EXCLUDE_PATHS) or [])
  for glob in exclude or []:
    # guard: already listed, or repeated inside this same request
    if glob in existing_excludes or glob in changed_excludes:
      continue
    changed_excludes.append(glob)

  # the filter block is created on first need; folder notes stay rejected per the structural
  # default every scope gets at configure time
  flt_raw = cfg.get(_K.FILTER)
  flt: dict = flt_raw if isinstance(flt_raw, dict) else {}
  fm_raw = flt.get(_K.FRONTMATTER)
  frontmatter: dict = fm_raw if isinstance(fm_raw, dict) else {}
  changed_keys: list[str] = []
  for key, predicate in (filter_frontmatter or {}).items():
    # guard: the operator already judges this key — their predicate wins
    if key in frontmatter:
      continue
    frontmatter = { **frontmatter, key: predicate }
    changed_keys.append(key)

  # Contract:
  # The `wiki` section is written at most once per call, and only when the scope actually
  # changed; a call that seeds nothing MUST leave the settings untouched.

  # guard: everything requested was already in place — no write at all
  if not changed_excludes and not changed_keys:
    return { _K.STATUS: _K.STATUS_UNCHANGED }

  if changed_excludes:
    cfg[_K.EXCLUDE_PATHS] = [ *existing_excludes, *changed_excludes ]
  if changed_keys:
    new_filter = { **flt, _K.FRONTMATTER: frontmatter }
    new_filter.setdefault(_K.FOLDER_NOTE, False)
    cfg[_K.FILTER] = new_filter
  scopes[scope_id] = cfg
  wiki[_K.SCOPES] = scopes
  _settings_set(repo, _K.WIKI_SECTION, wiki)
  return {
    _K.STATUS: _K.STATUS_ADDED,
    _K.ADDED_FILTER_KEYS: changed_keys,
    _K.ADDED_EXCLUDES: changed_excludes,
  }
