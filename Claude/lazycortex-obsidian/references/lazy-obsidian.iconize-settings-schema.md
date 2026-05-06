---
description: Iconize plugin's `settings` block inside `data.json` — the keys `lazy-obsidian.iconize-install` and `lazy-obsidian.audit` must assert on, captured from the upstream source for offline reference.
name: Iconize settings keys (for frontmatter-icon feature)
source: obsidian-icon-folder main.js, version 2.14.7
date-verified: 2026-04-23
---
# Iconize frontmatter-icon settings

The three settings `lazy-obsidian.iconize-install` and `lazy-obsidian.audit`
must assert on the `settings` block inside
`.obsidian/plugins/obsidian-icon-folder/data.json`:

| Purpose | Key | Required value | Iconize default |
|---|---|---|---|
| Enable frontmatter-icon feature | `iconInFrontmatterEnabled` | `true` | `false` |
| Icon name property | `iconInFrontmatterFieldName` | `"iconize_icon"` | `"icon"` |
| Icon color property | `iconColorInFrontmatterFieldName` | `"iconize_color"` | `"iconColor"` |

Verified against Iconize version `2.14.7` on 2026-04-23.
Re-verify when the pinned Iconize version changes.

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

The template at `claude/lazycortex-obsidian/templates/obsidian/plugin-settings.json` already
encodes the three required values shown in the table above (`iconInFrontmatterEnabled: true`,
`iconInFrontmatterFieldName: "iconize_icon"`, `iconColorInFrontmatterFieldName: "iconize_color"`)
under its `obsidian-icon-folder.settings` key.

`/lazy-obsidian.update-plugin obsidian-icon-folder` is the applier — it deep-merges that override
block onto the vault's `obsidian-icon-folder/data.json` after every binary sync. `lazy-obsidian.audit`
Phase 2.5 re-verifies those three keys against this reference file, to catch drift if a future Iconize
release renames them.
