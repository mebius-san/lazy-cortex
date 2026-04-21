---
protocol_version: 1.0.0
hook_version: 1.0.0
owner_skill: lazy-obsidian.iconize-sync
---

# Obsidian Iconize Protocol (vault-local)

Single source of truth for how file/folder icons are computed from frontmatter
and written to `.obsidian/plugins/obsidian-icon-folder/data.json` in this vault.
Read by `lazy-obsidian.iconize-sync`, the `.githooks/pre-commit` shim, and the
plugin-shipped PostToolUse hook (auto-loaded from the plugin's `hooks/hooks.json`
when `lazycortex-obsidian` is enabled).

This file describes the MECHANICS (resolver inputs/outputs, entry format,
version policy). The declarative resolver rules live in
`.claude/obsidian-iconize/icon-map.json` — edit that to change what icons are
produced, which matchers fire, or to add your own registries.

## Versioning

Both `protocol_version` and `hook_version` use SemVer `MAJOR.MINOR.PATCH`.
MAJOR mismatch between the worker and the installed hooks triggers a hook
reinstall (`lazy-obsidian.iconize-sync install-hooks`). MINOR/PATCH drift is
compatible.

## Data model

Entries written to `data.json`:
- Path-keyed: `"<vault-relative-path>": {"iconName": "...", "iconColor"?: "..."}`
- Plugin-owned reserved keys (`settings`, `rules`, `recentlyUsedIcons`) are
  never touched.

Your registries (roles, steps, requests, or anything custom) live in the local
`icon-map.json` — NOT in `data.json`. The worker reads the icon-map, computes
path-keyed entries, and only ever writes those to `data.json`.

## Resolver

Input: `(vault_relative_path, frontmatter_dict)`. Output: zero, one, or two
`data.json` entries (the second for emitting on `parent_dir`).

Matchers in `icon-map.json` are evaluated in array order; first match wins.
Each matcher has a `when` predicate, a `resolve` spec, and an `emit` list.

### `when` predicates

`basename`, `basename_in`, `path_glob`, `frontmatter.<key>: <value>`,
`role_matches_basename: true`, `callback: <id>`. Multiple keys AND together.

### `resolve` shapes

- Plain: `{iconName, iconColor?}`, each value either literal or `{from, key, field?}`.
- Base + overlays: `{base: {...}, overlays: [{when, iconName, iconColor, priority}]}`.
- Callback: `{callback: <id>}` (subprocess at `.claude/callbacks/<id>`).

### `emit` targets

`"self"` (the file itself), `"parent_dir"` (the enclosing folder). Emitting
both writes the same icon twice — once at the file path, once at the folder.

## Stage → iconColor table

The worker ships a default table for authored-doc stages. Override in
`icon-map.json` under `stage_colors` if desired.

| stage | default color |
|---|---|
| empty | #e2e8f0 |
| draft | #fde68a |
| review | #fef3c7 |
| done | #d1fae5 |
| rejected | #f87171 |
| cancelled | #cbd5e1 |

## Entry format rules

- Vault-relative paths, forward slashes, no leading `/`, no trailing `/` on folders.
- Files: full basename with extension.
- Case-sensitive.
- `iconName`: Lucide `Li<PascalCase>` or emoji.
- `iconColor`: lowercase `#rgb` or `#rrggbb`. Omitted for monochrome.
- Writes use 2-space indent, UTF-8 (no ASCII escapes), trailing newline.

## Logging

Every `lazy-obsidian.iconize-sync` invocation logs to
`./.logs/claude/lazy-obsidian.iconize-sync/YYYY-MM-DD_HH-MM-SS.md`. Hooks do
not log (they are silent on no-op). Hook failures go to stderr and block the
commit.

## Non-goals

- Managing Iconize's `rules` array.
- Installing icon packs.
- Writing frontmatter (consumer skills own that).

## For plugin maintainers

This mirror of the vault-facing protocol exists so the `lazy-obsidian.audit` skill can cross-check code against spec.

### Worker exit codes

| Code | Name | Meaning |
|---|---|---|
| 0 | EXIT_OK | Success. |
| 1 | EXIT_VALIDATION | Invalid input, malformed config, or bad CLI usage. |
| 2 | EXIT_DATAFILE_MISSING | Vault has no `.obsidian/` or no Iconize `data.json`. |
| 3 | EXIT_CONCURRENT | `data.json` mtime changed between read and write. |
| 4 | EXIT_TARGET_MISSING | Target path to sync does not exist. |
| 5 | EXIT_VERSION_DRIFT | Installed hook version does not match worker. |

### Subcommand dispatch

| Subcommand | Handler |
|---|---|
| sync | cmd_sync |
| sync-staged | cmd_sync_staged |
| reconcile | cmd_reconcile |
| install-hooks | cmd_install_hooks |
| check-versions | cmd_check_versions |
