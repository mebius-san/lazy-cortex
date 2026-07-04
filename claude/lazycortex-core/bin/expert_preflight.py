"""
Launchability preflight for routine-dispatched experts.

Validates that every expert a routine dispatches (inbox / schedule / git /
md-scan routines carrying an `expert` key) is actually launchable: its spawn
config is well-formed, its agent reference resolves, its declared aspects and
protocols resolve, and its optional per-expert MCP servers initialize without
hanging. The dynamic probe emulates the real expert launch by building the
command line through `expert_pump.build_expert_argv` — the same builder the
pump uses — but with a trivial prompt that does no real work, so a broken
`mcp_config` (a server that times out at init, needs auth, or fails to spawn)
is surfaced fast instead of eating a live routine's wall timeout.

Emits a JSON verdict document to stdout; the `lazy-runtime.preflight` skill owns
the log write, the operator-facing table, and any settings fix. This bin never
mutates settings and always exits 0 on a completed run — the verdict travels in
the JSON, not the exit code (non-zero is reserved for invocation errors).
"""
from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from expert_pump import build_expert_argv, _normalize_mcp_config, _normalize_setting_sources, _VALID_SETTING_SOURCES
from lazy_settings import load_section
# waiver: ReferenceError is reference_resolver's domain exception, not the builtin
from reference_resolver import resolve, ReferenceError  # pylint: disable=redefined-builtin
from constants import JobConfigKey, RoutineKey, SettingsFile, SettingsKey

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Routine types whose `expert` key names an expert this preflight validates.
# `subprocess` is excluded: it always dispatches a `command`, never an expert.
_EXPERT_ROUTINE_TYPES = frozenset({ "inbox", "schedule", "git", "md-scan" })
# The type discriminator's default when a routine omits `type`.
_DEFAULT_ROUTINE_TYPE = "subprocess"
# The singular protocol key a routine may carry instead of the `protocols` list.
_ROUTINE_PROTOCOL_SINGULAR = "protocol"

# Model tiers accepted without a WARN (mirrors expert_runtime._MODEL_TIERS plus `default`).
_MODEL_TIERS = frozenset({ "haiku", "sonnet", "opus", "default" })

# Wall budget (seconds) for one probe subprocess; a hung server should be
# dropped by MCP_TIMEOUT long before this trips. TimeoutExpired past this = hung.
_PROBE_TIMEOUT_SEC = 90
# Per-server MCP init/tool budget handed to the spawn (milliseconds).
_MCP_TIMEOUT_MS = "15000"

# The trivial prompt the probe uses — resolves the agent and exercises MCP init
# without doing any of the expert's real work.
_PROBE_PROMPT = "Reply with exactly PREFLIGHT_OK and use no tools."
_PROBE_OK_TOKEN = "PREFLIGHT_OK"


# ----------------------------------------------------------------------------------------
class Level:
  """
  Severity labels for a static-check finding.

  Attributes:
    INFO: An informational note that does not affect the verdict.
    WARN: A soft finding (e.g. an unrecognized model tier) that does not fail the expert.
    FAIL: A hard finding that fails the expert's verdict.
  """

  INFO = "info"
  WARN = "warn"
  FAIL = "fail"


# ----------------------------------------------------------------------------------------
class Srv:
  """
  Per-server MCP-init classifications parsed from the probe debug log.

  Attributes:
    CONNECTED: The server completed MCP initialization successfully.
    TIMED_OUT: The server did not initialize within the MCP timeout.
    AUTH_REQUIRED: The server needs interactive authentication / login.
    SPAWN_FAILED: The server's launcher command could not be spawned.
    PENDING_APPROVAL: The server's config is awaiting operator approval.
    UNKNOWN: The server's init outcome could not be recognized from the log.
  """

  CONNECTED = "connected"
  TIMED_OUT = "timed-out"
  AUTH_REQUIRED = "auth-required"
  SPAWN_FAILED = "spawn-failed"
  PENDING_APPROVAL = "pending-approval"
  UNKNOWN = "unknown"


