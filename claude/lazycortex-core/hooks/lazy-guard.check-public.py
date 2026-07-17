#!/usr/bin/env python3

"""
PreToolUse hook: scan staged git changes for secrets, PII, and infrastructure leaks before
committing to a public repo (or to the public subtree of a partially-public repo).

The hook fires on Bash tool calls matching `git commit` and on `mcp__git__git_commit` calls,
inspects the staged diff against the same patterns enforced by the `lazy-guard.check-public`
skill, and either blocks the commit (on secret findings) or injects an advisory warning
(on PII / infra / path findings).

Gating:
  - The hook only runs in repos that carry `.guard-waivers.json` at the root.
  - The waivers file may declare a `public_scopes` list of globs; when set, only staged
    files matching one of those globs are scanned and everything else is treated as
    private and ignored. When the field is absent or empty, the whole repo is scanned.

Waivers from `.guard-waivers.json` suppress known-acceptable findings.
"""

from __future__ import annotations
# waiver: bare-name sibling imports (flat bin/), resolved at runtime via sys.path; not statically resolvable
# pylint: disable=import-error,wrong-import-position

from typing import TypedDict

import json
import os
import re
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# Resolve the sibling bin/ dir so the enablement gate is importable.

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
import hook_gate  # noqa: E402
# waiver: intentional suppression — the flagged rule is a known false positive / accepted exception on this line
from constants import HookName  # noqa: E402


class _Check(TypedDict):
  """
  One secret/PII scan check: a compiled pattern plus a human-readable name.
  """
  name: str
  pattern: re.Pattern[str]


def _compile_scope_glob(glob: str) -> re.Pattern[str]:
  """
  Compile a repo-relative path glob (supporting `**`) to an anchored regular expression.

  The compiled pattern treats `**` as any depth (including empty), `*` as one path segment
  (no `/`), and `?` as a single non-slash character. Patterns are anchored at both ends and
  expect forward-slash separators (repo-root-relative).

  Args:
    glob: The glob pattern to compile.

  Returns:
    A compiled regular expression that matches paths covered by the glob.
  """
  parts = []
  i = 0
  while i < len(glob):
    c = glob[i]
    if c == "*" and i + 1 < len(glob) and glob[i + 1] == "*":
      parts.append(".*")
      i += 2
      # consume a following slash so `dir/**/file` also matches `dir/file`
      if i < len(glob) and glob[i] == "/":
        parts.append("/?")
        i += 1
    elif c == "*":
      parts.append("[^/]*")
      i += 1
    elif c == "?":
      parts.append("[^/]")
      i += 1
    elif c in r".^$+(){}|\\":
      parts.append(re.escape(c))
      i += 1
    else:
      parts.append(c)
      i += 1
  return re.compile("^" + "".join(parts) + "$")


def _in_public_scope(path: str, compiled_globs: list[re.Pattern[str]]) -> bool:
  """
  Return whether the given path is considered part of the public scope.

  Args:
    path: Repo-root-relative path to test.
    compiled_globs: Compiled scope globs from `.guard-waivers.json`.

  Returns:
    True when no scope globs are configured (legacy whole-repo-public behavior) or when
    the path matches at least one configured glob; False otherwise.
  """
  # guard: no scopes declared — treat the whole repo as public
  if not compiled_globs:
    return True
  return any(rx.match(path) for rx in compiled_globs)

# ----------------------------------------------------------------------------------------
# Check categories and patterns
# ----------------------------------------------------------------------------------------

# Category A: Secrets (FAIL — blocks commit)
FAIL_CHECKS: dict[str, _Check] = {
  "A1": {
    "name": "Private key marker",
    "pattern": re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----"),
  },
  "A2": {
    "name": "AWS access key",
    "pattern": re.compile(r"AKIA[0-9A-Z]{16}"),
  },
  "A3": {
    "name": "API key/token/password literal",
    "pattern": re.compile(
      r'(?i)(api[_-]?key|api[_-]?secret|api[_-]?token|password|passwd)'
      r'''\s*[=:"']\s*["']?[A-Za-z0-9_\-/.+]{20,}'''
    ),
  },
  "A4": {
    "name": "High-entropy base64 on secret-context line",
    "pattern": re.compile(
      r'(?i)(key|token|secret|password|encryption|credential)'
      r'''\s*[=:"']\s*["']?[A-Za-z0-9+/]{32,}={0,2}["']?'''
    ),
  },
  "A5": {
    "name": "Connection string with credentials",
    "pattern": re.compile(
      r"(?i)(mysql|postgres|mongodb|redis|amqp|ftp)://[^@\s]+:[^@\s]+@"
    ),
  },
  "A6": {
    "name": "Bearer token literal",
    "pattern": re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-.]{20,}"),
  },
}

# Category B/C/D: WARN — allows commit but injects warning
WARN_CHECKS: dict[str, _Check] = {
  "B1": {
    "name": "Email address",
    "pattern": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
  },
  "B2": {
    "name": "Service user ID",
    "pattern": re.compile(
      r"(?i)(telegram|tg|user[_-]?id|chat[_-]?id|allow[_-]?from)"
      r"""[\s=:"'\[]+\d{6,12}"""
    ),
  },
  "C1": {
    "name": "Tailscale/CGNAT IP",
    "pattern": re.compile(
      r"\b100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"
    ),
  },
  "D1": {
    "name": "Hardcoded absolute user path",
    "pattern": re.compile(r"/(Users|home)/\w+/"),
  },
}

