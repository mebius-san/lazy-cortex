"""
Routine type taxonomy + per-type schema validation for lazy-core.runtime.

Each entry under `lazy-core.runtime.routines` may carry an optional `type`
field. Default is `subprocess` (current behavior, unchanged). Allowed values:
`subprocess`, `inbox`, `schedule`, `git`, `md-scan`.

Validation is closed-set strict: unknown types or unknown fields raise
RoutineConfigError. Every type accepts EITHER `command` OR `expert` + `request`,
not both, not neither — enforced uniformly via `_validate_command_or_expert`.
"""
from __future__ import annotations

VALID_TYPES = { "subprocess", "inbox", "schedule", "git", "md-scan" }


def _resolve_cross_repo_target(repo, expert: str):
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
  from pathlib import Path as _Path
  from expert_name import parse as _parse_expert_name
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
    "optional": { "command", "expert", "request", "timeout_sec" },
  },
  "schedule": {
    "required": { "cron" },
    "optional": { "command", "expert", "request", "timeout_sec" },
  },
  "git": {
    "required": { "branch", "watch", "interval_sec" },
    "optional": {
      "command", "expert", "request", "timeout_sec",
      "repo_dir", "remote", "path_filter",
    },
  },
  "md-scan": {
    "required": { "paths", "frontmatter_filter", "interval_sec" },
    "optional": { "command", "expert", "request", "timeout_sec" },
  },
}

COMMON_ALLOWED = { "type", "protocol", "protocols", "priority", "ignore_halt" }


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
  p = cfg.get("protocols")
  if isinstance(p, list):
    return list(p)
  single = cfg.get("protocol")
  if isinstance(single, str):
    return [ single ]
  return []


