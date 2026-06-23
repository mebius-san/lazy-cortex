"""Mechanical opt-in handler — owns the full frontmatter shape for
request files.

Invoked by the `spec.request-open` md-scan routine for files in
`<vault-root>/requests/*.md` that are not yet in the review loop
(`review_active` missing or false-without-finalize). The handler
brings the file to the canonical opt-in shape: 8 frontmatter keys +
Waiting banner, atomic commit under `spec.request-open` identity.
No LLM dispatch.

State table for the input file:

- **Naked** (no frontmatter)
  → write fresh shape, commit, outcome `opened`.
- **Partial bootstrap** (request_status: draft, missing review_active
  or review_round or review_approved or banner) → write the missing
  pieces, commit, outcome `repaired`.
- **Fully opted in** (all required keys present, banner above first H1)
  → outcome `already-opted-in`, no-op.
- **Ready-for-apply** (request_status: draft + review_result present)
  → outcome `ready-for-apply-skip`, no-op. Post-finalize state owned
  by the apply-gate routine, not the open transition.
- **Terminal status** (request_status in {accepted, rejected})
  → outcome `terminal-state-skip`, no-op.
- **Has frontmatter but request_status is set to an unknown value** →
  outcome `unknown-state-skip`, no-op (operator state, not script's
  business).

The split between this script and the LLM agent is: anything that can
be decided WITHOUT reading the body (frontmatter shape, banner) is
script work; classification, candidate enumeration, routing, attach /
spawn invocation is LLM agent work in the review specialist mode and
apply-gate mode.
"""
from __future__ import annotations
# waiver: bare-name sibling import (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

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

# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
from spec_keys import BannerTag, Outcome, SpecKey, SpecValue, State  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
from spec_paths import find_settings_root, spec_content_root  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
from summary_render import apply_container_stats  # noqa: E402


_REQUIRED_REVIEW_KEYS = (SpecKey.REVIEW_ACTIVE, SpecKey.REVIEW_ROUND, SpecKey.REVIEW_APPROVED)
_REQUIRED_SPEC_KEYS = (SpecKey.ROLE, SpecKey.STATUS, SpecKey.CLASS)
_TERMINAL_STATUSES = frozenset({"accepted", "rejected"})
_BANNER = f"> [!hint] Waiting {BannerTag.IN_PROCESS}"

_FRESH_FRONTMATTER = (
    "---\n"
    f"{SpecKey.ROLE}: {SpecValue.ROLE_REQUEST}\n"
    f"{SpecKey.STATUS}: {SpecValue.STATUS_DRAFT}\n"
    f"{SpecKey.CLASS}: {SpecValue.CLASS_UNKNOWN}\n"
    f"{SpecKey.REVIEW_ACTIVE}: {SpecValue.TRUE}\n"
    f"{SpecKey.REVIEW_ROUND}: {SpecValue.ROUND_ONE}\n"
    f"{SpecKey.REVIEW_APPROVED}: {SpecValue.FALSE}\n"
    "tags:\n"
    f"  - {SpecValue.TAG_DRAFT}\n"
    "---\n"
)


def _parse_frontmatter(text: str) -> tuple[dict, int, int]:
  """
  Parse the YAML frontmatter block at the start of a file's text.

  Returns `({}, 0, 0)` when there is no parseable frontmatter.

  Returns:
    A three-tuple of `(values, fm_start_idx, fm_end_idx)` where `values` is a flat
    dict of top-level scalar keys and the indices bound the YAML block including the
    closing `---` line.
  """
  if not text.startswith("---\n"):
    return {}, 0, 0
  rest = text[4:]
  end_idx = rest.find("\n---\n")
  if end_idx < 0:
    return {}, 0, 0
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
  return values, 0, fm_end


