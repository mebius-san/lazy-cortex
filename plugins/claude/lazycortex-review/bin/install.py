"""Bootstrap lazy-review into a consumer repo.

Writes (or leaves alone if present) the following pieces of state:

- `<repo>/.claude/lazy.settings.json` — adds the `review` section and the
  `experts` entries for the plugin's own system experts if absent (existing
  values are never overwritten, except that `review.watch_root` is widened to
  cover every review class), and reconciles the
  `routines["lazy-review.collect"]` / `routines["lazy-review.coordinator-watch"]` /
  `routines["lazy-review.sanitize"]` trio through the core CLI's
  `reconcile-routine` verb: the keys this plugin owns are corrected to the shipped
  value on every run, every other key the registration carries is the operator's
  and is left as it stands.
- `<repo>/.experts/.jobs/` and `<repo>/.logs/lazy-review/runs/`
  directories.

On a repo installed before the coordinator migration the script also
retires the `lazy-review.scan` routine, derives `review.watch_root` from
the paths that routine used to scan, and drops the `history` expert link
from every review class. Every run widens `review.watch_root` until each
review class's globs fall under it. `review._version` is left alone throughout —
`lazycortex-core` owns that ladder and stamps it from its own migrations.

The settings file is read and written only through the core CLI's settings verbs; this script
never opens it itself, and a file the verbs cannot read or write ends the run as a refusal.

The CLI prints a summary of what changed.

This script does NOT touch `.gitignore`; the consumer is told what
entries to add (see the install SKILL.md).
"""
from __future__ import annotations

import argparse
import copy
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
import doc_class as _doc_class  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import git_ops as _git_ops  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from keys import JobKey, Paths, ReviewKey  # noqa: E402  # pylint: disable=import-error,wrong-import-position


# ----------------------------------------------------------------------------------------
class _SettingsKey:
  """
  Settings-file section and field names this script reads but no other module needs.

  Attributes:
    ROUTINES: The routine-registry section.
    DAEMON: The runtime-daemon section.
    GIT: The daemon's git block.
    BASE_BRANCH: The daemon's base-branch field inside that block.
  """

  # The routine-registry section.
  ROUTINES = "routines"
  # The runtime-daemon section.
  DAEMON = "daemon"
  # The daemon's git block.
  GIT = "git"
  # The daemon's base-branch field inside that block.
  BASE_BRANCH = "base_branch"


# ----------------------------------------------------------------------------------------
class _CoreCommand:
  """
  Wire tokens of the `lazycortex-core reconcile-routine` verb this install drives.

  Attributes:
    RECONCILE_ROUTINE: The subcommand name.
    CFG_FLAG: Flag carrying the shipped config body as JSON.
    MANAGED_FLAG: Flag carrying the comma-separated owned-key list.
    CWD_FLAG: Flag carrying the repository root to write into.
    STATUS: Result key holding the verb's outcome word.
  """

  # The subcommand name.
  RECONCILE_ROUTINE = "reconcile-routine"
  # Flag carrying the shipped config body as JSON.
  CFG_FLAG = "--cfg-json"
  # Flag carrying the comma-separated owned-key list.
  MANAGED_FLAG = "--managed"
  # Flag carrying the repository root to write into.
  CWD_FLAG = "--cwd"
  # Result key holding the verb's outcome word.
  STATUS = "status"
  # Subcommand reading one settings section.
  SETTINGS_GET = "settings-get"
  # Subcommand writing one settings section.
  SETTINGS_SET = "settings-set"
  # Flag asking for the section exactly as stored and written as given.
  VERBATIM_FLAG = "--verbatim"
  # Result key holding a refused call's failure text.
  ERROR = "error"


_REQUIRED_DIRS = (
    ".experts/.jobs",
    ".logs/lazy-review/runs",
)

# Settings-section keys this script seeds or migrates. `review.watch_root` scopes the
# coordinator watch's single git pathspec; `review.coordination_rules` is the vault-wide
# operator rule layer the coordinator reads (empty string = no layer).
_WATCH_ROOT = JobKey.WATCH_ROOT
_COORDINATION_RULES = "coordination_rules"
_PROTOCOLS = "protocols"

