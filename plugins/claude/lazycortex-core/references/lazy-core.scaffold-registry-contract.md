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

- Plugins copy their templates into the consumer's `.claude/templates/<group>/` during install. The plugin's source-tree path (`plugins/claude/<plugin>/templates/<group>/`) is the canonical seed; the consumer copy is what the registry points at.
- `<group>` is plugin-chosen (e.g. `core`, `diagram`, `obsidian`, `specs`). Two plugins SHOULD NOT share a group name — collision means one plugin's templates overwrite the other's during install.

## Manifest — source of truth

Each plugin declares its registry entries in a per-group manifest `plugins/claude/<plugin>/templates/<group>/scaffold.entries.json` (`{ "version": 1, "templates": { "<consumer-path>": [globs] } }`). This is the plugin-side SOT; `group` is derived from the directory, not stored. Full shape: `scaffold.entries-schema.md`. The manifest is read in place at install — never copied to the consumer — and is the input to the primitive's upsert. `lazycortex-core` itself uses a manifest (`templates/core/scaffold.entries.json`) like every other plugin; its shipped rule template ships an empty `{}` registry, populated at install.

## The primitive

`<core-cli>` stands for the core plugin's `bin/lazycortex-core` file — the newest copy under `~/.claude/plugins/cache/lazycortex/lazycortex-core/<version>/`, or `plugins/claude/lazycortex-core/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

The `## Registry` block is owned exclusively by the `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> scaffold` CLI (`bin/scaffold_registry.py`), a dependency-free parser/serializer (no PyYAML). Five subcommands, each of which takes `--registry <path>` naming the registry markdown file to operate on — argparse marks the flag required on all five, so an invocation that omits it exits 2 without touching anything:

