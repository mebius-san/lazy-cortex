#!/usr/bin/env sh
# ~/.local/bin/chk-py — managed by /lazy-python.install (Phase 2b); edit the template, not this copy.
# Finds the nearest <repo>/cli/chk-py above the current directory and runs it through sh,
# so the repo copy never needs the exec bit and the command name stays the same everywhere.
set -eu
_dir=$PWD
while :; do
  if [ -f "$_dir/cli/chk-py" ]; then
    exec sh "$_dir/cli/chk-py" "$@"
  fi
  if [ "$_dir" = "/" ]; then
    break
  fi
  _dir=$(dirname "$_dir")
done
echo "chk-py: no cli/chk-py found between $PWD and /" >&2
exit 1
