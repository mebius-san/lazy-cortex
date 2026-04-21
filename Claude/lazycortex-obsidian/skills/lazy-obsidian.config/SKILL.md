---
name: lazy-obsidian.config
description: "Install and update the curated musthave community plugins in the current project's Obsidian vault. Plugin binaries are not shipped in this plugin — each run compares the vault's installed version against the latest GitHub release and downloads fresh `manifest.json` / `main.js` / `styles.css` directly into the vault only when the remote is newer. Custom plugins like `iconize-reloader` ship bundled in the template and sync the same way. After each binary update, opinionated settings from `plugin-settings.json` are merged into the vault's `<id>/data.json` (user keys outside the override block are preserved). Regenerates `community-plugins.json` in correct load order. Scope is strictly plugin configuration — does not touch top-level vault settings, `.gitignore`, vault nickname, or MCP wiring. Idempotent — safe to re-run."
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(mkdir -p *), Bash(cp *), Bash(cp -R *), Bash(mv *), Bash(rm *), Bash(test *), Bash(ls *), Bash(stat *), Bash(date *), Bash(git rev-parse*), Bash(basename *), Bash(diff *), Bash(jq *), Bash(curl *)
---

# Configure Obsidian Vault Plugins

Install and update the curated musthave community plugins in the current project's Obsidian vault. Plugin binaries are fetched directly into the vault from GitHub releases, per plugin, only when a newer version is available. No intermediate cache folder.

**Scope is strictly plugin configuration.** This skill does not touch `app.json`, `appearance.json`, `core-plugins.json`, `hotkeys.json`, `.gitignore`, `.mcp.json`, or the vault nickname. Those are the user's concern.

## Phase 1 — Locate template and vault

Resolve plugin install path from `~/.claude/plugins/installed_plugins.json` entry `lazycortex-obsidian@lazycortex`. Template source: `<installPath>/templates/obsidian/`.

Abort with a clear message if:
- The plugin isn't enabled (no entry in `installed_plugins.json`).
- The template dir is missing (`/plugin update lazycortex-obsidian@lazycortex` needed).

Determine vault target:
- `repo_root = git rev-parse --show-toplevel` (fall back to cwd and warn if not in a git repo).
- `vault = <repo_root>/.obsidian`

Read `<template>/.lazy-obsidian.manifest.json` → `musthave` and `loadOrder` arrays. Read `<template>/plugin-settings.json` → per-plugin override blocks. Every plugin list in later phases comes from these — never hardcode names.

**Classify each musthave plugin:**
- If `<template>/plugins/<id>/` exists → **bundled** (source for binaries is the template dir; no network fetch).
- Else → **registry** (source for binaries is GitHub; Phase 3 fetches on demand).

## Phase 2 — Mode detection

- If `<vault>` does **not** exist → **greenfield**. Create `<vault>/plugins/`.
- If `<vault>` **does** exist → **audit**.

Record mode in the report.

## Phase 3 — Install or update each musthave plugin

**One pass per plugin.** For each `id` in `manifest.musthave`, update the vault directly from the effective source — only when the source version is newer than the vault version.

### 3a. Determine vault version

