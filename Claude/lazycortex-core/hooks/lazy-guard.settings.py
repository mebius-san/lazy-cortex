#!/usr/bin/env python3
"""PreToolUse hook: guard Claude Code settings files against dangerous changes.

Fires on every Edit/Write tool call. Fast-exits for non-settings files (~1ms).
For settings files, enforces:
  - Global ~/.claude/settings.local.json must stay empty
  - No broad wildcards (Bash(*), Edit(*), Write(*)) in allow lists
  - No destructive commands promoted from deny to allow
  - No removal of critical deny rules
  - Warns on bulk permission additions, broad MCP wildcards, dangerous flags
  - Reports newly granted permissions so Claude stops re-asking
"""

import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GLOBAL_CLAUDE = os.path.realpath(os.path.expanduser("~/.claude"))

# Permissions that must never appear in an allow list
BLOCKED_ALLOW_PATTERNS = [
    (r'"Bash\(\*\)"', "Bash(*) matches ALL bash commands — far too broad"),
    (r'"Edit\(\*\)"', "Edit(*) matches ALL file edits — far too broad"),
    (r'"Write\(\*\)"', "Write(*) matches ALL file writes — far too broad"),
    (r'"Bash\(rm\s+-rf\b', "rm -rf in allow list defeats the deny rule"),
    (r'"Bash\(rm\s+-fr\b', "rm -fr in allow list defeats the deny rule"),
    (r'"Bash\(git\s+push\s+--force', "git push --force in allow list defeats the deny rule"),
    (r'"Bash\(git\s+reset\s+--hard', "git reset --hard in allow list defeats the deny rule"),
    (r'"Bash\(sudo\b', "sudo in allow list defeats the deny rule"),
]

# Deny rules that must not be removed (substrings to match)
CRITICAL_DENY_RULES = [
    "Bash(rm -rf *)",
    "Bash(rm -fr *)",
    "Bash(sudo *)",
    "Bash(su *)",
    "Bash(git push --force*)",
    "Bash(git push *--force*)",
    "Bash(git reset --hard*)",
    "Bash(curl *|bash*)",
    "Bash(wget *|bash*)",
]

# Flags that are dangerous if introduced
DANGEROUS_FLAGS = [
    ("dangerouslyDisableSandbox", "Disabling sandbox removes file system protections"),
    ("bypassPermissions", "Bypassing permissions removes all safety checks"),
]

BULK_THRESHOLD = 5  # warn if this many permissions added at once

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def classify_path(file_path, cwd=""):
    """Determine if a file path is a settings file and whether it's global."""
    if file_path.startswith("~"):
        resolved = os.path.expanduser(file_path)
    elif not os.path.isabs(file_path):
        resolved = os.path.join(cwd, file_path) if cwd else os.path.abspath(file_path)
    else:
        resolved = file_path

    resolved = os.path.realpath(resolved)
    basename = os.path.basename(resolved)
    parent = os.path.basename(os.path.dirname(resolved))

    is_settings = parent == ".claude" and basename in ("settings.json", "settings.local.json")
    is_local = basename == "settings.local.json"
    is_global = resolved.startswith(GLOBAL_CLAUDE + os.sep) or os.path.dirname(resolved) == GLOBAL_CLAUDE
    is_global_local = is_global and is_local

    return {
        "is_settings": is_settings,
        "is_global": is_global,
        "is_local": is_local,
        "is_global_local": is_global_local,
        "resolved": resolved,
    }


def is_empty_settings(parsed):
    """Check if parsed JSON is effectively empty settings."""
    if not parsed or parsed == {}:
        return True
    perms = parsed.get("permissions", {})
    if not perms:
        return parsed == {"permissions": {}}
    allow = perms.get("allow", [])
    deny = perms.get("deny", [])
    ask = perms.get("ask", [])
    other_keys = set(parsed.keys()) - {"permissions", "$schema"}
    if other_keys:
        return False
    perm_keys = set(perms.keys()) - {"allow", "deny", "ask"}
    if perm_keys:
        return False
    return not allow and not deny and not ask


