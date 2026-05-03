#!/bin/bash
# Resolve the latest lazycortex-core in the plugin cache and exec its runner.
# Real cache layout is 4 levels:
#   ~/.claude/plugins/cache/<registry>/<plugin>/<version>/bin/<plugin>
# Survives plugin version bumps without re-rendering the supervisor unit.
RUNNER=$(ls -d ~/.claude/plugins/cache/*/lazycortex-core/*/bin/runner 2>/dev/null | sort -r | head -1)
[ -z "$RUNNER" ] && { echo "lazycortex-core/bin/runner not found in plugin cache" >&2; exit 1; }
exec "$RUNNER" "$@"
