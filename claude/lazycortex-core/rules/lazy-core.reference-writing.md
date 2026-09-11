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

### 4.1 Splitting is the default remedy

A reference over budget usually carries several subjects no single reader needs together. Extract each into a sibling reference, leave a one-paragraph stub in the parent that keeps the extracted section's original number — so every existing `§ N` citation still resolves to something — and have each sibling name its origin in its opening line. Repoint section-anchored citations at the sibling that now owns them. `lazy-core.runtime-schema.md` and the four siblings its stubs name are the worked example.

### 4.2 `size-waiver:` — the per-file exception

Splitting does nothing for a reference that is genuinely read WHOLE: when every chapter fires on every read, extracting one only moves the same bytes behind a second `Read`. Such a file declares the exception in its own frontmatter:

`size-waiver: "<why the file is read whole, naming the reader it protects>"`

- The value must be a concrete one-line reason **and** name the reader — an agent, a skill, a class of consumer — that loads the file whole. `true` / `yes` / `""` → `FAIL` (invalid waiver), exactly as `lazy-log.logging` treats `logging-waiver`.
- **Per file, never a moved threshold.** 25 KB and 50 KB stand unchanged for every other reference, and a waived file's real size still appears in the audit's measurement row.
- It waives the size budget and **nothing else** — every other clause in this rule still applies to a waived file.
- It lives in frontmatter rather than in a repo-root registry because a reference ships inside its plugin to consumers who have no such registry, and because the audit already parses every reference's frontmatter for `description:` — the waiver costs no extra read and cannot drift away from the file it excuses.

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
- **A response envelope of its own.** `outcome` / `error` / `result` belong to `lazy-core.expert-runtime-contract.md` and already reach the expert in its system prompt. A protocol declares which *values* `outcome` takes and which extra fields it adds — never a replacement status key (`"status": "done"`). A protocol that prescribes one silently disarms the runtime: no discriminator is written, every failure classifies as success, and a consumer that drains an input on success destroys it. Do not restate the envelope even correctly; a copy is a future divergence.

`lazy-core.audit` flags any `*-protocol.md` containing the strings `lazy.settings.json`, `review.classes`, `routines:`, top-level `experts:` JSON keys, `## Role rules`, `## Role vocabulary`, `## Per-role`, `## Markup the agent writes`, `role == "`, or `when role ==` as `WARN` ("protocol carries consumer-config / agent-side content; see § 9 of `lazy-core.reference-writing`"). The check has a waiver path for the meta-contract itself (`lazy-core.expert-protocols-contract.md`), which describes what protocols are and necessarily references the forbidden patterns to forbid them.

The envelope clause is checked separately and is a `FAIL`, not a `WARN`: any `*-protocol.md` that mentions `response.json` and never mentions `outcome`, or that names a `"status"` / `"state"` key inside a fenced block under a heading mentioning `response.json` / `Output`, gets "protocol overrides the response envelope; `outcome` is owned by `lazy-core.expert-runtime-contract`". Same meta-contract waiver.

## Enforcement

`lazy-core.audit` runs the checks above on `.claude/references/*.md`, `~/.claude/references/*.md`, and `claude/*/references/*.md`. `lazy-core.doctor` Phase 3 surfaces the findings and prompts for fixes. Subtype-specific deeper validation (e.g. protocol §§ 4.1–4.9 from `lazy-core.expert-protocols-contract.md`) is enforced by `lazy-core.audit`'s expert-runtime phase.