# ----------------------------------------------------------------------------------------
class RKey:
  """
  Field names in the per-expert result and its nested finding / server / fix dicts.

  Attributes:
    NAME: The expert or server name.
    STATIC: The static-check finding list.
    DYNAMIC: The dynamic-probe result block, or null when the probe was skipped.
    SETTING_SOURCES: The effective `--setting-sources` scopes the spawn will pass.
    VERDICT: The `ok` / `fail` verdict for the expert.
    FIXES: The proposed-fix list for a failing expert.
    LEVEL: The severity of a static finding.
    MESSAGE: The human-readable text of a static finding.
    EXIT: The probe subprocess exit code.
    DURATION_S: The probe wall duration in seconds.
    TIMED_OUT: Whether the probe hit the wall timeout.
    AGENT_RESOLVED: Whether the probe resolved the agent (vs. the default assistant).
    SERVERS: The per-server classification list of the probe.
    BEST_EFFORT_PLUGIN_DIRS: Whether plugin-dir resolution was left best-effort.
    STATUS: A server's MCP-init status.
    DETAIL: A short human-readable detail line.
    KIND: The fix-proposal kind.
    TARGET: The fix-proposal target locator.
    ACTION: The fix-proposal action description.
  """

  NAME = "name"
  STATIC = "static"
  DYNAMIC = "dynamic"
  SETTING_SOURCES = "setting_sources"
  VERDICT = "verdict"
  FIXES = "fixes"
  LEVEL = "level"
  MESSAGE = "message"
  EXIT = "exit"
  DURATION_S = "duration_s"
  TIMED_OUT = "timed_out"
  AGENT_RESOLVED = "agent_resolved"
  SERVERS = "servers"
  BEST_EFFORT_PLUGIN_DIRS = "best_effort_plugin_dirs"
  STATUS = "status"
  DETAIL = "detail"
  KIND = "kind"
  TARGET = "target"
  ACTION = "action"


# ----------------------------------------------------------------------------------------
class Verdict:
  """
  Verdict labels for a single expert.

  Attributes:
    OK: The expert is launchable with the current config.
    FAIL: The expert has a hard static failure or a failed launch probe.
  """

  OK = "ok"
  FAIL = "fail"


# ----------------------------------------------------------------------------------------
class FixKind:
  """
  Proposal kinds the skill maps to a confirm-then-apply flow.

  Attributes:
    DROP_MCP_SERVER: Remove an offending server from the expert's mcp_config.
    MCP_LOGIN: Authenticate a server manually (cannot be auto-fixed).
    FIX_PATH: Correct or remove a bad mcp_config path.
  """

  DROP_MCP_SERVER = "drop-mcp-server"
  MCP_LOGIN = "mcp-login"
  FIX_PATH = "fix-path"


# Substrings that fingerprint a static finding as a bad mcp_config path (drives fix-path).
_BAD_PATH_MARKERS = ("mcp_config path does not exist", "mcp_config path does not parse as JSON")
# The finding message emitted when the agent reference is missing entirely.
_MSG_MISSING_AGENT = "missing 'agent' reference (spawn would fall back to the default assistant)"
# Prefix of the finding message emitted when the agent reference does not resolve.
_MSG_AGENT_UNRESOLVED = "agent ref does not resolve"
# Substrings that fingerprint the agent-unresolved static findings (gates the probe).
_AGENT_UNRESOLVED_MARKERS = (_MSG_AGENT_UNRESOLVED, _MSG_MISSING_AGENT)

# Server statuses that make a spawn's verdict `fail` when any declared server hits them.
_SRV_BAD = frozenset({ Srv.TIMED_OUT, Srv.AUTH_REQUIRED, Srv.SPAWN_FAILED, Srv.PENDING_APPROVAL })


def _settings_path(repo: Path) -> Path:
  """
  Return the tracked settings-file path for a repository.

  Args:
    repo: Repository root whose `lazy.settings.json` is consulted.

  Returns:
    Path to `<repo>/.claude/lazy.settings.json`.
  """
  return Path(repo) / SettingsFile.REL


def _strip_repo_suffix(expert: str) -> tuple[str, str | None]:
  """
  Split a routine `expert` value into a bare name and optional cross-repo key.

  An `expert@<repo-key>` value targets a sibling repository; this preflight only
  validates local-repo experts, so the caller records the cross-repo key as a
  skipped target rather than resolving it here.

  Args:
    expert: The routine's `expert` value, optionally suffixed with `@<repo-key>`.

  Returns:
    A tuple of the bare expert name and the cross-repo key, or `None` when the
    value carries no `@<repo-key>` suffix.
  """
  # guard: no cross-repo suffix — the whole value is the bare local expert name
  if "@" not in expert:
    return expert, None
  bare, _, repo_key = expert.rpartition("@")
  # guard: a bare `@.` suffix is the canonical synonym for a local expert
  if not repo_key or repo_key == ".":
    return (bare or expert), None
  return bare, repo_key


