"""
Coordinator wake-trigger worker for the `lazy-spec.coordinator-watch` and `lazy-spec.coordinator-deletes`
git-watch routines.

Invoked once per tick, via a `type: git`, `watch: changed_files` routine (`lazycortex-core`'s
own file-level git-watch — see `routine_types._compute_git_items`) rather than a periodic
directory scan. Under the routine's default `group: "all"` the daemon hands every changed
markdown file of the tick to this worker as ONE `{dir: ".", paths, sha, author_name,
author_email}` item in a single JSON argv; a consumer that declared `group: "dir"` or a glob
list hands a `{dir, paths, ...}` item per matched directory instead, and `group: "file"` the
plain `{path, status, sha, author_name, author_email}` item per file. A non-bot commit
reaching this checkout IS trigger 1 (`operator-edit`) —
there is no dirty-tree signal to read, because the operator's edit lives in a different
checkout until it is committed AND pushed AND pulled here
(`.superpowers/sdd/2026-08-10-spec-coordinator/model-audit.md` § Step 0). Beyond that,
detects a non-empty `# Coordinator commands` section or a ticked option under one of the
coordinator's own `[!question]` callouts — and, when any of the three fires, dispatches one
`spec.coordinator` expert job via the `lazycortex-core dispatch-job` CLI (the same § 1c
boundary contract `gate_dispatch.py` uses for launch-checkbox jobs). The `coordinator_job`
marker in `spec_job_markers.py`'s gitignored runtime sidecar enforces one active coordinator job per
asset; the git-watch routine's own cursor (not a marker) is what keeps a repeat tick with
no new commit from re-dispatching, and this worker's own dispatch-cursor store beside the
sidecar records the last item sha dispatched on per note, bounding the bot-buried-operator
lookback so an already-handled operator commit never re-dispatches. Because all of that lives
outside the note, neither stamping nor clearing it costs a commit, and no hand-edit of the
note can break the mutex; a wake itself writes and commits the note only when a frontmatter
stamp or a warning line actually changed it.

The routine's `filter.any_of` also matches every authored doc carrying a non-null
`spec_doc_type` — an item naming one of those is resolved to its OWNING asset's status
folder-note, and dispatched on a `review_result` transition against a content-shaped marker
recorded on that note (`spec_coordinator_doc_state`), independent of the sibling commit's own
author (`CoordinatorTrigger.DOC_TRANSITION` — see `_resolve_doc_transition`).

The grouped `{dir, paths, sha, author_name, author_email}` item is the shape a tick normally
takes: every changed member of the range at once, under a `dir` that is the repo root (`.`)
by default. The `dir` is a coarse bucket, never an asset boundary — `main` splits the members
by the nearest status folder-note between each member's own folder and `dir`, so an asset
whose status note and/or sibling docs changed gets exactly one coordinator job per tick
regardless of how many of its members changed, honoring the same trigger priority as the
single-file form (COMMAND, halt, ANSWER, JOB_DONE, DOC_TRANSITION, OPERATOR_EDIT) but scanning
every member for a `review_result` transition in one pass instead of one file at a time, and
reading OPERATOR_EDIT off the group's own last commit (the item's own `sha`/`author_email`)
rather than a single file's. A member no status note owns is dispatched as the single-file
item it would have been ungrouped. When one owner's or one orphan's dispatch raises, the rest
of the tick still runs, and the worker closes with the daemon's partial-failure line —
`{"failed_paths": [...]}` last on stdout, exit 1 — so only those members are retried.

The `lazy-spec.coordinator-deletes` routine (`watch: deleted_files`, no frontmatter filter) feeds the
same worker, so an item may name paths that no longer exist. A deleted path wakes the note that still
owns its place as an ordinary operator edit: the asset's status note while the asset folder stands,
else the owning product's level note. A system document deleted from the spec content root wakes the
catalog root's level note, and one deleted from a product root wakes that product's level note. A
deletion authored by a bot identity, or one no coordinated note owns, wakes nothing. In a grouped
item, a deleted sibling of an asset still on disk joins that asset's one dispatch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from collections.abc import Callable, Mapping


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import asset_types  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import error_report  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import gate_dispatch  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import gate_tick  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import history_journal  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_explainers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_ops  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import resolve_product  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_doc_types  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_job_markers  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_keys import (  # noqa: E402  # pylint: disable=import-error,wrong-import-position
    LEVEL_ROLES,
    AnsweredQuestionKey,
    AssetTypeKey,
    CoordinatorTrigger,
    Gate,
    JobMarker,
    LevelDoc,
    PluginErrorCause,
    ReleaseKey,
    Section,
    SpecCoordinatorDocStateKey,
    SpecCoordinatorReadyStateKey,
    SpecHaltKey,
    SpecKey,
    SpecTargetsKey,
    SpecValue,
    Stage,
    StageKey,
    TickAction,
)


# The fixed expert this worker ever dispatches — unlike `gate_dispatch`'s per-checkbox review-
# class resolution, the coordinator is one persona for every asset (`spec.coordinator`,
# registered live per `lazy-spec.coordination-playbook.md` § 1), never resolved from a review class.
_COORDINATOR_EXPERT = "spec.coordinator"

# The second persona this worker routes to, chosen by the woken folder-note's own `spec_role`
# rather than by anything on the wire: a level note (`LEVEL_ROLES` — a product's own note or the
# catalog root's) is this expert's, every asset status note stays `_COORDINATOR_EXPERT`'s.
_CATALOG_EXPERT = "spec.catalog-coordinator"

# The guideline role folded into context via `gate_dispatch.collect_guideline_paths`, per
# `lazy-spec.coordination-playbook.md` § 2 layer 3 (`products[<key>].guidelines.coordinator` + `"*"`).
_COORDINATOR_ROLE = "coordinator"
_GUIDELINES_KEY = "guidelines"

# Bot identity for this worker's own commit (frontmatter stamps, warning lines) — the `@bot.`
# substring is what the coordinator's own self-suppression check (playbook § 1) relies on to
# never re-wake itself on this worker's writes.
_DISPATCH_AUTHOR_NAME = "lazy-spec.coordinator-watch"
_DISPATCH_AUTHOR_EMAIL = "lazy-spec.coordinator-watch@bot.invalid"

# This worker's own dispatch-cursor store beside the job-marker sidecar: one sha per note — the
# last git-watch item dispatched on — bounding `_has_operator_authored_recently`'s scan so an
# already-handled operator commit never re-dispatches. Runtime scratch like the sidecar: losing
# it costs at most one duplicate dispatch, so it is rebuilt rather than guarded.

# Decision: the lookback bound lives in a gitignored runtime store, not in a `# History` wake
# line whose commit doubled as the bound — the wake lines were daemon mechanics polluting an
# operator-facing section, and on a single-daemon deployment the sidecar loses nothing the
# commit protected; the cost accepted is one possible duplicate dispatch on a checkout whose
# store is fresh, which the dedup key and the active-job guard absorb.

_CURSOR_SIDECAR = "lazy-specs.dispatch-cursors.json"
_CURSOR_TMP_SUFFIX = ".tmp"

# Frontmatter key listing the requests a document was attributed to — a small literal kept local
# rather than imported, so the module takes on no import coupling for one string.
_SPEC_SOURCE_REQUESTS = "spec_source_requests"

# Bundle wire key naming the protocol references `lazycortex-core dispatch-job` unions with the
# dispatching routine's own — a small literal kept local rather than imported, so the module takes
# on no import coupling for one string.
_WIRE_PROTOCOLS = "protocols"

# The two keys of the snapshot whose change of value wakes the release owner above the asset
_APPROVAL_EDGES = ( Gate.DESIGN_DONE, Gate.SPEC_CANCELLED )
# Prefix of the error-ledger incident key a failed release-owner wake opens, followed by the level note's path
_WAKE_INCIDENT_PREFIX = "spec-wake:"

# Settings-section keys for the vault-wide coordination-rules doc (`lazy-spec.config-protocol.md`).
_SPEC_SECTION = "spec"
_COORD_RULES_KEY = "coordination_rules"

# Product-record key holding a product's vault-relative spec-content path (`resolve_product.py`).
_SPEC_PATH_KEY = "spec_path"

# `[!question]` callout detection and its ticked-option marker, per
# `lazy-spec.coordination-playbook.md` § 9. `_QUESTION_HEAD_RE` alone matches ANY `[!question]`
# callout, coordinator-authored or not — `_QUESTION_ATTRIBUTION` is what narrows a ticked one
# down to the coordinator's own pen (below).
_QUESTION_HEAD_RE = re.compile(r"^>\s*\[!question\]")
_CALLOUT_HEAD_RE = re.compile(r"^>\s*\[!")
_TICKED_OPTION_RE = re.compile(r"^>\s*-\s*\[x\]", re.IGNORECASE)

# The coordinator's own pen format for a `[!question]` callout it writes (`lazy-spec.coordinator.md`
# "Your pen" + `lazy-spec.coordination-playbook.md` § 9) — its LAST quoted line, exactly. An
# expert-authored or operator-authored `[!question]` never carries this line, so a ticked option
# under one of THOSE blocks never satisfies `_find_ticked_question_block`'s attribution check
# below and never wakes the ANSWER trigger.
_QUESTION_ATTRIBUTION = "> — spec.coordinator"

# The same attribution line for the level persona, and the closed set of both. A level note's
# questions are signed by the catalog coordinator, so an ANSWER on one would never match the
# asset persona's line; membership in this two-element set is what lets one ladder serve both,
# and an expert- or operator-authored `[!question]` still matches neither.
_CATALOG_QUESTION_ATTRIBUTION = f"> — {_CATALOG_EXPERT}"
_QUESTION_ATTRIBUTIONS = frozenset({ _QUESTION_ATTRIBUTION, _CATALOG_QUESTION_ATTRIBUTION })

# ATX heading boundary: a line opening with one to six `#` and whitespace ends the section above it.
_HEADING_RE = re.compile(r"^#{1,6}\s")

# HTML comment span — strips the shipped `<!-- ... -->` placeholder before the emptiness test,
# so a section that still carries only the scaffolded instruction comment reads as empty.
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

# Self-suppression substring — any commit author whose email contains this never counts as
# operator activity (`lazy-spec.coordination-playbook.md` § 1).
_BOT_MARK = "@bot."

# Wire keys on a `changed_files` git-watch item (`routine_types._compute_git_items`).
_ITEM_PATH = "path"
_ITEM_AUTHOR_NAME = "author_name"
_ITEM_AUTHOR_EMAIL = "author_email"
_ITEM_SHA = "sha"

# Additional wire keys on a grouped git-watch item (`routine_types._group_git_items`) — `dir`
# replaces `_ITEM_PATH` as the item's own subject, `paths` names every changed member under it.
_ITEM_DIR = "dir"
_ITEM_PATHS = "paths"

# Key of the partial-failure line a `command` worker prints LAST on stdout before exiting
# non-zero (`lazy-core.routine-types-schema.md` § Partial failure of a multi-path unit): the
# daemon retries only the member paths it names, never the paths that already dispatched.
_FAILED_PATHS = "failed_paths"

# `spec_role` value naming an asset's own status folder-note — the one role that runs the asset
# ladder; a document lying directly in a product root or the content root resolves to a level
# note instead, and a loose document to a folder-note carrying neither role, which is skipped.
_SPEC_ROLE_STATUS = "status"

# Bounded lookback window for `_has_operator_authored_recently`'s bot-buried-operator-commit
# rescue (N3) — see that function's docstring for why this is a fixed window, not a range scan.
_AUTHOR_LOOKBACK_COMMITS = 10

# The two frontmatter keys the busy-guard used to stamp before the sidecar-declined migration —
# their bare string values, kept local because the shared key vocabulary dropped both once every
# writer of them retired. Read-only here: an old
# install's note still carrying either is treated as a declined-wake for one tick and the keys
# are stripped (`_strip_legacy_pending`), never re-written.
_LEGACY_PENDING_EDIT_KEY = "spec_coordinator_pending_edit"
_LEGACY_PENDING_DOC_KEY = "spec_coordinator_pending_doc"


def read_section_body(body: str, heading: str) -> str:
  """
  Extract the text inside the section opened by `heading`, up to the next ATX heading.

  Args:
    body: The folder-note section text to search.
    heading: The exact heading line to locate (e.g. `# Coordinator commands`).

  Returns:
    The stripped section text — with `heading`'s own protected-owner tag line and any HTML
    comment removed first — or `""` when the heading is absent or its section is empty.
  """
  # locate the heading line itself
  lines = body.splitlines()
  head_idx = None
  for idx, line in enumerate(lines):
    if line.strip() == heading:
      head_idx = idx
      break

  # guard: heading not present — nothing to extract
  if head_idx is None:
    return ""

  # the next real ATX heading closes the section; absent one, the section runs to the end
  end = len(lines)
  for pos in range(head_idx + 1, len(lines)):
    if _HEADING_RE.match(lines[pos]):
      end = pos
      break

  # drop the section's own `#protected/<owner>/<region>` tag line — structural
  # scaffolding, never operator content; an operator line that happens to match some OTHER
  # section's tag still counts, so this only ever strips the tag this exact heading owns
  section_lines = lines[head_idx + 1:end]
  if section_lines and section_lines[0].strip() == note_ops.PROTECTED_MARKERS.get(heading):
    section_lines = section_lines[1:]

  # drop the section's own explainer line the same way — self-description, never operator content
  if section_lines and note_explainers.is_explainer_line(section_lines[0], heading):
    section_lines = section_lines[1:]

  # strip HTML comments before the emptiness test — the shipped template placeholder is one,
  # and it must never read as operator-authored content
  return _HTML_COMMENT_RE.sub("", "\n".join(section_lines)).strip()


def _is_attributed_ticked_block(ticked: bool, block_lines: list[str]) -> bool:
  """
  Check whether a candidate `[!question]` block is both ticked and the coordinator's own.

  A ticked block whose last non-empty quoted line is not one of the coordinator personas'
  attribution lines (compared trimmed) is a foreign — expert-authored or otherwise
  non-coordinator — question that happens to carry a ticked option; it is never an answer to
  one of the coordinator's own questions. Trailing empty quoted lines (a bare `>` continuation
  after the attribution) are ignored.

  Args:
    ticked: Whether the block carries a ticked `- [x]` option.
    block_lines: The block's accumulated raw lines, head line first.

  Returns:
    True when `ticked` is set and the last non-empty line in `block_lines` trims to one of
    `_QUESTION_ATTRIBUTIONS`.
  """

  # Domain(spec.lifecycle):
  # # Attributed-answer detection
  # A ticked option under a question callout counts as an answer to the coordinator only when
  # the callout carries the coordinator's own signed closing line — a question an expert or an
  # operator raised, even ticked, is never mistaken for a reply to something the coordinator
  # itself asked. Two personas share this recognition, each signed with its own line, so a note
  # that hosts both an asset-level and a product-level coordinator still tells their own
  # questions apart. Scanning back past any blank continuation line before comparing the
  # signature also matters, since a trailing blank line under a genuine signature must not
  # defeat a real match.

  # an unticked block never reaches ANSWER regardless of attribution
  if not ticked:
    return False

  # scan backward past any trailing blank quoted line (bare `>`) to the last substantive one
  for line in reversed(block_lines):
    stripped = line.strip()

    # a blank quote continuation carries no content to compare — keep scanning back
    if stripped == ">":
      continue
    return stripped in _QUESTION_ATTRIBUTIONS
  return False


def _find_ticked_question_block(body: str) -> str | None:
  """
  Locate the first coordinator-attributed `[!question]` callout in `body` carrying a ticked
  `- [x]` option.

  A ticked block that does NOT end in one of the coordinator personas' own attribution lines is
  skipped rather than returned — scanning continues past it, so a foreign ticked question
  earlier in the body never hides a genuine coordinator question further down.

  Args:
    body: The folder-note section text to search.

  Returns:
    The matching block's raw text (from its `[!question]` head line through its attribution
    line), or None when no `[!question]` block carries both a ticked option and the
    coordinator's own attribution.
  """
  in_block = False
  ticked = False
  block_lines: list[str] = []

  # walk the body once, tracking whether the current line sits inside a `[!question]` block
  for line in body.splitlines():
    stripped = line.strip()

    # entering a [!question] callout — flush a prior attributed-ticked block first
    if _QUESTION_HEAD_RE.match(stripped):
      if in_block and _is_attributed_ticked_block(ticked, block_lines):
        return "\n".join(block_lines)
      in_block, ticked, block_lines = True, False, [line]
      continue

    # lines outside a question block are passed over
    if not in_block:
      continue

    # a different callout starts, or the quote-block ends — this question block is over
    if _CALLOUT_HEAD_RE.match(stripped) or not stripped.startswith(">"):
      if _is_attributed_ticked_block(ticked, block_lines):
        return "\n".join(block_lines)
      in_block = False
      continue
    block_lines.append(line)
    if _TICKED_OPTION_RE.match(stripped):
      ticked = True

  # the body ended while still inside an attributed-ticked block (no trailing heading)
  if in_block and _is_attributed_ticked_block(ticked, block_lines):
    return "\n".join(block_lines)
  return None


def _compute_answer_fingerprint(block: str) -> str:
  """
  Compute a content fingerprint for a ticked `[!question]` block.

  Args:
    block: The ticked question block's raw text, as returned by `_find_ticked_question_block`.

  Returns:
    A hex digest identifying this exact block content.
  """

  # Decision: content hash, not a commit sha — `model-audit.md` I-A: a sha-valued marker can name a
  # commit the daemon later rewrites or destroys on a push conflict, permanently losing the
  # marker's meaning; a content hash keeps meaning whatever commit currently carries this text

  # the digest of the block's exact text is the fingerprint
  return hashlib.sha256(block.encode()).hexdigest()


def _has_operator_authored_recently(repo_root: Path, item: dict, cursor: str | None) -> bool:
  """
  Check whether the item's author, or a recent commit touching the same path, is non-`@bot.`.

  Args:
    repo_root: The repository root to run `git` in.
    item: The git-watch `changed_files` item for this note.
    cursor: The last item sha this worker dispatched on for the note, from the dispatch-cursor
      store; None when nothing is recorded yet.

  Returns:
    True when the item's own author is non-bot, or when the path's commits after `cursor`
    (falling back to a bounded window of the most recent ones when no cursor is usable) include
    a non-bot author; False otherwise, including when the item carries no usable `path` / `sha`.
  """

  # Domain(spec.lifecycle):
  # # Buried-operator-commit rescue for a git-watch tick
  # A change watch hands the coordinator only the single most recent commit on a document's own
  # path, so an operator's edit is invisible to that commit alone whenever an automated commit
  # lands on the same path afterward, inside the same watch window — the operator's edit is
  # buried under the newer one. The rescue scans the document's own commit history since the
  # last commit the coordinator actually reacted to, and treats any commit in that span authored
  # by someone other than the automation's own identity as proof an operator touched the
  # document during the window, even though the watch item itself points at the later, automated
  # commit. Without a known starting point for the scan, the rescue instead looks back a fixed
  # number of commits and stops early the moment it reaches one of the coordinator's own
  # historic commits, since everything before that point has already been accounted for.

  # an item whose own author is non-bot answers the check at once
  if _BOT_MARK not in item.get(_ITEM_AUTHOR_EMAIL, ""):
    return True

  # a bot-authored tip can bury an operator commit on the same path within one pull batch (N3;
  # the same failure mode fixed for the note's own commit history in cfed7046, before this
  # worker's git-watch resew)
  sha = item.get(_ITEM_SHA)
  path = item.get(_ITEM_PATH)

  # guard: nothing to scan without both fields
  if not sha or not path:
    return False

  # the cursor bounds the scan to commits this worker has not dispatched on yet (N6 — without a
  # lower bound, the same operator commit re-fires on every later bot tick until it ages out of
  # the window); a cursor git no longer knows (rewritten history, a sha recorded on another
  # checkout) falls through to the fixed window below
  if cursor:
    ranged = subprocess.run(
        ["git", "log", "--format=%ae", "-n", str(_AUTHOR_LOOKBACK_COMMITS),
         f"{cursor}..{sha}", "--", path],
        cwd = str(repo_root), capture_output = True, text = True, check = False, encoding = "utf-8",
    )
    if ranged.returncode == 0:
      return any(_BOT_MARK not in email for email in ranged.stdout.splitlines())

  # no usable cursor: a fixed-size window of the path's own recent authors, ending at the
  # item's reported tip.
  # limit: blind past `_AUTHOR_LOOKBACK_COMMITS` bot commits per pull, the cursor scan above is the upgrade
  out = subprocess.run(
      ["git", "log", "--format=%ae", "-n", str(_AUTHOR_LOOKBACK_COMMITS), sha, "--", path],
      cwd = str(repo_root), capture_output = True, text = True, check = False, encoding = "utf-8",
  ).stdout
  for email in out.splitlines():
    if _BOT_MARK not in email:
      return True

    # this worker's own historic wake commit proves everything older was already
    # dispatched on — the worker no longer writes such commits, but pre-cursor installs still
    # carry them, and they keep bounding the window until a cursor is stamped
    if email == _DISPATCH_AUTHOR_EMAIL:
      return False
  return False


def cursor_store_path(repo_root: Path) -> Path:
  """
  Return the path of this worker's dispatch-cursor store.

  Args:
    repo_root: Repository root holding the gitignored `.runtime/` directory.

  Returns:
    Absolute path of `<repo>/.runtime/lazy-specs.dispatch-cursors.json`, whether or not it
    exists.
  """
  return spec_job_markers.sidecar_path(repo_root).parent / _CURSOR_SIDECAR


def _is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
  """
  Check whether one commit is reachable from another.

  Args:
    repo_root: The repository root to run `git` in.
    ancestor: The commit that must be reachable.
    descendant: The commit reachability is checked from.

  Returns:
    True when `ancestor` is `descendant` itself or one of its ancestors; False otherwise,
    including when either hash is unknown to the repository.
  """
  return subprocess.run(
      [ "git", "merge-base", "--is-ancestor", ancestor, descendant ],
      cwd = str(repo_root), capture_output = True, text = True, check = False, encoding = "utf-8",
  ).returncode == 0


def _read_dispatch_cursor(repo_root: Path, asset_note: Path) -> str | None:
  """
  Read the note's dispatch cursor — the last item sha this worker dispatched on.

  Args:
    repo_root: Repository root holding the cursor store.
    asset_note: The asset status folder-note the cursor belongs to.

  Returns:
    The recorded sha, or None when the store is absent, unreadable, or holds nothing usable for
    this note — a corrupt store is runtime scratch and re-derives itself, so it never fails a
    tick.
  """
  # only a non-empty string is a usable sha bound; an absent or mangled store records nothing
  value = _read_cursor_store(repo_root).get(spec_job_markers.note_key(repo_root, asset_note))
  return value if isinstance(value, str) and value else None


def _stamp_dispatch_cursor(repo_root: Path, asset_note: Path, sha: object) -> None:
  """
  Record the item sha this tick dispatched on, so later lookbacks scan only past it.

  Args:
    repo_root: Repository root holding the cursor store.
    asset_note: The asset status folder-note the cursor belongs to.
    sha: The handled item's commit sha; a falsy or non-string value (a synthetic
      wake carries no commit) records nothing.
  """
  # guard: a synthetic wake has no commit to bound a later lookback with
  if not isinstance(sha, str) or not sha:
    return

  # an absent or mangled store starts empty — it is runtime scratch and re-derives itself
  data = _read_cursor_store(repo_root)
  data[spec_job_markers.note_key(repo_root, asset_note)] = sha
  _write_cursor_store(repo_root, data)


def prune_dispatch_cursors(repo_root: Path, drop: Callable[[str], bool], *, dry_run: bool = False) -> list[str]:
  """
  Remove every dispatch cursor whose note key the predicate selects.

  Args:
    repo_root: Repository root holding the cursor store.
    drop: Called with each stored note key; True removes that cursor.
    dry_run: When True, report the selected keys and write nothing.

  Returns:
    The selected note keys, sorted; empty when the store is absent, unreadable, or holds no match.

  Raises:
    OSError: The rewritten store could not be written.
  """
  data = _read_cursor_store(repo_root)
  dropped = sorted(key for key in data if drop(key))

  # guard: a dry run or a store with nothing to drop leaves the file exactly as it is
  if dry_run or not dropped:
    return dropped

  # the surviving cursors replace the store through the same atomic write the stamp uses
  _write_cursor_store(repo_root, { key: value for key, value in data.items() if key not in dropped })
  return dropped


def _read_cursor_store(repo_root: Path) -> dict:
  """
  Read the whole dispatch-cursor store.

  Args:
    repo_root: Repository root holding the cursor store.

  Returns:
    The stored mapping, or an empty one when the store is absent, unreadable, or not a JSON object — the store is
    runtime scratch and re-derives itself, so it never fails a tick.
  """
  # an absent or unreadable store is the "nothing recorded yet" answer, never a failure
  try:
    data = json.loads(cursor_store_path(repo_root).read_text(encoding = "utf-8"))
  except (OSError, json.JSONDecodeError):
    return {}
  return data if isinstance(data, dict) else {}


def _write_cursor_store(repo_root: Path, data: Mapping[str, object]) -> None:
  """
  Replace the dispatch-cursor store atomically.

  Args:
    repo_root: Repository root holding the cursor store.
    data: The whole store to serialise.

  Raises:
    OSError: The store directory could not be created or the store could not be written.
  """
  path = cursor_store_path(repo_root)
  path.parent.mkdir(parents = True, exist_ok = True)

  # write beside the target and rename over it, so a reader never observes a half-written store
  tmp = path.with_suffix(path.suffix + _CURSOR_TMP_SUFFIX)
  tmp.write_text(json.dumps(data, indent = 2, sort_keys = True) + "\n", encoding = "utf-8")
  os.replace(tmp, path)


def _read_marker_dict(frontmatter: dict, key: str) -> dict:
  """
  Parse a worker-internal key→value JSON-dict marker off the asset note's frontmatter.

  A missing or malformed marker reads as "nothing recorded yet" rather than raising, since these
  keys are never operator- or persona-authored (`SpecCoordinatorDocStateKey` and
  `SpecCoordinatorReadyStateKey`, keyed by sibling-doc basename and gate name respectively).

  Args:
    frontmatter: The asset status folder-note's parsed frontmatter.
    key: The frontmatter key to read.

  Returns:
    The parsed dict, or `{}` when the key is absent, not valid JSON, or not a JSON object.
  """
  # guard: no marker recorded yet
  if not (raw := frontmatter.get(key)):
    return {}
  try:
    parsed = json.loads(raw)
  except json.JSONDecodeError:
    return {}
  return parsed if isinstance(parsed, dict) else {}


def _read_doc_state(frontmatter: dict) -> dict:
  """
  Parse the asset note's `spec_coordinator_doc_state` marker into a basename→value dict.

  Args:
    frontmatter: The asset status folder-note's parsed frontmatter.

  Returns:
    The parsed dict, or `{}` when the key is absent, not valid JSON, or not a JSON object.
  """
  return _read_marker_dict(frontmatter, SpecCoordinatorDocStateKey.STATE)


def _resolve_doc_transition(sibling_doc: Path, frontmatter: dict, *,
                            raised_lags: Mapping[str, str] | None = None) -> tuple[str, str] | None:
  """
  Detect a `review_result` transition on one sibling doc against the asset note's own marker.

  A `review_result` equal to the recorded marker still counts as a transition while the document's stage
  lags its accepted result and that lag is not yet on the asset's stage-lag record; once the lag is on the
  record, the same verdict is a noop again.

  The sibling's commit author never enters this check (`CoordinatorTrigger.DOC_TRANSITION`'s
  own docstring) — a commit that never touches `review_result` (an operator's prose edit, a
  writer's draft, any other non-review bot commit) leaves `current == previous` and is a noop
  by construction, with no author check needed to exclude it.

  A document parked at `spec_stage: deferred` never transitions here: its verdict is recorded on
  the file and read by nobody until `lazy-spec.set-stage <doc> draft` brings it back. The commit
  that carried the verdict still reaches the owning note as an ordinary operator edit — this
  guard silences the DOC_TRANSITION arm alone, never the wake itself.

  Args:
    sibling_doc: The sibling doc's own path (the git-watch item's `path`, resolved to a file).
    frontmatter: The owning asset's status folder-note frontmatter, carrying the previously-recorded
      marker (`spec_keys.SpecCoordinatorDocStateKey.STATE`), if any.
    raised_lags: The asset's stage-lag record, from `spec_job_markers.read_stage_lag`; None reads as an
      empty record.

  Returns:
    `(basename, new_value)` when the sibling's current `review_result` differs from the recorded
    marker — including `(basename, "")` when a recorded result was cleared — or equals it while
    the sibling's stage lags the accepted result and that lag is not on the record; `None` when the
    sibling is parked, has never carried a result, or matches the marker with its stage in step or
    its lag already on the record.
  """
  basename = sibling_doc.name
  sibling_fm, _ = flip_gate.parse_frontmatter(sibling_doc.read_text(encoding = "utf-8"))

  # guard: a parked document's verdict transitions nothing until it returns to `draft`
  if str(sibling_fm.get(StageKey.STAGE, "")).strip() == Stage.DEFERRED:
    return None
  current = sibling_fm.get(SpecKey.REVIEW_RESULT)
  previous = _read_doc_state(frontmatter).get(basename)

  # guard: no result now and none ever recorded — nothing has transitioned in either direction
  if current is None and not previous:
    return None

  # a cleared result is the document re-entering review: recorded as the empty token, so the
  # next terminal value — even the same one as before — differs from the marker and re-fires
  if current is None:
    return basename, SpecCoordinatorDocStateKey.REVIEW_REOPENED

  # guard: identical to what this worker already dispatched on — a re-tick, not a transition, unless the
  # approval it dispatched on never reached the document's stage and that lag has not woken anyone yet
  if current == previous and not gate_tick.is_stage_lag_unraised(sibling_doc, raised_lags or {}):
    return None
  return basename, current


def _is_member_signal_eligible(member: Path) -> bool:
  """
  Check whether one changed sibling counts as an operator-edit signal.

  A sibling under active review (`review_active: true`) is the review loop's own business — an
  operator's edit there must not wake the spec coordinator until the review ends, the moment
  `CoordinatorTrigger.DOC_TRANSITION` already covers (operator decision 2026-08-15). A member
  missing on disk is a deletion — an operator-edit signal no review owns, left to the author check.

  Args:
    member: One changed sibling-doc path.

  Returns:
    True when `member` is missing on disk, or is a file whose frontmatter does NOT carry
    `review_active: true`; False when the member is under active review.
  """
  # guard: a deleted member is an edit no review owns — eligible, the author check still decides
  if not member.is_file():
    return True
  frontmatter, _ = flip_gate.parse_frontmatter(member.read_text(encoding = "utf-8"))
  return not flip_gate.is_true(frontmatter, SpecKey.REVIEW_ACTIVE)


def _has_group_note_changed(item: dict, asset_note: Path, repo_root: Path) -> bool:
  """
  Check whether a grouped item's own `paths` names the status folder-note itself, distinct from
  its sibling members.

  A note edit is always an eligible operator-edit signal regardless of any sibling's
  `review_active` state (`_is_member_signal_eligible`'s own docstring) — this is how the OPERATOR_
  EDIT arm tells "only siblings changed" (where the review_active carve-out applies) apart from
  "the note itself changed" (where it never does).

  Args:
    item: The grouped git-watch item (`paths` names every changed member, including the note
      when it changed).
    asset_note: The asset's own status folder-note path.
    repo_root: The repository root `item["paths"]` entries resolve against.

  Returns:
    True when one of `item["paths"]` resolves to `asset_note`.
  """
  resolved_note = asset_note.resolve()
  for raw in item.get(_ITEM_PATHS, []):
    # guard: a non-string entry (a malformed wire item) can't name a path
    if not isinstance(raw, str):
      continue
    if (repo_root / raw).resolve() == resolved_note:
      return True
  return False


def resolve_wake_trigger(
    repo_root: Path, frontmatter: dict, body: str, item: dict, markers: dict, cursor: str | None,
) -> str | None:
  """
  Resolve the wake trigger for this tick, honoring the halt override.

  Args:
    repo_root: The repository root to run `git` in.
    frontmatter: The folder-note's parsed frontmatter.
    body: The folder-note section text (after frontmatter).
    item: The git-watch `changed_files` item for this note (`path`, `status`, `sha`,
      `author_name`, `author_email`).
    markers: The note's runtime marker entry, from `spec_job_markers.read`.
    cursor: The note's dispatch cursor, from `_read_dispatch_cursor` — bounds the
      operator-author lookback.

  Returns:
    A `CoordinatorTrigger` token, or None when nothing wakes the coordinator this tick.
  """

  # Domain(spec.lifecycle):
  # # Wake-trigger priority order
  # A coordinator wake evaluates several possible reasons to act, in a fixed order, and only the
  # first one that applies is acted on this wake: an explicit operator command, then — unless
  # the asset is paused — a fresh answer to a question the coordinator itself asked, then a
  # background job finishing, then a linked document's review outcome changing, then any other
  # operator edit. Pausing an asset silences every one of these except the explicit command,
  # which still gets through, so an operator can always reach a paused asset directly even
  # though the automation around it has gone quiet. An edit to a linked document that is itself
  # under active review belongs to that review's own loop rather than to this precedence, so it
  # is never treated as an operator edit until the review concludes.

  # a non-empty commands section wakes the coordinator even on a halted asset — the one
  # exception to the halt override below (playbook § 1, § 5 "Commands run on halted assets too")
  if read_section_body(body, Section.COORD_COMMANDS):
    return CoordinatorTrigger.COMMAND

  # guard: halt silences every other trigger
  if flip_gate.is_true(frontmatter, SpecHaltKey.HALTED):
    return None

  # a ticked question re-fires only when its content differs from the fingerprint stamped the
  # last time this worker dispatched on it (I1/I-D: retires the trigger so a destroyed removal
  # commit — the coordinator's own — can't resurrect an infinite re-dispatch loop)
  if (ticked_block := _find_ticked_question_block(body)) is not None:
    if frontmatter.get(AnsweredQuestionKey.FINGERPRINT) != _compute_answer_fingerprint(ticked_block):
      return CoordinatorTrigger.ANSWER

  # a launch-checkbox job finishing wakes the coordinator whoever authored the commit that
  # carried it — the exemption is per-transition, not per-author (C3). `gate_tick` raised this
  # flag when it retired the job, so the sidecar rather than any commit's identity is what makes
  # the transition visible here; a wake this tick preempts keeps its flag for a later one.
  if markers.get(JobMarker.PENDING_WAKE) == JobMarker.JOB_DONE:
    return CoordinatorTrigger.JOB_DONE

  # a non-`@bot.` author on the item IS trigger 1 — the operator's edit only exists here once it
  # has been committed, pushed, and pulled into this checkout, so there is no dirty-tree signal
  # for this worker to read (unlike a single-checkout deployment)
  # neither the item's own author nor a recent bot-buried one was the operator
  if not _has_operator_authored_recently(repo_root, item, cursor):
    return None
  return CoordinatorTrigger.OPERATOR_EDIT


def _resolve_group_trigger(
    repo_root: Path, frontmatter: dict, body: str, item: dict, markers: dict, members: list[Path],
    asset_note: Path, cursor: str | None, *, raised_lags: Mapping[str, str],
) -> tuple[str | None, dict[str, str]]:
  """
  Resolve the wake trigger for a grouped git-watch item, honoring the halt override.

  Mirrors `resolve_wake_trigger`'s priority ladder (COMMAND, halt, ANSWER, JOB_DONE,
  OPERATOR_EDIT), replacing its single-sibling `sibling_doc` reasoning with one pass over every
  member path: every member resolving to a genuine `review_result` transition is collected
  (basename -> new value) rather than stopping at the first, so DOC_TRANSITION fires with the
  full set a caller can stamp in one go — no transition is dropped to a later tick just because
  another member's transition also fired this same tick.

  Args:
    repo_root: The repository root to run `git` in.
    frontmatter: The asset status folder-note's parsed frontmatter.
    body: The folder-note section text (after frontmatter).
    item: The grouped git-watch item (`dir`, `paths`, `sha`, `author_name`, `author_email`).
    markers: The note's runtime marker entry, from `spec_job_markers.read`.
    members: The group's sibling-doc member paths, excluding the status note itself.
    asset_note: The asset's own status folder-note path — used only to tell whether the note
      itself is one of `item["paths"]`'s changed members (`_has_group_note_changed`), for the
      OPERATOR_EDIT arm's review-active carve-out below.
    cursor: The note's dispatch cursor, from `_read_dispatch_cursor` — bounds the
      operator-author lookback.
    raised_lags: The note's stage-lag record, from `spec_job_markers.read_stage_lag`.

  Returns:
    A `(trigger, transitions)` pair. `trigger` is a `CoordinatorTrigger` token, or None when
    nothing wakes the coordinator this tick. `transitions` maps every sibling basename that
    transitioned to its new `review_result` value; non-empty only when `trigger` is
    `CoordinatorTrigger.DOC_TRANSITION`.
  """
  # a non-empty commands section wakes the coordinator even on a halted asset — the same
  # exception `resolve_wake_trigger` grants the single-file form
  if read_section_body(body, Section.COORD_COMMANDS):
    return CoordinatorTrigger.COMMAND, {}

  # guard: halt silences every other trigger
  if flip_gate.is_true(frontmatter, SpecHaltKey.HALTED):
    return None, {}

  # a ticked question re-fires only when its content differs from the fingerprint stamped the
  # last time this worker dispatched on it
  if (ticked_block := _find_ticked_question_block(body)) is not None:
    if frontmatter.get(AnsweredQuestionKey.FINGERPRINT) != _compute_answer_fingerprint(ticked_block):
      return CoordinatorTrigger.ANSWER, {}

  # a launch-checkbox job finishing wakes the coordinator whoever authored this tick's commit
  if markers.get(JobMarker.PENDING_WAKE) == JobMarker.JOB_DONE:
    return CoordinatorTrigger.JOB_DONE, {}

  # one pass over every member — every transition found is kept, not just the first
  transitions: dict[str, str] = {}
  for member in members:
    # guard: a member gone between scan and dispatch, or carrying no document type, is skipped
    # silently rather than failing the whole group resolution
    if not spec_doc_types.is_ladder_document(member):
      continue
    resolved = _resolve_doc_transition(member, frontmatter, raised_lags = raised_lags)
    if resolved is not None:
      basename, value = resolved
      transitions[basename] = value
  if transitions:
    return CoordinatorTrigger.DOC_TRANSITION, transitions

  # a review-active sibling's own edit is the review loop's business, not an operator-edit
  # signal (operator 2026-08-15) — the note itself changing is always an eligible signal, but a
  # siblings-only tick needs at least one member NOT under active review before the group's own
  # author even matters; skipping this cheaply avoids the git lookback below when nothing in the
  # group could ever count
  # nothing in this grouped tick could ever count as an operator-edit signal
  if not _has_group_note_changed(item, asset_note, repo_root) and not any(
      _is_member_signal_eligible(member) for member in members
  ):
    return None, {}

  # a non-`@bot.` author on the group's own last commit IS trigger 1, read off the group
  # directory's path rather than a single file's (`_has_operator_authored_recently` only ever
  # reads `_ITEM_PATH`/`_ITEM_SHA`/`_ITEM_AUTHOR_EMAIL`, so the group's `dir` is remapped onto
  # `_ITEM_PATH` for this call)
  dir_item = {
      _ITEM_AUTHOR_EMAIL: item.get(_ITEM_AUTHOR_EMAIL, ""),
      _ITEM_SHA: item.get(_ITEM_SHA),
      _ITEM_PATH: item.get(_ITEM_DIR),
  }

  # neither the item's own author nor a recent bot-buried one on the group's dir was the
  # operator
  if not _has_operator_authored_recently(repo_root, dir_item, cursor):
    return None, {}
  return CoordinatorTrigger.OPERATOR_EDIT, {}


def _level_doc_transitions(frontmatter: dict, members: list[Path], *,
                           raised_lags: Mapping[str, str]) -> dict[str, str]:
  """
  Collect every `review_result` transition the named level documents carry.

  Every named document is checked, so no transition that landed in the same commit is dropped to
  a later tick.

  Args:
    frontmatter: The level note's parsed frontmatter, holding the recorded document state each
      candidate value is compared against.
    members: The level documents this tick names.
    raised_lags: The level note's stage-lag record, from `spec_job_markers.read_stage_lag`.

  Returns:
    Every transitioned document's basename mapped to its new `review_result` value; empty when
    none of the named documents moved.
  """
  transitions: dict[str, str] = {}
  for member in members:
    # guard: a document gone between scan and dispatch, or not part of the level ladder, carries
    # no transition to read
    if not member.is_file() or member.name not in LevelDoc.BASENAMES:
      continue
    resolved = _resolve_doc_transition(member, frontmatter, raised_lags = raised_lags)
    if resolved is not None:
      basename, value = resolved
      transitions[basename] = value
  return transitions


def _resolve_level_trigger(
    repo_root: Path, frontmatter: dict, body: str, item: dict, members: list[Path], cursor: str | None, *,
    raised_lags: Mapping[str, str],
) -> tuple[str | None, dict[str, str]]:
  """
  Resolve the wake trigger for a level note, honoring the halt override.

  The level ladder runs the same priority order the asset ladder does (COMMAND, halt, ANSWER,
  transition, OPERATOR_EDIT), minus `JobMarker.PENDING_WAKE`: no level launch checkbox ever
  queues an expert job, so `CoordinatorTrigger.JOB_DONE` has nothing to fire on. Every level
  document named in `members` is scanned for a `review_result` transition in one pass, so none
  is dropped to a later tick just because another transitioned in the same commit.

  Args:
    repo_root: The repository root to run `git` in.
    frontmatter: The level note's parsed frontmatter.
    body: The level note's section text (after frontmatter).
    item: The git-watch item for this tick.
    members: The level documents this tick names — the one changed document, every existing one
      when a declined wake is being redeemed, or empty when the tick named the note itself.
    cursor: The note's dispatch cursor, bounding the operator-author lookback.
    raised_lags: The level note's stage-lag record, from `spec_job_markers.read_stage_lag`.

  Returns:
    A `(trigger, transitions)` pair. `trigger` is a `CoordinatorTrigger` token, or None when
    nothing wakes the coordinator this tick. `transitions` maps every level-document basename
    that transitioned to its new `review_result` value; non-empty only when `trigger` is
    `CoordinatorTrigger.DOC_TRANSITION`.
  """
  # a non-empty commands section wakes the coordinator even on a halted level, the same
  # exception both asset-side resolvers grant
  if read_section_body(body, Section.COORD_COMMANDS):
    return CoordinatorTrigger.COMMAND, {}

  # guard: halt silences every other trigger
  if flip_gate.is_true(frontmatter, SpecHaltKey.HALTED):
    return None, {}

  # a ticked question re-fires only when its content differs from the stamped fingerprint
  if (ticked_block := _find_ticked_question_block(body)) is not None:
    if frontmatter.get(AnsweredQuestionKey.FINGERPRINT) != _compute_answer_fingerprint(ticked_block):
      return CoordinatorTrigger.ANSWER, {}

  # one pass over every named level document — every transition found is kept, not just the first
  transitions = _level_doc_transitions(frontmatter, members, raised_lags = raised_lags)
  if transitions:
    return CoordinatorTrigger.DOC_TRANSITION, transitions

  # a document-only tick whose every document is under active review is the review loop's
  # business, not an operator-edit signal — the note's own tick (no members) always checks
  if members and not any(_is_member_signal_eligible(member) for member in members):
    return None, {}

  # neither the item's own author nor a recent bot-buried one was the operator
  if not _has_operator_authored_recently(repo_root, item, cursor):
    return None, {}
  return CoordinatorTrigger.OPERATOR_EDIT, {}


def _resolve_product_note_path(repo_root: Path, product_record: dict) -> Path | None:
  """
  Resolve a product record's own folder-note path (Obsidian folder-note convention).

  This is the product's level note as well as the note an asset wake reads as context: the
  folder's own name, never the product's compound-key, is what names it, so a product whose key
  differs from its directory still owns exactly one note.

  Args:
    repo_root: The repository root the product's `spec_path` is relative to.
    product_record: The owning product's settings record.

  Returns:
    The `<spec-content-root>/<spec_path>/<basename>.md` path, or None when the record carries
    no usable `spec_path`.
  """
  spec_path = product_record.get(_SPEC_PATH_KEY)

  # guard: no usable spec_path on this record
  if not isinstance(spec_path, str) or not spec_path:
    return None
  product_dir = spec_paths.spec_content_root(repo_root) / spec_path
  return product_dir / f"{product_dir.name}.md"


def _ancestor_note_paths(repo_root: Path, key: str | None) -> list[str]:
  """
  List the level notes of every product enclosing `key`'s, outermost first.

  Args:
    repo_root: The repository root the product records resolve under.
    key: The owning product's compound-key, or None when no product owns the path.

  Returns:
    Repo-relative paths of the ancestor notes that exist on disk; a registered ancestor whose
    note was never created contributes nothing and no warning.
  """
  # guard: no owning product at all — no ancestor chain to walk
  if key is None:
    return []
  paths: list[str] = []
  for ancestor_key in resolve_product.ancestor_chain(repo_root, key):
    ancestor_record = resolve_product.resolve_product_by_key(repo_root, ancestor_key) or {}
    ancestor_note = _resolve_product_note_path(repo_root, ancestor_record)
    if ancestor_note is not None and ancestor_note.is_file():
      paths.append(_to_rel_path(repo_root, ancestor_note))
  return paths


def _catalog_note_path(repo_root: Path) -> Path:
  """
  Resolve the catalog root's own level note.

  Args:
    repo_root: The repository root the spec content root is resolved under.

  Returns:
    The `<content-root>/<content-root-name>.md` path, whether or not it exists.
  """
  content_root = spec_paths.spec_content_root(repo_root)
  return content_root / f"{content_root.name}.md"


def _members_by_owner(group_dir: Path, raw_paths: list) -> list[tuple[Path, Path | None]]:
  """
  Resolve a grouped item's member paths and pair each with the status folder-note owning it.

  A group glob knows only a depth, never an asset boundary, so ownership is decided by the climb
  from a member's own folder up to `group_dir` (inclusive): the nearest folder whose folder-note
  carries the asset status role owns it, and a member with no such folder over it is nobody's.

  Args:
    group_dir: The group's matched directory, resolved.
    raw_paths: The item's member paths, relative to the current directory (the repo root).

  Returns:
    `(member, owner)` pairs in first-seen order, `owner` None for an unowned member; a non-string
    entry (a malformed wire item) names no path and is dropped.
  """
  pairs: list[tuple[Path, Path | None]] = []
  for raw in raw_paths:
    # guard: a non-string entry (a malformed wire item) can't name a path
    if not isinstance(raw, str):
      continue
    member = (Path.cwd() / raw).resolve()
    pairs.append(( member, _owner_status_note(member.parent, group_dir) ))
  return pairs


def _split_group_by_owner(group_dir: Path, raw_paths: list) -> dict[Path, list[Path]]:
  """
  Split a grouped git-watch item's member paths by the asset that owns each of them.

  A group glob knows only a depth, never an asset boundary, so a nested asset's own files land
  in its enclosing asset's group, and under a nested product the group dir may be no asset at
  all. Each member therefore climbs from its own folder up to `group_dir` (inclusive) to the
  nearest folder whose folder-note carries `spec_role: status`; that note owns it.

  Args:
    group_dir: The group's matched directory, resolved.
    raw_paths: The item's member paths, relative to the current directory (the repo root).

  Returns:
    A map of owning status folder-note to its member paths (the note itself included when it
    changed), in first-seen order; a member with no status note over it is dropped.
  """
  owners: dict[Path, list[Path]] = {}
  for member, owner in _members_by_owner(group_dir, raw_paths):
    # guard: no status folder-note between this member and the group dir — nobody's object
    if owner is None:
      continue
    owners.setdefault(owner, []).append(member)
  return owners


def _orphan_members(group_dir: Path, raw_paths: list) -> list[Path]:
  """
  List a grouped item's members that no status folder-note owns.

  A member with no status note between its own folder and `group_dir` is not an asset's file:
  it is a level document of a nested product whose folder the parent's shallow glob grouped,
  a bare group folder's own note, or a file of an asset folder deleted whole (its status note
  deleted with it, so none is left above the file). Each such member is handled as the
  single-file item it would have been ungrouped; a deleted file then wakes the owning
  product's level note.

  Args:
    group_dir: The group's matched directory, resolved.
    raw_paths: The item's member paths, relative to the current directory (the repo root).

  Returns:
    The orphan members, resolved, in first-seen order.
  """
  return [ member for member, owner in _members_by_owner(group_dir, raw_paths) if owner is None ]


def _owner_status_note(start: Path, top: Path) -> Path | None:
  """
  Find the nearest status folder-note from `start` up to `top`, both inclusive.

  Args:
    start: The folder to begin at, resolved.
    top: The highest folder to look in, resolved.

  Returns:
    The first `<dir>/<dir.name>.md` carrying `spec_role: status` on the way up, or None when
    none does or `start` does not sit under `top`.
  """
  # guard: a member outside the group dir has no owner among the group's folders
  if start != top and top not in start.parents:
    return None
  for candidate in (start, *start.parents):
    note = candidate / f"{candidate.name}.md"
    if note.is_file():
      frontmatter, _ = flip_gate.parse_frontmatter(note.read_text(encoding = "utf-8"))
      if frontmatter.get(SpecKey.ROLE) == _SPEC_ROLE_STATUS:
        return note

    # the group dir was the last folder to look in
    if candidate == top:
      return None
  return None


def _resolve_owner_note(repo_root: Path, changed: Path) -> Path:
  """
  Resolve the folder-note that owns one changed document, by where the document lies.

  Three placements answer to three owners: a file directly in the spec content root belongs to
  the catalog root's level note, a file directly in a registered product's `spec_path` belongs
  to that product's level note, and everything else follows the Obsidian folder-note convention
  of its own directory.

  Args:
    repo_root: The repository root the content root and the product records resolve under.
    changed: The changed document's own path.

  Returns:
    The owning folder-note's path, whether or not it exists.
  """
  changed_dir = changed.parent.resolve()

  # a system document lying beside the catalog root's note belongs to that note
  if changed_dir == spec_paths.spec_content_root(repo_root).resolve():
    return _catalog_note_path(repo_root)

  # a system document lying directly in a product's spec path belongs to that product's note —
  # a document deeper down (an asset's own sibling) resolves past this arm to the convention below
  key, record = resolve_product.resolve_product_by_path(repo_root, _to_rel_path(repo_root, changed))
  if key is not None and isinstance(record, dict):
    level_note = _resolve_product_note_path(repo_root, record)
    if level_note is not None and level_note.parent.resolve() == changed_dir:
      return level_note

  # every other document is owned by its own folder's note
  return changed_dir / f"{changed_dir.name}.md"


def _has_snapshot_changed(cur_ready: dict, prev_ready: dict) -> bool:
  """
  Tell whether the observed gate snapshot differs from what the ready-state marker already records.

  Args:
    cur_ready: The gate values observed this tick.
    prev_ready: The marker's recorded values; a key the marker never carried reads as false.

  Returns:
    True when at least one observed value differs from the recorded one.
  """
  return any(value != prev_ready.get(key, False) for key, value in cur_ready.items())


def _is_marker_legacy(prev_ready: dict) -> bool:
  """
  Tell whether the recorded ready-state marker's keys differ from the two approval keys.

  A marker that was never recorded is not legacy. Callers stamp a legacy marker to the current two-key snapshot on
  that wake and read its missing approval keys as matching the observed values.

  Args:
    prev_ready: The marker's recorded values; empty when no marker was recorded.

  Returns:
    True when a marker was recorded and its keys are not exactly `spec_design_done` and `spec_cancelled`: either
    one of them is missing or a retired key such as `spec_develop_done` or `spec_tests_passing` is still carried.
  """
  return bool(prev_ready) and set(prev_ready) != set(_APPROVAL_EDGES)


def wake_release_owner_on_approval(repo_root: Path, asset_dir: Path, *, today: str | None) -> None:
  """
  Wake the release owner of an asset whose approval, or cancellation, just crossed.

  The owner is the outermost product in the asset's chain with a `source` of its own. An asset in a chain with no
  owner, or an owner whose level note was never created, wakes nothing.

  Notes:
    - The caller invokes this only after its own dispatch has already landed, never before.
    - A failed dispatch does not propagate; it is reported as a warning to the core error ledger, one incident per
      level note, and a later successful dispatch on the same level note closes that incident.

  Args:
    repo_root: The repository root the product records resolve under.
    asset_dir: The asset folder whose start document's approval, or whose cancellation, just crossed.
    today: Optional ISO date forwarded into the level note's own `# History` line.

  Raises:
    Exception: Any error the owner lookup raises; it runs outside the best-effort dispatch.
  """
  _wake_release_owner(repo_root, asset_dir, trigger = CoordinatorTrigger.ASSET_APPROVED,
                      dispatch = _dispatch_asset_approved, today = today)


def wake_release_owner_on_publish(repo_root: Path, release_dir: Path, *, today: str | None) -> None:
  """
  Wake the release owner of a release that was just published.

  The owner is the outermost product in the release's chain with a `source` of its own. A release in a chain with
  no owner, or an owner whose level note was never created, wakes nothing.

  Notes:
    - The caller invokes this only after the publish commit has landed, never before.
    - A failed dispatch does not propagate; it is reported as a warning to the core error ledger, one incident per
      level note, and a later successful dispatch on the same level note closes that incident.

  Args:
    repo_root: The repository root the product records resolve under.
    release_dir: The folder of the release that was just published; it only locates the owner.
    today: Optional ISO date forwarded into the level note's own `# History` line.

  Raises:
    Exception: Any error the owner lookup raises; it runs outside the best-effort dispatch.
  """
  _wake_release_owner(repo_root, release_dir, trigger = CoordinatorTrigger.RELEASE_PUBLISHED,
                      dispatch = _dispatch_release_published, today = today)


def _dispatch_asset_approved(level_note: Path, asset_dir: Path, today: str | None) -> None:
  """
  Dispatch the `ASSET_APPROVED` job on the level note, naming the asset folder relative to the owner's root.

  Args:
    level_note: The release owner's level note.
    asset_dir: The asset folder whose approval, or whose cancellation, just crossed.
    today: Optional ISO date forwarded into the level note's own `# History` line.
  """
  coordinator_dispatch(level_note, {}, today = today,
                       asset_approved = asset_dir.resolve().relative_to(level_note.resolve().parent).as_posix())


def _dispatch_release_published(level_note: Path, _release_dir: Path, today: str | None) -> None:
  """
  Dispatch the `RELEASE_PUBLISHED` job; a published release names no asset.

  Args:
    level_note: The release owner's level note.
    _release_dir: The published release's folder; unused, the job carries no token.
    today: Optional ISO date forwarded into the level note's own `# History` line.
  """
  coordinator_dispatch(level_note, {}, today = today, release_published = True)


def _wake_release_owner(repo_root: Path,
                        target_dir: Path,
                        *,
                        trigger: str,
                        dispatch: Callable[[Path, Path, str | None], None],
                        today: str | None) -> None:
  """
  Resolve the release owner of a folder and run the given dispatch on its level note.

  The owner is the outermost product in the folder's chain with a `source` of its own. A folder in a chain with no
  owner, or an owner whose level note was never created, wakes nothing.

  Notes:
    - The caller invokes this only after the change itself has landed: an approval after the asset's own
      dispatch, a publish after the publish commit.
    - Only the dispatch itself is best-effort: a failure does not propagate; it is reported as a warning to the core
      error ledger under the `RELEASE_OWNER_WAKE_FAILED` cause, one incident per level note, with the trigger in
      the detail. A dispatch that succeeds closes that incident if it is open.

  Args:
    repo_root: The repository root the product records resolve under.
    target_dir: The asset folder whose start document's approval, or whose cancellation, just crossed; for a
      `RELEASE_PUBLISHED` job, the published release's folder, which only locates the owner.
    trigger: The `CoordinatorTrigger` token the dispatch raises, named in the reported detail.
    dispatch: The dispatch of the job itself, called with the level note, `target_dir` and `today`.
    today: Optional ISO date forwarded into the level note's own `# History` line.

  Raises:
    Exception: Any error the owner lookup raises; it runs outside the best-effort dispatch.
  """

  # Domain(spec.lifecycle):
  # # Upward wake to the release owner
  # The product that owns releases is told, one hop upward, in two cases. An asset's design crossing approval in
  # either direction, or the asset being cancelled or reinstated, changes what the next release would carry. A
  # release being published successfully changes it too, because what shipped no longer waits. The product is
  # told once, so its level view stays current without polling every asset inside it. A release's own note,
  # the owner's unit of shipping, never raises the approval edge itself.
  # The product told is the outermost one in the asset's chain that builds releases. An asset outside any
  # product, under a chain that builds no releases, or under an owner whose level note was never created
  # wakes nobody. The notification travels exactly one hop outward from the change and is never chased further.
  # On an approval change the owner re-hangs its rows and rewrites its brief; the approval of a design never
  # starts a build, the operator's tick does. On a published release, which names no asset, the owner
  # recomputes what the next release would carry, puts up or takes down its start row, and rewrites its brief.
  # A failed production deploy publishes nothing and wakes nobody.
  # The wake fires only after the change itself has safely landed, and it is best-effort: a failure telling the
  # owner never undoes the approval record or the publish. A snapshot recorded before the approval gates were
  # tracked reads as matching, so the upgrade itself raises no wake.

  # the owning product, then the outermost product in its chain that builds releases
  key, _record = resolve_product.resolve_product_by_path(repo_root, _to_rel_path(repo_root, target_dir))
  owner_key = resolve_product.find_release_owner_key(repo_root, key) if key else None

  # guard: an asset outside any registered product, or under a chain that builds no releases, wakes nothing
  if owner_key is None:
    return
  owner_record = resolve_product.resolve_product_by_key(repo_root, owner_key) or {}
  level_note = _resolve_product_note_path(repo_root, owner_record)

  # guard: an owner whose level note was never created has no level coordinator to wake
  if level_note is None or not level_note.is_file():
    return

  # the upward hop itself: a published release names no asset, an approval carries the asset's folder relative to
  # the owner's root; one incident per level note folds every failed wake of that owner
  incident = f"{_WAKE_INCIDENT_PREFIX}{_to_rel_path(repo_root, level_note)}"
  try:
    dispatch(level_note, target_dir, today)
  # waiver: best-effort boundary — the change that raised the wake has landed, so a failed wake is reported, not raised
  except Exception as error:
    error_report.report_marked_warning(repo_root, cause = PluginErrorCause.RELEASE_OWNER_WAKE_FAILED,
                                       incident = incident, detail = f"{trigger}: {error}")
    return

  # a wake that went through proves an earlier failure of the same owner cleared; with no marker, no core call
  error_report.resolve_marked(repo_root, incident)


def _to_rel_path(repo_root: Path, target: Path) -> str:
  """
  Render a manifest entry's repo-relative path.

  Args:
    repo_root: The repository root the entry is named against.
    target: The file or folder the bundle declares.

  Returns:
    The path relative to `repo_root`, or the target's bare name when it lies outside the repo.
  """
  # a target outside the repo has no relative form — its bare name is all the manifest can carry
  try:
    return target.relative_to(repo_root).as_posix()
  except ValueError:
    return target.name


def _coordination_rules_context(repo_root: Path) -> tuple[list[str], list[str]]:
  """
  Resolve the vault-wide coordination-rules doc every coordinated note reads.

  Args:
    repo_root: The repository root the configured path is relative to.

  Returns:
    A `(context, warnings)` pair: `context` holds the doc's repo-relative path when one is
    configured and resolves to a file; `warnings` names a configured path that does not.
  """
  rules_rel = (gate_dispatch.load_settings(repo_root).get(_SPEC_SECTION) or {}).get(_COORD_RULES_KEY)

  # guard: no vault-wide rules doc configured — nothing to name either way
  if not rules_rel:
    return [], []
  rules_path = repo_root / rules_rel

  # a configured path that does not resolve is a warning, never a silent drop
  if rules_path.is_file():
    return [ _to_rel_path(repo_root, rules_path) ], []
  return [], [ f"coordination rules not found: {rules_rel}" ]


def _build_level_bundle(
    repo_root: Path, level_note: Path, role: str, trigger: str, *,
    doc_transition: str | None = None, asset_approved: str | None = None,
) -> tuple[list[str], list[str], list[str], dict, str, list[str]]:
  """
  Assemble the `lazycortex-core dispatch-job` wire bundle pieces for a level-note wakeup.

  Source names the level note itself; context names the level documents, the rules layers the note's role
  needs and, on an asset-approved wake, the asset's folder, all as repo-relative paths. The playbook rides the
  bundle as a protocol reference and guidelines ride in the payload as paths the expert reads in place, never
  as copied files. A declared guideline path that does not resolve is reported among the bundle's warnings.

  Args:
    repo_root: The repository root the CLI resolves settings and its own binary against.
    level_note: The level folder-note path — a product's own or the catalog root's.
    role: The note's `spec_role` value, which selects both the rules layers and the playbook.
    trigger: The `CoordinatorTrigger` token this wakeup resolved to.
    doc_transition: The level-document basename that transitioned, when `trigger` is
      `CoordinatorTrigger.DOC_TRANSITION`; folded into `payload["doc"]`. None otherwise.
    asset_approved: The owner-relative path token of the asset whose approval or cancellation raised this wake,
      when `trigger` is `CoordinatorTrigger.ASSET_APPROVED`; folded into `payload["asset"]`. None otherwise.

  Returns:
    A `(source, context, warnings, payload, dedup_key, protocols)` tuple, where `source` and
    `context` are repo-relative path manifests and `protocols` names the level playbook the
    dispatched job reads on top of the dispatching routine's own. `payload["kind"]` is the note's
    role; `payload["product"]`, `payload["guidelines"]`, `payload["doc"]`, `payload["asset"]` and
    `payload["warnings"]` each appear only when they carry something.
  """
  relative = _to_rel_path(repo_root, level_note)
  source = [ relative ]
  context: list[str] = []
  warnings: list[str] = []

  # the level ladder's own documents, in writing order — only the ones written so far
  level_dir = level_note.parent
  for basename, _doc_type, _gate in LevelDoc.CHAIN:
    doc = level_dir / basename
    if doc.is_file():
      context.append(_to_rel_path(repo_root, doc))

  # the rules layers, chosen by role: a product reads the catalog root above it and its own
  # product guidelines; the catalog root reads every product note below it instead
  product_record: dict = {}
  guideline_paths: list[str] = []
  if role == SpecValue.ROLE_PRODUCT:
    _key, record = resolve_product.effective_record_by_path(repo_root, relative)
    product_record = record or {}
    catalog_note = _catalog_note_path(repo_root)
    if catalog_note.is_file():
      context.append(_to_rel_path(repo_root, catalog_note))

    # the ancestor products' level notes, outermost first — the same layer a nested product's
    # own asset reads before its own note (lazy-spec.coordination-playbook § 3)
    context.extend(_ancestor_note_paths(repo_root, _key))
    guideline_paths, guideline_warnings = gate_dispatch.collect_guideline_paths(
        repo_root, product_record, _COORDINATOR_ROLE,
    )
    warnings.extend(guideline_warnings)
  else:
    for key, record in resolve_product.load_products(repo_root).items():
      # guard: a malformed product record names no note to read
      if not isinstance(record, dict):
        continue

      # guard: a nested product is its parent's child, never the catalog root's
      if resolve_product.ancestor_chain(repo_root, key):
        continue
      product_note = _resolve_product_note_path(repo_root, record)
      if product_note is not None and product_note.is_file():
        context.append(_to_rel_path(repo_root, product_note))

    # the catalog root stands above every product, so only the catalog-wide guidelines reach it
    guideline_paths, guideline_warnings = gate_dispatch.collect_guideline_paths(
        repo_root, { _GUIDELINES_KEY: resolve_product.load_catalog_guidelines(repo_root) },
        _COORDINATOR_ROLE,
    )
    warnings.extend(guideline_warnings)

  # the approved (or cancelled) asset's own folder, named in context, so the owner's coordinator reads the start
  # document that just crossed
  if asset_approved is not None:
    approved_dir = resolve_product.resolve_asset_token(level_note.parent, asset_approved)
    if approved_dir is None:
      warnings.append(f"approved asset not found: {asset_approved}")
    else:
      context.append(_to_rel_path(repo_root, approved_dir))

  # the vault-wide coordination-rules doc, the same layer an asset wake reads
  rules_context, rules_warnings = _coordination_rules_context(repo_root)
  context.extend(rules_context)
  warnings.extend(rules_warnings)

  # the level playbook, resolved off the type registry by role the same way an asset type
  # resolves its own — a reference the agent reads at spawn time, never a file the pump copies
  playbook = asset_types.playbook_ref(role, product_record)
  protocols = [ playbook ] if playbook else []

  # dedup key scoped to this note, the same shape the asset ladder uses — one coordinator job
  # per note, regardless of which trigger woke it
  # waiver: payload wire-key literals, single-source alongside `_build_bundle`'s own — this dict
  # IS the wire schema, not a reusable domain key
  payload: dict[str, object] = { "kind": role, "trigger": trigger }

  # the owning product's record, so the persona reads product config off the wire; the catalog
  # root has no product of its own and omits the field entirely
  if product_record:
    # waiver: payload wire-key literal, same wire-schema dict as the literals above
    payload["product"] = product_record

  # guidelines are named, never copied — the expert reads the real files in the tree
  if guideline_paths:
    payload[gate_dispatch.PayloadKey.GUIDELINES] = guideline_paths

  # doc field is only meaningful for a DOC_TRANSITION wake — every other trigger omits it
  if doc_transition is not None:
    # waiver: payload wire-key literal, same wire-schema dict as the literals above
    payload["doc"] = doc_transition

  # asset field names the approved or cancelled asset on an ASSET_APPROVED wake, the same key
  if asset_approved is not None:
    # waiver: payload wire-key literal, same wire-schema dict as the literals above
    payload["asset"] = asset_approved

  # an unresolved context path is visible to the dispatched job itself, not only to the caller
  if warnings:
    # waiver: payload wire-key literal, same wire-schema dict as the literals above
    payload["warnings"] = warnings

  # the assembled manifests, the payload, and the per-note dedup key the guard is scoped by
  return source, context, warnings, payload, f"{relative}:coordinator", protocols


def _build_bundle(
    repo_root: Path, asset_dir: Path, asset_note: Path, fm_text: str, trigger: str, *,
    doc_transition: str | None = None,
) -> tuple[list[str], list[str], list[str], dict, str]:
  """
  Assemble the `lazycortex-core dispatch-job` wire bundle pieces for a coordinator wakeup.

  Source names the note itself; context names the documents and folders the coordinator needs to read, all as
  repo-relative paths the pump copies when it claims the job. Guidelines and the `decisions.md` registries are
  never copied: they ride in the payload as paths the expert reads in place. A declared path that does not
  resolve to a file becomes a warning string for the caller's `# History` line, never a silent drop; a
  container folder with no folder-note and a missing `decisions.md` are the exceptions and never warn.

  Args:
    repo_root: The repository root the CLI resolves settings and its own binary against.
    asset_dir: The asset folder holding the status folder-note.
    asset_note: The status folder-note path.
    fm_text: The folder-note's frontmatter block text (for list-typed key reads).
    trigger: The `CoordinatorTrigger` token this wakeup resolved to.
    doc_transition: The sibling-doc basename that transitioned, when `trigger` is
      `CoordinatorTrigger.DOC_TRANSITION`; folded into `payload["doc"]` so the coordinator knows
      which sibling to walk first. None for every other trigger.

  Returns:
    A `(source, context, warnings, payload, dedup_key)` tuple, where `source` and `context` are
    repo-relative path manifests. `payload["product"]` always
    carries the asset's owning product's effective record (`{}` when the asset has none) —
    every undeclared inheritable key already resolved from its ancestors, so the coordinator
    persona reads product-level config straight off the wire instead of re-resolving it.
    `payload["guidelines"]` and `payload["decisions"]` name the files the
    expert reads in place, each omitted when nothing resolved.
    `warnings` is also folded into `payload["warnings"]` when non-empty, so an
    unresolved context path (e.g. an unresolvable `spec_targets` token) is visible to the
    dispatched job itself, not only the caller's own `# History` line (I11).
  """
  relative = _to_rel_path(repo_root, asset_note)

  # source is always the note itself, named by the path the pump copies at claim
  source = [ relative ]
  context: list[str] = []
  warnings: list[str] = []

  # the owning product's key and effective record, resolved from the asset's folder path
  _key, product_record = resolve_product.effective_record_by_path(repo_root, _to_rel_path(repo_root, asset_dir))
  product_record = product_record or {}

  # the ancestor products' level notes, outermost first — a nested product's asset reads the
  # rules of every product enclosing it before its own (lazy-spec.coordination-playbook § 3)
  context.extend(_ancestor_note_paths(repo_root, _key))

  # the asset's own product note, appended last of the two so it lands closest to the asset
  product_note = _resolve_product_note_path(repo_root, product_record)
  if product_note is not None and product_note.is_file():
    context.append(_to_rel_path(repo_root, product_note))
  # a resolved product with a still-missing folder-note is a warning; no owning product at all
  # (product_record still `{}`) is not — there is nothing declared to have gone missing
  elif product_record:
    warnings.append(f"product folder-note not found: {product_record.get(_SPEC_PATH_KEY)}")

  # the container chain itself, anchored on the product's own spec-path root
  if isinstance(spec_path := product_record.get(_SPEC_PATH_KEY), str) and spec_path:
    product_dir = spec_paths.spec_content_root(repo_root) / spec_path

    # an asset dispatched from outside its own product's tree has no container chain to walk
    if product_dir in asset_dir.parents:
      containers = [ ancestor for ancestor in asset_dir.parents if product_dir in ancestor.parents ]
      for container in reversed(containers):
        container_note = container / f"{container.name}.md"
        if container_note.is_file():
          context.append(_to_rel_path(repo_root, container_note))

  # every declared spec_targets asset's own folder, named by its repo-relative path — the folder
  # rather than the note alone, so the pump lands it under a path-derived bucket name and two assets
  # in the same product sharing a slug (`auth` at the root and `bugs/auth`) stay apart in the
  # bucket (I10)
  for token in gate_tick.read_fm_list(fm_text, SpecTargetsKey.TARGETS):
    target_dir = gate_tick.target_asset_dir(asset_dir, token)

    # guard: a declared target token that resolves to no existing asset folder is a warning,
    # never a hard failure of the whole context fold-in
    if target_dir is None:
      warnings.append(f"spec_targets not found: {token}")
      continue
    context.append(_to_rel_path(repo_root, target_dir))

  # every declared source-request wikilink, resolved to its file
  for raw in gate_tick.read_fm_list(fm_text, _SPEC_SOURCE_REQUESTS):
    # strip the list-write quoting first, then the `|display` gloss, then the `[[...]]` brackets
    # — each layer wraps the one before it, so unwrapping out of order leaves stray characters
    pure = raw.strip().strip('"').strip("'").split("|")[0].strip("[]")
    req_path = spec_paths.resolve_wikilink(pure, repo_root)
    if req_path.is_file():
      context.append(_to_rel_path(repo_root, req_path))
    else:
      warnings.append(f"source request not found: {pure}")

  # the vault-wide coordination-rules doc (lazy-spec.config-protocol.md), when configured
  rules_context, rules_warnings = _coordination_rules_context(repo_root)
  context.extend(rules_context)
  warnings.extend(rules_warnings)

  # coordinator-role, asset-type and wildcard guidelines, same lookup `gate_dispatch` uses for
  # checkbox jobs — named in the payload rather than staged into the bucket, since the expert
  # reads the real files
  guideline_paths, guideline_warnings = gate_dispatch.collect_guideline_paths(
      repo_root, product_record, _COORDINATOR_ROLE, asset_type = asset_types.type_of(asset_note),
  )
  warnings.extend(guideline_warnings)

  # the asset's and owning product's decisions registries — named beside the guideline lookup
  # rather than folded into it, since they go to every dispatched role uniformly; a missing
  # decisions.md is normal (lazily created) and never a warning, so nothing here extends `warnings`
  decisions_paths = gate_dispatch.collect_decisions_paths(repo_root, asset_dir, product_record)

  # dedup key scoped to this asset + the coordinator's own fixed label — one coordinator job
  # per asset, regardless of which trigger woke it
  # waiver: payload wire-key literal, single-source alongside every other "payload[...]" literal
  # below — this dict IS the wire schema, not a reusable domain key
  payload: dict[str, object] = {
      "kind": "coordinator", "trigger": trigger, "asset": relative, "product": product_record,
  }

  # guidelines and decisions are named, never copied — the expert reads the real files in the tree
  if guideline_paths:
    payload[gate_dispatch.PayloadKey.GUIDELINES] = guideline_paths
  if decisions_paths:
    payload[gate_dispatch.PayloadKey.DECISIONS] = decisions_paths

  # doc field is only meaningful for a DOC_TRANSITION wake — every other trigger omits it
  if doc_transition is not None:
    # waiver: payload wire-key literal, same wire-schema dict as the literals above
    payload["doc"] = doc_transition

  # an unresolved context path (e.g. an unresolvable spec_targets token) was previously
  # visible only in the caller's `# History` line, never to the dispatched job itself — folded
  # into the payload too so the coordinator persona can see what it's missing (I11)
  if warnings:
    # waiver: payload wire-key literal, same wire-schema dict as the "kind"/"trigger"/"asset"/"doc" literals above
    payload["warnings"] = warnings
  return source, context, warnings, payload, f"{relative}:coordinator"


def _commit(asset_dir: Path, asset_note: Path, subject: str) -> None:
  """
  Commit the rewritten status folder-note under this worker's own bot identity.

  Nothing is committed when the asset is not inside a git repository; the operator's staged
  entries never ride into the commit.

  Args:
    asset_dir: The asset folder, locating the enclosing repository.
    asset_note: The status folder-note path that was just rewritten.
    subject: The commit subject line.

  Raises:
    subprocess.CalledProcessError: If the commit fails.
  """
  top = flip_gate.git_field(asset_dir, ["rev-parse", "--show-toplevel"], "")

  # guard: asset is not inside a git repository — skip commit
  if not top:
    return
  repo = Path(top)

  # commit under the dedicated bot identity by explicit pathspec, its icon repaint folded in, so the tree is
  # clean for the next daemon iteration while a populated index (e.g. the operator's recover.py triage,
  # `git stash push -u`) neither rides along nor gets the note's content written into it
  flip_gate.commit_paths(
      repo, [ asset_note ],
      author_name = _DISPATCH_AUTHOR_NAME, author_email = _DISPATCH_AUTHOR_EMAIL, subject = subject,
  )


def _has_group_wake(
    frontmatter: dict, body: str, item: dict, members: list[Path], *, raised_lags: Mapping[str, str],
    note_changed: bool = True, basenames: frozenset[str] | None = None,
) -> bool:
  """
  Check whether a tick the busy-job guard is about to decline actually carries a wake-worthy
  signal — a cheap "is there anything to catch up on" probe, not the full trigger ladder.

  Mirrors the front of `_resolve_group_trigger`'s own ladder (COMMAND, ANSWER, sibling
  transition) plus a bare non-`@bot.` check on `item`'s own author, WITHOUT `_resolve_group_
  trigger`'s halt override or its `JobMarker.PENDING_WAKE` short-circuit — a busy job has no
  wake to preempt yet, and halting an asset must not suppress recording that something happened
  while the job was running (the halt override governs DISPATCH, not bookkeeping). Bot-authored
  noise with none of these signals must never set the busy-guard's sidecar flag, or every git-
  watch tick during a long-running job would stamp `declined` for nothing to actually redeem.

  Args:
    frontmatter: The asset status folder-note's parsed frontmatter.
    body: The folder-note section text (after frontmatter).
    item: The git-watch item for this tick — the single-file, sibling-doc, or grouped shape;
      only `_ITEM_AUTHOR_EMAIL` is read directly here.
    members: The sibling-doc paths to check for a `review_result` transition — `[sibling_doc]`
      on a sibling-item tick, the group's member paths on a grouped tick, or `[]` on the plain
      status-note tick (which has no siblings of its own to scan).
    note_changed: Whether the status note itself is one of this tick's changed paths. True by
      default, preserving the unconditional author check for the plain status-note and sibling-
      item tick shapes; the grouped-tick caller passes the real `_has_group_note_changed` result, so
      a siblings-only group needs at least one member NOT under active review
      (`_is_member_signal_eligible`) before the author check even runs (operator 2026-08-15).
    basenames: The level ladder's closed document set, on a level note; None on an asset, where
      a member is scanned for a transition when it carries a `spec_doc_type`
      (`spec_doc_types.is_ladder_document`).
    raised_lags: The note's stage-lag record, from `spec_job_markers.read_stage_lag`.

  Returns:
    True when a `# Coordinator commands` section is non-empty, a coordinator-attributed ticked
    question differs from its recorded fingerprint, any member's `review_result` differs from
    what this worker last recorded for it or lags its stage with no wake on the stage-lag record, or
    (subject to the `note_changed` carve-out above) the item's own author is non-`@bot.`.
  """
  # an operator command waiting in `# Coordinator commands` is always worth a wake
  if read_section_body(body, Section.COORD_COMMANDS):
    return True

  # a ticked coordinator question counts only when its answer differs from the recorded fingerprint,
  # so an answer the coordinator already consumed never wakes it again
  if (ticked_block := _find_ticked_question_block(body)) is not None:
    if frontmatter.get(AnsweredQuestionKey.FINGERPRINT) != _compute_answer_fingerprint(ticked_block):
      return True

  # a tracked member whose `review_result` moved since this worker last recorded it is a wake
  for member in members:
    if spec_doc_types.is_ladder_document(member, basenames) \
        and _resolve_doc_transition(member, frontmatter, raised_lags = raised_lags) is not None:
      return True

  # a siblings-only tick (note itself unchanged) with every member under active review
  # carries no operator-edit signal to check the author against
  if not note_changed and not any(_is_member_signal_eligible(member) for member in members):
    return False
  return _BOT_MARK not in item.get(_ITEM_AUTHOR_EMAIL, "")


def _strip_legacy_pending(fm_text: str) -> str:
  """
  Remove the retired frontmatter pending-note keys from an old install's note.

  `spec_coordinator_pending_edit` / `spec_coordinator_pending_doc` predate the sidecar-declined
  migration (`JobMarker.PENDING_WAKE`) — a note still carrying either is stale state from a
  worker version that no longer exists, cleaned up opportunistically on the next write rather
  than through a dedicated migration pass.

  Args:
    fm_text: The frontmatter block text (including its opening/closing `---` fences).

  Returns:
    `fm_text` with both legacy keys deleted; a no-op when neither is present.
  """
  fm_text = gate_tick.del_fm_key(fm_text, _LEGACY_PENDING_EDIT_KEY)
  return gate_tick.del_fm_key(fm_text, _LEGACY_PENDING_DOC_KEY)


# waiver: one tick function walks the whole trigger ladder end to end; splitting it would
# scatter one coherent decision across several functions sharing the same mutable snapshot
def coordinator_dispatch(asset_note: Path,  # pylint: disable=too-many-branches
                         item: dict,
                         *,
                         today: str | None = None,
                         sibling_doc: Path | None = None,
                         group_members: list[Path] | None = None,
                         level_doc: Path | None = None,
                         asset_approved: str | None = None,
                         release_start: bool = False,
                         release_published: bool = False) -> dict:
  """
  Detect operator activity on one coordinated folder-note and dispatch its expert when it wakes.

  The note's own `spec_role` picks the persona: an asset's status note dispatches
  `spec.coordinator`, a product's or the catalog root's level note dispatches
  `spec.catalog-coordinator` on the level ladder instead. Everything around the dispatch — the
  one-active-job guard, the dispatch cursor, the marker sidecar, the commit identity — is keyed
  by note path and behaves identically for both.

  At most one coordinator job runs per asset at a time. A wake-worthy signal that arrives while
  one is already running is remembered rather than acted on immediately, and is redeemed once
  the job finishes by resolving triggers fresh against the asset's current state — honoring the
  same halt override every other trigger respects. A fresh wakeup queues the job, stamps the
  asset's job marker in the sidecar, records the item on the dispatch cursor, and commits under
  this worker's own bot identity whenever doing so actually changes the note.

  A finished job that left an approved document at the draft stage wakes the coordinator once more
  over that document; a repeat of the same lag is recorded as one warning in the note's history
  and wakes nobody. A wake dispatched over a lagging document counts its lag as already woken.

  When `sibling_doc` is given, this is a sibling-item tick: the wake is decided by the sibling's
  own `review_result` changing rather than by `item`'s commit against `asset_note`, honoring the
  same halt override every other trigger respects (`lazy-spec.coordination-playbook.md` § 1).

  Guarantees:
    - At most one coordinator job runs against a given note at a time; a wake that arrives while
      one is still active never dispatches a second job for that note until the running one
      finishes.
    - Writes and commits the status folder-note only when the produced text differs from the
      note's bytes as read at the start of the call; a wake that changes nothing leaves the note
      byte-identical and creates no commit.
    - On the wake of an asset's status note, the context handed to a dispatched job lists the
      rule layers outermost first, so the layer closest to the asset lands last: ancestor
      products' level notes, the owning product's note, then container folder-notes shallowest
      first; a container without a folder-note contributes no entry and no warning.

  Notes:
    - A raise here leaves the tick's in-memory state unwritten, but the wake it carried is not
      lost: a non-zero exit from this CLI invocation is caught by `dispatch_git`'s command
      shape, which records the item and retries it, ahead of any fresh item, on the next tick
      — self-healing until the exception stops recurring, or the item's sha becomes
      unreachable, in which case it is dropped instead of replayed.
    - A call on an asset of any type but `release` whose `Gate.DESIGN_DONE` or
      `Gate.SPEC_CANCELLED` changed value dispatches one job on the level note of the product that
      owns releases. That side effect runs only after this asset's own dispatch has landed, and
      never propagates a failure of its own back to the caller (N2).
    - That edge does not require a trigger to have resolved on the asset itself: both gates are
      normally flipped by a bot-authored commit that wakes nothing here, so the crossing is
      evaluated before the no-trigger exit, recorded on the note, and dispatched onward from that
      exit too.

  Args:
    asset_note: The status folder-note path; its parent is the asset dir.
    item: The git-watch item that woke this tick — either the single-file `changed_files` shape
      (`path`, `status`, `sha`, `author_name`, `author_email`; `path` names `sibling_doc` itself
      on a sibling-item tick, never `asset_note`) or, when `group_members` is given, the grouped
      shape (`dir`, `paths`, `sha`, `author_name`, `author_email`) naming the asset directory and
      the last commit that touched it.
    today: Optional ISO date forwarded into the `# History` line.
    sibling_doc: The sibling doc's own path, when this tick's item is one of the asset's typed
      documents rather than the status folder-note itself. None for the ordinary status-note tick;
      mutually exclusive with `group_members`.
    group_members: The group's OTHER member paths — every sibling doc a grouped `{dir, paths,
      ...}` item names, excluding the status folder-note itself. Given only for a grouped tick;
      trigger resolution then runs `_resolve_group_trigger` (one pass over every member) instead
      of the single-file `resolve_wake_trigger` / `sibling_doc` branching,
      and `item`'s own `sha`/`author_email` name the group directory's own last commit rather
      than one file's. None for every other call shape; mutually exclusive with `sibling_doc`.
    level_doc: The level document's own path, when this tick's item is one of the level ladder's
      basenames (`LevelDoc.BASENAMES`) rather than the level note itself. Given only when
      `asset_note` is a level note; a level tick naming the note itself passes None, and trigger
      resolution then reads the ordinary ladder off the note alone.
    asset_approved: The owner-relative path token of an asset whose start document just reached
      `approved` (or was re-approved, or whose asset was cancelled), when this call is the one-hop
      upward dispatch that crossing raises on the level note of the product owning releases.
      Trigger resolution short-circuits to `CoordinatorTrigger.ASSET_APPROVED` (honoring the halt
      override); `item` is `{}` on this path. None for every ordinary tick.
    release_start: True when this call is the one-hop downward dispatch raised on a release's own
      status note after `Start release`, and again after a verdict on the revised `architecture.md`
      of the build's first step. Accepted only by a status note of type `release` — any other note
      refuses it; trigger resolution short-circuits to `CoordinatorTrigger.RELEASE_START` (honoring
      the halt override); `item` is `{}` on this path.
    release_published: True when this call is the one-hop upward dispatch raised on the level note of the
      product owning releases after a release was published. Accepted only by a level note — any other note
      refuses it; trigger resolution short-circuits to `CoordinatorTrigger.RELEASE_PUBLISHED` (honoring the
      halt override); `item` is `{}` on this path.

  Returns:
    `{"action": "refused", "reason"}` when `release_start` names a note that is not a release, or
    `release_published` names a note that is not a level note;
    `{"action": "noop"}`; `{"action": "dispatch-stale", "trigger", "job_id"}` when the dispatch
    matched an already-finished bundle — the trigger is retired, not retried, since the
    git-watch routine's own cursor has already advanced past this item regardless (N2); or
    `{"action": "dispatched", "trigger", "expert", "job_id", "warnings"}` on a fresh dispatch.

  Raises:
    RuntimeError: When the `lazycortex-core` CLI can't be resolved or exits non-zero.
    subprocess.CalledProcessError: When the commit of the rewritten note fails — propagated
      from `_commit`.
  """
  # the asset folder and its repo root anchor every path resolved below
  asset_dir = asset_note.parent
  repo_root = flip_gate.repo_root(asset_dir)

  # a manual wake (lazy-spec.drive's path-only item) carries neither `sha` nor `author_email` —
  # derive both from the newest commit touching the path, so the operator-author check, the
  # cursor-bounded lookback, and the dispatch-cursor stamp all work exactly as they do for a
  # daemon git-watch item; a daemon item's own fields always win over the derivation
  if item.get(_ITEM_PATH) and (not item.get(_ITEM_SHA) or not item.get(_ITEM_AUTHOR_EMAIL)):
    head = subprocess.run(
        ["git", "log", "-1", "--format=%H%x00%ae", "--", str(item[_ITEM_PATH])],
        cwd = str(repo_root), capture_output = True, text = True, check = False, encoding = "utf-8",
    )
    if head.returncode == 0 and head.stdout.strip():
      sha, _, email = head.stdout.strip().partition("\x00")
      item = { **item, _ITEM_SHA: item.get(_ITEM_SHA) or sha,
               _ITEM_AUTHOR_EMAIL: item.get(_ITEM_AUTHOR_EMAIL) or email }

  # snapshot the note once — every branch below decides off this one read
  today_str = flip_gate.effective_today(today)
  text = spec_paths.read_text(asset_note)
  original_text = text
  frontmatter, fm_end = flip_gate.parse_frontmatter(text)
  body = text[fm_end:]
  markers = spec_job_markers.read(repo_root, asset_note)
  raised_lags = spec_job_markers.read_stage_lag(repo_root, asset_note)
  cursor = _read_dispatch_cursor(repo_root, asset_note)

  # the note's own role picks the ladder and the persona; everything else below is shared
  role = str(frontmatter.get(SpecKey.ROLE) or "")
  is_level = role in LEVEL_ROLES
  asset_type = "" if is_level else str(frontmatter.get(AssetTypeKey.TYPE) or "")
  expert = _CATALOG_EXPERT if is_level else _COORDINATOR_EXPERT
  doc_basenames = LevelDoc.BASENAMES if is_level else None

  # guard: a release-start wake belongs to a release's own status note and to nothing else
  if release_start and asset_type != ReleaseKey.ASSET_TYPE:
    return {
        TickAction.ACTION: TickAction.REFUSED,
        TickAction.REASON: f"release-start on a note that is not a release: {asset_note.name}",
    }

  # guard: a release-published wake belongs to the level note of the product that owns releases and to nothing else
  if release_published and not is_level:
    return {
        TickAction.ACTION: TickAction.REFUSED,
        TickAction.REASON: f"release-published on a note that is not a level note: {asset_note.name}",
    }

  # Domain(spec.lifecycle):
  # # One coordinator job per asset
  # At most one coordinator action ever runs against a given asset at a time. A reason to act
  # that arrives while one is already running is not queued or replayed — it is remembered as a
  # single flag, since acting on it immediately could mean rewriting the asset's own record out
  # from under the action already in flight. Once free, that flag makes the coordinator look at
  # the asset's current state fresh rather than replay the original reason, since real time has
  # passed and something more specific may already have happened. A flag raised because the
  # running action itself just finished survives a wake that gets preempted by something more
  # urgent, so its result is still revisited later; a flag raised for any other reason is
  # cleared the moment any wake at all is acted on for the asset, because whatever runs next
  # already accounts for it. Pausing the asset holds either flag untouched until the pause is
  # lifted, rather than resolving it into a generic catch-up the operator never asked for.
  # An action that is still waiting its turn has not looked at anything yet: it reads the asset
  # only when it actually starts, so a reason arriving before that is already covered by it and
  # is neither flagged nor replayed — flagging it would make the coordinator act twice on the
  # same change, once in the queued action and once more on the record that action leaves. The
  # same holds for a running action and every change that was already part of what it read
  # when it started: only a change that arrived after that moment is genuinely unseen.

  # Contract:
  # At most one coordinator job runs against a given note at a time; a wake that arrives while
  # a job is still active for that note never dispatches a second job until the running one
  # finishes.

  # one active coordinator job per asset — unconditional, no halt/command exception
  note_dirty = False
  coordinator_job = markers[JobMarker.COORDINATOR_JOB]
  if isinstance(coordinator_job, dict):
    marker = gate_tick.find_active_job_marker(
        repo_root, coordinator_job[JobMarker.EXPERT], coordinator_job[JobMarker.JOB_ID],
    )

    # a bundle with no terminal marker yet is still running
    if marker is None:
      # a job still in the queue reads the tree only when the pump claims it, so this item —
      # and every commit before the claim — is already covered by the queued job itself. The
      # dispatch cursor moves past the item so the job's own later commit cannot replay it as a
      # bot-buried operator edit, and no `declined` flag is stamped, since there is nothing left
      # to redeem once the job runs. A `job-done` flag already raised is left as it is.
      # queued, never claimed — covered, nothing to defer
      if gate_tick.is_job_queued(
          repo_root, coordinator_job[JobMarker.EXPERT], coordinator_job[JobMarker.JOB_ID],
      ):
        _stamp_dispatch_cursor(repo_root, asset_note, item.get(_ITEM_SHA))
        return { TickAction.ACTION: TickAction.NOOP }

      # a claimed job copied its inputs from the tree at one exact commit; an item already
      # reachable from that commit was inside what it read, so it is covered the same way —
      # only a change that reached the tree after the claim is genuinely unseen and deferred.
      # A bundle without the marker (an older pump, a synthetic wake with no commit) reads as
      # unseen, the conservative side. The daemon checkout only ever fast-forwards, so no member
      # commit of a group is reachable only through a merge the claim missed.
      # limit: a grouped item is judged by its newest commit alone, check every member if merges appear
      claim_head = gate_tick.read_job_claim_head(
          repo_root, coordinator_job[JobMarker.EXPERT], coordinator_job[JobMarker.JOB_ID],
      )
      item_sha = item.get(_ITEM_SHA)
      # the running job already read this commit — covered, nothing to defer
      if claim_head and item_sha and _is_ancestor(repo_root, item_sha, claim_head):
        _stamp_dispatch_cursor(repo_root, asset_note, item_sha)
        return { TickAction.ACTION: TickAction.NOOP }

      # the git-watch cursor advances past this item regardless of the noop below, so a
      # wake-worthy tick seen here would otherwise be lost the moment the job finishes with
      # nothing further changing the note (N2) — one sidecar flag, no note write, no commit;
      # job-done already means "wake me", so a later decline must never overwrite it
      wake_members = group_members if group_members is not None else [
          doc for doc in ( sibling_doc, level_doc ) if doc is not None
      ]

      # the review-active carve-out only ever applies to a genuine grouped tick — the plain
      # status-note and sibling-item shapes keep `_has_group_wake`'s default `note_changed
      # = True`, which is an unconditional author check exactly as before this fix
      wake_note_changed = (
          _has_group_note_changed(item, asset_note, repo_root) if group_members is not None else True
      )
      if (
          markers.get(JobMarker.PENDING_WAKE) is None
          and _has_group_wake(
              frontmatter, body, item, wake_members, raised_lags = raised_lags,
              note_changed = wake_note_changed, basenames = doc_basenames,
          )
      ):
        spec_job_markers.update(repo_root, asset_note, { JobMarker.PENDING_WAKE: JobMarker.DECLINED })
      # limit: an approval crossing waits for the job too, evaluate it before this branch if the wait costs
      return { TickAction.ACTION: TickAction.NOOP }

    # the bundle finished since the last tick — clear the slot now so a trigger firing this
    # same tick dispatches immediately instead of first colliding with the old dedup key (M1)
    if marker == gate_tick.JOB_MARKER_DEAD:
      # DEAD is not eligible for dedup matching in the first place (expert_runtime's own scan
      # excludes it), so this guard owes only the WARNING line — never consume_stale_job. Same
      # text as gate_tick's periodic sweep of this key (fix-round-1: this guard used to consume
      # DEAD identically to DONE/CANCELLED, silently dropping the line whenever it won the race)
      body = history_journal.append(
          body,
          gate_tick.coordinator_job_dead_line(
              coordinator_job[JobMarker.TRIGGER], coordinator_job[JobMarker.JOB_ID],
              lang = note_explainers.lang_for_note(asset_note),
          ),
          today_str, repo = repo_root,
      )

      # the WARNING line is the only note text this guard ever produces — the marker clear
      # itself is a sidecar write, so every other branch leaves the note byte-identical
      text = text[:fm_end] + body
      note_dirty = True
    else:
      gate_dispatch.consume_stale_job(
          repo_root, coordinator_job[JobMarker.EXPERT], coordinator_job[JobMarker.JOB_ID])
    markers = spec_job_markers.update(repo_root, asset_note, { JobMarker.COORDINATOR_JOB: None })

    # a finished job that left an approved document at `draft` wakes the coordinator once, then
    # warns — the same check the gate tick runs when it sweeps the job first; that check commits
    # the note itself, so every branch below decides off the state it left
    if (
        marker == gate_tick.JOB_MARKER_DONE
        and gate_tick.update_stage_lag(asset_note, asset_dir, repo_root, today_str)
    ):
      text = spec_paths.read_text(asset_note)
      original_text = text
      frontmatter, fm_end = flip_gate.parse_frontmatter(text)
      body = text[fm_end:]
      markers = spec_job_markers.read(repo_root, asset_note)
      raised_lags = spec_job_markers.read_stage_lag(repo_root, asset_note)

  # an old install's note still carrying either retired frontmatter pending-note key reads as a
  # declined-wake for this tick — redeemed the same way the sidecar flag is below, and stripped
  # off the note on whichever write follows (`_strip_legacy_pending`, applied to `fm_text` once
  # it's built further down)
  legacy_pending = _LEGACY_PENDING_EDIT_KEY in frontmatter or _LEGACY_PENDING_DOC_KEY in frontmatter

  # resolve what woke the coordinator, honoring the halt override
  doc_transition = None
  group_transitions: dict[str, str] = {}
  if group_members is not None:
    trigger, group_transitions = _resolve_group_trigger(
        repo_root, frontmatter, body, item, markers, group_members, asset_note, cursor,
        raised_lags = raised_lags,
    )

    # the FULL set stamps into spec_coordinator_doc_state below; `doc_transition` only carries
    # the first-sorted pair so every other consumer built around a single (basename, value) —
    # the History line, the dedup match — keeps working unchanged (brief step 5)
    if trigger == CoordinatorTrigger.DOC_TRANSITION:
      first = sorted(group_transitions)[0]
      doc_transition = (first, group_transitions[first])
  elif asset_approved is not None:
    # halt silences the upward approval wake exactly like every other automation trigger
    # (playbook § 1); `item` is empty on this synthetic path
    trigger = None if flip_gate.is_true(frontmatter, SpecHaltKey.HALTED) else CoordinatorTrigger.ASSET_APPROVED
  elif release_start:
    # halt silences the downward release-start wake the same way; `item` is empty on this synthetic path
    trigger = None if flip_gate.is_true(frontmatter, SpecHaltKey.HALTED) else CoordinatorTrigger.RELEASE_START
  elif release_published:
    # halt silences the upward release-published wake the same way; `item` is empty on this synthetic path
    trigger = None if flip_gate.is_true(frontmatter, SpecHaltKey.HALTED) else CoordinatorTrigger.RELEASE_PUBLISHED
  elif is_level:
    # the level ladder reads its own documents rather than an asset's siblings, and resolves the
    # full transition set in one pass exactly as the grouped asset form does
    trigger, group_transitions = _resolve_level_trigger(
        repo_root, frontmatter, body, item, [ level_doc ] if level_doc is not None else [], cursor,
        raised_lags = raised_lags,
    )
    if trigger == CoordinatorTrigger.DOC_TRANSITION:
      first = sorted(group_transitions)[0]
      doc_transition = (first, group_transitions[first])
  elif sibling_doc is not None:
    resolved = _resolve_doc_transition(sibling_doc, frontmatter, raised_lags = raised_lags)

    # halt silences a doc-transition wake exactly like every other automation trigger
    # (playbook § 1) — a sibling item never carries the COMMAND exemption, since COMMAND is
    # read off the asset note's own body, not the sibling
    if resolved is None or flip_gate.is_true(frontmatter, SpecHaltKey.HALTED):
      trigger = None
    else:
      trigger = CoordinatorTrigger.DOC_TRANSITION
      doc_transition = resolved
  else:
    trigger = resolve_wake_trigger(repo_root, frontmatter, body, item, markers, cursor)

  # nothing else claimed this tick — a wake the busy-guard declined (or a legacy install's
  # pending-note key) redeems by re-resolving triggers against the asset's CURRENT on-disk
  # state, since the flag alone doesn't say what specifically changed while the job was busy;
  # unlike the shape-specific branches above, this always scans every sibling doc in the asset
  # directory rather than only the member(s) this tick's own item happened to name
  # snapshotted once, up front, and never reset below — Finding 2 needs the ORIGINAL flag value
  # to survive even when a normal-ladder trigger (COMMAND/ANSWER/DOC_TRANSITION/OPERATOR_EDIT)
  # resolves before this block ever runs, so the consumption check further down can still tell a
  # declined wake was riding along on whichever trigger actually won
  redeemed_wake = markers.get(JobMarker.PENDING_WAKE)
  if trigger is None and (redeemed_wake in (JobMarker.JOB_DONE, JobMarker.DECLINED) or legacy_pending):
    redeem_members = sorted(
        entry for entry in asset_dir.iterdir() if spec_doc_types.is_ladder_document(entry, doc_basenames)
    )
    if is_level:
      trigger, group_transitions = _resolve_level_trigger(
          repo_root, frontmatter, body, item, redeem_members, cursor, raised_lags = raised_lags,
      )
    else:
      trigger, group_transitions = _resolve_group_trigger(
          repo_root, frontmatter, body, item, markers, redeem_members, asset_note, cursor,
          raised_lags = raised_lags,
      )
    if trigger is None:
      # nothing specific replayed — the generic fallback token per the flag that forced this
      # redemption; a legacy-only note (no sidecar flag) falls back the same way declined does.
      # A halted asset is a noop here, never a fallback dispatch: `_resolve_group_trigger` already
      # returned None for exactly that reason (its halt override, COMMAND excepted — but COMMAND
      # would have set `trigger` above, never reaching this branch), and forcing a fallback trigger
      # anyway would both dispatch AND consume the flag below, permanently losing the wake instead
      # of leaving it for the operator to lift the halt and redeem later.
      if not flip_gate.is_true(frontmatter, SpecHaltKey.HALTED):
        trigger = (
            CoordinatorTrigger.JOB_DONE if redeemed_wake == JobMarker.JOB_DONE
            else CoordinatorTrigger.OPERATOR_EDIT
        )
    elif trigger == CoordinatorTrigger.DOC_TRANSITION:
      first = sorted(group_transitions)[0]
      doc_transition = (first, group_transitions[first])

  # the gate crossing this tick observed, read BEFORE the no-trigger exit below: the edge does not
  # belong to this asset's own wake — an approval reaches the release owner's level ladder above —
  # and both its gates are normally flipped by a bot-authored commit that wakes nothing here, so a
  # crossing evaluated after the exit would be lost (N1)
  cur_ready = None
  approved_crossed = False
  prev_ready: dict = {}
  if not is_level:
    prev_ready = _read_marker_dict(frontmatter, SpecCoordinatorReadyStateKey.STATE)
    cur_ready = {
        Gate.DESIGN_DONE: flip_gate.is_true(frontmatter, Gate.DESIGN_DONE),
        Gate.SPEC_CANCELLED: flip_gate.is_true(frontmatter, Gate.SPEC_CANCELLED),
    }

    # the approval edge rides the same marker too, in both directions; a recorded marker from before the
    # approval keys existed reads as matching on them, so the upgrade itself raises no hop
    approved_crossed = asset_type != ReleaseKey.ASSET_TYPE and any(
        cur_ready[key] != prev_ready.get(key, cur_ready[key] if prev_ready else False) for key in _APPROVAL_EDGES
    )

  # no trigger this tick: record a gate crossing and the dead-job line if either landed, wake the
  # release owner that crossing reaches, and leave without dispatching
  if trigger is None:
    # a crossing that landed on a commit nothing else woke on still has to be recorded and
    # dispatched onward: the approval edge is flipped by bot-authored commits (the coordinator's own
    # `flip-gate` write), which suppress this asset's own wake but say nothing about the
    # release owner above. The whole observed snapshot is stamped, exactly as the
    # dispatching path stamps it, so the edge cannot re-fire on a later tick.
    # A marker lacking the approval keys is stamped to the full snapshot on its first wake, so a
    # later approval or reopening is measured against a recorded value rather than read as matching.
    stamped = approved_crossed or _is_marker_legacy(prev_ready)
    fm_head = text[:fm_end]
    if stamped and cur_ready is not None:
      fm_head = gate_tick.set_fm_json(fm_head, SpecCoordinatorReadyStateKey.STATE, cur_ready)
    text = fm_head + text[fm_end:]

    # the dead-job WARNING line above still needs to land even with nothing left to dispatch;
    # a job merely consumed left no note text behind, so that tick writes nothing at all
    if note_dirty or stamped:
      # name what actually landed: the dead-job line outranks a crossing, a crossing outranks an upgrade
      what = (
          f"coordinator job died on {asset_dir.name}" if note_dirty
          else f"recorded gate crossing on {asset_dir.name}" if approved_crossed
          else f"recorded gate snapshot on {asset_dir.name}"
      )
      spec_paths.write_text_atomic(asset_note, note_explainers.heal_note_text(asset_note, text))
      _commit(asset_dir, asset_note, f"{_DISPATCH_AUTHOR_NAME}: {what}")

    # the hop runs after the record lands, so a failing release owner can't lose the stamp
    if approved_crossed:
      wake_release_owner_on_approval(repo_root, asset_dir, today = today)
    return { TickAction.ACTION: TickAction.NOOP }

  # assemble and queue the coordinator job's wire bundle — the level branch reads the level
  # ladder's own layers instead of the asset's type, tools and targets
  protocols: list[str] = []
  if is_level:
    source, context, warnings, payload, dedup_key, protocols = _build_level_bundle(
        repo_root, asset_note, role, trigger,
        doc_transition = doc_transition[0] if doc_transition is not None else None,
        asset_approved = asset_approved,
    )
  else:

    # Contract:
    # On the wake of an asset's status note, the context handed to a dispatched coordinator job
    # lists the rule layers outermost first: every ancestor product's level note, then the owning
    # product's note, then the container folder-notes between the product root and the asset
    # folder, shallowest first, so the layer closest to the asset lands last. A container without
    # a folder-note MUST contribute no entry and no warning.

    # build the asset wake's bundle from the asset's own type, tools and targets
    source, context, warnings, payload, dedup_key = _build_bundle(
        repo_root, asset_dir, asset_note, text[:fm_end], trigger,
        doc_transition = doc_transition[0] if doc_transition is not None else None,
    )

  # a grouped tick's FULL transition set rides in payload too — `payload["doc"]` above already
  # names the first-sorted basename, "docs" only needs to appear when there is more than one to
  # add, so the coordinator can process every transitioned sibling in one pass (brief step 5)
  if len(group_transitions) > 1:
    # waiver: payload wire-key literal, same wire-schema dict as `_build_bundle`'s own wire-key literals
    payload["docs"] = sorted(group_transitions)
  bundle = {
      gate_dispatch.WireKey.EXPERT: expert,
      gate_dispatch.WireKey.PAYLOAD: payload,
      gate_dispatch.WireKey.SOURCE: source,
      gate_dispatch.WireKey.DEDUP_KEY: dedup_key,
  }

  # context is optional on the wire — only sent when there's actually something in it
  if context:
    bundle[gate_dispatch.WireKey.CONTEXT] = context

  # so is the playbook reference: core unions it with the dispatching routine's own protocols,
  # which is how one routine serves two ladders with two playbooks
  if protocols:
    bundle[_WIRE_PROTOCOLS] = protocols
  response = gate_dispatch.core_dispatch_job(repo_root, bundle)
  job_id = str(response.get(gate_dispatch.WireKey.JOB_ID))

  # consume the sidecar wake now that this tick's dispatch has landed, so the same wake cannot
  # fire a second coordinator. The two flag values consume on different terms: `job-done` only
  # when it actually won resolution (`trigger == JOB_DONE`) — a wake this tick preempted (a
  # command, an answer) keeps its flag and fires on a later tick, unchanged from before this
  # fix. `declined` inherits the retired `pending_edit` flag's own behaviour instead — it is
  # consumed on ANY successful dispatch of this asset, whichever trigger won, because unlike
  # job-done it carries no trigger identity of its own to wait for; leaving it set past a
  # dispatch that already covers the same wake would just re-redeem it, uselessly, next tick.
  # Deliberately after the dispatch rather than before it: a raise from `gate_dispatch.core_dispatch_job`
  # leaves this tick's state unwritten and `dispatch_git` replays the item, which is only
  # self-healing while the flag that carried the wake is still there to be read again.
  if trigger == CoordinatorTrigger.JOB_DONE or redeemed_wake == JobMarker.DECLINED:
    spec_job_markers.update(repo_root, asset_note, { JobMarker.PENDING_WAKE: None })

  # these three stamps land on EVERY exit past this point, stale-retire included (I6) — a
  # stale-retired trigger still genuinely fired (the sibling's review_result really did change,
  # or the ticked question really was new); leaving them unset on that exit would let the exact
  # same content re-fire the identical trigger on a later, non-stale tick, since nothing else
  # ever records that this worker already reacted to it. A legacy install's retired pending-note
  # keys are stripped here too — this write is "the nearest write" `_strip_legacy_pending`'s own
  # docstring promises, whatever the trigger that produced it.
  fm_text = _strip_legacy_pending(text[:fm_end])

  # record the approval-gate snapshot this tick observed, regardless of whether it crossed
  # anything, so the NEXT tick's crossing check compares against the latest state (N1) — a
  # level note has no `cur_ready` to stamp, since it never runs the check itself. A
  # marker that already records every observed value is left as it is, so a wake that changed
  # nothing does not rewrite it — unless it is a legacy marker, one whose keys differ from the two
  # approval keys (including one still carrying the retired `spec_develop_done` /
  # `spec_tests_passing`), which is stamped on its first wake
  if cur_ready is not None and (_has_snapshot_changed(cur_ready, prev_ready) or _is_marker_legacy(prev_ready)):
    fm_text = gate_tick.set_fm_json(fm_text, SpecCoordinatorReadyStateKey.STATE, cur_ready)

  # stamp the answered-question fingerprint so an identical ticked block never re-fires ANSWER
  # once this worker has already reacted to it (I1/I-D)
  answered_block = _find_ticked_question_block(body) if trigger == CoordinatorTrigger.ANSWER else None
  if answered_block is not None:
    fm_text = note_ops.set_fm_scalar(
        fm_text, AnsweredQuestionKey.FINGERPRINT, _compute_answer_fingerprint(answered_block),
    )

  # stamp the sibling's transitioned review_result so an unchanged re-tick never re-fires
  # DOC_TRANSITION for the same basename+value (mirrors the ANSWER fingerprint stamp above)
  if doc_transition is not None:
    basename, new_value = doc_transition
    state = _read_doc_state(frontmatter)

    # a grouped (or redeemed-declined) tick may have found MORE than one sibling transition in
    # the same pass — stamp them all now so none is lost to a later tick (brief step 5); every
    # other DOC_TRANSITION path (single sibling-doc tick) always has exactly one pair here
    state.update(group_transitions or { basename: new_value })
    fm_text = gate_tick.set_fm_json(fm_text, SpecCoordinatorDocStateKey.STATE, state)

    # a lagging document this wake fired over has spent its one wake; the next finish only warns
    gate_tick.record_stage_lag_wake(
        repo_root, asset_note, [ asset_dir / name for name in group_transitions or { basename: new_value } ],
    )

  # a dedup hit matching a finished-but-unconsumed bundle is retired rather than tracked — left
  # unconsumed, the same terminal bundle would keep matching this dedup key on every future tick.
  # The git-watch cursor has already moved past this item regardless (N2), so this trigger is
  # retired, not retried — the M1 slot clear above (a finished bundle's marker cleared before the
  # dispatch) makes this path rare, reached
  # only by a genuine same-tick race rather than the routine steady state it used to be.
  if (
      response.get(gate_dispatch.WireKey.STATUS) == gate_dispatch.ALREADY_QUEUED_STATUS
      and gate_tick.find_active_job_marker(repo_root, expert, job_id) is not None
  ):
    gate_dispatch.consume_stale_job(repo_root, expert, job_id)

    # the retired trigger still counts as handled — the cursor moves so the same commit never
    # re-fires, and the I6 stamps persist below only when they actually changed the note
    _stamp_dispatch_cursor(repo_root, asset_note, item.get(_ITEM_SHA))
    new_text = fm_text + body
    if new_text != original_text:
      spec_paths.write_text_atomic(asset_note, note_explainers.heal_note_text(asset_note, new_text))
      _commit(
          asset_dir, asset_note,
          f"{_DISPATCH_AUTHOR_NAME}: stale dispatch for {trigger} on {asset_dir.name}",
      )

    # an approval crossing wakes the release owner's level coordinator only after this asset's own
    # dispatch has landed, one hop, best-effort, so a broken release owner can't strand it (N2)
    if approved_crossed:
      wake_release_owner_on_approval(repo_root, asset_dir, today = today)

    # this tick's own trigger was retired, not dispatched — see the guard above
    return { TickAction.ACTION: TickAction.DISPATCH_STALE, TickAction.TRIGGER: trigger, TickAction.JOB_ID: job_id }

  # record the dispatched job in runtime state so the active-job guard blocks a second
  # concurrent dispatch — no note write, so this stamp costs no commit of its own and nothing
  # an operator editing the note can break; the cursor moves in the same breath, so the handled
  # item's commit never re-fires a later lookback
  spec_job_markers.update(repo_root, asset_note, {
      JobMarker.COORDINATOR_JOB: { JobMarker.TRIGGER: trigger, JobMarker.EXPERT: expert, JobMarker.JOB_ID: job_id },
  })
  _stamp_dispatch_cursor(repo_root, asset_note, item.get(_ITEM_SHA))

  # the wake itself leaves no `# History` line — `# History` records the asset's own
  # transitions, not this worker's mechanics; a dispatch warning (an unresolved context path)
  # is still landed, one line each, never a silent skip
  new_body = body
  for warning in warnings:
    new_body = history_journal.append(new_body, warning, today_str, repo = repo_root)

  # Contract:
  # The status folder-note MUST be written and committed only when the produced text differs
  # from the note's bytes as read at the start of the call — a frontmatter stamp, a legacy-key
  # strip, a warning line, or the dead-job WARNING line. A wake that changes nothing MUST leave
  # the note byte-identical and MUST NOT create a commit.

  # write and commit only when something above actually changed the note — an I6 stamp, a
  # legacy-key strip, a warning line, the dead-job WARNING; a plain wake leaves the note
  # byte-identical and costs no commit at all, so explainer healing rides real writes only
  new_text = fm_text + new_body
  if new_text != original_text:
    spec_paths.write_text_atomic(asset_note, note_explainers.heal_note_text(asset_note, new_text))
    _commit(
        asset_dir, asset_note,
        f"{_DISPATCH_AUTHOR_NAME}: wake {trigger} on {asset_dir.name} → {expert} ({job_id})",
    )

  # an approval crossing wakes the release owner's level coordinator only after this asset's own
  # dispatch has landed, one hop, best-effort, so a broken release owner can't strand it (N2)
  if approved_crossed:
    wake_release_owner_on_approval(repo_root, asset_dir, today = today)

  # the fresh dispatch this tick queued
  return {
      TickAction.ACTION: TickAction.DISPATCHED,
      TickAction.TRIGGER: trigger,
      TickAction.EXPERT: expert,
      TickAction.JOB_ID: job_id,
      TickAction.WARNINGS: warnings,
  }


