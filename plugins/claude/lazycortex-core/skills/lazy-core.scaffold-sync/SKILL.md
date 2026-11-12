---
name: lazy-core.scaffold-sync
description: "Dispatched by a plugin install flow that cannot run `bin/lazycortex-core` itself, to sync its scaffold templates; not for direct use."
allowed-tools: Read, Bash(git rev-parse*), Bash("${LAZYCORTEX_PYTHON:-python3}" *), Agent
execution-discipline-waiver: "nested-from-install — the calling install skill owns step discipline; a preamble here would re-anchor the caller and drop its remaining steps (lazy-core.skill-writing § 1.5)"
---
# Sync Scaffold Templates and Registry

Copies every authoring template shipped by a plugin into the consumer's `.claude/templates/<group>/` directories, then upserts the corresponding entries into the scaffold registry. Invoked with `args: "plugin=<name> installPath=<path> scope=<project|user>"`; an install skill that can already run the core plugin's `bin/lazycortex-core` runs the `scaffold sync-plugin` verb directly instead. Safe to re-invoke; every write is idempotent.

## Process

### Resolve inputs

Parse `plugin` (the plugin's installed name, e.g. `lazycortex-core`), `installPath` (the plugin's install root) and `scope` (`project` or `user`) from `args`.

### Run the verb

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" scaffold sync-plugin --plugin <plugin> --install-path <installPath> --scope <scope>)
```

The `scaffold sync-plugin` verb does the whole job and prints one JSON line: `templates` (one `{group, file, state}` per template, `state` one of `installed`, `unchanged`, `refreshed`, `protected`, `failed`), `counts`, `failed`, `registry` (the registry file) and `status` — the registry outcome, one of `registered`, `unchanged`, `created-and-registered`, `none` (the plugin ships no manifest), `collision` or `error`, with `message` explaining the last three. Exit 3 means a template write did not verify; never restate a `failed` template as applied.

A template reported `protected` is a path the registry lists under `_local`: the operator's own file, left byte-for-byte as it is. Protection is a safety net, not the fix — surface every such line and name the `_local` entry behind it.

## Report

```
Templates synced:
  <group>/<file>: <state>
  ...

Registry upsert: <status>
```

One line per `templates` entry. A `protected` line carries the reason and the entry behind it — `<group>/<file>: protected — registered under `_local`, left as authored`. Then the `status` line. The outcome of this skill is the verb's `status`; never report a sync the verb did not answer.

## Failure modes

- **`scaffold-sync` reports `none`** — the plugin ships no `templates/*/scaffold.entries.json` → nothing was registered; the plugin does not use the scaffold system. Not an error.
- **`scaffold-sync` reports `collision`** — two groups declare the same template path with different globs; the verb wrote nothing, and `message` names the key and both groups → edit the plugin's `scaffold.entries.json` manifests so there is no overlap, then re-run.
- **`scaffold-sync` reports `error`** — the consumer's `lazy-core.scaffold.md` registry does not parse; the verb wrote nothing, and `message` carries the findings → fix the registry block, then re-run.
- **A template reports `protected`** — the consumer path is registered under `_local`, so the operator's own file was kept and the shipped template did not land → not an error; the `_local` entry sits in a group this plugin supplies, which `/lazy-core.scaffold-local` refuses to create. Re-file that entry under a group of its own with `/lazy-core.scaffold-local mode=remove` followed by `mode=add`, then re-run this skill.