`mkdir -p <vault>/plugins/<id>`. Read `vault_version = jq -r '.version // ""' <vault>/plugins/<id>/manifest.json` (returns empty string if the file doesn't exist — treat as "plugin absent").

### 3b. Determine source version

**Bundled plugin** → `source_version = jq -r '.version' <template>/plugins/<id>/manifest.json`. No network.

**Registry plugin** → resolve the GitHub repo and fetch the remote `manifest.json` inline:

1. **Resolve repo from community registry.** Fetch `https://raw.githubusercontent.com/obsidianmd/obsidian-releases/master/community-plugins.json` once per run, hold in memory (the registry is ~3–4 MB; one fetch per `.config` run is fine). Find the entry `{id == <id>}` and read `repo` (e.g. `blacksmithgu/obsidian-dataview`).
   - **Not found** → skip silently. State: **not-in-registry**. Expected for custom plugins that shouldn't have been classified registry (defensive path only).
   - **Registry fetch failed** → WARN, state: **registry-unavailable**, skip all network-dependent plugins this run.
2. **Fetch remote version.**
   `source_version=$(curl -fsSL https://github.com/<repo>/releases/latest/download/manifest.json | jq -r '.version')`
   - Fetch or parse fails → WARN, state: **fetch-failed**, continue to next plugin.

### 3c. Compare and act

- `source_version` empty (network failure on a registry plugin with no prior install): state: **unreachable**, skip.
- `vault_version` empty (plugin absent from vault):
  - **Greenfield mode** → install. Go to 3d.
  - **Audit mode** → `AskUserQuestion`: **install** / **skip**. install → 3d, state **created**. skip → state **opted-out** (re-asks next run unless user removes id from vault's `community-plugins.json`).
- `source_version == vault_version` → state: **unchanged**. Skip binary copy. Phase 4 still runs (overrides are re-enforced).
- `source_version > vault_version` (treat as string compare — Obsidian plugin versions are dot-separated semver-ish; a simple `!=` with an "install if source looks newer" heuristic is sufficient, but in practice the comparison is a literal "are they the same string"): install/update, state: **updated-<vault>-to-<source>**.
- `source_version < vault_version` → WARN, state: **vault-newer**, do not overwrite.

### 3d. Install/update the plugin files

Write directly into `<vault>/plugins/<id>/`:

**Bundled plugin:**
- `cp <template>/plugins/<id>/manifest.json <vault>/plugins/<id>/manifest.json`
- `cp <template>/plugins/<id>/main.js <vault>/plugins/<id>/main.js`
- `cp <template>/plugins/<id>/styles.css <vault>/plugins/<id>/styles.css` (only if it exists in template; otherwise ensure any vault `styles.css` is removed to stay coherent).

**Registry plugin** — stream each asset straight from the release URL:
- `curl -fsSL https://github.com/<repo>/releases/latest/download/manifest.json -o <vault>/plugins/<id>/manifest.json`
- `curl -fsSL https://github.com/<repo>/releases/latest/download/main.js -o <vault>/plugins/<id>/main.js`
  - Required. If it 404s or errors, WARN, state: **fetch-failed**, revert `manifest.json` from a pre-download backup so the vault isn't left in a half-updated state.
- `curl -fsSL https://github.com/<repo>/releases/latest/download/styles.css -o <vault>/plugins/<id>/styles.css`
  - Optional. On HTTP 404, delete any existing vault `styles.css` so the vault stays coherent with upstream. Use `curl --write-out '%{http_code}'` or `curl -f` + exit-code branching to distinguish 404 from other failures.

**Pre-download backup for registry updates**: before overwriting, rename the current `<vault>/plugins/<id>/manifest.json` → `manifest.json.bak`. Delete the `.bak` on success; restore it on failure. Same pattern for `main.js` if safety is wanted; `styles.css` doesn't need a backup because its absence is a valid state.

## Phase 4 — Enforce settings overrides

**Runs every invocation, after Phase 3.** Idempotent — applies the opinionated keys from `<template>/plugin-settings.json` on top of each vault plugin's `data.json`.

For each `id` in `manifest.musthave`:

1. If the plugin ended up in state **opted-out**, **unreachable**, **not-in-registry**, or **fetch-failed** and there's no vault dir → skip.
2. Read the override block: `jq '.["<id>"] // {}' <template>/plugin-settings.json`.
   - Empty / missing / `{}` → skip. State: **no-overrides**.
3. Ensure `<vault>/plugins/<id>/data.json` exists — if absent, create it with `{}`.
4. Deep-merge our block on top of the vault file: `jq -s '.[0] * .[1]' <vault>/.../data.json <(jq '.["<id>"]' <template>/plugin-settings.json)` → write back atomically (write to `data.json.tmp`, then `mv`).
5. Compare pre-merge and post-merge content:
   - Same → state: **overrides-current**.
   - Different → state: **overrides-applied** (one or more of our keys was reset to our opinionated value).

Merge semantics: our override block wins on every key it defines, recursively. Keys we don't define (plugin defaults, user-added tweaks) are preserved. Arrays are **replaced**, not concatenated — if an override key is an array, it clobbers the vault's value for that key entirely.

## Phase 5 — Regenerate `community-plugins.json` in load order

After Phase 3, the set of plugin dirs present in `<vault>/plugins/` is known.

Build the new `community-plugins.json` as the subset of `manifest.loadOrder` whose dir exists in `<vault>/plugins/`. This preserves dependency-aware load order: dependent plugins (e.g. `folder-notes` depends on `obsidian-icon-folder`) always load after their deps.

Diff against the existing `<vault>/community-plugins.json`. If changed, show the diff and `AskUserQuestion`: **write** / **keep-current**. In greenfield mode, write silently.

## Phase 6 — Report and log

Print a structured report:

```
### setup
mode: greenfield | audit
plugin sync:
  - <id>: <created | updated-<old>-to-<new> | unchanged | vault-newer | opted-out | not-in-registry | fetch-failed | unreachable>
  - ...
settings overrides:
  - <id>: <overrides-applied | overrides-current | no-overrides>
  - ...
community-plugins.json: <created | updated | unchanged | kept-current>

### next
- open the vault in Obsidian (restart if already open — .obsidian/plugins/ changed)
- (any manual step surfaced by warnings)
```

Log the run to `./.logs/claude/lazy-obsidian.config/YYYY-MM-DD_HH-MM-SS.md` per the logging rule. Two separate steps: `Bash(mkdir -p ...)` then `Write`. Include `git_sha` and `git_branch` in frontmatter.

## Safety notes

- **Never delete** a plugin directory the user has in `<vault>/plugins/` that isn't in the manifest. Report it as **user-added** in the log and leave it alone.
- **Half-updated safety.** Phase 3d backs up `manifest.json` (and optionally `main.js`) before overwriting registry plugins. On fetch failure, restore from the backup so the vault isn't left with a mismatched version string and code.
- **Scan for credential fields** before applying overrides. If the existing vault `data.json` contains `apiKey`, `token`, `secret`, or `key` and our override block touches the same object path, WARN once before writing — user likely has real credentials there. The current `plugin-settings.json` doesn't touch any such fields; this guard is future-proofing.
- **Override curation is the user's job.** `plugin-settings.json` ships with a migration snapshot of the previous `data.json` contents. Over time, prune keys that match upstream plugin defaults — otherwise harmless churn occurs whenever the plugin bumps a default.
- **Idempotent**: re-running on a current vault produces zero mutations — Phase 3 reports **unchanged** for every id (source and vault versions match), Phase 4 reports **overrides-current** for every id, Phase 5 reports **unchanged**.
- **Dry run**: if the user passes `--dry-run`, run all phases read-only — Phase 3 still fetches the registry and remote `manifest.json` (read-only) so the report shows what *would* be downloaded; no files are written. Phase 4 computes the merge result in-memory and reports **overrides-applied** vs **overrides-current** without writing back.
