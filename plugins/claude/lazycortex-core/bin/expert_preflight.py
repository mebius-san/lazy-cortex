"""
Launchability preflight for routine-dispatched experts.

Validates that every expert a routine dispatches (inbox / schedule / git /
md-scan routines carrying an `expert` key) is actually launchable: its spawn
config is well-formed, its agent reference resolves, its declared aspects and
protocols resolve, and its optional per-expert MCP servers initialize without
hanging. The dynamic probe launches the expert for real, exactly as a routine
would, with a trivial prompt that does no real work, so a broken `mcp_config`
(a server that times out at init, needs auth, or fails to spawn) is surfaced
fast instead of eating a live routine's wall timeout. Alongside the
per-expert verdicts it reports the checkout-level conditions that make a launch
harmful rather than broken: an inbox already driven by another daemon on this
host, a sandbox whose unsandboxed-retry switch is not recorded closed (fail),
and a sandbox allowlist that does not cover a location its own entries
resolve to (fail for write, warn for read) — a confined spawn is checked
against the resolved path, so every write through such a symlink fails.

Emits a JSON verdict document to stdout; the `lazy-runtime.preflight` skill owns
the log write, the operator-facing table, and any settings fix. This bin never
mutates settings and always exits 0 on a completed run — the verdict travels in
the JSON, not the exit code (non-zero is reserved for invocation errors).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from expert_pump import (  # pylint: disable=import-error
  build_expert_argv,
  _normalize_mcp_config,
  _normalize_setting_sources,
  _VALID_SETTING_SOURCES,
)
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from expert_runtime import resolve_agent_model  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from lazy_settings import load_section, resolve_agent_model_tier  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from plugin_dirs_cli import derive_plugin_dirs  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
import rate_limit_flag  # pylint: disable=import-error
# waiver: ReferenceError is reference_resolver's domain exception, not the builtin
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from reference_resolver import resolve, ReferenceError  # pylint: disable=import-error,redefined-builtin
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from constants import (  # pylint: disable=import-error
  HaltReason,
  InboxGuardKey,
  JobConfigKey,
  RateLimitGuardKey,
  RoutineKey,
  RoutineType,
  SandboxKey,
  SandboxSyncKey,
  SettingsFile,
  SettingsKey,
)
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from external_dirs import is_declared  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from inbox_guard import check_inbox_collision  # pylint: disable=import-error
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
from sandbox_scope import audit  # pylint: disable=import-error

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Routine types whose `expert` key names an expert this preflight validates.
# `subprocess` is excluded: it always dispatches a `command`, never an expert.
_EXPERT_ROUTINE_TYPES = frozenset({ RoutineType.INBOX, "schedule", "git", "md-scan" })
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
class ServerStatus:
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
class ResultKey:
  """
  Field names in the verdict document, the per-expert result, and its nested finding / server / fix dicts.

  Attributes:
    EXPERTS: The per-expert result list of the verdict document.
    SUMMARY: The one-line headline of the verdict document.
    NAME: The expert or server name.
    STATIC: The static-check finding list.
    DYNAMIC: The dynamic-probe result block, or null when the probe was skipped.
    SETTING_SOURCES: The effective `--setting-sources` scopes the spawn will pass.
    VERDICT: The `ok` / `fail` verdict for the expert.
    FIXES: The proposed-fix list for a failing expert.
    REPO: The repository-level finding list, shared by every expert in the checkout.
    LEVEL: The severity of a static finding.
    MESSAGE: The human-readable text of a static finding.
    EXIT: The probe subprocess exit code.
    DURATION_S: The probe wall duration in seconds.
    TIMED_OUT: Whether the probe hit the wall timeout.
    SPAWN_ERROR: Why the probe subprocess could not be spawned, or null when it ran.
    AGENT_RESOLVED: Whether the probe resolved the agent (vs. the default assistant).
    SERVERS: The per-server classification list of the probe.
    BEST_EFFORT_PLUGIN_DIRS: Whether plugin-dir resolution was left best-effort.
    STATUS: A server's MCP-init status.
    DETAIL: A short human-readable detail line.
    KIND: The fix-proposal kind.
    TARGET: The fix-proposal target locator.
    ACTION: The fix-proposal action description.
    SKIPPED: The reason token when the probe was deliberately not run.
  """

  EXPERTS = "experts"
  SUMMARY = "summary"
  NAME = "name"
  STATIC = "static"
  DYNAMIC = "dynamic"
  SETTING_SOURCES = "setting_sources"
  VERDICT = "verdict"
  FIXES = "fixes"
  REPO = "repo"
  LEVEL = "level"
  MESSAGE = "message"
  EXIT = "exit"
  DURATION_S = "duration_s"
  TIMED_OUT = "timed_out"
  SPAWN_ERROR = "spawn_error"
  AGENT_RESOLVED = "agent_resolved"
  SERVERS = "servers"
  BEST_EFFORT_PLUGIN_DIRS = "best_effort_plugin_dirs"
  STATUS = "status"
  DETAIL = "detail"
  KIND = "kind"
  TARGET = "target"
  ACTION = "action"
  SKIPPED = "skipped"


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
    PIN_MODEL: Pin a model tier for an expert that resolves no explicit model.
  """

  DROP_MCP_SERVER = "drop-mcp-server"
  MCP_LOGIN = "mcp-login"
  FIX_PATH = "fix-path"
  PIN_MODEL = "pin-model"


# Prefix of the finding message emitted when a declared mcp_config path is absent on disk.
_MSG_PATH_MISSING = "mcp_config path does not exist"
# Prefix of the finding message emitted when a declared mcp_config path is present but not JSON.
_MSG_PATH_UNPARSABLE = "mcp_config path does not parse as JSON"
# Substrings that fingerprint a static finding as a bad mcp_config path (drives fix-path).
_BAD_PATH_MARKERS = (_MSG_PATH_MISSING, _MSG_PATH_UNPARSABLE)
# The finding message emitted when no explicit model resolves for the expert (drives pin-model).
_MSG_UNPINNED_MODEL = "no explicit model resolves (spawn would inherit the CLI default)"
# The finding message emitted when the agent reference is missing entirely.
_MSG_MISSING_AGENT = "missing 'agent' reference (spawn would fall back to the default assistant)"
# Prefix of the finding message emitted when the agent reference does not resolve.
_MSG_AGENT_UNRESOLVED = "agent ref does not resolve"
# Substrings that fingerprint the agent-unresolved static findings (gates the probe).
_AGENT_UNRESOLVED_MARKERS = (_MSG_AGENT_UNRESOLVED, _MSG_MISSING_AGENT)
# Prefix of the probe's spawn-error message when the CLI binary cannot be started at all.
_MSG_PROBE_UNSPAWNABLE = "probe could not spawn the CLI binary"

