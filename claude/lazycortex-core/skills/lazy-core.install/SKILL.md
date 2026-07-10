---
name: lazy-core.install
description: "Bootstrap the lazycortex-core plugin for the current project (or globally). Copies every rule template shipped by the plugin into the rules directory, syncs authoring templates into `.claude/templates/core/`, bootstraps the scaffold registry, seeds runtime defaults, registers experts (always — they are dispatch-routing config, not daemon-only), and — behind two remembered gates (project-level `daemon.enabled`, per-checkout `daemon.run_here`) — sets up the daemon routines + supervisor. Idempotent and quiet on re-run — every decision is persisted and never re-asked; an enabled plugin installs its whole surface. Detects install scope automatically."
allowed-tools: Read, Write, Edit, Glob, AskUserQuestion, TaskCreate, TaskUpdate, TaskList, TaskGet, Skill, Bash(mkdir -p *), Bash(git rev-parse*), Bash(git init*), Bash(cp *), Bash(rm *), Bash(test *), Bash(find *), Bash(date *), Bash(diff *), Bash(chmod *), Bash(launchctl *), Bash(systemctl *), Bash(python3 *)
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
   - `Step 7 — Bootstrap .logs/, .runtime/, lazy.settings.local.json gitignore, and .lazyignore`
   - `Step 8 — Migrate stale lazycortex-log hook registrations`
   - `Step 9 — Bootstrap runtime defaults`
   - `Step 10 — Bootstrap experts directory`
   - `Step 10.5 — Bootstrap .memory/ directory`
   - `Step 11 — Register expert candidates`
   - `Step 12 — Bootstrap expert-pump routine`
   - `Step 13 — Gate 2 (run_here) + daemon supervisor install`
   - `Step 13.5 — Configure expert-spawn sandbox in .runtime/sandbox.settings.json`
   - `Step 14 — Report`
   - `Step 15 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `already-ignored`, `absent`, `skipped-per-user-choice`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Decisions are remembered, never re-asked

This skill is **idempotent and quiet on re-run**. Every choice it makes is persisted, and on the next run the persisted value is read first and honoured silently — the user is asked again only when nothing is on record yet.

- **Plugin enabled = full functionality.** An enabled plugin is installed whole. There is no per-rule "install this rule?" prompt and no per-artifact opt-in — wanting the plugin means wanting its surface.
- **Two daemon gates, asked once each:**
  - `daemon.enabled` (tracked `lazy.settings.json`) — does *this project* use the background daemon at all? Set false → the daemon-only steps (routines, supervisor, sandbox, runtime plumbing) are skipped for the project and never re-raised. Experts, `agent_models` tiers, rules, skills, and manual commands still install — they are not daemon-bound.
  - `daemon.run_here` (this checkout's gitignored `lazy.settings.local.json`) — run the daemon for *this checkout* (this working copy)? Per-checkout, NOT per-machine: each clone of the project has its own overlay, so several checkouts on one machine each decide independently. Set false → the supervisor + sandbox are skipped for this checkout and never re-raised, even though the project keeps `daemon.enabled = true`.
- **Everything derivable is derived, not asked:** install scope (from where the plugin is *enabled* — see Step 1), supervisor kind (from platform), dev-mode (from whether this repo ships plugin sources), expert git identity (a deterministic bot id).

## File-sync policy (applies to every file this skill writes)

Every file this skill creates or updates follows three cases — no per-file "install?" prompt, no routine drift wizard:

1. **Absent or unchanged** — target missing, or byte-identical to the shipped / last-known version → write the new version silently. State `installed` / `unchanged`.
2. **Locally changed but cleanly mergeable** — target diverged from shipped, but the shipped delta applies without contradicting local edits (new sections / keys / entries added, every local-only chunk left untouched) → merge silently. State `merged`.
3. **Genuine conflict** — the same region (a key, a line, a block) was changed both locally and in the shipped version in ways that cannot be reconciled automatically → the ONLY case that asks. `AskUserQuestion` naming the file, quoting the conflicting region, and showing a unified diff; options `merge-shipped` / `keep-local`.

"Conflict" means you cannot determine what should survive — not merely "the bytes differ". No contradiction → no question. A no-longer-shipped file (orphan) is left in place silently (`kept-orphan`); this skill never deletes consumer files.

## Step 0: Verify Python ≥ 3.12 (floor)

Every plugin in this marketplace requires Python ≥ 3.12. This step runs first; on a machine that already meets the floor it is silent (one `python3 -V` invocation) and the install proceeds straight to Step 1. Per-plugin `<ns>.install` skills inherit this gate — they do NOT re-probe.

Run `Bash(python3 -V)` and parse the version. A missing or below-floor interpreter is an environment prerequisite, not a choice — do NOT open an `AskUserQuestion`. Print one line and stop:

> Python 3.12+ required (found `<detected version or 'not found'>`). Install it, then re-run `/lazy-core.install`. macOS: `brew install python@3.12 && brew link python@3.12 --force`. Linux: `pyenv install 3.12 && pyenv global 3.12`.

State outcome `aborted-python-floor-not-met` and skip Steps 1–15.

If `python3 -V` reports ≥ 3.12.0: state outcome `python-floor-ok (<version>)` and proceed to Step 1.

When raising the floor in the future, bump this step's numeric threshold in the same edit as any other floor-bearing reference.

## Step 1: Detect install scope

Scope = **where the plugin is actually enabled**, not where `/plugin install` last ran. The `scope` field in `installed_plugins.json` records the install command's origin (a shared-cache download registration), which drifts from the activation scope — a plugin enabled per-project in `.claude/settings.json` can carry an install record of `scope: "user"`. Enablement is the source of truth for where config belongs.

Resolve it with the shared helper, which reads `enabledPlugins` from the project settings first, then the global settings, and falls back to the install record's own `scope` only when neither settings file enables the plugin:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import subprocess
from lazy_install_phases import detect_install_scope
root = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True).stdout.strip() or '.'
print(detect_install_scope('lazycortex-core@lazycortex', project_root=root))
")
```

