---
description: Contract for the `lazy_setup_phase:` frontmatter key — allowed values, ordering inside `lazy-core.setup`, and the chained-from-inside-another-install anti-pattern.
---
# `lazy_setup_phase` frontmatter contract

Skills opt into the `lazy-core.setup` meta-installer by declaring `lazy_setup_phase:` in their `SKILL.md` frontmatter. The meta-installer discovers participating skills dynamically — no central registry to edit.

## Allowed values

- `pre-install` — runs before any plugin templates land. Reserved for future use.
- `per-plugin` — implicit for any skill whose directory matches `*.install`. Declaring this key on a `*.install` skill is unnecessary; declaring it on a non-install skill forces it to run alongside installers.
- `post-install` — cross-cutters that depend on plugin templates already being in place (e.g. permission registrars, model-tier wizards).

Any other value is a `WARN` finding from `lazy-core.audit`.

## Ordering inside `lazy-core.setup`

1. All `pre-install` skills, alphabetical.
2. All `per-plugin` skills (any directory matching `*.install`), with `lazy-core.install` first, then alphabetical.
3. All `post-install` skills, alphabetical.

## Anti-pattern: chained-from-inside-another-install

If skill A is already invoked from inside skill B's install flow, A MUST NOT also carry `lazy_setup_phase:`. Double-running re-prompts the user and breaks idempotence.

Concrete example: `lazy-obsidian.iconize-install` is chained from `lazy-obsidian.install`. It does not carry the frontmatter key.

## How to opt in

Add a single line to the skill's frontmatter:

```yaml
lazy_setup_phase: post-install
```

That is the only edit needed; `lazy-core.setup` discovers and orders the skill on its next run.

## Enforcement

`lazy-core.audit` Agent B greps every `SKILL.md` for the `lazy_setup_phase:` key and emits `WARN` when the value is outside `{pre-install, per-plugin, post-install}`. There is no `FAIL` severity here — the meta-installer treats unknown values as opt-out, but flags them for author attention.
