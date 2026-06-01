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

`references/` is the canonical name at every scope — there is no `protocols/` or `schemas/` folder. The resolver maps the `category` argument (`protocols`, `agents`, `aspects`) to the on-disk directory (`references`, `agents`, `references`); see `bin/reference_resolver.py:plugin_dir_for_category`.

## 1. Subtypes and filename suffix conventions

Every new reference file SHOULD declare its subtype via filename suffix. Existing files without the suffix are grandfathered.

| Subtype | Suffix | Scaffold template | Loaded by |
|---|---|---|---|
| Protocol | `<name>-protocol.md` | `core/protocol-template.md` | `reference_resolver` (runtime) |
| Aspect | `<name>-aspect.md` | `core/aspect-template.md` | `reference_resolver` (runtime, `category="aspects"`) |
| Schema | `<name>-schema.md` | `core/schema-template.md` | humans + audits |
| Contract | `<name>-contract.md` | `core/contract-template.md` | humans + audits |
| Other / freeform | no suffix required | — | varies |

A protocol file is the formal request/response contract for an expert (see `lazy-core.expert-protocols-contract.md`). A schema documents a config or data shape. A contract is the meta-spec for an artifact KIND (e.g. what every protocol file must contain). Mismatches between filename suffix and content (e.g. a `*-schema.md` file lacking a schema table) → `WARN`.

An aspect file is the meta-contract for a behavior layer composed into one or more experts (see `lazy-core.expert-aspects-contract.md`).

## 2. Mandatory frontmatter (FAIL if missing)

- `description:` — one-line summary. **Required for every reference.**
- Subtype-specific fields:

| Subtype | Required additional frontmatter |
|---|---|
| Protocol | `name:` (the bare reference key), `version:` (integer protocol version) |
| Aspect | `name:` (the bare reference key) |
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

## 9. Protocol scope fence — no consumer-config leakage

A `*-protocol.md` file documents the WIRE contract: what the dispatcher writes into `request.json`, what the expert writes into `response.json`, the per-kind contents of `source/` / `context/` / `result/`, and the side-effect rules the expert respects while handling one request. See `lazy-core.expert-protocols-contract.md § 1 Out of scope` for the full negative list.

A `*-protocol.md` file MUST NOT include:

- `lazy.settings.json` shape — no `routines:`, no `experts:`, no `review.classes:` JSON snippets. Consumer config goes in the consumer plugin's functional spec and its configure-wizard skill (`<plugin>.configure` or equivalent).
- Tutorial JSON snippets showing "how to register this expert" or "where to put this in settings".
- Lifecycle prose tied to the consumer's state machine that goes beyond what the expert observes per request. Cross-job state transitions belong in the consumer's spec.
- **Per-`role` behaviour rules.** `role` is a free-form agent-self-label the dispatcher transports verbatim; the protocol MUST NOT enumerate `role` values, prescribe per-`role` behaviour, or include a "## Role rules" / "## Role vocabulary" / "## Per-role" section. Structural ownership / IO contract belongs under a `## Mode rules` section keyed on the closed `mode` enum (see `lazy-core.expert-protocols-contract.md § 4.2`).
- **Agent-side markup conventions.** Callout shapes, marker formats, intro-callout layouts, "the agent MUST emit `[!question]` with prefix X" — these are agent behaviour, not wire. A "## Markup the agent writes" / "## Output shape" section in a protocol file is a scope violation; that prose belongs in the agent's own `.md` body.

`lazy-core.audit` flags any `*-protocol.md` containing the strings `lazy.settings.json`, `review.classes`, `routines:`, top-level `experts:` JSON keys, `## Role rules`, `## Role vocabulary`, `## Per-role`, `## Markup the agent writes`, `role == "`, or `when role ==` as `WARN` ("protocol carries consumer-config / agent-side content; see § 9 of `lazy-core.reference-writing`"). The check has a waiver path for the meta-contract itself (`lazy-core.expert-protocols-contract.md`), which describes what protocols are and necessarily references the forbidden patterns to forbid them.

## Enforcement

`lazy-core.audit` runs the checks above on `.claude/references/*.md`, `~/.claude/references/*.md`, and `claude/*/references/*.md`. `lazy-core.doctor` Phase 3 surfaces the findings and prompts for fixes. Subtype-specific deeper validation (e.g. protocol §§ 4.1–4.9 from `lazy-core.expert-protocols-contract.md`) is enforced by `lazy-core.audit`'s expert-runtime phase.