def collect_target_experts(repo: Path) -> tuple[list[str], list[str]]:
  """
  Enumerate the local experts every expert-shape routine dispatches.

  Walks `routines[*]`, keeps entries whose type is one of inbox / schedule / git
  / md-scan AND that carry an `expert` key (skipping `command`-shape routines),
  strips any `@<repo-key>` cross-repo suffix, and de-duplicates the bare local
  names in first-seen order.

  Args:
    repo: Repository root whose settings are read.

  Returns:
    A tuple of the de-duplicated local expert names and the sorted, de-duplicated
    set of cross-repo `expert@<repo-key>` targets that were skipped.
  """
  routines = load_section(_settings_path(repo), SettingsKey.ROUTINES)
  local: list[str] = []
  skipped: set[str] = set()
  for cfg in routines.values():
    # guard: skip the _version sentinel and any non-dict routine value
    if not isinstance(cfg, dict):
      continue
    rtype = cfg.get(RoutineKey.TYPE, _DEFAULT_ROUTINE_TYPE)
    # guard: only expert-dispatching routine types name an expert to validate
    if rtype not in _EXPERT_ROUTINE_TYPES:
      continue
    expert = cfg.get(RoutineKey.EXPERT)
    # guard: command-shape routine — no expert to validate
    if not expert or not isinstance(expert, str):
      continue
    bare, repo_key = _strip_repo_suffix(expert)
    if repo_key is not None:
      skipped.add(f"{bare}@{repo_key}")
      continue
    # de-dup while preserving first-seen order
    if bare not in local:
      local.append(bare)
  return local, sorted(skipped)


def _routine_protocols_for_expert(repo: Path, expert: str) -> list[str]:
  """
  Collect the protocol references any routine attaches when dispatching an expert.

  Protocols live on the routine (via `protocols` or the singular `protocol`), not
  on the expert, so they are gathered across every routine that dispatches this
  local expert and de-duplicated.

  Args:
    repo: Repository root whose settings are read.
    expert: Bare local expert name whose dispatching routines are scanned.

  Returns:
    The de-duplicated protocol references, in first-seen order.
  """
  routines = load_section(_settings_path(repo), SettingsKey.ROUTINES)
  out: list[str] = []
  for cfg in routines.values():
    # guard: skip the _version sentinel and any non-dict routine value
    if not isinstance(cfg, dict):
      continue
    routine_expert = cfg.get(RoutineKey.EXPERT)
    # guard: routine does not name a string expert
    if not isinstance(routine_expert, str):
      continue
    bare, _repo_key = _strip_repo_suffix(routine_expert)
    # guard: routine dispatches a different expert
    if bare != expert:
      continue
    refs = cfg.get(RoutineKey.PROTOCOLS)
    if isinstance(refs, list):
      for r in refs:
        if isinstance(r, str) and r and r not in out:
          out.append(r)
    single = cfg.get(_ROUTINE_PROTOCOL_SINGULAR)
    if isinstance(single, str) and single and single not in out:
      out.append(single)
  return out


def _finding(level: str, message: str) -> dict:
  """
  Build one static-check finding dict.

  Args:
    level: Severity label from `Level`.
    message: Human-readable description of the finding.

  Returns:
    A `{level, message}` finding dict.
  """
  return { RKey.LEVEL: level, RKey.MESSAGE: message }


def _static_checks(repo: Path, expert: str, entry: dict | None) -> list[dict]:
  """
  Run the no-spawn validation checks for one expert.

  Verifies the expert is registered, its agent reference resolves, each declared
  aspect and each dispatching-routine protocol resolves, each `mcp_config` path
  exists and parses as JSON, and any pinned model is a recognized tier. Missing
  or unresolvable required references are `fail`; an unknown model tier is a
  soft `warn`.

  Args:
    repo: Repository root whose references and settings are consulted.
    expert: Bare local expert name being validated.
    entry: The `experts[<expert>]` settings block, or `None` when unregistered.

  Returns:
    A list of `{level, message}` finding dicts; empty when every check passed.
  """
  findings: list[dict] = []
  # guard: expert not registered in settings — every other check is moot
  if not isinstance(entry, dict):
    findings.append(_finding(Level.FAIL, f"expert '{expert}' not found in settings.experts"))
    return findings

  agent_ref = entry.get(JobConfigKey.AGENT)
  # guard: no agent reference — the spawn silently falls back to the default assistant
  if not agent_ref or not isinstance(agent_ref, str):
    findings.append(_finding(Level.FAIL, _MSG_MISSING_AGENT))
  else:
    try:
      # waiver: cross-module reference-category token, not an internal key
      resolve(agent_ref, category = "agents", repo = repo)
    except ReferenceError as e:
      findings.append(_finding(Level.FAIL, f"{_MSG_AGENT_UNRESOLVED}: {e}"))

  for aspect_ref in (entry.get(JobConfigKey.ASPECTS) or []):
    # guard: skip malformed non-string aspect entries defensively
    if not isinstance(aspect_ref, str) or not aspect_ref:
      continue
    try:
      # waiver: cross-module reference-category token, not an internal key
      resolve(aspect_ref, category = "aspects", repo = repo)
    except ReferenceError as e:
      findings.append(_finding(Level.FAIL, f"aspect ref does not resolve: {e}"))

  for protocol_ref in _routine_protocols_for_expert(repo, expert):
    try:
      # waiver: cross-module reference-category token, not an internal key
      resolve(protocol_ref, category = "protocols", repo = repo)
    except ReferenceError as e:
      findings.append(_finding(Level.FAIL, f"protocol ref does not resolve: {e}"))

  findings.extend(_mcp_config_checks(repo, entry.get(JobConfigKey.MCP_CONFIG)))
  findings.extend(_setting_sources_checks(entry.get(JobConfigKey.SETTING_SOURCES)))

  model = entry.get(JobConfigKey.MODEL)
  if model and isinstance(model, str) and not _model_is_known(repo, model):
    findings.append(_finding(Level.WARN, f"model '{model}' is not a known tier nor present in agent_models"))

  return findings


