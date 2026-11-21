"""
Access to the `wiki` settings section and its idempotent, non-interactive seeding — the `ensure-axes` CLI subcommand.

Gives the wiki CLI and sibling modules one door to the `wiki` section of the repository settings: locating the
`lazycortex-core` CLI, reading a section, and adding classification axes and per-scope defaults without ever
overwriting an operator's own entries. Reads and writes go through core's settings CLI rather than touching
`lazy.settings.json` directly, so core stays the only owner of how settings are persisted.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import ClassVar, Final, Literal


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import plugin_registry as _plugin_registry  # noqa: E402  # pylint: disable=import-error,wrong-import-position


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
    ARG_SCOPE: Core CLI flag naming the settings layer a read targets.
    STATUS: Result-dict key naming one scope's outcome.
    STATUS_ADDED: Outcome value when at least one axis was newly unioned in.
    STATUS_UNCHANGED: Outcome value when every requested axis was already declared.
    STATUS_ERROR: Outcome value when the named scope does not exist.
    ADDED: Result-dict key listing the axes newly added to the vocabulary.
    ADDED_FILTER_KEYS: Result-dict key listing the filter keys newly seeded on a scope.
    ADDED_EXCLUDES: Result-dict key listing the exclude globs newly appended to a scope.
    ADDED_INDEX_BADGES: Result-dict key listing the index badges newly seeded on a scope.
    REASON: Result-dict key naming why an outcome is `error`.
    SCOPES: Key within the `wiki` section holding the per-scope config dict.
    EXCLUDE_PATHS: Per-scope key holding the scope's own exclude globs.
    FILTER: Per-scope key holding the on-the-fly node filter.
    FRONTMATTER: Filter sub-key holding the per-frontmatter-key predicates.
    FOLDER_NOTE: Filter sub-key selecting or rejecting folder notes.
    INDEX_BADGES: Per-scope key listing the frontmatter keys the topic index shows as badges on node lines.
    ERROR: Top-level result key used only for the malformed-`wiki.tag_axes` guard, in place of
      the normal status-keyed result shape.
    REGISTRY_STAGE: Name of the install-registry lookup stage, as the core-CLI resolution error
      reports it.
    MSG_CORE_CLI_UNRESOLVABLE: Leading text of the error message raised when no lookup stage finds the core CLI.
  """

  # Settings section name carrying the axis vocabulary.
  WIKI_SECTION = "wiki"
  # Section-level key holding the ordered list of classification axes.
  TAG_AXES = "tag_axes"
  # Name of the `lazycortex-core` plugin/binary.
  CORE_PLUGIN_NAME = "lazycortex-core"
  # The `bin` path segment under a plugin root.
  BIN_SEGMENT = "bin"
  # Env var the daemon exports naming candidate plugin roots.
  ENV_PLUGIN_DIRS = "LAZYCORTEX_PLUGIN_DIRS"
  # Core CLI subcommand name for a section read.
  SUB_SETTINGS_GET = "settings-get"
  # Core CLI subcommand name for a section write.
  SUB_SETTINGS_SET = "settings-set"
  # Core CLI flag naming the repository root.
  ARG_CWD = "--cwd"
  # Core CLI flag naming the settings layer a read targets.
  ARG_SCOPE = "--scope"
  # Result-dict key naming one scope's outcome.
  STATUS = "status"
  # Outcome value when at least one axis was newly unioned in.
  STATUS_ADDED = "added"
  # Outcome value when every requested axis was already declared.
  STATUS_UNCHANGED = "unchanged"
  # Outcome value when the named scope does not exist.
  STATUS_ERROR = "error"
  # Result-dict key listing the axes newly added to the vocabulary.
  ADDED = "added_axes"
  # Result-dict key listing the filter keys newly seeded on a scope.
  ADDED_FILTER_KEYS = "added_filter_keys"
  # Result-dict key listing the exclude globs newly appended to a scope.
  ADDED_EXCLUDES = "added_excludes"
  # Result-dict key listing the index badges newly seeded on a scope.
  ADDED_INDEX_BADGES = "added_index_badges"
  # Result-dict key naming why an outcome is `error`.
  REASON = "reason"
  # Key within the `wiki` section holding the per-scope config dict.
  SCOPES = "scopes"
  # Per-scope key holding the scope's own exclude globs.
  EXCLUDE_PATHS = "exclude_paths"
  # Per-scope key holding the on-the-fly node filter.
  FILTER = "filter"
  # Filter sub-key holding the per-frontmatter-key predicates.
  FRONTMATTER = "frontmatter"
  # Filter sub-key selecting or rejecting folder notes.
  FOLDER_NOTE = "folder_note"
  # Per-scope key listing the frontmatter keys the topic index shows as badges on node lines.
  INDEX_BADGES = "index_badges"
  # Top-level result key used only for the malformed-`wiki.tag_axes` guard, in place of the normal status-keyed
  # result shape.
  ERROR = "error"
  # Name of the install-registry lookup stage, as the core-CLI resolution error reports it.
  REGISTRY_STAGE = "Claude Code's plugin registry"
  # Opening of the error raised when no lookup stage finds the core CLI.
  MSG_CORE_CLI_UNRESOLVABLE = "lazycortex-core CLI not resolvable"
  # Settings section carrying the terms scopes.
  TERMS_SECTION = "terms"
  # Per-scope key naming a terms scope's dictionary directory.
  TERMS_DIR = "dir"
  # Key within the `wiki` section configuring the generated domain-spec tree.
  DOMAINS = "domains"
  # Key within the domains configuration naming the tree's directory.
  DOMAINS_OUTPUT = "output"
  # Directory of the domain-spec tree when its configuration names none; mirrors the default `domains.py` applies.
  DEFAULT_DOMAINS_OUTPUT = "docs/domains"


