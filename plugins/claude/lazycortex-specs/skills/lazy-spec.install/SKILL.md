---
name: lazy-spec.install
description: "Run when the operator asks to set up the spec system in a repo, after enabling or updating lazycortex-specs, or when spec skills misbehave because the `spec` settings section, the per-category template-override dirs, the `lazy-spec.gate-tick` routine, the request-handler runtime, or the content-root vault spec (`vision.md`) are missing. Also the place the vault spec gets seeded and the first product gets registered. Idempotent — safe to re-run."
allowed-tools: Read, Write, Edit, Skill, Bash(mkdir -p *), Bash(git rev-parse*), Bash(test *), Bash(ls *), Bash(date *), Bash(PYTHONPATH=* python3 *), Bash("${LAZYCORTEX_PYTHON:-python3}" *), AskUserQuestion, Agent
---
# Install lazycortex-specs

Bootstrap the plugin in the right scope: ensure the consumer dir exists where per-product authored-doc template overrides live, read-or-seed the repo default language, register the `lazy-spec.gate-tick` routine so the daemon clears finished job markers and structurally checks each asset's status folder-note, register the `lazy-spec.coordinator-watch` routine so the daemon hands operator activity to `spec.coordinator` (the one that actually decides gates and flips them), wire the request-handler runtime, and register the first product.

## Install philosophy (read before any action)

- **Plugin enabled = full functionality.** An enabled plugin is installed whole. There is no per-part "wire this?" opt-in — wanting the plugin means wanting its surface. The only questions this skill asks collect GENUINE project config that cannot be derived (the repo authoring language; the first product) and are read-first (Read-first / never re-ask).
- **No daemon gate.** Every routine this skill registers is registered unconditionally — the manual tick drives them just as the daemon does (see § Routines are registered unconditionally). The daemon's own question belongs to `lazy-core.install`, which does not ask it either.
- **Scope is derived, never asked.** Install scope comes from where the plugin is *enabled* (see Step 1); a project-scope enablement wins even when the install record's `scope` is `user`. Python floor is owned by `lazy-core.install`'s first phase — this skill never re-probes it.

## File-sync policy (applies to every file this skill writes)

Every file this skill creates or updates — settings sections, routine entries, review classes, the `lazy.settings.json` blocks — follows three cases; there is no per-file "install?" prompt and no routine/entry drift wizard:

1. **Absent or unchanged** — target missing, or byte-identical to the shipped / last-known version → write silently. State `installed` / `unchanged`.
2. **Locally changed but cleanly mergeable** — target diverged, but the shipped delta applies without contradicting local edits (new keys / entries / globs added, every local-only chunk left untouched) → merge silently. State `merged`.
3. **Genuine conflict** — the same region (a key, a line, a block) was changed both locally and in the shipped version in ways that cannot be reconciled automatically → the ONLY case that asks. The site that raises it prints the context first, filled from the run (`lazy-core.skill-writing` § 11): **Where** — `/lazy-spec.install · Step <N>`, the file and the key / entry in conflict; **Found** — the conflicting region quoted, local and shipped, as a unified diff; **Why asking** — the two edits contradict and neither can be picked mechanically; **Answers** — `merge-shipped` (the shipped region replaces the local one now; every other local chunk stays untouched) / `keep-local` (the local region stays; the shipped delta for that region is dropped, and the conflict is raised again on the next run while it persists). Then `AskUserQuestion`: `header` names the file, `question` names the entry and asks which version survives, options `merge-shipped` / `keep-local` with those descriptions.

"Conflict" means you cannot determine what should survive — not merely "the bytes differ". No contradiction → no question. A no-longer-shipped entry (orphan) is left in place silently (`kept-orphan`); this skill never deletes consumer config.

## Routines are registered unconditionally — there is no daemon gate

Steps 5, 5b, and 6 register routines (`lazy-spec.gate-tick`, `lazy-spec.coordinator-watch`, `lazy-spec.request-open`, `lazy-spec.request-apply`). None of them is gated on `daemon.enabled`: `/lazy-runtime.tick` runs the registered set in the daemon's own priority order on a checkout that never starts one, so an unregistered routine is not a saved dead entry, it is a routine the operator cannot tick. The flag governs only what a live daemon process must own — the supervisor unit and the metrics endpoint — and both belong to `lazy-core.install`. Never read it here, and never ask about it.

## Routine registrations are reconciled, never skipped

Every step that registers a routine (5, 5b, 5c, 6a, 6b, 6.7) calls `lazycortex-core:lazy-routine.register` in **reconcile mode**, passing the shipped `cfg` and the list of keys this plugin owns:

```
Skill(skill: "lazycortex-core:lazy-routine.register", args: "name=<name> cfg=<cfg-json> --managed <key>,<key>")
```

The plain register call is never used here: it aborts on a name it already knows, so a consumer registered under an older shape keeps that shape forever, and nothing this skill writes afterwards ever revisits the entry.

**What `--managed` names is the plugin's own knowledge** — the routine type, the path mask, the filter predicates, the watch mode, the `command:` worker, the request template. Those keys are corrected to the shipped value on every run. Every other key the recorded entry carries is the operator's answer and is left exactly as it stands: `interval_sec`, `timeout_sec`, `priority`, `cron`, `branch`, `hooks_enabled`, `ignore_halt`, and a hand-set `group` (the daemon's whole-list default applies when absent). A shipped key the entry never carried is filled in. Each step names its own `--managed` list beside its `cfg`; the registrar returns `registered`, `refreshed`, or `unchanged`, and the step reports whichever came back.

A stale install-managed value is therefore never a drift question and never an unregister/re-register dance — it is simply rewritten on the next run.

**The one case reconcile cannot merge is a shape change.** The registrar validates the merged entry against the routine type's closed vocabulary, so an entry whose recorded `type` differs from the shipped one, or which still carries the older `expert:` + `request:` pair where the shipped shape has `command:`, raises `RoutineConfigError` instead of being written. That is the genuine conflict the File-sync policy means — surface it through the policy's conflict question: **Where** — this step, `routines.<name>` in `<settings-dir>/lazy.settings.json`; **Found** — the recorded entry against the shipped `cfg`; **Why asking** — the two shapes cannot be merged mechanically and the operator keys of the old entry would be discarded with it; **Answers** — `merge-shipped` (`/lazy-routine.unregister <name>`, then re-register the shipped `cfg`, carrying over the operator keys read back from the removed entry) / `keep-local` (the entry stays and the routine keeps running its old shape, raised again on the next run). Outcome: `shape-migrated` or `shape-kept-local`.

**No routine of another plugin is reconciled from here.** Step 7b seeds a `spec_stage` exclusion into the wiki plugin's own routines through the core CLI's absent-key-only `routine-ensure-filter`, never through `--managed`: reasserting a sibling's `filter` block from this side would delete whatever that plugin, or the operator, put there.

## Execution discipline (MANDATORY — read before any action)

This skill has 17 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. Canonical list (titles verbatim):
   - `Step 1 — Detect install scope`
   - `Step 2 — Determine paths`
   - `Step 3 — Ensure consumer dirs`
   - `Step 3b — Mirror plugin rules into .claude/rules/`
   - `Step 4 — Seed default language`
   - `Step 5 — Register the gate-tick routine`
   - `Step 5b — Register the coordinator-watch routine`
   - `Step 5c — Register the collect routine`
   - `Step 6 — Wire the request-handler runtime`
   - `Step 6.5 — Seed agent-model tiers`
   - `Step 6.7 — Register the upstream-tick routine`
   - `Step 6.9 — Seed the vault spec and the catalog root's level note`
   - `Step 7 — Offer first product registration`
   - `Step 7b — Ensure product/category wiki axes (wiki-conditional)`
   - `Step 7c — Backfill spec_doc_type across the catalog`
   - `Step 8 — Register the plugin-CLI Bash allow-pattern`
   - `Step 9 — Verify`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `created`, `already-exists`, `skipped-per-user-choice`).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1: Detect install scope

Scope = **where the plugin is actually enabled**, not where `/plugin install` last ran. The `scope` field in `installed_plugins.json` records the install command's origin, which drifts from the activation scope — a plugin enabled per-project in `.claude/settings.json` can carry an install record of `scope: "user"`. Enablement is the source of truth for where config belongs.

Resolve it via the core CLI, which reads `enabledPlugins` from the project settings first, then the global settings, and falls back to the install record's own `scope` only when neither settings file enables the plugin:

**Resolve `<core-cli>` once, before the first call.** It is the core plugin's `bin/lazycortex-core` file: when this repo authors the plugin itself (`plugins/claude/lazycortex-core/.claude-plugin/plugin.json` exists) that is `<repo-root>/plugins/claude/lazycortex-core/bin/lazycortex-core`; otherwise `Read` `$HOME/.claude/plugins/installed_plugins.json` and take `<installPath>/bin/lazycortex-core` from the last `lazycortex-core@lazycortex` record. Hold the absolute path and run every verb as `Bash("${LAZYCORTEX_PYTHON:-python3}" <core-cli> <verb> …)` — never as a bare command: the file carries no exec bit and no plugin `bin/` is on `PATH`.

```
Bash("${LAZYCORTEX_PYTHON:-python3}" <core-cli> detect-scope lazycortex-specs@lazycortex)
```