def _mcp_config_checks(repo: Path, mcp_config: object) -> list[dict]:
  """
  Validate that each declared `mcp_config` path exists and parses as JSON.

  Args:
    repo: Repository root that relative config paths resolve against.
    mcp_config: The expert's `mcp_config` value — a path string, a list of them,
      or a falsy value for a hermetic (zero-server) spawn.

  Returns:
    A list of `{level, message}` finding dicts; empty when every path is present
    and valid, or when no MCP config is declared.
  """
  findings: list[dict] = []
  # guard: hermetic spawn — no MCP config to validate
  if not mcp_config:
    return findings
  # guard: mcp_config must be a path string or a list of them
  if not isinstance(mcp_config, (str, list)):
    # waiver: reporting the type name of an arbitrary settings value; type(x).__name__ is the right idiom — no class-system object
    findings.append(_finding(Level.FAIL, f"mcp_config must be a string or list, got {type(mcp_config).__name__}"))
    return findings
  for cfg_path in _normalize_mcp_config(mcp_config, repo):
    p = Path(cfg_path)
    # guard: declared config path is absent on disk
    if not p.is_file():
      findings.append(_finding(Level.FAIL, f"mcp_config path does not exist: {cfg_path}"))
      continue
    try:
      # waiver: stdlib encoding idiom
      json.loads(p.read_text(encoding = "utf-8"))
    except (OSError, json.JSONDecodeError) as e:
      findings.append(_finding(Level.FAIL, f"mcp_config path does not parse as JSON: {cfg_path} — {e}"))
  return findings


def _setting_sources_checks(setting_sources: object) -> list[dict]:
  """
  Flag any declared `setting_sources` value outside the recognized scope set.

  Emits one `warn` per declared value that is not one of `user` / `project` /
  `local` — the normalizer drops those before they reach the spawn, so the flag
  silently narrows unless the operator is told. The effective scopes themselves
  travel as a result field, not a finding, so a well-formed entry stays clean.

  Args:
    setting_sources: The expert's `setting_sources` value — a scope string, a
      list of them, or a falsy value for the hermetic default.

  Returns:
    A list of `{level, message}` finding dicts; empty when every declared scope
    is recognized or none are declared.
  """
  findings: list[dict] = []
  # guard: only a declared string/list can carry an unrecognized scope
  if not isinstance(setting_sources, (str, list)):
    return findings
  raw = setting_sources.split(",") if isinstance(setting_sources, str) else setting_sources
  for s in raw:
    # guard: skip non-string / empty entries — normalizer drops them silently
    if not isinstance(s, str) or not s.strip():
      continue
    scope = s.strip().lower()
    if scope not in _VALID_SETTING_SOURCES:
      findings.append(_finding(
        Level.WARN, f"setting_sources value '{s}' is not one of user / project / local (dropped)"
      ))
  return findings


def _model_is_known(repo: Path, model: str) -> bool:
  """
  Return whether a pinned model is a recognized tier or an `agent_models` entry.

  Args:
    repo: Repository root whose `agent_models` section is consulted.
    model: The expert's pinned `model` value.

  Returns:
    True when the value is a known tier or appears as a value in any `agent_models`
    group; False otherwise.
  """
  # guard: value is one of the well-known tiers — accept without reading settings
  if model in _MODEL_TIERS:
    return True
  groups = load_section(_settings_path(repo), SettingsKey.AGENT_MODELS)
  for entries in groups.values():
    # guard: skip non-dict group values (the _version sentinel, etc.)
    if not isinstance(entries, dict):
      continue
    if model in entries.values():
      return True
  return False


