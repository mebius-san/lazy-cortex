#!/usr/bin/env python3

"""
PostToolUse hook that records every successful git commit to `.logs/commits.jsonl`.

Fires after any `Bash` command containing a `git commit` invocation (leading, chained like
`git add … && git commit … && git push`, or flag-prefixed like `git -C dir commit`) or after
`mcp__git__git_commit`. Writes one JSON line per commit with the
SHA, ISO date, author, branch, subject, body, file list, and aggregate insertions / deletions. The
file is the raw commit feed that `lazy-log.recall`, `lazy-log.timeline`, and `lazy-log.summary`
search, and that the daemon's journal rotation keeps.

Notes:
  - No LLM call, no network, fast (~50ms).
  - Never blocks the commit outcome. A journalling failure — an unwritable journal directory or
    lock file, a lock still held past the wait budget, or a failed append — is recorded as an
    incident in the repository's error ledger at `.runtime/errors.jsonl` instead.
  - The read-then-append window is serialised on a sibling lock file, so concurrent runs on one
    commit leave exactly one entry.
  - Creates the `.logs/` directory if missing.
  - Works whether the commit was invoked via `Bash` or via the `mcp__git__git_commit` tool.
"""

from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import contextlib
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import TextIO

  from collections.abc import Iterator


# Resolve the sibling bin/ dir so the enablement gate is importable.

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import error_ledger  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
import hook_gate  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design); resolved at runtime via sys.path
from constants import HookName, IncidentKey, IncidentKind, IncidentPhase  # noqa: E402


# Freshness window for the failure-path HEAD check: a HEAD younger than this is treated as
# produced by the just-finished chain (the commit succeeded, a later segment failed).
HEAD_FRESHNESS_SECONDS = 60

# Wait budget for the commit-journal lock. A holder does one read-then-append pass, so genuine
# contention clears in milliseconds; a stall past the budget means the holder is wedged, and the
# entry is recorded as lost rather than waited on while the observed tool call hangs.
JOURNAL_LOCK_TIMEOUT_SECONDS = 5.0
JOURNAL_LOCK_POLL_SECONDS = 0.05

# Incident coordinates for a journalling failure. The key folds repeats of one cause into a single
# incident, and the three causes stay separate so an unwritable directory never merges with a stall.
JOURNAL_INCIDENT_PREFIX = "commit-journal"
CAUSE_DIR_UNWRITABLE = "journal_dir_unwritable"
CAUSE_LOCK_TIMEOUT = "journal_lock_timeout"
CAUSE_WRITE_FAILED = "journal_write_failed"


