#!/usr/bin/env sh
# Self-resolving wrapper for the lazycortex-python `chk` aggregator.
# Managed by /lazy-python.install (Phase 2) — edit the template, not this copy.
#
# Path-agnostic by design: resolves the active lazycortex-python install at exec
# time rather than baking in an absolute, version-pinned path.
# - Survives plugin version bumps without re-running install (cache dir is
#   versioned; a frozen path goes stale on every /plugin update and is then swept).
# - No /Users/... leakage into a tracked cli/ wrapper — path hygiene holds.
set -eu

_bin="bin/chk"

# 1. Dev vault: this wrapper lives at <repo>/cli/chk-py; prefer the live source tree.
_here=$(cd "$(dirname "$0")" && pwd)
_dev="$_here/../claude/lazycortex-python/$_bin"
if [ -x "$_dev" ]; then
  exec "$_dev" "$@"
fi

# 2. Daemon context: a supervisor may export $LAZYCORTEX_PLUGIN_DIRS for its subprocesses.
if [ -n "${LAZYCORTEX_PLUGIN_DIRS:-}" ]; then
  _old_ifs=$IFS
  IFS=:
  for _d in $LAZYCORTEX_PLUGIN_DIRS; do
    if [ -x "$_d/$_bin" ]; then
      IFS=$_old_ifs
      exec "$_d/$_bin" "$@"
    fi
  done
  IFS=$_old_ifs
fi

# 3. Consumer install: read Claude Code's plugin manifest for the active install path.
_resolved=$(python3 - "$_bin" <<'PY'
import json, os, sys

bin_rel = sys.argv[1]
cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
manifest = os.path.join(cfg, "plugins", "installed_plugins.json")
try:
  with open(manifest, encoding = "utf-8") as fh:
    data = json.load(fh)
except (OSError, ValueError):
  sys.exit(0)


def version_key(version):
  parts = []
  for piece in version.split("."):
    parts.append(int(piece) if piece.isdigit() else 0)
  return parts


candidates = []
for key, entries in (data.get("plugins") or {}).items():
  if key.split("@", 1)[0] != "lazycortex-python":
    continue
  for entry in entries or []:
    install_path = entry.get("installPath")
    if not install_path:
      continue
    bin_path = os.path.join(install_path, bin_rel)
    if os.access(bin_path, os.X_OK):
      project_scope = entry.get("scope") == "project"
      candidates.append((project_scope, version_key(entry.get("version") or ""), bin_path))

if not candidates:
  sys.exit(0)
# Prefer project scope over user scope, then the highest version.
candidates.sort(key = lambda c: (c[0], c[1]))
print(candidates[-1][2])
PY
)
if [ -n "$_resolved" ] && [ -x "$_resolved" ]; then
  exec "$_resolved" "$@"
fi

echo "chk-py: cannot locate the lazycortex-python plugin." >&2
echo "  Install/enable it, or re-run /lazy-python.install if the layout drifted." >&2
exit 1
