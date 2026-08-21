"""
Routine type taxonomy + per-type schema validation for lazy-core.runtime.

Each entry under the `routines` section may carry an optional `type`
field. Default is `subprocess` (current behavior, unchanged). Allowed values:
`subprocess`, `inbox`, `schedule`, `git`, `md-scan`.

Validation is closed-set strict: unknown types or unknown fields raise
RoutineConfigError. Every type accepts EITHER `command` OR `expert` + `request`,
not both, not neither — enforced uniformly via `_validate_command_or_expert`.
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

from typing import overload

import sys

from constants import (
  EnvVar, JobCollectKey, JobConfigKey, JobErrorCategory, JobStatus, RoutineKey, StateKey,
  TickResultKey,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  import re
  from pathlib import Path


VALID_TYPES = { "subprocess", "inbox", "schedule", "git", "md-scan" }

# (routine name, flag) pairs whose retired-key warning already went out this process — the
# registry is re-validated every daemon iteration, so the warning must not repeat per pass
_RETIRED_FLAGS_WARNED: set[tuple[str, str]] = set()

# how long a transient-error inbox bundle stays parked before it is retired for a retry —
# matches the doctor's dead-job takeover threshold so both retry paths age out together
TRANSIENT_RETRY_AGE_SEC = 3600.0

# default window a deferred inbox bundle stays parked before its input is re-dispatched.
# A deferral waits on the world changing by hand (an operator creating the record the
# import needs), so the default is a day rather than the transient path's hour; a routine
# overrides it with `deferred_retry_sec`.
DEFERRED_RETRY_AGE_SEC = 86400.0


VALID_GIT_WATCH = {
  "new_commits", "new_files", "changed_files", "deleted_files", "renamed_files",
}

# maps a file-level diff status to the `git log --diff-filter=` flag that finds its
# last-changing commit; "R" (renames) widens to the union of add/modify/delete/rename
_DIFF_FILTER_FLAGS = { "A": "A", "M": "M", "D": "D", "R": "AMDR" }

# Per-type schemas. `command`, `expert`, `request` are all optional in every
# type — the EITHER/OR invariant is enforced separately by
# `_validate_command_or_expert`. Type-specific required fields (cron, branch,
# inbox_dir, paths, …) live in `required`; type-specific optional knobs
# (timeout_sec, path_filter, remote, …) live in `optional`.
SCHEMAS = {
  "subprocess": {
    "required": { "interval_sec" },
    "optional": { "command", "expert", "request", "timeout_sec" },
  },
  "inbox": {
    "required": { "inbox_dir", "interval_sec" },
    "optional": {
      "command", "expert", "request", "timeout_sec", "filter", "deferred_retry_sec",
    },
  },
  "schedule": {
    "required": { "cron" },
    "optional": { "command", "expert", "request", "timeout_sec" },
  },
  "git": {
    "required": { "branch", "watch", "interval_sec" },
    "optional": {
      "command", "expert", "request", "timeout_sec",
      "repo_dir", "remote", "path_filter", "filter", "group_globs",
    },
  },
  "md-scan": {
    "required": { "paths", "interval_sec" },
    "optional": { "command", "expert", "request", "timeout_sec", "filter" },
  },
}

COMMON_ALLOWED = {
  "type", "protocol", "protocols", "priority", "ignore_halt", "isolate", "allow_merge",
  RoutineKey.HOOKS_ENABLED, RoutineKey.GIT_AUTHOR,
}


def _routine_protocols(cfg: dict) -> list[str]:
  """
  Return the routine's declared protocols list.

  Routine config accepts either `protocol: <id>` (single) or
  `protocols: [<id>, ...]` (list). A single value is normalised to a one-item
  list. An empty list is returned when the routine did not declare a protocol;
  the caller decides whether that is an error for the given routine type.

  Args:
    cfg: Routine configuration dict.

  Returns:
    The declared protocol IDs, or an empty list when none were declared.
  """
  p = cfg.get(RoutineKey.PROTOCOLS)
  if isinstance(p, list):
    return list(p)
  # waiver: routine-config schema field name, single-source set in SCHEMAS, not a reusable cross-module key
  single = cfg.get("protocol")
  if isinstance(single, str):
    return [ single ]
  return []


# Separator used inside `LAZYCORTEX_ROUTINE_PROTOCOLS`. Cannot be `:`
# because protocol IDs are `<plugin-name>:<artifact-name>` and already
# contain colons. Semicolon is safe — no current protocol ID carries one
# and the convention is single-token-with-namespace.
ROUTINE_PROTOCOLS_ENV = "LAZYCORTEX_ROUTINE_PROTOCOLS"
_ROUTINE_PROTOCOLS_SEP = ";"


def routine_protocols_env(cfg: dict) -> dict[str, str]:
  """
  Build the environment overlay that propagates declared protocols to a subprocess.

  Callers pass this overlay into `subprocess.run(env = {**os.environ, **overlay})`
  so the spawned process inherits the rest of the environment and gains the
  protocol list. The subprocess reads the env var, parses on `;`, and uses the
  list when it queues its own expert jobs via `dispatch-job` — that is how
  routine-declared protocols reach the agent's `config.json` in `command:`-shape
  (the `expert:`-shape path threads protocols through `dispatch_job(protocols=...)`
  directly and does not need this overlay).

  Args:
    cfg: Routine configuration dict.

  Returns:
    `{LAZYCORTEX_ROUTINE_PROTOCOLS: "<id1>;<id2>;..."}` when the routine declared
    any protocols, else an empty dict.
  """
  protocols = _routine_protocols(cfg)
  # guard: routine declared no protocols — overlay is empty
  if not protocols:
    return {}
  return { ROUTINE_PROTOCOLS_ENV: _ROUTINE_PROTOCOLS_SEP.join(protocols) }


def routine_hooks_env(cfg: dict) -> dict[str, str]:
  """
  Build the environment overlay that gates lazycortex hooks inside a routine's subprocess.

  The overlay is emitted unconditionally, empty value included: `hook_gate.is_enabled` keys on
  the variable's *presence*, so an absent variable would leave every hook running while an empty
  one silences all of them. A routine therefore runs no lazycortex hook unless it names one.

  Args:
    cfg: Routine configuration dict.

  Returns:
    `{LAZYCORTEX_HOOKS_ALLOW_LIST: "<name1>,<name2>,..."}` with the routine's declared hook short
    names, blank and whitespace-only names dropped, or an empty-value entry when it declared none.
  """
  # Contract: the entry is emitted on every call, empty value included — `hook_gate.is_enabled`
  # keys on the variable's presence, so omitting it would leave every hook running.
  names = cfg.get(RoutineKey.HOOKS_ENABLED) or []
  return {
    EnvVar.HOOKS_ALLOW_LIST: ",".join(name.strip() for name in names if name.strip()),
  }


def routine_git_author_env(cfg: dict) -> dict[str, str]:
  """
  Build the environment overlay that stamps the routine's git identity on its commits.

  Mirrors the expert-job convention for automatic-commit identity. A routine without a
  `git_author` block commits under the daemon process's own identity, exactly as before this
  overlay existed.

  Guarantees:
    - Exports the author pair alone; no committer variable ever appears in the overlay.

  Args:
    cfg: Routine configuration dict.

  Returns:
    `{GIT_AUTHOR_NAME: ..., GIT_AUTHOR_EMAIL: ...}` when the routine declares a `git_author`
    block, else an empty dict.
  """

  # Domain(runtime.bot-identity): [routine.git-author]
  # # Routine commit identity
  # A routine that commits on its own behalf can carry its own recorded author identity, separate
  # from the identity of the process running it. Only the author side of a commit's identity is ever
  # exported this way — the committer side is deliberately left untouched, because every consumer that
  # needs to tell an automatic commit apart from an operator's own edit reads the author, never the
  # committer. A routine that declares no identity of its own commits under the identity of the
  # process that runs it, exactly as if this mechanism did not exist for it.

  author = cfg.get(RoutineKey.GIT_AUTHOR)
  # guard: routine declares no git identity — commit under the process identity, as before
  if not isinstance(author, dict):
    return {}

  # Contract:
  # The overlay carries the author pair alone; a committer variable is NEVER exported —
  # the committer stays the spawning process's own identity.

  # Decision: export the author pair only, never the committer — both identity consumers read the author
  # the daemon's loop-detect and the coordinators' operator-vs-bot check both attribute an
  # automatic commit by its author, so touching the committer would change nothing they see

  # stamp the declared identity onto every commit the subprocess makes
  # waiver: environment-variable names and small internal subkeys, not reusable domain keys
  return {
    "GIT_AUTHOR_NAME": author.get("name", ""),
    # waiver: small internal subkey, not a reusable domain key
    "GIT_AUTHOR_EMAIL": author.get("email", ""),
  }


def routine_subprocess_env(cfg: dict) -> dict[str, str]:
  """
  Build the full environment overlay a routine's spawned subprocess inherits.

  Callers pass this overlay into `subprocess.run(env = {**os.environ, **overlay})` so the
  spawned process inherits the rest of the environment plus every routine-scoped variable this
  module manages.

  Args:
    cfg: Routine configuration dict.

  Returns:
    The merged overlay: the declared-protocols entry when the routine has any, the git-author
    pair when the routine declares one, plus the hook allow-list entry, which is always present.
  """
  return { **routine_protocols_env(cfg), **routine_git_author_env(cfg), **routine_hooks_env(cfg) }


def parse_routine_protocols_env(env_value: str | None) -> list[str]:
  """
  Parse the env-var value produced by `routine_protocols_env` back into a list.

  Args:
    env_value: Raw value of the `LAZYCORTEX_ROUTINE_PROTOCOLS` env var, or None.

  Returns:
    The list of protocol IDs encoded in the env var, or an empty list when the
    value is empty or unset.
  """
  # guard: env var is empty or unset — nothing to parse
  if not env_value:
    return []
  return [ p for p in env_value.split(_ROUTINE_PROTOCOLS_SEP) if p ]


class RoutineConfigError(ValueError):
  """
  Raised when a routine entry's config does not conform to its type schema.
  """


# the flat sub-keys a composite filter block accepts — reused for the top-level
# `filter` dict, each `filter.any_of[i]` member, and the any_of/flat-key exclusion check
_FILTER_COMPOSITE_SUBKEYS = { "frontmatter", "folder_note", "basename" }


def _validate_filter_composite(name: str, flt: dict, ctx: str) -> None:
  """
  Validate one composite filter block's sub-keys.

  Shared by the top-level `filter` dict and each member of `filter.any_of` —
  both accept the same vocabulary: `frontmatter`, `folder_note`, `basename`.

  Args:
    name: Routine name (used in error messages).
    flt: The composite filter dict to validate.
    ctx: Dotted context label for error messages (`"filter"` or
      `"filter.any_of[<i>]"`).

  Raises:
    RoutineConfigError: On any structural violation or unknown sub-key.
  """
  # guard: composite filter member must be a dict
  if not isinstance(flt, dict):
    raise RoutineConfigError(f"routine '{name}': '{ctx}' must be a dict")
  unknown = set(flt) - _FILTER_COMPOSITE_SUBKEYS
  # guard: a sub-key outside the known vocabulary is rejected rather than ignored
  if unknown:
    raise RoutineConfigError(f"routine '{name}': unknown key(s) in '{ctx}': {sorted(unknown)}")

  # frontmatter is a per-key {in, not_in} predicate map — validated key by key
  # waiver: routine-config schema field name, single-source set in _FILTER_COMPOSITE_SUBKEYS, not a reusable cross-module key
  frontmatter_flt = flt.get("frontmatter")
  if frontmatter_flt is not None:
    # guard: frontmatter sub-filter must be a dict of {in,not_in} predicates
    if not isinstance(frontmatter_flt, dict):
      raise RoutineConfigError(f"routine '{name}': '{ctx}.frontmatter' must be a dict")
    for key, pred in frontmatter_flt.items():
      # guard: legacy bare-list/scalar predicate is no longer accepted
      if not isinstance(pred, dict):
        raise RoutineConfigError(
          f"routine '{name}': {ctx}.frontmatter['{key}'] must be {{in:[...],not_in:[...]}}, "
          f"not a bare list/scalar"
        )
      for side in ( "in", "not_in" ):
        # guard: in/not_in, when present, must be a list
        if side in pred and not isinstance(pred[side], list):
          raise RoutineConfigError(f"routine '{name}': {ctx}.frontmatter['{key}'].{side} must be a list")

  # folder_note is a tri-state boolean sub-filter — validated independently of frontmatter/basename
  # waiver: routine-config schema field name, single-source set in _FILTER_COMPOSITE_SUBKEYS, not a reusable cross-module key
  folder_note_flt = flt.get("folder_note")
  # guard: folder_note, when present, must be a boolean
  if folder_note_flt is not None and not isinstance(folder_note_flt, bool):
    raise RoutineConfigError(f"routine '{name}': '{ctx}.folder_note' must be a boolean")

  # basename is an {in, not_in} sub-filter, same shape as a single frontmatter predicate
  # waiver: routine-config schema field name, single-source set in _FILTER_COMPOSITE_SUBKEYS, not a reusable cross-module key
  basename_flt = flt.get("basename")
  if basename_flt is not None:
    # guard: basename sub-filter must be a dict of {in,not_in}
    if not isinstance(basename_flt, dict):
      raise RoutineConfigError(
        f"routine '{name}': {ctx}.basename must be {{in:[...],not_in:[...]}}, not a bare list/scalar"
      )
    for side in ( "in", "not_in" ):
      # guard: in/not_in, when present, must be a list
      if side in basename_flt and not isinstance(basename_flt[side], list):
        raise RoutineConfigError(f"routine '{name}': {ctx}.basename.{side} must be a list")


def _validate_command_or_expert(name: str, cfg: dict, rtype: str) -> None:
  """
  Enforce the EITHER/OR contract that every routine type shares.

  Either `command` is set, or BOTH `expert` and `request` are set — never both
  shapes, never neither.

  Args:
    name: Routine name (used in error messages).
    cfg: Routine configuration dict.
    rtype: Routine type (used in error messages).

  Raises:
    RoutineConfigError: When both shapes are present or neither shape is present.
  """

  # Domain(runtime.routines): [routine.dispatch]
  # # Command-or-expert dispatch shape
  # A routine's actual unit of work is dispatched in exactly one of two shapes, regardless of the
  # routine's own kind: a shell command it spawns as a subprocess, or a named expert together with
  # a request template it submits as a job. The two shapes are mutually exclusive and jointly
  # exhaustive — a routine that declares neither has nothing to dispatch, and one that declares both
  # is ambiguous about which shape actually runs. Both cases are rejected before the routine is ever
  # scheduled, rather than picking one shape by convention and silently ignoring the other.

  has_command = RoutineKey.COMMAND in cfg
  has_expert = RoutineKey.EXPERT in cfg
  # waiver: routine-config schema field name, single-source set in SCHEMAS, not a reusable cross-module key
  has_request = "request" in cfg
  # guard: both shapes declared — ambiguous configuration
  if has_command and (has_expert or has_request):
    raise RoutineConfigError(
      f"routine '{name}' (type={rtype}): set EITHER 'command' OR 'expert' + 'request', not both"
    )
  # guard: neither shape declared — nothing to dispatch
  if not has_command and not (has_expert and has_request):
    raise RoutineConfigError(
      f"routine '{name}' (type={rtype}): must set EITHER 'command' OR 'expert' + 'request'"
    )


def validate_routine_entry(name: str, cfg: dict) -> None:
  """
  Validate one entry from the `routines` section.

  Guarantees:
    - An entry that passes carries a recognised type, every field that type's schema requires, and
      no field outside that schema's closed vocabulary.

  Args:
    name: Routine name (used in error messages).
    cfg: Routine configuration dict.

  Raises:
    RoutineConfigError: When the type is unknown, required fields are missing,
      unknown fields are present, the EITHER/OR shape between `command` and
      `expert + request` is violated, a common field (`hooks_enabled`,
      `git_author`) has the wrong shape, the `filter` block's own shape is
      invalid, or a per-type constraint fails.
  """

  # Domain(runtime.routines): [routine.type] [routine.schema]
  # # Routine type taxonomy
  # A routine's type decides what shape of work it produces and which configuration fields it
  # accepts. A plain routine runs on a fixed polling interval alone; an inbox routine additionally
  # watches a directory for dropped files; a schedule routine fires on a cron expression instead of a
  # plain interval; a git routine watches local commit history for a chosen kind of change; a
  # markdown-scan routine walks a configured set of path globs looking for matching documents. Every
  # type accepts only its own declared fields plus a small shared vocabulary; a field outside that
  # closed set, or a type outside this fixed list, is rejected outright rather than silently ignored,
  # so a mistyped configuration key surfaces immediately instead of quietly doing nothing.

  # Contract:
  # An entry that passes this call carries a recognised type, every field that type's
  # schema requires, and no field outside that schema's closed vocabulary (plus the
  # small shared vocabulary every type accepts). An entry violating any of these
  # conditions always raises `RoutineConfigError` — nothing is silently accepted with
  # an unrecognised or missing field ignored.

  # waiver: routine-type token, single-source set in VALID_TYPES/SCHEMAS, not a reusable cross-module key
  rtype = cfg.get(RoutineKey.TYPE, "subprocess")
  # guard: unknown routine type — reject before further validation
  if rtype not in VALID_TYPES:
    raise RoutineConfigError(
      f"routine '{name}': unknown type '{rtype}'. "
      f"Valid: {sorted(VALID_TYPES)}."
    )

  # the type's schema splits the field vocabulary this routine is allowed to carry
  schema = SCHEMAS[rtype]
  # waiver: internal schema-dict subkey, single-source set in SCHEMAS
  required = schema["required"]
  # waiver: internal schema-dict subkey, single-source set in SCHEMAS
  optional = schema["optional"]
  allowed = required | optional | COMMON_ALLOWED

  # the declared fields are checked against the schema in both directions
  keys = set(cfg)
  missing = required - keys
  # guard: required field(s) absent — closed-set rejection
  if missing:
    raise RoutineConfigError(
      f"routine '{name}' (type={rtype}): missing required field(s): {sorted(missing)}"
    )

  # a field outside the schema is rejected rather than ignored
  unknown = keys - allowed
  # guard: caller passed an undeclared field — closed-set rejection
  if unknown:
    raise RoutineConfigError(
      f"routine '{name}' (type={rtype}): unknown field(s): {sorted(unknown)}"
    )

  # the command/expert pair carries its own cross-field rule
  _validate_command_or_expert(name, cfg, rtype)

  # Orphaned keys of the retired routine-side worktree path: still ALLOWED (a consumer's config
  # must not start failing validation over a dead flag) but ignored with a warning, until
  # `lazy-core.doctor` / `lazy-core.autocheckup` prunes them from the settings file. Once per
  # process, not per validation pass — the daemon re-validates the registry every iteration,
  # and a per-pass warning would write one stderr line per polling interval forever.
  for flag in ( "isolate", "allow_merge" ):
    if flag in cfg and (name, flag) not in _RETIRED_FLAGS_WARNED:
      _RETIRED_FLAGS_WARNED.add((name, flag))
      sys.stderr.write(
        f"routine '{name}': '{flag}' is retired and ignored — remove it "
        f"(lazy-core.doctor offers the prune)\n"
      )

  # the hook allow-list reaches a subprocess environment as a joined string, where a bare string
  # would expand character by character into a list of nonsense hook names
  hooks = cfg.get(RoutineKey.HOOKS_ENABLED)
  # guard: hooks_enabled, when present, must be a list of strings
  if hooks is not None and (
      not isinstance(hooks, list) or not all(isinstance(entry, str) for entry in hooks)):
    raise RoutineConfigError(f"routine '{name}': 'hooks_enabled' must be a list of strings")

  # the git identity reaches the subprocess environment as two strings, so a malformed block
  # would silently stamp empty or nonsense author fields on every commit the routine makes
  author = cfg.get(RoutineKey.GIT_AUTHOR)
  # guard: git_author, when present, must be a dict of string name/email
  if author is not None and (
      not isinstance(author, dict)
      # waiver: small internal subkeys, not reusable domain keys
      or not all(isinstance(author.get(field), str) for field in ( "name", "email" ))):
    raise RoutineConfigError(
      f"routine '{name}': 'git_author' must be a dict with string 'name' and 'email'"
    )

  # the optional filter sub-mapping is validated key by key
  # waiver: routine-config schema field name, single-source set in SCHEMAS, not a reusable cross-module key
  flt = cfg.get("filter")
  if flt is not None:
    # guard: filter must be a dict
    if not isinstance(flt, dict):
      raise RoutineConfigError(f"routine '{name}': 'filter' must be a dict")
    # waiver: filter-block sub-key literal, not a reusable cross-module key
    any_of = flt.get("any_of")
    if any_of is not None:
      flat_keys = set(flt) & _FILTER_COMPOSITE_SUBKEYS
      # guard: any_of is mutually exclusive with a flat sub-filter at the same level
      if flat_keys:
        raise RoutineConfigError(
          f"routine '{name}': 'filter.any_of' is mutually exclusive with flat "
          f"filter {sorted(flat_keys)} at the same level"
        )
      # guard: any_of must be a list of composite filters
      if not isinstance(any_of, list):
        raise RoutineConfigError(f"routine '{name}': 'filter.any_of' must be a list")
      # an empty any_of would match nothing forever (any([]) is False) — the inverted
      # polarity of an absent/empty flat filter, which accepts everything
      # guard: any_of must declare at least one member
      if not any_of:
        raise RoutineConfigError(f"routine '{name}': 'filter.any_of' must not be empty")
      for idx, member in enumerate(any_of):
        _validate_filter_composite(name, member, f"filter.any_of[{idx}]")
    else:
      # waiver: dotted-context label for error messages, not a reusable domain key
      _validate_filter_composite(name, flt, "filter")

  # a git routine carries a watch mode drawn from a closed set
  # waiver: routine-type token, single-source set in VALID_TYPES/SCHEMAS, not a reusable cross-module key
  if rtype == "git":
    # waiver: routine-config schema field name, single-source set in SCHEMAS, not a reusable cross-module key
    watch = cfg.get("watch")
    # guard: unrecognised git watch mode — closed-set rejection
    if watch not in VALID_GIT_WATCH:
      raise RoutineConfigError(
        f"routine '{name}' (type=git): invalid watch value '{watch}'. "
        f"Valid: {sorted(VALID_GIT_WATCH)}."
      )

    # dir-level grouping rides on file-level items, so it needs a path to group by
    # waiver: routine-config schema field name, single-source set in SCHEMAS, not a reusable cross-module key
    group_globs = cfg.get("group_globs")
    if group_globs is not None:
      # guard: the key must be a non-empty list of non-empty glob strings
      if (not isinstance(group_globs, list) or not group_globs
          or not all(isinstance(glob_pat, str) and glob_pat.strip() for glob_pat in group_globs)):
        raise RoutineConfigError(
          f"routine '{name}' (type=git): 'group_globs' must be a non-empty list of glob strings"
        )
      # guard: commit items carry no path — nothing to group
      # waiver: git watch-mode token, single-source set in VALID_GIT_WATCH, not a reusable cross-module key
      if watch == "new_commits":
        raise RoutineConfigError(
          f"routine '{name}' (type=git): 'group_globs' cannot be combined with "
          f"watch 'new_commits' — commit items carry no path to group by"
        )

  # an md-scan routine carries the path globs its scan is bounded by
  # waiver: routine-type token, single-source set in VALID_TYPES/SCHEMAS, not a reusable cross-module key
  if rtype == "md-scan":
    # guard: paths must be a list of globs
    # waiver: routine-config schema field name, single-source set in SCHEMAS, not a reusable cross-module key
    if not isinstance(cfg.get("paths"), list):
      raise RoutineConfigError(
        f"routine '{name}' (type=md-scan): 'paths' must be a list of globs"
      )


def dispatch_routine(repo: Path, name: str, cfg: dict) -> dict:
  """
  Dispatch one routine tick and return the standard tick result dict.

  Switches on `cfg["type"]` (default `subprocess`). For non-default types,
  delegates to the per-type handler in this module. For `subprocess`, delegates
  to `runtime_daemon.dispatch_subprocess` (lazy import to avoid module cycle).

  Args:
    repo: Path-like reference to the repository the tick runs in.
    name: Routine name.
    cfg: Routine configuration dict.

  Returns:
    The tick result dict produced by the per-type handler.

  Raises:
    RoutineConfigError: When `cfg["type"]` is unknown at dispatch time (the
      validator should have caught this earlier; this is a defensive guard).
  """
  # waiver: routine-type token, single-source set in VALID_TYPES/SCHEMAS, not a reusable cross-module key
  rtype = cfg.get(RoutineKey.TYPE, "subprocess")
  if rtype == "subprocess":
    # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
    from runtime_daemon import dispatch_subprocess
    return dispatch_subprocess(repo, name, cfg)
  # waiver: routine-type token, single-source set in VALID_TYPES/SCHEMAS, not a reusable cross-module key
  if rtype == "inbox":
    return dispatch_inbox(repo, name, cfg)
  # waiver: routine-type token, single-source set in VALID_TYPES/SCHEMAS, not a reusable cross-module key
  if rtype == "schedule":
    return dispatch_schedule(repo, name, cfg)
  # waiver: routine-type token, single-source set in VALID_TYPES/SCHEMAS, not a reusable cross-module key
  if rtype == "git":
    return dispatch_git(repo, name, cfg)
  # waiver: routine-type token, single-source set in VALID_TYPES/SCHEMAS, not a reusable cross-module key
  if rtype == "md-scan":
    return dispatch_md_scan(repo, name, cfg)
  # guard: validator should have caught this — defensive last-resort
  raise RoutineConfigError(f"routine '{name}': unknown type '{rtype}' at dispatch time")


# Per-type handlers — implementations land in their own phases (C/D/E).
# Until then, calling these returns a clean error result so the daemon's
# tick loop doesn't crash; just logs and moves on.

def _check_inout(pred: dict, actual: object) -> bool:
  """
  Apply a single `{ in, not_in }` allow/deny predicate against one value.

  `in` (when non-empty) is an allow-list; `not_in` (when non-empty) is a
  deny-list. Both AND together.

  Args:
    pred: Predicate dict — `{ in: [...], not_in: [...] }`.
    actual: The value under evaluation.

  Returns:
    True if the allow-list and deny-list both accept `actual`; False otherwise.
  """
  # waiver: predicate-filter schema subkey, not a reusable domain key
  include = pred.get("in") or []
  # waiver: predicate-filter schema subkey, not a reusable domain key
  exclude = pred.get("not_in") or []
  # guard: allow-list declared and value outside it
  if include and actual not in include:
    return False
  # guard: deny-list declared and value inside it
  if exclude and actual in exclude:
    return False
  return True


def _match_frontmatter_filter(flt: dict, frontmatter: dict) -> bool:
  """
  Apply a per-key `{ in, not_in }` frontmatter predicate.

  All keys AND together. `None` in either list matches a missing key or an
  explicit None. No legacy bare-list form.

  Args:
    flt: Per-key predicate dict — `{ <key>: { in: [...], not_in: [...] } }`.
    frontmatter: Parsed frontmatter dict from a candidate file.

  Returns:
    True if every key's allow-list and deny-list both accept the corresponding
    frontmatter value; False otherwise.
  """
  return all(
    _check_inout(pred, frontmatter.get(key))
    for key, pred in flt.items()
  )


def _match_filter(flt: dict, frontmatter: dict, path: object = None) -> bool:
  """
  Apply a composite routine filter against one item.

  Filter shape: `{ "frontmatter": { <key>: { in, not_in } }, "folder_note": <bool>,
  "basename": { in, not_in } }`, or `{ "any_of": [ <composite>, ... ] }`. `any_of`
  is mutually exclusive with the flat sub-keys at the same level (enforced by the
  validator) and passes when any one member composite passes (OR semantics).
  Absent `any_of`, every declared sub-filter must pass (AND semantics).
  `frontmatter` is evaluated against the item's parsed frontmatter; an item
  without frontmatter parses to `{}`. `folder_note` (tri-state) constrains
  whether the item is a folder note (`Path(p).stem == Path(p).parent.name`).
  `basename` matches `Path(path).name`. When `path` is `None` the item is
  treated as not a folder note and as having no basename (`None`).

  Guarantees:
    - An item with no declared sub-condition in the filter block passes unconditionally.
    - Every declared flat sub-condition must all pass; under `any_of`, passing any one alternative
      composite is sufficient.

  Args:
    flt: Composite filter block from the routine config — may be empty.
    frontmatter: Parsed frontmatter dict from the item under evaluation.
    path: Optional file path used for folder-note and basename matching. When
      absent, the `folder_note` predicate treats the item as a non-folder-note
      and the `basename` predicate evaluates against `None`.

  Returns:
    True when the item passes the filter; False otherwise. An empty filter
    block accepts everything.
  """

  # Domain(runtime.routines): [routine.filter]
  # # Composite routine filter semantics
  # A routine's filter narrows which items its tick acts on. At the flat level, every declared
  # sub-condition — a frontmatter field predicate, folder-note membership, basename — must all hold at
  # once for an item to pass; an item with no declared sub-conditions passes unconditionally. An
  # alternative-group block replaces the flat conditions at that level with a list of alternative
  # filter blocks, and the item passes when at least one alternative passes, layering an OR of
  # alternatives on top of the default AND of conditions. Each field-level predicate itself carries an
  # allow-list and a deny-list that both must accept the value, so a field can be constrained from
  # either or both directions independently.

  # Contract:
  # An item with no declared sub-condition in `flt` passes unconditionally — an empty or absent
  # filter block never rejects anything. Every declared flat sub-condition (`frontmatter`,
  # `folder_note`, `basename`) must all pass for the item to pass; under `any_of`, the item passes
  # when at least one alternative composite passes.

  # an OR-composite delegates to its members instead of the flat sub-keys below
  # waiver: filter-block sub-key literal, not a reusable cross-module key
  any_of = flt.get("any_of")
  if any_of is not None:
    return any(_match_filter(member, frontmatter, path) for member in any_of)

  # frontmatter sub-filter — evaluated against the item's parsed frontmatter
  # waiver: filter-block sub-key literal, single-source set in _FILTER_COMPOSITE_SUBKEYS, not a reusable cross-module key
  frontmatter_flt = flt.get("frontmatter")
  # guard: a frontmatter sub-filter is declared — it must pass
  if isinstance(frontmatter_flt, dict) and not _match_frontmatter_filter(frontmatter_flt, frontmatter):
    return False

  # folder_note (tri-state) constrains matches by folder-note status; path_str/_Path below
  # are shared setup for both this block and the basename block that follows it
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from pathlib import Path as _Path
  path_str = str(path) if path is not None else None
  # waiver: filter-block sub-key literal, single-source set in _FILTER_COMPOSITE_SUBKEYS, not a reusable cross-module key
  want_folder_note = flt.get("folder_note")
  if want_folder_note is not None:
    is_folder_note = path_str is not None and _Path(path_str).stem == _Path(path_str).parent.name
    # guard: want only folder-notes but this isn't one
    if want_folder_note and not is_folder_note:
      return False
    # guard: forbid folder-notes but this is one
    if (not want_folder_note) and is_folder_note:
      return False

  # basename sub-filter — matches Path(path).name; path=None evaluates against None
  # waiver: filter-block sub-key literal, single-source set in _FILTER_COMPOSITE_SUBKEYS, not a reusable cross-module key
  basename_flt = flt.get("basename")
  # guard: a basename sub-filter is declared — it must pass
  if isinstance(basename_flt, dict) and not _check_inout(
    basename_flt, _Path(path_str).name if path_str is not None else None
  ):
    return False
  return True


def _not_implemented(name: str, rtype: str) -> dict:
  """
  Build a clean error result for a routine type whose handler is not yet implemented.

  Args:
    name: Routine name.
    rtype: Routine type for which no handler exists.

  Returns:
    A tick result dict with `exit = -1` and a human-readable error message.
  """
  return {
    TickResultKey.NAME: name,
    TickResultKey.EXIT: -1,
    TickResultKey.DURATION_SEC: 0.0,
    TickResultKey.ERROR: f"type {rtype!r} not yet implemented",
  }


@overload
def _render_template(template: dict, values: dict) -> dict: ...
@overload
def _render_template(template: object, values: dict) -> object: ...
def _render_template(template: object, values: dict) -> object:
  """
  Substitute `{field}` placeholders in string values of a JSON-shaped template.

  Walks dicts and lists; runs `str.format(**values)` on string leaves. Literal `{`
  and `}` must be doubled (`{{`, `}}`). A placeholder referencing a var that
  isn't provided raises `KeyError` — caller treats this as a routine failure
  rather than silently emitting a malformed request.

  Args:
    template: A dict, list, str, or other JSON-shaped value to render.
    values: Mapping of placeholder names to their substitution values.

  Returns:
    The rendered template with string leaves substituted.

  Raises:
    KeyError: When a string leaf references a placeholder absent from `values`.
  """
  if isinstance(template, dict):
    return { k: _render_template(v, values) for k, v in template.items() }
  if isinstance(template, list):
    return [ _render_template(v, values) for v in template ]
  if isinstance(template, str):
    return template.format(**values)
  return template


def _is_retryable_transient(done_job: dict) -> bool:
  """
  Decide whether a finished inbox bundle is a spawn fault worth re-dispatching.

  True for a failed bundle whose error category marks a spawn-level fault and
  that finished longer than `TRANSIENT_RETRY_AGE_SEC` ago; false for a success,
  for any other error category, and for a fault too recent to have outlived the
  outage that caused it.

  Args:
    done_job: One finished-bundle descriptor as returned by `completed_dedup_jobs`.

  Returns:
    `True` when the bundle should be retired so its input re-dispatches.
  """
  # ponytail: unbounded retry — one re-dispatch per TRANSIENT_RETRY_AGE_SEC for as long as the
  # spawn keeps faulting; add an attempt counter in the bundle if the churn ever costs anything
  return (
    done_job[JobCollectKey.STATUS] != JobStatus.DONE
    and done_job.get(JobCollectKey.CATEGORY) == JobErrorCategory.TRANSIENT
    and done_job.get(JobCollectKey.AGE_SEC, 0.0) >= TRANSIENT_RETRY_AGE_SEC
  )


def _remove_harness_artifacts(inbox_dir: Path) -> None:
  """
  Remove empty harness bookkeeping directories from an inbox folder.

  The inbox is an operator-facing folder, often synced or shared outside the harness, so leftover
  bookkeeping directories must not accumulate there. A directory still holding real content is left
  untouched.

  Notes:
    - Failures are ignored; the cleanup is best-effort and never raises.

  Args:
    inbox_dir: Path-like reference to the routine's configured inbox directory.
  """
  # innermost first, so the parent becomes removable in the same pass; a directory that still
  # holds anything real fails rmdir and survives, which is the wanted behaviour
  for rel in (".claude/.cc-writes", ".claude"):
    try:
      (inbox_dir / rel).rmdir()
    except OSError:
      pass


def _is_returnable_deferral(done_job: dict, *, window_sec: float) -> bool:
  """
  Decide whether a deferred inbox bundle has waited long enough to be re-dispatched.

  A deferral parks its input untouched and waits on something outside the runtime —
  typically an operator creating the record the work needs. Retiring the bundle at
  once would re-spawn against the same unchanged world every tick, so the input is
  returned to the queue only after the configured window has elapsed.

  Args:
    done_job: One finished-bundle descriptor as returned by `completed_dedup_jobs`.
    window_sec: Seconds a deferred bundle stays parked before its input returns.

  Returns:
    `True` when the bundle is deferred and older than the window.
  """
  return (
    done_job[JobCollectKey.STATUS] == JobStatus.DEFERRED
    and done_job.get(JobCollectKey.AGE_SEC, 0.0) >= window_sec
  )


def _file_fingerprint(path: Path) -> str | None:
  """
  Build the identity token of an inbox file as it stands right now.

  Lets a later pass tell this exact file apart from a different file that later
  occupies the same path, even when the replacement is byte-identical and shares
  the same modification time.

  Args:
    path: Path-like reference to the file to fingerprint.

  Returns:
    An opaque token comparable with `_is_same_file`, or `None` when the file cannot
    be read.
  """
  try:
    stat_result = path.stat()
  except OSError:
    return None
  return (
    f"{stat_result.st_dev}:{stat_result.st_ino}"
    f":{stat_result.st_size}:{stat_result.st_mtime_ns}"
  )


def _is_same_file(path: Path, fingerprint: str | None) -> bool:
  """
  Decide whether a path still holds the file a recorded fingerprint was taken from.

  A caller about to destroy an input asks this first, so a fresh file that landed
  under a name already processed is left alone instead of being drained as if the
  work on it were done.

  Notes:
    - A `None` fingerprint means the recorded bundle predates the fingerprint field; the
      answer is then the historical one, `True`, so an in-flight queue keeps draining.

  Args:
    path: Path-like reference to the file about to be acted on.
    fingerprint: Token previously produced by `_file_fingerprint`, or `None`.

  Returns:
    `True` when the file is the recorded one or when no record exists.
  """
  # guard: bundle carries no fingerprint (dispatched before the field existed)
  if fingerprint is None:
    return True
  return _file_fingerprint(path) == fingerprint


def dispatch_inbox(repo: Path, name: str, cfg: dict) -> dict:
  """
  Scan `cfg["inbox_dir"]` and dispatch one job per non-hidden file found.

  Two sub-shapes (validator enforces exactly-one):

    - `expert + request`: each tick performs a reconcile pass followed by a
      dispatch pass. The reconcile pass drains succeeded jobs by unlinking the
      input file and consuming the bundle, but only when the path still holds
      the same file the job ran on; a succeeded job whose input was replaced
      in the meantime is retired without draining, so the replacement is
      dispatched on its own on a later pass. Failed jobs are left parked — the
      unconsumed bundle's dedup key blocks re-dispatch until an operator
      triages the dead letter. Two kinds of parked bundle age out instead of
      waiting for a triage: a transient failure, once older than
      `TRANSIENT_RETRY_AGE_SEC`, and a deferral, once older than the routine's
      `deferred_retry_sec` (default `DEFERRED_RETRY_AGE_SEC`). Both are retired
      without draining the input, so the same tick re-dispatches the file. The
      dispatch pass submits one job per remaining file, keyed on the file's
      absolute path via `dedup_key` and the `{file}` placeholder in `request`.
      A candidate whose identity cannot be read is left in the inbox for a
      later tick instead of being dispatched, since a job whose input identity
      is unknown could not later be reconciled safely. The inbox is the source
      of truth; the file is never copied into the job bundle.
    - `command`: spawn `command + [<absolute-path-to-inbox-file>]` as a
      blocking subprocess per file. The file stays in the inbox until the
      consumer command moves or deletes it — the routine never removes the
      input file itself.

  Guarantees:
    - The inbox file is never copied into a dispatched job; the file at its original path is the
      single source of truth for that unit of work.
    - In the `expert + request` shape, the file is unlinked only after a job whose bundle still
      names the exact file that was dispatched finishes successfully; a failed job, a bundle whose
      identity no longer matches the file at that path, or a file whose identity could not be read
      at dispatch time all leave the file untouched.
    - In the `command` shape, the routine never removes the input file itself.

  Notes:
    - On every tick over an existing inbox directory, removes empty harness bookkeeping
      directories left inside that folder; a directory still holding real content is left
      untouched. This removal targets only those bookkeeping directories, never the input file.

  Args:
    repo: Path-like reference to the repository.
    name: Routine name.
    cfg: Routine configuration dict.

  Returns:
    The standard tick result dict — `exit = 0` and `dispatched_count = N` on
    success, `exit = -1` and an `error` field on failure.
  """

  # Contract:
  # The inbox file is never copied into a dispatched job — the file at its original path is the
  # single source of truth for that unit of work. In the `expert + request` shape, the file is
  # unlinked only after a job whose bundle still names the exact file that was dispatched (identity
  # checked by a stat-based fingerprint) finishes successfully; a failed job, a bundle whose
  # fingerprint no longer matches the file at that path, or a file whose identity could not be read
  # at dispatch time all leave the file untouched. In the `command` shape, the routine NEVER removes
  # the input file itself — the spawned command owns moving or deleting it.

  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import time
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from pathlib import Path
  started = time.time()
  repo = Path(repo)
  inbox_rel = cfg[RoutineKey.INBOX_DIR]
  inbox_dir = repo / inbox_rel

  # guard: configured inbox dir does not exist — nothing to scan
  if not inbox_dir.exists():
    # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
    from external_dirs import is_declared
    # guard: a declared external dir that is absent or dangling is a real failure, not an idle tick —
    # the daemon opens one folded `routine:<name>` incident from the non-zero exit
    if is_declared(repo, inbox_rel):
      return {
        TickResultKey.NAME: name, TickResultKey.EXIT: -1,
        TickResultKey.DURATION_SEC: time.time() - started,
        "dispatched_count": 0,
        # waiver: daemon error/trigger token, not an internal key
        TickResultKey.ERROR: f"external_dir_broken: {inbox_rel}",
      }
    return {
      TickResultKey.NAME: name, TickResultKey.EXIT: 0,
      TickResultKey.DURATION_SEC: time.time() - started,
      "dispatched_count": 0,
      TickResultKey.NOTE: "inbox_dir does not exist",
    }

  # the inbox is an operator-facing folder (often Dropbox-synced) — harness bookkeeping dirs
  # left behind by an agent that touched it must not accumulate there
  _remove_harness_artifacts(inbox_dir)

  # sorted for deterministic dispatch order
  candidates = []
  for entry in sorted(inbox_dir.iterdir()):
    # guard: hidden entry — skip
    if entry.name.startswith("."):
      continue
    # guard: symlink — operator state, never moved
    if entry.is_symlink():
      continue
    # guard: not a regular file — skip subdirs etc.
    if not entry.is_file():
      continue
    candidates.append(entry)

  # Optional composite filter — same matcher md-scan / git use. A non-markdown or
  # unreadable item parses to {}, so a `None`-accepting frontmatter predicate keeps
  # it; a value-requiring predicate naturally drops non-frontmatter items.
  # waiver: routine-config schema field name, single-source set in SCHEMAS, not a reusable cross-module key
  flt = cfg.get("filter", {})
  if flt:
    # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
    from frontmatter_parser import parse_frontmatter
    kept = []
    for entry in candidates:
      try:
        # waiver: stdlib idiom, not a domain constant
        text = entry.read_text(errors = "replace")
      except OSError:
        text = ""
      # guard: item failed the composite filter — drop it
      if not _match_filter(flt, parse_frontmatter(text), entry):
        continue
      kept.append(entry)
    candidates = kept

  # a command routine runs a subprocess, an expert routine dispatches a job per file
  use_command = RoutineKey.COMMAND in cfg
  if use_command:
    # waiver: inline numeric/default literal, not a domain constant
    timeout_sec = cfg.get(RoutineKey.TIMEOUT_SEC, 300)
    try:
      # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
      from runtime_daemon import resolve_routine_command
      resolved_cmd = list(resolve_routine_command(list(cfg[RoutineKey.COMMAND])))
    except Exception as e:
      return {
        TickResultKey.NAME: name, TickResultKey.EXIT: -1,
        TickResultKey.DURATION_SEC: time.time() - started,
        TickResultKey.ERROR: f"inbox command resolution failed: {e}",
      }
    # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
    import os as _os
    # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
    import subprocess as _subprocess
    subprocess_env = { **_os.environ, **routine_subprocess_env(cfg) }
    dispatched = 0
    for f in candidates:
      try:
        # blocking — one process at a time, no parallel spawns
        _subprocess.run(
          [ *resolved_cmd, str(f.resolve()) ],
          cwd = str(repo),
          timeout = timeout_sec,
          capture_output = True,
          text = True,
          env = subprocess_env,
          check = False,
        )
        dispatched += 1
      except Exception as e:
        return {
          TickResultKey.NAME: name, TickResultKey.EXIT: -1,
          TickResultKey.DURATION_SEC: time.time() - started,
          "dispatched_count": dispatched,
          TickResultKey.ERROR: f"inbox subprocess dispatch failed at {f.name}: {e}",
        }
    return {
      TickResultKey.NAME: name, TickResultKey.EXIT: 0,
      TickResultKey.DURATION_SEC: time.time() - started,
      "dispatched_count": dispatched,
    }

  # the expert branch renders one request per candidate file
  expert = cfg[RoutineKey.EXPERT]
  request_template = cfg["request"]
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from expert_runtime import completed_dedup_jobs, consume_job, dispatch_job
  protocols = _routine_protocols(cfg)
  # the dispatch surface takes a real path; symlinks are resolved so a daemon started through a
  # symlinked checkout writes the same bundle paths as one started through the canonical one
  target_repo = Path(repo).resolve()

  # how long a deferred bundle waits before its input is offered to the queue again
  # waiver: routine-config schema field name, single-source set in SCHEMAS, not a reusable cross-module key
  deferred_window = float(cfg.get("deferred_retry_sec", DEFERRED_RETRY_AGE_SEC))

  # Domain(runtime.routines): [routine.inbox] [routine.dedup]
  # # Inbox dead-letter aging
  # An inbox item that failed keeps its dispatch slot occupied so the same input is never resubmitted
  # while an operator has not yet looked at it — the parked result is a dead letter waiting on triage.
  # Two kinds of parked result age out and re-dispatch on their own instead of waiting for triage
  # indefinitely. A spawn-level fault, where the work never actually ran, retries after a short fixed
  # window on the order of an hour, on the assumption that whatever caused the spawn to fail has
  # likely cleared by then. A deferral, where the work ran but decided the input is not actionable
  # yet, waits on something outside the system to change — typically an operator creating a record the
  # work depends on — so its window defaults to a full day and can be widened per routine; retiring it
  # sooner would just re-observe the same unchanged world on every tick.

  # Reconcile finished work against the inbox. The input file is never copied
  # into the job bundle (only its path is passed), so the inbox is the single
  # source of truth: a succeeded job drains its input here; a failed job is
  # left parked — its bundle stays DONE-but-unconsumed so the dedup key keeps
  # the file from re-dispatching (a dead-letter the operator triages). Success
  # means an explicit finished outcome in the response — anything less counts
  # as failed, because the input is destroyed here and nowhere else. Two parked
  # shapes age out on their own instead: a stale transient error (the spawn
  # faulted rather than the work) and a deferral (the expert postponed the work
  # and left the input alone). Both are retired without draining the input, so
  # the loop below re-dispatches the same file on this very tick.
  for done_job in completed_dedup_jobs(target_repo, expert):
    # guard: stale transient failure — retire the bundle so the input re-dispatches
    if _is_retryable_transient(done_job):
      consume_job(target_repo, expert, done_job[JobCollectKey.JOB_ID])
      continue
    # guard: the deferral has waited out its window — offer the input to the queue again
    if _is_returnable_deferral(done_job, window_sec = deferred_window):
      consume_job(target_repo, expert, done_job[JobCollectKey.JOB_ID])
      continue
    # guard: failed or still-waiting deferred job — leave the input parked behind its bundle
    if done_job[JobCollectKey.STATUS] != JobStatus.DONE:
      continue
    src = Path(done_job[JobCollectKey.DEDUP_KEY])
    # guard: the path now holds a different file than the one the job processed — an
    # operator dropped a fresh file under a name the inbox has seen before (bank
    # exports reuse names), and draining it here would destroy work never done
    if not _is_same_file(src, done_job.get(JobCollectKey.DEDUP_FINGERPRINT)):
      consume_job(target_repo, expert, done_job[JobCollectKey.JOB_ID])
      continue
    try:
      # the expert may have filed the input away itself on success; a missing
      # original is the expected post-success state, so unlink is best-effort
      src.unlink()
    except OSError:
      pass
    consume_job(target_repo, expert, done_job[JobCollectKey.JOB_ID])

  # every surviving candidate becomes one dispatched job
  dispatched = 0
  for f in candidates:
    # guard: reconcile (or an external actor) drained this file — nothing to send
    if not f.exists():
      continue
    fingerprint = _file_fingerprint(f)
    # guard: the file's identity cannot be read, so the retire pass would have nothing to
    # check the path against before deleting it — leave it for a later tick rather than
    # dispatch work whose input can be swapped out underneath it unnoticed
    if fingerprint is None:
      continue
    request = _render_template(request_template, { "file": str(f) })
    try:
      result = dispatch_job(
        target_repo, expert, request,
        protocols = protocols,
        dedup_key = str(f),
        dedup_fingerprint = fingerprint,
      )
    except Exception as e:
      return {
        TickResultKey.NAME: name, TickResultKey.EXIT: -1,
        TickResultKey.DURATION_SEC: time.time() - started,
        "dispatched_count": dispatched,
        TickResultKey.ERROR: f"inbox dispatch failed at {f.name}: {e}",
      }
    # guard: an in-flight or parked (dead-letter) bundle already owns this file
    if result.get(JobCollectKey.STATUS) == JobStatus.ALREADY_QUEUED:
      continue
    dispatched += 1

  # the tick result reports how many jobs went out this pass
  return {
    TickResultKey.NAME: name, TickResultKey.EXIT: 0,
    TickResultKey.DURATION_SEC: time.time() - started,
    "dispatched_count": dispatched,
  }


def dispatch_schedule(repo: Path, name: str, cfg: dict) -> dict:
  """
  Fire one dispatch when the cron expression has crossed a boundary since last_run.

  The daemon-level `due_routines` decides when this handler runs; the handler
  itself just dispatches. Two sub-shapes (validator enforces exactly-one):

    - `command`: spawn subprocess (delegates to `runtime_daemon.dispatch_subprocess`).
    - `expert + request`: dispatch a single job to the named expert.

  Args:
    repo: Path-like reference to the repository.
    name: Routine name.
    cfg: Routine configuration dict.

  Returns:
    The standard tick result dict — `exit = 0` and `dispatched_count = 1` on
    success.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import time
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from datetime import UTC, datetime
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from pathlib import Path
  started = time.time()

  # a command routine delegates straight to the subprocess dispatcher
  if RoutineKey.COMMAND in cfg:
    # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
    from runtime_daemon import dispatch_subprocess
    sub_cfg = { RoutineKey.COMMAND: cfg[RoutineKey.COMMAND] }
    if RoutineKey.TIMEOUT_SEC in cfg:
      sub_cfg[RoutineKey.TIMEOUT_SEC] = cfg[RoutineKey.TIMEOUT_SEC]
    # the delegate builds the subprocess environment from the config it is handed, so every field
    # that reaches that environment has to survive the prune
    for carried in ( "protocol", RoutineKey.PROTOCOLS, RoutineKey.HOOKS_ENABLED ):
      if carried in cfg:
        sub_cfg[carried] = cfg[carried]
    return dispatch_subprocess(Path(repo), name, sub_cfg)

  # the expert branch renders the request template against the current time
  expert = cfg[RoutineKey.EXPERT]
  # waiver: routine-config schema field name, single-source set in SCHEMAS, not a reusable cross-module key
  request_template = cfg["request"]
  now = datetime.now(UTC)
  request = _render_template(request_template, {
    "cron_fire_ts": now.isoformat(),
    "cron_fire_unix": str(int(now.timestamp())),
  })
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from expert_runtime import dispatch_job
  # the dispatch surface takes a real path; symlinks are resolved so a daemon started through a
  # symlinked checkout writes the same bundle paths as one started through the canonical one
  target_repo = Path(repo).resolve()
  dispatch_job(
    target_repo, expert, request,
    protocols = _routine_protocols(cfg),
  )
  return {
    TickResultKey.NAME: name, TickResultKey.EXIT: 0,
    TickResultKey.DURATION_SEC: time.time() - started,
    "dispatched_count": 1,
  }