# Server statuses that make a spawn's verdict `fail` when any declared server hits them.
_BAD_STATUSES = frozenset({
  ServerStatus.TIMED_OUT, ServerStatus.AUTH_REQUIRED, ServerStatus.SPAWN_FAILED, ServerStatus.PENDING_APPROVAL,
})

# Ordered (marker-tuple, status, detail) rules for classifying a server's init
# outcome from the debug log. Severe outcomes are listed first so a later
# "connected" line cannot mask an earlier failure. Markers are lowercased
# substrings of the real `claude --debug mcp` output.
_CLASSIFY_RULES: tuple[tuple[tuple[str, ...], str, str], ...] = (
  (("timed out", "timeout", "terminal connection error", "failed to connect"),
   ServerStatus.TIMED_OUT, "server timed out during MCP init"),
  (("enoent", "command not found", "no such file"),
   ServerStatus.SPAWN_FAILED, "server command failed to spawn (ENOENT / not found)"),
  (("needs authentication", "unauthorized", "oauth", "401", "requires auth"),
   ServerStatus.AUTH_REQUIRED, "server requires authentication / login"),
  (("pending approval", "pending", "approve"),
   ServerStatus.PENDING_APPROVAL, "server config pending approval"),
  (("successfully connected", "connection established", "initialized", "ready"),
   ServerStatus.CONNECTED, ""),
)


def _resolve_settings_path(repo: Path) -> Path:
  """
  Resolve the tracked settings-file path for a repository.

  Args:
    repo: Repository root whose `lazy.settings.json` is consulted.

  Returns:
    Path to `<repo>/.claude/lazy.settings.json`.
  """
  return Path(repo) / SettingsFile.REL


def _load_rate_guard_cfg(repo: Path) -> dict:
  """
  Load the rate-limit guard configuration from a repository's daemon settings section.

  Notes:
    - Reads `lazy.settings.json` and its local overlay from disk.

  Args:
    repo: Repository root whose `lazy.settings.json` is consulted.

  Returns:
    The guard configuration the daemon section resolves to.

  Raises:
    json.JSONDecodeError: If the tracked `lazy.settings.json` or its local overlay is not valid JSON.
  """
  return rate_limit_flag.config(load_section(_resolve_settings_path(repo), SettingsKey.DAEMON))


def collect_target_experts(repo: Path) -> list[str]:
  """
  Enumerate the experts every expert-shape routine dispatches.

  The result names every expert an expert-dispatching routine can launch, each once; a
  command-shape routine contributes nothing.

  Guarantees:
    - Each expert appears once, in the order its first dispatching routine is declared.

  Notes:
    - Reads `lazy.settings.json` and its local overlay from disk.

  Args:
    repo: Repository root whose settings are read.

  Returns:
    The de-duplicated expert names, in first-seen order.

  Raises:
    json.JSONDecodeError: If the tracked `lazy.settings.json` or its local overlay is not valid JSON.
  """
  seen: list[str] = []

  # Contract:
  # Each expert appears exactly once, in the order its first dispatching routine is declared;
  # the preflight evaluates and renders the targets in that order.

  # walk every routine, keeping the first mention of each expert
  for cfg in load_section(_resolve_settings_path(repo), SettingsKey.ROUTINES).values():
    # guard: skip the _version sentinel and any non-dict routine value
    if not isinstance(cfg, dict):
      continue

    # guard: only expert-dispatching routine types name an expert to validate
    if cfg.get(RoutineKey.TYPE, _DEFAULT_ROUTINE_TYPE) not in _EXPERT_ROUTINE_TYPES:
      continue

    # guard: command-shape routine — no expert to validate
    if not (expert := cfg.get(RoutineKey.EXPERT)) or not isinstance(expert, str):
      continue

    # de-dup while preserving first-seen order
    if expert not in seen:
      seen.append(expert)

  # the targets in first-seen order
  return seen


def _collect_routine_protocols(repo: Path, expert: str) -> list[str]:
  """
  Collect the protocol references any routine attaches when dispatching an expert.

  Protocols live on the routine (via `protocols` or the singular `protocol`), not
  on the expert, so they are gathered across every routine that dispatches this
  expert and de-duplicated.

  Guarantees:
    - Each reference appears once, in the order its first dispatching routine declares it, a
      routine's list before its singular key.

  Notes:
    - Reads `lazy.settings.json` and its local overlay from disk.

  Args:
    repo: Repository root whose settings are read.
    expert: Expert name whose dispatching routines are scanned.

  Returns:
    The de-duplicated protocol references, in first-seen order.

  Raises:
    json.JSONDecodeError: If the tracked `lazy.settings.json` or its local overlay is not valid JSON.
  """
  out: list[str] = []

  # Contract:
  # Each reference appears exactly once, in the order its first dispatching routine declares
  # it, with a routine's list contributing before its singular key; the static checks resolve
  # the references in that order.

  # walk every routine that dispatches this expert, merging its references in declaration order
  for cfg in load_section(_resolve_settings_path(repo), SettingsKey.ROUTINES).values():
    # guard: skip the _version sentinel and any non-dict routine value
    if not isinstance(cfg, dict):
      continue

    # guard: routine does not name a string expert
    if not isinstance(routine_expert := cfg.get(RoutineKey.EXPERT), str):
      continue

    # guard: routine dispatches a different expert
    if routine_expert != expert:
      continue

    # the plural list contributes every non-empty string reference not seen yet
    if isinstance(refs := cfg.get(RoutineKey.PROTOCOLS), list):
      for ref in refs:
        if isinstance(ref, str) and ref and ref not in out:
          out.append(ref)

    # the singular key is merged after the list so a routine may carry either or both
    if isinstance(single := cfg.get(_ROUTINE_PROTOCOL_SINGULAR), str) and single and single not in out:
      out.append(single)

  # the references in first-seen order
  return out


