#!/usr/bin/env bash
# HOOK_VERSION: 1.0.0
# HOOK_PROTOCOL: obsidian.iconize-sync
# This file is managed by `lazy-obsidian.iconize-sync install-hooks`.
# Re-run that command after updating the plugin to refresh this shim.
exec python3 "{{PLUGIN_BIN_PATH}}/iconize_sync.py" sync-staged