def due_for_schedule(name: str, cfg: dict, now_unix: float, last_run_unix: float) -> bool:
  # waiver: `name` kept for symmetry with other routine helpers (see docstring); unused here
  # pylint: disable=unused-argument
  """
  Return whether a `schedule` routine has crossed a fire boundary since last_run.

  Wraps `cron.due_since` with unix-time arguments so the daemon-level scheduler
  can mix interval-based and cron-based routines uniformly.

  Args:
    name: Routine name (unused; kept for symmetry with other routine helpers).
    cfg: Routine configuration dict containing the `cron` expression.
    now_unix: Current time as a unix timestamp.
    last_run_unix: Timestamp of the previous run, or `0` if the routine has
      never run.

  Returns:
    True if the cron expression has fired at least once since `last_run_unix`;
    False otherwise.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from datetime import UTC, datetime
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from cron import parse, due_since
  spec = parse(cfg["cron"])
  # waiver: inline numeric/default literal, not a domain constant
  epoch = datetime(1970, 1, 1, tzinfo = UTC)
  last_run_dt = (
    datetime.fromtimestamp(last_run_unix, tz = UTC)
    if last_run_unix > 0 else epoch
  )
  now_dt = datetime.fromtimestamp(now_unix, tz = UTC)
  return due_since(spec, last_run_dt, now_dt)


def dispatch_git(repo: Path, name: str, cfg: dict) -> dict:
  """
  Watch local HEAD and fire one dispatch per matching item.

  Two sub-shapes (validator enforces exactly-one):

    - `expert + request`: render `request` with the item dict's templating vars
      and dispatch a job to `expert`.
    - `command`: spawn `command + [<item-as-json>]` as a blocking subprocess,
      one item at a time, no parallel spawns. The item-json is a one-line JSON
      encoding of the per-watch item dict (e.g. `{"sha":"...","subject":"...",...}`).
      An item whose worker exits non-zero is recorded in `failed_items` and
      retried, ahead of any fresh item, on a later tick; the cursor still
      advances past it so one broken item never stalls the rest.

  `last_seen_sha` is tracked in `state.json`'s `git_watch.<name>` block. First
  run records the current ref and dispatches nothing (no history backfill).
  Non-ancestor (force-push / rebase) resets baseline and computes no fresh
  items over the discarded range; any `failed_items` still reachable from the
  new ref are dispatched regardless (an unreachable one is dropped instead).

  `remote` is read from config but ignored by the watch — remote sync is the
  daemon's responsibility (`daemon.git.remote_sync`). The field is kept for
  schema back-compat (vestigial; not rejected).

  Guarantees:
    - `last_seen_sha` always advances to the tick's HEAD by the time a successful tick returns,
      including a tick whose range was discarded by a force-push or rebase.
    - The first tick after a watch is configured never backfills prior history; it records the
      current HEAD as the baseline and dispatches nothing.
    - An item a worker subprocess failed on is retried on a later tick, ahead of any fresh item, for
      as long as its commit stays reachable from HEAD; once history rewrites it away it is dropped
      rather than redelivered.

  Args:
    repo: Path-like reference to the repository.
    name: Routine name.
    cfg: Routine configuration dict.

  Returns:
    The standard tick result dict — `exit = 0` with `dispatched_count` on
    success, `exit = -1` and an `error` field on failure.
  """

  # Contract:
  # `last_seen_sha` always advances to the tick's HEAD by the time the tick returns, on every
  # successful tick after the first — including a tick whose range was discarded by a force-push or
  # rebase. The very first tick after a watch is configured records the current HEAD as the baseline
  # and dispatches nothing; no prior history is ever backfilled. An item a worker subprocess failed
  # on is retried on a later tick, ahead of any fresh item, for as long as its commit stays reachable
  # from HEAD; once history rewrites it away it is dropped rather than redelivered.

  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import json as _json
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import subprocess
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import time
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from pathlib import Path
  started = time.time()
  repo = Path(repo)

  # the watched git dir may sit below the repo root the routine is registered in
  # waiver: routine-config schema field name, single-source set in SCHEMAS, not a reusable cross-module key
  work_dir = (repo / cfg.get("repo_dir", ".")).resolve()
  # remote is vestigial — read but unused (remote sync is daemon-level)
  # waiver: the read is the point — it documents the config field this routine consumes, and the subscript validates its presence
  _remote = cfg.get("remote", "origin")  # noqa: F841
  # waiver: the read is the point — it documents the config field this routine consumes, and the subscript validates its presence
  _branch = cfg[RoutineKey.BRANCH]  # noqa: F841
  watch = cfg["watch"]
  # waiver: routine-config schema field name, single-source set in SCHEMAS, not a reusable cross-module key
  path_filter = cfg.get("path_filter")

  # guard: work_dir is not a git repo (worktree-aware probe)
  # waiver: filesystem path idiom, not a domain constant
  if not (work_dir / ".git").exists() and not (work_dir.is_dir() and _is_git_dir(work_dir)):
    # waiver: one-off routine-outcome note/reason token, not an internal key
    return _err(name, started, "not_a_git_repo", f"{work_dir} is not a git repo")

  # current HEAD is the upper bound of the range this tick scans
  try:
    head_sha = subprocess.check_output(
      [ "git", "rev-parse", "HEAD" ],
      cwd = str(work_dir), text = True,
    ).strip()
  except subprocess.CalledProcessError as e:
    # waiver: one-off routine-outcome note/reason token, not an internal key
    return _err(name, started, "rev_parse_failed", str(e))

  # the last-seen sha, and any items a previous tick's worker failed on, are per-routine
  # state carried across ticks
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import runtime_state
  state = runtime_state.load(repo)
  git_state = state.setdefault(StateKey.GIT_WATCH, {}).setdefault(name, {})
  last_seen = git_state.get(StateKey.LAST_SEEN_SHA)

  # Domain(runtime.routines): [routine.git-watch]
  # # Git-watch baseline and force-push detection
  # A git watch remembers, per watch, the commit it last scanned up to — its baseline. The very first
  # tick after a watch is configured has no baseline yet: it records the current commit as the
  # starting point and dispatches nothing, so a watch never floods on the whole prior history the
  # moment it is turned on. On every later tick, the baseline commit is checked for reachability from
  # the current commit; when it is still reachable, the range between the two is ordinary forward
  # history and every matching item in it is fresh work. When the baseline is no longer reachable — a
  # force-push or a rebase discarded it — the watch treats the discarded range as having produced no
  # fresh items rather than guessing at what might have been rewritten, and simply resets its baseline
  # to the current commit. A previously failed item is retried independently of this reset, but only
  # while its own commit is still reachable from the current commit; one that history has rewritten
  # away is dropped instead of being replayed against a commit it no longer descends from.

  # guard: first run — record baseline, dispatch nothing (nothing could have failed yet)
  if last_seen is None:
    runtime_state.update(
      repo,
      lambda s: s.setdefault(StateKey.GIT_WATCH, {}).setdefault(name, {}).update({StateKey.LAST_SEEN_SHA: head_sha})
    )
    # waiver: one-off routine-outcome note/reason token, not an internal key
    return _ok(name, started, dispatched_count = 0, note = "first_run_baseline_recorded")

  # Items a previous tick's worker subprocess exited non-zero on are retried before any fresh
  # work — the whole point of tracking them is that a broken item must not strand the wake
  # behind it until an unrelated commit happens to wake this routine again. An entry whose sha
  # history no longer knows (force-push / rebase rewrote it away) degrades gracefully: dropped
  # rather than replayed, using the same ancestry discipline the force-push guard below uses.
  stored_failed = git_state.get(StateKey.FAILED_ITEMS, [])
  retry_items = [
    entry for entry in stored_failed
    # waiver: `_compute_git_items`'s per-watch item-shape key, not a reusable domain key
    if entry.get("sha") and _is_ancestor(work_dir, entry["sha"], head_sha)
  ]
  dropped_count = len(stored_failed) - len(retry_items)

  # guard: ref hasn't moved and nothing is pending retry — a plain no-op tick
  if last_seen == head_sha and not retry_items and not dropped_count:
    return _ok(name, started, dispatched_count = 0)

  # decide what fresh work (if any) this tick's range contributes; retry items that survived
  # the ancestry check above are unaffected either way and still get dispatched below
  fresh_items: list[dict] = []
  force_pushed = last_seen != head_sha and not _is_ancestor(work_dir, last_seen, head_sha)
  # force-push detected — no fresh items are computed over the discarded range; the
  # unconditional cursor write at the end of this tick already advances LAST_SEEN_SHA to
  # head_sha regardless of this branch, so a separate reset write here was dead code (M11)
  if not force_pushed and last_seen != head_sha:
    # the watch mode decides what a single item is (a commit, a path, a rename pair)
    fresh_items = _compute_git_items(work_dir, last_seen, head_sha, watch, path_filter)

    # Optional composite filter — same matcher md-scan / inbox use. Items carrying a
    # file `path` are evaluated against their parsed frontmatter; an unreadable or
    # frontmatter-less file (a deletion, or code with no frontmatter) parses to {}, so
    # a `None`-accepting filter keeps it. Path-less items (e.g. new_commits watch) run
    # through the matcher too, with empty frontmatter and no path, so the folder_note
    # (and any) predicate is honoured — folder_note: true excludes them.
    # waiver: routine-config schema field name, single-source set in SCHEMAS, not a reusable cross-module key
    flt = cfg.get("filter", {})
    if flt:
      # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
      from frontmatter_parser import parse_frontmatter
      kept = []
      for item in fresh_items:
        # waiver: small internal subkey, not a reusable domain key
        rel = item.get("path")
        # guard: item carries no file path — match against {} / path=None so the
        # folder_note (and any) predicate decides; not-a-folder-note by definition.
        if rel is None:
          if _match_filter(flt, {}, None):
            kept.append(item)
          continue
        try:
          # waiver: stdlib idiom, not a domain constant
          text = (work_dir / rel).read_text(errors = "replace")
        except OSError:
          text = ""
        # guard: file failed the composite filter — drop this item
        if not _match_filter(flt, parse_frontmatter(text), rel):
          continue
        kept.append(item)
      fresh_items = kept

    # optional dir-level grouping — N same-dir file items collapse into one item per group
    # dir AFTER the filter, so a worker whose real unit is the directory is invoked once
    # per dir over the surviving members; paths outside every glob stay file-level items
    # waiver: routine-config schema field name, single-source set in SCHEMAS, not a reusable cross-module key
    group_globs = cfg.get("group_globs")
    if group_globs and fresh_items:
      fresh_items = _group_git_items(work_dir, fresh_items, group_globs, f"{last_seen}..{head_sha}")

  # a command routine receives the items as a subprocess payload, not as jobs; retries go
  # first, so a broken item gets its next attempt before any fresh item is even tried
  # limit: a retried item is dispatched as-is, never re-matched against `cfg`'s composite
  # filter (that filter only ever ran over `fresh_items`, above) — a filter edited between
  # the failing tick and the retry tick has no effect on items already queued for retry;
  # upgrade path is re-running the same filter pass over `retry_items` here if that drift
  # ever needs to be closed
  next_failed_items = retry_items
  if RoutineKey.COMMAND in cfg:
    # waiver: inline numeric/default literal, not a domain constant
    timeout_sec = cfg.get(RoutineKey.TIMEOUT_SEC, 300)
    try:
      # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
      from runtime_daemon import resolve_routine_command
      resolved_cmd = list(resolve_routine_command(list(cfg[RoutineKey.COMMAND])))
    except Exception as e:
      return _err(name, started, "command_resolution_failed", str(e))
    # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
    import os as _os
    subprocess_env = { **_os.environ, **routine_subprocess_env(cfg) }
    still_failing = []
    for item in retry_items + fresh_items:
      # a retried item carries its own `reason` from a prior failure — strip it before
      # resending the item-json payload; the worker only ever expects the raw item shape
      # waiver: this module's own FAILED_ITEMS entry key, not a reusable domain key
      clean_item = { k: v for k, v in item.items() if k != "reason" }
      payload = _json.dumps(clean_item, sort_keys = True)
      try:
        # blocking — one process at a time, no parallel spawns
        proc = subprocess.run(
          [ *resolved_cmd, payload ],
          cwd = str(repo),
          timeout = timeout_sec,
          capture_output = True,
          text = True,
          env = subprocess_env,
          check = False,
        )
      except Exception as e:
        # the spawn itself faulted (e.g. TimeoutExpired) rather than the worker reporting a
        # clean non-zero exit — bail out before the `failed_items` write below, so this item
        # (and the rest of `retry_items + fresh_items`) is retried from scratch next tick
        # instead of the tick crashing mid-loop with that write abandoned; same as
        # `dispatch_inbox`'s command-shape handles the same fault
        # waiver: one-off routine-outcome note/reason token, not an internal key
        return _err(name, started, "command_dispatch_failed", str(e))

      # worker failed on this item — keep it for the next tick's retry pass; the cursor
      # still advances below so one broken item never stalls the whole conveyor
      if proc.returncode != 0:
        # waiver: inline numeric/default literal, not a domain constant — bounds the stored
        # reason so a chatty worker can't grow state.json without limit
        stderr_tail = proc.stderr[-300:].strip() if proc.stderr else ""
        still_failing.append({ **clean_item, "reason": f"exit {proc.returncode}: {stderr_tail}" })
    next_failed_items = still_failing
  else:
    expert = cfg[RoutineKey.EXPERT]
    request_template = cfg["request"]
    # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
    from expert_runtime import dispatch_job
    protocols = _routine_protocols(cfg)
    # the dispatch surface takes a real path; symlinks are resolved so a daemon started through a
    # symlinked checkout writes the same bundle paths as one started through the canonical one
    target_repo = Path(repo).resolve()
    for item in fresh_items:
      rendered = _render_template(request_template, item)
      dispatch_job(target_repo, expert, rendered, protocols = protocols)

  # the scanned range is closed by advancing the last-seen sha to HEAD; failed items persist
  # (or clear) alongside it so the next tick knows what to retry
  runtime_state.update(
    repo,
    lambda s: s.setdefault(StateKey.GIT_WATCH, {}).setdefault(name, {}).update({
      StateKey.LAST_SEEN_SHA: head_sha,
      StateKey.FAILED_ITEMS: next_failed_items,
    })
  )

  # fold every status worth a daemon-log line into one note — a persistent per-item failure
  # stays a visible line on every tick until it clears or its sha is dropped, per design
  notes = []
  if force_pushed:
    # waiver: one-off routine-outcome note/reason token, not an internal key
    notes.append("force_push_baseline_reset")
  if dropped_count:
    notes.append(f"dropped {dropped_count} unreachable failed item(s) after history rewrite")
  if next_failed_items:
    notes.append(f"{len(next_failed_items)} item(s) still failing — retried next tick")
  return _ok(
    name, started, dispatched_count = len(retry_items) + len(fresh_items),
    **({ TickResultKey.NOTE: "; ".join(notes) } if notes else {}),
  )


def _ok(name: str, started: float, **extra: object) -> dict:
  """
  Build a success tick result dict.

  Args:
    name: Routine name.
    started: Start time as a unix timestamp (used to compute duration).
    **extra: Additional fields merged into the result dict.

  Returns:
    A tick result dict with `exit = 0`, `duration_sec`, and any extra fields.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import time
  return {
    TickResultKey.NAME: name, TickResultKey.EXIT: 0,
    TickResultKey.DURATION_SEC: time.time() - started,
    **extra,
  }


