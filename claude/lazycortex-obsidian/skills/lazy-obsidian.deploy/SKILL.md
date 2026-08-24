---
name: lazy-obsidian.deploy
description: "Run on a checkout whose vault config is missing or stale — a fresh clone of a vault repo, a machine that never opened this vault, a teammate setting up from the repo alone — or when the operator asks to deploy / restore / rebuild the Obsidian config. Rebuilds `.obsidian/` from the tracked `.obsidian.manifest.json`, fetching every plugin bundle at its latest release. The sibling `/lazy-obsidian.capture` is what wrote that manifest."
allowed-tools: Read, Bash(python3 *), Bash(git rev-parse*), Bash(test *), Bash(mkdir -p *), Bash(date *), Write, AskUserQuestion, Agent
argument-hint: "[<repo-root>]"
dirty-tree-waiver: "writes only into `.obsidian/`, which the manifest workflow keeps gitignored; on a vault that still tracks it, restoring the operator's own recorded config is theirs to commit"
---
# Deploy the vault config from its manifest

Rebuilds the current repo's Obsidian config directory from `.obsidian.manifest.json`: every plugin at its latest release, the captured settings on top, snippets, theme, and the top-level config files.

Never pins a version. The manifest records what a plugin was captured under, not what to install — a plugin migrates its own settings forward when Obsidian first opens it.

## Execution discipline (MANDATORY — read before any action)

This skill has 5 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Locate the manifest`
   - `Step 2 — Guard an existing vault`
   - `Step 3 — Run the deploy worker`
   - `Step 4 — Report what landed`
   - `Step 5 — Log the run`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means the step's logic ran AND an outcome word was produced.
3. **Do not reach the Log step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.**
4. **The Log step is a structural verifier.** Its output MUST contain one line per task above.

## Input

Optional positional argument: the vault repo root. Omitted means the current repo.

## Step 1 — Locate the manifest

- `repo_root = git rev-parse --show-toplevel` (or the passed argument).
- `test -f <repo_root>/.obsidian.manifest.json` — absent → **FAIL**: "No `.obsidian.manifest.json` at `<repo_root>` — run `/lazy-obsidian.capture` on a machine that has this vault configured."

Outcome: `manifest: <repo_root>/.obsidian.manifest.json`.

## Step 2 — Guard an existing vault

`test -d <repo_root>/.obsidian` — absent is the normal case (fresh checkout); proceed with outcome `fresh`.

Present means the checkout already has a configured vault, and deploy would overwrite its config files with the manifest's. Ask once via `AskUserQuestion`:

> `.obsidian/` already exists at `<repo_root>`. Deploy overwrites its config from the manifest — local changes made since the last capture are lost. Proceed?

Options: `Deploy anyway` / `Cancel`. Default is `Cancel`. On cancel, stop the skill with outcome `cancelled-by-operator` and go straight to Step 5.

Outcome: `fresh`, `overwrite-approved`, or `cancelled-by-operator`.

## Step 3 — Run the deploy worker

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/vault_manifest.py" deploy <repo_root>
```

The worker prints a JSON report. A non-zero exit means `errors` is non-empty; every error names one plugin, snippet, or theme that was skipped — the rest of the vault was still written.

The worker never touches `workspace*`, caches, obsidian-git authentication, or Iconize's own database (rebuilt from note frontmatter by `iconize-reloader`).

Outcome: `deployed` or `deployed-with-errors: <N>`.

## Step 4 — Report what landed

Surface in the final summary:

- `plugins` — one line per plugin with the source it came from: `upstream` (GitHub latest), `cache` (vendored fallback, upstream unreachable), `bundled` (shipped inside this plugin).
- `theme` — restored, already present, or the error naming a theme the operator installs from Obsidian once.
- `secrets_omitted` — **always surface this list in full when non-empty.** Each entry is a settings value the manifest deliberately does not carry: an API token, a password. Name them so the operator enters them in Obsidian by hand; nothing else will.
- `errors` — verbatim.

Then tell the operator to open Obsidian once: plugins load their settings and run their own schema migrations on first launch, which is what makes a captured-under-an-older-version snapshot land correctly.

Outcome: `reported`.

## Step 5 — Log the run

Write a run log to `./.logs/claude/lazy-obsidian.deploy/` per `lazy-log.logging`.

1. `Bash(mkdir -p ./.logs/claude/lazy-obsidian.deploy)`
2. Capture `git_sha` via `Bash(git rev-parse HEAD)` and `git_branch` via `Bash(git rev-parse --abbrev-ref HEAD)`; use `no-git` if either fails.
3. `Bash(date -u +%Y-%m-%d_%H-%M-%S)` → timestamp for the filename.
4. `Write` the log to `./.logs/claude/lazy-obsidian.deploy/<timestamp>.md` with frontmatter `git_sha`, `git_branch`, `date`, `input`, then a `# lazy-obsidian.deploy` heading, `## Actions` (one line per step with its outcome) and `## Result`.

Outcome: `logged`.

## Report

One line per task in the canonical list, with its outcome word, followed by the per-plugin source lines and any omitted secrets.

## Failure modes

- **"No `.obsidian.manifest.json`"** — this vault was never captured. Run `/lazy-obsidian.capture` where it is configured, commit, pull here, re-run.
- **A plugin reports `served from cache`** — GitHub was unreachable or the release lacked assets; the vendored copy under the user's cache was used instead. Re-run when the network is back to pull latest.
- **A plugin reports `not in the community catalog`** — it has no public catalog entry. Add a `repo` key (`owner/name`) to that plugin's entry in the manifest, or ship it bundled under the plugin's own templates.
- **A theme reports `not installed and not bundled`** — install it once from Obsidian's appearance settings; the manifest records the name, not the theme's CSS.
- **Icons and folder colours are missing after deploy** — expected: they are rebuilt by `iconize-reloader` from note frontmatter, not by this skill. Open Obsidian, or run `/lazy-obsidian.iconize-sync reconcile`.
