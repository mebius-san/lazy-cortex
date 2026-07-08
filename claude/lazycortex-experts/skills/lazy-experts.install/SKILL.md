---
name: lazy-experts.install
description: "Bootstrap the lazycortex-experts plugin for the current project (or globally). Seeds two things into `lazy.settings.json`: (1) agent-model tiers for the generic agents from `lazycortex-core`'s `default-tiers.json` into `agent_models.lazycortex`; (2) composed expert entries per the class map (technical classes seed six roles; fiction classes `sci-fi`/`fantasy` seed only `fiction-writer`) into `experts` — every entry also carries `lazycortex-experts:lazy-experts.discipline-aspect` (plus `lazy-experts.tech-writing-aspect` on technical classes), `lazycortex-core:lazy-memory.persona-aspect`, and a deterministic bot `git_author`. Asks which expert classes to register ONLY when the experts list is empty; on a populated list it derives the classes already present and completes them without asking. Experts and tiers are dispatch-routing config used by interactive flows AND the daemon — never gated on `daemon.enabled`. Idempotent and quiet on re-run; existing entries are never overwritten. Detects install scope automatically."
allowed-tools: Read, Write, Edit, Glob, AskUserQuestion, TaskCreate, TaskUpdate, TaskList, TaskGet, Bash(mkdir -p *), Bash(git rev-parse*), Bash(test *), Bash(date *), Bash(ls *), Bash(python3 *), Bash(lazycortex-core *)
---
# Install lazycortex-experts

Seed two things into the consumer's `lazy.settings.json` so dispatch routing works out of the box: agent-model tiers (so each generic agent gets the right Claude tier) and composed expert entries per the class map (Step 5), every entry carrying the persona aspect so the expert accumulates private memory under `.memory/<self>/`. No rules to sync — this plugin ships none. Both shapes are **dispatch-routing config consumed by interactive flows (spec / review / direct expert dispatch) as well as the daemon**, so neither is gated on `daemon.enabled`.

## Execution discipline (MANDATORY — read before any action)

This skill has 7 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Detect install scope`
   - `Step 2 — Determine target paths`
   - `Step 3 — Determine expert classes`
   - `Step 4 — Seed agent_models`
   - `Step 5 — Seed expert entries`
   - `Step 6 — Verify / Report`
   - `Step 7 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `unchanged`, `added`, `kept-local`, `asked`, `derived`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Decisions are remembered, never re-asked

This skill is **idempotent and quiet on re-run**. It asks exactly one thing, and only on a fresh project:

- **Expert classes** — which domain aspects to register (e.g. `claude-plugin`, `game-dev`, `dotfiles`, `sci-fi`, `fantasy`). Asked ONLY when the `experts` section is empty (a fresh project). When `experts` already holds entries, the skill derives the classes already present from their `aspects` and completes those — never re-asking, never silently dragging in classes you didn't choose.
- **Install scope** is derived from where the plugin is *enabled* (see Step 1); a project-scope enablement wins even when the install record's `scope` is `user`.
- **Expert git identity** is a deterministic bot id (`{name: <title-cased expert>, email: <expert-key>@lazycortex.local}`), never the operator's `git config`.
- **Existing entries are never overwritten**, including hand-customized composed experts.
- **No daemon gate.** Experts and `agent_models` tiers are dispatch-routing config used outside the daemon too (interactive `Agent` dispatch, spec / review writers), so this skill seeds them regardless of `daemon.enabled`. Only the runtime *routines / supervisor* (owned by `lazy-core.install` and the routine-registering plugins) are daemon-gated.

## Step 1: Detect install scope

Scope = **where the plugin is actually enabled**, not where `/plugin install` last ran. The `scope` field in `installed_plugins.json` records the install command's origin, which drifts from the activation scope — a plugin enabled per-project in `.claude/settings.json` can carry an install record of `scope: "user"`. Resolve it via the core CLI, which reads `enabledPlugins` from the project settings first, then the global settings, falling back to the install record's own `scope` only when neither enables the plugin:

```
Bash(lazycortex-core detect-scope lazycortex-experts@lazycortex)
```

