#!/usr/bin/env python3

"""
PostToolUse hook that records every successful git commit to `.logs/commits.jsonl`.

Fires after `Bash(git commit*)` or `mcp__git__git_commit`. Writes one JSON line per commit with the
SHA, ISO date, author, branch, subject, body, file list, and aggregate insertions / deletions. The
file is the raw commit feed that `lazy-log.distill` later converts into functional prose in
`.logs/changelog.md`, and that `lazy-log.recall` searches.

Notes:
  - No LLM call, no network, fast (~50ms).
  - Silent on failure — the hook never blocks the commit outcome.
  - Creates the `.logs/` directory if missing.
  - Works whether the commit was invoked via `Bash` or via the `mcp__git__git_commit` tool.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


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

  try:
    # sha, iso-date, author, subject — joined by NUL so subjects containing tabs survive intact
    raw = subprocess.check_output(
      [ "git", "log", "-1", "--pretty=format:%H%x00%cI%x00%an <%ae>%x00%s" ],
      stderr = subprocess.DEVNULL,
      text = True,
    )
    # waiver: inline numeric literal (maxsplit count), not a domain constant
    sha, date, author, subject = raw.split("\x00", 3)
  except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
    return None

  try:
    branch = subprocess.check_output(
      [ "git", "rev-parse", "--abbrev-ref", "HEAD" ],
      stderr = subprocess.DEVNULL,
      text = True,
    ).strip()
  except (subprocess.CalledProcessError, FileNotFoundError):
    branch = ""

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


def should_run(payload: dict) -> bool:
  """
  Decide whether the current hook invocation corresponds to a successful git commit.

  Args:
    payload: The Claude Code hook payload parsed from stdin. Expected to carry `tool_name`,
      `tool_input`, and optionally `tool_response`.

  Returns:
    True when the payload represents a successful `mcp__git__git_commit` call or a `Bash` call
    whose command starts with `git commit` and whose recorded exit code is zero or unknown.
    False for every other tool invocation and for `Bash` git commits whose response carries a
    non-zero exit code.
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
    if re.match(r"git\s+commit\b", command):
      # in PostToolUse we also want to skip failures; consult tool_response when present
      # waiver: external-format hook-payload field name, not an internal key
      response = payload.get("tool_response", {})
      # response may carry "exit_code" or similar; be permissive when the field is absent
      # waiver: external-format hook-payload field name, not an internal key
      exit_code = response.get("exit_code")
      # guard: known failure exit code — do not record
      if exit_code is not None and exit_code != 0:
        return False
      return True
  return False


def main() -> None:
  """
  Entry point invoked once per hook trigger.

  Reads the hook payload from stdin, decides whether the call is a recordable git commit, gathers
  the commit metadata, and appends a single JSON line to `<repo-root>/.logs/commits.jsonl`. Every
  failure path returns silently so the hook never blocks the originating tool call.
  """
  try:
    payload = json.load(sys.stdin)
  except (json.JSONDecodeError, ValueError):
    return

  # guard: payload is not a recordable commit
  if not should_run(payload):
    return

  info = get_commit_info()
  # guard: no commit metadata available (not in a repo, no HEAD, or git missing)
  if info is None:
    return

  # waiver: one-off commit-record schema field name, not a reusable domain key
  root = info.pop("root")
  # waiver: filesystem path idiom (run-log directory), not a domain constant
  logs_dir = os.path.join(root, ".logs")
  try:
    os.makedirs(logs_dir, exist_ok = True)
  except OSError:
    return

  # waiver: filesystem filename idiom (commit-ledger file), not a domain constant
  path = os.path.join(logs_dir, "commits.jsonl")

  # idempotency: don't append the same SHA twice (useful if the hook fires multiple times somehow
  # — e.g., for both Bash and MCP on the same commit)
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
  except FileNotFoundError:
    pass

  try:
    with open(path, "a", encoding = "utf-8") as f:
      f.write(json.dumps(info) + "\n")
  except OSError:
    return


if __name__ == "__main__":
  # noinspection PyBroadException
  try:
    main()
  except Exception:
    pass
  sys.exit(0)
