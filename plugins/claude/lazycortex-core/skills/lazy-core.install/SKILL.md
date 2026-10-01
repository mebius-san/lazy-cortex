---
name: lazy-core.install
description: "Run when the operator asks to set up lazycortex-core in a repo (or globally), or when core artifacts are missing — the plugin's rules are not in `.claude/rules/`, `lazy.settings.json` has no runtime section, `.experts/` is not initialised. Installs this plugin only; `/lazy-core.setup` is the one that runs every plugin's install. Never sets up the background daemon — that is `/lazy-core.daemon-setup`. Idempotent and quiet on re-run — decisions are persisted and never re-asked."
allowed-tools: Read, Write, Edit, AskUserQuestion, Skill, Bash(mkdir -p *), Bash(git rev-parse*), Bash(git init*), Bash(cp *), Bash(rm *), Bash(test *), Bash(ls *), Bash(find *), Bash(date *), Bash(diff *), Bash(cmp *), Bash(jq *), Bash(chmod *), Bash(launchctl *), Bash(systemctl *), Bash(python3 *), Bash(python *), Bash(py *), Bash("${LAZYCORTEX_PYTHON:-python3}" *), Agent
---
# Install lazycortex-core

Bootstrap the plugin in the right scope: copy every rule template shipped by the plugin into the target `rules/` directory, sync authoring templates into the consumer's `templates/core/` directory, and ensure the scaffold registry is in place.

## Execution discipline (MANDATORY — read before any action)

This skill has 22 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 0 — Verify Python ≥ 3.12 (floor)`
   - `Step 1 — Detect install scope`
   - `Step 2 — Determine paths`
   - `Step 3 — Sync rule templates`
   - `Step 4 — Sync authoring templates`
   - `Step 5 — Verify`
   - `Step 6 — Seed lazy.settings.json`
   - `Step 6.5 — Seed git-guard flags`
   - `Step 7 — Bootstrap .logs/, .runtime/, lazy.settings.local.json gitignore, and .lazyignore`
   - `Step 7.5 — Pin LF line endings in .gitattributes`
   - `Step 8 — Migrate stale lazycortex-log hook registrations`
   - `Step 9 — Bootstrap runtime defaults`
   - `Step 10 — Bootstrap experts directory`
   - `Step 10.5 — Bootstrap .memory/ directory`
   - `Step 10.7 — Install lazy-claude wrapper`
   - `Step 11 — Register expert candidates`
   - `Step 12 — Bootstrap built-in routines (expert pump, doctor tick, index guard, weekly autocheckup)`
   - `Step 12.5 — Restore externally-sourced working directories`
   - `Step 13 — Remove a stray supervisor unit`
   - `Step 13.5 — Configure expert-spawn sandbox in .runtime/sandbox.settings.json`
   - `Step 14 — Report`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `already-ignored`, `absent`, `skipped-per-user-choice`).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Decisions are remembered, never re-asked

This skill is **idempotent and quiet on re-run**. Every choice it makes is persisted, and on the next run the persisted value is read first and honoured silently — the user is asked again only when nothing is on record yet.

- **Plugin enabled = full functionality.** An enabled plugin is installed whole. There is no per-rule "install this rule?" prompt and no per-artifact opt-in — wanting the plugin means wanting its surface.
- **The daemon is not this skill's business.** The whole runtime layer — the `daemon` and `routines` sections, the built-in routines, `.experts/`, the expert registry, the spawn sandbox — is driven by `/lazy-runtime.tick` just as well as by a background daemon, so all of it installs here, ungated. `daemon.enabled` is seeded `false` when absent (Step 9c) and never asked; the supervisor unit, the `daemon.run_here` map and the metrics endpoint belong to `/lazy-core.daemon-setup`, which the operator runs on the rare occasion a project gets a daemon. The one daemon repair install keeps is Step 13: a supervisor unit on a checkout the project does not name is an error, and install removes it without asking.
- **Everything derivable is derived, not asked:** install scope (from where the plugin is *enabled* — see Step 1), expert git identity (a deterministic bot id).

## File-sync policy (applies to every file this skill writes)

Two classes of file and, inside the second, one class of value. Which policy applies follows from who owns the bytes, never from how large the diff is.

### Install-managed mirrors — overwrite on drift

Files copied verbatim out of the plugin cache: every rule under `rules/`, every authoring template, every rendered runtime shim. The plugin owns them end to end. A consumer who wants different content authors **their own** rule file or registers a `_local` scaffold entry — the mirror itself is not an editing surface, so a target that differs from the shipped source is a stale copy by construction.

1. **Absent** → copy. State `installed`.
2. **Byte-identical** → nothing. State `unchanged`.
3. **Bytes differ** → overwrite from the shipped source. State `refreshed`.

No diff preview, no merge, no question in any of the three. A no-longer-shipped file inside an owned namespace (orphan) is left in place silently (`kept-orphan`); this skill never deletes consumer files.

**The verdict is the script's, not yours.** `${CLAUDE_PLUGIN_ROOT}/bin/file_sync.py` byte-compares (`filecmp.cmp(shallow=False)`), writes, and re-compares each write before reporting it. Reading two files and judging them current is the defect this policy exists to prevent: an `unchanged` / `already-current` claim with no receipt behind it is a reporting defect, and a `failed` entry in a receipt means the write did not land — surface it, never restate it as applied.

Sole exception: `lazy-core.scaffold.md` wraps a consumer-owned `## Registry` block inside a plugin-owned file — see §5a under Step 3.

### Consumer-owned config — union in, ask only on contradiction

Files the consumer authors, where this skill contributes keys or sections: `settings.json`, `lazy.settings.json`, `.gitignore`, the sandbox and permission files, `pyproject.toml`-shaped config. Add what is missing, leave what is there byte-for-byte — except the values this plugin wrote itself, which the section below governs.

A **genuine conflict** — an existing value that directly opposes a required one (e.g. `sandbox.enabled: false` against a required `true`) — is the only case that asks. The raising step prints the four context items before the call (`lazy-core.skill-writing` § 11): **where** — `/lazy-core.install · Step <N> — <title>` and the target file path; **found** — the conflicting region quoted, with a unified diff of local against shipped; **why asking** — the local value contradicts the required one and the skill cannot tell which should survive; **answers** — `merge-shipped` writes the required value into the file now, `keep-local` leaves the file untouched and the step states its conflict outcome; nothing beyond the file itself is persisted, so the question returns on the next run while the contradiction stands. The call: `header` a short label, `question` naming the file and the key, options `merge-shipped` / `keep-local`, each with a description of its effect. "Conflict" means you cannot determine what should survive, not merely that the bytes differ.

### Install-managed values — compare content, refresh on drift

Inside a consumer-owned file, some values are the plugin's own writing: a routine's `paths` mask and `filter` block, an expert entry's `agent` and `aspects` pointers, the writer slots and role roster a review class seeds, a registration this skill created and still owns. The consumer owns the file; the plugin owns those values. A step that wrote such a value is the step that keeps it current.

1. **Absent** → write the shipped form. State `installed`.
2. **Matches the shipped form** → nothing. State `unchanged`.
3. **Differs from the shipped form** → rewrite the plugin-owned keys to it, silently. State `refreshed`.

**Presence is not currency.** A step that returns on `if <key> in <section>` accepts whatever a past version of this plugin wrote and can never correct it: the shipped default moves, the recorded value does not, and the consumer keeps a stale mask, a retired pointer, or a role set the plugin no longer composes. Every step that seeds a value MUST re-read what is on record and compare it against what it would write today. This holds at every depth — a section present with its own keys missing is a partial write to complete, not an entry to accept.

A stale shipped default is **not** a genuine conflict: the question of what should survive has an answer, and it is the shipped form. The conflict question is reached only when the recorded value is neither the shipped form nor derivable from the repo — a slot naming a role that exists in neither the shipped set nor the consumer's own `experts` registry.

**Where the consumer is meant to override**, the value records that it was seeded (`{"tier": …, "seeded_from": …}` in `agent_models`) and a bare recorded value is the operator's pin. Refresh reaches the seeded form only; an operator's own value is `kept-local` and never rewritten. A value with no such provenance marker is plugin-owned by default — the marker exists to carve out the operator's, not the reverse.

## Step 0: Verify Python ≥ 3.12 (floor)

