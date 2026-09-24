---
description: <one-line summary — what this rule enforces and where it applies>
paths:
  - "<glob1>"
  - "<glob2>"
---
# <Rule Title>

<One paragraph: what this rule covers, who reads it, when it fires. Keep it tight — rules are loaded into context.>

## 1. <First testable invariant>

<Spell out the rule. State FAIL vs WARN explicitly. Link to the audit check that enforces it where one exists.>

## 2. <Second testable invariant>

<…>

## 3. <Third testable invariant>

<…>

<!--
Authoring notes (delete before saving):

- Frontmatter shape: canonical YAML block-list `paths:` per `lazy-core.rule-writing § 1`.
  Inline-array form (`paths: [...]`) is FAIL-severity.
- For always-loaded rules, replace `paths:` with `always_loaded: "<concrete one-line reason>"`.
- Size budgets: `always_loaded:` ≤ 3 KB, `paths:`-scoped ≤ 10 KB (WARN) / ≤ 25 KB (FAIL).
- No fenced code block > 10 lines (FAIL). Move runnable templates to `<plugin>/templates/`.
- Filename: `namespace.name.md` (dot-namespace).
- Cross-references in the body must resolve on disk.
- Plugin-shipped rules add a final `## Enforcement` section naming the audit/skill that emits findings for the invariants above (see `lazy-core.{rule,skill,agent}-writing.md` for examples). Project-local rules with no audit behind them omit this section.
-->