def _inbox_dir_checks(repo: Path, expert: str) -> list[dict]:
  """
  Validate that every declared inbox this expert is dispatched from resolves on disk.

  An inbox routine whose directory is declared as externally sourced but absent or dangling
  cannot dispatch anything, so the expert behind it is not launchable in this checkout. An
  inbox that is simply not created yet is left alone — only a declared path is an error.

  Notes:
    - Reads `lazy.settings.json` and its local overlay from disk, and resolves each declared
      inbox against the filesystem.

  Args:
    repo: Repository root whose routine registry and declaration are read.
    expert: Expert name whose dispatching routines are scanned.

  Returns:
    One `fail` finding per unresolvable declared inbox; empty when every one resolves.

  Raises:
    json.JSONDecodeError: If the tracked `lazy.settings.json` or its local overlay is not valid JSON.
  """
  findings: list[dict] = []

  # every inbox routine dispatching this expert must reach its directory
  for name, cfg in load_section(_resolve_settings_path(repo), SettingsKey.ROUTINES).items():
    # guard: skip the _version sentinel and any non-dict routine value
    if not isinstance(cfg, dict):
      continue

    # guard: only an inbox routine has a directory to resolve
    if cfg.get(RoutineKey.TYPE) != RoutineType.INBOX:
      continue

    # guard: routine does not name a string expert
    if not isinstance(routine_expert := cfg.get(RoutineKey.EXPERT), str):
      continue

    # guard: routine dispatches a different expert
    if routine_expert != expert:
      continue

    # guard: a routine without a string inbox path is caught by schema validation, not here
    if not isinstance(rel := cfg.get(RoutineKey.INBOX_DIR), str) or not rel:
      continue

    # guard: the inbox resolves — nothing to report
    if (repo / rel).exists():
      continue

    # guard: an undeclared inbox may simply not be created yet
    if not is_declared(repo, rel):
      continue

    # a declared inbox that is absent means the external directory never reached this checkout
    findings.append(_build_finding(
      Level.FAIL,
      f"routine '{name}' inbox_dir '{rel}' does not resolve — the declared external "
      f"directory is missing or dangling in this checkout",
    ))

  # one finding per unreachable declared inbox
  return findings


def _repo_checks(repo: Path) -> list[dict]:
  """
  Validate the checkout-level conditions that make a launch harmful or broken.

  Launchability is not only a property of one expert's config: a checkout whose inbox is already
  driven by another daemon on this host dispatches every file twice, and a checkout whose sandbox
  allowlist does not cover a location it is meant to reach fails every write through it silently.
  Both conditions apply to every expert dispatched from this checkout, so they belong in the
  same verdict document rather than in any one expert's per-expert findings.

  Args:
    repo: Repository root whose inbox ownership and sandbox scope are read.

  Returns:
    One `fail` finding per contested inbox, one `fail` when the sandbox's unsandboxed-retry
    switch is not recorded closed, one `fail` per uncovered sandbox write location, plus one
    `warn` per uncovered sandbox read location; empty when the checkout owns every inbox it
    scans and its sandbox scope covers everything it grants with the retry closed (or records
    no scope, or confinement off).
  """
  # a contested inbox is a hard finding on its own; the sandbox audit adds its own rows after it
  return [
    _build_finding(Level.FAIL, f"inbox ownership: {finding[InboxGuardKey.DETAIL]}")
    for finding in check_inbox_collision(repo)
  ] + _sandbox_checks(repo)


def _sandbox_checks(repo: Path) -> list[dict]:
  """
  Validate that the sandbox scope of a checkout grants what its allowlist entries reach.

  A confined spawn is checked against the location the operating system resolves, so an
  entry reached through a symlink permits nothing where the data actually lives: every
  write lands as `Operation not permitted` and every job dispatched into that directory
  fails, one after another, with nothing in the config looking wrong. A checkout with no
  sandbox file spawns unconfined and has nothing to report.

  Args:
    repo: Repository root whose recorded sandbox scope is read.

  Returns:
    One `fail` finding when the unsandboxed-retry switch is not recorded closed, one `fail` per
    uncovered write location and one `warn` per uncovered read location; empty when the recorded
    scope reaches everything with the retry closed, when confinement is recorded as off, or when
    no scope is recorded.
  """
  result = audit(repo)

  # guard: no sandbox file — spawns run unconfined, so no allowlist can be short
  if not result[SandboxSyncKey.PRESENT]:
    return []

  # guard: confinement recorded as off — the allowlist grants nothing and denies nothing
  if result[SandboxSyncKey.ENABLED] is False:
    return []

  # every finding ends with the same remedy — recording the scope again
  remedy = f"run `lazycortex-core sandbox-sync --repo-root {repo}` to record it"

  # the retry hatch is a finding whenever it is not recorded closed — Claude Code defaults it to open;
  # then one finding per uncovered write location and one per uncovered read location
  return ([] if result[SandboxSyncKey.ALLOW_UNSANDBOXED] is False else [
    _build_finding(Level.FAIL, f"sandbox {SandboxKey.ALLOW_UNSANDBOXED} is not recorded as false — a command the "
                               f"sandbox blocks is retried unsandboxed and only meets the permission check, so a "
                               f"confined spawn can still write outside its scope on the second try; {remedy}")
  ]) + [
    _build_finding(Level.FAIL, f"sandbox allowWrite does not cover '{location}' — a confined spawn is checked "
                               f"against the resolved path, so every write through that symlink fails; {remedy}")
    for location in result[SandboxSyncKey.MISSING_WRITE]
  ] + [
    _build_finding(Level.WARN, f"sandbox allowRead does not cover '{location}' — a confined spawn cannot read "
                               f"through that symlink; {remedy}")
    for location in result[SandboxSyncKey.MISSING_READ]
  ]


def _build_finding(level: str, message: str) -> dict:
  """
  Build one static-check finding dict.

  Args:
    level: Severity label from `Level`.
    message: Human-readable description of the finding.

  Returns:
    A `{level, message}` finding dict.
  """
  return { ResultKey.LEVEL: level, ResultKey.MESSAGE: message }


def _has_unresolved_agent(findings: list[dict]) -> bool:
  """
  Report whether a finding list records a missing or unresolvable agent reference.

  Args:
    findings: Static-check finding dicts for one expert.

  Returns:
    True when any finding's message carries an agent-unresolved marker.
  """
  return any(
    any(marker in finding.get(ResultKey.MESSAGE, "") for marker in _AGENT_UNRESOLVED_MARKERS) for finding in findings
  )