def _has_banner(body: str) -> bool:
  """
  Return True when `body` carries the Waiting banner above any first H1.

  Returns:
    True when a recognised review-status tag appears before the first H1 heading;
    False when the H1 comes first or no banner is found.
  """
  # First non-empty line of body region above first H1 must be the
  # banner. The banner is a one-line callout with the tag.
  for line in body.splitlines():
    # guard: skip blank lines
    if not line.strip():
      continue
    if line.startswith("# "):
      return False  # H1 came first → no banner
    if BannerTag.IN_PROCESS in line or BannerTag.ACTION_NEEDED in line or BannerTag.READY in line:
      return True
  # Any other non-empty, non-H1 line — keep scanning (could be
  # blank padding, stale snippet, etc.).
  return False


def _classify(values: dict, body: str) -> str:
  """
  Classify a request file's current state from its frontmatter values and body.

  Returns:
    One of `naked`, `partial`, `ready`, `ready-for-apply`, `terminal`, or `unknown-state`.
  """
  if not values:
    return State.NAKED
  status = values.get(SpecKey.STATUS)
  if status in _TERMINAL_STATUSES:
    return State.TERMINAL
  if status == SpecValue.STATUS_DRAFT:
      # Post-finalize files carry `review_result` (set by finalize
      # as the last step) plus `request_status: draft` while the
      # apply-gate routine has not yet flipped status to terminal.
      # That state belongs to the apply-gate, not the open
      # transition — re-bootstrapping here would undo the finalize.
    if values.get(SpecKey.REVIEW_RESULT):
      return State.READY_FOR_APPLY
  # Required review-side keys + banner = fully opted in
    missing = [k for k in _REQUIRED_REVIEW_KEYS if k not in values]
    if missing or not _has_banner(body):
      return State.PARTIAL
    return State.READY
  if status is None or status == "":
      # Has some frontmatter but no request_status: operator state,
      # not script's business
    return State.UNKNOWN
  return State.UNKNOWN


def _set_field(fm_text: str, key: str, value: str) -> str:
  """
  Add or replace `key: value` in a frontmatter block delimited by `---`.

  Inserts before the closing `---` when the key is absent; replaces the
  existing line in place when present.

  Returns:
    The updated frontmatter text with the key set to the given value.
  """
  pat = re.compile(rf"(?m)^{re.escape(key)}\s*:.*$")
  if pat.search(fm_text):
    return pat.sub(f"{key}: {value}", fm_text, count=1)
# Insert before closing ---
  close_idx = fm_text.rfind("---\n")
  if close_idx < 0:
    return fm_text
  return fm_text[:close_idx] + f"{key}: {value}\n" + fm_text[close_idx:]


def _unset_field(fm_text: str, key: str) -> str:
  """
  Remove the `key: …` line from `fm_text`. No-op when absent.

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

  Returns:
    The frontmatter text with the given member present in the `tags:` block.
  """
  tags_re = re.compile(r"(?m)^tags\s*:\s*\n((?:\s+- .*\n)*)")
  m = tags_re.search(fm_text)
  if m:
    existing = m.group(1)
    if f"- {member}" in existing:
      return fm_text
    new_block = existing + f"  - {member}\n"
    return fm_text[:m.start(1)] + new_block + fm_text[m.end(1):]
# No tags block — insert before closing ---
  close_idx = fm_text.rfind("---\n")
  if close_idx < 0:
    return fm_text
  return fm_text[:close_idx] + f"tags:\n  - {member}\n" + fm_text[close_idx:]


def _repair(text: str, values: dict, fm_end: int) -> str:
  """
  Bring partial frontmatter up to the canonical opt-in shape.

  Returns:
    The complete file text with all missing review keys filled in, the
    `request/draft` tag ensured, and the Waiting banner prepended to the body
    when absent.
  """
  fm_text = text[:fm_end]
  body = text[fm_end:]
  # Spec keys: only add if missing (operator may have meaningful values)
  if SpecKey.ROLE not in values:
    fm_text = _set_field(fm_text, SpecKey.ROLE, SpecValue.ROLE_REQUEST)
  if SpecKey.CLASS not in values:
    fm_text = _set_field(fm_text, SpecKey.CLASS, SpecValue.CLASS_UNKNOWN)
