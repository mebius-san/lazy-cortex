---
name: lazy-experts.install
description: "Bootstrap the lazycortex-experts plugin for the current project (or globally). Seeds two things into `lazy.settings.json`: (1) agent-model tiers for the three generic agents (interpreter, designer, planner) from `lazycortex-core`'s `default-tiers.json` into `agent_models.lazycortex`; (2) one composed expert entry per (agent × domain-aspect) pair into `experts` — every seeded expert also carries `lazycortex-core:lazy-memory.persona-aspect` so each accumulates private memory across runs. Idempotent — safe to re-run; existing entries are never overwritten."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(git rev-parse*), Bash(test *), Bash(date *), Bash(ls *), Bash(python3 *), AskUserQuestion
---
# Install lazycortex-experts

Seed two things into the consumer's `lazy.settings.json` so dispatch routing works out of the box: agent-model tiers (so each generic agent gets the right Claude tier) and composed expert entries (one per agent × domain-aspect pair, every entry carrying the persona aspect so the expert accumulates private memory under `.memory/<self>/`). No rules to sync — this plugin ships none.

## Execution discipline (MANDATORY — read before any action)

This skill has 6 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Detect install scope`
   - `Step 2 — Determine target paths`
   - `Step 3 — Seed agent_models`
   - `Step 4 — Seed expert entries`
   - `Step 5 — Verify / Report`
   - `Step 6 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `unchanged`, `skipped-per-user-choice`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1: Detect install scope

Read `~/.claude/plugins/installed_plugins.json`. The `lazycortex-experts@lazycortex` key holds an array — non-empty proves the plugin is installed and usable in the current cwd.

**Do NOT compare `projectPath` against the current working directory.** Step 2 targets `<repo-root>` regardless.

Inspect the `scope` field of the entries:
- `"user"` → global, target `~/.claude/lazy.settings.json`.
- `"project"` → per-project, target `<repo-root>/.claude/lazy.settings.json`.

If both scopes appear, ask the user which to target. Default: `project`.

Abort **only** if `lazycortex-experts@lazycortex` is absent or its array is empty. Message: `lazycortex-experts not enabled — add "lazycortex-experts@lazycortex": true to enabledPlugins in your settings.json and run /plugin install lazycortex/lazycortex-experts.`

Outcome: `scope-detected: <user|project>`.

## Step 2: Determine target paths

| Scope | `lazy.settings.json` path |
|---|---|
| `user` | `~/.claude/lazy.settings.json` |
| `project` | `<repo-root>/.claude/lazy.settings.json` (root = `git rev-parse --show-toplevel`, or cwd if not in a git repo — warn the user) |

Locate `lazycortex-core`'s shipped defaults file per the inter-plugin boundary contract — walk `$LAZYCORTEX_PLUGIN_DIRS` first, fall back to the cache glob when env is unset (install-time invocation outside the daemon):

```bash
FILE=""
IFS=":" read -ra DIRS <<< "${LAZYCORTEX_PLUGIN_DIRS:-}"
for d in "${DIRS[@]}"; do
  if [[ "$d" == *"/lazycortex-core" ]] && [ -f "$d/skills/lazy-core.agent-models/default-tiers.json" ]; then
    FILE="$d/skills/lazy-core.agent-models/default-tiers.json"; break
  fi
done
[ -z "$FILE" ] && FILE=$(ls ~/.claude/plugins/cache/lazycortex/lazycortex-core/*/skills/lazy-core.agent-models/default-tiers.json 2>/dev/null | sort -V | tail -1)
```

Newest version wins. If the file is absent → FAIL with `lazycortex-core not installed; install it before /lazy-experts.install`. Do NOT fall through to a hardcoded fallback — silent drift is exactly what the SOT is meant to prevent.

Outcome: `target-resolved: <path>`, `defaults-resolved: <path>`.

## Step 3: Seed agent_models

Read the target `lazy.settings.json`. If missing or unparseable, initialize as `{"_version": 1, "agent_models": {}, "experts": {"_version": 1}}`. Ensure `agent_models.lazycortex` exists as an object (create empty `{}` if absent — never overwrite other groups).

Read the resolved defaults JSON. Select every key under `defaults` that starts with `lazycortex-experts:` — these are the agent-tier entries to seed.

For each `(dispatch, tier)` pair from the defaults file, write back only if anything changed:

- **absent** in `agent_models.lazycortex` → add the entry. State `added`.
- **equal** → leave untouched. State `unchanged`.
- **different** → leave the user's value untouched. State `kept-local` (report both values).

Never touch other `lazycortex` entries (seeded by sibling install skills).

Outcome (one line per seeded entry): `lazycortex.<key> = <tier> (<state>)`.

## Step 4: Seed expert entries

Enumerate the agents and aspects this plugin ships, then seed one composed expert entry per (agent × domain-aspect) pair under `lazy.settings.json[experts]`. Every seeded entry also carries `lazycortex-core:lazy-memory.persona-aspect` so the expert is opted into the memory subsystem.

### Enumerate

