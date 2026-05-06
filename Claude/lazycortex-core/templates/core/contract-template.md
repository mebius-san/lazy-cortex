---
description: <one-line summary — what artifact kind this contract specifies and who authors instances>
---
# <artifact-kind> contract

<One paragraph: what kind of artifact this contract governs, who authors instances of it, who reads them at runtime, and what guarantees both sides can rely on. A contract describes the META-spec for a class of artifact — instances live elsewhere, NOT inside the contract file itself.>

---

## 1. What a <artifact-kind> is

A `<artifact-kind>` is a <markdown / JSON / YAML> file at:

```
<plugin>/<location>/<name>.<ext>
```

<Describe how it's referenced from other artifacts (e.g. `experts.settings.json` keys, frontmatter, settings sections, registry blocks), and what naming or filename conventions apply.>

---

## 2. Required structure

Every instance of this artifact must declare:

### 2.1 <First required clause>

<What must be present, with example shape.>

### 2.2 <Second required clause>

<...>

---

## 3. Schema

<Formal grammar / JSON shape / YAML shape that every instance follows. Use a fenced data block (yaml / json / toml) — these are exempt from the 10-line cap when they ARE the artifact's primary content per `lazy-core.rule-writing § 3`.>

```yaml
<schema or canonical example>
```

---

## 4. Versioning

<How instances of this artifact are versioned: by filename (no embedded version), by frontmatter `version` field, by SemVer constants, by some combination. State explicitly what counts as backward-compatible vs incompatible, and what the upgrade path is for incompatible changes.>

---

## 5. Validation expectations

`<auditor-skill-or-agent>` enforces:

- <invariant 1> — `FAIL` when ...
- <invariant 2> — `WARN` when ...
- <invariant 3> — ...

<Where findings surface (e.g. `lazy-core.doctor` Phase N).>

<!--
Authoring notes (delete before saving):

- Placement: `<plugin>/references/<name>-contract.md` for new files (suffix triggers this template via lazy-core.scaffold). Pre-existing contracts without the suffix would be grandfathered (per `lazy-core.reference-writing § 1`); the in-tree set was migrated and none currently remain.
- A contract describes the META-spec for an artifact KIND — what every instance must contain. It is not itself an instance; instances live in their own files (`<plugin>/references/<name>-protocol.md`, `<plugin>/references/<name>-schema.md`, `<consumer>/.claude/lazy.settings.json`, etc.).
- Cross-reference the auditor or runtime code that enforces the contract (file paths + line numbers).
- If this contract is the seed for a scaffold template, link to the template path under `<plugin>/templates/<group>/`.
- Versioning of the contract doc itself: edit in place for clarifications. For incompatible meta-spec changes, ship a new contract file (e.g. `<name>-v2-contract.md`) and migrate consumers.
-->
