---
description: Schema for a plugin's per-group scaffold.entries.json manifest — the source-of-truth a plugin declares so its install can register scaffold-registry entries.
---
# scaffold.entries manifest schema

A `scaffold.entries.json` manifest is the plugin-side **source of truth** for the scaffold-registry entries a plugin contributes. It lives at `claude/<plugin>/templates/<group>/scaffold.entries.json` — one manifest per template group. It is read in place at install time by `lazy-core.scaffold-sync` (which copies the group's templates and upserts the entries into the consumer registry) and is authored / edited via the plugin's scaffold-type management workflow. It is **never copied to the consumer** and is never touched by the `lazycortex-core scaffold` primitive (that primitive operates only on the consumer registry `lazy-core.scaffold.md`).

---

## 1. Top-level fields

| Field | Type | Default | Required | Description |
|---|---|---|---|---|
| `version` | `int` | — | yes | Manifest schema version. Currently `1`. Bump + ship a migration for an incompatible shape change. |
| `templates` | `object` | `{}` | yes | Map of consumer-scope template path → list of glob strings. Becomes `data[<plugin>]` in the consumer registry **verbatim**. |

`group` is **not** a stored field — it is derived from the manifest's own directory name (`templates/<group>/scaffold.entries.json`). A plugin with multiple groups ships one manifest per group; `scaffold-sync` unions their `templates` maps into the single `data[<plugin>]` key (a template-path key declared by two groups with conflicting globs is a `scaffold-sync` FAIL).

## 2. The `templates` map

| Field | Type | Default | Required | Description |
|---|---|---|---|---|
| `<consumer template path>` | `array[string]` | — | yes | Key: the consumer-scope path of the authoring template (e.g. `.claude/templates/<group>/<kind>-template.md`) — used as-is, no rewriting. Value: the globs that, when a new file matches one, trigger "read this template first" in `lazy-core.scaffold`. |

Globs follow the plain-scalar policy of the registry (a `*`-leading glob is quoted when rendered into YAML; the JSON manifest stores the bare string). `${CLAUDE_PLUGIN_ROOT}` must never appear in a key — it does not resolve outside plugin trees.

## 3. Example

```json
{
  "version": 1,
  "templates": {
    ".claude/templates/core/protocol-template.md": [
      ".claude/references/*-protocol.md",
      "~/.claude/references/*-protocol.md"
    ]
  }
}
```

## 4. Validation

`lazy-core.scaffold-sync` reads the manifest at install time; malformed JSON or a cross-group key collision aborts the sync. The entries it upserts into the consumer registry are then validated by `lazycortex-core scaffold validate` (single fenced block, leaf = list of strings, no `${CLAUDE_PLUGIN_ROOT}`, plain-scalar correctness, cross-key glob overlap → `WARN`). On the plugin-source side, the plugin-source audit checks that any plugin shipping a `scaffold.entries.json` (a) has the referenced template files present under its `templates/<group>/`, (b) wires `lazy-core.scaffold-sync` into its install skill, and (c) parses against this schema. The scaffold-type management workflow is the blessed author of the manifest; hand-edits are valid plain JSON.