def _err(name: str, started: float, error_kind: str, detail: str) -> dict:
  """
  Build a failure tick result dict.

  Args:
    name: Routine name.
    started: Start time as a unix timestamp (used to compute duration).
    error_kind: Short error category tag.
    detail: Human-readable detail string appended after the error kind.

  Returns:
    A tick result dict with `exit = -1`, `duration_sec`, and a combined
    `error` field.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import time
  return {
    TickResultKey.NAME: name, TickResultKey.EXIT: -1,
    TickResultKey.DURATION_SEC: time.time() - started,
    TickResultKey.ERROR: f"{error_kind}: {detail}",
  }


def _is_git_dir(path: Path) -> bool:
  """
  Check whether the given path is inside a git working tree.

  Uses `git rev-parse --git-dir` rather than just `.git` existence so worktrees
  and bare repos are recognised correctly.

  Args:
    path: Path-like reference to the candidate directory.

  Returns:
    True when `git rev-parse --git-dir` succeeds at `path`; False otherwise.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import subprocess
  rc = subprocess.run(
    [ "git", "rev-parse", "--git-dir" ],
    cwd = str(path), capture_output = True, check = False,
  )
  return rc.returncode == 0


def _is_ancestor(work_dir: Path, ancestor: str, descendant: str) -> bool:
  """
  Check whether `ancestor` is reachable from `descendant` via git history.

  Args:
    work_dir: Path-like reference to the git working tree.
    ancestor: Candidate ancestor SHA.
    descendant: Candidate descendant SHA.

  Returns:
    True when `ancestor` is an ancestor of `descendant`; False otherwise (also
    False when either SHA is unknown to git).
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import subprocess
  rc = subprocess.run(
    [ "git", "merge-base", "--is-ancestor", ancestor, descendant ],
    cwd = str(work_dir), capture_output = True, check = False,
  )
  return rc.returncode == 0


def _compute_git_items(work_dir: Path, last_seen: str, head_sha: str,
                       watch: str, path_filter: str | None) -> list[dict]:
  """
  Enumerate per-watch items between two SHAs.

  Returns a list of dicts whose keys are the templating variables documented in
  `references/lazy-core.runtime-schema.md` for the corresponding `watch` value.

  Args:
    work_dir: Path-like reference to the git working tree.
    last_seen: Baseline SHA (exclusive lower bound of the range).
    head_sha: Current SHA (inclusive upper bound of the range).
    watch: Watch mode — one of the values in `VALID_GIT_WATCH`.
    path_filter: Optional pathspec pattern restricting the enumeration; None
      means no filter.

  Returns:
    A list of item dicts; empty when no items match the watch mode in the range.

  Raises:
    RoutineConfigError: When `watch` is not a recognised watch mode.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import subprocess
  rng = f"{last_seen}..{head_sha}"
  pathspec = [ "--", path_filter ] if path_filter else []

  # commit-level watches read the range straight from the log
  # waiver: git CLI/output vocabulary, not a domain constant
  if watch == "new_commits":
    out = subprocess.check_output(
      [ "git", "log",
        "--format=%H%x09%h%x09%s%x09%an%x09%ae%x09%ct",
        rng, *pathspec ],
      cwd = str(work_dir), text = True,
    ).strip()
    items = []
    if out:
      for line in out.splitlines():
        parts = line.split("\t")
        # waiver: inline numeric/default literal, not a domain constant
        if len(parts) >= 6:
          sha, short_sha, subj, an, ae, ct = parts[:6]
          items.append({
            "sha": sha,
            "short_sha": short_sha,
            "subject": subj,
            "author_name": an,
            "author_email": ae,
            "commit_ts": ct,
          })
    return items

  # file-level watches read a name-status diff instead of the log
  if watch in ("new_files", "changed_files", "deleted_files"):
    # use diff --name-status for added/modified/deleted classification
    out = subprocess.check_output(
      [ "git", "diff", "--name-status", rng, *pathspec ],
      cwd = str(work_dir), text = True,
    ).strip()
    wanted = {
      "new_files": { "A" },
      "changed_files": { "A", "M" },
      "deleted_files": { "D" },
    }[watch]
    items = []
    if out:
      for line in out.splitlines():
        parts = line.split("\t")
        # guard: malformed diff row — skip
        if len(parts) < 2:
          continue
        # strip percent for renames etc.
        status = parts[0][:1]
        # guard: status not in the requested set
        if status not in wanted:
          continue
        path = parts[1]
        sha = _last_change_sha(work_dir, path, rng, status)
        author_name, author_email = _last_change_author(work_dir, path, rng, status)
        items.append({
          "path": path, "status": status, "sha": sha,
          "author_name": author_name, "author_email": author_email,
        })
    return items

  # renames need the rename-detection pass to pair the old and new path
  # waiver: git CLI/output vocabulary, not a domain constant
  if watch == "renamed_files":
    out = subprocess.check_output(
      [ "git", "diff", "--name-status", "--find-renames", rng, *pathspec ],
      cwd = str(work_dir), text = True,
    ).strip()
    items = []
    if out:
      for line in out.splitlines():
        parts = line.split("\t")
        # waiver: git CLI/output vocabulary, not a domain constant
        if len(parts) >= 3 and parts[0].startswith("R"):
          old_path, new_path = parts[1], parts[2]
          # waiver: git CLI/output vocabulary, not a domain constant
          sha = _last_change_sha(work_dir, new_path, rng, "R")
          author_name, author_email = _last_change_author(work_dir, new_path, rng, "R")
          items.append({
            "old_path": old_path,
            "new_path": new_path,
            "sha": sha,
            "author_name": author_name,
            "author_email": author_email,
          })
    return items

  # every watch value is handled above, so reaching here means the config is invalid
  raise RoutineConfigError(f"unknown git watch value: {watch!r}")


