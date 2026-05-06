---
description: <one-line summary — what this schema documents and who reads/writes it>
---
# <subject> schema

<One paragraph: which artifact this schema governs (a section of `lazy.settings.json`, a JSON file format, a frontmatter convention, etc.), where it lives on disk, who reads it, and who writes it.>

---

## 1. Top-level fields

| Field | Type | Default | Required | Description |
|---|---|---|---|---|
| `<field>` | `<type>` | `<default>` | yes/no | <description> |
| `<field>` | `<type>` | `<default>` | yes/no | <description> |

## 2. <Sub-block name> (delete if not applicable)

When the schema has nested blocks (e.g. `daemon`, `routines`, `settings`), document each in its own section.

| Field | Type | Default | Required | Description |
|---|---|---|---|---|
| `<field>` | `<type>` | `<default>` | yes/no | <description> |

## 3. Example

```json
{
  "<key>": "<value>"
}
```

## 4. Validation

<Who validates this schema (e.g. `lazy-core.audit`, plugin install skill, runtime resolver, frontmatter loader), when (load time, save time, scrape time), and what failures look like (`FAIL` vs `WARN`). Cite the audit phase or code path that enforces each invariant.>

<!--
Authoring notes (delete before saving):

- Placement: `<plugin>/references/<name>-schema.md` for new files (suffix triggers this template via lazy-core.scaffold). Pre-existing schema docs without the suffix (e.g. `lazy-core.runtime.md`, `lazy-core.settings-v2.md`, `iconize-settings-keys.md`) are grandfathered.
- Drop the `## 1.` / `## 2.` numbering if the schema is small — see `iconize-settings-keys.md` for a flat-table style with no subsections.
- Cross-reference any code that reads/writes this schema (file paths + line numbers) so the schema doc and the code stay in sync. If the code lives in this plugin, link with `<plugin>/bin/<file>.py:<line>`.
- If the schema has a `_version` or `version` field, document its meaning in § 1 and how incompatible changes are handled (typically: bump the version, ship a migration, gate on the `_version` value at load time).
- Versioning of the schema doc itself: edit in place for clarifications and additions; bump the schema's `_version` field (and document the migration) for incompatible shape changes. The doc's filename never carries a version suffix.
-->
