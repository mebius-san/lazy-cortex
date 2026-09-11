"""
Coordinator wake-trigger worker for the `lazy-spec.coordinator-watch` git-watch routine.

Invoked once per changed markdown file under the spec content root, via a `type: git`,
`watch: changed_files` routine (`lazycortex-core`'s own file-level git-watch — see
`routine_types._compute_git_items`) rather than a periodic directory scan. The daemon
resolves each item to a `(path, status, sha, author_name, author_email)` dict and passes it
as one JSON argv; a non-bot commit reaching this checkout IS trigger 1 (`operator-edit`) —
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

A second item shape reaches this worker when several of an asset's own paths (its status note
and/or any number of its sibling docs) changed in the same range: a grouped
`{dir, paths, sha, author_name, author_email}` item naming the asset directory and every changed
member at once, rather than one item per file. It resolves to the SAME owning asset's status
folder-note and dispatches at most one coordinator job per tick regardless of how many members
changed, honoring the same trigger priority as the single-file form (COMMAND, halt, ANSWER,
JOB_DONE, DOC_TRANSITION, OPERATOR_EDIT) but scanning every member for a `review_result`
transition in one pass instead of one file at a time, and reading OPERATOR_EDIT off the group's
own last commit (the item's own `sha`/`author_email`) rather than a single file's.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

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
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import asset_types  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import flip_gate  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import gate_dispatch  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import gate_tick  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import iconize_inline  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_explainers  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import note_ops  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import resolve_product  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_doc_types  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_job_markers  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_keys import (  # noqa: E402
    LEVEL_ROLES,
    AnsweredQuestionKey,
    CoordinatorTrigger,
    Gate,
    JobMarker,
    LevelDoc,
    Section,
    SpecCoordinatorDocStateKey,
    SpecCoordinatorReadyStateKey,
    SpecDependsOnKey,
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

# The guideline role folded into context via `gate_dispatch._collect_guideline_context`, per
# `lazy-spec.coordination-playbook.md` § 2 layer 3 (`products[<key>].guidelines.coordinator` + `"*"`).
_COORDINATOR_ROLE = "coordinator"

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

# Mirrored `spec_source_requests` frontmatter key from `apply_request.py`'s own `_K` class,
# duplicated here rather than imported per this bin/ tree's own per-file small-constant
# convention (see `gate_tick._write_fm_list`'s docstring).
_SPEC_SOURCE_REQUESTS = "spec_source_requests"

# Bundle wire key naming the protocol references `lazycortex-core dispatch-job` unions with the
# dispatching routine's own, duplicated here per this bin/ tree's own per-file small-constant
# convention — `gate_dispatch._WireKey` predates the level branch, the only sender of this key.
_WIRE_PROTOCOLS = "protocols"

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
# below and never wakes the ANSWER trigger (4a debt — see that function's docstring).
_QUESTION_ATTRIBUTION = "> — spec.coordinator"

# The same attribution line for the level persona, and the closed set of both. A level note's
# questions are signed by the catalog coordinator, so an ANSWER on one would never match the
# asset persona's line; membership in this two-element set is what lets one ladder serve both,
# and an expert- or operator-authored `[!question]` still matches neither.
_CATALOG_QUESTION_ATTRIBUTION = f"> — {_CATALOG_EXPERT}"
_QUESTION_ATTRIBUTIONS = frozenset({ _QUESTION_ATTRIBUTION, _CATALOG_QUESTION_ATTRIBUTION })

# ATX heading boundary, mirroring `flip_gate._append_under_heading`'s own section-end rule.
_HEADING_RE = re.compile(r"^#{1,6}\s")

# HTML comment span — strips the shipped `<!-- ... -->` placeholder before the emptiness test,
# so a section that still carries only the scaffolded instruction comment reads as empty.
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

# Self-suppression substring — any commit author whose email contains this never counts as
# operator activity (`lazy-spec.coordination-playbook.md` § 1).
_BOT_MARK = "@bot."

# Wire keys on a `changed_files` git-watch item (`routine_types._compute_git_items`).
_ITEM_PATH = "path"
_ITEM_AUTHOR_EMAIL = "author_email"
_ITEM_SHA = "sha"

# Additional wire keys on a grouped git-watch item (`routine_types._group_git_items`) — `dir`
# replaces `_ITEM_PATH` as the item's own subject, `paths` names every changed member under it.
_ITEM_DIR = "dir"
_ITEM_PATHS = "paths"

# `spec_role` value naming an asset's own status folder-note — the only folder-note shape a
# sibling doc's owning `<dir>/<dir>.md` may resolve to; a product-root sibling doc (`tech.md`,
# a loose `design.md`) resolves the same convention to an operator-zone folder-note that never
# carries this value, which is exactly how `main` tells the two apart.
_SPEC_ROLE_STATUS = "status"

# Bounded lookback window for `_has_operator_authored_recently`'s bot-buried-operator-commit
# rescue (N3) — see that function's docstring for why this is a fixed window, not a range scan.
_AUTHOR_LOOKBACK_COMMITS = 10

# The two frontmatter keys the busy-guard used to stamp before the sidecar-declined migration —
# their bare string values, duplicated here per this bin/ tree's own per-file small-constant
# convention (`_SPEC_SOURCE_REQUESTS` above), since `PendingEditKey` / `SpecCoordinatorPendingDocKey`
# no longer exist in `spec_keys.py` once every writer of them retired. Read-only here: an old
# install's note still carrying either is treated as a declined-wake for one tick and the keys
# are stripped (`_strip_legacy_pending`), never re-written.
_LEGACY_PENDING_EDIT_KEY = "spec_coordinator_pending_edit"
_LEGACY_PENDING_DOC_KEY = "spec_coordinator_pending_doc"


def _read_section_body(body: str, heading: str) -> str:
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
  if section_lines and section_lines[0].strip() == note_ops._PROTECTED_MARKERS.get(heading):
    section_lines = section_lines[1:]

  # drop the section's own explainer line the same way — self-description, never operator content
  if section_lines and note_explainers.EXPLAINER_LINE_RE.match(section_lines[0]):
    section_lines = section_lines[1:]

  # strip HTML comments before the emptiness test — the shipped template placeholder is one,
  # and it must never read as operator-authored content
  raw = "\n".join(section_lines)
  return _HTML_COMMENT_RE.sub("", raw).strip()


def _is_attributed_ticked_block(ticked: bool, block_lines: list[str]) -> bool:
  """
  Check whether a candidate `[!question]` block is both ticked and the coordinator's own.

  A ticked block whose last NON-EMPTY quoted line does not match `_QUESTION_ATTRIBUTION`
  (trimmed compare) is a foreign — expert-authored or otherwise non-coordinator — question that
  happens to carry a ticked option; it must never be mistaken for an answer to one of the
  coordinator's own questions (4a debt: the ANSWER trigger used to wake on ANY ticked
  `[!question]`, regardless of who wrote it). Skipping past trailing empty quoted lines (a bare
  `>` continuation after the attribution) matters — comparing `block_lines[-1]` directly would
  silently defeat a genuine match the moment one of those trails the attribution (fix-round-1).

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

  # guard: an unticked block never reaches ANSWER regardless of attribution
  if not ticked:
    return False
  # scan backward past any trailing blank quoted line (bare `>`) to the last substantive one
  for line in reversed(block_lines):
    stripped = line.strip()
    # guard: a blank quote continuation carries no content to compare — keep scanning back
    if stripped == ">":
      continue
    return stripped in _QUESTION_ATTRIBUTIONS
  return False


