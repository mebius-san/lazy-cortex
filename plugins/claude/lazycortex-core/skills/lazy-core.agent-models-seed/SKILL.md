---
name: lazy-core.agent-models-seed
description: "Dispatched by a plugin install flow that cannot run `bin/lazycortex-core` itself, to seed its agent-model tiers; not for direct use."
allowed-tools: Read, Bash("${LAZYCORTEX_PYTHON:-python3}" *), Agent
execution-discipline-waiver: "nested-from-install — the calling install skill owns step discipline; a preamble here would re-anchor the caller and drop its remaining steps (lazy-core.skill-writing § 1.5)"
---
# Seed agent-model tiers for a plugin

Seed the `agent_models.lazycortex` domain group of a consumer's `lazy.settings.json` with the canonical model tiers for the subagents one plugin ships. Invoked with `args: "prefix=lazycortex-<x> scope=<project|user>"`; an install skill that can already run the core plugin's `bin/lazycortex-core` calls the `agent-models-seed` verb directly instead. Idempotent; a re-run with unchanged inputs writes nothing.

## Process

### Resolve inputs

Parse `prefix` (the plugin's dispatch-string prefix, e.g. `lazycortex-diagram`) and `scope` (`project` or `user`, the install scope the caller already resolved) from `args`.

### Run the verb

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" agent-models-seed --prefix <prefix> --scope <scope>)
```

The `agent-models-seed` verb owns the tier table lookup, the per-key comparison and the write; it prints one JSON line. Exit 0 carries `outcome` (`seeded-N`, `unchanged`, `no-entries`), `sot` (the tier table it read) and `entries` (`{dispatch, tier, state, previous}` with `state` one of `added`, `unchanged`, `refreshed`, `kept-local`). Exit 1 carries a refusal `outcome` — `sot-missing`, `missing-prefix`, `missing-scope`, `settings-unparseable` — and a `message`. The outcome of this skill is the verb's `outcome`; never report a seed the verb did not answer.

## Report

Return a compact block the caller folds into its own report:

```
agent-models-seed(<prefix>, <scope>): <outcome>
  sot: <sot>
  <dispatch> = <tier> (<state>)
  ...
```

One line per `entries` item. On `no-entries`, say so plainly and name `default-tiers.json` as the file to extend.

## Failure modes

- **Install reports `sot-missing` while seeding tiers** — `lazycortex-core`'s `default-tiers.json` could not be found → install `lazycortex-core` first, then re-run the plugin's install.
- **Install reports `settings-unparseable`** — the target `lazy.settings.json` is not valid JSON, and the verb leaves it untouched → fix the file by hand, then re-run the install.
- **Seed reports `no-entries` for a plugin that ships agents** — the plugin's `<prefix>:<agent>` dispatch strings are missing from `default-tiers.json` → add them to `lazycortex-core`'s `default-tiers.json`, then re-run.
