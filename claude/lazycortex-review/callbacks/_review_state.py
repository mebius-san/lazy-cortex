#!/usr/bin/env python3
"""
Iconize callback: report the review-loop state of a document under review.

Invoked via stdin JSON `{"op": "when", "path": "<vault-relative>.md", "frontmatter": {...}}`.
The review loop states its current state in the document's banner callout — the first
non-empty body line after the frontmatter — as a `#review/<tag>` token, so the answer is
read from there rather than from a frontmatter key. `review_phase: awaiting-operator`,
which the submit entry writes, counts as awaiting the operator.

Two wrapper symlinks point here; the question is the invoked name:

- `review-awaits-operator` — the document needs a human gesture before anything moves.
  A folder note (`<dir>/<dir>.md`) answers for its whole folder: it matches when any
  document beside it is waiting, so a glance at the tree says which folder needs a human.
- `review-in-process` — agents are actively working the document; the operator waits.
  Answered per-document only, never through a folder note.

Any error, unreadable file, or unrecognized shape returns `{"match": false}`. Never raises.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


class WaitTag:
  """
  Banner tags that mean the loop has stopped and a human gesture is the next move.

  Attributes:
    ACTION_NEEDED: Banner tag for a callout blocked on an operator decision before work can resume.
    READY: Banner tag for a callout announcing the document is ready for the operator to review.
    CONCERNS_DECISION: Banner tag for a callout awaiting an operator decision on raised concerns.
  """

  ACTION_NEEDED = "action-needed"
  READY = "ready"
  CONCERNS_DECISION = "concerns-decision"


class WorkTag:
  """
  Banner tags that mean the loop's own agents hold the document right now.

  Attributes:
    IN_PROCESS: Banner tag for a callout while an agent is actively working the document.
    FINALIZING: Banner tag for a callout while the loop is closing out the document.
  """

  IN_PROCESS = "in-process"
  FINALIZING = "finalizing"


class Callback:
  """
  Iconize callback names this script answers to, resolved from its own argv[0].

  Attributes:
    AWAITS_OPERATOR: Invocation name that asks whether the document awaits an operator gesture.
    IN_PROCESS: Invocation name that asks whether the loop's own agents currently hold the document.
  """

  AWAITS_OPERATOR = "review-awaits-operator"
  IN_PROCESS = "review-in-process"


class Key:
  """
  JSON keys exchanged with the iconize host, and the frontmatter key read as a fallback.

  Attributes:
    PATH: Stdin payload key carrying the document's vault-relative path.
    MATCH: Stdout response key carrying the boolean callback answer.
    FRONTMATTER: Stdin payload key carrying the document's parsed frontmatter mapping.
    PHASE: Frontmatter key the submit entry sets, read as a fallback for the awaiting-operator state.
  """

  PATH = "path"
  MATCH = "match"
  FRONTMATTER = "frontmatter"
  PHASE = "review_phase"


# the `review_phase` value the submit entry leaves behind while it waits for the operator
AWAITING_PHASE = "awaiting-operator"

# the banner is a callout whose first line carries the state tag
BANNER_TAG_RE = re.compile(r"^>\s*\[!\w+\][^#\n]*#review/([a-z-]+)\s*$")


def _vault_root() -> Path:
  """
  Locate the vault root the callback was invoked against.

  Returns:
    The resolved repository root, falling back to the working directory when git cannot
    answer.
  """
  try:
    proc = subprocess.run(
      ["git", "rev-parse", "--show-toplevel"],
      capture_output = True, text = True, check = True,
    )
    return Path(proc.stdout.strip())
  except (OSError, subprocess.CalledProcessError):
    # the worker invokes callbacks with the vault as cwd; the shipped file's own parents
    # point into the plugin tree, never at the vault
    return Path.cwd()


def _banner_tag(text: str) -> str | None:
  """
  Read the review state tag out of a document's banner callout.

  Args:
    text: Full document text to scan for the banner callout.

  Returns:
    The tag following `#review/` on the banner line, or None when the document carries
    no banner.
  """
  lines = text.splitlines()
  start = 0
  # skip the frontmatter block so the banner is the first body line examined
  if lines and lines[0].strip() == "---":
    for idx, line in enumerate(lines[1:], start = 1):
      if line.strip() == "---":
        start = idx + 1
        break
  for line in lines[start:]:
    # guard: the banner is the first non-empty body line; anything else means none is present
    if not line.strip():
      continue
    tag_match = BANNER_TAG_RE.match(line)
    return tag_match.group(1) if tag_match else None
  return None


def _is_folder_note(path: str) -> bool:
  """
  Report whether a path is the note standing in for its own folder.

  Args:
    path: Vault-relative path being tested.

  Returns:
    True when the file stem equals the name of the directory holding it — the
    `{{folder_name}}` shape the folder-notes plugin resolves.
  """
  note = Path(path)
  return note.stem == note.parent.name


def _has_waiting_sibling(root: Path, path: str) -> bool:
  """
  Report whether any document beside a folder note is waiting on the operator.

  A folder carries the state of what it holds: the operator scanning the tree wants the
  folder to say "something in here needs you" without opening it.

  Args:
    root: Vault root the path is resolved against.
    path: Folder note's own vault-relative path; its parent directory is what gets scanned.

  Returns:
    True when at least one sibling markdown file is parked for a human gesture.
  """
  folder = (root / path).parent
  try:
    entries = sorted(folder.iterdir())
  except OSError:
    return False

  # the folder note itself is skipped, or the answer would be circular
  for entry in entries:
    # guard: only sibling markdown documents participate
    # waiver: filesystem extension idiom, not a domain constant
    if not entry.is_file() or entry.suffix != ".md" or entry.stem == folder.name:
      continue
    try:
      # waiver: stdlib text-mode tokens; a named constant would only move them away from the call
      text = entry.read_text(encoding = "utf-8")
    except OSError:
      continue
    if _banner_tag(text) in { WaitTag.ACTION_NEEDED, WaitTag.READY, WaitTag.CONCERNS_DECISION }:
      return True
  return False


def is_awaiting_operator(path: str, frontmatter: dict) -> bool:
  """
  Report whether the document at `path` is parked waiting for a human gesture.

  A folder note answers for its whole folder: it matches when any document beside it is
  waiting, so the tree shows which folder needs attention without being opened.

  Args:
    path: Document's vault-relative path.
    frontmatter: Document's parsed frontmatter mapping from the callback payload.

  Returns:
    True when the banner carries a state that stops the loop for the operator, when the
    submit entry has parked the document in the awaiting-operator phase, or when the path
    is a folder note holding a waiting document.
  """
  # the submit entry answers in frontmatter; the ordinary loop answers in the banner
  if isinstance(frontmatter, dict) and frontmatter.get(Key.PHASE) == AWAITING_PHASE:
    return True

  # a folder note carries no banner of its own — it reports what its folder holds
  root = _vault_root()
  if _is_folder_note(path):
    return _has_waiting_sibling(root, path)

  # the document itself is the source of truth; an unreadable one simply does not match
  try:
    # waiver: stdlib text-mode tokens; a named constant would only move them away from the call
    text = (root / path).read_text(encoding = "utf-8")
  except OSError:
    return False
  return _banner_tag(text) in { WaitTag.ACTION_NEEDED, WaitTag.READY, WaitTag.CONCERNS_DECISION }


def is_in_process(path: str) -> bool:
  """
  Report whether the review loop's own agents hold the document at `path` right now.

  Answered per-document only — folder notes never aggregate this state, so the tree
  highlights folders solely for the states that need a human.

  Args:
    path: Document's vault-relative path.

  Returns:
    True when the banner carries a working state, False otherwise.
  """
  root = _vault_root()
  # the document itself is the source of truth; an unreadable one simply does not match
  try:
    # waiver: stdlib text-mode tokens; a named constant would only move them away from the call
    text = (root / path).read_text(encoding = "utf-8")
  except OSError:
    return False
  return _banner_tag(text) in { WorkTag.IN_PROCESS, WorkTag.FINALIZING }


def main() -> int:
  """
  Run the iconize callback: answer the review-state question named by argv[0].

  Returns:
    Process exit code; always 0 on a completed run.
  """
  try:
    payload = json.loads(sys.stdin.read() or "{}")
  except (OSError, ValueError):
    payload = {}
  path = payload.get(Key.PATH, "")
  frontmatter = payload.get(Key.FRONTMATTER) or {}
  question = Path(sys.argv[0]).name

  # answer the question named by argv[0]; a missing or non-string path never matches
  if not isinstance(path, str) or not path:
    match = False
  elif question == Callback.AWAITS_OPERATOR:
    match = is_awaiting_operator(path, frontmatter)
  elif question == Callback.IN_PROCESS:
    match = is_in_process(path)
  else:
    match = False
  sys.stdout.write(json.dumps({ Key.MATCH: match }))
  return 0


if __name__ == "__main__":
  sys.exit(main())
