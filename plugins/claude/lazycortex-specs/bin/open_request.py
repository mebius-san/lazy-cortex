"""Mechanical opt-in handler for request files.

Invoked by the `lazy-spec.request-open` md-scan routine for files in
`<vault-root>/requests/*.md` that are not yet in the review loop
(`review_active` missing or false-without-finalize). The handler writes only
the spec-side frontmatter — `spec_role`, `request_status`, `request_class`,
the `request/draft` tag, and clearing a stale `review_result` — then
delegates the review-side opt-in shape (`review_active`, `review_round`,
`review_approved`, `review_phase`, `review_main_done`, the Waiting banner,
and the `# History` section) to lazycortex-review's own `start` verb. The
atomic commit under the `lazy-spec.request-open` identity is still owned
here. No LLM dispatch.

State table for the input file:

- **Naked** (no frontmatter)
  → write fresh shape, commit, outcome `opened`.
- **Partial bootstrap** (request_status: draft, missing review_active
  or review_round or review_approved or review_phase or review_main_done
  or banner) → write the missing pieces, commit, outcome `repaired`.
- **Fully opted in** (all required keys present, banner above first H1)
  → outcome `already-opted-in`, no-op.
- **Ready-for-apply** (request_status: draft + review_result present)
  → outcome `ready-for-apply-skip`, no-op. Post-finalize state owned
  by the apply-gate routine, not the open transition.
- **Terminal status** (request_status in {accepted, rejected})
  → outcome `terminal-state-skip`, no-op.
- **Has frontmatter but request_status is missing or set to a value that is
  neither draft nor terminal** → outcome `unknown-state-skip`, no-op
  (operator state, not script's business).

On the naked and partial paths, the spec-side frontmatter write to disk happens before
`_bootstrap_review` runs. If that delegated call raises `SystemExit` (CLI unresolved, timeout,
or non-zero exit), the write has already landed and the commit never happens, leaving the file
uncommitted and half-shaped in the worktree. This self-heals: the next md-scan tick
re-classifies the file as `partial` and retries the repair.

Two splits govern who does the work here. Between this script and the LLM
agent: anything decidable WITHOUT reading the body (frontmatter shape,
banner) is script work; classification, candidate enumeration, routing,
attach / spawn invocation is LLM agent work in the review specialist mode
and apply-gate mode. Between this script and the sibling plugin: the
spec-side frontmatter keys are written directly here, while the
review-side opt-in shape is delegated to lazycortex-review's own CLI
rather than duplicated by hand.
"""
from __future__ import annotations

import argparse
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
import flip_gate  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_keys import BannerTag, Outcome, PlanReview, SpecKey, SpecValue, State  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
# pylint: disable-next=import-error,wrong-import-position
from spec_paths import (  # noqa: E402
    find_settings_root, read_text, require_plugin_cli, spec_content_root, write_text_atomic,
)
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import spec_frontmatter  # noqa: E402  # pylint: disable=import-error,wrong-import-position
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from summary_render import apply_container_stats  # noqa: E402  # pylint: disable=import-error,wrong-import-position


_REQUIRED_REVIEW_KEYS = (
    SpecKey.REVIEW_ACTIVE, SpecKey.REVIEW_ROUND, SpecKey.REVIEW_APPROVED,
    SpecKey.REVIEW_PHASE, SpecKey.REVIEW_MAIN_DONE,
)
_TERMINAL_STATUSES = frozenset({"accepted", "rejected"})

# The review-side half of the opt-in shape — `review_active` / `review_round` / `review_approved`
# / `review_phase` / `review_main_done`, the Waiting banner and the `# History` section — belongs
# to lazycortex-review and is produced by its own `start` verb, never hand-written here. Two
# copies of that shape drift apart, and the coordinator then burns a repair commit on every
# request to reconcile them.
# waiver: sibling-plugin CLI subcommand flag — no constants class in this module carries it
_NO_COMMIT_FLAG = "--no-commit"

