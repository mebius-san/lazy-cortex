---
protocol_version: 2.0.0
hook_version: 2.0.0
owner_skill: lazy-obsidian.iconize-sync
---
# Obsidian Iconize Protocol (vault-local)

Single source of truth for how file and folder icons are computed and where
they get written. Two writers cooperate:

- **Python worker** (`${CLAUDE_PLUGIN_ROOT}/bin/iconize_sync.py`) — reads
  frontmatter + the local `icon-map.json`, resolves each note's icon/color,
  writes the result back into that note's frontmatter as
  `iconize_icon` / `iconize_color`. Never touches `data.json`.
- **iconize-reloader plugin** (vault-shipped, at
  `<vault>/plugins/iconize-reloader/`) — watches folder-note frontmatter and
  writes folder-keyed entries into
  `.obsidian/plugins/obsidian-icon-folder/data.json`. Also repaints the
  file explorer when `data.json` changes on disk.
- **Iconize** (community plugin `obsidian-icon-folder`) — reads frontmatter
  via its native frontmatter-icon feature and paints file icons; reads
  folder-keyed entries out of `data.json` and paints folder icons.

This file describes MECHANICS (resolver inputs/outputs, frontmatter shape,
folder-note routing, version policy). The declarative resolver rules live
in `.claude/obsidian-iconize/icon-map.json` — edit that to change what icons
are produced or to add your own registries.

## Versioning

Protocol 2.x — frontmatter-as-source-of-truth. 1.x wrote file-keyed entries
into `data.json`; incompatible, migrate via `lazy-obsidian.iconize-install`.

Both `protocol_version` and `hook_version` use SemVer `MAJOR.MINOR.PATCH`.
MAJOR mismatch between the worker and the installed hooks triggers a hook
reinstall (`lazy-obsidian.iconize-sync install-hooks`). MINOR/PATCH drift is
compatible.

## Data model

**Frontmatter (written by the worker):**

```yaml
---
iconize_icon: LiFolder
iconize_color: "#fde68a"
---
```

- `iconize_icon` — icon id (required when the resolver fires for the note).
  Unquoted — icon ids are bare identifiers.
- `iconize_color` — hex color (optional). **Always double-quoted** because
  `#` opens a YAML comment when unquoted.
- Worker adds these keys when the resolver fires, updates them when the
  resolver's output changes, and removes them when the resolver no longer
  matches the note.

**`data.json` (written only by the reloader):**

- Folder-keyed entries: `"<vault-relative-folder-path>": {"iconName": "...", "iconColor"?: "..."}`.
- Reloader derives each folder entry from that folder's folder-note
  frontmatter (see "Folder Notes routing" below).
- Reloader never writes file-keyed entries. User-driven file icons set via
  Iconize's right-click menu survive (Iconize itself writes them).
- Plugin-owned reserved keys (`settings`, `rules`, `recentlyUsedIcons`) are
  never touched by either writer.

Your registries (roles, steps, requests, custom) live in the local
`icon-map.json` — NOT in `data.json` and NOT in frontmatter.

## Resolver

Input: `(vault_relative_path, frontmatter_dict)`. Output: zero or one
`(icon, color?)` pair written to the note's own frontmatter.

Matchers in `icon-map.json` are evaluated in array order; first match wins.
Each matcher has a `when` predicate and a `resolve` spec. (The `emit` field
retired at schema 2 — folder decoration flows from folder-notes, not from
matcher output.)

### `when` predicates

`basename`, `basename_in`, `path_glob`, `frontmatter.<key>: <value>`,
`role_matches_basename: true`, `callback: <id>`. Multiple keys AND together.

### `resolve` shapes

- Plain: `{iconName, iconColor?}`, each value either literal or
  `{from, key, field?}`.
- Base + overlays: `{base: {...}, overlays: [{when, iconName, iconColor, priority}]}`.
- Callback: `{callback: <id>}` (subprocess at `.claude/callbacks/<id>`).

## Folder Notes routing

Folders don't have frontmatter of their own. Iconize paints folder icons
from `data.json` folder-keyed entries. The reloader bridges the two by
reading each folder's **folder-note** — the note conventionally named after
its folder. Naming is driven by the Folder Notes community plugin's
`folderNoteName` template (default: `{{folder_name}}`, yielding
`<folder>/<folder>.md`).

For each folder-note that carries `iconize_icon` in frontmatter, the
reloader writes a folder-keyed entry at the parent folder's path. If
`iconize_color` is also present, it's written as `iconColor`. If the icon
is removed from frontmatter, the reloader removes the folder entry.

Folders whose folder-note has no `iconize_icon` → no folder entry, no
folder icon (deliberate; the vault never had one).

Folders that have no folder-note at all → no folder icon. Use the Folder
Notes plugin to create a folder-note if you want to decorate that folder.

## Stage → iconColor table

If you use a stage-colored schema, define the table in `icon-map.json` under
`stage_colors` as a `{stage: "#rrggbb"}` map. The worker looks up each
frontmatter `stage` in this table at resolve time. No defaults are shipped —
the table is vault-specific.

## Entry format rules

**Frontmatter:** YAML keys, UTF-8, line-terminated with `\n`. Worker
preserves the existing fence style (`---` or `...`), key order, and quote
style of other keys. See the worker's frontmatter rewriter for details.

**`data.json`:** vault-relative paths with forward slashes, no leading `/`,
no trailing `/` on folders. JSON with two-space indent; reloader writes
atomically via `data.json.tmp` rename.

## Logging

Every `lazy-obsidian.iconize-sync` invocation logs to
`./.logs/claude/lazy-obsidian.iconize-sync/YYYY-MM-DD_HH-MM-SS.md`. Hooks do
not log (they are silent on no-op). Hook failures go to stderr and block the
commit.

## Non-goals

- Managing Iconize's `rules` array.
- Installing icon packs.
