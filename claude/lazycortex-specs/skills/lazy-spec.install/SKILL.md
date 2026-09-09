---
name: lazy-spec.install
description: "Run when the operator asks to set up the spec system in a repo, after enabling or updating lazycortex-specs, or when spec skills misbehave because the `spec` settings section, the per-category template-override dirs, the `lazy-spec.gate-tick` routine, the request-handler runtime, or the content-root vault spec (`vision.md`) are missing. Also the place the vault spec gets seeded and the first product gets registered. Idempotent — safe to re-run."
allowed-tools: Read, Write, Edit, Glob, Skill, Bash(mkdir -p *), Bash(git rev-parse*), Bash(test *), Bash(date *), Bash(PYTHONPATH=* python3 *), Bash(lazycortex-core *), Bash(lazycortex-wiki *), Bash(ls *), AskUserQuestion, Agent
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

## Execution discipline (MANDATORY — read before any action)

This skill has 18 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

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
   - `Step 10 — Log the run`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `created`, `already-exists`, `skipped-per-user-choice`).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1: Detect install scope

Scope = **where the plugin is actually enabled**, not where `/plugin install` last ran. The `scope` field in `installed_plugins.json` records the install command's origin, which drifts from the activation scope — a plugin enabled per-project in `.claude/settings.json` can carry an install record of `scope: "user"`. Enablement is the source of truth for where config belongs.

Resolve it via the core CLI, which reads `enabledPlugins` from the project settings first, then the global settings, and falls back to the install record's own `scope` only when neither settings file enables the plugin:

```
Bash(lazycortex-core detect-scope lazycortex-specs@lazycortex)
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

The plugin install path (`<installPath>`) is the `installPath` field from `installed_plugins.json` for `lazycortex-specs@lazycortex`. The plugin ships:

- Protocol-contract docs at `${CLAUDE_PLUGIN_ROOT}/references/*.md`
- Default authored-doc templates at `${CLAUDE_PLUGIN_ROOT}/templates/spec.<category>/` (one folder per built-in category: `spec.feature/`, `spec.change/`, `spec.bug/`, `spec.product/`, `spec.request/`; operator-defined categories add their own under `spec.<name>/` via `/lazy-spec.add-asset-type`)

These are read directly from the plugin cache at runtime — this skill does NOT copy them into the consumer tree.

## Step 3: Ensure consumer dirs

Create (with `mkdir -p`) the single consumer directory that holds per-project artifacts:

| Path (relative to consumer root) | Purpose |
|---|---|
| `templates/spec.feature/`, `templates/spec.change/`, `templates/spec.bug/`, `templates/spec.product/`, `templates/spec.request/` | One per category; each holds optional `<compound-key>/` per-product override sub-folders for that category's templates |

Report `created` or `already-exists`.

This skill does NOT create a `templates/spec.workflows/` dir — workflow machinery has been removed from the plugin. Products live in the `products` settings section and repos live in the `repos` settings section, not in rule files — `.claude/rules/` carries only the plugin's own authoring rules, mirrored in Step 3b below.

Project scope only: if a spec output directory is needed (e.g. a `Specs/` vault root), defer that decision to `lazy-spec.product-config` — the only vault content this skill creates is the vault-spec draft (Step 6.9); everything else is `lazy-spec.product-config`'s.

## Step 3b: Mirror plugin rules into `.claude/rules/`

Mirror every rule file shipped under `${CLAUDE_PLUGIN_ROOT}/rules/` into `<consumer>/.claude/rules/` — today this is the single file `spec.decisions.md`, the plugin's first rule. References, skills, commands, and templates stay in the plugin and are read by absolute path from `${CLAUDE_PLUGIN_ROOT}/...`; only rules ship into the consumer's session-loaded set (same split `lazy-python.install` Step 1 already applies to its own three rules).

Install-managed mirror per the **File-sync policy** above: absent → copy (`installed`); byte-identical → nothing (`unchanged`); different → overwrite from the shipped source (`refreshed`). No diff preview, no merge, no question — the plugin owns these bytes end to end; a consumer wanting different content authors their own rule file. A no-longer-shipped rule (orphan) is left in place silently.

```
Bash(mkdir -p <consumer>/.claude/rules && for f in ${CLAUDE_PLUGIN_ROOT}/rules/*.md; do b=$(basename "$f"); t="<consumer>/.claude/rules/$b"; if [ ! -f "$t" ]; then cp "$f" "$t"; echo "installed:$b"; elif cmp -s "$f" "$t"; then echo "unchanged:$b"; else cp "$f" "$t"; echo "refreshed:$b"; fi; done)
```

Outcome: `rules-mirrored:<N>` where N is the count of `installed` + `refreshed` rules (0 means every rule was already current).

## Step 4: Seed default language

Three settings sections back the spec system: `products` (cross-plugin), `repos` (cross-plugin — maps each repo key to its local checkout metadata), and `spec` (plugin-owned, holds `language`). All three are registered in lazy-core's `CURRENT_VERSIONS` and **auto-initialize on first `settings-get`**. Install does NOT hand-write any of them — `products` and `repos` records are authored by `lazy-spec.product-config`; this step only optionally seeds `spec.language`.

The repo authoring language is GENUINE project config — it cannot be derived — so this step keeps its question, but read-first: a language already on record is never re-asked.

**Read first.** Run `Bash(lazycortex-core settings-get spec)` and inspect `language`. If the section already carries a non-`en` `language` (a prior install or hand-edit set it), state outcome `language-on-record:<code>` and skip the question entirely. Only when nothing is on record (section absent, or `language` still the `en` default) do you ask.

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
Bash(lazycortex-core settings-get spec)
```

Parse the printed JSON, set `language` to the operator's code, and pipe the full object back:

```
Bash(printf '%s' '<patched-spec-section-json>' | lazycortex-core settings-set spec)
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

**Compare the recorded `paths` before accepting `already-present`.** `/lazy-routine.register` refuses a name it already knows, so a repo registered under an older shape keeps that shape forever — either an over-wide `["**/*.md"]` that re-parses every markdown file in the repository each tick, or a narrowed products-subtree glob that matches nothing under a layout with no literal `products/` segment. Read the entry back with `Bash(lazycortex-core settings-get routines)` and, when `routines["lazy-spec.gate-tick"].paths` differs from the shipped value above, refresh it the way Step 5b refreshes its filter: unregister, then re-register with the `cfg` above. A stale mask is an install-managed value that rotted, never a genuine conflict. Outcome: `paths-current` or `paths-migrated`.