def try_parse_json(text):
    """Try to parse text as JSON, return None on failure."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def extract_permission_entries(text):
    """Extract permission entries from settings text.

    For full JSON (Write), parse and pull from allow/deny/ask arrays.
    For partial text (Edit), match patterns that look like tool permissions:
      - PascalCase names: Read, TaskCreate, Glob
      - Tool(pattern): Bash(git *), Edit(~/.openclaw/**)
      - MCP tools: mcp__context7__query-docs
    Excludes JSON structural keys (lowercase: permissions, allow, hooks, etc.)
    """
    parsed = try_parse_json(text)
    if parsed and isinstance(parsed, dict):
        perms = parsed.get("permissions", {})
        entries = set()
        for key in ("allow", "deny", "ask"):
            for entry in perms.get(key, []):
                if isinstance(entry, str):
                    entries.add(entry)
        return entries
    # Partial text (Edit fragments): match uppercase-starting tool names and mcp__ prefixes
    return set(re.findall(r'"([A-Z][A-Za-z]+(?:\([^"]*\))?|mcp__[^"]+)"', text))


def output_block(reason):
    """Block the tool call — write to stderr, exit 2."""
    msg = json.dumps({
        "hookSpecificOutput": {"permissionDecision": "deny"},
        "systemMessage": reason,
    })
    sys.stderr.write(msg)
    sys.exit(2)


def output_allow_with_message(message):
    """Allow but inject a system message."""
    json.dump({"systemMessage": message}, sys.stdout)
    sys.exit(0)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def check_global_local_guard(classification, tool_name, payload):
    """Block any non-empty write to global settings.local.json."""
    if not classification["is_global_local"]:
        return

    tool_input = payload.get("tool_input", {})

    if tool_name == "Write":
        content = tool_input.get("content", "")
        parsed = try_parse_json(content)
        if parsed is not None and not is_empty_settings(parsed):
            output_block(
                "Global ~/.claude/settings.local.json must stay empty. "
                "Add permissions to project-level .claude/settings.local.json "
                "or (if truly global) to ~/.claude/settings.json instead."
            )
    elif tool_name == "Edit":
        new_string = tool_input.get("new_string", "")
        old_string = tool_input.get("old_string", "")
        if new_string.strip() and new_string.strip() != old_string.strip():
            output_block(
                "Global ~/.claude/settings.local.json must stay empty. "
                "Add permissions to project-level .claude/settings.local.json "
                "or (if truly global) to ~/.claude/settings.json instead."
            )


def check_blocked_allow_patterns(new_text):
    """Check for dangerous patterns in allow lists. Returns first match or None.

    For full JSON (Write), scopes the check to the allow array only.
    For partial text (Edit fragments), checks the entire text since the
    fragment is typically being inserted into an allow array context.
    """
    parsed = try_parse_json(new_text)
    if parsed and isinstance(parsed, dict):
        # Full JSON: only check the allow array
        allow_entries = parsed.get("permissions", {}).get("allow", [])
        check_text = " ".join(f'"{e}"' for e in allow_entries)
    else:
        # Edit fragment: check the whole text
        check_text = new_text

    if not check_text:
        return None

    for pattern, reason in BLOCKED_ALLOW_PATTERNS:
        if re.search(pattern, check_text):
            return reason
    return None


def check_critical_deny_removal(old_text, new_text):
    """Check if a critical deny rule is being removed."""
    if not old_text:
        return None

    for rule in CRITICAL_DENY_RULES:
        if rule in old_text and rule not in new_text:
            return f"Removing critical deny rule '{rule}' weakens safety. This rule prevents destructive operations."
    return None


def collect_warnings(old_text, new_text):
    """Collect non-blocking warnings."""
    warnings = []

    # Bulk permission additions
    new_perms = extract_permission_entries(new_text)
    old_perms = extract_permission_entries(old_text) if old_text else set()
    added = new_perms - old_perms
    if len(added) >= BULK_THRESHOLD:
        warnings.append(f"Adding {len(added)} permissions at once — review each for appropriate scope.")

    # Broad MCP wildcards
    if re.search(r'"mcp__[^"]*\*"', new_text):
        if not old_text or not re.search(r'"mcp__[^"]*\*"', old_text):
            warnings.append("Broad MCP tool wildcard detected. Consider scoping to specific tools.")

    # Dangerous flags
    for flag, msg in DANGEROUS_FLAGS:
        if flag in new_text and (old_text is None or flag not in old_text):
            warnings.append(f"'{flag}' detected: {msg}")

    return warnings


def generate_auto_context(old_text, new_text):
    """Generate info about newly granted permissions."""
    new_perms = extract_permission_entries(new_text)
    old_perms = extract_permission_entries(old_text) if old_text else set()
    added = new_perms - old_perms

    if not added or len(added) > 20:
        return None

    lines = ["Settings updated. New permissions granted:"]
    for p in sorted(added):
        lines.append(f"  - {p}")
    lines.append("You no longer need to ask for approval to use these.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    raw = sys.stdin.read()
    payload = json.loads(raw)

    tool_input = payload.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    tool_name = payload.get("tool_name", "")
    cwd = payload.get("cwd", "")

    # Fast path: not a settings file
    classification = classify_path(file_path, cwd)
    if not classification["is_settings"]:
        sys.exit(0)

    # Guard: global settings.local.json must stay empty
    check_global_local_guard(classification, tool_name, payload)

    # Extract content for analysis
    if tool_name == "Write":
        old_text = None
        new_text = tool_input.get("content", "")
    elif tool_name == "Edit":
        old_text = tool_input.get("old_string", "")
        new_text = tool_input.get("new_string", "")
    else:
        sys.exit(0)

    # Check deny removal first — deletions have empty new_text but non-empty old_text
    deny_removal = check_critical_deny_removal(old_text, new_text)
    if deny_removal:
        output_block(deny_removal)

    if not new_text:
        sys.exit(0)

    # Block checks
    blocked = check_blocked_allow_patterns(new_text)
    if blocked:
        output_block(blocked)

    # Warning + auto-context
    messages = []

    warnings = collect_warnings(old_text, new_text)
    if warnings:
        messages.append("Settings guardian warnings:\n" + "\n".join(f"  - {w}" for w in warnings))

    context = generate_auto_context(old_text, new_text)
    if context:
        messages.append(context)

    if messages:
        output_allow_with_message("\n\n".join(messages))

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