# Settings layer with the local overlay merged into the tracked file.
_LAYER_MERGED: Final = "merged"

# Encoding of the JSON exchanged with the core CLI.
_ENCODING: Final = "utf-8"

# Codec error handler that turns a byte that is not valid text into a replacement mark instead of failing.
_DECODE_LOSSY: Final = "replace"


def resolve_core_cli() -> Path:
  """
  Locate the `lazycortex-core` CLI binary this module dispatches settings reads and writes to.

  Returns:
    Resolved binary usable as a subprocess argument.

  Raises:
    RuntimeError: If the binary is found neither under the plugin directories named by the environment, nor in the
      dev-vault sibling layout, nor in the plugin registry's recorded install of `lazycortex-core`.
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
  # vault, where plugins lie as neighbouring directories; the registry of installed plugins, which records
  # where each enabled plugin was installed and which version. The store of downloaded copies is never
  # searched: it keeps every version ever installed, so its newest copy need not be the one enabled. No single
  # source is mandatory on its own, but when none of them worked, the work stops with an error listing
  # everything that was searched: silently continuing without the neighbour is not allowed.

  # dev-vault fallback — this file sits at plugins/claude/lazycortex-wiki/bin/axes.py, so core's own
  # bin/ is two levels up and back down into the sibling plugin tree
  sibling = Path(__file__).resolve().parents[2] / _K.CORE_PLUGIN_NAME / _K.BIN_SEGMENT / _K.CORE_PLUGIN_NAME
  if sibling.is_file():
    return sibling

  # registry fallback — a real consumer install where neither the daemon env nor the dev-vault
  # checkout applies; the install root Claude Code recorded for core's highest installed version
  installed = _plugin_registry.installed_plugin_root(_K.CORE_PLUGIN_NAME)
  if installed is not None:
    cli = installed / _K.BIN_SEGMENT / _K.CORE_PLUGIN_NAME
    if cli.is_file():
      return cli

  # none of the three stages found a binary — name what was searched so a misconfigured runner
  # is diagnosable
  searched = [ dir_path for dir_path in env_dirs if dir_path ] or [ "<unset>" ]
  raise RuntimeError(
    f"{_K.MSG_CORE_CLI_UNRESOLVABLE}: no {_K.BIN_SEGMENT}/{_K.CORE_PLUGIN_NAME} under any "
    f"directory named by ${_K.ENV_PLUGIN_DIRS} (searched: {', '.join(searched)}), no dev-vault "
    f"sibling at '{sibling}', and no {_K.CORE_PLUGIN_NAME} install recorded in {_K.REGISTRY_STAGE}."
  )


def read_settings(repo: Path,
                  section: str,
                  *,
                  layer: Literal["tracked", "local", "merged"] = "tracked") -> dict:
  """
  Read one settings section via `lazycortex-core settings-get`.

  Args:
    repo: Absolute repository root the section is read from.
    section: Top-level settings-section name.
    layer: Settings layer to read — `tracked` (no local overlay), `local` (the overlay alone) or `merged` (the
      effective view).

  Returns:
    The section dict of the requested layer, per `settings-get`'s contract.

  Raises:
    RuntimeError: When the `lazycortex-core` CLI cannot be resolved or exits non-zero.
    ValueError: When the CLI exits 0 but its answer is not valid JSON or not valid UTF-8 text
      (`json.JSONDecodeError` or `UnicodeDecodeError`).
  """
  proc = subprocess.run(
    [
      sys.executable, str(resolve_core_cli()), _K.SUB_SETTINGS_GET, section,
      _K.ARG_SCOPE, layer, _K.ARG_CWD, str(repo),
    ],
    capture_output = True, check = False,
  )

  # guard: non-zero exit — surface stdout+stderr for diagnosis rather than a bare JSON parse error; the output is
  # taken as bytes, so the exit status alone tells success from failure
  if proc.returncode != 0:
    raise RuntimeError(
      f"lazycortex-core {_K.SUB_SETTINGS_GET} exit={proc.returncode} "
      f"stdout={proc.stdout.decode(_ENCODING, errors = _DECODE_LOSSY)!r} "
      f"stderr={proc.stderr.decode(_ENCODING, errors = _DECODE_LOSSY)!r}"
    )

  # the section itself is parsed strictly: an answer that is not valid text is no answer
  return json.loads(proc.stdout)


def scope_dictionary_dirs(scopes: object) -> list[str]:
  """
  Return the dictionary directories a terms scope map configures.

  Args:
    scopes: The `terms.scopes` value.

  Returns:
    Repo-relative directories without a trailing slash, in configuration order.
  """
  # guard: a missing or malformed scope map configures no directory
  if not isinstance(scopes, dict):
    return []

  # every scope naming a directory contributes it once
  dirs = [
    cfg[_K.TERMS_DIR].rstrip("/") for cfg in scopes.values()
    if isinstance(cfg, dict) and isinstance(cfg.get(_K.TERMS_DIR), str) and cfg[_K.TERMS_DIR].strip("/")
  ]
  return list(dict.fromkeys(dirs))



# ----------------------------------------------------------------------------------------
class DictionaryDirs:
  """
  The dictionary directories of every terms scope a repository's merged settings configure.
  """

  # opt: the dictionary directories of each repository, read once per process and shared by every caller — valid
  # while no process changes the terms settings and then reads the directories again; a caller that does passes
  # the directories explicitly instead
  _by_repo: ClassVar[dict[Path, list[str]]] = {}


  @classmethod
  def read(cls, repo: str | Path) -> list[str]:
    """
    Read the dictionary directory of every terms scope a repository's merged settings configure.

    Guarantees:
      - A failure reading the settings never raises; the result is then an empty list.
      - The returned list is the caller's own copy; changing it never affects any later answer.

    Args:
      repo: Absolute repository root.

    Returns:
      A new list of repo-relative directories without a trailing slash; empty when the settings cannot be read.
    """

    # Contract:
    # A failure reading the settings never raises; the result is then an empty list.

    # Contract:
    # The returned list is the caller's own copy; changing it never affects any later answer.

    # a repository already read this process answers from the memo, as a copy the caller may change freely
    key = Path(repo).resolve()
    if key in cls._by_repo:
      return list(cls._by_repo[key])

    # a settings read that fails leaves no directory to protect rather than failing the caller, and is tried again
    try:
      terms = read_settings(Path(repo), _K.TERMS_SECTION, layer = _LAYER_MERGED)
    except ( RuntimeError, ValueError, OSError ):
      return []

    # a successful read is remembered for every later caller of the process
    cls._by_repo[key] = scope_dictionary_dirs(terms.get(_K.SCOPES) if isinstance(terms, dict) else None)
    return list(cls._by_repo[key])



# ----------------------------------------------------------------------------------------
def read_managed_dirs(repo: Path, *, dictionaries: list[str] | None = None) -> list[str]:
  """
  Return the directories whose files the wiki generates or owns, so no pass over documents enters them.

  Guarantees:
    - A failure reading the settings never raises; the result holds the directories that could be read.

  Args:
    repo: Absolute repository root.
    dictionaries: The dictionary directories to use instead of reading the terms settings, for a caller that holds
      settings newer than the ones this process read before.

  Returns:
    The dictionary directories, then the generated domain-spec tree when it is configured.
  """

  # Contract:
  # A failure reading the settings never raises; the result holds the directories that could be read.

  # the directories of every terms scope come first, as the caller holds them or as the settings name them
  dirs = DictionaryDirs.read(repo) if dictionaries is None else list(dictionaries)

  # the domain-spec tree counts only when its configuration is present; a failed read adds nothing
  try:
    wiki = read_settings(repo, _K.WIKI_SECTION, layer = _LAYER_MERGED)
  except ( RuntimeError, ValueError, OSError ):
    return dirs

  # the domain-spec tree's configuration, when the section carries one
  domains = wiki.get(_K.DOMAINS) if isinstance(wiki, dict) else None

  # guard: no domain-spec tree is configured
  if not isinstance(domains, dict) or not domains:
    return dirs

  # the tree's directory, its default when unnamed, joins the dictionary directories once
  output = str(domains.get(_K.DOMAINS_OUTPUT) or _K.DEFAULT_DOMAINS_OUTPUT).rstrip("/")
  return list(dict.fromkeys([ *dirs, output ]))


def _save_settings(repo: Path, section: str, value: dict) -> None:
  """
  Write one settings section via `lazycortex-core settings-set`.

  Args:
    repo: Absolute repository root the section is written to.
    section: Top-level settings-section name.
    value: Full section dict to persist (surrounding sections are untouched by core).

  Raises:
    RuntimeError: When the `lazycortex-core` CLI cannot be resolved or exits non-zero.
  """
  proc = subprocess.run(
    [ sys.executable, str(resolve_core_cli()), _K.SUB_SETTINGS_SET, section, _K.ARG_CWD, str(repo) ],
    input = json.dumps(value).encode(_ENCODING), capture_output = True, check = False,
  )

  # guard: non-zero exit — surface stdout+stderr for diagnosis
  if proc.returncode != 0:
    raise RuntimeError(
      f"lazycortex-core {_K.SUB_SETTINGS_SET} exit={proc.returncode} "
      f"stdout={proc.stdout.decode(_ENCODING, errors = _DECODE_LOSSY)!r} "
      f"stderr={proc.stderr.decode(_ENCODING, errors = _DECODE_LOSSY)!r}"
    )


def ensure_axes(repo: Path, axes: list[str]) -> dict:
  """
  Idempotently union `axes` into the repository-wide `wiki.tag_axes` list.

  Makes the requested axes part of the vocabulary the whole repository classifies by, keeping
  every axis the operator already declared. Applying the same request again changes nothing.

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

  # Contract:
  # No scope's own configuration is read or written by this call; the axis vocabulary belongs
  # to the repository, and a scope only ever narrows what the repository already declares.

  # read the current axis vocabulary before unioning in the requested axes
  wiki = read_settings(repo, _K.WIKI_SECTION)
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
    # collect only an axis neither declared nor already collected earlier in this same request
    if axis in existing or axis in missing:
      continue
    missing.append(axis)

  # Contract:
  # The `wiki` section is written at most once per call, and only when `tag_axes` actually
  # changed; a call that adds nothing MUST leave the settings untouched.

  # every requested axis is already declared — report it unchanged, with no write at all
  if not missing:
    return { _K.STATUS: _K.STATUS_UNCHANGED }

  # append the missing axes and persist the section in one write
  wiki[_K.TAG_AXES] = [ *existing, *missing ]
  _save_settings(repo, _K.WIKI_SECTION, wiki)
  return { _K.STATUS: _K.STATUS_ADDED, _K.ADDED: missing }