# An inner subprocess bound only buys a diagnostic when it trips before the daemon kills the
# whole handler, so it has to sit strictly below the driving routine's own `timeout_sec`. The
# `lazy-spec.request-open` routine bounds this handler at 30s, hence a local 20s rather than the
# shared `PlanReview.START_TIMEOUT_S` (60s), which would never trip here. That shared constant
# has no margin at its own call sites either — `lazy-spec.gate-tick` and
# `lazy-spec.coordinator-watch` are both `timeout_sec: 60`, so the daemon's kill and the inner
# timeout land together and spawn time decides which wins. Fixing those is their modules' call.
_BOOTSTRAP_TIMEOUT_S = 20

_FRESH_FRONTMATTER = (
    "---\n"
    f"{SpecKey.ROLE}: {SpecValue.ROLE_REQUEST}\n"
    f"{SpecKey.STATUS}: {SpecValue.STATUS_DRAFT}\n"
    f"{SpecKey.CLASS}: {SpecValue.CLASS_UNKNOWN}\n"
    "tags:\n"
    f"  - {SpecValue.TAG_DRAFT}\n"
    "---\n"
)

# The frontmatter list key the request mirror tag is kept under.
_TAGS_KEY = "tags"


def _parse_frontmatter(text: str) -> tuple[dict, int, int]:
  """
  Parse the YAML frontmatter block at the start of a file's text.

  Args:
    text: Full file text, potentially including a leading YAML frontmatter block.

  Returns:
    A three-tuple of `(values, fm_start_idx, fm_end_idx)` where `values` is a flat
    dict of top-level scalar keys and the indices bound the YAML block including the
    closing `---` line. Returns `({}, 0, 0)` when the text carries no parseable
    frontmatter.
  """
  values, fm_end = spec_frontmatter.parse(text)
  return values, 0, fm_end


def _has_banner(body: str) -> bool:
  """
  Return True when `body` carries the Waiting banner above any first H1.

  Args:
    body: Markdown body text below the frontmatter block, scanned for the banner.

  Returns:
    True when a recognised review-status tag appears before the first H1 heading;
    False when the H1 comes first or no banner is found.
  """
  # scan down to the first H1: a banner tag on any line above it counts, other lines are passed over
  for line in body.splitlines():
    # guard: skip blank lines
    if not line.strip():
      continue
    if line.startswith("# "):
      return False  # H1 came first → no banner
    if BannerTag.IN_PROCESS in line or BannerTag.ACTION_NEEDED in line or BannerTag.READY in line:
      return True

  # the body ended with neither a banner nor an H1 — no banner
  return False


def _classify(values: dict, body: str) -> str:
  """
  Classify a request file's current state from its frontmatter values and body.

  Args:
    values: Parsed frontmatter values for the file being classified.
    body: Markdown body text below the frontmatter block.

  Returns:
    One of `naked`, `partial`, `ready`, `ready-for-apply`, `terminal`, or `unknown-state`.
  """

  # Domain(spec.requests):
  # # Request intake state table
  # A request file's place in the intake pipeline is read entirely from its own frontmatter and
  # body, never carried anywhere else: a file with no frontmatter yet has not opted in at all; a
  # draft carrying every opt-in key plus its banner is fully in the review loop; a draft missing
  # any of those pieces is only partway opted in; a draft that also carries a review result has
  # already been finalized and awaits the separate apply step, which owns that state exclusively;
  # an accepted or rejected status is terminal and closed to further opt-in; and a file that has
  # frontmatter but no status, or a status that is neither draft nor one of those two, is left
  # alone as operator state nobody but the operator should touch.

  # read the state off the frontmatter, most decisive signal first
  if not values:
    return State.NAKED
  status = values.get(SpecKey.STATUS)
  if status in _TERMINAL_STATUSES:
    return State.TERMINAL
  if status == SpecValue.STATUS_DRAFT:
    # a finalized draft carries `review_result` until the apply-gate flips its status; that state
    # belongs to the apply-gate, and re-bootstrapping here would undo the finalize
    if values.get(SpecKey.REVIEW_RESULT):
      return State.READY_FOR_APPLY

    # every required review-side key plus the banner means fully opted in
    if any(key not in values for key in _REQUIRED_REVIEW_KEYS) or not _has_banner(body):
      return State.PARTIAL
    return State.READY

  # frontmatter without a status, or with a status outside the known set, is operator state
  return State.UNKNOWN