The composite `{in: [...], not_in: []}` predicate is the shape the md-scan filter expects (same form as `lazy-review.scan`'s `review_active` / `review_result` clauses): `null` in `in` matches a missing key or explicit null, so an asset whose status note has not yet stamped `spec_cancelled` / `spec_released` still matches. The filter selects every live (un-cancelled, un-released) asset status folder-note across the vault content root.

The daemon resolves `command[0]` (`lazycortex-specs`) to the plugin's bin script and runs it as `lazycortex-specs gate-tick <matched-file-path>` — it **appends the matched file's absolute path as the last argv** (same convention `lazy-review.scan`'s `process-file` relies on). `gate-tick <asset_note>` reads the appended status folder-note path, clears the runtime sidecar's `active_job` marker when its bundle has landed a terminal marker (raising a `job-done` wake and opening report review on `DONE`), and runs `note_check` — it dispatches no jobs of its own and carries no protocol (pure script, nothing here ever produces LLM markdown output).

Outcome: `routine-registered`, or the `paths-current` / `paths-migrated` outcome from the comparison above when the routine was already registered.

## Step 5b: Register the coordinator-watch routine

`spec.coordinator` wakes on: a non-`@bot.`-authored commit reaching this checkout and changing an asset's status folder-note (the operator's own gesture — a tick, an edit — committed and pushed from wherever the operator works, then pulled in by this checkout's next daemon iteration); a non-empty `# Coordinator commands` section; a ticked option under one of the coordinator's own `[!question]` callouts; a launch-checkbox job's terminal marker landing, raised by `lazy-spec.gate-tick` as a `job-done` wake in the runtime sidecar and fired whoever authored the commit it landed alongside (`lazy-spec.coordination-playbook.md` § 1); or a sibling authored doc's own `review_result` appearing or changing, also regardless of that commit's authorship (`CoordinatorTrigger.DOC_TRANSITION`, same § 1). This step registers the `lazy-spec.coordinator-watch` **git-watch** routine via the blessed `/lazy-routine.register` skill — it does NOT hand-write the routine JSON into settings. Unlike `lazy-spec.gate-tick` (Step 5, an `md-scan` routine that re-scans every candidate file each tick), this routine watches the spec content root's own git history: the daemon computes each changed markdown file's last-changing commit and author once per tick (`lazy-core.runtime-schema.md` § 8 `git` / `watch: changed_files`) and hands that to the worker directly — there is no dirty-tree signal to read in the daemon's own checkout, and no separate "have I seen this commit" marker for the worker to maintain (the git-watch routine keeps its own cursor in `state.json`).

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
    "group_globs": [
      "<vault_root>/<spec_path>/*/*"
    ],
    "command": ["lazycortex-specs", "coordinator-dispatch"]
  }
}
```

`group_globs` collapses multiple changed paths under the same asset directory into ONE worker dispatch per tick (`lazy-core.runtime-schema.md` § git `group_globs`) — one glob per registered product, generated from the same `products` settings data the `<vault_root>`/`<spec_path>` resolution above already reads, at category/asset depth: `<vault_root>/<spec_path>/*/*` (drop the `<vault_root>/` prefix when `spec.vault_root` is `.`, same as `path_filter`). A path AT the glob's own depth (the category folder-note) and any path outside every product's glob stay ordinary single-file items — `coordinator-dispatch`'s `{path}` branch still serves those unchanged; only paths strictly below `<spec_path>/<category>/<slug>` (`asset_dir`) collapse into the grouped `{dir, paths, ...}` item. **On a from-scratch install with zero products registered yet** (Step 7, the first product registration, runs after this one), core's `routine_types.py` rejects an empty `group_globs` list (`'group_globs' must be a non-empty list`) — OMIT the `group_globs` key from the `cfg` dict entirely in that case, rather than writing it as `[]`, as the JSON shape above shows for the ≥1-product case. `lazy-spec.product-config` Step 12 then CREATES the key, with this product's own glob, the first time a product is registered or edited, and unions further products' globs into it from there. Re-running this step against an ALREADY-registered routine that lacks the key backfills it the same way — idempotently, as the union of every currently-registered product's glob (empty when there are none, in which case the key stays omitted), never removing an operator-added entry.

The first member carries no `spec_released` exclusion — a note is filtered out only while it is cancelled. An asset crossing `spec_released` into true is exactly the commit that must reach the dispatcher, since that is where the one-hop upward `asset-released` wake onto the product's level note is decided (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.catalog-playbook.md` § 5); excluding released notes would drop the release flip's own commit and the upward wake with it. A released asset is otherwise quiet — no gate moves, no checkbox hangs — so the widened member costs a resolved-and-discarded tick, never a spurious job. `product` and `catalog` never carry `spec_released` at all.

The second member selects on the presence of `spec_doc_type` rather than on a closed list of filenames: an empty `in` declares no allow-list, and `not_in: [null]` rejects a file where the key is absent or null. That leaves exactly the typed documents of the content root — the canonical authored docs and an expert's markdown attachments alike, without the routine having to know either set by name. An untyped stray markdown file under the vault matches nothing and wakes no coordinator.

`architecture.md` is an ordinary sibling doc kind — its review class (main writer `architect`, one `planner_review` validation slot) is wired in § 6e below, same as the other five doc kinds.

`<base_branch>` is the consumer's `daemon.git.base_branch` (the field is vestigial for a git-watch routine — the watch target is always local `HEAD` — but still required by the schema; see `lazy-routine.register/SKILL.md`'s git-type row). `<vault_root>` is the `spec.vault_root` setting (default `specs`), resolved the same way Step 5's `paths` glob and the `lazy-review.scan` sync (Step 6f) resolve it; when it is `.`, the `path_filter` collapses to `:(glob)**/*.md`.

The daemon resolves `command[0]` (`lazycortex-specs`) to the plugin's bin script and runs it once per changed file OR once per matched asset group (per `group_globs` above) as `lazycortex-specs coordinator-dispatch '<item-json>'` — a single JSON argv carrying either `{"path", "status", "sha", "author_name", "author_email"}` for an ungrouped file or `{"dir", "paths", "sha", "author_name", "author_email"}` for a grouped asset directory (`routine_types.dispatch_git`'s `command:` sub-shape), **not** a bare file path the way `lazy-spec.gate-tick` / `lazy-review.scan` pass one. For an ungrouped item, `coordinator-dispatch` resolves `item["path"]` against its `cwd` (the repo root, set by the daemon); when it names a status folder-note directly it detects whether the note carries a wake trigger, and when it names a sibling doc instead (the `any_of` filter's other member) it resolves the OWNING asset's status folder-note and detects a `review_result` transition against that note's own marker. For a grouped item, `coordinator-dispatch` resolves `item["dir"]` to the same owning asset's status folder-note directly and scans every member in `item["paths"]` for a wake trigger in one pass, dispatching at most one `spec.coordinator` job per tick regardless of how many members changed. Either shape dispatches one `spec.coordinator` job when a trigger fires; a no-op tick touches nothing.

If `/lazy-routine.register` reports the routine is already registered, accept its outcome (`unchanged` / `present`) — do not force-overwrite. A pre-existing `md-scan`-shaped entry from an install that predates the git-watch resew is a genuine shape conflict, not an `unchanged` match — surface it through the skill's normal conflict path rather than silently upgrading it. Outcome: `routine-registered` or `routine-already-present`.

**Stale-filter migration — read the registered filter before accepting `already-present`.** `/lazy-routine.register` aborts on a name it already knows, so accepting its outcome on an install that predates the level coordinator leaves the OLD filter in place forever: the routine keeps matching `spec_role: status` only, no level note ever reaches `coordinator-dispatch`, and every product's and the catalog root's system documents sit unstaged with nobody to promote them. Read the entry before accepting anything:

```
Bash(lazycortex-core settings-get routines)
```

Inspect `routines["lazy-spec.coordinator-watch"].filter`. It is **stale** whenever it differs from the shipped `filter` block in the `cfg` above in any way — a missing key, an extra key, a changed `in` / `not_in` list. Compare the whole block, not a checklist of known drifts: an enumerated test only catches the migrations someone remembered to write down, so the next key added to the shipped filter goes missing in every repo that already has the routine. Today's known drifts are all instances of that one rule — a `spec_role.in` without both `product` and `catalog`, a leftover `spec_released` key, an absent `spec_cancelled` key. A stale entry is the same class of finding Step 6d's terminal-writer swap is — an install-managed value that rotted against the shipped shape, not an `unchanged` match and not a genuine conflict — so it is refreshed silently and resolved the same way, by replacing the entry rather than editing settings by hand:

1. Hold the entry's `group_globs` list from the `settings-get` read above — `/lazy-routine.unregister` prints only `unregistered`, so the read just made is the only copy. Never re-derive the list from `products` alone: an operator-added glob is not in `products` and would be lost.
2. `Skill(skill: "lazycortex-core:lazy-routine.unregister", args: "lazy-spec.coordinator-watch")`.
3. Re-run this step's `/lazy-routine.register` call with the `cfg` above, carrying the held `group_globs` list verbatim (omit the key entirely when the removed entry had none).

The two calls are one migration, never left half-done: an unregister without the re-register leaves the daemon with no coordinator routine at all. A filter that matches the shipped block exactly is current — accept `already-present` and skip the migration entirely. Outcome: `filter-current` or `filter-migrated`.

### 5b-a. Seed the mandatory protocols

The coordinator reasons from `lazy-spec.coordination-playbook.md` on every dispatched job, and its jobs (`code-plan.md` / `test-plan.md` writers, the `code-report.md` / `test-report.md` journals the launch ladder opens, the coordinator's own `# Status brief` prose) all produce markdown in the vault — this routine, not `lazy-spec.gate-tick`, is the one that actually dispatches those jobs, so both protocols attach here. Attach them regardless of whether this step registered the routine or found it already present — the union is idempotent and never removes what the operator added:

