---
name: lazy-core.install
description: "Bootstrap the lazycortex-core plugin for the current project (or globally). Copies every rule template shipped by the plugin into the rules directory, syncs authoring templates into `.claude/templates/core/`, bootstraps the scaffold registry, seeds runtime defaults, and offers expert wizard and daemon supervisor setup. Idempotent — safe to re-run. Detects install scope automatically."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(git rev-parse*), Bash(git init*), Bash(cp *), Bash(rm *), Bash(test *), Bash(date *), Bash(diff *), Bash(chmod *), Bash(launchctl *), Bash(systemctl *), Bash(python3 *)
---
# Install lazycortex-core

Bootstrap the plugin in the right scope: copy every rule template shipped by the plugin into the target `rules/` directory, sync authoring templates into the consumer's `templates/core/` directory, and ensure the scaffold registry is in place.

## Execution discipline (MANDATORY — read before any action)

This skill has 16 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 0 — Verify Python ≥ 3.12 (floor)`
   - `Step 1 — Detect install scope`
   - `Step 2 — Determine paths`
   - `Step 3 — Sync rule templates`
   - `Step 4 — Sync authoring templates`
   - `Step 5 — Verify`
   - `Step 6 — Seed lazy.settings.json`
   - `Step 7 — Bootstrap .logs/ directory`
   - `Step 8 — Migrate stale lazycortex-log hook registrations`
   - `Step 9 — Bootstrap runtime defaults`
   - `Step 10 — Bootstrap experts directory`
   - `Step 10.5 — Bootstrap .memory/ directory`
   - `Step 11 — Expert-add wizard`
   - `Step 12 — Bootstrap expert-pump routine`
   - `Step 13 — Offer daemon supervisor install`
   - `Step 14 — Report`
   - `Step 15 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `already-ignored`, `absent`, `skipped-per-user-choice`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 0: Verify Python ≥ 3.12 (floor)

Every plugin in this marketplace requires Python ≥ 3.12. This step runs first; on a machine that already meets the floor it is silent (one `python3 -V` invocation) and the install proceeds straight to Step 1. Per-plugin `<ns>.install` skills inherit this gate — they do NOT re-probe.

Run `Bash(python3 -V)` and parse the version. If `python3` is missing or the version is below `3.12.0`, walk the user through install via `AskUserQuestion`:

```
AskUserQuestion:
  question: "Python 3.12+ is required (found `<detected version or 'not found'>`). How would you like to install it?"
  description: "All LazyCortex plugins target Python 3.12 as a single floor. Pick the route that matches this machine; once Python is upgraded, re-run `/lazy-core.install`."
  options:
    - "macOS — `brew install python@3.12 && brew link python@3.12 --force`"
    - "Linux / cross-platform — `pyenv install 3.12 && pyenv global 3.12`"
    - "Skip — abort install"
```