def _set_field(fm_text: str, key: str, value: str) -> str:
  """
  Add or replace `key: value` in a frontmatter block delimited by `---`.

  Inserts before the closing `---` when the key is absent; replaces the
  existing line in place when present.

  Args:
    fm_text: Frontmatter text block, including its opening and closing `---` fences.
    key: Frontmatter key to set.
    value: Value to assign to the key.

  Returns:
    The updated frontmatter text with the key set to the given value.
  """
  return spec_frontmatter.set_scalar(fm_text, key, value)


def _unset_field(fm_text: str, key: str) -> str:
  """
  Remove the `key: …` line from `fm_text`. No-op when absent.

  Args:
    fm_text: Frontmatter text block to remove the key from.
    key: Frontmatter key whose line is removed.

  Returns:
    The frontmatter text with the matching key line removed, or the original
    text unchanged when the key is not present.
  """
  pat = re.compile(rf"(?m)^{re.escape(key)}\s*:.*\n")
  return pat.sub("", fm_text, count = 1)


def _ensure_tags_member(fm_text: str, member: str) -> str:
  """
  Ensure the `tags:` block contains `- <member>`.

  Creates the block when absent; appends the member when the block exists
  but does not already include it.

  Args:
    fm_text: Frontmatter text block to update.
    member: Tag value to ensure is present in the `tags:` block.

  Returns:
    The frontmatter text with the given member present in the `tags:` block.
  """
  members = spec_frontmatter.read_list(fm_text, _TAGS_KEY)

  # guard: already a member — nothing to write
  if member in members:
    return fm_text
  return spec_frontmatter.write_list(fm_text, _TAGS_KEY, [ *members, member ])


def _resolve_review_cli(repo: Path) -> Path:
  """
  Resolve the `lazycortex-review` CLI binary, failing hard when it cannot be found.

  Args:
    repo: The repository root whose own plugin tree is searched.

  Returns:
    The resolved binary path.

  Raises:
    SystemExit: When no lookup stage finds the `lazycortex-review` CLI.
  """
  try:
    return require_plugin_cli(PlanReview.REVIEW_CLI, repo)
  # guard: unresolved — the message names every lookup stage that was searched
  except RuntimeError as exc:
    sys.stderr.write(f"{exc}\n")
    raise SystemExit(3) from None


def _bootstrap_review(file_path: Path) -> None:
  """
  Seed the review-side opt-in shape for a request file via the sibling review CLI.

  Notes:
    - Invokes the review CLI as a subprocess and leaves the resulting changes uncommitted for
      the caller to fold into its own atomic commit.

  Args:
    file_path: Request file whose review-side shape is being seeded.

  Raises:
    SystemExit: When the review CLI cannot be resolved, times out, or exits non-zero.
  """
  try:
    res = subprocess.run(
        [sys.executable, str(_resolve_review_cli(flip_gate.repo_root(file_path.parent))), PlanReview.START_VERB,
         _NO_COMMIT_FLAG, str(file_path)],
        cwd = str(file_path.parent), capture_output = True, text = True, check = False,
        timeout = _BOOTSTRAP_TIMEOUT_S, encoding = "utf-8",
    )
  # guard: a hung review CLI would otherwise stall every routine on the daemon's serial tick
  except subprocess.TimeoutExpired:
    sys.stderr.write(
        f"{PlanReview.REVIEW_CLI} start timed out after {_BOOTSTRAP_TIMEOUT_S}s "
        f"on {file_path}\n"
    )
    raise SystemExit(3) from None

  # guard: a failed bootstrap leaves a half-shaped document — surface it as a routine error
  if res.returncode != 0:
    sys.stderr.write(
        f"{PlanReview.REVIEW_CLI} start failed on {file_path}: "
        f"exit={res.returncode} stderr={res.stderr.strip()[:240]}\n"
    )
    raise SystemExit(3)