def get_commit_info() -> dict | None:
  """
  Return a dictionary describing the current `HEAD` commit, or `None` when no commit is reachable.

  Returns:
    A mapping with the repository root, commit SHA, commit date, author, branch, subject, body,
    list of changed files, and aggregate insertion and deletion counts. `None` when the working
    directory is not inside a git repository, when no commit exists yet, or when `git` is not on
    the executable search path.
  """
  try:
    root = subprocess.check_output(
      [ "git", "rev-parse", "--show-toplevel" ],
      stderr = subprocess.DEVNULL,
      text = True,
    ).strip()
  except (subprocess.CalledProcessError, FileNotFoundError):
    return None

  # sha, iso-date, author, subject — joined by NUL so subjects containing tabs survive intact
  try:
    raw = subprocess.check_output(
      [ "git", "log", "-1", "--pretty=format:%H%x00%cI%x00%an <%ae>%x00%s" ],
      stderr = subprocess.DEVNULL,
      text = True,
    )
    # waiver: inline numeric literal (maxsplit count), not a domain constant
    sha, date, author, subject = raw.split("\x00", 3)
  except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
    return None

  # branch the commit landed on; a detached HEAD or missing git leaves it blank
  try:
    branch = subprocess.check_output(
      [ "git", "rev-parse", "--abbrev-ref", "HEAD" ],
      stderr = subprocess.DEVNULL,
      text = True,
    ).strip()
  except (subprocess.CalledProcessError, FileNotFoundError):
    branch = ""

  # commit body below the subject line — trailers and prose the history searches later read
  try:
    body = subprocess.check_output(
      [ "git", "log", "-1", "--pretty=format:%b" ],
      stderr = subprocess.DEVNULL,
      text = True,
    )
  except (subprocess.CalledProcessError, FileNotFoundError):
    body = ""

  # file stats from numstat — insertions, deletions, filename per row
  try:
    numstat = subprocess.check_output(
      [ "git", "show", "--numstat", "--format=", "HEAD" ],
      stderr = subprocess.DEVNULL,
      text = True,
    ).strip()
  except (subprocess.CalledProcessError, FileNotFoundError):
    numstat = ""

  # accumulate per-file stats; binary files report "-" instead of a number and contribute zero
  files = []
  total_ins = 0
  total_del = 0
  for line in numstat.splitlines():
    parts = line.split("\t")
    # waiver: inline numeric literal (numstat column count), not a domain constant
    if len(parts) == 3:
      ins_raw, del_raw, path = parts
      ins = int(ins_raw) if ins_raw.isdigit() else 0
      dl = int(del_raw) if del_raw.isdigit() else 0
      files.append(path)
      total_ins += ins
      total_del += dl

  # one flat record per commit — the shape the ledger line is serialised from
  return {
    "root": root,
    "sha": sha,
    "date": date,
    "author": author,
    "branch": branch,
    "subject": subject,
    "body": body.strip(),
    "files": files,
    "insertions": total_ins,
    "deletions": total_del,
  }


def head_is_fresh() -> bool:
  """
  Report whether the current `HEAD` commit was created within the freshness window.

  Returns:
    True when the committer timestamp of `HEAD` lies within `HEAD_FRESHNESS_SECONDS` of the
    current wall clock. False when the timestamp is older, when the repository has no reachable
    `HEAD`, or when `git` is not on the executable search path.
  """
  try:
    raw = subprocess.check_output(
      [ "git", "log", "-1", "--pretty=format:%ct" ],
      stderr = subprocess.DEVNULL,
      text = True,
    ).strip()
    committed_at = int(raw)
  except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
    return False
  return abs(time.time() - committed_at) <= HEAD_FRESHNESS_SECONDS


def record_failure(root: str, cause: str, detail: str) -> None:
  """
  Record one commit-journalling failure as an incident in the repository's error ledger.

  Args:
    root: Absolute path to the repository root whose ledger receives the incident.
    cause: The cause token naming which part of the journalling step failed.
    detail: One-line human-readable description of the failure, including the underlying error.
  """
  # the ledger swallows its own failures, so an unrecordable incident still cannot fail the commit
  error_ledger.record(Path(root), {
    IncidentKey.INCIDENT: f"{JOURNAL_INCIDENT_PREFIX}:{cause}",
    IncidentKey.PHASE: IncidentPhase.OPENED,
    IncidentKey.KIND: IncidentKind.PLUGIN_ERROR,
    IncidentKey.CAUSE: cause,
    IncidentKey.DETAIL: detail,
    # waiver: the hook's own canonical name doubles as the actor label; IncidentActor names daemon subsystems only
    IncidentKey.ACTOR: HookName.COMMIT_RECORDER,
  })


def wait_for_lock(lock: TextIO) -> bool:
  """
  Take an exclusive lock on an open lock file, waiting up to the journal lock budget.

  Args:
    lock: An open, writable file object to lock.

  Returns:
    True once the lock is held by this process. False when the wait budget elapsed with the lock
    still held elsewhere, in which case nothing is locked.
  """
  # poll rather than block: a wedged holder must not keep the observed tool call waiting forever
  deadline = time.time() + JOURNAL_LOCK_TIMEOUT_SECONDS
  while True:
    try:
      fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
      return True
    except OSError:
      # guard: budget spent — leave the lock unheld so the caller records a dropped entry
      if time.time() >= deadline:
        return False
      time.sleep(JOURNAL_LOCK_POLL_SECONDS)


