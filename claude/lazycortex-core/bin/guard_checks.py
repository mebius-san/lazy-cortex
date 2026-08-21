#!/usr/bin/env python3

"""
Shared pattern library and scan primitives for the lazy-guard hook family.

Owns the secret (FAIL) and PII/infrastructure (WARN) check registries, the safe-line
suppressions, the `.guard-public.json` config loader (waivers + `public_scopes`), and the
staged-diff / whole-file scanning helpers. Consumed by the `lazy-guard.secrets` and
`lazy-guard.check-public` hooks and by the publish-time secret gate.

CLI: `guard_checks.py scan-files <path>...` scans full file contents against the FAIL
checks (waivers honoured, safe lines skipped) and exits non-zero when findings remain —
the shape publish pipelines gate on.
"""

from __future__ import annotations

from typing import TypedDict

import json
import os
import re
import subprocess
import sys
from datetime import date
from fnmatch import fnmatch

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  pass


# waiver: filesystem filename idiom (guard opt-in / waivers config file), not a domain constant
CONFIG_FILENAME = ".guard-public.json"

# waiver: one-off human-facing CLI header
SCAN_FINDINGS_HEADER = "SECRETS FOUND:"


class Check(TypedDict):
  """
  One secret/PII scan check: a compiled pattern plus a human-readable name.

  Attributes:
    name: Human-readable label identifying the check in findings output.
    pattern: Compiled regular expression the check matches against scanned lines.
  """
  name: str
  pattern: re.Pattern[str]