def _servers_in_config(repo: Path, mcp_config: object) -> list[str]:
  """
  List the server names declared across an expert's MCP-config files.

  Args:
    repo: Repository root that relative config paths resolve against.
    mcp_config: The expert's `mcp_config` value — a path string, a list, or falsy.

  Returns:
    The declared server names in declaration order, de-duplicated; empty when no
    config is declared or no file parses.
  """
  # guard: hermetic spawn — no servers declared
  if not mcp_config or not isinstance(mcp_config, (str, list)):
    return []
  names: list[str] = []
  for cfg_path in _normalize_mcp_config(mcp_config, repo):
    p = Path(cfg_path)
    # guard: unreadable / missing config — static check already flagged it
    if not p.is_file():
      continue
    try:
      # waiver: stdlib encoding idiom
      data = json.loads(p.read_text(encoding = "utf-8"))
    except (OSError, json.JSONDecodeError):
      continue
    # waiver: external MCP-config JSON field name, not an internal key
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if isinstance(servers, dict):
      for name in servers:
        if name not in names:
          names.append(name)
  return names


def _derive_plugin_dirs(repo: Path) -> tuple[str, bool]:
  """
  Best-effort reconstruction of the `LAZYCORTEX_PLUGIN_DIRS` value for a probe.

  The preflight usually runs interactively, not under the daemon, so the daemon's
  env handle is absent. This mirrors the daemon's own resolution: dev-vault plugin
  sources under `<repo>/claude/*/.claude-plugin/plugin.json` first, then the latest
  cached version of each plugin under `~/.claude/plugins/cache/*/<plugin>/<version>/`.

  Args:
    repo: Repository root whose in-repo plugin sources are scanned.

  Returns:
    A tuple of the `os.pathsep`-joined plugin-dir string (possibly empty) and a
    flag that is True when at least one plugin dir was derived; False signals the
    caller to mark plugin-dir resolution as best-effort in the finding.
  """
  dirs: list[str] = []
  # Dev-vault sources take precedence (matches lazy.runtime.sh --dev-mode).
  dev_claude = Path(repo) / "claude"
  # guard: not a dev vault — skip the in-repo source scan
  if dev_claude.is_dir():
    for entry in sorted(dev_claude.iterdir()):
      # waiver: plugin-manifest layout idiom, mirrors reference_resolver / runtime_daemon
      manifest = entry / ".claude-plugin" / "plugin.json"
      if manifest.is_file():
        dirs.append(str(entry.resolve()))
  # Fall back to (and augment with) the plugin cache's latest version per plugin.
  # waiver: filesystem path idiom
  cache = Path.home() / ".claude/plugins/cache"
  if cache.is_dir():
    for registry in sorted(cache.iterdir()):
      # guard: skip non-directory entries in the cache root
      if not registry.is_dir():
        continue
      for plugin in sorted(registry.iterdir()):
        # guard: skip non-directory entries under a registry
        if not plugin.is_dir():
          continue
        versions = [ v for v in plugin.iterdir() if v.is_dir() ]
        # guard: plugin dir exists but has no cached versions
        if not versions:
          continue
        latest = sorted(versions, key = lambda v: v.name, reverse = True)[0]
        resolved = str(latest.resolve())
        if resolved not in dirs:
          dirs.append(resolved)
  return os.pathsep.join(dirs), bool(dirs)


def _probe_env(repo: Path) -> tuple[dict[str, str], bool]:
  """
  Build the environment for a probe spawn, deriving plugin dirs when unset.

  Args:
    repo: Repository root used to derive plugin dirs when the env handle is absent.

  Returns:
    A tuple of the environment mapping and a flag that is True when plugin-dir
    resolution was left best-effort (no `LAZYCORTEX_PLUGIN_DIRS` in the inherited
    env and none could be derived).
  """
  env = os.environ.copy()
  # A hanging MCP server is dropped after MCP_TIMEOUT instead of eating the wall budget.
  # waiver: external Claude Code environment-variable name, not a domain key
  env["MCP_TIMEOUT"] = _MCP_TIMEOUT_MS
  # waiver: external Claude Code environment-variable name, not a domain key
  env["MCP_TOOL_TIMEOUT"] = _MCP_TIMEOUT_MS
  best_effort = False
  # waiver: environment-variable name, not a domain key
  if not env.get("LAZYCORTEX_PLUGIN_DIRS"):
    derived, ok = _derive_plugin_dirs(repo)
    if derived:
      # waiver: environment-variable name, not a domain key
      env["LAZYCORTEX_PLUGIN_DIRS"] = derived
    best_effort = not ok
  return env, best_effort


def _contract_path() -> Path:
  """
  Return the absolute path to the expert-runtime contract system prompt.

  Returns:
    Absolute path to `references/lazy-core.expert-runtime-contract.md` under the
    plugin root, so the probe's system-prompt append matches the real spawn.
  """
  # waiver: filesystem path idiom, not a domain constant
  return (Path(__file__).parent.parent / "references" / "lazy-core.expert-runtime-contract.md").resolve()


