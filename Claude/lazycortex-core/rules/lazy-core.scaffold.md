---
description: Registry of authoring templates for any new artifact a plugin registers.
always_loaded: fires at create-time; path-scoped contracts don't trigger on Write
---
# Scaffold

Before composing any **new** file whose path matches a glob below, `Read` the matching template first and start from it — never compose from memory. Contract & extension rules: `claude/lazycortex-core/references/lazy-core.scaffold-registry.md`.

## Registry

```yaml
lazycortex-core:
  .claude/templates/core/rule-template.md:
    - .claude/rules/*.md
    - ~/.claude/rules/*.md
  .claude/templates/core/skill-template.md:
    - .claude/skills/*/SKILL.md
  .claude/templates/core/agent-template.md:
    - .claude/agents/*.md
  .claude/templates/core/command-template.md:
    - .claude/commands/*.md
```
