#!/usr/bin/env bash
# Shared project-venv logic for cfg / chk / tst — sourced, never executed.
#
# Defines the helpers that locate, verify and configure the project venv; sourcing it
# runs nothing but the project-root resolution below. `bin/cfg` calls `_cfg_venv` to
# create / update the venv on request; `_ensure_venv.sh` (sourced by chk / tst) checks
# `_venv_is_fresh` and calls `_cfg_venv` only when it may install.
#
# Target venv: `[tool.lazy-python].venv` from pyproject.toml when set (~ expanded,
# relative paths resolved against the project root), else `<project>/.venv`.
#
# Everything the venv must carry comes from pyproject.toml (+ .python-version):
#   - interpreter: `uv venv` run in the project directory picks one satisfying
#     `requires-python` / `.python-version`; an existing venv whose interpreter does not
#     satisfy them is recreated (`uv venv --clear`), otherwise it is updated in place;
#   - packages: `[project].dependencies`, every extra, every `[dependency-groups]` group,
#     plus the checker tools (mypy/pylint/pytest/ruff + pytest-clarity/pytest-sugar/pytest-xdist);
#     the argument list comes from `venv_spec.py install-args`.
# A successful configure records a digest of exactly those inputs in
# `<venv>/.lazy-python-cfg` (`venv_spec.py stamp`). The venv is fresh iff it carries the
# tools AND that stamp matches the current digest — editing an unrelated pyproject
# section (e.g. `[tool.ruff]`) keeps it fresh; a venv with no stamp is stale.
#
# Protected mode (`LAZYCORTEX_PROTECTED` set to anything but empty or `0`): nothing
# installs — `_cfg_venv` refuses outright.
#
# venv_spec.py reads pyproject with `tomllib`, so it runs under the venv's own python and
# needs Python >= 3.11 there. A venv keeps its executables in bin/ on macOS / Linux and in
# Scripts/ (with .exe names) on Windows; every helper resolves whichever layout the venv
# carries. Sourced by bash (cfg, chk, tst) and by zsh (the checker tests), so the syntax
# stays common to both.

# Directory holding this file (and venv_spec.py): BASH_SOURCE under bash, $0 under zsh.
_lazy_py_bin="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

