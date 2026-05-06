---
description: Authoring contract for reference docs (protocols, schemas, contracts) under references/ at any scope.
paths:
  - .claude/references/*.md
  - ~/.claude/references/*.md
  - claude/*/references/*.md
---
# Reference Authoring

Reference files live under `references/` at any of three scopes:

| Scope | Location | Resolved by |
|---|---|---|
| Plugin-shipped | `claude/<plugin>/references/<name>.md` | `<plugin>:<name>` via `bin/reference_resolver.py` |
| Consumer override | `<repo>/.claude/references/<name>.md` | bare `<name>` via `bin/reference_resolver.py` |
| User scope | `~/.claude/references/<name>.md` | `user:<name>` via `bin/reference_resolver.py` |

`references/` is the canonical name at every scope — there is no `protocols/` or `schemas/` folder. The resolver maps the `category` argument (`protocols`, `agents`) to the on-disk directory (`references`, `agents`); see `bin/reference_resolver.py:plugin_dir_for_category`.

## 1. Subtypes and filename suffix conventions

Every new reference file SHOULD declare its subtype via filename suffix. Existing files without the suffix are grandfathered.

| Subtype | Suffix | Scaffold template | Loaded by |
|---|---|---|---|
| Protocol | `<name>-protocol.md` | `core/protocol-template.md` | `reference_resolver` (runtime) |
| Schema | `<name>-schema.md` | `core/schema-template.md` | humans + audits |
| Contract | `<name>-contract.md` | `core/contract-template.md` | humans + audits |
| Other / freeform | no suffix required | — | varies |

A protocol file is the formal request/response contract for an expert (see `lazy-core.expert-protocols-contract.md`). A schema documents a config or data shape. A contract is the meta-spec for an artifact KIND (e.g. what every protocol file must contain). Mismatches between filename suffix and content (e.g. a `*-schema.md` file lacking a schema table) → `WARN`.

## 2. Mandatory frontmatter (FAIL if missing)

- `description:` — one-line summary. **Required for every reference.**
- Subtype-specific fields:

| Subtype | Required additional frontmatter |
|---|---|
| Protocol | `name:` (the bare reference key), `version:` (integer protocol version) |
| Schema | none beyond `description:` |
| Contract | none beyond `description:` |

Missing `description:` → `FAIL`. Missing subtype-specific required field → `FAIL`.

## 3. Placement

A reference file MUST live directly under a `references/` directory — not in a sibling folder named differently, not in a subdirectory of `references/` (the `lazycortex-specs` plugin's `references/spec/` is the only sanctioned subdirectory; no new ones without a corresponding update to this rule).

A `*-protocol.md` / `*-schema.md` / `*-contract.md` file outside `references/` → `WARN`.

## 4. Size budget

References are **not always-loaded**; they are read on demand by the resolver, audits, or humans following links. Budgets are looser than for rules:

- **WARN** at 25 KB — consider splitting or moving examples to a sibling file.
- **FAIL** at 50 KB.

Large fenced data blocks (yaml / json / toml that ARE the reference's primary content) are exempt from per-block size caps, matching `lazy-core.rule-writing § 3`.

## 5. Cross-references must resolve

Filenames, paths, slash-commands, and code references mentioned in the body must exist on disk. Broken reference → `WARN`. Same predicate as `lazy-core.rule-writing § 5`.

## 6. Versioning

Protocols are versioned by filename: incompatible changes ship as a new file (e.g. `lazy-review.doc-review-v2-protocol.md`); the old file stays until consumers migrate. No version number is embedded in the reference key (`<plugin>:<name>`). Schema and contract docs are edited in place for clarifications; for incompatible meta-spec changes, ship a new contract file with a `-v2` suffix.

The `version:` frontmatter field on protocols is the **protocol's own** version (per `lazy-core.expert-protocols-contract.md § 5`), independent of the plugin's `plugin.json` version.

## 7. Filename format

`namespace.name.md` (dot-namespace) preferred but not required — bare names without a namespace are tolerated. Missing dot → no severity.

## 8. References describe, they do not execute

Reference files document contracts, schemas, and protocols. They MUST NOT contain executable steps, "Execution discipline" preambles, or Report sections — those belong in skills/agents that *apply* the contract.

## Enforcement

`lazy-core.audit` runs the checks above on `.claude/references/*.md`, `~/.claude/references/*.md`, and `claude/*/references/*.md`. `lazy-core.doctor` Phase 3 surfaces the findings and prompts for fixes. Subtype-specific deeper validation (e.g. protocol §§ 4.1–4.9 from `lazy-core.expert-protocols-contract.md`) is enforced by `lazy-core.audit`'s expert-runtime phase.