def _group_dir_for(path: str, group_globs: list) -> str | None:
  """
  Resolve the group directory a file path collapses into, if any.

  Globs are tried in list order — the first match wins. A glob matches segment-by-segment
  (`*` never crosses `/`), and the file must sit strictly below the glob's depth, so a
  note lying AT that depth (a folder-note beside the group dirs) never becomes its own
  group.

  Args:
    path: Repo-relative file path from a git-watch item.
    group_globs: Ordered glob list from the routine's `group_globs` config key.

  Returns:
    The matched directory prefix as a repo-relative path, or None when no glob matches.
  """

  # Domain(runtime.routines): [routine.git-watch] [routine.grouping]
  # # Directory-level grouping of file-level watch items
  # A git watch normally treats one changed file as one unit of work, but some consumers really care
  # about a whole directory changing together — an asset folder, a bundle of related files.
  # Declaring an ordered list of directory globs lets file-level items collapse into one item per
  # matching directory: every matched file becomes a member of its directory's single item instead of
  # a standalone item of its own. The first glob that matches wins, matching is done segment by
  # segment so a wildcard never crosses a path separator, and a file must sit strictly below the
  # matched glob's own depth — a file that sits exactly at that depth, such as a note describing the
  # group itself, never becomes a group of one. Grouping cannot be combined with a watch whose items
  # carry no path at all, since there is nothing to group by in that case.

  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import fnmatch
  parts = path.split("/")
  for pattern in group_globs:
    pat = pattern.split("/")
    # guard: the file must sit strictly below the glob's depth — a path at or above it has no group dir
    if len(parts) <= len(pat):
      continue
    if all(fnmatch.fnmatch(seg, p) for seg, p in zip(parts[: len(pat)], pat, strict = True)):
      return "/".join(parts[: len(pat)])
  return None


