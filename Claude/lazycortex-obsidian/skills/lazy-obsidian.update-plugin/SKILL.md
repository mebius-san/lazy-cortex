---
name: lazy-obsidian.update-plugin
description: "Install or update a single Obsidian vault community plugin by id. Version-aware: skip if current, install if missing, update if the remote is newer. Resolves the GitHub repo via the Obsidian community registry (or reads from a bundled source in `<installPath>/templates/obsidian/plugins/<id>/` when `--bundled` is passed). Fetches `manifest.json` / `main.js` / `styles.css` with backup-safe writes. Deep-merges the opinionated override block for `<id>` from `<installPath>/templates/obsidian/plugin-settings.json` onto `<vault>/plugins/<id>/data.json`. Registers `<id>` in `<vault>/community-plugins.json`. Primitive called from `/lazy-obsidian.install` (for `dataview`) and `/lazy-obsidian.iconize-install` (for `obsidian-icon-folder`, `folder-notes`, `iconize-reloader`)."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(git rev-parse*), Bash(cp *), Bash(rm *), Bash(mv *), Bash(test *), Bash(date *), Bash(jq *), Bash(curl *), AskUserQuestion
argument-hint: "<plugin-id> [--bundled]"
---
# Install or update one Obsidian vault plugin

Primitive skill. Installs or updates a single Obsidian community plugin into the current repo's vault at `<repo-root>/.obsidian/`. Version-aware — no-ops when the vault is already at the latest version. Always re-applies the opinionated override block from `plugin-settings.json` on top of the vault plugin's `data.json`, so re-running is cheap and idempotent.

## Execution discipline (MANDATORY — read before any action)

This skill has 9 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Locate plugin install path and vault`
   - `Step 2 — Determine source version`
   - `Step 3 — Determine vault version`
   - `Step 4 — Compare and decide`
   - `Step 5 — Install/update binaries`
   - `Step 6 — Apply opinionated overrides`
   - `Step 7 — Register in community-plugins.json`
   - `Step 8 — Report`
   - `Step 9 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `already-ignored`, `absent`, `skipped-per-user-choice`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Input

One required argument: the plugin id (e.g. `dataview`, `obsidian-icon-folder`, `folder-notes`, `iconize-reloader`).

Optional flag: `--bundled` — skip the GitHub resolution and copy binaries from `<installPath>/templates/obsidian/plugins/<id>/` instead. Use for plugins shipped bundled inside this plugin (today: `iconize-reloader`).

## Step 1 — Locate plugin install path and vault

Resolve `<installPath>` from `~/.claude/plugins/installed_plugins.json` entry `lazycortex-obsidian@lazycortex`. Abort with a clear message if the plugin isn't enabled.

Determine vault:

- `repo_root = git rev-parse --show-toplevel` (fall back to cwd and WARN if not in a git repo).
- `vault = <repo_root>/.obsidian`.
- `mkdir -p <vault>/plugins/` so later phases can write safely even in greenfield vaults.

## Step 2 — Determine source version

### Registry mode (no `--bundled`)

1. Fetch the Obsidian community registry once per session (hold in memory if multiple invocations happen in the same session — the file is ~3–4 MB):
   ```
   curl -fsSL https://raw.githubusercontent.com/obsidianmd/obsidian-releases/master/community-plugins.json
   ```
   - Fetch failed → **FAIL**: "Could not fetch Obsidian community registry. Check network and retry."
2. Find the entry `{id == <id>}` and read `repo` (e.g. `blacksmithgu/obsidian-dataview`).
   - Not found → **FAIL**: "`<id>` not in the Obsidian community registry. Check the id spelling or pass `--bundled` if it's a plugin shipped by this LazyCortex plugin."
3. Fetch remote manifest:
   ```
   source_version=$(curl -fsSL https://github.com/<repo>/releases/latest/download/manifest.json | jq -r '.version')
   ```
   - Fetch or parse failed → **FAIL**: "Could not fetch latest release manifest for `<id>` from `<repo>`. Retry."

### Bundled mode (`--bundled`)