@contextlib.contextmanager
def journal_lock(path: str) -> Iterator[bool]:
  """
  Hold the commit journal's lock for the duration of the `with` block.

  Args:
    path: Absolute path of the lock file to take the lock on; created when missing.

  Yields:
    True when the lock is held for the body of the block, False when the wait budget elapsed
    without it. The lock is released when the block exits, however it exits.

  Raises:
    OSError: The lock file could not be opened for writing.
  """
  # waiver: stdlib file-mode / encoding literals, not domain constants
  with open(path, "w", encoding = "utf-8") as lock:
    yield wait_for_lock(lock)


def should_run(payload: dict) -> bool:
  """
  Decide whether the current hook invocation corresponds to a successful git commit.

  Args:
    payload: The Claude Code hook payload parsed from stdin. Expected to carry `tool_name`,
      `tool_input`, and optionally `tool_response`.

  Returns:
    - True when the payload represents a `mcp__git__git_commit` call, or a `Bash` call containing a
      `git commit` invocation anywhere in the command — leading, chained (`git add X && git commit
      -m "..." && git push`), or flag-prefixed (`git -C dir commit`) — whose recorded exit code is
      zero or unknown, or a failed such `Bash` call whose `HEAD` commit is nonetheless fresh (in a
      chain the exit code belongs to the last failed segment, so a successful commit followed by a
      failed push still records).
    - False for every other tool invocation, and for `Bash` git commits that left `HEAD` stale.
    - Quoted look-alikes (e.g. `echo "git commit"`) are accepted false positives: the hook is
      deliberately permissive, `get_commit_info()` still requires a real `HEAD`, and the caller's
      SHA dedup absorbs repeat and spurious firings.
  """
  # waiver: external-format hook-payload field name, not an internal key
  tool_name = payload.get("tool_name", "")
  # waiver: external Claude Code tool name, not a domain key
  if tool_name == "mcp__git__git_commit":
    return True
  # waiver: external Claude Code tool name, not a domain key
  if tool_name == "Bash":
    # waiver: external-format hook-payload field names, not internal keys
    command = payload.get("tool_input", {}).get("command", "")

    # search, not match: real-world commits are usually chained (`git add … && git commit …`),
    # so the commit verb rarely sits at position 0; each `(?:\s+-\S+(?:\s+[^-\s]\S*)?)` tolerates
    # one flag between `git` and `commit`, with or without a separate argument token (`-C dir`,
    # `-c k=v`, `--no-pager`). Flag arguments with embedded whitespace
    # (`git -C "dir with space" commit`) still don't match — accepted gap.
    if re.search(r"\bgit\b(?:\s+-\S+(?:\s+[^-\s]\S*)?)*\s+commit\b", command):
      # in PostToolUse a non-zero exit code belongs to the LAST failed segment of a chain, so a
      # successful commit followed by a failed push must still record; consult HEAD freshness
      # waiver: external-format hook-payload field name, not an internal key
      response = payload.get("tool_response", {})

      # response may carry "exit_code" or similar; be permissive when the field is absent
      # waiver: external-format hook-payload field name, not an internal key
      exit_code = response.get("exit_code")

      # guard: failed call — record only when HEAD is fresh (a genuinely failed `git commit`
      # leaves HEAD at the old, stale commit; the caller's SHA dedup covers re-commit retries)
      if exit_code is not None and exit_code != 0:
        return head_is_fresh()
      return True
  return False


