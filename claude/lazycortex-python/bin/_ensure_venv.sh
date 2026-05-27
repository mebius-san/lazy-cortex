#!/usr/bin/env zsh
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
set -euo pipefail

_project_dir="${CLAUDE_PROJECT_DIR:-${PWD}}"

# Check whether a candidate venv is complete: the four required bins (mypy, pylint,
# pytest, ruff) AND the two pytest plugins (pytest-clarity, pytest-sugar) importable.
_venv_has_tools() {
  local venv="$1"
  local tool
  for tool in mypy pylint pytest ruff; do
    [ -x "${venv}/bin/${tool}" ] || return 1
  done
  # guard: pytest plugins ship no bin — verify they import in the venv's interpreter
  [ -x "${venv}/bin/python" ] || return 1
  "${venv}/bin/python" -c "import pytest_clarity, pytest_sugar" >/dev/null 2>&1 || return 1
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

# Activate a venv: prepend its bin/ to PATH and return successfully.
_activate() {
  local venv="$1"
  export PATH="${venv}/bin:${PATH}"
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
if [ ! -x "${_venv_dir}/bin/python" ]; then
  echo "[lazy-python] creating project venv at ${_venv_dir}..." >&2
  uv venv --python 3.12 "${_venv_dir}" >&2
fi

# Augment-not-wipe — add only the missing checker tools; uv leaves everything else in place.
if ! _venv_has_tools "${_venv_dir}"; then
  echo "[lazy-python] installing checker tools into ${_venv_dir}..." >&2
  uv pip install --quiet --python "${_venv_dir}/bin/python" mypy pylint pytest pytest-clarity pytest-sugar ruff >&2
fi

_activate "${_venv_dir}"