def _rekey_to_own_commit(repo_root: Path, item: dict, rel_path: str) -> dict:
  """
  Re-key a grouped item's commit fields to the last commit touching one of its own paths.

  The lookup is bounded at the item's own `sha`, so a retried item never picks up a commit
  newer than its range.

  Notes:
    - Spawns one `git log` subprocess in `repo_root` per call.

  Args:
    repo_root: The repository root to run `git` in.
    item: The grouped git-watch item, or an orphan's single-path derivation of it.
    rel_path: The repo-relative path (an asset dir, or an orphan file) to key the commit off.

  Returns:
    A copy of `item` with the three commit fields replaced; `item` itself when git knows no
    commit touching `rel_path` (a path outside history, or a range sha rewritten away).
  """

  # Domain(spec.lifecycle):
  # # Each asset of a batch is judged by its own last commit
  # A batch of changed paths arrives attributed to one commit, the last of the scanned range, and
  # that commit may belong to a different asset entirely. The wake triggers read the commit's
  # author to tell an operator's edit from the system's own, so an asset whose only change was
  # the system's would wake on another asset's operator edit if the batch's attribution were
  # taken at face value. Each owner is therefore re-attributed to the last commit touching its
  # own folder before its triggers are judged, and that lookup never reaches past the batch's
  # own commit, so a batch retried later still judges the state it was raised for.

  # bounded at the range tip when the item carries one; an unknown tip (rewritten history)
  # makes git fail, and the item keeps the range-level fields rather than losing the tick
  sha = item.get(_ITEM_SHA)
  head = subprocess.run(
      [ "git", "log", "-1", "--format=%H%x00%an%x00%ae", *([ sha ] if isinstance(sha, str) and sha else []),
        "--", rel_path ],
      cwd = str(repo_root), capture_output = True, text = True, check = False, encoding = "utf-8",
  )

  # guard: no commit to key off — the range-level fields stay
  if head.returncode != 0 or not head.stdout.strip():
    return item
  own_sha, name, email = head.stdout.strip().split("\x00", 2)
  return { **item, _ITEM_SHA: own_sha, _ITEM_AUTHOR_NAME: name, _ITEM_AUTHOR_EMAIL: email }