def main() -> None:
  """
  Handle one hook invocation.

  Reads the hook payload from stdin, decides whether the call is a recordable git commit, gathers
  the commit metadata, and appends a single JSON line to `<repo-root>/.logs/commits.jsonl`. Never
  fails the originating tool call: a journalling failure is recorded in the repository's error
  ledger instead of raised.

  Guarantees:
    - The commit-journal read-then-append window is serialised across concurrent hook invocations.
    - Concurrent hook invocations for the same commit never leave a duplicate entry in the journal.
    - An entry the hook could not journal is recorded as an incident in the error ledger, never
      silently dropped.
  """
  # Enablement gate — first action. An expert spawn short-circuits here via a pure env check.
  # guard: hook disabled in the current context
  if not hook_gate.is_enabled(HookName.COMMIT_RECORDER):
    return

  # the hook payload names the tool call that just finished
  try:
    payload = json.load(sys.stdin)
  except (json.JSONDecodeError, ValueError):
    return

  # guard: payload is not a recordable commit
  if not should_run(payload):
    return

  # read the commit straight from git rather than trusting the command line
  info = get_commit_info()

  # guard: no commit metadata available (not in a repo, no HEAD, or git missing)
  if info is None:
    return

  # the repo root locates the ledger and is dropped from the record itself
  # waiver: one-off commit-record schema field name, not a reusable domain key
  root = info.pop("root")
  # waiver: filesystem path idiom (run-log directory), not a domain constant
  logs_dir = os.path.join(root, ".logs")
  try:
    os.makedirs(logs_dir, exist_ok = True)
  except OSError as e:
    record_failure(root, CAUSE_DIR_UNWRITABLE, f"cannot create the journal directory: {e}")
    return

  # the ledger downstream recall reads from
  # waiver: filesystem filename idiom (commit-ledger file), not a domain constant
  path = os.path.join(logs_dir, "commits.jsonl")

  # Contract:
  # Concurrent hook invocations observing the same commit never leave a duplicate entry
  # for that commit SHA in the journal file. An entry the hook could not journal is
  # recorded as an incident in the error ledger rather than silently dropped.

  # the read-then-append window below is serialised on this lock: two hooks firing on one commit
  # would otherwise each miss the other's line and append a duplicate, and the journal directory is
  # synced, so an unguarded append is not atomic on its own
  try:
    # waiver: lock-file suffix idiom (companion to the commit-ledger file), not a domain constant
    with journal_lock(path + ".lock") as locked:
      # guard: the holder outlived the wait budget — drop the entry, but leave it observable
      if not locked:
        # waiver: one-off commit-record schema field name, not a reusable domain key
        record_failure(root, CAUSE_LOCK_TIMEOUT, f"journal lock held elsewhere; dropped {info['sha']}")
        return

      # idempotency: don't append the same SHA twice (useful if the hook fires multiple times
      # somehow — e.g., for both Bash and MCP on the same commit)
      try:
        with open(path, encoding = "utf-8") as f:
          for line in f:
            try:
              entry = json.loads(line)
            except ValueError:
              continue

            # guard: SHA already recorded — skip duplicate append
            # waiver: one-off commit-record schema field name, not a reusable domain key
            if entry.get("sha") == info["sha"]:
              return
      except OSError:
        # an unreadable journal leaves nothing to dedup against; the append below reports the rest
        pass

      # append one JSON line; a write failure degrades to a missing entry, never a failed commit
      try:
        with open(path, "a", encoding = "utf-8") as f:
          f.write(json.dumps(info) + "\n")
      except OSError as e:
        record_failure(root, CAUSE_WRITE_FAILED, f"cannot append to the journal: {e}")
        return
  except OSError as e:
    record_failure(root, CAUSE_DIR_UNWRITABLE, f"cannot open the journal lock: {e}")
    return


if __name__ == "__main__":
  # noinspection PyBroadException
  try:
    main()
  # waiver: hook must never fail the tool call it observes — any crash degrades to a silent no-op
  except Exception:
    pass
  sys.exit(0)
