#!/usr/bin/env bash
# Shared venv resolver for chk / tst.
#
# Verifies the project venv and activates it; configures it (creates / updates) only
# when it is missing or stale and installing is allowed. The configure logic, the
# freshness test and the target-venv resolution live in `_cfg_venv.sh` (shared with
# `bin/cfg`, the `cfg-py` command) — see its header for what "configured" means.
#
# Probe order:
#   1. $VIRTUAL_ENV carrying the checker tools → used as is (the user's explicit choice;
#      no freshness check, nothing installed).
#   2. The target venv: [tool.lazy-python].venv when set, else <project>/.venv.
#      Fresh (tools present AND its `.lazy-python-cfg` stamp matches the current
#      pyproject requirement digest) → activated. Missing or stale →
#        - protected mode (LAZYCORTEX_PROTECTED set): fail, telling to run `cfg-py`
#          outside protected mode — nothing is installed;
#        - [tool.lazy-python] bootstrap-fallback = false: fail, pointing at `cfg-py`;
#        - otherwise: run cfg-py's logic (create / recreate / update + stamp), then activate.
#
# A venv keeps its executables in bin/ on macOS / Linux and in Scripts/ (with .exe names)
# on Windows; every probe resolves whichever layout the venv carries. Sourced by bash (chk,
# tst) and by zsh (the checker tests), so the syntax stays common to both.
set -euo pipefail

# Shared helpers live beside this file: BASH_SOURCE under bash, $0 under zsh.
source "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/_cfg_venv.sh"

# Activate a venv: prepend its executables dir to PATH and return successfully.
_activate() {
  local venv="$1"
  export PATH="$(_venv_bin_dir "${venv}"):${PATH}"
}

# ---- Probe 1: $VIRTUAL_ENV ----------------------------------------------------
if [ -n "${VIRTUAL_ENV:-}" ] && _venv_has_tools "${VIRTUAL_ENV}"; then
  _activate "${VIRTUAL_ENV}"
  return 0 2>/dev/null || exit 0
fi

# ---- Probe 2: target venv, fresh ---------------------------------------------
_venv_dir="$(_target_venv)"
if _venv_is_fresh "${_venv_dir}"; then
  _activate "${_venv_dir}"
  return 0 2>/dev/null || exit 0
fi

# ---- Missing or stale: protected mode installs nothing -----------------------
if _lazy_py_protected; then
  echo "[lazy-python] the project venv at ${_venv_dir} is missing or stale (not configured against the current pyproject.toml)" >&2
  echo "[lazy-python] LAZYCORTEX_PROTECTED is set, so nothing is installed here" >&2
  echo "[lazy-python] run cfg-py from an interactive session or console, outside protected mode, then retry" >&2
  return 1 2>/dev/null || exit 1
fi

# ---- Missing or stale: automatic configure opted out --------------------------
if [ "$(_read_pyproject_key bootstrap-fallback)" = "false" ]; then
  echo "[lazy-python] the project venv at ${_venv_dir} is missing or stale and bootstrap-fallback = false" >&2
  echo "[lazy-python] options:" >&2
  echo "  - run cfg-py to create / update it from pyproject.toml" >&2
  echo "  - activate a venv with mypy/pylint/pytest/ruff + pytest-clarity/pytest-sugar (sets \$VIRTUAL_ENV)" >&2
  return 1 2>/dev/null || exit 1
fi

# ---- Missing or stale: configure it (cfg-py's logic) -------------------------
_cfg_venv "${_venv_dir}" || { return 1 2>/dev/null || exit 1; }
_activate "${_venv_dir}"