# Ordered (marker-tuple, status, detail) rules for classifying a server's init
# outcome from the debug log. Severe outcomes are listed first so a later
# "connected" line cannot mask an earlier failure. Markers are lowercased
# substrings of the real `claude --debug mcp` output.
_CLASSIFY_RULES: tuple[tuple[tuple[str, ...], str, str], ...] = (
  (("timed out", "timeout", "terminal connection error", "failed to connect"),
   Srv.TIMED_OUT, "server timed out during MCP init"),
  (("enoent", "command not found", "no such file"),
   Srv.SPAWN_FAILED, "server command failed to spawn (ENOENT / not found)"),
  (("needs authentication", "unauthorized", "oauth", "401", "requires auth"),
   Srv.AUTH_REQUIRED, "server requires authentication / login"),
  (("pending approval", "pending", "approve"),
   Srv.PENDING_APPROVAL, "server config pending approval"),
  (("successfully connected", "connection established", "initialized", "ready"),
   Srv.CONNECTED, ""),
)


def _classify_server(debug_text: str, server: str) -> tuple[str, str]:
  """
  Classify one declared MCP server's init outcome from the probe debug log.

  Scans the debug-file lines that mention the server against the ordered
  classification rules, preferring the most severe match so a later "connected"
  line cannot mask an earlier failure.

  Args:
    debug_text: Full text of the probe's `--debug-file` output.
    server: The declared server name to classify.

  Returns:
    A tuple of the status and a short human-readable detail line, empty when the
    status is `connected` or `unknown`.
  """
  # guard: no debug output captured — cannot classify from the file
  if not debug_text:
    return Srv.UNKNOWN, "no debug output captured"
  relevant = [ ln for ln in debug_text.splitlines() if server in ln ]
  # guard: server never mentioned in the debug log — leave it unclassified
  if not relevant:
    return Srv.UNKNOWN, "server not mentioned in debug log"
  joined = "\n".join(relevant).lower()
  for markers, status, detail in _CLASSIFY_RULES:
    if any(m in joined for m in markers):
      return status, detail
  return Srv.UNKNOWN, "server mentioned but init outcome not recognized"


def _classify_servers(debug_text: str, declared_servers: list[str], timed_out: bool) -> list[dict]:
  """
  Classify every declared server for one probe run.

  Args:
    debug_text: Full text of the probe's `--debug-file` output.
    declared_servers: The server names declared in the expert's mcp_config.
    timed_out: Whether the probe hit the wall timeout — makes the log untrustworthy.

  Returns:
    A per-server list of `{name, status, detail}` dicts.
  """
  servers: list[dict] = []
  for name in declared_servers:
    # A wall-timeout means the log cannot be trusted — treat every server as timed-out.
    if timed_out:
      servers.append({
        RKey.NAME: name, RKey.STATUS: Srv.TIMED_OUT,
        RKey.DETAIL: "probe wall-timeout — server likely hung at init",
      })
      continue
    status, detail = _classify_server(debug_text, name)
    servers.append({ RKey.NAME: name, RKey.STATUS: status, RKey.DETAIL: detail })
  return servers


def _read_debug_file(debug_file: str) -> str:
  """
  Read and then remove a probe's temporary debug-log file.

  Args:
    debug_file: Path to the `--debug-file` the probe wrote.

  Returns:
    The file's text, or an empty string when it could not be read.
  """
  try:
    # waiver: stdlib encoding idiom
    text = Path(debug_file).read_text(encoding = "utf-8", errors = "replace")
  except OSError:
    text = ""
  try:
    os.unlink(debug_file)
  except OSError:
    pass
  return text