- `<installPath>` is the `installPath` field from `~/.claude/plugins/installed_plugins.json` for `lazycortex-experts@lazycortex`.
- **Agents**: `Glob <installPath>/agents/lazy-experts.*.md`. For each match, the role is the basename minus the `lazy-experts.` prefix and `.md` suffix — currently `interpreter`, `designer`, `planner`.
- **Domain aspects**: `Glob <installPath>/references/lazy-experts.*-aspect.md`. For each match, the domain key is the basename minus the `lazy-experts.` prefix and `-aspect.md` suffix — currently `claude-plugin`, `game-dev`, `dotfiles`.

If either glob is empty, abort with `plugin-cache-incomplete: <missing-dir>`. The cache must hold both agents and aspects before seeding can run.

### Compose

For each `(domain, role)` pair (cartesian product — N agents × M aspects = N×M entries), build the expert key by prefix-mapping the domain to its short form:

| Domain (aspect basename suffix) | Expert-key prefix |
|---|---|
| `claude-plugin` | `claude-plugin-` |
| `game-dev` | `game-` |
| `dotfiles` | `dotfiles-` |
| *(other / future)* | `<domain>-` (verbatim) |

The expert key is `<prefix><role>`. Examples: `claude-plugin-designer`, `game-interpreter`, `dotfiles-planner`. The prefix map is closed-set for the three v1 domains; future domain aspects fall through to the verbatim form.

The composed entry's shape:

```jsonc
"<expert-key>": {
  "agent": "lazycortex-experts:lazy-experts.<role>",
  "aspects": [
    "lazycortex-experts:lazy-experts.<domain>-aspect",
    "lazycortex-core:lazy-memory.persona-aspect"
  ],
  "git_author": {
    "name": "<title-case-with-spaces>",
    "email": "<expert-key>@lazycortex.local"
  }
}
```

The `git_author.name` is the expert key with hyphens replaced by spaces, title-cased (e.g. `Claude Plugin Designer`, `Game Interpreter`). The email pins the canonical local domain so commits attributed to the expert are visibly distinct from operator commits.

### Apply

Ensure `experts` exists as an object with `_version: 1` (create if absent — never overwrite). For each composed entry, per-key semantics matching Step 3:

- **absent** → add the entry verbatim. State `added`.
- **present** (any shape) → leave untouched. State `kept-local`. Do NOT overwrite even if the existing entry has different aspects or a stale `agent` ref — operators may have customized.

If any mutation happened, write the file with `_version: 1` preserved at the top of both `agent_models` and `experts`.

Outcome (one line per seeded entry): `experts.<expert-key> (<state>)`.

## Step 5: Verify / Report

- Read back the written `lazy.settings.json` and confirm it parses + contains the three `lazycortex-experts:*` keys under `agent_models.lazycortex` AND the expected N×M expert keys under `experts`.
- For each seeded expert, confirm both aspect refs resolve (the file glob from Step 4 already proved this for domain aspects; the persona aspect must exist in `~/.claude/plugins/cache/lazycortex/lazycortex-core/*/references/lazy-memory.persona-aspect.md`).
- Report to the user:
  - Scope detected.
  - Plugin version + commit synced from (from `installed_plugins.json`).
  - Defaults file path used.
  - Per-key outcome for both `agent_models` and `experts`.

Outcome: `verified` or `verify-failed: <reason>`.

## Step 6: Log the run

Log to `./.logs/claude/lazy-experts.install/YYYY-MM-DD_HH-MM-SS.md` per `lazy-log.logging`. Required frontmatter: `git_sha`, `git_branch`, `date` (UTC), `input`.

Use two separate steps: `Bash(mkdir -p ./.logs/claude/lazy-experts.install)` then the `Write` tool. Never chain.

Outcome: `logged: <path>`.

## Report

One line per task in the canonical list above, with its outcome word.

## Failure modes

- **`/lazy-experts.install` aborts: "plugin not enabled"** — `lazycortex-experts@lazycortex` has no entry in `~/.claude/plugins/installed_plugins.json` → add `"lazycortex-experts@lazycortex": true` to `enabledPlugins` in `settings.json`, restart Claude Code, re-run.
- **`/lazy-experts.install` aborts: "lazycortex-core not installed"** — the defaults file glob returned nothing → install `lazycortex-core` first (`/plugin install lazycortex/lazycortex-core`), then re-run.

## Notes

- **Idempotent**: re-running this skill is safe. Entries are only added when absent; existing entries are never overwritten — including hand-customized composed experts.
- **Re-run after `/plugin update`**: `/plugin update` refreshes the plugin cache but does not re-sync settings. Re-run if `default-tiers.json` shipped new `lazycortex-experts:*` rows OR a new domain aspect shipped in a later release — the cartesian-product step picks the new entries up.
- **Scope independence**: project-scope installs do not affect global config.
- **Memory side-effect**: every seeded expert carries `lazycortex-core:lazy-memory.persona-aspect`, which lets the expert write to `.memory/<self>/` via `lazy-memory.write`. `lazy-core.install` ensures the `.memory/` directory exists and is un-ignored. Removing the persona aspect from a seeded expert is supported (the expert just stops growing memory) — the install skill never re-adds it on re-run.