# Lines matching these are safe (template expressions, variable refs, etc.)
SAFE_LINE_PATTERNS = [
  re.compile(r"\{\{.*\}\}"),           # chezmoi template expression
  re.compile(r'[=:"\']\s*\$\{?\w'),    # shell variable reference
  re.compile(r"@example\.(com|org)"),  # example domains
  re.compile(r"@test\.com"),
  re.compile(r"noreply@"),
  re.compile(r"no-reply@"),
  re.compile(r"Co-Authored-By:"),      # git trailer
]

# ----------------------------------------------------------------------------------------
# Waiver loading
# ----------------------------------------------------------------------------------------


def load_config(root: str) -> tuple[list, list[re.Pattern[str]]]:
  """
  Load the waivers and public-scope globs declared for a repository.

  Reads `<root>/.guard-waivers.json`. A missing or unreadable file yields an empty result.
  Scope-glob entries that are not non-empty strings or that fail to compile are silently
  dropped; the remaining entries are returned in source order. An empty list of scope globs
  signals the legacy behavior of treating the whole repo as public.

  Args:
    root: Absolute path to the repository root.

  Returns:
    A tuple `(waivers, compiled_scope_globs)` where `waivers` is the list of waiver dicts
    from the file and `compiled_scope_globs` is the list of compiled scope-glob regexes.
  """
  # waiver: filesystem filename idiom (guard-waivers config file), not a domain constant
  waiver_path = os.path.join(root, ".guard-waivers.json")
  try:
    with open(waiver_path, encoding = "utf-8") as f:
      data = json.load(f)
  except (json.JSONDecodeError, OSError):
    return [], []
  # waiver: external-format guard-waivers config field names, not internal keys
  waivers = data.get("waivers", []) or []
  # waiver: external-format guard-waivers config field name, not an internal key
  scopes_raw = data.get("public_scopes", []) or []
  compiled = []
  for g in scopes_raw:
    # guard: drop non-string or empty scope entries
    if not isinstance(g, str) or not g:
      continue
    try:
      compiled.append(_compile_scope_glob(g))
    except re.error:
      # invalid glob — skip silently so a single bad entry doesn't disable the whole config
      continue
  return waivers, compiled


def is_waived(check_id: str, file_path: str, matched_text: str, waivers: list) -> bool:
  """
  Return whether a finding is covered by any configured waiver.

  A waiver matches when its check identifier covers the finding (`*` or exact match), its
  scope glob covers the file path (`*` or `fnmatch`), its pattern matches the offending
  text (case-insensitive `re.search`), and any declared expiry is still in the future.

  Args:
    check_id: Identifier of the check that produced the finding (e.g. `"A3"`).
    file_path: Repo-relative path of the file where the finding occurred.
    matched_text: Substring captured by the check's regex.
    waivers: Waiver dicts loaded from `.guard-waivers.json`.

  Returns:
    True if at least one waiver covers the finding; False otherwise.
  """
  # waiver: deferred / late-bound local import per the plugin import style (avoids import cycles / optional deps)
  from datetime import date

  today = date.today().isoformat()
  for w in waivers:
    # check-id match
    # waiver: external-format guard-waivers config field name, not an internal key
    wcheck = w.get("check", "*")
    # guard: skip waivers whose check id does not match
    if wcheck not in ("*", check_id):
      continue
    # scope match
    # waiver: external-format guard-waivers config field name, not an internal key
    scope = w.get("scope", "*")
    # guard: skip waivers whose scope does not cover this path
    if scope != "*" and not fnmatch(file_path, scope):
      continue
    # pattern match
    try:
      # guard: skip waivers whose pattern does not match the finding
      if not re.search(w.get("pattern", ""), matched_text, re.IGNORECASE):
        continue
    except re.error:
      continue
    # expiry check
    # waiver: external-format guard-waivers config field name, not an internal key
    expires = w.get("expires")
    # guard: skip expired waivers
    if expires and today >= expires:
      continue
    return True
  return False


# ----------------------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------------------


