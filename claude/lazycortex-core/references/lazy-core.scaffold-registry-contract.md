---
description: Contract for the scaffold registry YAML block authored by `lazy-core.scaffold` — schema, plain-scalar policy, install-skill responsibilities, and audit invariants.
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

## Install-skill responsibilities

Every plugin install skill that contributes templates to the registry MUST:

1. **Copy templates** — `<installPath>/templates/<group>/*` → `<consumerScope>/.claude/templates/<group>/`. Idempotent: skip byte-identical files; prompt on drift the same way the rule sync does.
2. **Upsert its own top-level key** in the YAML block under `## Registry` of `<consumerScope>/.claude/rules/lazy-core.scaffold.md`:
   - If the registry file does not exist: create a minimal one — frontmatter (`description`, `always_loaded`), `# Scaffold` H1, the one-line trigger sentence pointing at this contract reference, and an empty `## Registry` YAML block (`{}`). Then proceed with the upsert. This handles cross-scope installs (e.g. `lazycortex-core` global, another plugin per-project — the per-project install creates the project registry on first use, and `lazycortex-core`'s global key remains under its own global registry).
   - Parse the YAML block. Replace `data[<plugin-dir-name>]` byte-for-byte with the plugin's current `template → [globs]` mapping. Serialize back, preserving formatting of all other top-level keys.
3. **Never touch any other top-level key.** The plugin owns exactly one key. `_local` and other plugins' keys are out of bounds.
4. **Report the outcome** per template entry: `registered`, `unchanged`, `removed`, `created-registry-and-registered` (when the install seeded a new registry file), or `skipped` (with reason).

Uninstall skills (when they exist) MUST delete their own top-level key entirely AND remove the template files the key referenced.

## Customer-authored entries

The reserved top-level key `_local` (underscore prefix) holds customer-authored entries. Install skills MUST NOT touch `_local` (or any non-plugin key the customer adds). The recommended structure:

```yaml
_local:
  .claude/templates/recipes/recipe-template.md:
    - prompts/recipes/*.md
  .claude/templates/runbooks/runbook-template.md:
    - docs/runbooks/*.md
```

A customer may also use any other top-level key that doesn't collide with an installed plugin directory name. `_local` is the conventional landing spot.

## Validation

`lazy-core.audit` enforces:

- **Single fenced YAML block** under `## Registry` — additional blocks or non-YAML content in that section is a finding.
- **Block parses as valid YAML** — top level must be a mapping; values must be mappings; leaf values must be sequences of strings.
- **No duplicate top-level keys** — YAML itself forbids this; the audit surfaces parser errors as `[FAIL]`.
- **No path drift** — every template-key path must resolve from the registry's containing scope (`.claude/templates/<group>/...` exists; `~/.claude/templates/<group>/...` for global registries).
- **No `${CLAUDE_PLUGIN_ROOT}/...`** anywhere in the block — fails because the variable doesn't resolve outside plugin trees.
- **Plugin keys match an installed plugin** — top-level keys other than `_local` SHOULD correspond to a plugin in `~/.claude/plugins/installed_plugins.json`. Orphan keys (plugin uninstalled but registry entry remains) surface as `[WARN]` for cleanup.

Findings surface in `lazy-core.doctor` Phase 3 alongside the rest of the rule-writing-compliance scan.
