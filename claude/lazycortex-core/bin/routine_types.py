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

from constants import (
  JobCollectKey, JobConfigKey, JobErrorCategory, JobStatus, RoutineKey, StateKey, TickResultKey,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  import re
  from pathlib import Path


VALID_TYPES = { "subprocess", "inbox", "schedule", "git", "md-scan" }

# how long a transient-error inbox bundle stays parked before it is retired for a retry —
# matches the doctor's dead-job takeover threshold so both retry paths age out together
TRANSIENT_RETRY_AGE_SEC = 3600.0

# default window a deferred inbox bundle stays parked before its input is re-dispatched.
# A deferral waits on the world changing by hand (an operator creating the record the
# import needs), so the default is a day rather than the transient path's hour; a routine
# overrides it with `deferred_retry_sec`.
DEFERRED_RETRY_AGE_SEC = 86400.0


def _resolve_cross_repo_target(repo: Path, expert: str) -> tuple[str, Path, dict]:
  """
  Resolve `expert@<repo>` syntax into the target repository and dispatch kwargs.

  Used by inbox / schedule / git / md-scan routines to enable
  `cfg.expert = "validator@backend"` cross-repo dispatch. Routines are
  fire-and-forget: bundle uploads, foreign daemon processes, response is
  written but never collected on the local side. This is by design — the
  polling+apply loop lives only in lazy-review writer-loop. Bare expert
  names pass through unchanged: the resolved target equals the local repo.

  Args:
    repo: Path-like reference to the local repository.
    expert: Expert name, optionally suffixed with `@<repo-key>`.

  Returns:
    A tuple `(bare_expert, target_repo, dispatch_kwargs)` where `dispatch_kwargs`
    is `{"dispatched_from": <local>}` for cross-repo dispatch or `{}` for local
    dispatch.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from pathlib import Path as _Path
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from expert_name import parse as _parse_expert_name
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from repo_resolver import resolve as _resolve_target_repo
  bare_expert, repo_key = _parse_expert_name(expert)
  target_repo = _resolve_target_repo(repo, repo_key)
  local = _Path(repo).resolve()
  kwargs = { "dispatched_from": local } if target_repo != local else {}
  return bare_expert, target_repo, kwargs


VALID_GIT_WATCH = {
  "new_commits", "new_files", "changed_files", "deleted_files", "renamed_files",
}

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
      "repo_dir", "remote", "path_filter", "filter",
    },
  },
  "md-scan": {
    "required": { "paths", "interval_sec" },
    "optional": { "command", "expert", "request", "timeout_sec", "filter" },
  },
}

COMMON_ALLOWED = {
  "type", "protocol", "protocols", "priority", "ignore_halt", "isolate", "allow_merge",
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

  Args:
    name: Routine name (used in error messages).
    cfg: Routine configuration dict.

  Raises:
    RoutineConfigError: When the type is unknown, required fields are missing,
      unknown fields are present, the EITHER/OR shape between `command` and
      `expert + request` is violated, or a per-type custom constraint fails.
  """
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

  # the optional flags are type-checked before any consumer reads them
  for flag in ( "isolate", "allow_merge" ):
    # guard: isolate/allow_merge, when present, must be booleans
    if flag in cfg and not isinstance(cfg[flag], bool):
      raise RoutineConfigError(f"routine '{name}': '{flag}' must be a boolean")

  # the optional filter sub-mapping is validated key by key
  # waiver: routine-config schema field name, single-source set in SCHEMAS, not a reusable cross-module key
  flt = cfg.get("filter")
  if flt is not None:
    # guard: filter must be a dict
    if not isinstance(flt, dict):
      raise RoutineConfigError(f"routine '{name}': 'filter' must be a dict")
    # waiver: routine-config schema field name, single-source set in SCHEMAS, not a reusable cross-module key
    fm = flt.get("frontmatter")
    if fm is not None:
      # guard: frontmatter sub-filter must be a dict of {in,not_in} predicates
      if not isinstance(fm, dict):
        raise RoutineConfigError(f"routine '{name}': 'filter.frontmatter' must be a dict")
      for k, pred in fm.items():
        # guard: legacy bare-list/scalar predicate is no longer accepted
        if not isinstance(pred, dict):
          raise RoutineConfigError(
            f"routine '{name}': filter.frontmatter['{k}'] must be {{in:[...],not_in:[...]}}, "
            f"not a bare list/scalar"
          )
        for side in ( "in", "not_in" ):
          # guard: in/not_in, when present, must be a list
          if side in pred and not isinstance(pred[side], list):
            raise RoutineConfigError(
              f"routine '{name}': filter.frontmatter['{k}'].{side} must be a list"
            )
    # waiver: routine-config schema field name, single-source set in SCHEMAS, not a reusable cross-module key
    fn = flt.get("folder_note")
    # guard: folder_note, when present, must be a boolean
    if fn is not None and not isinstance(fn, bool):
      raise RoutineConfigError(f"routine '{name}': 'filter.folder_note' must be a boolean")

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

def _match_frontmatter_filter(flt: dict, frontmatter: dict) -> bool:
  """
  Apply a per-key `{ in, not_in }` frontmatter predicate.

  `in` (when non-empty) is an allow-list; `not_in` (when non-empty) is a
  deny-list. Both AND together, and all keys AND together. `None` in either
  list matches a missing key or an explicit None. No legacy bare-list form.

  Args:
    flt: Per-key predicate dict — `{ <key>: { in: [...], not_in: [...] } }`.
    frontmatter: Parsed frontmatter dict from a candidate file.

  Returns:
    True if every key's allow-list and deny-list both accept the corresponding
    frontmatter value; False otherwise.
  """
  for key, pred in flt.items():
    actual = frontmatter.get(key)
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


def _match_filter(flt: dict, frontmatter: dict, path: object = None) -> bool:
  """
  Apply a composite routine filter against one item.

  Filter shape: `{ "frontmatter": { <key>: { in, not_in } }, "folder_note": <bool> }`.
  Each declared sub-filter must pass (AND semantics). `frontmatter` is evaluated
  against the item's parsed frontmatter; an item without frontmatter parses to `{}`.
  `folder_note` (tri-state) constrains whether the item is a folder note
  (`Path(p).stem == Path(p).parent.name`). When `path` is `None` the item is
  treated as not a folder note.

  Args:
    flt: Composite filter block from the routine config — may be empty.
    frontmatter: Parsed frontmatter dict from the item under evaluation.
    path: Optional file path used for folder-note detection. When absent, the
      `folder_note` predicate treats the item as a non-folder-note.

  Returns:
    True when every declared sub-filter accepts the item; False otherwise. An
    empty filter block accepts everything.
  """
  # waiver: routine-config schema field name, single-source set in SCHEMAS, not a reusable cross-module key
  fm = flt.get("frontmatter")
  # guard: a frontmatter sub-filter is declared — it must pass
  if isinstance(fm, dict) and not _match_frontmatter_filter(fm, frontmatter):
    return False
  # waiver: routine-config schema field name, single-source set in SCHEMAS, not a reusable cross-module key
  want = flt.get("folder_note")
  if want is not None:
    # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
    from pathlib import Path as _Path
    _p = str(path) if path is not None else None
    is_fn = _p is not None and _Path(_p).stem == _Path(_p).parent.name
    # guard: want only folder-notes but this isn't one
    if want and not is_fn:
      return False
    # guard: forbid folder-notes but this is one
    if (not want) and is_fn:
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


def dispatch_inbox(repo: Path, name: str, cfg: dict) -> dict:
  """
  Scan `cfg["inbox_dir"]` and dispatch one job per non-hidden file found.

  Two sub-shapes (validator enforces exactly-one):

    - `expert + request`: each tick performs a reconcile pass followed by a
      dispatch pass. The reconcile pass drains succeeded jobs by unlinking the
      input file and consuming the bundle; failed jobs are left parked — the
      unconsumed bundle's dedup key blocks re-dispatch until an operator
      triages the dead letter. Two kinds of parked bundle age out instead of
      waiting for a triage: a transient failure, once older than
      `TRANSIENT_RETRY_AGE_SEC`, and a deferral, once older than the routine's
      `deferred_retry_sec` (default `DEFERRED_RETRY_AGE_SEC`). Both are retired
      without draining the input, so the same tick re-dispatches the file. The
      dispatch pass submits one job per remaining file, keyed on the file's
      absolute path via `dedup_key` and the `{file}` placeholder in `request`.
      The inbox is the source of truth; the file is never copied into the job
      bundle.
    - `command`: spawn `command + [<absolute-path-to-inbox-file>]` as a
      blocking subprocess per file. The file stays in the inbox until the
      consumer command moves or deletes it — the routine never removes the
      input file itself.

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
    subprocess_env = { **_os.environ, **routine_protocols_env(cfg) }
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
  bare_expert, target_repo, xrepo_kwargs = _resolve_cross_repo_target(repo, expert)

  # how long a deferred bundle waits before its input is offered to the queue again
  # waiver: routine-config schema field name, single-source set in SCHEMAS, not a reusable cross-module key
  deferred_window = float(cfg.get("deferred_retry_sec", DEFERRED_RETRY_AGE_SEC))

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
  for done_job in completed_dedup_jobs(target_repo, bare_expert):
    # guard: stale transient failure — retire the bundle so the input re-dispatches
    if _is_retryable_transient(done_job):
      consume_job(target_repo, bare_expert, done_job[JobCollectKey.JOB_ID], **xrepo_kwargs)
      continue
    # guard: the deferral has waited out its window — offer the input to the queue again
    if _is_returnable_deferral(done_job, window_sec = deferred_window):
      consume_job(target_repo, bare_expert, done_job[JobCollectKey.JOB_ID], **xrepo_kwargs)
      continue
    # guard: failed or still-waiting deferred job — leave the input parked behind its bundle
    if done_job[JobCollectKey.STATUS] != JobStatus.DONE:
      continue
    try:
      # the expert may have filed the input away itself on success; a missing
      # original is the expected post-success state, so unlink is best-effort
      Path(done_job[JobCollectKey.DEDUP_KEY]).unlink()
    except OSError:
      pass
    consume_job(target_repo, bare_expert, done_job[JobCollectKey.JOB_ID], **xrepo_kwargs)

  # every surviving candidate becomes one dispatched job
  dispatched = 0
  for f in candidates:
    # guard: reconcile (or an external actor) drained this file — nothing to send
    if not f.exists():
      continue
    request = _render_template(request_template, { "file": str(f) })
    try:
      result = dispatch_job(
        target_repo, bare_expert, request,
        protocols = protocols,
        dedup_key = str(f),
        **xrepo_kwargs,
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
  bare_expert, target_repo, xrepo_kwargs = _resolve_cross_repo_target(Path(repo), expert)
  dispatch_job(
    target_repo, bare_expert, request,
    protocols = _routine_protocols(cfg),
    **xrepo_kwargs,
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
    - `command`: spawn `command + [<item-as-json>]` as a non-blocking subprocess
      with PID-based dedup. The item-json is a one-line JSON encoding of the
      per-watch item dict (e.g. `{"sha":"...","subject":"...",...}`).

  `last_seen_sha` is tracked in `state.json`'s `git_watch.<name>` block. First
  run records the current ref and dispatches nothing (no history backfill).
  Non-ancestor (force-push / rebase) resets baseline and dispatches nothing.

  `remote` is read from config but ignored by the watch — remote sync is the
  daemon's responsibility (`daemon.git.remote_sync`). The field is kept for
  schema back-compat (vestigial; not rejected).

  Args:
    repo: Path-like reference to the repository.
    name: Routine name.
    cfg: Routine configuration dict.

  Returns:
    The standard tick result dict — `exit = 0` with `dispatched_count` on
    success, `exit = -1` and an `error` field on failure.
  """
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

  # the last-seen sha is per-routine state carried across ticks
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  import runtime_state
  state = runtime_state.load(repo)
  git_state = state.setdefault(StateKey.GIT_WATCH, {}).setdefault(name, {})
  last_seen = git_state.get(StateKey.LAST_SEEN_SHA)

  # guard: first run — record baseline, dispatch nothing
  if last_seen is None:
    runtime_state.update(
      repo,
      lambda s: s.setdefault(StateKey.GIT_WATCH, {}).setdefault(name, {}).update({StateKey.LAST_SEEN_SHA: head_sha})
    )
    # waiver: one-off routine-outcome note/reason token, not an internal key
    return _ok(name, started, dispatched_count = 0, note = "first_run_baseline_recorded")

  # guard: ref hasn't moved since last tick
  if last_seen == head_sha:
    return _ok(name, started, dispatched_count = 0)

  # guard: force-push detected — reset baseline, dispatch nothing
  if not _is_ancestor(work_dir, last_seen, head_sha):
    runtime_state.update(
      repo,
      lambda s: s.setdefault(StateKey.GIT_WATCH, {}).setdefault(name, {}).update({StateKey.LAST_SEEN_SHA: head_sha})
    )
    # waiver: one-off routine-outcome note/reason token, not an internal key
    return _ok(name, started, dispatched_count = 0, note = "force_push_baseline_reset")

  # the watch mode decides what a single item is (a commit, a path, a rename pair)
  items = _compute_git_items(work_dir, last_seen, head_sha, watch, path_filter)

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
    for item in items:
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
    items = kept

  # a command routine receives the items as a subprocess payload, not as jobs
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
    subprocess_env = { **_os.environ, **routine_protocols_env(cfg) }
    for item in items:
      payload = _json.dumps(item, sort_keys = True)
      # blocking — one process at a time, no parallel spawns
      subprocess.run(
        [ *resolved_cmd, payload ],
        cwd = str(repo),
        timeout = timeout_sec,
        capture_output = True,
        text = True,
        env = subprocess_env,
        check = False,
      )
  else:
    expert = cfg[RoutineKey.EXPERT]
    request_template = cfg["request"]
    # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
    from expert_runtime import dispatch_job
    protocols = _routine_protocols(cfg)
    bare_expert, target_repo, xrepo_kwargs = _resolve_cross_repo_target(repo, expert)
    for item in items:
      rendered = _render_template(request_template, item)
      dispatch_job(target_repo, bare_expert, rendered, protocols = protocols, **xrepo_kwargs)

  # the scanned range is closed by advancing the last-seen sha to HEAD
  runtime_state.update(
    repo,
    lambda s: s.setdefault(StateKey.GIT_WATCH, {}).setdefault(name, {}).update({StateKey.LAST_SEEN_SHA: head_sha})
  )
  return _ok(name, started, dispatched_count = len(items))


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
        items.append({ "path": path, "status": status, "sha": sha })
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
          items.append({
            "old_path": old_path,
            "new_path": new_path,
            "sha": sha,
          })
    return items

  # every watch value is handled above, so reaching here means the config is invalid
  raise RoutineConfigError(f"unknown git watch value: {watch!r}")


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
  flag = { "A": "A", "M": "M", "D": "D", "R": "AMDR" }.get(status, "AMDR")
  try:
    out = subprocess.check_output(
      [ "git", "log", f"--diff-filter={flag}",
        "--format=%H", "-1", rng, "--", path ],
      cwd = str(work_dir), text = True,
    ).strip()
    return out or "unknown"
  except subprocess.CalledProcessError:
    # waiver: stdlib idiom, not a domain constant
    return "unknown"


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
    # waiver: routine-config schema field name, single-source set in SCHEMAS, not a reusable cross-module key
    request_template = cfg["request"]
    bare_expert, target_repo, xrepo_kwargs = _resolve_cross_repo_target(repo, expert)
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
    subprocess_env = { **_os.environ, **routine_protocols_env(cfg) }
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
          target_repo, bare_expert, str(f), **xrepo_kwargs,
        )
        result = dispatch_job(
          target_repo, bare_expert, request,
          protocols = protocols,
          dedup_key = str(f),
          # md-scan is in-place by contract (the consumer edits the file
          # where it lies) → the dispatched expert may write + commit in
          # place (Bug 87). Default True; a routine opts out of in-place
          # writes with `can_commit_in_repo: false` in its config.
          can_commit_in_repo = cfg.get(JobConfigKey.CAN_COMMIT_IN_REPO, True),
          **xrepo_kwargs,
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