def _static_checks(repo: Path, expert: str, entry: dict | None) -> list[dict]:
  """
  Run the no-spawn validation checks for one expert.

  Verifies the expert is registered, its agent reference resolves, each declared
  aspect and each dispatching-routine protocol resolves, each `mcp_config` path
  exists and parses as JSON, any pinned model is a recognized tier, an explicit
  model resolves for the expert either via a pinned model or an `agent_models` entry
  for its agent, and every declared inbox directory it is dispatched from resolves
  on disk. Missing or unresolvable required references and an unresolved model
  are `fail`; an unknown model tier is a soft `warn`.

  Notes:
    - Reads `lazy.settings.json`, its local overlay, the referenced files and each declared
      `mcp_config` file from disk; nothing is written.

  Args:
    repo: Repository root whose references and settings are consulted.
    expert: Bare local expert name being validated.
    entry: The `experts[<expert>]` settings block, or `None` when unregistered.

  Returns:
    A list of `{level, message}` finding dicts; empty when every check passed.

  Raises:
    json.JSONDecodeError: If the tracked `lazy.settings.json` or its local overlay is not valid JSON.
  """
  findings: list[dict] = []

  # guard: expert not registered in settings — every other check is moot
  if not isinstance(entry, dict):
    findings.append(_build_finding(Level.FAIL, f"expert '{expert}' not found in settings.experts"))
    return findings

  # the agent reference is the spawn's identity — without a resolvable one the spawn
  # silently falls back to the default assistant
  agent_ref = entry.get(JobConfigKey.AGENT)

  # an absent reference fails outright; a present one still has to resolve
  if not agent_ref or not isinstance(agent_ref, str):
    findings.append(_build_finding(Level.FAIL, _MSG_MISSING_AGENT))
  else:
    try:
      # waiver: cross-module reference-category token, not an internal key
      resolve(agent_ref, category = "agents", repo = repo)
    except ReferenceError as error:
      findings.append(_build_finding(Level.FAIL, f"{_MSG_AGENT_UNRESOLVED}: {error}"))

  # an aspect that does not resolve costs the spawn part of its instruction set
  for aspect_ref in (entry.get(JobConfigKey.ASPECTS) or []):
    # guard: skip malformed non-string aspect entries defensively
    if not isinstance(aspect_ref, str) or not aspect_ref:
      continue

    # a well-formed reference still has to resolve to a file
    try:
      # waiver: cross-module reference-category token, not an internal key
      resolve(aspect_ref, category = "aspects", repo = repo)
    except ReferenceError as error:
      findings.append(_build_finding(Level.FAIL, f"aspect ref does not resolve: {error}"))

  # a dispatching routine's protocol must resolve or the expert runs without its contract
  for protocol_ref in _collect_routine_protocols(repo, expert):
    # each reference is resolved on its own so one bad protocol does not hide the next
    try:
      # waiver: cross-module reference-category token, not an internal key
      resolve(protocol_ref, category = "protocols", repo = repo)
    except ReferenceError as error:
      findings.append(_build_finding(Level.FAIL, f"protocol ref does not resolve: {error}"))

  # delegate the two structured settings blocks to their own checkers
  findings.extend(_mcp_config_checks(repo, entry.get(JobConfigKey.MCP_CONFIG)))
  findings.extend(_setting_sources_checks(entry.get(JobConfigKey.SETTING_SOURCES)))

  # an unrecognized pin is only a soft warning — the CLI may still accept the alias
  model = entry.get(JobConfigKey.MODEL)
  if model and isinstance(model, str) and not _is_known_model(repo, model):
    findings.append(_build_finding(Level.WARN, f"model '{model}' is not a known tier nor present in agent_models"))

  # Domain(runtime.preflight):
  # # Explicit-model invariant for a dispatchable expert
  # Every expert a routine can actually launch must resolve to one explicit model before it counts
  # as launchable — either a model pinned on the expert itself or a tier recorded for its agent
  # elsewhere in settings. An expert with neither is not merely warned about; it fails outright,
  # because a spawn that resolves no explicit model silently inherits whatever model the operator's
  # own CLI happens to default to at that moment, which drifts unnoticed as that personal default
  # changes and produces a launch nobody actually chose.

  # the invariant is checked only once the agent itself is sound — a missing / unresolvable agent
  # is the actionable defect, and a model finding on top of it would double-fail with a misleading
  # pin-model fix — and only when no pin on the expert already settles it; a sound agent reference
  # is always a non-empty string, so it is handed to the resolver as is
  if (not _has_unresolved_agent(findings) and not (model and isinstance(model, str))
      and resolve_agent_model(repo, agent_ref) is None):
    findings.append(_build_finding(
      Level.FAIL,
      f"{_MSG_UNPINNED_MODEL}: set experts.{expert}.model or add an agent_models entry for '{agent_ref}'",
    ))

  # inbox reachability is the last static gate before the caller sees a verdict
  findings.extend(_inbox_dir_checks(repo, expert))
  return findings