```
Bash(lazycortex-core add-protocols --routine lazy-spec.coordinator-watch --ids lazycortex-specs:lazy-spec.coordination-playbook,lazycortex-core:lazy-core.markdown-style)
```

No question is asked here: a mandatory protocol is not an operator choice, and the step must also land under `lazy-core.autosetup`, where every question-gated step is skipped.

This sub-step carries no outcome of its own — it rolls into Step 5b's, which reads `routine-registered+protocol-seeded` or `routine-already-present+protocol-seeded`.

### 5b-b. Verify the coordinator's output can actually leave this checkout

The coordinator's every write — `# Status brief`, `[!question]` callouts, gate flips, `# Coordinator commands` locking — is a local commit in the daemon's own checkout. It reaches the operator only through the daemon's post-iteration `_git_post` push, which itself only runs when `daemon.git.remote_sync == "pull_push"` (`runtime_daemon.py`'s `_git_post`). A checkout with `remote_sync` unset or set to anything else piles up every coordinator commit locally, forever invisible to the operator.

Read the tracked `daemon.git` block. `<core-bin>` is `<installPath-of-lazycortex-core>/bin` — resolve `lazycortex-core@lazycortex`'s `installPath` from `installed_plugins.json`:

```
Bash(PYTHONPATH=<core-bin> python3 -c "from lazy_settings import load_tracked_section; from pathlib import Path; print(load_tracked_section(Path('<repo-root>/.claude/lazy.settings.json'),'daemon').get('git',{}).get('remote_sync','unset'))")
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

If `/lazy-routine.register` reports the routine is already registered, accept its outcome. Outcome: `routine-registered` or `routine-already-present`.

## Step 6: Wire the request-handler runtime

Request files at `<vault-root>/requests/` are processed by three runtime channels:

- **md-scan open (mechanical, command-based)** — fires on naked request files (no `review_active`, no `review_result`). Pure state flip: writes the opt-in frontmatter keys + Waiting banner and commits under the `lazy-spec.request-open` bot identity. No LLM spawn, ~1s latency. Routine `routines.lazy-spec.request-open` with `command:` shape pointing at `lazycortex-specs open-request`.
- **md-scan apply (mechanical, command-based)** — fires on post-finalize request files (`request_status: draft` + `review_result` in {`approved`, `approved-with-concerns`}). Reads the resolved routing prose, calls `lazycortex-specs scaffold-asset` for spawn targets — asset folder + status folder-note only, the note carrying the `spec_source_requests` union and its `## Source requests` projection; no document is seeded and no review is opened at apply (documents come later, one launch-checkbox tick at a time, via `lazycortex-specs seed-doc`) — records attribution on each attach target's primary doc (no callout) and re-opens its review, stamps terminal markers (`request_class`, `request_status`, mirror tag, status callout) and strips `# Routing`, atomic commit under `lazy-spec.request-apply` bot identity. No LLM dispatch — the worker is the Python primitive at `${CLAUDE_PLUGIN_ROOT}/bin/apply_request.py`, which also implements the attach and spawn enactment directly (no separate `spec.request-attach` / `spec.request-spawn` skills exist). Routine `routines.lazy-spec.request-apply` with `command:` shape pointing at `lazycortex-specs apply-request`.
- **lazy-review specialist** — `spec.catalog-coordinator`, running in its routing mode (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.catalog-playbook.md` § 10), runs all content work (classify, find candidates, surface the routing decision, fold to prose) during the review loop. Requires the agent registered as an expert AND a review class entry mapping `requests/*.md` to `spec.catalog-coordinator` under `terminal.routing` (the post-approve terminal-action section writer group that owns the `# Routing` heading — surfaces only after the operator approves the body, persists through finalize so the apply worker can read the resolved routing prose, and never triggers revert-to-main since operator choices are not concerns). The class declares a separate `main` chain — the consumer-supplied interpreter expert.

Without all three wired, the request inbox is dead from the daemon's perspective. The request runtime is part of the plugin's own surface — enabling the plugin means wanting it — so this step writes the blocks unconditionally; there is no `wire-now` / `skip` opt-in (per § Install philosophy).

**Project-scope only.** Request files live in `<vault-root>/requests/` per-vault; wiring at user scope would point the daemon at the wrong path. If Step 1 detected user scope, skip this step silently — outcome `skipped-user-scope`.

Read `lazy.settings.json` (create the file if missing) and merge the blocks per the File-sync policy: absent → write silently; present and cleanly mergeable → merge silently; genuine conflict (an existing entry whose shape contradicts the shipped one) → the only case that asks. Report `wiring-applied:<count-added>` (count of blocks newly added/merged; 0 means everything was already in place).

### 6a. md-scan open routine (mechanical, command-based)

Under `routines` add the key `lazy-spec.request-open` if missing:

```yaml
lazy-spec.request-open:
  type: md-scan
  interval_sec: 60
  timeout_sec: 30
  priority: 30
  paths: ["requests/*.md"]
  filter:
    folder_note: false
    frontmatter:
      review_active: {in: [null], not_in: []}
      review_result: {in: [null], not_in: []}
  command: ["lazycortex-specs", "open-request"]
```

The joint filter `review_active: [null] + review_result: [null]` catches files that have not yet entered the review loop — naked files (no frontmatter at all) AND partial-bootstrap files (`request_status: draft` set but `review_active` missing). The `review_result: [null]` clause excludes post-finalize files: finalize strips `review_active` AND stamps `review_result` (`approved` / `approved-with-concerns`), so those files match `review_active: [null]` alone but must be routed to the apply gate, not re-bootstrapped. The `folder_note: false` clause excludes the `requests/` folder-note (`requests/requests.md` — the Obsidian folder-note convention `<dir>/<dir>.md`): it is an inbox description carrying no `review_active` / `review_result`, so without this clause it matches the filter on every tick and the routine re-dispatches it forever (open-request finds nothing to do and never stamps the frontmatter that would drop it out). The command brings the file to canonical opt-in shape, atomic commit under `lazy-spec.request-open` bot identity.

Once the script commits with `review_active: true`, the file falls out of this routine's filter and into `lazy-review.scan`'s loop. After finalize stamps `review_result`, the apply routine (6b) takes over.

If the routine already exists, apply the File-sync policy: byte-identical → `unchanged`; a stale shape that the shipped delta upgrades cleanly → merge silently (`merged`). Upgrades that count as clean: adding the missing `review_result: [null]` clause; adding the missing `filter.folder_note: false` clause; setting `interval_sec` to `60` when it still carries the legacy `5` (an operator-chosen value other than 5 stays untouched) — all provided no local edit contradicts them. Only a genuine contradiction (a local edit that the shipped shape would overwrite incompatibly — older `expert:` form replaced by `command:`, a deliberately narrowed `request_status: [null]` filter, an operator-set `folder_note: true`) triggers the File-sync conflict question, filled as: Where — Step 6a, `routines.lazy-spec.request-open` in `<settings-dir>/lazy.settings.json`; Found — the local entry against the shipped shape as a unified diff; Why asking — that local edit contradicts the shipped shape; Answers — `merge-shipped` / `keep-local` per the policy.

### 6b. md-scan apply routine (mechanical, command-based)

Under `routines` add the key `lazy-spec.request-apply` if missing:

```yaml
lazy-spec.request-apply:
  type: md-scan
  interval_sec: 60
  timeout_sec: 60
  priority: 20
  paths: ["requests/*.md"]
  filter:
    folder_note: false
    frontmatter:
      request_status: {in: ["draft"], not_in: []}
      review_result: {in: ["approved", "approved-with-concerns"], not_in: []}
  command: ["lazycortex-specs", "apply-request"]
```

The daemon resolves `command[0]` (`lazycortex-specs`) to the plugin's bin script and runs it as `lazycortex-specs apply-request <matched-file-path>` — same convention as `lazy-spec.request-open`. The worker is a deterministic Python primitive (`${CLAUDE_PLUGIN_ROOT}/bin/apply_request.py`); no LLM dispatch happens at this gate. It parses the `# Routing` section, runs `lazycortex-specs scaffold-asset` for any spawn target — asset folder + status folder-note only, the note carrying the `spec_source_requests` union and its `## Source requests` projection; no document is seeded and no review is opened at apply (the request body is never copied anywhere — a checkbox-seeded doc's main writer reads the source request from its review job's `context/`, per `lazy-spec.request-protocol.md` § Body distribution rules) — maintains `spec_source_requests` frontmatter + the `## Requests` projection inside `# Sources` on each attach target's primary doc (attribution only, no callout) and opens a review cycle on that populated doc via `lazycortex-review start`, then stamps the request file's terminal markers and atomic-commits under `lazy-spec.request-apply` bot identity.

The joint filter `request_status: ["draft"] + review_result: ["approved", "approved-with-concerns"]` matches only the post-finalize state: finalize stamped `review_result` (clean approve OR approve-with-concerns) as its last step, and the terminal `request_status` has not been written yet (still `draft`). Stop-aborted reviews (no `review_result` ever written) and mid-review files (transient `review_*` keys present but `review_result` not yet stamped) do not match — apply only fires on a clean finalize. The worker reads the resolved routing prose that `spec.coordinator` folded into `# Routing` during review (its routing mode, per `lazy-spec.coordination-playbook.md` Chapter 7) and enacts it.

If the routine already exists, apply the File-sync policy: the older `expert: lazy-spec.request-apply` form (LLM-dispatched apply) is superseded by the shipped `command:` shape; the missing `filter.folder_note: false` clause is added; and `interval_sec` is set to `60` when it still carries the legacy `5` (an operator-chosen value other than 5 stays untouched) — when no local edit contradicts these, merge silently (`merged`); only when a local edit on that entry would be lost does it become a genuine conflict and raise the File-sync conflict question, filled as: Where — Step 6b, `routines.lazy-spec.request-apply` in `<settings-dir>/lazy.settings.json`; Found — the local entry against the shipped shape as a unified diff; Why asking — that local edit would be lost; Answers — `merge-shipped` / `keep-local` per the policy.

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

The `lazy-spec.request-apply` worker scaffolds entity folders (`features/<slug>/`, `changes/<slug>/`, `bugs/<slug>/`) under each registered product's `<spec_path>` — folder + status folder-note only. Every authored doc, `design.md` included, is created later by a ticked launch checkbox: the coordinator runs `lazycortex-specs seed-doc`, then opens the doc's review via `lazy-review.start` when the folder-note carries source requests, or waits for the operator's own commit into the skeleton otherwise. Those docs (`design.md`, `bug.md`, the opt-in `code-plan.md` / `test-plan.md`, and the `code-report.md` / `test-report.md` journals the launch ladder later opens for review on job completion) need their own review classes so the daemon dispatches the right writer for each one — without these classes, checkbox-seeded or later-authored docs sit at `[!hint] Waiting #review/in-process` forever because no class matches their paths. The same applies to the two **system-level** classes: the product-root `design.md` / `tech.md` pair and the identical pair at the spec content-root (the project-wide spec — no config key declares it; the files' existence is the declaration) are typed `system-design` / `system-tech` and reviewed under their own classes, never under the asset-level `design` class.

Under `review.classes` append the entries below if no existing entry's `paths` already covers them. **Each entry carries a `class:` key with the exact bare doc-kind token** (`vision`, `system-vision`, `use-cases`, `design`, `system-design`, `system-tech`, `architecture`, `ui-design`, `code-plan`, `test-plan`, `code-report`, `test-report`). A review class is declared by this config, not by a code-side enum: only the subset the settings-migration ladder keys off carries a token in `ReviewClassName` (`lazycortex-core`'s `bin/constants.py`) — `design`, `bug`, `architecture`, `code-plan`, `test-plan`, `code-report`, `test-report` — and the rest (`use-cases`, `system-design`, `system-tech`, `ui-design`) are review classes the older ladder steps never touch, so a matching constant is neither present nor needed; the `vision` / `system-vision` classes are seeded into existing vaults by the v10 → v11 migration step, which keys off the literal class tokens. Omitting the `class:` key, as an earlier revision of this seed did for the path-only siblings, makes a fresh install diverge from a migrated-in-place vault: `migrate_all`'s `_add_architecture_class` / `_add_planner_review_to_design` steps both search for `entry.get("class") == "<token>"` and, finding no match on a `class`-less entry, append a SECOND `architecture` class and silently skip `design`'s `planner_review` slot. Glob `<spec_path_prefix>/products/*` is illustrative — the real `paths` glob each consumer writes mirrors the `spec_path` shape they registered (e.g. `Server/products/*` for a `spec_path: Server/products/<key>` product). For a vault with multiple products, the globs cover them all uniformly because the product key is a single path segment under the same prefix.

```yaml
# vision.md class (asset-level) — designer writes goals/value for one feature or change; NO
# validators — the writer and the operator close the loop (a designer validator would be
# self-validation; an architect has nothing to check in a goals-and-value document)
- class: vision
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol", "lazycortex-specs:lazy-spec.doc-height-protocol"]
  paths:
    - "<spec_path_prefix>/products/*/features/*/vision.md"
    - "<spec_path_prefix>/products/*/changes/*/vision.md"
  context_from_frontmatter: [spec_source_requests]
  experts:
    main:
      - name: <designer-expert>
# use-cases.md class (all levels) — use-case-writer writes; one designer_review validation slot
# (asset-level: opt-in sibling created by a ticked launch checkbox; seed-doc copies the status
# folder-note's spec_source_requests onto the seeded doc, so context_from_frontmatter folds the
# originating request(s) into the writer's bundle, same as design/bug. Product-root and
# content-root use-cases.md are operator-authored and ride the same class — the writer set is
# identical at every level)
- class: use-cases
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol"]
  paths:
    - "<spec_path_prefix>/products/*/features/*/use-cases.md"
    - "<spec_path_prefix>/products/*/changes/*/use-cases.md"
    - "<spec_path_prefix>/products/*/use-cases.md"
    - "use-cases.md"
  context_from_frontmatter: [spec_source_requests]
  experts:
    main:
      - name: <use-case-writer-expert>
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
    - "<spec_path_prefix>/products/*/features/*/design.md"
    - "<spec_path_prefix>/products/*/changes/*/design.md"
    - "<spec_path_prefix>/products/*/bugs/*/design.md"
  context_from_frontmatter: [spec_source_requests]
  experts:
    main:
      - name: <designer-expert>
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
    - "<spec_path_prefix>/products/*/vision.md"
    - "<content_root>/vision.md"
  context_from_frontmatter: [spec_source_requests]
  experts:
    main:
      - name: <system-designer-expert>
- class: system-design
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol", "lazycortex-specs:lazy-spec.doc-height-protocol"]
  paths:
    - "<spec_path_prefix>/products/*/design.md"
    - "<content_root>/design.md"
  context_from_frontmatter: [spec_source_requests]
  experts:
    main:
      - name: <system-designer-expert>
    validation:
      architect_review:
        name: <architect-expert>
        section: Architect review
        position: bottom
# system-tech class — the product-root tech.md AND the content-root (project-wide) tech.md;
# the architect writes (a tech spec is code structure, not code), no validators
- class: system-tech
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol"]
  paths:
    - "<spec_path_prefix>/products/*/tech.md"
    - "<content_root>/tech.md"
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
    - "<spec_path_prefix>/products/*/features/*/architecture.md"
    - "<spec_path_prefix>/products/*/changes/*/architecture.md"
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
    - "<spec_path_prefix>/products/*/features/*/ui-design.md"
    - "<spec_path_prefix>/products/*/changes/*/ui-design.md"
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
    - "<spec_path_prefix>/products/*/features/*/code-plan.md"
    - "<spec_path_prefix>/products/*/changes/*/code-plan.md"
    - "<spec_path_prefix>/products/*/bugs/*/code-plan.md"
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
    - "<spec_path_prefix>/products/*/features/*/test-plan.md"
    - "<spec_path_prefix>/products/*/changes/*/test-plan.md"
    - "<spec_path_prefix>/products/*/bugs/*/test-plan.md"
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
    - "<spec_path_prefix>/products/*/features/*/code-report.md"
    - "<spec_path_prefix>/products/*/changes/*/code-report.md"
    - "<spec_path_prefix>/products/*/bugs/*/code-report.md"
  experts:
    main:
      - name: <developer-expert>
# test-report.md class — tester writes; no validators
- class: test-report
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol"]
  paths:
    - "<spec_path_prefix>/products/*/features/*/test-report.md"
    - "<spec_path_prefix>/products/*/changes/*/test-report.md"
    - "<spec_path_prefix>/products/*/bugs/*/test-report.md"
  experts:
    main:
      - name: <tester-expert>

- class: data-report
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol"]
  paths:
    - "<spec_path_prefix>/products/*/*/*/data-report.md"
  experts:
    main:
      - name: <data-writer-expert>

- class: docs-report
  protocols: ["lazycortex-specs:lazy-spec.expert-signals-protocol"]
  paths:
    - "<spec_path_prefix>/products/*/*/*/docs-report.md"
  experts:
    main:
      - name: <docs-writer-expert>
```

`<use-case-writer-expert>` / `<designer-expert>` / `<system-designer-expert>` / `<architect-expert>` / `<ui-designer-expert>` / `<planner-expert>` / `<developer-expert>` / `<tester-expert>` / `<data-writer-expert>` / `<docs-writer-expert>` are placeholders for the consumer-supplied COMPOSED expert key (typically `<domain>.<role>` from `lazycortex-experts`, e.g. `claude-plugin.designer` — never a bare role word like `designer`; a project-local override expert key works the same way). `<content_root>` in the system-class globs is the spec content-root (`spec.vault_root`, default `specs`) — the project-wide pair lives loose at that root, beside `requests/`. When the consumer has not registered one of them yet, omit that class until the expert exists — without a registered `main`, the dispatcher logs a no-writer warning per-tick. For built-in `bug.md` docs (bug-kind layout substitutes `bug.md` for `design.md`), extend the design class's `paths` with the matching bug glob or add a separate `class: bug` class with a bug-specific main writer — carry the same `context_from_frontmatter: [spec_source_requests]` key onto that class too.

The `design` and `test-plan` classes' `main` experts carry one requirement beyond ordinary review-writing: `spec.coordinator`'s change-cascade dispatch (`lazy-spec.coordination-playbook.md` Chapter 4, wire shape in `lazy-spec.lifecycle-protocol.md` Part 4) dispatches them to fold a change's design delta into a *different* asset's own `design.md` / `test-plan.md` in place, and an in-place edit only lands a commit when the dispatched expert's own `experts.<name>` settings entry carries `can_commit_in_repo: true` — the dispatch primitive reads that flag from the expert's own registration, never from the wire bundle (a state-mutating op never takes caller-side a field its owner can read itself). Set `can_commit_in_repo: true` on whichever expert each product wired into those two classes' `main[0].name`. Skipping this leaves the cascade's edits uncommitted — the daemon's dirty-tree guard then blocks every subsequent routine on that repo.

`context_from_frontmatter` is a generic class-config key (not tied to any one document origin): at main-job dispatch, the dispatcher reads each named frontmatter key off the document under review, resolves wikilink (`[[path]]`) or bare repo-relative values to repo files, and folds every resolved file into the job bundle's `context/`. `spec_source_requests` reaches a doc two ways — `lazy-spec.request-apply`'s `ensure_source_request` writer stamps it onto an attach target's primary doc, and `lazycortex-specs seed-doc` copies the status folder-note's union (stamped there at apply) onto every checkbox-seeded doc — so carrying the key here means the design writer's job bundle includes the originating request file(s), the same distribution pattern plan 2 uses for guideline context. An unresolvable value is never silent — it surfaces as a warning on the tick summary, never a dispatch failure.

Validator composition follows one rule: the architect is the standing validator of everything design-shaped (`design`, `system-design`, `ui-design`, and `code-plan` against the architecture), the designer validates the actors/flows that precede design (`use-cases`), the developer validates the plans that will drive execution (`test-plan`), and no class is validated by its own main writer. `architecture` keeps its `planner_review` slot (the planner checking whether the doc holds enough decisions to decompose into a plan). The vision classes (`vision`, `system-vision`), the report classes (`code-report`, `test-report`, `data-report`, `docs-report`), and `system-tech` wire no validators — their doc is approved by the operator directly through the standard review UI. No class carries a `terminal` block — these classes have no post-approve routing (the apply transition completes the request lifecycle; downstream is the per-asset gate machine, not another review round). The settings-migration ladder's older steps (`_add_architecture_class` / `_add_planner_review_to_design` in `lazycortex-core`'s `bin/lazy_settings_migrations/review.py`) predate this composition — they migrate old vaults to the pre-`system-design` shape; the current composition reaches an existing vault by manual migration, not by ladder.

**`tech.md` carries no review class, and gains no planner-validation slot here.** `ReviewClassName` (`lazycortex-core`'s `bin/constants.py`) is a closed set — `plan` (legacy), `code-plan`, `test-plan`, `code-report`, `test-report`, `design`, `bug`, `architecture` — with no `tech` token, and no `class: tech` entry exists anywhere in this seed or in the settings-migration ladder (`lazycortex-core`'s `bin/lazy_settings_migrations/review.py`). A product's `tech.md` is authored inline by `lazy-spec.create-from-code` (product-level) or by hand (feature/change-level — `lazy-spec.doctor`'s own source-staleness check reads it as a plain file, never as a review-dispatched one); it is never dispatched through review, so there is no review class for a planner-validation slot to attach to. Nothing in this seed changes for `tech`.

**These same classes are also the launch-checkbox expert source.** `spec.coordinator` (dispatched by the `lazy-spec.coordinator-watch` routine, per `lazy-spec.coordination-playbook.md` Chapter 3) resolves a ticked checkbox's expert from the review class whose name matches the checkbox's own RESULT document — a uniform rule with no label-keyed exceptions: the checkbox that produces a `code-plan` resolves the `code-plan` class, a `test-plan` the `test-plan` class, and each tool's implementation checkbox the class named after that tool's own `report_doc` — `code-report`, `data-report`, `docs-report`, `test-report`. Which checkboxes exist at all is declared by the asset's type and tool playbooks, not by a table here. Each class's `experts.main[0].name` is the dispatched expert — whichever expert a product registered there (the placeholders above, or whatever `lazy-spec.product-config`'s wizard assigned instead). Review on a finished job's report is opened by the coordinator itself on its `job-done` wake, through the class matching that report's own document type; `lazy-spec.gate-tick` no longer does it.

**Suggest `workspace: branch` on whichever expert is wired into a report class's `main[0].name`.** The acceptance cycle these two classes drive (`lazy-spec.coordination-playbook.md` § 6) runs its launch-checkbox job and every continuation on a job-scoped branch, enforced by the runtime, not by prose — see `lazy-core.runtime-schema.md` § Workspace for the mechanics and `experts[<name>].merge` for the companion merge setting. This is a seed proposal only, same discipline as `can_commit_in_repo` above: `/lazy-experts.install` already seeds `workspace: branch` on its own developer/tester entries when the consumer uses `lazycortex-experts`; when the consumer supplies a project-local expert instead, point them at that same setting by hand — never overwrite an existing `workspace` value on an entry this skill does not own.

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

**Read first — register only when a source is configured.** Run `Bash(lazycortex-core settings-get spec)` and inspect `upstream`. An absent section, or one carrying only the reserved limit keys (`max_units_per_tick`, `max_text_file_bytes`, `fetch_failure_threshold`) with no `<repo-key>` entry, means no upstream source is configured — a schedule routine with nothing to do is dead weight, so skip silently with outcome `skipped-no-upstream-configured` and continue to Step 7. Only when at least one non-reserved key is present does this step proceed. No question — the presence of a configured source is genuine project state, not a choice this step re-asks. Re-run this check on every re-invocation of `/lazy-spec.install` (not just the first) so a source added later still gets the routine wired without a separate manual step.

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

The daemon resolves `command[0]` (`lazycortex-specs`) to the plugin's bin script and runs `lazycortex-specs upstream-tick` on the configured cadence — the same primitive `/lazy-spec.upstream-run` invokes manually; both share one implementation, so a scheduled pass and a manual run behave identically. No `hooks_enabled` entry is set — the routine schema's empty default already silences every lazycortex hook inside its own subprocesses, which is what this routine's atomic per-unit commits need.

If `/lazy-routine.register` reports the routine is already registered, accept its outcome (`unchanged` / `present`) — do not force-overwrite. Outcome: `routine-registered`, `routine-already-present`, or `skipped-no-upstream-configured`.

## Step 6.9: Seed the vault spec and the catalog root's level note

The project-wide `vision.md` at the spec content-root — the **vault spec** — is the starting point of the whole catalog: it states what the project is, for whom, and what counts as success; the split into products is a consequence of it (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.layout-protocol.md` Part 1). `lazy-spec.product-config` refuses to register the first product while it is absent (accepting a pre-existing `design.md` without one as a legal pre-vision state), so this step seeds a draft before Step 7 offers that registration.