# Resolve the project root: the toplevel of the checkout CLAUDE_PROJECT_DIR names
# when set (Claude Code points it at the session's project), else of the checkout
# the shell runs in ($LAZY_REPO_ROOT first, then PWD), as the plugin locator's
# `toplevel` verb prints it; outside git the start directory itself. Keying it on
# the checkout root (not bare PWD) stops a stray `.venv` from being created in a
# subdirectory when chk/tst is run from somewhere below the repo root. A locator
# that cannot run (no interpreter, a broken copy) leaves the start directory in charge.
if [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
  _project_dir="$("${LAZYCORTEX_PYTHON:-python3}" "${_lazy_py_bin}/python_locator.py" toplevel \
    --start "${CLAUDE_PROJECT_DIR}" 2>/dev/null || printf '%s' "${CLAUDE_PROJECT_DIR}")"
else
  _project_dir="$("${LAZYCORTEX_PYTHON:-python3}" "${_lazy_py_bin}/python_locator.py" toplevel 2>/dev/null \
    || printf '%s' "${PWD}")"
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

# Name the first piece a candidate venv lacks: one of the four required bins (mypy, pylint,
# pytest, ruff), its python, or one of the three pytest plugins (pytest-clarity, pytest-sugar,
# pytest-xdist), which ship no bin and are checked by importing them in the venv's interpreter.
# Prints the name and succeeds when something is missing; prints nothing and fails when the
# venv is complete.
_venv_missing_tool() {
  local venv="$1"
  local tool python module
  for tool in mypy pylint pytest ruff; do
    if ! _venv_exe "${venv}" "${tool}" >/dev/null; then
      printf '%s' "${tool}"
      return 0
    fi
  done
  if ! python="$(_venv_exe "${venv}" python)"; then
    printf '%s' "python"
    return 0
  fi
  # the three plugins import together in a complete venv; only a failure probes them one by one
  if "${python}" -c "import pytest_clarity, pytest_sugar, xdist" >/dev/null 2>&1; then
    return 1
  fi
  for module in pytest_clarity:pytest-clarity pytest_sugar:pytest-sugar xdist:pytest-xdist; do
    if ! "${python}" -c "import ${module%%:*}" >/dev/null 2>&1; then
      printf '%s' "${module#*:}"
      return 0
    fi
  done
  # the combined import failed though each plugin imports alone: name the set
  printf '%s' "pytest-clarity, pytest-sugar or pytest-xdist"
  return 0
}

# Check whether a candidate venv is complete: every piece `_venv_missing_tool` checks is there.
_venv_has_tools() {
  ! _venv_missing_tool "$1" >/dev/null
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

# Succeed when protected mode is on: LAZYCORTEX_PROTECTED set to anything but empty or `0`.
_lazy_py_protected() {
  [ -n "${LAZYCORTEX_PROTECTED:-}" ] && [ "${LAZYCORTEX_PROTECTED}" != "0" ]
}

# Print the target venv: [tool.lazy-python].venv when set, else <project>/.venv.
_target_venv() {
  local configured
  configured="$(_read_pyproject_key venv)"
  if [ -z "${configured}" ]; then
    printf '%s' "${_project_dir}/.venv"
    return 0
  fi
  # Expand ~ and resolve relative paths against the project dir.
  configured="${configured/#\~/$HOME}"
  case "${configured}" in
    /*) printf '%s' "${configured}" ;;
    *) printf '%s' "${_project_dir}/${configured}" ;;
  esac
}

# Run venv_spec.py <command> under the venv's own python (needs >= 3.11 for tomllib).
_venv_spec() {
  local venv="$1" command="$2" python
  python="$(_venv_exe "${venv}" python)" || {
    echo "[lazy-python] no python in ${venv}" >&2
    return 1
  }
  # guard: tomllib arrived in Python 3.11 — an older venv cannot read pyproject.toml
  if ! "${python}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
    echo "[lazy-python] ${python} is older than Python 3.11 (no tomllib); lazy-python needs a venv on Python >= 3.11" >&2
    return 1
  fi
  "${python}" -I "${_lazy_py_bin}/venv_spec.py" "${command}" "${_project_dir}" "${venv}"
}

# Succeed when the venv carries the checker tools AND was configured against the current
# pyproject requirement inputs.
_venv_is_fresh() {
  local venv="$1" verdict
  _venv_has_tools "${venv}" || return 1
  verdict="$(_venv_spec "${venv}" fresh 2>/dev/null)" || return 1
  [ "${verdict}" = "fresh" ]
}

# Judge the venv's interpreter against the project's Python requirement: with VIRTUAL_ENV
# pointing at it, `uv python find` reports the venv's own python only when it satisfies
# requires-python / .python-version. Directories are compared after resolving symlinks (the
# venv's python is itself a symlink to its base interpreter).
# Returns 0 when it satisfies, 1 when uv names another interpreter, 2 when `uv python find`
# itself fails — then uv's own stderr is printed verbatim on stderr.
_venv_interpreter_ok() {
  local venv="$1" found found_dir venv_dir err_file uv_status
  err_file="$(mktemp)"
  uv_status=0
  found="$(VIRTUAL_ENV="${venv}" uv python find --directory "${_project_dir}" 2>"${err_file}")" || uv_status=$?
  # guard: a uv failure is uv's to explain, never read as a mismatch
  if [ "${uv_status}" -ne 0 ]; then
    cat "${err_file}" >&2
    rm -f "${err_file}"
    return 2
  fi
  rm -f "${err_file}"
  found_dir="$(cd "$(dirname "${found}")" 2>/dev/null && pwd -P)" || return 1
  venv_dir="$(cd "$(_venv_bin_dir "${venv}")" 2>/dev/null && pwd -P)" || return 1
  [ "${found_dir}" = "${venv_dir}" ]
}

# Create or update <venv> to the project's requirements plus the checker tools, then
# record the requirement stamp. Refuses in protected mode; never runs without uv.
_cfg_venv() {
  local venv="$1" python args_text arg verdict
  local -a install_args

  # guard: protected mode installs nothing, whoever asks
  if _lazy_py_protected; then
    echo "[lazy-python] refusing to configure ${venv}: LAZYCORTEX_PROTECTED is set (protected mode installs nothing)" >&2
    echo "[lazy-python] run cfg-py from an interactive session or console, not in protected mode" >&2
    return 1
  fi
  # guard: every create / install step goes through uv
  if ! command -v uv >/dev/null 2>&1; then
    echo "[lazy-python] uv not on PATH — cannot configure ${venv}" >&2
    echo "  install uv (brew install uv) or activate a venv with the checker tools (\$VIRTUAL_ENV)" >&2
    return 1
  fi

  # interpreter: create when missing, recreate when it does not satisfy the project, else keep;
  # a uv failure while judging it stops here and leaves the venv as it is
  if ! _venv_exe "${venv}" python >/dev/null; then
    echo "[lazy-python] creating project venv at ${venv}..." >&2
    uv venv --directory "${_project_dir}" "${venv}" >&2 || return 1
  else
    verdict=0
    _venv_interpreter_ok "${venv}" || verdict=$?
    if [ "${verdict}" -eq 2 ]; then
      echo "[lazy-python] uv python find failed (its output is above); ${venv} is left as it is" >&2
      return 1
    elif [ "${verdict}" -ne 0 ]; then
      echo "[lazy-python] recreating ${venv}: its interpreter does not satisfy the project's" \
        "Python requirement..." >&2
      uv venv --directory "${_project_dir}" --clear "${venv}" >&2 || return 1
    fi
  fi
  python="$(_venv_exe "${venv}" python)" || return 1

  # packages: project dependencies, all extras, all groups, plus the checker tools
  args_text="$(_venv_spec "${venv}" install-args)" || return 1
  install_args=()
  while IFS= read -r arg; do
    if [ -n "${arg}" ]; then
      install_args+=("${arg}")
    fi
  done <<< "${args_text}"
  echo "[lazy-python] installing project requirements and checker tools into ${venv}..." >&2
  uv pip install --quiet --python "${python}" "${install_args[@]}" >&2 || return 1

  # stamp: only a fully configured venv records the inputs it was configured against
  _venv_spec "${venv}" stamp || return 1
}