The command prints exactly one word:
- `project` → target `<repo-root>/.claude/lazy.settings.json` (project wins even when the install record's scope is `user`, and when both scopes enable it).
- `user` → target `~/.claude/lazy.settings.json` (enabled only globally, or the fallback resolved there).
- `not-installed` → `lazycortex-experts@lazycortex` is absent / has an empty array in `installed_plugins.json`; the plugin has never been installed on this machine.

**Do NOT compare `projectPath` against the current working directory.** Step 2 targets `<repo-root>` regardless.

The scope is derived — do NOT ask. Abort **only** on `not-installed` (the shared plugin cache is the sole proof of installation, and enablement cannot substitute for missing sources). Message: `lazycortex-experts not enabled — add "lazycortex-experts@lazycortex": true to enabledPlugins in your settings.json and run /plugin install lazycortex/lazycortex-experts.`

Outcome: `scope-detected: <user|project>`.

## Step 2: Determine target paths

| Scope | `lazy.settings.json` path |
|---|---|
| `user` | `~/.claude/lazy.settings.json` |
| `project` | `<repo-root>/.claude/lazy.settings.json` (root = `git rev-parse --show-toplevel`, or cwd if not in a git repo — warn the user) |

Locate `lazycortex-core`'s shipped defaults file per the inter-plugin boundary contract — walk `$LAZYCORTEX_PLUGIN_DIRS` first, fall back to the cache glob when env is unset (install-time invocation outside the daemon):

```bash
CORE_DIR=""
IFS=":" read -ra DIRS <<< "${LAZYCORTEX_PLUGIN_DIRS:-}"
for d in "${DIRS[@]}"; do
  if [[ "$d" == *"/lazycortex-core" ]] && [ -f "$d/skills/lazy-core.agent-models/default-tiers.json" ]; then
    CORE_DIR="$d"; break
  fi
done
[ -z "$CORE_DIR" ] && CORE_DIR=$(ls -d ~/.claude/plugins/cache/lazycortex/lazycortex-core/*/ 2>/dev/null | sort -V | tail -1)
FILE="$CORE_DIR/skills/lazy-core.agent-models/default-tiers.json"
```

Newest version wins. If `$FILE` is absent → FAIL with `lazycortex-core not installed; install it before /lazy-experts.install`. Do NOT fall through to a hardcoded fallback — silent drift is exactly what the SOT is meant to prevent.

Outcome: `target-resolved: <path>`, `defaults-resolved: <path>`.

## Step 3: Determine expert classes

The expert "classes" are the domain aspects this plugin ships. Enumerate the available classes, then decide which to register based on whether the project already has experts. This is the skill's only interactive decision — and only on a fresh (empty) experts list.

### Enumerate available classes and roles

- `<installPath>` is the `installPath` field from `~/.claude/plugins/installed_plugins.json` for `lazycortex-experts@lazycortex`.
- **Classes (domain aspects)**: `Glob <installPath>/references/lazy-experts.*-aspect.md`, minus the cross-cutting aspects `discipline` and `tech-writing` (they compose onto experts, they are not classes). The class key is the basename minus the `lazy-experts.` prefix and the `-aspect.md` suffix — currently `claude-plugin`, `game-dev`, `dotfiles`, `sci-fi`, `fantasy`.
- **Roles (agents)**: `Glob <installPath>/agents/lazy-experts.*.md`. The role is the basename minus the `lazy-experts.` prefix and `.md` suffix — currently `interpreter`, `designer`, `planner`, `implementer`, `debugger`, `reviewer`, `fiction-writer`. Which roles a class seeds is decided by the class map in Step 5.

If either glob is empty, abort with `plugin-cache-incomplete: <missing-dir>`.

### Decide the class set

Load the `experts` section (via `lazy_settings.load_tracked_section`). Count the entries whose key is not `_version`.

- **Empty** (no expert entries) → ask the operator which classes to register:

```
AskUserQuestion:
  question: "Which expert classes should this project register?"
  description: "Each class is a domain the generic experts specialise in (the aspect they load). Pick the domain(s) this project works in — re-run later to add more. Roles are seeded per the class map: technical classes get all six engineering roles; sci-fi/fantasy get fiction-writer."
  multiSelect: true
  options: one per available class (e.g. "claude-plugin", "game-dev", "dotfiles", "sci-fi", "fantasy")
```

  The chosen classes are the class set. State `asked: <classes>`.

- **Non-empty** → do NOT ask. Derive the class set from the existing entries: for each entry (besides `_version`), read its `aspects` list and extract every ref of the form `lazycortex-experts:lazy-experts.<domain>-aspect`, excluding the cross-cutting aspects `discipline` and `tech-writing` (they compose onto every technical expert and are not classes); collapse the remaining `<domain>` values to a set. That derived set is the class set — Step 5 completes any missing roles for exactly those classes and adds no others. State `derived: <classes>`.

Outcome: `classes: <comma-list> (asked|derived)`.

## Step 4: Seed agent_models

Read the target `lazy.settings.json`. If missing or unparseable, initialize as `{"_version": 1, "agent_models": {}, "experts": {"_version": 1}}`. Ensure `agent_models.lazycortex` exists as an object (create empty `{}` if absent — never overwrite other groups).

Read the resolved defaults JSON. Select every key under `defaults` that starts with `lazycortex-experts:` — these are the agent-tier entries to seed.

For each `(dispatch, tier)` pair from the defaults file, write back only if anything changed:

- **absent** in `agent_models.lazycortex` → add the entry. State `added`.
- **equal** → leave untouched. State `unchanged`.
- **different** → leave the user's value untouched. State `kept-local` (report both values).

Never touch other `lazycortex` entries (seeded by sibling install skills).

Outcome (one line per seeded entry): `lazycortex.<key> = <tier> (<state>)`.

## Step 5: Seed expert entries

Seed one composed expert entry per (class × role) pair from the **class map** below, for the class set from Step 3. Every seeded entry also carries `lazycortex-core:lazy-memory.persona-aspect` (memory subsystem opt-in) and the cross-cutting aspects the map assigns.

### The class map

| Class kind | Classes | Roles seeded | Cross-cutting aspects (appended after the domain aspect) |
|---|---|---|---|
| technical | `claude-plugin`, `game-dev`, `dotfiles`, and any future class not listed as fiction | `interpreter`, `designer`, `planner`, `implementer`, `debugger`, `reviewer` | `lazy-experts.discipline-aspect`, `lazy-experts.tech-writing-aspect`, `lazy-memory.persona-aspect` |
| fiction | `sci-fi`, `fantasy` | `fiction-writer` | `lazy-experts.discipline-aspect`, `lazy-memory.persona-aspect` |

Technical classes never seed `fiction-writer`; fiction classes never receive `lazy-experts.tech-writing-aspect` (its bans contradict literary craft). The fiction row is the closed list above; a future genre aspect extends it in the same edit that ships the aspect.

### Compose

For each `(class, role)` pair from the class map (restricted to the Step 3 class set), build the expert key by domain-mapping the class to its short form:

| Class (aspect basename suffix) | Expert-key domain |
|---|---|
| `claude-plugin` | `claude-plugin` |
| `game-dev` | `game` |
| `dotfiles` | `dotfiles` |
| `sci-fi` | `sci-fi` |
| `fantasy` | `fantasy` |
| *(other / future)* | `<class>` (verbatim) |

The expert key is `<domain>.<role>` — dot-separated. Examples: `claude-plugin.designer`, `game.interpreter`, `dotfiles.planner`. The domain map is closed-set for the five shipped classes (three technical + two fiction); future classes fall through to the verbatim class name. This is the marketplace-wide expert-key convention `<domain>.<role>` (cf. `review.historian`, `wiki.curator`, `spec.request-router`).

The composed entry's shape:

```jsonc
"<expert-key>": {
  "agent": "lazycortex-experts:lazy-experts.<role>",
  "aspects": [
    "lazycortex-experts:lazy-experts.<class>-aspect",
    "lazycortex-experts:lazy-experts.discipline-aspect",
    "lazycortex-experts:lazy-experts.tech-writing-aspect",   // technical classes only — omit for fiction classes
    "lazycortex-core:lazy-memory.persona-aspect"
  ],
  "git_author": {
    "name": "<title-case-with-spaces>",
    "email": "<expert-key>@lazycortex.local"
  }
}
```

The `git_author.name` is the expert key with the `.` separator and any `-` replaced by spaces, title-cased (e.g. `claude-plugin.designer` → `Claude Plugin Designer`, `game.interpreter` → `Game Interpreter`). The email pins the canonical local domain so commits attributed to the expert are visibly distinct from operator commits.

### Apply

Ensure `experts` exists as an object with `_version: 1` (create if absent — never overwrite). For each composed entry, per-key semantics matching Step 4:

- **absent** → add the entry verbatim. State `added`.
- **present** (any shape) → leave untouched. State `kept-local`. Do NOT overwrite even if the existing entry has different aspects or a stale `agent` ref — operators may have customized.

Load → modify → save uses `lazy_settings.load_tracked_section` so the local overlay never leaks into the tracked file. If any mutation happened, write the file with `_version: 1` preserved at the top of both `agent_models` and `experts`.

Outcome (one line per composed entry): `experts.<expert-key> (<state>)`.

While iterating, count existing entries that (a) reference a technical-class domain aspect of this plugin and (b) lack `lazycortex-experts:lazy-experts.tech-writing-aspect` in `aspects`. Do not modify them.

## Step 6: Verify / Report

- Read back the written `lazy.settings.json` and confirm it parses + contains the `lazycortex-experts:*` keys under `agent_models.lazycortex` (one per shipped generic agent) AND the expert keys the Step 5 class map prescribes for the class set under `experts`.
- For each seeded expert, confirm every aspect ref the class map assigns resolves: the class aspect (already proved by the Step 3 glob), `lazy-experts.discipline-aspect` and — for technical-class experts — `lazy-experts.tech-writing-aspect` (both under `<installPath>/references/`), and `lazy-memory.persona-aspect` (under `~/.claude/plugins/cache/lazycortex/lazycortex-core/*/references/`).
- For each seeded expert, confirm its `agent` ref resolves to an existing file under `<installPath>/agents/` (i.e. `lazy-experts.<role>.md` exists). A missing agent file is a `verify-failed: agent-ref-unresolved <expert-key>` outcome.
- Report to the user:
  - Scope detected.
  - Plugin version + commit synced from (from `installed_plugins.json`).
  - Defaults file path used.
  - Class set + whether it was `asked` or `derived` (Step 3).
  - Per-key outcome for both `agent_models` and `experts`.
  - If any existing technical-class experts lack the tech-writing aspect: `hint: <N> existing expert(s) missing lazycortex-experts:lazy-experts.tech-writing-aspect — append it to their aspects[] by hand, or remove the entries and re-run to re-seed.`

Outcome: `verified` or `verify-failed: <reason>`.

## Step 7: Log the run

Log to `./.logs/claude/lazy-experts.install/YYYY-MM-DD_HH-MM-SS.md` per `lazy-log.logging`. Required frontmatter: `git_sha`, `git_branch`, `date` (UTC), `input`.

Use two separate steps: `Bash(mkdir -p ./.logs/claude/lazy-experts.install)` then the `Write` tool. Never chain.

Outcome: `logged: <path>`.

## Report

One line per task in the canonical list above, with its outcome word.

## Failure modes

- **`/lazy-experts.install` aborts: "plugin not enabled"** — `lazycortex-experts@lazycortex` has no entry in `~/.claude/plugins/installed_plugins.json` → add `"lazycortex-experts@lazycortex": true` to `enabledPlugins` in `settings.json`, restart Claude Code, re-run.
- **`/lazy-experts.install` aborts: "lazycortex-core not installed"** — the defaults file glob returned nothing → install `lazycortex-core` first (`/plugin install lazycortex/lazycortex-core`), then re-run.
- **`/lazy-experts.install` aborts: "plugin-cache-incomplete"** — the agents or references glob under `<installPath>` returned nothing → run `/plugin update lazycortex-experts@lazycortex` to restore the cache, then re-run.

## Notes

- **Idempotent**: re-running this skill is safe. Entries are only added when absent; existing entries are never overwritten — including hand-customized composed experts.
- **Class set is sticky once seeded**: a fresh (empty) `experts` list prompts for classes; a populated list derives the classes already present and completes their roles. To ADD a new class to an already-populated project, register one expert of that class by hand (or clear `experts` and re-run to be re-prompted).
- **Re-run after `/plugin update`**: `/plugin update` refreshes the plugin cache but does not re-sync settings. Re-run if `default-tiers.json` shipped new `lazycortex-experts:*` rows OR a new role agent shipped — Step 5 fills the missing entries the class map prescribes for the existing class set.
- **Scope independence**: project-scope installs do not affect global config.
- **Not daemon-gated**: experts and tiers are routing config used by interactive dispatch too, so this skill seeds them whether or not the project runs the daemon. The daemon only affects whether *routines* fire (registered by `lazy-core.install` and the routine-owning plugins).
- **Memory side-effect**: every seeded expert carries `lazycortex-core:lazy-memory.persona-aspect`, which lets the expert write to `.memory/<self>/` via `lazy-memory.write`. `lazy-core.install` ensures the `.memory/` directory exists. Removing the persona aspect from a seeded expert is supported (the expert just stops growing memory) — the install skill never re-adds it on re-run.
