---
name: lazy-obsidian.audit
description: "Semantic audit for the lazycortex-obsidian plugin. Verifies iconize-sync artifacts stay coherent: worker version constants match template HOOK_VERSION markers, icon-map template parses and covers at least one authored-doc + one status-file matcher, protocol template's `owner_skill` points at an existing skill, hook templates carry parseable version markers. Read-first; presents findings, then asks which to fix. Delegated from `lazy-core.doctor` Phase 3."
allowed-tools: Read, Glob, Grep, Bash(python3 *), Bash(mkdir -p *), Bash(date *), Bash(git rev-parse*), AskUserQuestion, Write
argument-hint: "(no arguments — runs the full plugin audit)"
---

# lazycortex-obsidian audit

Semantic integrity check for the plugin. Orthogonal to `lazy-core.doctor`'s
generic structural checks (filename format, frontmatter presence, etc.) —
this skill owns the domain-specific invariants.

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
- **WARN** if no authored-doc-style matcher is present (no matcher with
  `basename_in` containing common authored-doc basenames OR no
  `role_matches_basename` shorthand).
- **WARN** if no status-file-style matcher with `emit: ["self", "parent_dir"]`
  is present.

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

## Logging

`./.logs/claude/lazy-obsidian.audit/YYYY-MM-DD_HH-MM-SS.md` per the logging
rule.

## Integration with `lazy-core.doctor`

`lazy-core.doctor` Phase 3 delegates to this skill. Add a Phase-3 step in
`lazycortex-core`'s doctor that probes for `lazycortex-obsidian` in the
installed plugins list and, when present, invokes this skill. Tracked as a
follow-up.
