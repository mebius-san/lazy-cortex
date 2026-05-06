---
name: <protocol-short-name>
version: 1
description: <one-line summary — what this protocol governs and who its consumer is>
---
# <protocol-short-name> protocol v1

Canonical contract for jobs dispatched to experts via lazycortex-core's expert runtime queue, where the consumer is `<consumer-skill-or-cli>` (or any other consumer producing `<protocol-short-name>`-shaped jobs).

## Request shape (`request.json`)

```json
{
  "kind":    "<comma-separated values from the kind enum below>",
  "role":    "<free-form string from class.experts[].role; document reserved values below>",
  "request": "<protocol-specific prose composed by the consumer>",
  "source":  [{"path": "source/<file>", "description": "..."}],
  "context": [{"path": "context/<file>", "description": "..."}],
  "result":  [{"path": "result/<file>", "description": "where to write output"}]
}
```

Field notes:

- `kind` — see `## Kind enum` below.
- `role` — see `## Role vocabulary` below.
- `request` — <describe what the prose looks like; mention if the consumer renders from a template>.
- <document any protocol-specific extra fields, or write "No extra fields.">

## Response shape (`response.json`)

```json
{
  "outcome": "<comma-separated values from the outcome enum below>",
  "result":  ["result/<file>"],
  "error":   {"category": "logical | transient | technical", "message": "..."}
}
```

`outcome=error` is reserved across all protocols — never define a `kind` or non-error `outcome` value named `error`.

<document any protocol-specific extra response fields, or write "No extra fields.">

## Kind enum

- `<kind-1>` — <one-line description of the operation>
- `<kind-2>` — <one-line description>

## Role vocabulary

Document every `role` string the expert prompt knows to handle and how each shifts behaviour. Free-form prose roles are also valid (interpreted as nuanced guidance by the expert prompt).

- `<role-1>` — <how the expert behaves under this role>
- `<role-2>` — <how the expert behaves under this role>

## Outcome by kind

| kind | valid outcomes |
|---|---|
| `<kind-1>` | <list of outcomes> |
| `<kind-2>` | <list of outcomes> |

## Per-kind contents

For each kind, describe what the consumer puts in `source/` / `context/` and what the expert writes to `result/`.

### `<kind-1>`
- **source/** — <required input files, naming conventions>
- **context/** — <optional reference files>
- **result/** — <output files the expert writes>

### `<kind-2>`
- ...

## Side-effect rules

- The expert MAY: <enumerate allowed side-effects, e.g. editing source/ files in place for `kind=review`>
- The expert MUST NOT: <enumerate forbidden side-effects>

## Error categories

| Category | Used when |
|---|---|
| `logical` | <when applicable, or "not used"> |
| `transient` | <when applicable, or "not used"> |
| `technical` | <when applicable, or "not used"> |

Protocols may subset to fewer categories; they may not introduce new category names.

<!--
Authoring notes (delete before saving):

- Placement: `<plugin>/references/<name>-protocol.md` for new files (suffix declares the type and triggers this template via lazy-core.scaffold). Pre-existing protocols without the suffix would be grandfathered (per `lazy-core.reference-writing § 1`); the in-tree set was migrated and none currently remain.
- Reference key: `<plugin>:<name>` in `experts.settings.json` resolves to `<plugin>/references/<name>.md` via reference_resolver. The bare `<name>` is the file's basename without `.md`, so a renamed protocol (e.g. `lazy-review.doc-review-protocol.md`) is referenced as `lazycortex-review:lazy-review.doc-review-protocol`.
- Versioning by filename: incompatible changes ship as a new file (e.g. `lazy-review.doc-review-v2-protocol.md`); the old file stays until consumers migrate. No version field, no version syntax in reference strings.
- Contract source of truth: `claude/lazycortex-core/references/lazy-core.expert-protocols-contract.md`. The clauses above mirror that contract; consult it for the standard job-dir layout (request.json, READY, source/, context/, result/, response.json, DONE).
- Worked example: `claude/lazycortex-review/references/lazy-review.doc-review-protocol.md`.
-->
