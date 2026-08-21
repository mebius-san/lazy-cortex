#!/usr/bin/env python3

"""
PreToolUse hook: warn about PII and infrastructure leaks staged for a public repo (or for
the public subtree of a partially-public repo).

Fires on:
- `Bash` tool calls — gated on the command containing a `git commit` invocation
  (flags between `git` and `commit`, including `-C <dir>`, are tolerated).
- `mcp__git__git_commit` calls — always a commit, no further filtering.

Behavior:
- PII / infrastructure / path finding (email, service user ID, Tailscale IP, absolute
  user path) in the staged diff — this branch injects an advisory warning via
  `additionalContext`; the commit proceeds.
- Clean scan, non-commit call, malformed payload, outside a git repo, empty diff — no-op.

Gates (cross-cutting):
- The hook only runs in repos that carry `.guard-public.json` at the root — the marker
  `lazy-repo.mark-public` writes when a repo (or a subtree) is declared public. Private
  repos have no public surface for these warnings to protect. Secrets are NOT this hook's
  business: the always-on `lazy-guard.secrets` sibling blocks those in every repo.
- A `-C <dir>` flag on the Bash git command retargets the scan to that repository.
- `.guard-public.json` may declare a `public_scopes` list of globs; when set, only staged
  files matching one of those globs are scanned and everything else is treated as private
  and ignored. When the field is absent or empty, the whole repo is scanned. Waivers from
  the same file suppress known-acceptable findings.
"""

from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

import json
import re
import sys
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Resolve the sibling bin/ dir so the enablement gate and scan primitives are importable.

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design)
import guard_checks  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design)
import hook_gate  # noqa: E402
# waiver: deferred sibling import follows the sys.path.insert above (ruff E402 by design)
from constants import HookName  # noqa: E402


def main() -> None:
  """
  Entry point for the PreToolUse hook.

  Reads the Claude Code hook payload from stdin, decides whether the tool call is a git
  commit to scan, walks the staged diff of the target repository for added lines hitting
  PII / infrastructure patterns inside the declared public scope, and surfaces surviving
  findings as advisory context. No-op on any unsupported tool call, on repos without
  `.guard-public.json`, when no staged diff is present, and when scope filtering drops
  every staged file.
  """
  # Enablement gate — first action. An expert spawn short-circuits here via a pure env check.
  # guard: hook disabled in the current context
  if not hook_gate.is_enabled(HookName.CHECK_PUBLIC):
    return

  # parse hook input
  try:
    hook_input = json.load(sys.stdin)
  except (json.JSONDecodeError, ValueError):
    # not JSON — ignore silently so a malformed payload never crashes the trigger
    return

  # the tool identity and its input decide whether this call is a commit worth scanning
  # waiver: external-format hook-payload field name, not an internal key
  tool_name = hook_input.get("tool_name", "")
  # waiver: external-format hook-payload field name, not an internal key
  tool_input = hook_input.get("tool_input", {})

  # gate: only git commit commands (Bash or MCP git); Bash may retarget via `-C <dir>`
  chdir = None
  # waiver: external Claude Code tool name, not a domain key
  if tool_name == "Bash":
    # waiver: external-format tool-input field name, not an internal key
    command = tool_input.get("command", "")
    # guard: ignore Bash calls with no `git commit` invocation anywhere in the command
    # (search, not match: chained commands like `git add … && git commit …` must still gate;
    # each `(?:\s+-\S+(?:\s+[^-\s]\S*)?)` tolerates one flag between `git` and `commit`, with or
    # without a separate argument token — `-C dir`, `-c k=v`, `--no-pager`. Quoted look-alikes
    # (`echo "git commit"`) are accepted false positives — a spurious firing merely triggers a
    # harmless extra scan. Flag arguments with embedded whitespace
    # (`git -C "dir with space" commit`) still don't match — accepted gap.)
    if not re.search(r"\bgit\b(?:\s+-\S+(?:\s+[^-\s]\S*)?)*\s+commit\b", command):
      return
    chdir = guard_checks.extract_git_chdir(command)
  # waiver: external Claude Code tool name, not a domain key
  elif tool_name == "mcp__git__git_commit":
    pass  # always a commit, no further filtering needed
  else:
    return

  # the scan targets the repo the commit lands in, not necessarily the process cwd
  root = guard_checks.find_repo_root(chdir)
  # guard: not inside a git repository — nothing to scan
  if root is None:
    return
  # guard: public-marker file absent — this repo declares no public surface
  if not guard_checks.has_config(root):
    return

  # collect the staged diff (added lines only)
  added_lines = guard_checks.collect_staged_added_lines(root)
  # guard: nothing staged — nothing to scan
  if not added_lines:
    return

  # the repo's own waivers and public scopes govern what counts as a finding here
  waivers, scope_globs = guard_checks.load_config(root)

  # subtree-public mode: drop changes outside the declared public scopes.
  # No scopes declared -> treat the whole repo as public (legacy behavior).
  if scope_globs:
    added_lines = [
      (f, c) for f, c in added_lines if guard_checks.in_public_scope(f, scope_globs)
    ]
    # guard: nothing remains after scope filtering
    if not added_lines:
      return

  # advisory findings decide the branch: any survivor warns, none blocks
  warn_findings = guard_checks.scan_lines(added_lines, guard_checks.WARN_CHECKS, waivers)
  # guard: clean scan — nothing to surface to the user
  if not warn_findings:
    return

  # warn but allow
  msg_parts = [ "WARNING: staged changes contain flagged content" ]
  msg_parts.extend(warn_findings)
  msg_parts.append("")
  msg_parts.append(
    # waiver: one-off human-facing message
    "Run /lazy-guard.check-public to review, "
    "or add waivers to .guard-public.json"
  )
  result = {
    "hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "additionalContext": "\n".join(msg_parts),
    }
  }

  # the decision reaches Claude Code as the hook's stdout payload
  json.dump(result, sys.stdout)


if __name__ == "__main__":
  main()
