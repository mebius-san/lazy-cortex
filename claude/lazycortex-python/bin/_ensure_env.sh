#!/usr/bin/env sh
# _ensure_env.sh — optional project-environment bootstrap for chk / tst.
#
# Sources a repo-declared shell script named by `python.env_source` in
# <cwd>/.claude/lazy.settings.json, so any environment that script sets up
# (secret-path exports, provider credentials, etc.) is visible to the pytest /
# checker process that runs next. Projects that need environment bootstrap keep
# it in their own shell wrapper today; without this hook the plugin runners would
# silently run tests in a half-configured environment.
#
# Contract:
#   - key absent / null / empty   → no-op (behaviour byte-identical to no hook)
#   - key set + file exists        → source it in the current shell
#   - key set + file missing       → abort non-zero, naming the key + resolved path
#     (do NOT run tests / checkers in a half-configured environment)
#
# Path resolution: both `.claude/lazy.settings.json` and the `env_source` value
# are resolved relative to the current working directory — the same cwd that
# scopes tests/<module>/ for pytest — NOT the venv resolver's project root.
#
# Sourced (not executed) by chk / tst AFTER _ensure_venv.sh, so `python3`
# resolves to the just-activated venv interpreter and the exports land in the
# shell that execs pytest / the checker.

# Read `python.env_source` from <cwd>/.claude/lazy.settings.json with a stdlib
# one-liner. No dependency on lazycortex-core: chk / tst run standalone from a
# bare terminal where $LAZYCORTEX_PLUGIN_DIRS is unset, so the core settings
# helper is unavailable here — a raw JSON read is the only portable option.
_env_source=""
if command -v python3 >/dev/null 2>&1; then
  _env_source="$(python3 - <<'PY' 2>/dev/null || true
import json, os, sys
path = os.path.join(".claude", "lazy.settings.json")
try:
    with open(path, encoding = "utf-8") as handle:
        data = json.load(handle)
except (OSError, ValueError):
    sys.exit(0)
section = data.get("python")
if isinstance(section, dict):
    value = section.get("env_source")
    if isinstance(value, str) and value.strip():
        sys.stdout.write(value.strip())
PY
)"
fi

# guard: no key on record → behave exactly as before (no env hook)
if [ -n "${_env_source:-}" ]; then
  case "$_env_source" in
    /*) _env_file="$_env_source" ;;
    *)  _env_file="$PWD/$_env_source" ;;
  esac
  if [ -f "$_env_file" ]; then
    # shellcheck disable=SC1090
    . "$_env_file"
  else
    echo "[lazy-python] python.env_source is set to '$_env_source' but the resolved file does not exist:" >&2
    echo "[lazy-python]   $_env_file" >&2
    echo "[lazy-python] fix the path in .claude/lazy.settings.json or remove the key; refusing to run in a half-configured environment" >&2
    return 1 2>/dev/null || exit 1
  fi
fi
