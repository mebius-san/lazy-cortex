---
description: Contract for the scaffold registry — schema, plain-scalar policy, per-plugin manifest SOT, the scaffold primitive, install via scaffold-sync, the registry-file write discipline, precedence, and audit invariants.
---
# Scaffold registry contract

`lazy-core.scaffold` is a single always-loaded registry expressed as a fenced YAML mapping. The structure is:

```
plugin-name → (template-path → [globs])
```

Plugin ownership is structural: each plugin owns its own top-level key (the plugin directory name); the reserved key `_local` carries customer-authored entries. There are no comment markers, no out-of-band annotations — the data structure IS the ownership boundary.

## Schema

```yaml
<plugin-dir-name | _local>:                 # top-level: string, required
  <template-path>:                            # second-level: string, repeatable
    - <glob>                                  # third-level: list of strings, repeatable
    - <glob>
  <template-path>:
    - <glob>
```

- **Top-level key**: either an installed plugin's directory name (e.g. `lazycortex-core`, `lazycortex-diagram`) or the reserved key `_local`. Mixed-case allowed; match the plugin directory name verbatim.
- **Second-level key (template path)**: relative to consumer scope — `.claude/templates/<group>/<artifact>-template.md` (project) or `~/.claude/templates/<group>/...` (user). Never `${CLAUDE_PLUGIN_ROOT}/...` (the variable doesn't resolve outside plugin trees).
- **Third-level value (glob list)**: zero or more strings. Empty list is legal but pointless.

## Plain-scalar policy

Globs and template paths are written as YAML plain scalars — no quotes — provided they don't begin with a YAML-reserved character (`*`, `&`, `!`, `|`, `>`, `%`, `@`, `` ` ``, `[`, `{`, `,`, `?`, `:` followed by space). Globs starting with `*` (e.g. `*.md`) MUST be quoted as `"*.md"`; the `.claude/foo/*.md` shape is fine plain because `*` is mid-string.

## Template path scheme

- Plugins copy their templates into the consumer's `.claude/templates/<group>/` during install. The plugin's source-tree path (`claude/<plugin>/templates/<group>/`) is the canonical seed; the consumer copy is what the registry points at.
- `<group>` is plugin-chosen (e.g. `core`, `diagram`, `obsidian`, `specs`). Two plugins SHOULD NOT share a group name — collision means one plugin's templates overwrite the other's during install.

## Manifest — source of truth

Each plugin declares its registry entries in a per-group manifest `claude/<plugin>/templates/<group>/scaffold.entries.json` (`{ "version": 1, "templates": { "<consumer-path>": [globs] } }`). This is the plugin-side SOT; `group` is derived from the directory, not stored. Full shape: `scaffold.entries-schema.md`. The manifest is read in place at install — never copied to the consumer — and is the input to the primitive's upsert. `lazycortex-core` itself uses a manifest (`templates/core/scaffold.entries.json`) like every other plugin; its shipped rule template ships an empty `{}` registry, populated at install.

## The primitive

The `## Registry` block is owned exclusively by the `lazycortex-core scaffold` CLI (`bin/scaffold_registry.py`), a dependency-free parser/serializer (no PyYAML). Subcommands: `upsert --plugin <n> --entries <@file|json>`, `remove --plugin <n>`, `list`, `validate`. Writes are **surgical** — only the target key's line-region is rewritten; every other top-level key (`_local`, sibling plugins) and all bytes outside the fence stay byte-for-byte. `upsert` of identical entries is `unchanged`; a missing registry file is created from a minimal template. `_local` is an ordinary key to the primitive — no special-casing.

## Install-skill responsibilities

Every plugin that contributes templates to the registry MUST invoke `lazy-core.scaffold-sync` from its install skill: `Skill(skill: "lazycortex-core:lazy-core.scaffold-sync", args: "plugin=<name> installPath=<path> scope=<project|user>")`. That one shipped skill does the whole job:

1. **Copy templates** — `<installPath>/templates/<group>/*` (excluding `scaffold.entries.json`) → `<consumerScope>/.claude/templates/<group>/`. Idempotent; prompts on drift the same way the rule sync does.
2. **Upsert the plugin's key** — reads the plugin's `scaffold.entries.json` manifest(s), unions them across groups, and calls `scaffold upsert --plugin <name>`, which surgically replaces only `data[<name>]` and creates a minimal registry file if absent.
3. **Touches no other key** — `_local` and sibling-plugin keys are out of bounds, enforced by the primitive's surgical write (not by convention).

Install skills MUST NOT hand-roll the YAML upsert (parse / replace / serialize) — that logic lives once, in the primitive. Uninstall skills (when they exist) drop their own key via `scaffold remove --plugin <name>` and delete the template files the manifest referenced.

## Customer-authored entries

The reserved top-level key `_local` (underscore prefix) holds customer-authored entries. Install skills MUST NOT touch `_local` (or any non-plugin key the customer adds). The recommended structure:

```yaml
_local:
  .claude/templates/recipes/recipe-template.md:
    - prompts/recipes/*.md
  .claude/templates/runbooks/runbook-template.md:
    - docs/runbooks/*.md
```

A customer may also use any other top-level key that doesn't collide with an installed plugin directory name. `_local` is the conventional landing spot. The shipped `lazy-core.scaffold-local` skill is the safe path to add/remove `_local` entries without hand-editing the YAML (it has no manifest — `_local` is its own SOT, with the template authored in place).

## Registry-file write discipline (§5a)

The `## Registry` block is **primitive-owned**. Generic rule-sync (`lazy-core.install` Step 3) MUST exclude `lazy-core.scaffold.md` from its `overwrite` path and MUST NOT rewrite the `## Registry` block — it may additively merge only the prose/frontmatter above it. The block is mutated only by `scaffold upsert` / `remove`, surgically. The file is created (full template + `{}`) only when absent; when present-and-parseable, only key-regions change; when present-but-broken, the primitive FAILs and surfaces the parse error rather than clobbering.

## Precedence & collisions (§7)

When globs from coexisting keys match the same path, resolution (stated in the scaffold rule body, applied by Claude at consumption-time) is: **most-specific glob wins** — within a key and across keys; on an equal-specificity tie, `_local` overrides plugin keys. `scaffold validate` reports cross-key glob overlaps as `WARN` (silent shadowing made visible); a plugin-vs-plugin overlap is the stronger signal (types should not collide).

## Validation

`lazy-core.audit` runs `lazycortex-core scaffold validate` against each in-scope registry and maps its findings into the audit glossary. The primitive's deterministic parse enforces:

- **Single fenced YAML block** under `## Registry` — additional blocks or non-YAML content in that section is a finding.
- **Block parses as valid YAML** — top level must be a mapping; values must be mappings; leaf values must be sequences of strings.
- **No duplicate top-level keys** — YAML itself forbids this; the audit surfaces parser errors as `[FAIL]`.
- **No path drift** — every template-key path must resolve from the registry's containing scope (`.claude/templates/<group>/...` exists; `~/.claude/templates/<group>/...` for global registries).
- **No `${CLAUDE_PLUGIN_ROOT}/...`** anywhere in the block — fails because the variable doesn't resolve outside plugin trees.
- **Plugin keys match an installed plugin** — top-level keys other than `_local` SHOULD correspond to a plugin in `~/.claude/plugins/installed_plugins.json`. Orphan keys (plugin uninstalled but registry entry remains) surface as `[WARN]` for cleanup.
- **No cross-key glob overlap** — two top-level keys matching the same glob surface as `[WARN]` (silent shadowing); see §7 precedence.

Findings surface in `lazy-core.doctor` Phase 3 alongside the rest of the rule-writing-compliance scan.