def _group_git_items(work_dir: Path, items: list[dict], group_globs: list, rng: str) -> list[dict]:
  """
  Collapse file-level items into one item per matched group directory.

  A worker whose real unit of work is a directory (an asset folder, a bundle) is invoked
  once per dir with every member path, instead of once per file. Items whose path matches
  no glob pass through unchanged, so grouping is an overlay on the file-level watch, not a
  replacement.

  Args:
    work_dir: Path-like reference to the git working tree.
    items: File-level items from `_compute_git_items`, already filtered.
    group_globs: Ordered glob list from the routine's `group_globs` config key.
    rng: The `<last_seen>..<head>` range this tick scans, for the group's attribution.

  Returns:
    Ungrouped items followed by one dict per group dir, each carrying `dir`, sorted
    member `paths`, and the `sha` / `author_name` / `author_email` of the last commit
    touching the dir in range.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import subprocess

  # split the stream: path-less or unmatched items pass through, the rest bucket by group dir
  singles: list[dict] = []
  groups: dict[str, list[dict]] = {}
  for item in items:
    # a renamed_files item carries the pair; the new path is the member's identity
    # waiver: `_compute_git_items`'s per-watch item-shape keys, not reusable domain keys
    path = item.get("path") or item.get("new_path")
    gdir = _group_dir_for(path, group_globs) if path else None
    if gdir is None:
      singles.append(item)
      continue
    groups.setdefault(gdir, []).append(item)

  # emit one item per group dir, appended after the pass-through singles
  for gdir in sorted(groups):
    members = groups[gdir]

    # attribute the group to the last commit touching the dir in range — one log call per group
    try:
      line = subprocess.check_output(
        [ "git", "log", "-1", "--format=%H%x09%an%x09%ae", rng, "--", gdir ],
        cwd = str(work_dir), text = True,
      ).strip()
    except subprocess.CalledProcessError:
      line = ""

    # unpack the log line, padding short splits; an empty line degrades to the first
    # member's own attribution rather than dropping the group
    # waiver: inline numeric/default literal, not a domain constant
    sha, author_name, author_email = [ *line.split("\t"), "", "", "" ][:3] if line else (
      # waiver: `_compute_git_items`'s per-watch item-shape keys, not reusable domain keys
      members[0].get("sha", ""), members[0].get("author_name", ""), members[0].get("author_email", ""),
    )

    # the group item — dir identity plus sorted member paths
    singles.append({
      "dir": gdir,
      # waiver: `_compute_git_items`'s per-watch item-shape keys, not reusable domain keys
      "paths": sorted(str(member.get("path") or member.get("new_path")) for member in members),
      "sha": sha,
      "author_name": author_name,
      "author_email": author_email,
    })
  return singles


def _last_change_sha(work_dir: Path, path: str, rng: str, status: str) -> str:
  """
  Return the most recent commit SHA in `rng` matching the status filter for `path`.

  Args:
    work_dir: Path-like reference to the git working tree.
    path: Path of the file to look up.
    rng: Commit range expression (e.g. `<base>..<head>`).
    status: Single-letter diff status (A/M/D) — `R` maps to the union `AMDR`.

  Returns:
    The matching commit SHA, or the literal string `unknown` when no such
    commit can be located.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import subprocess

  # resolve the diff-filter flag and query the most recent matching commit's sha
  # waiver: "R" here is the same rename status letter documented on the `status` param above, not a domain constant
  flag = _DIFF_FILTER_FLAGS.get(status, _DIFF_FILTER_FLAGS["R"])
  try:
    out = subprocess.check_output(
      [ "git", "log", f"--diff-filter={flag}",
        "--format=%H", "-1", rng, "--", path ],
      cwd = str(work_dir), text = True,
    ).strip()
    return out or "unknown"
  except subprocess.CalledProcessError:
    # guard: git log failed for this range/path — best-effort, "unknown" not a raise
    # waiver: documented sentinel per this function's own Returns: contract, not a domain constant
    return "unknown"


