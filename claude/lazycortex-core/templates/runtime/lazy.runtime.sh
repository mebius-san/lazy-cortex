#!/usr/bin/env bash
# Resolve the latest lazycortex-core in the plugin cache and exec its runner.
# Real cache layout is 4 levels:
#   ~/.claude/plugins/cache/<registry>/<plugin>/<version>/bin/<plugin>
# Survives plugin version bumps without re-rendering the supervisor unit.
#
# Usage: lazy.runtime.sh [--dev-mode] <repo-root> [--plugin-dir <path>]...
#
# --dev-mode: scan <repo-root>/claude/*/.claude-plugin/plugin.json and inject
# one --plugin-dir <plugin-root> per match BEFORE existing args. The runner
# consults --plugin-dir paths first and falls back to the cache, so dev-mode
# transparently prefers in-repo plugin sources over their cached copies.
DEV_MODE=0
ARGS=()
REPO=""
for arg in "$@"; do
  if [ "$arg" = "--dev-mode" ]; then
    DEV_MODE=1
    continue
  fi
  ARGS+=("$arg")
  # First non-flag positional is repo-root (runner's contract).
  if [ -z "$REPO" ] && [ "${arg#--}" = "$arg" ]; then
    REPO="$arg"
  fi
done

if [ "$DEV_MODE" = "1" ] && [ -n "$REPO" ] && [ -d "$REPO/claude" ]; then
  DEV_DIRS=()
  for plugin_json in "$REPO"/claude/*/.claude-plugin/plugin.json; do
    [ -f "$plugin_json" ] || continue
    plugin_dir=$(dirname "$(dirname "$plugin_json")")
    DEV_DIRS+=(--plugin-dir "$plugin_dir")
  done
  # Insert --plugin-dir args directly after repo-root so the runner sees them
  # before any operator-supplied flags. ARGS[0] is repo-root by construction.
  if [ ${#DEV_DIRS[@]} -gt 0 ]; then
    ARGS=("${ARGS[0]}" "${DEV_DIRS[@]}" "${ARGS[@]:1}")
  fi
fi

RUNNER=$(ls -d ~/.claude/plugins/cache/*/lazycortex-core/*/bin/runner 2>/dev/null | sort -r | head -1)
[ -z "$RUNNER" ] && { echo "lazycortex-core/bin/runner not found in plugin cache" >&2; exit 1; }
exec "$RUNNER" "${ARGS[@]}"
