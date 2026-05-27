#!/usr/bin/env zsh
# Thin wrapper for lazycortex-python `tst` aggregator.
# Path to the plugin binary is substituted at install time via /lazy-python.install Phase 2.
# DO NOT EDIT — re-run install to refresh after plugin updates.
set -euo pipefail
exec "{{TST_BIN_PATH}}" "$@"