def _last_change_author(work_dir: Path, path: str, rng: str, status: str) -> tuple[str, str]:
  """
  Return the author name and email of the most recent commit in `rng` matching the status filter for `path`.

  Args:
    work_dir: Path-like reference to the git working tree.
    path: Path of the file to look up.
    rng: Commit range expression (e.g. `<base>..<head>`).
    status: Single-letter diff status (A/M/D) — `R` maps to the union `AMDR`.

  Returns:
    A tuple `(author_name, author_email)` from the matching commit, or a pair of empty
    strings when no such commit can be located.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import subprocess

  # resolve the diff-filter flag and query the author of the matching commit in range
  # waiver: "R" here is the same rename status letter documented on the `status` param above, not a domain constant
  flag = _DIFF_FILTER_FLAGS.get(status, _DIFF_FILTER_FLAGS["R"])
  try:
    out = subprocess.check_output(
      [ "git", "log", f"--diff-filter={flag}",
        "--format=%an%x09%ae", "-1", rng, "--", path ],
      cwd = str(work_dir), text = True,
    ).strip()
  except subprocess.CalledProcessError:
    # guard: git log failed for this range/path — best-effort, empty strings not a raise
    return "", ""

  # guard: no matching commit in range — best-effort, empty strings not a raise
  if not out:
    return "", ""

  # split the tab-separated "name<TAB>email" line into its two fields
  parts = out.split("\t")

  # guard: malformed output — treat as empty rather than raising
  if len(parts) < 2:
    return "", ""

  # name and email, in the order %an%x09%ae wrote them
  return parts[0], parts[1]


def _compile_recursive_glob(pat: str) -> re.Pattern[str]:
  """
  Compile a `**`-bearing glob into an anchored regex matcher.

  `**` as a whole segment matches any number of path segments, including
  zero; a trailing bare `**` matches any descendant. Within a segment `*`
  matches any run of non-`/` characters and `?` exactly one. The result is
  anchored at both ends — unlike `PurePath.match`, which is right-anchored.

  Args:
    pat: Glob pattern containing at least one `**` segment.

  Returns:
    The compiled pattern; use `.match(rel_posix_path)`.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import re
  segs = pat.split("/")
  parts = [ "^" ]
  for i, seg in enumerate(segs):
    last = i == len(segs) - 1
    if seg == "**":
      parts.append(".*" if last else "(?:[^/]+/)*")
      continue
    piece = "".join(
      "[^/]*" if ch == "*" else "[^/]" if ch == "?" else re.escape(ch)
      for ch in seg
    )
    parts.append(piece if last else piece + "/")
  return re.compile("".join(parts) + r"\Z")


