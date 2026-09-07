---
description: Iconize plugin's `settings` block inside `data.json` — the keys `lazy-obsidian.iconize-install` and `lazy-obsidian.audit` must assert on, captured from the upstream source for offline reference.
name: Iconize settings keys (for frontmatter-icon feature)
source: obsidian-icon-folder main.js, version 2.14.7
date-verified: 2026-04-23
---
# Iconize frontmatter-icon settings

The three settings `lazy-obsidian.iconize-install` and `lazy-obsidian.audit` must assert on the `settings` block inside `.obsidian/plugins/obsidian-icon-folder/data.json`:

| Purpose | Key | Required value | Iconize default |
|---|---|---|---|
| Enable frontmatter-icon feature | `iconInFrontmatterEnabled` | `true` | `false` |
| Icon name property | `iconInFrontmatterFieldName` | `"iconize_icon"` | `"icon"` |
| Icon color property | `iconColorInFrontmatterFieldName` | `"iconize_color"` | `"iconColor"` |

Verified against Iconize version `2.14.7` on 2026-04-23. Re-verify when the pinned Iconize version changes.

## Source locations in main.js

Defaults are declared at line 3202–3204:

```js
iconInFrontmatterEnabled: false,
iconInFrontmatterFieldName: 'icon',
iconColorInFrontmatterFieldName: 'iconColor',
```

Settings UI labels are defined in the `FrontmatterOptions` class (line 5058):

| Key | `.setName(...)` label | `.setDesc(...)` description |
|---|---|---|
| `iconInFrontmatterEnabled` | `Use icon in frontmatter` | Toggles whether to set the icon based on the frontmatter property `icon`. |
| `iconInFrontmatterFieldName` | `Frontmatter icon field name` | Sets the name of the frontmatter field which contains the icon. |
| `iconColorInFrontmatterFieldName` | `Frontmatter icon color field name` | Sets the name of the frontmatter field which contains the icon color. |

## Note on plugin-settings.json

The template at `claude/lazycortex-obsidian/templates/obsidian/plugin-settings.json` already encodes the three required values shown in the table above (`iconInFrontmatterEnabled: true`, `iconInFrontmatterFieldName: "iconize_icon"`, `iconColorInFrontmatterFieldName: "iconize_color"`) under its `obsidian-icon-folder.settings` key.

`/lazy-obsidian.update-plugin obsidian-icon-folder` is the applier — it deep-merges that override block onto the vault's `obsidian-icon-folder/data.json` after every binary sync. `lazy-obsidian.audit` Phase 2.5 re-verifies those three keys against this reference file, to catch drift if a future Iconize release renames them.

## Icon-map key: `paint_roots`

The three keys above configure Iconize itself. The worker's own configuration lives in a separate file, the icon-map at `.claude/iconize/obsidian-icon-map.json`, whose resolver semantics are documented in `lazy-obsidian.iconize-protocol.md`. One of its top-level keys governs which part of the vault is configured at all, so it is recorded here beside the settings it interacts with.

| Key | Type | Meaning | Absent |
|---|---|---|---|
| `paint_roots` | list of repo-relative directory prefixes | The only areas of the vault the worker may paint. Outside `paint_roots` the worker does not read or write the note: no matcher runs for it, nothing is written, and any `iconize_icon` / `iconize_color` it already carries is left exactly as it stands. | The whole vault is in scope — the behaviour every icon-map had before this key existed. |

A prefix claims a path across a directory boundary only, so `specs` claims `specs/product/design.md` and never `specsheets/design.md`. Scaffolding-template trees stay exempt from painting whether or not they fall inside a listed prefix.

Narrowing the list does not clean up after itself: icons already written in an area the list no longer covers stay put, because no run touches that area again. Removing them is a manual edit.

`/lazy-obsidian.iconize-install` Step 2.7 seeds the key with a single entry — the consumer's spec content root, read from `spec.vault_root` in `.claude/lazy.settings.json` and defaulting to `specs` — on a fresh install, and adds it to an existing icon-map that does not carry it. An authored value is never rewritten.
