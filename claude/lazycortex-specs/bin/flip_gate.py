"""Declarative gate-flip primitive for spec assets.

An asset is a folder `<spec_path>/<category>/<slug>/` holding a status
folder-note `<slug>/<slug>.md` whose frontmatter carries flat boolean
gates (`spec_design_done`, `spec_plan_done`, `spec_develop_done`,
`spec_tests_passing`, `spec_released`) plus a `spec_cancelled` flag, and
sibling authored docs (`design.md` + `plan.md`, or `bug.md` + `plan.md`
for the built-in `bug` category) carrying a per-file `spec_stage`.

`flip_gate` moves one gate from false to true (or, with `off`, back to
false). A false→true flip is allowed only when the gate's precondition in
the contract table holds; a refused flip mutates no files. An `off` flip
skips precondition checks (turning a gate off is always allowed) but is
still refused while the asset is cancelled.

Design choice — the `auto` flag controls ONLY the callout annotation; the
primitive always performs the mutation when called. The interactive
operator-confirm for human-signal gates lives in the Claude-side skill,
not in this primitive: callers that need a confirm gate apply it before
invoking `flip_gate`.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
  sys.path.insert(0, str(_BIN))

# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
from spec_keys import (  # noqa: E402
    BOOL_TRUE,
    FLIP_GATE_NAME,
    LOG_CLAUDE,
    LOG_NO_GIT,
    LOG_ROOT,
    PLAN_OPENABLE_STAGES,
    FlipResult,
    Gate,
    PlanReview,
    Section,
    SiblingDoc,
    Stage,
    StageKey,
)
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
from summary_render import parent_container_note, apply_container_stats  # noqa: E402


# Per-file stages that count as "accepted" for a derived-gate precondition.
_ACCEPTED_STAGES = frozenset({Stage.APPROVED, Stage.CANCELLED})


# Used by `_promote_to_draft_if_empty` to rewrite spec_stage scalars + the spec/<stage> mirror
# tag in a single pass. Same shape as the gate-tick promotion regexes so a doctor scan reading
# either worker's commits sees identical wire format.
_SPEC_STAGE_RE = re.compile(r"(?m)^spec_stage\s*:.*$")
_SPEC_TAG_RE = re.compile(r"(?m)^(\s+-\s+spec/)[A-Za-z0-9_\-]+\s*$")


def _today(today: str | None) -> str:
  """
  Return the effective date string for callout and history lines.

  Returns:
    The supplied `today` when given, else the current UTC date in ISO form.
  """
  # guard: caller-supplied date wins so tests pin deterministic output
  if today is not None:
    return today
  return datetime.now(UTC).date().isoformat()


def _parse_frontmatter(text: str) -> tuple[dict, int]:
  """
  Parse the leading YAML frontmatter block of a file's text.

  Returns:
    A two-tuple `(values, fm_end_idx)` where `values` is a flat dict of
    top-level scalar keys and `fm_end_idx` is the index just past the closing
    `---` line; `({}, 0)` when there is no parseable frontmatter.
  """
  if not text.startswith("---\n"):
    return {}, 0
  rest = text[4:]
  end_idx = rest.find("\n---\n")
  if end_idx < 0:
    return {}, 0
  block = rest[:end_idx]
  # waiver: inline numeric literal -- length of the leading '---\n' fence consumed above
  fm_end = 4 + end_idx + len("\n---\n")
  values: dict = {}
  for line in block.splitlines():
    stripped = line.lstrip()
    # guard: skip blank lines and comment / bullet markers
    if not stripped or stripped.startswith(("#", "-")):
      continue
    # guard: skip lines without a key:value separator
    if ":" not in line:
      continue
    k, _, v = line.partition(":")
    k = k.strip()
    # guard: skip entries with an empty key
    if not k:
      continue
    values[k] = v.strip()
  return values, fm_end


def _is_true(values: dict, key: str) -> bool:
  """
  Return whether a frontmatter boolean key reads as true.

  Returns:
    True when the key's value is the literal `true`; False otherwise.
  """
  return values.get(key, "").strip().lower() == BOOL_TRUE


def _sibling_stage(asset_dir: Path, name: str) -> str | None:
  """
  Read the `spec_stage` of a sibling authored doc.

  Returns:
    The doc's `spec_stage` value, or None when the sibling is absent or
    carries no stage key.
  """
  doc = asset_dir / name
  # guard: sibling may not exist in this layout
  if not doc.is_file():
    return None
  fm, _ = _parse_frontmatter(doc.read_text())
  return fm.get(StageKey.STAGE)


def _design_doc_name(asset_dir: Path) -> str:
  """
  Resolve the design-side doc name for the asset's layout.

  Returns:
    `bug.md` for the bug layout (a `bug.md` sibling exists and no
    `design.md` does), else `design.md`.
  """
  has_bug = (asset_dir / SiblingDoc.BUG).is_file()
  has_design = (asset_dir / SiblingDoc.DESIGN).is_file()
  # guard: bug layout is bug.md present and design.md absent
  if has_bug and not has_design:
    return SiblingDoc.BUG
  return SiblingDoc.DESIGN


def preconditions_met(asset_dir: Path, gate: str, fm: dict, stages: dict) -> bool:
  """
  Check whether a false→true flip of `gate` satisfies the contract table.

  The `stages` mapping holds the sibling doc names (`design.md` / `bug.md`,
  `plan.md`) to their current `spec_stage` values; `fm` is the folder-note's
  parsed frontmatter.

  Returns:
    True when the gate's precondition holds; False otherwise.
  """
  if gate == Gate.DESIGN_DONE:
    design_name = _design_doc_name(asset_dir)
    return stages.get(design_name) in _ACCEPTED_STAGES
  if gate == Gate.PLAN_DONE:
    return _is_true(fm, Gate.DESIGN_DONE) and stages.get(SiblingDoc.PLAN) in _ACCEPTED_STAGES
  if gate == Gate.DEVELOP_DONE:
    return _is_true(fm, Gate.PLAN_DONE)
  if gate == Gate.TESTS_PASSING:
    return _is_true(fm, Gate.DEVELOP_DONE)
  if gate == Gate.RELEASED:
    return _is_true(fm, Gate.TESTS_PASSING)
  return False


def _collect_stages(asset_dir: Path) -> dict:
  """
  Read every sibling doc stage relevant to the precondition table.

  Returns:
    A mapping of sibling doc name to its `spec_stage`, omitting absent docs.
  """
  stages: dict = {}
  for name in ("design.md", "bug.md", "plan.md"):
    stage = _sibling_stage(asset_dir, name)
    # guard: only record siblings that exist
    if stage is not None:
      stages[name] = stage
  return stages


def _set_bool(fm_text: str, key: str, value: bool) -> str:
  """
  Set or insert `key: <true|false>` in a frontmatter block.

  Replaces the existing line in place when the key is present; inserts before
  the closing `---` when absent.

  Returns:
    The updated frontmatter text.
  """
  literal = "true" if value else "false"
  pat = re.compile(rf"(?m)^{re.escape(key)}\s*:.*$")
  if pat.search(fm_text):
    return pat.sub(f"{key}: {literal}", fm_text, count = 1)
  close_idx = fm_text.rfind("---\n")
  # guard: malformed frontmatter without a closing fence
  if close_idx < 0:
    return fm_text
  return fm_text[:close_idx] + f"{key}: {literal}\n" + fm_text[close_idx:]


def _append_under_heading(body: str, heading: str, line: str) -> str:
  """
  Append `line` to the section opened by `heading` in `body`.

  Inserts after the heading and any existing section lines, before the next
  ATX heading (`^#{1,6}\\s`); appends a fresh section at end-of-body when
  the heading is absent. Lines beginning with `#` but no space (e.g.
  `#protected/spec/…` tags) are NOT treated as section boundaries.

  Returns:
    The body text with the new line placed inside the named section.
  """
  lines = body.splitlines()
  head_idx = None
  for i, ln in enumerate(lines):
    if ln.strip() == heading:
      head_idx = i
      break
  # guard: heading missing — append a fresh section
  if head_idx is None:
    suffix = "" if body.endswith("\n") else "\n"
    return body + f"{suffix}\n{heading}\n\n{line}\n"
  insert_at = len(lines)
  for j in range(head_idx + 1, len(lines)):
    # guard: stop before the next real ATX heading; a `#protected/...` tag
    # line has no space after `#` and is NOT a boundary
    if re.match(r"^#{1,6}\s", lines[j]):
      insert_at = j
      break
  # Trim trailing blanks inside the section so the new line sits flush.
  end = insert_at
  while end > head_idx + 1 and not lines[end - 1].strip():
    end -= 1
  new_lines = [*lines[:end], line, *lines[end:]]
  return "\n".join(new_lines) + ("\n" if body.endswith("\n") else "")


def _write_log(
    asset_dir: Path, gate: str, value: bool, reason: str, *, plan_review: str | None = None,
) -> None:
  """
  Write a run-log file for this flip under the spec.flip-gate log dir.

  Args:
    asset_dir: The asset folder the flip was applied to.
    gate: The gate key that was flipped.
    value: The boolean the gate was set to.
    reason: Optional human-or-source note recorded with the flip.
    plan_review: The post-flip plan-review auto-open status, or None when the
      follow-up did not apply to this flip.
  """
  cwd = asset_dir
  sha = _git_field(cwd, ["rev-parse", "HEAD"], LOG_NO_GIT)
  branch = _git_field(cwd, ["rev-parse", "--abbrev-ref", "HEAD"], LOG_NO_GIT)
  ts = datetime.now(UTC)
  stamp = ts.strftime("%Y-%m-%d_%H-%M-%S")
  date_str = ts.strftime("%Y-%m-%d %H:%M:%S UTC")
  log_dir = _repo_root(cwd) / LOG_ROOT / LOG_CLAUDE / FLIP_GATE_NAME
  log_dir.mkdir(parents = True, exist_ok = True)
  # guard: record the plan-review follow-up line only when the follow-up applied
  plan_line = f"- plan.md review auto-open: {plan_review}\n" if plan_review is not None else ""
  body = (
      "---\n"
      f"git_sha: {sha}\n"
      f"git_branch: {branch}\n"
      f"date: {date_str}\n"
      f"input: flip-gate {asset_dir.name} {gate} (value={value}, reason={reason or 'none'})\n"
      "---\n\n"
      "# spec.flip-gate\n\n"
      "## Actions\n\n"
      f"- flipped `{gate}` → {str(value).lower()} on `{asset_dir.name}`\n"
      f"{plan_line}\n"
      "## Result\n\n"
      f"- success — `{gate}` set to {str(value).lower()}\n"
  )
  (log_dir / f"{stamp}.md").write_text(body)


def _git_field(cwd: Path, args: list[str], fallback: str) -> str:
  """
  Run a read-only `git` query, returning a fallback on any failure.

  Returns:
    The trimmed git output, or `fallback` when git is unavailable or errors.
  """
  try:
    out = subprocess.run(
        ["git", *args], cwd = cwd, check = True, capture_output = True, text = True,
    )
  except (subprocess.CalledProcessError, FileNotFoundError):
    return fallback
  return out.stdout.strip() or fallback


def _repo_root(cwd: Path) -> Path:
  """
  Resolve the git repo root for log placement, falling back to `cwd`.

  Returns:
    The repository top-level `Path`, or `cwd` when not inside a git repo.
  """
  top = _git_field(cwd, ["rev-parse", "--show-toplevel"], "")
  # guard: not a git repo — log beside the asset
  if not top:
    return cwd
  return Path(top)


def _resolve_review_cli() -> Path | None:
  """
  Find the `lazycortex-review` CLI binary via the plugin-dir env contract.

  Walks `$LAZYCORTEX_PLUGIN_DIRS` (exported by the daemon for every
  subprocess routine) for `<dir>/bin/lazycortex-review`, mirroring the
  resolution pattern in `lazycortex-review/bin/dispatcher.py`. No
  plugin-cache fallback is attempted — the post-flip auto-open is
  best-effort and a missing CLI degrades to a logged skip.

  Returns:
    Absolute path to the resolved binary, or None when no plugin dir
    on the env path carries a `bin/lazycortex-review` entry.
  """
  dirs = os.environ.get(PlanReview.PLUGIN_DIRS_ENV, "").split(os.pathsep)
  for d in dirs:
    # guard: empty path segment (from a trailing/double pathsep) — skip it
    if not d:
      continue
    cli = Path(d) / PlanReview.BIN_DIR / PlanReview.REVIEW_CLI
    if cli.is_file():
      return cli
  return None


# waiver: `fm_after` is part of the prescribed helper signature (post-flip folder-note
# frontmatter, passed by the caller); the plan-side checks read `plan.md` directly, so the
# folder-note view is currently unused but kept on the wire for signature stability.
# pylint: disable=unused-argument
def _auto_open_plan_review(asset_dir: Path, gate: str, off: bool, fm_after: dict) -> str | None:
  """
  Open review on the sibling `plan.md` after a forward `spec_design_done` flip.

  Only applies to a forward (`off` is False) flip of `spec_design_done`;
  every other gate and every `--off` flip returns None (not applicable).
  When applicable, the sibling `plan.md` is opened into review only if its
  `spec_stage` is empty or draft AND it is not already in active review.

  The review-open is best-effort: it subprocesses the `lazycortex-review`
  CLI's `start` verb via the `$LAZYCORTEX_PLUGIN_DIRS` boundary contract,
  and ANY failure (CLI not resolvable, non-zero exit, timeout) degrades to a
  logged skip — the already-committed gate flip is never undone or reported
  as failed because the follow-up could not run.

  Args:
    asset_dir: The asset folder holding the sibling `plan.md`.
    gate: The gate that was just flipped.
    off: Whether the flip was an `--off` (backward) flip.
    fm_after: Parsed frontmatter of the folder-note after the flip.

  Returns:
    A short status token (`opened`, `skip:stage`, `skip:active`,
    `skip:no-plan`, `skip:review-cli-unavailable`), or None when the
    follow-up does not apply to this flip.
  """
  # guard: only a forward spec_design_done flip has a plan.md follow-up
  if off or gate != Gate.DESIGN_DONE:
    return None
  plan = asset_dir / SiblingDoc.PLAN
  # guard: no plan.md sibling — nothing to open
  if not plan.is_file():
    return PlanReview.SKIP_NO_PLAN
  plan_fm, _ = _parse_frontmatter(plan.read_text())
  # guard: plan.md past the openable stage set (e.g. already approved)
  if plan_fm.get(StageKey.STAGE) not in PLAN_OPENABLE_STAGES:
    return PlanReview.SKIP_STAGE
  # guard: plan.md already opted into review — do not re-open
  if _is_true(plan_fm, PlanReview.REVIEW_ACTIVE_KEY):
    return PlanReview.SKIP_ACTIVE
  # Promote `spec_stage: empty → draft` BEFORE opening review. Lifecycle protocol Part 1 says
  # `draft` covers "review_active: true (in the loop)" — opening review on a plan whose stage is
  # still `empty` would land a committed state that contradicts the mapping (review_active=true
  # alongside spec_stage=empty). Flipping first means the lazy-review.start opt-in commit lands
  # on an already-consistent doc. Idempotent — `draft` (the other PLAN_OPENABLE_STAGES member)
  # produces no change and skips the commit.
  _promote_to_draft_if_empty(asset_dir, plan, plan_fm)
  cli = _resolve_review_cli()
  # guard: review CLI not resolvable on the env path — degrade to a skip
  if cli is None:
    return PlanReview.SKIP_CLI_UNAVAILABLE
  try:
    proc = subprocess.run(
        [str(cli), PlanReview.START_VERB, str(plan.resolve())],
        capture_output = True, text = True, timeout = PlanReview.START_TIMEOUT_S, check = False,
    )
  # waiver: fire-and-forget follow-up — the gate flip already succeeded and committed;
  # ANY review-open failure (CLI crash, timeout, unimplemented verb) must degrade to a
  # logged skip, never abort or undo the flip. See lazy-specs functional-spec § Stage 5.
  except (OSError, subprocess.SubprocessError):
    return PlanReview.SKIP_CLI_UNAVAILABLE
  # guard: non-zero exit (verb not wired yet, bad path, internal error) — skip, don't fail
  if proc.returncode != 0:
    return PlanReview.SKIP_CLI_UNAVAILABLE
  return PlanReview.OPENED


_FLIP_AUTHOR_NAME = FLIP_GATE_NAME
_FLIP_AUTHOR_EMAIL = f"{FLIP_GATE_NAME}@bot.lazy-cortex"


def _commit_flip(asset_dir: Path, note: Path, gate: str, value: bool) -> None:
  """
  Atomically commit the folder-note flip under the `spec.flip-gate` bot identity.

  Stages the single status folder-note and commits with a deterministic subject naming the gate
  and its new value. Skipped silently when the asset does not live inside a git repository (the
  unit-test fixture path, where the worker is exercised against a bare tmp dir). The daemon
  always runs the routine inside the operator's repo, so production reaches the commit branch
  every time. Any subprocess error inside the commit branch propagates — the flip is a state
  mutation the caller promised was atomic, and silently swallowing a commit failure would leave
  the daemon's dirty-tree guard tripping every subsequent iteration with no visible cause.

  Args:
    asset_dir: The asset folder; used to resolve the enclosing repo root for the `git` cwd.
    note: The folder-note path that was just rewritten.
    gate: The gate key that was flipped.
    value: The boolean value the gate was set to.
  """
  top = _git_field(asset_dir, ["rev-parse", "--show-toplevel"], "")
  # guard: asset is not inside a git repository — skip commit (test-fixture path); the file
  # write above remains and is the entire mutation the bare-fixture caller observes
  if not top:
    return
  repo = Path(top)
  add_paths = [str(note)]
  parent = parent_container_note(asset_dir)
  if parent is not None and apply_container_stats(parent):
    add_paths.append(str(parent))
  subprocess.run(
      ["git", "add", "--", *add_paths],
      cwd = str(repo), check = True, capture_output = True,
  )
  subject = f"{FLIP_GATE_NAME}: {gate} → {str(value).lower()} on {asset_dir.name}"
  subprocess.run(
      [
          "git",
          "-c", f"user.name={_FLIP_AUTHOR_NAME}",
          "-c", f"user.email={_FLIP_AUTHOR_EMAIL}",
          "-c", "commit.gpgsign=false",
          "commit", "-q", "-m", subject,
      ],
      cwd = str(repo), check = True, capture_output = True,
  )


def _promote_to_draft_if_empty(asset_dir: Path, plan: Path, plan_fm: dict) -> bool:
  """
  Promote `plan.md` from `spec_stage: empty` to `draft` if currently empty; no-op otherwise.

  Called by `_auto_open_plan_review` BEFORE the `lazycortex-review start` subprocess so the
  opt-in commit lands on an already-consistent doc. Lifecycle protocol § Part 1 maps
  `spec_stage: draft` to "review_active: true (in the loop)" — opening review on an `empty`
  doc and leaving its stage at `empty` would land a committed state that contradicts the
  mapping. Doing this BEFORE the subprocess means git history never carries the inconsistent
  intermediate snapshot.

  Mutation set: rewrites `spec_stage:` value in plan's frontmatter, rewrites the
  `- spec/<stage>` mirror tag in lock-step, appends one `# History` line to the asset's status
  folder-note, atomic git commit under `spec.flip-gate@bot.lazy-cortex`. Skipped silently when
  the asset is not inside a git repository (matches `_commit_flip`'s test-fixture defence).

  Args:
    asset_dir: The asset folder holding both `plan.md` and the status folder-note.
    plan: The `plan.md` path inside `asset_dir`.
    plan_fm: Pre-parsed plan frontmatter (saves a second read).

  Returns:
    True when the file was rewritten and the transition recorded; False when `plan.md` was
    already at `draft` (the only other PLAN_OPENABLE_STAGES member) and no mutation applied.
  """
  current = plan_fm.get(StageKey.STAGE, "").strip()
  # guard: only `empty` is auto-promotable to `draft` here; `draft` is the no-op fast-path
  if current != Stage.EMPTY:
    return False
  text = plan.read_text()
  _, fm_end = _parse_frontmatter(text)
  fm_text = text[:fm_end]
  body = text[fm_end:]
  fm_text = _SPEC_STAGE_RE.sub(f"{StageKey.STAGE}: {Stage.DRAFT}", fm_text, count = 1)
  fm_text = _SPEC_TAG_RE.sub(rf"\g<1>{Stage.DRAFT}", fm_text, count = 1)
  plan.write_text(fm_text + body)
  # Append one history line to the asset's status folder-note.
  note = asset_dir / f"{asset_dir.name}.md"
  note_text = note.read_text()
  _, note_fm_end = _parse_frontmatter(note_text)
  note_fm_text = note_text[:note_fm_end]
  note_body = note_text[note_fm_end:]
  date_str = _today(None)
  hist = f"- {date_str} — {FLIP_GATE_NAME} · {plan.name} spec_stage {Stage.EMPTY}→{Stage.DRAFT}"
  note_body = _append_under_heading(note_body, Section.HISTORY, hist)
  note.write_text(note_fm_text + note_body)
  _commit_promote_to_draft(asset_dir, plan, note)
  return True


def _commit_promote_to_draft(asset_dir: Path, plan: Path, note: Path) -> None:
  """
  Atomically commit the plan `empty → draft` flip plus the folder-note history append.

  Defensive skip when the asset is not inside a git repository — matches `_commit_flip` so the
  unit-test fixture path (bare tmp dir without `git init`) keeps working without a commit.

  Args:
    asset_dir: The asset folder; used to resolve the enclosing repo root for the `git` cwd.
    plan: The plan.md path that was rewritten.
    note: The asset's status folder-note path that was appended.
  """
  top = _git_field(asset_dir, ["rev-parse", "--show-toplevel"], "")
  # guard: asset is not inside a git repository — skip commit (test-fixture path); the file
  # writes above remain and are the entire mutation the bare-fixture caller observes
  if not top:
    return
  repo = Path(top)
  subprocess.run(
      ["git", "add", "--", str(plan), str(note)],
      cwd = str(repo), check = True, capture_output = True,
  )
  subject = (
      f"{FLIP_GATE_NAME}: {plan.name} spec_stage "
      f"{Stage.EMPTY}→{Stage.DRAFT} on {asset_dir.name}"
  )
  subprocess.run(
      [
          "git",
          "-c", f"user.name={_FLIP_AUTHOR_NAME}",
          "-c", f"user.email={_FLIP_AUTHOR_EMAIL}",
          "-c", "commit.gpgsign=false",
          "commit", "-q", "-m", subject,
      ],
      cwd = str(repo), check = True, capture_output = True,
  )


def flip_gate(
    asset_dir: Path,
    gate: str,
    *,
    off: bool = False,
    auto: bool = False,
    reason: str = "",
    today: str | None = None,
) -> dict:
  """
  Flip one boolean gate on an asset's status folder-note.

  A false→true flip is refused (no file mutation) when the gate's
  precondition does not hold; an `off` flip skips precondition checks. Any
  flip is refused while the asset is cancelled. On success the folder-note
  frontmatter is rewritten, a `[!gate]` callout is appended to `# Gates`, a
  line is appended to `# History`, and a run-log file is written.

  Args:
    asset_dir: The asset folder holding `<asset_dir.name>.md` and siblings.
    gate: The `spec_*` gate key to flip.
    off: When True, set the gate to false (precondition checks skipped).
    auto: When True, annotate the callout with an `auto:` prefix.
    reason: Optional human-or-source note recorded in the callout.
    today: Optional ISO date pinned into the callout and history line.

  Returns:
    `{"status": "flipped", "gate": gate, "value": <bool>}` on success, or
    `{"status": "refused", "gate": gate, "reason": <message>}` when refused.
  """
  note = asset_dir / f"{asset_dir.name}.md"
  text = note.read_text()
  fm_values, fm_end = _parse_frontmatter(text)
  # guard: a cancelled asset refuses every flip, on or off
  if _is_true(fm_values, Gate.SPEC_CANCELLED):
    return {FlipResult.STATUS: FlipResult.REFUSED, "gate": gate, "reason": "asset is cancelled"}
  stages = _collect_stages(asset_dir)
  value = not off
  if not off and not preconditions_met(asset_dir, gate, fm_values, stages):
    return {
        FlipResult.STATUS: FlipResult.REFUSED,
        "gate": gate,
        "reason": f"precondition not met for {gate}",
    }
  fm_text = _set_bool(text[:fm_end], gate, value)
  body = text[fm_end:]
  date_str = _today(today)
  note_text = (reason or "auto") if not auto else f"auto: {reason}" if reason else "auto"
  callout = f"> [!gate] {gate} — flipped {date_str} ({note_text})"
  body = _append_under_heading(body, Section.GATES, callout)
  hist = f"- {date_str} — {FLIP_GATE_NAME} · {gate} → {str(value).lower()}"
  body = _append_under_heading(body, Section.HISTORY, hist)
  note.write_text(fm_text + body)
  # Atomic commit of the folder-note edit under the flip-gate bot identity. Without this the
  # daemon's next iteration trips its dirty-tree guard and silently skips every routine until
  # the operator commits by hand. The commit happens BEFORE `_auto_open_plan_review` so the
  # follow-up review-open subprocess sees a clean tree (it does its own commit on top).
  _commit_flip(asset_dir, note, gate, value)
  fm_after, _ = _parse_frontmatter(fm_text)
  result = {FlipResult.STATUS: FlipResult.FLIPPED, "gate": gate, "value": value}
  plan_review = _auto_open_plan_review(asset_dir, gate, off, fm_after)
  # guard: fold the follow-up status into the result only when it applies
  if plan_review is not None:
    result[PlanReview.KEY] = plan_review
  _write_log(asset_dir, gate, value, reason, plan_review = plan_review)
  return result


def main(argv: list[str]) -> int:
  """
  Flip a gate on an asset from the command line, printing the result as JSON.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on a flip, 1 on a refusal, 2 when the asset note is missing.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs flip-gate")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("asset_dir", type = Path)
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("gate")
  # waiver: argparse CLI signature -- option flag + standard argparse action
  parser.add_argument("--off", action = "store_true",
                      # waiver: one-off human-facing message -- argparse help text
                      help = "set the gate to false (skip precondition checks)")
  # waiver: argparse CLI signature -- option flag + standard argparse action
  parser.add_argument("--auto", action = "store_true",
                      # waiver: one-off human-facing message -- argparse help text
                      help = "annotate the callout with an auto: prefix")
  # waiver: argparse CLI signature -- option flag + default
  parser.add_argument("--reason", default = "",
                      # waiver: one-off human-facing message -- argparse help text
                      help = "note recorded in the gate callout")
  args = parser.parse_args(argv)
  asset_dir: Path = args.asset_dir.resolve()
  note = asset_dir / f"{asset_dir.name}.md"
  # guard: asset status folder-note must exist
  if not note.is_file():
    sys.stderr.write(f"no status folder-note: {note}\n")
    return 2
  result = flip_gate(
      asset_dir, args.gate, off = args.off, auto = args.auto, reason = args.reason,
  )
  print(json.dumps(result))
  return 0 if result[FlipResult.STATUS] == FlipResult.FLIPPED else 1


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