# Separator used inside ``LAZYCORTEX_ROUTINE_PROTOCOLS``. Cannot be ``:``
# because protocol IDs are ``<plugin-name>:<artifact-name>`` and already
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
  has_command = "command" in cfg
  has_expert = "expert" in cfg
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
  Validate one entry from `lazy-core.runtime.routines`.

  Args:
    name: Routine name (used in error messages).
    cfg: Routine configuration dict.

  Raises:
    RoutineConfigError: When the type is unknown, required fields are missing,
      unknown fields are present, the EITHER/OR shape between `command` and
      `expert + request` is violated, or a per-type custom constraint fails.
  """
  rtype = cfg.get("type", "subprocess")
  # guard: unknown routine type — reject before further validation
  if rtype not in VALID_TYPES:
    raise RoutineConfigError(
      f"routine '{name}': unknown type '{rtype}'. "
      f"Valid: {sorted(VALID_TYPES)}."
    )

  schema = SCHEMAS[rtype]
  required = schema["required"]
  optional = schema["optional"]
  allowed = required | optional | COMMON_ALLOWED

  keys = set(cfg)
  missing = required - keys
  # guard: required field(s) absent — closed-set rejection
  if missing:
    raise RoutineConfigError(
      f"routine '{name}' (type={rtype}): missing required field(s): {sorted(missing)}"
    )

  unknown = keys - allowed
  # guard: caller passed an undeclared field — closed-set rejection
  if unknown:
    raise RoutineConfigError(
      f"routine '{name}' (type={rtype}): unknown field(s): {sorted(unknown)}"
    )

  _validate_command_or_expert(name, cfg, rtype)

  if rtype == "git":
    watch = cfg.get("watch")
    # guard: unrecognised git watch mode — closed-set rejection
    if watch not in VALID_GIT_WATCH:
      raise RoutineConfigError(
        f"routine '{name}' (type=git): invalid watch value '{watch}'. "
        f"Valid: {sorted(VALID_GIT_WATCH)}."
      )

  if rtype == "md-scan":
    # guard: paths must be a list of globs
    if not isinstance(cfg.get("paths"), list):
      raise RoutineConfigError(
        f"routine '{name}' (type=md-scan): 'paths' must be a list of globs"
      )
    # guard: frontmatter_filter must be a dict
    if not isinstance(cfg.get("frontmatter_filter"), dict):
      raise RoutineConfigError(
        f"routine '{name}' (type=md-scan): 'frontmatter_filter' must be a dict"
      )


def dispatch_routine(repo, name: str, cfg: dict) -> dict:
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
  rtype = cfg.get("type", "subprocess")
  if rtype == "subprocess":
    from runtime_daemon import dispatch_subprocess
    return dispatch_subprocess(repo, name, cfg)
  if rtype == "inbox":
    return dispatch_inbox(repo, name, cfg)
  if rtype == "schedule":
    return dispatch_schedule(repo, name, cfg)
  if rtype == "git":
    return dispatch_git(repo, name, cfg)
  if rtype == "md-scan":
    return dispatch_md_scan(repo, name, cfg)
  # guard: validator should have caught this — defensive last-resort
  raise RoutineConfigError(f"routine '{name}': unknown type '{rtype}' at dispatch time")


# Per-type handlers — implementations land in their own phases (C/D/E).
# Until then, calling these returns a clean error result so the daemon's
# tick loop doesn't crash; just logs and moves on.

def _match_frontmatter_filter(flt: dict, frontmatter: dict) -> bool:
  """
  Apply an AND-combined frontmatter filter for md-scan.

  Filter shape: `{key: <value-or-list-of-values>}`. The file matches when EVERY
  key in the filter has its frontmatter value present in the accepted-values
  list. `None` in the accepted list matches a missing key OR an explicit `None`
  value. Scalar values in the filter are treated as single-element lists.

  Args:
    flt: Filter dict from the routine config.
    frontmatter: Parsed frontmatter dict from a candidate file.

  Returns:
    True if every filter key accepts the corresponding frontmatter value;
    False otherwise.
  """
  for key, accepted in flt.items():
    if not isinstance(accepted, list):
      accepted = [ accepted ]
    actual = frontmatter.get(key, None)
    # guard: value not in accepted list and not a None-matches-missing exception
    if actual not in accepted and not (None in accepted and actual is None):
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
  import time
  return {
    "name": name,
    "exit": -1,
    "duration_sec": 0.0,
    "error": f"type {rtype!r} not yet implemented",
  }


def _render_template(template, vars: dict):
  """
  Substitute `{field}` placeholders in string values of a JSON-shaped template.

  Walks dicts and lists; runs `str.format(**vars)` on string leaves. Literal `{`
  and `}` must be doubled (`{{`, `}}`). A placeholder referencing a var that
  isn't provided raises `KeyError` — caller treats this as a routine failure
  rather than silently emitting a malformed request.

  Args:
    template: A dict, list, str, or other JSON-shaped value to render.
    vars: Mapping of placeholder names to their substitution values.

  Returns:
    The rendered template with string leaves substituted.

  Raises:
    KeyError: When a string leaf references a placeholder absent from `vars`.
  """
  if isinstance(template, dict):
    return { k: _render_template(v, vars) for k, v in template.items() }
  if isinstance(template, list):
    return [ _render_template(v, vars) for v in template ]
  if isinstance(template, str):
    return template.format(**vars)
  return template


def dispatch_inbox(repo, name: str, cfg: dict) -> dict:
  """
  Scan `cfg["inbox_dir"]` and dispatch one job per non-hidden file.

  Two sub-shapes (validator enforces exactly-one):

    - `expert + request`: move the file into a new job dir under
      `.experts/.jobs/<expert>/<uuid>/source/`, write `request.json` with the
      `{file}` placeholder substituted, touch READY. The file is removed from
      the inbox once the job dir is sealed.
    - `command`: spawn `command + [<absolute-path-to-inbox-file>]` as a
      non-blocking subprocess with PID-based dedup per file. The file stays in
      the inbox until the consumer command moves or deletes it — the routine
      does not clean up after `command`.

  The inbox directory is empty when the routine returns successfully in
  `expert + request` mode (the historical contract).

  Args:
    repo: Path-like reference to the repository.
    name: Routine name.
    cfg: Routine configuration dict.

  Returns:
    The standard tick result dict — `exit = 0` and `dispatched_count = N` on
    success, `exit = -1` and an `error` field on failure.
  """
  import json, time, uuid
  from pathlib import Path
  started = time.time()
  repo = Path(repo)
  inbox_dir = repo / cfg["inbox_dir"]

  # guard: configured inbox dir does not exist — nothing to scan
  if not inbox_dir.exists():
    return {
      "name": name, "exit": 0,
      "duration_sec": time.time() - started,
      "dispatched_count": 0,
      "note": "inbox_dir does not exist",
    }

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

  use_command = "command" in cfg
  if use_command:
    timeout_sec = cfg.get("timeout_sec", 300)
    try:
      from runtime_daemon import resolve_routine_command
      resolved_cmd = list(resolve_routine_command(list(cfg["command"])))
    except Exception as e:
      return {
        "name": name, "exit": -1,
        "duration_sec": time.time() - started,
        "error": f"inbox command resolution failed: {e}",
      }
    import os as _os
    import subprocess as _subprocess
    subprocess_env = { **_os.environ, **routine_protocols_env(cfg) }
    dispatched = 0
    for f in candidates:
      try:
        # blocking — one process at a time, no parallel spawns
        _subprocess.run(
          resolved_cmd + [ str(f.resolve()) ],
          cwd = str(repo),
          timeout = timeout_sec,
          capture_output = True,
          text = True,
          env = subprocess_env,
        )
        dispatched += 1
      except Exception as e:
        return {
          "name": name, "exit": -1,
          "duration_sec": time.time() - started,
          "dispatched_count": dispatched,
          "error": f"inbox subprocess dispatch failed at {f.name}: {e}",
        }
    return {
      "name": name, "exit": 0,
      "duration_sec": time.time() - started,
      "dispatched_count": dispatched,
    }

  expert = cfg["expert"]
  request_template = cfg["request"]
  from expert_runtime import dispatch_job
  protocols = _routine_protocols(cfg)

  dispatched = 0
  for f in candidates:
    request = _render_template(request_template, { "file": f.name })
    try:
      text = f.read_text()
    except OSError as e:
      return {
        "name": name, "exit": -1,
        "duration_sec": time.time() - started,
        "dispatched_count": dispatched,
        "error": f"inbox read failed at {f.name}: {e}",
      }
    try:
      bare_expert, target_repo, xrepo_kwargs = _resolve_cross_repo_target(repo, expert)
      dispatch_job(
        target_repo, bare_expert, request,
        protocols = protocols,
        source = { f.name: text },
        **xrepo_kwargs,
      )
      # remove from inbox now that the source is captured in the job dir
      f.unlink()
      dispatched += 1
    except Exception as e:
      return {
        "name": name, "exit": -1,
        "duration_sec": time.time() - started,
        "dispatched_count": dispatched,
        "error": f"inbox dispatch failed at {f.name}: {e}",
      }

  return {
    "name": name, "exit": 0,
    "duration_sec": time.time() - started,
    "dispatched_count": dispatched,
  }


def dispatch_schedule(repo, name: str, cfg: dict) -> dict:
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
  import time
  from datetime import datetime, timezone
  from pathlib import Path
  started = time.time()

  if "command" in cfg:
    from runtime_daemon import dispatch_subprocess
    sub_cfg = { "command": cfg["command"] }
    if "timeout_sec" in cfg:
      sub_cfg["timeout_sec"] = cfg["timeout_sec"]
    return dispatch_subprocess(Path(repo), name, sub_cfg)

  expert = cfg["expert"]
  request_template = cfg["request"]
  now = datetime.now(timezone.utc)
  request = _render_template(request_template, {
    "cron_fire_ts": now.isoformat(),
    "cron_fire_unix": str(int(now.timestamp())),
  })
  from expert_runtime import dispatch_job
  bare_expert, target_repo, xrepo_kwargs = _resolve_cross_repo_target(Path(repo), expert)
  dispatch_job(
    target_repo, bare_expert, request,
    protocols = _routine_protocols(cfg),
    **xrepo_kwargs,
  )
  return {
    "name": name, "exit": 0,
    "duration_sec": time.time() - started,
    "dispatched_count": 1,
  }


def due_for_schedule(name: str, cfg: dict, now_unix: float, last_run_unix: float) -> bool:
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
  from datetime import datetime, timezone
  from cron import parse, due_since
  spec = parse(cfg["cron"])
  EPOCH = datetime(1970, 1, 1, tzinfo = timezone.utc)
  last_run_dt = (
    datetime.fromtimestamp(last_run_unix, tz = timezone.utc)
    if last_run_unix > 0 else EPOCH
  )
  now_dt = datetime.fromtimestamp(now_unix, tz = timezone.utc)
  return due_since(spec, last_run_dt, now_dt)


def dispatch_git(repo, name: str, cfg: dict) -> dict:
  """
  Watch `<remote>/<branch>` and fire one dispatch per matching item.

  Two sub-shapes (validator enforces exactly-one):

    - `expert + request`: render `request` with the item dict's templating vars
      and dispatch a job to `expert`.
    - `command`: spawn `command + [<item-as-json>]` as a non-blocking subprocess
      with PID-based dedup. The item-json is a one-line JSON encoding of the
      per-watch item dict (e.g. `{"sha":"...","subject":"...",...}`).

  `last_seen_sha` is tracked in `state.json`'s `git_watch.<name>` block. First
  run records the current ref and dispatches nothing (no history backfill).
  Force-push (last_seen_sha not in remote branch history) resets baseline and
  dispatches nothing.

  Args:
    repo: Path-like reference to the repository.
    name: Routine name.
    cfg: Routine configuration dict.

  Returns:
    The standard tick result dict — `exit = 0` with `dispatched_count` on
    success, `exit = -1` and an `error` field on failure.
  """
  import json as _json
  import subprocess, time
  from pathlib import Path
  started = time.time()
  repo = Path(repo)

  work_dir = (repo / cfg.get("repo_dir", ".")).resolve()
  remote = cfg.get("remote", "origin")
  branch = cfg["branch"]
  watch = cfg["watch"]
  path_filter = cfg.get("path_filter")

  # guard: work_dir is not a git repo (worktree-aware probe)
  if not (work_dir / ".git").exists() and not (work_dir.is_dir() and _is_git_dir(work_dir)):
    return _err(name, started, "not_a_git_repo", f"{work_dir} is not a git repo")

  fetch = subprocess.run(
    [ "git", "fetch", "--quiet", remote, branch ],
    cwd = str(work_dir), capture_output = True, text = True,
  )
  # guard: remote fetch failed — surface stderr tail
  if fetch.returncode != 0:
    return _err(name, started, "fetch_failed", fetch.stderr.strip()[-500:])

  try:
    head_sha = subprocess.check_output(
      [ "git", "rev-parse", f"{remote}/{branch}" ],
      cwd = str(work_dir), text = True,
    ).strip()
  except subprocess.CalledProcessError as e:
    return _err(name, started, "rev_parse_failed", str(e))

  import runtime_state
  state = runtime_state.load(repo)
  git_state = state.setdefault("git_watch", {}).setdefault(name, {})
  last_seen = git_state.get("last_seen_sha")

  # guard: first run — record baseline, dispatch nothing
  if last_seen is None:
    git_state["last_seen_sha"] = head_sha
    runtime_state.save(repo, state)
    return _ok(name, started, dispatched_count = 0, note = "first_run_baseline_recorded")

  # guard: ref hasn't moved since last tick
  if last_seen == head_sha:
    return _ok(name, started, dispatched_count = 0)

  # guard: force-push detected — reset baseline, dispatch nothing
  if not _is_ancestor(work_dir, last_seen, head_sha):
    git_state["last_seen_sha"] = head_sha
    runtime_state.save(repo, state)
    return _ok(name, started, dispatched_count = 0, note = "force_push_baseline_reset")

  items = _compute_git_items(work_dir, last_seen, head_sha, watch, path_filter)

  if "command" in cfg:
    timeout_sec = cfg.get("timeout_sec", 300)
    try:
      from runtime_daemon import resolve_routine_command
      resolved_cmd = list(resolve_routine_command(list(cfg["command"])))
    except Exception as e:
      return _err(name, started, "command_resolution_failed", str(e))
    import os as _os
    import subprocess as _subprocess
    subprocess_env = { **_os.environ, **routine_protocols_env(cfg) }
    for item in items:
      payload = _json.dumps(item, sort_keys = True)
      # blocking — one process at a time, no parallel spawns
      _subprocess.run(
        resolved_cmd + [ payload ],
        cwd = str(repo),
        timeout = timeout_sec,
        capture_output = True,
        text = True,
        env = subprocess_env,
      )
  else:
    expert = cfg["expert"]
    request_template = cfg["request"]
    from expert_runtime import dispatch_job
    protocols = _routine_protocols(cfg)
    bare_expert, target_repo, xrepo_kwargs = _resolve_cross_repo_target(repo, expert)
    for item in items:
      rendered = _render_template(request_template, item)
      dispatch_job(target_repo, bare_expert, rendered, protocols = protocols, **xrepo_kwargs)

  git_state["last_seen_sha"] = head_sha
  runtime_state.save(repo, state)
  return _ok(name, started, dispatched_count = len(items))


def _ok(name, started, **extra):
  """
  Build a success tick result dict.

  Args:
    name: Routine name.
    started: Start time as a unix timestamp (used to compute duration).
    **extra: Additional fields merged into the result dict.

  Returns:
    A tick result dict with `exit = 0`, `duration_sec`, and any extra fields.
  """
  import time
  return {
    "name": name, "exit": 0,
    "duration_sec": time.time() - started,
    **extra,
  }


def _err(name, started, error_kind, detail):
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
  import time
  return {
    "name": name, "exit": -1,
    "duration_sec": time.time() - started,
    "error": f"{error_kind}: {detail}",
  }


def _is_git_dir(path) -> bool:
  """
  Check whether the given path is inside a git working tree.

  Uses `git rev-parse --git-dir` rather than just `.git` existence so worktrees
  and bare repos are recognised correctly.

  Args:
    path: Path-like reference to the candidate directory.

  Returns:
    True when `git rev-parse --git-dir` succeeds at `path`; False otherwise.
  """
  import subprocess
  rc = subprocess.run(
    [ "git", "rev-parse", "--git-dir" ],
    cwd = str(path), capture_output = True,
  )
  return rc.returncode == 0


def _is_ancestor(work_dir, ancestor: str, descendant: str) -> bool:
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
  import subprocess
  rc = subprocess.run(
    [ "git", "merge-base", "--is-ancestor", ancestor, descendant ],
    cwd = str(work_dir), capture_output = True,
  )
  return rc.returncode == 0


def _compute_git_items(work_dir, last_seen: str, head_sha: str,
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
  import subprocess
  rng = f"{last_seen}..{head_sha}"
  pathspec = [ "--", path_filter ] if path_filter else []

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

  if watch == "renamed_files":
    out = subprocess.check_output(
      [ "git", "diff", "--name-status", "--find-renames", rng, *pathspec ],
      cwd = str(work_dir), text = True,
    ).strip()
    items = []
    if out:
      for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0].startswith("R"):
          old_path, new_path = parts[1], parts[2]
          sha = _last_change_sha(work_dir, new_path, rng, "R")
          items.append({
            "old_path": old_path,
            "new_path": new_path,
            "sha": sha,
          })
    return items

  raise RoutineConfigError(f"unknown git watch value: {watch!r}")


def _last_change_sha(work_dir, path: str, rng: str, status: str) -> str:
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
    return "unknown"


def dispatch_md_scan(repo, name: str, cfg: dict) -> dict:
  """
  Glob `cfg["paths"]`, filter by frontmatter, dispatch one job per surviving file.

  For each candidate that passes `cfg["frontmatter_filter"]`:

    - `expert + request` shape: dispatch a job to the named expert via
      `expert_runtime.dispatch_job` with `dedup_key = str(f)`. The expert
      receives the absolute path under the `file` key (with any extra keys
      from `request` templated in).
    - `command` shape: spawn `command + [str(f)]` as a subprocess. Dedup via a
      per-routine PID lockfile under `.experts/.subprocess-locks/<routine-name>/<sha>.json`
      so two ticks don't race for the same file. Stale locks (dead PID, or
      older than `timeout_sec`) are replaced.

  In-place semantics: never moves the source file; the consumer reads and edits
  the file where it lies. Per-file errors accumulate; one bad file does NOT
  abort the scan tick for the remaining files. Shared-state errors
  (`frontmatter_parser` missing, command resolution failure) DO abort early —
  those are not per-file conditions and retrying them per file is wasteful
  noise.

  Args:
    repo: Path-like reference to the repository.
    name: Routine name.
    cfg: Routine configuration dict.

  Returns:
    The standard tick result dict — `exit = 0` on a pass (possibly with
    accumulated per-file errors under `errors`), `exit = -1` and an `error`
    field when every candidate failed or a shared-state setup failed.
  """
  import fnmatch
  import os
  import time
  from pathlib import Path
  started = time.time()
  repo = Path(repo)

  paths_globs = cfg["paths"]
  flt = cfg["frontmatter_filter"]

  # Walk + fnmatch — stdlib `glob` and `Path.glob`/`rglob` are avoided here
  # because `**` semantics shifted between Python 3.12 / 3.13 / 3.14.
  # Same shape as lazy-review's _iter_class_files. Dedupe by resolved abs path.
  seen_abs = set()
  candidates = []
  for base, dirs, files in os.walk(str(repo)):
    # guard: never descend into git internals
    dirs[ : ] = [ d for d in dirs if d != ".git" ]
    for fname in files:
      full = Path(base) / fname
      rel = full.relative_to(repo).as_posix()
      for pat in paths_globs:
        # guard: pattern does not match this file
        if not fnmatch.fnmatch(rel, pat):
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

  dispatched = 0
  skipped = 0
  # Per-file errors accumulate; one bad file does NOT abort the scan tick
  # for the remaining files (Bug 59). Shared-state errors (frontmatter_parser
  # missing, command resolution failure) DO abort early — those are not
  # per-file conditions and retrying them per file is wasteful noise.
  errors: list[dict] = []
  try:
    from frontmatter_parser import parse_frontmatter
  except ImportError:
    return {
      "name": name, "exit": -1,
      "duration_sec": time.time() - started,
      "error": "frontmatter_parser module unavailable",
    }

  use_command = "command" in cfg
  if not use_command:
    from expert_runtime import dispatch_job
    protocols = _routine_protocols(cfg)
    expert = cfg["expert"]
    request_template = cfg["request"]
    bare_expert, target_repo, xrepo_kwargs = _resolve_cross_repo_target(repo, expert)
  else:
    timeout_sec = cfg.get("timeout_sec", 300)
    # Resolve `command[0]` (plugin name) to the actual bin path once per
    # tick — same resolver `dispatch_subprocess` (subprocess routine type)
    # uses. Without this, `subprocess.run` tries to find the plugin name
    # on `$PATH` and fails with `No such file or directory`.
    try:
      from runtime_daemon import resolve_routine_command
      resolved_cmd = list(resolve_routine_command(list(cfg["command"])))
    except Exception as e:
      return {
        "name": name, "exit": -1,
        "duration_sec": time.time() - started,
        "error": f"md-scan command resolution failed: {e}",
      }
    import os as _os
    import subprocess as _subprocess
    subprocess_env = { **_os.environ, **routine_protocols_env(cfg) }

  for f in candidates:
    try:
      text = f.read_text(errors = "replace")
    except OSError:
      continue
    fm = parse_frontmatter(text)
    # guard: candidate failed the frontmatter filter — skip
    if not _match_frontmatter_filter(flt, fm):
      continue
    try:
      if use_command:
        # Blocking — one process at a time per tick. The daemon's main loop is
        # intentionally serial: parallel spawns are a strict no-no across the
        # runtime.
        proc = _subprocess.run(
          resolved_cmd + [ str(f) ],
          cwd = str(repo),
          timeout = timeout_sec,
          capture_output = True,
          text = True,
          env = subprocess_env,
        )
        if proc.returncode != 0:
          tail = (proc.stderr or "")[-500:].strip()
          errors.append({
            "file": str(f),
            "exit": proc.returncode,
            "stderr_tail": tail,
          })
          continue
        dispatched += 1
      else:
        request = _render_template(
          request_template, { "file": str(f) },
        )
        result = dispatch_job(
          target_repo, bare_expert, request,
          protocols = protocols,
          dedup_key = str(f),
          **xrepo_kwargs,
        )
        if result.get("status") == "already-queued":
          skipped += 1
        else:
          dispatched += 1
    except Exception as e:
      errors.append({
        "file": str(f),
        "exit": -1,
        "stderr_tail": f"dispatch raised: {e}",
      })
      continue

  # Surface aggregated per-file errors in the routine result. Exit code is
  # non-zero only when EVERY candidate failed (= the whole tick was lost) so
  # operators can distinguish "one fixture broken" from "the routine is
  # down". A mixed pass returns exit=0 with `errors=[…]` for visibility.
  total_handled = dispatched + skipped
  if errors and total_handled == 0:
    first = errors[0]
    return {
      "name": name,
      "exit": first.get("exit", 1) or 1,
      "duration_sec": time.time() - started,
      "dispatched_count": dispatched,
      "skipped_count": skipped,
      "errors_count": len(errors),
      "errors": errors[:10],
      "error": (
        f"md-scan: all {len(errors)} candidate(s) failed; "
        f"first at {first['file']}: {first.get('stderr_tail', '')[:200]}"
      ),
    }
  result: dict = {
    "name": name, "exit": 0,
    "duration_sec": time.time() - started,
    "dispatched_count": dispatched,
    "skipped_count": skipped,
  }
  if errors:
    result["errors_count"] = len(errors)
    result["errors"] = errors[:10]
  return result
