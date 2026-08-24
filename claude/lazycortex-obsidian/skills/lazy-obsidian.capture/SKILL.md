---
name: lazy-obsidian.capture
description: "Run when the operator changed this vault's Obsidian configuration and wants it recorded — new plugin installed, settings tweaked, snippet added, theme or palette changed — or asks to snapshot / capture the vault config. Writes the whole `.obsidian/` surface into the tracked `.obsidian.manifest.json` and commits it, so the config reaches other checkouts as one reviewed file. The sibling `/lazy-obsidian.deploy` rebuilds `.obsidian/` from what this skill wrote."
allowed-tools: Read, Bash(python3 *), Bash(git rev-parse*), Bash(git status*), Bash(git diff*), Bash(git add -N *), Bash(git commit *), Bash(mkdir -p *), Bash(date *), Write, AskUserQuestion, Agent
argument-hint: "[<repo-root>]"
---
# Capture the vault config into its manifest

Snapshots the current repo's Obsidian config directory into `.obsidian.manifest.json` and commits it. The manifest is the vault's configuration source of truth; `.obsidian/` itself is untracked and rebuilt by `/lazy-obsidian.deploy`.

Idempotent: re-running on an unchanged vault rewrites the same bytes and commits nothing.

## Execution discipline (MANDATORY — read before any action)

This skill has 5 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Locate the vault`
   - `Step 2 — Run the capture worker`
   - `Step 3 — Review the report`
   - `Step 4 — Commit the manifest`
   - `Step 5 — Log the run`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means the step's logic ran AND an outcome word was produced. A no-op counts only with an explicit outcome (`unchanged`, `nothing-to-commit`).
3. **Do not reach the Log step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.**
4. **The Log step is a structural verifier.** Its output MUST contain one line per task above.

## Input

Optional positional argument: the vault repo root. Omitted means the current repo.

## Step 1 — Locate the vault

- `repo_root = git rev-parse --show-toplevel` (or the passed argument).
- `test -d <repo_root>/.obsidian` — absent → **FAIL**: "No `.obsidian/` under `<repo_root>` — nothing to capture."

Outcome: `vault: <repo_root>`.

## Step 2 — Run the capture worker

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/vault_manifest.py" capture <repo_root>
```

The worker prints a JSON report and writes `<repo_root>/.obsidian.manifest.json`. A non-zero exit means the report's `errors` list is non-empty.

Outcome: `captured` or `failed: <first error>`.

## Step 3 — Review the report

Read the report and surface, in the final summary:

- `plugins` — how many plugins the manifest now carries.
- `snippets` — snippet filenames, and which are vault-owned rather than plugin-shipped.
- `theme` — the recorded theme, or `none`.
- `secrets_omitted` — **always surface this list in full when non-empty.** Each entry is a value the worker refused to record; whoever deploys this vault enters it by hand. An empty list is reported as `none`.

Then inspect what actually changed:

```
git diff --stat -- <repo_root>/.obsidian.manifest.json
```

No diff → outcome `unchanged`, skip Step 4 with outcome `nothing-to-commit`.

Outcome: `reviewed: <N> plugins, <M> snippets, <K> secrets omitted`.

## Step 4 — Commit the manifest

New file (first capture on this vault) → `git add -N <repo_root>/.obsidian.manifest.json` first, per `lazy-core.git`; never a plain `git add`.

```
git commit -m "chore(obsidian): capture vault config manifest" -- <repo_root>/.obsidian.manifest.json
```

The pathspec carries the manifest and nothing else — the operator's index is not yours.

**This skill never untracks `.obsidian/` and never edits `.gitignore`.** On a vault still tracking `.obsidian/**`, say so once in the summary and name the two commands the operator runs by hand:

```
printf '.obsidian/\n' >> <repo_root>/.gitignore
git rm -r --cached .obsidian
```

That is a one-time migration, not part of this skill's cycle.

Outcome: `committed: <sha>` or `nothing-to-commit`.

## Step 5 — Log the run

Write a run log to `./.logs/claude/lazy-obsidian.capture/` per `lazy-log.logging`.

1. `Bash(mkdir -p ./.logs/claude/lazy-obsidian.capture)`
2. Capture `git_sha` via `Bash(git rev-parse HEAD)` and `git_branch` via `Bash(git rev-parse --abbrev-ref HEAD)`; use `no-git` if either fails.
3. `Bash(date -u +%Y-%m-%d_%H-%M-%S)` → timestamp for the filename.
4. `Write` the log to `./.logs/claude/lazy-obsidian.capture/<timestamp>.md` with frontmatter `git_sha`, `git_branch`, `date`, `input`, then a `# lazy-obsidian.capture` heading, `## Actions` (one line per step with its outcome) and `## Result`.

Outcome: `logged`.

## Report

One line per task in the canonical list, with its outcome word. Secrets omitted are listed in full; an untracked-migration reminder appears only when `.obsidian/` is still tracked.

## Failure modes

- **"No `.obsidian/` under `<repo_root>`"** — the checkout has no vault config to capture. Run `/lazy-obsidian.deploy` if a manifest exists, or open the folder as a vault in Obsidian first.
- **Report lists `secrets_omitted`** — expected, not an error: an API token or password was found and deliberately not recorded. Whoever deploys the vault enters it by hand.
- **Manifest diff is huge on a vault that barely changed** — a plugin rewrote its whole settings file (schema migration on update). Read the diff before committing; the manifest is a reviewed file, that is the point of it.
