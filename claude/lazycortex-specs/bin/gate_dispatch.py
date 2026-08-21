"""
Job-dispatch support primitives shared by `lazycortex-specs`' own dispatch workers.

`_core_dispatch_job` / `consume_stale_job` queue and retire jobs via the `lazycortex-core` CLI's
`dispatch-job` / `consume-job` subcommands — the § 1c inter-plugin boundary contract in
`dev.plugin-boundaries.md`. `_collect_guideline_paths` names a product's role + wildcard
guideline files for a dispatch bundle; `_collect_decisions_paths` names the same bundle's asset
and owning-product `decisions.md` registries beside them, per
`spec-decisions-design.md` § "How decisions are read" — every job bundle gets both registries
regardless of dispatched role, unlike the guideline lookup's per-role selection. No Python
import of `lazycortex-core` internals. `coordinator_dispatch.py` and `gate_tick.py`'s own
coordinator-job sweep are this module's production callers today — the launch-checkbox ladder
itself is dispatched by the `spec.coordinator` persona directly (its own
`Bash(lazycortex-core dispatch-job ...)` verb), not through a Python primitive here.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import json
import os
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_keys import PlanReview  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402


# ----------------------------------------------------------------------------------------
class _WireKey:
  """
  Top-level keys of the `lazycortex-core dispatch-job` stdin bundle.

  Attributes:
    EXPERT: The dispatched expert's name.
    PAYLOAD: The job payload dict (`kind` / `role` / `request`).
    SOURCE: The repo-relative paths of the source files the pump copies at claim time.
    CONTEXT: The repo-relative paths of the context files the pump copies at claim time.
    RESULT: The list of expected result filenames.
    DEDUP_KEY: The dedup key guarding against a repeat dispatch.
    JOB_ID: The queued job's id, as returned by the CLI.
    STATUS: The dedup-hit token the CLI echoes back on its own response instead of a fresh
      `queue_path` (absent on a fresh dispatch); mirrored file-wise from `lazycortex-core`'s
      `JobStatus.ALREADY_QUEUED` per `dev.plugin-boundaries.md` § 2a rather than imported.
  """

  EXPERT = "expert"
  PAYLOAD = "payload"
  SOURCE = "source"
  CONTEXT = "context"
  RESULT = "result"
  DEDUP_KEY = "dedup_key"
  JOB_ID = "job_id"
  STATUS = "status"


class _PayloadKey:
  """
  Payload keys naming files the expert reads in place rather than receiving as copies.

  Attributes:
    GUIDELINES: Repo-relative paths of the product's role guidelines followed by its wildcard
      ones.
    DECISIONS: Repo-relative paths of the asset's own `decisions.md` followed by the owning
      product's.
  """

  GUIDELINES = "guidelines"
  DECISIONS = "decisions"


# Mirrored dedup-hit status token from `lazycortex-core`'s `constants.JobStatus.ALREADY_QUEUED`,
# read file-wise off the wire response per `dev.plugin-boundaries.md` § 2a.
ALREADY_QUEUED_STATUS = "already-queued"


# ----------------------------------------------------------------------------------------
class _SettingsKey:
  """
  Keys read from `.claude/lazy.settings.json` while resolving guidelines.

  Attributes:
    GUIDELINES: A product record's `guidelines` dict.
    WILDCARD_ROLE: The guidelines role key that applies to every dispatched role.
  """

  GUIDELINES = "guidelines"
  WILDCARD_ROLE = "*"


# Product-record key holding a product's vault-relative spec-content path, per this bin/ tree's
# own per-file small-constant convention (see `gate_tick._write_fm_list`'s docstring) — mirrors
# `resolve_product.py`'s own private `_SPEC_PATH_KEY` rather than importing it.
_SPEC_PATH_KEY = "spec_path"

# `decisions.md` is the on-disk filename at both asset and product level (spec-decisions-design.md
# § "Storage"); the manifest names each registry by its own repo-relative path, and the asset's
# own always precedes the product's, so the shared basename never needs disambiguating.
_DECISIONS_FILENAME = "decisions.md"

_SETTINGS_REL = Path(".claude") / "lazy.settings.json"
_PLUGIN_DIRS_ENV = "LAZYCORTEX_PLUGIN_DIRS"
_REPO_ROOT_ENV = "LAZY_REPO_ROOT"
_CORE_CLI_NAME = "lazycortex-core"
_BIN_DIR = "bin"
_DISPATCH_VERB = "dispatch-job"
_CONSUME_VERB = "consume-job"
_PLUGIN_TREE_DIR = "claude"


def _load_settings(repo: Path) -> dict:
  """
  Read `<repo>/.claude/lazy.settings.json`.

  Args:
    repo: The repository root holding `.claude/lazy.settings.json`.

  Returns:
    Parsed settings dict, or `{}` when the file is absent or unparseable.
  """
  path = repo / _SETTINGS_REL
  # guard: no settings file — nothing to resolve against
  if not path.is_file():
    return {}

  # a malformed file is treated the same as an absent one — every caller already has a fallback
  try:
    return json.loads(path.read_text())
  except json.JSONDecodeError:
    return {}


def _collect_guideline_paths(repo: Path, product_record: dict, role: str) -> tuple[list[str], list[str]]:
  """
  Resolve the product's role guidelines plus the wildcard `"*"` guidelines to repo-relative paths.

  Per `products[<key>].guidelines` (`lazy-spec.product-config` schema), a missing declared path is
  never a silent skip — it is surfaced as a warning string for the caller to log.

  Args:
    repo: The repository root the declared guideline paths are relative to.
    product_record: The owning product's settings record, or `{}` when none was resolved.
    role: The dispatched job's role token — selects `guidelines[role]` in the config.

  Returns:
    A `(paths, warnings)` pair: `paths` holds the repo-relative path of every declared guideline
    that resolves to a file, role-specific ones first; `warnings` names every declared path that
    does not.
  """
  # role-specific guidelines first, then the wildcard set that applies to every role
  guidelines_cfg = (product_record or {}).get(_SettingsKey.GUIDELINES) or {}
  declared = list(guidelines_cfg.get(role) or []) + list(guidelines_cfg.get(_SettingsKey.WILDCARD_ROLE) or [])

  # a path that doesn't resolve is a warning, never a silent drop
  paths: list[str] = []
  warnings: list[str] = []
  for rel in declared:
    path = repo / rel
    if path.is_file():
      paths.append(rel)
    else:
      warnings.append(f"guideline not found: {rel}")
  return paths, warnings


def _collect_decisions_paths(repo: Path, asset_dir: Path | None, product_record: dict) -> list[str]:
  """
  Resolve the asset's and owning product's `decisions.md` registries to repo-relative paths.

  Every dispatched role receives the same decisions registries, regardless of role. The two
  files share a basename, so their order carries which is which: the asset's own registry
  always precedes the product's.

  Args:
    repo: The repository root the product's spec content root, and hence its `spec_path`, is resolved from.
    asset_dir: The asset's own folder holding its `decisions.md`, or `None` for a bundle with no
      owning asset (e.g. a product-level dispatch).
    product_record: The owning product's settings record, or `{}` when none was resolved.

  Returns:
    The repo-relative path of whichever registry resolved to an existing file, the asset's own
    first; a registry that does not exist yet is silently omitted.
  """
  # the asset level, when this bundle has an owning asset — asset_dir already IS the resolved
  # folder, never a token needing translation against a root
  paths: list[str] = []
  if asset_dir is not None:
    asset_decisions = asset_dir / _DECISIONS_FILENAME
    if asset_decisions.is_file():
      paths.append(str(asset_decisions.relative_to(repo)))

  # the product level mirrors the asset level, keyed off the product record's own spec_path —
  # spec_path is content-root-relative (resolve_product.py's own docstring: "vault-relative"),
  # not repo-root-relative, so it resolves against spec_paths.spec_content_root(repo) the same
  # way coordinator_dispatch.py's _resolve_product_note_path does, never bare `repo / spec_path`
  spec_path = (product_record or {}).get(_SPEC_PATH_KEY)
  # a product record with a usable spec_path — absent or malformed simply skips this half
  if isinstance(spec_path, str) and spec_path:
    product_decisions = spec_paths.spec_content_root(repo) / spec_path / _DECISIONS_FILENAME
    if product_decisions.is_file():
      paths.append(str(product_decisions.relative_to(repo)))

  # the two appends above are independent of each other — nothing left to reconcile between them
  return paths


def _resolve_core_cli(repo: Path) -> Path:
  """
  Find the `lazycortex-core` CLI binary.

  Two-stage lookup, per the § 1c inter-plugin boundary contract:

    1. Walk `$LAZYCORTEX_PLUGIN_DIRS` for `<dir>/bin/lazycortex-core`.
    2. Dev-fallback to `<repo>/claude/lazycortex-core/bin/lazycortex-core` —
       this dev vault carries lazycortex-core's own source tree, so a
       session running the plugins straight from `claude/*` (not from an
       installed plugin cache) still resolves the CLI.

  Args:
    repo: The repository root the dev-fallback path is resolved against.

  Returns:
    Absolute path to the resolved `lazycortex-core` binary.

  Raises:
    RuntimeError: When both lookup stages fail to find a binary.
  """
  # Stage 1 — env-declared plugin dirs (set by the daemon for every subprocess routine).
  dirs = os.environ.get(_PLUGIN_DIRS_ENV, "").split(os.pathsep)
  for plugin_dir in dirs:
    # guard: empty path segment (from a trailing/double pathsep) — skip it
    if not plugin_dir:
      continue
    cli = Path(plugin_dir) / _BIN_DIR / _CORE_CLI_NAME
    if cli.is_file():
      return cli

  # Stage 2 — dev-vault-only fallback, deliberate per the task brief — this repo IS
  # lazycortex-core's own source tree, so a session with no plugin cache on the env path
  # (e.g. a direct dev run of the specs plugin) still resolves the CLI without one plugin
  # hardcoding another's installed-cache layout (dev.plugin-boundaries § 2b is about the
  # cache, not this repo's own source tree)
  # waiver: sibling-plugin path reach is intentional here — see the paragraph above
  fallback = repo / _PLUGIN_TREE_DIR / _CORE_CLI_NAME / _BIN_DIR / _CORE_CLI_NAME
  if fallback.is_file():
    return fallback

  # neither stage found a binary — nothing left to try
  raise RuntimeError(
      f"lazycortex-core CLI not resolvable: ${_PLUGIN_DIRS_ENV} yields no match "
      f"and {fallback} is absent from this repo"
  )


def _core_dispatch_job(repo: Path, bundle: dict) -> dict:
  """
  Invoke `lazycortex-core dispatch-job` with a JSON bundle on stdin.

  Args:
    repo: The repository root passed to the CLI as `$LAZY_REPO_ROOT`, so it resolves settings
      and job storage against this repo rather than its own working directory.
    bundle: The dispatch-job wire bundle (see `_WireKey`), serialized to stdin as JSON.

  Returns:
    Parsed JSON response dict from the CLI's stdout.

  Raises:
    RuntimeError: When the CLI exits non-zero.
    json.JSONDecodeError: When the CLI exits zero but its stdout is not valid JSON.
  """
  cli = _resolve_core_cli(repo)
  env = os.environ.copy()
  env[_REPO_ROOT_ENV] = str(repo)
  # `check=False` so a non-zero exit is reported with the actual stdout/stderr below, rather
  # than losing that detail to a bare CalledProcessError
  proc = subprocess.run(
      [str(cli), _DISPATCH_VERB],
      input = json.dumps(bundle),
      capture_output = True,
      text = True,
      env = env,
      check = False,
  )
  if proc.returncode != 0:
    raise RuntimeError(
        f"lazycortex-core {_DISPATCH_VERB} exit={proc.returncode} "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
  return json.loads(proc.stdout)


def consume_stale_job(repo: Path, expert: str, job_id: str) -> None:
  """
  Retire a finished-but-unconsumed job bundle via `lazycortex-core consume-job`, best-effort.

  A dedup hit whose `job_id` is already DONE (`ALREADY_QUEUED_STATUS` alongside a terminal
  marker) keeps blocking every future dispatch under the same dedup key until something calls
  `consume-job` on it — `expert_runtime.dispatch_job`'s own dedup scan documents a DONE-but-not-
  CONSUMED bundle as still active for matching purposes. The caller here has already recorded a
  warning of its own for the stale hit, so per the error-ledger contract this call is fire-and-
  forget: any failure (CLI unresolvable, hung or crashed subprocess) degrades to a silent no-op
  rather than raising, since the caller's own tick already succeeded and will simply retry the
  same key on the next tick.

  Args:
    repo: The repository root the CLI resolves settings and its own binary against.
    expert: The stale bundle's dispatched expert name.
    job_id: The stale bundle's job id.
  """
  # guard: CLI unresolvable — nothing to retire against, degrade to a no-op
  try:
    cli = _resolve_core_cli(repo)
  except RuntimeError:
    return

  # the wire bundle is `{expert, job_id}` per the `consume-job` CLI's published contract
  env = os.environ.copy()
  env[_REPO_ROOT_ENV] = str(repo)
  request = json.dumps({ _WireKey.EXPERT: expert, _WireKey.JOB_ID: job_id })

  # bounded by `PlanReview.START_TIMEOUT_S`, the same ceiling every other best-effort follow-up
  # subprocess in this plugin uses — a hung retirement must not stall the serial daemon loop
  try:
    subprocess.run(
        [str(cli), _CONSUME_VERB],
        input = request,
        capture_output = True,
        text = True,
        env = env,
        timeout = PlanReview.START_TIMEOUT_S,
        check = False,
    )
  # waiver: fire-and-forget best-effort retirement per the error-ledger contract — any subprocess
  # failure (crash, timeout) degrades to a silent no-op, never raises
  except (OSError, subprocess.SubprocessError):
    pass