def _run_probe(repo: Path, entry: dict) -> dict:
  """
  Emulate one expert launch and classify its MCP init and agent resolution.

  Builds the spawn command line through `expert_pump.build_expert_argv` — the
  same builder the pump uses, so the probed line matches the real spawn — with a
  trivial prompt, `--debug mcp`, and a `--debug-file`. A hung server is bounded
  by `MCP_TIMEOUT`; a probe that still overruns `_PROBE_TIMEOUT_SEC` is treated
  as hung. The verdict logic ok's only when the process exited 0 in budget, no
  declared server hit a bad status, and the agent resolved.

  Args:
    repo: Repository root the probe spawn runs inside.
    entry: The `experts[<expert>]` settings block.

  Returns:
    A dynamic-result dict with `exit`, `duration_s`, `timed_out`, `agent_resolved`,
    a per-server `servers` list, and a `best_effort_plugin_dirs` flag.
  """
  env, best_effort = _probe_env(repo)
  agent_ref = entry.get(JobConfigKey.AGENT) or ""
  mcp_config = entry.get(JobConfigKey.MCP_CONFIG)
  model = entry.get(JobConfigKey.MODEL)
  setting_sources = entry.get(JobConfigKey.SETTING_SOURCES)
  declared_servers = _servers_in_config(repo, mcp_config)

  argv = build_expert_argv(
    repo, env,
    contract_path = _contract_path(), model = model, mcp_config = mcp_config,
    agent_ref = agent_ref, prompt = _PROBE_PROMPT,
    setting_sources = setting_sources,
  )
  # waiver: temp-file naming idiom, not a domain constant
  fd, debug_file = tempfile.mkstemp(prefix = "lazy_preflight_", suffix = ".log")
  os.close(fd)
  # --debug mcp + --debug-file so per-server MCP init is logged for classification.
  # waiver: external Claude Code CLI flags, not internal keys
  argv = [ *argv, "--debug", "mcp", "--debug-file", debug_file ]

  started = time.monotonic()
  timed_out = False
  exit_code: int | None = None
  stdout = ""
  try:
    proc = subprocess.run(
      argv, cwd = repo, env = env,
      capture_output = True, text = True, timeout = _PROBE_TIMEOUT_SEC, check = False,
    )
    exit_code = proc.returncode
    stdout = proc.stdout or ""
  except subprocess.TimeoutExpired as e:
    timed_out = True
    stdout = e.stdout if isinstance(e.stdout, str) else ""
  duration = round(time.monotonic() - started, 2)

  debug_text = _read_debug_file(debug_file)
  servers = _classify_servers(debug_text, declared_servers, timed_out)
  agent_resolved = _PROBE_OK_TOKEN in stdout or (exit_code == 0 and not timed_out)
  return {
    RKey.EXIT: exit_code,
    RKey.DURATION_S: duration,
    RKey.TIMED_OUT: timed_out,
    RKey.AGENT_RESOLVED: bool(agent_resolved),
    RKey.SERVERS: servers,
    RKey.BEST_EFFORT_PLUGIN_DIRS: best_effort,
  }


def _fixes_for(expert: str, static: list[dict], dynamic: dict | None) -> list[dict]:
  """
  Propose concrete fixes for one failing expert.

  Translates bad-path static findings into `fix-path` proposals and each bad
  per-server dynamic status into a `drop-mcp-server` (timed-out / spawn-failed)
  or `mcp-login` (auth-required / pending-approval) proposal. The skill applies
  each only after the operator confirms.

  Args:
    expert: Bare local expert name the fixes target.
    static: The static-check finding list for the expert.
    dynamic: The dynamic-probe result, or `None` when the probe was skipped.

  Returns:
    A list of `{kind, target, action, detail}` fix-proposal dicts; empty when no
    actionable fix applies.
  """
  fixes: list[dict] = []
  for finding in static:
    msg = finding.get(RKey.MESSAGE, "")
    if any(marker in msg for marker in _BAD_PATH_MARKERS):
      fixes.append({
        RKey.KIND: FixKind.FIX_PATH,
        RKey.TARGET: f"{expert}.mcp_config",
        RKey.ACTION: "correct or remove the bad mcp_config path in lazy.settings.json",
        RKey.DETAIL: msg,
      })
  # guard: no probe ran — only static-derived fixes are available
  if not dynamic:
    return fixes
  for srv in dynamic.get(RKey.SERVERS, []):
    status = srv.get(RKey.STATUS)
    name = srv.get(RKey.NAME)
    # guard: healthy or unclassifiable servers need no fix
    if status not in _SRV_BAD:
      continue
    if status in (Srv.TIMED_OUT, Srv.SPAWN_FAILED):
      fixes.append({
        RKey.KIND: FixKind.DROP_MCP_SERVER,
        RKey.TARGET: f"{expert}.mcp_config:{name}",
        RKey.ACTION: f"remove server '{name}' from {expert}'s mcp_config",
        RKey.DETAIL: srv.get(RKey.DETAIL) or status,
      })
    else:
      fixes.append({
        RKey.KIND: FixKind.MCP_LOGIN,
        RKey.TARGET: f"{expert}.mcp_config:{name}",
        RKey.ACTION: f"authenticate the server manually: claude mcp login {name}",
        RKey.DETAIL: srv.get(RKey.DETAIL) or status,
      })
  return fixes


def _verdict_for(static: list[dict], dynamic: dict | None) -> str:
  """
  Compute the pass/fail verdict for one expert from its findings.

  Args:
    static: The static-check finding list for the expert.
    dynamic: The dynamic-probe result, or `None` when the probe was skipped.

  Returns:
    `fail` when any static finding is `fail` or the probe reported a hang, a
    non-zero exit with an unresolved agent, or a bad server status; `ok` otherwise.
  """
  # guard: any hard static failure fails the expert regardless of the probe
  if any(f.get(RKey.LEVEL) == Level.FAIL for f in static):
    return Verdict.FAIL
  # guard: static-only run (no probe) with no hard failure passes
  if not dynamic:
    return Verdict.OK
  # guard: probe hit the wall timeout — hung spawn
  if dynamic.get(RKey.TIMED_OUT):
    return Verdict.FAIL
  # guard: agent never resolved — spawn would fall back to the default assistant
  if not dynamic.get(RKey.AGENT_RESOLVED):
    return Verdict.FAIL
  # guard: any declared server hit a bad init status
  if any(s.get(RKey.STATUS) in _SRV_BAD for s in dynamic.get(RKey.SERVERS, [])):
    return Verdict.FAIL
  return Verdict.OK