def _mcp_config_checks(repo: Path, mcp_config: object) -> list[dict]:
  """
  Validate that each declared `mcp_config` path exists and parses as JSON.

  Notes:
    - Reads each declared config file from disk and parses it; nothing is written.

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
    # waiver: reporting the type name of an arbitrary settings value; type(x).__name__ is the right idiom —
    # no class-system object exists to name it by
    findings.append(_build_finding(
      Level.FAIL, f"mcp_config must be a string or list, got {type(mcp_config).__name__}",
    ))
    return findings

  # every declared path is checked; the first bad one does not hide the rest
  for cfg_path in _normalize_mcp_config(mcp_config, repo):
    cfg_file = Path(cfg_path)

    # guard: declared config path is absent on disk
    if not cfg_file.is_file():
      findings.append(_build_finding(Level.FAIL, f"{_MSG_PATH_MISSING}: {cfg_path}"))
      continue

    # a present file still has to parse — the spawn would fail on it otherwise
    try:
      # waiver: stdlib encoding idiom
      json.loads(cfg_file.read_text(encoding = "utf-8"))
    except (OSError, json.JSONDecodeError) as error:
      findings.append(_build_finding(Level.FAIL, f"{_MSG_PATH_UNPARSABLE}: {cfg_path} — {error}"))

  # one finding per bad path
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

  # a comma-joined string declares the same scopes a list does
  for source in (setting_sources.split(",") if isinstance(setting_sources, str) else setting_sources):
    # guard: skip non-string / empty entries — normalizer drops them silently
    if not isinstance(source, str) or not source.strip():
      continue

    # an unrecognized scope is dropped by the normalizer, so the operator is told here
    if source.strip().lower() not in _VALID_SETTING_SOURCES:
      findings.append(_build_finding(
        Level.WARN, f"setting_sources value '{source}' is not one of user / project / local (dropped)"
      ))

  # one warning per unrecognized scope
  return findings


def _is_known_model(repo: Path, model: str) -> bool:
  """
  Return whether a pinned model is a recognized tier or an `agent_models` entry.

  Notes:
    - Reads `lazy.settings.json` and its local overlay from disk unless the value is a
      well-known tier.

  Args:
    repo: Repository root whose `agent_models` section is consulted.
    model: The expert's pinned `model` value.

  Returns:
    True when the value is a known tier or appears as the effective tier of any
    `agent_models` entry (bare pin or seed object); False otherwise.

  Raises:
    json.JSONDecodeError: If the tracked `lazy.settings.json` or its local overlay is not valid JSON.
  """
  # guard: value is one of the well-known tiers — accept without reading settings
  if model in _MODEL_TIERS:
    return True

  # any agent_models group naming the value as an effective tier makes it known
  for entries in load_section(_resolve_settings_path(repo), SettingsKey.AGENT_MODELS).values():
    # guard: skip non-dict group values (the _version sentinel, etc.)
    if not isinstance(entries, dict):
      continue

    # unwrap each entry (bare pin or seed object) to its effective tier before comparing;
    # `seeded_from` is bookkeeping and must never make a model count as known
    if any(resolve_agent_model_tier(val) == model for val in entries.values()):
      return True

  # neither a tier nor a recorded model
  return False


def _read_config_servers(repo: Path, mcp_config: object) -> list[str]:
  """
  List the server names declared across an expert's MCP-config files.

  Guarantees:
    - Each server name appears once, in the order the config files declare it.

  Notes:
    - Reads each declared config file from disk; a missing or unparsable file is skipped, since
      the static check reports it.

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

  # Contract:
  # Each server name appears exactly once, in the order the config files declare it — file by
  # file, then entry by entry; the probe classifies and reports the servers in that order.

  # collect the server table of every readable config, file by file
  names: list[str] = []
  for cfg_path in _normalize_mcp_config(mcp_config, repo):
    cfg_file = Path(cfg_path)

    # guard: unreadable / missing config — static check already flagged it
    if not cfg_file.is_file():
      continue

    # a file that does not parse was flagged by the static check too
    try:
      # waiver: stdlib encoding idiom
      data = json.loads(cfg_file.read_text(encoding = "utf-8"))
    except (OSError, json.JSONDecodeError):
      continue

    # the server table is the only part of the config the probe classifies
    # waiver: external MCP-config JSON field name, not an internal key
    if isinstance(data, dict) and isinstance(servers := data.get("mcpServers"), dict):
      for name in servers:
        if name not in names:
          names.append(name)

  # the names in declaration order
  return names


def _build_probe_env(repo: Path) -> tuple[dict[str, str], bool]:
  """
  Build the environment for a probe spawn, deriving plugin dirs when unset.

  Notes:
    - Reads `LAZYCORTEX_PLUGIN_DIRS` from the process environment; when it is unset, scans the
      checkout's plugin sources and the plugin cache to derive it.
    - Returns a copy of the process environment; the caller's environment is left untouched.

  Args:
    repo: Repository root used to derive plugin dirs when the env handle is absent.

  Returns:
    A tuple of the environment mapping and a flag that is True when plugin-dir
    resolution was left best-effort (no `LAZYCORTEX_PLUGIN_DIRS` in the inherited
    env and none could be derived).
  """
  env = os.environ.copy()

  # a hanging MCP server is dropped after MCP_TIMEOUT instead of eating the wall budget
  # waiver: external Claude Code environment-variable name, not a domain key
  env["MCP_TIMEOUT"] = _MCP_TIMEOUT_MS
  # waiver: external Claude Code environment-variable name, not a domain key
  env["MCP_TOOL_TIMEOUT"] = _MCP_TIMEOUT_MS

  # outside the daemon the plugin-dir list is rebuilt; failing that, the probe runs best-effort
  best_effort = False
  # waiver: environment-variable name, not a domain key
  if not env.get("LAZYCORTEX_PLUGIN_DIRS"):
    derived, resolved = derive_plugin_dirs(repo)
    if derived:
      # waiver: environment-variable name, not a domain key
      env["LAZYCORTEX_PLUGIN_DIRS"] = derived
    best_effort = not resolved
  return env, best_effort


def _resolve_contract_path() -> Path:
  """
  Resolve the absolute path to the expert-runtime contract system prompt.

  Returns:
    Absolute path to `references/lazy-core.expert-runtime-contract.md` under the
    plugin root, so the probe's system-prompt append matches the real spawn.
  """
  # waiver: filesystem path idiom, not a domain constant
  return (Path(__file__).parent.parent / "references" / "lazy-core.expert-runtime-contract.md").resolve()


def _classify_server(debug_text: str, server: str) -> tuple[str, str]:
  """
  Classify one declared MCP server's init outcome from the probe debug log.

  The status reflects the most severe outcome the log records for the server, so a benign line
  later in the transcript never hides an earlier failure.

  Args:
    debug_text: Full text of the probe's `--debug-file` output.
    server: The declared server name to classify.

  Returns:
    A tuple of the status and a short human-readable detail line, empty only when the
    status is `connected`.
  """

  # Domain(runtime.preflight):
  # # Severity-first classification of a probed server
  # A server's declared MCP-init outcome is read by scanning every debug-log line that mentions it
  # against a fixed list of outcome markers ordered from most to least severe, and the first
  # matching outcome wins. The order matters because the log is a running transcript, not a final
  # verdict: a server that failed early can still emit an unrelated benign line — including the
  # words for a successful connection — later in the same run, and reading markers in severity order
  # keeps that later line from masking the real failure underneath it.

  # guard: no debug output captured — cannot classify from the file
  if not debug_text:
    return ServerStatus.UNKNOWN, "no debug output captured"

  # guard: server never mentioned in the debug log — leave it unclassified
  if not (relevant := [ line for line in debug_text.splitlines() if server in line ]):
    return ServerStatus.UNKNOWN, "server not mentioned in debug log"

  # the server's lines are lowercased once and scanned rule by rule, most severe first
  joined = "\n".join(relevant).lower()
  for markers, status, detail in _CLASSIFY_RULES:
    if any(marker in joined for marker in markers):
      return status, detail

  # mentioned, but no rule recognized the outcome
  return ServerStatus.UNKNOWN, "server mentioned but init outcome not recognized"


