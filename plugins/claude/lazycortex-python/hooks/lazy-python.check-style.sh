#!/usr/bin/env bash
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
# - A thin shim: the payload goes on stdin to ${CLAUDE_PLUGIN_ROOT}/bin/check_style_hook.py,
#   run under the plugin interpreter, so the hook needs no JSON tool (`jq` is absent from
#   Git Bash on Windows). Stdlib-only — no venv needed.
# - When all filters pass (Edit/Write + .py + the file compiles), runs
#   ${CLAUDE_PLUGIN_ROOT}/bin/pcf.py on the edited file and emits any violations as a
#   PostToolUse additionalContext JSON payload to stdout.
# - File exclusion (`.venv`, `__pycache__`, project `[tool.pcf] exclude` paths) is delegated
#   to pcf.py: the hook passes the edited file through with `--honor-excludes`, and pcf.py's
#   own exclude logic decides whether to analyze it. Without that flag pcf.py checks any file
#   it is explicitly given; the flag is what keeps an edit under an excluded path a no-op here.
#   No source-root filter, no install-time substitution.
# - Every other path is a deterministic no-op exit 0.
#
# Contract (lazy-core.hook-writing § 1–3, 8):
#   § 1 script discipline · § 2 trigger gating · § 3 branch determinism · § 8 logging
# Sections 4–7 (no-dirty-tree, no-foreign-staged, auto-commit loop guard,
# transactional skip) are vacuous here: this hook never writes to the working tree
# and never touches the git index.

exec "${LAZYCORTEX_PYTHON:-python3}" "$CLAUDE_PLUGIN_ROOT/bin/check_style_hook.py"
