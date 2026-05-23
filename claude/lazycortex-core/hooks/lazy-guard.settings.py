#!/usr/bin/env python3
"""
PreToolUse hook: guard Claude Code settings files against dangerous changes.

Fires on every Edit/Write tool call. Fast-exits for non-settings files (~1ms).
For settings files, enforces:
  - No broad wildcards (Bash(*), Edit(*), Write(*)) in allow lists.
  - No destructive commands promoted from deny to allow.
  - No removal of critical deny rules.
  - Warns on per-tool permission additions to tracked settings.json (permissions belong in the
    paired gitignored settings.local.json).
  - Warns on bulk permission additions, broad MCP wildcards, dangerous flags.
  - Reports newly granted permissions so Claude stops re-asking.

Note: under the current policy, ~/.claude/settings.local.json is a valid destination for
globally-scoped per-tool permissions (opt-in via lazy-guard.allow-mcp). The earlier
"must stay empty" rule was removed when settings.local.json became the default target for
permissions.
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


def classify_path(file_path, cwd = ""):
  """
  Classify a file path as a Claude Code settings file and determine its scope.

  Args:
    file_path: Path to the file being touched by the tool call. May be absolute, user-relative
      (`~`), or relative to `cwd`.
    cwd: Working directory used to resolve `file_path` when it is relative.

  Returns:
    Dict describing the path: `is_settings` (True when the file is `settings.json` or
    `settings.local.json` directly under a `.claude` directory), `is_global` (True when the
    file lives under the user's global `~/.claude/`), `is_local` (True when the filename is
    `settings.local.json`), `is_global_local` (True when both global and local), and `resolved`
    (absolute realpath of the file).
  """
  # resolve the path against user-home, cwd, or as-is
  if file_path.startswith("~"):
    resolved = os.path.expanduser(file_path)
  elif not os.path.isabs(file_path):
    resolved = os.path.join(cwd, file_path) if cwd else os.path.abspath(file_path)
  else:
    resolved = file_path

  resolved = os.path.realpath(resolved)
  basename = os.path.basename(resolved)
  parent = os.path.basename(os.path.dirname(resolved))

  is_settings = parent == ".claude" and basename in ( "settings.json", "settings.local.json" )
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
  """
  Report whether a parsed settings JSON object is effectively empty.

  A settings object is considered empty when it has no top-level keys beyond `permissions`
  and `$schema`, and its `permissions` block carries no `allow`, `deny`, or `ask` entries
  and no other permission keys.

  Args:
    parsed: Parsed JSON object loaded from a settings file, or None.

  Returns:
    True when the object carries no meaningful permission or top-level configuration; False
    otherwise.
  """
  # guard: missing or literally `{}` — treat as empty
  if not parsed or parsed == {}:
    return True
  perms = parsed.get("permissions", {})
  # guard: no permissions block at all
  if not perms:
    return parsed == { "permissions": {} }
  allow = perms.get("allow", [])
  deny = perms.get("deny", [])
  ask = perms.get("ask", [])
  other_keys = set(parsed.keys()) - { "permissions", "$schema" }
  # guard: any non-permissions top-level key disqualifies emptiness
  if other_keys:
    return False
  perm_keys = set(perms.keys()) - { "allow", "deny", "ask" }
  # guard: any unrecognised permission key disqualifies emptiness
  if perm_keys:
    return False
  return not allow and not deny and not ask


def try_parse_json(text):
  """
  Parse a text payload as JSON, returning None when parsing fails.

  Args:
    text: Text to parse. Accepts arbitrary input — non-JSON or non-string values yield None
      rather than raising.

  Returns:
    The parsed JSON value when `text` is valid JSON; None when parsing fails for any reason
    (invalid syntax, wrong input type).
  """
  try:
    return json.loads(text)
  except ( json.JSONDecodeError, TypeError ):
    return None


def extract_permission_entries(text):
  """
  Extract Claude Code permission entries (tool names and tool-with-pattern specifiers) from
  a settings payload.

  Two recognised shapes are supported:
    - Full JSON settings documents — entries are pulled from the `allow`, `deny`, and `ask`
      arrays under the `permissions` block.
    - Partial Edit fragments — entries that look like permission specifiers are pulled
      heuristically: PascalCase tool names (`Read`, `TaskCreate`), tool-with-pattern
      specifiers (`Bash(git *)`, `Edit(~/.openclaw/**)`), and MCP tool ids
      (`mcp__context7__query-docs`).

  Lowercase structural keys (`permissions`, `allow`, `hooks`, etc.) are never matched in the
  heuristic shape.

  Args:
    text: Settings payload — either a full JSON document or an Edit fragment.

  Returns:
    Set of permission entry strings discovered in the payload.
  """
  parsed = try_parse_json(text)
  if parsed and isinstance(parsed, dict):
    perms = parsed.get("permissions", {})
    entries = set()
    for key in ( "allow", "deny", "ask" ):
      for entry in perms.get(key, []):
        if isinstance(entry, str):
          entries.add(entry)
    return entries
  # Partial text (Edit fragments): match uppercase-starting tool names and mcp__ prefixes
  return set(re.findall(r'"([A-Z][A-Za-z]+(?:\([^"]*\))?|mcp__[^"]+)"', text))


def output_block(reason):
  """
  Emit a `deny` PreToolUse hook decision to stdout and exit the hook process.

  The function writes a Claude Code hook protocol response that vetoes the in-flight tool
  call, then terminates the hook with exit code 0 so the trigger sees a clean veto rather
  than a crashed hook.

  Args:
    reason: Human-readable explanation of why the tool call is being blocked. Surfaced to the
      user as the `permissionDecisionReason`.

  Raises:
    SystemExit: Always — the hook terminates with exit code 0 after emitting the decision.
  """
  json.dump({
    "hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "permissionDecision": "deny",
      "permissionDecisionReason": reason,
    }
  }, sys.stdout)
  sys.exit(0)


def output_allow_with_message(message):
  """
  Emit a non-blocking system message alongside an implicit allow, then exit the hook process.

  The function writes a Claude Code hook protocol response that injects a `systemMessage`
  visible to Claude without vetoing the in-flight tool call, then terminates the hook with
  exit code 0.

  Args:
    message: Human-readable text to surface as the `systemMessage` payload.

  Raises:
    SystemExit: Always — the hook terminates with exit code 0 after emitting the message.
  """
  json.dump({ "systemMessage": message }, sys.stdout)
  sys.exit(0)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def check_tracked_permissions_leak(classification, old_text, new_text):
  """
  Report when per-tool permissions are being added to a tracked `settings.json`.

  Per-tool permissions are personal posture and belong in the paired gitignored
  `settings.local.json`. Adding them to tracked `settings.json` leaks them to anyone who
  shares the repo or dotfiles. The result is advisory only — the user may intentionally want
  a tracked permission, so this never blocks the call.

  Args:
    classification: Path-classification dict returned by `classify_path`.
    old_text: Previous settings text (Edit `old_string` or None for Write).
    new_text: New settings text (Edit `new_string` or Write `content`).

  Returns:
    Warning message string describing the leak, or None when no new permissions are being
    added or when the target is already a `settings.local.json` (which is the correct
    destination for personal permissions).
  """
  # guard: writes to settings.local.json or non-settings files are not leaks
  if classification["is_local"] or not classification["is_settings"]:
    return None
  old_perms = extract_permission_entries(old_text) if old_text else set()
  new_perms = extract_permission_entries(new_text)
  added = new_perms - old_perms
  # guard: nothing new added — no leak to report
  if not added:
    return None
  return (
    f"Per-tool permissions are being added to tracked settings.json "
    f"({len(added)} new entr{'y' if len(added) == 1 else 'ies'}). "
    f"Consider moving to the paired settings.local.json (gitignored) "
    f"so they don't ship to teammates."
  )


def check_blocked_allow_patterns(new_text):
  """
  Detect blocked patterns inside a settings payload's allow list.

  For full JSON documents the check is scoped to the `permissions.allow` array. For partial
  Edit fragments the check scans the entire fragment because the fragment is typically being
  inserted into an allow-array context where blocking patterns would land in the allow list.

  Args:
    new_text: New settings text being written — either a full JSON document or an Edit
      fragment.

  Returns:
    The reason string from the first matching `BLOCKED_ALLOW_PATTERNS` entry, or None when
    no blocked pattern is detected.
  """
  parsed = try_parse_json(new_text)
  if parsed and isinstance(parsed, dict):
    # Full JSON: only check the allow array
    allow_entries = parsed.get("permissions", {}).get("allow", [])
    check_text = " ".join(f'"{e}"' for e in allow_entries)
  else:
    # Edit fragment: check the whole text
    check_text = new_text

  # guard: no text to inspect — nothing to block
  if not check_text:
    return None

  for pattern, reason in BLOCKED_ALLOW_PATTERNS:
    if re.search(pattern, check_text):
      return reason
  return None


def check_critical_deny_removal(old_text, new_text):
  """
  Detect removal of a critical deny rule between the previous and new settings text.

  Args:
    old_text: Previous settings text (Edit `old_string`). When falsy the check is skipped —
      there is no prior state to compare against (e.g. fresh Write).
    new_text: New settings text being written.

  Returns:
    Human-readable explanation naming the removed deny rule, or None when no critical deny
    rule is being removed.
  """
  # guard: no previous text — cannot detect removal
  if not old_text:
    return None

  for rule in CRITICAL_DENY_RULES:
    if rule in old_text and rule not in new_text:
      return f"Removing critical deny rule '{rule}' weakens safety. This rule prevents destructive operations."
  return None


def collect_warnings(old_text, new_text):
  """
  Collect non-blocking advisory warnings for a settings change.

  Warnings cover bulk permission additions (more than `BULK_THRESHOLD` new entries at once),
  newly introduced broad MCP tool wildcards, and newly introduced dangerous flags
  (`dangerouslyDisableSandbox`, `bypassPermissions`).

  Args:
    old_text: Previous settings text (Edit `old_string` or None for Write).
    new_text: New settings text being written.

  Returns:
    List of human-readable warning strings — empty when no advisory conditions trigger.
  """
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
  """
  Build an informational message listing newly granted permissions.

  When the settings change adds a small number of new permission entries (more than zero,
  at most twenty), the message tells Claude that those permissions are now granted so it
  stops re-asking for approval. Larger sets are suppressed — they signal a bulk edit that
  the operator should review manually rather than have the agent quietly absorb.

  Args:
    old_text: Previous settings text (Edit `old_string` or None for Write).
    new_text: New settings text being written.

  Returns:
    Multi-line message listing the newly granted permissions, or None when nothing was
    added or the added set exceeds twenty entries.
  """
  new_perms = extract_permission_entries(new_text)
  old_perms = extract_permission_entries(old_text) if old_text else set()
  added = new_perms - old_perms

  # guard: no additions or too many to inline — suppress the auto-context
  if not added or len(added) > 20:
    return None

  lines = [ "Settings updated. New permissions granted:" ]
  for p in sorted(added):
    lines.append(f"  - {p}")
  lines.append("You no longer need to ask for approval to use these.")
  return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
  """
  Run the PreToolUse settings-guard hook against the in-flight Edit or Write tool call.

  Reads the Claude Code hook payload from stdin, fast-exits for non-settings files, then
  applies the block checks (critical-deny removal, blocked allow patterns) and the advisory
  checks (leak warning, bulk additions, MCP wildcards, dangerous flags, newly-granted
  permissions context). Emits at most one hook response — a `deny` decision, a non-blocking
  system message, or a silent allow.

  Raises:
    SystemExit: Always — the hook process terminates with exit code 0 on every code path,
      either silently or after emitting a hook protocol response.
  """
  raw = sys.stdin.read()
  payload = json.loads(raw)

  tool_input = payload.get("tool_input", {})
  file_path = tool_input.get("file_path", "")
  tool_name = payload.get("tool_name", "")
  cwd = payload.get("cwd", "")

  # Fast path: not a settings file
  classification = classify_path(file_path, cwd)
  # guard: not a settings file — let the call through silently
  if not classification["is_settings"]:
    sys.exit(0)

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

  # guard: nothing being written — no further analysis needed
  if not new_text:
    sys.exit(0)

  # Block checks
  blocked = check_blocked_allow_patterns(new_text)
  if blocked:
    output_block(blocked)

  # Warning + auto-context
  messages = []

  warnings = collect_warnings(old_text, new_text)
  leak = check_tracked_permissions_leak(classification, old_text, new_text)
  if leak:
    warnings.append(leak)
  if warnings:
    messages.append("Settings guardian warnings:\n" + "\n".join(f"  - {w}" for w in warnings))

  context = generate_auto_context(old_text, new_text)
  if context:
    messages.append(context)

  if messages:
    output_allow_with_message("\n\n".join(messages))

  sys.exit(0)


if __name__ == "__main__":
  # noinspection PyBroadException
  try:
    main()
  except Exception:
    pass
  sys.exit(0)