def main() -> None:
  """
  Entry point for the PreToolUse hook.

  Reads the Claude Code hook payload from stdin, decides whether the tool call is a git
  commit to scan, walks the staged diff for added lines that hit secret or warn patterns,
  and writes the hook decision to stdout. Findings classified as secrets block the commit
  via `permissionDecision: "deny"`; lower-severity findings are surfaced as additional
  context but do not block. The hook is a no-op on any unsupported tool call, on repos
  without `.guard-waivers.json`, when no staged diff is present, and when scope filtering
  drops every staged file.

  Returns:
    None. The hook decision (if any) is serialized as JSON on stdout.
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

  # waiver: external-format hook-payload field name, not an internal key
  tool_name = hook_input.get("tool_name", "")
  # waiver: external-format hook-payload field name, not an internal key
  tool_input = hook_input.get("tool_input", {})

  # gate: only git commit commands (Bash or MCP git)
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
  # waiver: external Claude Code tool name, not a domain key
  elif tool_name == "mcp__git__git_commit":
    pass  # always a commit, no further filtering needed
  else:
    return

  # only run in repos that opted in via .guard-waivers.json
  try:
    root = subprocess.check_output(
      [ "git", "rev-parse", "--show-toplevel" ],
      stderr = subprocess.DEVNULL,
      text = True,
    ).strip()
  except (subprocess.CalledProcessError, FileNotFoundError):
    return
  # guard: opt-in file absent — leave the trigger untouched
  # waiver: filesystem filename idiom (guard-waivers opt-in file), not a domain constant
  if not os.path.isfile(os.path.join(root, ".guard-waivers.json")):
    return

  # collect the staged diff (added lines only)
  try:
    diff = subprocess.check_output(
      [ "git", "diff", "--cached", "--diff-filter=ACMR", "-U0" ],
      stderr = subprocess.DEVNULL,
      text = True,
    )
  except (subprocess.CalledProcessError, FileNotFoundError):
    # no diff or git not available
    return

  # guard: nothing staged — nothing to scan
  if not diff:
    return

  # parse diff into (file, line_content) pairs — only added lines
  current_file = None
  added_lines = []
  for line in diff.splitlines():
    # waiver: git diff-output token, not a domain constant
    if line.startswith("diff --git"):
      match = re.search(r" b/(.+)$", line)
      if match:
        current_file = match.group(1)
    elif line.startswith("+") and not line.startswith("+++"):
      content = line[1:]  # strip leading +
      if current_file:
        added_lines.append((current_file, content))

  # guard: no added content captured from the diff
  if not added_lines:
    return

  # drop .age files — they're encrypted by design
  # waiver: filesystem extension idiom (age-encrypted artifact), not a domain constant
  added_lines = [ (f, c) for f, c in added_lines if not f.endswith(".age") ]
  # guard: every staged file was an .age artifact
  if not added_lines:
    return

  waivers, scope_globs = load_config(root)

  # subtree-public mode: drop changes outside the declared public scopes.
  # No scopes declared -> treat the whole repo as public (legacy behavior).
  if scope_globs:
    added_lines = [ (f, c) for f, c in added_lines if _in_public_scope(f, scope_globs) ]
    # guard: nothing remains after scope filtering
    if not added_lines:
      return

  fail_findings = []
  warn_findings = []

  for file_path, content in added_lines:
    # skip safe lines (templates, variable refs, etc.)
    # guard: skip lines matching a known safe-line pattern
    if any(p.search(content) for p in SAFE_LINE_PATTERNS):
      continue

    # check FAIL patterns
    for check_id, check in FAIL_CHECKS.items():
      # waiver: internal check-definition schema field name, single-source set in FAIL_CHECKS/WARN_CHECKS
      m = check["pattern"].search(content)
      if m and not is_waived(check_id, file_path, m.group(), waivers):
        fail_findings.append(
          # waiver: internal check-definition schema field name, single-source set in FAIL_CHECKS/WARN_CHECKS
          f"  [{check_id}] {check['name']}: {file_path}"
        )

    # check WARN patterns
    for check_id, check in WARN_CHECKS.items():
      # waiver: internal check-definition schema field name, single-source set in FAIL_CHECKS/WARN_CHECKS
      m = check["pattern"].search(content)
      if m and not is_waived(check_id, file_path, m.group(), waivers):
        warn_findings.append(
          # waiver: internal check-definition schema field name, single-source set in FAIL_CHECKS/WARN_CHECKS
          f"  [{check_id}] {check['name']}: {file_path}"
        )

  # deduplicate
  fail_findings = list(dict.fromkeys(fail_findings))
  warn_findings = list(dict.fromkeys(warn_findings))

  # guard: clean scan — nothing to surface to the user
  if not fail_findings and not warn_findings:
    return

  # build response
  if fail_findings:
    # block commit
    msg_parts = [ "BLOCKED: staged changes contain potential secrets" ]
    msg_parts.extend(fail_findings)
    if warn_findings:
      msg_parts.append("")
      # waiver: one-off human-facing message
      msg_parts.append("Also found warnings:")
      msg_parts.extend(warn_findings)
    msg_parts.append("")
    msg_parts.append(
      # waiver: one-off human-facing message
      "Run /lazy-guard.check-public for details and fixes, "
      "or add waivers to .guard-waivers.json"
    )
    result = {
      "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "\n".join(msg_parts),
      }
    }
  else:
    # warn but allow
    msg_parts = [ "WARNING: staged changes contain flagged content" ]
    msg_parts.extend(warn_findings)
    msg_parts.append("")
    msg_parts.append(
      # waiver: one-off human-facing message
      "Run /lazy-guard.check-public to review, "
      "or add waivers to .guard-waivers.json"
    )
    result = {
      "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": "\n".join(msg_parts),
      }
    }

  json.dump(result, sys.stdout)


if __name__ == "__main__":
  main()
