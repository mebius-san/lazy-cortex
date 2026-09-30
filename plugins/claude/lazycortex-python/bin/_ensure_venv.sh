#!/usr/bin/env bash
# Shared venv resolver for chk / tst.
#
# Probe-then-fallback design — reuses existing venv if found, falls back to
# creating / augmenting a repo-root <project>/.venv only when nothing else is
# available.
#
# Works standalone — no env vars needed for probes 1-3, so chk-py / tst-py run
# from a bare terminal. Probe 4 creates / augments <project>/.venv in the repo
# root, never wipes it: a missing venv is created with `uv venv`, and the checker
# tools (mypy/pylint/pytest/ruff plus the pytest-clarity / pytest-sugar plugins)
# are added in place with `uv pip install` (idempotent — uv adds only
# missing/outdated packages, never removes project deps). Self-promoting:
# once probe 4 creates <project>/.venv, subsequent runs hit probe 2 and skip
# probe 4 entirely; a pre-existing project .venv lacking the tools gets them
# added to the same dir (probe 2 fails _venv_has_tools → probe 4 augments it).
#
# Probe order:
#   1. $VIRTUAL_ENV (activated venv)
#   2. <project>/.venv/
#   3. [tool.lazy-python].venv in pyproject.toml
#   4. fallback: create / augment <project>/.venv
#
# Opt out of (4) via [tool.lazy-python] bootstrap-fallback = false.
#
# A venv keeps its executables in bin/ on macOS / Linux and in Scripts/ (with .exe names)
# on Windows; every probe resolves whichever layout the venv carries. Sourced by bash (chk,
# tst) and by zsh (the checker tests), so the syntax stays common to both.
set -euo pipefail

# Resolve the project root: CLAUDE_PROJECT_DIR when set (Claude Code points it at
# the repo root), else the git top-level, else PWD as a last resort. Keying the
# fallback on the git root (not bare PWD) stops a stray `.venv` from being created
# in a subdirectory when chk/tst is run from somewhere below the repo root.
_project_dir="${CLAUDE_PROJECT_DIR:-}"
if [ -z "${_project_dir}" ]; then
  _project_dir="$(git rev-parse --show-toplevel 2>/dev/null || printf '%s' "${PWD}")"
fi

# Print a venv's executables directory: bin/ (macOS / Linux) or Scripts/ (Windows).
_venv_bin_dir() {
  if [ -d "$1/bin" ]; then
    printf '%s' "$1/bin"
  else
    printf '%s' "$1/Scripts"
  fi
}

# Print the path of executable <name> in a venv's executables dir, with or without the
# Windows .exe suffix; fail when neither exists.
_venv_exe() {
  local dir
  dir="$(_venv_bin_dir "$1")"
  if [ -x "${dir}/$2" ]; then
    printf '%s' "${dir}/$2"
  elif [ -x "${dir}/$2.exe" ]; then
    printf '%s' "${dir}/$2.exe"
  else
    return 1
  fi
}

# Check whether a candidate venv is complete: the four required bins (mypy, pylint,
# pytest, ruff) AND the two pytest plugins (pytest-clarity, pytest-sugar) importable.
_venv_has_tools() {
  local venv="$1"
  local tool python
  for tool in mypy pylint pytest ruff; do
    _venv_exe "${venv}" "${tool}" >/dev/null || return 1
  done
  # guard: pytest plugins ship no bin — verify they import in the venv's interpreter
  python="$(_venv_exe "${venv}" python)" || return 1
  "${python}" -c "import pytest_clarity, pytest_sugar" >/dev/null 2>&1 || return 1
  return 0
}

# Read a `[tool.lazy-python].<key>` value from <project>/pyproject.toml.
# Prints the raw value (quotes stripped) or nothing if absent / file missing.
_read_pyproject_key() {
  local key="$1"
  local pyproject="${_project_dir}/pyproject.toml"
  [ -f "${pyproject}" ] || return 0
  # Extract the [tool.lazy-python] block, find the key line, strip "key = " prefix and outer quotes.
  sed -n '/^\[tool\.lazy-python\]/,/^\[/p' "${pyproject}" 2>/dev/null \
    | grep -E "^[[:space:]]*${key}[[:space:]]*=" \
    | head -1 \
    | sed -E 's/^[[:space:]]*[a-zA-Z_-]+[[:space:]]*=[[:space:]]*//; s/^"//; s/"[[:space:]]*$//' \
    || true
}

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

# ---- Probe 2: <project>/.venv ------------------------------------------------
if _venv_has_tools "${_project_dir}/.venv"; then
  _activate "${_project_dir}/.venv"
  return 0 2>/dev/null || exit 0
fi

# ---- Probe 3: [tool.lazy-python].venv ----------------------------------------
_configured_venv=$(_read_pyproject_key venv)
if [ -n "${_configured_venv}" ]; then
  # Expand ~ and resolve relative paths against the project dir.
  _configured_venv="${_configured_venv/#\~/$HOME}"
  case "${_configured_venv}" in
    /*) ;;
    *) _configured_venv="${_project_dir}/${_configured_venv}" ;;
  esac
  if _venv_has_tools "${_configured_venv}"; then
    _activate "${_configured_venv}"
    return 0 2>/dev/null || exit 0
  fi
fi

# ---- Probe 4: fallback uv-bootstrap ------------------------------------------
_fallback_flag=$(_read_pyproject_key bootstrap-fallback)
if [ "${_fallback_flag}" = "false" ]; then
  echo "[lazy-python] no venv found and bootstrap-fallback = false" >&2
  echo "[lazy-python] options:" >&2
  echo "  - activate a venv with mypy/pylint/pytest/ruff + pytest-clarity/pytest-sugar (sets \$VIRTUAL_ENV)" >&2
  echo "  - create <project>/.venv with those tools" >&2
  echo "  - set [tool.lazy-python] venv = \"<path>\" in pyproject.toml" >&2
  echo "  - flip [tool.lazy-python] bootstrap-fallback = true to allow plugin-local venv" >&2
  return 1 2>/dev/null || exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "[lazy-python] uv not on PATH but bootstrap fallback required" >&2
  echo "  install uv (brew install uv) or configure an existing venv via probes 1-3" >&2
  return 1 2>/dev/null || exit 1
fi

# Fallback venv lives in the repo root. Create it only when absent; never wipe.
_venv_dir="${_project_dir}/.venv"

# Create-if-missing — a pre-existing .venv (e.g. one carrying project deps) is left intact.
if ! _venv_exe "${_venv_dir}" python >/dev/null; then
  echo "[lazy-python] creating project venv at ${_venv_dir}..." >&2
  uv venv --python 3.12 "${_venv_dir}" >&2
fi

# Augment-not-wipe — add only the missing checker tools; uv leaves everything else in place.
if ! _venv_has_tools "${_venv_dir}"; then
  echo "[lazy-python] installing checker tools into ${_venv_dir}..." >&2
  uv pip install --quiet --python "$(_venv_exe "${_venv_dir}" python)" mypy pylint pytest pytest-clarity pytest-sugar ruff >&2
fi

_activate "${_venv_dir}"