def _find_deleted_path_owner(repo_root: Path, deleted: Path) -> Path | None:
  """
  Resolve the coordinated folder-note that still owns the place a deleted file lay.

  Args:
    repo_root: The repository root the content root and the product records resolve under.
    deleted: The deleted file's absolute, resolved path.

  Returns:
    The owning note on disk — the note a live document there would resolve to, else the nearest
    asset status note above it, else the owning product's level note — or None when none exists.
  """

  # Domain(spec.lifecycle):
  # # A deleted document wakes whoever still owns its place
  # Removing a document is an edit to whatever coordinates the place it lay in. While the asset
  # folder still stands, its own status record is that owner and has to notice its launch rows
  # and brief have gone stale. When the whole asset was removed with it, nothing at the asset's
  # level is left to notice, so the product the asset belonged to is the owner instead and
  # refreshes its own picture of what it holds. A system document deleted from the catalog root
  # wakes the catalog root's own record; any other deletion no product owns concerns nobody.

  # the note a live document in the same place would resolve to, while it still coordinates
  owner = _resolve_owner_note(repo_root, deleted)
  if owner.is_file():
    frontmatter, _ = flip_gate.parse_frontmatter(owner.read_text(encoding = "utf-8"))
    role = frontmatter.get(SpecKey.ROLE)
    if role == _SPEC_ROLE_STATUS or role in LEVEL_ROLES:
      return owner

  # the nearest asset still standing above the deleted place (an attachment folder, a nested asset)
  if (status_note := _owner_status_note(deleted.parent, spec_paths.spec_content_root(repo_root).resolve())):
    return status_note

  # no asset is left over the place — the owning product's level note, when it exists
  _, record = resolve_product.resolve_product_by_path(repo_root, _to_rel_path(repo_root, deleted))
  level_note = _resolve_product_note_path(repo_root, record) if isinstance(record, dict) else None
  return level_note if level_note is not None and level_note.is_file() else None


