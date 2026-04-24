---
description: Authoring contract for rule files. Mandatory frontmatter (description + paths scope OR always_loaded waiver), size budget, dot-namespace filename, no large code blocks, artifact-reference integrity, no narrative padding, plugin-vs-local scoping.
paths: [".claude/rules/**"]
---
# Rule Authoring

Rule files under `.claude/rules/` and `<plugin>/rules/` are loaded into session context. Every rule must justify its cost.

## 1. Mandatory frontmatter (FAIL if missing)

- `description:` — one-line summary.
- Exactly one of:
  - `paths: ["<glob>", ...]` — folder scope; rule loads only when matching files are touched. Preferred.
  - `always_loaded: "<concrete one-line reason>"` — waiver for rules that genuinely constrain every turn (e.g. logging, hygiene, security). Empty string or boolean `true` → `FAIL`.

No frontmatter at all → `FAIL`. Frontmatter with neither `paths` nor `always_loaded` → `FAIL`.

## 2. Size budget

Budget depends on load profile:

- `always_loaded:` rules > 3 KB → `FAIL`. These load on every turn; keep them tight.
- `paths:`-scoped rules > 10 KB → `WARN`. They load only when matching files are touched, so some breathing room is fine — but content > 10 KB should still move to `<plugin>/skills/<skill>/references/*.md` and be `Read` on demand.
- `paths:`-scoped rules > 25 KB → `FAIL` regardless of scope.

## 3. No large code blocks

Any code block > 10 lines → `FAIL`. Put runnable templates in `<plugin>/templates/` or a skill reference and link to them.

## 4. Filename format

`namespace.name.md` (dot-namespace). Missing dot → `WARN`.

## 5. Artifact references must resolve

Slash-commands (`/name`), agent subagent-types, rule filenames, `references/…` paths, hook paths, and `skills/<name>/SKILL.md` paths mentioned in the body must exist on disk. Broken reference → `WARN`.

## 6. No narrative padding

Same denylist as `lazy-core.skill-writing § 4`: `\bv\d+\.\d+\.\d+`, `user had to`, `we got burned`, `in a past session`, `in a previous run`. Match → `WARN`. Author owns final call.

## 7. Plugin-vs-local scoping

- **Governs plugin-shipped artifacts** → `<plugin>/rules/`, `paths:` scoped to consumer location (`.claude/**` etc.).
- **Project-only** (not consumers) → `.claude/rules/`, `paths:` scoped narrowly (`claude/**`, `claude/*/skills/**`).
- **Every action, any file** → `<plugin>/rules/` with `always_loaded:`. Use sparingly; each is a tax on every consumer.

**Local pointer pattern**: when a plugin rule also needs to cover plugin-authoring sources (`claude/**` in this vault), keep the plugin rule narrowly scoped and add a thin pointer in `.claude/rules/` with a wider `paths:` glob cross-referencing the plugin rule. Each file carries its own scope; no content duplication.

## 8. Rules are read, not executed

Rules describe invariants. They do not carry `Execution discipline` preambles or Report steps — those belong in skills/agents that *apply* the rule.

## Enforcement

`lazy-core.audit` Agent B runs the checks above on `.claude/rules/*.md`, `~/.claude/rules/*.md`, and `claude/*/rules/*.md`. `lazy-core.doctor` Phase 3 surfaces the findings and prompts for fixes.