# Default protocol references the coordinator folds into EVERY writer dispatch, on top of the
# plugin's own wire protocol and any per-class `classes[].protocols` extras. Config, not prose:
# a consumer that wants a different markdown canon edits `review.protocols`, never the agent.
_DEFAULT_PROTOCOLS = [ "lazycortex-core:lazy-core.markdown-style" ]
_HISTORY_GROUP = "history"

# Sections this install reads, and the subset it writes back — in the order a fresh file gains them.
_READ_SECTIONS = ( JobKey.REVIEW, JobKey.EXPERTS, _SettingsKey.ROUTINES, _SettingsKey.DAEMON )
_WRITTEN_SECTIONS = ( JobKey.REVIEW, JobKey.EXPERTS, _SettingsKey.ROUTINES )

_RETIRED_SCAN_ROUTINE = "lazy-review.scan"
_COLLECT_ROUTINE = "lazy-review.collect"
_WATCH_ROUTINE = "lazy-review.coordinator-watch"
_SANITIZE_ROUTINE = "lazy-review.sanitize"

# Per-routine list of the config keys this plugin owns — corrected to the shipped value on
# every install, where every other key the registration carries stays the operator's answer.
# Owned: the dispatch shape (`type` / `watch`), the CLI verb the routine runs (`command`), and the
# path mask the watch derives from `review.watch_root` — none of them is a value the operator
# could have decided, and all of them are values this plugin has changed before. Deliberately NOT
# owned: `protocols` (an operator attaches an extra protocol deliberately through the offer verb,
# and reasserting the shipped list would delete that attachment on the next install — the shipped
# refs reach a registration that lacks them through the same additive union), `interval_sec`,
# `timeout_sec`, `priority`, `cron` and `branch` (cadence and scope the operator retunes), and
# the watch's `filter` block — `review_active` is load-bearing there, but the block stays
# operator-owned: an operator's own predicates on it must survive every install, and owning the
# whole block would silently delete them on the next run. A registration that carries no `filter` at all still
# gains the shipped one, which is the case a stale install actually presents.
_MANAGED_FIELDS = {
    _COLLECT_ROUTINE: ("command",),
    _WATCH_ROUTINE: ("type", "watch", "path_filter", "command"),
    _SANITIZE_ROUTINE: ("type", "command"),
}

# Whole-repo watch scope, used when nothing narrower can be derived. Collapses the
# pathspec to `:(glob)**/*.md`.
_REPO_ROOT_WATCH = "."

# `branch` is required by the git-routine schema but vestigial for a `changed_files` watch —
# the daemon always reads local HEAD. Used only when the consumer has no `daemon.git` block
# and the checkout cannot be interrogated.
# limit: literal fallback when neither settings nor git can name a branch; the routine is
# inert without a daemon anyway, and `/lazy-core.install` seeds `daemon.git.base_branch`.
_FALLBACK_BRANCH = "main"


# ----------------------------------------------------------------------------------------
class SettingsRefusedError(Exception):
  """
  Refusal raised when the core CLI cannot read or write the settings file.

  Callers catch it to report the refusal instead of failing with a traceback.

  Attributes:
    reason: The refusal text, naming the settings file.
  """

  def __init__(self, reason: str) -> None:
    """
    Create the refusal carrying the text that names the settings file.

    Args:
      reason: The refusal text, naming the settings file.
    """
    # the base exception carries the reason as its message
    super().__init__(reason)

    # the reason the caller prints in its refusal
    self.reason = reason


def _common_root(roots: list[str]) -> str:
  """
  Name the deepest directory every one of `roots` sits under.

  Args:
    roots: Repo-relative directories, `.` standing for the whole repository.

  Returns:
    Their common directory, or `.` when they share none or the list is empty.
  """
  # guard: nothing to intersect means the whole repo is in scope
  if not roots:
    return _REPO_ROOT_WATCH
  return os.path.commonpath(roots) or _REPO_ROOT_WATCH


