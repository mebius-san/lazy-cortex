---
description: Registry of authoring templates for any new artifact a plugin registers.
always_loaded: fires at create-time; path-scoped contracts don't trigger on Write
---
# Scaffold

Before composing any **new** file whose path matches a glob below, `Read` the matching template first and start from it — never compose from memory. Contract & extension rules: `claude/lazycortex-core/references/lazy-core.scaffold-registry-contract.md`.

When several globs match one path, the most specific wins, within a key and across keys. Specificity is a total order: wildcard-free path segments, then literal characters outside wildcards, then `_local` over a plugin key.

## Registry

```yaml
{}
```