**Project scope only.** Vault content lives per-repo; at user scope skip silently with outcome `skipped-user-scope`.

1. Resolve the content-root: `<settings-dir>/<spec.vault_root>` (`spec.vault_root` from `Bash(lazycortex-core settings-get spec)`, default `specs`).
2. If `<content-root>/vision.md` already exists — in any state, draft or approved — leave it untouched. Outcome: `already-present`. A content-root `design.md` without a vision is also left untouched — the pre-vision state is legal and migrated by the operator by hand, never by this step.
3. Otherwise `Bash(mkdir -p <content-root>)`, then instantiate `${CLAUDE_PLUGIN_ROOT}/templates/spec.docs/vault-vision.md`, substituting `{{project}}` with the repo-root directory name, and `Write` the result to `<content-root>/vision.md`. Outcome: `seeded`.

No question — the seed is fully derivable. No review dispatch either: the shared `system-vision` review class already covers the content-root `vision.md` glob, so the review loop picks the document up through the normal channels once the operator starts filling it in. The gate `lazy-spec.product-config` enforces is the file's presence; any stricter condition (written / approved) is deliberately not part of this contract yet.

4. Seed (or repair) the catalog root's **level note** — the folder-note `spec.catalog-coordinator` owns, at `<content-root>/<basename of content-root>.md`, carrying `spec_role: catalog`, the four level gates, and the coordinator's own body sections:

   ```
   Bash(lazycortex-specs catalog-note backfill --root)
   ```

   The verb creates the note from the shipped level-note template when it is absent and, when it is present, adds only what it lacks — no key is rewritten, no section is moved, and the operator's `# Coordinator rules` and rendered `# Summary` survive byte-for-byte. Re-running it on a conforming note writes nothing. Fold its returned `note` path into the install's own commit.