# Review keys: enforce canonical defaults if missing
  if SpecKey.REVIEW_ACTIVE not in values:
    fm_text = _set_field(fm_text, SpecKey.REVIEW_ACTIVE, SpecValue.TRUE)
  if SpecKey.REVIEW_ROUND not in values:
    fm_text = _set_field(fm_text, SpecKey.REVIEW_ROUND, SpecValue.ROUND_ONE)
  if SpecKey.REVIEW_APPROVED not in values:
    fm_text = _set_field(fm_text, SpecKey.REVIEW_APPROVED, SpecValue.FALSE)
# Clear the terminal apply-gate discriminator so re-entering the
# review loop does not also trigger the downstream apply-gate
# routine on the next md-scan tick. `review_result` is set only
# by finalize; its presence after re-open would be a stale signal.
  if SpecKey.REVIEW_RESULT in values:
    fm_text = _unset_field(fm_text, SpecKey.REVIEW_RESULT)
  fm_text = _ensure_tags_member(fm_text, SpecValue.TAG_DRAFT)
  # Banner
  body_stripped = body.lstrip("\n")
  if not _has_banner(body_stripped):
    body_stripped = _BANNER + "\n\n" + body_stripped
  return fm_text + body_stripped


def open_naked_file(file_path: Path) -> str:
  """
  Apply the mechanical opt-in transition to `file_path`.

  Returns:
    One of `opened`, `repaired`, `already-opted-in`, `ready-for-apply-skip`,
    `terminal-state-skip`, or `unknown-state-skip`.
  """
  text = file_path.read_text()
  values, _, fm_end = _parse_frontmatter(text)
  state = _classify(values, text[fm_end:])
  if state == State.NAKED:
    body = text.lstrip("\n")
    file_path.write_text(_FRESH_FRONTMATTER + _BANNER + "\n\n" + body)
    return Outcome.OPENED
  if state == State.PARTIAL:
    file_path.write_text(_repair(text, values, fm_end))
    return Outcome.REPAIRED
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
  """Stage `file_path` and commit under the named bot identity in a
    single atomic step. The `-c user.name=` / `-c user.email=`
    overrides keep concurrent bot commits from racing on the per-repo
    git config (same trick `lazycortex-review/bin/git_ops.py` uses).
    """
  cwd = file_path.parent
  add_paths: list[str] = [str(file_path)]
  # waiver: inbox path segments are fixed protocol constants; no constants class in this module
  inbox = spec_content_root(find_settings_root(file_path.parent)) / "requests" / "requests.md"
  if inbox.is_file() and apply_container_stats(inbox):
    add_paths.append(str(inbox))
  subprocess.run(
      ["git", "add", "--", *add_paths],
      cwd = cwd, check = True, capture_output = True,
  )
  subprocess.run(
      [
          "git",
          "-c", f"user.name={author_name}",
          "-c", f"user.email={author_email}",
          "-c", "commit.gpgsign=false",
          "commit", "-q", "-m", subject,
      ],
      cwd = cwd, check = True, capture_output = True,
  )


def main(argv: list[str]) -> int:
  """
  Apply the mechanical opt-in transition to a request file from the command line.

  Args:
    argv: Command-line arguments, excluding the program name.

  Returns:
    Exit code: 0 on success, 2 when the file does not exist or is not a markdown file.
  """
  # waiver: argparse CLI signature -- program name shown in --help / usage
  parser = argparse.ArgumentParser(prog = "lazycortex-specs open-request")
  # waiver: argparse CLI signature -- positional argument name
  parser.add_argument("file", type = Path)
  parser.add_argument(
      # waiver: argparse CLI signature -- option flag + bot-identity default
      "--author-name", default = "spec.request-open",
      # waiver: one-off human-facing message -- argparse help text
      help = "git author name for the opt-in commit",
  )
  parser.add_argument(
      # waiver: argparse CLI signature -- option flag + bot-identity default
      "--author-email", default = "spec.request-open@bot.invalid",
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
  # waiver: filesystem path idiom -- markdown file extension guard
  if not file_path.exists() or file_path.suffix.lower() != ".md":
    sys.stderr.write(f"not a markdown file: {file_path}\n")
    return 2
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
