#!/usr/bin/env bash
# HOOK_VERSION: 1.0.0
# HOOK_PROTOCOL: obsidian.iconize-sync
# This file is managed by `lazy-obsidian.iconize-install`.
# Re-run that command if the plugin layout changes (rare).
#
# Path-agnostic by design: resolves the currently-installed lazycortex-obsidian
# plugin at exec time rather than baking in an absolute, version-pinned path.
# - No ${CLAUDE_PLUGIN_ROOT} (git hooks don't get it; only Claude Code-run hooks do).
# - No /Users/... leakage into tracked .githooks/ — path hygiene holds for every contributor.
# - Survives plugin version bumps without re-running install.
set -eu
# Highest installed plugin version wins (sort -V is version-aware on macOS + Linux).
bin="$(ls -d ~/.claude/plugins/cache/*/lazycortex-obsidian/*/bin 2>/dev/null | sort -V | tail -1)"
if [ -z "$bin" ] || [ ! -f "$bin/iconize_sync.py" ]; then
  # Plugin uninstalled or cache pruned — a git commit must never fail because
  # an optional hook is unavailable. Exit silently.
  exit 0
fi
exec python3 "$bin/iconize_sync.py" sync-staged