def evaluate_expert(repo: Path, expert: str, *, probe: bool) -> dict:
  """
  Evaluate one expert: static checks, optional dynamic probe, verdict, and fixes.

  Args:
    repo: Repository root whose settings and references are consulted.
    expert: Bare local expert name to evaluate.
    probe: When True, run the dynamic launch probe; when False, static checks only.

  Returns:
    A per-expert result dict carrying `name`, `static`, `dynamic` (or `None`),
    `setting_sources`, `verdict`, and `fixes`.
  """
  experts = load_section(_settings_path(repo), SettingsKey.EXPERTS)
  raw_entry = experts.get(expert)
  entry = raw_entry if isinstance(raw_entry, dict) else None
  static = _static_checks(repo, expert, entry)

  raw_sources = entry.get(JobConfigKey.SETTING_SOURCES) if entry is not None else None
  effective_sources = _normalize_setting_sources(
    raw_sources if isinstance(raw_sources, (str, list)) else None
  )

  dynamic: dict | None = None
  # Only probe a registered expert whose agent statically resolves — a probe with
  # a missing agent would spuriously "pass" via the default-assistant fallback.
  agent_resolves = entry is not None and not any(
    any(marker in f.get(RKey.MESSAGE, "") for marker in _AGENT_UNRESOLVED_MARKERS)
    for f in static
  )
  if probe and entry is not None and agent_resolves:
    dynamic = _run_probe(repo, entry)

  verdict = _verdict_for(static, dynamic)
  fixes = _fixes_for(expert, static, dynamic) if verdict == Verdict.FAIL else []
  return {
    RKey.NAME: expert,
    RKey.STATIC: static,
    RKey.DYNAMIC: dynamic,
    RKey.SETTING_SOURCES: effective_sources,
    RKey.VERDICT: verdict,
    RKey.FIXES: fixes,
  }


def preflight(repo: Path, *, expert: str | None, probe: bool) -> dict:
  """
  Run the launchability preflight over one or all expert-shape routines' experts.

  Args:
    repo: Repository root whose settings are read and whose spawns are emulated.
    expert: A single bare local expert to evaluate, or `None` for every target.
    probe: When True, run the dynamic launch probe per expert; when False, static only.

  Returns:
    The full verdict document: `experts` (per-expert results), `skipped_cross_repo`
    (unvalidated `expert@<repo>` targets), and a one-line `summary`.
  """
  repo = Path(repo)
  targets, skipped = collect_target_experts(repo)
  # guard: a single-expert run narrows the target list to just that name
  if expert is not None:
    targets = [ expert ]
    skipped = []

  results = [ evaluate_expert(repo, name, probe = probe) for name in targets ]
  failed = sum(1 for r in results if r[RKey.VERDICT] == Verdict.FAIL)
  mode = "static-only" if not probe else "static+probe"
  summary = f"{len(results)} expert(s) checked ({mode}); {failed} failing, {len(results) - failed} ok"
  if skipped:
    summary += f"; {len(skipped)} cross-repo target(s) skipped"
  return {
    "experts": results,
    "skipped_cross_repo": skipped,
    "summary": summary,
  }


def _cli(argv: list[str]) -> int:
  """
  Parse arguments, run the preflight, and print the JSON verdict document.

  Args:
    argv: Argument vector after the program name.

  Returns:
    Process exit code: 0 on a completed run (verdict travels in the JSON),
    2 on an argument error.
  """
  parser = argparse.ArgumentParser(
    prog = "expert_preflight",
    description = "Validate that routine-dispatched experts are launchable.",
  )
  parser.add_argument("--cwd", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")
  parser.add_argument("--expert", default = None, help = "Evaluate a single expert by bare name")
  parser.add_argument("--no-probe", action = "store_true", help = "Run static checks only (no spawn)")
  args = parser.parse_args(argv)

  repo = Path(args.cwd) if args.cwd else Path(os.environ.get("LAZY_REPO_ROOT", os.getcwd()))
  doc = preflight(repo, expert = args.expert, probe = not args.no_probe)
  print(json.dumps(doc, indent = 2))
  return 0


if __name__ == "__main__":
  sys.exit(_cli(sys.argv[1:]))