def _find_ticked_question_block(body: str) -> str | None:
  """
  Locate the first coordinator-attributed `[!question]` callout in `body` carrying a ticked
  `- [x]` option.

  A ticked block that does NOT end in the coordinator's own `_QUESTION_ATTRIBUTION` line is
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

    # guard: not currently inside a question block — nothing to check on this line
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
  # guard: the body ended while still inside an attributed-ticked block (no trailing heading)
  if in_block and _is_attributed_ticked_block(ticked, block_lines):
    return "\n".join(block_lines)
  return None


def _compute_answer_fingerprint(block: str) -> str:
  """
  Compute a content fingerprint for a ticked `[!question]` block.

  A content hash rather than a commit sha — `model-audit.md` I-A: a sha-valued marker can name a
  commit the daemon later rewrites or destroys on a push conflict, permanently losing the
  marker's meaning; a content hash keeps meaning whatever commit currently carries this text.

  Args:
    block: The ticked question block's raw text, as returned by `_find_ticked_question_block`.

  Returns:
    A hex digest identifying this exact block content.
  """
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

  # guard: the item's own author is already non-bot — nothing further to check
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
        cwd = str(repo_root), capture_output = True, text = True, check = False,
    )
    if ranged.returncode == 0:
      return any(_BOT_MARK not in email for email in ranged.stdout.splitlines())

  # no usable cursor: a fixed-size window of the path's own recent authors, ending at the
  # item's reported tip.
  # limit: this fallback misses the operator commit when more than `_AUTHOR_LOOKBACK_COMMITS`
  # bot commits land on the same path between pulls; the cursor path above is the upgrade and
  # takes over the moment the first dispatch stamps it
  out = subprocess.run(
      ["git", "log", "--format=%ae", "-n", str(_AUTHOR_LOOKBACK_COMMITS), sha, "--", path],
      cwd = str(repo_root), capture_output = True, text = True, check = False,
  ).stdout
  for email in out.splitlines():
    if _BOT_MARK not in email:
      return True
    # guard: this worker's own historic wake commit proves everything older was already
    # dispatched on — the worker no longer writes such commits, but pre-cursor installs still
    # carry them, and they keep bounding the window until a cursor is stamped
    if email == _DISPATCH_AUTHOR_EMAIL:
      return False
  return False


def _cursor_store_path(repo_root: Path) -> Path:
  """
  Return the path of this worker's dispatch-cursor store.

  Args:
    repo_root: Repository root holding the gitignored `.runtime/` directory.

  Returns:
    Absolute path of `<repo>/.runtime/lazy-specs.dispatch-cursors.json`, whether or not it
    exists.
  """
  return spec_job_markers.sidecar_path(repo_root).parent / _CURSOR_SIDECAR


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
  # an absent or unreadable store is the "nothing recorded yet" answer, never a failure
  try:
    data = json.loads(_cursor_store_path(repo_root).read_text())
  except (OSError, json.JSONDecodeError):
    return None

  # guard: a non-object store (hand-mangled scratch) reads as "nothing recorded"
  if not isinstance(data, dict):
    return None

  # only a non-empty string is a usable sha bound
  value = data.get(spec_job_markers.note_key(repo_root, asset_note))
  return value if isinstance(value, str) and value else None


def _stamp_dispatch_cursor(repo_root: Path, asset_note: Path, sha: object) -> None:
  """
  Record the item sha this tick dispatched on, so later lookbacks scan only past it.

  Args:
    repo_root: Repository root holding the cursor store.
    asset_note: The asset status folder-note the cursor belongs to.
    sha: The handled item's commit sha; a falsy or non-string value (a synthetic
      dependency-ready wake carries no commit) records nothing.
  """
  # guard: a synthetic wake has no commit to bound a later lookback with
  if not isinstance(sha, str) or not sha:
    return

  # an absent or unreadable store starts empty — it is runtime scratch and re-derives itself
  path = _cursor_store_path(repo_root)
  try:
    data = json.loads(path.read_text())
  except (OSError, json.JSONDecodeError):
    data = {}

  # guard: a non-object store is scratch — rebuild it rather than crash the tick
  if not isinstance(data, dict):
    data = {}

  # write beside the target and rename over it, so a reader never observes a half-written store
  data[spec_job_markers.note_key(repo_root, asset_note)] = sha
  path.parent.mkdir(parents = True, exist_ok = True)
  tmp = path.with_suffix(path.suffix + _CURSOR_TMP_SUFFIX)
  tmp.write_text(json.dumps(data, indent = 2, sort_keys = True) + "\n")
  os.replace(tmp, path)


def _read_marker_dict(fm: dict, key: str) -> dict:
  """
  Parse a worker-internal key→value JSON-dict marker off the asset note's frontmatter.

  Best-effort, mirroring the other worker-internal markers (`_find_ticked_question_block` and
  friends) — a missing or malformed marker reads as "nothing recorded yet" rather than raising,
  since these keys are never operator- or persona-authored (`SpecCoordinatorDocStateKey` /
  `SpecCoordinatorReadyStateKey`, keyed by sibling-doc basename and gate name respectively).

  Args:
    fm: The asset status folder-note's parsed frontmatter.
    key: The frontmatter key to read.

  Returns:
    The parsed dict, or `{}` when the key is absent, not valid JSON, or not a JSON object.
  """
  raw = fm.get(key)
  # guard: no marker recorded yet
  if not raw:
    return {}
  try:
    parsed = json.loads(raw)
  except json.JSONDecodeError:
    return {}
  return parsed if isinstance(parsed, dict) else {}


def _read_doc_state(fm: dict) -> dict:
  """
  Parse the asset note's `spec_coordinator_doc_state` marker into a basename→value dict.

  Args:
    fm: The asset status folder-note's parsed frontmatter.

  Returns:
    The parsed dict, or `{}` when the key is absent, not valid JSON, or not a JSON object.
  """
  return _read_marker_dict(fm, SpecCoordinatorDocStateKey.STATE)


def _is_tracked_document(path: Path, basenames: frozenset[str] | None = None) -> bool:
  """
  Check whether one changed path is a document the woken note's own ladder tracks.

  The level ladder owns a closed set of four filenames, so a level caller names it. The asset
  ladder owns none: `lazy-spec.layout-protocol.md` gives an authored document's basename no
  semantics, and the `lazy-spec.coordinator-watch` routine's own second `filter.any_of` member
  selects on the PRESENCE of a non-null `spec_doc_type` rather than on any filename list.
  Mirroring that predicate here is what lets an asset's freely-named typed document reach
  `_resolve_doc_transition`; a typed document with nothing to transition is harmless there, so
  the predicate never needs to know which kinds are review-tracked.

  Args:
    path: The changed path to classify.
    basenames: The level ladder's closed document set, on a level note; None on an asset, where
      the `spec_doc_type` predicate decides instead.

  Returns:
    True when `path` is a file this ladder tracks as one of its documents; False when the path
    is gone between scan and dispatch, is its own folder's note, or carries no document type.
  """
  # guard: a path gone between scan and dispatch is no document on either ladder
  if not path.is_file():
    return False

  # the level ladder's membership is the closed set and nothing else
  if basenames is not None:
    return path.name in basenames

  # guard: an expert's non-markdown attachment carries no frontmatter to read, and a folder's own
  # note is the coordination object rather than one of its documents
  # waiver: markdown-suffix literal, single-source alongside every other ".md" folder-note
  # literal in this module
  if path.suffix != ".md" or path.name == f"{path.parent.name}.md":
    return False

  # the asset ladder's membership is the routine's own predicate, read off the file
  return bool(spec_doc_types.doc_type_of(path))


def _resolve_doc_transition(sibling_doc: Path, fm: dict) -> tuple[str, str] | None:
  """
  Detect a `review_result` transition on one sibling doc against the asset note's own marker.

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
    fm: The owning asset's status folder-note frontmatter, carrying the previously-recorded
      marker (`spec_keys.SpecCoordinatorDocStateKey.STATE`), if any.

  Returns:
    `(basename, new_value)` when the sibling's current `review_result` differs from the recorded
    marker — including `(basename, "")` when a recorded result was cleared; `None` when the
    sibling is parked, has never carried a result, or matches the marker.
  """
  basename = sibling_doc.name
  sibling_fm, _ = flip_gate._parse_frontmatter(sibling_doc.read_text())
  # guard: a parked document's verdict transitions nothing until it returns to `draft`
  if str(sibling_fm.get(StageKey.STAGE, "")).strip() == Stage.DEFERRED:
    return None
  current = sibling_fm.get(SpecKey.REVIEW_RESULT)
  previous = _read_doc_state(fm).get(basename)
  # guard: no result now and none ever recorded — nothing has transitioned in either direction
  if current is None and not previous:
    return None
  # a cleared result is the document re-entering review: recorded as the empty token, so the
  # next terminal value — even the same one as before — differs from the marker and re-fires
  if current is None:
    return basename, SpecCoordinatorDocStateKey.REVIEW_REOPENED
  # guard: identical to what this worker already dispatched on — a re-tick, not a transition
  if current == previous:
    return None
  return basename, current


def _is_member_signal_eligible(member: Path) -> bool:
  """
  Check whether one changed sibling counts as an operator-edit signal.

  A sibling under active review (`review_active: true`) is the review loop's own business — an
  operator's edit there must not wake the spec coordinator until the review ends, the moment
  `CoordinatorTrigger.DOC_TRANSITION` already covers (operator decision 2026-08-15). A member
  gone between scan and dispatch carries no signal either way.

  Args:
    member: One changed sibling-doc path.

  Returns:
    True when `member` is a file on disk whose frontmatter does NOT carry `review_active: true`;
    False when the member is missing, or is under active review.
  """
  # guard: a member gone between scan and dispatch carries no signal
  if not member.is_file():
    return False
  fm, _ = flip_gate._parse_frontmatter(member.read_text())
  return not flip_gate._is_true(fm, SpecKey.REVIEW_ACTIVE)


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


def _resolve_wake_trigger(
    repo_root: Path, fm: dict, body: str, item: dict, markers: dict, cursor: str | None,
) -> str | None:
  """
  Resolve the wake trigger for this tick, honoring the halt override.

  Args:
    repo_root: The repository root to run `git` in.
    fm: The folder-note's parsed frontmatter.
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
  if _read_section_body(body, Section.COORD_COMMANDS):
    return CoordinatorTrigger.COMMAND

  # guard: halt silences every other trigger
  if flip_gate._is_true(fm, SpecHaltKey.HALTED):
    return None

  # a ticked question re-fires only when its content differs from the fingerprint stamped the
  # last time this worker dispatched on it (I1/I-D: retires the trigger so a destroyed removal
  # commit — the coordinator's own — can't resurrect an infinite re-dispatch loop)
  ticked_block = _find_ticked_question_block(body)
  if ticked_block is not None:
    if fm.get(AnsweredQuestionKey.FINGERPRINT) != _compute_answer_fingerprint(ticked_block):
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
  # guard: neither the item's own author nor a recent bot-buried one was the operator
  if not _has_operator_authored_recently(repo_root, item, cursor):
    return None
  return CoordinatorTrigger.OPERATOR_EDIT