The command prints exactly one word:
- `project` — enabled in `<repo-root>/.claude/settings.json` (project wins even when the install record's scope is `user`, and when both scopes enable it); Step 2 targets `<repo-root>/.claude/`.
- `user` — enabled only in `~/.claude/settings.json` (or the fallback resolved there); Step 2 targets `~/.claude/` (and the project-scope-only request wiring in Step 6 is skipped).
- `not-installed` — `lazycortex-specs@lazycortex` is absent / has an empty array in `~/.claude/plugins/installed_plugins.json`; the plugin has never been installed on this machine.

The scope is derived — do NOT ask.

**Do NOT compare an entry's `projectPath` against the current working directory.** Step 2 targets `<repo-root>` (i.e. `git rev-parse --show-toplevel` in the current cwd) regardless of any entry's `projectPath`. A `projectPath` mismatch is **never** grounds for aborting.

Abort **only** on `not-installed` — the shared plugin cache is the sole proof of installation, and enablement cannot substitute for missing sources. In that case tell the user to install it first:
```json
"enabledPlugins": { "lazycortex-specs@lazycortex": true }
```
then run `/plugin install lazycortex/lazycortex-specs`.

## Step 2: Determine paths

Project root is `git rev-parse --show-toplevel` (or current working directory if not in a git repo — warn the user).

| Scope | Consumer root |
|---|---|
| `user` | `~/.claude/` |
| `project` | `<repo-root>/.claude/` |

The plugin install path (`<installPath>`) is what `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-specs` prints: the authoring repo's `plugins/claude/lazycortex-specs/` when this checkout ships the plugin, else the exported or newest cached copy — never `installed_plugins.json` read by hand. The plugin ships:

- Protocol-contract docs at `${CLAUDE_PLUGIN_ROOT}/references/*.md`
- Default authored-doc templates at `${CLAUDE_PLUGIN_ROOT}/templates/spec.<context>/` (one folder per shipped type: `spec.feature/`, `spec.change/`, `spec.bug/`, `spec.content/`, `spec.research/`, `spec.product/`, `spec.request/`; operator-defined types add their own under `spec.<name>/` via `/lazy-spec.add-asset-type`)

These are read directly from the plugin cache at runtime — this skill does NOT copy them into the consumer tree.

## Step 3: Ensure consumer dirs

Create (with `mkdir -p`) the single consumer directory that holds per-project artifacts:

| Path (relative to consumer root) | Purpose |
|---|---|
| `templates/spec.feature/`, `templates/spec.change/`, `templates/spec.bug/`, `templates/spec.content/`, `templates/spec.research/`, `templates/spec.product/`, `templates/spec.vault/`, `templates/spec.docs/`, `templates/spec.request/` | One per template context: the shipped asset types, the two levels, the linear base, the request inbox; each asset-type and product folder holds optional `<compound-key>/` per-product override sub-folders |

Report `created` or `already-exists`.

This skill does NOT create a `templates/spec.workflows/` dir — workflow machinery has been removed from the plugin. Products live in the `products` settings section and repos live in the `repos` settings section, not in rule files — `.claude/rules/` carries only the plugin's own authoring rules, mirrored in Step 3b below.

Project scope only: if a spec output directory is needed (e.g. a `Specs/` vault root), defer that decision to `lazy-spec.product-config` — the only vault content this skill creates is the vault-spec draft (Step 6.9); everything else is `lazy-spec.product-config`'s.

## Step 3b: Mirror plugin rules into `.claude/rules/`

Mirror every rule file shipped under `${CLAUDE_PLUGIN_ROOT}/rules/` into `<consumer>/.claude/rules/` — today this is the single file `spec.decisions.md`, the plugin's first rule. References, skills, commands, and templates stay in the plugin and are read by absolute path from `${CLAUDE_PLUGIN_ROOT}/...`; only rules ship into the consumer's session-loaded set (same split `lazy-python.install` Step 1 already applies to its own three rules).

Install-managed mirror per the **File-sync policy** above: absent → copy (`installed`); byte-identical → nothing (`unchanged`); different → overwrite from the shipped source (`refreshed`). No diff preview, no merge, no question — the plugin owns these bytes end to end; a consumer wanting different content authors their own rule file. A no-longer-shipped rule (orphan) is left in place silently.

```
Bash("${LAZYCORTEX_PYTHON:-python3}" <core-cli> file-sync --src "${CLAUDE_PLUGIN_ROOT}/rules" --dst <consumer>/.claude/rules --copy-diverged)
```

The receipt's `counts` map carries one entry per state (`installed`, `unchanged`, `refreshed`). Outcome: `rules-mirrored:<N>` where N is `installed` + `refreshed` (0 means every rule was already current).

## Step 3c: Move context templates out of the linear base

Before 9.0 a product-level or catalog-root document and a research design were overridden through composite filenames in the consumer's linear base. They now live in their context folders. For each file below that exists, move it; a target already present is a conflict — report both paths, move nothing for that pair, and continue with the next:

| From (`.claude/templates/spec.docs/`) | To (`.claude/templates/`) |
|---|---|
| `system-vision.md` | `spec.product/vision.md` |
| `system-design.md` | `spec.product/design.md` |
| `system-tech.md` | `spec.product/tech.md` |
| `vault-vision.md` | `spec.vault/vision.md` |
| `vault-design.md` | `spec.vault/design.md` |
| `vault-tech.md` | `spec.vault/tech.md` |
| `research-design.md` | `spec.research/design.md` |

`Bash(test -e <to> || mv <from> <to>)` per row — a worktree move, never `git mv`. Then, for every consumer template under `.claude/templates/spec.*/` that carries `spec_doc_type`, confirm the type is declared: `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" doc-type resolve <type> [--product <key>])`; a non-zero exit is a WARN naming the file. Outcome: `moved:<n>` / `conflicts:<n>` / `unknown-type:<n>` / `nothing-to-move`.

## Step 4: Seed default language

Three settings sections back the spec system: `products` (cross-plugin), `repos` (cross-plugin — maps each repo key to its local checkout metadata), and `spec` (plugin-owned, holds `language`). All three are registered in lazy-core's `CURRENT_VERSIONS` and **auto-initialize on first `settings-get`**. Install does NOT hand-write any of them — `products` and `repos` records are authored by `lazy-spec.product-config`; this step only optionally seeds `spec.language`.

The repo authoring language is GENUINE project config — it cannot be derived — so this step keeps its question, but read-first: a language already on record is never re-asked.

**Read first.** Run `Bash("${LAZYCORTEX_PYTHON:-python3}" <core-cli> settings-get spec)` and inspect `language`. If the section already carries a non-`en` `language` (a prior install or hand-edit set it), state outcome `language-on-record:<code>` and skip the question entirely. Only when nothing is on record (section absent, or `language` still the `en` default) do you ask.

The plugin's effective default language is `en` until overridden.

```
Context (print before asking):
- Where: /lazy-spec.install · Step 4 — Seed default language; target `spec.language` in <settings-dir>/lazy.settings.json
- Found: `settings-get spec` → `language` <absent | "en" (the default)>
- Why asking: the repo authoring language is genuine project config that cannot be derived
- Answers: `keep-en` — nothing written, outcome `language-default-en`; `set-other` — the follow-up below asks the code, then `language` is written into the `spec` section (read-patch-write, `_version` preserved), outcome `language-set:<code>`; a non-`en` value on record is never re-asked (`language-on-record:<code>`)
AskUserQuestion: header "Spec language", question "Set a non-default authoring language for spec docs in <repo>? The plugin defaults to en. Pick another only if this repo's specs are authored in a different language.", options `keep-en` — accept the `en` default; write nothing / `set-other` — seed a different language code into the `spec` section.
```

If `keep-en`: outcome `language-default-en`. Skip the write.

If `set-other`: ask the operator for the language code, then read-patch-write the `spec` section so the auto-init `_version` is preserved:

```
Context (print before asking):
- Where: Step 4 — language code; target `spec.language`
- Found: nothing on record (the operator just chose `set-other`)
- Why asking: the code itself is the config
- Answers: any ISO 639-1 code via "other" — written as `spec.language` below; never re-asked once on record
AskUserQuestion: header "Language code", question "ISO 639-1 code for spec docs in <repo> (e.g. `ru`, `de`)?", free text via "other".
```

```
Bash("${LAZYCORTEX_PYTHON:-python3}" <core-cli> settings-get spec)
```

Parse the printed JSON, set `language` to the operator's code, and pipe the full object back:

```
Bash(printf '%s' '<patched-spec-section-json>' | "${LAZYCORTEX_PYTHON:-python3}" <core-cli> settings-set spec)
```

Outcome: `language-set:<code>`. Why read-patch-write rather than emit a bare `{language: <code>}`: `settings-set` persists the whole section, so the auto-init `_version` field must survive the round-trip — drop it and the section reverts to an unversioned shape.

## Step 5: Register the gate-tick routine

The daemon clears finished job markers and structurally checks every asset's status folder-note (`spec_role: status`) — `spec.coordinator` (Step 5b) is what decides and flips gates. This step registers the `lazy-spec.gate-tick` md-scan routine via the blessed `/lazy-routine.register` skill — it does NOT hand-write the routine JSON into settings.

Invoke `lazycortex-core:lazy-routine.register` via the `Skill` tool, passing a `cfg` dict so the wizard runs programmatically (no per-field prompts). The exact routine:

```json
{
  "name": "lazy-spec.gate-tick",
  "cfg": {
    "type": "md-scan",
    "interval_sec": 60,
    "timeout_sec": 60,
    "paths": ["<vault_root>/**/*.md"],
    "filter": {
      "frontmatter": {
        "spec_role": {"in": ["status"], "not_in": []},
        "spec_cancelled": {"in": [null, false], "not_in": []},
        "spec_released": {"in": [null, false], "not_in": []}
      }
    },
    "command": ["lazycortex-specs", "gate-tick"]
  }
}
```

`<vault_root>` is the `spec.vault_root` setting (default `specs`); when it is `.`, drop the segment and the glob starts at the repository root.

The mask spans the whole vault because the filter, not the glob, is what selects: every non-product subtree under the content root (`requests/`, the project-level system documents, an operator's own folders) carries a `spec_role` other than `status`, or no frontmatter at all, so the frontmatter predicate rejects all of it. The one tree that made width expensive rather than wrong was the mirrored `upstream/` content, which no longer lives under the vault at all — it sits at `<repo>/upstream/`, outside every glob this routine writes.

**Managed keys — `type,paths,filter,command`.** Pass them as `--managed type,paths,filter,command` per § Routine registrations are reconciled, never skipped: the mask, the frontmatter predicate and the worker are this plugin's own knowledge, while `interval_sec` / `timeout_sec` are the operator's cadence and stay outside the list. Absent that reconciliation a repo registered under an older shape keeps it forever — either an over-wide `["**/*.md"]` that re-parses every markdown file in the repository each tick, or a narrowed products-subtree glob that matches nothing under a layout with no literal `products/` segment.

The composite `{in: [...], not_in: []}` predicate is the shape the md-scan filter expects (same form as the `review_active` / `review_result` clauses on Step 6a's own routine): `null` in `in` matches a missing key or explicit null, so an asset whose status note has not yet stamped `spec_cancelled` / `spec_released` still matches. The filter selects every live (un-cancelled, un-released) asset status folder-note across the vault content root.

The daemon resolves `command[0]` (`lazycortex-specs`) to the plugin's bin script and runs it as `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" gate-tick <matched-file-path>` — it **appends the matched file's absolute path as the last argv** (the md-scan convention every command-based routine of this type relies on). `gate-tick <asset_note>` reads the appended status folder-note path, clears the runtime sidecar's `active_job` marker when its bundle has landed a terminal marker (raising a `job-done` wake and opening report review on `DONE`), and runs `note_check` — it dispatches no jobs of its own and carries no protocol (pure script, nothing here ever produces LLM markdown output).

Outcome: `registered`, `refreshed`, or `unchanged`, whichever the registrar returned.

## Step 5b: Register the coordinator-watch routine

`spec.coordinator` wakes on: a non-`@bot.`-authored commit reaching this checkout and changing an asset's status folder-note (the operator's own gesture — a tick, an edit — committed and pushed from wherever the operator works, then pulled in by this checkout's next daemon iteration); a non-empty `# Coordinator commands` section; a ticked option under one of the coordinator's own `[!question]` callouts; a launch-checkbox job's terminal marker landing, raised by `lazy-spec.gate-tick` as a `job-done` wake in the runtime sidecar and fired whoever authored the commit it landed alongside (`lazy-spec.coordination-playbook.md` § 1); or a sibling authored doc's own `review_result` appearing or changing, also regardless of that commit's authorship (`CoordinatorTrigger.DOC_TRANSITION`, same § 1). This step registers the `lazy-spec.coordinator-watch` **git-watch** routine via the blessed `/lazy-routine.register` skill — it does NOT hand-write the routine JSON into settings. Unlike `lazy-spec.gate-tick` (Step 5, an `md-scan` routine that re-scans every candidate file each tick), this routine watches the spec content root's own git history: the daemon computes each changed markdown file's last-changing commit and author once per tick (`lazy-core.routine-types-schema.md` § `git` / `watch: changed_files`) and hands that to the worker directly — there is no dirty-tree signal to read in the daemon's own checkout, and no separate "have I seen this commit" marker for the worker to maintain (the git-watch routine keeps its own cursor in `state.json`).

Invoke `lazycortex-core:lazy-routine.register` via the `Skill` tool, passing a `cfg` dict so the wizard runs programmatically (no per-field prompts). The routine's `filter.any_of` matches two shapes, scoped to the spec content root via `path_filter` rather than `paths`: every live coordination note — an asset status folder-note, a product's level note, or the catalog root's level note (one composite member) — OR any typed document of the content root (the other member); `coordinator_dispatch` resolves each matched document to its owning note before deciding anything, and routes that note to `spec.coordinator` or `spec.catalog-coordinator` by its role:

```json
{
  "name": "lazy-spec.coordinator-watch",
  "cfg": {
    "type": "git",
    "branch": "<base_branch>",
    "watch": "changed_files",
    "path_filter": ":(glob)<vault_root>/**/*.md",
    "interval_sec": 60,
    "timeout_sec": 60,
    "filter": {
      "any_of": [
        {
          "frontmatter": {
            "spec_role": {"in": ["status", "product", "catalog"], "not_in": []},
            "spec_cancelled": {"in": [null, false], "not_in": []}
          }
        },
        {
          "frontmatter": {
            "spec_doc_type": {"in": [], "not_in": [null]}
          }
        }
      ]
    },
    "command": ["lazycortex-specs", "coordinator-dispatch"]
  }
}
```

The routine declares no `group` key, so the daemon's default `group: "all"` applies: every changed path the tick found reaches the worker as ONE `{"dir": ".", "paths": [...], "sha", "author_name", "author_email"}` item (`lazy-core.routine-types-schema.md` § git `group`) — one worker call per tick, whatever the number of changed files or registered products. The `dir` is the repo root, never an asset boundary: `coordinator-dispatch` splits the members by the nearest status folder-note above each one and dispatches once per owner, so a nested asset's own documents wake the nested asset, not the enclosing one, and a member no status note owns — a product's or the catalog root's own level document, a group folder-note — is re-routed through the single-file path, resolving to the folder-note that owns it. Nothing per product is registered on the routine: a spawned or configured product joins the watch the moment its files lie under `path_filter`. When some owners' dispatches raise, the worker still runs the rest, then prints `{"failed_paths": [...]}` — the failed owners' member paths — as its LAST stdout line and exits 1, so the daemon's retry cursor carries only those paths into the next tick (same schema, § Partial failure of a multi-path unit); the members that dispatched clean are never replayed.

The first member carries no `spec_released` exclusion — a note is filtered out only while it is cancelled. An asset crossing `spec_released` into true is exactly the commit that must reach the dispatcher, since that is where the one-hop upward `asset-released` wake onto the product's level note is decided (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.catalog-playbook.md` § 5); excluding released notes would drop the release flip's own commit and the upward wake with it. A released asset is otherwise quiet — no gate moves, no checkbox hangs — so the widened member costs a resolved-and-discarded tick, never a spurious job. `product` and `catalog` never carry `spec_released` at all.

The second member selects on the presence of `spec_doc_type` rather than on a closed list of filenames: an empty `in` declares no allow-list, and `not_in: [null]` rejects a file where the key is absent or null. That leaves exactly the typed documents of the content root — the canonical authored docs and an expert's markdown attachments alike, without the routine having to know either set by name. An untyped stray markdown file under the vault matches nothing and wakes no coordinator.

`architecture.md` is an ordinary sibling doc kind — its review class (main writer `architect`, one `planner_review` validation slot) is wired in § 6e below, same as the other five doc kinds.

`<base_branch>` is the consumer's `daemon.git.base_branch` (the field is vestigial for a git-watch routine — the watch target is always local `HEAD` — but still required by the schema; see `lazy-routine.register/SKILL.md`'s git-type row). `<vault_root>` is the `spec.vault_root` setting (default `specs`), resolved the same way Step 5's `paths` glob resolves it; when it is `.`, the `path_filter` collapses to `:(glob)**/*.md`.

The daemon resolves `command[0]` (`lazycortex-specs`) to the plugin's bin script and runs it once per tick as `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" coordinator-dispatch '<item-json>'` — a single JSON argv carrying the whole-list `{"dir": ".", "paths", "sha", "author_name", "author_email"}` item (`routine_types.dispatch_git`'s `command:` sub-shape), **not** a bare file path the way `lazy-spec.gate-tick` / `lazy-review.scan` pass one. A consumer that set `group: "file"` on the routine by hand gets the per-file `{"path", "status", "sha", "author_name", "author_email"}` item instead, and `group: "dir"` or a glob list a `{"dir", "paths", ...}` item per matched directory — every shape resolves against the worker's `cwd` (the repo root, set by the daemon). For each member of a grouped item — and for a single `path` item — `coordinator-dispatch` finds the owning note: a status folder-note named directly is checked for a wake trigger, and a sibling doc (the `any_of` filter's other member) resolves to the OWNING asset's status folder-note and is checked for a `review_result` transition against that note's own marker. Every member of one owner is scanned in one pass, so an asset dispatches at most one `spec.coordinator` job per tick regardless of how many of its members changed; a no-op tick touches nothing.