On macOS / Linux options: print the corresponding command for the user to run in their own shell — do NOT execute it (this skill never installs system packages on the user's behalf). Then state outcome `awaiting-user-install` and abort the run; the user re-runs `/lazy-core.install` once the upgrade lands.

On `Skip — abort install`: state outcome `aborted-python-floor-not-met` and exit with the message `Python 3.12+ required — re-run /lazy-core.install once installed.`. Skip Steps 1–15.

If `python3 -V` reports ≥ 3.12.0: state outcome `python-floor-ok (<version>)` and proceed to Step 1.

When raising the floor in the future, bump this step's numeric threshold in the same edit as any other floor-bearing reference.

## Step 1: Detect install scope

Read `~/.claude/plugins/installed_plugins.json` and find the entry for `lazycortex-core@lazycortex`. The `scope` field is either:
- `"user"` — plugin enabled globally in `~/.claude/settings.json`
- `"project"` — plugin enabled in a project's `.claude/settings.json`

If the plugin has entries at both scopes, ask the user which to target. Default: `project`.

If no entry is found, the plugin isn't actually installed — abort and tell the user to enable it first in their `settings.json`:
```json
"enabledPlugins": { "lazycortex-core@lazycortex": true }
```

## Step 2: Determine paths

Enumerate every rule file shipped by the plugin via `Glob: <installPath>/rules/*.md` — never hardcode filenames. `<installPath>` is the `installPath` field from `installed_plugins.json`.

For each source file `<installPath>/rules/<name>.md`, the target is:

| Scope | Rule destination | Templates destination |
|---|---|---|
| `user` | `~/.claude/rules/<name>.md` | `~/.claude/templates/core/` |
| `project` | `<repo-root>/.claude/rules/<name>.md` | `<repo-root>/.claude/templates/core/` |

Project root is `git rev-parse --show-toplevel` (or current working directory if not in a git repo — warn the user).

If the glob returns zero files, abort and tell the user the plugin cache is empty — they likely need to run `/plugin update lazycortex-core@lazycortex` first.

## Step 3: Sync rule templates (per-rule + orphan detection)

Rules eat context on every session — the user owns the decision to install each one.

### Enumerate source and target

- Source rules: `Glob <installPath>/rules/*.md`.
- Owned namespaces: the plugin name minus the `lazycortex-` prefix (so `lazycortex-core` → `lazy-core`), plus every unique `<ns>.` prefix appearing in source rule filenames (for this plugin that includes both `lazy-core` and `lazy-guard`).
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
   - description: ``**Purpose:** <source description>\n\n**What changed:** <one-sentence summary of the diff — e.g. \"source removes a blank line and lowercases `Claude/**` → `claude/**` in an example\">\n\n**Full diff:**\n```diff\n<unified diff, truncated to ~40 lines if longer>\n`````
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

## Step 4: Sync authoring templates

The plugin ships authoring templates under `<installPath>/templates/core/` that other plugins and customer-authored scaffolds reference via `.claude/templates/core/...`. Sync them into the consumer scope so the scaffold registry's paths resolve.

### Enumerate

- Source: `Glob <installPath>/templates/core/*.md`. If empty, abort the step with outcome `absent` (the plugin cache is broken).
- Target dir: `<consumerScope>/templates/core/` (where `<consumerScope>` is `~/.claude/` for user scope, `<repo-root>/.claude/` for project scope).
- Ensure target dir exists with `mkdir -p`.

### Per-template decision

For each source template, compute state and act:

1. **New** — target missing → copy source to target. State **installed**.
2. **Unchanged** — both present, byte-identical (`diff -q`) → no action. State **unchanged**.
3. **Drift** — both present, differ → `AskUserQuestion`:
   - question: ``Template `<name>` has drift — overwrite with shipped version?``
   - description: ``**What this is:** `.claude/templates/core/<name>` is referenced by `lazy-core.scaffold` for new artifact authoring.\n\n**Full diff:**\n```diff\n<unified diff, truncated to ~40 lines if longer>\n`````
   - options: **overwrite** / **keep-local**.
   - Overwrite → copy source to target, state **updated**. Keep-local → state **kept-local**.

No orphan detection — the plugin owns the `core/` group exclusively, but customer-edited copies are valid keep-local outcomes.

### Outcome

One line per template: `<name>: <state> → <targetPath>`.

## Step 5: Verify

For each installed rule file:

- Read it back and confirm its `---` frontmatter parses
- Confirm the file is under 3 KB (per the `lazy-core.doctor` rule-size threshold)

## Step 6: Seed lazy.settings.json

Non-destructively seed the `agent_models` section with the three built-in subagents and create empty reserved slots for user- and project-authored agents.

### Target file

| Scope | Path |
|---|---|
| `user` | `~/.claude/lazy.settings.json` |
| `project` | `<repo-root>/.claude/lazy.settings.json` |

### Read or initialize

Read the target file. If missing or unparseable, treat its contents as `{"version": 1, "agent_models": {}}`.

### Ensure reserved groups exist

Ensure `agent_models._builtin`, `agent_models._user`, and `agent_models._project` exist as objects (create empty `{}` if absent — never overwrite existing content).

### Seed `_builtin` defaults

Pull tier values from `${CLAUDE_PLUGIN_ROOT}/skills/lazy-core.agent-models/default-tiers.json` — single source of truth for both this seed step and the `lazy-core.agent-models` wizard. Select every entry under `defaults` whose key matches the built-in dispatch set `{Explore, Plan, general-purpose, statusline-setup}` (bare names with no `:`). Those are the entries to seed under `_builtin`, key + tier verbatim from the JSON.

If `default-tiers.json` is missing or unparseable → FAIL with `default-tiers.json missing or invalid at <path>; reinstall lazycortex-core`. Don't fall back to hardcoded values — silent drift between this seed and the wizard's "accept all template defaults" batch is exactly what the SOT is meant to prevent.

Per-key semantics (write back only if anything changed):

- **absent** in `agent_models._builtin` → add the entry with the JSON's tier. State **added**.
- **equal** → leave untouched. State **unchanged**.
- **different** → leave the user's value untouched. State **kept-local** (report user's value alongside the JSON's).

Never touch `_user` or `_project` entries — those slots are filled interactively by `lazy-core.agent-models`.

### Pre-write context (MANDATORY before Write)

Before calling `Write` on a **newly-created** file (target was missing or unparseable), print this explanation in the conversation so the subsequent permission prompt has context above it:

> Creating `<targetPath>` at **<scope>** scope (`user` = `~/.claude/lazy.settings.json` applies to every project; `project` = `<repo-root>/.claude/lazy.settings.json` applies to this repo only).
>
> This file routes subagent dispatches to model tiers (`haiku` / `sonnet` / `opus` / `default`). Structure:
> - `_builtin` — defaults for the three built-in subagent types (seeded now).
> - `_user` — your globally-authored agents (filled later by `/lazy-core.agent-models`, writes to the global file).
> - `_project` — this project's agents (filled later by `/lazy-core.agent-models`, writes to the project file).
>
> **Routing rule**: `/lazy-core.agent-models` auto-routes by group — `_user.*` → global file, `_project.*` → project file, plugin-domain groups → the plugin's own install scope. Override with `--scope=project|global` for deliberate deviations.
>
> **Scope precedence when both files exist**: reads merge with **project wins per-group** — a duplicate group in the project file shadows the global file's copy.
>
> The file looks mostly empty because `_user` / `_project` are reserved slots waiting for `/lazy-core.agent-models` to populate them based on the agents you actually have.

For **existing files** (mutations to an already-present file), print a one-line context instead: `Updating <targetPath>: <N> _builtin default(s) added.` No permission prompt is expected for in-place edits the user already owns, but the context line keeps the report grounded.

### Write back

If any mutation happened, write the file with `version: 1` at the top. Preserve existing groups (plugin-domain groups like `lazycortex`, third-party groups, etc.) verbatim.

### Report outcome

One line per seeded default: `_builtin.<key> = <value> (<state>)`. Plus `_user`, `_project`: `created (empty)` if new, `unchanged` otherwise.

## Step 7: Bootstrap .logs/ directory

Create `.logs/` at the repo root and ensure `.gitignore` covers it. `.logs/` is gitignored runtime state: daemon output, recall logs, and the commit-recorder feed. This step runs unconditionally (it is not gated on runtime-setup confirmation) and is absorbed from the retired `lazy-log.install` skill.

Run via:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from pathlib import Path
from lazy_install_phases import bootstrap_logs_dir
print(bootstrap_logs_dir(Path('.')))
")
```

Outcome: `bootstrapped` (dir created and/or `.gitignore` updated) or `already-present` (both existed).

## Step 8: Migrate stale lazycortex-log hook registrations

The `lazycortex-log` plugin was retired and folded into `lazycortex-core`. Its `hooks/lazy-log.commit-recorder.py` was registered under `${CLAUDE_PLUGIN_ROOT}/lazycortex-log/hooks/` in consumer `settings.json` files. This step strips those stale registrations from the four standard settings paths so the retired plugin path no longer appears in the consumer's hook pipeline.

Run via:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from pathlib import Path
from lazy_install_phases import migrate_log_hooks
for p in [Path('.claude/settings.json'),
          Path('.claude/settings.local.json'),
          Path.home() / '.claude/settings.json',
          Path.home() / '.claude/settings.local.json']:
    print(f'{p}: {migrate_log_hooks(p)}')
")
```

Idempotent: a second run on already-clean files is a no-op. Report one line per path with its outcome word (`migrated` or `no-stale-entries`).

## Step 9: Bootstrap runtime defaults

Steps 9–13 set up the per-repo runtime layer (`.experts/`, expert wizard, daemon supervisor). They operate on the **current working repo**, independent of the plugin's install scope — runtime artifacts are always per-repo, even when the plugin is installed at user scope.

For Steps 9–13, `<repo-root>` is the cwd's git toplevel (resolved or initialized in 9a below), even if Step 1 detected install scope as `user`.

### 9a. Resolve the runtime repo

Run `git rev-parse --show-toplevel` in cwd:

- If it succeeds, set `<repo-root>` to the returned path and proceed to 9b.
- If it fails (cwd is not inside a git repo), ask:

  ```
  AskUserQuestion:
    question: "Current directory is not a git repository. Initialize one here to enable runtime/experts setup?"
    description: "Runtime artifacts (`.experts/`, daemon supervisor units) need a repo root. Initializing here means git-tracking your runtime config alongside the rest of the directory; skipping bypasses runtime/experts setup for this run — Steps 3–8 are unaffected."
    options: ["Initialize git here", "Skip — no runtime setup"]
  ```

  - On `Initialize git here`: run `Bash(git init)` in cwd, then set `<repo-root>` to cwd. Proceed to 9b.
  - On `Skip — no runtime setup`: mark Steps 9–13 with outcome `skipped-not-in-git-repo`, skip to Step 14.

### 9b. Confirm runtime setup

Ask once:

```
AskUserQuestion:
  question: "Bootstrap runtime/experts for this repo at `<repo-root>`?"
  description: "Sets up `lazy.settings.json[experts]`, `.claude/bin/lazy.runtime.sh` shim, the `lazy-core.runtime` block in `.claude/lazy.settings.json`, plus the expert-add wizard and optional daemon supervisor. Skip if you don't need this in this repo yet — the rest of the install is unaffected and you can re-run `/lazy-core.install` later."
  options: ["Yes", "Skip — this repo doesn't need runtime/experts"]
```

- On `Skip — this repo doesn't need runtime/experts`: mark Steps 9–13 with outcome `skipped-per-user-choice`, skip to Step 14.
- On `Yes`: continue with 9c below and run Steps 10–13.

### 9c. Write `lazy-core.runtime`

Read `<repo-root>/.claude/lazy.settings.json`. If the top-level key `lazy-core.runtime` is absent, add it by running:

```bash
PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from lazy_settings import save_section
from pathlib import Path
save_section(
    Path('<repo-root>/.claude/lazy.settings.json'),
    'lazy-core.runtime',
    {
        '_version': 1,
        'daemon': {
            'git': None,
            'polling_interval_sec': 5,
            'cleanup_completed_after': '7d',
            'cleanup_failed_after': '30d',
            'cleanup_dead_after': '7d'
        },
        'routines': {}
    }
)
"
```

State **bootstrapped** if the section was absent and was written; **already-present** if it already existed (do NOT overwrite); **skipped-not-in-git-repo** or **skipped-per-user-choice** if 9a/9b chose to skip.

## Step 10: Bootstrap experts directory

If Step 9 was skipped (outcome `skipped-not-in-git-repo` or `skipped-per-user-choice`), inherit the same outcome and skip this step.

Otherwise, perform the following three idempotent operations:

### Ensure `lazy.runtime.sh` shim

Check whether `<repo-root>/.claude/bin/lazy.runtime.sh` exists (`Bash(test -f ...)`). If missing:
1. `Bash(mkdir -p <repo-root>/.claude/bin/)`
2. `Bash(cp ${CLAUDE_PLUGIN_ROOT}/templates/runtime/lazy.runtime.sh <repo-root>/.claude/bin/lazy.runtime.sh)`
3. `Bash(chmod +x <repo-root>/.claude/bin/lazy.runtime.sh)`

The shim resolves the latest `lazycortex-core/bin/runner` from the plugin cache at exec time, so supervisor units don't need re-rendering after `/plugin update`.

State **created** if copied; **already-present** if it existed.

### Ensure `lazy.settings.json[experts]`

Check whether the `experts` section exists in `<repo-root>/.claude/lazy.settings.json`. If missing, write it with content `{"_version": 1}` via `lazy_settings.save_section`.

State **created** if written; **already-present** if it existed.

### Ensure `.gitignore` entries

Read `<repo-root>/.gitignore` (or treat as empty if missing). Ensure it contains both of the following lines:
- `.experts/.jobs/`
- `.logs/lazy-core/runtime/`

If either line is absent, append all missing lines to `.gitignore` with `Edit` (or `Write` if the file was missing). State **updated** if any line was appended; **already-present** if both were already there.

## Step 10.5: Bootstrap .memory/ directory

If Step 9 was skipped (outcome `skipped-not-in-git-repo` or `skipped-per-user-choice`), inherit the same outcome and skip this step.

Otherwise, ensure `.memory/` exists and is **un-ignored** in `.gitignore` so memory notes are tracked in git (per `Spec §8.1`):

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from pathlib import Path
from lazy_install_phases import bootstrap_memory_dir
print(bootstrap_memory_dir(Path('.')))
")
```

Outcome: `bootstrapped` (dir created and/or `.gitignore` updated) or `already-present` (both existed).

## Step 11: Expert-add wizard

If Step 9 was skipped (outcome `skipped-not-in-git-repo` or `skipped-per-user-choice`), inherit the same outcome and skip this step.

Otherwise, ask the user once:

```
AskUserQuestion:
  question: "Scan installed plugins for expert candidates to register in this repo?"
  options: ["Yes", "Skip — I'll do this later"]
```

On `Skip — I'll do this later`, state **skipped-per-user-choice** and move to Step 12.

On `Yes`, run the wizard:

### 1. Discover candidates

Glob for agent files containing `expert_protocol:` frontmatter at three scopes. For the plugin cache, resolve the latest version per plugin via lexicographic sort on the version directory:

- `~/.claude/plugins/cache/*/*/` — list subdirectories, take the lexicographically last one as latest version, then glob `<latest-version>/agents/*.md`
- `~/.claude/agents/*.md`
- `<repo-root>/.claude/agents/*.md`

For each candidate file, `Read` its frontmatter. If `expert_protocol:` is present, record:
- `source_scope`: `plugin-cache`, `user`, or `project`
- `plugin` (from the cache directory structure, or `user`/`project` for the latter two scopes)
- `agent_name`: the basename of the file without `.md`
- `expert_protocol_ref`: the value of `expert_protocol:` (a protocol reference string)

Resolve the protocol file via:

```bash
PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from reference_resolver import resolve_reference
from pathlib import Path
ref = '<expert_protocol_ref>'
resolved = resolve_reference(ref, base_path=Path('<repo-root>'))
print(resolved)
"
```

If `resolve_reference` raises an exception or returns `None`, skip that candidate and record it in the report as `protocol-unresolvable`.

If no candidates are found after scanning all three scopes, state **no-candidates** and proceed to Step 12.

### 2. Filter already-registered candidates

Load the `experts` section of `<repo-root>/.claude/lazy.settings.json` (via `lazy_settings.load_section`). Skip any candidate whose `agent_name` already appears as a key in the section (besides `_version`).

If all candidates are filtered out, state **all-already-registered** and proceed to Step 12.

### 3. Present each candidate one at a time

For each remaining candidate, ask:

```
AskUserQuestion:
  question: "Install expert candidate `<plugin>:<agent_name>` (protocol `<expert_protocol_ref>`)?"
  options: ["Yes", "Skip", "Stop wizard"]
```

On `Skip`: move to the next candidate.
On `Stop wizard`: stop iterating; proceed to Step 12 with whatever was accepted so far.
On `Yes`: ask for the three fields below (one `AskUserQuestion` each, strictly in sequence):

**a.** Local name for this expert in the project:
```
AskUserQuestion:
  question: "Local name for this expert in the project?"
  description: "Default: <agent_name>"
  options: ["<agent_name> (default)", "Enter custom name"]
```
If `<agent_name> (default)` is chosen, use `agent_name` as the local name. If `Enter custom name`, prompt once more with a free-text question for the name.

**b.** Git author name:
```
AskUserQuestion:
  question: "git_author.name for commits this expert makes?"
  description: "Default: <output of `git config user.name`>"
  options: ["<git config user.name> (default)", "Enter custom name"]
```
Use default if chosen; otherwise prompt once more.

**c.** Git author email:
```
AskUserQuestion:
  question: "git_author.email for commits this expert makes?"
  description: "Default: <output of `git config user.email`>"
  options: ["<git config user.email> (default)", "Enter custom email"]
```
Use default if chosen; otherwise prompt once more.

### 4. Write accepted candidates to `lazy.settings.json[experts]`

For each accepted candidate, merge the new entry via:

```bash
PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from pathlib import Path
from lazy_settings import load_section, save_section
p = Path('<repo-root>/.claude/lazy.settings.json')
section = load_section(p, 'experts')
section['<local_name>'] = {
    'agent': '<plugin>:<agent_name>',
    'git_author': {'name': '<author_name>', 'email': '<author_email>'}
}
save_section(p, 'experts', section)
"
```

State one line per candidate: `<local_name>: registered` or `skipped`.

## Step 12: Bootstrap expert-pump routine

If Step 9 was skipped (outcome `skipped-not-in-git-repo` or `skipped-per-user-choice`), inherit the same outcome and skip this step.

Otherwise, check two conditions:
1. The `experts` section of `<repo-root>/.claude/lazy.settings.json` contains at least one expert entry (a key that is not `_version` and whose value is a dict).
2. `lazy.settings.json[lazy-core.runtime].routines` does NOT already contain a key `lazy-expert.pump`.

If both conditions are true, run:

```bash
PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from expert_runtime import bootstrap_default_routines
from pathlib import Path
bootstrap_default_routines(Path('<repo-root>'))
"
```

State **registered** if the routine was added; **already-present** if it was already there; **skipped-no-experts** if condition 1 was false.

## Step 13: Offer daemon supervisor install

If Step 9 was skipped (outcome `skipped-not-in-git-repo` or `skipped-per-user-choice`), inherit the same outcome and skip this step.

Otherwise, only proceed if Step 12 produced outcome **registered** (i.e., the expert-pump routine was freshly added — there is something to drain). If Step 12 was **already-present** or **skipped-no-experts**, state **skipped-no-pump** and move on.

Ask:

```
AskUserQuestion:
  question: "Install a daemon supervisor to run the expert-pump routine automatically?"
  options: ["macOS launchd", "Linux systemd", "Skip — I'll start the daemon manually"]
```

On `Skip — I'll start the daemon manually`: state **skipped-per-user-choice**.

On `macOS launchd`:
1. Read `${CLAUDE_PLUGIN_ROOT}/templates/runtime/com.lazycortex.runtime.plist`.
2. Substitute `{REPO_ROOT}` → absolute path of `<repo-root>`, `{REPO_NAME}` → basename of `<repo-root>` (the shim path is built into the templates as `{REPO_ROOT}/.claude/bin/lazy.runtime.sh` — no separate runner-path substitution needed).
3. `Bash(mkdir -p ~/Library/LaunchAgents/)`
4. Write the rendered plist to `~/Library/LaunchAgents/com.lazycortex.runtime.<REPO_NAME>.plist`.
5. `Bash(launchctl load ~/Library/LaunchAgents/com.lazycortex.runtime.<REPO_NAME>.plist)`
6. State **launchd-installed**.

On `Linux systemd`:
1. Read `${CLAUDE_PLUGIN_ROOT}/templates/runtime/lazy-core-runtime.service`.
2. Substitute `{REPO_ROOT}` and `{REPO_NAME}` as above.
3. `Bash(mkdir -p ~/.config/systemd/user/)`
4. Write the rendered unit to `~/.config/systemd/user/lazy-core-runtime-<REPO_NAME>.service`.
5. `Bash(systemctl --user enable --now lazy-core-runtime-<REPO_NAME>.service)`
6. State **systemd-installed**.

## Step 14: Report

Report to the user:
- Python version probe outcome (Step 0)
- Scope detected (user vs project)
- Plugin version/commit synced from: `<version>` / `<gitCommitSha>` (from `installed_plugins.json`)
- For each rule: state (**created**, **updated**, **unchanged**, or **kept-local**) and target `<path>`
- For each authoring template: state and target `<path>` (Step 4)
- Per-key `agent_models` seed outcome from Step 6
- `.logs/` directory bootstrap outcome (Step 7)
- Hook migration outcome (Step 8): one line per settings path (`migrated` or `no-stale-entries`)
- Runtime bootstrap outcome (Step 9)
- Experts directory bootstrap outcome (Step 10)
- `.memory/` directory bootstrap outcome (Step 10.5)
- Expert-add wizard outcome (Step 11)
- Expert-pump routine registration outcome (Step 12)
- Daemon supervisor install outcome (Step 13)

## Step 15: Log the run

Log to `./.logs/claude/lazy-core.install/YYYY-MM-DD_HH-MM-SS.md` per the logging rule (include `git_sha` frontmatter).

Use two separate steps: `Bash(mkdir -p ...)` then the `Write` tool. Never chain with `&&` or use `cat > file <<'EOF'`.

## Failure modes

- **`/lazy-core.install` aborts: "plugin isn't actually installed — enable it first"** — `lazycortex-core@lazycortex` is missing from `enabledPlugins` in `~/.claude/settings.json`, or the marketplace entry for `lazycortex` is absent from `extraKnownMarketplaces` → add both blocks to `~/.claude/settings.json`, restart Claude Code, then re-run.
- **`/lazy-core.install` aborts: "plugin cache is empty — run `/plugin update` first"** — the rule glob under the plugin's `installPath` returned zero files → run `/plugin update lazycortex-core@lazycortex` to refresh the cache, then re-run.
- **Step 4 aborts: "plugin cache is broken" (templates directory empty)** — the `templates/core/` directory inside the plugin cache is missing or empty → run `/plugin update lazycortex-core@lazycortex`, then re-run.
- **Step 6 fails: "default-tiers.json missing or invalid"** — `lazy-core.agent-models/default-tiers.json` cannot be read or parsed → reinstall `lazycortex-core` to restore the file, then re-run.
- **Step 7 fails: `.logs/` not a directory** — a file named `.logs` already exists at the repo root → remove or rename it, then re-run.
- **Step 7 fails: `.gitignore` unwritable** — `bootstrap_logs_dir` raised a permission or I/O error → check permissions on the repo root, then re-run.
- **Step 8 fails: settings.json malformed JSON** — one of the four standard settings paths contains invalid JSON → fix the file manually, then re-run.
- **Step 9 fails: settings file unwritable** — `lazy_settings.save_section` raises a permission or I/O error when writing `lazy-core.runtime` into `.claude/lazy.settings.json` → check file permissions on `.claude/lazy.settings.json` and the `.claude/` directory, then re-run.
- **Step 11 wizard: "no candidates found"** — no agent files with `expert_protocol:` frontmatter were found under any of the three discovery scopes → no experts are available to register; the wizard skips automatically.
- **Step 11 wizard: frontmatter parse failure** — a candidate agent file's frontmatter is malformed YAML → the candidate is skipped and flagged in the report as `parse-error`; fix the frontmatter manually and re-run `/lazy-core.install` to pick it up.
- **Step 11 wizard: protocol reference unresolvable** — `reference_resolver.resolve_reference` returns `None` or raises for a candidate's `expert_protocol:` value → the candidate is skipped and flagged as `protocol-unresolvable`; verify the protocol file exists at the referenced path or reinstall the owning plugin.
- **Step 13 fails: supervisor template not found** — `${CLAUDE_PLUGIN_ROOT}/templates/runtime/com.lazycortex.runtime.plist` or `lazy-core-runtime.service` is missing from the plugin cache → run `/plugin update lazycortex-core@lazycortex` to restore templates, then re-run.
- **Step 13 fails: `launchctl load` error** — the plist was written but `launchctl load` returned a non-zero exit code → inspect the plist at `~/Library/LaunchAgents/` for substitution errors, then run `launchctl load <path>` manually.
- **Step 13 fails: `systemctl --user enable --now` error** — the service unit was written but `systemctl` returned a non-zero exit code → run `systemctl --user status lazy-core-runtime-<REPO_NAME>.service` to inspect the error, then correct and re-enable manually.

## Notes

- **Idempotent**: running this skill multiple times is safe. Files are only created/updated when there's a real change.
- **Re-run after `/plugin update`**: `/plugin update` refreshes the plugin cache but does **not** re-sync rule files into `.claude/rules/`. Re-run this skill after every plugin update to pick up rule changes — otherwise projects keep running the old rule content.
- **Scope independence**: running at project scope does not affect other projects or the global config.
- **Runtime is per-repo, not per-scope**: Steps 3–8 follow the plugin's install scope (`user` writes to `~/.claude/`, `project` writes to `<repo-root>/.claude/`). Steps 9–13 always target the current working repo (cwd's git toplevel) regardless of install scope, because runtime artifacts (`.experts/`, daemon supervisor units) are inherently per-repo. Run `/lazy-core.install` from inside each repo where you want runtime to be set up.
- **Re-run after `git clone`**: rules/templates/`lazy.settings.json`/`lazy.runtime.sh` are committed into the repo, but the daemon supervisor units (launchd plist / systemd service) are per-user and not in the repo. Re-run this skill after cloning to install the supervisor for the current machine and to pick up any newer plugin shipped versions. Pick `Skip — no runtime setup` in 9a or `Skip — this repo doesn't need runtime/experts` in 9b if you don't want runtime in this repo at all.
- **Next steps shown to user**: if any rule was **created** or **updated**, remind the user to restart Claude Code (rules are loaded on session start).