def _resolve_group_trigger(
    repo_root: Path, fm: dict, body: str, item: dict, markers: dict, members: list[Path],
    asset_note: Path, cursor: str | None,
) -> tuple[str | None, dict[str, str]]:
  """
  Resolve the wake trigger for a grouped git-watch item, honoring the halt override.

  Mirrors `_resolve_wake_trigger`'s priority ladder (COMMAND, halt, ANSWER, JOB_DONE,
  OPERATOR_EDIT), replacing its single-sibling `sibling_doc` reasoning with one pass over every
  member path: every member resolving to a genuine `review_result` transition is collected
  (basename -> new value) rather than stopping at the first, so DOC_TRANSITION fires with the
  full set a caller can stamp in one go — no transition is dropped to a later tick just because
  another member's transition also fired this same tick.

  Args:
    repo_root: The repository root to run `git` in.
    fm: The asset status folder-note's parsed frontmatter.
    body: The folder-note section text (after frontmatter).
    item: The grouped git-watch item (`dir`, `paths`, `sha`, `author_name`, `author_email`).
    markers: The note's runtime marker entry, from `spec_job_markers.read`.
    members: The group's sibling-doc member paths, excluding the status note itself.
    asset_note: The asset's own status folder-note path — used only to tell whether the note
      itself is one of `item["paths"]`'s changed members (`_has_group_note_changed`), for the
      OPERATOR_EDIT arm's review-active carve-out below.
    cursor: The note's dispatch cursor, from `_read_dispatch_cursor` — bounds the
      operator-author lookback.

  Returns:
    A `(trigger, transitions)` pair. `trigger` is a `CoordinatorTrigger` token, or None when
    nothing wakes the coordinator this tick. `transitions` maps every sibling basename that
    transitioned to its new `review_result` value; non-empty only when `trigger` is
    `CoordinatorTrigger.DOC_TRANSITION`.
  """
  # a non-empty commands section wakes the coordinator even on a halted asset — the same
  # exception `_resolve_wake_trigger` grants the single-file form
  if _read_section_body(body, Section.COORD_COMMANDS):
    return CoordinatorTrigger.COMMAND, {}

  # guard: halt silences every other trigger
  if flip_gate._is_true(fm, SpecHaltKey.HALTED):
    return None, {}

  # a ticked question re-fires only when its content differs from the fingerprint stamped the
  # last time this worker dispatched on it
  ticked_block = _find_ticked_question_block(body)
  if ticked_block is not None:
    if fm.get(AnsweredQuestionKey.FINGERPRINT) != _compute_answer_fingerprint(ticked_block):
      return CoordinatorTrigger.ANSWER, {}

  # a launch-checkbox job finishing wakes the coordinator whoever authored this tick's commit
  if markers.get(JobMarker.PENDING_WAKE) == JobMarker.JOB_DONE:
    return CoordinatorTrigger.JOB_DONE, {}

  # one pass over every member — every transition found is kept, not just the first
  transitions: dict[str, str] = {}
  for member in members:
    # guard: a member gone between scan and dispatch, or carrying no document type, is skipped
    # silently rather than failing the whole group resolution
    if not _is_tracked_document(member):
      continue
    resolved = _resolve_doc_transition(member, fm)
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
  # guard: nothing in this grouped tick could ever count as an operator-edit signal
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
  # guard: neither the item's own author nor a recent bot-buried one on the group's dir was the
  # operator
  if not _has_operator_authored_recently(repo_root, dir_item, cursor):
    return None, {}
  return CoordinatorTrigger.OPERATOR_EDIT, {}


