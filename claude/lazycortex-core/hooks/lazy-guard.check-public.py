#!/usr/bin/env python3
"""PreToolUse hook: scan staged git changes for secrets, PII, and infrastructure
leaks before committing to a public repo (or the public subtree of a repo).

Fires on Bash tool calls matching `git commit` (and mcp__git__git_commit).
Checks staged diff content against the same patterns used by the
lazy-guard.check-public skill.

- FAIL findings (secrets): block the commit
- WARN findings (PII, infra, paths): inject a warning but allow

Gating: the hook only runs in repos that have `.guard-waivers.json` at the
root. That file can also declare a `public_scopes` list of globs — when set,
only staged files matching one of those globs are scanned; everything else
is treated as private and ignored. When the field is absent or empty, the
whole repo is scanned.

Reads waivers from `.guard-waivers.json` to suppress known-acceptable
findings.
"""

import json
import os
import re
import subprocess
import sys
from fnmatch import fnmatch


def _compile_scope_glob(glob):
    """Compile a path glob (supporting `**`) to a regex.

    `**` matches any depth (including empty); `*` matches one path segment
    (no `/`). Patterns are anchored at both ends. Paths are repo-root-
    relative, forward-slash separated.
    """
    parts = []
    i = 0
    while i < len(glob):
        c = glob[i]
        if c == "*" and i + 1 < len(glob) and glob[i + 1] == "*":
            parts.append(".*")
            i += 2
            # Consume a following slash so `dir/**/file` also matches `dir/file`.
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


def _in_public_scope(path, compiled_globs):
    """Return True if `path` matches any compiled glob, or if list is empty."""
    if not compiled_globs:
        return True
    return any(rx.match(path) for rx in compiled_globs)

# ---------------------------------------------------------------------------
# Check categories and patterns
# ---------------------------------------------------------------------------

# Category A: Secrets (FAIL — blocks commit)
FAIL_CHECKS = {
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
WARN_CHECKS = {
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
    re.compile(r"@example\.(com|org)"),   # example domains
    re.compile(r"@test\.com"),
    re.compile(r"noreply@"),
    re.compile(r"no-reply@"),
    re.compile(r"Co-Authored-By:"),       # git trailer
]

# ---------------------------------------------------------------------------
# Waiver loading
# ---------------------------------------------------------------------------


def load_config(root):
    """Load .guard-waivers.json; return (waivers, compiled_scope_globs).

    Missing file or parse errors -> ([], []). An empty list of scope globs
    means "whole repo is public" (legacy behavior).
    """
    waiver_path = os.path.join(root, ".guard-waivers.json")
    try:
        with open(waiver_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return [], []
    waivers = data.get("waivers", []) or []
    scopes_raw = data.get("public_scopes", []) or []
    compiled = []
    for g in scopes_raw:
        if not isinstance(g, str) or not g:
            continue
        try:
            compiled.append(_compile_scope_glob(g))
        except re.error:
            continue
    return waivers, compiled


def is_waived(check_id, file_path, matched_text, waivers):
    """Check if a finding is covered by any waiver."""
    from datetime import date

    today = date.today().isoformat()
    for w in waivers:
        # Check ID match
        wcheck = w.get("check", "*")
        if wcheck != "*" and wcheck != check_id:
            continue
        # Scope match
        scope = w.get("scope", "*")
        if scope != "*" and not fnmatch(file_path, scope):
            continue
        # Pattern match
        try:
            if not re.search(w.get("pattern", ""), matched_text, re.IGNORECASE):
                continue
        except re.error:
            continue
        # Expiry check
        expires = w.get("expires")
        if expires and today >= expires:
            continue
        return True
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    # Parse hook input
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return  # not JSON, ignore

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    # Gate: only git commit commands (Bash or MCP git)
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if not re.match(r"git\s+commit\b", command):
            return
    elif tool_name == "mcp__git__git_commit":
        pass  # always a commit, no further filtering needed
    else:
        return

    # Only run in repos that opted in via .guard-waivers.json
    try:
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return
    if not os.path.isfile(os.path.join(root, ".guard-waivers.json")):
        return

    # Get staged diff (added lines only)
    try:
        diff = subprocess.check_output(
            ["git", "diff", "--cached", "--diff-filter=ACMR", "-U0"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return  # no diff or git not available

    if not diff:
        return

    # Parse diff into (file, line_content) pairs — only added lines
    current_file = None
    added_lines = []
    for line in diff.splitlines():
        if line.startswith("diff --git"):
            match = re.search(r" b/(.+)$", line)
            if match:
                current_file = match.group(1)
        elif line.startswith("+") and not line.startswith("+++"):
            content = line[1:]  # strip leading +
            if current_file:
                added_lines.append((current_file, content))

    if not added_lines:
        return

    # Skip .age files
    added_lines = [(f, c) for f, c in added_lines if not f.endswith(".age")]
    if not added_lines:
        return

    waivers, scope_globs = load_config(root)

    # Subtree-public mode: drop changes outside the declared public scopes.
    # No scopes declared -> treat the whole repo as public (legacy behavior).
    if scope_globs:
        added_lines = [(f, c) for f, c in added_lines if _in_public_scope(f, scope_globs)]
        if not added_lines:
            return

    fail_findings = []
    warn_findings = []

    for file_path, content in added_lines:
        # Skip safe lines (templates, variable refs, etc.)
        if any(p.search(content) for p in SAFE_LINE_PATTERNS):
            continue

        # Check FAIL patterns
        for check_id, check in FAIL_CHECKS.items():
            m = check["pattern"].search(content)
            if m and not is_waived(check_id, file_path, m.group(), waivers):
                fail_findings.append(
                    f"  [{check_id}] {check['name']}: {file_path}"
                )

        # Check WARN patterns
        for check_id, check in WARN_CHECKS.items():
            m = check["pattern"].search(content)
            if m and not is_waived(check_id, file_path, m.group(), waivers):
                warn_findings.append(
                    f"  [{check_id}] {check['name']}: {file_path}"
                )

    # Deduplicate
    fail_findings = list(dict.fromkeys(fail_findings))
    warn_findings = list(dict.fromkeys(warn_findings))

    if not fail_findings and not warn_findings:
        return

    # Build response
    if fail_findings:
        # Block commit
        msg_parts = ["BLOCKED: staged changes contain potential secrets"]
        msg_parts.extend(fail_findings)
        if warn_findings:
            msg_parts.append("")
            msg_parts.append("Also found warnings:")
            msg_parts.extend(warn_findings)
        msg_parts.append("")
        msg_parts.append(
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
        # Warn but allow
        msg_parts = ["WARNING: staged changes contain flagged content"]
        msg_parts.extend(warn_findings)
        msg_parts.append("")
        msg_parts.append(
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