def _dispatch_deleted_path(deleted: Path, item: dict, today: str | None) -> dict:
  """
  Run the dispatch for one deleted path — an operator edit on the note that still owns its place.

  Args:
    deleted: The deleted file's absolute, resolved path.
    item: The git-watch item the path came from (its commit fields ride into the dispatch).
    today: Optional ISO date forwarded into the note's own `# History` line.

  Returns:
    The tick's result dict; `{"action": "noop"}` when the deletion is bot-authored or no
    coordinated note owns the deleted place.
  """
  # guard: a bot-authored deletion is the system's own housekeeping — no later commit can bury an
  # operator's deletion of the same path, so the item's own author is the deletion's author
  if _BOT_MARK in item.get(_ITEM_AUTHOR_EMAIL, ""):
    return { TickAction.ACTION: TickAction.NOOP }

  # the deleted file's own folder may be gone too, so git runs in the nearest one still standing
  standing = next(folder for folder in deleted.parents if folder.is_dir())

  # guard: no coordinated note owns the deleted place
  if (owner := _find_deleted_path_owner(flip_gate.repo_root(standing), deleted)) is None:
    return { TickAction.ACTION: TickAction.NOOP }

  # an ordinary operator-edit wake on the owner — the deleted file has no frontmatter to read
  return coordinator_dispatch(owner, item, today = today)