def _resolve_watch_root(existing: dict) -> str:
  """
  Resolve the watch root, widened until it covers every review class.

  Args:
    existing: The parsed settings object, possibly empty.

  Returns:
    The common directory of the base root and every `review.classes[].paths` glob's own root.
    The base root is an already-recorded `review.watch_root`, else the root of the retired
    scan routine's globs, else `.` on a greenfield install. The result never lies below the
    base root.
  """
  review = existing.get(JobKey.REVIEW, {})
  recorded = review.get(_WATCH_ROOT)

  # the recorded value is the base; without one, the retired scan routine's globs stand in for it
  if isinstance(recorded, str) and recorded:
    base = recorded.rstrip("/") or _REPO_ROOT_WATCH
  else:
    scan_paths = existing.get(_SettingsKey.ROUTINES, {}).get(_RETIRED_SCAN_ROUTINE, {}).get(JobKey.PATHS)
    base = _common_root([ _doc_class.glob_root(pattern) for pattern in scan_paths or [] ])

  # every class glob must fall under the watch, or its documents' commits never wake the coordinator
  class_roots = [
      _doc_class.glob_root(pattern)
      for cls in review.get(JobKey.CLASSES) or [] if isinstance(cls, dict)
      for pattern in cls.get(JobKey.PATHS) or [] if isinstance(pattern, str)
  ]
  return _common_root([ base, *class_roots ])


def _resolve_branch(repo: Path, existing: dict) -> str:
  """
  Resolve the branch name the git-watch routine registration declares.

  Args:
    repo: Repository root the install targets.
    existing: The parsed settings object, possibly empty.

  Returns:
    The consumer's `daemon.git.base_branch`, else the checkout's current branch,
    else the literal fallback.
  """
  recorded = existing.get(_SettingsKey.DAEMON, {}).get(_SettingsKey.GIT, {}).get(_SettingsKey.BASE_BRANCH)

  # the daemon's own base branch is authoritative when the consumer has one
  if isinstance(recorded, str) and recorded:
    return recorded

  # without one, the checkout's current branch, else the literal fallback when git cannot name it
  proc = subprocess.run(
      ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
      capture_output = True, text = True, check = False, encoding = "utf-8",
  )
  return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else _FALLBACK_BRANCH