**Managed keys — `type,watch,path_filter,filter,command`.** Pass them as `--managed type,watch,path_filter,filter,command` per § Routine registrations are reconciled, never skipped. The whole `filter` block is this plugin's — an install that predates the level coordinator recorded a filter matching `spec_role: status` only, so no level note ever reached `coordinator-dispatch` and every product's and the catalog root's system documents sat unstaged with nobody to promote them; reconcile rewrites the block whole, which is what keeps the next key added to the shipped filter from going missing in every repo that already has the routine. `branch`, `interval_sec`, `timeout_sec`, and a hand-set `group` are the operator's. A pre-existing `md-scan`-shaped entry from an install that predates the git-watch resew cannot be merged into the git shape at all: the registrar raises `RoutineConfigError`, handled as the shape conflict that section describes. Outcome: `registered`, `refreshed`, or `unchanged`, whichever the registrar returned.

### 5b-a. Seed the mandatory protocols

The coordinator reasons from `lazy-spec.coordination-playbook.md` on every dispatched job, and its jobs (`code-plan.md` / `test-plan.md` writers, the `code-report.md` / `test-report.md` journals the launch ladder opens, the coordinator's own `# Status brief` prose) all produce markdown in the vault — this routine, not `lazy-spec.gate-tick`, is the one that actually dispatches those jobs, so both protocols attach here. Attach them regardless of whether this step registered the routine or found it already present — the union is idempotent and never removes what the operator added:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" <core-cli> add-protocols --routine lazy-spec.coordinator-watch --ids lazycortex-specs:lazy-spec.coordination-playbook,lazycortex-core:lazy-core.markdown-style)
```

No question is asked here: a mandatory protocol is not an operator choice, and the step must also land under `lazy-core.autosetup`, where every question-gated step is skipped.

This sub-step carries no outcome of its own — it rolls into Step 5b's, which reads `<registrar-outcome>+protocol-seeded` (`registered` / `refreshed` / `unchanged`).

### 5b-b. Verify the coordinator's output can actually leave this checkout

The coordinator's every write — `# Status brief`, `[!question]` callouts, gate flips, `# Coordinator commands` locking — is a local commit in the daemon's own checkout. It reaches the operator only through the daemon's post-iteration `_git_post` push, which itself only runs when `daemon.git.remote_sync == "pull_push"` (`runtime_daemon.py`'s `_git_post`). A checkout with `remote_sync` unset or set to anything else piles up every coordinator commit locally, forever invisible to the operator.

Read the tracked `daemon.git` block. `<core-bin>` is `<core-root>/bin`, where `<core-root>` is what `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-core` prints — the authoring repo's `plugins/claude/lazycortex-core/` when this checkout ships the plugin, else the exported or newest cached copy. Outside an authoring repo that is the `installPath` of `lazycortex-core@lazycortex` from `installed_plugins.json`:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" <core-cli> settings-get daemon --key git/remote_sync --cwd <repo-root>)
```

When the printed value is anything other than `pull_push`, REPORT it plainly in this step's outcome — do not write `remote_sync` yourself, that is operator territory and a checkout without an `origin` remote legitimately has none configured. State the finding as `remote-sync-not-pull-push:<value>` alongside whatever Step 5b's own outcome was, so the operator sees it before relying on the coordinator unattended. When the value already reads `pull_push`, no separate outcome line is needed — fold a plain `remote-sync-ok` into Step 5b's report.

## Step 5c: Register the collect routine

A finished expert job leaves its terminal marker (`DONE` / `DEAD` / `CANCELLED`) inside `.experts/.jobs/<expert>/<job_id>/` — a path no md-scan signature covers, so `lazy-spec.gate-tick` (Step 5, an md-scan routine gated on the note's own directory changing) never wakes on it: the note's folder is untouched when a job finishes. This routine is the delivery channel — the specs-side analog of `lazy-review.collect`. Every tick it reads the job-marker sidecar (`.runtime/lazy-specs.jobs.json`), and for each note with a recorded marker runs the same per-note `gate-tick` in-process; gate-tick's own job-done commit is what then wakes `lazy-spec.coordinator-watch`.

Invoke `lazycortex-core:lazy-routine.register` via the `Skill` tool with:

```json
{
  "name": "lazy-spec.collect",
  "cfg": {
    "command": ["lazycortex-specs", "collect-tick"],
    "interval_sec": 60,
    "timeout_sec": 120,
    "priority": 15
  }
}
```

The shape mirrors `lazy-review.collect` (same interval, timeout, priority — the two postmen are peers on the schedule). The worker takes no per-file argv: `collect-tick` sweeps the whole sidecar itself and exits immediately when it records nothing.

**Managed keys — `type,command`.** Pass them as `--managed type,command` per § Routine registrations are reconciled, never skipped; `interval_sec`, `timeout_sec` and `priority` are the operator's schedule. Outcome: `registered`, `refreshed`, or `unchanged`, whichever the registrar returned.

## Step 6: Wire the request-handler runtime

Request files at `<vault-root>/requests/` are processed by three runtime channels:

- **md-scan open (mechanical, command-based)** — fires on naked request files (no `review_active`, no `review_result`). Pure state flip: writes the opt-in frontmatter keys + Waiting banner and commits under the `lazy-spec.request-open` bot identity. No LLM spawn, ~1s latency. Routine `routines.lazy-spec.request-open` with `command:` shape pointing at `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" open-request`.
- **md-scan apply (mechanical, command-based)** — fires on post-finalize request files (`request_status: draft` + `review_result` in {`approved`, `approved-with-concerns`}). Reads the resolved routing prose, calls `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" scaffold-asset` for spawn targets — asset folder + status folder-note only, the note carrying the `spec_source_requests` union and its `## Source requests` projection; no document is seeded and no review is opened at apply (documents come later, one launch-checkbox tick at a time, via `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" seed-doc`) — records attribution on each attach target's primary doc (no callout) and re-opens its review, stamps terminal markers (`request_class`, `request_status`, mirror tag, status callout) and strips `# Routing`, atomic commit under `lazy-spec.request-apply` bot identity. No LLM dispatch — the worker is the Python primitive at `${CLAUDE_PLUGIN_ROOT}/bin/apply_request.py`, which also implements the attach and spawn enactment directly (no separate `spec.request-attach` / `spec.request-spawn` skills exist). Routine `routines.lazy-spec.request-apply` with `command:` shape pointing at `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" apply-request`.
- **lazy-review specialist** — `spec.catalog-coordinator`, running in its routing mode (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.catalog-playbook.md` § 10), runs all content work (classify, find candidates, surface the routing decision, fold to prose) during the review loop. Requires the agent registered as an expert AND a review class entry mapping `requests/*.md` to `spec.catalog-coordinator` under `terminal.routing` (the post-approve terminal-action section writer group that owns the `# Routing` heading — surfaces only after the operator approves the body, persists through finalize so the apply worker can read the resolved routing prose, and never triggers revert-to-main since operator choices are not concerns). The class declares a separate `main` chain — the consumer-supplied interpreter expert.

Without all three wired, the request inbox is dead from the daemon's perspective. The request runtime is part of the plugin's own surface — enabling the plugin means wanting it — so this step writes the blocks unconditionally; there is no `wire-now` / `skip` opt-in (per § Install philosophy).

**Project-scope only.** Request files live in `<vault-root>/requests/` per-vault; wiring at user scope would point the daemon at the wrong path. If Step 1 detected user scope, skip this step silently — outcome `skipped-user-scope`.

Read `lazy.settings.json` (create the file if missing) and merge the `experts` and `review.classes` blocks per the File-sync policy: absent → write silently; present and cleanly mergeable → merge silently; genuine conflict (an existing entry whose shape contradicts the shipped one) → the only case that asks. The two routine blocks (6a, 6b) are not hand-merged at all — they go through the registrar in reconcile mode, per § Routine registrations are reconciled, never skipped. Report `wiring-applied:<count-added>` (count of blocks newly added/merged; 0 means everything was already in place).

### 6a. md-scan open routine (mechanical, command-based)

Register `lazy-spec.request-open` through `lazycortex-core:lazy-routine.register` in reconcile mode — never by hand-editing the `routines` section. The shipped `cfg`:

```yaml
lazy-spec.request-open:
  type: md-scan
  interval_sec: 60
  timeout_sec: 30
  priority: 30
  paths: ["<vault_root>/requests/*.md"]
  filter:
    folder_note: false
    frontmatter:
      review_active: {in: [null], not_in: []}
      review_result: {in: [null], not_in: []}
  command: ["lazycortex-specs", "open-request"]
```

`<vault_root>` is the `spec.vault_root` setting (default `specs`), resolved exactly as Step 5's `paths` glob resolves it; when it is `.`, drop the segment and the glob is `requests/*.md`. A routine `paths` glob is repo-relative, unlike the `review.classes[]` globs of 6d, which are relative to `review.watch_root`. The daemon matches a `**`-free glob right-anchored, so a bare `requests/*.md` still finds `<vault_root>/requests/`, but it also fires on every other `requests/` folder in the repository — an inbox the open-request worker would stamp and commit as a spec request. The prefix keeps the sieve on the one inbox this plugin owns.

The joint filter `review_active: [null] + review_result: [null]` catches files that have not yet entered the review loop — naked files (no frontmatter at all) AND partial-bootstrap files (`request_status: draft` set but `review_active` missing). The `review_result: [null]` clause excludes post-finalize files: finalize strips `review_active` AND stamps `review_result` (`approved` / `approved-with-concerns`), so those files match `review_active: [null]` alone but must be routed to the apply gate, not re-bootstrapped. The `folder_note: false` clause excludes the `requests/` folder-note (`requests/requests.md` — the Obsidian folder-note convention `<dir>/<dir>.md`): it is an inbox description carrying no `review_active` / `review_result`, so without this clause it matches the filter on every tick and the routine re-dispatches it forever (open-request finds nothing to do and never stamps the frontmatter that would drop it out). The command brings the file to canonical opt-in shape, atomic commit under `lazy-spec.request-open` bot identity.

Once the script commits with `review_active: true`, the file falls out of this routine's filter and into the review loop — `lazycortex-review`'s own `lazy-review.coordinator-watch` routine picks the commit up. After finalize stamps `review_result`, the apply routine (6b) takes over.

**Managed keys — `type,paths,filter,command`.** Pass them as `--managed type,paths,filter,command` per § Routine registrations are reconciled, never skipped, so the joint `review_active` / `review_result` predicate and the `folder_note: false` clause reach an entry registered before either existed. `interval_sec`, `timeout_sec` and `priority` are the operator's — an entry still carrying the legacy `interval_sec: 5` keeps it, since nothing can tell that value apart from a cadence the operator chose. A deliberately narrowed `request_status: [null]` filter or an operator-set `folder_note: true` is inside the managed block and is rewritten with it; an operator who needs a different predicate here owns the whole routine and re-registers it.

### 6b. md-scan apply routine (mechanical, command-based)

Register `lazy-spec.request-apply` through `lazycortex-core:lazy-routine.register` in reconcile mode — never by hand-editing the `routines` section. The shipped `cfg`:

```yaml
lazy-spec.request-apply:
  type: md-scan
  interval_sec: 60
  timeout_sec: 60
  priority: 20
  paths: ["<vault_root>/requests/*.md"]
  filter:
    folder_note: false
    frontmatter:
      request_status: {in: ["draft"], not_in: []}
      review_result: {in: ["approved", "approved-with-concerns"], not_in: []}
  command: ["lazycortex-specs", "apply-request"]
```

`<vault_root>` resolves exactly as in 6a.

**Resolve `<review-cli>` once, before the first call.** It is the review plugin's `bin/lazycortex-review` file: when this repo authors the plugin itself (`plugins/claude/lazycortex-review/.claude-plugin/plugin.json` exists) that is `<repo-root>/plugins/claude/lazycortex-review/bin/lazycortex-review`; otherwise `Read` `$HOME/.claude/plugins/installed_plugins.json` and take `<installPath>/bin/lazycortex-review` from the last `lazycortex-review@lazycortex` record. Hold the absolute path and run every verb as `Bash("${LAZYCORTEX_PYTHON:-python3}" <review-cli> <verb> …)` — never as a bare command: the file carries no exec bit and no plugin `bin/` is on `PATH`.

The daemon resolves `command[0]` (`lazycortex-specs`) to the plugin's bin script and runs it as `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" apply-request <matched-file-path>` — same convention as `lazy-spec.request-open`. The worker is a deterministic Python primitive (`${CLAUDE_PLUGIN_ROOT}/bin/apply_request.py`); no LLM dispatch happens at this gate. It parses the `# Routing` section, runs `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" scaffold-asset` for any spawn target — asset folder + status folder-note only, the note carrying the `spec_source_requests` union and its `## Source requests` projection; no document is seeded and no review is opened at apply (the request body is never copied anywhere — a checkbox-seeded doc's main writer reads the source request from its review job's `context/`, per `lazy-spec.request-protocol.md` § Body distribution rules) — maintains `spec_source_requests` frontmatter + the `## Requests` projection inside `# Sources` on each attach target's primary doc (attribution only, no callout) and opens a review cycle on that populated doc via `"${LAZYCORTEX_PYTHON:-python3}" <review-cli> start`, then stamps the request file's terminal markers and atomic-commits under `lazy-spec.request-apply` bot identity.

The joint filter `request_status: ["draft"] + review_result: ["approved", "approved-with-concerns"]` matches only the post-finalize state: finalize stamped `review_result` (clean approve OR approve-with-concerns) as its last step, and the terminal `request_status` has not been written yet (still `draft`). Stop-aborted reviews (no `review_result` ever written) and mid-review files (transient `review_*` keys present but `review_result` not yet stamped) do not match — apply only fires on a clean finalize. The worker reads the resolved routing prose that `spec.coordinator` folded into `# Routing` during review (its routing mode, per `lazy-spec.coordination-playbook.md` Chapter 7) and enacts it.

**Managed keys — `type,paths,filter,command`.** Pass them as `--managed type,paths,filter,command` per § Routine registrations are reconciled, never skipped: the glob, the post-finalize predicate and the worker are this plugin's, while `interval_sec`, `timeout_sec` and `priority` are the operator's — an entry still carrying the legacy `interval_sec: 5` keeps it, since nothing can tell that value apart from a cadence the operator chose. The older `expert: lazy-spec.request-apply` form (LLM-dispatched apply) is a shape change, not a merge: the shipped `command:` alongside the recorded `expert:` + `request:` pair violates the registrar's EITHER/OR rule and raises `RoutineConfigError`, handled as the shape conflict that section describes.

### 6c. Expert entry

Under `experts` add the key `spec.coordinator` if missing:

```yaml
spec.coordinator:
  agent: lazycortex-specs:lazy-spec.coordinator
  can_commit_in_repo: true
  git_author:
    name: spec.coordinator
    email: spec.coordinator@bot.invalid
```

The coordinator's own writes always carry this identity, and its `@bot.` substring is exactly what its own self-suppression check (`lazy-spec.coordination-playbook.md` § 1) relies on to never re-wake itself on its own commits. The dispatch worker that fires it, `coordinator_dispatch.py`, is wired as the `lazy-spec.coordinator-watch` routine (Step 5b) — that routine's registration is what actually resolves this expert; this step only needs the entry to exist.

`can_commit_in_repo: true` is required, not optional — the same convention the `design` / `test-plan` cascade writers use below. Absent, `expert_pump` extends the coordinator's spawn prompt with a no-commit clause forbidding it from committing its own pen writes (`# Status brief`, `[!question]` callouts, `# Coordinator commands` locking) — but the coordinator has no dispatcher-side apply path the way a reviewed document does, so those writes would either never land (the clause obeyed) or leave the tree dirty forever (the clause ignored), and a dirty tree after `lazy-expert.pump` halts the daemon before its next `_git_post` push, stranding the whole tick.

Under `experts` also add the key `spec.catalog-coordinator` if missing — the level coordinator that owns the catalog root's and each product's system documents (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.catalog-playbook.md`):

```yaml
spec.catalog-coordinator:
  agent: lazycortex-specs:lazy-spec.catalog-coordinator
  can_commit_in_repo: true
  git_author:
    name: spec.catalog-coordinator
    email: spec.catalog-coordinator@bot.invalid
```

Both coordinators are fired by the SAME routine (Step 5b): `coordinator_dispatch.py` resolves the owning note of every changed document and routes it by `spec_role` — `status` to `spec.coordinator`, `product` / `catalog` to this one. There is no second routine to register, and the `can_commit_in_repo` / `@bot.` reasoning above applies to this entry identically.

The apply transition does NOT register an expert — its routine is `command:`-shape (the Python primitive). The bot identity for the apply commit is hardcoded as `lazy-spec.request-apply` / `lazy-spec.request-apply@bot.invalid` in the worker's CLI defaults. Override with `--author-name` / `--author-email` if a consumer needs a different identity.

If an older `spec.request-router` or `lazy-spec.request-apply` expert entry remains (from a previous install predating the coordinator model, where routing decisions were a dedicated LLM-dispatched router rather than `spec.coordinator`'s own call), it is now an orphan. Per the File-sync policy, orphans are left in place silently (`kept-orphan`); this skill never deletes consumer config.

### 6d. Review class

Under `review.classes` find the entry carrying `class: request` (fall back to matching the `requests/*.md` glob for a pre-identity entry — and stamp `class: request` onto it while you are there). Absent → append the entry below. Present → compare its install-managed slots against the shape below and complete or correct them, per the File-sync policy's install-managed-value rule; an entry on record is never a reason to skip.

```yaml
- class: request
  paths: ["requests/*.md"]
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol"]
  experts:
    main:
      - name: <consumer-interpreter-expert>
    terminal:
      routing:
        name: spec.catalog-coordinator
        section: Routing
        position: top
```

Writer shapes per the new schema (audit-enforced): `main` is a LIST of `{name}` writer objects; each `validation` / `terminal` section is a SINGLE writer object `{name, section, position}` (no list, no `repo` — the deprecated `repo` field is omitted). `main` is the body-content interpreter expert the consumer supplies. `terminal.routing` is `spec.catalog-coordinator`, the post-approve routing-decision writer that owns the `# Routing` heading — routing is decided at the catalog level, the one place every product and both level ladders are visible at once (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.catalog-playbook.md` § 10), not by a dedicated router persona. An install that predates this move carries `spec.coordinator` in this slot, with `position: bottom`. That is **not** a genuine conflict and must never be surfaced as one: the File-sync policy reserves that class for a value where the skill cannot tell what should survive, and here it can — the asset coordinator has no routing mode left to serve the slot with, so the stale name is a shipped default that rotted, never an operator's choice. Rewrite `name` and `position` silently, the way every other install-managed value is refreshed. Ask only when the slot holds a name that is neither the shipped one nor any key under `experts` in this repo: that is a role the operator wired themselves, and it is theirs to keep or replace. Surfacing the stale default instead makes the step unfixable under `lazy-core.autosetup`, which skips every question and leaves the slot broken — the failure that kept nine consumer repos pointed at a writer whose agent declares routing is not its job, so `# Routing` was never written and `lazy-spec.request-apply` had no decision to enact. It fires only AFTER the operator approves the body, follows `lazy-review.doc-review-protocol` § `mode == terminal` (surfaces the routing decision as a `[!question]`, folds the operator's answer into prose naming the targets), the `# Routing` section persists through finalize so `lazy-spec.request-apply` can read the resolved routing prose, and the section never triggers revert-to-main (operator choices are not concerns). The coordinator declares no `frontmatter` block in this role — per the doc-review protocol, terminal-mode writers do not write frontmatter at all; everything it decides lives in its section body. `request_class` is stamped by `lazy-spec.request-apply` post-finalize (it reads the class verdict from the routing prose and writes the field alongside `request_status` and the mirror tag — see the `lazy-spec.request-apply` agent body for the full apply contract). `main` writers and validators likewise own the document BODY only; daemon state keys (`review_*`) are written mechanically, never through an expert overlay.

If the consumer has not yet registered an interpreter expert, omit `main` — the class still dispatches `spec.catalog-coordinator` on `# Routing` changes.

**`main` is backfilled on a later run.** The omission above is a gap waiting on a prerequisite, not a decision: an interpreter expert registered afterwards must reach the slot, and only this step can put it there. So on every run, when the class entry exists with no `main` (or an empty one) and an interpreter expert is now on record under `experts`, write it in and state **refreshed**. Without the backfill the permitted omission is permanent — the class exists, so an append-only step skips it forever, and the request opens for review with no writer for its body. That is the state five consumer repos are in today, each with a registered `<domain>.interpreter` the slot never received.

`main` naming a role absent from `experts` is the one case that asks, per the File-sync policy: the operator wired a writer this skill does not know, and replacing it silently would be overriding their choice.

If `review` section is absent, create `{_version: 1, classes: [<entry>]}`. If `classes` is present but no entry covers `requests/*.md`, append.

### 6e. Review classes for spec docs

The `lazy-spec.request-apply` worker scaffolds entity folders (`<slug>/` for a feature at the product root, `changes/<slug>/`, `bugs/<slug>/`) under each registered product's `<spec_path>` — folder + status folder-note only. Every authored doc, `design.md` included, is created later by a ticked launch checkbox: the coordinator runs `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" seed-doc`, then opens the doc's review via `lazy-review.start` when the folder-note carries source requests, or waits for the operator's own commit into the skeleton otherwise. Those docs (`design.md`, `bug.md`, the opt-in `code-plan.md` / `test-plan.md`, and the `code-report.md` / `test-report.md` journals the launch ladder later opens for review on job completion) need their own review classes so the daemon dispatches the right writer for each one — without these classes, checkbox-seeded or later-authored docs sit at `[!hint] Waiting #review/in-process` forever because no class matches their paths. The same applies to the **system-level** classes: the product-root `design.md` / `tech.md` pair and the identical pair at the spec content-root (the project-wide spec — no config key declares it; the files' existence is the declaration) are typed `system-design` / `system-tech` and reviewed under their own classes, never under the asset-level `design` class; the product-root `ui-design.md` — the product's shared look, which the assets' own `ui-design.md` refine — is typed `system-ui-design` and reviewed under its own class the same way, and so is the product-root `use-cases.md` — the product's use cases, which the assets' own `use-cases.md` refine — typed `system-use-cases`.

Under `review.classes` append each entry below whose `class:` token no existing entry carries — coverage is judged on the token, never on `paths`, since a typed document routes by type and two classes may legitimately share a glob (`design` and `research-design` both match `*/*/design.md`). One retirement runs first: an existing entry labeled `class: research` — the one-document form an earlier release seeded, whose `research.md` type no longer exists — is removed from `review.classes` before the append, and the step states `retired-research-class`; an operator-declared class with any other label is never touched. **Each entry carries a `class:` key with the exact bare doc-kind token** (`vision`, `system-vision`, `use-cases`, `system-use-cases`, `design`, `system-design`, `system-tech`, `architecture`, `ui-design`, `system-ui-design`, `code-plan`, `test-plan`, `bug`, `code-report`, `test-report`, `data-report`, `docs-report`, `research-design`, `research-report`). A review class is declared by this config, not by a code-side enum: only the subset the settings-migration ladder keys off carries a token in `ReviewClassName` (`lazycortex-core`'s `bin/constants.py`) — `design`, `bug`, `architecture`, `code-plan`, `test-plan`, `code-report`, `test-report` — and the rest (`use-cases`, `system-use-cases`, `system-design`, `system-tech`, `ui-design`, `system-ui-design`) are review classes the older ladder steps never touch, so a matching constant is neither present nor needed; the `vision` / `system-vision` classes are seeded into existing vaults by the v10 → v11 migration step, which keys off the literal class tokens. Omitting the `class:` key, as an earlier revision of this seed did for the path-only siblings, makes a fresh install diverge from a migrated-in-place vault: `migrate_all`'s `_add_architecture_class` / `_add_planner_review_to_design` steps both search for `entry.get("class") == "<token>"` and, finding no match on a `class`-less entry, append a SECOND `architecture` class and silently skip `design`'s `planner_review` slot. The `paths` globs are right-anchored (`PurePath.match`, same as `lazycortex-review`'s `doc_class`): `*/*/design.md` matches a `design.md` two levels below any folder, so one table serves every product regardless of the organizational folders above its `spec_path` — no literal `products/` segment and no `spec_path` prefix belongs in a `paths` value, and the table below is the same one `lazy-spec.product-config` Step 12 writes.

```yaml
# vision.md class (asset-level) — designer writes goals/value for one feature or change; NO
# validators — the writer and the operator close the loop (a designer validator would be
# self-validation; an architect has nothing to check in a goals-and-value document)
- class: vision
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol", "lazycortex-specs:lazy-spec.doc-height-protocol"]
  paths:
    - "*/*/vision.md"
  context_from_frontmatter: [spec_source_requests]
  experts:
    main:
      - name: <designer-expert>
      - name: <editor-expert>
# use-cases.md class (all levels) — use-case-writer writes; one designer_review validation slot
# (asset-level: opt-in sibling created by a ticked launch checkbox; seed-doc copies the status
# folder-note's spec_source_requests onto the seeded doc, so context_from_frontmatter folds the
# originating request(s) into the writer's bundle, same as design/bug. The content-root
# use-cases.md is operator-authored and rides the same class; the product-root one is typed
# system-use-cases and has its own class below)
- class: use-cases
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol"]
  paths:
    - "*/use-cases.md"
    - "use-cases.md"
  context_from_frontmatter: [spec_source_requests]
  experts:
    main:
      - name: <use-case-writer-expert>
      - name: <editor-expert>
    validation:
      designer_review:
        name: <designer-expert>
        section: Designer review
        position: bottom
# system-use-cases class — the product-root use-cases.md (the product's actors and the scenarios
# that cross its assets), above which the assets' own use-cases docs refine. Product roots only —
# the content root's use-cases.md stays on the class above. The same use-case-writer and editor
# write it and the designer validates, as on the asset class; the doc-height protocol keeps it at
# the product's altitude. The glob is the asset class's — a typed document routes by type, so the
# two never collide.
- class: system-use-cases
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol", "lazycortex-specs:lazy-spec.doc-height-protocol"]
  paths:
    - "*/use-cases.md"
  context_from_frontmatter: [spec_source_requests]
  experts:
    main:
      - name: <use-case-writer-expert>
      - name: <editor-expert>
    validation:
      designer_review:
        name: <designer-expert>
        section: Designer review
        position: bottom
# design.md class (asset-level) — designer writes; one architect_review validation slot
# (structural feasibility judged while the behavior is still on paper; operator still approves)
- class: design
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol", "lazycortex-specs:lazy-spec.doc-height-protocol"]
  paths:
    - "*/*/design.md"
  context_from_frontmatter: [spec_source_requests]
  experts:
    main:
      - name: <designer-expert>
      - name: <editor-expert>
    validation:
      architect_review:
        name: <architect-expert>
        section: Architect review
        position: bottom
# system-design class — the product-root design.md AND the content-root (project-wide) design.md;
# the system-designer writes, the architect validates. One expert set serves both scales.
# system-vision class — the product-root vision.md AND the content-root (project-wide) vision.md
# (the vault spec); the system-designer writes at both scales; NO validators — same reasoning as
# the asset vision class
- class: system-vision
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol", "lazycortex-specs:lazy-spec.doc-height-protocol"]
  paths:
    - "*/vision.md"
    - "vision.md"
  context_from_frontmatter: [spec_source_requests]
  experts:
    main:
      - name: <system-designer-expert>
      - name: <editor-expert>
- class: system-design
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol", "lazycortex-specs:lazy-spec.doc-height-protocol"]
  paths:
    - "*/design.md"
    - "design.md"
  context_from_frontmatter: [spec_source_requests]
  experts:
    main:
      - name: <system-designer-expert>
      - name: <editor-expert>
    validation:
      architect_review:
        name: <architect-expert>
        section: Architect review
        position: bottom
# system-tech class — the product-root tech.md AND the content-root (project-wide) tech.md;
# the architect writes the technologies the level is built with — stack and platforms, never
# code structure — and the height protocol keeps the product document from repeating the
# content-root one; no validators
- class: system-tech
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol", "lazycortex-specs:lazy-spec.doc-height-protocol"]
  paths:
    - "*/tech.md"
    - "tech.md"
  experts:
    main:
      - name: <architect-expert>
# architecture.md class — architect writes; opt-in sibling, feature/change-level only (like
# code-plan/test-plan below, no context_from_frontmatter: the doc lives beside design.md in the
# same asset directory, and its writer's context comes from the checkbox dispatch that opens the
# doc, not from a re-attached originating request)
- class: architecture
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol"]
  paths:
    - "*/architecture.md"
  experts:
    main:
      - name: <architect-expert>
    validation:
      planner_review:
        name: <planner-expert>
        section: Planner review
        position: bottom
# ui-design.md class — ui-designer writes; one architect_review validation slot (screen/navigation
# shape checked against the architecture before implementation). Opt-in sibling like architecture
# above, created by a ticked launch checkbox; deliberately no context_from_frontmatter — its
# writer's inputs are the approved design.md / use-cases.md beside it (per the playbooks), not the
# originating request
- class: ui-design
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol"]
  paths:
    - "*/ui-design.md"
  experts:
    main:
      - name: <ui-designer-expert>
    validation:
      architect_review:
        name: <architect-expert>
        section: Architect review
        position: bottom
# system-ui-design class — the product-root ui-design.md (the product's shared look: design
# system, recurring screen patterns, navigation skeleton), above which the assets' own ui-design
# docs refine. Product roots only — the content root never hangs one. The same ui-designer writes
# it and the architect validates, as on the asset class; the doc-height protocol keeps it at the
# product's altitude. The glob is the asset class's — a typed document routes by type, so the
# two never collide.
- class: system-ui-design
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol", "lazycortex-specs:lazy-spec.doc-height-protocol"]
  paths:
    - "*/ui-design.md"
  experts:
    main:
      - name: <ui-designer-expert>
    validation:
      architect_review:
        name: <architect-expert>
        section: Architect review
        position: bottom
# code-plan.md class — planner writes; tester + architect validate (the plan is checked against
# the architecture before execution)
- class: code-plan
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol"]
  paths:
    - "*/code-plan.md"
  experts:
    main:
      - name: <planner-expert>
    validation:
      tester_review:
        name: <tester-expert>
        section: Tester review
        position: bottom
      architect_review:
        name: <architect-expert>
        section: Architect review
        position: bottom
# test-plan.md class — tester writes; developer validates (never the tester itself)
- class: test-plan
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol"]
  paths:
    - "*/test-plan.md"
  experts:
    main:
      - name: <tester-expert>
    validation:
      developer_review:
        name: <developer-expert>
        section: Developer review
        position: bottom
# code-report.md class — developer writes; no validators
- class: code-report
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol"]
  paths:
    - "*/code-report.md"
  experts:
    main:
      - name: <developer-expert>
# test-report.md class — tester writes; no validators
- class: test-report
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol"]
  paths:
    - "*/test-report.md"
  experts:
    main:
      - name: <tester-expert>

- class: data-report
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol"]
  paths:
    - "*/data-report.md"
  experts:
    main:
      - name: <data-writer-expert>

- class: docs-report
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol"]
  paths:
    - "*/docs-report.md"
  experts:
    main:
      - name: <docs-writer-expert>

# design.md class of a research asset (research-design) — designer writes the research design
# (sections per the research-design template) from the originating request; one
# researcher_review validation slot (can each question be answered as posed, are the boundaries
# set, is the known part sourced). context_from_frontmatter folds the originating request(s) into the writer's
# bundle, same as design/bug.
- class: research-design
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol"]
  paths:
    - "*/*/design.md"
  context_from_frontmatter: [spec_source_requests]
  experts:
    main:
      - name: <designer-expert>
      - name: <editor-expert>
    validation:
      researcher_review:
        name: <researcher-expert>
        section: Researcher review
        position: bottom
# research.md class (research-report) — the research tool's report, researcher writes from the
# approved research design; NO validators — the report is accepted by the operator, and a second
# expert would double the cost of every round. Not a journal: stage-bearing, edited in place.
- class: research-report
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol"]
  paths:
    - "*/research.md"
  experts:
    main:
      - name: <researcher-expert>
      - name: <editor-expert>
# bug.md class — tester writes the report; developer validates (the same DV shape product-config
# Step 12 generates); context_from_frontmatter folds the originating request(s) in
- class: bug
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol"]
  paths:
    - "bugs/*/bug.md"
  context_from_frontmatter: [spec_source_requests]
  experts:
    main:
      - name: <tester-expert>
    validation:
      developer_review:
        name: <developer-expert>
        section: Developer review
        position: bottom
```

`<use-case-writer-expert>` / `<designer-expert>` / `<system-designer-expert>` / `<architect-expert>` / `<ui-designer-expert>` / `<planner-expert>` / `<developer-expert>` / `<tester-expert>` / `<data-writer-expert>` / `<docs-writer-expert>` / `<researcher-expert>` / `<editor-expert>` are placeholders for the consumer-supplied COMPOSED expert key (typically `<domain>.<role>` from `lazycortex-experts`, e.g. `claude-plugin.designer` — never a bare role word like `designer`; a project-local override expert key works the same way). The bare `vision.md` / `design.md` / `tech.md` entries of the system classes catch the project-wide set that lives loose at the spec content-root (`spec.vault_root`, default `specs`), beside `requests/`. When the consumer has not registered one of them yet, omit that class until the expert exists — without a registered `main`, the dispatcher logs a no-writer warning per-tick. `<editor-expert>` is the one exception: it is never the reason to omit a class. It stands second in `main` on the eight prose classes — `vision`, `system-vision`, `use-cases`, `system-use-cases`, `design`, `system-design`, `research-design`, `research-report` — so the editing pass runs after the author in every main round, before the document reaches the operator; when no `<domain>.editor` is registered, drop that one entry and seed the class with its author alone. **The editor joins on re-run.** A class of those seven that already exists with its author as the only main writer gains the editor entry the moment a `<domain>.editor` of the same domain as `main[0]` appears in the experts registry — an append at position two, never a rewrite of the author's entry, stated as `editor-joined: <class>…`; a class the operator narrowed to a `review_expert` override or wired to a different chain is left alone. Journals, plans, `request`, `bug`, `system-tech`, `architecture`, and the two ui-design classes carry no editor: journals are only appended to, the rest are lists and structure where the prose canon buys little per dispatch. The `bug` class above is that layout's own class (bug-kind layout substitutes `bug.md` for `design.md`); it carries the same `context_from_frontmatter: [spec_source_requests]` key as `design`.

The `design` and `test-plan` classes' `main` experts carry one dispatch beyond ordinary review-writing: `spec.coordinator`'s change-cascade dispatch (`lazy-spec.coordination-playbook.md` Chapter 4, wire shape in `lazy-spec.lifecycle-protocol.md` Part 4) sends them to fold a change's design delta into a *different* asset's own `design.md` / `test-plan.md`. That folded document is a catalog document like every other: the writer returns it through its job's `result/`, and the coordinator — which owns cascade sequencing and therefore knows which asset the delta was folded into — lands it on the job-done wake with the `land-result` verb the specs CLI carries, naming the job dir and the target document, committed under the collector's bot identity with explicit paths. The writer never edits the other asset's document where it sits and never commits it.

`can_commit_in_repo` is therefore not what makes a cascade edit land — a cascade whose document never arrives in `result/` is an undelivered job, which the coordinator flags as such, not a missing flag. The seeding instruction itself is unchanged: set `can_commit_in_repo: true` on whichever expert each product wired into those two classes' `main[0].name`, read by the dispatch primitive from the expert's own registration and never from the wire bundle (a state-mutating op never takes caller-side a field its owner can read itself). What the flag governs is work that lands OUTSIDE the spec catalog.

`context_from_frontmatter` is a generic class-config key (not tied to any one document origin): at main-job dispatch, the dispatcher reads each named frontmatter key off the document under review, resolves wikilink (`[[path]]`) or bare repo-relative values to repo files, and folds every resolved file into the job bundle's `context/`. `spec_source_requests` reaches a doc two ways — `lazy-spec.request-apply`'s `ensure_source_request` writer stamps it onto an attach target's primary doc, and `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" seed-doc` copies the status folder-note's union (stamped there at apply) onto every checkbox-seeded doc — so carrying the key here means the design writer's job bundle includes the originating request file(s), the same distribution pattern plan 2 uses for guideline context. An unresolvable value is never silent — it surfaces as a warning on the tick summary, never a dispatch failure.

Validator composition follows one rule: the architect is the standing validator of everything design-shaped (`design`, `system-design`, `ui-design`, `system-ui-design`, and `code-plan` against the architecture), the designer validates the actors/flows that precede design (`use-cases`, `system-use-cases`), the developer validates the plans that will drive execution (`test-plan`) and the bug report (`bug`), the researcher validates the research design (`research-design`), and no class is validated by its own main writer. `architecture` keeps its `planner_review` slot (the planner checking whether the doc holds enough decisions to decompose into a plan). The vision classes (`vision`, `system-vision`), the report classes (`code-report`, `test-report`, `data-report`, `docs-report`), `system-tech`, and `research-report` wire no validators — their doc is approved by the operator directly through the standard review UI. No class carries a `terminal` block — these classes have no post-approve routing (the apply transition completes the request lifecycle; downstream is the per-asset gate machine, not another review round). The settings-migration ladder's older steps (`_add_architecture_class` / `_add_planner_review_to_design` in `lazycortex-core`'s `bin/lazy_settings_migrations/review.py`) predate this composition — they migrate old vaults to the pre-`system-design` shape; the current composition reaches an existing vault by manual migration, not by ladder.

**`tech.md` carries no review class, and gains no planner-validation slot here.** `ReviewClassName` (`lazycortex-core`'s `bin/constants.py`) is a closed set — `plan` (legacy), `code-plan`, `test-plan`, `code-report`, `test-report`, `design`, `bug`, `architecture` — with no `tech` token, and no `class: tech` entry exists anywhere in this seed or in the settings-migration ladder (`lazycortex-core`'s `bin/lazy_settings_migrations/review.py`). A product's `tech.md` is authored inline by `lazy-spec.create-from-code` (product-level) or by hand (feature/change-level — `lazy-spec.audit`'s own source-staleness check reads it as a plain file, never as a review-dispatched one); it is never dispatched through review, so there is no review class for a planner-validation slot to attach to. Nothing in this seed changes for `tech`.

