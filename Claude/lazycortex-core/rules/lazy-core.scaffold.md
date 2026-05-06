---
description: Registry of authoring templates for any new artifact a plugin registers.
always_loaded: fires at create-time; path-scoped contracts don't trigger on Write
---
# Scaffold

Before composing any **new** file whose path matches a glob below, `Read` the matching template first and start from it — never compose from memory. Contract & extension rules: `claude/lazycortex-core/references/lazy-core.scaffold-registry-contract.md`.

## Registry

```yaml
lazycortex-core:
  .claude/templates/core/rule-template.md:
    - .claude/rules/*.md
    - ~/.claude/rules/*.md
  .claude/templates/core/skill-template.md:
    - .claude/skills/*/SKILL.md
    - ~/.claude/skills/*/SKILL.md
  .claude/templates/core/agent-template.md:
    - .claude/agents/*.md
    - ~/.claude/agents/*.md
  .claude/templates/core/command-template.md:
    - .claude/commands/*.md
    - ~/.claude/commands/*.md
  .claude/templates/core/protocol-template.md:
    - .claude/references/*-protocol.md
    - ~/.claude/references/*-protocol.md
  .claude/templates/core/schema-template.md:
    - .claude/references/*-schema.md
    - ~/.claude/references/*-schema.md
  .claude/templates/core/contract-template.md:
    - .claude/references/*-contract.md
    - ~/.claude/references/*-contract.md
```