def _repair(text: str, values: dict, fm_end: int) -> str:
  """
  Bring partial frontmatter up to the canonical spec-side opt-in shape.

  Args:
    text: Full file text, frontmatter and body, of the file being repaired.
    values: Parsed frontmatter values already present in the file.
    fm_end: Offset marking the end of the frontmatter block within `text`.

  Returns:
    The complete file text with the missing request keys filled in, the stale
    apply-gate discriminator cleared, and the `request/draft` tag ensured.
  """
  fm_text = text[:fm_end]

  # Spec keys: only add if missing (operator may have meaningful values)
  if SpecKey.ROLE not in values:
    fm_text = _set_field(fm_text, SpecKey.ROLE, SpecValue.ROLE_REQUEST)
  if SpecKey.CLASS not in values:
    fm_text = _set_field(fm_text, SpecKey.CLASS, SpecValue.CLASS_UNKNOWN)

  # clear the terminal apply-gate discriminator so re-entering the review loop does not also
  # trigger the downstream apply-gate on the next md-scan tick; after a re-open it is stale
  if SpecKey.REVIEW_RESULT in values:
    fm_text = _unset_field(fm_text, SpecKey.REVIEW_RESULT)
  fm_text = _ensure_tags_member(fm_text, SpecValue.TAG_DRAFT)

  # a closing fence at the very end of the file gets its line break, so whatever the review side
  # appends below it starts on a line of its own
  return fm_text.rstrip("\n") + "\n" + text[fm_end:].lstrip("\n")


def open_naked_file(file_path: Path) -> str:
  """
  Apply the mechanical opt-in transition to a request file.

  Guarantees:
    - When the delegated review-side bootstrap fails after the spec-side frontmatter write has
      already landed, the file is left in a shape the next call classifies as `partial`, so a
      retry on the same file always resumes and completes the interrupted opt-in.

  Notes:
    - Writes to `file_path` and, for the `opened` and `repaired` outcomes, invokes the
      `lazycortex-review` CLI to seed the review-side shape before returning.

  Args:
    file_path: Request file to bring to the canonical opt-in shape.

  Returns:
    One of `opened`, `repaired`, `already-opted-in`, `ready-for-apply-skip`,
    `terminal-state-skip`, or `unknown-state-skip`.

  Raises:
    SystemExit: When the review CLI cannot be resolved or exits non-zero, for the
      `opened` and `repaired` transitions.
  """

  # Domain(spec.requests):
  # # Partial opt-in self-heals on the next pass
  # Opening a request is two steps that cannot land as one transaction: the spec-side frontmatter
  # is written to disk first, and only afterward is the review-side shape delegated onward. When
  # the delegated step fails, the new shape is left on disk without ever being committed — but
  # that half-shaped file is exactly what the next pass classifies as partial, so the same repair
  # is simply retried instead of getting stuck. No operator intervention is needed for an
  # interrupted opt-in to complete itself.

  # Contract:
  # When the delegated review-side bootstrap fails after the spec-side frontmatter write has
  # already landed, the file is left in a shape the next call classifies as `partial`, so a
  # retry on the same file always resumes and completes the interrupted opt-in.

  # classify the file's current opt-in state from its frontmatter and body
  text = read_text(file_path)
  values, _, fm_end = _parse_frontmatter(text)
  state = _classify(values, text[fm_end:])

  # a naked file gets the fresh opt-in frontmatter; an empty frontmatter block the file already
  # carries is replaced, never stacked under
  if state == State.NAKED:
    write_text_atomic(file_path, _FRESH_FRONTMATTER + text[fm_end:].lstrip("\n"))
    _bootstrap_review(file_path)
    return Outcome.OPENED

  # a half-opted-in file has its frontmatter repaired and the review-side bootstrap retried
  if state == State.PARTIAL:
    write_text_atomic(file_path, _repair(text, values, fm_end))
    _bootstrap_review(file_path)
    return Outcome.REPAIRED

  # every other state is left untouched and reported by its own skip outcome
  if state == State.READY:
    return Outcome.ALREADY_OPTED_IN
  if state == State.READY_FOR_APPLY:
    return Outcome.READY_FOR_APPLY_SKIP
  if state == State.TERMINAL:
    return Outcome.TERMINAL_STATE_SKIP
  return Outcome.UNKNOWN_STATE_SKIP


