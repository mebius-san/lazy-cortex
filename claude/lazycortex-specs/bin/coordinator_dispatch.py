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
no new commit from re-dispatching. Because that marker lives outside the note, neither stamping
nor clearing it costs a commit, and no hand-edit of the note can break the mutex.

The routine's `filter.any_of` also matches sibling authored docs by basename (`design.md`,
`code-plan.md`, ...) — an item naming one of those is resolved to its OWNING asset's status
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
import spec_job_markers  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_paths  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from spec_keys import (  # noqa: E402
    AnsweredQuestionKey,
    CoordinatorTrigger,
    Gate,
    HistoryEvent,
    JobMarker,
    Section,
    SiblingDoc,
    SpecCoordinatorDocStateKey,
    SpecCoordinatorReadyStateKey,
    SpecDependsOnKey,
    SpecHaltKey,
    SpecKey,
    SpecTargetsKey,
)


# The fixed expert this worker ever dispatches — unlike `gate_dispatch`'s per-checkbox review-
# class resolution, the coordinator is one persona for every asset (`spec.coordinator`,
# registered live per `lazy-spec.coordination-playbook.md` § 1), never resolved from a review class.
_COORDINATOR_EXPERT = "spec.coordinator"

# The guideline role folded into context via `gate_dispatch._collect_guideline_context`, per
# `lazy-spec.coordination-playbook.md` § 2 layer 3 (`products[<key>].guidelines.coordinator` + `"*"`).
_COORDINATOR_ROLE = "coordinator"

# Bot identity for this worker's own commit (job-metadata write + History line) — the `@bot.`
# substring is what the coordinator's own self-suppression check (playbook § 1) relies on to
# never re-wake itself on this worker's writes.
_DISPATCH_AUTHOR_NAME = "lazy-spec.coordinator-watch"
_DISPATCH_AUTHOR_EMAIL = "lazy-spec.coordinator-watch@bot.invalid"

# Mirrored `spec_source_requests` frontmatter key from `apply_request.py`'s own `_K` class,
# duplicated here rather than imported per this bin/ tree's own per-file small-constant
# convention (see `gate_tick._write_fm_list`'s docstring).
_SPEC_SOURCE_REQUESTS = "spec_source_requests"

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