def _dispatch_single_path(changed: Path, item: dict, today: str | None) -> dict:
  """
  Run the single-file dispatch for one changed path — a document or a folder-note.

  A document basename resolves to the folder-note that owns it, by where the document lies;
  every other match IS the folder-note the routine's own `any_of` member selected. The owner's
  own role then picks the ladder: an asset's status note runs the asset one, a product's or the
  catalog root's level note the level one, and a note carrying neither is nobody's object. A path
  that no longer exists is a deletion and wakes the note that still owns its place instead.

  Args:
    changed: The changed file's absolute, resolved path.
    item: The git-watch item the path came from (its commit fields ride into the dispatch).
    today: Optional ISO date forwarded into the note's own `# History` line.

  Returns:
    The tick's result dict; `{"action": "noop"}` on every guard (no owning note, a note without
    a coordination role, a document of the other ladder, a deletion that is bot-authored or
    that no coordinated note owns).
  """
  # a path that no longer exists is a deletion, routed to whichever note still owns where it lay
  if not changed.is_file():
    return _dispatch_deleted_path(changed, item, today)

  # a document basename resolves to the folder-note that owns it, by where the document lies;
  # every other match IS the folder-note the routine's own `any_of` member selected
  repo_root = flip_gate.repo_root(changed.parent)
  is_document = spec_doc_types.is_ladder_document(changed) or changed.name in LevelDoc.BASENAMES
  owner = _resolve_owner_note(repo_root, changed) if is_document else changed

  # guard: no folder-note owns this path (a bare folder, or a race with a deletion) — nothing
  # this worker tracks a coordinator job against
  if not owner.is_file():
    return { TickAction.ACTION: TickAction.NOOP }

  # the owner's own role picks the ladder: an asset's status note runs the asset one, a product's
  # or the catalog root's level note the level one, and a note carrying neither is nobody's object
  frontmatter, _ = flip_gate.parse_frontmatter(owner.read_text(encoding = "utf-8"))
  role = frontmatter.get(SpecKey.ROLE)

  # guard: a note carrying no coordination role is nobody's object
  if role != _SPEC_ROLE_STATUS and role not in LEVEL_ROLES:
    return { TickAction.ACTION: TickAction.NOOP }

  # guard: a document belonging to the OTHER ladder is not one this note tracks — the level set
  # and the asset predicate overlap on `design.md` / `tech.md`, so the union that found the owner
  # must be narrowed by the owner's own role here (a level note's basenames, the asset predicate
  # otherwise)
  if is_document and not spec_doc_types.is_ladder_document(
      changed, LevelDoc.BASENAMES if role in LEVEL_ROLES else None):
    return { TickAction.ACTION: TickAction.NOOP }

  # the changed document, when the tick named one rather than the note itself
  doc = changed if is_document else None
  if role == _SPEC_ROLE_STATUS:
    return coordinator_dispatch(owner, item, today = today, sibling_doc = doc)
  return coordinator_dispatch(owner, item, today = today, level_doc = doc)