def _classify_servers(debug_text: str, declared_servers: list[str], *, timed_out: bool) -> list[dict]:
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
    # a wall-timeout means the log cannot be trusted — treat every server as timed-out
    if timed_out:
      servers.append({
        ResultKey.NAME: name, ResultKey.STATUS: ServerStatus.TIMED_OUT,
        ResultKey.DETAIL: "probe wall-timeout — server likely hung at init",
      })
      continue

    # otherwise the log decides per server
    status, detail = _classify_server(debug_text, name)
    servers.append({ ResultKey.NAME: name, ResultKey.STATUS: status, ResultKey.DETAIL: detail })

  # one row per declared server, in declaration order
  return servers


def _read_and_unlink_debug_file(debug_file: str) -> str:
  """
  Read and then remove a probe's temporary debug-log file.

  Notes:
    - Deletes the file after reading it; a failed removal is ignored and leaves the file to the OS.

  Args:
    debug_file: Path to the `--debug-file` the probe wrote.

  Returns:
    The file's text, or an empty string when it could not be read.
  """
  # an unreadable log is reported as empty, which classifies every server as unknown
  try:
    # waiver: stdlib encoding idiom
    text = Path(debug_file).read_text(encoding = "utf-8", errors = "replace")
  except OSError:
    text = ""

  # the temp file is litter once read; a failed unlink leaves it to the OS and never fails the probe
  try:
    os.unlink(debug_file)
  except OSError:
    pass

  # the captured transcript
  return text


def _run_probe(repo: Path, entry: dict) -> dict:
  """
  Emulate one expert launch and classify its MCP init and agent resolution.

  The probe launches the expert for real with a trivial prompt, on the same command line the
  pump would use, so a broken MCP server or an unresolvable agent surfaces here instead of inside
  a live routine. A hung server is cut off after its init budget, and a spawn that overruns the
  wall budget is reported as timed out rather than failed. A spawn the host refuses outright —
  most often because the `claude` binary is not on PATH — is reported as a spawn error naming the
  binary, with no exit code and the agent unresolved.

  Notes:
    - Spawns one real `claude` subprocess inside the repository and blocks until it exits or the
      probe wall budget runs out.
    - Writes the MCP debug log to a temporary file and removes it once read, whether or not the
      spawn started.
    - Sets the MCP timeout variables on a copy of the process environment; the caller's environment
      is left untouched.
    - May record the shared rate-limit flag when a probe frame trips the guard; a failed write is
      reported on stderr and never fails the probe.

  Args:
    repo: Repository root the probe spawn runs inside.
    entry: The `experts[<expert>]` settings block.

  Returns:
    A dynamic-result dict with `exit`, `duration_s`, `timed_out`, `spawn_error` (the message, or
    `None` when the spawn started), `agent_resolved`, a per-server `servers` list, and a
    `best_effort_plugin_dirs` flag.

  Raises:
    json.JSONDecodeError: If the tracked `lazy.settings.json` or its local overlay is not valid JSON.
  """
  env, best_effort = _build_probe_env(repo)
  mcp_config = entry.get(JobConfigKey.MCP_CONFIG)

  # build the same command line the pump would spawn, then bolt on MCP debug output
  argv = build_expert_argv(
    repo, env,
    contract_path = _resolve_contract_path(), model = entry.get(JobConfigKey.MODEL), mcp_config = mcp_config,
    agent_ref = entry.get(JobConfigKey.AGENT) or "", prompt = _PROBE_PROMPT,
    setting_sources = entry.get(JobConfigKey.SETTING_SOURCES),
  )

  # the MCP debug log lands in a temp file the probe writes and this run removes once read
  # waiver: temp-file naming idiom, not a domain constant
  handle, debug_file = tempfile.mkstemp(prefix = "lazy_preflight_", suffix = ".log")
  os.close(handle)

  # --debug mcp + --debug-file so per-server MCP init is logged for classification.
  # waiver: external Claude Code CLI flags, not internal keys
  argv = [ *argv, "--debug", "mcp", "--debug-file", debug_file ]

  # the result slots every outcome below fills in: the clock, and the flags a normal exit leaves unset
  started = time.monotonic()
  timed_out = False
  spawn_error: str | None = None
  exit_code: int | None = None
  stdout = ""

  # run the probe spawn under a bounded timeout — an overrun counts as hung, not failed, and a
  # spawn the host refuses (binary not on PATH) counts as a spawn error the verdict reports
  try:
    proc = subprocess.run(
      argv, cwd = repo, env = env,
      capture_output = True, text = True, timeout = _PROBE_TIMEOUT_SEC, check = False,
    )
    exit_code = proc.returncode
    stdout = proc.stdout or ""
  except subprocess.TimeoutExpired as error:
    timed_out = True
    stdout = error.stdout if isinstance(error.stdout, str) else ""
  except OSError as error:
    spawn_error = f"{_MSG_PROBE_UNSPAWNABLE} '{argv[0]}': {error}"

  # the probe's own wall time, read before the frame scan below adds its share
  # waiver: captured before the rate-limit frame scan so the reported duration is the probe's alone
  duration = round(time.monotonic() - started, 2)

  # a probe is a real spawn with the pump's own stream-json argv, so its frames feed the shared
  # rate-limit flag exactly as a job run's do; best-effort — a write failure never fails the probe
  try:
    cfg = _load_rate_guard_cfg(repo)
    if cfg[RateLimitGuardKey.ENABLED]:
      for info in rate_limit_flag.frames(stdout):
        if (trigger := rate_limit_flag.triggered(info, cfg)) is not None:
          # waiver: writer self-identification label, not a reusable domain key
          rate_limit_flag.record(info, trigger, writer = "preflight-probe")
  except OSError as error:
    sys.stderr.write(f"rate-limit guard: probe cannot write flag: {error}\n")

  # turn the raw run into per-server statuses plus the agent-resolution verdict
  return {
    ResultKey.EXIT: exit_code,
    ResultKey.DURATION_S: duration,
    ResultKey.TIMED_OUT: timed_out,
    ResultKey.SPAWN_ERROR: spawn_error,
    ResultKey.AGENT_RESOLVED: _PROBE_OK_TOKEN in stdout or (exit_code == 0 and not timed_out),
    ResultKey.SERVERS: _classify_servers(
      _read_and_unlink_debug_file(debug_file), _read_config_servers(repo, mcp_config), timed_out = timed_out,
    ),
    ResultKey.BEST_EFFORT_PLUGIN_DIRS: best_effort,
  }