# Sibling-doc basenames the `lazy-spec.coordinator-watch` routine's `filter.any_of` also matches
# (Task 1's basename sub-filter) — an item naming one of these is a doc-transition candidate,
# never a status folder-note. `architecture.md` arrived with the `architecture` review class
# (plan 4b Task 7); its basename is listed here alongside every other sibling doc kind.
_SIBLING_BASENAMES = frozenset({
    SiblingDoc.DESIGN, SiblingDoc.ARCHITECTURE, SiblingDoc.CODE_PLAN, SiblingDoc.TEST_PLAN,
    SiblingDoc.TECH, SiblingDoc.BUG, SiblingDoc.CODE_REPORT, SiblingDoc.TEST_REPORT,
})

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
    True when `ticked` is set and the last non-empty line in `block_lines` trims to
    `_QUESTION_ATTRIBUTION`.
  """
  # guard: an unticked block never reaches ANSWER regardless of attribution
  if not ticked:
    return False
  # scan backward past any trailing blank quoted line (bare `>`) to the last substantive one
  for line in reversed(block_lines):
    stripped = line.strip()
    # guard: a blank quote continuation carries no content to compare — keep scanning back
    if stripped == ">":
      continue
    return stripped == _QUESTION_ATTRIBUTION
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


def _has_operator_authored_recently(repo_root: Path, item: dict) -> bool:
  """
  Check whether the item's author, or a recent commit touching the same path, is non-`@bot.`.

  Args:
    repo_root: The repository root to run `git` in.
    item: The git-watch `changed_files` item for this note.

  Returns:
    True when the item's own author is non-bot, or when a bounded lookback of the path's most
    recent commits (ending at the item's own `sha`, stopping at this worker's own last wake
    commit) finds a non-bot author among them; False otherwise, including when the item carries
    no usable `path` / `sha`.
  """
  # guard: the item's own author is already non-bot — nothing further to check
  if _BOT_MARK not in item.get(_ITEM_AUTHOR_EMAIL, ""):
    return True

  # a bot-authored tip can bury an operator commit on the same path within one pull batch (N3;
  # the same failure mode fixed for the note's own commit history in cfed7046, before this
  # worker's git-watch resew).
  # limit: fails to find the operator commit when more than `_AUTHOR_LOOKBACK_COMMITS` bot
  # commits land on the same path between pulls; upgrade path is exposing the git-watch
  # routine's own tick cursor on the item (today it lives only in core's own state.json), giving
  # this worker a true lower bound to scan from instead of a fixed window
  sha = item.get(_ITEM_SHA)
  path = item.get(_ITEM_PATH)

  # guard: nothing to scan without both fields
  if not sha or not path:
    return False

  # a fixed-size window of the path's own recent authors, ending at the item's reported tip
  out = subprocess.run(
      ["git", "log", "--format=%ae", "-n", str(_AUTHOR_LOOKBACK_COMMITS), sha, "--", path],
      cwd = str(repo_root), capture_output = True, text = True, check = False,
  ).stdout
  for email in out.splitlines():
    if _BOT_MARK not in email:
      return True
    # guard: this worker's own wake commit proves everything older was already dispatched on
    # (N6 — without this stop, the lookback re-finds the same operator commit on every tick
    # until it ages out of the window, re-dispatching several times per genuine operator gesture)
    if email == _DISPATCH_AUTHOR_EMAIL:
      return False
  return False


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


def _resolve_doc_transition(sibling_doc: Path, fm: dict) -> tuple[str, str] | None:
  """
  Detect a `review_result` transition on one sibling doc against the asset note's own marker.

  The sibling's commit author never enters this check (`CoordinatorTrigger.DOC_TRANSITION`'s
  own docstring) — a commit that never touches `review_result` (an operator's prose edit, a
  writer's draft, any other non-review bot commit) leaves `current == previous` and is a noop
  by construction, with no author check needed to exclude it.

  Args:
    sibling_doc: The sibling doc's own path (the git-watch item's `path`, resolved to a file).
    fm: The owning asset's status folder-note frontmatter, carrying the previously-recorded
      marker (`spec_keys.SpecCoordinatorDocStateKey.STATE`), if any.

  Returns:
    `(basename, new_value)` when the sibling's current `review_result` differs from what this
    worker already recorded for that basename (appeared or changed); `None` when the sibling
    carries no `review_result` right now, or it matches the recorded value.
  """
  basename = sibling_doc.name
  sibling_fm, _ = flip_gate._parse_frontmatter(sibling_doc.read_text())
  current = sibling_fm.get(SpecKey.REVIEW_RESULT)
  # guard: no stamped result on the sibling right now — nothing has transitioned TO
  if current is None:
    return None
  previous = _read_doc_state(fm).get(basename)
  # guard: identical to what this worker already dispatched on — a re-tick, not a transition
  # limit: a doc that reopens for review (review_result cleared) then re-lands the SAME terminal
  # value never re-fires, since the marker is only ever updated on a successful dispatch, not on
  # the intervening clear; upgrade path is stamping the marker on every observed value, not only
  # on a wake, if a genuine re-approval-to-the-same-token needs to re-wake the coordinator
  if current == previous:
    return None
  return basename, current


def _member_signal_eligible(member: Path) -> bool:
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


def _group_note_changed(item: dict, asset_note: Path, repo_root: Path) -> bool:
  """
  Check whether a grouped item's own `paths` names the status folder-note itself, distinct from
  its sibling members.

  A note edit is always an eligible operator-edit signal regardless of any sibling's
  `review_active` state (`_member_signal_eligible`'s own docstring) — this is how the OPERATOR_
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


def _resolve_wake_trigger(repo_root: Path, fm: dict, body: str, item: dict, markers: dict) -> str | None:
  """
  Resolve the wake trigger for this tick, honoring the halt override.

  Args:
    repo_root: The repository root to run `git` in.
    fm: The folder-note's parsed frontmatter.
    body: The folder-note section text (after frontmatter).
    item: The git-watch `changed_files` item for this note (`path`, `status`, `sha`,
      `author_name`, `author_email`).
    markers: The note's runtime marker entry, from `spec_job_markers.read`.

  Returns:
    A `CoordinatorTrigger` token, or None when nothing wakes the coordinator this tick.
  """
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
  if not _has_operator_authored_recently(repo_root, item):
    return None
  return CoordinatorTrigger.OPERATOR_EDIT


def _resolve_group_trigger(
    repo_root: Path, fm: dict, body: str, item: dict, markers: dict, members: list[Path],
    asset_note: Path,
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
      itself is one of `item["paths"]`'s changed members (`_group_note_changed`), for the
      OPERATOR_EDIT arm's review-active carve-out below.

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
    # guard: a member gone between scan and dispatch, or not a tracked sibling kind, is skipped
    # silently rather than failing the whole group resolution
    if not member.is_file() or member.name not in _SIBLING_BASENAMES:
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
  if not _group_note_changed(item, asset_note, repo_root) and not any(
      _member_signal_eligible(member) for member in members
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
  if not _has_operator_authored_recently(repo_root, dir_item):
    return None, {}
  return CoordinatorTrigger.OPERATOR_EDIT, {}


def _resolve_product_note_path(repo_root: Path, product_record: dict) -> Path | None:
  """
  Resolve a product record's own folder-note path (Obsidian folder-note convention).

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
  for dependent_note in _scan_dependents(asset_dir):
    try:
      coordinator_dispatch(dependent_note, {}, today = today, dependency_wake = my_token)
    # limit: stderr-only per the `gate_dispatch.consume_stale_job` §5 fire-and-forget precedent
    # in this same plugin; error-ledger route blocked: the closed cause-set spec
    # (docs/specs/lazy-core.errors.functional-spec.md) is absent from this repo — upgrade path
    # is adding an `error-record` call with a real `--cause` once that spec lands
    except Exception as error:  # pragma: no cover — defensive, see N2
      sys.stderr.write(f"reverse-dependency wake failed for {dependent_note}: {error}\n")


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


def _build_bundle(
    repo_root: Path, asset_dir: Path, asset_note: Path, fm_text: str, trigger: str, *,
    doc_transition: str | None = None, dependency_ready: str | None = None,
) -> tuple[list[str], list[str], list[str], dict, str]:
  """
  Assemble the `lazycortex-core dispatch-job` wire bundle pieces for a coordinator wakeup.

  Source names the note itself; context names the owning product's folder-note, the folders of
  every `spec_targets` asset, the folders of every `spec_depends_on` dependency asset, every
  `spec_source_requests` file (resolved via wikilink), and the vault-wide
  `spec.coordination_rules` doc — all as repo-relative paths the pump copies when it claims the
  job. The product's `coordinator` + `"*"` guidelines and the asset's + owning product's
  `decisions.md` registries (`spec-decisions-design.md` § "Coordinator") are never copied at
  all: they ride in the payload as paths the expert reads in place.
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
  rules_rel = (gate_dispatch._load_settings(repo_root).get(_SPEC_SECTION) or {}).get(_COORD_RULES_KEY)
  if rules_rel:
    rules_path = repo_root / rules_rel
    if rules_path.is_file():
      context.append(_to_rel_path(repo_root, rules_path))
    else:
      warnings.append(f"coordination rules not found: {rules_rel}")

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
      item tick shapes; the grouped-tick caller passes the real `_group_note_changed` result, so
      a siblings-only group needs at least one member NOT under active review
      (`_member_signal_eligible`) before the author check even runs (operator 2026-08-15).

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
    if member.is_file() and member.name in _SIBLING_BASENAMES and _resolve_doc_transition(member, fm) is not None:
      return True
  # guard: a siblings-only tick (note itself unchanged) with every member under active review
  # carries no operator-edit signal to check the author against
  if not note_changed and not any(_member_signal_eligible(member) for member in members):
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
    group_members: list[Path] | None = None,
) -> dict:
  """
  Detect operator activity on one asset and dispatch a `spec.coordinator` job when it wakes.

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

  Args:
    asset_note: The status folder-note path; its parent is the asset dir.
    item: The git-watch item that woke this tick — either the single-file `changed_files` shape
      (`path`, `status`, `sha`, `author_name`, `author_email`; `path` names `sibling_doc` itself
      on a sibling-item tick, never `asset_note`) or, when `group_members` is given, the grouped
      shape (`dir`, `paths`, `sha`, `author_name`, `author_email`) naming the asset directory and
      the last commit that touched it.
    today: Optional ISO date forwarded into the `# History` line.
    sibling_doc: The sibling doc's own path, when this tick's item is a sibling-doc basename
      match rather than the status folder-note itself. None for the ordinary status-note tick;
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
  today_str = flip_gate._today(today)
  text = asset_note.read_text()
  fm, fm_end = flip_gate._parse_frontmatter(text)
  body = text[fm_end:]
  markers = spec_job_markers.read(repo_root, asset_note)

  # one active coordinator job per asset — unconditional, no halt/command exception
  note_dirty = False
  coordinator_job = markers[JobMarker.COORDINATOR_JOB]
  if isinstance(coordinator_job, dict):
    job_info = coordinator_job
    marker = gate_tick._find_active_job_marker(
        repo_root, job_info[JobMarker.EXPERT], job_info[JobMarker.JOB_ID],
    )
    # guard: bundle carries no terminal marker yet — still running
    if marker is None:
      # the git-watch cursor advances past this item regardless of the noop below, so a
      # wake-worthy tick seen here would otherwise be lost the moment the job finishes with
      # nothing further changing the note (N2) — one sidecar flag, no note write, no commit;
      # job-done already means "wake me", so a later decline must never overwrite it
      wake_members = group_members if group_members is not None else (
          [ sibling_doc ] if sibling_doc is not None else []
      )
      # the review-active carve-out only ever applies to a genuine grouped tick — the plain
      # status-note and sibling-item shapes keep `_group_carries_wake`'s default `note_changed
      # = True`, which is an unconditional author check exactly as before this fix
      wake_note_changed = (
          _group_note_changed(item, asset_note, repo_root) if group_members is not None else True
      )
      if (
          markers.get(JobMarker.PENDING_WAKE) is None
          and _group_carries_wake(fm, body, item, wake_members, note_changed = wake_note_changed)
      ):
        spec_job_markers.update(repo_root, asset_note, { JobMarker.PENDING_WAKE: JobMarker.DECLINED })
      return { "action": "noop" }
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
              _DISPATCH_AUTHOR_NAME, job_info[JobMarker.TRIGGER],
              job_info[JobMarker.JOB_ID], today_str,
              lang = note_explainers.lang_for_note(asset_note),
          ),
      )
      # the WARNING line is the only note text this guard ever produces — the marker clear
      # itself is a sidecar write, so every other branch leaves the note byte-identical
      text = text[:fm_end] + body
      note_dirty = True
    else:
      gate_dispatch.consume_stale_job(repo_root, job_info[JobMarker.EXPERT], job_info[JobMarker.JOB_ID])
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
        repo_root, fm, body, item, markers, group_members, asset_note,
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
    trigger = _resolve_wake_trigger(repo_root, fm, body, item, markers)

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
    redeem_members = sorted(p for p in asset_dir.iterdir() if p.is_file() and p.name in _SIBLING_BASENAMES)
    trigger, group_transitions = _resolve_group_trigger(
        repo_root, fm, body, item, markers, redeem_members, asset_note,
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

  # guard: nothing wakes the coordinator this tick
  if trigger is None:
    # the dead-job WARNING line above still needs to land even with nothing left to dispatch;
    # a job merely consumed left no note text behind, so that tick writes nothing at all
    if note_dirty:
      asset_note.write_text(note_explainers.heal_note_text(asset_note, text))
      _commit(
          asset_dir, asset_note,
          f"{_DISPATCH_AUTHOR_NAME}: coordinator job died on {asset_dir.name}",
      )
    return { "action": "noop" }

  # a wake resolved on THIS asset — decide whether any OTHER asset waiting on it as a
  # dependency is worth waking too (C2), but only when THIS asset's own readiness gates
  # actually crossed to true against what this worker last recorded, not on every wake: an
  # operator prose edit or an unrelated command moves nothing a dependent cares about, and
  # queuing a coordinator job per dependent for it is a real headless spawn with real cost
  # (N1). One hop only regardless: `cur_ready` stays None on a `dependency_wake` call, so a
  # chain of dependents settles one reverse-hop per tick rather than fanning out recursively.
  # limit: a dependent already running its own job falls through the ordinary busy-guard above
  # and is flagged declined (this call's `item` is `{}`, which reads as non-bot), so it redeems
  # as OPERATOR_EDIT rather than DEPENDENCY_READY once free — the dispatch still happens, just
  # under the generic label; upgrade path is a dedicated pending-dependency wake token if that
  # label ever needs to survive the busy-guard
  cur_ready = None
  wake_dependents = False
  my_token = ""
  if dependency_wake is None:
    prev_ready = _read_marker_dict(fm, SpecCoordinatorReadyStateKey.STATE)
    cur_ready = {
        Gate.DEVELOP_DONE: flip_gate._is_true(fm, Gate.DEVELOP_DONE),
        Gate.TESTS_PASSING: flip_gate._is_true(fm, Gate.TESTS_PASSING),
    }
    wake_dependents = any(value and not prev_ready.get(key, False) for key, value in cur_ready.items())
    my_token = f"{asset_dir.parent.name}/{asset_dir.name}"

  # assemble and queue the coordinator job's wire bundle
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
      gate_dispatch._WireKey.EXPERT: _COORDINATOR_EXPERT,
      gate_dispatch._WireKey.PAYLOAD: payload,
      gate_dispatch._WireKey.SOURCE: source,
      gate_dispatch._WireKey.DEDUP_KEY: dedup_key,
  }
  # context is optional on the wire — only sent when there's actually something in it
  if context:
    bundle[gate_dispatch._WireKey.CONTEXT] = context
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

  # These three stamps land on EVERY exit past this point, stale-retire included (I6) — a
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
      and gate_tick._find_active_job_marker(repo_root, _COORDINATOR_EXPERT, job_id) is not None
  ):
    gate_dispatch.consume_stale_job(repo_root, _COORDINATOR_EXPERT, job_id)
    # the localized narrative tail of the History line, in the note's authoring language
    stale_tail = note_explainers.history_line(asset_note, HistoryEvent.DISPATCH_STALE,
                                              trigger = trigger, job_id = job_id)
    new_body = flip_gate._append_under_heading(
        body, Section.HISTORY, f"- {today_str} — {_DISPATCH_AUTHOR_NAME} · {stale_tail}",
    )
    asset_note.write_text(note_explainers.heal_note_text(asset_note, fm_text + new_body))
    _commit(
        asset_dir, asset_note,
        f"{_DISPATCH_AUTHOR_NAME}: stale dispatch for {trigger} on {asset_dir.name}",
    )

    # this asset's own dispatch already landed above — the reverse wake runs after, never
    # before, so a broken dependent can't strand it (N2)
    if wake_dependents:
      _wake_ready_dependents(asset_dir, my_token, today = today)

    # this tick's own trigger was retired, not dispatched — see the guard above
    return { "action": "dispatch-stale", "trigger": trigger, "job_id": job_id }

  # record the dispatched job in runtime state so the active-job guard blocks a second
  # concurrent dispatch — no note write, so this stamp costs no commit of its own and nothing
  # an operator editing the note can break
  spec_job_markers.update(repo_root, asset_note, { JobMarker.COORDINATOR_JOB: {
      JobMarker.TRIGGER: trigger,
      JobMarker.EXPERT: _COORDINATOR_EXPERT,
      JobMarker.JOB_ID: job_id,
  } })

  # record the wakeup in History, then one line per unresolved context path — never a silent skip
  # the localized narrative tail of the History line, in the note's authoring language
  woke_tail = note_explainers.history_line(asset_note, HistoryEvent.WOKE, trigger = trigger,
                                           expert = _COORDINATOR_EXPERT, job_id = job_id)
  new_body = flip_gate._append_under_heading(
      body, Section.HISTORY, f"- {today_str} — {_DISPATCH_AUTHOR_NAME} · {woke_tail}",
  )
  for warning in warnings:
    new_body = flip_gate._append_under_heading(
        new_body, Section.HISTORY, f"- {today_str} — {_DISPATCH_AUTHOR_NAME} · {warning}",
    )
  asset_note.write_text(note_explainers.heal_note_text(asset_note, fm_text + new_body))
  _commit(
      asset_dir, asset_note,
      f"{_DISPATCH_AUTHOR_NAME}: wake {trigger} on {asset_dir.name} → {_COORDINATOR_EXPERT} ({job_id})",
  )

  # this asset's own dispatch already landed above — the reverse wake runs after, never
  # before, so a broken dependent can't strand it (N2)
  if wake_dependents:
    _wake_ready_dependents(asset_dir, my_token, today = today)

  # the fresh dispatch this tick queued
  return {
      "action": "dispatched",
      "trigger": trigger,
      "expert": _COORDINATOR_EXPERT,
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
  status folder-note (`spec_role: status`) OR a sibling-doc basename (`_SIBLING_BASENAMES`) —
  `item["path"]` names whichever one matched. A sibling-doc item is resolved to its OWNING
  asset's status folder-note (the Obsidian folder-note convention, `<dir>/<dir>.md`) before
  dispatch; a sibling living outside an asset folder (a product-root `tech.md` / loose
  `design.md` — no coordinator-job tracking exists at that level) resolves the same convention
  to a folder-note that never carries `spec_role: status`, and is skipped.

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
      print(json.dumps({ "action": "noop" }))
      return 0
    fm, _ = flip_gate._parse_frontmatter(asset_note.read_text())
    # guard: an operator-zone folder-note (never `spec_role: status`) tracks no coordinator job
    if fm.get(SpecKey.ROLE) != _SPEC_ROLE_STATUS:
      print(json.dumps({ "action": "noop" }))
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

  # a sibling-doc basename match resolves to its OWNING asset's status folder-note; every other
  # match is the status folder-note itself (the routine's other `any_of` member)
  if changed.name in _SIBLING_BASENAMES:
    # guard: the sibling doc was deleted or moved between the git-watch scan and this dispatch
    if not changed.is_file():
      print(json.dumps({ "action": "noop" }))
      return 0
    asset_dir = changed.parent
    asset_note = asset_dir / f"{asset_dir.name}.md"
    # guard: no folder-note here, or it's an operator-zone one (a product-root sibling) rather
    # than an asset's own status note — nothing this worker tracks a coordinator job against
    if not asset_note.is_file():
      print(json.dumps({ "action": "noop" }))
      return 0
    fm, _ = flip_gate._parse_frontmatter(asset_note.read_text())
    if fm.get(SpecKey.ROLE) != _SPEC_ROLE_STATUS:
      print(json.dumps({ "action": "noop" }))
      return 0
    result = coordinator_dispatch(asset_note, item, today = args.today, sibling_doc = changed)
  else:
    # guard: the note was deleted or moved between the git-watch scan and this dispatch
    if not changed.is_file():
      print(json.dumps({ "action": "noop" }))
      return 0
    result = coordinator_dispatch(changed, item, today = args.today)

  # run the tick and report the result the same way every other lazycortex-specs worker does
  print(json.dumps(result))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
