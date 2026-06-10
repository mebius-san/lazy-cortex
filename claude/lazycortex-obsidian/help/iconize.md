---
chapter_type: block
summary: Scaffold, configure, and run the iconize-sync system to keep Obsidian file and folder icons in sync with your vault's frontmatter-driven icon registry.
last_regen: 2026-06-10
diagram_spec:
  anchor: "How the three skills fit together"
  request: "Flow diagram showing the three-skill iconize block: iconize-install scaffolds plugins + icon-map + hooks; iconize-config edits the icon-map registry; iconize-sync runs the worker to write iconize_icon/iconize_color into note frontmatter; Iconize plugin and iconize-reloader plugin then paint icons on screen from frontmatter and data.json respectively."
  kind_hint: flow
source_skills:
  - lazy-obsidian.iconize-install
  - lazy-obsidian.iconize-config
  - lazy-obsidian.iconize-sync
---
# Iconize — frontmatter-driven icon management for Obsidian vaults

The iconize block gives you a declarative, version-controlled way to keep every file and folder icon in your Obsidian vault in sync with the vault's own frontmatter semantics. Instead of clicking icons one by one inside Obsidian, you maintain a registry — a JSON map of roles, stages, statuses, and any other domain you care about — and the worker writes the correct `iconize_icon` and `iconize_color` keys into each note's YAML frontmatter automatically. The Iconize plugin reads those keys live and paints icons in file tabs and titles; the bundled iconize-reloader plugin watches folder-note frontmatter and bridges it into folder icons in the file explorer.

Three skills divide the work cleanly: `/lazy-obsidian.iconize-install` sets up the entire system from scratch in a single pass; `/lazy-obsidian.iconize-config` is a wizard for editing the icon registry without touching the file by hand; and `/lazy-obsidian.iconize-sync` runs the worker that reconciles the registry into your vault's notes.

## When you'd use this

- Setting up Iconize on a fresh repo or after cloning a project that has an Obsidian vault — install all three dependency plugins and scaffold the registry in one command.
- Extending or refining the icon scheme after adding new frontmatter roles, stages, or status values to your vault.
- Applying a changed registry across the whole vault, a path prefix, or just the files touched in a pending commit.
- Keeping icons consistent across machines — the registry lives in `.claude/iconize/obsidian-icon-map.json` and is tracked by git; Iconize's runtime `data.json` is gitignored because the worker regenerates it.

## How it fits together

You start with `/lazy-obsidian.iconize-install`. This skill installs the three required Obsidian plugins (`obsidian-icon-folder`, `folder-notes`, and the bundled `iconize-reloader`) into your vault via `/lazy-obsidian.update-plugin`, scaffolds the icon-map at `.claude/iconize/obsidian-icon-map.json`, installs the pre-commit shim to `.githooks/pre-commit`, and adds Iconize's `data.json` to `.gitignore` so runtime state does not pollute commits. It also asserts the Iconize frontmatter-feature settings (`iconInFrontmatterEnabled`, `iconInFrontmatterFieldName`, `iconColorInFrontmatterFieldName`) in your vault's plugin config so the worker's output keys match what Iconize expects to read. The install is quiet and idempotent — safe to re-run on any repo that already has it set up.

Once the system is scaffolded, `/lazy-obsidian.iconize-config` is how you grow the registry. It walks you through adding, editing, or removing entries in any named registry (roles, steps, requests, or a custom one you name) via one-question-at-a-time prompts. Each entry needs a key name, a Lucide icon name (PascalCase with `Li` prefix) or emoji, and an optional hex color. After every session the skill writes the updated JSON back with stable formatting. Run `/lazy-obsidian.iconize-sync reconcile` after any registry edit so the new entries land in your vault's frontmatter.

`/lazy-obsidian.iconize-sync` is the worker dispatcher. Its most-used subcommands are:

- `reconcile` — walks all `.md` files (or a `--prefix` subtree) and rewrites `iconize_icon` / `iconize_color` everywhere the registry has an opinion. Files that no longer match any rule have those keys cleared.
- `sync <path>` — resolves and rewrites a single file; this is what the PostToolUse hook calls after every Write or Edit to keep things current without a full sweep.
- `sync-staged` — resolves only the `.md` files in the git index and re-stages them, so icon frontmatter is always consistent inside a commit. The pre-commit shim calls this automatically.
- `reconcile-dirty` — safety net for files written via Bash or bulk renames that bypass the PostToolUse hook; the Stop hook calls this at the end of every agent turn.
- `check-versions` — confirms the pre-commit shim's `HOOK_VERSION` and the icon-map's `schema_version` are compatible with the installed worker.

