#!/usr/bin/env bash
# Resolve the latest lazycortex-core in the plugin cache and exec its runner.
# Real cache layout is 4 levels:
#   ~/.claude/plugins/cache/<registry>/<plugin>/<version>/bin/<plugin>
# Survives plugin version bumps without re-rendering the supervisor unit.
#
# Usage: lazy.runtime.sh [--login-shell] [--env-file <path>]... [--dev-mode] <repo-root> [--plugin-dir <path>]...
#
# --login-shell: re-exec the whole shim through a login shell ($SHELL -lc, default
# /bin/zsh) so the daemon inherits the operator's login environment (.zprofile /
# .zshrc -> CLAUDE_CODE_OAUTH_TOKEN + full PATH). launchd and systemd exec the shim
# directly, without a login shell, so on a headless host the daemon otherwise lacks
# both the auth token and a complete PATH (the `claude` binary may not resolve).
# Host-agnostic: no personal paths are hardcoded — the login shell sources whatever
# the operator's dotfiles export. Guarded by LAZYCORTEX_LOGIN_REEXEC so the
# re-exec'd pass does not loop.
#
# --env-file <path> (repeatable): source <path> (set -a; . <path>; set +a) so its
# exported vars reach the runner -> daemon -> claude. Surgical alternative to
# --login-shell when only a token file (e.g. ~/.claude/.env) is needed, not a full
# login PATH. A leading ~ is expanded; a missing file is skipped silently. Combines
# with --login-shell (sourced after the re-exec, layering on top).
#
# --dev-mode: scan <repo-root>/claude/*/.claude-plugin/plugin.json and inject
# one --plugin-dir <plugin-root> per match BEFORE existing args. The runner
# consults --plugin-dir paths first and falls back to the cache, so dev-mode
# transparently prefers in-repo plugin sources over their cached copies.

# Re-exec through a login shell before parsing, so the operator's .zprofile/.zshrc
# populate the environment (token + PATH) for everything below. The guard variable
# stops the re-exec'd pass from re-triggering. launchd's StandardOutPath /
# StandardErrorPath redirections live on inherited fds and survive the exec.
if [ -z "${LAZYCORTEX_LOGIN_REEXEC:-}" ]; then
  for arg in "$@"; do
    if [ "$arg" = "--login-shell" ]; then
      export LAZYCORTEX_LOGIN_REEXEC=1
      exec "${SHELL:-/bin/zsh}" -lc 'exec "$@"' _ "$0" "$@"
    fi
  done
fi

DEV_MODE=0
ENV_FILES=()
ARGS=()
REPO=""
while [ $# -gt 0 ]; do
  case "$1" in
    --login-shell)
      # Consumed by the re-exec above (a no-op on the re-exec'd pass); never
      # forwarded to the runner, which rejects unknown args.
      shift
      ;;
    --dev-mode)
      DEV_MODE=1
      shift
      ;;
    --env-file)
      if [ $# -ge 2 ]; then
        ENV_FILES+=("$2")
        shift 2
      else
        shift
      fi
      ;;
    *)
      ARGS+=("$1")
      # First non-flag positional is repo-root (runner's contract).
      if [ -z "$REPO" ] && [ "${1#--}" = "$1" ]; then
        REPO="$1"
      fi
      shift
      ;;
  esac
done

# Source operator-supplied env files (surgical token path). launchd does not expand
# a leading ~, so expand it here; the [ -f ] guard tolerates a missing/bad path.
for ef in "${ENV_FILES[@]}"; do
  case "$ef" in
    "~/"*) ef="$HOME/${ef#\~/}" ;;
    "~") ef="$HOME" ;;
  esac
  if [ -f "$ef" ]; then
    set -a
    . "$ef"
    set +a
  fi
done

if [ "$DEV_MODE" = "1" ] && [ -n "$REPO" ] && [ -d "$REPO/claude" ]; then
  DEV_DIRS=()
  for plugin_json in "$REPO"/claude/*/.claude-plugin/plugin.json; do
    [ -f "$plugin_json" ] || continue
    plugin_dir=$(dirname "$(dirname "$plugin_json")")
    DEV_DIRS+=(--plugin-dir "$plugin_dir")
  done
  # Insert --plugin-dir args directly after repo-root so the runner sees them
  # before any operator-supplied flags. ARGS[0] is repo-root by construction.
  if [ ${#DEV_DIRS[@]} -gt 0 ]; then
    ARGS=("${ARGS[0]}" "${DEV_DIRS[@]}" "${ARGS[@]:1}")
  fi
fi

RUNNER=$(ls -d ~/.claude/plugins/cache/*/lazycortex-core/*/bin/runner 2>/dev/null | sort -r | head -1)
[ -z "$RUNNER" ] && { echo "lazycortex-core/bin/runner not found in plugin cache" >&2; exit 1; }
exec "$RUNNER" "${ARGS[@]}"
