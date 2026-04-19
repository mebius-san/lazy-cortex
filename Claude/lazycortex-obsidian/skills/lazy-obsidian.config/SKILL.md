---
name: lazy-obsidian.config
description: "Bootstrap or audit the current project's Obsidian vault against the plugin's curated snapshot. Greenfield mode (no .obsidian/) copies the full snapshot. Audit mode (existing .obsidian/) diffs each musthave plugin's data.json and asks per-plugin whether to overwrite, keep local, or merge missing keys. Prompts for each optional plugin, regenerates community-plugins.json in correct load order, updates .gitignore with the canonical Obsidian block, and optionally wires the obsidian-mcp server into .mcp.json. Idempotent — safe to re-run."
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(mkdir -p *), Bash(cp *), Bash(cp -R *), Bash(test *), Bash(ls *), Bash(date *), Bash(git rev-parse*), Bash(basename *), Bash(diff *), Bash(jq *)
---

# Configure Obsidian Vault

Bootstrap or audit the current project's Obsidian vault (`.obsidian/`) against the plugin's shipped snapshot. Per-plugin drift prompts. Prompts for optional plugins, vault nickname, and MCP server wiring. Every mutation is user-confirmed in audit mode.

**Never blanket-ignore `.obsidian/`.** See Phase 7 below for the canonical `.gitignore` block and the three credential-bearing plugins.

## Phase 1 — Locate template and vault

Resolve plugin install path from `~/.claude/plugins/installed_plugins.json` entry `lazycortex-obsidian@lazycortex`. Template source: `<installPath>/templates/obsidian/`.

Abort with a clear message if:
- The plugin isn't enabled (no entry in `installed_plugins.json`).
- The template dir is missing (`/plugin update lazycortex-obsidian@lazycortex` needed).

Determine vault target:
- `repo_root = git rev-parse --show-toplevel` (fall back to cwd and warn if not in a git repo).
- `vault = <repo_root>/.obsidian`

Read `<template>/.lazy-obsidian.manifest.json` → `musthave`, `optional`, `loadOrder`, `credentialBearing` arrays. Every plugin list in later phases comes from this manifest — never hardcode names.

## Phase 2 — Mode detection

- If `<vault>` does **not** exist → **greenfield**. `cp -R <template>/ <vault>/` then continue to Phase 3 with all plugins in state **created**.
- If `<vault>` **does** exist → **audit**. Continue with per-plugin/per-file comparison in later phases.

Record mode in the report.

## Phase 3 — Musthave plugin sync

For each `id` in `manifest.musthave` (order: the order in the manifest array):

1. If `<vault>/plugins/<id>/` is missing:
   - `cp -R <template>/plugins/<id> <vault>/plugins/<id>`.
   - State: **created**. No prompt.
