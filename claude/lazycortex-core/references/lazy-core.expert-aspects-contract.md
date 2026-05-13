---
description: Meta-spec for aspect files — what every `<plugin>/references/<name>-aspect.md` instance must declare so any expert composing the aspect inherits a well-defined behavior layer.
---
# Expert aspect contract

An aspect file is a composable system-prompt layer that shapes an expert's behavior on top of its protocol-defined work. This document is the meta-contract: what every aspect file must declare, and what every expert composing the aspect can rely on.

Aspects and protocols are sibling categories. A **protocol** defines the request/response contract for a job (`kind`, `role`, fields, outcomes). An **aspect** shapes how the expert *acts* — what it may write outside the job dir, what universal kinds/roles/outcomes it must handle, what tools it must consult.

---

## 1. What an aspect file is

An aspect file is a plain markdown file at:

```
<plugin>/references/<name>-aspect.md
```

It is referenced from an **expert entry** in `lazy.settings.json[experts][<expert>].aspects[]` as `<plugin>:<name>-aspect`. The runtime resolver (`reference_resolver.resolve(ref, category="aspects", ...)`) maps the `aspects` category to the plugin's `references/` dir — same on-disk location as protocols, distinct semantic category.

**Scope**: aspects are **expert-side** config (the expert opts into a behavior layer), while protocols are **routine-side** config (the routine declares the contract for the jobs it dispatches). The dispatcher reads `aspects` from the expert entry and writes them through to each job's `<jdir>/config.json`. The pump resolves each aspect ref and lists its path in the user-message prompt as `- aspect: <path>` so the expert reads it alongside protocols.

**Versioning by filename** (§ 5). Incompatible changes ship as a new file with a new name; the old file stays until all consumers migrate.

---

## 2. Required structure

Every instance of this artifact must declare:

### 2.1 Frontmatter

- `name:` — bare reference key (matches the filename basename without `-aspect.md`).
- `description:` — one-line summary; surfaces in `lazy-core.audit` and `/lazy-core.doctor`.

### 2.2 Body sections

In order:

1. **Purpose** — one paragraph stating what behavior the aspect adds.
2. **Side-effect rules** — what the expert MAY write outside its job dir (carved out from the universal "must not touch" rule in `lazy-core.expert-runtime-contract.md`), and what it MUST NOT write.
3. **Kind / role / outcome additions** (optional) — new universal `kind` / `role` / `outcome` values the composing expert must handle. State "No additions." when none.
4. **Discovery and tooling** — paths the expert reads, skills/CLIs available.
5. **Obligations** — explicit "you must …" statements binding every expert composing this aspect.

---

## 3. Schema

```yaml
# frontmatter
name: <aspect-short-name>
description: <one-line>

# body sections (in order)
- "## Purpose"
- "## Side-effect rules"
- "## Kind / role / outcome additions"  # optional; required heading even when "No additions."
- "## Discovery and tooling"
- "## Obligations"
```

---

## 4. Composition model

Each expert may carry zero or more aspects. The dispatcher copies the expert's `aspects[]` verbatim into `<jdir>/config.json.aspects[]`. The pump resolves each ref via `reference_resolver.resolve(..., category="aspects", ...)` and lists the resolved path in the user-message prompt with the label `- aspect: <path>`.

The expert reads each listed aspect file at the start of its run and applies the layered behavior on top of its protocol-defined work. Composition is additive — overlapping obligations stack; conflicting rules surface as a `lazy-core.audit` finding (`aspects-conflict`, INFO severity).

---

## 5. Versioning

Aspects are versioned **by filename**. There is no version field in the reference string.

- **Backward-compatible changes** (clarify prose, add an obligation): edit the existing file.
- **Incompatible changes** (remove an obligation consumers rely on, change a kind's semantics): create a new file with a new name (e.g. `lazy-memory.persona-v2-aspect.md`). The old file stays. Consumers migrate by updating `lazy.settings.json[experts][<expert>].aspects[]`.

---

## 6. Validation expectations

`lazy-core.audit` Agent D enforces:

- Aspect file is valid markdown and parses without error → `FAIL` on malformed.
- All required sections (§ 2.2) are present → `FAIL` on missing.
- Every `aspects[]` entry across `lazy.settings.json[experts]` resolves via `reference_resolver` → `FAIL` on unresolvable.
- Aspect filename matches `^[a-z0-9._-]+-aspect\.md$` → `WARN` on suffix mismatch.

`lazy-core.doctor` Phase 3 surfaces findings and prompts for fixes.

---

## 7. Worked example

See `claude/lazycortex-core/references/lazy-memory.persona-aspect.md` — the canonical implementation of a full aspect against this contract.
