---
name: lazy-obsidian.update-plugin
description: "Run when the operator asks to install, refresh, or update a single Obsidian community plugin by id in this repo's vault, or when a vault plugin is reported as out of date. Version-aware — no-ops when the vault is already current; `--bundled` installs from the plugin's own bundled source instead of GitHub. Other skills call the `plugin-install` verb directly instead of this skill."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(git rev-parse*), Bash(test *), Bash(date *), Bash("${LAZYCORTEX_PYTHON:-python3}" *), AskUserQuestion, Agent
argument-hint: "<plugin-id> [--bundled] [--dry-run]"
---
# Install or update one Obsidian vault plugin

Installs or updates a single Obsidian community plugin into the current repo's vault at `<repo-root>/.obsidian/`, through the plugin's `plugin-install` verb. The verb is version-aware — it no-ops when the vault is already at the source's version — and re-applies the opinionated override block from `plugin-settings.json` on top of the vault plugin's `data.json` on every run, so re-running is cheap and idempotent.

## Execution discipline (MANDATORY — read before any action)

This skill has 2 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Run plugin-install`
   - `Step 2 — Report`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `unchanged`, `present`).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Input

One required argument: the plugin id (e.g. `dataview`, `obsidian-icon-folder`, `folder-notes`, `iconize-reloader`).

Optional flags:

- `--bundled` — copy the bundle shipped in this plugin's `templates/obsidian/plugins/<id>/` instead of resolving it from the community registry. Use for plugins shipped bundled inside this plugin (today: `iconize-reloader`).
- `--dry-run` — report the state tuple a real run would produce and write nothing.

## Step 1 — Run plugin-install

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-obsidian" plugin-install <id> [--bundled] [--dry-run])
```

The vault defaults to `<git toplevel>/.obsidian`. The verb prints one JSON line with `status`, `id`, `binary`, `overrides`, `community`, `warnings`, `touched_paths`, `reason`:

- Exit 0, `status: installed` → outcome **installed**; keep `binary`, `overrides`, `community`, `warnings` for Step 2.
- Exit 1, `status: refused` → outcome **refused**; the vault is left as it was. Keep `reason` for Step 2.

## Step 2 — Report

Print one structured line the caller can parse:

```
<id>: binary=<created|unchanged|updated-<A>-to-<B>|vault-newer|fetch-failed>
       overrides=<no-overrides|overrides-applied|overrides-current>
       community=<created|added|present>
```

On a refusal, `binary=fetch-failed` with the verb's `reason` on its own line, and no `overrides` / `community` values. Print every `warnings` entry as a `WARN:` line under the tuple — a cached bundle served while upstream was unreachable, a vault plugin newer than the source, credential-like values in `data.json` the override block touches.

## Failure modes

Each refusal arrives as the verb's `reason`, with `status: refused` and exit 1. Every refusal except a failed write comes before the first write, so the vault is left exactly as it was:

- **"`<id>` is not a plain plugin id; nothing written."** — the id carries a path separator or another character that would write outside the vault's plugins directory → pass the bare plugin id (e.g. `dataview`).
- **"`<path>` is not a JSON array; cannot register `<id>` safely."** — the vault's `community-plugins.json` is unreadable or holds something other than an array → open Obsidian once to let it rewrite the file, or fix the JSON by hand, then re-run.
- **"Cannot merge overrides for `<id>`: …"** — the override block in this plugin's `plugin-settings.json` or the vault plugin's `data.json` cannot be read or merged → fix the JSON the message names, then re-run.
- **"`<id>` is not bundled in `templates/obsidian/plugins/`. Remove `--bundled` …"** — `--bundled` was passed for a plugin this plugin does not ship (today only `iconize-reloader` is bundled) → re-run without `--bundled` to resolve it from the community registry.
- **"Could not fetch Obsidian community registry. Check network and retry."** — the community catalog could not be fetched and no cached copy exists → check network connectivity and retry.
- **"`<id>` not in the Obsidian community registry. …"** — the id is misspelled, or it names a plugin this plugin ships and `--bundled` was left off → check the id spelling, or re-run with `--bundled` for `iconize-reloader`.
- **"Could not fetch latest release manifest for `<id>` from `<repo>` (…). Retry."** — the release could not be fetched and no cached bundle of the plugin exists → check network connectivity and retry.
- **"Could not install `<id>` binaries (…); the vault plugin was restored from backup."** — writing the bundle into the vault failed → the previous `manifest.json`, `main.js` and `styles.css` are back and a plugin directory the run created is removed; check disk space and permissions, then retry.

A run that is not refused can still print `WARN:` lines: a cached bundle installed while upstream was unreachable, a vault plugin newer than its source left as it is (`binary=vault-newer`), and credential-like values in `data.json` objects the override block touches.

## Idempotency & safety

- **Idempotent:** re-running on a current vault produces zero mutations — `unchanged` + `overrides-current` + `present`.
- **Scope-bounded:** operates on the single `<id>` passed in. It never reads or modifies sibling plugin dirs, nor the vault's top-level settings files other than `community-plugins.json`.
- **Network-free in bundled mode:** `--bundled` makes no network call, making it safe in offline environments for plugins shipped in this LazyCortex plugin.
- The bundle source, the version comparison, the rollback on a failed write, and the refusals are the `plugin-install` verb's; this skill restates none of them.

## Callers

`/lazy-obsidian.install` (`dataview`), `/lazy-obsidian.iconize-install` (`obsidian-icon-folder`, `folder-notes`, `iconize-reloader --bundled`) and `/lazy-obsidian.diagram-install` (`mermaid-popup`) run the `plugin-install` verb directly, not this skill.
