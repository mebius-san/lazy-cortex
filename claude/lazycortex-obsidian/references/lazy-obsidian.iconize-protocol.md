---
name: lazy-obsidian.iconize-protocol
version: 2
description: Vault-local Iconize protocol — how the Python worker, the bundled `iconize-reloader` Obsidian plugin, and Iconize itself cooperate to compute file/folder icons from frontmatter and apply them at the live `data.json`.
protocol_version: 2.2.0
hook_version: 4.0.0
owner_skill: lazy-obsidian.iconize-sync
---
# Obsidian Iconize Protocol (vault-local)

Single source of truth for how file and folder icons are computed and where they get written. Two writers cooperate:

- **Python worker** (`${CLAUDE_PLUGIN_ROOT}/bin/iconize_sync.py`) — reads frontmatter + the local `obsidian-icon-map.json`, resolves each note's icon/color, writes the result back into that note's frontmatter as `iconize_icon` / `iconize_color`. Never touches `data.json`.
- **iconize-reloader plugin** (vault-shipped, at `<vault>/plugins/iconize-reloader/`) — watches folder-note frontmatter and writes folder-keyed entries into `.obsidian/plugins/obsidian-icon-folder/data.json`. Also repaints the file explorer when `data.json` changes on disk.
- **Iconize** (community plugin `obsidian-icon-folder`) — reads frontmatter via its native frontmatter-icon feature and paints file icons; reads folder-keyed entries out of `data.json` and paints folder icons.

This file describes MECHANICS (resolver inputs/outputs, frontmatter shape, folder-note routing, version policy). The declarative resolver rules live in `.claude/iconize/obsidian-icon-map.json` — edit that to change what icons are produced or to add your own registries.

## Versioning

Protocol 2.x — frontmatter-as-source-of-truth. 1.x wrote file-keyed entries into `data.json`; incompatible, migrate via `lazy-obsidian.iconize-install`.

Both `protocol_version` and `hook_version` use SemVer `MAJOR.MINOR.PATCH`. The icon-map's optional `min_hook_version` is checked against the worker's `hook_version` on every run; an unsatisfied requirement sends the hooks inert until the plugin is updated. MINOR/PATCH drift is compatible.

## Data model

**Frontmatter (written by the worker):**

```yaml
---
iconize_icon: LiFolder
iconize_color: "#fde68a"
---
```

- `iconize_icon` — icon id (required when the resolver fires for the note). Unquoted — icon ids are bare identifiers.
- `iconize_color` — hex color (optional). **Always double-quoted** because `#` opens a YAML comment when unquoted.
- Worker adds these keys when the resolver fires and updates them when the resolver's output changes. A note no matcher claims is left untouched — removing an icon is a manual (or owning-manager's) act, never the worker's.

**`data.json` writers — exhaustive:**

- **iconize-reloader plugin** — writes folder-keyed entries derived from folder-note frontmatter (see "Folder Notes routing" below). This is the only automated writer in the iconize-sync system.
- **Iconize itself** — writes file-keyed entries when the user picks an icon from its right-click menu, and rewrites its own `settings` / `rules` / `recentlyUsedIcons` blocks on UI interaction.
- **Worker** — never writes `data.json`. Frontmatter-only.

Folder-keyed entry shape: `"<vault-relative-folder-path>": {"iconName": "...", "iconColor"?: "..."}`.

Reserved keys (`settings`, `rules`, `recentlyUsedIcons`) are owned by Iconize and never touched by the reloader or the worker.

Your registries (roles, steps, requests, custom) live in the local `obsidian-icon-map.json` — NOT in `data.json` and NOT in frontmatter.

## Resolver

Input: `(vault_relative_path, frontmatter_dict)`. Output: zero or one `(icon, color?)` pair written to the note's own frontmatter.

The matcher list is a **composition of layers**, rebuilt on every run: the personal map's `matchers` plus every matcher from the plugin-shipped registries discovered via `$LAZYCORTEX_PLUGIN_DIRS` (see `lazy-obsidian.iconize-registry-contract.md`). Evaluation is first-match-wins over the composed list, ordered by descending matcher `priority`; on equal priority the operator's matcher beats a plugin's. Personal matchers without `priority` default to `1000` (above every registry band), so a map that never heard of priorities behaves exactly as before. Each matcher has a `when` predicate and a `resolve` spec. (The `emit` field retired at schema 2 — folder decoration flows from folder-notes, not from matcher output.)

