"""Bootstrap lazy-review into a consumer repo.

Writes (or leaves alone if present) the following pieces of state:

- `<repo>/.claude/lazy.settings.json` — adds the `review` section, the
  `experts` entries for the plugin's own system experts, and the
  `routines["lazy-review.collect"]` / `routines["lazy-review.coordinator-watch"]` /
  `routines["lazy-review.sanitize"]` trio if absent. Existing values are never
  overwritten.
- `<repo>/.experts/.jobs/` and `<repo>/.logs/lazy-review/runs/`
  directories.

On a repo installed before the coordinator migration the script also
retires the `lazy-review.scan` routine, derives `review.watch_root` from
the paths that routine used to scan, and drops the `history` expert link
from every review class. `review._version` is left alone throughout —
`lazycortex-core` owns that ladder and stamps it from its own migrations.

The CLI prints a summary of what changed.

This script does NOT touch `.gitignore`; the consumer is told what
entries to add (see the install SKILL.md).
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import argparse
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
from keys import JobKey, Paths, ReviewKey  # noqa: E402  # pylint: disable=wrong-import-position


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

  ROUTINES = "routines"
  DAEMON = "daemon"
  GIT = "git"
  BASE_BRANCH = "base_branch"


_REQUIRED_DIRS = (
    ".experts/.jobs",
    ".logs/lazy-review/runs",
)

# Settings-section keys this script seeds or migrates. `review.watch_root` scopes the
# coordinator watch's single git pathspec; `review.coordination_rules` is the vault-wide
# operator rule layer the coordinator reads (empty string = no layer).
_WATCH_ROOT = "watch_root"
_COORDINATION_RULES = "coordination_rules"
_PROTOCOLS = "protocols"

# Default protocol references the coordinator folds into EVERY writer dispatch, on top of the
# plugin's own wire protocol and any per-class `classes[].protocols` extras. Config, not prose:
# a consumer that wants a different markdown canon edits `review.protocols`, never the agent.
_DEFAULT_PROTOCOLS = [ "lazycortex-core:lazy-core.markdown-style" ]
_HISTORY_GROUP = "history"

_RETIRED_SCAN_ROUTINE = "lazy-review.scan"
_COLLECT_ROUTINE = "lazy-review.collect"
_WATCH_ROUTINE = "lazy-review.coordinator-watch"
_SANITIZE_ROUTINE = "lazy-review.sanitize"

# Whole-repo watch scope, used when nothing narrower can be derived. Collapses the
# pathspec to `:(glob)**/*.md`, mirroring how `spec.vault_root: "."` is resolved.
_REPO_ROOT_WATCH = "."

# Glob metacharacters that end a pathspec's wildcard-free directory prefix.
_GLOB_CHARS = "*?["

# `branch` is required by the git-routine schema but vestigial for a `changed_files` watch —
# the daemon always reads local HEAD. Used only when the consumer has no `daemon.git` block
# and the checkout cannot be interrogated.
# limit: literal fallback when neither settings nor git can name a branch; the routine is
# inert without a daemon anyway, and `/lazy-core.install` seeds `daemon.git.base_branch`.
_FALLBACK_BRANCH = "main"


def _wildcard_free_prefix(pattern: str) -> str:
  """
  Return the leading directory part of `pattern` that carries no glob metacharacter.

  Args:
    pattern: A repo-relative path glob, e.g. `specs/core/**/*.md`.

  Returns:
    The wildcard-free prefix (`specs/core`), or an empty string when the first
    component already globs.
  """
  parts: list[str] = []
  for part in pattern.split("/"):
    # guard: the first globbing component ends the literal prefix
    if any(ch in part for ch in _GLOB_CHARS):
      break
    parts.append(part)
  return "/".join(parts)


def _derive_watch_root(scan_paths: list[str]) -> str:
  """
  Derive the watch root shared by the retired scan routine's path globs.

  Args:
    scan_paths: The `lazy-review.scan` routine's `paths` list.

  Returns:
    The common wildcard-free directory the globs sit under, or `.` when they
    share no such directory.
  """
  prefixes = [p for p in (_wildcard_free_prefix(g) for g in scan_paths) if p]
  # guard: no literal prefix at all (or none survived) means the whole repo is in scope
  if not prefixes or len(prefixes) != len(scan_paths):
    return _REPO_ROOT_WATCH
  return os.path.commonpath(prefixes) or _REPO_ROOT_WATCH


def _resolve_watch_root(existing: dict) -> str:
  """
  Resolve the watch root, preferring what the consumer already recorded.

  Args:
    existing: The parsed settings object, possibly empty.

  Returns:
    An already-recorded `review.watch_root`, the root derived from the retired scan
    routine's globs, or `.` on a greenfield install.
  """
  recorded = existing.get(JobKey.REVIEW, {}).get(_WATCH_ROOT)
  # guard: the operator's own value wins over any derivation
  if isinstance(recorded, str) and recorded:
    return recorded.rstrip("/") or _REPO_ROOT_WATCH
  scan = existing.get(_SettingsKey.ROUTINES, {}).get(_RETIRED_SCAN_ROUTINE, {})
  return _derive_watch_root(scan.get(JobKey.PATHS) or [])


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
  # guard: the daemon's own base branch is authoritative when the consumer has one
  if isinstance(recorded, str) and recorded:
    return recorded
  proc = subprocess.run(
      ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
      capture_output = True, text = True, check = False,
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
          # class (or the lazy-spec.product-config wizard) can reference them without a
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
  # The md-scan routine is retired — its `process-file` consumer no longer exists, so a
  # surviving registration is a routine the daemon runs into a missing subcommand.
  if existing.get(_SettingsKey.ROUTINES, {}).pop(_RETIRED_SCAN_ROUTINE, None) is not None:
    migrated.append(f"{_SettingsKey.ROUTINES}.{_RETIRED_SCAN_ROUTINE} (removed)")
  # The historian is gone; the coordinator writes `# History` inline, so a `history`
  # link in a class points at an expert nothing dispatches.
  review = existing.get(JobKey.REVIEW, {})
  for idx, cls in enumerate(review.get(JobKey.CLASSES) or []):
    if cls.get(JobKey.EXPERTS, {}).pop(_HISTORY_GROUP, None) is not None:
      migrated.append(f"{JobKey.REVIEW}.{JobKey.CLASSES}[{idx}].{JobKey.EXPERTS}.{_HISTORY_GROUP} (removed)")
  # Both cleanups above are version-independent, and `review._version` stays untouched on purpose:
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
    d = repo / rel
    if not d.exists():
      d.mkdir(parents=True, exist_ok=True)
      created.append(rel)
  return created


def _ensure_settings(repo: Path) -> dict:
  """
  Merge the default lazy-review settings into `repo`'s `.claude` settings file.

  Existing top-level and nested keys are left untouched; only missing keys are added.
  Retired registrations from an earlier schema are then removed.

  Returns:
    A dict with the settings file path, the list of keys that were added, and the
    list of migrations applied.
  """
  settings_dir = repo / Paths.CLAUDE_DIR
  settings_dir.mkdir(parents=True, exist_ok=True)
  settings_path = settings_dir / Paths.SETTINGS_FILE
  if settings_path.exists():
    existing = json.loads(settings_path.read_text())
  else:
    existing = {}
  # The seed is built against what is already on disk: the watch root and branch it
  # declares are derived from the consumer's own state, so it must be built before
  # the merge and before the migration strips what it derives from.
  defaults = _default_settings(repo, existing)
  added: list[str] = []
  for top_key, top_value in defaults.items():
    if top_key not in existing:
      existing[top_key] = top_value
      added.append(top_key)
      continue
    # Merge nested defaults conservatively.
    if isinstance(top_value, dict) and isinstance(existing[top_key], dict):
      for k, v in top_value.items():
        if k not in existing[top_key]:
          existing[top_key][k] = v
          added.append(f"{top_key}.{k}")
  migrated = _migrate(existing)
  settings_path.write_text(json.dumps(existing, indent=2) + "\n")
  return {"settings_path": str(settings_path), "added_keys": added, "migrated": migrated}


def install(repo: Path) -> dict:
  """
  Bootstrap the lazy-review directory structure and default settings for a repository.

  Args:
    repo: Path to the repository root to install into.

  Returns:
    Dict with keys `repo`, `created_dirs`, `settings_path`, `added_keys`, and `migrated`.
  """
  repo = repo.resolve()
  dirs = _ensure_dirs(repo)
  settings_info = _ensure_settings(repo)
  return {
      "repo": str(repo),
      "created_dirs": dirs,
      **settings_info,
  }


def main(argv: list[str]) -> int:
  """
  Run the install bootstrap and print the JSON report to stdout.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: always 0.
  """
  # waiver: argparse CLI signature, not a domain key
  parser = argparse.ArgumentParser(prog="lazy-review.install")
  # waiver: argparse CLI signature, not a domain key
  parser.add_argument("--cwd", type=Path, default=Path.cwd())
  args = parser.parse_args(argv)
  report = install(args.cwd)
  print(json.dumps(report, indent=2))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