**These same classes are also the launch-checkbox expert source.** `spec.coordinator` (dispatched by the `lazy-spec.coordinator-watch` routine, per `lazy-spec.coordination-playbook.md` Chapter 3) resolves a ticked checkbox's expert from the review class whose name matches the checkbox's own RESULT document — a uniform rule with no label-keyed exceptions: the checkbox that produces a `code-plan` resolves the `code-plan` class, a `test-plan` the `test-plan` class, and each tool's implementation checkbox the class named after that tool's own `report_doc` — `code-report`, `data-report`, `docs-report`, `test-report`, `research-report`. Which checkboxes exist at all is declared by the asset's type and tool playbooks, not by a table here. Each class's `experts.main[0].name` is the dispatched expert — whichever expert a product registered there (the placeholders above, or whatever `lazy-spec.product-config`'s wizard assigned instead). Review on a finished job's report is opened by the coordinator itself on its `job-done` wake, through the class matching that report's own document type; `lazy-spec.gate-tick` no longer does it.

**Suggest `workspace: branch` on whichever expert is wired into a report class's `main[0].name`.** The acceptance cycle these two classes drive (`lazy-spec.coordination-playbook.md` § 6) runs its launch-checkbox job and every continuation on a job-scoped branch, enforced by the runtime, not by prose — see `lazy-core.expert-runtime-schema.md` § Workspace for the mechanics and `experts[<name>].merge` for the companion merge setting. This is a seed proposal only, same discipline as `can_commit_in_repo` above: `/lazy-experts.install` already seeds `workspace: branch` on its own developer/tester entries when the consumer uses `lazycortex-experts`; when the consumer supplies a project-local expert instead, point them at that same setting by hand — never overwrite an existing `workspace` value on an entry this skill does not own.

### 6f. Class protocols + retired-sieve cleanup (MANDATORY when 6d/6e classes are added)

The writers of the 6d/6e classes are dispatched by `lazycortex-review`'s coordinator, and its dispatch rule reads each class entry's optional `protocols` list (see `lazy-review.coordination-playbook.md`, Dispatch) — that list is where this plugin's wire contract rides. Ensure every 6d/6e class entry carries `protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol"]` — absent-only union: append the reference when the key or the entry predates it, never remove anything an operator added. `lazycortex-core:lazy-core.markdown-style` is deliberately NOT listed per class — it rides the section-level `review.protocols` default `lazy-review.install` seeds, and a per-class copy would only drift.

**Legacy cleanup.** Two leftovers from the retired md-scan sieve model may survive on an older repo:

- `routines["lazy-review.scan"]` — retired by `/lazy-review.install` (its `process-file` consumer no longer exists). Do not touch it here; report `legacy-scan-routine-present` so the operator re-runs that install.
- `.experts/.spec-imports/` — the retired `/spec.import` clone cache; nothing will ever populate it again. `Bash(test -d .experts/.spec-imports)`: **absent** → outcome `spec-imports-cache-absent`. **Present** → ask (this deletes data — propose, never silently delete). **No answer** → outcome `refused-no-answer`, cache untouched.

  ```
  Context (print before asking):
  - Where: /lazy-spec.install · Step 6f — Retired-sieve cleanup; target `<repo-root>/.experts/.spec-imports/` and its `.gitignore` line
  - Found: the directory exists (<N> entries); nothing will ever populate it again
  - Why asking: deleting data — the only case a cleanup proposes instead of acting
  - Answers: `Delete the cache and its .gitignore line` — both removed now, outcome `spec-imports-cache-removed`; `Leave it for now` — untouched, outcome `skipped-operator-kept-cache`, offered again on the next run while the directory exists
  AskUserQuestion: header "Retired cache", question "Delete the retired `/spec.import` clone cache at `.experts/.spec-imports/` in <repo> together with its `.gitignore` line?", options `Delete the cache and its .gitignore line` / `Leave it for now` with the descriptions above.
  ```

Outcome: `wiring-applied:<N>` where N is 0..11 (the four 6a–6d blocks plus the six 6e classes plus the 6f class-protocols sync), plus the 6f sub-outcomes (`class-protocols-seeded:<M>` / `class-protocols-already-present`, and the legacy-cleanup outcomes above when they fire).

## Step 6.5: Seed agent-model tiers

The plugin ships the `spec.coordinator` and `spec.catalog-coordinator` subagents (both wired as experts in Step 6c). Seed the `agent_models.lazycortex` group with this plugin's subagents by dispatching the shared primitive — it owns the `default-tiers.json` locate, the `lazycortex-specs:`-prefix filter, and the non-destructive per-key semantics (absent→add, equal→unchanged, different→kept-local). There is no inline tier logic here.

Dispatch, passing the scope resolved in Step 1 (`project` | `user`):

```
Skill(skill: "lazycortex-core:lazy-core.agent-models-seed", args: "prefix=lazycortex-specs scope=<scope>")
```

Fold the primitive's returned report block verbatim into this skill's Step 9 report. Surface its terminal outcomes:

- **`sot-missing`** — `lazycortex-core`'s `default-tiers.json` was not found → the primitive aborts; relay its message (`lazycortex-core not installed; install it before seeding lazycortex-specs tiers`) and do not fabricate seed lines.
- **`no-entries`** — the SOT lists no `lazycortex-specs:` agents → report it plainly (a maintainer must extend `default-tiers.json`); not an abort.

Step outcome: `seeded` (any entry added) or `unchanged`.

## Step 6.7: Register the upstream-tick routine

The `upstream/` fetch/detect pass (mirror external design sources, diff against the last-processed snapshot, hang an operator checkbox on drift) can run unattended on a schedule instead of the operator remembering to invoke `/lazy-spec.upstream-run`. This step registers that schedule routine via `/lazy-routine.register` — it does NOT hand-write the routine JSON into settings, and it does NOT configure `spec.upstream` itself (that is a hand-edit of the `spec` settings section per `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.config-protocol.md` Part 4; no wizard exists for it yet).

**Read first — register only when a source is configured.** Run `Bash("${LAZYCORTEX_PYTHON:-python3}" <core-cli> settings-get spec)` and inspect `upstream`. An absent section, or one carrying only the reserved limit keys (`max_units_per_tick`, `max_text_file_bytes`, `fetch_failure_threshold`) with no `<repo-key>` entry, means no upstream source is configured — a schedule routine with nothing to do is dead weight, so skip silently with outcome `skipped-no-upstream-configured` and continue to Step 7. Only when at least one non-reserved key is present does this step proceed. No question — the presence of a configured source is genuine project state, not a choice this step re-asks. Re-run this check on every re-invocation of `/lazy-spec.install` (not just the first) so a source added later still gets the routine wired without a separate manual step.

Invoke `lazycortex-core:lazy-routine.register` via the `Skill` tool, passing a `cfg` dict so the wizard runs programmatically (no per-field prompts). The exact routine:

```json
{
  "name": "lazy-spec.upstream-tick",
  "cfg": {
    "type": "schedule",
    "cron": "*/30 * * * *",
    "command": ["lazycortex-specs", "upstream-tick"]
  }
}
```

The daemon resolves `command[0]` (`lazycortex-specs`) to the plugin's bin script and runs `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" upstream-tick` on the configured cadence — the same primitive `/lazy-spec.upstream-run` invokes manually; both share one implementation, so a scheduled pass and a manual run behave identically. No `hooks_enabled` entry is set — the routine schema's empty default already silences every lazycortex hook inside its own subprocesses, which is what this routine's atomic per-unit commits need.

**Managed keys — `type,command`.** Pass them as `--managed type,command` per § Routine registrations are reconciled, never skipped; `cron` is the operator's cadence and stays outside the list. Outcome: `registered`, `refreshed`, `unchanged`, or `skipped-no-upstream-configured`.

## Step 6.9: Seed the vault spec and the catalog root's level note

The project-wide `vision.md` at the spec content-root — the **vault spec** — is the starting point of the whole catalog: it states what the project is, for whom, and what counts as success; the split into products is a consequence of it (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md` Part 1). `lazy-spec.product-config` refuses to register the first product while it is absent (accepting a pre-existing `design.md` without one as a legal pre-vision state), so this step seeds a draft before Step 7 offers that registration.

**Project scope only.** Vault content lives per-repo; at user scope skip silently with outcome `skipped-user-scope`.

1. Resolve the content-root: `<settings-dir>/<spec.vault_root>` (`spec.vault_root` from `Bash("${LAZYCORTEX_PYTHON:-python3}" <core-cli> settings-get spec)`, default `specs`).
2. If `<content-root>/vision.md` already exists — in any state, draft or approved — leave it untouched. Outcome: `already-present`. A content-root `design.md` without a vision is also left untouched — the pre-vision state is legal and migrated by the operator by hand, never by this step.
3. `Bash(mkdir -p <content-root>)`, then seed (or repair) the catalog root's **level note** — whether or not the vision exists — the folder-note `spec.catalog-coordinator` owns, at `<content-root>/<basename of content-root>.md`, carrying `spec_role: catalog`, the four level gates, and the coordinator's own body sections:

   ```
   Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" catalog-note backfill --root)
   ```

   The verb creates the note from the shipped level-note template when it is absent and, when it is present, adds only what it lacks — no key is rewritten, no section is moved, and the operator's `# Coordinator rules` and rendered `# Summary` survive byte-for-byte. Re-running it on a conforming note writes nothing. Fold its returned `note` path into the install's own commit.

4. When item 2 found neither file, seed the vault spec beside that note — never by copying a template yourself:

   ```
   Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" seed-doc --root <content-root>/<basename of content-root>.md --doc vision.md:system-vision)
   ```

   The primitive instantiates the `system-vision` type's template with every token filled (the content-root's own name stands in for the product at the catalog root), injects the type's `iconize_icon` / `iconize_color`, sets `spec_stage: empty`; seeding journals nothing. Fold the returned `doc` path into the install's own commit. Outcome: `seeded`.

No question — the seed is fully derivable. No review dispatch either: the shared `system-vision` review class already covers the content-root `vision.md` glob, so the review loop picks the document up through the normal channels once the operator starts filling it in. The gate `lazy-spec.product-config` enforces is the file's presence; any stricter condition (written / approved) is deliberately not part of this contract yet.

5. Backfill **every registered product's** level note the same way — one call per key in `products`, each landing at `<spec_path>/<leaf of spec_path>.md` (the folder-note convention, never the product's own key), so an existing catalog gains the level role, gates, and sections it predates:

   ```
   Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" catalog-note backfill <product-key>)
   ```

   Zero products registered yet (the from-scratch path — Step 7 registers the first one, and `lazy-spec.product-config` Step 11 calls this same verb for it) makes this a silent no-op.