2. Else compare `<vault>/plugins/<id>/data.json` byte-for-byte with `<template>/plugins/<id>/data.json`:
   - Both missing → state: **no-data** (rare; just verify `manifest.json` + `main.js` exist).
   - One missing → treat like drift (ask).
   - Both present & identical → state: **unchanged**.
   - Both present & differ → **drift**:
     - Show a unified diff (`diff -u <template>/... <vault>/...`).
     - `AskUserQuestion` with three options:
       - **overwrite** — `cp <template>/.../data.json <vault>/.../data.json`. State: **updated**.
       - **keep-local** — leave `<vault>` untouched. State: **kept-local**.
       - **merge-missing** — write `jq -s '.[0] * .[1]' <template>/.../data.json <vault>/.../data.json` to `<vault>/.../data.json` (snapshot keys fill in where the user has gaps; user's explicit overrides win on conflicts). State: **merged**.
   - One plugin per `AskUserQuestion` call (wizard-style per global rule — never batch).

Also sync `manifest.json` and `main.js` byte-for-byte with a single yes/no prompt per plugin if they differ, because stale plugin code is a common source of errors. Skip prompt if only `data.json` drifts.

## Phase 4 — Optional plugin prompts

For each `id` in `manifest.optional`:

- If `<vault>/plugins/<id>/` exists → handle exactly like Phase 3 (drift prompts). State tracked separately as **opt-unchanged / opt-updated / opt-kept-local / opt-merged**.
- If absent → `AskUserQuestion` (one question per plugin): **install** or **skip**.
  - install → `cp -R <template>/plugins/<id> <vault>/plugins/<id>`. State: **opt-installed**.
  - skip → no action. State: **opt-skipped**.

## Phase 5 — Regenerate `community-plugins.json` in load order

After Phases 3–4, the set of plugin dirs present in `<vault>/plugins/` is known.

Build the new `community-plugins.json` as the subset of `manifest.loadOrder` whose dir exists in `<vault>/plugins/`. This preserves dependency-aware load order: dependent plugins (e.g. `folder-notes` depends on `obsidian-icon-folder`) always load after their deps.

Diff against the existing `<vault>/community-plugins.json`. If changed, show the diff and `AskUserQuestion`: **write** / **keep-current**. In greenfield mode, write silently.

## Phase 6 — Top-level config sync

For each of these files in the snapshot, run the same byte-compare + drift-prompt flow:
`app.json`, `appearance.json`, `core-plugins.json`, `graph.json`, `hotkeys.json`, `daily-notes.json`, `bookmarks.json`, `command-palette.json`, `types.json`.

Greenfield: all written silently. Audit: diff + ask per file (overwrite / keep-local — merge-missing only offered if both files parse as JSON objects).

## Phase 7 — `.gitignore` update

**Never blanket-ignore `.obsidian/`.** That throws away themes, snippets, hotkeys, and per-plugin configs — all normal shared vault state. Use the granular block below instead.

Canonical block:

```
# ---------------------------------------------------------------------------------------
# Obsidian

# Volatile workspace state
.obsidian/workspace*

# Graph view state
.obsidian/graph.json

# Cache
.obsidian/cache/

# Vault trash
.trash/

# Plugin state files
# Most plugin data.json files contain only settings and feature state, and are
# tracked so the same config applies across machines and clones. A few plugins
# store (or have fields reserved for) API keys / tokens — those stay ignored.
.obsidian/plugins/copilot-auto-completion/data.json
.obsidian/plugins/quickadd/data.json
.obsidian/plugins/obsidian-excalidraw-plugin/data.json
```

**Credential-bearing plugins always ignored** — three community plugins store credentials in their `data.json`:

- `copilot-auto-completion` — OpenAI key in `settings.openAIApiSettings.key`
- `quickadd` — OpenAI key field (reserved; may be blank)
- `obsidian-excalidraw-plugin` — API keys for LLM-backed features

If the user un-ignores any other plugin's `data.json` in a downstream vault, they should audit it for credential fields first (scan for `apiKey`, `token`, `secret`, `key`). Surface a warning if you spot such fields during reconciliation.

Decision tree for the write:

- `<repo_root>/.gitignore` does not exist → create it with only this block. State: **created**.
- Exists and already contains `.obsidian/workspace` (any form) → already installed. State: **already-present**.
- Exists with a blanket `.obsidian/` (or `.obsidian` without trailing slash) line → replace that one line with this block. Show a preview diff and confirm. State: **replaced-blanket**.
- Exists, no `.obsidian/*` coverage → append the block. State: **appended**.

## Phase 8 — Vault nickname (prompted, no silent default)

- Compute `default = basename "$repo_root"`.
- `AskUserQuestion` with options: the `default` (marked *Recommended*) and **Other** (user supplies a custom string via notes).
- Read current `<vault>/plugins/vault-nickname/data.json` (created in Phase 3 if musthave sync ran).
- Write a new object merging: preserve every existing key (notably `overrideAppTitle`), set `nickname = <chosen>`.
  - Prefer `jq --arg n "$NICK" '. + {nickname: $n}'` over a full rewrite — preserves unknown keys the user may have added.
- State: **set-<value>**.

## Phase 9 — MCP wiring (prompted, opt-in)

- `AskUserQuestion`: "Wire the `obsidian` MCP server into this repo's `.mcp.json`?" — **yes** / **no**.
- If no: skip. State: **skipped-by-user**.
- If yes:

Canonical entry:
```json
"obsidian": {
  "command": "uvx",
  "args": ["obsidian-mcp"],
  "env": { "OBSIDIAN_VAULT_PATH": "." }
}
```

`OBSIDIAN_VAULT_PATH` **must** be `"."` — the MCP server already runs with its project dir as cwd, so `"."` resolves to the repo root for every clone. Never write a `/Users/...` or `$HOME`-expanded absolute path into tracked `.mcp.json` (global CLAUDE.md rule).

Logic (ported verbatim from `~/dotfiles/.claude/agents/obsidian.setup.md` §4):

- `<repo_root>/.mcp.json` does not exist → create it with `{"mcpServers": {"obsidian": <entry>}}`. State: **created**.
- Exists, `mcpServers.obsidian` missing → add the `obsidian` key with the canonical entry; do not touch other servers. State: **added-obsidian-entry**.
- Exists, `mcpServers.obsidian.env.OBSIDIAN_VAULT_PATH == "."` → skip. State: **already-present**.
- Exists, `mcpServers.obsidian` present but `env.OBSIDIAN_VAULT_PATH` is anything else (absolute path, empty, missing, wrong key) → correct that single field to `"."` in place; do not modify `command`, `args`, or any other field; do not touch other servers. State: **corrected-vault-path**.

Use `Edit` (not full-file `Write`) when correcting an existing file, to preserve formatting.

## Phase 10 — Report and log

Print a structured report (mirror the dotfiles agent's shape, adapted):

```
### setup
mode: greenfield | audit
musthave plugins:
  - <id>: <state>
  - ...
optional plugins:
  - <id>: <state>
  - ...
community-plugins.json: <created | updated | unchanged | kept-current>
top-level configs:
  - app.json: <state>
  - ...
.gitignore: created | appended | replaced-blanket | already-present
vault nickname: <value>
mcp.json: created | added-obsidian-entry | corrected-vault-path | already-present | skipped-by-user

### next
- open the vault in Obsidian (restart if already open — .obsidian/ changed)
- (any manual step surfaced by warnings)
```

Log the run to `./.logs/claude/lazy-obsidian.config/YYYY-MM-DD_HH-MM-SS.md` per the logging rule. Two separate steps: `Bash(mkdir -p ...)` then `Write`. Include `git_sha` and `git_branch` in frontmatter.

## Safety notes

- **Never delete** a plugin directory the user has in `<vault>/plugins/` that isn't in the snapshot. Report it as **user-added** in the log and leave it alone.
- **Never write** a `data.json` for a `credentialBearing` plugin from the snapshot unless the user explicitly picks overwrite — these files may carry secrets in the user's local copy. When offering the drift prompt for these plugins, call out the credential risk in the question text.
- **Idempotent**: re-running on an unchanged vault must produce zero prompts and report everything as **unchanged / already-present**.
- **Dry run**: if the user passes `--dry-run`, run all phases except mutations — print the plan and exit.
