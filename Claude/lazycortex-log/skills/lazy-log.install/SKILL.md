---
name: lazy-log.install
description: "Bootstrap the lazycortex-log plugin for the current project (or globally). Copies every rule template shipped by the plugin into the rules directory, creates docs/changelog.md if missing, and ensures .gitignore covers .logs/ and docs/changelog.md. Idempotent — safe to re-run. Detects install scope automatically."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(git rev-parse*), Bash(cp *), Bash(rm *), Bash(test *), Bash(date *)
---
# Install lazycortex-log

Bootstrap the plugin in the right scope: copy every rule template shipped by the plugin, create `docs/changelog.md`, and make sure `.gitignore` covers `.logs/`.

## Execution discipline (MANDATORY — read before any action)

This skill has 8 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Detect install scope`
   - `Step 2 — Determine paths`
   - `Step 3 — Sync rule templates`
   - `Step 4 — Create docs/changelog.md`
   - `Step 5 — Update .gitignore`
   - `Step 6 — Seed lazy.settings.json`
   - `Step 7 — Verify`
   - `Step 8 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `already-ignored`, `absent`, `skipped-per-user-choice`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1: Detect install scope

Read `~/.claude/plugins/installed_plugins.json` and find the entry for `lazycortex-log@lazycortex`. The `scope` field is either:
- `"user"` — plugin enabled globally in `~/.claude/settings.json`
- `"project"` — plugin enabled in a project's `.claude/settings.json`

If the plugin has entries at both scopes, ask the user which to target. Default: `project`.

If no entry is found, the plugin isn't actually installed — abort and tell the user to enable it first in their `settings.json`:
```json
"enabledPlugins": { "lazycortex-log@lazycortex": true }
```

## Step 2: Determine paths

Enumerate every rule file shipped by the plugin via `Glob: <installPath>/rules/*.md` — never hardcode filenames. `<installPath>` is the `installPath` field from `installed_plugins.json` for `lazycortex-log@lazycortex`.

For each source file `<installPath>/rules/<name>.md`, the rule destination by scope is:

| Scope | Rule destination | Changelog | .gitignore update |
|---|---|---|---|
| `user` | `~/.claude/rules/<name>.md` | (not created — changelog is per-repo) | (not updated) |
| `project` | `<repo-root>/.claude/rules/<name>.md` | `<repo-root>/docs/changelog.md` | `<repo-root>/.gitignore` |

Project root is `git rev-parse --show-toplevel` (or current working directory if not in a git repo — but warn the user).

If the glob returns zero files, abort and tell the user the plugin cache is empty — they likely need to run `/plugin update lazycortex-log@lazycortex` first.

## Step 3: Sync rule templates (per-rule + orphan detection)

Rules eat context on every session — the user owns the decision to install each one.

### Enumerate source and target

- Source rules: `Glob <installPath>/rules/*.md`.
- Owned namespaces: the plugin name minus the `lazycortex-` prefix (so `lazycortex-log` → `lazy-log`), plus every unique `<ns>.` prefix appearing in source rule filenames.
- Target candidates: `Glob <targetRulesDir>/<ns>.*.md` for each owned namespace. Union them.
- Ensure the destination directory exists with `mkdir -p`.

### Per-rule decision (wizard-style, one question at a time)

Every per-rule prompt MUST surface the rule's **purpose** so the user (who may not remember what a given rule file does) can make an informed decision. Extract `description:` from the rule file's frontmatter — from the **source** file for New/Drift, from the **target** file for Orphan (source is gone). If the description is longer than ~200 chars, use its first sentence. If no `description:` field exists, fall back to the first non-heading line of the body, and flag the missing-description as a WARN in the report.

For every rule name in (source ∪ target), determine its state and act:

1. **New** — target missing, source present → `AskUserQuestion` with:
   - question: ``Install rule `<name>.md`?``
   - description: ``**Purpose:** <source description>\n\n**What this does:** Copies the shipped rule into `<targetPath>`. Rules are auto-loaded into every Claude Code session (when `always_loaded`) or when editing files matching their `paths:` scope.``
   - options: **install** / **skip**.
   - Install → copy source to target, state **installed**. Skip → state **skipped**.
2. **Unchanged** — both present, byte-identical → no prompt. State **unchanged**.
3. **Drift** — both present, differ → `AskUserQuestion` with:
   - question: ``Rule `<name>.md` has drift — overwrite with shipped version?``
   - description: ``**Purpose:** <source description>\n\n**What changed:** <one-sentence summary of the diff>\n\n**Full diff:**\n```diff\n<unified diff, truncated to ~40 lines if longer>\n`````
   - options: **overwrite** / **keep-local**.
   - Overwrite → copy source to target, state **updated**. Keep-local → state **kept-local**.
