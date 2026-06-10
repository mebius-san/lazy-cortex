"""Per-file gate-tick worker for the md-scan daemon.

Invoked once per matched asset status folder-note. It computes the lowest
gate in `GATE_ORDER` that is currently false and whose precondition holds,
then advances the asset one notch:

- A DERIVED gate (`spec_design_done` / `spec_plan_done`) is auto-flipped
  by calling `flip_gate.flip_gate(..., auto=True)` IN-PROCESS. This
  in-process call is the single code path and satisfies the
  "canonical primitive" requirement — the worker does not re-subprocess
  the CLI; it imports the sibling primitive and calls it directly so the
  callout / history / log side effects are produced exactly once by the
  one owner of those mutations.
- A HUMAN-SIGNAL gate (`spec_develop_done` / `spec_tests_passing` /
  `spec_released`) cannot be auto-derived: the worker appends a
  `[!ready]` callout to `## Gates` (once — idempotent) telling the
  operator how to flip it by hand.
- A previously-appended `[!ready]` callout whose precondition has since
  regressed is rewritten in place to a `[!info]` withdrawal callout.

The worker never emits task checkboxes — readiness is a callout, not a
to-do item.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error

import argparse
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

# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
import flip_gate  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
from spec_keys import (  # noqa: E402
    DERIVED_GATES,
    GATE_ORDER,
    Section,
    SiblingDoc,
    SpecKey,
    Stage,
    StageKey,
    TickAction,
)


# Marker fragments for locating the readiness callout in the body.
_READY_MARK = "[!ready]"
_READY_TAIL = " ready to flip"


# Stage-promotion rules — `gate_tick` § Step 0.
# Per `spec.lifecycle-protocol.md` Part 1: a doc whose review finalized as approved (or
# approved-with-concerns) advances `spec_stage` from `draft` to `approved`. Other stages are
# terminal (`approved`, `cancelled`) or operator-attention (`rejected`, `empty`); only `draft`
# is auto-promotable. The promotion mirrors what `/spec.set-stage <doc> approved` does
# interactively: rewrite the `spec_stage:` frontmatter value, update the `spec/<stage>` mirror
# tag in lock-step, append one `## History` line to the asset's status folder-note.
_APPROVED_REVIEW_RESULTS = frozenset({Stage.APPROVED, "approved-with-concerns"})
_STAGEABLE_SIBLINGS = (
    SiblingDoc.DESIGN,
    SiblingDoc.BUG,
    SiblingDoc.PLAN,
    "tech.md",
)
# Match `spec_stage: <token>` on its own frontmatter line. Group-less replacement is enough —
# the value is fully rewritten, no segment is preserved.
_SPEC_STAGE_RE = re.compile(r"(?m)^spec_stage\s*:.*$")
# Match a `- spec/<token>` mirror tag line under `tags:`. Group 1 captures the leading
# whitespace + `- spec/` prefix so the rewrite preserves the file's existing tag indentation.
_SPEC_TAG_RE = re.compile(r"(?m)^(\s+-\s+spec/)[A-Za-z0-9_\-]+\s*$")

# Bot identity for the stage-promotion atomic commit. Mirrors the pattern used by
# `spec.request-apply` / `spec.request-open` — promote-stage is an automated state advance,
# attributable to the routine, not to the operator.
_PROMOTE_AUTHOR_NAME = "spec.gate-tick"
_PROMOTE_AUTHOR_EMAIL = "spec.gate-tick@bot.lazy-cortex"


def _rewrite_doc_for_promotion(doc_path: Path) -> bool:
  """
  Rewrite one sibling doc's `spec_stage` and mirror tag when its review approves promotion.

  Conditions for the rewrite (ALL must hold): `review_result` is `approved` or
  `approved-with-concerns`, AND `spec_stage` is exactly `draft`. Any other stage value
  (`empty`, `approved`, `rejected`, `cancelled`) is left untouched — those are either
  terminal or operator-attention states that auto-promotion must not overwrite.

  Args:
    doc_path: The sibling authored doc to consider.

  Returns:
    True when the file was actually mutated; False on every other path (sibling missing, no
    frontmatter, review not approved, stage not `draft`).
  """
  # guard: sibling may not exist in this layout
  if not doc_path.is_file():
    return False
  text = doc_path.read_text()
  fm, fm_end = flip_gate._parse_frontmatter(text)
  # guard: no parseable frontmatter — nothing to promote
  if fm_end == 0:
    return False
  result_value = fm.get(SpecKey.REVIEW_RESULT, "").strip()
  # guard: review must show approval (clean or with-concerns) before stage flips
  if result_value not in _APPROVED_REVIEW_RESULTS:
    return False
  stage_value = fm.get(StageKey.STAGE, "").strip()
  # guard: only `draft` is auto-promotable; terminal / operator-attention stages are skipped
  if stage_value != Stage.DRAFT:
    return False
  fm_text = text[:fm_end]
  body = text[fm_end:]
  fm_text = _SPEC_STAGE_RE.sub(f"{StageKey.STAGE}: {Stage.APPROVED}", fm_text, count = 1)
  fm_text = _SPEC_TAG_RE.sub(rf"\g<1>{Stage.APPROVED}", fm_text, count = 1)
  doc_path.write_text(fm_text + body)
  return True


def _append_promotion_history(asset_note: Path, doc_name: str, today: str) -> None:
  """
  Append one `## History` line to the asset's status folder-note recording the promotion.

  Mirrors the `spec.set-stage` history format so doctor-side tag-vs-history consistency checks
  cannot tell auto-promotions from interactive ones.

  Args:
    asset_note: The status folder-note whose `## History` section receives the line.
    doc_name: Bare filename of the promoted sibling (e.g. `design.md`).
    today: ISO date string pinned into the history line.
  """
  text = asset_note.read_text()
  _, fm_end = flip_gate._parse_frontmatter(text)
  fm_text = text[:fm_end]
  body = text[fm_end:]
  line = (
      f"- {today} — {_PROMOTE_AUTHOR_NAME} · {doc_name} "
      f"spec_stage {Stage.DRAFT}→{Stage.APPROVED}"
  )
  body = flip_gate._append_under_heading(body, Section.HISTORY, line)
  asset_note.write_text(fm_text + body)


def _commit_promotions(asset_dir: Path, promoted_docs: list[str]) -> None:
  """
  Atomic git commit of the promoted sibling docs plus the folder-note history append.

  Stages every promoted sibling file and the asset's status folder-note, then commits under
  the dedicated bot identity. The commit subject names every promoted doc so the history
  scrolls naturally.

  Args:
    asset_dir: The asset folder holding the siblings and the status folder-note.
    promoted_docs: Bare filenames of the siblings that were just rewritten.
  """
  repo = flip_gate._repo_root(asset_dir)
  paths = [str(asset_dir / name) for name in promoted_docs]
  paths.append(str(asset_dir / f"{asset_dir.name}.md"))
  subprocess.run(
      ["git", "add", "--", *paths],
      cwd = str(repo), check = True, capture_output = True,
  )
  joined = ", ".join(promoted_docs)
  subject = (
      f"{_PROMOTE_AUTHOR_NAME}: promote spec_stage "
      f"{Stage.DRAFT}→{Stage.APPROVED} on {joined}"
  )
  subprocess.run(
      [
          "git",
          "-c", f"user.name={_PROMOTE_AUTHOR_NAME}",
          "-c", f"user.email={_PROMOTE_AUTHOR_EMAIL}",
          "-c", "commit.gpgsign=false",
          "commit", "-q", "-m", subject,
      ],
      cwd = str(repo), check = True, capture_output = True,
  )


def _commit_readiness_change(
    asset_dir: Path, asset_note: Path, gate: str, *, withdrawn: bool,
) -> None:
  """
  Atomic git commit of a readiness callout drop or withdrawal under `spec.gate-tick`.

  Without this commit the worker's `asset_note.write_text(...)` leaves the folder-note dirty,
  tripping the daemon's dirty-tree-skip guard on the next iteration and silently halting every
  routine on the asset. Defensive skip when the asset is not inside a git repository (the
  unit-test fixture path that exercises the worker against a bare tmp dir).

  Args:
    asset_dir: The asset folder; used to resolve the enclosing repo root for the `git` cwd.
    asset_note: The status folder-note path that was just rewritten.
    gate: The gate whose readiness callout was dropped or withdrawn.
    withdrawn: True when the prior `[!ready]` was replaced by `[!info] readiness withdrawn`;
      False when a fresh `[!ready]` was appended. Drives the commit subject.
  """
  top = flip_gate._git_field(asset_dir, ["rev-parse", "--show-toplevel"], "")
  # guard: asset is not inside a git repository — skip commit (test-fixture path); the file
  # write above remains and is the entire mutation the bare-fixture caller observes
  if not top:
    return
  repo = Path(top)
  subprocess.run(
      ["git", "add", "--", str(asset_note)],
      cwd = str(repo), check = True, capture_output = True,
  )
  action = "withdraw readiness" if withdrawn else "drop readiness callout"
  subject = f"{_PROMOTE_AUTHOR_NAME}: {action} for {gate} on {asset_dir.name}"
  subprocess.run(
      [
          "git",
          "-c", f"user.name={_PROMOTE_AUTHOR_NAME}",
          "-c", f"user.email={_PROMOTE_AUTHOR_EMAIL}",
          "-c", "commit.gpgsign=false",
          "commit", "-q", "-m", subject,
      ],
      cwd = str(repo), check = True, capture_output = True,
  )


def _advance_stages_from_review(asset_dir: Path, asset_note: Path, today: str) -> list[str]:
  """
  Promote every sibling whose review approved the doc and whose stage is `draft`.

  Walks the four authored-doc siblings (`design.md`, `bug.md`, `plan.md`, `tech.md`), promotes
  each whose conditions hold (see `_rewrite_doc_for_promotion`), appends one history line per
  promotion to the asset's status folder-note, and atomically commits if anything was rewritten.

  Args:
    asset_dir: The asset folder containing the siblings and the status folder-note.
    asset_note: The asset's status folder-note path.
    today: ISO date string forwarded into the history lines.

  Returns:
    Bare filenames of the promoted siblings, in walk order; empty when nothing was promoted.
  """
  promoted: list[str] = []
  for name in _STAGEABLE_SIBLINGS:
    doc = asset_dir / name
    # guard: this sibling did not meet the promotion conditions — skip without writing
    if not _rewrite_doc_for_promotion(doc):
      continue
    promoted.append(name)
    _append_promotion_history(asset_note, name, today)
  # guard: nothing was promoted this tick — leave the index clean, skip the commit
  if not promoted:
    return promoted
  _commit_promotions(asset_dir, promoted)
  return promoted


def _next_flippable(asset_dir: Path, fm: dict, stages: dict) -> str | None:
  """
  Find the lowest false gate whose precondition currently holds.

  Returns:
    The gate key to advance, or None when no gate is both false and ready.
  """
  for gate in GATE_ORDER:
    # guard: only consider gates that are not already true
    if flip_gate._is_true(fm, gate):
      continue
    if flip_gate.preconditions_met(asset_dir, gate, fm, stages):
      return gate
  return None


def _prev_gate(gate: str) -> str | None:
  """
  Return the gate immediately preceding `gate` in `GATE_ORDER`.

  Returns:
    The predecessor gate key, or None when `gate` is the first in order.
  """
  idx = GATE_ORDER.index(gate)
  # guard: first gate has no predecessor
  if idx == 0:
    return None
  return GATE_ORDER[idx - 1]


def _ready_callout(gate: str, slug: str) -> str:
  """
  Build the multi-line `[!ready]` callout for a human-signal gate.

  Returns:
    The callout block text (no trailing newline).
  """
  prev = _prev_gate(gate)
  pre_line = f"{prev} = true" if prev else "all derived gates resolved"
  return (
      f"> [!ready] {gate} ready to flip\n"
      f"> preconditions met: {pre_line}.\n"
      f"> to flip — run `/spec.flip-gate {slug} {gate}`."
  )


def _withdrawn_callout(gate: str) -> str:
  """
  Build the `[!info]` readiness-withdrawal callout.

  Returns:
    The single-line callout text (no trailing newline).
  """
  return f"> [!info] readiness withdrawn — {gate} precondition no longer met"


def _find_ready_block(body: str, gate: str) -> tuple[int, int] | None:
  """
  Locate the `[!ready]` callout block for `gate` in `body`.

  The block spans the `[!ready]` heading line and every immediately
  following `>`-prefixed continuation line.

  Returns:
    A `(start_line, end_line)` half-open line-index range, or None when no
    such block exists.
  """
  lines = body.splitlines()
  head = f"> {_READY_MARK} {gate}{_READY_TAIL}"
  for i, ln in enumerate(lines):
    if ln.strip() == head:
      end = i + 1
      while end < len(lines) and lines[end].startswith(">"):
        end += 1
      return i, end
  return None


def _has_ready(body: str, gate: str) -> bool:
  """
  Return whether a `[!ready]` callout for `gate` already exists.

  Returns:
    True when the readiness callout is present in the body.
  """
  return _find_ready_block(body, gate) is not None


def _append_callout(body: str, block: str) -> str:
  """
  Append a callout block under the `## Gates` section.

  Returns:
    The body text with the block inserted at the end of the Gates section.
  """
  lines = body.splitlines()
  head_idx = None
  for i, ln in enumerate(lines):
    if ln.strip() == Section.GATES:
      head_idx = i
      break
  # guard: no Gates section — append a fresh one at end of body
  if head_idx is None:
    suffix = "" if body.endswith("\n") else "\n"
    return body + f"{suffix}\n{Section.GATES}\n\n{block}\n"
  insert_at = len(lines)
  for j in range(head_idx + 1, len(lines)):
    # guard: stop before the next markdown heading
    if lines[j].startswith("#"):
      insert_at = j
      break
  end = insert_at
  while end > head_idx + 1 and not lines[end - 1].strip():
    end -= 1
  new_lines = [*lines[:end], block, *lines[end:]]
  return "\n".join(new_lines) + ("\n" if body.endswith("\n") else "")


def _replace_block(body: str, span: tuple[int, int], block: str) -> str:
  """
  Replace the line range `span` in `body` with `block`.

  Returns:
    The body text with the spanned lines swapped for the block.
  """
  lines = body.splitlines()
  start, end = span
  new_lines = [*lines[:start], block, *lines[end:]]
  return "\n".join(new_lines) + ("\n" if body.endswith("\n") else "")


def gate_tick(asset_note: Path, today: str | None = None) -> dict:
  """
  Advance one asset's gates by a single notch.

  Auto-flips the next derived gate when ready, drops a one-time readiness
  callout for the next human-signal gate, or withdraws a stale readiness
  callout whose precondition has regressed. A no-op when nothing applies.

  Args:
    asset_note: The status folder-note path; its parent is the asset dir.
    today: Optional ISO date forwarded to the flip primitive for callouts.

  Returns:
    A result dict whose `action` is one of `auto-flipped`, `ready-callout`,
    `readiness-withdrawn`, or `noop`, with the affected `gate` when not a no-op.
  """
  asset_dir = asset_note.parent
  today_str = flip_gate._today(today)
  # Step 0 — sibling-doc stage promotion (per README/overview promise: "Drive an asset's
  # readiness gates AND per-file stages"). When a sibling doc's review finalized as approved
  # and its `spec_stage` is still `draft`, flip the stage in lock-step with its mirror tag and
  # append the asset's `## History`. Return early — the gate-flip pass on the next tick reads
  # the freshly promoted stages and advances `spec_design_done` / `spec_plan_done` naturally.
  promoted = _advance_stages_from_review(asset_dir, asset_note, today_str)
  # guard: a promotion happened this tick — surface it and let the next tick advance gates
  if promoted:
    return {TickAction.ACTION: TickAction.STAGE_PROMOTED, "docs": promoted}
  text = asset_note.read_text()
  fm, fm_end = flip_gate._parse_frontmatter(text)
  body = text[fm_end:]
  stages = flip_gate._collect_stages(asset_dir)
  # First reconcile any stale readiness callout against current preconditions.
  for gate in GATE_ORDER:
    span = _find_ready_block(body, gate)
    # guard: only withdraw a present callout whose precondition no longer holds
    if span is not None and not flip_gate.preconditions_met(asset_dir, gate, fm, stages):
      new_body = _replace_block(body, span, _withdrawn_callout(gate))
      asset_note.write_text(text[:fm_end] + new_body)
      _commit_readiness_change(asset_dir, asset_note, gate, withdrawn = True)
      return {TickAction.ACTION: TickAction.READINESS_WITHDRAWN, "gate": gate}
  # `next_gate` (not `gate`) — the loop variable above narrows `gate` to `str`, so reassigning
  # the variable to `_next_flippable(...)` (returns `str | None`) widens the type and trips
  # mypy strict variable-narrowing on the loop-binding leak.
  next_gate = _next_flippable(asset_dir, fm, stages)
  # guard: nothing false-and-ready to advance
  if next_gate is None:
    return {TickAction.ACTION: TickAction.NOOP}
  if next_gate in DERIVED_GATES:
    source = flip_gate._design_doc_name(asset_dir) if next_gate == GATE_ORDER[0] else "plan.md"
    flip_gate.flip_gate(
        asset_dir, next_gate, auto = True, reason = f"{source} approved", today = today,
    )
    return {TickAction.ACTION: TickAction.AUTO_FLIPPED, "gate": next_gate}
  # Human-signal gate: append the readiness callout once.
  if _has_ready(body, next_gate):
    return {TickAction.ACTION: TickAction.NOOP}
  new_body = _append_callout(body, _ready_callout(next_gate, asset_dir.name))
  asset_note.write_text(text[:fm_end] + new_body)
  _commit_readiness_change(asset_dir, asset_note, next_gate, withdrawn = False)
  return {TickAction.ACTION: TickAction.READY_CALLOUT, "gate": next_gate}


def main(argv: list[str]) -> int:
  """
  Advance one asset's gates from the command line, printing the result as JSON.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success, 2 when the asset note is missing.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs gate-tick")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("asset_note", type = Path)
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--today", default = None,
                      # waiver: one-off human-facing message -- argparse help text
                      help = "ISO date pinned into emitted callouts")
  args = parser.parse_args(argv)
  asset_note: Path = args.asset_note.resolve()
  # guard: asset status folder-note must exist
  if not asset_note.is_file():
    sys.stderr.write(f"no status folder-note: {asset_note}\n")
    return 2
  result = gate_tick(asset_note, today = args.today)
  print(json.dumps(result))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