# Walk-list cache shared by every md-scan routine of one daemon iteration: sibling
# routines tick back-to-back, and each RepoWalk costs git subprocesses. TTL sits
# below the minimum routine interval (60s) so every tick still re-walks once.
# waiver: module-level mutable cache — the daemon main loop is serial by contract, no locking needed
_WALK_CACHE: dict[str, tuple[float, list[Path]]] = {}
_WALK_CACHE_TTL_SEC = 30.0
# waiver: filesystem sentinel path under the gitignored runtime log tree, not a reusable cross-module key
_MD_SCAN_STATE_DIR = ".logs/lazy-core/runtime/md-scan-state"


def _walk_repo_files(repo: Path, now: float) -> list[Path]:
  """
  Return the repo's non-ignored file list, shared across md-scan routines.

  Args:
    repo: Path-like reference to the repository.
    now: Tick start timestamp used for cache freshness.

  Returns:
    Absolute file paths from `RepoWalk`, possibly served from the per-repo
    cache when a walk younger than the TTL exists.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from repo_walk import RepoWalk
  key = str(repo.resolve())
  cached = _WALK_CACHE.get(key)
  # guard: a fresh-enough walk already exists for this repo — share it
  if cached is not None and now - cached[0] < _WALK_CACHE_TTL_SEC:
    return cached[1]
  files = list(RepoWalk(repo).iter_files())
  _WALK_CACHE[key] = ( now, files )
  return files


def _dir_signature(d: Path, walk_files: list[Path], memo: dict[str, str]) -> str:
  """
  Fingerprint a directory subtree by file paths, mtimes, and sizes.

  The candidate's whole parent directory is hashed — not the candidate file
  alone — because md-scan consumers (e.g. the spec gate-tick worker) read
  sibling documents to decide whether work exists. Only files present in the
  ignore-filtered walk list participate, so ever-churning gitignored state
  (runtime journals, job bundles) can never invalidate a signature.

  Args:
    d: Directory to fingerprint.
    walk_files: The tick's ignore-filtered absolute file list.
    memo: Per-tick cache mapping directory path to its computed signature.

  Returns:
    Hex digest stable while no walked file under `d` changes.
  """

  # Domain(runtime.routines): [routine.md-scan]
  # # Change detection by directory signature
  # A scan that spawns an external command for every matching file would repeat the same no-op work
  # every tick once nothing has changed, so a change is detected instead by fingerprinting the whole
  # directory the candidate lives in — not just the candidate file — because the work often reads
  # sibling files to decide whether anything is actually due. The fingerprint folds in only the files
  # the tick's own scan already considers relevant (paths, modification times, sizes); anything the
  # scan ignores, such as ever-churning runtime bookkeeping, can never by itself invalidate a
  # previously clean signature. A candidate whose directory signature matches the one recorded after
  # its last clean run is skipped entirely; a failed run is never recorded as clean, so it is retried
  # on the very next tick rather than silently going stale.

  key = str(d)
  # guard: already fingerprinted this directory during this tick
  if key in memo:
    return memo[key]
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import hashlib
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import os
  prefix = key.rstrip(os.sep) + os.sep
  entries = []
  for p in walk_files:
    sp = str(p)
    # guard: file lives outside the fingerprinted directory
    if not sp.startswith(prefix):
      continue
    try:
      st = os.stat(sp)
    except OSError:
      continue
    entries.append(( sp, st.st_mtime_ns, st.st_size ))
  entries.sort()
  sig = hashlib.sha256(repr(entries).encode()).hexdigest()
  memo[key] = sig
  return sig


def _scan_state_path(repo: Path, name: str) -> Path:
  """
  Compute the dispatch-state file path for one command-shape md-scan routine.

  Args:
    repo: Path-like reference to the repository.
    name: Routine name.

  Returns:
    Path under the gitignored runtime log tree.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from pathlib import Path
  return Path(repo) / _MD_SCAN_STATE_DIR / f"{name}.json"


