---
name: lazy-core.agent-models-seed
description: "Dispatched by a plugin's `<namespace>.install` skill (core, diagram, experts, obsidian, python, review, specs, wiki) to seed that plugin's agent-model tiers into the consumer's `lazy.settings.json`; not for direct use. Tiers come from `lazycortex-core`'s `default-tiers.json`, and an operator's existing value is never overwritten."
allowed-tools: Read, Write, Bash(ls *), Bash(FILE=*), Bash(git rev-parse*), AskUserQuestion, Agent
execution-discipline-waiver: "nested-from-install — the calling install skill owns step discipline; a preamble here would re-anchor the caller and drop its remaining steps (lazy-core.skill-writing § 1.5)"
---
# Seed agent-model tiers for a plugin

Seed the `agent_models.lazycortex` domain group of a consumer's `lazy.settings.json` with the canonical model tiers for the subagents one plugin ships. Tier values are read at runtime from `lazycortex-core`'s `default-tiers.json` — the single source of truth — so a plugin's install never hardcodes tiers and picks up a `default-tiers.json` edit on its next run. Invoked from a plugin's own install skill via `Skill(skill: "lazycortex-core:lazy-core.agent-models-seed", args: "prefix=lazycortex-<x> scope=<project|user>")`. Idempotent; a re-run with unchanged inputs writes nothing.

## Process

### Resolve inputs

Parse two inputs from `args` (or the invoking skill's context):

- `prefix` — the plugin's dispatch-string prefix, e.g. `lazycortex-diagram`. Every `default-tiers.json` key of the form `<prefix>:<agent>` is in scope. Required — abort `missing-prefix` if absent.
- `scope` — `project` or `user`, the install scope the caller already resolved (via `"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" detect-scope`). Required — abort `missing-scope` if absent or not one of the two.

### Resolve the target settings file

| `scope` | Target |
|---|---|
| `project` | `<repo-root>/.claude/lazy.settings.json`, where `<repo-root>` is `git rev-parse --show-toplevel` in the current cwd |
| `user` | `~/.claude/lazy.settings.json` |

### Locate `default-tiers.json` (the SOT)

`lazycortex-core` is a declared dependency of every consuming plugin, so it is installed (cache) or co-resident (dev vault). Locate the canonical defaults file per the inter-plugin boundary contract — walk `$LAZYCORTEX_PLUGIN_DIRS` first, fall back to the cache glob when the env is unset (install-time invocation outside the daemon):

```bash
FILE=""
IFS=":" read -ra DIRS <<< "${LAZYCORTEX_PLUGIN_DIRS:-}"
for d in "${DIRS[@]}"; do
  if [[ "$d" == *"/lazycortex-core" ]] && [ -f "$d/skills/lazy-core.agent-models/default-tiers.json" ]; then
    FILE="$d/skills/lazy-core.agent-models/default-tiers.json"; break
  fi
done
echo "${FILE:-unresolved}"
```

`unresolved` → `Bash(ls <home>/.claude/plugins/cache/lazycortex/lazycortex-core/*/skills/lazy-core.agent-models/default-tiers.json)` (`<home>` = the absolute home directory) and take the printed path whose version segment sorts highest numerically (`10.0.0` above `9.1.1`). That one pattern is the whole enumeration: never `find` or a walk of the cache, and a refusal is terminal.

The newest version wins. If the file is absent → abort `sot-missing` with `lazycortex-core not installed; install it before seeding <prefix> tiers` — never fall through to a hardcoded fallback (silent drift is exactly what the SOT prevents). Outcome: `sot-resolved` or abort.

### Build the seed set

Read and parse the SOT JSON. Select every key under `defaults` whose string begins with `<prefix>:`. Those `(dispatch, tier)` pairs — key and tier verbatim — are the seed set. An empty seed set (the plugin ships agents but none are listed in `default-tiers.json`) is a reportable `no-entries` outcome, NOT an abort — surface it so a maintainer knows the SOT is missing this plugin's agents.

### Apply per-key semantics

Read the target settings file. If missing or unparseable, treat it as `{"version": 1, "agent_models": {}}`. Ensure `agent_models.lazycortex` exists as an object (create empty `{}` if absent — never overwrite existing content, never touch other groups such as `_project` or `_user`).

**Every entry this skill writes is a seed, never a bare string.** A seed is the object
`{"tier": <SOT tier>, "seeded_from": <SOT tier>}` — the shape `lazy-core.install` Step 6 defines,
where `seeded_from` records the shipped default in force when the entry was written. A bare tier
string is the operator's pin (hand-written, or written by the `/lazy-core.agent-models` wizard),
and this skill never writes one and never rewrites one. Writing the seed form is what makes a
later re-run able to tell an untouched seed from a decision: presence is not currency, so a
plugin-owned value must stay refreshable when the shipped default moves.

For each `(dispatch, tier)` in the seed set, read what is on record and compare:

- **absent** in `agent_models.lazycortex` → write `{"tier": <SOT tier>, "seeded_from": <SOT tier>}`. State `added`.
- **seed object, untouched (`tier == seeded_from`), equal to the SOT** → leave untouched. State `unchanged`.
- **seed object, untouched (`tier == seeded_from`), SOT has moved** → rewrite BOTH fields to the SOT's tier, silently. State `refreshed` — report the old tier alongside the new. A stale shipped default is not the operator's choice.
- **seed object, edited (`tier != seeded_from`)** → leave untouched. State `kept-local` — the operator changed a seeded entry, so it is a pin from that moment on.
- **bare tier string** → leave untouched, whatever its value. State `kept-local` — report the consumer's value alongside the SOT's.

Never touch any `lazycortex` entry outside this prefix.

### Write back

If any mutation happened, `Write` the whole settings object back with `version: 1` at the top. If nothing changed, do not write. Outcome: `seeded-N` (N entries `added` or `refreshed`), `unchanged`, or `no-entries`.

## Report

Return a compact block the caller folds into its own report:

```
agent-models-seed(<prefix>, <scope>): <outcome>
  sot: <resolved default-tiers.json path>
  <dispatch> = <tier> (<state>)
  ...
```

One line per seed-set entry with its state. On `no-entries`, say so plainly and name `default-tiers.json` as the file to extend.

## Logging

Log to `./.logs/claude/lazy-core.agent-models-seed/YYYY-MM-DD_HH-MM-SS.md` per `lazy-log.logging`. Create the dir with `Bash(mkdir -p ./.logs/claude/lazy-core.agent-models-seed)`, then `Write` the file — never chain. Frontmatter: `git_sha`, `git_branch`, `date` (UTC), `input` (the args string). Body: `# lazy-core.agent-models-seed` heading, `## Actions` (resolved SOT path, per-key states), `## Result` (outcome word + summary).

## Failure modes

- **Install reports `sot-missing` while seeding tiers** — `lazycortex-core`'s `default-tiers.json` could not be found on `$LAZYCORTEX_PLUGIN_DIRS` or in the plugin cache → install `lazycortex-core` first, then re-run the plugin's install.
- **Seed reports `no-entries` for a plugin that ships agents** — the plugin's `<prefix>:<agent>` dispatch strings are missing from `default-tiers.json` → add them to `lazycortex-core`'s `default-tiers.json`, then re-run.