- Source dir: `<installPath>/templates/obsidian/plugins/<id>/`.
- Abort with **FAIL** if the dir doesn't exist: "`<id>` is not bundled in `templates/obsidian/plugins/`. Remove `--bundled` to resolve from the community registry instead."
- `source_version=$(jq -r '.version' <installPath>/templates/obsidian/plugins/<id>/manifest.json)`.

## Step 3 — Determine vault version

```
test -f <vault>/plugins/<id>/manifest.json \
  && vault_version=$(jq -r '.version // ""' <vault>/plugins/<id>/manifest.json) \
  || vault_version=""
```

Empty string = plugin absent from vault.

## Step 4 — Compare and decide

| Condition | Action | Report state |
|---|---|---|
| `vault_version` empty | Install → Step 5 | `created` |
| `source_version == vault_version` | Skip binary copy; continue to Step 6 (overrides still re-enforced) | `unchanged` |
| `source_version != vault_version` and source is newer | Update → Step 5 | `updated-<vault>-to-<source>` |
| `vault_version` is newer than `source_version` (rare; user manually upgraded past the template/registry) | Skip, WARN | `vault-newer` |

String inequality is sufficient for Obsidian plugin versions (dot-separated semver-ish). If you need true version-awareness later, swap in a comparator; today's callers don't need it.

## Step 5 — Install/update binaries

`mkdir -p <vault>/plugins/<id>`.

### Pre-download backup (both modes)

If `<vault>/plugins/<id>/manifest.json` exists, `mv` it aside to `manifest.json.bak`. Same for `main.js` → `main.js.bak`. `styles.css` is optional and its absence is a valid state — no backup needed.

### Registry mode

- `curl -fsSL https://github.com/<repo>/releases/latest/download/manifest.json -o <vault>/plugins/<id>/manifest.json` — required.
- `curl -fsSL https://github.com/<repo>/releases/latest/download/main.js -o <vault>/plugins/<id>/main.js` — required.
- `curl -fsSL --write-out '%{http_code}' https://github.com/<repo>/releases/latest/download/styles.css -o <vault>/plugins/<id>/styles.css` — optional. On HTTP 404, remove any pre-existing vault `styles.css` so the vault stays coherent with upstream.

### Bundled mode

- `cp <installPath>/templates/obsidian/plugins/<id>/manifest.json <vault>/plugins/<id>/manifest.json`
- `cp <installPath>/templates/obsidian/plugins/<id>/main.js <vault>/plugins/<id>/main.js`
- If `<installPath>/templates/obsidian/plugins/<id>/styles.css` exists: `cp` it. If the source has no `styles.css` but the vault has one, `rm` the vault copy so it stays coherent with the bundled source.

### Success vs failure

- Success → `rm` the `.bak` files.
- Any required download/copy failed → restore `.bak` → original names and **FAIL** with the underlying error. Leave the vault in a consistent pre-run state.

## Step 6 — Apply opinionated overrides

Read the override block for `<id>` from `<installPath>/templates/obsidian/plugin-settings.json`:

```
override=$(jq '.["<id>"] // {}' <installPath>/templates/obsidian/plugin-settings.json)
```

If the block is missing or empty (`{}`) → skip. Report state: `no-overrides`.

Otherwise, deep-merge onto the vault's `data.json`:

1. Ensure `<vault>/plugins/<id>/data.json` exists; if absent, create it with `{}`.
2. Atomic write:
   ```
   jq -s '.[0] * .[1]' \
     <vault>/plugins/<id>/data.json \
     <(jq '.["<id>"]' <installPath>/templates/obsidian/plugin-settings.json) \
     > <vault>/plugins/<id>/data.json.tmp
   mv <vault>/plugins/<id>/data.json.tmp <vault>/plugins/<id>/data.json
   ```
3. Compare pre-merge and post-merge content:
   - Same bytes → `overrides-current`.
   - Different → `overrides-applied`.

### Merge semantics

Our override block wins on every key it defines, recursively. Keys outside the block (plugin defaults, user tweaks) are preserved verbatim. Arrays are **replaced**, not concatenated — an array key in the override clobbers the vault value.

### Credential-scan guard

Before overwriting, scan the pre-merge `data.json` for `apiKey` / `token` / `secret` / `key` literals. If any exist AND the override block touches the same object path, WARN once before writing — the user likely has real credentials there. The current `plugin-settings.json` doesn't touch any such fields; this is future-proofing for when new override blocks get added.