Step outcome folds all three: `<vision seeded|already-present>` + `root-note-<created|updated|unchanged>` + `products-backfilled:<n>`.

## Step 7: Offer first product registration

The vault spec from Step 6.9 now exists, so registration can follow it — products are a consequence of the repo-wide spec.

```
Context (print before asking):
- Where: /lazy-spec.install · Step 7 — Offer first product registration; target `products` and `repos` in <settings-dir>/lazy.settings.json
- Found: `products` on record: <keys, or "none">; vault spec `<content-root>/vision.md`: <seeded | already-present>
- Why asking: the first product is genuine project config, and whether to register it now or later is the operator's call
- Answers: `register-now` — invoke `lazy-spec.product-config` via the `Skill` tool to walk through repo cfg + product cfg creation; it writes the product record into `products` and, for a code-bound product, the repo record describing its source checkout into `repos` (outcome `registered: <compound-key>`); `skip` — consumer config stays empty, outcome `skipped-per-user-choice`; the operator runs `lazy-spec.product-config` later when ready, and this step offers again on the next install run
AskUserQuestion: header "First product", question "Register the first product of <repo> now via the `lazy-spec.product-config` wizard, or later?", options `register-now` / `skip` with the descriptions above.
```

If `register-now`: invoke `lazy-spec.product-config` via the `Skill` tool. Report the dispatch outcome. If `skip`: state `skipped-per-user-choice`.