- `scaffold upsert --registry <path> --plugin <n> --entries <@file|json>`
- `scaffold remove --registry <path> --plugin <n>`
- `scaffold list --registry <path>`
- `scaffold validate --registry <path>`
- `scaffold sync-rule --registry <path> --src <shipped rule file>` — the whole-file refresh, not a per-key write: it replaces the plugin-owned prose and frontmatter of the rule file from `--src` while carrying the consumer's `## Registry` block across, and `--registry` names the consumer's target copy rather than a bare registry. Status is `installed`, `unchanged`, `refreshed`, `failed`, or `error` (the consumer's block does not parse — the file is left alone). This is the invocation `lazy-core.install` Step 3 §5a makes for `lazy-core.scaffold.md`.

Registry writes (`upsert` / `remove`) are **surgical** — only the target key's line-region is rewritten; every other top-level key (`_local`, sibling plugins) and all bytes outside the fence stay byte-for-byte. `upsert` of identical entries is `unchanged`; a missing registry file is created from a minimal template. `_local` is an ordinary key to the primitive — no special-casing.

## Install-skill responsibilities

Every plugin that contributes templates to the registry MUST invoke `lazy-core.scaffold-sync` from its install skill: `Skill(skill: "lazycortex-core:lazy-core.scaffold-sync", args: "plugin=<name> installPath=<path> scope=<project|user>")`. That one shipped skill does the whole job:

1. **Copy templates** — `<installPath>/templates/<group>/*` (excluding `scaffold.entries.json`) → `<consumerScope>/.claude/templates/<group>/`. Idempotent; prompts on drift the same way the rule sync does. **A plugin writes only its own files.** Before copying, the skill resolves every path the registry lists under `_local` and passes it to the sync script as a protected target: such a file is never compared, never overwritten, and reported as `protected`. A shipped template that carries the same filename confers no claim on it — name equality is not ownership.
2. **Upsert the plugin's key** — reads the plugin's `scaffold.entries.json` manifest(s), unions them across groups, and calls `scaffold upsert --registry <consumer registry> --plugin <name> --entries <@file>`, which surgically replaces only `data[<name>]` and creates a minimal registry file if absent.
3. **Touches no other key** — `_local` and sibling-plugin keys are out of bounds, enforced by the primitive's surgical write (not by convention).

Install skills MUST NOT hand-roll the YAML upsert (parse / replace / serialize) — that logic lives once, in the primitive. Uninstall skills (when they exist) drop their own key via `scaffold remove --registry <consumer registry> --plugin <name>` and delete the template files the manifest referenced.

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

**A `_local` template gets a group of its own.** `lazy-core.scaffold-local` collects the groups the installed plugins supply — the parent directory of every template path under a non-`_local` key — and refuses an `add` that names one of them, because that directory is re-synced on every install of the plugin that owns it. The refusal names the occupied group and asks for another; it never picks a substitute. `remove` is exempt, so an entry already filed in an occupied group stays removable. The `protected` handling in § Install-skill responsibilities is the safety net behind this refusal, not a licence to skip it.

## Registry-file write discipline (§5a)

The `## Registry` block is **primitive-owned**. Generic rule-sync (`lazy-core.install` Step 3) MUST exclude `lazy-core.scaffold.md` from its `overwrite` path and MUST NOT rewrite the `## Registry` block — it may additively merge only the prose/frontmatter above it. The block is mutated only by `scaffold upsert` / `remove`, surgically. The file is created (full template + `{}`) only when absent; when present-and-parseable, only key-regions change; when present-but-broken, the primitive FAILs and surfaces the parse error rather than clobbering.

## Precedence & collisions (§7)

When globs from coexisting keys match the same path, resolution (stated in the scaffold rule body, applied by Claude at consumption-time) is: **most-specific glob wins** — within a key and across keys.

Specificity is a **total order of three steps**, walked in sequence and stopping at the first that separates the two globs:

1. **Wildcard-free path segments** — count the `/`-separated segments that contain no `*` or `?`. More wins. `.claude/rules/*.md` (2) beats `plugins/claude/*/rules/*.md` (1).
2. **Literal characters outside the wildcards** — on a tie, count the characters of the glob that are not `*` or `?`. More wins. `.claude/references/*-schema.md` beats `.claude/references/*.md`.
3. **`_local` over a plugin key** — on a tie, the customer-authored key wins.

The three steps are a total order by construction: any two globs that reach step 3 sit in different keys or are the same entry, so every pair of matched globs has one predictable winner and the outcome never depends on the order entries were registered.

`scaffold validate` reports cross-key glob overlaps as `WARN` (silent shadowing made visible); a plugin-vs-plugin overlap is the stronger signal (types should not collide).

## Validation

`lazy-core.audit` runs `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> scaffold validate` against each in-scope registry and maps its findings into the audit glossary. The primitive's deterministic parse enforces:

- **Single fenced YAML block** under `## Registry` — additional blocks or non-YAML content in that section is a finding.
- **Block parses as valid YAML** — top level must be a mapping; values must be mappings; leaf values must be sequences of strings.
- **No duplicate top-level keys** — YAML itself forbids this; the audit surfaces parser errors as `[FAIL]`.
- **No path drift** — every template-key path must resolve from the registry's containing scope (`.claude/templates/<group>/...` exists; `~/.claude/templates/<group>/...` for global registries). A path that is missing or unreadable on disk surfaces as `missing_template` / `[WARN]`. It never blocks: an author whose file matches that entry's globs writes freely, and no neighbouring template is substituted for the missing one. The check runs only when the caller names the consumer scope, so the in-process `validate(md)` used before a registry write is unaffected.
- **No `${CLAUDE_PLUGIN_ROOT}/...`** anywhere in the block — fails because the variable doesn't resolve outside plugin trees.
- **Plugin keys match an installed plugin** — top-level keys other than `_local` SHOULD correspond to a plugin in `~/.claude/plugins/installed_plugins.json`. Orphan keys (plugin uninstalled but registry entry remains) surface as `orphan_key` / `[WARN]` for cleanup. The check runs only when the caller supplies the installed set, and an unreadable installed-plugin record skips it rather than reporting every key as orphaned.
- **No cross-key glob overlap** — two top-level keys matching the same glob surface as `[WARN]` (silent shadowing); see §7 precedence.

Findings surface in `lazy-core.doctor` Phase 3 alongside the rest of the rule-writing-compliance scan.
