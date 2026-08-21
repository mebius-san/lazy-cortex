"""
One `spec.upstream` tick, all three lifecycle phases (`docs/tasks/lazycortex-specs.upstream.md`
§ 8), one unit at a time.

**Phase A — unfreeze.** For each `UpstreamStatus.IN_REVIEW` unit, reads its linked request
file's own `request_status` / `review_active` / `review_result` and closes the freeze: accepted
routing replaces `processed/` with `source/` and moves the unit to `processed`; a stopped review
or a routing decision naming no target releases the unit back to `drifted`/`new`; a request file
that no longer resolves is left frozen for `doctor_scan` (§ 13, below) to catch as a dangling
mutex.

**Phase B — fetch and detect.** Mirrors each configured unit's directory via the `remote-mirror`
core primitive (`dev.plugin-boundaries.md` § 1c) into
`upstream/<repo-key>/<mount>/<unit-path>/source/`, diffs it against `processed/`, derives the
closed `UpstreamStatus` set, and rewrites each touched unit's own folder-note (`# Actions`
checkbox, skipped-file lists).

**Phase C — request.** For a `new`/`drifted`/`postponed` unit whose `# Actions` checkbox the
operator ticked in a prior commit, diffs `source/` against `processed/`, writes a body-only
request file under `requests/`, and freezes the unit onto `UpstreamStatus.IN_REVIEW` with a
link back to it.

Every phase's write for one unit lands in that unit's own single atomic commit under a bot
identity, bounded by `max_units_per_tick` with a persisted cursor for continuation across
ticks. Every configured source's own repo-level folder-note (§ 5: fetch status, retry
bookkeeping against `fetch_failure_threshold`, a live Dataview summary of its units) is kept
current every tick, in its own atomic commit, independent of that per-unit budget.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import flip_gate
import iconize_inline
import note_explainers
import resolve_language
import spec_paths
from spec_keys import (
    DraftKey, HistoryEvent, UPSTREAM_ACTION_LABELS, UPSTREAM_FROZEN_STATUSES, UpstreamAction,
    UpstreamKey, UpstreamRole, UpstreamSourceKey, UpstreamSourceStatus, UpstreamStatus,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


class _K:
  """
  String and numeric constants for the upstream fetch/detect worker.

  Attributes:
    SPEC_SECTION: Settings top-level key holding plugin-owned spec settings.
    UPSTREAM_SECTION: `spec` settings sub-key holding every configured upstream source.
    MAX_UNITS: Config key naming the shared per-tick unit-work budget.
    MAX_TEXT_BYTES: Config key naming the per-file mirror size ceiling.
    FETCH_FAILURE_THRESHOLD: Config key naming the source-note retry threshold (read-through
      only — Phase B never consumes it).
    RESERVED_KEYS: Config keys under `upstream` that are never a `<repo-key>`.
    URL: Per-source config key naming the git URL.
    BRANCH: Per-source config key naming the tracked branch.
    MOUNTS: Per-source config key holding the mount map.
    SOURCE_PATH: Per-mount config key naming the in-repo root.
    UNITS: Per-mount config key holding the unit-boundary glob list.
    EXCLUDE: Per-mount config key holding the exclusion glob list.
    DEFAULT_MAX_UNITS: Fallback `max_units_per_tick`.
    DEFAULT_MAX_TEXT_BYTES: Fallback `max_text_file_bytes`.
    DEFAULT_FAILURE_THRESHOLD: Fallback `fetch_failure_threshold`.
    UPSTREAM_ROOT: Content-root-relative segment upstream mirrors live under.
    RUNTIME_CLONE_ROOT: Repo-relative dir holding one gitignored clone per `<repo-key>`.
    CURSOR_FILE: Repo-relative path of the fetch-phase continuation cursor.
    SOURCE_DIR: Unit-relative dir holding the current mirror.
    PROCESSED_DIR: Unit-relative dir holding the last-processed snapshot.
    MD_SUFFIX: Markdown file extension.
    GIT: Git executable name.
    GIT_DIR: `.git` entry marking a working copy.
    BOT_NAME: Git author name for this module's own commits.
    BOT_EMAIL: Git author email for this module's own commits.
    ACTIONS_H1: Heading of a unit note's operator-actions section.
    SKIPPED_CURRENT_H1: Heading of a unit note's current not-mirrored-file list.
    SKIPPED_PROCESSED_H1: Heading of a unit note's processed not-mirrored-file list.
    LEGACY_SKIPPED_CURRENT_H1: The current list's pre-rename heading, read-only fallback.
    LEGACY_SKIPPED_PROCESSED_H1: The processed list's pre-rename heading, read-only fallback.
    HISTORY_H1: Heading of a unit note's closed-request log.
    LANG_EN: English language token — the explainer fallback.
    LANG_RU: Russian language token.
    NONE_MARKER: Placeholder line rendered under an empty list section.
    MODE_PLAN: `remote-mirror` plan-only mode token.
    MODE_SYNC: `remote-mirror` sync mode token.
    PLUGIN_DIRS_ENV: Env var listing plugin dirs to resolve the core CLI in.
    CORE_CLI_NAME: The `lazycortex-core` CLI binary name.
    BIN_DIR: Per-plugin `bin/` sub-dir.
    PLUGIN_TREE_DIR: Dev-vault plugin-tree segment (fallback CLI resolution).
    REPO_ROOT_ENV: Env var the core CLI reads to resolve settings/paths against.
    REMOTE_MIRROR_VERB: The core CLI's `remote-mirror` subcommand token.
    PROG: CLI program name shown in `--help` output.
    ARG_CWD: CLI flag overriding the repo root.
    MODE: `remote-mirror` request field naming the mode token.
    CACHE_DIR: `remote-mirror` request field naming the shared working-clone directory.
    INCLUDE: `remote-mirror` request field naming the include-glob list scoping the request.
    MAX_BYTES: `remote-mirror` request field naming the per-file size ceiling.
    DEST: `remote-mirror` request field naming the sync/plan destination directory.
    SKIP_FETCH: `remote-mirror` request field reusing an existing clone without a network
      round-trip — set on every per-unit sync, since the tick's own plan call already fetched.
    REQUESTS_DIR: Content-root-relative dir a Phase C request lands under.
    REQUEST_H1: Heading of a request body's sole, service-only section.
    REQUEST_STATUS_KEY: Frontmatter key naming a request file's lifecycle status.
    REQUEST_REVIEW_ACTIVE_KEY: Frontmatter key naming whether a request is under active review.
    REQUEST_REVIEW_RESULT_KEY: Frontmatter key naming a finalized review's terminal verdict.
    REQUEST_STATUS_DRAFT: Pre-terminal `request_status` value.
    REQUEST_STATUS_ACCEPTED: Terminal `request_status` value for a routed-and-applied request.
    REQUEST_STATUS_REJECTED: Terminal `request_status` value for a request whose routing named
      no applicable target.
    SOURCE_NOTE_H1: Heading of a source note's fetch-status section.
    SOURCE_UNITS_H1: Heading of a source note's Dataview unit-summary section.
    SOURCE_INVALID_H1: Heading of a source note's vault-unsafe-directory-name list (§ 3/§ 5).
    ICONIZE_ICON: Frontmatter key carrying a folder-note's icon.
    ICONIZE_COLOR: Frontmatter key carrying a folder-note's icon colour.
    SOURCE_NOTE_ICON: Default icon seeded on every source's repo-level folder-note.
    ROOT_NOTE_ICON: Default icon seeded on the root upstream catalog note.
    INTAKE_COLOR: Accent colour the root catalog note and each per-source note carry — both are
      intake shelves, which the catalog paints apart from the ordinary containers. A unit note
      carries no icon keys at all.
    ROOT_NOTE_TITLE: Title line of the root upstream catalog note.
    UNSAFE_NAME_CHARS: Characters that make a source directory name vault-unsafe (§ 3).
    CASE_DUPLICATE_REASON: Refusal reason rendered for a name colliding only in case (§ 3).
    DATAVIEWJS_FENCE: Fenced-code language tag opening a `dataviewjs` block.
    DOCTOR_PROG: CLI program name shown in `upstream-doctor --help` output.
  """

  SPEC_SECTION = "spec"
  UPSTREAM_SECTION = "upstream"
  MAX_UNITS = "max_units_per_tick"
  MAX_TEXT_BYTES = "max_text_file_bytes"
  FETCH_FAILURE_THRESHOLD = "fetch_failure_threshold"
  RESERVED_KEYS = frozenset({MAX_UNITS, MAX_TEXT_BYTES, FETCH_FAILURE_THRESHOLD})
  URL = "url"
  BRANCH = "branch"
  MOUNTS = "mounts"
  SOURCE_PATH = "source_path"
  UNITS = "units"
  EXCLUDE = "exclude"
  DEFAULT_MAX_UNITS = 7
  DEFAULT_MAX_TEXT_BYTES = 1_048_576
  DEFAULT_FAILURE_THRESHOLD = 5
  UPSTREAM_ROOT = "upstream"
  RUNTIME_CLONE_ROOT = ".runtime/lazy-specs/upstreams"
  CURSOR_FILE = ".runtime/lazy-specs/upstream_tick_cursor.json"
  SOURCE_DIR = "source"
  PROCESSED_DIR = "processed"
  MD_SUFFIX = ".md"
  GIT = "git"
  GIT_DIR = ".git"
  BOT_NAME = "lazy-spec.upstream-tick"
  BOT_EMAIL = "lazy-spec.upstream-tick@bot.invalid"
  ACTIONS_H1 = "# Actions"
  SKIPPED_CURRENT_H1 = "# Not mirrored (current)"
  SKIPPED_PROCESSED_H1 = "# Not mirrored (processed)"
  LEGACY_SKIPPED_CURRENT_H1 = "# Skipped (current)"
  LEGACY_SKIPPED_PROCESSED_H1 = "# Skipped (processed)"
  HISTORY_H1 = "# History"
  LANG_EN = "en"
  LANG_RU = "ru"
  NONE_MARKER = "_(none)_"
  MODE_PLAN = "plan"
  MODE_SYNC = "sync"
  PLUGIN_DIRS_ENV = "LAZYCORTEX_PLUGIN_DIRS"
  CORE_CLI_NAME = "lazycortex-core"
  BIN_DIR = "bin"
  PLUGIN_TREE_DIR = "claude"
  REPO_ROOT_ENV = "LAZY_REPO_ROOT"
  REMOTE_MIRROR_VERB = "remote-mirror"
  PROG = "lazycortex-specs upstream-tick"
  ARG_CWD = "--cwd"
  MODE = "mode"
  CACHE_DIR = "cache_dir"
  INCLUDE = "include"
  MAX_BYTES = "max_bytes"
  DEST = "dest"
  SKIP_FETCH = "skip_fetch"
  REQUESTS_DIR = "requests"
  REQUEST_H1 = "# Upstream"
  REQUEST_STATUS_KEY = "request_status"
  REQUEST_REVIEW_ACTIVE_KEY = "review_active"
  REQUEST_REVIEW_RESULT_KEY = "review_result"
  REQUEST_STATUS_DRAFT = "draft"
  REQUEST_STATUS_ACCEPTED = "accepted"
  REQUEST_STATUS_REJECTED = "rejected"
  SOURCE_NOTE_H1 = "# Fetch status"
  SOURCE_UNITS_H1 = "# Units"
  SOURCE_INVALID_H1 = "# Invalid names"
  ICONIZE_ICON = "iconize_icon"
  ICONIZE_COLOR = "iconize_color"
  SOURCE_NOTE_ICON = "LiGitFork"
  ROOT_NOTE_ICON = "LiCloudDownload"

  # Domain(obsidian.icon-resolution):
  # # Intake shelf accent colour
  # Colour marks state, and an ordinary container carries none at all — but the intake shelf is
  # the deliberate exception to that rule. The vault-root request inbox and every upstream note
  # are where unprocessed material lands, so they must be findable at a glance among otherwise
  # colourless containers. They are painted with a fixed accent chosen to sit outside the state
  # palette entirely, so an intake shelf can never be misread as an asset sitting in some state.

  # accent colour shared by the root upstream catalog note and every per-source note
  INTAKE_COLOR = "#f0abfc"

  ROOT_NOTE_TITLE = "# Upstream"
  UNSAFE_NAME_CHARS = frozenset({ "#", "[", "]", "|", ":" })
  CASE_DUPLICATE_REASON = "case-only duplicate of another unit directory"
  DATAVIEWJS_FENCE = "```dataviewjs"
  DOCTOR_PROG = "lazycortex-specs upstream-doctor"


# Reason token `remote-mirror` never emits — this module's own ignore-filter adds it on top of
# the primitive's `symlink` / `too-large` / `binary` set (`lazy-spec.config-protocol.md` Part 4).
SKIP_REASON_IGNORED = "ignored"

# Byte length of the truncated content-hash shown in a skipped-file listing line.
_HASH_DISPLAY_LEN = 12

# Repo-relative path of the settings file, mirroring `spec_paths.py`'s own constant.
_SETTINGS_REL = Path(".claude") / "lazy.settings.json"

# Throwaway plan-mode `dest` segment — plan mode never writes, so this path is never created;
# it only has to be a value `remote-mirror`'s own path-relative-to-`dest` classification accepts.
_PLAN_DEST_SEGMENT = ".unused-plan-dest"

# `doctor_scan` finding-detail messages long enough to trip the magic-literal check.
_PROCESSED_WITHOUT_SNAPSHOT_DETAIL = (
    "note reads `spec_upstream_status: processed` but `processed/` is missing or empty"
)
_IN_REVIEW_NO_LINK_DETAIL = "note reads `spec_upstream_status: in-review` but carries no request link"


# ----------------------------------------------------------------------------------------
class _PlanKey:
  """
  Field names of a `remote-mirror` response's plan items, mirrored from the primitive's own
  wire contract (`remote_mirror.py`'s `_Key` — not imported, per `dev.plugin-boundaries.md` § 2a).

  Attributes:
    PATH: Plan-item field naming the classified file's relative POSIX path.
    ACTION: Plan-item field naming the classification token.
    ERROR: Response field naming an error message when the request could not be completed.
    PLAN: Response field naming the classified plan-item list.
    ADDED: Action token for a newly landed file.
    UPDATED: Action token for a changed file.
    FETCHED_SHA: Response field naming the clone's resolved commit SHA on a successful sync.
  """

  PATH = "path"
  ACTION = "action"
  ERROR = "error"
  PLAN = "plan"
  ADDED = "added"
  UPDATED = "updated"
  FETCHED_SHA = "fetched_sha"


# ----------------------------------------------------------------------------------------
class _SkipKey:
  """
  Field names of a skip-list entry as this module renders and re-parses it — a superset of
  `_PlanKey`'s wire shape, since `remote-mirror`'s own skip reason plus this module's own
  content hash both fold into the same dict.

  Attributes:
    REASON: Field naming why the file was skipped (`remote-mirror`'s own tokens, plus
      `SKIP_REASON_IGNORED`).
    SIZE: Field naming the skipped file's byte size, when known.
    HASH: Field naming the skipped file's own content hash.
  """

  REASON = "reason"
  SIZE = "size"
  HASH = "hash"


# Text encoding used to hash the aggregate state signature.
_ENCODING = "utf-8"


# ----------------------------------------------------------------------------------------
class GlobMatcher:
  """
  Shell-style glob matcher with path-aware separator semantics, mirroring the semantics of
  `lazycortex-core`'s own `remote_mirror.GlobMatcher` (`dev.plugin-boundaries.md` § 2a forbids
  importing it directly — this is an independent, equivalent implementation, not a copy of
  runtime state).

  Matches repo-relative POSIX paths against glob patterns where a single `*` matches within one
  path component and `**` matches zero or more whole components.
  """

  def __init__(self) -> None:
    """
    Create a matcher ready to test paths against glob patterns.
    """
    self._cache: dict[str, re.Pattern] = {}

  def match(self, rel_posix: str, pattern: str) -> bool:
    """
    Return True when `rel_posix` matches `pattern` under shell glob semantics.

    Args:
      rel_posix: Path-relative POSIX path string (no leading `/`).
      pattern: Shell glob pattern; `**` matches zero or more path components.

    Returns:
      True on a match, False otherwise.
    """
    # compile once per pattern — the same globs are re-tested against every candidate path
    if pattern not in self._cache:
      self._cache[pattern] = self._compile(pattern)
    return bool(self._cache[pattern].match(rel_posix))

  def _compile(self, pattern: str) -> re.Pattern:
    """
    Compile one glob pattern to a `re.Pattern` with the same `*`/`**` semantics as `match`.

    Args:
      pattern: Shell glob pattern; may or may not contain `**`.

    Returns:
      Compiled regular expression equivalent to the pattern under this class's glob rules.
    """
    parts = pattern.split("**")
    segs: list[str] = []
    for part in parts:
      escaped = re.escape(part).replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
      segs.append(escaped)
    regex = ".*".join(segs)
    regex = regex.replace("/.*/", "(?:/|/.*/)")
    if regex.startswith(".*/"):
      regex = "(?:.*/)?" + regex[3:]
    if regex.endswith("/.*"):
      regex = regex[:-3] + "(?:/.*)?"
    return re.compile("^" + regex + "$")


# italic one-liners rendered under every generated section heading, per vault language —
# the bot note documents itself so the operator never has to guess what a section means
# waiver: the RU lines carry `# noqa: RUF001` — Cyrillic in Russian UI strings is the content,
# not a lookalike-character typo; the checker cannot distinguish deliberate Russian text
_EXPLAINERS: dict[tuple[str, str], str] = {
    (_K.ACTIONS_H1, _K.LANG_EN): "Operator decisions for this unit: tick one box — the next tick acts on it.",
    # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
    (_K.ACTIONS_H1, _K.LANG_RU):
        # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "Решения оператора по юниту: отметьте один чекбокс — следующий тик его исполнит.",  # noqa: RUF001
    (_K.SKIPPED_CURRENT_H1, _K.LANG_EN):
        "Source files left out of the current mirror (source/): too large or not text. "
        "Judge the unit knowing these are absent.",
    (_K.SKIPPED_CURRENT_H1, _K.LANG_RU):
    # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "Файлы источника, не попавшие в текущее зеркало (source/): слишком большие или нетекстовые. "  # noqa: RUF001
    # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "Оценивайте юнит с учётом того, чего здесь нет.",  # noqa: RUF001
    (_K.SKIPPED_PROCESSED_H1, _K.LANG_EN):
        "Files that were absent from the last accepted snapshot (processed/) — "
        "the baseline drift is measured against.",
    (_K.SKIPPED_PROCESSED_H1, _K.LANG_RU):
    # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "Файлы, отсутствовавшие в последнем принятом снапшоте (processed/) — базе, от которой меряется дрейф.",  # noqa: RUF001
    (_K.HISTORY_H1, _K.LANG_EN): "Closed requests of this unit; lines are appended by the tick.",
    # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
    (_K.HISTORY_H1, _K.LANG_RU): "Закрытые реквесты юнита; строки дописывает рутина.",  # noqa: RUF001
    (_K.SOURCE_NOTE_H1, _K.LANG_EN): "Result of the last scheduled fetch of this source repository.",
    # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
    (_K.SOURCE_NOTE_H1, _K.LANG_RU): "Итог последнего планового фетча репозитория-источника.",  # noqa: RUF001
    (_K.SOURCE_INVALID_H1, _K.LANG_EN):
        "Source directories whose names are unsafe for the vault — no unit is created for them.",
    (_K.SOURCE_INVALID_H1, _K.LANG_RU):
    # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
        "Каталоги источника с именами, небезопасными для вольта — юниты по ним не создаются.",  # noqa: RUF001
    (_K.SOURCE_UNITS_H1, _K.LANG_EN): "Live summary of this source's units (Dataview).",
    # waiver: deliberate Russian UI string — Cyrillic is content, not a lookalike typo (RUF001)
    (_K.SOURCE_UNITS_H1, _K.LANG_RU): "Живая сводка юнитов источника (Dataview).",  # noqa: RUF001
}


def _with_explainer(section: str, lang: str) -> str:
  """
  Insert the section's italic explainer line right under its heading.

  Idempotent: an explainer already present under the heading (any language, from a prior
  render) is replaced rather than stacked.

  Args:
    section: A rendered section — heading line plus body.
    lang: The vault's authoring language; falls back to English per line.

  Returns:
    The section with exactly one explainer line under the heading, or unchanged when no
    explainer is defined for its heading.
  """
  return note_explainers.with_explainer(section, lang, _EXPLAINERS)


def _load_upstream_config(repo: Path) -> dict:
  """
  Read the `spec.upstream` settings sub-section.

  Args:
    repo: Repository root holding `.claude/lazy.settings.json`.

  Returns:
    Parsed `upstream` sub-section, or `{}` when absent/malformed.
  """
  path = repo / _SETTINGS_REL
  # guard: no settings file at all — nothing configured
  if not path.is_file():
    return {}
  # a malformed settings file is treated the same as an absent one — every caller already
  # falls back to an empty section
  try:
    spec = json.loads(path.read_text()).get(_K.SPEC_SECTION)
  except json.JSONDecodeError:
    return {}
  if not isinstance(spec, dict):
    return {}
  upstream = spec.get(_K.UPSTREAM_SECTION)
  return upstream if isinstance(upstream, dict) else {}


def _source_keys(cfg: dict) -> list[str]:
  """
  List configured `<repo-key>` entries, in deterministic order.

  Args:
    cfg: Parsed `spec.upstream` section.

  Returns:
    Sorted repo-key names, skipping the reserved limit keys.
  """
  return sorted(k for k, v in cfg.items() if k not in _K.RESERVED_KEYS and isinstance(v, dict))


def _resolve_core_cli(repo: Path) -> Path:
  """
  Find the `lazycortex-core` CLI binary (`dev.plugin-boundaries.md` § 1c).

  Args:
    repo: Repository root the dev-fallback path is resolved against.

  Returns:
    Absolute path to the resolved `lazycortex-core` binary.

  Raises:
    RuntimeError: When neither the env-declared plugin dirs nor the dev-vault fallback resolve.
  """
  dirs = os.environ.get(_K.PLUGIN_DIRS_ENV, "").split(os.pathsep)
  for plugin_dir in dirs:
    # guard: empty path segment from a trailing/double separator
    if not plugin_dir:
      continue
    cli = Path(plugin_dir) / _K.BIN_DIR / _K.CORE_CLI_NAME
    if cli.is_file():
      return cli
  # waiver: sibling-plugin path reach is intentional — this dev vault IS lazycortex-core's own
  # source tree, so a session with no plugin-cache env still resolves the CLI
  fallback = repo / _K.PLUGIN_TREE_DIR / _K.CORE_CLI_NAME / _K.BIN_DIR / _K.CORE_CLI_NAME
  if fallback.is_file():
    return fallback
  raise RuntimeError(
      f"lazycortex-core CLI not resolvable: ${_K.PLUGIN_DIRS_ENV} yields no match "
      f"and {fallback} is absent from this repo"
  )


def _call_remote_mirror(repo: Path, payload: dict) -> dict:
  """
  Invoke `lazycortex-core remote-mirror` with a JSON request on stdin.

  Args:
    repo: Repository root passed to the CLI as `$LAZY_REPO_ROOT`.
    payload: Request body per the `remote-mirror` CLI contract (`url`, `branch?`, `cache_dir`,
      `include[]`, `exclude[]`, `max_bytes?`, `dest`, `mode`).

  Returns:
    Parsed JSON response — `{fetched_sha, plan, applied}` on success, `{error}` on a fetch
    failure the primitive itself reported in-band.

  Raises:
    RuntimeError: The CLI process itself could not be resolved or crashed outside its own
      documented `{"error": ...}` contract.
  """
  cli = _resolve_core_cli(repo)
  env = os.environ.copy()
  env[_K.REPO_ROOT_ENV] = str(repo)
  proc = subprocess.run(
      [str(cli), _K.REMOTE_MIRROR_VERB],
      input = json.dumps(payload), capture_output = True, text = True, env = env, check = False,
  )
  # guard: the CLI's own contract is "0 on success, 1 on any failure — always valid JSON on
  # stdout" (remote_mirror.py `main`); a non-JSON stdout means the process itself crashed
  try:
    return json.loads(proc.stdout)
  except json.JSONDecodeError as exc:
    raise RuntimeError(
        f"remote-mirror crashed: exit={proc.returncode} stdout={proc.stdout!r} "
        f"stderr={proc.stderr!r}"
    ) from exc


def _clone_dir(repo: Path, repo_key: str) -> Path:
  """
  Resolve one source's gitignored working-clone directory.

  Args:
    repo: Repository root.
    repo_key: The configured source's key.

  Returns:
    `<repo>/.runtime/lazy-specs/upstreams/<repo-key>`.
  """
  return repo / _K.RUNTIME_CLONE_ROOT / repo_key


def _clone_origin_mismatch(clone_dir: Path, url: str) -> bool:
  """
  Check an existing clone's `origin` remote against the configured URL.

  Per `lazy-spec.config-protocol.md` Part 4, a mismatch is a fetch error for that source — the clone
  is never re-pointed or deleted automatically.

  Args:
    clone_dir: The source's working-clone directory.
    url: The currently configured `url` for that source.

  Returns:
    `True` when the clone exists and its `origin` differs from `url`; `False` when the clone is
    absent (nothing to compare yet) or already matches.
  """
  # guard: no clone yet — nothing to mismatch against, `remote-mirror` will clone fresh
  if not (clone_dir / _K.GIT_DIR).is_dir():
    return False
  proc = subprocess.run(
      [_K.GIT, "remote", "get-url", "origin"], cwd = str(clone_dir),
      capture_output = True, text = True, check = False,
  )
  return proc.returncode == 0 and proc.stdout.strip() != url


def _mount_source_paths(cfg: dict) -> dict[str, str]:
  """
  Map every configured mount name to its `source_path`.

  Args:
    cfg: One source's config record.

  Returns:
    `{mount_name: source_path}`.
  """
  mounts = cfg.get(_K.MOUNTS) or {}
  return { name: rec.get(_K.SOURCE_PATH, "") for name, rec in mounts.items() if isinstance(rec, dict) }


def _match_unit_dirs(all_paths: list[str], source_path: str, units: list[str], exclude: list[str]) -> set[str]:
  """
  Derive candidate unit directories (relative to `source_path`) matching a mount's `units` globs.

  Args:
    all_paths: Every file path in the fetched clone, clone-root-relative.
    source_path: The mount's in-repo root.
    units: Unit-boundary glob patterns, relative to `source_path`.
    exclude: Exclusion glob patterns, same relative base, checked after `units`.

  Returns:
    Set of matched unit-path strings (POSIX, relative to `source_path`).
  """
  matcher = GlobMatcher()
  prefix = f"{source_path}/" if source_path and source_path != "." else ""
  # collect every directory segment under source_path that appears in the file-path list
  dirs: set[str] = set()
  for p in all_paths:
    # guard: file lies outside this mount's source_path
    if prefix and not p.startswith(prefix):
      continue
    rel = p[len(prefix):]
    parts = rel.split("/")[:-1]
    for depth in range(1, len(parts) + 1):
      dirs.add("/".join(parts[:depth]))
  matched: set[str] = set()
  for d in dirs:
    if any(matcher.match(d, pat) for pat in units) and not any(matcher.match(d, pat) for pat in exclude):
      matched.add(d)
  return matched


def _unit_glob_matches(unit_path: str, units: list[str], exclude: list[str]) -> bool:
  """
  Test one unit path against a mount's `units`/`exclude` globs directly, independent of whether
  the directory currently exists in the fetched tree.

  Deliberately separate from `_match_unit_dirs` (which derives candidates FROM the tree's
  current file list): the excluded-vs-orphaned distinction (§ 8) needs a pure config-glob test —
  a directory that vanished from the source tree also vanishes from `_match_unit_dirs`'s output,
  so testing membership in that tree-derived set can never tell "still in scope but gone" apart
  from "fell out of `units`/`exclude`".

  Args:
    unit_path: Unit path, relative to the mount's `source_path`.
    units: Unit-boundary glob patterns.
    exclude: Exclusion glob patterns, checked after `units`.

  Returns:
    `True` when `unit_path` matches at least one `units` pattern and no `exclude` pattern.
  """
  matcher = GlobMatcher()
  return (
      any(matcher.match(unit_path, pat) for pat in units)
      and not any(matcher.match(unit_path, pat) for pat in exclude)
  )


def _has_overlap(unit_dirs: set[str]) -> bool:
  """
  Detect a nested or duplicate match among a mount's unit directories.

  Args:
    unit_dirs: Matched unit-path strings for one mount.

  Returns:
    `True` when one matched path is a path-prefix of another (config refusal for the mount).
  """
  paths = sorted(unit_dirs)
  for i, a in enumerate(paths):
    for b in paths[i + 1:]:
      if b == a or b.startswith(a + "/"):
        return True
  return False


def _invalid_char_reason(unit_path: str) -> str | None:
  """
  Test one candidate unit path for vault-unsafe characters (§ 3), independent of any other
  unit's own name.

  Args:
    unit_path: Candidate unit path, relative to the mount's `source_path`.

  Returns:
    A human-readable refusal reason, or `None` when every segment is vault-safe.
  """
  for segment in unit_path.split("/"):
    bad = next((ch for ch in _K.UNSAFE_NAME_CHARS if ch in segment), None)
    # guard: first offending character found — one reason is enough, no need to scan further
    if bad is not None:
      return f"unsafe character {bad!r} in directory name {segment!r}"
  return None


def _filter_invalid_units(
    candidates: set[str], existing: set[str],
) -> tuple[set[str], list[tuple[str, str]]]:
  """
  Split a mount's freshly-matched candidate unit paths into vault-safe and refused (§ 3).

  Guarantees:
    - A candidate whose name collides only in case with an already-landed unit path in
      `existing` is always refused, never accepted in place of the landed spelling.

  Args:
    candidates: Unit paths this tick's source tree matched (`_match_unit_dirs`'s output).
    existing: Unit paths already materialized in the vault for this mount — their names are
      never re-validated (already accepted on a prior tick); they only seed the case-collision
      check so a fresh candidate cannot silently overwrite one of them. A candidate that IS one
      of these (the ordinary idle-tick re-match of an already-landed unit) is never its own
      collision — only a DIFFERENT spelling colliding in case counts.

  Returns:
    `(accepted, refused)` — the vault-safe subset of `candidates`, and `(unit_path, reason)`
    pairs for every refused one, source-order-independent (sorted by `unit_path`).
  """
  # casefold -> the one original spelling that currently owns it
  taken = { name.casefold(): name for name in existing }
  accepted: set[str] = set()
  refused: list[tuple[str, str]] = []
  for unit_path in sorted(candidates):
    reason = _invalid_char_reason(unit_path)
    casefolded = unit_path.casefold()

    # Contract:
    # A candidate whose name is a different spelling that collides only in case with an
    # already-landed unit path in `existing` is always refused; it never silently overwrites
    # or shadows the landed spelling on a case-insensitive filesystem.

    # something else (a different spelling) already owns this casefolded name
    if reason is None and taken.get(casefolded, unit_path) != unit_path:
      reason = _K.CASE_DUPLICATE_REASON
    if reason is not None:
      refused.append((unit_path, reason))
      continue
    accepted.add(unit_path)
    taken.setdefault(casefolded, unit_path)
  return accepted, refused


def _vault_existing_units(content_root: Path, repo_key: str, mount: str) -> set[str]:
  """
  Enumerate unit directories already present in the vault for one mount, from a prior tick.

  Args:
    content_root: Spec content-root.
    repo_key: The source's key.
    mount: The mount name.

  Returns:
    Set of unit-path strings whose folder-note already exists under
    `upstream/<repo-key>/<mount>/`.
  """
  base = content_root / _K.UPSTREAM_ROOT / repo_key / mount
  # guard: nothing landed under this mount yet
  if not base.is_dir():
    return set()
  found: set[str] = set()
  for dirpath, _dirs, files in os.walk(str(base)):
    unit_dir = Path(dirpath)
    for fname in files:
      if fname == f"{unit_dir.name}{_K.MD_SUFFIX}":
        found.add(unit_dir.relative_to(base).as_posix())
  return found


def _plan_all_sources(repo: Path, cfg: dict) -> dict[str, tuple[list[str], str | None]]:
  """
  Plan every configured source's file tree exactly once for this tick.

  Args:
    repo: Repository root.
    cfg: Parsed `spec.upstream` section.

  Returns:
    `{repo_key: (tree_paths, error)}`, one entry per configured source.
  """
  out: dict[str, tuple[list[str], str | None]] = {}
  for repo_key in _source_keys(cfg):
    source_cfg = cfg[repo_key]
    mounts = _mount_source_paths(source_cfg)
    out[repo_key] = _plan_source_tree(repo, repo_key, source_cfg, mounts)
  return out


def _ordered_units(
    repo: Path, cfg: dict, content_root: Path, tree_by_source: dict[str, tuple[list[str], str | None]],
) -> tuple[list[tuple[str, str, str]], set[tuple[str, str]], dict[str, list[tuple[str, str, str]]]]:
  """
  Build the deterministic, tick-stable list of every unit to consider, per `lazy-spec.config-protocol`
  Part 5 — the union of the source tree's config-matched directories and whatever unit
  directories already exist in the vault.

  Args:
    repo: Repository root (unused directly — kept for signature symmetry with the vault scan).
    cfg: Parsed `spec.upstream` section.
    content_root: Spec content-root.
    tree_by_source: This tick's already-planned `{repo_key: (tree_paths, error)}`, from
      `_plan_all_sources` — never re-fetched here.

  Returns:
    `(ordered, refused_mounts, invalid_names)` — sorted `(repo_key, mount, unit_path)` tuples;
    the set of `(repo_key, mount)` pairs whose `units` overlap this tick (§ 8: a refused mount is
    refused whole — a refused mount's own units still enumerate from whatever already exists in the
    vault, but every one of them reports `UpstreamStatus.EXCLUDED` this tick — `_advance_unit`
    reads `refused_mounts`, not a tree-derived match set, see `_unit_glob_matches`); and
    `{repo_key: [(mount, unit_path, reason), ...]}` for every freshly-matched candidate this
    tick refused for a vault-unsafe name (§ 3) — never enumerated into `ordered` at all.
  """
  del repo
  out: list[tuple[str, str, str]] = []
  refused_mounts: set[tuple[str, str]] = set()
  invalid_names: dict[str, list[tuple[str, str, str]]] = {}
  for repo_key in _source_keys(cfg):
    source_cfg = cfg[repo_key]
    mounts = _mount_source_paths(source_cfg)
    tree_paths, error = tree_by_source.get(repo_key, ([], "not planned"))
    for mount, source_path in mounts.items():
      rec = (source_cfg.get(_K.MOUNTS) or {}).get(mount) or {}
      units_cfg = list(rec.get(_K.UNITS) or [])
      exclude_cfg = list(rec.get(_K.EXCLUDE) or [])
      matched: set[str] = set()
      # guard: tree unreadable this tick — only vault-existing units are still visitable
      if error is None:
        matched = _match_unit_dirs(tree_paths, source_path, units_cfg, exclude_cfg)
        # guard: overlapping units — refuse the whole mount, not the tick
        if _has_overlap(matched):
          refused_mounts.add((repo_key, mount))
      existing = _vault_existing_units(content_root, repo_key, mount)
      matched, refused = _filter_invalid_units(matched, existing)
      if refused:
        invalid_names.setdefault(repo_key, []).extend(
            (mount, unit_path, reason) for unit_path, reason in refused
        )
      for unit_path in sorted(matched | existing):
        out.append((repo_key, mount, unit_path))
  return sorted(out), refused_mounts, invalid_names


def _plan_source_tree(
    repo: Path, repo_key: str, source_cfg: dict, mounts: dict[str, str],
) -> tuple[list[str], str | None]:
  """
  Fetch one source once and plan its full file tree across every configured mount.

  A single read-only `remote-mirror` plan call, scoped to the union of every mount's
  `source_path`, gives every downstream unit-directory match for that source without a second
  network round-trip per mount.

  Args:
    repo: Repository root.
    repo_key: The source's key.
    source_cfg: The source's config record (`url`, `branch?`, `mounts`).
    mounts: `{mount_name: source_path}` already resolved from `source_cfg`.

  Returns:
    `(paths, error)` — clone-root-relative file paths on success (`error` is `None`), or
    `([], error)` when the clone/fetch step itself failed or the source has no usable `url`.
  """
  url = source_cfg.get(_K.URL)
  # guard: malformed source record — nothing to fetch
  if not url:
    return [], "missing 'url'"
  clone_dir = _clone_dir(repo, repo_key)
  # guard: an existing clone points at a different remote — never silently re-fetch the wrong repo
  if _clone_origin_mismatch(clone_dir, url):
    return [], f"clone origin mismatch for '{repo_key}': configured url is '{url}'"
  include = [f"{sp}/**" if sp and sp != "." else "**" for sp in mounts.values()]
  result = _call_remote_mirror(repo, {
      _K.URL: url, _K.BRANCH: source_cfg.get(_K.BRANCH), _K.CACHE_DIR: str(clone_dir),
      _K.INCLUDE: include, _K.DEST: str(clone_dir / _PLAN_DEST_SEGMENT),
      _K.MODE: _K.MODE_PLAN,
  })
  # guard: `remote-mirror` reported an in-band fetch failure — isolate this source, not the tick
  if _PlanKey.ERROR in result:
    return [], str(result[_PlanKey.ERROR])
  return [item[_PlanKey.PATH] for item in result.get(_PlanKey.PLAN, [])], None


def _unit_dir(content_root: Path, repo_key: str, mount: str, unit_path: str) -> Path:
  """
  Resolve one unit's own directory under the vault.

  Args:
    content_root: Spec content-root.
    repo_key: The source's key.
    mount: The mount name.
    unit_path: Unit path, relative to the mount's `source_path`.

  Returns:
    `<content_root>/upstream/<repo-key>/<mount>/<unit_path>`.
  """
  return content_root / _K.UPSTREAM_ROOT / repo_key / mount / unit_path


def _sha256_file(path: Path) -> str:
  """
  Hash one file's bytes.

  Args:
    path: File to hash.

  Returns:
    Hex sha256 digest.
  """
  return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_signature(base: Path) -> dict[str, str]:
  """
  Snapshot a directory's file content as `{relpath: sha256}`.

  Args:
    base: Directory to walk; absence yields an empty signature.

  Returns:
    Mapping of POSIX relpath to content hash, empty when `base` doesn't exist.
  """
  # guard: directory not created yet
  if not base.is_dir():
    return {}
  out: dict[str, str] = {}
  for dirpath, _dirs, files in os.walk(str(base)):
    for fname in files:
      p = Path(dirpath) / fname
      out[p.relative_to(base).as_posix()] = _sha256_file(p)
  return out


def _git_ignored(repo: Path, rel_paths: list[str]) -> set[str]:
  """
  Batch-check which repo-relative paths git would ignore.

  `.lazyignore` merging (the wiki plugin's own `RepoWalk._ignored` precedent) is deliberately
  out of scope here — a cross-plugin private-method reach would violate
  `dev.plugin-boundaries.md`; only the repo's own `.gitignore`/exclude mechanism is checked.

  Args:
    repo: Repository root.
    rel_paths: Repo-relative POSIX paths to check.

  Returns:
    Subset of `rel_paths` git would ignore; empty when `rel_paths` is empty.
  """
  # guard: nothing to check
  if not rel_paths:
    return set()
  proc = subprocess.run(
      [_K.GIT, "check-ignore", "--stdin"], cwd = str(repo),
      input = "\n".join(rel_paths), capture_output = True, text = True, check = False,
  )
  return set(proc.stdout.splitlines())


def _apply_ignore_filter(repo: Path, source_dir: Path, plan: list[dict]) -> tuple[list[dict], list[dict]]:
  """
  Remove any synced file the vault's own git would ignore, folding it into the skip list.

  Args:
    repo: Repository root.
    source_dir: The unit's `source/` directory, already synced by `remote-mirror`.
    plan: The applied sync plan for this unit (`remote-mirror`'s own action/reason items).

  Returns:
    `(kept_plan, newly_skipped)` — `kept_plan` excludes any item this filter removed;
    `newly_skipped` carries `{path, reason: "ignored"}` for each one, plus `size`/`hash` where
    the file was still readable at deletion time (never for a symlink), read before it is
    deleted so a content-only edit to an otherwise-ignored file still
    participates in drift detection, § 3), for the caller to fold into the unit's current
    skipped-file list alongside `remote-mirror`'s own skips.
  """
  landed = [item for item in plan if item.get(_PlanKey.ACTION) in (_PlanKey.ADDED, _PlanKey.UPDATED)]
  rel_paths = [str((source_dir / item[_PlanKey.PATH]).relative_to(repo)) for item in landed]
  ignored = _git_ignored(repo, rel_paths)
  kept: list[dict] = []
  skipped: list[dict] = []
  for item in plan:
    file_path = source_dir / item[_PlanKey.PATH]
    rel_in_repo = str(file_path.relative_to(repo))
    if rel_in_repo in ignored:
      entry = { _PlanKey.PATH: item[_PlanKey.PATH], _SkipKey.REASON: SKIP_REASON_IGNORED }
      # guard: read the file's own size/hash before deleting it — the bytes are gone after
      if file_path.is_file() and not file_path.is_symlink():
        entry[_SkipKey.SIZE] = file_path.stat().st_size
        entry[_SkipKey.HASH] = _sha256_file(file_path)
      file_path.unlink(missing_ok = True)
      skipped.append(entry)
      continue
    kept.append(item)
  return kept, skipped


def _aggregate_hash(signature: dict[str, str], skipped: list[dict]) -> str:
  """
  Combine a mirrored tree's content signature and its skipped-file list into one state hash.

  Used both to compare `source/` against `processed/` (drift detection — skipped-file hashes
  participate in the comparison exactly like mirrored content, § 3) and to compare the current
  state against a stored postponed hash.

  Args:
    signature: `{relpath: sha256}` of every mirrored file.
    skipped: Skip-list entries, each carrying at least a `path`; a `hash` key (present for
      oversized/binary skips this module hashed itself) folds into the aggregate too.

  Returns:
    Hex sha256 digest over a canonical, sorted rendering of both inputs.
  """
  lines = [f"{k}:{v}" for k, v in sorted(signature.items())]
  # a skip entry's hash is truncated to `_HASH_DISPLAY_LEN` on every round trip through a
  # rendered note (`_render_skipped_section` displays only that many characters, and
  # `_extract_section` can only ever recover what was displayed) — truncating here too keeps a
  # freshly-synced full hash and a round-tripped one comparable at the same precision, so an
  # accepted unit whose only change was a skipped file never spuriously re-drifts
  lines += sorted(
      f"skip:{item.get(_PlanKey.PATH)}:{item.get(_SkipKey.HASH, '')[:_HASH_DISPLAY_LEN]}"
      for item in skipped
  )
  return hashlib.sha256("\n".join(lines).encode(_ENCODING)).hexdigest()


_KNOWN_FORGE_HOSTS = {
    "github.com": "blob",
    "gitea.com": "src/commit",
    "codeberg.org": "src/commit",
}

# GitLab's blob-URL shape differs from the table above (`-/blob` segment); `.com` plus any
# self-hosted `gitlab.*` subdomain share it.
_GITLAB_COM = "gitlab.com"
_GITLAB_SUBDOMAIN_PREFIX = "gitlab."


def _forge_blob_url(url: str, revision: str, path: str) -> str | None:
  """
  Best-effort web-viewer link for one file at one revision of a mirrored source.

  Args:
    url: The source's configured git URL (SSH or HTTPS form).
    revision: Commit SHA the link should pin to.
    path: File path relative to the repo root.

  Returns:
    An HTTPS blob-view URL, or `None` when the host isn't recognised.
  """
  # limit: covers github.com, the common self-hosted gitea/forgejo `src/commit` shape, and
  # GitLab's `-/blob`; an unrecognised host (GitHub Enterprise, Bitbucket, sourcehut, ...)
  # returns None rather than guessing a URL shape — upgrade path: fold in the forge table
  # `lazy-spec.resolve-repo` already carries, once this worker's source config gains a `forge` field.

  # normalise `git@host:owner/repo.git` to `host/owner/repo`
  ssh_match = re.match(r"^git@([^:]+):(.+?)(?:\.git)?$", url)
  if ssh_match:
    host, owner_repo = ssh_match.group(1), ssh_match.group(2)
  else:
    https_match = re.match(r"^https?://([^/]+)/(.+?)(?:\.git)?$", url)
    # guard: neither SSH nor HTTPS shape recognised
    if not https_match:
      return None
    host, owner_repo = https_match.group(1), https_match.group(2)
  if host in _KNOWN_FORGE_HOSTS:
    return f"https://{host}/{owner_repo}/{_KNOWN_FORGE_HOSTS[host]}/{revision}/{path}"
  if host == _GITLAB_COM or host.startswith(_GITLAB_SUBDOMAIN_PREFIX):
    return f"https://{host}/{owner_repo}/-/blob/{revision}/{path}"
  return None


def _render_skipped_section(heading: str, items: list[dict], url: str, revision: str) -> str:
  """
  Render one skipped-file list section of a unit note.

  Args:
    heading: The section's H1 heading text.
    items: Skip entries, each carrying `path`, `reason`, and optionally `size` / `hash`.
    url: The source's configured git URL, for forge-link building.
    revision: Source commit SHA the entries were observed at.

  Returns:
    The heading plus one bullet per entry, or a `_(none)_` placeholder when `items` is empty.
  """
  # guard: nothing skipped this state — placeholder line, not an empty section
  if not items:
    return f"{heading}\n{_K.NONE_MARKER}\n"
  lines = [heading]
  for item in items:
    path = item.get(_PlanKey.PATH, "")
    reason = item.get(_SkipKey.REASON, "")
    size = item.get(_SkipKey.SIZE)
    digest = item.get(_SkipKey.HASH)
    bits = [f"`{path}`"]
    if size is not None:
      bits.append(f"{size} bytes")
    bits.append(reason)
    if digest:
      bits.append(f"sha256:`{digest[:_HASH_DISPLAY_LEN]}`")
    link = _forge_blob_url(url, revision, path) if digest else None
    if link:
      bits.append(f"[source]({link})")
    lines.append("- " + " — ".join(bits))
  return "\n".join(lines) + "\n"


def _label_for_content_status(content_status: str) -> str | None:
  """
  Map an actionable content status to its `# Actions` checkbox label.

  Args:
    content_status: `UpstreamStatus.NEW` or `UpstreamStatus.DRIFTED` — the status a postponed
      unit would carry were it not shadowed by its postpone toggle.

  Returns:
    The matching `UpstreamAction` label, or `None` when `content_status` carries no checkbox.
  """
  return {
      UpstreamStatus.NEW: UpstreamAction.TAKE_INTO_WORK,
      UpstreamStatus.DRIFTED: UpstreamAction.PROCESS_UPDATE,
  }.get(content_status)


def _render_actions(status: str, *, gated: bool = False, resume_label: str | None = None) -> str:
  """
  Render a unit note's `# Actions` section body for one computed status.

  `UpstreamStatus.NEW` and `UpstreamStatus.DRIFTED` carry the primary operator checkbox plus a
  `POSTPONE` checkbox alongside it, rendered as siblings; a `UpstreamStatus.POSTPONED` unit
  carries its resume checkbox (when `resume_label` is given) plus the `POSTPONE` box rendered
  TICKED — the postpone is a toggle (§ 7): the operator unticks it to release the unit without
  a request, or ticks the resume box, which takes the unit into work and cancels the postpone
  in the same tick. Every other status renders an inert one-line note
  (`docs/tasks/lazycortex-specs.upstream.md`, the merge-decision status wording). A draft-gated
  unit never carries a checkbox regardless of status (§ 4a draft-gate: a gated unit gets no
  checkbox).

  Args:
    status: The unit's current `UpstreamStatus` value.
    gated: Whether the unit's own canon note (mirrored into `source/`) carries `spec_draft: true`.
    resume_label: The `UpstreamAction` label a postponed unit's own content status would carry,
      rendered as its checkbox; ignored for any status other than `UpstreamStatus.POSTPONED`.

  Returns:
    The `# Actions` heading plus body.
  """
  if gated:
    return f"{_K.ACTIONS_H1}\n_(no action needed — upstream design still a draft)_\n"
  label = _label_for_content_status(status)
  if label:
    return f"{_K.ACTIONS_H1}\n- [ ] {label}\n- [ ] {UpstreamAction.POSTPONE}\n"
  if status == UpstreamStatus.POSTPONED and resume_label:
    return (
        f"{_K.ACTIONS_H1}\n- [ ] {resume_label}\n- [x] {UpstreamAction.POSTPONE}\n"
        "_(postponed by operator — untick Postpone to release without a request; ticking the "
        "box above takes the unit into work and cancels the postpone)_\n"
    )
  notes = {
      UpstreamStatus.IN_REVIEW: "request in review",
      UpstreamStatus.POSTPONED: "postponed by operator",
      UpstreamStatus.PROCESSED: "up to date",
      UpstreamStatus.ORPHANED: "directory removed from source",
      UpstreamStatus.INVALID: "no markdown files in this directory",
      UpstreamStatus.EXCLUDED: "excluded from mount configuration",
  }
  return f"{_K.ACTIONS_H1}\n_(no action needed — {notes.get(status, status)})_\n"


def _extract_section(body: str, heading: str) -> list[dict]:
  """
  Parse a previously-rendered skipped-file section back into structured entries.

  Only understands this module's own `_render_skipped_section` output — good enough to compare
  the current skip-list against the last-processed one for drift detection.

  Args:
    body: A unit note's full body text.
    heading: The H1 heading naming the section to extract (e.g. `_K.SKIPPED_PROCESSED_H1`).

  Returns:
    List of `{path, hash}` dicts recovered from the section's bullet lines; empty when the
    heading is absent or the section carries only the `_(none)_` placeholder.
  """
  # a note written before the heading rename still carries the legacy heading — read it once;
  # the next render rewrites the note under the new name
  if heading not in body:
    legacy = {
        _K.SKIPPED_CURRENT_H1: _K.LEGACY_SKIPPED_CURRENT_H1,
        _K.SKIPPED_PROCESSED_H1: _K.LEGACY_SKIPPED_PROCESSED_H1,
    }.get(heading)
    # guard: section not present under either name (first-ever write)
    if not legacy or legacy not in body:
      return []
    heading = legacy
  after = body.split(heading, 1)[1]
  section = after.split("\n#", 1)[0]
  out: list[dict] = []
  for line in section.splitlines():
    # guard: only bullet lines carry an entry
    if not line.startswith("- `"):
      continue
    path_match = re.match(r"^- `([^`]+)`", line)
    hash_match = re.search(r"sha256:`([0-9a-f]+)`", line)
    if path_match:
      out.append({
          _PlanKey.PATH: path_match.group(1),
          _SkipKey.HASH: hash_match.group(1) if hash_match else "",
      })
  return out


def _render_note(
    *, unit_path: str, status: str, revision: str, url: str,
    skipped_current: list[dict], skipped_processed: list[dict], history_body: str,
    gated: bool = False, postponed_hash: str | None = None, resume_label: str | None = None,
    request_wikilink: str | None = None, lang: str = _K.LANG_EN,
) -> str:
  """
  Render one unit's full folder-note text.

  Args:
    unit_path: The unit's own path, relative to its mount's `source_path`.
    status: The unit's current `UpstreamStatus` value.
    revision: Source commit SHA the unit's `source/` was last synced from.
    url: The owning source's configured git URL.
    skipped_current: Current-state skip entries.
    skipped_processed: Last-processed-state skip entries (empty until the accept step first
      writes one).
    history_body: The existing `# History` section text, plus any newly closed entry the
      caller has already folded in — this module never appends to it itself.
    gated: Whether the unit's own canon note carries `spec_draft: true` — suppresses the
      operator checkbox regardless of `status`.
    postponed_hash: The stored postponed-state hash, carried through frontmatter only while
      `status` is `UpstreamStatus.POSTPONED`.
    resume_label: The `UpstreamAction` label a postponed unit's own content status would carry,
      threaded through to `_render_actions`; ignored for any status other than
      `UpstreamStatus.POSTPONED`.
    request_wikilink: The active request's wikilink target, carried through frontmatter only
      while `status` is `UpstreamStatus.IN_REVIEW`.
    lang: The vault's authoring language, selecting each section's explainer line.

  Returns:
    Full note text: frontmatter, title, `# Actions`, both not-mirrored sections, `# History` —
    every generated section carrying its italic explainer line under the heading.
  """
  title = unit_path.rsplit("/", 1)[-1]

  # both extra frontmatter lines are status-scoped: the postponed hash only survives while
  # postponed, the request link only while in-review — every other status carries neither
  postponed_line = (
      f"{UpstreamKey.POSTPONED_HASH}: {postponed_hash}\n"
      if status == UpstreamStatus.POSTPONED and postponed_hash else ""
  )
  request_line = (
      f"{UpstreamKey.REQUEST}: [[{request_wikilink}]]\n"
      if status == UpstreamStatus.IN_REVIEW and request_wikilink else ""
  )

  # assemble the fixed-order frontmatter block, with the two status-scoped lines spliced in
  frontmatter = (
      "---\n"
      f"{UpstreamKey.STATUS}: {status}\n"
      f"{UpstreamKey.REVISION}: {revision}\n"
      f"{postponed_line}"
      f"{request_line}"
      "tags:\n"
      f"  - upstream/{status}\n"
      f"spec_role: {UpstreamRole.UNIT}\n"
      "---\n"
  )

  # the body's fixed section order — title, actions, both not-mirrored lists, history; every
  # generated section gets its self-documenting explainer line spliced under the heading
  sections = [
      f"# {title} — upstream unit\n",
      _with_explainer(_render_actions(status, gated = gated, resume_label = resume_label), lang),
      _with_explainer(_render_skipped_section(_K.SKIPPED_CURRENT_H1, skipped_current, url, revision), lang),
      _with_explainer(_render_skipped_section(_K.SKIPPED_PROCESSED_H1, skipped_processed, url, revision), lang),
      _with_explainer(history_body or f"{_K.HISTORY_H1}\n{_K.NONE_MARKER}\n", lang),
  ]
  return frontmatter + "\n" + "\n".join(sections)


def _read_note(path: Path) -> tuple[dict, str]:
  """
  Read a unit note's frontmatter and body.

  Args:
    path: The note's path.

  Returns:
    `(frontmatter, body)`; `({}, "")` when the file doesn't exist yet.
  """
  # guard: first-ever tick for this unit — nothing to read
  if not path.is_file():
    return {}, ""
  text = path.read_text()
  fm, end = flip_gate._parse_frontmatter(text)
  return fm, text[end:]


def _is_draft_gated(source_dir: Path, unit_title: str) -> bool:
  """
  Check the draft-gate flag on a unit's own canon note, mirrored verbatim into `source/`.

  Per `docs/tasks/lazycortex-specs.upstream.md` (the merge-decision rules): a root folder-note under
  `source/`, same-named as the unit itself, that parses as a canon note and carries
  `spec_draft: true` gates the unit — no note, an unparseable note, or an absent flag are all
  the ungated (normal) case.

  Args:
    source_dir: The unit's synced `source/` directory.
    unit_title: The unit's own directory basename (the canon note's expected filename stem).

  Returns:
    `True` only when the canon note exists, parses, and carries `spec_draft: true`.
  """
  canon = source_dir / f"{unit_title}{_K.MD_SUFFIX}"
  # guard: no root note mirrored for this unit — ungated
  if not canon.is_file():
    return False
  fm, _end = flip_gate._parse_frontmatter(canon.read_text())
  return flip_gate._is_true(fm, DraftKey.DRAFT)


_ACTION_SKIPPED = "skipped"

# Statuses a draft-gated unit may hold onto instead of advancing into a fresh new/drifted
# transition (§ draft-gate: status stays put).
_GATE_HOLD_STATUSES = (UpstreamStatus.NEW, UpstreamStatus.DRIFTED, UpstreamStatus.PROCESSED)

# Cursor-file field name.
_CURSOR_KEY = "cursor"


def _flatten_synced_tree(source_dir: Path, include_root: str) -> None:
  """
  Relocate a fresh `remote-mirror` sync's output from its clone-root-relative nesting up to
  `source_dir`'s own root.

  `remote-mirror` always writes a matched file at `dest/<clone-root-relative path>` — there is
  no primitive-side option to strip the `include` glob's own prefix (`dev.plugin-boundaries.md`
  forbids reaching into the primitive to add one). Since `_sync_unit_source` always wipes
  `source_dir` before syncing, every file this pass wrote lives under
  `source_dir/<include_root>/...`; this call moves each one up to `source_dir/...` and removes
  the now-empty nesting, so `source/` mirrors the unit's own root the way § 2 describes it
  (the unit's own flat mirror of its text files) — flat at the unit's own directory, not the
  clone's.

  Args:
    source_dir: The unit's `source/` directory, freshly synced by `remote-mirror`.
    include_root: The clone-root-relative path this sync's `include` glob was rooted at.
  """
  nested_root = source_dir
  for segment in include_root.split("/"):
    nested_root = nested_root / segment
  # guard: nothing matched this sync (an empty unit, or every file skipped) — nothing to move
  if not nested_root.is_dir():
    return
  for dirpath, _dirs, files in os.walk(str(nested_root)):
    for fname in files:
      src = Path(dirpath) / fname
      dst = source_dir / src.relative_to(nested_root)
      dst.parent.mkdir(parents = True, exist_ok = True)
      src.replace(dst)

  # Decision: remove the exact nested chain walked above (now emptied of files), not a
  # first-segment guess — a unit whose own real content starts with the same top segment name
  # as include_root would otherwise have that real subtree deleted alongside the relic nesting.

  # remove the now-empty relic nesting
  shutil.rmtree(nested_root)

  # prune the now-emptied ancestor chain up to source_dir's own root
  ancestor = nested_root.parent
  while ancestor != source_dir:
    try:
      ancestor.rmdir()
    except OSError:
      # guard: still holds real content (e.g. a name-collision sibling) — stop pruning upward
      break
    ancestor = ancestor.parent


def _sync_unit_source(
    repo: Path, source_cfg: dict, clone_dir: Path, source_path: str,
    unit_path: str, source_dir: Path, max_bytes: int,
) -> tuple[list[dict], str | None, str | None]:
  """
  Bring one unit's `source/` directory up to date as a flat mirror of its own root, filtered
  against the vault's own ignore rules on top of `remote-mirror`'s own skip classification.

  Args:
    repo: Repository root.
    source_cfg: The owning source's config record.
    clone_dir: The source's shared working-clone directory.
    source_path: The mount's in-repo root.
    unit_path: The unit's own path, relative to `source_path`.
    source_dir: The unit's `source/` directory (sync destination) — wholly wiped and
      rewritten every call, since `source/` is routine-owned only (§ 3) and a full rewrite
      keeps a removed-upstream-file's disappearance from `source/` unconditional rather than
      dependent on reconciling `remote-mirror`'s own dest-state bookkeeping against the
      flattened layout.
    max_bytes: Per-file size ceiling passed to `remote-mirror`.

  Returns:
    `(skip_entries, fetched_sha, error)` — every currently-skipped file (`remote-mirror`'s own
    `too-large`/`binary`/`symlink` reasons plus this module's own `ignored`), path fields
    relative to the unit's own root, each carrying a size/hash where the bytes are still
    readable, and the clone's resolved commit SHA on success (`error` is `None`); `([], None,
    error)` on an in-band fetch failure (`source_dir` is left empty, never partially written).
  """
  include_root = f"{source_path}/{unit_path}" if source_path and source_path != "." else unit_path
  # guard: routine-owned directory, wiped before every sync so a removed upstream file cannot
  # survive under a stale flattened path `remote-mirror`'s own dest-state tracking never sees
  if source_dir.is_dir():
    shutil.rmtree(source_dir)
  source_dir.mkdir(parents = True)
  result = _call_remote_mirror(repo, {
      _K.URL: source_cfg.get(_K.URL), _K.BRANCH: source_cfg.get(_K.BRANCH),
      _K.CACHE_DIR: str(clone_dir), _K.INCLUDE: [f"{include_root}/**"],
      _K.MAX_BYTES: max_bytes, _K.DEST: str(source_dir), _K.MODE: _K.MODE_SYNC,
      _K.SKIP_FETCH: True,
  })
  # guard: fetch failed — isolated to this unit; source_dir stays empty, never partially written
  if _PlanKey.ERROR in result:
    return [], None, str(result[_PlanKey.ERROR])
  plan = result.get(_PlanKey.PLAN, [])
  _flatten_synced_tree(source_dir, include_root)

  # every downstream path (skip entries, ignore-filter, note rendering) reads unit-relative,
  # not clone-relative — strip the same prefix `_flatten_synced_tree` just relocated away
  clone_prefix = f"{include_root}/"
  flat_plan = [
      { **item, _PlanKey.PATH: item[_PlanKey.PATH][len(clone_prefix):] }
      for item in plan if item[_PlanKey.PATH].startswith(clone_prefix)
  ]
  primitive_skips = [item for item in flat_plan if item.get(_PlanKey.ACTION) == _ACTION_SKIPPED]
  entries: list[dict] = []
  for item in primitive_skips:
    clone_file = clone_dir / include_root / item[_PlanKey.PATH]
    entry = { _PlanKey.PATH: item[_PlanKey.PATH], _SkipKey.REASON: item.get(_SkipKey.REASON, "") }
    # guard: the clone still holds the file's bytes for a too-large/binary skip (not a symlink)
    if clone_file.is_file() and not clone_file.is_symlink():
      entry[_SkipKey.SIZE] = clone_file.stat().st_size
      entry[_SkipKey.HASH] = _sha256_file(clone_file)
    entries.append(entry)
  _, ignored = _apply_ignore_filter(repo, source_dir, flat_plan)
  entries.extend(ignored)
  return entries, result.get(_PlanKey.FETCHED_SHA), None


def _history_section(body: str) -> str:
  """
  Extract a unit note's existing `# History` section verbatim.

  `# History` is always this module's last-rendered section, so everything from its heading to
  the end of the text is the whole section — this module never appends to it (a later task's
  request-close step owns that write).

  Args:
    body: A unit note's full body text (frontmatter stripped).

  Returns:
    The `# History` heading plus its body, or `""` when the note has none yet.
  """
  # guard: no note yet, or a note predating this section
  if _K.HISTORY_H1 not in body:
    return ""
  return body[body.index(_K.HISTORY_H1):]


def _append_history_entry(history_body: str, entry: str) -> str:
  """
  Fold one newly closed outcome onto the front of a unit note's `# History` section.

  Args:
    history_body: The section's existing rendered text (from `_history_section`), or `""` when
      the note carries none yet.
    entry: The single rendered bullet line to add (no trailing newline).

  Returns:
    The `# History` heading plus `entry` followed by whatever entries were already there, with
    the `_(none)_` placeholder dropped once a real entry lands.
  """
  # default to the standard empty-section shape when the note carries no prior history
  history_body = history_body or f"{_K.HISTORY_H1}\n{_K.NONE_MARKER}\n"
  heading, _sep, rest = history_body.partition("\n")
  # a prior render's explainer line is presentation, not history — the next render re-adds it
  lines = [
      line for line in rest.splitlines()
      if line.strip() and line.strip() != _K.NONE_MARKER
      and not (line.startswith("*") and line.rstrip().endswith("*"))
  ]
  lines.insert(0, entry)
  return heading + "\n" + "\n".join(lines) + "\n"


def _wikilink_target(raw: str) -> str:
  """
  Strip a frontmatter-scalar `[[path]]` wikilink down to its bare target.

  Mirrors the bracket-stripping `coordinator_dispatch.py`'s own wikilink readers apply to a
  frontmatter-list member, applied here to the single-scalar `spec_upstream_request` value.

  Args:
    raw: The raw frontmatter scalar, e.g. `[[requests/foo]]`.

  Returns:
    The bare target path, e.g. `requests/foo`.
  """
  return raw.strip().strip('"').strip("'").split("|")[0].strip("[]")


def _read_request_frontmatter(repo: Path, wikilink: str) -> dict | None:
  """
  Read one request file's frontmatter from its wikilink target.

  Args:
    repo: Repository root the wikilink is relative to.
    wikilink: The request file's repo-relative wikilink target (`.md` suffix dropped).

  Returns:
    The parsed frontmatter dict, or `None` when the target no longer resolves to a file — a
    dangling mutex Phase A leaves for the doctor rather than guessing at (§ 8).
  """
  path = repo / f"{wikilink}{_K.MD_SUFFIX}"
  # guard: the request was deleted by hand — nothing to read
  if not path.is_file():
    return None
  fm, _end = flip_gate._parse_frontmatter(path.read_text())
  return fm


def _is_action_ticked(body: str, label: str) -> bool:
  """
  Check whether a unit note's `# Actions` section carries `label`'s checkbox ticked.

  Reads `body` as it stood before this tick's own rewrite — the operator's own last commit —
  so a tick this same pass is about to re-render never shadows the trigger it is meant to act on.

  Args:
    body: A unit note's full body text (frontmatter stripped), read prior to this tick.
    label: The `UpstreamAction` checkbox label to look for.

  Returns:
    `True` when a ticked `- [x] <label>` line appears under `# Actions`.
  """
  return f"- [x] {label}" in _actions_section(body)


def _has_unticked_action(body: str, label: str) -> bool:
  """
  Check whether a unit note's `# Actions` section carries `label`'s checkbox present but unticked.

  Distinct from a missing box: a postponed note rendered before the postpone toggle existed
  carries no `POSTPONE` line at all, and its absence must not read as an operator cancel.

  Args:
    body: A unit note's full body text (frontmatter stripped), read prior to this tick.
    label: The `UpstreamAction` checkbox label to look for.

  Returns:
    `True` when an unticked `- [ ] <label>` line appears under `# Actions`.
  """
  return f"- [ ] {label}" in _actions_section(body)


def _actions_section(body: str) -> str:
  """
  Extract a unit note's `# Actions` section body, empty when the section is absent.

  Args:
    body: A unit note's full body text (frontmatter stripped).

  Returns:
    The text between the `# Actions` heading and the next H1, or `""` without the heading.
  """
  # guard: no actions section at all yet — nothing to search
  if _K.ACTIONS_H1 not in body:
    return ""
  return body.split(_K.ACTIONS_H1, 1)[1].split("\n#", 1)[0]


def _unit_diff(
    source_dir: Path, processed_dir: Path, skipped_current: list[dict], skipped_processed: list[dict],
) -> tuple[list[str], list[str], list[str], list[str]]:
  """
  Diff a unit's current mirror against its last-processed snapshot, mirror and skip-lists alike.

  Args:
    source_dir: The unit's current `source/` directory.
    processed_dir: The unit's last-processed `processed/` directory (need not exist — an empty
      signature reads as "everything is added").
    skipped_current: Current-state skip entries (`path` + optional `hash`).
    skipped_processed: Last-processed-state skip entries, same shape.

  Returns:
    `(added, modified, removed, skip_changed)` — sorted POSIX-relpath lists; `skip_changed`
    names a skipped file whose own recorded hash differs between the two states (§ 3: a
    perceptibly-changed skipped file must not disappear from drift detection).
  """
  # the three-way mirrored-file diff: present only on one side, or present on both with a
  # changed content hash
  cur_sig = _tree_signature(source_dir)
  processed_sig = _tree_signature(processed_dir)
  added = sorted(path for path in cur_sig if path not in processed_sig)
  removed = sorted(path for path in processed_sig if path not in cur_sig)
  modified = sorted(
      path for path, digest in cur_sig.items() if path in processed_sig and processed_sig[path] != digest
  )

  # the skip-list side of the same comparison — a skipped file's own hash stands in for content
  # it was never actually mirrored, so its bucket is "changed", not added/modified/removed
  cur_skip = { item[_PlanKey.PATH]: item.get(_SkipKey.HASH, "") for item in skipped_current }
  processed_skip = { item[_PlanKey.PATH]: item.get(_SkipKey.HASH, "") for item in skipped_processed }
  skip_changed = sorted(
      path for path in cur_skip.keys() | processed_skip.keys() if cur_skip.get(path) != processed_skip.get(path)
  )
  return added, modified, removed, skip_changed


def _render_request_body(
    *, unit_path: str, note_wikilink: str, reason: str, revision: str,
    added: list[str], modified: list[str], removed: list[str], skip_changed: list[str],
) -> str:
  """
  Render a Phase C request's body-only content (§ 9: the body is service-only content).

  Carries only structural facts — the unit's own path, a link back to its note, why the request
  exists, and per-bucket path lists — never file contents or a rendered diff (§ 9: the full
  design and the full diff are never copied into the body). The `## Material` section is the
  deterministic
  hook that closes the writer's context chain: the request travels to the writer whole (the
  review loop's own contract), so a concrete Read instruction with real paths, right in the
  body, replaces the writer having to infer the unit's location from the `- Note:` link plus a
  guess at directory layout.

  Args:
    unit_path: The unit's own directory, repo-relative (`_dispatch_request`'s own
      `str(unit_dir.resolve().relative_to(repo))`) — carries the `spec.vault_root` segment, so
      `unit_path/source/` and `unit_path/processed/` are real Read targets from the repo root.
    note_wikilink: The unit note's own repo-relative wikilink target.
    reason: `UpstreamStatus.NEW` or `UpstreamStatus.DRIFTED` — why this request was opened.
    revision: Source commit SHA the diffed `source/` was synced from.
    added: Sorted paths present only in `source/`.
    modified: Sorted paths present in both with a changed content hash.
    removed: Sorted paths present only in `processed/`.
    skip_changed: Sorted paths whose skip-list hash differs between the two states.

  Returns:
    Naked markdown body text — no frontmatter — for `open_request.py`'s own opt-in transition
    to bring into the review loop.
  """
  def _bullets(paths: list[str]) -> str:
    # guard: nothing in this bucket — the placeholder line, not an empty section
    if not paths:
      return f"{_K.NONE_MARKER}\n"
    return "".join(f"- `{path}`\n" for path in paths)

  # the service-only header line block: what/why/where, no content
  lines = [
      f"{_K.REQUEST_H1}\n",
      f"- Unit: `{unit_path}`\n",
      f"- Note: [[{note_wikilink}]]\n",
      f"- Reason: {reason}\n",
      f"- Revision: {revision}\n",
      "\n## Material\n"
      f"Before writing, Read the unit's material: `{unit_path}/{_K.SOURCE_DIR}/` "
      f"(current upstream state) and `{unit_path}/{_K.PROCESSED_DIR}/` "
      "(last processed snapshot).\n",
      "\n## Added\n", _bullets(added),
      "\n## Modified\n", _bullets(modified),
      "\n## Removed\n", _bullets(removed),
      "\n## Skipped changed\n", _bullets(skip_changed),
  ]
  # a drift request additionally carries a one-line, content-free essence of the change (§ 9)
  if reason == UpstreamStatus.DRIFTED:
    lines.append(
        f"\n## Summary\n{len(added)} added, {len(modified)} modified, "
        f"{len(removed)} removed, {len(skip_changed)} skipped files changed\n",
    )
  return "".join(lines)


def _unique_request_path(requests_dir: Path, slug: str) -> Path:
  """
  Resolve a collision-free request filename under `requests/` (§ 9: numeric-suffix collisions).

  Args:
    requests_dir: The vault's `requests/` directory.
    slug: The unit's own slug (its directory basename), the request's preferred filename stem.

  Returns:
    `requests_dir/<slug>.md`, or the first `requests_dir/<slug>-<n>.md` not already on disk.
  """
  candidate = requests_dir / f"{slug}{_K.MD_SUFFIX}"
  suffix = 2
  while candidate.exists():
    candidate = requests_dir / f"{slug}-{suffix}{_K.MD_SUFFIX}"
    suffix += 1
  return candidate


def _dispatch_request(
    repo: Path, content_root: Path, unit_dir: Path, note_path: Path, unit_path: str,
    source_cfg: dict, resume_status: str, revision: str,
    skipped_current: list[dict], existing_body: str,
) -> tuple[bool, str]:
  """
  Phase C: open one request from a ticked `# Actions` checkbox and freeze the unit onto it.

  Write order is fail-safe (§ 8): the note (status `in-review`, request link, checkbox gone) is
  written before the request file, and both land in one atomic commit — a crash mid-write leaves
  a doctor-visible dangling state rather than two requests for the same change.

  Args:
    repo: Repository root.
    content_root: Spec content-root.
    unit_dir: The unit's own directory.
    note_path: The unit note's own path.
    unit_path: The unit's own path, relative to its mount's `source_path`.
    source_cfg: The owning source's config record.
    resume_status: `UpstreamStatus.NEW` or `UpstreamStatus.DRIFTED` — the content status this
      tick's fresh sync computed (the unit's own, unshadowed by any postpone toggle).
    revision: Source commit SHA this tick's fresh `source/` was synced from.
    skipped_current: This tick's freshly computed current-state skip entries.
    existing_body: The note's body text as it stood before this tick's own rewrite.

  Returns:
    `(had_work, status)` — `True, UpstreamStatus.IN_REVIEW` once committed.
  """
  # diff the freshly-synced source/ against the last accepted snapshot for the request's lists
  source_dir = unit_dir / _K.SOURCE_DIR
  processed_dir = unit_dir / _K.PROCESSED_DIR
  skipped_processed = _extract_section(existing_body, _K.SKIPPED_PROCESSED_H1)
  added, modified, removed, skip_changed = _unit_diff(
      source_dir, processed_dir, skipped_current, skipped_processed,
  )

  # resolve where the request lands and what it links back to — repo-relative throughout (via
  # unit_dir/note_path/request_path), so both carry the `spec.vault_root` segment (default
  # "specs"); `full_unit_path` doubles as the `## Material` section's literal Read target
  note_wikilink = str(note_path.resolve().relative_to(repo).with_suffix(""))
  full_unit_path = str(unit_dir.resolve().relative_to(repo))
  slug = unit_path.rsplit("/", 1)[-1]
  requests_dir = content_root / _K.REQUESTS_DIR
  requests_dir.mkdir(parents = True, exist_ok = True)
  request_path = _unique_request_path(requests_dir, slug)
  request_wikilink = str(request_path.resolve().relative_to(repo).with_suffix(""))

  # Contract:
  # The note is written before the request file, and both land in one commit — a crash
  # mid-write leaves a doctor-visible dangling in-review note rather than two requests for
  # the same change.

  # step 1 of the contract above: the note, frozen onto the request that's about to exist
  new_note_text = _render_note(
      unit_path = unit_path, status = UpstreamStatus.IN_REVIEW, revision = revision,
      url = source_cfg.get(_K.URL, ""), skipped_current = skipped_current,
      skipped_processed = skipped_processed, history_body = _history_section(existing_body),
      request_wikilink = request_wikilink, lang = resolve_language.resolve_repo_language(repo),
  )
  note_path.write_text(new_note_text)
  request_path.write_text(_render_request_body(
      unit_path = full_unit_path, note_wikilink = note_wikilink, reason = resume_status,
      revision = revision, added = added, modified = modified, removed = removed,
      skip_changed = skip_changed,
  ))
  had_work = _commit_unit(
      repo, unit_dir, unit_path, UpstreamStatus.IN_REVIEW, extra_paths = (request_path,),
  )
  return had_work, UpstreamStatus.IN_REVIEW


def _accept_unit(
    repo: Path, unit_dir: Path, note_path: Path, unit_path: str, source_url: str,
    revision: str, existing_body: str, wikilink: str,
) -> tuple[bool, str]:
  """
  Phase A, accepted branch: replace `processed/` with `source/` and close the review out.

  Args:
    repo: Repository root.
    unit_dir: The unit's own directory.
    note_path: The unit note's own path.
    unit_path: The unit's own path, relative to its mount's `source_path`.
    source_url: The owning source's configured git URL.
    revision: The note's own recorded `spec_upstream_revision` value, carried through unchanged.
    existing_body: The note's body text as it stood before this tick.
    wikilink: The closed request's own wikilink target, for the `# History` line.

  Returns:
    `(had_work, status)` — `status` is always `UpstreamStatus.PROCESSED`.
  """
  source_dir = unit_dir / _K.SOURCE_DIR
  processed_dir = unit_dir / _K.PROCESSED_DIR
  # processed/ is REPLACED, not merged — a file the source dropped must disappear from the
  # snapshot too (§ 8: replaced wholesale, never topped up)
  if processed_dir.is_dir():
    shutil.rmtree(processed_dir)
  shutil.copytree(source_dir, processed_dir)
  skipped_current = _extract_section(existing_body, _K.SKIPPED_CURRENT_H1)

  # the repo language feeds both the History line and the note render; the resolver walks to
  # the settings root and reads config, so one lookup serves both
  repo_language = resolve_language.resolve_repo_language(repo)
  # the localized narrative tail of the processed-request History line
  processed_tail = note_explainers.history_line_for_lang(
      repo_language, HistoryEvent.REQUEST_PROCESSED, wikilink = wikilink,
  )
  history_body = _append_history_entry(
      _history_section(existing_body),
      f"- {flip_gate._today(None)} — {_K.BOT_NAME} · {processed_tail}",
  )
  new_text = _render_note(
      unit_path = unit_path, status = UpstreamStatus.PROCESSED, revision = revision,
      url = source_url, skipped_current = skipped_current, skipped_processed = skipped_current,
      history_body = history_body, lang = repo_language,
  )
  note_path.write_text(new_text)
  had_work = _commit_unit(repo, unit_dir, unit_path, UpstreamStatus.PROCESSED)
  return had_work, UpstreamStatus.PROCESSED


def _release_unit(
    repo: Path, unit_dir: Path, note_path: Path, unit_path: str, source_url: str,
    revision: str, existing_body: str, fallback_status: str, history_note: str,
) -> tuple[bool, str]:
  """
  Phase A, release branch: unfreeze a unit whose review closed without an accepted routing.

  Covers both a review the operator stopped without a verdict and a routing decision that named
  no applicable target (§ 8) — the two differ only in the `# History` line, since neither one
  remembers anything about the specific state that was under review (the operator can always
  postpone the released unit if the source state itself is the problem).

  Args:
    repo: Repository root.
    unit_dir: The unit's own directory.
    note_path: The unit note's own path.
    unit_path: The unit's own path, relative to its mount's `source_path`.
    source_url: The owning source's configured git URL.
    revision: The note's own recorded `spec_upstream_revision` value, carried through unchanged.
    existing_body: The note's body text as it stood before this tick.
    fallback_status: `UpstreamStatus.DRIFTED` when `processed/` already exists, else
      `UpstreamStatus.NEW` — the unit's own § 8 fetch/detect ladder position minus the freeze.
    history_note: The closing outcome's own one-line message (no date/author prefix).

  Returns:
    `(had_work, status)` — `status` is `fallback_status`.
  """
  skipped_current = _extract_section(existing_body, _K.SKIPPED_CURRENT_H1)
  skipped_processed = _extract_section(existing_body, _K.SKIPPED_PROCESSED_H1)
  history_body = _append_history_entry(
      _history_section(existing_body), f"- {flip_gate._today(None)} — {_K.BOT_NAME} · {history_note}",
  )
  new_text = _render_note(
      unit_path = unit_path, status = fallback_status, revision = revision, url = source_url,
      skipped_current = skipped_current, skipped_processed = skipped_processed,
      history_body = history_body, lang = resolve_language.resolve_repo_language(repo),
  )
  note_path.write_text(new_text)
  had_work = _commit_unit(repo, unit_dir, unit_path, fallback_status)
  return had_work, fallback_status


def _advance_frozen_unit(
    repo: Path, unit_dir: Path, note_path: Path, unit_path: str,
    existing_fm: dict, existing_body: str, source_url: str,
) -> tuple[bool, str]:
  """
  Phase A: decide one in-review unit's fate from its linked request's own current state.

  Args:
    repo: Repository root.
    unit_dir: The unit's own directory.
    note_path: The unit note's own path.
    unit_path: The unit's own path, relative to its mount's `source_path`.
    existing_fm: The note's own frontmatter, as read before this tick.
    existing_body: The note's body text as it stood before this tick.
    source_url: The owning source's configured git URL.

  Returns:
    `(had_work, status)` — a release or accept outcome's own result, or `(False,
    UpstreamStatus.IN_REVIEW)` when the unit stays frozen (request still active, or its link
    does not resolve — a dangling mutex left for the doctor, § 8).
  """
  revision = existing_fm.get(UpstreamKey.REVISION, "")
  request_raw = existing_fm.get(UpstreamKey.REQUEST)
  # guard: no request link recorded on the note — nothing to unfreeze against
  if not request_raw:
    return False, UpstreamStatus.IN_REVIEW
  wikilink = _wikilink_target(request_raw)
  request_fm = _read_request_frontmatter(repo, wikilink)
  # guard: the linked request no longer resolves — a dangling mutex, the doctor's own scope
  if request_fm is None:
    return False, UpstreamStatus.IN_REVIEW

  # a released unit's own § 8 ladder position, minus the freeze — used by every release branch
  processed_dir = unit_dir / _K.PROCESSED_DIR
  fallback_status = UpstreamStatus.DRIFTED if processed_dir.is_dir() else UpstreamStatus.NEW
  request_status = request_fm.get(_K.REQUEST_STATUS_KEY, "")

  # the closed outcome ladder (§ 8): accepted, technically-failed routing, operator-stopped
  if request_status == _K.REQUEST_STATUS_ACCEPTED:
    return _accept_unit(
        repo, unit_dir, note_path, unit_path, source_url, revision, existing_body, wikilink,
    )
  if request_status == _K.REQUEST_STATUS_REJECTED:
    return _release_unit(
        repo, unit_dir, note_path, unit_path, source_url, revision, existing_body, fallback_status,
        f"routing on [[{wikilink}]] named no applicable target — released to {fallback_status}",
    )
  review_active = flip_gate._is_true(request_fm, _K.REQUEST_REVIEW_ACTIVE_KEY)
  review_result = request_fm.get(_K.REQUEST_REVIEW_RESULT_KEY, "")
  if request_status == _K.REQUEST_STATUS_DRAFT and not review_active and not review_result:
    return _release_unit(
        repo, unit_dir, note_path, unit_path, source_url, revision, existing_body, fallback_status,
        f"review stopped on [[{wikilink}]] without a verdict — released to {fallback_status}",
    )
  # still under active review, or awaiting the apply pass — stay frozen
  return False, UpstreamStatus.IN_REVIEW


def _commit_paths(repo: Path, paths: list[Path], subject: str) -> bool:
  """
  Stage a fixed path set and commit it under this module's bot identity, when the staged
  contents actually changed this tick.

  Shared by `_commit_unit` (one unit's own directory) and `_update_source_note` (one source's
  own repo-level note) — both are "write text, then let git decide" atomic single-target
  commits under the same bot identity.

  Guarantees:
    - Any `.md` path among `paths` has its icon-frontmatter repaint folded into this same
      commit; no separate icons commit ever follows a note-owning bot commit.

  Args:
    repo: Repository root.
    paths: Paths to stage, absolute or repo-relative.
    subject: The commit subject line.

  Returns:
    `True` when a commit was made; `False` when nothing was staged (no change this tick).
  """

  # Contract:
  # Any `.md` path among `paths` has its icon-frontmatter repaint folded into this same commit;
  # no separate icons commit ever follows a note-owning bot commit.

  # resolve every target to a repo-relative path git can stage
  rel_paths = [str(path.resolve().relative_to(repo.resolve())) for path in paths]

  # fold each note's icon repaint into this same commit so no separate icons commit follows
  rel_paths.extend(iconize_inline.repaint_paths(
      repo, [p for p in rel_paths if p.endswith(_K.MD_SUFFIX)],
  ))

  # stage the fixed target set
  subprocess.run([_K.GIT, "add", "--", *rel_paths], cwd = str(repo), check = True, capture_output = True)
  staged = subprocess.run([_K.GIT, "diff", "--cached", "--quiet"], cwd = str(repo), check = False)

  # guard: nothing actually changed on disk — free target, no commit
  if staged.returncode == 0:
    return False

  # commit under this module's own bot identity
  subprocess.run([
      _K.GIT, "-c", f"user.name={_K.BOT_NAME}", "-c", f"user.email={_K.BOT_EMAIL}",
      "-c", "commit.gpgsign=false", "commit", "-q", "-m", subject,
  ], cwd = str(repo), check = True, capture_output = True)
  return True


def _commit_unit(
    repo: Path, unit_dir: Path, unit_path: str, status: str, *, extra_paths: tuple[Path, ...] = (),
) -> bool:
  """
  Commit one unit's whole directory (plus any extra paths) under this module's bot identity,
  when the staged contents actually changed this tick.

  Args:
    repo: Repository root.
    unit_dir: The unit's own directory (`source/`, `processed/`, and its note).
    unit_path: The unit's own path, for the commit subject.
    status: The unit's freshly computed status, for the commit subject.
    extra_paths: Additional paths to stage alongside `unit_dir` — Phase C's own freshly written
      request file, staged in the same atomic commit as the note that links to it.

  Returns:
    `True` when a commit was made; `False` when nothing was staged (unit unchanged this tick).
  """
  # the unit's own note, named for repaint purposes — `unit_dir` alone is a directory, and
  # `_commit_paths` only repaints paths it can see end in `.md`
  note_path = unit_dir / f"{unit_dir.name}{_K.MD_SUFFIX}"
  return _commit_paths(
      repo, [unit_dir, note_path, *extra_paths], f"lazy-spec.upstream-tick: {unit_path} -> {status}",
  )


def _advance_unit(
    repo: Path, content_root: Path, repo_key: str, mount: str, unit_path: str,
    source_cfg: dict, mount_cfg: dict, tree_paths: list[str], tree_error: str | None,
    mount_refused: bool, max_bytes: int,
) -> tuple[bool, str | None]:
  """
  Advance one unit's recorded state for this tick — all three phases, one unit (§ 8).

  Dispatches to Phase A (`_advance_frozen_unit`) for an in-review unit and to Phase C
  (`_dispatch_request`) for a `new`/`drifted`/`postponed` unit whose `# Actions` checkbox the
  operator ticked in a prior commit; otherwise runs Phase B's own fetch/detect/render ladder.

  Notes:
    - Ticking both the primary action checkbox and the `POSTPONE` checkbox in the same commit
      resolves to the primary take-into-work action (§ 7); postpone never takes effect
      when both are ticked together.

  Args:
    repo: Repository root.
    content_root: Spec content-root.
    repo_key: The unit's source key.
    mount: The unit's mount name.
    unit_path: The unit's own path, relative to the mount's `source_path`.
    source_cfg: The owning source's config record.
    mount_cfg: The owning mount's config record.
    tree_paths: The source's already-planned file-tree paths (empty when `tree_error` is set).
    tree_error: The source's fetch/plan error this tick, or `None`.
    mount_refused: Whether this unit's mount has overlapping `units` this tick — every unit
      under a refused mount reports `UpstreamStatus.EXCLUDED` regardless of its own glob match.
    max_bytes: Per-file mirror size ceiling.

  Returns:
    `(had_work, status)` — whether a commit was made, and the unit's resulting
    `UpstreamStatus` value. `status` is `None` only when a draft-gated unit's first-ever landing
    was undone this tick — it never materialized (no `source/`, no note, § draft-gate).
  """
  # resolve this unit's on-disk layout before anything else needs it
  unit_dir = _unit_dir(content_root, repo_key, mount, unit_path)
  title = unit_path.rsplit("/", 1)[-1]
  note_path = unit_dir / f"{title}{_K.MD_SUFFIX}"
  source_dir = unit_dir / _K.SOURCE_DIR
  processed_dir = unit_dir / _K.PROCESSED_DIR

  # a prior tick's own status/revision is the baseline every branch below may fall back to
  existing_fm, existing_body = _read_note(note_path)
  prior_status = existing_fm.get(UpstreamKey.STATUS)
  # guard: frozen — Phase A decides an in-review unit's fate from its linked request alone,
  # never touching the fetch/detect ladder below
  if prior_status in UPSTREAM_FROZEN_STATUSES:
    return _advance_frozen_unit(
        repo, unit_dir, note_path, unit_path, existing_fm, existing_body, source_cfg.get(_K.URL, ""),
    )
  # guard: already-materialized unit whose mirrored canon note already carries `spec_draft: true`
  # — frozen wholesale, checked against the PRIOR tick's own mirror so a steady-state gated unit
  # never gets re-synced (draft-gate: the mirror stays unrefreshed and the status stays put)
  if source_dir.is_dir() and _is_draft_gated(source_dir, title):
    return False, prior_status

  # existence-in-source and the pure config-glob match are independent inputs — conflating them
  # is exactly what made `orphaned` unreachable before this split (a vanished directory also
  # vanishes from any tree-derived match set)
  source_path = mount_cfg.get(_K.SOURCE_PATH, "")
  prefix = f"{source_path}/" if source_path and source_path != "." else ""
  exists_in_source = tree_error is not None or any(p.startswith(f"{prefix}{unit_path}/") for p in tree_paths)
  units_cfg = list(mount_cfg.get(_K.UNITS) or [])
  exclude_cfg = list(mount_cfg.get(_K.EXCLUDE) or [])
  glob_matches = _unit_glob_matches(unit_path, units_cfg, exclude_cfg)

  # defaults the excluded/orphaned/unreachable branches leave untouched; only the normal sync
  # path below ever assigns something other than these
  gated = False
  postponed_hash: str | None = None
  resume_status: str | None = None
  skipped_current: list[dict] = []
  revision = existing_fm.get(UpstreamKey.REVISION, "")

  # the closed status ladder, in its documented order (§ 8): excluded, orphaned, unreachable,
  # then the normal sync-and-compare path
  if tree_error is None and (mount_refused or not glob_matches):
    status = UpstreamStatus.EXCLUDED
  elif tree_error is None and not exists_in_source:
    status = UpstreamStatus.ORPHANED
  elif tree_error is not None:
    # guard: source unreachable this tick — isolate, leave the unit exactly as it was
    return False, prior_status or UpstreamStatus.NEW
  else:
    clone_dir = _clone_dir(repo, repo_key)
    skip_entries, fetched_sha, sync_error = _sync_unit_source(
        repo, source_cfg, clone_dir, source_path, unit_path, source_dir, max_bytes,
    )
    if sync_error is not None:
      return False, prior_status or UpstreamStatus.NEW
    revision = fetched_sha or revision
    skipped_current = skip_entries
    has_md = any(
        fname.endswith(_K.MD_SUFFIX) for _d, _dirs, files in os.walk(str(source_dir)) for fname in files
    )
    if not has_md:
      status = UpstreamStatus.INVALID
    else:
      gated = _is_draft_gated(source_dir, title)
      # guard: first-ever landing of a unit whose own root note already carries `spec_draft:
      # true` — undo this tick's sync entirely, the fetch/detect phase never materializes it
      # (there is no prior state to freeze back to; it never existed before this tick)
      if gated and prior_status is None:
        shutil.rmtree(unit_dir, ignore_errors = True)
        return False, None
      # underlying content status first, independent of any postpone toggle — a postponed unit's
      # own resume action (§ 7) needs the status the toggle is shadowing, not `POSTPONED` itself
      cur_hash = _aggregate_hash(_tree_signature(source_dir), skipped_current)
      if not processed_dir.is_dir():
        underlying_status = UpstreamStatus.NEW
      else:
        skipped_processed = _extract_section(existing_body, _K.SKIPPED_PROCESSED_H1)
        processed_hash = _aggregate_hash(_tree_signature(processed_dir), skipped_processed)
        underlying_status = (
            UpstreamStatus.PROCESSED if cur_hash == processed_hash else UpstreamStatus.DRIFTED
        )
      content_status = underlying_status
      stored_postponed = existing_fm.get(UpstreamKey.POSTPONED_HASH)

      # an unticked POSTPONE toggle on a postponed note is the operator's cancel gesture (§ 7:
      # the operator's own release gesture) — release without a request; a note with no POSTPONE line at all
      # (rendered before the toggle existed) stays postponed
      postpone_cancelled = (
          prior_status == UpstreamStatus.POSTPONED
          and _has_unticked_action(existing_body, UpstreamAction.POSTPONE)
      )
      if stored_postponed and stored_postponed == cur_hash and not postpone_cancelled and (
          underlying_status in (UpstreamStatus.NEW, UpstreamStatus.DRIFTED)
      ):
        content_status = UpstreamStatus.POSTPONED
        postponed_hash = stored_postponed
      elif not gated and prior_status != UpstreamStatus.POSTPONED and underlying_status in (
          UpstreamStatus.NEW, UpstreamStatus.DRIFTED,
      ) and _is_action_ticked(existing_body, UpstreamAction.POSTPONE):
        # operator ticked "Postpone" on a fresh new/drifted unit (§ 7) — freeze this exact
        # content state; the primary checkbox's own resume-dispatch check further below still
        # runs unconditionally, so a same-commit tick of BOTH boxes still lets the primary
        # take-into-work action win and short-circuit past this render entirely
        content_status = UpstreamStatus.POSTPONED
        postponed_hash = cur_hash
      # a draft-gated unit never advances into a fresh new/drifted transition; every other
      # unit takes its freshly computed content status as-is
      if gated and content_status in (UpstreamStatus.NEW, UpstreamStatus.DRIFTED):
        status = prior_status if prior_status in _GATE_HOLD_STATUSES else UpstreamStatus.NEW
      else:
        status = content_status
        # a ticked take-into-work/process-update checkbox is only actionable on the two
        # statuses that ever carry one directly, or a postponed unit resuming into either
        if not gated and underlying_status in (UpstreamStatus.NEW, UpstreamStatus.DRIFTED):
          resume_status = underlying_status

  # Phase C: a ticked checkbox from the note as it stood before this tick's own rewrite wins
  # over the normal fetch/detect render below — the unit is about to freeze onto a request
  resume_label = _label_for_content_status(resume_status) if resume_status is not None else None
  if resume_status is not None and resume_label is not None and _is_action_ticked(
      existing_body, resume_label,
  ):
    return _dispatch_request(
        repo, content_root, unit_dir, note_path, unit_path, source_cfg,
        resume_status, revision, skipped_current, existing_body,
    )

  # render and persist the note, then commit whatever this pass actually changed on disk
  skipped_processed_for_note = _extract_section(existing_body, _K.SKIPPED_PROCESSED_H1)
  new_text = _render_note(
      unit_path = unit_path, status = status, revision = revision, url = source_cfg.get(_K.URL, ""),
      skipped_current = skipped_current, skipped_processed = skipped_processed_for_note,
      history_body = _history_section(existing_body), gated = gated, postponed_hash = postponed_hash,
      resume_label = resume_label, lang = resolve_language.resolve_repo_language(repo),
  )
  unit_dir.mkdir(parents = True, exist_ok = True)
  note_path.write_text(new_text)
  had_work = _commit_unit(repo, unit_dir, unit_path, status)
  return had_work, status


def _load_cursor(repo: Path) -> int:
  """
  Read the fetch phase's continuation cursor.

  Args:
    repo: Repository root.

  Returns:
    The persisted cursor index, or `0` when absent/malformed.
  """
  path = repo / _K.CURSOR_FILE
  # guard: no cursor persisted yet — start from the beginning
  if not path.is_file():
    return 0
  try:
    return int(json.loads(path.read_text()).get(_CURSOR_KEY, 0))
  except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
    return 0


def _save_cursor(repo: Path, cursor: int) -> None:
  """
  Persist the fetch phase's continuation cursor.

  Args:
    repo: Repository root.
    cursor: The next tick's starting index into the ordered unit list.
  """
  path = repo / _K.CURSOR_FILE
  path.parent.mkdir(parents = True, exist_ok = True)
  path.write_text(json.dumps({ _CURSOR_KEY: cursor }))


def _source_note_path(content_root: Path, repo_key: str) -> Path:
  """
  Resolve one configured source's own repo-level folder-note (§ 5).

  Args:
    content_root: Spec content-root.
    repo_key: The source's key.

  Returns:
    `<content_root>/upstream/<repo-key>/<repo-key>.md`.
  """
  return content_root / _K.UPSTREAM_ROOT / repo_key / f"{repo_key}{_K.MD_SUFFIX}"


# One-line description under the root catalog note's title, per vault authoring language.
_ROOT_NOTE_EXPLAINERS = {
    _K.LANG_EN: "_Mirrored external sources — one folder per configured source repo._",
    _K.LANG_RU: "_Зеркала внешних источников — по папке на каждый настроенный репозиторий._",
}


def _ensure_root_note(repo: Path, content_root: Path) -> Path | None:
  """
  Seed the root upstream catalog folder-note once, so the `upstream/` folder carries its icon.

  Args:
    repo: Repository root.
    content_root: Spec content-root.

  Returns:
    The created `<content_root>/upstream/upstream.md` path, or `None` when the note already
    exists — an existing note is operator territory and is never rewritten.
  """
  note_path = content_root / _K.UPSTREAM_ROOT / f"{_K.UPSTREAM_ROOT}{_K.MD_SUFFIX}"
  # guard: write-once — an existing note is operator-owned, byte-identical after this call
  if note_path.is_file():
    return None

  # seed the icon frontmatter plus a one-line description in the vault's authoring language
  explainer = _ROOT_NOTE_EXPLAINERS.get(
      resolve_language.resolve_repo_language(repo), _ROOT_NOTE_EXPLAINERS[_K.LANG_EN],
  )
  note_path.parent.mkdir(parents = True, exist_ok = True)
  note_path.write_text(
      "---\n"
      f"{_K.ICONIZE_ICON}: {_K.ROOT_NOTE_ICON}\n"
      f'{_K.ICONIZE_COLOR}: "{_K.INTAKE_COLOR}"\n'
      "---\n"
      f"{_K.ROOT_NOTE_TITLE}\n\n"
      f"{explainer}\n"
  )
  return note_path


# Decision: the Dataview block is scoped by `dv.current().file.folder`, not a repo-relative
# path substituted from the `spec.vault_root` setting — Obsidian resolves the note's own folder
# at render time, so the query needs no substituted root at all and stays correct however the
# vault is mounted; a substituted-root query would additionally require this Python module to
# re-derive vault_root at render time, for no benefit over letting Obsidian do it natively.

def _render_source_note(
    *, status: str, failures: int, error: str | None, last_success: str | None,
    invalid: list[tuple[str, str, str]] | None = None, refused_mounts: list[str] | None = None,
    lang: str = _K.LANG_EN,
) -> str:
  """
  Render one source's own repo-level folder-note (§ 5): fetch status, the vault-unsafe
  directory names this tick refused (§ 3), plus a live Dataview summary of every unit under it.

  The rendered text depends only on this function's own arguments (see module-level Decision
  comment above for why the Dataview block itself needs no unit-status input at all) — never on
  any UNIT's own current status, so the caller does not need to re-render this note just because
  a unit's status changed.

  Args:
    status: `UpstreamSourceStatus.OK` or `UpstreamSourceStatus.FAILING`.
    failures: Consecutive fetch-failure count this tick observed.
    error: The most recent fetch failure's own message; only rendered while `status` is
      `UpstreamSourceStatus.FAILING`.
    last_success: ISO date of the most recent successful fetch, or `None` before the first one.
    invalid: `(mount, unit_path, reason)` for every candidate directory this tick refused for a
      vault-unsafe name — never became a unit. Defaults to none refused.
    refused_mounts: Mount names whose `units` globs overlap this tick (§ 4: a refused mount is
      refused whole) — rendered as a line each under the fetch-status section so the refusal is
      visible on the note, not only in the tick log. Defaults to none refused.

  Returns:
    Full note text: frontmatter, title, fetch-status section, invalid-names section, Dataview
    unit summary.
  """
  invalid = invalid or []
  refused_mounts = refused_mounts or []
  # both extra frontmatter lines are status-scoped, same convention as _render_note's own
  # postponed/request lines: the error only survives while failing, the success date only once
  # there has been one
  error_line = (
      f"{UpstreamSourceKey.FETCH_ERROR}: {json.dumps(error)}\n"
      if status == UpstreamSourceStatus.FAILING and error else ""
  )
  last_success_line = (
      f"{UpstreamSourceKey.FETCH_LAST_SUCCESS}: {last_success}\n" if last_success else ""
  )

  # assemble the fixed-order frontmatter block, with the two status-scoped lines spliced in
  frontmatter = (
      "---\n"
      f"{UpstreamSourceKey.FETCH_STATUS}: {status}\n"
      f"{UpstreamSourceKey.FETCH_FAILURES}: {failures}\n"
      f"{error_line}"
      f"{last_success_line}"
      f"{_K.ICONIZE_ICON}: {_K.SOURCE_NOTE_ICON}\n"
      f'{_K.ICONIZE_COLOR}: "{_K.INTAKE_COLOR}"\n'
      "tags:\n"
      f"  - upstream/source/{status}\n"
      f"spec_role: {UpstreamRole.SOURCE}\n"
      "---\n"
  )

  # the human-readable status body under # Fetch status: the one-line fetch verdict, then one
  # bullet per overlap-refused mount
  status_body = (
      "_(ok)_" if status == UpstreamSourceStatus.OK else f"_(failing — {error or 'unknown error'})_"
  )
  for mount in sorted(refused_mounts):
    status_body += f"\n- `{mount}` — mount refused: overlapping `units` globs"

  # one bullet per refused directory (§ 3), sorted for tick-to-tick stability; empty list reads
  # as the same none-marker every other list section in this module renders
  invalid_body = (
      "\n".join(f"- `{mount}/{unit_path}` — {reason}" for mount, unit_path, reason in sorted(invalid))
      if invalid else _K.NONE_MARKER
  )

  # the live Dataview summary — written once, never re-derived from unit state (see docstring)
  dataview = (
      f"{_K.DATAVIEWJS_FENCE}\n"
      "const folder = dv.current().file.folder;\n"
      "const units = dv.pages('\"' + folder + '\"')\n"
      f"  .where(p => p.spec_role === \"{UpstreamRole.UNIT}\")\n"
      "  .sort(p => p.spec_upstream_status, \"asc\");\n"
      "dv.table(\n"
      "  [\"Unit\", \"Status\", \"Request\"],\n"
      "  units.map(p => [p.file.link, p.spec_upstream_status ?? \"\", p.spec_upstream_request ?? \"\"]),\n"
      ");\n"
      "```\n"
  )

  # the body's fixed section order — fetch status, invalid names, then the unit summary; every
  # section carries its self-documenting explainer line under the heading
  sections = [
      _with_explainer(f"{_K.SOURCE_NOTE_H1}\n{status_body}\n", lang),
      _with_explainer(f"{_K.SOURCE_INVALID_H1}\n{invalid_body}\n", lang),
      _with_explainer(f"{_K.SOURCE_UNITS_H1}\n{dataview}", lang),
  ]
  return frontmatter + "\n" + "\n".join(sections)


def _update_source_note(
    repo: Path, content_root: Path, repo_key: str, error: str | None, threshold: int, today: str,
    *, invalid: list[tuple[str, str, str]] | None = None, refused_mounts: list[str] | None = None,
    extra_paths: list[Path] | None = None,
) -> bool:
  """
  Recompute and, on change, rewrite one configured source's own repo-level folder-note (§ 5),
  in its own atomic commit — independent of `max_units_per_tick`, since this is bookkeeping
  about the SOURCE, not unit work.

  Retry bookkeeping (§ 5, retries accumulate up to the threshold): every tick is an attempt; the consecutive
  failure count persists in the note's own frontmatter and grows silently below `threshold` —
  the note's `FETCH_STATUS` only flips to `UpstreamSourceStatus.FAILING` once the count reaches
  it, and the first success afterward resets both.

  Args:
    repo: Repository root.
    content_root: Spec content-root.
    repo_key: The source's key.
    error: This tick's own fetch/plan error for this source, or `None` on success.
    threshold: The source's configured `fetch_failure_threshold`.
    today: ISO date string for a fresh `FETCH_LAST_SUCCESS` value.
    invalid: `(mount, unit_path, reason)` for every candidate this tick refused for a
      vault-unsafe name (§ 3) — always this tick's own, not carried over from a prior one.
    refused_mounts: Mount names whose `units` globs overlap this tick — always this tick's own.
    extra_paths: Additional freshly written paths folded into this note's own commit — the
      root catalog note's one-time seed rides here rather than in a commit of its own.

  Returns:
    `True` when the note changed and was committed this tick; `False` otherwise.
  """
  note_path = _source_note_path(content_root, repo_key)
  existing_fm, _existing_body = _read_note(note_path)

  # frontmatter scalars round-trip as strings (flip_gate._parse_frontmatter's own contract) —
  # a missing/malformed count reads as the "never failed" baseline, not a crash
  try:
    prior_failures = int(existing_fm.get(UpstreamSourceKey.FETCH_FAILURES, 0))
  except (TypeError, ValueError):
    prior_failures = 0
  prior_last_success = existing_fm.get(UpstreamSourceKey.FETCH_LAST_SUCCESS)
  prior_last_success = prior_last_success if isinstance(prior_last_success, str) else None

  # a success resets the streak unconditionally; a failure grows it and only flips the visible
  # status once it reaches the configured threshold (§ 5: retries accumulate up to the threshold)
  last_success: str | None
  if error is None:
    failures = 0
    status = UpstreamSourceStatus.OK
    note_error = None
    last_success = today
  else:
    failures = prior_failures + 1
    status = UpstreamSourceStatus.FAILING if failures >= threshold else UpstreamSourceStatus.OK
    note_error = error if status == UpstreamSourceStatus.FAILING else None
    last_success = prior_last_success

  # write-then-let-git-decide, same idiom as every other note this module writes
  note_path.parent.mkdir(parents = True, exist_ok = True)
  note_path.write_text(_render_source_note(
      status = status, failures = failures, error = note_error, last_success = last_success,
      invalid = invalid, refused_mounts = refused_mounts, lang = resolve_language.resolve_repo_language(repo),
  ))
  return _commit_paths(
      repo, [note_path, *(extra_paths or [])],
      f"lazy-spec.upstream-tick: {repo_key} source -> {status}",
  )


def run(repo: Path) -> dict:
  """
  Execute one `lazy-spec.upstream-tick` fetch/detect pass.

  Args:
    repo: Repository root.

  Returns:
    Summary dict: `units_ordered` (full unit-list size this tick computed), `units_visited`
    (how many this tick actually looked at), `units_touched` (how many spent the work budget),
    `statuses` (per-`UpstreamStatus` counts across every visited unit), and `errors` (unique
    per-source fetch-failure messages, isolated so one dead source never blocks another).
  """
  # config + limits first — everything below reads from these
  cfg = _load_upstream_config(repo)
  content_root = spec_paths.spec_content_root(repo)
  max_units = int(cfg.get(_K.MAX_UNITS, _K.DEFAULT_MAX_UNITS))
  max_bytes = int(cfg.get(_K.MAX_TEXT_BYTES, _K.DEFAULT_MAX_TEXT_BYTES))
  failure_threshold = int(cfg.get(_K.FETCH_FAILURE_THRESHOLD, _K.DEFAULT_FAILURE_THRESHOLD))

  # one plan per source, then the deterministic union that walk consumes
  tree_by_source = _plan_all_sources(repo, cfg)
  ordered, refused_mounts, invalid_names = _ordered_units(repo, cfg, content_root, tree_by_source)
  errors = sorted({
      f"{repo_key}: {error}" for repo_key, (_paths, error) in tree_by_source.items() if error is not None
  })

  # the root upstream catalog note is seeded once alongside the first configured source —
  # write-once, then operator-owned; it rides the first source note's own commit below
  root_note = _ensure_root_note(repo, content_root) if tree_by_source else None

  # every configured source gets its own repo-level note kept current — independent of
  # max_units_per_tick and of whether it has any matched units yet (§ 5)
  today = flip_gate._today(None)
  for repo_key, (_paths, error) in tree_by_source.items():
    _update_source_note(
        repo, content_root, repo_key, error, failure_threshold, today,
        invalid = invalid_names.get(repo_key, []),
        refused_mounts = sorted(
            mount_name for source_key, mount_name in refused_mounts if source_key == repo_key
        ),
        extra_paths = [root_note] if root_note is not None else None,
    )
    # the seed rides exactly one commit — once handed to the first source note, it is spent
    root_note = None

  # guard: nothing configured or nothing landed yet — no units to visit
  if not ordered:
    return { "units_ordered": 0, "units_visited": 0, "units_touched": 0, "statuses": {}, "errors": errors }

  # walk the ordered list circularly from the persisted cursor, spending budget only on work
  budget = max_units
  visited = 0
  idx = _load_cursor(repo) % len(ordered)
  statuses: dict[str, int] = {}
  touched = 0
  while visited < len(ordered) and budget > 0:
    repo_key, mount, unit_path = ordered[idx]
    tree_paths, tree_error = tree_by_source[repo_key]
    source_cfg = cfg[repo_key]
    mount_cfg = (source_cfg.get(_K.MOUNTS) or {}).get(mount) or {}
    mount_refused = (repo_key, mount) in refused_mounts
    had_work, status = _advance_unit(
        repo, content_root, repo_key, mount, unit_path, source_cfg, mount_cfg,
        tree_paths, tree_error, mount_refused, max_bytes,
    )
    # a `None` status is a draft-gated unit's undone first landing — it never materialized, so
    # there is nothing to count here (contrast every other status, which always counts)
    if status is not None:
      statuses[status] = statuses.get(status, 0) + 1
    if had_work:
      budget -= 1
      touched += 1
    visited += 1
    idx = (idx + 1) % len(ordered)

  # a full pass with budget to spare resets the cursor; an early stop resumes at the next unit
  next_cursor = 0 if visited >= len(ordered) else idx
  _save_cursor(repo, next_cursor)
  return {
      "units_ordered": len(ordered), "units_visited": visited, "units_touched": touched,
      "statuses": statuses, "errors": errors,
  }


class DoctorFinding:
  """
  Closed vocabulary of `doctor_scan` finding kinds (`docs/tasks/lazycortex-specs.upstream.md`
  § 13). Every kind here is a FAIL — `doctor_scan` never emits a WARN-severity finding; the
  severity call is `lazy-spec.doctor`'s own, made against the calling agent's report format.

  Attributes:
    UNCONFIGURED_SOURCE: A `upstream/<repo-key>/` subtree exists with no matching config entry
      (§ 12: a subtree on disk with no matching config entry).
    UNCONFIGURED_MOUNT: A `upstream/<repo-key>/<mount>/` subtree exists with no matching mount
      in that source's config.
    MISSING_NOTE: A unit directory (carries `source/` or `processed/`) has no own note file.
    TAG_STATUS_MISMATCH: A unit note's `tags:` list does not mirror its own
      `spec_upstream_status` value.
    PROCESSED_WITHOUT_SNAPSHOT: A unit note reads `UpstreamStatus.PROCESSED` but its
      `processed/` directory is missing or empty. Content divergence in a populated
      `processed/` is not checked (see `_scan_unit`).
    DANGLING_REQUEST_LINK: A `UpstreamStatus.IN_REVIEW` unit's request link is missing, or
      present but does not resolve to an existing request file (§ 8: dangling mutex).
    UNKNOWN_ACTION_LABEL: A unit note's `# Actions` section carries a checkbox label outside
      the closed `UpstreamAction` set (deferred from Task 5's own scope to this one).
    CLONE_ORIGIN_MISMATCH: A configured source's working clone points at a different remote
      than its current `url` (Task 4's own guard, surfaced here by name for the operator).
  """

  UNCONFIGURED_SOURCE = "unconfigured-source"
  UNCONFIGURED_MOUNT = "unconfigured-mount"
  MISSING_NOTE = "missing-note"
  TAG_STATUS_MISMATCH = "tag-status-mismatch"
  PROCESSED_WITHOUT_SNAPSHOT = "processed-without-snapshot"
  DANGLING_REQUEST_LINK = "dangling-request-link"
  UNKNOWN_ACTION_LABEL = "unknown-action-label"
  CLONE_ORIGIN_MISMATCH = "clone-origin-mismatch"


def _finding(kind: str, repo_key: str, detail: str, *, unit_path: str | None = None) -> dict:
  """
  Build one `doctor_scan` finding entry.

  Args:
    kind: One of `DoctorFinding`'s closed set.
    repo_key: The source the finding belongs to.
    detail: Human-readable one-line explanation.
    unit_path: The unit's own path, relative to its mount's `source_path`, when the finding is
      unit-scoped; `None` for a source- or mount-scoped finding.

  Returns:
    `{kind, repo_key, unit_path, detail}`.
  """
  return { "kind": kind, "repo_key": repo_key, "unit_path": unit_path, "detail": detail }


def _configured_mounts(cfg: dict, repo_key: str) -> set[str]:
  """
  List one configured source's own mount names.

  Args:
    cfg: Parsed `spec.upstream` section.
    repo_key: The source's key.

  Returns:
    Set of configured mount names for `repo_key`.
  """
  return set(_mount_source_paths(cfg.get(repo_key) or {}).keys())


def _material_unit_dirs(mount_base: Path) -> dict[str, Path]:
  """
  Enumerate every directory under one mount's own base that carries unit material — a
  `source/` or `processed/` child — regardless of whether it also carries a note.

  Args:
    mount_base: `<content_root>/upstream/<repo-key>/<mount>/`.

  Returns:
    `{unit_path: unit_dir}`, `unit_path` POSIX-relative to `mount_base`; empty when the mount
    has nothing landed yet.
  """
  # guard: mount subtree not materialized yet — nothing to enumerate
  if not mount_base.is_dir():
    return {}
  found: dict[str, Path] = {}
  for dirpath, _dirs, _files in os.walk(str(mount_base)):
    unit_dir = Path(dirpath)
    # guard: the mount base itself is never a unit
    if unit_dir == mount_base:
      continue
    if (unit_dir / _K.SOURCE_DIR).is_dir() or (unit_dir / _K.PROCESSED_DIR).is_dir():
      found[unit_dir.relative_to(mount_base).as_posix()] = unit_dir
  return found


def _unknown_action_labels(body: str) -> list[str]:
  """
  Read every checkbox label under a unit note's `# Actions` section, regardless of tick state.

  Args:
    body: A unit note's full body text (frontmatter stripped).

  Returns:
    Sorted, de-duplicated labels found outside `UPSTREAM_ACTION_LABELS` — empty when the
    section is absent or every label present is a recognised one.
  """
  # guard: no actions section at all — nothing to check
  if _K.ACTIONS_H1 not in body:
    return []
  section = body.split(_K.ACTIONS_H1, 1)[1].split("\n#", 1)[0]
  labels = {
      match.group(1)
      for match in re.finditer(r"^- \[[ x]\] (.+)$", section, re.MULTILINE)
      if match.group(1) not in UPSTREAM_ACTION_LABELS
  }
  return sorted(labels)


def _parse_tags(text: str) -> list[str]:
  """
  Read a block-style `tags:` list back out of frontmatter text.

  `flip_gate._parse_frontmatter` is a flat-scalar parser only — it skips every bullet line
  (`stripped.startswith(("#", "-"))`), so a block list like `tags:\\n  - upstream/new` reads
  back as an empty string there. Every value this module ever renders under `tags:` is exactly
  this bullet-list shape (`_render_note`, `_render_source_note`), so a small dedicated reader
  is cheaper and less surprising than growing the shared parser to handle general YAML lists it
  otherwise never needs.

  Args:
    text: A note's full text (frontmatter plus body) or just its frontmatter block.

  Returns:
    Every bulleted value under the first `tags:` line found, in document order; empty when no
    `tags:` header line is present or it introduces no bullets.
  """
  # guard: no tags header at all
  if not (match := re.search(r"^tags:\s*$", text, re.MULTILINE)):
    return []
  out: list[str] = []
  for line in text[match.end():].splitlines():
    if bullet := re.match(r"^\s*-\s*(.+?)\s*$", line):
      out.append(bullet.group(1))
      continue
    # guard: a blank line before the first bullet is just the header's own line break; once a
    # bullet has landed, the first non-bullet line (blank or not) ends the list
    if out or line.strip():
      break
  return out


def _scan_unit(repo: Path, repo_key: str, unit_path: str, unit_dir: Path) -> list[dict]:
  """
  Run every unit-scoped § 13 check against one unit directory.

  Args:
    repo: Repository root.
    repo_key: The unit's source key.
    unit_path: The unit's own path, relative to its mount's `source_path`.
    unit_dir: The unit's own directory.

  Returns:
    Findings for this unit — empty when it is clean.
  """
  title = unit_path.rsplit("/", 1)[-1]
  note_path = unit_dir / f"{title}{_K.MD_SUFFIX}"
  findings: list[dict] = []

  # guard: material with no note at all — every other check below reads the note, so it
  # cannot run without one
  if not note_path.is_file():
    return [_finding(
        DoctorFinding.MISSING_NOTE, repo_key,
        f"`{unit_dir}` carries source/ or processed/ but no `{title}.md` note",
        unit_path = unit_path,
    )]

  # every check below is a pure read against the note's frontmatter/body or raw text
  fm, body = _read_note(note_path)
  status = fm.get(UpstreamKey.STATUS, "")

  # status <-> tags mirror (a hand-edit could desync the two independently) — tags is a block
  # list, unreadable through the flat-scalar fm dict (see _parse_tags)
  if status and f"upstream/{status}" not in _parse_tags(note_path.read_text()):
    findings.append(_finding(
        DoctorFinding.TAG_STATUS_MISMATCH, repo_key,
        f"note reads `spec_upstream_status: {status}` but `tags:` lacks `upstream/{status}`",
        unit_path = unit_path,
    ))

  # Decision: check emptiness only, not content divergence between a non-empty processed/ and
  # what the note's own hash would predict — the fetch/detect ladder already recomputes that
  # divergence into DRIFTED on its very next tick, so a doctor-side content check would only
  # ever catch a state already self-correcting; the write-time invariant below is the one gap
  # the ladder itself cannot see (a crash or hand-edit between ticks).

  # processed at rest with an empty/missing snapshot — the fetch/detect ladder can only ever
  # write PROCESSED alongside a populated processed/, so a mismatch means a hand-edit or a
  # crash mid-write
  if status == UpstreamStatus.PROCESSED:
    processed_dir = unit_dir / _K.PROCESSED_DIR
    if not (processed_dir.is_dir() and any(processed_dir.iterdir())):
      findings.append(_finding(
          DoctorFinding.PROCESSED_WITHOUT_SNAPSHOT, repo_key, _PROCESSED_WITHOUT_SNAPSHOT_DETAIL,
          unit_path = unit_path,
      ))

  # dangling request link — § 8's own doctor-visible mutex: IN_REVIEW with no resolvable
  # request. `_advance_frozen_unit` already reports this same condition every tick it runs
  # (`had_work=False`) without ever fixing it — this is that same read, surfaced as a finding.
  if status == UpstreamStatus.IN_REVIEW:
    request_raw = fm.get(UpstreamKey.REQUEST)
    if not request_raw:
      findings.append(_finding(
          DoctorFinding.DANGLING_REQUEST_LINK, repo_key, _IN_REVIEW_NO_LINK_DETAIL,
          unit_path = unit_path,
      ))
    elif _read_request_frontmatter(repo, _wikilink_target(request_raw)) is None:
      findings.append(_finding(
          DoctorFinding.DANGLING_REQUEST_LINK, repo_key,
          f"linked request `{request_raw}` no longer resolves",
          unit_path = unit_path,
      ))

  # unrecognized checkbox label under # Actions — closed UpstreamAction set (deferred from
  # Task 5)
  for label in _unknown_action_labels(body):
    findings.append(_finding(
        DoctorFinding.UNKNOWN_ACTION_LABEL, repo_key,
        f"`# Actions` carries unrecognized label `{label}`",
        unit_path = unit_path,
    ))
  return findings


def doctor_scan(repo: Path) -> dict:
  """
  Run every `spec.upstream` § 13 doctor check, read-only.

  Wiki.domains-style honesty (§ 13): when `spec.upstream` carries no configured source, this
  returns `configured: False` with no findings at all — a scope the operator never set up has
  nothing to be wrong. Every finding kind here is `lazy-spec.doctor`'s own to render as FAIL; this
  worker never distinguishes severity or offers a fix — `orphaned` / `invalid` / `excluded` /
  `postponed` units and an active `in-review` freeze are the documented steady states (§ 13)
  and are never findings on their own.

  Guarantees:
    - Never writes to disk or to git — every call is a pure read, whatever it finds.
    - Returns `configured: False` with an empty `findings` list, never a finding of any kind,
      when `spec.upstream` has no configured source at all.

  Args:
    repo: Repository root.

  Returns:
    `{configured, findings}` — `findings` is a list of `{kind, repo_key, unit_path, detail}`
    dicts, `kind` drawn from `DoctorFinding`'s closed set.
  """

  # Contract:
  # Read-only: no write, no commit, ever. `lazy-spec.doctor` (Check 9) and its own fix loop rely
  # on this — a doctor scan must never itself be the thing that changes state.

  cfg = _load_upstream_config(repo)
  repo_keys = _source_keys(cfg)

  # guard: nothing configured — silent, not a finding (wiki.domains-style honesty)
  if not repo_keys:
    return { "configured": False, "findings": [] }

  # resolve the vault-relative walk root once, for every check below
  upstream_root = spec_paths.spec_content_root(repo) / _K.UPSTREAM_ROOT
  findings: list[dict] = []

  # subtrees on disk with no matching config entry (§ 12: a subtree on disk with no matching config entry)
  on_disk_repo_keys = (
      { path.name for path in upstream_root.iterdir() if path.is_dir() }
      if upstream_root.is_dir() else set()
  )
  for stray_key in sorted(on_disk_repo_keys - set(repo_keys)):
    findings.append(_finding(
        DoctorFinding.UNCONFIGURED_SOURCE, stray_key,
        f"`upstream/{stray_key}/` exists but `spec.upstream.{stray_key}` is not configured",
    ))

  # walk every configured source: its own clone, its own stray mounts, its own units
  for repo_key in repo_keys:
    url = cfg[repo_key].get(_K.URL, "")
    clone_dir = _clone_dir(repo, repo_key)
    if _clone_origin_mismatch(clone_dir, url):
      findings.append(_finding(
          DoctorFinding.CLONE_ORIGIN_MISMATCH, repo_key,
          f"working clone at `{clone_dir}` does not point at the configured url '{url}'",
      ))

    # mounts on disk with no matching config entry, same shape as the repo-key check above
    repo_base = upstream_root / repo_key
    configured_mounts = _configured_mounts(cfg, repo_key)
    on_disk_mounts = (
        { path.name for path in repo_base.iterdir() if path.is_dir() }
        if repo_base.is_dir() else set()
    )
    for stray_mount in sorted(on_disk_mounts - configured_mounts):
      findings.append(_finding(
          DoctorFinding.UNCONFIGURED_MOUNT, repo_key,
          f"`upstream/{repo_key}/{stray_mount}/` exists but no mount by that name is configured",
      ))

    # every unit under every mount that is BOTH configured and materialized on disk
    for mount in sorted(configured_mounts & on_disk_mounts):
      for unit_path, unit_dir in sorted(_material_unit_dirs(repo_base / mount).items()):
        findings.extend(_scan_unit(repo, repo_key, unit_path, unit_dir))

  # every check above folded into one flat findings list
  return { "configured": True, "findings": findings }


def main(argv: list[str]) -> int:
  """
  Run the `upstream-tick` subcommand.

  Args:
    argv: Subcommand tail (optional `--cwd`).

  Returns:
    `0` on a completed pass — a per-source fetch failure is isolated and reported in the
    printed summary's `errors` list, never raised.

  Raises:
    SystemExit: `argparse` rejects an unrecognised flag or a missing option value (exit `2`).
    RuntimeError: The `lazycortex-core` CLI could not be resolved, or crashed outside its own
      documented `{"error": ...}` contract.
  """
  parser = argparse.ArgumentParser(prog = _K.PROG)
  parser.add_argument(_K.ARG_CWD, default = None)
  args = parser.parse_args(argv)
  repo = Path(args.cwd).resolve() if args.cwd else spec_paths.find_settings_root(Path.cwd())
  print(json.dumps(run(repo)))
  return 0


def main_doctor(argv: list[str]) -> int:
  """
  Run the `upstream-doctor` subcommand.

  Args:
    argv: Subcommand tail (optional `--cwd`).

  Returns:
    `0` always — `doctor_scan` is read-only and reports every finding in its own JSON output
    rather than raising.
  """
  parser = argparse.ArgumentParser(prog = _K.DOCTOR_PROG)
  parser.add_argument(_K.ARG_CWD, default = None)
  args = parser.parse_args(argv)
  repo = Path(args.cwd).resolve() if args.cwd else spec_paths.find_settings_root(Path.cwd())
  print(json.dumps(doctor_scan(repo)))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