## Step 7b: Ensure product/category wiki axes (wiki-conditional)

`product` and `category` are the two classification axes a spec catalog needs. `lazycortex-wiki` owns `tag_axes`, which is repository-wide — one vocabulary for the whole vault, narrowed per scope — and this plugin never writes it directly: it goes through the blessed CLI-subprocess contract (the `$LAZYCORTEX_PLUGIN_DIRS` binary lookup). `lazycortex-wiki` is NOT a dependency of `lazycortex-specs`, so this whole step is conditional and silent on absence: no question, no abort, no partial-install warning.

**Locate the wiki CLI.** Same three-stage lookup `lazycortex-wiki/bin/axes.py`'s own `_resolve_core_cli` uses for a sibling plugin's binary — deliberately NOT the `<core-bin>` resolution Step 5b-b uses (that one reads `installed_plugins.json`'s `installPath` directly, a different mechanism suited to a hard dependency this skill already knows is installed; `lazycortex-wiki` is optional here, so its absence from `installed_plugins.json` and an unset `$LAZYCORTEX_PLUGIN_DIRS` both need a graceful miss, which the glob-based lookup gives for free): `$LAZYCORTEX_PLUGIN_DIRS` first — empty at plain interactive install-time, since only the daemon exports it — then the dev-vault sibling layout, and only then a version-sorted glob over the plugin cache. The order is the whole point: reaching the cache before the sibling would silently run a stale installed copy in a checkout that carries the wiki's own sources.

Every sub-step below uses only `Bash(test *)` and `Bash(ls *)` — both on this skill's `allowed-tools` line — rather than a single compound multi-line script, so no new Bash pattern needs whitelisting for this step:

1. **Env-dirs stage.** `Bash(test -n "$LAZYCORTEX_PLUGIN_DIRS" && echo "$LAZYCORTEX_PLUGIN_DIRS")`. Empty output → go to stage 2. Non-empty → split the printed value on `:`; for each candidate `<dir>`, `Bash(test -f "<dir>/bin/lazycortex-wiki" && echo "<dir>/bin/lazycortex-wiki")` until one prints a path — hold that as `$WIKI_CLI` and skip stages 2 and 3.
2. **Dev-vault sibling stage** (only when stage 1 found nothing). In a checkout that carries the plugin sources themselves, the wiki's binary sits beside this plugin's own tree: `Bash(test -f plugins/claude/lazycortex-wiki/bin/lazycortex-wiki && echo plugins/claude/lazycortex-wiki/bin/lazycortex-wiki)`, run from the repo root. A printed path is `$WIKI_CLI` — skip stage 3. No output → go to stage 3. This stage is what keeps a dev checkout on its own sources instead of a stale installed copy, and it is the stage a plain interactive install most often lands on when the daemon never exported the env var.
3. **Plugin-cache stage** (only when stages 1 and 2 found nothing). `Bash(ls <home>/.claude/plugins/cache/*/lazycortex-wiki/*/bin/lazycortex-wiki)`, where `<home>` is the absolute home directory (`Bash(test -n "$HOME" && echo "$HOME")` prints it). Nothing printed → `$WIKI_CLI` stays unresolved. One or more lines → each names a version-embedding path (`.../<version>/bin/lazycortex-wiki`); take the newest version by numeric sort, so `10.0.0` outranks `9.1.1`, matching `axes.py`'s own newest-version pick — as `$WIKI_CLI`. That one pattern is the whole enumeration: never `find` or a walk of the cache, and a refusal is terminal.

- `$WIKI_CLI` unresolved after all three stages → `lazycortex-wiki` is not installed on this machine. State `skipped-no-wiki` and move on to Step 8 — this is the normal, expected outcome for a repo without the wiki plugin.
- `$WIKI_CLI` resolved → continue below.

**Ensure the axes.** The axis vocabulary belongs to the repository, not to any one scope, so this is a single call regardless of how many products are registered. `$WIKI_CLI` resolved to an absolute path in the plugin-cache case (stage 3 above) and to a repo-relative one in the dev-vault case (stage 2), neither of which the literal-prefix `Bash("${LAZYCORTEX_PYTHON:-python3}" *)` pattern would match — prefix the call with `test -f "$WIKI_CLI" &&` so the invoked text always starts with `test `, matching the already-allowed `Bash(test *)` pattern regardless of how `$WIKI_CLI` resolved:

```
Bash(test -f "$WIKI_CLI" && "${LAZYCORTEX_PYTHON:-python3}" "$WIKI_CLI" ensure-axes product category --repo <repo-root>)
```

Idempotent union into `wiki.tag_axes` — a repository that already declares both axes reports `{"status": "unchanged"}` and is left untouched; an operator's other axes are never dropped, and no scope is read or written. A scope narrows the vocabulary to the axes it uses, so declaring these two here makes them available to the spec scope without touching any scope's own list.

A non-zero exit is non-fatal: surface its stderr first line in the report and continue below; do NOT abort the install.

**Seed the spec-catalog scope defaults.** A spec catalog's wiki scope skips unfinished and working documents by default: a stage-bearing doc is curated only once `spec_stage` reaches `approved` (a doc with no `spec_stage` at all — a terms dictionary, a decisions registry — passes; markdown attachments mirror their owner's stage per `lazy-spec.file-roles-protocol.md` § Attachments, so they follow the owner), a doc whose own review rejected it stays out via `review_result`, a doc under review is already skipped by the `review_active` predicate the configure wizard seeds, and the request inbox (`<vault_root>/requests/**`, raw requests and their archive) plus plan/report working papers are excluded by name — the scope's own `topics_index` is skipped structurally and needs no entry. `/lazy-wiki.configure` asks no exclude question for a scope covering the catalog; this seed is the one source. The seed is idempotent and never overwrites an operator's own predicate for the same key, so a project that deliberately loosened the default keeps its loosening on every re-run.