def _resolve_level_trigger(
    repo_root: Path, fm: dict, body: str, item: dict, members: list[Path], cursor: str | None,
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
    fm: The level note's parsed frontmatter.
    body: The level note's section text (after frontmatter).
    item: The git-watch item for this tick.
    members: The level documents this tick names — the one changed document, every existing one
      when a declined wake is being redeemed, or empty when the tick named the note itself.
    cursor: The note's dispatch cursor, bounding the operator-author lookback.

  Returns:
    A `(trigger, transitions)` pair. `trigger` is a `CoordinatorTrigger` token, or None when
    nothing wakes the coordinator this tick. `transitions` maps every level-document basename
    that transitioned to its new `review_result` value; non-empty only when `trigger` is
    `CoordinatorTrigger.DOC_TRANSITION`.
  """
  # a non-empty commands section wakes the coordinator even on a halted level, the same
  # exception both asset-side resolvers grant
  if _read_section_body(body, Section.COORD_COMMANDS):
    return CoordinatorTrigger.COMMAND, {}

  # guard: halt silences every other trigger
  if flip_gate._is_true(fm, SpecHaltKey.HALTED):
    return None, {}

  # a ticked question re-fires only when its content differs from the stamped fingerprint
  ticked_block = _find_ticked_question_block(body)
  if ticked_block is not None:
    if fm.get(AnsweredQuestionKey.FINGERPRINT) != _compute_answer_fingerprint(ticked_block):
      return CoordinatorTrigger.ANSWER, {}

  # one pass over every named level document — every transition found is kept, not just the first
  transitions: dict[str, str] = {}
  for member in members:
    # guard: a document gone between scan and dispatch, or not part of the level ladder, carries
    # no transition to read
    if not member.is_file() or member.name not in LevelDoc.BASENAMES:
      continue
    resolved = _resolve_doc_transition(member, fm)
    if resolved is not None:
      basename, value = resolved
      transitions[basename] = value
  if transitions:
    return CoordinatorTrigger.DOC_TRANSITION, transitions

  # guard: a document-only tick whose every document is under active review is the review loop's
  # business, not an operator-edit signal — the note's own tick (no members) always checks
  if members and not any(_is_member_signal_eligible(member) for member in members):
    return None, {}

  # guard: neither the item's own author nor a recent bot-buried one was the operator
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


def _scan_dependents(asset_dir: Path) -> list[Path]:
  """
  Find every OTHER asset's status folder-note in the product tree whose `spec_depends_on`
  names `asset_dir` (C2's reverse edge — nothing else ever wakes a dependent asset when the
  dependency it is waiting on becomes ready).

  One hop only, and resolved through `gate_tick._target_asset_dir` — the same primitive
  `_build_bundle`'s own `spec_depends_on` fold-in uses — rather than a bare string compare, so
  any token spelling that fold-in already accepts also wakes the dependent here. The category
  enumeration mirrors the product's own built-in/`asset_types` folder walk used elsewhere
  in this module.

  Args:
    asset_dir: The asset folder that just woke — the dependency other assets may declare.

  Returns:
    Every matching asset's status folder-note path, in directory-scan order.
  """
  # limit: reads and frontmatter-parses every asset note in the product on every call — correct
  # at current product sizes and cheap next to the coordinator LLM dispatch it precedes; upgrade
  # path is a repo-root reverse-dependency index (built once, invalidated on spec_depends_on
  # writes) once a product's asset count makes the per-wake scan itself a measurable cost (N9)
  product_root = asset_dir.parent.parent
  hits: list[Path] = []
  # guard: no product tree above this asset — nothing to scan
  if not product_root.is_dir():
    return hits
  for cat_dir in sorted(p for p in product_root.iterdir() if p.is_dir()):
    for candidate_dir in sorted(p for p in cat_dir.iterdir() if p.is_dir()):
      # guard: never wake the asset that just woke off its own dependency list
      if candidate_dir == asset_dir:
        continue
      candidate_note = candidate_dir / f"{candidate_dir.name}.md"
      # guard: no status folder-note here — not a real asset
      if not candidate_note.is_file():
        continue
      text = candidate_note.read_text()
      _, fm_end = flip_gate._parse_frontmatter(text)
      for token in gate_tick._read_fm_list(text[:fm_end], SpecDependsOnKey.DEPENDS_ON):
        if gate_tick._target_asset_dir(candidate_dir, token) == asset_dir:
          hits.append(candidate_note)
          break
  return hits


def _wake_ready_dependents(asset_dir: Path, my_token: str, *, today: str | None) -> None:
  """
  Dispatch a `DEPENDENCY_READY` job on every OTHER asset that names this one in its own
  `spec_depends_on`.

  Best-effort: one dependent's failure is caught and logged rather than propagated, so it can
  never strand this asset's own already-committed dispatch (N2).

  Notes:
    - The caller invokes this only after its own dispatch has already landed, never before.

  Args:
    asset_dir: The asset folder whose readiness gate just crossed to true.
    my_token: This asset's own `<category>/<slug>` token, folded into each dependent's
      `payload["dep"]`.
    today: Optional ISO date forwarded into each dependent's own `# History` line.
  """

  # Domain(spec.lifecycle):
  # # Downstream wake on dependency and release crossings
  # When an asset's own readiness advances far enough that something else waiting on it could
  # now proceed, every asset that names this one as a dependency is woken to check again, so a
  # chain of related work never sits idle only because nothing prompted a second look.
  # Separately, when an asset finishes and is released, the product that contains it is woken
  # once, so a product-level view stays current without polling every asset inside it. Both
  # notifications travel exactly one hop outward from the asset that changed — never chased
  # further downstream from there — and only fire once the asset's own change has safely landed,
  # so a failure telling a neighbour can never undo or block the change that caused it.

  for dependent_note in _scan_dependents(asset_dir):
    try:
      coordinator_dispatch(dependent_note, {}, today = today, dependency_wake = my_token)
    # limit: stderr-only per the `gate_dispatch.consume_stale_job` §5 fire-and-forget precedent
    # in this same plugin; error-ledger route blocked: the closed cause-set spec
    # (docs/specs/lazy-core.errors.functional-spec.md) is absent from this repo — upgrade path
    # is adding an `error-record` call with a real `--cause` once that spec lands
    except Exception as error:  # pragma: no cover — defensive, see N2
      sys.stderr.write(f"reverse-dependency wake failed for {dependent_note}: {error}\n")


def _wake_product_note(repo_root: Path, asset_dir: Path, my_token: str, *, today: str | None) -> None:
  """
  Dispatch an `ASSET_RELEASED` job on the level note of the product owning this asset.

  Best-effort like the reverse-dependency fan-out beside it: one hop, and a failure here is
  logged rather than propagated, so it can never strand the asset's own already-landed dispatch.

  Notes:
    - The caller invokes this only after its own dispatch has already landed, never before.

  Args:
    repo_root: The repository root the product records resolve under.
    asset_dir: The asset folder whose release gate just crossed to true.
    my_token: The asset's own `<category>/<slug>` token, folded into `payload["asset"]`.
    today: Optional ISO date forwarded into the level note's own `# History` line.
  """
  # the owning product, resolved from the asset's own folder rather than from any note it carries
  key, record = resolve_product.resolve_product_by_path(repo_root, _to_rel_path(repo_root, asset_dir))
  level_note = _resolve_product_note_path(repo_root, record) if key and isinstance(record, dict) else None

  # guard: an asset outside any registered product, or a product whose level note was never
  # created, has no level coordinator to wake
  if level_note is None or not level_note.is_file():
    return

  # the upward hop itself, carrying no git item of its own — the release is the whole signal
  try:
    coordinator_dispatch(level_note, {}, today = today, asset_released = my_token)
  # limit: stderr-only per the `_wake_ready_dependents` precedent beside it; error-ledger route
  # blocked by the same absent closed cause-set spec, with the same upgrade path
  except Exception as error:  # pragma: no cover — defensive, mirrors the reverse-dependency wake
    sys.stderr.write(f"asset-released wake failed for {level_note}: {error}\n")


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
  rules_rel = (gate_dispatch._load_settings(repo_root).get(_SPEC_SECTION) or {}).get(_COORD_RULES_KEY)
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
    doc_transition: str | None = None, asset_released: str | None = None,
) -> tuple[list[str], list[str], list[str], dict, str, list[str]]:
  """
  Assemble the `lazycortex-core dispatch-job` wire bundle pieces for a level-note wakeup.

  Source names the level note itself; context names the level documents that already exist, the
  vault-wide `spec.coordination_rules` doc, and one layer chosen by role — the catalog root's own
  note above a product's, every registered product's note below the catalog root's. A level note
  declares no asset type, no tools, no targets and no dependencies, so none of those is read;
  the playbook is resolved off the type registry by the note's role and rides the bundle as a
  protocol reference rather than as a copied file. The product's `coordinator` + `"*"` guidelines
  ride in the payload as paths the expert reads in place, exactly as they do for an asset.

  Args:
    repo_root: The repository root the CLI resolves settings and its own binary against.
    level_note: The level folder-note path — a product's own or the catalog root's.
    role: The note's `spec_role` value, which selects both the rules layers and the playbook.
    trigger: The `CoordinatorTrigger` token this wakeup resolved to.
    doc_transition: The level-document basename that transitioned, when `trigger` is
      `CoordinatorTrigger.DOC_TRANSITION`; folded into `payload["doc"]`. None otherwise.
    asset_released: The `<category>/<slug>` token of the asset whose release raised this wake,
      when `trigger` is `CoordinatorTrigger.ASSET_RELEASED`; folded into `payload["asset"]`.
      None otherwise.

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
    _key, record = resolve_product.resolve_product_by_path(repo_root, relative)
    product_record = record or {}
    catalog_note = _catalog_note_path(repo_root)
    if catalog_note.is_file():
      context.append(_to_rel_path(repo_root, catalog_note))
    guideline_paths, guideline_warnings = gate_dispatch._collect_guideline_paths(
        repo_root, product_record, _COORDINATOR_ROLE,
    )
    warnings.extend(guideline_warnings)
  else:
    for record in resolve_product._load_products(repo_root).values():
      # guard: a malformed product record names no note to read
      if not isinstance(record, dict):
        continue
      product_note = _resolve_product_note_path(repo_root, record)
      if product_note is not None and product_note.is_file():
        context.append(_to_rel_path(repo_root, product_note))

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
  # waiver: payload wire-key literal, same wire-schema dict as the literals above
  if product_record:
    payload["product"] = product_record
  # guidelines are named, never copied — the expert reads the real files in the tree
  if guideline_paths:
    payload[gate_dispatch._PayloadKey.GUIDELINES] = guideline_paths
  # doc field is only meaningful for a DOC_TRANSITION wake — every other trigger omits it
  # waiver: payload wire-key literal, same wire-schema dict as the literals above
  if doc_transition is not None:
    payload["doc"] = doc_transition
  # asset field is only meaningful for an ASSET_RELEASED wake — it names the released asset's
  # own token, not this note
  # waiver: payload wire-key literal, same wire-schema dict as the literals above
  if asset_released is not None:
    payload["asset"] = asset_released
  # an unresolved context path is visible to the dispatched job itself, not only to the caller
  # waiver: payload wire-key literal, same wire-schema dict as the literals above
  if warnings:
    payload["warnings"] = warnings
  # the assembled manifests, the payload, and the per-note dedup key the guard is scoped by
  return source, context, warnings, payload, f"{relative}:coordinator", protocols


def _build_bundle(
    repo_root: Path, asset_dir: Path, asset_note: Path, fm_text: str, trigger: str, *,
    doc_transition: str | None = None, dependency_ready: str | None = None,
) -> tuple[list[str], list[str], list[str], dict, str]:
  """
  Assemble the `lazycortex-core dispatch-job` wire bundle pieces for a coordinator wakeup.

  Source names the note itself; context names the owning product's folder-note, every container
  folder-note lying strictly between the product's spec-path root and the asset folder — top-down,
  so the layer closest to the asset lands last — the folders of every `spec_targets` asset, the
  folders of every `spec_depends_on` dependency asset, every `spec_source_requests` file (resolved
  via wikilink), and the vault-wide `spec.coordination_rules` doc — all as repo-relative paths the
  pump copies when it claims the job. A container folder with no folder-note of its own contributes
  nothing to context and is never a warning. The product's `coordinator` + `"*"` guidelines and the
  asset's + owning product's `decisions.md` registries (`spec-decisions-design.md` § "Coordinator")
  are never copied at all: they ride in the payload as paths the expert reads in place.
  A declared path that does not resolve to a file is never a silent drop — it becomes a
  warning string for the caller's `# History` line; a missing `decisions.md` is the one
  exception — it is created lazily by the first decision recorded into it, so its absence is
  never a warning.

  Args:
    repo_root: The repository root the CLI resolves settings and its own binary against.
    asset_dir: The asset folder holding the status folder-note.
    asset_note: The status folder-note path.
    fm_text: The folder-note's frontmatter block text (for list-typed key reads).
    trigger: The `CoordinatorTrigger` token this wakeup resolved to.
    doc_transition: The sibling-doc basename that transitioned, when `trigger` is
      `CoordinatorTrigger.DOC_TRANSITION`; folded into `payload["doc"]` so the coordinator knows
      which sibling to walk first. None for every other trigger.
    dependency_ready: The `<category>/<slug>` token of the dependency asset that just woke,
      when `trigger` is `CoordinatorTrigger.DEPENDENCY_READY`; folded into `payload["dep"]` so
      the coordinator knows which dependency to re-check. None for every other trigger.

  Returns:
    A `(source, context, warnings, payload, dedup_key)` tuple, where `source` and `context` are
    repo-relative path manifests. `payload["product"]` always
    carries the asset's owning product settings record verbatim (`{}` when the asset has none),
    so the coordinator persona reads product-level config straight off the wire instead of
    re-resolving it. `payload["guidelines"]` and `payload["decisions"]` name the files the
    expert reads in place, each omitted when nothing resolved.
    `warnings` is also folded into `payload["warnings"]` when non-empty, so an
    unresolved context path (e.g. an unresolvable `spec_depends_on` token) is visible to the
    dispatched job itself, not only the caller's own `# History` line (I11).
  """
  relative = _to_rel_path(repo_root, asset_note)

  # source is always the note itself, named by the path the pump copies at claim
  source = [ relative ]
  context: list[str] = []
  warnings: list[str] = []

  # the owning product's own folder-note, resolved the same way `gate_tick`'s dispatch pass does
  product_rel = _to_rel_path(repo_root, asset_dir)
  _key, product_record = resolve_product.resolve_product_by_path(repo_root, product_rel)
  product_record = product_record or {}
  product_note = _resolve_product_note_path(repo_root, product_record)
  if product_note is not None and product_note.is_file():
    context.append(_to_rel_path(repo_root, product_note))
  # a resolved product with a still-missing folder-note is a warning; no owning product at all
  # (product_record still `{}`) is not — there is nothing declared to have gone missing
  elif product_record:
    warnings.append(f"product folder-note not found: {product_record.get(_SPEC_PATH_KEY)}")

  # Contract:
  # Container folder-notes between the product root and the asset folder MUST reach `context`
  # top-down (shallowest first), so the group-scoped `# Coordinator rules` layer closest to the
  # asset lands last; a container without a folder-note MUST contribute no entry and no warning.

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
  # rather than the note alone, so the pump lands it under `<category>-<slug>` and two categories
  # in the same product sharing a slug (`features/x` and `bugs/x`) stay apart in the bucket (I10)
  for token in gate_tick._read_fm_list(fm_text, SpecTargetsKey.TARGETS):
    target_dir = gate_tick._target_asset_dir(asset_dir, token)
    # guard: a declared target token that resolves to no existing asset folder is a warning,
    # never a hard failure of the whole context fold-in
    if target_dir is None:
      warnings.append(f"spec_targets not found: {token}")
      continue
    context.append(_to_rel_path(repo_root, target_dir))

  # every declared spec_depends_on asset's own folder — same token shape, resolution primitive,
  # and category-qualified landing as spec_targets above, just a different frontmatter key
  for token in gate_tick._read_fm_list(fm_text, SpecDependsOnKey.DEPENDS_ON):
    dep_dir = gate_tick._target_asset_dir(asset_dir, token)
    # guard: a declared dependency token that resolves to no existing asset folder is a
    # warning, never a hard failure of the whole context fold-in
    if dep_dir is None:
      warnings.append(f"spec_depends_on not found: {token}")
      continue
    context.append(_to_rel_path(repo_root, dep_dir))

  # every declared source-request wikilink, resolved to its file
  for raw in gate_tick._read_fm_list(fm_text, _SPEC_SOURCE_REQUESTS):
    # strip the list-write quoting first, then the `|display` gloss, then the `[[...]]` brackets
    # — each layer wraps the one before it, so unwrapping out of order leaves stray characters
    pure = raw.strip().strip('"').strip("'").split("|")[0].strip("[]")
    req_path = repo_root / f"{pure}.md"
    if req_path.is_file():
      context.append(_to_rel_path(repo_root, req_path))
    else:
      warnings.append(f"source request not found: {pure}")

  # the vault-wide coordination-rules doc (lazy-spec.config-protocol.md), when configured
  rules_context, rules_warnings = _coordination_rules_context(repo_root)
  context.extend(rules_context)
  warnings.extend(rules_warnings)

  # coordinator-role + wildcard guidelines, same lookup `gate_dispatch` uses for checkbox jobs —
  # named in the payload rather than staged into the bucket, since the expert reads the real files
  guideline_paths, guideline_warnings = gate_dispatch._collect_guideline_paths(
      repo_root, product_record, _COORDINATOR_ROLE,
  )
  warnings.extend(guideline_warnings)

  # the asset's and owning product's decisions registries — named beside the guideline lookup
  # rather than folded into it, since they go to every dispatched role uniformly; a missing
  # decisions.md is normal (lazily created) and never a warning, so nothing here extends `warnings`
  decisions_paths = gate_dispatch._collect_decisions_paths(repo_root, asset_dir, product_record)

  # dedup key scoped to this asset + the coordinator's own fixed label — one coordinator job
  # per asset, regardless of which trigger woke it
  # waiver: payload wire-key literal, single-source alongside every other "payload[...]" literal
  # below — this dict IS the wire schema, not a reusable domain key
  payload: dict[str, object] = {
      "kind": "coordinator", "trigger": trigger, "asset": relative, "product": product_record,
  }
  # guidelines and decisions are named, never copied — the expert reads the real files in the tree
  if guideline_paths:
    payload[gate_dispatch._PayloadKey.GUIDELINES] = guideline_paths
  if decisions_paths:
    payload[gate_dispatch._PayloadKey.DECISIONS] = decisions_paths
  # doc field is only meaningful for a DOC_TRANSITION wake — every other trigger omits it
  # waiver: payload wire-key literal, same wire-schema dict as the literals two lines up
  if doc_transition is not None:
    payload["doc"] = doc_transition
  # dep field is only meaningful for a DEPENDENCY_READY wake — every other trigger omits it (C2)
  # waiver: payload wire-key literal, same wire-schema dict as the literals above
  if dependency_ready is not None:
    payload["dep"] = dependency_ready
  # an unresolved context path (e.g. an unresolvable spec_depends_on token) was previously
  # visible only in the caller's `# History` line, never to the dispatched job itself — folded
  # into the payload too so the coordinator persona can see what it's missing (I11)
  # waiver: payload wire-key literal, same wire-schema dict as the "kind"/"trigger"/"asset"/"doc"
  # literals above
  if warnings:
    payload["warnings"] = warnings
  dedup_key = f"{relative}:coordinator"
  return source, context, warnings, payload, dedup_key


def _commit(asset_dir: Path, asset_note: Path, subject: str) -> None:
  """
  Commit the rewritten status folder-note under this worker's own bot identity, atomically.

  Defensive no-op when the asset is not inside a git repository, mirroring
  `gate_tick._commit_note_change`.

  Args:
    asset_dir: The asset folder; used to resolve the enclosing repo root for the `git` cwd.
    asset_note: The status folder-note path that was just rewritten.
    subject: The commit subject line.

  Raises:
    subprocess.CalledProcessError: When `git add` or `git commit` exits non-zero.
  """
  top = flip_gate._git_field(asset_dir, ["rev-parse", "--show-toplevel"], "")
  # guard: asset is not inside a git repository — skip commit
  if not top:
    return
  repo = Path(top)

  # fold the note's icon repaint into this same commit so no separate icons commit follows
  extra_paths = iconize_inline.repaint_paths(
      repo, [str(asset_note.resolve().relative_to(repo.resolve()))],
  )

  # stage the rewritten folder-note so the tree is clean for the next daemon iteration
  subprocess.run(
      ["git", "add", "--", str(asset_note), *extra_paths],
      cwd = str(repo), check = True, capture_output = True,
  )

  # commit under the dedicated bot identity, with an explicit pathspec so a populated index
  # (e.g. the operator's recover.py triage, `git stash push -u`) never rides along
  subprocess.run(
      [
          "git",
          "-c", f"user.name={_DISPATCH_AUTHOR_NAME}",
          "-c", f"user.email={_DISPATCH_AUTHOR_EMAIL}",
          "-c", "commit.gpgsign=false",
          "commit", "-q", "-m", subject, "--", str(asset_note), *extra_paths,
      ],
      cwd = str(repo), check = True, capture_output = True,
  )


def _group_carries_wake(
    fm: dict, body: str, item: dict, members: list[Path], *, note_changed: bool = True,
    basenames: frozenset[str] | None = None,
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
    fm: The asset status folder-note's parsed frontmatter.
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
      (`_is_tracked_document`).

  Returns:
    True when a `# Coordinator commands` section is non-empty, a coordinator-attributed ticked
    question differs from its recorded fingerprint, any member's `review_result` differs from
    what this worker last recorded for it, or (subject to the `note_changed` carve-out above) the
    item's own author is non-`@bot.`.
  """
  if _read_section_body(body, Section.COORD_COMMANDS):
    return True
  ticked_block = _find_ticked_question_block(body)
  if ticked_block is not None:
    if fm.get(AnsweredQuestionKey.FINGERPRINT) != _compute_answer_fingerprint(ticked_block):
      return True
  for member in members:
    if _is_tracked_document(member, basenames) and _resolve_doc_transition(member, fm) is not None:
      return True
  # guard: a siblings-only tick (note itself unchanged) with every member under active review
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
  fm_text = gate_tick._del_fm_key(fm_text, _LEGACY_PENDING_EDIT_KEY)
  fm_text = gate_tick._del_fm_key(fm_text, _LEGACY_PENDING_DOC_KEY)
  return fm_text


def coordinator_dispatch(
    asset_note: Path, item: dict, *,
    today: str | None = None, sibling_doc: Path | None = None, dependency_wake: str | None = None,
    group_members: list[Path] | None = None, level_doc: Path | None = None,
    asset_released: str | None = None,
) -> dict:
  """
  Detect operator activity on one coordinated folder-note and dispatch its expert when it wakes.

  The note's own `spec_role` picks the persona: an asset's status note dispatches
  `spec.coordinator`, a product's or the catalog root's level note dispatches
  `spec.catalog-coordinator` on the level ladder instead. Everything around the dispatch — the
  one-active-job guard, the dispatch cursor, the marker sidecar, the commit identity — is keyed
  by note path and behaves identically for both.

  At most one coordinator job runs per asset at a time. While a job is still running, the note is
  untouched unless a wakeup arrives that would otherwise be lost: any wake-worthy signal (a
  non-empty commands section, a fresh answer, a sibling `review_result` transition, or a non-bot
  author) stamps one sidecar flag,
  `JobMarker.PENDING_WAKE: JobMarker.DECLINED` — no note write, no commit, and never overwriting
  an already-raised `job-done` flag. A busy job ignores even a non-empty commands section until
  then. Once free, a finished job's marker is cleared in the sidecar, which touches no note text
  and so costs no commit; only a job found DEAD leaves a `# History` WARNING line behind, and
  that line is committed even when nothing else wakes the coordinator this tick. A `job-done` or
  `declined` sidecar flag then redeems by re-resolving triggers against the asset's CURRENT
  on-disk state (every sibling doc in the asset directory, not only whichever member this tick's
  own item happened to name), falling back to `JOB_DONE` / `OPERATOR_EDIT` respectively when
  nothing specific replays — except on a halted asset, where the fallback is skipped entirely and
  the flag survives untouched for the operator to redeem after lifting the halt (the halt override
  every other trigger already respects). Consumption differs by flag: `job-done` is cleared only
  when it actually wins resolution, surviving a preempting trigger for a later tick; `declined` is
  cleared on ANY successful dispatch of this asset, whichever trigger won. A fresh wakeup queues
  the job, stamps the asset's job marker in the sidecar, appends a `# History` line, and commits
  under this worker's own bot identity.

  When `sibling_doc` is given, this is a sibling-item tick — trigger resolution never reasons
  about `item`'s own commit against `asset_note` the way the ordinary status-note tick does
  (`item` names `sibling_doc`'s commit here, not the asset note's own); instead it compares the
  sibling's current `review_result` against the value this worker last recorded for it, honoring
  the same halt override every other trigger respects (`lazy-spec.coordination-playbook.md` § 1).

  Guarantees:
    - At most one coordinator job runs against a given note at a time; a wake that arrives while
      one is still active never dispatches a second job for that note until the running one
      finishes.
    - Writes and commits the status folder-note only when the produced text differs from the
      note's bytes as read at the start of the call; a wake that changes nothing leaves the note
      byte-identical and creates no commit.

  Notes:
    - A raise here leaves the tick's in-memory state unwritten, but the wake it carried is not
      lost: a non-zero exit from this CLI invocation is caught by `dispatch_git`'s command
      shape, which records the item and retries it, ahead of any fresh item, on the next tick
      — self-healing until the exception stops recurring, or the item's sha becomes
      unreachable, in which case it is dropped instead of replayed.
    - A top-level call (`dependency_wake` is None) whose own wake crosses a readiness gate also
      dispatches a job — and writes and commits that job's own status folder-note — on every
      OTHER asset that names this one in its own `spec_depends_on` (C2/N1). That side effect
      runs only after this asset's own dispatch has landed, and never propagates a failure of
      its own back to the caller (N2).
    - A top-level call on an asset whose `Gate.RELEASED` crossed to true dispatches one job on
      the owning product's level note, on the same best-effort terms.
    - Neither of those two edges requires a trigger to have resolved on the asset itself: both
      gates are normally flipped by a bot-authored commit that wakes nothing here, so both
      crossings are evaluated before the no-trigger exit, recorded on the note together, and
      dispatched onward from that exit too.

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
    dependency_wake: The `<category>/<slug>` token of a dependency asset that just woke, when
      this call is the one-hop reverse-dependency dispatch a wake on that asset triggers (C2)
      rather than an ordinary git-watch tick. Trigger resolution short-circuits to
      `CoordinatorTrigger.DEPENDENCY_READY` (honoring the halt override like every other
      trigger) and never reasons about `sibling_doc` on this path; `item` is still read by the
      busy-job guard (a declined wake here flags `declined` in the sidecar, same as any other
      declined non-bot item). None for every ordinary tick; mutually exclusive with
      `sibling_doc`.
    group_members: The group's OTHER member paths — every sibling doc a grouped `{dir, paths,
      ...}` item names, excluding the status folder-note itself. Given only for a grouped tick;
      trigger resolution then runs `_resolve_group_trigger` (one pass over every member) instead
      of the single-file `_resolve_wake_trigger` / `sibling_doc` / `dependency_wake` branching,
      and `item`'s own `sha`/`author_email` name the group directory's own last commit rather
      than one file's. None for every other call shape; mutually exclusive with `sibling_doc`
      and `dependency_wake`.
    level_doc: The level document's own path, when this tick's item is one of the level ladder's
      basenames (`LevelDoc.BASENAMES`) rather than the level note itself. Given only when
      `asset_note` is a level note; a level tick naming the note itself passes None, and trigger
      resolution then reads the ordinary ladder off the note alone.
    asset_released: The `<category>/<slug>` token of an asset whose release gate just crossed,
      when this call is the one-hop upward dispatch that crossing raises on the owning product's
      level note. Trigger resolution short-circuits to `CoordinatorTrigger.ASSET_RELEASED`
      (honoring the halt override like every other trigger); `item` is `{}` on this path, so
      nothing is read off a commit. None for every ordinary tick.

  Returns:
    `{"action": "noop"}`; `{"action": "dispatch-stale", "trigger", "job_id"}` when the dispatch
    matched an already-finished bundle — the trigger is retired, not retried, since the
    git-watch routine's own cursor has already advanced past this item regardless (N2); or
    `{"action": "dispatched", "trigger", "expert", "job_id", "warnings"}` on a fresh dispatch.

  Raises:
    RuntimeError: When the `lazycortex-core` CLI can't be resolved or exits non-zero.
    subprocess.CalledProcessError: When the commit of the rewritten note fails — propagated
      from `_commit`.
  """
  # read the current note once — every branch below decides off this one snapshot
  asset_dir = asset_note.parent
  repo_root = flip_gate._repo_root(asset_dir)

  # a manual wake (lazy-spec.drive's path-only item) carries neither `sha` nor `author_email` —
  # derive both from the newest commit touching the path, so the operator-author check, the
  # cursor-bounded lookback, and the dispatch-cursor stamp all work exactly as they do for a
  # daemon git-watch item; a daemon item's own fields always win over the derivation
  if item.get(_ITEM_PATH) and (not item.get(_ITEM_SHA) or not item.get(_ITEM_AUTHOR_EMAIL)):
    head = subprocess.run(
        ["git", "log", "-1", "--format=%H%x00%ae", "--", str(item[_ITEM_PATH])],
        cwd = str(repo_root), capture_output = True, text = True, check = False,
    )
    if head.returncode == 0 and head.stdout.strip():
      sha, _, email = head.stdout.strip().partition("\x00")
      item = { **item, _ITEM_SHA: item.get(_ITEM_SHA) or sha,
               _ITEM_AUTHOR_EMAIL: item.get(_ITEM_AUTHOR_EMAIL) or email }

  # snapshot the note once — every branch below decides off this one read
  today_str = flip_gate._today(today)
  text = asset_note.read_text()
  original_text = text
  fm, fm_end = flip_gate._parse_frontmatter(text)
  body = text[fm_end:]
  markers = spec_job_markers.read(repo_root, asset_note)
  cursor = _read_dispatch_cursor(repo_root, asset_note)

  # the note's own role picks the ladder and the persona; everything else below is shared
  role = str(fm.get(SpecKey.ROLE) or "")
  is_level = role in LEVEL_ROLES
  expert = _CATALOG_EXPERT if is_level else _COORDINATOR_EXPERT
  doc_basenames = LevelDoc.BASENAMES if is_level else None

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

  # Contract:
  # At most one coordinator job runs against a given note at a time; a wake that arrives while
  # a job is still active for that note never dispatches a second job until the running one
  # finishes.

  # one active coordinator job per asset — unconditional, no halt/command exception
  note_dirty = False
  coordinator_job = markers[JobMarker.COORDINATOR_JOB]
  if isinstance(coordinator_job, dict):
    marker = gate_tick._find_active_job_marker(
        repo_root, coordinator_job[JobMarker.EXPERT], coordinator_job[JobMarker.JOB_ID],
    )
    # guard: bundle carries no terminal marker yet — still running
    if marker is None:
      # the git-watch cursor advances past this item regardless of the noop below, so a
      # wake-worthy tick seen here would otherwise be lost the moment the job finishes with
      # nothing further changing the note (N2) — one sidecar flag, no note write, no commit;
      # job-done already means "wake me", so a later decline must never overwrite it
      wake_members = group_members if group_members is not None else [
          doc for doc in ( sibling_doc, level_doc ) if doc is not None
      ]
      # the review-active carve-out only ever applies to a genuine grouped tick — the plain
      # status-note and sibling-item shapes keep `_group_carries_wake`'s default `note_changed
      # = True`, which is an unconditional author check exactly as before this fix
      # limit: a `Gate.RELEASED` crossing landing while a coordinator job is active is deferred
      # here with everything else — the readiness marker stays unstamped, so the next tick that
      # finds the guard clear still sees the crossing and dispatches the upward level wake;
      # upgrade path is evaluating the crossing above this guard if the deferral ever costs more
      # than the duplicate-dispatch risk of doing it while a job holds the note
      wake_note_changed = (
          _has_group_note_changed(item, asset_note, repo_root) if group_members is not None else True
      )
      if (
          markers.get(JobMarker.PENDING_WAKE) is None
          and _group_carries_wake(
              fm, body, item, wake_members,
              note_changed = wake_note_changed, basenames = doc_basenames,
          )
      ):
        spec_job_markers.update(repo_root, asset_note, { JobMarker.PENDING_WAKE: JobMarker.DECLINED })
      return { TickAction.ACTION: TickAction.NOOP }
    # the bundle finished since the last tick — clear the slot now so a trigger firing this
    # same tick dispatches immediately instead of first colliding with the old dedup key (M1)
    if marker == gate_tick._JOB_MARKER_DEAD:
      # DEAD is not eligible for dedup matching in the first place (expert_runtime's own scan
      # excludes it), so this guard owes only the WARNING line — never consume_stale_job. Same
      # text as gate_tick's periodic sweep of this key (fix-round-1: this guard used to consume
      # DEAD identically to DONE/CANCELLED, silently dropping the line whenever it won the race)
      body = flip_gate._append_under_heading(
          body, Section.HISTORY,
          gate_tick._coordinator_job_dead_warning_line(
              _DISPATCH_AUTHOR_NAME, coordinator_job[JobMarker.TRIGGER],
              coordinator_job[JobMarker.JOB_ID], today_str,
              lang = note_explainers.lang_for_note(asset_note),
          ),
      )
      # the WARNING line is the only note text this guard ever produces — the marker clear
      # itself is a sidecar write, so every other branch leaves the note byte-identical
      text = text[:fm_end] + body
      note_dirty = True
    else:
      gate_dispatch.consume_stale_job(
          repo_root, coordinator_job[JobMarker.EXPERT], coordinator_job[JobMarker.JOB_ID])
    markers = spec_job_markers.update(repo_root, asset_note, { JobMarker.COORDINATOR_JOB: None })

  # an old install's note still carrying either retired frontmatter pending-note key reads as a
  # declined-wake for this tick — redeemed the same way the sidecar flag is below, and stripped
  # off the note on whichever write follows (`_strip_legacy_pending`, applied to `fm_text` once
  # it's built further down)
  legacy_pending = _LEGACY_PENDING_EDIT_KEY in fm or _LEGACY_PENDING_DOC_KEY in fm

  # resolve what woke the coordinator, honoring the halt override
  doc_transition = None
  group_transitions: dict[str, str] = {}
  if group_members is not None:
    trigger, group_transitions = _resolve_group_trigger(
        repo_root, fm, body, item, markers, group_members, asset_note, cursor,
    )
    # the FULL set stamps into spec_coordinator_doc_state below; `doc_transition` only carries
    # the first-sorted pair so every other consumer built around a single (basename, value) —
    # the History line, the dedup match — keeps working unchanged (brief step 5)
    if trigger == CoordinatorTrigger.DOC_TRANSITION:
      first = sorted(group_transitions)[0]
      doc_transition = (first, group_transitions[first])
  elif dependency_wake is not None:
    # halt silences a dependency-ready wake exactly like every other automation trigger
    # (playbook § 1); item/sibling_doc carry nothing to reason about on this synthetic path
    trigger = None if flip_gate._is_true(fm, SpecHaltKey.HALTED) else CoordinatorTrigger.DEPENDENCY_READY
  elif asset_released is not None:
    # halt silences the upward release wake the same way; `item` is empty on this synthetic path
    trigger = None if flip_gate._is_true(fm, SpecHaltKey.HALTED) else CoordinatorTrigger.ASSET_RELEASED
  elif is_level:
    # the level ladder reads its own documents rather than an asset's siblings, and resolves the
    # full transition set in one pass exactly as the grouped asset form does
    trigger, group_transitions = _resolve_level_trigger(
        repo_root, fm, body, item, [ level_doc ] if level_doc is not None else [], cursor,
    )
    if trigger == CoordinatorTrigger.DOC_TRANSITION:
      first = sorted(group_transitions)[0]
      doc_transition = (first, group_transitions[first])
  elif sibling_doc is not None:
    resolved = _resolve_doc_transition(sibling_doc, fm)
    # halt silences a doc-transition wake exactly like every other automation trigger
    # (playbook § 1) — a sibling item never carries the COMMAND exemption, since COMMAND is
    # read off the asset note's own body, not the sibling
    if resolved is None or flip_gate._is_true(fm, SpecHaltKey.HALTED):
      trigger = None
    else:
      trigger = CoordinatorTrigger.DOC_TRANSITION
      doc_transition = resolved
  else:
    trigger = _resolve_wake_trigger(repo_root, fm, body, item, markers, cursor)

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
    redeem_members = sorted(p for p in asset_dir.iterdir() if _is_tracked_document(p, doc_basenames))
    if is_level:
      trigger, group_transitions = _resolve_level_trigger(
          repo_root, fm, body, item, redeem_members, cursor,
      )
    else:
      trigger, group_transitions = _resolve_group_trigger(
          repo_root, fm, body, item, markers, redeem_members, asset_note, cursor,
      )
    if trigger is None:
      # nothing specific replayed — the generic fallback token per the flag that forced this
      # redemption; a legacy-only note (no sidecar flag) falls back the same way declined does.
      # A halted asset is a noop here, never a fallback dispatch: `_resolve_group_trigger` already
      # returned None for exactly that reason (its halt override, COMMAND excepted — but COMMAND
      # would have set `trigger` above, never reaching this branch), and forcing a fallback trigger
      # anyway would both dispatch AND consume the flag below, permanently losing the wake instead
      # of leaving it for the operator to lift the halt and redeem later.
      if not flip_gate._is_true(fm, SpecHaltKey.HALTED):
        trigger = (
            CoordinatorTrigger.JOB_DONE if redeemed_wake == JobMarker.JOB_DONE
            else CoordinatorTrigger.OPERATOR_EDIT
        )
    elif trigger == CoordinatorTrigger.DOC_TRANSITION:
      first = sorted(group_transitions)[0]
      doc_transition = (first, group_transitions[first])

  # the gate crossings this tick observed, read BEFORE the no-trigger exit below: neither edge
  # belongs to this asset's own wake — the release reaches the level ladder above and the
  # readiness reaches the dependents beside — and both are normally flipped by a bot-authored
  # commit that wakes nothing here, so a crossing evaluated after the exit would be lost (C2/N1)
  # limit: a dependent already running its own job falls through the ordinary busy-guard above
  # and is flagged declined (this call's `item` is `{}`, which reads as non-bot), so it redeems
  # as OPERATOR_EDIT rather than DEPENDENCY_READY once free — the dispatch still happens, just
  # under the generic label; upgrade path is a dedicated pending-dependency wake token if that
  # label ever needs to survive the busy-guard
  cur_ready = None
  wake_dependents = False
  released_crossed = False
  my_token = ""
  prev_ready: dict = {}
  if dependency_wake is None and not is_level:
    prev_ready = _read_marker_dict(fm, SpecCoordinatorReadyStateKey.STATE)
    cur_ready = {
        Gate.DEVELOP_DONE: flip_gate._is_true(fm, Gate.DEVELOP_DONE),
        Gate.TESTS_PASSING: flip_gate._is_true(fm, Gate.TESTS_PASSING),
        Gate.RELEASED: flip_gate._is_true(fm, Gate.RELEASED),
    }
    # the release gate rides the same marker but a different edge: it wakes the level coordinator
    # above, never the dependents beside — a dependent waits on readiness, not on a release
    wake_dependents = any(
        value and not prev_ready.get(key, False)
        for key, value in cur_ready.items() if key != Gate.RELEASED
    )
    released_crossed = cur_ready[Gate.RELEASED] and not prev_ready.get(Gate.RELEASED, False)
    my_token = f"{asset_dir.parent.name}/{asset_dir.name}"

  # guard: nothing wakes the coordinator this tick
  if trigger is None:
    # a crossing that landed on a commit nothing else woke on still has to be recorded and
    # dispatched onward: both edges are flipped by bot-authored commits (the coordinator's own
    # `flip-gate` write), which suppress this asset's own wake but say nothing about the
    # neighbours waiting on them. The whole observed snapshot is stamped, exactly as the
    # dispatching path stamps it, so neither edge can re-fire on a later tick.
    crossed = released_crossed or wake_dependents
    if crossed and cur_ready is not None:
      text = gate_tick._set_fm_json(
          text[:fm_end], SpecCoordinatorReadyStateKey.STATE, cur_ready,
      ) + text[fm_end:]
    # the dead-job WARNING line above still needs to land even with nothing left to dispatch;
    # a job merely consumed left no note text behind, so that tick writes nothing at all
    if note_dirty or crossed:
      asset_note.write_text(note_explainers.heal_note_text(asset_note, text))
      _commit(
          asset_dir, asset_note,
          f"{_DISPATCH_AUTHOR_NAME}: coordinator job died on {asset_dir.name}" if note_dirty
          else f"{_DISPATCH_AUTHOR_NAME}: recorded gate crossing on {asset_dir.name}",
      )
    # both hops run after the record lands, so a failing neighbour can't lose the stamp
    if wake_dependents:
      _wake_ready_dependents(asset_dir, my_token, today = today)
    if released_crossed:
      _wake_product_note(repo_root, asset_dir, my_token, today = today)
    return { TickAction.ACTION: TickAction.NOOP }

  # assemble and queue the coordinator job's wire bundle — the level branch reads the level
  # ladder's own layers instead of the asset's type, tools, targets and dependencies
  protocols: list[str] = []
  if is_level:
    source, context, warnings, payload, dedup_key, protocols = _build_level_bundle(
        repo_root, asset_note, role, trigger,
        doc_transition = doc_transition[0] if doc_transition is not None else None,
        asset_released = asset_released,
    )
  else:
    source, context, warnings, payload, dedup_key = _build_bundle(
        repo_root, asset_dir, asset_note, text[:fm_end], trigger,
        doc_transition = doc_transition[0] if doc_transition is not None else None,
        dependency_ready = dependency_wake,
    )
  # a grouped tick's FULL transition set rides in payload too — `payload["doc"]` above already
  # names the first-sorted basename, "docs" only needs to appear when there is more than one to
  # add, so the coordinator can process every transitioned sibling in one pass (brief step 5)
  # waiver: payload wire-key literal, same wire-schema dict as `_build_bundle`'s own
  # "kind"/"trigger"/"asset"/"doc"/"dep" literals — this dict IS the wire schema, not a reusable
  # domain key
  if len(group_transitions) > 1:
    payload["docs"] = sorted(group_transitions)
  bundle = {
      gate_dispatch._WireKey.EXPERT: expert,
      gate_dispatch._WireKey.PAYLOAD: payload,
      gate_dispatch._WireKey.SOURCE: source,
      gate_dispatch._WireKey.DEDUP_KEY: dedup_key,
  }
  # context is optional on the wire — only sent when there's actually something in it
  if context:
    bundle[gate_dispatch._WireKey.CONTEXT] = context
  # so is the playbook reference: core unions it with the dispatching routine's own protocols,
  # which is how one routine serves two ladders with two playbooks
  if protocols:
    bundle[_WIRE_PROTOCOLS] = protocols
  response = gate_dispatch._core_dispatch_job(repo_root, bundle)
  job_id = str(response.get(gate_dispatch._WireKey.JOB_ID))

  # consume the sidecar wake now that this tick's dispatch has landed, so the same wake cannot
  # fire a second coordinator. The two flag values consume on different terms: `job-done` only
  # when it actually won resolution (`trigger == JOB_DONE`) — a wake this tick preempted (a
  # command, an answer) keeps its flag and fires on a later tick, unchanged from before this
  # fix. `declined` inherits the retired `pending_edit` flag's own behaviour instead — it is
  # consumed on ANY successful dispatch of this asset, whichever trigger won, because unlike
  # job-done it carries no trigger identity of its own to wait for; leaving it set past a
  # dispatch that already covers the same wake would just re-redeem it, uselessly, next tick.
  # Deliberately after the dispatch rather than before it: a raise from `_core_dispatch_job`
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

  # record the readiness-gate snapshot this tick observed, regardless of whether it crossed
  # anything, so the NEXT tick's crossing check compares against the latest state (N1) — a
  # `dependency_wake` call has no `cur_ready` to stamp, since it never runs the check itself
  if cur_ready is not None:
    fm_text = gate_tick._set_fm_json(fm_text, SpecCoordinatorReadyStateKey.STATE, cur_ready)

  # stamp the answered-question fingerprint so an identical ticked block never re-fires ANSWER
  # once this worker has already reacted to it (I1/I-D)
  answered_block = _find_ticked_question_block(body) if trigger == CoordinatorTrigger.ANSWER else None
  if answered_block is not None:
    fm_text = note_ops._set_fm_scalar(
        fm_text, AnsweredQuestionKey.FINGERPRINT, _compute_answer_fingerprint(answered_block),
    )

  # stamp the sibling's transitioned review_result so an unchanged re-tick never re-fires
  # DOC_TRANSITION for the same basename+value (mirrors the ANSWER fingerprint stamp above)
  if doc_transition is not None:
    basename, new_value = doc_transition
    state = _read_doc_state(fm)
    # a grouped (or redeemed-declined) tick may have found MORE than one sibling transition in
    # the same pass — stamp them all now so none is lost to a later tick (brief step 5); every
    # other DOC_TRANSITION path (single sibling-doc tick) always has exactly one pair here
    state.update(group_transitions or { basename: new_value })
    fm_text = gate_tick._set_fm_json(fm_text, SpecCoordinatorDocStateKey.STATE, state)

  # a dedup hit matching a finished-but-unconsumed bundle is retired rather than tracked — left
  # unconsumed, the same terminal bundle would keep matching this dedup key on every future tick.
  # The git-watch cursor has already moved past this item regardless (N2), so this trigger is
  # retired, not retried — the M1 consumption above (job_consumed) makes this path rare, reached
  # only by a genuine same-tick race rather than the routine steady state it used to be.
  if (
      response.get(gate_dispatch._WireKey.STATUS) == gate_dispatch.ALREADY_QUEUED_STATUS
      and gate_tick._find_active_job_marker(repo_root, expert, job_id) is not None
  ):
    gate_dispatch.consume_stale_job(repo_root, expert, job_id)
    # the retired trigger still counts as handled — the cursor moves so the same commit never
    # re-fires, and the I6 stamps persist below only when they actually changed the note
    _stamp_dispatch_cursor(repo_root, asset_note, item.get(_ITEM_SHA))
    new_text = fm_text + body
    if new_text != original_text:
      asset_note.write_text(note_explainers.heal_note_text(asset_note, new_text))
      _commit(
          asset_dir, asset_note,
          f"{_DISPATCH_AUTHOR_NAME}: stale dispatch for {trigger} on {asset_dir.name}",
      )

    # this asset's own dispatch already landed above — the reverse wake runs after, never
    # before, so a broken dependent can't strand it (N2)
    if wake_dependents:
      _wake_ready_dependents(asset_dir, my_token, today = today)

    # a release crossing wakes the level coordinator above this asset, on the same terms: after
    # this asset's own dispatch, one hop, best-effort
    if released_crossed:
      _wake_product_note(repo_root, asset_dir, my_token, today = today)

    # this tick's own trigger was retired, not dispatched — see the guard above
    return { TickAction.ACTION: TickAction.DISPATCH_STALE, "trigger": trigger, "job_id": job_id }

  # record the dispatched job in runtime state so the active-job guard blocks a second
  # concurrent dispatch — no note write, so this stamp costs no commit of its own and nothing
  # an operator editing the note can break; the cursor moves in the same breath, so the handled
  # item's commit never re-fires a later lookback
  spec_job_markers.update(repo_root, asset_note, { JobMarker.COORDINATOR_JOB: {
      JobMarker.TRIGGER: trigger,
      JobMarker.EXPERT: expert,
      JobMarker.JOB_ID: job_id,
  } })
  _stamp_dispatch_cursor(repo_root, asset_note, item.get(_ITEM_SHA))

  # the wake itself leaves no `# History` line — `# History` records the asset's own
  # transitions, not this worker's mechanics; a dispatch warning (an unresolved context path)
  # is still landed, one line each, never a silent skip
  new_body = body
  for warning in warnings:
    new_body = flip_gate._append_under_heading(
        new_body, Section.HISTORY, f"- {today_str} — {_DISPATCH_AUTHOR_NAME} · {warning}",
    )

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
    asset_note.write_text(note_explainers.heal_note_text(asset_note, new_text))
    _commit(
        asset_dir, asset_note,
        f"{_DISPATCH_AUTHOR_NAME}: wake {trigger} on {asset_dir.name} → {expert} ({job_id})",
    )

  # this asset's own dispatch already landed above — the reverse wake runs after, never
  # before, so a broken dependent can't strand it (N2)
  if wake_dependents:
    _wake_ready_dependents(asset_dir, my_token, today = today)

  # a release crossing wakes the level coordinator above this asset, on the same terms: after
  # this asset's own dispatch, one hop, best-effort
  if released_crossed:
    _wake_product_note(repo_root, asset_dir, my_token, today = today)

  # the fresh dispatch this tick queued
  return {
      TickAction.ACTION: TickAction.DISPATCHED,
      "trigger": trigger,
      "expert": expert,
      "job_id": job_id,
      "warnings": warnings,
  }


def main(argv: list[str]) -> int:
  """
  Run one coordinator-dispatch tick from the command line, printing the result as JSON.

  Invoked by the `lazy-spec.coordinator-watch` git-watch routine as `coordinator-dispatch
  <item-json>` — one line of JSON per changed file (or per grouped asset directory), per
  `routine_types.dispatch_git`'s `command:` sub-shape (`[*resolved_cmd, json.dumps(item)]`,
  spawned with `cwd = repo`). The item carries one of two shapes: a grouped
  `{dir, paths, sha, author_name, author_email}` item names an asset directory and every one of
  its changed members at once and is resolved straight to that directory's own status
  folder-note (a group without one — a bare category folder, or a race with a deletion — is
  skipped); otherwise the routine's `filter.any_of` matches a single changed file, either a
  status folder-note (`spec_role: status`) OR an authored document carrying a non-null
  `spec_doc_type` — `item["path"]` names whichever one matched. A sibling-doc item is resolved to its OWNING
  asset's status folder-note (the Obsidian folder-note convention, `<dir>/<dir>.md`) before
  dispatch; a sibling living outside an asset folder (a product-root `tech.md` / loose
  `design.md` — no coordinator-job tracking exists at that level) resolves the same convention
  to a folder-note that never carries `spec_role: status`, and is skipped.

  A document parked at `spec_stage: deferred` is dispatched on like any other changed path — the
  owning note still needs its gates, brief, and launch rows put in order. What a parked document
  never does is carry a `review_result` transition, so a bot-authored commit landing nothing
  but its verdict reaches no trigger at all.

  Args:
    argv: Command-line arguments, excluding the program name — exactly one, the item JSON.

  Returns:
    Exit code: 2 when the item JSON is malformed or carries neither a usable `dir` nor a usable
    `path`; 0 on every other path, including a noop when the resolved path no longer exists (a
    note deleted or moved between the git-watch scan and this dispatch) or resolves to a doc
    this worker never tracks a coordinator job against.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs coordinator-dispatch")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("item_json", type = str)
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--today", default = None,
                      # waiver: one-off human-facing message -- argparse help text
                      help = "ISO date pinned into the emitted history line")
  args = parser.parse_args(argv)

  # parse the git-watch item and pull out the changed file's path
  try:
    item = json.loads(args.item_json)
  except json.JSONDecodeError:
    sys.stderr.write(f"malformed git-watch item JSON: {args.item_json!r}\n")
    return 2
  raw_dir = item.get(_ITEM_DIR) if isinstance(item, dict) else None
  # guard: a grouped `{dir, paths, ...}` item resolves straight to its owning asset's status
  # folder-note — one dispatch for the whole group; the single-file `path` form below is the
  # fallback for a changed file outside the routine's directory-grouping glob
  if isinstance(raw_dir, str) and raw_dir:
    asset_dir = (Path.cwd() / raw_dir).resolve()
    asset_note = asset_dir / f"{asset_dir.name}.md"
    # guard: a group without a status folder-note (a bare category folder, or a race with a
    # deletion) is not an asset this worker tracks
    if not asset_note.is_file():
      print(json.dumps({ TickAction.ACTION: TickAction.NOOP }))
      return 0
    fm, _ = flip_gate._parse_frontmatter(asset_note.read_text())
    # guard: an operator-zone folder-note (never `spec_role: status`) tracks no coordinator job
    if fm.get(SpecKey.ROLE) != _SPEC_ROLE_STATUS:
      print(json.dumps({ TickAction.ACTION: TickAction.NOOP }))
      return 0
    # every OTHER member path in the group, resolved once here rather than re-derived inside
    # `coordinator_dispatch` — the status note itself is never one of its own sibling members
    members = [
        (Path.cwd() / p).resolve() for p in item.get(_ITEM_PATHS, [])
        if isinstance(p, str) and (Path.cwd() / p).resolve() != asset_note.resolve()
    ]
    result = coordinator_dispatch(asset_note, item, today = args.today, group_members = members)
    print(json.dumps(result))
    return 0

  # the single-file `changed_files` form — the routine's other `any_of` member
  raw_path = item.get(_ITEM_PATH) if isinstance(item, dict) else None
  # guard: neither shape a git-watch item takes carries anything to dispatch on
  if not isinstance(raw_path, str) or not raw_path:
    sys.stderr.write(f"git-watch item carries no {_ITEM_DIR!r} or {_ITEM_PATH!r}: {item!r}\n")
    return 2

  # the daemon spawns this command with cwd = repo root (routine_types.dispatch_git), so a
  # relative item path resolves against the current directory
  changed = (Path.cwd() / raw_path).resolve()

  # guard: the file was deleted or moved between the git-watch scan and this dispatch
  if not changed.is_file():
    print(json.dumps({ TickAction.ACTION: TickAction.NOOP }))
    return 0

  # a document basename resolves to the folder-note that owns it, by where the document lies;
  # every other match IS the folder-note the routine's own `any_of` member selected
  repo_root = flip_gate._repo_root(changed.parent)
  is_document = _is_tracked_document(changed) or changed.name in LevelDoc.BASENAMES
  owner = _resolve_owner_note(repo_root, changed) if is_document else changed

  # guard: no folder-note owns this path (a bare folder, or a race with a deletion) — nothing
  # this worker tracks a coordinator job against
  if not owner.is_file():
    print(json.dumps({ TickAction.ACTION: TickAction.NOOP }))
    return 0

  # the owner's own role picks the ladder: an asset's status note runs the asset one, a product's
  # or the catalog root's level note the level one, and a note carrying neither is nobody's object
  fm, _ = flip_gate._parse_frontmatter(owner.read_text())
  role = fm.get(SpecKey.ROLE)

  # guard: a note carrying no coordination role is nobody's object
  if role != _SPEC_ROLE_STATUS and role not in LEVEL_ROLES:
    print(json.dumps({ TickAction.ACTION: TickAction.NOOP }))
    return 0

  # guard: a document belonging to the OTHER ladder is not one this note tracks — the level set
  # and the asset predicate overlap on `design.md` / `tech.md`, so the union that found the owner
  # must be narrowed by the owner's own role here
  own_basenames = LevelDoc.BASENAMES if role in LEVEL_ROLES else None
  if is_document and not _is_tracked_document(changed, own_basenames):
    print(json.dumps({ TickAction.ACTION: TickAction.NOOP }))
    return 0

  # the changed document, when the tick named one rather than the note itself
  doc = changed if is_document else None
  if role == _SPEC_ROLE_STATUS:
    result = coordinator_dispatch(owner, item, today = args.today, sibling_doc = doc)
  else:
    result = coordinator_dispatch(owner, item, today = args.today, level_doc = doc)

  # report the tick's result the same way every other lazycortex-specs worker does
  print(json.dumps(result))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
