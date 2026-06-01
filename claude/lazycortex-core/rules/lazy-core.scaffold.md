---
description: Registry of authoring templates for any new artifact a plugin registers.
always_loaded: fires at create-time; path-scoped contracts don't trigger on Write
---
# Scaffold

Before composing any **new** file whose path matches a glob below, `Read` the matching template first and start from it — never compose from memory. Contract & extension rules: `claude/lazycortex-core/references/lazy-core.scaffold-registry-contract.md`.

When several globs match the same path, the most-specific wins (within a key and across keys); on an equal-specificity tie, `_local` overrides plugin keys.

## Registry

```yaml
{}
```