4. **Orphan** — target present, source missing → `AskUserQuestion` with:
   - question: ``Rule `<name>.md` is no longer shipped by the plugin — delete from `<targetDir>`?``
   - description: ``**Purpose (from your local copy):** <target description>\n\n**Why you're seeing this:** The plugin used to ship this rule but no longer does (renamed, merged into another rule, or deprecated). Keeping it means it stays loaded into your sessions but will never receive updates.``
   - options: **delete** / **keep**.
   - Delete → `rm <target>`, state **deleted**. Keep → state **kept-orphan**.

One `AskUserQuestion` at a time — wait for the answer before the next prompt.

### Namespace-scoped deletion

Orphan detection only considers target files whose filename starts with one of this plugin's owned namespaces. Rules from other plugins and user-authored rules in unrelated namespaces are never offered for deletion.

## Step 4: Create docs/changelog.md (project scope only)

If `<repo-root>/docs/changelog.md` does not exist:

1. `mkdir -p <repo-root>/docs`
2. `Write` a seed file:
   ```markdown
   # Changelog

   Functional descriptions of changes to this repo, generated by the `lazy-log.distill` agent from `.logs/commits.jsonl`.

   The most recent changes appear at the top.

   <!-- lazy-log: last-distilled-sha = none -->
   ```

If it already exists, leave it alone.

## Step 5: Update .gitignore (project scope only)

Read `<repo-root>/.gitignore`. Ensure it covers both `.logs/` and `docs/changelog.md` — both are per-contributor local artifacts (structured commit log + distilled prose memory for the local Claude session). Add whichever is missing.

If neither is covered, append a Claude Code block:

```
# ---------------------------------------------------------------------------------------
# Claude Code logs (lazycortex-log)

.logs/
docs/changelog.md
```

If the block already exists but is missing one of the two entries, add the missing entry to it. If both are already covered (either by this block or equivalent patterns), skip.

## Step 6: Seed lazy.settings.json

Non-destructively seed the `lazycortex` domain group in `agent_models` with the four subagents this plugin ships.

### Target file

| Scope | Path |
|---|---|
| `user` | `~/.claude/lazy.settings.json` |
| `project` | `<repo-root>/.claude/lazy.settings.json` |

### Read or initialize

Read the target file. If missing or unparseable, treat its contents as `{"version": 1, "agent_models": {}}`.

### Ensure domain group exists

Ensure `agent_models.lazycortex` exists as an object (create empty `{}` if absent — never overwrite existing content, and never touch other groups).

### Seed defaults

| Dispatch string | Default model |
|---|---|
| `lazycortex-log:lazy-log.distill` | `haiku` |
| `lazycortex-log:lazy-log.timeline` | `haiku` |
| `lazycortex-log:lazy-log.recall` | `sonnet` |
| `lazycortex-log:lazy-log.summary` | `sonnet` |

Per-key semantics (write back only if anything changed):

- **absent** → add the entry with its default value. State **added**.
- **equal** → leave untouched. State **unchanged**.
- **different** → leave the user's value untouched. State **kept-local** (report value).

Never touch other `lazycortex` entries (e.g. `lazycortex-obsidian:*` seeded by `lazy-obsidian.install`).

### Write back

If any mutation happened, write the file with `version: 1` at the top.

### Report outcome

One line per seeded default: `lazycortex.<key> = <value> (<state>)`.

## Step 7: Verify

- Read back each installed rule file and confirm its `---` frontmatter parses
- If `docs/changelog.md` was created, read back its first line
- Report to the user what was done:
  - Scope detected
  - Plugin version/commit synced from: `<version>` / `<gitCommitSha>` (from `installed_plugins.json`)
  - For each rule: state (**created**, **updated**, **unchanged**, or **kept-local**) and target `<path>`
  - Changelog created at `<path>` (or "already exists")
  - .gitignore updated (or "already covers .logs/")
  - Per-key `agent_models` seed outcome from Step 6

## Step 8: Log the run

Log to `./.logs/claude/lazy-log.install/YYYY-MM-DD_HH-MM-SS.md` per the logging rule (include `git_sha` frontmatter).

Use two separate steps: `Bash(mkdir -p ...)` then `Write` tool. Never chain with `&&`.

## Notes

- **Idempotent**: running this skill multiple times is safe. Files are only created/updated when there's a real change.
- **Re-run after `/plugin update`**: `/plugin update` refreshes the plugin cache but does **not** re-sync rule files into `.claude/rules/`. Re-run this skill after every plugin update to pick up rule changes — otherwise projects keep running the old rule content.
- **Scope independence**: running at project scope does not affect other projects or the global config.
- **Next steps shown to user**: if any rule was **created** or **updated**, remind the user to restart Claude Code (rules are loaded on session start).