def _default_settings(repo: Path, existing: dict) -> dict:
  """
  Build the settings sections this install seeds into `repo`.

  Args:
    repo: Repository root the install targets.
    existing: The parsed settings object the seed is merged into.

  Returns:
    A settings-shaped dict of the `review`, `experts`, and `routines` sections.
  """
  watch_root = _resolve_watch_root(existing)
  glob_root = "" if watch_root == _REPO_ROOT_WATCH else f"{watch_root}/"
  return {
      "review": {
          # No `_version` here: the `review` ladder belongs to `lazycortex-core`'s
          # `CURRENT_VERSIONS`, and a number stamped from this side makes core skip its own
          # next step on every consumer this install touches.
          "classes": [],
          "edit_marker_style": "simple",
          # Repairer name the coordinator resolves for parse-broken files. Pinned to
          # the registered expert key so the marketplace `<domain>.<role>` convention
          # holds.
          "doc_doctor": "review.doc_doctor",
          # Single git pathspec root for the coordinator watch — the routine cannot carry
          # a per-class list, so class precision stays in `review.classes[].paths`.
          _WATCH_ROOT: watch_root,
          # Vault-wide operator rule layer, read by the coordinator on every wake. Empty
          # means "no layer"; the operator points it at their own file when they want one.
          _COORDINATION_RULES: "",
          # Protocol refs attached to every writer dispatch (absent-only seed — an
          # operator's own list, empty included, is never overwritten).
          _PROTOCOLS: list(_DEFAULT_PROTOCOLS),
      },
      "experts": {
          "_version": 1,
          # Plugin-shipped system experts, registered unconditionally so a review
          # class can reference them without a
          # separate wiring step. Absent-only merge — never overwrites local edits.
          "review.coordinator": {
              "agent": "lazycortex-review:lazy-review.coordinator",
              "git_author": {
                  "name": "review.coordinator",
                  "email": "review.coordinator@bot.invalid",
              },
              # The coordinator commits its own body edits and the `Doc-Review-Phase`
              # trailer, and this registered identity is what its self-suppression reads.
              "can_commit_in_repo": True,
          },
          "review.doc_doctor": {
              "agent": "lazycortex-review:lazy-review.doc_doctor",
              "git_author": {
                  "name": "Doc Doctor",
                  "email": "review.doc_doctor@bot.invalid",
              },
          },
      },
      "routines": {
          "_version": 1,
          # The postman: sweeps DONE expert jobs, lands their payload, clears the runtime
          # `active_job` marker, and raises the job-done wake in its place — its commit is
          # what carries that wake to the watch worker.
          _COLLECT_ROUTINE: {
              "command": ["lazycortex-review", "collect-tick"],
              "interval_sec": 60,
              "timeout_sec": 120,
              "priority": 15,
          },
          # The wake channel: one broad pathspec, narrowed to opted-in documents by the
          # frontmatter filter, with the trigger detection itself in the worker.
          _WATCH_ROUTINE: {
              "type": "git",
              "branch": _resolve_branch(repo, existing),
              "watch": "changed_files",
              "path_filter": f":(glob){glob_root}**/*.md",
              "interval_sec": 60,
              "timeout_sec": 60,
              "filter": {
                  "frontmatter": {
                      ReviewKey.ACTIVE: {"in": [True], "not_in": []},
                  },
              },
              "command": ["lazycortex-review", "coordinator-dispatch"],
              # The playbook is the coordinator's law; the style protocol is the only route by
              # which the callout shapes the playbook defers to reach it — they live in a
              # sibling plugin's root, which the coordinator cannot resolve a path into.
              "protocols": [
                  "lazycortex-review:lazy-review.coordination-playbook",
                  "lazycortex-core:lazy-core.markdown-style",
              ],
          },
          # The sanitizer: daily repair of the three file-provable stuck review-loop states
          # (state-sanitizers-design.md). No git_author — its repairs are runtime-sidecar
          # state and job dispatches, never a commit.
          _SANITIZE_ROUTINE: {
              "type": "schedule",
              "cron": "0 4 * * *",
              "command": ["lazycortex-review", "sanitize"],
              "timeout_sec": 300,
          },
      },
  }


def resolve_core_cli() -> Path:
  """
  Resolve the `lazycortex-core` CLI file.

  Returns:
    Path of the core CLI file.

  Raises:
    RuntimeError: When none of the three lookup stages finds a core CLI; the message names all three.
  """
  return _git_ops.require_core_cli()


def _run_core_settings(cli: Path, repo: Path, verb: str, *, section: str, payload: dict | None = None) -> object:
  """
  Run one core settings verb on a section of `repo`'s settings file.

  Args:
    cli: Path of the core CLI file.
    repo: Repository root whose settings file the verb targets.
    verb: The core settings subcommand, `settings-get` or `settings-set`.
    section: Name of the settings section the verb works on.
    payload: Section value written by `settings-set`; `None` for a read.

  Returns:
    The verb's parsed standard output.

  Raises:
    SettingsRefusedError: When the verb exits non-zero; the reason names the settings file and carries the error
      text core reported.
  """
  proc = subprocess.run(
      [ sys.executable, str(cli), verb, section, _CoreCommand.VERBATIM_FLAG, _CoreCommand.CWD_FLAG, str(repo) ],
      input = None if payload is None else json.dumps(payload),
      capture_output = True, text = True, check = False, encoding = "utf-8",
  )

  # guard: the verb refused — its error text, else its stderr, is the reason
  if proc.returncode != 0:
    lines = proc.stdout.strip().splitlines()
    try:
      reason = json.loads(lines[-1])[_CoreCommand.ERROR] if lines else proc.stderr.strip()
    except (json.JSONDecodeError, KeyError, TypeError):
      reason = proc.stdout.strip() or proc.stderr.strip()
    settings_path = str(repo / Paths.CLAUDE_DIR / Paths.SETTINGS_FILE)
    raise SettingsRefusedError(reason if str(reason).startswith(settings_path) else f"{settings_path}: {reason}")
  return json.loads(proc.stdout)