Resolve the scope covering each registered product: for every entry in `products` (skip the `_version` meta key), build the repo-relative probe path `<vault_root>/<spec_path>/design.md` — `<vault_root>` is the `spec.vault_root` setting (default `specs`); drop the `<vault_root>/` segment when it is `.`. `resolve-scope` matches the path against configured globs only — the file need not exist on disk yet:

```
Bash(test -f "$WIKI_CLI" && "${LAZYCORTEX_PYTHON:-python3}" "$WIKI_CLI" resolve-scope <vault_root>/<spec_path>/design.md --repo <repo-root>)
```

`{"scope_id": null}` → no configured wiki scope covers this product yet; count it under `no-scope` and skip it. Two products resolving to the same scope must not double-trigger the seed — dedupe scope ids across the loop. For every distinct `<id>`:

```
Bash(test -f "$WIKI_CLI" && "${LAZYCORTEX_PYTHON:-python3}" "$WIKI_CLI" ensure-scope-config <id> --filter-json '{"spec_stage": {"in": [null, "approved"]}, "review_result": {"not_in": ["rejected"]}}' --exclude '<vault_root>/requests/**' '**/*-plan.md' '**/*-report.md' --repo <repo-root>)
```

A non-zero exit from either call is the same non-fatal case as above — count it under `cli-failed`, surface its stderr first line, continue.