The three hooks (PostToolUse on Write/Edit, pre-commit shim, Stop) mean you rarely need to call `iconize-sync` directly — icons stay current as you work. The only time you call it explicitly is after a registry change (`reconcile`) or a bulk operation that you want to sweep immediately.

## Common adjustments

**Adding or changing icons for a new frontmatter value.** Run `/lazy-obsidian.iconize-config` and pick the registry that holds the value. The wizard prompts for the key, icon name, and color. After saving, run `/lazy-obsidian.iconize-sync reconcile` to apply everywhere.

**Scoping a reconcile to one plugin or folder.** Pass `--prefix <path>` to `reconcile`, or use `reconcile-plugin <plugin>` if you want to reconcile a specific LazyCortex plugin subtree and have the changes automatically re-staged.

**Checking whether your install is current after a plugin update.** Run `/lazy-obsidian.iconize-sync check-versions`. Exit code 0 means both axes (shim version and icon-map schema) are compatible. If it exits 5, re-run `/lazy-obsidian.iconize-install` to update the shim or migrate the schema.

**The icon-map schema needs migration.** If `/lazy-obsidian.iconize-install` detects the vault's icon-map is on an older schema, it applies the transform silently when a migration path exists. If no path exists, it asks whether to replace with the current empty-schema template. Your registries and matchers are shown before overwriting — you can copy them out first.

**Editing matcher logic.** The icon-map `matchers` array controls which frontmatter values resolve to which registry entries. Matchers are structural and benefit from seeing the whole file at once — edit `.claude/iconize/obsidian-icon-map.json` directly for that section. Only registry entries (the `registries` key) are managed through `/lazy-obsidian.iconize-config`.

## How the three skills fit together

```mermaid
%%{init: {'themeVariables':{'background':'transparent','lineColor':'#000','textColor':'#000','edgeLabelBackground':'#fff'},'themeCSS':'.edgeLabel{background-color:transparent!important}.edgeLabel p{background-color:transparent!important}','flowchart':{'diagramPadding':5,'useMaxWidth':true}}}%%
flowchart LR
  iconizeInstall[lazy-obsidian.iconize-install]
  iconizeConfig[lazy-obsidian.iconize-config]
  iconizeSync[lazy-obsidian.iconize-sync]
  pluginsScaffolded[Plugins + icon-map + hooks scaffolded]
  iconMapUpdated[Icon-map registry updated]
  frontmatterWritten[iconize_icon / iconize_color written to frontmatter]
  iconizePlugin[Iconize plugin]
  iconizeReloader[iconize-reloader plugin]
  iconsOnScreen[Icons painted on screen]

  iconizeInstall -->|scaffold| pluginsScaffolded
  pluginsScaffolded -->|ready| iconizeConfig
  iconizeConfig -->|edit icon-map| iconMapUpdated
  iconMapUpdated -->|trigger| iconizeSync
  iconizeSync -->|run worker| frontmatterWritten
  frontmatterWritten -->|reads frontmatter| iconizePlugin
  frontmatterWritten -->|reads data.json| iconizeReloader
  iconizePlugin -->|paint icons| iconsOnScreen
  iconizeReloader -->|paint icons| iconsOnScreen

  classDef entry fill:#1e3a5f,stroke:#4a90e2,color:#fff
  classDef action fill:#1e5f3a,stroke:#4ae290,color:#fff
  classDef success fill:#0d4d2a,stroke:#4ae290,color:#fff,stroke-width:2px
  classDef service fill:#1e4a5f,stroke:#4abce2,color:#fff

  class iconizeInstall entry
  class iconizeConfig entry
  class iconizeSync entry
  class pluginsScaffolded action
  class iconMapUpdated action
  class frontmatterWritten action
  class iconizePlugin service
  class iconizeReloader service
  class iconsOnScreen success
```

## See also

- [`install-and-audit`](install-and-audit.md) — the broader vault bootstrap block that chains into iconize-install as part of the full project setup
