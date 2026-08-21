#!/usr/bin/env python3

"""
PreToolUse hook: block any git commit whose staged diff contains a secret.

Fires on:
- `Bash` tool calls — gated on the command containing a `git commit` invocation
  (flags between `git` and `commit`, including `-C <dir>`, are tolerated).
- `mcp__git__git_commit` calls — always a commit, no further filtering.

Behavior:
- Secret finding (private key, AWS key, API token literal, high-entropy secret-context
  line, credentialed connection string, bearer token) in the staged diff — this branch
  denies the tool call via `permissionDecision: "deny"`.
- Clean scan, non-commit call, malformed payload, outside a git repo, empty diff — no-op.

Gates (cross-cutting):
- Runs in EVERY repo, public or private — secrets never belong in git history. The only
  off-switch is `hook_gate` (`hooks.disabled` in `lazy.settings.json`, or the expert-spawn
  allow-list). This deliberately differs from the `lazy-guard.check-public` sibling, whose
  PII/infra warnings are meaningful only for repos with a declared public surface.
- A `-C <dir>` flag on the Bash git command retargets the scan to that repository, so
  commits into a mirror checkout are scanned too.
- Waivers from the target repo's `.guard-public.json` (when present) suppress known false
  positives; `public_scopes` do NOT apply — a secret is a finding wherever it lands.
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
  secret patterns, and denies the commit when any un-waived finding remains. No-op on any
  unsupported tool call, outside a git repository, and on a clean or empty diff.
  """
  # Enablement gate — first action. An expert spawn short-circuits here via a pure env check.
  # guard: hook disabled in the current context
  if not hook_gate.is_enabled(HookName.SECRETS_GUARD):
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

  # collect the staged diff (added lines only)
  added_lines = guard_checks.collect_staged_added_lines(root)
  # guard: nothing staged — nothing to scan
  if not added_lines:
    return

  # Contract: `public_scopes` never shield a secret — this hook scans every staged path,
  # public or private, so the config's scope globs are deliberately discarded.

  # waivers suppress known false positives
  waivers, _ = guard_checks.load_config(root)

  # secret findings decide the branch: any survivor denies the commit
  findings = guard_checks.scan_lines(added_lines, guard_checks.FAIL_CHECKS, waivers)
  # guard: clean scan — leave the trigger untouched
  if not findings:
    return

  # build the deny response
  msg_parts = [ "BLOCKED: staged changes contain potential secrets" ]
  msg_parts.extend(findings)
  msg_parts.append("")
  msg_parts.append(
    # waiver: one-off human-facing message
    "Run /lazy-guard.check-public for details and fixes, "
    "or add waivers to .guard-public.json"
  )
  result = {
    "hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "permissionDecision": "deny",
      "permissionDecisionReason": "\n".join(msg_parts),
    }
  }

  # the decision reaches Claude Code as the hook's stdout payload
  json.dump(result, sys.stdout)


if __name__ == "__main__":
  main()
