---
name: lazy-wiki.install
description: "Run when the operator asks to set up the wiki in a repo, after a lazycortex-wiki update, or when wiki skills fail because the `lazy-wiki.navigation` rule, the `wiki`, `structure`, or `terms` settings section, or the `wiki.curator` / `wiki.terms-curator` / `wiki.structure-curator` expert is missing from the project. Bootstrap only — defining what the wiki covers is `/lazy-wiki.configure`, what the terms dictionary covers is `/lazy-wiki.configure terms`, and the structure map's profiles and routines are `/lazy-wiki.configure structure`. Idempotent and quiet on re-run; install scope is detected, never asked."
allowed-tools: Read, Write, Edit, Glob, AskUserQuestion, TaskCreate, TaskUpdate, TaskList, TaskGet, Skill, Bash(mkdir -p *), Bash(git rev-parse*), Bash(cp *), Bash(rm *), Bash(test *), Bash(date *), Bash(diff *), Bash(ls *), Bash(python3 *), Bash(lazycortex-core *), Bash(lazycortex-wiki *), Agent
---
# Install lazycortex-wiki

Bootstrap the plugin in the right scope: create the wiki template directory, sync the rules shipped by the plugin (`lazy-wiki.navigation`, `lazy-wiki.structure`) into the consumer's rules directory, seed the `wiki`, `structure`, and `terms` settings sections, seed agent model tiers for the curators and the domain-spec writer, compose the `wiki.curator`, `wiki.terms-curator`, and `wiki.structure-curator` experts (unconditionally — they are dispatch-routing config, not daemon-only), and — only when this project uses the background daemon — register the four wiki routines (`lazy-wiki.scan`, `lazy-wiki.scan-deletes`, `lazy-wiki.relink-weekly`, `lazy-wiki.doctor-apply`). When `wiki.domains` is configured, additionally compose the `wiki.domain-writer` expert and (daemon-gated) register the two domain routines (`lazy-wiki.domain-scan`, `lazy-wiki.domain-full`). For every scope carrying a `mirror` block, additionally (daemon-gated) register its `lazy-wiki.mirror-sync.<scope-id>` schedule routine. The structure map's three scan routines are per-repo wiring owned by `/lazy-wiki.configure structure`, alongside the terms scopes' scan routines owned by `/lazy-wiki.configure terms` — neither family is registered here. Idempotent and quiet on re-run.

## Execution discipline (MANDATORY — read before any action)

This skill has 10 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Detect install scope`
   - `Step 2 — Determine paths`
   - `Step 3 — Create template directory`
   - `Step 4 — Sync navigation rule`
   - `Step 5 — Seed wiki + structure + terms settings sections`
   - `Step 6 — Ensure the doc-kind wiki axis`
   - `Step 7 — Seed agent_models`
   - `Step 8 — Register curator experts + (daemon-gated) routines`
   - `Step 9 — Register the plugin-CLI Bash allow-pattern`
   - `Step 10 — Verify / Report + Log`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they produced an explicit outcome (`unchanged`, `merged`, `kept-local`, `skipped-daemon-disabled`, `already-present`, …).
3. **Do not reach the Report step until every prior task is `completed`.**
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Decisions are remembered, never re-asked

This skill is **idempotent and quiet on re-run**. Every choice it makes is persisted, and on the next run the persisted value is read first and honoured silently — the user is asked again only when nothing is on record yet.

- **Plugin enabled = full functionality.** An enabled plugin is installed whole. There is no per-rule "install this rule?" prompt and no per-artifact opt-in.
- **Daemon gate applies to routines only.** The `wiki.curator` expert is dispatch-routing config and is registered unconditionally; only the three wiki *routines* depend on the background daemon. This skill reads the tracked `daemon.enabled` flag and gates the routine registration on it silently — it never asks the daemon question itself (Gate 1 belongs to `lazy-core.install`).
- **Everything derivable is derived, not asked:** install scope (from where the plugin is *enabled* — see Step 1), curator git identity (a deterministic bot id), the watched branch.

## File-sync policy (applies to every file this skill writes)

Two classes of file, two policies. Which applies follows from who owns the bytes, never from how large the diff is.

**Install-managed mirrors** — every rule under `rules/`, copied verbatim out of the plugin cache. The plugin owns them end to end; a consumer who wants different content authors **their own** rule file rather than editing the mirror, so a target that differs from the shipped source is a stale copy by construction. Absent → copy (`installed`); byte-identical → nothing (`unchanged`); different → overwrite from the source (`refreshed`). No diff preview, no merge, no question. An orphan inside an owned namespace is left in place (`kept-orphan`) — this skill never deletes consumer files. The verdict comes from `file_sync.py`'s byte comparison and its post-write re-check, never from reading the two files and judging.

The navigation rule's `## Coverage` section is the one region a mirror carries that the shipped source cannot: `/lazy-wiki.configure` derives it from the configured scopes. It is **derived**, not authored — Step 4 overwrites the rule and then re-renders Coverage from `lazy.settings.json`, so nothing is preserved and nothing is lost.