## Step 7 — Register in `community-plugins.json`

`<vault>/community-plugins.json` is a JSON array of enabled plugin ids.

1. If the file doesn't exist → create it with `["<id>"]`. Report state: `community-plugins-created`.
2. If it exists:
   - Parse as JSON. If not an array → **FAIL** ("`<vault>/community-plugins.json` is not a JSON array; cannot register `<id>` safely.").
   - Present → report state: `community-plugins-present`.
   - Missing → append `<id>` preserving existing order, write atomically (`data.tmp` → `mv`). Report state: `community-plugins-added`.

## Step 8 — Report

Print one structured line the caller can parse:

```
<id>: binary=<created|unchanged|updated-<A>-to-<B>|vault-newer|fetch-failed>
       overrides=<no-overrides|overrides-applied|overrides-current>
       community=<created|added|present>
```

Return verbatim so chaining skills can key off the state tuple without re-parsing natural language.

## Step 9 — Log the run

Log to `./.logs/claude/lazy-obsidian.update-plugin/YYYY-MM-DD_HH-MM-SS.md` per the logging rule. Include `git_sha`, `git_branch`, and the input argument (`<id> [--bundled]`) in frontmatter. Body lists `<id>` and the final state tuple.

Two separate steps: `Bash(mkdir -p ...)` then the `Write` tool. Never chain with `&&` or use `cat > file <<'EOF'`.

## Failure modes

- **`/lazy-obsidian.update-plugin` aborts: "Could not fetch Obsidian community registry"** — the `curl` to `obsidianmd/obsidian-releases` failed → check network connectivity and retry.
- **`/lazy-obsidian.update-plugin` aborts: "`<id>` not in the Obsidian community registry"** — the plugin id is misspelled or is a bundled plugin passed without `--bundled` → verify the id against the Obsidian community plugins list, or add `--bundled` if it ships inside this plugin's templates.
- **`/lazy-obsidian.update-plugin` aborts: "Could not fetch latest release manifest for `<id>`"** — the GitHub release download failed → check network connectivity and retry; the vault is left unchanged (pre-download backups are restored).
- **`/lazy-obsidian.update-plugin` aborts: "`<id>` is not bundled in `templates/obsidian/plugins/`"** — `--bundled` was passed but the plugin's templates directory has no entry for `<id>` → remove `--bundled` to resolve from the community registry, or check that the plugin cache is current (`/plugin update lazycortex-obsidian@lazycortex`).
- **`/lazy-obsidian.update-plugin` aborts with binary download failure** — a required file (`manifest.json` or `main.js`) could not be downloaded → the vault is restored to its pre-run state via `.bak` files; check network connectivity and retry.
- **`/lazy-obsidian.update-plugin` aborts: "`community-plugins.json` is not a JSON array"** — the vault's `community-plugins.json` is corrupt → open Obsidian once to let it repair the file, or fix the JSON manually, then re-run.

## Idempotency & safety

- **Idempotent:** re-running on a current vault produces zero mutations — `unchanged` + `overrides-current` + `community-plugins-present`.
- **Backup-safe:** pre-download `.bak` files guarantee the vault is never left half-updated on a fetch failure.
- **Scope-bounded:** this skill operates on the single `<id>` passed in. It never reads or modifies sibling plugin dirs, nor the vault's top-level settings files (`app.json`, `appearance.json`, etc.).
- **Network-free in bundled mode:** `--bundled` skips all `curl` calls, making it safe to invoke in offline environments for plugins shipped in this LazyCortex plugin.

## Dry run

If the user passes `--dry-run` alongside the id, run Steps 1–4 (reads only) plus the Step 6 merge in-memory (no write). Print the state tuple that *would* be reported and exit without mutation.

## Callers

- `/lazy-obsidian.install` — calls `update-plugin dataview` at project scope to install Dataview for tag-page `Index` rendering.
- `/lazy-obsidian.iconize-install` — calls three times: `obsidian-icon-folder`, `folder-notes`, and `iconize-reloader --bundled`. The first two are registry plugins; the reloader ships bundled in this plugin's templates.