5. Backfill **every registered product's** level note the same way — one call per key in `products`, each landing at `<spec_path>/<leaf of spec_path>.md` (the folder-note convention, never the product's own key), so an existing catalog gains the level role, gates, and sections it predates:

   ```
   Bash(lazycortex-specs catalog-note backfill <product-key>)
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

**Locate the wiki CLI.** Same two-stage lookup `lazycortex-review/bin/coordinator_dispatch.py`'s own `_resolve_core_cli` uses for a sibling plugin's binary — deliberately NOT the `<core-bin>` resolution Step 5b-b uses (that one reads `installed_plugins.json`'s `installPath` directly, a different mechanism suited to a hard dependency this skill already knows is installed; `lazycortex-wiki` is optional here, so its absence from `installed_plugins.json` and an unset `$LAZYCORTEX_PLUGIN_DIRS` both need a graceful miss, which the glob-based lookup gives for free): `$LAZYCORTEX_PLUGIN_DIRS` first — empty at plain interactive install-time, since only the daemon exports it — then a version-sorted glob over the plugin cache:

Every sub-step below uses only `Bash(test *)` / `Bash(ls *)` — already on this skill's `allowed-tools` line — rather than a single compound multi-line script, so no new Bash pattern needs whitelisting for this step:

1. **Env-dirs stage.** `Bash(test -n "$LAZYCORTEX_PLUGIN_DIRS" && echo "$LAZYCORTEX_PLUGIN_DIRS")`. Empty output → go to stage 2. Non-empty → split the printed value on `:`; for each candidate `<dir>`, `Bash(test -f "<dir>/bin/lazycortex-wiki" && echo "<dir>/bin/lazycortex-wiki")` until one prints a path — hold that as `$WIKI_CLI` and skip stage 2.
2. **Plugin-cache glob** (only when stage 1 found nothing). `Bash(ls -d ~/.claude/plugins/cache/*/lazycortex-wiki/*/bin/lazycortex-wiki 2>/dev/null)`. No output → `$WIKI_CLI` stays unresolved. One or more lines → each names a version-embedding path (`.../<version>/bin/lazycortex-wiki`); take the newest version — `Bash(ls -d ~/.claude/plugins/cache/*/lazycortex-wiki/*/bin/lazycortex-wiki 2>/dev/null | sort -V | tail -1)`, a numeric version sort so `10.0.0` outranks `9.1.1`, matching `coordinator_dispatch.py`'s own newest-version pick — as `$WIKI_CLI`.

- `$WIKI_CLI` unresolved after both stages → `lazycortex-wiki` is not installed on this machine. State `skipped-no-wiki` and move on to Step 8 — this is the normal, expected outcome for a repo without the wiki plugin.
- `$WIKI_CLI` resolved → continue below.

**Ensure the axes.** The axis vocabulary belongs to the repository, not to any one scope, so this is a single call regardless of how many products are registered. `$WIKI_CLI` resolved to an absolute path in the plugin-cache case (stage 2 above), which the literal-prefix `Bash(lazycortex-wiki *)` pattern would NOT match — prefix the call with `test -x "$WIKI_CLI" &&` so the invoked text always starts with `test `, matching the already-allowed `Bash(test *)` pattern regardless of how `$WIKI_CLI` resolved:

```
Bash(test -x "$WIKI_CLI" && "$WIKI_CLI" ensure-axes product category --repo <repo-root>)
```

Idempotent union into `wiki.tag_axes` — a repository that already declares both axes reports `{"status": "unchanged"}` and is left untouched; an operator's other axes are never dropped, and no scope is read or written. A scope narrows the vocabulary to the axes it uses, so declaring these two here makes them available to the spec scope without touching any scope's own list.

A non-zero exit is non-fatal: surface its stderr first line in the report and continue below; do NOT abort the install.

**Seed the spec-catalog scope defaults.** A spec catalog's wiki scope skips unfinished and working documents by default: a stage-bearing doc is curated only once `spec_stage` reaches `approved` (a doc with no `spec_stage` at all — a terms dictionary, a decisions registry — passes; markdown attachments mirror their owner's stage per `lazy-spec.layout-protocol.md` § Attachments, so they follow the owner), a doc whose own review rejected it stays out via `review_result`, a doc under review is already skipped by the `review_active` predicate the configure wizard seeds, and the request inbox (`<vault_root>/requests/**`, raw requests and their archive) plus plan/report working papers are excluded by name — the scope's own `topics_index` is skipped structurally and needs no entry. `/lazy-wiki.configure` asks no exclude question for a scope covering the catalog; this seed is the one source. The seed is idempotent and never overwrites an operator's own predicate for the same key, so a project that deliberately loosened the default keeps its loosening on every re-run.

Resolve the scope covering each registered product: for every entry in `products` (skip the `_version` meta key), build the repo-relative probe path `<vault_root>/<spec_path>/design.md` — `<vault_root>` is the `spec.vault_root` setting (default `specs`); drop the `<vault_root>/` segment when it is `.`. `resolve-scope` matches the path against configured globs only — the file need not exist on disk yet:

```
Bash(test -x "$WIKI_CLI" && "$WIKI_CLI" resolve-scope <vault_root>/<spec_path>/design.md --repo <repo-root>)
```

`{"scope_id": null}` → no configured wiki scope covers this product yet; count it under `no-scope` and skip it. Two products resolving to the same scope must not double-trigger the seed — dedupe scope ids across the loop. For every distinct `<id>`:

```
Bash(test -x "$WIKI_CLI" && "$WIKI_CLI" ensure-scope-config <id> --filter-json '{"spec_stage": {"in": [null, "approved"]}, "review_result": {"not_in": ["rejected"]}}' --exclude '<vault_root>/requests/**' '**/*-plan.md' '**/*-report.md' --repo <repo-root>)
```

A non-zero exit from either call is the same non-fatal case as above — count it under `cli-failed`, surface its stderr first line, continue.

**Keep deferred documents out of the wiki routines.** The scope filter above keeps a `spec_stage: deferred` document out of the wiki graph, but the wiki's git-watch routines judge a changed file by their own `filter` block, not by the scope's: without a predicate of their own, every commit touching a parked document still dispatches a terms-curator job and a structure-curator job. Seed the predicate into each wiki routine the repository has registered, through the core CLI's routine seed — the same absent-key-only contract as the scope seed, so an operator's own `spec_stage` predicate on a routine is never overwritten. For each `<routine>` in `lazy-wiki.scan`, `lazy-wiki.terms-scan-<id>` (one per scope id resolved above), `lazy-wiki.structure-scan`, `lazy-wiki.structure-scan-deletes`, `lazy-wiki.structure-scan-renames`:

```
Bash(lazycortex-core routine-ensure-filter <routine> --filter-json '{"spec_stage": {"not_in": ["deferred"]}}')
```

`{"status": "error", "reason": "no such routine"}` (exit 1) means the repository never registered that routine — count it under `no-routine` and continue; it is the normal case for a repo without the structure map or without a terms dictionary. Files without frontmatter and documents without `spec_stage` pass a `not_in` predicate, so the seed narrows nothing but parked documents.

Outcome: `skipped-no-wiki`, or `axes-<added: N|unchanged>, preset-<seeded: N-scopes|unchanged>, routines-<seeded: N|unchanged> (no-scope: <M>, no-routine: <R>, cli-failed: <K>)` — the parenthetical is omitted when every count is `0`.

## Step 7c: Backfill `spec_doc_type` across the catalog

Every authored catalog document carries a `spec_doc_type` frontmatter key naming its document type (`lazy-spec.layout-protocol.md` § Document type). Documents written before typing landed carry none, and a document with no type resolves to no declaration — `lazy-spec.set-stage` refuses it, `lazy-spec.doctor` FAILs on it, and the review class it belongs to cannot be found. Run the one-shot backfill:

```
Bash(lazycortex-specs doc-type backfill)
```

It walks the spec content-root, derives each document's type from its `spec_role` (falling back to the filename stem when the document carries no role), and writes the key where it is missing. Report the returned `touched` / `skipped` counts.

Idempotent by construction: a document already carrying the key is counted `skipped` and left byte-identical, so a fresh install reports zeros and a re-run after a bulk content import picks up only what is new. The status folder-note and any untyped stranger derive no type and are not candidates at all.

**The backfill does not commit.** It leaves its writes in the worktree; committing them belongs to whoever is driving this install, in that repo's own commit.

Outcome: `backfilled: <touched>/<skipped>` (`backfilled: 0/0` on a fresh install with no catalog yet).

## Step 7d: Backfill `spec_asset_type` and rename the renamed document types

Every asset's status folder-note carries a `spec_asset_type` frontmatter key naming what the asset is (`lazy-spec.coordination-playbook.md`, the input-facts chapter). Assets created before the key existed carry none, and the coordinator cannot load a type playbook without it. Two shipped document types were also renamed — `dev-plan` to `code-plan` and `dev-report` to `code-report` — and a document still carrying an old type name resolves to no declaration. Run all three passes:

```
Bash(lazycortex-specs asset-type backfill)
Bash(lazycortex-specs doc-type rename dev-plan code-plan)
Bash(lazycortex-specs doc-type rename dev-report code-report)
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
Bash(lazycortex-core permission-allow <settings-local> "Bash(lazycortex-specs *)")
```

Outcome: `cli-allow-added` or `cli-allow-already-present`.

## Step 9: Verify

- Confirm the consumer dir from Step 3 now exists.
- Confirm `<consumer>/.claude/rules/spec.decisions.md` exists and is byte-identical to `${CLAUDE_PLUGIN_ROOT}/rules/spec.decisions.md` (Step 3b).
- Confirm the `lazy-spec.gate-tick` routine is present in `lazy.settings.json` (`routines.lazy-spec.gate-tick`) — pure script, no `protocols` entry.
- Confirm the `lazy-spec.coordinator-watch` routine is present in `lazy.settings.json` (`routines.lazy-spec.coordinator-watch`) and that its `protocols` list carries both `lazycortex-specs:lazy-spec.coordination-playbook` AND `lazycortex-core:lazy-core.markdown-style`.
- If Step 4 set a language: confirm `lazycortex-core settings-get spec` reports the chosen `language`.
- Project scope only: confirm `<content-root>/vision.md` exists (Step 6.9), or a pre-vision `design.md` without one.
- Unless Step 6 was `skipped-user-scope`: confirm the blocks are present in `lazy.settings.json` (`experts.spec.coordinator`, at least one `review.classes[]` entry covering `requests/*.md` with `terminal.routing` naming `spec.catalog-coordinator` at `position: top`; and `routines.lazy-spec.request-open` / `routines.lazy-spec.request-apply` unless the daemon gate skipped them). Note: no `experts.lazy-spec.request-apply` entry — the apply routine is `command:`-shape, not expert-based.
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
  - Step 5 outcome (`routine-registered` or `routine-already-present`)
  - Step 5b outcome (`routine-registered+protocol-seeded` or `routine-already-present+protocol-seeded`), plus 5b-b's `remote-sync-ok` or `remote-sync-not-pull-push:<value>`
  - Step 5c outcome (`routine-registered` or `routine-already-present`)
  - Step 6 outcome (`wiring-applied:<N>` or `skipped-user-scope`)
  - Step 6.5 outcome (`seeded` or `unchanged`), with the primitive's report block folded in verbatim; surface `sot-missing` / `no-entries` if returned
  - Step 6.7 outcome (`routine-registered`, `routine-already-present`, or `skipped-no-upstream-configured`)
  - Step 6.9 outcome (`seeded`, `already-present`, or `skipped-user-scope`)
  - Step 7 outcome (`registered: <compound-key>` or `skipped-per-user-choice`)
  - Step 7b outcome (`skipped-no-wiki` or `ensured: <N-scopes> (no-scope: <M-products>, cli-failed: <K>)`)
  - Step 7c outcome (`backfilled: <touched>/<skipped>`)
  - Step 7d outcome (`migrated: <touched> typed, <docs> retyped, <files> renamed`)

## Step 10: Log the run

Log to `./.logs/claude/lazy-spec.install/YYYY-MM-DD_HH-MM-SS.md` per the logging rule (include `git_sha` frontmatter).

Use two separate steps: `Bash(mkdir -p ...)` then `Write` tool. Never chain with `&&`.

## Failure modes

- **`/lazy-spec.install` aborts: plugin not installed** — `lazycortex-specs@lazycortex` has no entry in `~/.claude/plugins/installed_plugins.json` → add `"lazycortex-specs@lazycortex": true` to `enabledPlugins` in your `settings.json` and restart Claude Code, then re-run.
- **`/lazy-spec.install` reports `routine lazy-spec.gate-tick already registered`** — a prior install already wired the routine → accept the `routine-already-present` outcome; re-running never overwrites it. To change its shape, run `/lazy-routine.unregister lazy-spec.gate-tick` first, then re-run install.
- **`/lazy-spec.install` reports `routine lazy-spec.coordinator-watch already registered`** — same case as above, for the coordinator's own watch routine → accept `routine-already-present`; `/lazy-routine.unregister lazy-spec.coordinator-watch` first to change its shape.

## Notes

- **Idempotent**: running this skill multiple times is safe. Every write follows the File-sync policy — absent → write, cleanly mergeable → merge silently, genuine conflict → the only case that asks. The consumer dir is never recreated and orphaned entries are kept, never deleted.
- **Re-run after `/plugin update`**: this skill creates the one consumer dir and mirrors the plugin's own `rules/` (Step 3b re-syncs on every run). After a plugin update, the plugin's reference docs and templates refresh in cache automatically — no resync needed for those. Steps 5, 5b, and 6 surface any new wiring requirements on the next run.
- **Scope independence**: running at project scope does not affect other projects or the global config.
- **Per-product overrides** are NOT created by this skill — they live under `.claude/templates/spec.<category>/<compound-key>/` (one folder per category that the operator wants to customize), scaffolded by `lazy-spec.product-config` when the user opts into customization.
- **User-scope skip**: Step 6 (request runtime wiring) is a project-scope-only step. Request files live in `<vault-root>/requests/` per-vault; wiring at user scope would point the daemon at the wrong path. The skill detects user scope at Step 1 and silently skips Step 6 (`skipped-user-scope`).
