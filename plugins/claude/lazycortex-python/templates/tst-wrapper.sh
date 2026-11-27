#!/usr/bin/env bash
# Self-resolving wrapper for the lazycortex-python `tst` aggregator.
# Managed by /lazy-python.install (Phase 2) — edit the template, not this copy.
#
# Path-agnostic by design: resolves the active lazycortex-python install at exec
# time rather than baking in an absolute, version-pinned path.
# - Survives plugin version bumps without re-running install (cache dir is
#   versioned; a frozen path goes stale on every /plugin update and is then swept).
# - No /Users/... leakage into a tracked cli/ wrapper — path hygiene holds.
set -eu

_bin="bin/tst"

# Launch a file through the interpreter its own first line names — the exec bit is
# not part of the contract (a mode-blind git client strips it; Windows never has it).
_run() {
  _file=$1
  shift
  _interp=$(sed -n '1s/^#![[:space:]]*//p' "$_file")
  if [ -z "$_interp" ]; then
    echo "tst-py: $_file has no shebang" >&2
    exit 1
  fi
  # shellcheck disable=SC2086 — the shebang line is intentionally word-split
  exec $_interp "$_file" "$@"
}

# Locate the plugin through the shared locator deployed beside this wrapper: the exported plugin
# directories, then this checkout's own plugins/claude/ tree (a worktree's own tree inside a worktree),
# last the install the registry records for this repository or for the whole user — never another
# project's install. A miss prints the locator's error naming every place searched, and the wrapper stops.
_here=$(cd "$(dirname "$0")" && pwd)
_locator="$_here/lazy_python_locator.py"
if [ ! -f "$_locator" ]; then
  echo "tst-py: $_locator is missing; re-run /lazy-python.install." >&2
  exit 1
fi
if ! _root=$("${LAZYCORTEX_PYTHON:-python3}" "$_locator" root lazycortex-python --start "$_here"); then
  echo "tst-py: cannot locate the lazycortex-python plugin; install/enable it, or re-run /lazy-python.install." >&2
  exit 1
fi
if [ ! -f "$_root/$_bin" ]; then
  echo "tst-py: cannot locate the lazycortex-python plugin: $_root carries no $_bin; re-run /lazy-python.install." >&2
  exit 1
fi
_run "$_root/$_bin" "$@"