def read_section(cli: Path, repo: Path, section: str) -> object:
  """
  Read one section of `repo`'s settings file through the core CLI.

  Guarantees:
    - When core cannot read the settings file, the call raises `SettingsRefusedError`, which callers must handle.

  Args:
    cli: Path of the core CLI file.
    repo: Repository root whose settings file is read.
    section: Name of the settings section to read.

  Returns:
    The section exactly as stored, or `None` when the file carries no such section.

  Raises:
    SettingsRefusedError: When core cannot read the settings file.
  """

  # Contract:
  # When core cannot read the settings file, the call raises SettingsRefusedError;
  # callers MUST handle it, since no other exception type reports this condition.

  # the section exactly as the file carries it, or None when it carries none
  return _run_core_settings(cli, repo, _CoreCommand.SETTINGS_GET, section = section)


def write_section(cli: Path, repo: Path, section: str, *, value: dict) -> None:
  """
  Store one section of `repo`'s settings file through the core CLI.

  Guarantees:
    - The section is stored exactly as given, with no version stamp added.
    - When core cannot write the settings file, the call raises `SettingsRefusedError`, which callers must handle.

  Args:
    cli: Path of the core CLI file.
    repo: Repository root whose settings file is written.
    section: Name of the settings section to store.
    value: The section content to store.

  Raises:
    SettingsRefusedError: When core cannot write the settings file.
  """

  # Contract:
  # The section is stored exactly as given, with no version stamp added;
  # the version ladder of a section belongs to the core plugin alone.

  # Contract:
  # When core cannot write the settings file, the call raises SettingsRefusedError;
  # callers MUST handle it, since no other exception type reports this condition.

  # the section is stored exactly as given, with no version stamp added
  _run_core_settings(cli, repo, _CoreCommand.SETTINGS_SET, section = section, payload = value)


def _reconcile_routines(repo: Path, cfgs: dict) -> dict:
  """
  Bring each of this plugin's routine registrations in `repo` back to its shipped shape.

  Each registration ends up with its plugin-owned keys corrected to the shipped value and any shipped key it
  lacked filled in; every other key stays exactly as recorded.

  Args:
    repo: Repository root whose settings file carries the registrations.
    cfgs: The shipped config body per routine name.

  Returns:
    The verb's outcome word (`registered` / `refreshed` / `unchanged`) per routine name.

  Raises:
    RuntimeError: When the core CLI cannot be resolved, or a call exits non-zero.
  """
  # the core CLI owns the write; without it the routines would stay on whatever shape they were installed with
  cli = resolve_core_cli()
  outcomes: dict[str, str] = {}
  for name, cfg in cfgs.items():
    proc = subprocess.run(
        [
            sys.executable, str(cli), _CoreCommand.RECONCILE_ROUTINE, name,
            _CoreCommand.CFG_FLAG, json.dumps(cfg),
            _CoreCommand.MANAGED_FLAG, ",".join(_MANAGED_FIELDS[name]),
            _CoreCommand.CWD_FLAG, str(repo),
        ],
        capture_output = True, text = True, check = False, encoding = "utf-8",
    )

    # guard: the verb refused — a rejected config must not pass for a reconciled routine
    if proc.returncode != 0:
      raise RuntimeError(
          f"{_CoreCommand.RECONCILE_ROUTINE} {name} exit={proc.returncode} "
          f"stdout={proc.stdout.strip()!r} stderr={proc.stderr.strip()!r}"
      )
    outcomes[name] = json.loads(proc.stdout)[_CoreCommand.STATUS]
  return outcomes


