---
since: 10.0.0
supersedes: []
applies_when:
  - {path_exists: ".claude/rules/spec.decisions.md"}
  - {path_exists: ".claude/rules/lazy-spec.decisions.md"}
writes:
  - ".claude/rules/spec.decisions.md"
---
## Why

The plugin's decisions rule was renamed from `spec.decisions.md` to `lazy-spec.decisions.md`, so it carries the plugin namespace. Install mirrors the plugin's `rules/` into `.claude/rules/` and leaves a rule it no longer ships in place. A consumer that installed the old version keeps `.claude/rules/spec.decisions.md` beside the new `lazy-spec.decisions.md`: every session loads the same rule twice, and the stale copy never receives a later edit.

## Steps

`<repo-root>` is the root of the repository being migrated.

1. `rm "<repo-root>/.claude/rules/spec.decisions.md"`

## Done when

- `.claude/rules/spec.decisions.md` is absent while `.claude/rules/lazy-spec.decisions.md` is present.