def ensure_scope_config(repo: Path,
                        scope_id: str,
                        *,
                        filter_frontmatter: dict | None = None,
                        exclude: list[str] | None = None,
                        index_badges: list[str] | None = None) -> dict:
  """
  Idempotently seed filter predicates, exclude globs, and index badges on one configured scope.

  After the call the scope lists every requested exclude glob, and its filter carries every
  requested frontmatter predicate whose key it did not already carry. An operator's existing
  predicate for the same key always wins — the seed never overwrites or merges into it. The index
  badge list is seeded the same way: only a scope with no `index_badges` key at all receives the
  requested keys, and a scope that carries the key with any value keeps it exactly as found.

  Guarantees:
    - An existing predicate for a requested filter key is never overwritten, merged into, or
      reordered; only absent keys are seeded.
    - An exclude glob already listed is never duplicated; missing ones are appended in the order
      requested.
    - A present `index_badges` value — a list, an empty list, or any other value — is never
      changed; only a scope without the key is seeded, with the requested keys deduplicated in
      request order.
    - A scope that is not configured is never created; the failure is reported as this call's
      outcome and nothing is written.
    - The `wiki` section is written at most once per call, and only when the scope actually
      changed.

  Notes:
    - Reads and rewrites the repository's `wiki` settings section through the core settings
      CLI; a call that finds everything already in place writes nothing.

  Args:
    repo: Absolute repository root.
    scope_id: Id of the scope to seed; must already exist under `wiki.scopes`.
    filter_frontmatter: Frontmatter predicates to seed, keyed by frontmatter key; `None` seeds
      none.
    exclude: Exclude globs to append when missing; `None` appends none.
    index_badges: Frontmatter key names to seed as the scope's index badge list when the scope
      has none; `None` seeds none.

  Returns:
    `{"status": "added", "added_filter_keys": [...], "added_excludes": [...]}` when anything
    changed, also carrying `"added_index_badges": [...]` when the index badge list was seeded;
    `{"status": "unchanged"}` when everything requested was already in place; or
    `{"status": "error", "reason": "no such scope"}` for an unknown `scope_id`. When
    `wiki.scopes` itself is not an object, the result is instead the single-key
    `{"error": "wiki.scopes must be an object"}`.
  """
  wiki = read_settings(repo, _K.WIKI_SECTION)
  scopes = wiki.get(_K.SCOPES) or {}

  # guard: malformed `wiki.scopes` (e.g. a list) — report cleanly instead of crashing below
  if not isinstance(scopes, dict):
    return { _K.ERROR: "wiki.scopes must be an object" }

  # Contract:
  # A scope that is not already configured is NEVER created by this call; the refusal is
  # reported as this call's outcome and nothing is written to settings.

  # look up the named scope; guarded below so seeding never creates one
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

  # Contract:
  # An exclude glob already listed on the scope is NEVER duplicated; globs missing from the
  # scope's list are appended in the order requested.

  # collect the exclude globs the scope does not list yet, in request order
  changed_excludes: list[str] = []
  existing_excludes: list[str] = list(cfg.get(_K.EXCLUDE_PATHS) or [])
  for glob in exclude or []:
    # collect only a glob neither listed nor already collected earlier in this same request
    if glob in existing_excludes or glob in changed_excludes:
      continue
    changed_excludes.append(glob)

  # Contract:
  # A present `index_badges` value — a list, an empty list, or any other value — is NEVER
  # changed; only a scope without the key is seeded, with the requested keys deduplicated in
  # request order.

  # collect the index badges to seed, in request order; a scope that carries the key keeps it as found
  changed_badges: list[str] = []
  if _K.INDEX_BADGES not in cfg:
    for key in index_badges or []:
      # collect each badge key once, however often the request repeats it
      if key in changed_badges:
        continue
      changed_badges.append(key)

  # the filter block is created on first need; folder notes stay rejected per the structural
  # default every scope gets at configure time
  flt_raw = cfg.get(_K.FILTER)
  flt: dict = flt_raw if isinstance(flt_raw, dict) else {}
  fm_raw = flt.get(_K.FRONTMATTER)
  frontmatter: dict = fm_raw if isinstance(fm_raw, dict) else {}
  changed_keys: list[str] = []
  for key, predicate in (filter_frontmatter or {}).items():
    # seed only a key the operator does not judge yet — an existing predicate wins
    if key in frontmatter:
      continue
    frontmatter = { **frontmatter, key: predicate }
    changed_keys.append(key)

  # Contract:
  # The `wiki` section is written at most once per call, and only when the scope actually
  # changed; a call that seeds nothing MUST leave the settings untouched.

  # everything requested was already in place — report it unchanged, with no write at all
  if not changed_excludes and not changed_keys and not changed_badges:
    return { _K.STATUS: _K.STATUS_UNCHANGED }

  # fold each part that changed into the scope config
  if changed_excludes:
    cfg[_K.EXCLUDE_PATHS] = [ *existing_excludes, *changed_excludes ]
  if changed_badges:
    cfg[_K.INDEX_BADGES] = changed_badges
  if changed_keys:
    new_filter = { **flt, _K.FRONTMATTER: frontmatter }
    new_filter.setdefault(_K.FOLDER_NOTE, False)
    cfg[_K.FILTER] = new_filter
  scopes[scope_id] = cfg
  wiki[_K.SCOPES] = scopes
  _save_settings(repo, _K.WIKI_SECTION, wiki)

  # report what landed; the index badge entry appears only when the index badge list was seeded
  result: dict = {
    _K.STATUS: _K.STATUS_ADDED,
    _K.ADDED_FILTER_KEYS: changed_keys,
    _K.ADDED_EXCLUDES: changed_excludes,
  }
  if changed_badges:
    result[_K.ADDED_INDEX_BADGES] = changed_badges
  return result