The helper prints exactly one word:
- `project` — enabled in `<repo-root>/.claude/settings.json` (project wins even when the install record's scope is `user`, and when both scopes enable it); Steps 3–6 target `<repo-root>/.claude/`.
- `user` — enabled only in `~/.claude/settings.json` (or the fallback resolved there); Steps 3–6 target `~/.claude/`.
- `not-installed` — `lazycortex-core@lazycortex` is absent / has an empty array in `~/.claude/plugins/installed_plugins.json`; the plugin has never been installed on this machine.

The scope is derived — do NOT ask.

**Do NOT compare an entry's `projectPath` against the current working directory.** `projectPath` records where the install command was last run, not where the plugin "belongs" — Step 2 of this skill targets `<repo-root>` (i.e. `git rev-parse --show-toplevel` in the current cwd) regardless of any entry's `projectPath`. A `projectPath` mismatch is **never** grounds for aborting.

Abort **only** on `not-installed` — the shared plugin cache is the sole proof of installation, and enablement cannot substitute for missing sources. In that case tell the user to install it first:
```json
"enabledPlugins": { "lazycortex-core@lazycortex": true }
```
then run `/plugin install lazycortex/lazycortex-core`.

## Step 2: Determine paths

Enumerate every rule file shipped by the plugin via `Glob: <installPath>/rules/*.md` — never hardcode filenames. `<installPath>` is the `installPath` field from `installed_plugins.json`.

For each source file `<installPath>/rules/<name>.md`, the target is:

| Scope | Rule destination | Templates destination |
|---|---|---|
| `user` | `~/.claude/rules/<name>.md` | `~/.claude/templates/core/` |
| `project` | `<repo-root>/.claude/rules/<name>.md` | `<repo-root>/.claude/templates/core/` |

Project root is `git rev-parse --show-toplevel` (or current working directory if not in a git repo — warn the user).

If the glob returns zero files, abort and tell the user the plugin cache is empty — they likely need to run `/plugin update lazycortex-core@lazycortex` first.

## Step 3: Sync rule templates

An enabled plugin installs its whole rule surface — apply the **File-sync policy** per rule, no per-rule "install?" prompt.

### Enumerate source and target

- Source rules: `Glob <installPath>/rules/*.md`.
- Owned namespaces: the plugin name minus the `lazycortex-` prefix (so `lazycortex-core` → `lazy-core`), plus every unique `<ns>.` prefix appearing in source rule filenames (for this plugin that includes both `lazy-core` and `lazy-guard`).
- Target candidates: `Glob <targetRulesDir>/<ns>.*.md` for each owned namespace. Union them.
- Ensure the destination directory exists with `mkdir -p`.

### Apply the File-sync policy per rule

For every rule name in (source ∪ target):

- **New** (target missing) → copy source to target silently. State **installed**.
- **Unchanged** (byte-identical) → no action. State **unchanged**.
- **Drift, cleanly mergeable** (both present, differ, the shipped delta applies without contradicting local edits — new headings / list items / registry entries added, every local-only chunk preserved) → merge silently via `Edit`. State **merged**.
- **Conflict** (the same region changed incompatibly in both) → the only case that asks, per File-sync policy case 3. State **merged** or **kept-local** by the user's choice.
- **Orphan** (target present, source gone, within an owned namespace) → leave in place silently. State **kept-orphan**.

Target files outside this plugin's owned namespaces (other plugins, user-authored rules) are never touched and never reported as orphans.

### `lazy-core.scaffold.md` — registry-block exemption (§5a)

`lazy-core.scaffold.md` is special: its `## Registry` fenced block is **primitive-owned** — written only by `lazycortex-core scaffold` via Step 4's `scaffold-sync`. When this file reaches the File-sync policy:

- **New** — install it as shipped (an empty `{}` registry); Step 4 then populates it.
- **Drift** — merge only the prose / frontmatter region *above* `## Registry`; leave the `## Registry` block **byte-for-byte** (the shipped block is `{}`, so it contributes nothing to merge anyway).
- Never rewrite or clobber the consumer's populated `## Registry` block here — surgical per-key registry writes are `scaffold-sync`'s job.

## Step 4: Sync authoring templates

Authoring-template copy **and** scaffold-registry population are both done by `lazy-core.scaffold-sync`, invoked for `lazycortex-core` itself — core registers through the same path as any other plugin (dogfood).

Resolve this plugin's own `<installPath>` (the `installPath` field of `lazycortex-core@lazycortex` in `installed_plugins.json`) and the detected `<scope>` (`project` / `user`), then dispatch:

```
Skill(skill: "lazycortex-core:lazy-core.scaffold-sync", args: "plugin=lazycortex-core installPath=<installPath> scope=<scope>")
```

The skill discovers `<installPath>/templates/core/scaffold.entries.json`, copies `templates/core/*` (excluding the manifest) into `<consumerScope>/.claude/templates/core/` under the same File-sync policy, and upserts the `lazycortex-core` registry key from the manifest via `scaffold upsert` (surgical — the consumer's `_local` and any sibling-plugin keys stay byte-for-byte; per §5a the rest of `lazy-core.scaffold.md` is untouched).

### Outcome

The `scaffold-sync` report: per-template copy states plus the registry upsert status.

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

## Step 7: Bootstrap .logs/, .runtime/, lazy.settings.local.json gitignore, and .lazyignore

Create `.logs/` and `.runtime/` at the repo root, ensure `.gitignore` covers both, ensure `.gitignore` also lists `.claude/lazy.settings.local.json` (the gitignored personal overlay companion to the tracked `lazy.settings.json`), and seed a default `.lazyignore` at the repo root when one is absent.

- `.logs/` — gitignored runtime journal (daemon output, recall logs, commit-recorder feed).
- `.runtime/` — gitignored non-log daemon state (currently `state.json` carrying `last_run` / `git_watch` / `daemon_halted`).
- `.claude/lazy.settings.local.json` — gitignored personal-overlay file that `lazy_settings.load_section` deep-merges onto the tracked `lazy.settings.json`. No directory is created — the file is opt-in and materializes only when the consumer adds a local override. The `.gitignore` slot is reserved so accidental commits are impossible.
- `.lazyignore` — tracked git excludes file carrying the *extra* excludes (on top of `.gitignore`) that every tree-walking routine honours via git's ignore engine: venvs, `node_modules`, `__pycache__`, in-tree worktrees. Seeded from the shipped template only when absent — the consumer's own copy is authoritative and never overwritten.

All four concerns are handled by three helpers. This step runs unconditionally (not gated on runtime-setup confirmation); the `.logs/` half is absorbed from the retired `lazy-log.install` skill.

Run via:

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from pathlib import Path
from lazy_install_phases import bootstrap_logs_dir, bootstrap_lazy_settings_local_gitignore, bootstrap_lazyignore
print('.logs/+.runtime/:', bootstrap_logs_dir(Path('.')))
print('lazy.settings.local.json:', bootstrap_lazy_settings_local_gitignore(Path('.')))
print('.lazyignore:', bootstrap_lazyignore(Path('.'), Path('${CLAUDE_PLUGIN_ROOT}/templates/.lazyignore')))
")
```

Outcome per helper: `bootstrapped` (something was created/appended) or `already-present` for the first two; `seeded` / `already-present` / `template-missing` for `.lazyignore`.

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

For Steps 9–13, `<repo-root>` is the cwd's git toplevel (resolved in 9a, initialized in 9b only if the daemon is enabled and the cwd is not yet a repo), even if Step 1 detected install scope as `user`.

### 9a. Resolve the runtime repo

Run `git rev-parse --show-toplevel` in cwd. If it succeeds, set `<repo-root>` to the returned path and `is_git = true`. If it fails (cwd is not inside a git repo), set `<repo-root>` to cwd and `is_git = false`. Do NOT prompt to initialize git here — that question (if needed at all) is deferred to 9b's Gate-1-enabled branch, so a project that declines the daemon is never asked to create a repo it doesn't need.

### 9b. Gate 1 — does this project use the daemon? (`daemon.enabled`)

Whether the background daemon (routines, supervisor) runs **in this project at all** is a per-project decision, recorded once in the tracked `daemon.enabled` flag and honoured silently on every re-run. Read it first; ask only when nothing is on record. Note: this gates only daemon-only artifacts — expert registration (Step 11) and the `.memory/` dir (Step 10.5) run regardless, since experts are dispatched interactively too.

```bash
PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from lazy_settings import load_tracked_section
from pathlib import Path
sec = load_tracked_section(Path('<repo-root>/.claude/lazy.settings.json'), 'daemon')
print(sec.get('enabled', 'unset'))
"
```

- Output `True` → daemon used in this project; proceed to 9c and run Steps 10–13.5 (each still subject to Gate 2 for this checkout). Do NOT ask.
- Output `False` → daemon not used in this project; mark the daemon-only steps (9c, 10, 12, 13, 13.5) with outcome `skipped-daemon-disabled`, but STILL run Steps 10.5 (`.memory/`) and 11 (expert registration) — experts and their memory dir are dispatch-routing config used by interactive flows too, NOT daemon-gated — then go to Step 14. Do NOT ask.
- Output `unset` → ask once:

This is a **project-policy** question, NOT an operational one — keep all "run" / "here" / "this machine" language OUT of it (that belongs to Gate 2). Ask whether the daemon is part of the project's design at all:

```
AskUserQuestion:
  header: "Use daemon?"
  question: "Does this project use the background daemon at all? (project-wide policy — NOT about starting it on your machine)"
  description: "Recorded in the project's tracked `lazy.settings.json` as `daemon.enabled`, shared with everyone who clones the repo — it declares whether the daemon is part of this project's design. Whether to actually START it on this particular working copy is a SEPARATE question (Gate 2, asked next, per-checkout). 'No' permanently skips all daemon-only setup for the project; rules, skills, experts, and manual commands still install. Change it later by editing the flag and re-running `/lazy-core.install`."
  options: ["Yes — this project is daemon-driven", "No — this project never uses a daemon"]
```

  Persist the answer into the tracked `daemon` section, then branch:

```bash
PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from lazy_settings import load_tracked_section, save_section
from pathlib import Path
p = Path('<repo-root>/.claude/lazy.settings.json')
sec = load_tracked_section(p, 'daemon')
sec['enabled'] = <True|False>
save_section(p, 'daemon', sec)
"
```

  - `No` → outcome `daemon-disabled (project)`; skip the daemon-only steps (9c, 10, 12, 13, 13.5) but STILL run Steps 10.5 and 11 (experts are not daemon-gated), then go to Step 14.
  - `Yes` → outcome `daemon-enabled (project)`; continue below.

When the daemon is enabled but `is_git = false` (from 9a), the runtime layer needs a repo root. Ask once:

```
AskUserQuestion:
  question: "Initialize a git repository here so the daemon's runtime config can be tracked?"
  description: "The current directory is not a git repo, but the daemon you just enabled needs one for `.experts/` and supervisor units. 'Initialize' runs `git init` here; 'Skip' leaves the project daemon-enabled but bypasses runtime/experts setup on this run (re-run after `git init`)."
  options: ["Initialize git here", "Skip — no runtime setup this run"]
```

  - `Initialize git here` → `Bash(git init)` in cwd, keep `<repo-root>` = cwd, continue with 9c.
  - `Skip — no runtime setup this run` → mark Steps 9c–13.5 with outcome `skipped-not-in-git-repo`, go to Step 14.

When `is_git = true`, continue straight to 9c and run Steps 10–13.5.

### 9c. Write the flat `daemon` + `routines` sections

The runtime daemon reads its config from **flat top-level section keys** — `runtime_daemon.py` calls `load_section(path, "daemon")` and `load_section(path, "routines")` directly, and `expert_runtime.register_routine` writes the flat `routines` section. Seed those two sections (never a nested `lazy-core.runtime` object — nothing reads that shape).

Seed the default daemon keys with `setdefault` (so 9b's `enabled` flag and any existing values are preserved — never overwrite) and seed an empty `routines` section when absent:

```bash
PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import json
from lazy_settings import load_tracked_section, save_section
from pathlib import Path
p = Path('<repo-root>/.claude/lazy.settings.json')
sec = load_tracked_section(p, 'daemon')
before = dict(sec)
for k, v in {'git': None, 'polling_interval_sec': 5, 'cleanup_completed_after': '7d',
             'cleanup_failed_after': '30d', 'cleanup_dead_after': '7d',
             'stream_idle_timeout_sec': 90, 'stream_max_retries': 3}.items():
    sec.setdefault(k, v)
save_section(p, 'daemon', sec)
print('daemon: bootstrapped' if sec != before else 'daemon: already-present')
raw = json.loads(p.read_text()) if p.exists() else {}
if 'routines' not in raw:
    save_section(p, 'routines', {})
    print('routines: bootstrapped')
else:
    print('routines: already-present')
"
```

State **bootstrapped** if any default key or the routines section was newly written; **already-present** if everything was already present; **skipped-not-in-git-repo** or **skipped-daemon-disabled** if 9a/9b chose to skip.

## Step 10: Bootstrap experts directory

If Step 9 was skipped (outcome `skipped-not-in-git-repo` or `skipped-daemon-disabled`), inherit the same outcome and skip this step.

Otherwise, perform the following three idempotent operations:

### Ensure `lazy.runtime.sh` shim

The shim is content-tracked so consumers pick up new shim features (e.g. the `--dev-mode` flag added in lazy-core 0.18) on re-install without manual cleanup.

1. `Bash(mkdir -p <repo-root>/.claude/bin/)`
2. If `<repo-root>/.claude/bin/lazy.runtime.sh` is absent → copy + chmod, state **created**.
3. If present and `Bash(diff -q ${CLAUDE_PLUGIN_ROOT}/templates/runtime/lazy.runtime.sh <repo-root>/.claude/bin/lazy.runtime.sh)` reports differences → copy + chmod, state **refreshed**.
4. Otherwise → state **already-present** (no action).

Copy command in cases 2 and 3:
```
Bash(cp ${CLAUDE_PLUGIN_ROOT}/templates/runtime/lazy.runtime.sh <repo-root>/.claude/bin/lazy.runtime.sh)
Bash(chmod +x <repo-root>/.claude/bin/lazy.runtime.sh)
```

The shim resolves the latest `lazycortex-core/bin/runner` from the plugin cache at exec time, so supervisor units don't need re-rendering after `/plugin update`. Re-copying on content drift is safe — the shim's interface is stable (positional repo-root + repeatable `--plugin-dir`; the `--dev-mode`, `--login-shell`, and repeatable `--env-file <path>` flags are additive and stripped by the shim before the runner exec).

### Ensure `lazy.settings.json[experts]`

Check whether the `experts` section exists in `<repo-root>/.claude/lazy.settings.json`. If missing, write it with content `{"_version": 1}` via `lazy_settings.save_section`.

State **created** if written; **already-present** if it existed.

### Ensure `.gitignore` entries

Read `<repo-root>/.gitignore` (or treat as empty if missing). Ensure it contains the following line:
- `.experts/`

`.logs/` and `.runtime/` are owned by Step 7's `bootstrap_logs_dir` helper and need no entry here. The whole `.experts/` tree is runtime scratch (job queue, cross-repo trackers, subprocess locks) — ignore the directory, not just `.experts/.jobs/`. If a legacy narrower `.experts/.jobs/` line is present, replace it with `.experts/`; if no `.experts/` line is present, append it with `Edit` (or `Write` if the file was missing). State **updated** if appended or replaced; **already-present** if `.experts/` was already there.

## Step 10.5: Bootstrap .memory/ directory

If Step 9 resolved no repo (outcome `skipped-not-in-git-repo`), inherit that outcome and skip this step. Otherwise run it **even when the daemon is disabled** (`skipped-daemon-disabled`) — registered experts write memory under `.memory/<self>/` when dispatched interactively too, so the dir must exist regardless of the daemon.

Otherwise, ensure `.memory/` exists at the repo root and strip any legacy `!.memory/` line from `.gitignore` (older versions of this skill wrote a defensive un-ignore line; the line was selective paranoia and is now retired — memory notes track in git the normal way):

```
Bash(PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from pathlib import Path
from lazy_install_phases import bootstrap_memory_dir
print(bootstrap_memory_dir(Path('.')))
")
```

Outcome: `bootstrapped` (dir created and/or legacy line stripped) or `already-present` (dir existed and no legacy line present).

## Step 11: Register expert candidates

If Step 9 resolved no repo (outcome `skipped-not-in-git-repo`), inherit that outcome and skip this step (there is no settings file to write). Otherwise run it **even when the daemon is disabled** (`skipped-daemon-disabled`) — experts are dispatch-routing config resolved by interactive flows (spec / review / direct dispatch) as well as the daemon, so they are registered regardless of `daemon.enabled`.

Register every expert candidate the enabled plugins ship — there is no per-candidate prompt and no scan confirmation; an enabled plugin's experts are installed whole.

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

If no candidates are found after scanning all three scopes, state **no-scanned-candidates** — the built-in candidate below still registers, so proceed to § 1b, not to Step 12.

### 1b. Built-in candidate: the runtime doctor

`lazycortex-core` ships one dispatchable agent that carries no `expert_protocol:` frontmatter and is therefore invisible to the scan: the runtime doctor. Its dispatch config still lives in settings like every other expert's — the daemon's doctor tick resolves agent and model from the expert entry and `agent_models`, never from code defaults.

Append it to the candidate list unconditionally:

- `agent_name`: `lazy-runtime.doctor`
- `plugin`: `lazycortex-core`
- no protocol (the doctor routine supplies its context bundle directly; there is nothing to resolve)

It then flows through §§ 2–4 exactly like a scanned candidate (skipped if already registered, bot `git_author`, entry `{agent, git_author}`).

Additionally, ensure the doctor's model tier exists in the **project** `agent_models` (the expert runtime resolves models from `<repo-root>/.claude/lazy.settings.json` only). Pull the tier for key `lazycortex-core:lazy-runtime.doctor` from `${CLAUDE_PLUGIN_ROOT}/skills/lazy-core.agent-models/default-tiers.json` (same SOT and same missing-file FAIL as Step 6), then merge it under the `lazycortex` group via `load_tracked_section` / `save_section`:

- **absent** → add `agent_models.lazycortex["lazycortex-core:lazy-runtime.doctor"] = <tier from JSON>`. State **tier-added**.
- **present** (any value) → leave the user's value untouched. State **tier-kept-local**.

### 2. Filter already-registered candidates

Load the `experts` section of `<repo-root>/.claude/lazy.settings.json` (via `lazy_settings.load_tracked_section`). Skip any candidate whose `agent_name` already appears as a key in the section (besides `_version`).

If all candidates are filtered out, state **all-already-registered** and proceed to Step 12.

### 3. Derive each entry — no questions

For every remaining candidate:

- **local name** = its `agent_name` verbatim.
- **git_author** = a deterministic bot identity, NOT the operator's `git config`: `{name: <agent_name>, email: <agent_name>@lazycortex.local}`. The daemon distinguishes expert commits from operator commits by this email and runs loop-detection over it — reusing the human's identity would make operator commits look like bot commits and break that safety net.

### 4. Write all candidates to `lazy.settings.json[experts]`

For each candidate, merge the new entry via (load → modify → save uses `load_tracked_section` so the local overlay never leaks into the tracked file):

```bash
PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from pathlib import Path
from lazy_settings import load_tracked_section, save_section
p = Path('<repo-root>/.claude/lazy.settings.json')
section = load_tracked_section(p, 'experts')
section['<agent_name>'] = {
    'agent': '<plugin>:<agent_name>',
    'git_author': {'name': '<agent_name>', 'email': '<agent_name>@lazycortex.local'}
}
save_section(p, 'experts', section)
"
```

State one line per candidate: `<agent_name>: registered`.

## Step 12: Bootstrap expert-pump routine

If Step 9 was skipped (outcome `skipped-not-in-git-repo` or `skipped-daemon-disabled`), inherit the same outcome and skip this step.

Otherwise, check two conditions:
1. The `experts` section of `<repo-root>/.claude/lazy.settings.json` contains at least one expert entry (a key that is not `_version` and whose value is a dict).
2. The flat `routines` section of `<repo-root>/.claude/lazy.settings.json` (`load_section(path, 'routines')` — the same section `register_routine` writes to) does NOT already contain a key `lazy-expert.pump`.

If both conditions are true, run:

```bash
PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from expert_runtime import bootstrap_default_routines
from pathlib import Path
bootstrap_default_routines(Path('<repo-root>'))
"
```

State **registered** if the routine was added; **already-present** if it was already there; **skipped-no-experts** if condition 1 was false.

## Step 13: Gate 2 (run_here) + daemon supervisor install

If Step 9 was skipped (outcome `skipped-not-in-git-repo` or `skipped-daemon-disabled`), inherit the same outcome and skip this step.

Whether the daemon runs for **this checkout** (this working copy of the project) (Gate 2) is a per-checkout decision, recorded once in THIS checkout's own gitignored local overlay (`daemon.run_here`) and honoured silently on every re-run. It is NOT per-machine: a machine may hold several checkouts of the same project, each with its own `.claude/lazy.settings.local.json`, and the daemon runs only on the checkout(s) where `run_here` is true. Read it first; ask only when nothing is on record.

```bash
PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from lazy_settings import load_local_only_section
from pathlib import Path
sec = load_local_only_section(Path('<repo-root>/.claude/lazy.settings.json'), 'daemon')
print(sec.get('run_here', 'unset'))
"
```

- Output `True` → run the daemon for this checkout; proceed to 13a and install the supervisor. Do NOT ask.
- Output `False` → not this checkout; state **run-here-declined**, skip the supervisor and Step 13.5. Do NOT ask.
- Output `unset` → ask once:

This is the **operational** question — it OWNS the "run / start / this checkout" language (Gate 1 had none). The project already opted into the daemon; this decides whether to actually start it on this particular working copy:

```
AskUserQuestion:
  header: "Run here?"
  question: "Start the daemon for THIS checkout now? (the project is daemon-driven — this starts it on this working copy only)"
  description: "Recorded for THIS checkout in its own gitignored `lazy.settings.local.json` as `daemon.run_here` — each clone / working copy decides independently, so several checkouts of this project on one machine can each answer differently. 'Yes' installs a supervisor (launchd on macOS, systemd on Linux) that keeps the daemon running for this checkout. 'No' leaves the project's daemon config in place but never starts it for this checkout. Change it later by editing the flag and re-running `/lazy-core.install`."
  options: ["Yes — run it for this checkout", "No — not this checkout"]
```

  Persist the answer into the local overlay:

```bash
PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from lazy_settings import load_local_only_section, save_local_section
from pathlib import Path
p = Path('<repo-root>/.claude/lazy.settings.json')
sec = load_local_only_section(p, 'daemon')
sec['run_here'] = <True|False>
save_local_section(p, 'daemon', sec)
"
```

  - `No` → state **run-here-declined**; skip the supervisor install and Step 13.5.
  - `Yes` → state **run-here**; continue with 13a.

### 13a. Derive supervisor kind, dev-mode, and the per-checkout unit id (no questions)

- **Supervisor kind** = the platform: macOS (`darwin`) → launchd (13b); Linux → systemd (13c). No question — the platform is known.
- **`<REPO_ID>`** = a collision-free, per-checkout supervisor identifier: `<basename>-<hash>` where `<basename>` is the basename of `<repo-root>` and `<hash>` is the first 8 hex of `sha256(<absolute-repo-root>)`. The basename alone is NOT unique — two checkouts of this project (e.g. two dirs both named `LazyCortex`) would otherwise produce the same launchd Label / systemd unit name and clobber each other. Hashing the absolute path makes the unit id unique per checkout and stable across re-runs (same path → same id). Compute:

```bash
PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import hashlib, os, sys
root = os.path.abspath('<repo-root>')
print(os.path.basename(root) + '-' + hashlib.sha256(root.encode()).hexdigest()[:8])
"
```

  Hold the printed value as `<REPO_ID>` for 13b/13c. `<REPO_NAME>` (bare basename) is still used only for the human-readable systemd `Description`.
- **dev-mode** = whether this repo IS a plugin-authoring vault. It is True when `Bash(find <repo-root>/claude -maxdepth 3 -path '*/.claude-plugin/plugin.json' -print -quit)` returns a path, else False. In dev-mode the shim prefers in-repo plugin sources under `<repo-root>/claude/*/` over the cache. Persist the derived value under the flat `daemon` section so Step 13.5's sandbox block lists the right plugin-source paths:

```bash
PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from lazy_settings import load_tracked_section, save_section
from pathlib import Path
p = Path('<repo-root>/.claude/lazy.settings.json')
sec = load_tracked_section(p, 'daemon')
sec.setdefault('supervisor', {})['dev_mode'] = <True|False>
save_section(p, 'daemon', sec)
"
```

Hold the derived boolean as `<dev_mode>` for 13b/13c.

- **login-shell / env-files** = operator-provided supervisor options (NOT derived — read verbatim from the `daemon.supervisor` block, alongside `dev_mode`). They give the daemon a login-equivalent environment on headless hosts where launchd/systemd exec the shim without a login shell, so `claude -p` otherwise fails "Not logged in" and `claude` may not resolve in PATH. Both default off → byte-identical behaviour when absent.

```bash
PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
from lazy_settings import load_tracked_section
from pathlib import Path
sup = load_tracked_section(Path('<repo-root>/.claude/lazy.settings.json'), 'daemon').get('supervisor', {})
print('login_shell=' + ('1' if sup.get('login_shell') else '0'))
for ef in sup.get('env_files', []) or []:
    print('env_file=' + ef)
"
```

  Hold `<login_shell>` (bool) and the ordered `<env_files>` list for 13b/13c. Render each `env_files` entry **verbatim** — the shim expands a leading `~` itself (launchd does not), so do not pre-expand. `login_shell` solves both token and PATH; `env_files` is the surgical token-only path. They may combine.

### 13b. macOS launchd

When the platform is macOS (`darwin`):
1. **Migrate a legacy basename-only unit (if present).** Older installs named the unit by bare basename. If `~/Library/LaunchAgents/com.lazycortex.runtime.<REPO_NAME>.plist` exists AND its body contains `<string><repo-root></string>` (its `WorkingDirectory` points at THIS checkout — confirm with `Bash(grep -F "<repo-root>" ~/Library/LaunchAgents/com.lazycortex.runtime.<REPO_NAME>.plist)`), it is this checkout's old-scheme unit → `Bash(launchctl unload ~/Library/LaunchAgents/com.lazycortex.runtime.<REPO_NAME>.plist)` then `Bash(rm ~/Library/LaunchAgents/com.lazycortex.runtime.<REPO_NAME>.plist)` before installing the new one. If the legacy file is absent, or exists but points at a DIFFERENT checkout (a same-basename sibling), leave it untouched. State **legacy-unit-migrated** or **no-legacy-unit**.
2. Read `${CLAUDE_PLUGIN_ROOT}/templates/runtime/com.lazycortex.runtime.plist`.
3. Substitute `{REPO_ROOT}` → absolute path of `<repo-root>`, `{REPO_ID}` → the per-checkout id from 13a (the shim path is built into the template as `{REPO_ROOT}/.claude/bin/lazy.runtime.sh` — no separate runner-path substitution needed).
4. **Inject the shim flags** into `ProgramArguments`, between the `lazy.runtime.sh` line and the `{REPO_ROOT}` line, in this order (each is its own `<string>` element; indent matches the surrounding `<string>` lines — 8 spaces). Omit any whose source value is unset:
   - **If `<login_shell>` is True**: a `<string>--login-shell</string>` line.
   - **For each `<env_files>` entry** (in order): a `<string>--env-file</string>` line immediately followed by a `<string><path></string>` line carrying the verbatim path (`--env-file` and its value are two separate array elements).
   - **If `<dev_mode>` is True**: a `<string>--dev-mode</string>` line.
5. `Bash(mkdir -p ~/Library/LaunchAgents/)`
6. Write the rendered plist to `~/Library/LaunchAgents/com.lazycortex.runtime.<REPO_ID>.plist`.
7. `Bash(launchctl load ~/Library/LaunchAgents/com.lazycortex.runtime.<REPO_ID>.plist)`
8. State **launchd-installed** (or **launchd-installed-dev-mode** when `<dev_mode>` is True; append **-login-shell** / **-env-files** when those flags were injected).

### 13c. Linux systemd

When the platform is Linux:
1. **Migrate a legacy basename-only unit (if present).** If `~/.config/systemd/user/lazy-core-runtime-<REPO_NAME>.service` exists AND its `ExecStart=` references THIS checkout (confirm with `Bash(grep -F "<repo-root>" ~/.config/systemd/user/lazy-core-runtime-<REPO_NAME>.service)`) → `Bash(systemctl --user disable --now lazy-core-runtime-<REPO_NAME>.service)` then `Bash(rm ~/.config/systemd/user/lazy-core-runtime-<REPO_NAME>.service)` before installing the new one. If absent, or pointing at a different checkout, leave it. State **legacy-unit-migrated** or **no-legacy-unit**.
2. Read `${CLAUDE_PLUGIN_ROOT}/templates/runtime/lazy-core-runtime.service`.
3. Substitute `{REPO_ROOT}` → absolute path of `<repo-root>`, `{REPO_NAME}` → basename (used only in the human-readable `Description=`).
4. **Inject the shim flags** into the `ExecStart=` line (after step 3's substitution). Build a flag prefix and splice it between `lazy.runtime.sh` and `{REPO_ROOT}`, in order: `--login-shell` (if `<login_shell>` is True), then `--env-file <path>` per `<env_files>` entry (quote a path containing spaces), then `--dev-mode` (if `<dev_mode>` is True). With no flags the line is unchanged. Example with all three: `lazy.runtime.sh --login-shell --env-file ~/.claude/.env --dev-mode {REPO_ROOT}`.
5. `Bash(mkdir -p ~/.config/systemd/user/)`
6. Write the rendered unit to `~/.config/systemd/user/lazy-core-runtime-<REPO_ID>.service`.
7. `Bash(systemctl --user enable --now lazy-core-runtime-<REPO_ID>.service)`
8. State **systemd-installed** (or **systemd-installed-dev-mode** when `<dev_mode>` is True).
7. State **systemd-installed** (or **systemd-installed-dev-mode** when `<dev_mode>` is True).

## Step 13.5: Configure expert-spawn sandbox in .runtime/sandbox.settings.json

If Step 9 was skipped (outcome `skipped-not-in-git-repo` or `skipped-daemon-disabled`), OR Step 13 stated `run-here-declined`, inherit the skip with outcome `skipped-not-run-here` and move to Step 14 — there is no daemon running here to sandbox.

Otherwise, the runtime daemon spawns `claude -p --permission-mode dontAsk` subprocesses for every expert job, passing `--settings <repo-root>/.runtime/sandbox.settings.json`. The sandbox scope lives in that daemon-owned runtime file — NOT in `.claude/settings.local.json` — because `.claude/settings.local.json` is loaded by EVERY Claude session in the checkout, so a `sandbox.enabled: true` there would also confine the operator's interactive session (e.g. breaking `git push` over SSH, which the sandbox's HTTP/HTTPS proxy cannot carry). `--settings` is passed only on the spawn, so the sandbox reaches the expert subprocess and never the interactive session.

The spawn loads `--settings` AND the cwd's `.claude/settings.local.json`, merged (CLI layer wins on conflict). So the split is: the **sandbox** block goes to `.runtime/sandbox.settings.json`; the **permission scope** (`permissions` + `additionalDirectories`) stays in `.claude/settings.local.json`, where it serves both the spawn (via the merge) and the operator's interactive session (which needs those allows when running plugin CLIs manually).

Both writes are clean, non-contradictory merges — apply the File-sync policy **silently**: no confirmation, never overwrite an existing key, union missing scope in. Ask only on a genuine conflict per File-sync policy case 3 (e.g. an existing `sandbox.enabled: false` that contradicts the required `true`).

### 13.5b. Recommended blocks

Substitute `<repo-root>` with the absolute path of the current repo. Substitute `<plugin-source-N>` lines with one entry per plugin source directory the daemon will pass via `--plugin-dir` (Step 13a's derived `dev_mode` dictates whether these are in-repo `<repo-root>/claude/<plugin>/` paths or `~/.claude/plugins/cache/...` paths — list what the supervisor unit will actually use).

Block 1 — `<repo-root>/.runtime/sandbox.settings.json` (daemon-owned; read only by spawns via `--settings`):

```json
{
  "sandbox": {
    "enabled": true,
    "filesystem": {
      "allowRead":  ["<repo-root>", "<plugin-source-1>", "<plugin-source-2>", "..."],
      "allowWrite": ["<repo-root>"]
    }
  }
}
```

Block 2 — `<repo-root>/.claude/settings.local.json` (permission scope; loaded by every session in the checkout):

```json
{
  "additionalDirectories": ["<plugin-source-1>", "<plugin-source-2>", "..."],
  "permissions": {
    "allow": ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "Skill", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "Bash(lazycortex-core *)"],
    "deny":  ["Bash(find /*)", "Bash(find /Users/*)", "Bash(grep -r /*)", "Bash(grep -R /*)", "Bash(rg /*)", "Bash(rg --files /*)", "Bash(ls /Users/*)"]
  }
}
```

The `Bash(lazycortex-core *)` entry is required so dispatched experts can invoke the core CLI (`expert-pump-once`, `permission-allow`, etc.) — Claude Code's `dontAsk` permission mode auto-allows only well-known commands (git, python3, ls in PWD) and silently denies any other Bash command without an explicit allow-pattern. Sibling plugins' install skills add their own `Bash(lazycortex-<short> *)` patterns to this same `permissions.allow` list via `lazycortex-core permission-allow`.

Tilde-form (`~/...`) is acceptable for paths the operator wants portable across machines — Claude Code expands `~` at load time. Absolute paths are equally valid.

### 13.5c. Apply the File-sync policy to both files

`Read <repo-root>/.runtime/sandbox.settings.json` and apply Block 1:

1. **Missing or unparseable** → `Write` Block 1 verbatim as a new file. State **sandbox-created**.
2. **Present, no `sandbox` key** → `Edit` to add it (preserve every existing key). State **sandbox-appended**.
3. **Present, `sandbox` already there** → union missing `filesystem.allowRead` / `allowWrite` paths in, silently; never drop or replace existing entries. State **sandbox-merged**. Only a direct contradiction (e.g. `enabled: false`) triggers an `AskUserQuestion`.

`Read <repo-root>/.claude/settings.local.json` and apply Block 2 + migrate:

4. **Missing or unparseable** → `Write` Block 2 verbatim. State **perms-created**.
5. **Present** → union missing `permissions` / `additionalDirectories` scope in, silently (add only paths / tool names not already present; never drop existing). State **perms-merged**.
6. **Migration** — if this file carries a legacy top-level `sandbox` key (written by an earlier version of this step), REMOVE it: the sandbox now lives in the runtime file, and a `sandbox` here would confine the interactive session. State **migrated-local-sandbox**; **no-legacy-sandbox** when absent.

Never replace an entire key with the recommended value. The consumer's existing files are authoritative for shape; this skill only adds missing scope (and removes the migrated `sandbox` key).

### Outcome

One line combining the sandbox-file state, the permissions-file state, and the migration state — e.g. `sandbox-created · perms-merged · no-legacy-sandbox`, or `skipped-not-run-here`.

## Step 14: Report

Report to the user:
- Python version probe outcome (Step 0)
- Scope detected (user vs project)
- Plugin version/commit synced from: `<version>` / `<gitCommitSha>` (from `installed_plugins.json`)
- For each rule: state (**installed**, **merged**, **unchanged**, **kept-local**, or **kept-orphan**) and target `<path>`
- For each authoring template: state and target `<path>` (Step 4)
- Per-key `agent_models` seed outcome from Step 6
- `.logs/` directory + `.lazyignore` seed bootstrap outcome (Step 7)
- Hook migration outcome (Step 8): one line per settings path (`migrated` or `no-stale-entries`)
- Runtime bootstrap outcome (Step 9)
- Experts directory bootstrap outcome (Step 10)
- `.memory/` directory bootstrap outcome (Step 10.5)
- Expert registration outcome (Step 11)
- Expert-pump routine registration outcome (Step 12)
- Daemon supervisor install outcome (Step 13)
- Sandbox/permissions merge outcome (Step 13.5)

## Step 15: Log the run

Log to `./.logs/claude/lazy-core.install/YYYY-MM-DD_HH-MM-SS.md` per the logging rule (include `git_sha` frontmatter).

Use two separate steps: `Bash(mkdir -p ...)` then the `Write` tool. Never chain with `&&` or use `cat > file <<'EOF'`.

## Failure modes

- **`/lazy-core.install` aborts: "plugin isn't actually installed — enable it first"** — `lazycortex-core@lazycortex` is missing from `enabledPlugins` in `~/.claude/settings.json`, or the marketplace entry for `lazycortex` is absent from `extraKnownMarketplaces` → add both blocks to `~/.claude/settings.json`, restart Claude Code, then re-run.
- **`/lazy-core.install` aborts: "plugin cache is empty — run `/plugin update` first"** — the rule glob under the plugin's `installPath` returned zero files → run `/plugin update lazycortex-core@lazycortex` to refresh the cache, then re-run.
- **Step 4 aborts: "plugin cache is broken" (templates directory empty)** — the `templates/core/` directory inside the plugin cache is missing or empty → run `/plugin update lazycortex-core@lazycortex`, then re-run.
- **Step 6 fails: "default-tiers.json missing or invalid"** — `lazy-core.agent-models/default-tiers.json` cannot be read or parsed → reinstall `lazycortex-core` to restore the file, then re-run.
- **Step 7 fails: `.logs/` or `.runtime/` not a directory** — a file by either of those names already exists at the repo root → remove or rename it, then re-run.
- **Step 7 fails: `.gitignore` unwritable** — `bootstrap_logs_dir` raised a permission or I/O error → check permissions on the repo root, then re-run.
- **Step 8 fails: settings.json malformed JSON** — one of the four standard settings paths contains invalid JSON → fix the file manually, then re-run.
- **Step 9 fails: settings file unwritable** — `lazy_settings.save_section` raises a permission or I/O error when writing the flat `daemon` / `routines` sections into `.claude/lazy.settings.json` → check file permissions on `.claude/lazy.settings.json` and the `.claude/` directory, then re-run.
- **Step 11 wizard: "no candidates found"** — no agent files with `expert_protocol:` frontmatter were found under any of the three discovery scopes → no experts are available to register; the wizard skips automatically.
- **Step 11 wizard: frontmatter parse failure** — a candidate agent file's frontmatter is malformed YAML → the candidate is skipped and flagged in the report as `parse-error`; fix the frontmatter manually and re-run `/lazy-core.install` to pick it up.
- **Step 11 wizard: protocol reference unresolvable** — `reference_resolver.resolve_reference` returns `None` or raises for a candidate's `expert_protocol:` value → the candidate is skipped and flagged as `protocol-unresolvable`; verify the protocol file exists at the referenced path or reinstall the owning plugin.
- **Step 13 fails: supervisor template not found** — `${CLAUDE_PLUGIN_ROOT}/templates/runtime/com.lazycortex.runtime.plist` or `lazy-core-runtime.service` is missing from the plugin cache → run `/plugin update lazycortex-core@lazycortex` to restore templates, then re-run.
- **Step 13 fails: `launchctl load` error** — the plist was written but `launchctl load` returned a non-zero exit code → inspect the plist at `~/Library/LaunchAgents/` for substitution errors, then run `launchctl load <path>` manually.
- **Step 13 fails: `systemctl --user enable --now` error** — the service unit was written but `systemctl` returned a non-zero exit code → run `systemctl --user status lazy-core-runtime-<REPO_ID>.service` to inspect the error, then correct and re-enable manually.
- **Daemon never starts for this checkout after install** — Gate 2 (`daemon.run_here`) is `false` in this checkout's gitignored `lazy.settings.local.json`, so no supervisor was installed → edit the flag to `true` (or delete it) and re-run `/lazy-core.install` to install the supervisor for this checkout.
- **Re-run never asks about the daemon again** — both gates are already on record (`daemon.enabled` in tracked settings, `daemon.run_here` in the local overlay); this is the intended quiet-on-re-run behaviour → to revisit a decision, edit or delete the relevant flag and re-run.

## Notes

- **Idempotent**: running this skill multiple times is safe. Files are only created/updated when there's a real change.
- **Re-run after `/plugin update`**: `/plugin update` refreshes the plugin cache but does **not** re-sync rule files into `.claude/rules/`. Re-run this skill after every plugin update to pick up rule changes — otherwise projects keep running the old rule content.
- **Scope independence**: running at project scope does not affect other projects or the global config.
- **Runtime is per-repo, not per-scope**: Steps 3–8 follow the plugin's install scope (`user` writes to `~/.claude/`, `project` writes to `<repo-root>/.claude/`). Steps 9–13 always target the current working repo (cwd's git toplevel) regardless of install scope, because runtime artifacts (`.experts/`, daemon supervisor units) are inherently per-repo. Run `/lazy-core.install` from inside each repo where you want runtime to be set up.
- **Re-run after `git clone`**: rules/templates/`lazy.settings.json`/`lazy.runtime.sh` are committed into the repo (so `daemon.enabled` — Gate 1 — travels with the clone), but the daemon supervisor units (launchd plist / systemd service) and `daemon.run_here` (Gate 2) live in this checkout's gitignored overlay, not in the repo, so each clone decides for itself. Re-run this skill after cloning: it reads Gate 1 silently and asks Gate 2 once for this checkout. Answer Gate 2 "No" to keep the daemon off on this checkout.
- **Next steps shown to user**: if any rule was **created** or **updated**, remind the user to restart Claude Code (rules are loaded on session start).