Every plugin in this marketplace requires Python ≥ 3.12. This step runs first; on a machine where `python3` already meets the floor it is silent (one `python3 -V` invocation) and the install proceeds straight to Step 1. Per-plugin `<ns>.install` skills inherit this gate — they do NOT re-probe.

Probe the candidates in this order, one `Bash` call each, stopping at the first that qualifies: `Bash(python3 -V)`, `Bash(python -V)`, `Bash(py -3 -V)`. A candidate qualifies when the call exits 0, prints `Python X.Y.Z`, and the version is ≥ 3.12.0. A non-zero exit or a "Python was not found" message is the Windows Microsoft Store alias stub, not an interpreter — treat it as absent and move on. The first qualifying command is `<cmd>`.

No candidate qualifies → a missing or below-floor interpreter is an environment prerequisite, not a choice — do NOT open an `AskUserQuestion`. Print one line and stop:

> Python 3.12+ required (found `<best detected version or 'not found'>`). Install it, then re-run `/lazy-core.install`. macOS: `brew install python@3.12 && brew link python@3.12 --force`. Linux: `pyenv install 3.12 && pyenv global 3.12`. Windows: `winget install Python.Python.3.12` or the python.org installer.

State outcome `aborted-python-floor-not-met` and skip Steps 1–15.

`<cmd>` is `python3` → state outcome `python-floor-ok (<version>)` and proceed to Step 1; nothing is recorded.

`<cmd>` is anything else → every plugin call site runs `"${LAZYCORTEX_PYTHON:-python3}"`, so record the override in the gitignored `<repo-root>/.claude/settings.local.json` (`<repo-root>` from `Bash(git rev-parse --show-toplevel)`, the cwd outside git), running the verb under `<cmd>` itself:

```
Bash(<cmd> "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" install-phase python-env --command '<cmd>' --cwd <repo-root>)
```

The verb merges `env.LAZYCORTEX_PYTHON` into the file and never overwrites a value already there; a multi-word `<cmd>` (`py -3`) is recorded as that interpreter's absolute path, since call sites expand the variable as one word. It prints `python-env: <outcome>`:

- `unchanged` / `kept-local` → the session already carries the override: state `python-floor-ok (<version>, <cmd>)` and proceed to Step 1.
- `recorded` → the value reaches Claude Code only in a new session, and every later step runs through the variable. Print one line and stop: `Recorded LAZYCORTEX_PYTHON for <cmd> in .claude/settings.local.json — restart Claude Code, then re-run /lazy-core.install.` State outcome `python-env-recorded` and skip Steps 1–15.

When raising the floor in the future, bump this step's numeric threshold in the same edit as any other floor-bearing reference.

## Step 1: Detect install scope

Scope = **where the plugin is actually enabled**, not where `/plugin install` last ran. The `scope` field in `installed_plugins.json` records the install command's origin (a shared-cache download registration), which drifts from the activation scope — a plugin enabled per-project in `.claude/settings.json` can carry an install record of `scope: "user"`. Enablement is the source of truth for where config belongs.

Resolve it with the shared helper, which reads `enabledPlugins` from the project settings first, then the global settings, and falls back to the install record's own `scope` only when neither settings file enables the plugin:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" detect-scope lazycortex-core@lazycortex)
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

Enumerate every rule file shipped by the plugin via `Bash(ls <installPath>/rules/*.md)` — never hardcode filenames. `<installPath>` is what `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-core` prints: the authoring repo's own `plugins/claude/lazycortex-core/` when this checkout ships the plugin, else the daemon's exported plugin dir, else the newest cached install. Never read `installed_plugins.json` for it by hand — in a repo that authors the plugin that hands back the previous publish instead of the sources at hand, and every role, rule, template, or tier row added since is silently missed.

For each source file `<installPath>/rules/<name>.md`, the target is:

| Scope | Rule destination | Templates destination |
|---|---|---|
| `user` | `~/.claude/rules/<name>.md` | `~/.claude/templates/core/` |
| `project` | `<repo-root>/.claude/rules/<name>.md` | `<repo-root>/.claude/templates/core/` |

Project root is `git rev-parse --show-toplevel` (or current working directory if not in a git repo — warn the user).

If the glob returns zero files, abort and tell the user the plugin cache is empty — they likely need to run `/plugin update lazycortex-core@lazycortex` first.

## Step 3: Sync rule templates

An enabled plugin installs its whole rule surface — the rules are install-managed mirrors, so the **File-sync policy** applies: absent → copy, identical → nothing, different → overwrite. No per-rule prompt of any kind.

### Enumerate owned namespaces

Owned namespaces: the plugin name minus the `lazycortex-` prefix (so `lazycortex-core` → `lazy-core`), plus every unique `<ns>.` prefix appearing in source rule filenames under `<installPath>/rules/` (for this plugin that includes both `lazy-core` and `lazy-guard`).

### Run the script — it is the whole step

The mirror is script-driven end to end: byte comparison decides, the script writes, and it verifies each write. There is nothing here for you to judge. Run (one `--owned-glob` per owned namespace):

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/file_sync.py" --src <installPath>/rules --dst <targetRulesDir> --copy-diverged --exclude lazy-core.scaffold.md --owned-glob 'lazy-core.*.md' --owned-glob 'lazy-guard.*.md')
```

The script creates the destination directory, copies absent targets (**installed**), byte-compares the rest (**unchanged**), overwrites every stale target from the shipped source (**refreshed**), and reports owned targets with no source as **kept-orphan** (left in place). Exit code 3 with a non-empty `failed` array means a write did not verify — report it as `failed: <path>`, never as applied.

`lazy-core.scaffold.md` is excluded here and handled by §5a below. Target files outside this plugin's owned namespaces (other plugins, user-authored rules) are never touched and never reported as orphans.

**Quote the receipt's `counts` line in the report.** It is the evidence for whatever this step claims; an `already-current` verdict with no receipt behind it is a reporting defect.

### `lazy-core.scaffold.md` — registry-block exemption (§5a)

`lazy-core.scaffold.md` is the one mirror with consumer state inside it: its `## Registry` fenced block is **primitive-owned** — written only by `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" scaffold`, and holding the consumer's `_local` key alongside every installed plugin's key. Blind-overwriting it would wipe that. The prose and frontmatter around the block are plugin-owned like any other mirror.