def _atomic_commit(
    file_path: Path,
    *,
    author_name: str,
    author_email: str,
    subject: str,
) -> None:
  """
  Commit a request file's opt-in edit under a caller-supplied bot identity, without an icon repaint.

  Notes:
    - Also commits the requests inbox summary file when its container stats need updating.
    - The author identity applies to this commit only and never changes the repo's git config.
    - The operator's staged entries never ride into the commit.

  Args:
    file_path: Request file to commit.
    author_name: Git author name used for the commit.
    author_email: Git author email used for the commit.
    subject: Commit message subject.

  Raises:
    subprocess.CalledProcessError: If the commit fails.
  """

  # Domain(spec.notes):
  # # A container's summary rides the same commit as its membership
  # The requests inbox keeps a running summary of what it holds, and that summary is only ever
  # true the instant it is read if it changes in step with the requests it counts. Folding the
  # summary's own update into the very commit that opened or repaired a request is what keeps
  # the two from drifting apart — a separate summary commit would leave a window where the
  # displayed count disagrees with what the inbox actually contains.

  # the commit carries the request file, plus the inbox summary when its container stats changed
  add_paths: list[str] = [str(file_path)]
  # waiver: inbox path segments are fixed protocol constants; no constants class in this module
  inbox = spec_content_root(find_settings_root(file_path.parent)) / "requests" / "requests.md"
  if inbox.is_file() and apply_container_stats(inbox):
    add_paths.append(str(inbox))

  # commit them under the caller's bot identity, set for this one command only, with an explicit
  # pathspec so content anyone else staged never rides along; no icon repaint rides this commit
  flip_gate.commit_paths(
      flip_gate.repo_root(file_path.parent), add_paths, subject = subject, author_name = author_name,
      author_email = author_email, repaint = False,
  )


def main(argv: list[str]) -> int:
  """
  Apply the mechanical opt-in transition to a request file from the command line.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success, 2 when the file does not exist or is not a markdown file.

  Raises:
    SystemExit: When the review CLI cannot be resolved or exits non-zero while opening
      or repairing the file.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs open-request")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("file", type = Path)
  parser.add_argument(
      # waiver: argparse CLI signature -- option flag + bot-identity default
      "--author-name", default = "lazy-spec.request-open",
      # waiver: one-off human-facing message -- argparse help text
      help = "git author name for the opt-in commit",
  )
  parser.add_argument(
      # waiver: argparse CLI signature -- option flag + bot-identity default
      "--author-email", default = "lazy-spec.request-open@bot.invalid",
      # waiver: one-off human-facing message -- argparse help text
      help = "git author email for the opt-in commit",
  )
  parser.add_argument(
      # waiver: argparse CLI signature -- option flag + standard argparse action
      "--no-commit", action = "store_true",
      # waiver: one-off human-facing message -- argparse help text
      help = "apply file mutations but skip the git commit",
  )
  args = parser.parse_args(argv)
  file_path: Path = args.file.resolve()

  # guard: the named path is missing or is not a markdown document
  # waiver: filesystem path idiom -- markdown file extension guard
  if not file_path.exists() or file_path.suffix.lower() != ".md":
    sys.stderr.write(f"not a markdown file: {file_path}\n")
    return 2

  # open or repair the opt-in, then commit it unless the caller asked for an uncommitted run
  outcome = open_naked_file(file_path)
  if outcome in (Outcome.OPENED, Outcome.REPAIRED) and not args.no_commit:
    subject = (
        f"spec: open request {file_path.name}"
        if outcome == Outcome.OPENED
        else f"spec: repair partial opt-in {file_path.name}"
    )
    _atomic_commit(
        file_path,
        author_name = args.author_name,
        author_email = args.author_email,
        subject = subject,
    )
  print(f"open_request: {file_path} -> {outcome}")
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