def _migrate(existing: dict) -> list[str]:
  """
  Bring a pre-coordinator settings object to the current `review` schema in place.

  Args:
    existing: The parsed settings object, already merged with the current seed.

  Returns:
    One label per migration that actually changed something; empty on an
    already-current settings object.
  """
  migrated: list[str] = []

  # the md-scan routine is retired — its `process-file` consumer no longer exists, so a
  # surviving registration is a routine the daemon runs into a missing subcommand.
  if existing.get(_SettingsKey.ROUTINES, {}).pop(_RETIRED_SCAN_ROUTINE, None) is not None:
    migrated.append(f"{_SettingsKey.ROUTINES}.{_RETIRED_SCAN_ROUTINE} (removed)")

  # the historian is gone; the coordinator writes `# History` inline, so a `history`
  # link in a class points at an expert nothing dispatches.
  review = existing.get(JobKey.REVIEW, {})
  for idx, cls in enumerate(review.get(JobKey.CLASSES) or []):
    if cls.get(JobKey.EXPERTS, {}).pop(_HISTORY_GROUP, None) is not None:
      migrated.append(f"{JobKey.REVIEW}.{JobKey.CLASSES}[{idx}].{JobKey.EXPERTS}.{_HISTORY_GROUP} (removed)")

  # both cleanups above are version-independent, and `review._version` stays untouched on purpose:
  # the ladder is `lazycortex-core`'s, and it skips any section already standing at or beyond its
  # own target, so a number written here would strand core's next step unrun.
  return migrated


def _ensure_dirs(repo: Path) -> list[str]:
  """
  Create any required review directories under `repo` that don't already exist.

  Returns:
    Repo-relative paths of the directories that were created.
  """
  created: list[str] = []
  for rel in _REQUIRED_DIRS:
    path = repo / rel
    if not path.exists():
      path.mkdir(parents=True, exist_ok=True)
      created.append(rel)
  return created


def _merge_defaults(existing: dict, defaults: dict, added: list[str], prefix: str = "") -> None:
  """
  Merge `defaults` into `existing` in place, completing every missing key at any depth.

  Args:
    existing: The settings mapping being merged into, mutated in place.
    defaults: The shipped defaults to merge in.
    added: Collects the dotted path of every key this merge writes.
    prefix: Dotted path of `existing` within the settings root, for `added` labels.
  """
  for key, value in defaults.items():
    path = f"{prefix}.{key}" if prefix else key

    # absent at this depth — write the default whole, dict or scalar alike
    if key not in existing:
      existing[key] = value
      added.append(path)
      continue

    # a value present at this depth on both sides recurses; anything else is the consumer's own
    if isinstance(value, dict) and isinstance(existing[key], dict):
      _merge_defaults(existing[key], value, added, path)