**Keep deferred documents out of the wiki routines.** The scope filter above keeps a `spec_stage: deferred` document out of the wiki graph, but the wiki's git-watch routines judge a changed file by their own `filter` block, not by the scope's: without a predicate of their own, every commit touching a parked document still dispatches a terms-curator job and a structure-curator job. Seed the predicate into each wiki routine the repository has registered, through the core CLI's routine seed — the same absent-key-only contract as the scope seed, so an operator's own `spec_stage` predicate on a routine is never overwritten. For each `<routine>` in `lazy-wiki.scan`, `lazy-wiki.terms-scan-<id>` (one per scope id resolved above), `lazy-wiki.structure-scan`, `lazy-wiki.structure-scan-deletes`, `lazy-wiki.structure-scan-renames`:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" <core-cli> routine-ensure-filter <routine> --filter-json '{"spec_stage": {"not_in": ["deferred"]}}')
```

`{"status": "error", "reason": "no such routine"}` (exit 1) means the repository never registered that routine — count it under `no-routine` and continue; it is the normal case for a repo without the structure map or without a terms dictionary. Files without frontmatter and documents without `spec_stage` pass a `not_in` predicate, so the seed narrows nothing but parked documents.

Outcome: `skipped-no-wiki`, or `axes-<added: N|unchanged>, preset-<seeded: N-scopes|unchanged>, routines-<seeded: N|unchanged> (no-scope: <M>, no-routine: <R>, cli-failed: <K>)` — the parenthetical is omitted when every count is `0`.

## Step 7c: Backfill `spec_doc_type` across the catalog

Every authored catalog document carries a `spec_doc_type` frontmatter key naming its document type (`lazy-spec.file-roles-protocol.md` § Document type). Documents written before typing landed carry none, and a document with no type resolves to no declaration — `lazy-spec.set-stage` refuses it, `lazy-spec.audit` FAILs on it, and the review class it belongs to cannot be found. Run the one-shot backfill:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" doc-type backfill)
```

It walks the spec content-root, derives each document's type from its `spec_role` (falling back to the filename stem when the document carries no role), and writes the key where it is missing. Report the returned `touched` / `skipped` / `cleaned` counts.

Idempotent by construction: a document already carrying the key is counted `skipped` and left byte-identical, so a fresh install reports zeros and a re-run after a bulk content import picks up only what is new. No folder-note is a candidate — neither an asset's status note nor a level note of a product or of the catalog root — and neither is an untyped stranger.

`cleaned` counts the level notes a stale key was taken back off. An earlier release derived a type from the `product` / `catalog` role and wrote `spec_doc_type: <role>` onto the level note itself, which no level-note schema has ever had room for: `note-check` reports it as `unknown-key` and `lazy-spec.audit` FAILs on it. The same walk strips it wherever it is still recorded.

**The backfill does not commit.** It leaves its writes in the worktree; committing them belongs to whoever is driving this install, in that repo's own commit.

Outcome: `backfilled: <touched>/<skipped>/<cleaned>` (`backfilled: 0/0/0` on a fresh install with no catalog yet).

## Step 7d: Backfill `spec_asset_type` and rename the renamed document types

Every asset's status folder-note carries a `spec_asset_type` frontmatter key naming what the asset is (`lazy-spec.coordination-playbook.md`, the input-facts chapter). Assets created before the key existed carry none, and the coordinator cannot load a type playbook without it. Two shipped document types were also renamed — `dev-plan` to `code-plan` and `dev-report` to `code-report` — and a document still carrying an old type name resolves to no declaration. Run all three passes:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" asset-type backfill)
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" doc-type rename dev-plan code-plan)
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-specs" doc-type rename dev-report code-report)
```

The backfill walks the spec content-root, derives each status folder-note's type from the name of the folder holding the asset, writes `unknown` where no declaration claims that folder, and reports `touched` / `skipped`. Each rename moves the declaration key, rewrites every document carrying the old type, renames a document whose basename matched the old type, moves the shipped template, and renames every same-named review class — reporting `declaration` / `docs` / `files` / `template` / `classes`.

All three are idempotent: a second run finds nothing under the old names and reports zeros, so re-running this step on an already-migrated repo is a no-op.

`spec_tools` is deliberately NOT backfilled. Which tools an asset is realised with is a judgement about its approved documents, not something derivable from the tree — the coordinator settles it on each asset's next wake, or the operator writes it by hand.

**None of the three commits.** They leave their writes in the worktree; committing them belongs to whoever is driving this install, in that repo's own commit.

Outcome: `migrated: <touched> typed, <docs> retyped, <files> renamed`.

## Step 8: Register the plugin-CLI Bash allow-pattern

The plugin ships `bin/lazycortex-specs` which other skills invoke via `Bash(lazycortex-specs ...)` — `lazy-spec.create-asset` resolves a product record, `spec.coordinator` flips gates and dispatches jobs through it, etc. Expert subprocesses spawned by the `lazy-core.runtime` daemon run under Claude Code's `dontAsk` permission mode — that mode silently denies any Bash command not on the auto-allow list. Without this entry, every cross-skill CLI invocation from `spec.coordinator` or any other dispatched expert falls back to `Permission to use Bash has been denied because Claude Code is running in don't ask mode`, and the agent drifts off-protocol mid-step. (The apply routine is a `command:`-shape Python primitive, not an LLM dispatch — it does not pass through `dontAsk` mode but still benefits from the allow-pattern when an operator session runs `/spec.apply-request` manually.)

Per `lazy-core.hygiene` § Settings split, per-tool permissions live in `settings.local.json` (gitignored), never tracked `settings.json`. Target file resolves from Step 1's scope:

- project install → `<repo-root>/.claude/settings.local.json`
- user install → `~/.claude/settings.local.json`

Apply via the `lazycortex-core` CLI (idempotent — already-present patterns are no-ops):

```
Bash("${LAZYCORTEX_PYTHON:-python3}" <core-cli> permission-allow <settings-local> 'Bash("${LAZYCORTEX_PYTHON:-python3}" *)')
```

Outcome: `cli-allow-added` or `cli-allow-already-present`.

## Step 9: Verify

- Confirm the consumer dir from Step 3 now exists.
- Confirm `<consumer>/.claude/rules/spec.decisions.md` exists and is byte-identical to `${CLAUDE_PLUGIN_ROOT}/rules/spec.decisions.md` (Step 3b).
- Confirm the `lazy-spec.gate-tick` routine is present in `lazy.settings.json` (`routines.lazy-spec.gate-tick`) — pure script, no `protocols` entry.
- Confirm the `lazy-spec.coordinator-watch` routine is present in `lazy.settings.json` (`routines.lazy-spec.coordinator-watch`) and that its `protocols` list carries both `lazycortex-specs:lazy-spec.coordination-playbook` AND `lazycortex-core:lazy-core.markdown-style`.
- If Step 4 set a language: confirm `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> settings-get spec` reports the chosen `language`.
- Project scope only: confirm `<content-root>/vision.md` exists (Step 6.9), or a pre-vision `design.md` without one.
- Unless Step 6 was `skipped-user-scope`: confirm the blocks are present in `lazy.settings.json` (`experts.spec.coordinator`, at least one `review.classes[]` entry covering `requests/*.md` with `terminal.routing` naming `spec.catalog-coordinator` at `position: top`; and `routines.lazy-spec.request-open` / `routines.lazy-spec.request-apply` with `paths` of `<vault_root>/requests/*.md`, unless the daemon gate skipped them). Note: no `experts.lazy-spec.request-apply` entry — the apply routine is `command:`-shape, not expert-based.
- Confirm every 6d/6e `review.classes` entry carries `lazycortex-specs:lazy-spec.expert-signals-protocol` in its `protocols` list (Step 6f).
- **Wiki companion check (report-only).** The spec experts (architect above all) work best with the research surfaces `lazycortex-wiki` provides — the structure map, the domain tree, the terms dictionary, wiki query. Check the pairing and append one INFO line to the report; never ask a question, never install anything:
  - `lazycortex-wiki@lazycortex` absent from `installed_plugins.json` → `info: lazycortex-wiki is not installed — spec experts fall back to reading code directly; install and configure it (structure map, domain tree, terms dictionary, wiki scopes) for cheaper, better-grounded expert research.`
  - Installed, but `wiki.scopes` is empty AND `structure.depth_profiles` is empty AND `wiki.domains` is absent → `info: lazycortex-wiki is installed but nothing is configured — run /lazy-wiki.configure to give the spec experts a structure map, domain tree, or wiki scope to research against.`
  - Otherwise → no line.
- When Step 7b resolved `$WIKI_CLI`: confirm, for every scope it reported `ensured` against, that `wiki.scopes[<id>].tag_axes` now includes both `product` and `category`. When Step 7b was `skipped-no-wiki`, there is nothing to confirm.
- Report a summary line per task in the canonical Step list, plus:
  - Scope detected
  - Plugin version/commit from `installed_plugins.json` (`<version>` / `<gitCommitSha>`)
  - Consumer dir state from Step 3
  - Step 3b outcome (`rules-mirrored:<N>`)
  - Step 4 outcome (`language-on-record:<code>`, `language-default-en`, or `language-set:<code>`)
  - Step 5 outcome (`registered`, `refreshed`, or `unchanged`)
  - Step 5b outcome (`<registrar-outcome>+protocol-seeded`), plus 5b-b's `remote-sync-ok` or `remote-sync-not-pull-push:<value>`
  - Step 5c outcome (`registered`, `refreshed`, or `unchanged`)
  - Step 6 outcome (`wiring-applied:<N>` or `skipped-user-scope`)
  - Step 6.5 outcome (`seeded` or `unchanged`), with the primitive's report block folded in verbatim; surface `sot-missing` / `no-entries` if returned
  - Step 6.7 outcome (`registered`, `refreshed`, `unchanged`, or `skipped-no-upstream-configured`)
  - Step 6.9 outcome (`seeded`, `already-present`, or `skipped-user-scope`)
  - Step 7 outcome (`registered: <compound-key>` or `skipped-per-user-choice`)
  - Step 7b outcome (`skipped-no-wiki` or `ensured: <N-scopes> (no-scope: <M-products>, cli-failed: <K>)`)
  - Step 7c outcome (`backfilled: <touched>/<skipped>`)
  - Step 7d outcome (`migrated: <touched> typed, <docs> retyped, <files> renamed`)

## Failure modes

- **`/lazy-spec.install` aborts: plugin not installed** — `lazycortex-specs@lazycortex` has no entry in `~/.claude/plugins/installed_plugins.json` → add `"lazycortex-specs@lazycortex": true` to `enabledPlugins` in your `settings.json` and restart Claude Code, then re-run.
- **`/lazy-spec.install` reports `routine <name> already registered`** — the step called the registrar without its `--managed` list → re-invoke it in reconcile mode per § Routine registrations are reconciled, never skipped; an already-registered routine is refreshed, never skipped.
- **`/lazy-spec.install` reports `RoutineConfigError` on `lazy-spec.coordinator-watch`** — the recorded entry is still the `md-scan` shape an install predating the git-watch resew wrote, and reconcile cannot merge a type change → answer the shape-conflict question with `merge-shipped`, or run `/lazy-routine.unregister lazy-spec.coordinator-watch` and re-run install.

## Notes

- **Idempotent**: running this skill multiple times is safe. Every write follows the File-sync policy — absent → write, cleanly mergeable → merge silently, genuine conflict → the only case that asks. The consumer dir is never recreated and orphaned entries are kept, never deleted.
- **Re-run after `/plugin update`**: this skill creates the one consumer dir and mirrors the plugin's own `rules/` (Step 3b re-syncs on every run). After a plugin update, the plugin's reference docs and templates refresh in cache automatically — no resync needed for those. Steps 5, 5b, and 6 surface any new wiring requirements on the next run.
- **Scope independence**: running at project scope does not affect other projects or the global config.
- **Per-product overrides** are NOT created by this skill — they live under `.claude/templates/spec.<context>/<compound-key>/` (one folder per asset type or the product level that the operator wants to customize), scaffolded by `lazy-spec.product-config` when the user opts into customization.
- **User-scope skip**: Step 6 (request runtime wiring) is a project-scope-only step. Request files live in `<vault-root>/requests/` per-vault; wiring at user scope would point the daemon at the wrong path. The skill detects user scope at Step 1 and silently skips Step 6 (`skipped-user-scope`).
