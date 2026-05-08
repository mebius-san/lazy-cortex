---
description: Authoring contract for rule files. Mandatory frontmatter (description + paths scope OR always_loaded waiver), size budget, dot-namespace filename, no large code blocks, artifact-reference integrity, no narrative padding.
paths:
  - ".claude/rules/**"
  - ".claude/templates/core/rule-template.md"
---
# Rule Authoring

Rule files under `.claude/rules/` and `<plugin>/rules/` are loaded into session context. Every rule must justify its cost.

**Template:** `${CLAUDE_PLUGIN_ROOT}/templates/core/rule-template.md` — start from this when creating a new rule. The template encodes every clause below; copy its body, fill placeholders, delete the trailing authoring-notes block.

## 1. Mandatory frontmatter (FAIL if missing or non-canonical)

### 1.1 How rules actually load (Claude Code mechanic)

Per Claude Code docs (`code.claude.com/docs/en/memory#path-specific-rules`):

- **Rules without a `paths:` field** are loaded **unconditionally** and apply to all files — they sit in startup context every session.
- **Path-scoped rules** trigger when Claude **reads a file matching one of the globs**, not on every tool use. Bash, Grep, WebFetch, etc. don't pull them in; only file reads matching the pattern do.

This is the underlying behaviour. The clauses below are stricter than what Claude Code itself enforces — we **forbid** the implicit "no paths" shape so the always-loaded cost is never accidental.

### 1.2 Required keys

- `description:` — one-line summary.
- Exactly one of:
  - `paths:` — YAML **block-list** of glob strings, one per line, prefixed with `- `. This is the **only** documented canonical form (see § 1.1 link). Loads only when Claude reads a file matching one of the globs. Preferred over `always_loaded:`.
  - `always_loaded: "<concrete one-line reason>"` — explicit opt-in to always-loaded behaviour. Use only when the rule genuinely constrains every turn (e.g. logging, hygiene, security). Empty string or boolean `true` → `FAIL`.

Canonical `paths:` shape:

```
paths:
  - "src/api/**/*.ts"
  - "tests/**/*.test.ts"
```

The inline-array form `paths: ["a", "b"]` is **silently ignored by the Claude Code loader** — the rule does not load, no error surfaces. Both forms are valid YAML; the loader is stricter than the spec and accepts only the block-list. → `FAIL`. Detection: any line matching `^paths:\s*\[`.

No frontmatter at all → `FAIL`. Frontmatter with neither `paths` nor `always_loaded` → `FAIL`.

## 2. Size budget

Budget depends on load profile:

- `always_loaded:` rules > 3 KB → `FAIL`. These load on every turn; keep them tight.
- `paths:`-scoped rules > 10 KB → `WARN`. They load only when matching files are touched, so some breathing room is fine — but content > 10 KB should still move to `<plugin>/skills/<skill>/references/*.md` and be `Read` on demand.
- `paths:`-scoped rules > 25 KB → `FAIL` regardless of scope.

## 3. No large code blocks

Any code block > 10 lines → `FAIL`. Put runnable templates in `<plugin>/templates/` or a skill reference and link to them.

**Exemption — data blocks as the rule's primary content.** A fenced block whose language is a structured data format (`yaml`, `json`, `toml`) and whose content is the rule's authoritative payload (a registry, schema, or canonical mapping the rule exists to publish) is not subject to the 10-line cap. The exemption is narrow: example snippets, illustrative configs, and prose-supporting fragments still count toward the cap regardless of language.

## 4. Filename format

`namespace.name.md` (dot-namespace). Missing dot → `WARN`.

## 5. Artifact references must resolve

Slash-commands (`/name`), agent subagent-types, rule filenames, `references/…` paths, hook paths, and `skills/<name>/SKILL.md` paths mentioned in the body must exist on disk. Broken reference → `WARN`.

## 6. No narrative padding

Same denylist as `lazy-core.skill-writing § 4`: `\bv\d+\.\d+\.\d+`, `user had to`, `we got burned`, `in a past session`, `in a previous run`. Match → `WARN`. Author owns final call.

## 7. Rules are read, not executed

Rules describe invariants. They do not carry `Execution discipline` preambles or Report steps — those belong in skills/agents that *apply* the rule.

## Enforcement

`lazy-core.audit` Agent B runs the checks above on `.claude/rules/*.md`, `~/.claude/rules/*.md`, and `claude/*/rules/*.md`. `lazy-core.doctor` Phase 3 surfaces the findings and prompts for fixes.