# Category A: Secrets (FAIL — blocks commit / publish)
FAIL_CHECKS: dict[str, Check] = {
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
WARN_CHECKS: dict[str, Check] = {
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


def compile_scope_glob(glob: str) -> re.Pattern[str]:
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


def in_public_scope(path: str, compiled_globs: list[re.Pattern[str]]) -> bool:
  """
  Return whether the given path is considered part of the public scope.

  Args:
    path: Repo-root-relative path to test.
    compiled_globs: Compiled scope globs from the guard config.

  Returns:
    True when no scope globs are configured (legacy whole-repo-public behavior) or when
    the path matches at least one configured glob; False otherwise.
  """
  # guard: no scopes declared — treat the whole repo as public
  if not compiled_globs:
    return True
  return any(rx.match(path) for rx in compiled_globs)


def load_config(root: str) -> tuple[list, list[re.Pattern[str]]]:
  """
  Load the waivers and public-scope globs declared for a repository.

  Reads the guard config file at the repository root. A missing or unreadable file yields
  an empty result. Scope-glob entries that are not non-empty strings or that fail to
  compile are silently dropped; the remaining entries are returned in source order. An
  empty list of scope globs signals the legacy behavior of treating the whole repo as
  public.

  Args:
    root: Absolute path to the repository root.

  Returns:
    A tuple `(waivers, compiled_scope_globs)` where `waivers` is the list of waiver dicts
    from the file and `compiled_scope_globs` is the list of compiled scope-glob regexes.
  """
  config_path = os.path.join(root, CONFIG_FILENAME)
  try:
    with open(config_path, encoding = "utf-8") as f:
      data = json.load(f)
  except (json.JSONDecodeError, OSError):
    return [], []
  # waiver: external-format guard config field names, not internal keys
  waivers = data.get("waivers", []) or []
  # waiver: external-format guard config field name, not an internal key
  scopes_raw = data.get("public_scopes", []) or []
  compiled = []
  for g in scopes_raw:
    # guard: drop non-string or empty scope entries
    if not isinstance(g, str) or not g:
      continue
    try:
      compiled.append(compile_scope_glob(g))
    except re.error:
      # invalid glob — skip silently so a single bad entry doesn't disable the whole config
      continue
  return waivers, compiled


def has_config(root: str) -> bool:
  """
  Report whether the repository carries the guard config file at its root.

  Args:
    root: Absolute path to the repository root.

  Returns:
    True when the config file exists; False otherwise.
  """
  return os.path.isfile(os.path.join(root, CONFIG_FILENAME))


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
    waivers: Waiver dicts loaded from the guard config.

  Returns:
    True if at least one waiver covers the finding; False otherwise.
  """
  # a waiver covers the finding only when check id, scope, pattern, and expiry all agree
  today = date.today().isoformat()
  for w in waivers:
    # check-id match
    # waiver: external-format guard config field name, not an internal key
    wcheck = w.get("check", "*")
    # guard: skip waivers whose check id does not match
    if wcheck not in ("*", check_id):
      continue
    # scope match
    # waiver: external-format guard config field name, not an internal key
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
    # waiver: external-format guard config field name, not an internal key
    expires = w.get("expires")
    # guard: skip expired waivers
    if expires and today >= expires:
      continue
    return True
  return False


def extract_git_chdir(command: str) -> str | None:
  """
  Extract the directory a Bash git command targets via a `-C <dir>` flag, when present.

  Only the first `-C` occurrence between `git` and its subcommand is honoured, matching
  how the hooks' commit-gate regex tolerates flags. Quoted paths with embedded whitespace
  are not resolved — the caller falls back to the process cwd for those (accepted gap,
  same as the commit-gate regex).

  Args:
    command: The full Bash command string from the hook payload.

  Returns:
    The `-C` argument when the command carries one; None otherwise.
  """
  m = re.search(r"\bgit\s+(?:-(?!C)\S+(?:\s+[^-\s]\S*)?\s+)*-C\s+([^-\s]\S*)", command)
  return m.group(1) if m else None


def find_repo_root(cwd: str | None = None) -> str | None:
  """
  Resolve the absolute root of the git repository containing `cwd`.

  Args:
    cwd: Directory to resolve from; the process cwd when omitted.

  Returns:
    The repository root path, or None when `cwd` is not inside a git repository or the
    `git` binary is unavailable.
  """
  try:
    root = subprocess.check_output(
      [ "git", "rev-parse", "--show-toplevel" ],
      stderr = subprocess.DEVNULL,
      text = True,
      cwd = cwd,
    ).strip()
  except (subprocess.CalledProcessError, FileNotFoundError, NotADirectoryError, OSError):
    return None
  return root or None


def collect_staged_added_lines(root: str) -> list[tuple[str, str]]:
  """
  Collect the added lines of the repository's staged diff as `(file, line)` pairs.

  Age-encrypted files (`.age`) are dropped — they are unreadable by design and can only
  produce false positives.

  Args:
    root: Absolute path to the repository root whose index is read.

  Returns:
    The `(repo-relative path, added line content)` pairs of the staged diff, empty when
    nothing is staged or git is unavailable.
  """
  try:
    diff = subprocess.check_output(
      [ "git", "diff", "--cached", "--diff-filter=ACMR", "-U0" ],
      stderr = subprocess.DEVNULL,
      text = True,
      cwd = root,
    )
  except (subprocess.CalledProcessError, FileNotFoundError):
    return []

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
      if current_file:
        added_lines.append((current_file, line[1:]))

  # drop .age files — they're encrypted by design
  # waiver: filesystem extension idiom (age-encrypted artifact), not a domain constant
  return [ (f, c) for f, c in added_lines if not f.endswith(".age") ]


def scan_lines(
  lines: list[tuple[str, str]], checks: dict[str, Check], waivers: list,
) -> list[str]:
  """
  Scan `(file, line)` pairs against a check registry, honouring safe lines and waivers.

  Args:
    lines: The `(repo-relative path, line content)` pairs to scan.
    checks: The check registry to match (`FAIL_CHECKS` or `WARN_CHECKS`).
    waivers: Waiver dicts loaded from the guard config.

  Returns:
    Deduplicated human-readable finding lines, one per `(check, file)` hit.
  """
  findings = []
  for file_path, content in lines:
    # guard: skip lines matching a known safe-line pattern
    if any(p.search(content) for p in SAFE_LINE_PATTERNS):
      continue
    for check_id, check in checks.items():
      # waiver: internal check-definition schema field name, single-source set in FAIL_CHECKS/WARN_CHECKS
      m = check["pattern"].search(content)
      if m and not is_waived(check_id, file_path, m.group(), waivers):
        # waiver: internal check-definition schema field name, single-source set in FAIL_CHECKS/WARN_CHECKS
        findings.append(f"  [{check_id}] {check['name']}: {file_path}")
  return list(dict.fromkeys(findings))


def main(argv: list[str]) -> int:
  """
  Run the `scan-files` CLI: scan whole files against the FAIL checks.

  Reads each named file, scans every line against `FAIL_CHECKS` with the repo's waivers
  applied (config resolved from the first file's repository root), and prints findings.

  Args:
    argv: CLI arguments after the script name — the literal `scan-files` verb followed by
      one or more file paths.

  Returns:
    0 on a clean scan, 1 when findings remain, 2 on invocation error.
  """
  # guard: wrong verb or no paths — refuse with usage
  # waiver: one-off CLI verb literal, single call site
  if len(argv) < 2 or argv[0] != "scan-files":
    sys.stderr.write("usage: guard_checks.py scan-files <path>...\n")
    return 2

  # the first file's repo supplies the waivers every scanned path is judged against
  root = find_repo_root(os.path.dirname(os.path.abspath(argv[1])) or None)
  waivers, _ = load_config(root) if root else ([], [])

  # scan every readable file line by line; unreadable/binary files are skipped silently
  lines: list[tuple[str, str]] = []
  for path in argv[1:]:
    rel = os.path.relpath(path, root) if root else path
    try:
      # waiver: stdlib open() error-mode literal, not a domain constant
      with open(path, encoding = "utf-8", errors = "strict") as f:
        lines.extend((rel, line.rstrip("\n")) for line in f)
    except (OSError, UnicodeDecodeError):
      continue

  # findings decide the exit code — the publish gate branches on it
  findings = scan_lines(lines, FAIL_CHECKS, waivers)
  # guard: clean scan
  if not findings:
    return 0
  sys.stdout.write(SCAN_FINDINGS_HEADER + "\n" + "\n".join(findings) + "\n")
  return 1


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