def _propose_fixes(expert: str, static: list[dict], dynamic: dict | None) -> list[dict]:
  """
  Propose concrete fixes for one failing expert.

  Translates bad-path static findings into `fix-path` proposals, an unpinned-model
  static finding into a `pin-model` proposal, and each bad per-server dynamic status
  into a `drop-mcp-server` (timed-out / spawn-failed) or `mcp-login` (auth-required /
  pending-approval) proposal. The skill applies each only after the operator confirms.

  Args:
    expert: Bare local expert name the fixes target.
    static: The static-check finding list for the expert.
    dynamic: The dynamic-probe result, or `None` when the probe was skipped.

  Returns:
    A list of `{kind, target, action, detail}` fix-proposal dicts; empty when no
    actionable fix applies.
  """
  fixes: list[dict] = []

  # a static finding proposes a fix when its message fingerprints a bad path or an unpinned model
  for finding in static:
    msg = finding.get(ResultKey.MESSAGE, "")

    # a bad mcp_config path is corrected or removed in settings
    if any(marker in msg for marker in _BAD_PATH_MARKERS):
      fixes.append({
        ResultKey.KIND: FixKind.FIX_PATH,
        ResultKey.TARGET: f"{expert}.mcp_config",
        ResultKey.ACTION: "correct or remove the bad mcp_config path in lazy.settings.json",
        ResultKey.DETAIL: msg,
      })

    # an unpinned model is pinned on the expert or its agent
    if _MSG_UNPINNED_MODEL in msg:
      fixes.append({
        ResultKey.KIND: FixKind.PIN_MODEL,
        ResultKey.TARGET: f"{expert}.model",
        ResultKey.ACTION: (
          f"pin a model tier for expert '{expert}' in .claude/lazy.settings.json "
          f"(agent_models entry for its agent, or experts.{expert}.model)"
        ),
        ResultKey.DETAIL: msg,
      })

  # Domain(runtime.preflight):
  # # Two remedies for an unhealthy server, never one
  # An MCP server that timed out during init or failed to spawn at all gets no login prompt proposed
  # for it — that server is treated as broken beyond the operator's reach from here, and the remedy
  # offered is dropping it from the expert's configuration outright. A server that reports needing
  # authentication or sitting on pending approval is not broken the same way: the server itself
  # answered, only its credentials are missing, so the remedy offered instead is a manual login step
  # the operator can actually complete.

  # guard: no probe ran — only static-derived fixes are available
  if not dynamic:
    return fixes

  # every unhealthy server gets exactly one remedy, chosen by how it failed
  for srv in dynamic.get(ResultKey.SERVERS, []):
    status = srv.get(ResultKey.STATUS)
    name = srv.get(ResultKey.NAME)

    # guard: healthy or unclassifiable servers need no fix
    if status not in _BAD_STATUSES:
      continue

    # a server that never answered is dropped; one that answered but lacks credentials is logged into
    if status in (ServerStatus.TIMED_OUT, ServerStatus.SPAWN_FAILED):
      fixes.append({
        ResultKey.KIND: FixKind.DROP_MCP_SERVER,
        ResultKey.TARGET: f"{expert}.mcp_config:{name}",
        ResultKey.ACTION: f"remove server '{name}' from {expert}'s mcp_config",
        ResultKey.DETAIL: srv.get(ResultKey.DETAIL) or status,
      })
    else:
      fixes.append({
        ResultKey.KIND: FixKind.MCP_LOGIN,
        ResultKey.TARGET: f"{expert}.mcp_config:{name}",
        ResultKey.ACTION: f"authenticate the server manually: claude mcp login {name}",
        ResultKey.DETAIL: srv.get(ResultKey.DETAIL) or status,
      })

  # the proposals in finding order, static ones first
  return fixes


def _compute_verdict(static: list[dict], dynamic: dict | None) -> str:
  """
  Compute the pass/fail verdict for one expert from its findings.

  Args:
    static: The static-check finding list for the expert.
    dynamic: The dynamic-probe result, or `None` when the probe was skipped.

  Returns:
    `fail` when any static finding is `fail` or the probe reported a spawn error, a hang, a
    non-zero exit with an unresolved agent, or a bad server status; `ok` otherwise.
  """

  # Domain(runtime.preflight):
  # # A probe the runtime chose not to run proves nothing; a launch the host refused fails
  # A hard static finding fails an expert outright regardless of whether a probe ran, because a
  # broken reference or an unresolved model is wrong before any spawn is attempted. When a probe was
  # deliberately skipped instead of run — the account's rate-limit window is closed at the moment of
  # the check — its absence carries no verdict weight of its own: the expert passes on its static
  # findings alone rather than being penalized for a diagnostic the runtime chose not to spend. A
  # probe the runtime did try to run but the host refused to launch at all is a different case: an
  # expert that cannot be started cannot serve, so a refused launch fails it just as a probe that ran
  # and went wrong does. A probe that did run fails the expert on a wall-clock hang, an agent that
  # never proved it resolved, or any declared server landing in an unhealthy state.

  # guard: any hard static failure fails the expert regardless of the probe
  if any(finding.get(ResultKey.LEVEL) == Level.FAIL for finding in static):
    return Verdict.FAIL

  # guard: static-only run (no probe) with no hard failure passes
  if not dynamic:
    return Verdict.OK

  # guard: a deliberately skipped probe (rate-limit flag up) is not evidence of failure
  if dynamic.get(ResultKey.SKIPPED):
    return Verdict.OK

  # guard: the probe never started — the host cannot launch the expert at all
  if dynamic.get(ResultKey.SPAWN_ERROR):
    return Verdict.FAIL

  # guard: probe hit the wall timeout — hung spawn
  if dynamic.get(ResultKey.TIMED_OUT):
    return Verdict.FAIL

  # guard: agent never resolved — spawn would fall back to the default assistant
  if not dynamic.get(ResultKey.AGENT_RESOLVED):
    return Verdict.FAIL

  # guard: any declared server hit a bad init status
  if any(srv.get(ResultKey.STATUS) in _BAD_STATUSES for srv in dynamic.get(ResultKey.SERVERS, [])):
    return Verdict.FAIL

  # a probe that ran clean on a clean static pass
  return Verdict.OK