def main(argv: list[str]) -> int:
  """
  Run one coordinator-dispatch tick from the command line, printing the result as JSON.

  Invoked by the `lazy-spec.coordinator-watch` git-watch routine as `coordinator-dispatch
  <item-json>` — one call per tick under the routine's default `group: "all"`, per
  `routine_types.dispatch_git`'s `command:` sub-shape (`[*resolved_cmd, json.dumps(item)]`,
  spawned with `cwd = repo`). The item carries one of two shapes: a grouped
  `{dir, paths, sha, author_name, author_email}` item names a directory — the repo root (`.`)
  by default, a matched directory under a consumer's own `group: "dir"` or glob list — and
  every one of its changed members at once. Each member climbs from its own folder to the
  group's dir looking for the nearest status folder-note; a member an owner is found for joins
  that owner's one dispatch, keyed to the last commit touching that owner's own dir rather than
  the range tip the item names (which may be another asset's commit), and a member no status
  note owns — a product's or the catalog root's own level document, a bare group folder's
  own note, or a file of an asset folder deleted whole (its status note deleted too), which wakes
  the owning product's level note — is instead dispatched one by one through the same route a
  single-file item takes.
  A group where every member falls into neither bucket (the item's `paths` holds no usable
  string entry) is skipped. A dispatch that raises does not stop the tick: the rest of the
  owners and orphans still run, and the worker then prints `{"failed_paths": [...]}` — the
  failed owners' members and the failed orphans — as the LAST stdout line and exits 1, so the
  daemon retries only those paths. Otherwise (`group: "file"`) the routine's `filter.any_of` matches
  a single changed file, either a status folder-note (`spec_role: status`) OR an authored
  document carrying a non-null `spec_doc_type` — `item["path"]` names whichever one matched. A
  sibling-doc item is resolved to its OWNING asset's status folder-note (the Obsidian
  folder-note convention, `<dir>/<dir>.md`) before dispatch; a document lying directly in a
  product's spec path (a product-root `tech.md` / loose `design.md`) or in the content root
  resolves to that product's, or the catalog root's, level note and runs the level ladder. Only
  a document no coordinated note owns is skipped.

  A document parked at `spec_stage: deferred` is dispatched on like any other changed path — the
  owning note still needs its gates, brief, and launch rows put in order. What a parked document
  never does is carry a `review_result` transition, so a bot-authored commit landing nothing
  but its verdict reaches no trigger at all.

  Guarantees:
    - When at least one owner or orphan dispatch raised, the last stdout line is a JSON object
      whose `failed_paths` names exactly the failed member paths, and the exit code is 1.

  Args:
    argv: Command-line arguments, excluding the program name — the item JSON as the one positional argument,
      an optional `--today <date>` pinning the ISO date into the emitted history line, and an optional
      `--release-start <note path>`, with which the item JSON is not read at all.

  Returns:
    Exit code. With `--release-start` the release's status note is woken with the release-start trigger, the
    dispatch result is printed as one JSON line, and the exit code is 0 whatever that result says, a refused
    dispatch included. Without it: 2 when the item JSON is malformed or carries neither a usable `dir` nor a usable
    `path`; 1 when at least one owner's or orphan's dispatch of a grouped item raised (the
    `failed_paths` line printed last); 0 on every other path. A path that no longer exists wakes
    the note that still owns its place — the asset's status note, or the owning product's level
    note when the asset folder is gone too — and is a noop only when the deletion is bot-authored
    or no note owns it; a path resolving to a doc this worker never tracks a coordinator job
    against is a noop as well.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs coordinator-dispatch")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("item_json", type = str, nargs = "?", default = "")
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--today", default = None,
                      # waiver: one-off human-facing message -- argparse help text
                      help = "ISO date pinned into the emitted history line")
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--release-start", default = "",
                      # waiver: one-off human-facing message -- argparse help text
                      help = "a release's status note to wake with the release-start trigger, no git item")
  args = parser.parse_args(argv)

  # the downward release-start hop names a note and carries no git item at all
  if args.release_start:
    print(json.dumps(coordinator_dispatch(
        (Path.cwd() / args.release_start).resolve(), {}, today = args.today, release_start = True,
    )))
    return 0

  # parse the git-watch item and pull out the changed file's path
  try:
    item = json.loads(args.item_json)
  except json.JSONDecodeError:
    sys.stderr.write(f"malformed git-watch item JSON: {args.item_json!r}\n")
    return 2
  raw_dir = item.get(_ITEM_DIR) if isinstance(item, dict) else None

  # a grouped `{dir, paths, ...}` item is split by owner — each member path climbs to the
  # nearest status folder-note at or below the group's dir — and every owner gets one dispatch
  # over its own members; the single-file `path` form below arrives only from a routine that
  # declared `group: "file"`
  if isinstance(raw_dir, str) and raw_dir:
    group_dir = (Path.cwd() / raw_dir).resolve()
    raw_paths = item.get(_ITEM_PATHS, [])
    owners = _split_group_by_owner(group_dir, raw_paths)

    # a member with no status note over it — a product's or the catalog root's own level
    # document, a bare group folder's note, or a file of an asset folder deleted whole — is
    # dispatched as the single-file item it would have been ungrouped
    orphans = _orphan_members(group_dir, raw_paths)

    # guard: the item names no usable member path at all — nothing this worker tracks a
    # coordinator job against
    if not owners and not orphans:
      print(json.dumps({ TickAction.ACTION: TickAction.NOOP }))
      return 0

    # the member paths whose dispatch raised — the daemon's retry unit narrows to exactly these
    failed_paths: list[str] = []
    for asset_note, members in owners.items():
      # the owner's own narrowed item: its dir, its members only, and the commit fields re-keyed to
      # the last commit touching ITS dir — the group's fields name the range tip, which may be
      # another asset's operator commit and would otherwise fire operator-edit on this one
      owner_dir = _to_rel_path(Path.cwd(), asset_note.parent)
      owner_paths = [ _to_rel_path(Path.cwd(), member) for member in members ]
      owner_item = _rekey_to_own_commit(
          Path.cwd(), { **item, _ITEM_DIR: owner_dir, _ITEM_PATHS: owner_paths }, owner_dir,
      )

      # the status note itself is never one of its own sibling members
      siblings = [ member for member in members if member != asset_note ]
      try:
        result = coordinator_dispatch(asset_note, owner_item, today = args.today, group_members = siblings)
      # waiver: the tick's per-owner error boundary — one broken asset must not stop the rest
      except Exception as error:
        sys.stderr.write(f"coordinator-dispatch: {owner_item[_ITEM_DIR]}: {error!r}\n")
        failed_paths.extend(owner_paths)
        continue
      print(json.dumps(result))

    # the orphans go one by one through the single-path route, under the same error boundary
    for orphan in orphans:
      # the orphan's own repo-relative path replaces the group's member list on the item it is
      # dispatched with: the buried-operator-commit rescue reads `path` and never `paths`, so
      # the raw grouped item would leave it with no history to scan and no operator edit to find
      orphan_path = _to_rel_path(Path.cwd(), orphan)
      orphan_item = _rekey_to_own_commit(Path.cwd(), { **item, _ITEM_PATH: orphan_path }, orphan_path)
      try:
        result = _dispatch_single_path(orphan, orphan_item, args.today)
      # waiver: the tick's per-orphan error boundary — one broken document must not stop the rest
      except Exception as error:
        sys.stderr.write(f"coordinator-dispatch: {orphan_path}: {error!r}\n")
        failed_paths.append(orphan_path)
        continue
      print(json.dumps(result))

    # every dispatch ran clean — nothing for the daemon to retry
    if not failed_paths:
      return 0

    # Contract:
    # When at least one owner or orphan dispatch raised, the LAST line on stdout is a JSON
    # object whose `failed_paths` names exactly the member paths that failed, and the exit
    # code is 1; the daemon narrows its retry to those paths.

    # the partial-failure line the daemon reads: LAST on stdout, paired with a non-zero exit
    print(json.dumps({ _FAILED_PATHS: failed_paths }))
    return 1

  # the single-file `changed_files` form — the routine's other `any_of` member
  raw_path = item.get(_ITEM_PATH) if isinstance(item, dict) else None

  # guard: neither shape a git-watch item takes carries anything to dispatch on
  if not isinstance(raw_path, str) or not raw_path:
    sys.stderr.write(f"git-watch item carries no {_ITEM_DIR!r} or {_ITEM_PATH!r}: {item!r}\n")
    return 2

  # the daemon spawns this command with cwd = repo root (routine_types.dispatch_git), so a
  # relative item path resolves against the current directory
  changed = (Path.cwd() / raw_path).resolve()

  # print the tick's result as JSON on stdout, where the daemon reads it
  print(json.dumps(_dispatch_single_path(changed, item, args.today)))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