**No-match keeps, never strips.** A note no matcher claims is left untouched: sibling plugins (e.g. lazycortex-specs) write managed `iconize_icon` / `iconize_color` keys of their own, and the absence of a rule is not an instruction to remove them. The worker rewrites the keys only when a matcher resolves a value.

**Templates are never painted.** Every path under a scaffolding-template tree — a plugin's own `claude/<plugin>/templates/**` and the consumer's `.claude/templates/**` override tree — resolves to no match regardless of frontmatter, and the reconcile walk never enumerates it. A template carries the frontmatter of the notes it scaffolds, so a frontmatter-keyed rule would otherwise fire on the template itself: painting it dirties a shipped source file on every reconcile and bakes a stale icon into every note scaffolded from it afterwards.

*One-time cleanup on upgrade (protocol 2.2.0).* A template painted by an earlier worker keeps its `iconize_icon` / `iconize_color` keys — no-match keeps and never strips, so nothing removes them on its own, and every note scaffolded afterwards inherits the stale pair. Strip the two keys by hand from every `.md` under the template trees once after the upgrade; the notes those templates produce then take their icon from the matchers, as they should.

### `when` predicates

`basename`, `basename_in`, `path_glob`, `frontmatter.<key>: <value>`, `frontmatter_has: <key>`, `frontmatter_missing: <key>`, `is_folder_note: true|false`, `role_matches_basename: true`, `callback: <id>`. Multiple keys AND together.

### `resolve` shapes

- Plain: `{iconName, iconColor?}`, each value either literal or `{from, key, field?}`.
- Base + overlays: `{base: {...}, overlays: [{when, iconName, iconColor, priority}]}`.
- Callback: `{callback: <id>}` — subprocess at `.claude/callbacks/<id>`; for a plugin-registry matcher the vault dir still wins (operator override), the shipping plugin's own `callbacks/<id>` is the fallback.

## Folder Notes routing

Folders don't have frontmatter of their own. Iconize paints folder icons from `data.json` folder-keyed entries. The reloader bridges the two by reading each folder's **folder-note** — the note conventionally named after its folder. Naming is driven by the Folder Notes community plugin's `folderNoteName` template (default: `{{folder_name}}`, yielding `<folder>/<folder>.md`).

For each folder-note that carries `iconize_icon` in frontmatter, the reloader writes a folder-keyed entry at the parent folder's path. If `iconize_color` is also present, it's written as `iconColor`. If the icon is removed from frontmatter, the reloader removes the folder entry.

Folders whose folder-note has no `iconize_icon` → no folder entry, no folder icon (deliberate; the vault never had one).

Folders that have no folder-note at all → no folder icon. Use the Folder Notes plugin to create a folder-note if you want to decorate that folder.

## Stage → iconColor table

If you use a stage-colored schema, define the table in `obsidian-icon-map.json` under `stage_colors` as a `{stage: "#rrggbb"}` map. The worker looks up each frontmatter `stage` in this table at resolve time. No defaults are shipped — the table is vault-specific.

## Entry format rules

**Frontmatter:** YAML keys, UTF-8, line-terminated with `\n`. Worker preserves the existing fence style (`---` or `...`), key order, and quote style of other keys. See the worker's frontmatter rewriter for details.

**`data.json`:** vault-relative paths with forward slashes, no leading `/`, no trailing `/` on folders. JSON with two-space indent; reloader writes atomically via `data.json.tmp` rename.

## Logging

Every `lazy-obsidian.iconize-sync` invocation logs to `./.logs/claude/lazy-obsidian.iconize-sync/YYYY-MM-DD_HH-MM-SS.md`. Hooks do not log (they are silent on no-op). Hook failures go to stderr and block the commit.

## Non-goals

- Managing Iconize's `rules` array.
- Installing icon packs.