def _ensure_settings(repo: Path) -> dict:
  """
  Merge the default lazy-review settings into `repo`'s `.claude` settings file.

  Existing `review` and `experts` keys are left untouched at every depth; only missing keys
  are added, including sub-fields of an entry that already exists but was only partially
  written by an earlier install. The one exception is `review.watch_root`, widened until
  every review class sits under it and never narrowed. Retired registrations from an earlier schema are then
  removed, and this plugin's three routines are reconciled through the core CLI, which owns
  the write for those entries.

  Notes:
    - The settings file is read and written only through the core CLI; of the `review`, `experts`,
      and `routines` sections, only those that changed are written back.

  Args:
    repo: Repository root whose settings file is updated.

  Returns:
    A dict with the settings file path, the list of keys that were added, the list of
    migrations applied, and the reconcile outcome per routine name.

  Raises:
    SettingsRefusedError: When core cannot read or write the settings file.
    RuntimeError: When the core CLI cannot be resolved, or a routine reconcile call exits non-zero.
  """
  settings_dir = repo / Paths.CLAUDE_DIR
  settings_dir.mkdir(parents=True, exist_ok=True)
  settings_path = settings_dir / Paths.SETTINGS_FILE
  cli = resolve_core_cli()

  # the sections this install reads, exactly as the file carries them; an absent one stays absent
  existing: dict = {}
  for name in _READ_SECTIONS:
    if (section := read_section(cli, repo, name)) is not None:
      existing[name] = section
  before = copy.deepcopy(existing)

  # the seed is built against what is already on disk: the watch root and branch it
  # declares are derived from the consumer's own state, so it must be built before
  # the merge and before the migration strips what it derives from.
  defaults = _default_settings(repo, existing)

  # the routine bodies leave the absent-only merge: a registration already on record would
  # keep whatever shape it was installed with, and the owned keys are exactly what a plugin
  # update needs to correct. Everything else in the `routines` section — the `_version` meta
  # key — still rides the merge.
  cfgs = { name: defaults[_SettingsKey.ROUTINES].pop(name) for name in _MANAGED_FIELDS }
  added: list[str] = []
  _merge_defaults(existing, defaults, added)
  migrated = _migrate(existing)

  # a recorded watch root survives the merge untouched, so a widened one is written over it here;
  # a trailing slash alone is no widening and leaves the recorded spelling as it stands
  review = existing[JobKey.REVIEW]
  recorded = str(review.get(_WATCH_ROOT) or "").rstrip("/") or _REPO_ROOT_WATCH
  widened = defaults[JobKey.REVIEW][_WATCH_ROOT]
  if recorded != widened:
    migrated.append(f"{JobKey.REVIEW}.{_WATCH_ROOT} ({recorded!r} -> {widened!r})")
    review[_WATCH_ROOT] = widened

  # each section the merge, the migrations or the widening changed is written back as it now stands
  for name in _WRITTEN_SECTIONS:
    if name in existing and existing[name] != before.get(name):
      write_section(cli, repo, name, value = existing[name])

  # after the write, so the core CLI reconciles against the section this install just left
  # on disk rather than racing it
  reconciled = _reconcile_routines(repo, cfgs)
  return {
      "settings_path": str(settings_path), "added_keys": added,
      "migrated": migrated, "reconciled": reconciled,
  }


def install(repo: Path) -> dict:
  """
  Bootstrap the lazy-review directory structure and default settings for a repository.

  Guarantees:
    - Never overwrites a settings key the repository's settings file already has, at any
      nesting depth; only a missing key is added. Two exceptions: a key this plugin
      owns on one of the three routines it registers is always set to the shipped value,
      and `review.watch_root`, which is widened until every review class sits under it and
      never narrowed.

  Args:
    repo: Path to the repository root to install into.

  Returns:
    Dict with keys `repo`, `created_dirs`, `settings_path`, `added_keys`, `migrated`, and
    `reconciled`.

  Raises:
    SettingsRefusedError: When the core CLI cannot read or write the repository's settings file.
    RuntimeError: When the `lazycortex-core` CLI cannot be resolved, or its
      `reconcile-routine` verb refuses one of this plugin's routine configs.
  """

  # Contract:
  # Any settings key already present in the repository's settings file, at any nesting
  # depth, is left exactly as recorded; only a missing key is added. Two exceptions: a key
  # this plugin owns on one of the three routines it registers is ALWAYS set to the
  # shipped value, and `review.watch_root` is widened to the common directory of its recorded
  # value and every review class glob's root — never narrowed.

  repo = repo.resolve()
  return {
      "repo": str(repo),
      "created_dirs": _ensure_dirs(repo),
      **_ensure_settings(repo),
  }


def main(argv: list[str]) -> int:
  """
  Run the install bootstrap and print the JSON report to stdout.

  A refused settings file prints `{"status": "refused", "reason": ...}` instead of the report.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success, 1 when the settings file was refused.

  Raises:
    RuntimeError: When the core CLI cannot be resolved, or the install bootstrap's routine reconcile refuses and
      exits non-zero; it propagates uncaught.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog="lazy-review.install")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", type=Path, default=Path.cwd())
  args = parser.parse_args(argv)

  # a settings file core cannot read or write ends the run as a refusal naming the file, not a traceback
  try:
    report = install(args.cwd)
  except SettingsRefusedError as refusal:
    print(json.dumps({ "status": "refused", "reason": refusal.reason }))
    return 1
  print(json.dumps(report, indent=2))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