def _load_scan_state(repo: Path, name: str) -> dict:
  """
  Read the routine's persisted candidate-signature map, empty on any failure.

  Args:
    repo: Path-like reference to the repository.
    name: Routine name.

  Returns:
    Mapping of absolute candidate path to its last clean-run signature.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import json
  try:
    loaded = json.loads(_scan_state_path(repo, name).read_text())
  except (OSError, ValueError):
    return {}
  return loaded if isinstance(loaded, dict) else {}


def _save_scan_state(repo: Path, name: str, state: dict) -> None:
  """
  Persist the routine's candidate-signature map, best-effort.

  Args:
    repo: Path-like reference to the repository.
    name: Routine name.
    state: Mapping of absolute candidate path to signature.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import json
  path = _scan_state_path(repo, name)
  try:
    path.parent.mkdir(parents = True, exist_ok = True)
    path.write_text(json.dumps(state, indent = 1, sort_keys = True))
  except OSError:
    # guard: state persistence is an optimization — never fail the tick over it
    pass


def dispatch_md_scan(repo: Path, name: str, cfg: dict) -> dict:
  """
  Dispatch one job per file matching the routine's configured path globs and filter.

  For each candidate that passes `cfg["filter"]` (absent = match-all):

    - `expert + request` shape: dispatch a job to the named expert via
      `expert_runtime.dispatch_job` with `dedup_key = str(f)`. The expert
      receives the absolute path under the `file` key (with any extra keys
      from `request` templated in).
    - `command` shape: spawn `command + [str(f)]` as a blocking subprocess.
      A change-detection gate skips the spawn when the candidate's parent-dir
      signature (file paths + mtimes + sizes) is unchanged since the last
      clean run; the signature map persists under
      `.logs/lazy-core/runtime/md-scan-state/<routine-name>.json`. Failed
      runs are never recorded, so they retry on the next tick.

  In-place semantics: never moves the source file; the consumer reads and edits
  the file where it lies. Per-file errors accumulate; one bad file does NOT
  abort the scan tick for the remaining files. Shared-state errors
  (`frontmatter_parser` missing, command resolution failure) DO abort early —
  those are not per-file conditions and retrying them per file is wasteful
  noise.

  Args:
    repo: Path-like reference to the repository.
    name: Routine name.
    cfg: Routine configuration dict. Each entry in `cfg["paths"]` containing `**`
      is matched full-path-anchored, with `**` spanning any number of segments
      (including zero); an entry without `**` keeps `PurePath.match` semantics —
      right-anchored, shell-glob, `*` never crosses `/`.

  Returns:
    The standard tick result dict — `exit = 0` on a pass (possibly with
    accumulated per-file errors under `errors`), `exit = -1` and an `error`
    field when every candidate failed or a shared-state setup failed.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import time
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from pathlib import Path, PurePath
  started = time.time()
  repo = Path(repo)

  # the scan is bounded by the declared globs and the optional frontmatter filter
  # waiver: routine-config schema field name, single-source set in SCHEMAS, not a reusable cross-module key
  paths_globs = cfg["paths"]
  # waiver: routine-config schema field name, single-source set in SCHEMAS, not a reusable cross-module key
  flt = cfg.get("filter", {})

  # Dual matching semantics, compiled once per tick:
  #   - patterns containing `**` → anchored regex where `**` spans any number
  #     of segments (incl. zero) — enables coarse scope-root sieves
  #     (`<root>/**/*.md`); precision lives in the consumer's routing config
  #     and the frontmatter filter, not here.
  #   - plain patterns → PurePath.match, unchanged: right-anchored shell-glob
  #     semantics where `*` does NOT cross `/` (so `requests/*.md` matches
  #     only direct children).
  # RepoWalk (not stdlib glob — `**` semantics shifted across 3.12/3.13/3.14)
  # excludes `.git`, every `.gitignore`-ignored path, and `.lazyignore`
  # extra-excludes via git's own ignore engine. Dedupe by resolved abs path.
  compiled = [
    ( pat, _compile_recursive_glob(pat) if "**" in pat else None )
    for pat in paths_globs
  ]
  seen_abs = set()
  candidates = []
  walk_files = _walk_repo_files(repo, started)
  for full in walk_files:
    rel = full.relative_to(repo).as_posix()
    for pat, rx in compiled:
      matched = rx.match(rel) is not None if rx is not None else PurePath(rel).match(pat)
      # guard: pattern does not match this file
      if not matched:
        continue
      ap = full.resolve()
      # guard: already collected under a different glob — skip duplicate
      if ap in seen_abs:
        break
      seen_abs.add(ap)
      if ap.is_file():
        candidates.append(ap)
      break
  # Deterministic order (was implicit via `sorted(glob(...))` before).
  candidates.sort()

  # per-outcome tallies the tick reports back to the daemon
  dispatched = 0
  skipped = 0
  unchanged = 0
  # Per-file errors accumulate; one bad file does NOT abort the scan tick
  # for the remaining files (Bug 59). Shared-state errors (frontmatter_parser
  # missing, command resolution failure) DO abort early — those are not
  # per-file conditions and retrying them per file is wasteful noise.
  errors: list[dict] = []
  try:
    # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
    from frontmatter_parser import parse_frontmatter
  except ImportError:
    return {
      TickResultKey.NAME: name, TickResultKey.EXIT: -1,
      TickResultKey.DURATION_SEC: time.time() - started,
      TickResultKey.ERROR: "frontmatter_parser module unavailable",
    }

  # the two dispatch paths need different setup — an expert job, or a resolved consumer command
  use_command = RoutineKey.COMMAND in cfg
  if not use_command:
    # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
    from expert_runtime import dispatch_job, retire_completed_jobs
    protocols = _routine_protocols(cfg)
    expert = cfg[RoutineKey.EXPERT]
    # the dispatch surface takes a real path; symlinks are resolved so a daemon started through a
    # symlinked checkout writes the same bundle paths as one started through the canonical one
    target_repo = Path(repo).resolve()
    # waiver: routine-config schema field name, single-source set in SCHEMAS, not a reusable cross-module key
    request_template = cfg["request"]
  else:
    # waiver: inline numeric/default literal, not a domain constant
    timeout_sec = cfg.get(RoutineKey.TIMEOUT_SEC, 300)
    # Resolve `command[0]` (plugin name) to the actual bin path once per
    # tick — same resolver `dispatch_subprocess` (subprocess routine type)
    # uses. Without this, `subprocess.run` tries to find the plugin name
    # on `$PATH` and fails with `No such file or directory`.
    try:
      # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
      from runtime_daemon import resolve_routine_command
      resolved_cmd = list(resolve_routine_command(list(cfg[RoutineKey.COMMAND])))
    except Exception as e:
      return {
        TickResultKey.NAME: name, TickResultKey.EXIT: -1,
        TickResultKey.DURATION_SEC: time.time() - started,
        TickResultKey.ERROR: f"md-scan command resolution failed: {e}",
      }
    # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
    import os as _os
    # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
    import subprocess as _subprocess
    subprocess_env = { **_os.environ, **routine_subprocess_env(cfg) }
    # Change-detection state: a candidate whose parent-dir signature is unchanged
    # since the last clean run is skipped instead of re-spawning the consumer
    # every tick. Failed runs are never recorded, so they retry next tick.
    scan_state = _load_scan_state(repo, name)
    next_state: dict = {}
    sig_memo: dict[str, str] = {}

  # each candidate is re-read and re-filtered here — the glob only narrowed the field
  for f in candidates:
    try:
      # waiver: stdlib idiom, not a domain constant
      text = f.read_text(errors = "replace")
    except OSError:
      continue
    fm = parse_frontmatter(text)
    # guard: candidate failed the composite filter — skip
    if not _match_filter(flt, fm, f):
      continue
    try:
      if use_command:
        # waiver: resolved_cmd/timeout_sec/_subprocess/subprocess_env/scan_state/next_state/sig_memo are set in the use_command else-branch, used under the same guard
        # pylint: disable=possibly-used-before-assignment
        sig = _dir_signature(f.parent, walk_files, sig_memo)
        # guard: nothing under this candidate's directory changed since the last
        # clean run — the consumer would re-derive the same no-op; skip the spawn
        if scan_state.get(str(f)) == sig:
          next_state[str(f)] = sig
          unchanged += 1
          continue
        # Blocking — one process at a time per tick. The daemon's main loop is
        # intentionally serial: parallel spawns are a strict no-no across the
        # runtime.
        proc = _subprocess.run(
          [ *resolved_cmd, str(f) ],
          cwd = str(repo),
          timeout = timeout_sec,
          capture_output = True,
          text = True,
          env = subprocess_env,
          check = False,
        )
        if proc.returncode != 0:
          tail = (proc.stderr or "")[-500:].strip()
          errors.append({
            "file": str(f),
            TickResultKey.EXIT: proc.returncode,
            "stderr_tail": tail,
          })
          continue
        # Record the pre-run signature: the consumer's own edits shift the dir
        # signature, so the next tick re-runs once more and settles on a no-op.
        next_state[str(f)] = sig
        dispatched += 1
      else:
        request = _render_template(
          request_template, { "file": str(f) },
        )
        # retire this key's finished bundle first: md-scan never reads a
        # response back, so a prior attempt that completed (success or error)
        # would otherwise hold the dedup slot forever and block re-dispatch.
        # The candidate still matches the filter here, so the transition the
        # prior job was meant to drive did not take → retry. In-flight bundles
        # are left intact so a live job is never duplicated.
        retire_completed_jobs(
          target_repo, expert, str(f),
        )
        result = dispatch_job(
          target_repo, expert, request,
          protocols = protocols,
          dedup_key = str(f),
          # md-scan is in-place by contract (the consumer edits the file
          # where it lies) → the dispatched expert may write + commit in
          # place (Bug 87). Default True; a routine opts out of in-place
          # writes with `can_commit_in_repo: false` in its config.
          can_commit_in_repo = cfg.get(JobConfigKey.CAN_COMMIT_IN_REPO, True),
        )
        # waiver: small internal subkey, not a reusable domain key
        if result.get("status") == "already-queued":
          skipped += 1
        else:
          dispatched += 1
    except Exception as e:
      errors.append({
        "file": str(f),
        TickResultKey.EXIT: -1,
        "stderr_tail": f"dispatch raised: {e}",
      })
      continue

  # persist the change-detection state on the command path, and only when it actually moved
  # waiver: scan_state/next_state are set in the use_command else-branch, used under the same guard
  # pylint: disable=possibly-used-before-assignment
  if use_command and next_state != scan_state:
    _save_scan_state(repo, name, next_state)
  # Surface aggregated per-file errors in the routine result. Exit code is
  # non-zero only when EVERY candidate failed (= the whole tick was lost) so
  # operators can distinguish "one fixture broken" from "the routine is
  # down". A mixed pass returns exit=0 with `errors=[…]` for visibility.
  total_handled = dispatched + skipped + unchanged
  if errors and total_handled == 0:
    first = errors[0]
    return {
      TickResultKey.NAME: name,
      TickResultKey.EXIT: first.get(TickResultKey.EXIT, 1) or 1,
      TickResultKey.DURATION_SEC: time.time() - started,
      "dispatched_count": dispatched,
      "skipped_count": skipped,
      "errors_count": len(errors),
      "errors": errors[:10],
      TickResultKey.ERROR: (
        f"md-scan: all {len(errors)} candidate(s) failed; "
        # waiver: small internal subkey, not a reusable domain key
        f"first at {first['file']}: {first.get('stderr_tail', '')[:200]}"
      ),
    }
  result = {
    TickResultKey.NAME: name, TickResultKey.EXIT: 0,
    TickResultKey.DURATION_SEC: time.time() - started,
    "dispatched_count": dispatched,
    "skipped_count": skipped,
    # waiver: small internal subkey, not a reusable domain key
    "unchanged_count": unchanged,
  }
  if errors:
    # waiver: small internal subkey, not a reusable domain key
    result["errors_count"] = len(errors)
    # waiver: small internal subkey, not a reusable domain key
    result["errors"] = errors[:10]
  return result