One deterministic primitive resolves both halves — it takes the shipped file whole and grafts the consumer's existing block body back in:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" <core-cli> scaffold sync-rule --src <installPath>/rules/lazy-core.scaffold.md --registry <targetRulesDir>/lazy-core.scaffold.md)
```

`<core-cli>` is `<installPath>/bin/lazycortex-core`, run through the interpreter like every other verb — the file carries no exec bit. Status is `installed` (target absent — shipped file lands with its empty `{}` block, Step 4 then populates it), `unchanged`, `refreshed` (stale prose replaced, block carried over), `failed` (the write did not verify), or `error` (the consumer's block does not parse — report it and leave the file alone). Never hand-merge this file: surgical per-key registry writes are `scaffold-sync`'s job, and the prose is the primitive's.

## Step 4: Sync authoring templates

Authoring-template copy **and** scaffold-registry population are both done by `lazy-core.scaffold-sync`, invoked for `lazycortex-core` itself — core registers through the same path as any other plugin (dogfood).

Resolve this plugin's own `<installPath>` (via `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-core`, the same resolution the rules mirror used above) and the detected `<scope>` (`project` / `user`), then dispatch:

```
Skill(skill: "lazycortex-core:lazy-core.scaffold-sync", args: "plugin=lazycortex-core installPath=<installPath> scope=<scope>")
```

The skill discovers `<installPath>/templates/core/scaffold.entries.json`, copies `templates/core/*` (excluding the manifest) into `<consumerScope>/.claude/templates/core/` as install-managed mirrors (stale targets overwritten from the shipped source), and upserts the `lazycortex-core` registry key from the manifest via `scaffold upsert` (surgical — the consumer's `_local` and any sibling-plugin keys stay byte-for-byte; per §5a the rest of `lazy-core.scaffold.md` is untouched).

### Outcome

The `scaffold-sync` report: per-template copy states plus the registry upsert status.

## Step 5: Verify

For each installed rule file:

- Read it back and confirm its `---` frontmatter parses
- Confirm its size against the `lazy-core.rule-writing` § 2 budget: a rule carrying `always_loaded:` must be under 3 KB; a `paths:`-scoped rule gets a WARN above 10 KB and a FAIL above 25 KB, and is never measured against the 3 KB line

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

### Entry shape — a seed says so, a pin does not

An entry this step writes is a **seed**, and it records that it is one:

```json
"Explore": {"tier": "haiku", "seeded_from": "haiku"}
```

`seeded_from` holds the shipped default that was in force when the entry was written. A bare string (`"Explore": "opus"`) is the **operator's pin** — written by hand or by the wizard, never by this step, and never rewritten by it.

The two fields together say whether a seed is still untouched: `tier == seeded_from` means nobody has edited it since it was seeded, so a moved shipped default may replace it. `tier != seeded_from` means the operator edited a seeded entry — it is a pin from that moment on, and the marker only records where it started.

Per-key semantics (write back only if anything changed):

- **absent** in `agent_models._builtin` → add the seed entry with the JSON's tier in both fields. State **added**.
- **seed, `tier` equals the JSON's** → leave untouched. State **unchanged**.
- **seed, untouched (`tier == seeded_from`), JSON's default has moved** → rewrite both fields to the JSON's tier, silently. State **refreshed** (report the old tier alongside the new). This is the install-managed-value rule from the File-sync policy: a stale shipped default is not the operator's choice and not a conflict.
- **seed, edited (`tier != seeded_from`)** → leave untouched. State **kept-local**.
- **bare string** → the operator's pin. Leave untouched. State **kept-local**.

**Migrating a pre-provenance entry.** A bare string predating this shape is ambiguous. Resolve it once, in this step: read the shipped default's history for that key (`git log -p` over `default-tiers.json` in the plugin's own checkout when it is available; otherwise the current default alone). A bare value equal to the current default, or to any value that default previously held, was a seed — convert it to the seed shape and apply the rules above. Any other value was never a shipped default, so it is the operator's — leave it bare. When the history is unreachable, only the current-default match converts; the rest stay bare and stay `kept-local`, which errs toward the operator.

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

## Step 6.5: Seed git-guard flags

Make the two `lazy-core.git-guard` behaviours visible and tunable in the consumer's tracked settings. Both default to `true` in code; seeding them writes the defaults down so the operator can flip either one without reading the hook.

**Scope:** project only. The guard resolves its config from the repo root, so a `git` section at `user` scope is never read. At `user` scope, state `skipped-user-scope` and move on.

**Target:** `<repo-root>/.claude/lazy.settings.json`, section `git`.

Ensure the section exists with `"_version": 1`, then apply per-key semantics — **absent** → write the default, **present** → leave the operator's value untouched (`kept-local`, report the value):

These three are **operator-owned switches**, not install-managed values: absent-only is the correct policy here and stays. The distinction matters because the File-sync policy's refresh rule looks identical at the call site — the test is whether the plugin or the operator owns the value's meaning. A flag the operator flips to change behaviour is theirs; a pointer, mask, or roster this skill composed is the plugin's.

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Master kill-switch for the whole hook. |
| `pathspec_enabled` | `true` | Commits must name their paths; the index stays the operator's. |
| `mutex_enabled` | `true` | Staging-window mutex — dormant while `pathspec_enabled` is true. |

`pathspec_enabled` defaulting to `true` is a **behaviour change** for a repo upgrading from an older plugin version: agents lose bare `git commit`, `git add` with content, `git rm`, and `git mv`. Say so in the report line, and name the rollback: set `pathspec_enabled` to `false` to restore mutex-only behaviour. Do not ask — the default is deliberate and the flag is one edit away.

Report outcome: `git.<key> = <value> (<added|kept-local>)`, or `skipped-user-scope`.

## Step 7: Bootstrap .logs/, .runtime/, lazy.settings.local.json gitignore, and .lazyignore

Create `.logs/` and `.runtime/` at the repo root, each carrying its own self-ignoring `.gitignore` (so a renamed or newly-added service directory never depends on the consumer's tracked root `.gitignore` being revisited), ensure `.gitignore` also lists `.claude/lazy.settings.local.json` (the gitignored personal overlay companion to the tracked `lazy.settings.json`), and seed a default `.lazyignore` at the repo root when one is absent.

- `.logs/` — gitignored runtime journal (daemon output, recall logs, commit-recorder feed).
- `.runtime/` — gitignored non-log daemon state (currently `state.json` carrying `last_run` / `git_watch` / `daemon_halted`).
- `.claude/lazy.settings.local.json` — gitignored personal-overlay file that `lazy_settings.load_section` deep-merges onto the tracked `lazy.settings.json`. No directory is created — the file is opt-in and materializes only when the consumer adds a local override. The `.gitignore` slot is reserved so accidental commits are impossible.
- `.lazyignore` — tracked git excludes file carrying the *extra* excludes (on top of `.gitignore`) that every tree-walking routine honours via git's ignore engine: venvs, `node_modules`, `__pycache__`, in-tree worktrees. Seeded from the shipped template only when absent — the consumer's own copy is authoritative and never overwritten.

All four concerns are handled by three helpers. This step runs unconditionally (not gated on runtime-setup confirmation); the `.logs/` half is absorbed from the retired `lazy-log.install` skill.

Run via:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" install-phase logs)
```

Outcome per helper: `bootstrapped` (something was created/appended) or `already-present` for the first two; `seeded` / `already-present` / `template-missing` for `.lazyignore`.

## Step 7.5: Pin LF line endings in .gitattributes

Ensure `<repo>/.gitattributes` carries `* text=auto eol=lf` as its first rule, so git on every machine — any OS, any `core.autocrlf` — stores and checks out text files with LF, and a checkout synced between Windows and macOS never gets CRLF from git. The line goes first because a later, more specific rule wins; operator lines are never removed or reordered, and a re-run leaves the file byte-identical. Runs unconditionally, like Step 7.

Run via:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" install-phase gitattributes)
```

The verb prints two lines. `.gitattributes: created` / `updated` / `already-present`. `renormalize: needed` / `not-needed` — `needed` means the index already holds CRLF text files (`git ls-files --eol` reports `i/crlf`), which the new rule does not rewrite on its own. On `needed`, report a follow-up for the operator: run `git add --renormalize .` once and commit the result. Never run it from this skill — it stages content, and the index is the operator's.

## Step 8: Migrate stale lazycortex-log hook registrations

The `lazycortex-log` plugin was retired and folded into `lazycortex-core`. Its `hooks/lazy-log.commit-recorder.py` was registered under `${CLAUDE_PLUGIN_ROOT}/lazycortex-log/hooks/` in consumer `settings.json` files. This step strips those stale registrations from the four standard settings paths so the retired plugin path no longer appears in the consumer's hook pipeline.

Run via:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" install-phase log-hooks)
```

Idempotent: a second run on already-clean files is a no-op. Report one line per path with its outcome word (`migrated` or `no-stale-entries`).

## Step 9: Bootstrap runtime defaults

Steps 9–13.5 set up the per-repo runtime layer (`.experts/`, expert registry, routines, spawn sandbox). They operate on the **current working repo**, independent of the plugin's install scope — runtime artifacts are always per-repo, even when the plugin is installed at user scope.

For Steps 9–13.5, `<repo-root>` is the cwd's git toplevel (resolved in 9a, initialized in 9b when the cwd is not yet a repo), even if Step 1 detected install scope as `user`.

### 9a. Resolve the runtime repo

Run `git rev-parse --show-toplevel` in cwd. If it succeeds, set `<repo-root>` to the returned path and `is_git = true`. If it fails (cwd is not inside a git repo), set `<repo-root>` to cwd and `is_git = false`. Do NOT prompt to initialize git here — that question is 9b's.

### 9b. Ensure a repo root for the runtime layer

The runtime layer is **not** gated on the daemon. Routines, `.experts/`, the expert registry, and the spawn sandbox are what `/lazy-runtime.tick` drives on a checkout with no daemon at all, so every one of Steps 9c–13.5 runs regardless of `daemon.enabled`; the flag withholds only the supervisor unit and the metrics endpoint, both `/lazy-core.daemon-setup`'s. There is no project-policy question here and none is ever asked — `daemon.enabled` is seeded `false` by 9c when absent.

What the runtime layer does need is a repo: `.experts/`, the routine commits, and the tracked settings all live in one. When `is_git = false` (from 9a), ask once:

```
Context (print before asking):
- Where: /lazy-core.install · Step 9 — Bootstrap runtime defaults (9b); target <cwd>
- Found: `git rev-parse --show-toplevel` failed in <cwd> — the directory is not inside a git repository
- Why asking: the runtime layer (`.experts/`, the tracked `lazy.settings.json`, the commits routines make) needs a repo, with or without a background daemon; creating one is the operator's call
- Answers: `Initialize git here` — runs `git init` in <cwd> now, Steps 9c–13.5 proceed; `Skip — no runtime setup this run` — nothing written, Steps 9c–13.5 state `skipped-not-in-git-repo`; not persisted, asked again on the next run in a non-repo directory
AskUserQuestion:
  header: "Init git?"
  question: "Initialize a git repository in <cwd> so the lazycortex runtime config can be tracked?"
  options:
    - "Initialize git here" — "Runs `git init` here; runtime setup continues in this run."
    - "Skip — no runtime setup this run" — "Leaves the directory as is; re-run `/lazy-core.install` after `git init`."
```

  - `Initialize git here` → `Bash(git init)` in cwd, keep `<repo-root>` = cwd, continue with 9c.
  - `Skip — no runtime setup this run` → mark Steps 9c–13.5 with outcome `skipped-not-in-git-repo`, go to Step 14.

When `is_git = true`, continue straight to 9c and run Steps 10–13.5.

### 9c. Write the flat `daemon` + `routines` sections

The runtime daemon reads its config from **flat top-level section keys** — `runtime_daemon.py` calls `load_section(path, "daemon")` and `load_section(path, "routines")` directly, and `expert_runtime.register_routine` writes the flat `routines` section. Seed those two sections (never a nested `lazy-core.runtime` object — nothing reads that shape).

Seed the default daemon keys with `setdefault` (so any existing value is preserved — never overwrite), seed an empty `routines` section when absent, and derive the `daemon.git` block from the checkout. `enabled` is one of the seeded defaults and its default is `false`: a project declares itself daemon-supervised by writing the flag, and until it does, the runtime still installs whole and is ticked by hand.

```bash
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" install-phase --cwd <repo-root> daemon-defaults)
```

`daemon.git` is **derived, never asked** — `base_branch` is the checkout's current branch, and `remote_sync` is `"pull_push"` when the checkout has an `origin` remote. A daemon commits routine output into its own checkout; without a push that output reaches no other consumer, and a runtime checkout outside any file-sync has no second delivery channel. A checkout without `origin` gets `base_branch` alone and never pushes. `post_push_hook` is operator territory and is never seeded. The block is written only when absent or `null`, so a hand-tuned block survives every re-run — including one that deliberately omits `remote_sync`.

This runs here, not in `/lazy-core.daemon-setup`: `daemon.git` is config every machine driving the project needs, while that skill's `run_here` gate names the one that actually drives it. Gating the block on `run_here` would leave it unseeded on exactly the machines that clone the repo and expect the config to travel with it.

State **bootstrapped** if any default key or the routines section was newly written; **already-present** if everything was already present; **skipped-not-in-git-repo** if 9b left the checkout without a repo. Report the `daemon.git` outcome verbatim from the receipt: **seeded**, **kept-local**, or **skipped-no-branch** (detached `HEAD` — re-run after checking out a branch).

## Step 10: Bootstrap experts directory

If Step 9 was skipped (outcome `skipped-not-in-git-repo`), inherit the same outcome and skip this step.

Otherwise, perform the following three idempotent operations:

### Ensure `lazy.runtime.sh` shim

The shim is content-tracked so consumers pick up new shim features (e.g. the `--dev-mode` flag added in lazy-core 0.18) on re-install without manual cleanup.

The shim is install-managed (never locally edited) — sync it with the deterministic triage script, which copies on absence, refreshes on any byte difference, and reports the state:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/file_sync.py" --src ${CLAUDE_PLUGIN_ROOT}/templates/runtime/lazy.runtime.sh --dst <repo-root>/.claude/bin/lazy.runtime.sh --copy-diverged)
```

State = the receipt's state verbatim: **installed** (was absent), **refreshed** (differed, overwritten), or **unchanged**.

The shim resolves the latest `lazycortex-core/bin/runner` from the plugin cache at exec time, so supervisor units don't need re-rendering after `/plugin update`. Re-copying on content drift is safe — the shim's interface is stable (positional repo-root + repeatable `--plugin-dir`; the `--dev-mode`, `--login-shell`, and repeatable `--env-file <path>` flags are additive and stripped by the shim before the runner exec).

### Ensure `lazy.settings.json[experts]`

Check whether the `experts` section exists in `<repo-root>/.claude/lazy.settings.json`. If missing, create it: `Bash(echo '{}' | "${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-set experts --cwd <repo-root>)` writes the section with its `_version` stamp.

State **created** if written; **already-present** if it existed.

### Ensure `.gitignore` entries

`.experts/` does not exist yet at this point in a fresh install — it materializes lazily, the first time `dispatch_job` creates a job bundle, and drops its own self-ignoring `.gitignore` into itself right then (independent of this skill ever having run). This substep is belt-and-suspenders for a repo that already has an `.experts/` tree from before that runtime change shipped: read `<repo-root>/.gitignore` (or treat as empty if missing) and ensure it contains the following line:
- `.experts/`

`.logs/` and `.runtime/` are owned by Step 7's `bootstrap_logs_dir` helper and need no entry here. The whole `.experts/` tree is runtime scratch (job queue, subprocess locks) — ignore the directory, not just `.experts/.jobs/`. If a legacy narrower `.experts/.jobs/` line is present, replace it with `.experts/`; if no `.experts/` line is present, append it with `Edit` (or `Write` if the file was missing). State **updated** if appended or replaced; **already-present** if `.experts/` was already there.

`.memory/` carries no such entry, root or local — it is tracked in git by design (Step 10.5), the one service directory that is never gitignored.

## Step 10.5: Bootstrap .memory/ directory

If Step 9 resolved no repo (outcome `skipped-not-in-git-repo`), inherit that outcome and skip this step.

Otherwise, ensure `.memory/` exists at the repo root and strip any legacy `!.memory/` line from `.gitignore` (older versions of this skill wrote a defensive un-ignore line; the line was selective paranoia and is now retired — memory notes track in git the normal way):

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" install-phase memory-dir)
```

Outcome: `bootstrapped` (dir created and/or legacy line stripped) or `already-present` (dir existed and no legacy line present).

## Step 10.7: Install lazy-claude wrapper

Host-scoped and unconditional — runs at every install scope, with or without a git repo, with or without the daemon: the wrapper serves third-party daemons in other repositories, not this checkout. It gives them the subscription rate-limit guard: a headless `claude -p` call under a raised host-local rate-limit flag exits `75` without spawning, and a stream-json call feeds the frames it sees back into the shared flag. A daemon opts in by replacing the word `claude` in its launch command with the absolute wrapper path.

The wrapper is install-managed (never locally edited). Compare first, so a host already carrying the shipped bytes sees no sync call at all:

```
Bash(cmp -s "${CLAUDE_PLUGIN_ROOT}/bin/lazy_claude.py" $HOME/.local/bin/lazy-claude)
```

Exit 0 → state **unchanged** and continue to Step 11. Otherwise sync it with the same deterministic triage script as the runtime shim, which copies on absence, refreshes on any byte difference, sets the executable bit, and reports the state:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/file_sync.py" --src ${CLAUDE_PLUGIN_ROOT}/bin/lazy_claude.py --dst $HOME/.local/bin/lazy-claude --copy-diverged --chmod-x)
```

State = the receipt's state verbatim: **installed** (was absent) or **refreshed** (differed, overwritten). Re-copying on drift is safe — the wrapper is self-contained (stdlib only, no plugin imports) and its interface is the `claude` CLI's own.

## Step 11: Register expert candidates

If Step 9 resolved no repo (outcome `skipped-not-in-git-repo`), inherit that outcome and skip this step (there is no settings file to write).

Register every expert candidate the enabled plugins ship — there is no per-candidate prompt and no scan confirmation; an enabled plugin's experts are installed whole.

### 1. Discover candidates

List agent files that may carry `expert_protocol:` frontmatter at three scopes, one `Bash(ls …)` per pattern below — never `find`, a walk, or a glob over the plugin cache (`~/.claude/plugins/cache/*/*/*/` lists every version ever installed, and the stale ones sort first). Installed plugins come from the plugin registry, each resolved to the one directory its sources are read from:

- `Bash(jq -r '.plugins | keys[]' ~/.claude/plugins/installed_plugins.json)` — every installed `<plugin>@<marketplace>` key; for each, `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" plugin-root <plugin> --cwd <repo-root>)` prints the authored sources in a checkout that ships the plugin, else the newest cached version; then `Bash(ls <printed root>/agents/*.md)`. A non-zero exit means the plugin ships no resolvable sources — skip it.
- `~/.claude/agents/*.md`
- `<repo-root>/.claude/agents/*.md`

For each candidate file, `Read` its frontmatter. If `expert_protocol:` is present, record:
- `source_scope`: `plugin`, `user`, or `project`
- `plugin` (the registry key's plugin name, or `user`/`project` for the latter two scopes)
- `agent_name`: the basename of the file without `.md`
- `expert_protocol_ref`: the value of `expert_protocol:` (a protocol reference string)

Resolve the protocol file via:

```bash
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" resolve-ref '<expert_protocol_ref>' --category protocols --cwd <repo-root>)
```

The verb prints one JSON row `{ref, ok, path, error}` per reference. If the row reads `"ok": false` (the verb exits 1 and `error` names the reason), skip that candidate and record it in the report as `protocol-unresolvable`.

If no candidates are found after scanning all three scopes, state **no-scanned-candidates** — the built-in candidate below still registers, so proceed to § 1b, not to Step 12.

### 1b. Built-in candidates: the runtime doctor and the autocheckup agent

`lazycortex-core` ships two dispatchable agents that carry no `expert_protocol:` frontmatter and are therefore invisible to the scan. Their dispatch config still lives in settings like every other expert's — the runtime resolves agent and model from the expert entry and `agent_models`, never from code defaults.

Append both to the candidate list unconditionally:

- `agent_name`: `lazy-runtime.doctor` (expert key `runtime.doctor`) — `plugin`: `lazycortex-core`; no protocol (the doctor routine supplies its context bundle directly; there is nothing to resolve).
- `agent_name`: `lazy-core.autocheckup` (expert key `core.autocheckup`) — `plugin`: `lazycortex-core`; no protocol (the weekly `lazy-core.autocheckup` schedule routine — seeded by Step 12's bootstrap — dispatches it with a bare `{"repo": "."}` request).

Each then flows through §§ 2–4 exactly like a scanned candidate (skipped if already registered, bot `git_author`), with one addition these two candidates carry and a scanned one does not: their entry is `{agent, git_author, can_commit_in_repo: true}`. Both exist to commit — the doctor commits the reverts and the system-noise cleanups it decides on, the autocheckup commits the mechanical fixes it applied — and without the flag the pump appends the no-commit clause and their whole output strands. Unlike the other install-managed fields, this one is seeded on creation only: an existing entry carrying an explicit `false` is the operator's choice and stays.

Additionally, ensure lazycortex-core's own agent-model tiers — the doctor's included — exist in the **project** `agent_models.lazycortex` (the expert runtime resolves models from `<repo-root>/.claude/lazy.settings.json` only). Dogfood the shared seeding primitive instead of hand-rolling the SOT lookup (same pattern as Step 4 dispatching `lazy-core.scaffold-sync`):

```
Skill(skill: "lazycortex-core:lazy-core.agent-models-seed", args: "prefix=lazycortex-core scope=project")
```

`scope=project` (NOT Step 1's install scope) because Steps 9–13.5 always target the runtime repo and the doctor's tier must land in `<repo-root>/.claude/lazy.settings.json` for expert-runtime resolution. The primitive reads the same SOT (`default-tiers.json`, same missing-file FAIL as Step 6), seeds every `lazycortex-core:<agent>` key — the doctor plus its sibling agents — under the `lazycortex` group, and never clobbers an operator override. State per the primitive's report: **tier-added** (entries seeded), **tier-kept-local** (operator overrides preserved), or **unchanged**. Fold its per-key block into the Step 14 report.

### 2. Filter already-registered candidates

Load the `experts` section of `<repo-root>/.claude/lazy.settings.json`: `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-get experts --cwd <repo-root>)`. Derive each candidate's **expert key** per § 3 first, then compare — never merely test for presence:

- **Key absent** → a candidate to write in § 4. State **to-register**.
- **Key present, its install-managed fields matching what § 3 would derive** → nothing. State **already-registered**.
- **Key present, an install-managed field missing or differing** → complete or correct that field in place, silently, leaving every other field of the entry alone. State **refreshed**. Install-managed here means the fields § 3 derives — `agent` and `git_author`; a field the operator owns (`model`, `workspace`, `merge`, `can_commit_in_repo`, `arguments`) is never touched.

A present key whose entry is missing `agent` or points at an agent this plugin no longer ships is exactly the case the File-sync policy's install-managed-value rule covers: it was written by an older version of this step and nothing else will ever fix it. A candidate still registered under the pre-canon key (its `agent_name` verbatim) is NOT re-registered here — renaming an existing key is `lazy-core.doctor` Phase 2.55's job, not the installer's.

If no candidate is left to register or refresh, state **all-already-registered** and proceed to Step 12.

### 3. Derive each entry — no questions

For every remaining candidate:

- **expert key** = its `agent_name` with the leading `lazy-` stripped: `lazy-runtime.doctor` becomes `runtime.doctor`, `lazy-core.autocheckup` becomes `core.autocheckup`. The key is `<domain>.<role>` per `lazy-core.hygiene` § Naming — an expert key names a composition of domain and role, not the artifact serving it, so it never carries the plugin namespace the way the agent file does. The `agent` field below is what still points at the namespaced artifact. An `agent_name` with no `lazy-` prefix is already in that shape and is used verbatim.
- **git_author** = a deterministic bot identity, NOT the operator's `git config`: `{name: <expert key>, email: <expert key>@bot.invalid}`. The daemon distinguishes expert commits from operator commits by this email and runs loop-detection over it — reusing the human's identity would make operator commits look like bot commits and break that safety net. The domain is always `@bot.invalid` (RFC 2606 reserves `.invalid`, so the address is undeliverable by construction, and consumers that classify commits by the `@bot.` substring recognise it as-is).

### 4. Write all candidates to `lazy.settings.json[experts]`

For each candidate, merge the new entry via (the verb reads and writes the tracked file only, so the local overlay never leaks into it):

```bash
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-set experts --key '<expert_key>' --value '{"agent": "<plugin>:<agent_name>", "git_author": {"name": "<expert_key>", "email": "<expert_key>@bot.invalid"}}' --cwd <repo-root>)
```

The two names differ on purpose: the key is the § 3 `<domain>.<role>` form, the `agent` value keeps the artifact's own namespaced name.

State one line per candidate: `<expert_key>: registered`.

## Step 12: Bootstrap built-in routines (expert pump, doctor tick, index guard, weekly autocheckup)

If Step 9 was skipped (outcome `skipped-not-in-git-repo`), inherit the same outcome and skip this step. A registered routine is not daemon-only config: `/lazy-runtime.tick` runs the same set, in the same priority order, on a checkout that never starts a daemon.

Otherwise, check one condition: the `experts` section of `<repo-root>/.claude/lazy.settings.json` contains at least one expert entry (a key that is not `_version` and whose value is a dict).

Run the bootstrap whenever it holds — including on a repository that already has the routines. An existing entry is reconciled rather than skipped: a default key the entry predates is filled in (a repository installed before `hooks_enabled` existed would otherwise keep an expert-spawn allow-list nobody ever set, and the secret scan would stay off there forever), and the one key the built-ins claim as their own — the autocheckup's `type`, without which the daemon cannot tell how to run the entry at all — is corrected to the shipped value. Every other value the operator has set, empty list included, is never touched.

```bash
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" routines-bootstrap --cwd <repo-root>)
```

State **registered** if a routine was added; **refreshed** if an existing routine gained a default key it predated or had an owned key corrected; **unchanged** if nothing moved; **skipped-no-experts** if the condition was false.

## Step 12.5: Restore externally-sourced working directories

A repository may declare working directories it does not carry in git — bulk data, an inbox, secrets — in the tracked `external_dirs.paths` list. A fresh clone has the declaration but not the directories; each checkout records where they come from on this machine in its own gitignored overlay under `external_dirs.root`. Without that, a declared inbox never resolves and its routine can never dispatch.

Read the state first — never ask what is already on record:

```bash
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" external-dirs --cwd <repo-root> status)
```

- Output `no-declaration` → state **no-declaration** and continue to Step 13. Do NOT ask. (Optionally, when the repo registers an `inbox` routine whose `inbox_dir` is absent from the tree, report it as an INFO line in Step 14 so the operator knows the option exists — still no question.)
- Output `configured` → apply silently and report the per-path outcome. Do NOT ask.
- Output `in-place` → state **in-place** and continue to Step 13. Do NOT ask, do NOT apply: every declared path already exists here as a real directory, so this checkout is the source the others link from (the interactive copy of the project, typically).
- Output `declined` → state **declined-on-record** and continue to Step 13. Do NOT ask.
- Output `unconfigured` → ask **once**:

```
Context (print before asking):
- Where: /lazy-core.install · Step 12.5 — Restore externally-sourced working directories; target <repo-root>/.claude/lazy.settings.local.json (`external_dirs.root`)
- Found: tracked `external_dirs.paths` declares <N> director(y/ies): <comma-joined paths>; this checkout's local overlay has neither `external_dirs.root` nor `declined` (probe: `unconfigured`)
- Why asking: where those directories live on this machine is per-checkout and recorded nowhere (e.g. the interactive copy of this project)
- Answers: `Link them from a source root — I'll give the absolute path` — a follow-up takes the absolute path, persisted as `external_dirs.root` in the gitignored local overlay, and the declared paths are linked from it now; `Leave as is — don't ask again` — persists `external_dirs.declined = true` in the local overlay, the directories stay absent and any routine that needs one fails loudly on its next tick; never re-asked either way (delete `declined` to be asked again)
AskUserQuestion:
  header: "External dirs"
  question: "This repo declares <N> working director(y/ies) it does not carry in git (<comma-joined paths>). Where are they on this machine?"
  options:
    - "Link them from a source root — I'll give the absolute path" — "Next question asks for the source root; recorded for this checkout only, links created now."
    - "Leave as is — don't ask again" — "Records the decision in the local overlay; the declared directories stay absent."
```

On the first option, ask one follow-up for the absolute path, then persist and apply:

```bash
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" external-dirs --cwd <repo-root> set-root '<operator-supplied absolute path>')
```

On `Leave as is`, write `declined` into the same local overlay with `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-set external_dirs --key declined --value true --scope local --cwd <repo-root>)` and skip the apply.

Then, for `configured` and for a freshly-supplied root, apply the repair — the verb prints one JSON row `{path, status, action}` per path:

```bash
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" external-dirs --cwd <repo-root> apply)
```

`apply` never removes a real directory: a declared path occupied by operator content is reported as `skipped (was not_a_symlink)` and left alone. A path the filesystem refused to link is reported the same way, with the reason appended to the `was …` status. Surface every `skipped` line in Step 14 — those states need a human.

The repair outcome comes from the actions, not from the probe: **linked** when any record is `linked` or `relinked`, **unchanged** when every record is `unchanged` or `skipped`. (`configured` is the probe's word for "a source root is on record", never a step outcome.)

Then check that git cannot see what the repair just planted. Run this **after** the apply, never before it — a declared path that is not in the tree yet is classified the same way it will be once the link exists, but the operator can only be shown a real diff against a real slot:

```bash
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" external-dirs --cwd <repo-root> fix-ignore)
```

The verb prints `{"rows": [...], "proposed": [...]}` — one row `{path, status, source, gitignored, ignore_rule}` per declared path, and the `.gitignore` lines still missing. An empty `proposed` list → state **ignores-ok** and continue. Otherwise every proposed line is anchored (`/Data`, not `Data`) so it covers the declared slot and no same-named path deeper in the tree, and the two `ignore_rule` values need different explanations to the operator:

- `absent` — no rule covers the name at all.
- `dir_only` — a rule covers the name as a directory (`Data/`), and the repair planted a symlink, which git classifies as a file. The existing line is not wrong and is not touched; the anchored slashless line is added next to it.

`.gitignore` is a tracked file, so this is never a silent write. Ask once, quoting the exact lines:

```
Context (print before asking):
- Where: /lazy-core.install · Step 12.5 — Restore externally-sourced working directories (ignore coverage); target <repo-root>/.gitignore
- Found: git can see the just-linked director(y/ies) <comma-joined paths>; proposed lines: <the proposed lines, one per line, each with its reason — 'no rule' or 'existing <path>/ rule matches directories only, not the symlink'>
- Why asking: `.gitignore` is a tracked file — appending to it is never a silent write
- Answers: `Append the lines` — appends exactly the proposed lines now, existing lines untouched, file left modified and uncommitted; `Leave .gitignore as is` — nothing written, the links stay visible to git, the working tree stays dirty and a daemon on this checkout halts with `uncommitted_changes` on its first tick; not persisted, asked again on the next run while the lines are missing
AskUserQuestion:
  header: "Ignore links?"
  question: "git can see the external director(y/ies) just linked (<comma-joined paths>). Append <N> line(s) to <repo-root>/.gitignore?"
  options:
    - "Append the lines" — "Appends exactly the proposed lines; existing lines untouched."
    - "Leave .gitignore as is" — "Links stay visible to git; the daemon halts with `uncommitted_changes` on its first tick."
```

On **Append the lines**:

```bash
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" external-dirs --cwd <repo-root> fix-ignore --apply)
```

State **ignores-updated** and report the `appended` lines from the verb's JSON in Step 14. `.gitignore` is left modified and uncommitted — the operator commits it with whatever else this install changed.

On **Leave .gitignore as is**, state **ignores-declined** and carry one WARN line into Step 14 naming each still-visible path and the consequence: the tree stays dirty and the daemon halts on its first tick.

Outcome: `no-declaration` / `linked` / `unchanged` / `in-place` / `declined-on-record` / `ignores-ok` / `ignores-updated` / `ignores-declined`. The repair outcome and the ignore-coverage outcome are both stated — `linked, ignores-updated` is a normal pair.

## Step 13: Remove a stray supervisor unit

If Step 9 was skipped (outcome `skipped-not-in-git-repo`), inherit the same outcome and skip this step.

A launchd / systemd unit for a checkout the project does not name as its daemon driver is an error: a leak from a synced overlay or a stale install, and leaving it loaded keeps a duplicate daemon alive. This step removes it without asking. It never installs a unit — that is `/lazy-core.daemon-setup`'s job.

Read the flag first:

```bash
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" settings-get daemon --key enabled --cwd <repo-root>)
```

Output `false` → state **daemon-disabled** and continue to Step 13.5. Output `true` → read the map:

```bash
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" daemon-run-here --cwd <repo-root> check)
```

- `run-here` → this checkout is the driver; state **driver-checkout** and continue. Installing or refreshing its unit is `/lazy-core.daemon-setup`'s job.
- `unset` / `invalid-shape` → no usable map; state **run-here-unset** and continue. Do NOT ask — naming the driver is `/lazy-core.daemon-setup`'s question.
- `not-this-host` / `not-this-checkout` → remove this checkout's unit on this host, as below.

Compute `<REPO_ID>`, the per-checkout unit id:

```bash
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" install-phase --cwd <repo-root> repo-id)
```

The id is derived from this checkout's absolute path, so it is taken from that output and from nothing else — never from the list of loaded units, never from a sibling checkout of the same repository (a Dropbox checkout and the runtime clone carry different ids by construction). The existence checks below are a plain `ls` of the one path; a non-zero exit is the only evidence that the unit is absent, and no other probe substitutes for it.

macOS (`darwin`):
1. `Bash(ls ~/Library/LaunchAgents/com.lazycortex.runtime.<REPO_ID>.plist)` — non-zero exit → state **no-stray-unit** and stop.
2. `Bash(launchctl bootout gui/$UID/com.lazycortex.runtime.<REPO_ID>)` — a non-zero exit means it was not loaded.
3. `Bash(rm -f ~/Library/LaunchAgents/com.lazycortex.runtime.<REPO_ID>.plist)`
4. State **stray-unit-removed**.

Linux:
1. `Bash(ls ~/.config/systemd/user/lazy-core-runtime-<REPO_ID>.service)` — non-zero exit → state **no-stray-unit** and stop.
2. `Bash(systemctl --user disable --now lazy-core-runtime-<REPO_ID>.service)` — a non-zero exit means it was not enabled.
3. `Bash(rm -f ~/.config/systemd/user/lazy-core-runtime-<REPO_ID>.service)`
4. State **stray-unit-removed**.

Never touch a unit whose `<REPO_ID>` differs — it belongs to another checkout.

## Step 13.5: Configure expert-spawn sandbox in .runtime/sandbox.settings.json

If Step 9 was skipped (outcome `skipped-not-in-git-repo`), inherit the skip and move to Step 14. `daemon.enabled` does **not** gate this step: the sandbox confines expert spawns, and the expert pump spawns them under `/lazy-runtime.tick` on a checkout with no daemon and no supervisor exactly as it does under one. A checkout left unsandboxed because the daemon is off is a checkout whose manual ticks run unconfined.

Otherwise, the expert pump spawns `claude -p --permission-mode dontAsk` subprocesses for every expert job, passing `--settings <repo-root>/.runtime/sandbox.settings.json`. The sandbox scope lives in that daemon-owned runtime file — NOT in `.claude/settings.local.json` — because `.claude/settings.local.json` is loaded by EVERY Claude session in the checkout, so a `sandbox.enabled: true` there would also confine the operator's interactive session (e.g. breaking `git push` over SSH, which the sandbox's HTTP/HTTPS proxy cannot carry). `--settings` is passed only on the spawn, so the sandbox reaches the expert subprocess and never the interactive session.

The spawn loads `--settings` AND the cwd's `.claude/settings.local.json`, merged (CLI layer wins on conflict). So the split is: the **sandbox** block goes to `.runtime/sandbox.settings.json`; the **permission scope** (`permissions` + `additionalDirectories`) stays in `.claude/settings.local.json`, where it serves both the spawn (via the merge) and the operator's interactive session (which needs those allows when running plugin CLIs manually).

Both writes are clean, non-contradictory merges — apply the File-sync policy **silently**: no confirmation, never overwrite an existing key, union missing scope in. Ask only on a genuine conflict per the consumer-owned-config policy (e.g. an existing `sandbox.enabled: false` that contradicts the required `true`).

### 13.5b. Sandbox scope (CLI) and the permission block

The sandbox file is written by `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" sandbox-sync`, never by hand. The sandbox compares the **resolved** path, so an allowlist entry reached through a symlink grants nothing where the data actually lives — the CLI records the resolved location of every entry plus the targets of the symlinks directly inside it (an external-dirs `Data` / `-Inbox` slot), which is exactly what a hand-written allowlist misses.

Substitute `<repo-root>` with the absolute path of the current repo. The plugin sources a spawn reads are granted through ONE entry, the LazyCortex marketplace's cache root `~/.claude/plugins/cache/lazycortex` — never a versioned `<plugin>/<version>` directory (it goes stale on every `/plugin update` and accumulates), and never another marketplace's or a third-party plugin's directory (those are not this skill's to grant). In dev-mode the in-repo `<repo-root>/plugins/claude/<plugin>/` sources are already covered by the repo root; the cache entry is still written, since a spawn loads the sibling plugins this repo does not author from the cache.

```bash
"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" sandbox-sync --repo-root <repo-root> \
  --allow-read ~/.claude/plugins/cache/lazycortex
```

The repo root is granted read+write implicitly. The call also lays the `sandbox` section of `lazy.settings.json` over the file — the operator's network allowlist above all, in Claude Code's own `sandbox` shape; the file's `sandbox` block becomes the declaration, only `enabled`, `allowUnsandboxedCommands` and the two path allowlists survive undeclared, and a declared path allowlist entry joins the recorded list (`lazy-core.expert-runtime-schema.md` § Sandbox). The call is idempotent: it appends only what is missing, never overwrites a recorded `enabled` or `allowUnsandboxedCommands` except with a declared value, and never drops or reorders a recorded entry — with one exception: a recorded read grant that names a version-pinned `<plugin>/<version>` directory under the plugin cache root and whose directory no longer exists on disk (a dead pin left behind by a past `/plugin update`) is pruned. The write allowlist is never pruned, and a read entry outside the plugin cache root stays even when its path is missing. An unrecorded `allowUnsandboxedCommands` is written `false`: Claude Code defaults it to `true`, under which a command the sandbox blocks is retried unsandboxed and only meets the permission check — which Block 2's bare `Bash` allow passes — so a confined spawn could still delete outside its write scope on the second try.

Block 2 — `<repo-root>/.claude/settings.local.json` (permission scope; loaded by every session in the checkout):

```json
{
  "permissions": {
    "additionalDirectories": ["~/.claude/plugins/cache/lazycortex"],
    "allow": ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "Skill", "WebSearch", "WebFetch", "Bash(\"${LAZYCORTEX_PYTHON:-python3}\" *)"]
  }
}
```

The `Bash("${LAZYCORTEX_PYTHON:-python3}" *)` entry is required so dispatched experts can invoke the core CLI (`expert-pump-once`, `permission-allow`, etc.) — Claude Code's `dontAsk` permission mode auto-allows only well-known commands (git, python3, ls in PWD) and silently denies any other Bash command without an explicit allow-pattern. Sibling plugins' install skills add their own `Bash(lazycortex-<short> *)` patterns to this same `permissions.allow` list via `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" permission-allow`.

The bare `WebSearch` and `WebFetch` entries are required for the research-shaped experts (`lazycortex-experts`' researcher): under `dontAsk` both tools are refused without an explicit allow rule, `WebSearch` accepts only the bare form, and the bare `WebFetch` permits any domain. Neither tool runs through the Bash sandbox — they execute in-process — so the sandbox file does not govern them; the permission file does. `WebSearch` is unavailable on the Bedrock provider; that is a provider limit, not a seeding error, and the entry is still written.

Tilde-form (`~/...`) is acceptable for paths the operator wants portable across machines — Claude Code expands `~` at load time. Absolute paths are equally valid.

No `deny` list is seeded. What a spawn may reach on disk is the sandbox's business (`.runtime/sandbox.settings.json`, resolved paths, enforced by the OS), and this file is loaded by the operator's own interactive sessions too, so a deny rule here would police the operator, not the expert. Permission posture is consumer-owned — the install never writes one.

### 13.5c. Run the sandbox sync, then apply the consumer-owned-config policy to the permission file

Run the `sandbox-sync` call above and read its JSON result:

1. `changed: true` and `present: false` → State **sandbox-created**.
2. `changed: true` and `present: true` → State **sandbox-merged** (`added_read` / `added_write` name what was appended, `removed_read` names any dead plugin-cache version pin pruned).
3. `changed: false` → State **sandbox-unchanged**.
4. `enabled: false` → the checkout has confinement recorded as off, which contradicts the required `true`; the CLI left it alone. When the `sandbox` section of `lazy.settings.json` itself declares `enabled: false`, the file only mirrors that declaration and a write here would be undone by the next sync: do not ask, state **sandbox-conflict** and name the declaration as the place to flip it. Otherwise raise one `AskUserQuestion` per the consumer-owned-config policy and state **sandbox-conflict** when the operator keeps it off:

```
Context (print before asking):
- Where: /lazy-core.install · Step 13.5 — Configure expert-spawn sandbox in .runtime/sandbox.settings.json; target <repo-root>/.runtime/sandbox.settings.json
- Found: `sandbox.enabled` is `false` on record (region quoted, unified diff against the required `true`); `sandbox-sync` left it alone
- Why asking: the local value contradicts the required one and the skill cannot tell which should survive — confinement may have been switched off on purpose
- Answers: `merge-shipped` — writes `enabled: true` into the file now, expert spawns run confined; `keep-local` — file untouched, expert spawns on this checkout run unconfined, state **sandbox-conflict**; nothing beyond the file is persisted, so the question returns on the next run while the value stays `false`
AskUserQuestion:
  header: "Sandbox off"
  question: "<repo-root>/.runtime/sandbox.settings.json records `enabled: false`, but expert spawns require `true`. Merge the shipped value or keep the local one?"
  options:
    - "merge-shipped" — "Writes `enabled: true`; expert spawns are confined."
    - "keep-local" — "Leaves `false`; expert spawns on this checkout run unconfined (`sandbox-conflict`)."
```

`Read <repo-root>/.claude/settings.local.json` and apply Block 2 + migrate:

5. **Missing or unparseable** → `Write` Block 2 verbatim. State **perms-created**.
6. **Present** → union missing `permissions` scope in, silently (add only paths / tool names not already present; never drop existing). `additionalDirectories` lives under `permissions`, where Claude Code reads it; a top-level `additionalDirectories` left by an earlier version of this step is moved under `permissions` in the same edit. State **perms-merged**.
7. **Migration** — if this file carries a legacy top-level `sandbox` key (written by an earlier version of this step), REMOVE it: the sandbox now lives in the runtime file, and a `sandbox` here would confine the interactive session. State **migrated-local-sandbox**; **no-legacy-sandbox** when absent.

Never replace an entire key with the recommended value. The consumer's existing files are authoritative for shape; this skill only adds missing scope (and removes the migrated `sandbox` key).

### Outcome

One line combining the sandbox-file state, the permissions-file state, and the migration state — e.g. `sandbox-created · perms-merged · no-legacy-sandbox`, or `skipped-not-in-git-repo`.

## Step 14: Report

Report to the user:
- Python version probe outcome (Step 0)
- Scope detected (user vs project)
- Plugin version/commit synced from: `<version>` / `<gitCommitSha>` (from `installed_plugins.json`)
- For each rule: state (**installed**, **unchanged**, **refreshed**, **kept-orphan**, or **failed**) and target `<path>`, plus the receipt's `counts` line verbatim and the `scaffold sync-rule` status for `lazy-core.scaffold.md`
- For each authoring template: state and target `<path>` (Step 4)
- Per-key `agent_models` seed outcome from Step 6
- Per-key `git` flag seed outcome (Step 6.5), including the pathspec behaviour-change note when `pathspec_enabled` was newly written
- `.logs/` directory + `.lazyignore` seed bootstrap outcome (Step 7)
- `.gitattributes` outcome (Step 7.5), plus the `git add --renormalize .` follow-up when it printed `renormalize: needed`
- Hook migration outcome (Step 8): one line per settings path (`migrated` or `no-stale-entries`)
- Runtime bootstrap outcome (Step 9), including the `daemon.git` derivation outcome (`seeded` / `kept-local` / `skipped-no-branch`)
- Experts directory bootstrap outcome (Step 10)
- `.memory/` directory bootstrap outcome (Step 10.5)
- Expert registration outcome (Step 11)
- lazycortex-core agent-model tier seed outcome (Step 11 §1b, via `lazy-core.agent-models-seed`)
- Expert-pump routine registration outcome (Step 12)
- External working-directory outcome (Step 12.5), including every `skipped (was …)` line, the ignore-coverage outcome with each appended `.gitignore` line (or, on `ignores-declined`, the WARN naming every path git can still see)
- Stray supervisor unit outcome (Step 13)
- Sandbox/permissions merge outcome (Step 13.5)

## Failure modes

- **`/lazy-core.install` aborts: "plugin isn't actually installed — enable it first"** — `lazycortex-core@lazycortex` is missing from `enabledPlugins` in `~/.claude/settings.json`, or the marketplace entry for `lazycortex` is absent from `extraKnownMarketplaces` → add both blocks to `~/.claude/settings.json`, restart Claude Code, then re-run.
- **`/lazy-core.install` aborts: "plugin cache is empty — run `/plugin update` first"** — the rule glob under the plugin's `installPath` returned zero files → run `/plugin update lazycortex-core@lazycortex` to refresh the cache, then re-run.
- **Step 4 aborts: "plugin cache is broken" (templates directory empty)** — the `templates/core/` directory inside the plugin cache is missing or empty → run `/plugin update lazycortex-core@lazycortex`, then re-run.
- **Step 6 fails: "default-tiers.json missing or invalid"** — `lazy-core.agent-models/default-tiers.json` cannot be read or parsed → reinstall `lazycortex-core` to restore the file, then re-run.
- **Step 7 fails: `.logs/` or `.runtime/` not a directory** — a file by either of those names already exists at the repo root → remove or rename it, then re-run.
- **Step 7 fails: `.gitignore` unwritable** — `bootstrap_logs_dir` raised a permission or I/O error → check permissions on the repo root, then re-run.
- **Git still shows CRLF files after Step 7.5** — `renormalize: needed` was reported and the one-time renormalize was not run yet; the rule governs new writes, not content already in the index → run `git add --renormalize .` and commit.
- **Step 9c reports `git: skipped-no-branch`** — the checkout is on a detached `HEAD`, so there is no branch for the daemon to ride → `git checkout <branch>`, then re-run; until then the daemon does no remote sync.
- **The daemon commits but never pushes** — `daemon.git` carries `base_branch` without `remote_sync`, which is what a checkout with no `origin` remote gets → add the remote (`git remote add origin <url>`), delete the `git` block from `.claude/lazy.settings.json`, and re-run to have it re-derived.
- **Step 8 fails: settings.json malformed JSON** — one of the four standard settings paths contains invalid JSON → fix the file manually, then re-run.
- **Step 9 fails: settings file unwritable** — `install-phase daemon-defaults` reports a permission or I/O error when writing the flat `daemon` / `routines` sections into `.claude/lazy.settings.json` → check file permissions on `.claude/lazy.settings.json` and the `.claude/` directory, then re-run.
- **Step 11 wizard: "no candidates found"** — no agent files with `expert_protocol:` frontmatter were found under any of the three discovery scopes → no experts are available to register; the wizard skips automatically.
- **Step 11 wizard: frontmatter parse failure** — a candidate agent file's frontmatter is malformed YAML → the candidate is skipped and flagged in the report as `parse-error`; fix the frontmatter manually and re-run `/lazy-core.install` to pick it up.
- **Step 11 wizard: protocol reference unresolvable** — `resolve-ref` reports `"ok": false` for a candidate's `expert_protocol:` value → the candidate is skipped and flagged as `protocol-unresolvable`; verify the protocol file exists at the referenced path or reinstall the owning plugin.
- **Daemon never starts for this checkout after install** — install never sets up the daemon: `daemon.enabled` is seeded `false`, routines are registered and run through `/lazy-runtime.tick`, and no supervisor is installed → run `/lazy-core.daemon-setup` to enable the daemon, name the checkout that drives it, and install the supervisor.
- **A declared external directory stays absent after install** — the checkout has no `external_dirs.root` on record and the operator answered "Leave as is", so `declined` is set in the local overlay and Step 12.5 never asks again → delete `external_dirs.declined` from `.claude/lazy.settings.local.json` and re-run `/lazy-core.install` to be asked once more.
- **The daemon halts with `uncommitted_changes` right after install, and `git status` lists the external directories** — the links are visible to git: either Step 12.5 stated `ignores-declined`, or `.gitignore` covers the names as directories only (`Data/`) while the slots hold symlinks → re-run `/lazy-core.install` and accept the ignore-coverage question, which appends the anchored slashless lines (`/Data`) next to the existing ones.
- **A declared external directory is reported `skipped (was missing: PermissionError …)`** — the filesystem refused the link (a read-only parent, a slot held by another process); the remaining declared paths were still repaired → fix the permission and re-run `/lazy-core.install`, or accept Fix L4 in `/lazy-core.doctor`.
- **Install never asks about the daemon at all** — intended: the daemon is set up by `/lazy-core.daemon-setup`, not by install → run it when the project should get a background daemon.

## Notes

- **Idempotent**: running this skill multiple times is safe. Files are only created/updated when there's a real change.
- **Re-run after `/plugin update`**: `/plugin update` refreshes the plugin cache but does **not** re-sync rule files into `.claude/rules/`. Re-run this skill after every plugin update to pick up rule changes — otherwise projects keep running the old rule content.
- **Scope independence**: running at project scope does not affect other projects or the global config.
- **Runtime is per-repo, not per-scope**: Steps 3–8 follow the plugin's install scope (`user` writes to `~/.claude/`, `project` writes to `<repo-root>/.claude/`). Steps 9–13.5 always target the current working repo (cwd's git toplevel) regardless of install scope, because runtime artifacts (`.experts/`, routines, the spawn sandbox) are inherently per-repo. Run `/lazy-core.install` from inside each repo where you want runtime to be set up.
- **Re-run after `git clone`**: rules/templates/`lazy.settings.json`/`lazy.runtime.sh` are committed into the repo, so both `daemon.enabled` and the `daemon.run_here` map travel with the clone; supervisor units are per-checkout and per-machine and do not. Re-run this skill after cloning: a clone the map does not name tears down any stray unit it finds. Installing a unit is `/lazy-core.daemon-setup`'s job.
- **Next steps shown to user**: if any rule was **created** or **updated**, remind the user to restart Claude Code (rules are loaded on session start).