def evaluate_expert(repo: Path, expert: str, *, probe: bool) -> dict:
  """
  Evaluate one expert: static checks, optional dynamic probe, verdict, and fixes.

  Notes:
    - With `probe` true, spawns one real `claude` subprocess inside the repository and blocks
      until it exits or the probe wall budget runs out.
    - May record the shared rate-limit flag when the probe trips the guard; under a raised flag
      the probe is skipped rather than run.

  Args:
    repo: Repository root whose settings and references are consulted.
    expert: Bare local expert name to evaluate.
    probe: When True, run the dynamic launch probe; when False, static checks only.

  Returns:
    A per-expert result dict carrying `name`, `static`, `dynamic` (or `None`),
    `setting_sources`, `verdict`, and `fixes`.

  Raises:
    json.JSONDecodeError: If the tracked `lazy.settings.json` or its local overlay is not valid JSON.
  """
  # the settings block drives every check; an unregistered expert reaches them as None
  raw_entry = load_section(_resolve_settings_path(repo), SettingsKey.EXPERTS).get(expert)
  entry = raw_entry if isinstance(raw_entry, dict) else None
  static = _static_checks(repo, expert, entry)

  # the declared settings scopes, as written; they are normalized into the result below
  raw_sources = entry.get(JobConfigKey.SETTING_SOURCES) if entry is not None else None

  # the probe stays unrun unless it can produce a trustworthy signal
  dynamic: dict | None = None

  # only probe a registered expert whose agent statically resolves — a probe with
  # a missing agent would spuriously "pass" via the default-assistant fallback
  if probe and entry is not None and not _has_unresolved_agent(static):
    # the probe is itself a real `claude -p` spawn — under a raised rate-limit flag it is
    # skipped with an explicit outcome, never run and never counted as a failure; the same repo
    # config gates both sides — the skip here and the frame write inside the probe — so a
    # disabled guard never lets a foreign checkout's record suppress this repo's probes
    if _load_rate_guard_cfg(repo)[RateLimitGuardKey.ENABLED] and rate_limit_flag.is_raised():
      dynamic = { ResultKey.SKIPPED: HaltReason.RATE_LIMIT }
    else:
      dynamic = _run_probe(repo, entry)

  # fixes are proposed only for a failing expert — a passing one has nothing to repair
  verdict = _compute_verdict(static, dynamic)
  return {
    ResultKey.NAME: expert,
    ResultKey.STATIC: static,
    ResultKey.DYNAMIC: dynamic,
    ResultKey.SETTING_SOURCES: _normalize_setting_sources(
      raw_sources if isinstance(raw_sources, (str, list)) else None
    ),
    ResultKey.VERDICT: verdict,
    ResultKey.FIXES: _propose_fixes(expert, static, dynamic) if verdict == Verdict.FAIL else [],
  }


def preflight(repo: Path, *, expert: str | None, probe: bool) -> dict:
  """
  Run the launchability preflight over one or all expert-shape routines' experts.

  Notes:
    - With `probe` true, spawns one real `claude` subprocess per target, one after another, and
      blocks for up to the probe wall budget on each.
    - May record the shared rate-limit flag when a probe trips the guard; once raised, the
      remaining targets skip their probes.

  Args:
    repo: Repository root whose settings are read and whose spawns are emulated.
    expert: A single bare local expert to evaluate, or `None` for every target.
    probe: When True, run the dynamic launch probe per expert; when False, static only.

  Returns:
    The full verdict document: `experts` (per-expert results), `repo` (checkout-level
    findings), and a one-line `summary`.

  Raises:
    json.JSONDecodeError: If the tracked `lazy.settings.json` or its local overlay is not valid JSON.
  """
  repo = Path(repo)

  # a single-expert run evaluates just that name; otherwise every routine-dispatched expert is a target
  targets = [ expert ] if expert is not None else collect_target_experts(repo)

  # evaluate every target, then add the checkout-level findings that belong to no expert
  results = [ evaluate_expert(repo, name, probe = probe) for name in targets ]
  repo_findings = _repo_checks(repo)

  # a one-line headline the operator reads before drilling into the per-expert detail
  failed = sum(1 for result in results if result[ResultKey.VERDICT] == Verdict.FAIL)
  summary = (
    f"{len(results)} expert(s) checked ({'static-only' if not probe else 'static+probe'}); "
    f"{failed} failing, {len(results) - failed} ok"
  )
  if repo_findings:
    summary += f"; {len(repo_findings)} repo-level finding(s)"

  # the verdict document the preflight skill renders
  return {
    ResultKey.EXPERTS: results,
    ResultKey.REPO: repo_findings,
    ResultKey.SUMMARY: summary,
  }


def _cli(argv: list[str]) -> int:
  """
  Parse arguments, run the preflight, and print the JSON verdict document.

  Guarantees:
    - Exits 0 for a completed run regardless of the verdict; a non-zero exit is reserved for an
      invocation error.

  Args:
    argv: Argument vector after the program name.

  Returns:
    Process exit code: 0 on a completed run (verdict travels in the JSON).

  Raises:
    SystemExit: On an argument error, with exit code 2, raised by the argument parser.
  """
  # the preflight's command line: the repo root, an optional single expert, and the probe switch
  # waiver: argparse CLI signature and help strings, not domain keys
  parser = argparse.ArgumentParser(
    prog = "expert_preflight",
    # waiver: argparse CLI help string, not a domain key
    description = "Validate that routine-dispatched experts are launchable.",
  )
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", default = None, help = "Repository root (default: $LAZY_REPO_ROOT or cwd)")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--expert", default = None, help = "Evaluate a single expert by bare name")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--no-probe", action = "store_true", help = "Run static checks only (no spawn)")
  args = parser.parse_args(argv)

  # resolve the repo root, run the preflight, and emit the verdict document as JSON
  # waiver: LAZY_REPO_ROOT is the dispatcher's env contract, not a domain key
  repo = Path(args.cwd) if args.cwd else Path(os.environ.get("LAZY_REPO_ROOT", os.getcwd()))
  print(json.dumps(preflight(repo, expert = args.expert, probe = not args.no_probe), indent = 2))

  # Contract:
  # The process always exits 0 for a completed run; a non-zero exit is reserved for an
  # invocation error such as bad arguments, never for a failing verdict.

  # the verdict travels in the printed document, not in the exit code
  return 0


if __name__ == "__main__":
  sys.exit(_cli(sys.argv[1:]))
