---
name: lazy-obsidian.audit
description: "Semantic audit for the lazycortex-obsidian plugin. Verifies iconize-sync artifacts stay coherent: worker version constants match template HOOK_VERSION markers, icon-map template parses at the current schema with no retired keys, protocol template's `owner_skill` points at an existing skill, hook templates carry parseable version markers. Read-first; presents findings, then asks which to fix. Delegated from `lazy-core.doctor` Phase 3."
allowed-tools: Read, Glob, Grep, Bash(python3 *), Bash(mkdir -p *), Bash(date *), Bash(git rev-parse*), AskUserQuestion, Write
argument-hint: "(no arguments — runs the full plugin audit)"
---
# lazycortex-obsidian audit

Semantic integrity check for the plugin. Orthogonal to `lazy-core.doctor`'s
generic structural checks (filename format, frontmatter presence, etc.) —
this skill owns the domain-specific invariants.

## Execution discipline (MANDATORY — read before any action)

This skill has 8 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — Version coherence`
   - `Phase 2 — Icon-map template sanity`
   - `Phase 2.5 — Cross-artifact coherence for the two-writer model`
   - `Phase 3 — Protocol template sanity`
   - `Phase 4 — Skill cross-refs`
   - `Phase 6 — Protocol doc content checks`
   - `Phase 5 — Report + fix loop`
   - `Phase 7 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `already-ignored`, `absent`, `skipped-per-user-choice`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Phase 1 — Version coherence

- Read `${CLAUDE_PLUGIN_ROOT}/bin/iconize_sync.py`; extract
  `PROTOCOL_VERSION`, `HOOK_VERSION`, `SCHEMA_VERSION`, and `SUPPORTED_SCHEMA`
  constants.
- Grep `HOOK_VERSION:` markers out of:
  - `templates/obsidian-iconize/pre-commit-shim.sh`
  - `hooks/hooks.json` (plugin-shipped PostToolUse entry)
- **FAIL** if MAJOR differs between worker and any template/hook.
- **WARN** if MINOR/PATCH differs.
- **FAIL** if `SCHEMA_VERSION` is not a member of `SUPPORTED_SCHEMA` (the worker
  would refuse its own written config).
- **FAIL** if `templates/obsidian-iconize/icon-map.json`'s `schema_version`
  does not equal the worker's `SCHEMA_VERSION`.

## Phase 2 — Icon-map template sanity

- Load `templates/obsidian-iconize/icon-map.json`.
- **FAIL** if JSON doesn't parse.
- **FAIL** if required top-level keys missing (`schema_version`, `matchers`).
- **FAIL** if `schema_version != 2` (the current worker schema). v1 icon-maps
  in the template are a release-blocking regression — consumers copy this
  file as their starter.
- **FAIL** if any matcher contains an `emit` key (retired at schema 2;
  folder emission is now driven by Folder Notes template, not matcher
  output).

The template ships with `matchers: []` by design (consumers author their own
rules); matcher-coverage checks belong in a consumer-side audit, not here.

## Phase 2.5 — Cross-artifact coherence for the two-writer model

- Read `templates/obsidian/plugin-settings.json`.
- **FAIL** if `obsidian-icon-folder.settings.iconInFrontmatterEnabled` is
  not `true`.
- **FAIL** if `obsidian-icon-folder.settings.iconInFrontmatterFieldName`
  is not `"iconize_icon"`.
- **FAIL** if `obsidian-icon-folder.settings.iconColorInFrontmatterFieldName`
  is not `"iconize_color"`.
- **FAIL** if `folder-notes` is absent from the top-level override blocks
  (the reloader depends on the `folderNoteName` template being set).
- **WARN** if `folder-notes.folderNoteName` is not `"{{folder_name}}"` — the
  plugin supports other templates but the protocol doc documents the default.

- Read `templates/obsidian/plugins/iconize-reloader/manifest.json`.
- Extract `version`.
- Grep `RELOADER_VERSION` from `templates/obsidian/plugins/iconize-reloader/main.js`.
- **FAIL** if the manifest version does not match the `RELOADER_VERSION`
  constant — the reloader's runtime version marker is the handshake the
  audit surfaces to `lazy-core.doctor`.
- **FAIL** if the manifest version's MAJOR is `< 2` — the v1 reloader
  predates the folder-note writer.

## Phase 3 — Protocol template sanity

- Read `templates/obsidian-iconize/protocol.md`.
- **FAIL** if frontmatter missing or `owner_skill` is not a skill that exists
  under `skills/`.
- **WARN** if no `## Resolver` section.

## Phase 4 — Skill cross-refs

- Enumerate `skills/*/SKILL.md`.
- **FAIL** if any shipped skill's `allowed-tools` includes a Bash glob that
  hardcodes an absolute path (violates `lazy-core.hygiene`).
- **WARN** if the `iconize-sync` SKILL.md does not document all five
  subcommands (`sync`, `sync-staged`, `reconcile`, `install-hooks`,
  `check-versions`).

## Phase 5 — Report + fix loop

Collect all findings. Present a grouped report with `PASS` / `WARN` / `FAIL`
prefixes. For each `FAIL` / `WARN`, ask (one `AskUserQuestion`):
**fix** / **waive** / **skip**. Apply fixes where trivial; otherwise explain
what needs manual attention.

Follow the coordinator pattern documented in `lazycortex-core`'s
`references/lazy-core.parallel-scan.md` if the audit scans enough artifacts to
warrant parallel Explore subagents. Today's audit is small enough to run inline.

## Phase 6 — Protocol doc content checks

- Read `templates/obsidian-iconize/protocol.md`.
- **FAIL** if the protocol still describes `emit: ["self", "parent_dir"]`
  as a matcher output (retired at schema 2).
- **FAIL** if the protocol does not describe the two-writer model (worker
  writes frontmatter; reloader writes folder-keyed `data.json` entries).
- **WARN** if the protocol does not name `iconize_icon` / `iconize_color` as
  the canonical frontmatter keys.

## Phase 7 — Log the run

`./.logs/claude/lazy-obsidian.audit/YYYY-MM-DD_HH-MM-SS.md` per the logging
rule.

## Integration with `lazy-core.doctor`

`lazy-core.doctor` Phase 3 delegates to this skill. Add a Phase-3 step in
`lazycortex-core`'s doctor that probes for `lazycortex-obsidian` in the
installed plugins list and, when present, invokes this skill. Tracked as a
follow-up.