**Consumer-owned config** — `lazy.settings.json` and anything else the consumer authors: add what is missing, leave what is there byte-for-byte. A direct contradiction (an existing value that opposes a required one) is the ONLY case that asks. `AskUserQuestion` naming the file, quoting the region, showing a unified diff; options `merge-shipped` / `keep-local`. "Conflict" means you cannot determine what should survive, not merely that the bytes differ.

## Step 1: Detect install scope

Scope = **where the plugin is actually enabled**, not where `/plugin install` last ran. The `scope` field in `installed_plugins.json` records the install command's origin, which drifts from the activation scope — a plugin enabled per-project in `.claude/settings.json` can carry an install record of `scope: "user"`. Resolve it via the core CLI, which reads `enabledPlugins` from the project settings first, then the global settings, falling back to the install record's own `scope` only when neither enables the plugin:

```
Bash(lazycortex-core detect-scope lazycortex-wiki@lazycortex)
```

The command prints exactly one word:
- `project` → target `<repo-root>/.claude/` (project wins even when the install record's scope is `user`, and when both scopes enable it).
- `user` → target `~/.claude/` (enabled only globally, or the fallback resolved there).
- `not-installed` → `lazycortex-wiki@lazycortex` is absent / has an empty array in `installed_plugins.json`; the plugin has never been installed on this machine.

**Do NOT compare `projectPath` against the current working directory.** Step 2 targets `<repo-root>` regardless of any entry's `projectPath`.

The scope is derived — do NOT ask. Abort **only** on `not-installed` (the shared plugin cache is the sole proof of installation, and enablement cannot substitute for missing sources). Message: *"lazycortex-wiki not enabled — add `"lazycortex-wiki@lazycortex": true` to `enabledPlugins` in your `settings.json` and run `/plugin install lazycortex/lazycortex-wiki`."*

Outcome: `scope-detected: <user|project>`.

## Step 2: Determine paths

Run `Bash(git rev-parse --show-toplevel)` to get `<repo-root>` (or use cwd if not in a git repo — warn the user). `<installPath>` is the `installPath` field from `installed_plugins.json` for `lazycortex-wiki@lazycortex`.

Resolve paths:

| Scope | Rules dir | `lazy.settings.json` |
|---|---|---|
| `user` | `~/.claude/rules/` | `~/.claude/lazy.settings.json` |
| `project` | `<repo-root>/.claude/rules/` | `<repo-root>/.claude/lazy.settings.json` |

The `lazycortex-core` tier SOT (`default-tiers.json`) is located by the seeding primitive itself in Step 7 — this step only resolves the rules dir and target `lazy.settings.json` path from the scope.

Outcome: `target-resolved: <settings-path>`.

## Step 3: Create template directory

Ensure `<repo-root>/.claude/templates/wiki/` exists (project scope) or `~/.claude/templates/wiki/` exists (user scope):

```
Bash(mkdir -p <templates-wiki-dir>)
```

This directory is reserved for future per-project curator template customisation. Creating it now is idempotent.

Outcome: `created` or `already-present`.

## Step 4: Sync rules

Enumerate every rule file shipped by the plugin: `Glob <installPath>/rules/*.md` (currently `lazy-wiki.navigation.md` and `lazy-wiki.structure.md`). If the glob returns zero files → FAIL: *"Plugin cache is empty — run `/plugin update lazycortex-wiki@lazycortex` to refresh."*

Owned namespace: `lazy-wiki`.

An enabled plugin installs its whole rule surface — the rules are install-managed mirrors, so the **File-sync policy** applies: absent → copy, identical → nothing, different → overwrite. No per-rule prompt of any kind, and nothing here is yours to judge — byte comparison decides, the script writes, and it verifies each write:

```
Bash(<coreCli> file-sync --src <installPath>/rules --dst <rulesDir> --copy-diverged --owned-glob 'lazy-wiki.*.md')
```

`<coreCli>` is `<coreInstallPath>/bin/lazycortex-core`, where `<coreInstallPath>` is the `installPath` of `lazycortex-core@lazycortex` in `installed_plugins.json` — `lazycortex-core` is a hard dependency of this plugin, so the CLI is always present.

The command creates the destination directory, copies absent targets (**installed**), byte-compares the rest (**unchanged**), overwrites every stale target from the shipped source (**refreshed**), and reports owned targets with no source as **kept-orphan** (left in place, never deleted). Exit code 3 with a non-empty `failed` array means a write did not verify — report it as **failed**, never as applied.

Target files outside the `lazy-wiki` namespace (other plugins, user-authored rules) are never touched and never reported as orphans.

### Re-render the navigation rule's `## Coverage`

The shipped rule carries an empty `## Coverage` section, so a `refreshed` navigation rule has just lost the scope list the previous copy held. It is derived state — rebuild it rather than preserving it.

Skip when the mirror reported `unchanged` (the section is already current) or when `lazy.settings.json[wiki.scopes]` is empty (nothing to render; `/lazy-wiki.configure` fills it in later). Otherwise replace everything between the `## Coverage` heading and the next `##` with one bullet per scope, in id order, in exactly the shape `/lazy-wiki.configure` Phase 9 defines — that phase is the authority for the bullet format, and a second run must produce the same section rather than a longer one.

Outcome (one line per rule): `<name>.md: <state>`, plus the receipt's `counts` line verbatim and `coverage: <rendered|unchanged|no-scopes>`.

## Step 5: Seed wiki + structure + terms settings sections

Read the target `lazy.settings.json`. If missing or unparseable, initialise as `{"_version": 1}`.

Ensure the `wiki` key exists. If absent, add:

```json
{
  "_version": 2,
  "scopes": {},
  "tag_axes": [],
  "exclude": ["docs/structure.md"]
}
```

The stamp is `2` because a section seeded here is already in the post-hoist shape; the v1 → v2 ladder exists for repositories whose vocabulary still sits inside the scopes.

`tag_axes` is the repository-wide axis vocabulary every scope narrows from — seeded empty here and filled by Step 6 (`doc-kind`) and `/lazy-wiki.configure vault`. `exclude` is the glob list unioned into every scope's `exclude_paths`; it seeds with `docs/structure.md` and nothing else — the project-structure map carries no frontmatter to defend itself, so without the entry the curator appends a `# See also` block to it. The generated domain-spec tree needs no entry: it is derived from `wiki.domains.output` and excluded from every scope structurally.

Both keys carry the same absent-only semantics as the section itself: when `wiki` is already present but lacks one of them, add just that key and leave every existing value byte-for-byte.

Ensure the `structure` key exists. If absent, add:

```json
{
  "_version": 1,
  "depth_profiles": {},
  "exclude": ["docs/structure.md"]
}
```

`exclude` seeds with `docs/structure.md` itself and nothing else — the one mandatory entry (`lazy-wiki.structure`'s `rebuild` mode would otherwise describe the map inside the map). `depth_profiles` seeds empty; classes are per-repo and there is no configure wizard yet, so an operator adds them by hand-editing this key.

Ensure the `terms` key exists. If absent, add:

```json
{
  "_version": 1,
  "scopes": {}
}
```

`scopes` seeds empty: which documents a dictionary serves, where its file lives, and which of them are term sources are per-repo decisions made by `/lazy-wiki.configure terms`, which also registers the scope's scan routine.

Never overwrite an existing `wiki`, `structure`, or `terms` key or any nested key within any of them. State **seeded** if added, **already-present** if the key was there — independently per section.

Write the file if any mutation happened.

Outcome: `wiki-section: <seeded|already-present>` (with `tag_axes: <seeded|already-present>` and `exclude: <seeded|already-present>` appended), `structure-section: <seeded|already-present>`, `terms-section: <seeded|already-present>`.

## Step 6: Ensure the doc-kind wiki axis

`doc-kind` is the mandatory classification axis of the vault's vocabulary — the value that says what a node is by form (`design`, `skill`, `rule`, …), owned by this plugin. It is not an operator choice: no question is asked, and the axis is unioned into the repository-wide `wiki.tag_axes` unconditionally, exactly like any other install-managed default. Every scope reaches it from there: a scope declaring no narrowing speaks the full vocabulary, and one that narrows can only pick from it.

```
Bash(lazycortex-wiki ensure-axes doc-kind --repo <target-root>)
```

`<target-root>` is `~` at user scope or `<repo-root>` at project scope — same split Step 2's table resolves `lazy.settings.json` from (the CLI builds `<target-root>/.claude/lazy.settings.json`). Omitting it would let the primitive fall back to `$LAZY_REPO_ROOT`-or-cwd, which at user scope is the wrong file — this install skill runs from whatever directory the operator invoked it in, not from `~`.

The primitive writes `wiki.tag_axes` and nothing else — no scope is read or written, and there is no scope-targeting flag. The union is idempotent: an already-declared axis keeps its position, is never duplicated, and the settings file is not rewritten at all. The call prints `{"status": "added", "added_axes": ["doc-kind"]}` when the vocabulary grew, or `{"status": "unchanged"}` when it already carried the axis. It is load-bearing from the very first run — the vocabulary belongs to the repository, so it exists before any scope does.

A non-zero exit (the `lazycortex-core` CLI `ensure-axes` shells out to for the settings read/write could not be resolved, the write itself failed, or `wiki.tag_axes` is not a list — the primitive then prints `{"error": "wiki.tag_axes must be a list"}`) does NOT abort the whole install — report `doc-kind-axis: axes-cli-failed (<stderr or error first line>)` and continue to Step 7; the operator re-runs `/lazy-wiki.install` once the underlying cause (missing `lazycortex-core`, unwritable settings file, a hand-edited `tag_axes`) is fixed.

Outcome: `doc-kind-axis: <added|unchanged|axes-cli-failed>`.

## Step 7: Seed agent_models

Delegate the entire seed to the shared primitive — do not hand-roll SOT lookup, `lazycortex-wiki:` filtering, or per-key apply:

```
Skill(skill: "lazycortex-core:lazy-core.agent-models-seed", args: "prefix=lazycortex-wiki scope=<scope>")
```

`<scope>` is the value resolved in Step 1 (`project` or `user`). The primitive locates `lazycortex-core`'s `default-tiers.json`, selects every `lazycortex-wiki:*` entry, applies absent/equal/different (`added` / `unchanged` / `kept-local`) semantics against `agent_models.lazycortex`, and writes back only on a mutation.

Fold the primitive's returned `agent-models-seed(...)` block into the Step 10 report verbatim. Surface its outcome:

- `sot-missing` → abort the install (`lazycortex-core` not installed) — same FAIL as Step 2's defaults check.
- `no-entries` → surface plainly (`default-tiers.json` is missing this plugin's agents); not an abort.
- `seeded-N` / `unchanged` → the normal path.

Outcome: `agent-models: <seeded-N|unchanged|no-entries>`.

## Step 8: Register curator experts + (daemon-gated) routines

The `wiki.curator` and `wiki.terms-curator` **experts** are dispatch-routing config — the entries that resolve which agent + aspects run when each curator is dispatched. Both are registered **unconditionally**, exactly like any other expert (not daemon-gated). The three wiki **routines** (`lazy-wiki.scan`, `lazy-wiki.scan-deletes`, `lazy-wiki.relink-weekly`) only ever *fire* under the background daemon, so their registration is gated on the project's `daemon.enabled` flag. The non-daemon parts of this install (rule, settings section, doc-kind axis, `agent_models`, template dir, CLI allow-pattern) are done by Steps 3–7 and Step 9.

### Expert (always registered)

Ensure `experts` exists as an object with `_version: 1` (create if absent — never overwrite). Apply absent-only semantics for the `wiki.curator` key:

```json
"wiki.curator": {
  "agent": "lazycortex-wiki:lazy-wiki.curator",
  "aspects": ["lazycortex-core:lazy-memory.persona-aspect"],
  "git_author": {
    "name": "Wiki Curator",
    "email": "wiki.curator@bot.invalid"
  },
  "can_commit_in_repo": true
}
```

State `experts.wiki.curator: <seeded|kept-local>`.

The `wiki.terms-curator` **expert** is registered on the same terms — dispatch-routing config, not daemon-gated, absent-only:

```json
"wiki.terms-curator": {
  "agent": "lazycortex-wiki:lazy-wiki.terms-curator",
  "aspects": ["lazycortex-core:lazy-memory.persona-aspect"],
  "git_author": {
    "name": "Wiki Terms Curator",
    "email": "wiki.terms-curator@bot.invalid"
  },
  "can_commit_in_repo": true
}
```

`can_commit_in_repo: true` is load-bearing: the curator writes the dictionary into the working tree itself. The default is `false`, and a git routine never passes the flag, so without it on the record the curator cannot write to the repository at all.

State `experts.wiki.terms-curator: <seeded|kept-local>`.

The terms **routines** are not registered here. There is one per terms scope (`path_filter` is a single pathspec and cannot span a scope's unrelated trees), and scopes are `/lazy-wiki.configure terms`' business — it registers, rewrites, and removes them alongside the scope.

The `wiki.structure-curator` **expert** is registered on the same terms — dispatch-routing config, not daemon-gated, absent-only:

```json
"wiki.structure-curator": {
  "agent": "lazycortex-wiki:lazy-wiki.structure-curator",
  "aspects": ["lazycortex-core:lazy-memory.persona-aspect"],
  "git_author": {
    "name": "Wiki Structure Curator",
    "email": "wiki.structure-curator@bot.invalid"
  },
  "can_commit_in_repo": true
}
```

`can_commit_in_repo: true` is load-bearing here for the same reason as above: the curator writes `docs/structure.md` into the working tree itself. The structure **routines** (`lazy-wiki.structure-scan`, `lazy-wiki.structure-scan-deletes`, `lazy-wiki.structure-scan-renames`) are registered by `/lazy-wiki.configure structure`, not here.

State `experts.wiki.structure-curator: <seeded|kept-local>`.

### Daemon gate for the routines (read-first, never ask)

Gate 1 (`daemon.enabled`) is owned by `lazy-core.install`. This skill only **reads** the tracked flag and honours it silently — it never opens an `AskUserQuestion`. Resolve `<core-bin>` (the `bin/` dir of the newest `lazycortex-core` — walk `$LAZYCORTEX_PLUGIN_DIRS` for `*/lazycortex-core/bin`, falling back to `ls ~/.claude/plugins/cache/lazycortex/lazycortex-core/*/bin | sort -V | tail -1`), then read the flag:

```bash
PYTHONPATH=<core-bin> python3 -c "from lazy_settings import load_tracked_section; from pathlib import Path; print(load_tracked_section(Path('<repo-root>/.claude/lazy.settings.json'),'daemon').get('enabled','unset'))"
```

- Output `False` → the project does not use the daemon. **Skip ONLY the routine registration silently** (a routine that can't fire is dead config; the expert above stays registered). State the routine outcomes `skipped-daemon-disabled` and jump straight to the *First scope pointer* below.
- Output `True` or `unset` → register the routines below (do NOT ask; `lazy-core.install` owns Gate 1, and `unset` means the user has not yet run it — register so they are ready when the daemon is enabled).

### Routines

Ensure `routines` exists as an object (create `{"_version": 1}` if absent — never overwrite existing content). For each of the four routines below, apply absent-only semantics (present → **kept-local**, absent → **seeded**):

**`lazy-wiki.scan`** — event-driven git-watch routine, processes changed files:

```json
"lazy-wiki.scan": {
  "type": "git",
  "watch": "changed_files",
  "branch": "<current-branch>",
  "interval_sec": 60,
  "filter": {
    "frontmatter": { "review_active": { "not_in": [true] } },
    "folder_note": false
  },
  "command": ["lazycortex-wiki", "process-file"]
}
```

Substitute `<current-branch>` with the output of `Bash(git rev-parse --abbrev-ref HEAD)` (the branch the daemon watches). The core `dispatch_git` routine type reads `branch` as a branch-name string for `git rev-parse <remote>/<branch>` — a boolean breaks it.

The `filter` block is the earliest cut, on two criteria. `frontmatter` drops a changed file whose frontmatter matches before `process-file` runs, so a document under review (`review_active: true`) never reaches the curator. `folder_note: false` drops a note named after its own folder (`sync/sync.md`) — under the folder-notes convention that file renders as the folder itself, a structural navigation node rather than a document, so curating it produces summary + tags + See-also on a container. The predicate is tri-state: omitting the key means "do not restrict", and `true` selects folder notes exclusively. Both mirror the per-scope `filter` (the source of truth honored on every path); seeding them here keeps the daemon quiet during review and off the folder tree. Absent-only semantics apply to the whole routine — a user who removed the filter is not re-seeded.

**`lazy-wiki.scan-deletes`** — event-driven git-watch routine, prunes links to deleted nodes:

```json
"lazy-wiki.scan-deletes": {
  "type": "git",
  "watch": "deleted_files",
  "branch": "<current-branch>",
  "interval_sec": 60,
  "command": ["lazycortex-wiki", "prune-node"],
  "git_author": { "name": "lazy-wiki.scan-deletes", "email": "lazy-wiki.scan-deletes@bot.invalid" }
}
```

Same `<current-branch>` substitution as `lazy-wiki.scan`. No `filter` block — a deleted file has no frontmatter to read; `prune-node` itself skips paths that resolve to no scope. The consumer is deterministic (no curator dispatch): it drops See-also lines pointing at the deleted node, rebuilds `topics.md`, and commits — `git_author` stamps those commits with the routine's own bot identity instead of the daemon process's, so loop-detect and coordinator author checks see a bot, not the operator.

**`lazy-wiki.relink-weekly`** — weekly full rescan:

```json
"lazy-wiki.relink-weekly": {
  "type": "schedule",
  "cron": "0 4 * * 1",
  "command": ["lazycortex-wiki", "relink-all"]
}
```

**`lazy-wiki.doctor-apply`** — daily deterministic sanitizer; applies only the doctor's fixable finding set (`orphan-topic`, `index-desync`, `see-also-path-base`, `broken-see-also`, `stale-gloss` — pure index/link derivations, never mirror or content findings) across every scope and commits what it repaired:

```json
"lazy-wiki.doctor-apply": {
  "type": "schedule",
  "cron": "15 4 * * *",
  "command": ["lazycortex-wiki", "doctor", "--apply", "--commit"],
  "git_author": { "name": "lazy-wiki.doctor-apply", "email": "lazy-wiki.doctor-apply@bot.invalid" }
}
```

The consumer is deterministic (no expert dispatch), so no protocol is attached. `--commit` makes the CLI commit its own repairs — without it the routine's worktree writes would trip the daemon's dirty-tree guard; `git_author` stamps those commits with the routine's own bot identity.

### Domain-spec expert + routines (only when `wiki.domains` is configured)

Read `wiki.domains` from the target `lazy.settings.json`. Absent → skip this whole sub-step silently with outcome `skipped-no-domains` (the section is created by `/lazy-wiki.configure domains`; re-running this install afterwards registers everything below). Present → apply absent-only semantics to each entry:

**Expert `wiki.domain-writer`** (registered whenever `wiki.domains` is present — dispatch-routing config, not daemon-gated):

```json
"wiki.domain-writer": {
  "agent": "lazycortex-wiki:lazy-wiki.domain-spec-writer",
  "aspects": [],
  "git_author": {
    "name": "Domain Writer",
    "email": "wiki.domain-writer@bot.invalid"
  },
  "can_commit_in_repo": true
}
```

**Routines** (same daemon gate as the three wiki routines above — `skipped-daemon-disabled` when the gate is off):

**`lazy-wiki.domain-scan`** — event-driven git-watch routine; every changed file ticks the consumer, which itself skips paths outside the configured `code` globs and the dictionary, and exits 0 with zero work when every group hash matches:

```json
"lazy-wiki.domain-scan": {
  "type": "git",
  "watch": "changed_files",
  "branch": "<current-branch>",
  "interval_sec": 60,
  "command": ["lazycortex-wiki", "domain-tick"],
  "git_author": { "name": "lazy-wiki.domain-scan", "email": "lazy-wiki.domain-scan@bot.invalid" }
}
```

**`lazy-wiki.domain-full`** — weekly full pass, the insurance against missed wakes (same detect, no trigger-path filter):

```json
"lazy-wiki.domain-full": {
  "type": "schedule",
  "cron": "0 5 * * 1",
  "command": ["lazycortex-wiki", "domain-tick", "--full"],
  "git_author": { "name": "lazy-wiki.domain-full", "email": "lazy-wiki.domain-full@bot.invalid" }
}
```

Both routines dispatch `wiki.domain-writer` jobs that write markdown docs with formulas, so attach the markdown-style protocol to each (idempotent union, exactly like `lazy-wiki.scan` in the protocol sub-step below):

```
Bash(lazycortex-core add-protocols --routine lazy-wiki.domain-scan --ids lazycortex-core:lazy-core.markdown-style)
Bash(lazycortex-core add-protocols --routine lazy-wiki.domain-full --ids lazycortex-core:lazy-core.markdown-style)
```

### Mirror-sync routines (only for scopes with a `mirror` block)

Read `wiki.scopes` from the target `lazy.settings.json`. For every scope whose entry carries a `mirror` block, register one schedule routine named `lazy-wiki.mirror-sync.<scope-id>` (same daemon gate as the other routines — `skipped-daemon-disabled` when the gate is off; absent-only semantics):

```json
"lazy-wiki.mirror-sync.<scope-id>": {
  "type": "schedule",
  "cron": "30 4 * * *",
  "command": ["lazycortex-wiki", "mirror-sync", "<scope-id>"],
  "git_author": { "name": "lazy-wiki.mirror-sync", "email": "lazy-wiki.mirror-sync@bot.invalid" }
}
```

The consumer is deterministic (fetch → sync → commit; no expert dispatch), so no protocol is attached. `git_author` is one family identity across every mirror scope — the routine key already names the scope, the commit subject names the synced paths, and `git blame` on mirrored content must point at the sync bot, never at the operator who has not seen it. The commit it lands is picked up by the git-watch `lazy-wiki.scan` routine, which re-curates the changed mirror nodes — no second curation channel. Scopes without a `mirror` block get nothing; when no scope carries one, state the outcome `skipped-no-mirrors`. The block is created by `/lazy-wiki.configure mirror`; re-running this install afterwards registers the routine.

Write the file if any mutation happened (preserve `_version: 1` for both `routines` and `experts`).

### Seed the mandatory protocol

`lazy-wiki.scan` and `lazy-wiki.relink-weekly` dispatch curator jobs that write into vault notes (`wiki_summary`, tag values, the glossed `# See also` block), so both carry one mandatory protocol. Attach it after the routine write, whether the entry was just seeded or kept local — the union is idempotent and never removes what the operator added:

```
Bash(lazycortex-core add-protocols --routine lazy-wiki.scan --ids lazycortex-core:lazy-core.markdown-style)
Bash(lazycortex-core add-protocols --routine lazy-wiki.relink-weekly --ids lazycortex-core:lazy-core.markdown-style)
```

`lazy-wiki.scan-deletes` gets nothing: `prune-node` is deterministic and dispatches no expert, so a protocol there would be dead config.

No question is asked: a mandatory protocol is not an operator choice, and the step must also land under `lazy-core.autosetup`, where every question-gated step is skipped. Optional protocols remain `/lazy-routine.offer-protocols`' business — do NOT offer them for these routines, the curator writes frontmatter and one-line glosses, and no flagged candidate fits that.

Skip both calls with the routines when the daemon gate skipped their registration. This sub-step carries no outcome of its own — each seeded routine's line below gains a `+protocol` suffix.

Outcome (one line per seeded entry): `experts.wiki.curator: <seeded|kept-local>` (always), `experts.wiki.domain-writer: <seeded|kept-local|skipped-no-domains>`, `routines.<key>: <seeded|kept-local|skipped-daemon-disabled|skipped-no-domains|skipped-no-mirrors>`, with `+protocol` appended on `lazy-wiki.scan`, `lazy-wiki.relink-weekly`, `lazy-wiki.domain-scan`, and `lazy-wiki.domain-full` whenever the seeding above ran.

### First scope pointer

Do NOT ask. When `wiki.scopes` is empty, print a one-line pointer so the operator knows the next step — *"No wiki scopes configured yet — run `/lazy-wiki.configure` to add the first one."* When `wiki.scopes` already has entries, say nothing. Configuring a scope is genuine project work the operator drives via `/lazy-wiki.configure`; this install step only points at it, never prompts.

If yes → invoke `Skill(skill: "lazycortex-wiki:lazy-wiki.configure")`.

## Step 9: Register the plugin-CLI Bash allow-pattern

The plugin ships `bin/lazycortex-wiki` which is invoked from other skills via `Bash(lazycortex-wiki ...)` — `lazy-wiki.curator` (the daemon-dispatched expert) calls it to apply node curation, build the index, and dispatch link jobs. Expert subprocesses spawned by the `lazy-core.runtime` daemon run under Claude Code's `dontAsk` permission mode — that mode silently denies any Bash command not on the auto-allow list. Without this entry, every CLI invocation from the curator (`apply-node`, `build-index`, `dispatch-link`, `retag`) fails with `Permission to use Bash has been denied because Claude Code is running in don't ask mode`, and the curator drifts off-protocol mid-job.

Per `lazy-core.hygiene` § Settings split, per-tool permissions live in `settings.local.json` (gitignored), never tracked `settings.json`. Target file resolves from Step 1's scope:

- project install → `<repo-root>/.claude/settings.local.json`
- user install → `~/.claude/settings.local.json`

Apply via the `lazycortex-core` CLI (idempotent — already-present patterns are no-ops):

```
Bash(lazycortex-core permission-allow <settings-local> "Bash(lazycortex-wiki *)")
```

Outcome: `cli-allow-added` or `cli-allow-already-present`.

## Step 10: Verify / Report + Log

- Read back the written `lazy.settings.json` and confirm it parses.
- Confirm `wiki`, `structure`, `terms`, and `agent_models.lazycortex` are present, that `wiki.exclude` carries `docs/structure.md`, and that `wiki.tag_axes` includes `doc-kind` — the last one holds on a fresh install too, since the vocabulary is the repository's and does not wait for a scope. Do NOT expect `doc-kind` in any scope's own `tag_axes`: a scope list is a narrowing, and an absent or empty one means the scope uses the whole vocabulary.
- Confirm `experts.wiki.curator`, `experts.wiki.terms-curator`, and `experts.wiki.structure-curator` are present (all always registered; the terms and structure curators carry `can_commit_in_repo: true`). Do NOT expect any `routines.wiki.terms-scan-*` or `routines.wiki.structure-scan*` key — those families belong to `/lazy-wiki.configure terms` / `/lazy-wiki.configure structure`. When the daemon gate passed (enabled or unset): also confirm `routines.wiki.scan`, `routines.wiki.scan-deletes`, `routines.wiki.relink-weekly`, and `routines.lazy-wiki.doctor-apply` are present, and that `lazy-wiki.scan` / `lazy-wiki.relink-weekly` carry `lazycortex-core:lazy-core.markdown-style` in their `protocols`. When the routines were `skipped-daemon-disabled`, do NOT expect those routine keys — their absence is correct; `experts.wiki.curator` must still be present.
- When `wiki.domains` is configured: confirm `experts.wiki.domain-writer` is present, and — daemon gate permitting — `routines.wiki.domain-scan` / `routines.wiki.domain-full` with the markdown-style protocol. When `wiki.domains` is absent, do NOT expect any of them.
- For every scope with a `mirror` block — daemon gate permitting — confirm `routines.wiki.mirror-sync.<scope-id>` is present. When no scope carries one, do NOT expect any.
- Report to the user:
  - Scope detected.
  - Plugin version + commit synced from `installed_plugins.json`.
  - Defaults file path used.
  - Per-rule outcome from Step 4.
  - Settings-section outcomes from Steps 5–8 (including the Step 8 daemon-gate outcome).

Log to `./.logs/claude/lazy-wiki.install/<UTC-timestamp>.md` per `lazy-log.logging`. Required frontmatter: `git_sha`, `git_branch`, `date` (UTC), `input`.

Two separate steps: `Bash(mkdir -p ./.logs/claude/lazy-wiki.install)` then `Write` tool. Never chain.

Outcome: `verified` / `logged`.

## Report

One line per task in the canonical list above, with its outcome word.

## Failure modes

- **`/lazy-wiki.install` aborts: "plugin not enabled"** — `lazycortex-wiki@lazycortex` absent or empty in `~/.claude/plugins/installed_plugins.json` → add `"lazycortex-wiki@lazycortex": true` to `enabledPlugins`, restart Claude Code, re-run.
- **`/lazy-wiki.install` aborts: "lazycortex-core not installed"** — `default-tiers.json` not found → install `lazycortex-core` first, then re-run.
- **`/lazy-wiki.install` aborts: "plugin cache is empty"** — rule glob returned zero files → run `/plugin update lazycortex-wiki@lazycortex`, then re-run.
- **Curator never runs after install (no routines)** — Step 8 read `daemon.enabled = false` in the tracked `lazy.settings.json` and skipped the three wiki *routines* (outcome `skipped-daemon-disabled`); the `wiki.curator` expert, rule, settings section, and CLI allow-pattern still installed → enable the daemon via `/lazy-core.install` (Gate 1), then re-run `/lazy-wiki.install` to register the curator routines.
