#!/usr/bin/env sh
# PostToolUse hook for lazy-python.
#
# Auto-registered by the plugin manifest (hooks/hooks.json) under matcher Edit|Write —
# the Claude Code engine wires it up when the plugin is enabled; no consumer settings.json
# write is involved.
#
# Fires on:
# - Edit / Write tool calls — narrowed in-script to .py files.
#
# Behavior:
# - When all filters pass (Edit/Write + .py + py_compile clean), runs
#   ${CLAUDE_PLUGIN_ROOT}/bin/pcf.py on the edited file and emits any violations as a
#   PostToolUse additionalContext JSON payload to stdout. Stdlib-only — no venv needed.
# - File exclusion (`.venv`, `__pycache__`, project `[tool.pcf] exclude` paths) is delegated
#   to pcf.py: the hook passes the edited file through and pcf.py's own exclude logic decides
#   whether to analyze it. No source-root filter, no install-time substitution.
# - Every other path is a deterministic no-op exit 0.
#
# Contract (lazy-core.hook-writing § 1–3, 8):
#   § 1 script discipline · § 2 trigger gating · § 3 branch determinism · § 8 logging
# Sections 4–7 (no-dirty-tree, no-foreign-staged, auto-commit loop guard,
# transactional skip) are vacuous here: this hook never writes to the working tree
# and never touches the git index.

set -eu

# § 1 — defensive stdin handling; bail on empty payload.
PAYLOAD="$(cat)"
if [ -z "$PAYLOAD" ]; then
    exit 0
fi

# jq is optional — bail safely if absent (POSIX command -v probe).
command -v jq >/dev/null 2>&1 || exit 0

# § 2 — TRIGGER GATING — narrow Edit/Write matcher to .py files.
TOOL_NAME="$(printf '%s' "$PAYLOAD" | jq -r '.tool_name // ""')"
case "$TOOL_NAME" in
    Edit|Write) ;;
    *) exit 0 ;;
esac

FILE_PATH="$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.file_path // .tool_input.path // ""')"
[ -z "$FILE_PATH" ] && exit 0
case "$FILE_PATH" in
    *.py) ;;
    *) exit 0 ;;
esac

# Resolve project dir + file to real (symlink-resolved) absolute paths, then derive the
# repo-relative path used for reporting. pcf.py owns the exclude decision (see § comment above).
REAL_PROJECT_DIR="$(cd "$CLAUDE_PROJECT_DIR" 2>/dev/null && pwd -P)" || exit 0
REAL_FILE_PATH="$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$FILE_PATH")" || exit 0
case "$REAL_FILE_PATH" in
    "$REAL_PROJECT_DIR"/*) REL_PATH="${REAL_FILE_PATH#"$REAL_PROJECT_DIR"/}" ;;
    *) REL_PATH="$REAL_FILE_PATH" ;;
esac

# Skip if the file doesn't currently parse — an in-progress edit shouldn't surface
# spurious style violations from a syntactically incomplete buffer.
python3 -m py_compile "$REAL_FILE_PATH" 2>/dev/null || exit 0

# Run pcf.py and capture its notes. pcf emits one "<file>:<line>: note: <msg>" per
# violation; absence of `: note:` lines means clean (or excluded) file.
PCF_OUT="$(python3 "$CLAUDE_PLUGIN_ROOT/bin/pcf.py" "$REAL_FILE_PATH" 2>&1 || true)"
VIOLATIONS="$(printf '%s\n' "$PCF_OUT" | grep ': note:' || true)"
if [ -n "$VIOLATIONS" ]; then
    # § 3 — context-only branch: emit PostToolUse additionalContext JSON, nothing else.
    jq -n --arg issues "$VIOLATIONS" --arg file "$REL_PATH" '{
      "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": ("Style violations in " + $file + ":\n\n" + $issues)
      }
    }'
fi

exit 0
