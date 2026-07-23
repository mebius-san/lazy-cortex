---
name: lazy-experts.install
description: "Bootstrap the lazycortex-experts plugin for the current project (or globally). Seeds two things into `lazy.settings.json`: (1) agent-model tiers for the generic agents from `lazycortex-core`'s `default-tiers.json` into `agent_models.lazycortex`; (2) composed expert entries per the class map (technical classes seed seven roles; fiction classes `sci-fi`/`fantasy` seed only `fiction-writer`) into `experts` — every entry also carries `lazycortex-experts:lazy-experts.discipline-aspect` (plus `lazy-experts.tech-writing-aspect` on technical classes), `lazycortex-core:lazy-memory.persona-aspect`, and a deterministic bot `git_author`. Asks which expert classes to register ONLY when no domain-class experts exist yet (system experts seeded by sibling plugins don't count); when domain experts are present it derives the classes and completes them without asking. Also checks system-expert completeness against the registry of sibling-plugin experts and reports missing ones (never seeds them — the owning plugin's install does). Experts and tiers are dispatch-routing config used by interactive flows AND the daemon — never gated on `daemon.enabled`. Idempotent and quiet on re-run; existing entries are never overwritten. Detects install scope automatically."
allowed-tools: Read, Write, Edit, Glob, Skill, AskUserQuestion, TaskCreate, TaskUpdate, TaskList, TaskGet, Bash(mkdir -p *), Bash(git rev-parse*), Bash(test *), Bash(date *), Bash(ls *), Bash(python3 *), Bash(lazycortex-core *)
---
# Install lazycortex-experts

Seed two things into the consumer's `lazy.settings.json` so dispatch routing works out of the box: agent-model tiers (so each generic agent gets the right Claude tier) and composed expert entries per the class map (Step 5), every entry carrying the persona aspect so the expert accumulates private memory under `.memory/<self>/`. No rules to sync — this plugin ships none. Both shapes are **dispatch-routing config consumed by interactive flows (spec / review / direct expert dispatch) as well as the daemon**, so neither is gated on `daemon.enabled`.

## Execution discipline (MANDATORY — read before any action)

This skill has 8 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Detect install scope`
   - `Step 2 — Determine target paths`
   - `Step 3 — Determine expert classes`
   - `Step 4 — Seed agent_models`
   - `Step 5 — Seed expert entries`
   - `Step 6 — Check system experts`
   - `Step 7 — Verify / Report`
   - `Step 8 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `unchanged`, `added`, `kept-local`, `asked`, `derived`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Decisions are remembered, never re-asked

This skill is **idempotent and quiet on re-run**. It asks exactly one thing, and only on a fresh project:

- **Expert classes** — which domain aspects to register (e.g. `claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`, `sci-fi`, `fantasy`). Asked ONLY when the `experts` section holds no domain-class entries — a fresh project, or one that so far carries only system experts seeded by sibling plugins (`wiki.curator`, `review.historian`, …). When domain-class entries exist, the skill derives the classes already present from their `aspects` and completes those — never re-asking, never silently dragging in classes you didn't choose.
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

The `lazycortex-core` defaults file (`default-tiers.json`, the tier SOT) is located by the seeding primitive itself in Step 4 — this step only resolves the target `lazy.settings.json` path from the scope.

Outcome: `target-resolved: <path>`.

## Step 3: Determine expert classes

The expert "classes" are the domain aspects this plugin ships. Enumerate the available classes, then decide which to register based on whether the project already has experts. This is the skill's only interactive decision — and only on a fresh (empty) experts list.

### Enumerate available classes and roles

- `<installPath>` is the `installPath` field from `~/.claude/plugins/installed_plugins.json` for `lazycortex-experts@lazycortex`.
- **Classes (domain aspects)**: `Glob <installPath>/references/lazy-experts.*-aspect.md`, minus the cross-cutting aspects `discipline` and `tech-writing` (they compose onto experts, they are not classes). The class key is the basename minus the `lazy-experts.` prefix and the `-aspect.md` suffix — currently `claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`, `sci-fi`, `fantasy`.
- **Roles (agents)**: `Glob <installPath>/agents/lazy-experts.*.md`. The role is the basename minus the `lazy-experts.` prefix and `.md` suffix — currently `interpreter`, `designer`, `planner`, `implementer`, `debugger`, `reviewer`, `tester`, `fiction-writer`. Which roles a class seeds is decided by the class map in Step 5.

If either glob is empty, abort with `plugin-cache-incomplete: <missing-dir>`.

### Decide the class set

Load the `experts` section (via `lazy_settings.load_tracked_section`). Partition the entries (besides `_version`) into two groups:

- **Domain entries** — entries whose `aspects` list contains at least one ref of the form `lazycortex-experts:lazy-experts.<domain>-aspect`, excluding the cross-cutting aspects `discipline` and `tech-writing` (they compose onto every technical expert and are not classes). These are the working expert sets this skill owns.
- **System entries** — everything else: experts seeded by sibling plugins (`wiki.curator`, `review.historian`, `spec.request-router`, `lazy-runtime.doctor`, …). They never count toward the class decision.

Decide on the **domain entries only**:

- **No domain entries** (fresh project, or only system experts so far) → ask the operator which classes to register:

```
AskUserQuestion:
  question: "Which expert classes should this project register?"
  description: "Each class is a domain the generic experts specialise in (the aspect they load). Pick the domain(s) this project works in — re-run later to add more. Roles are seeded per the class map: technical classes get all seven engineering roles; sci-fi/fantasy get fiction-writer."
  multiSelect: true
  options: one per available class (e.g. "claude-plugin", "game-dev", "dotfiles", "obsidian-plugin", "data-pipeline", "sci-fi", "fantasy")
```

  The chosen classes are the class set. State `asked: <classes>`.

- **Domain entries exist** → do NOT ask. Derive the class set from them: collapse each entry's `lazycortex-experts:lazy-experts.<domain>-aspect` refs to a set of `<domain>` values. That derived set is the class set — Step 5 completes any missing roles for exactly those classes and adds no others. State `derived: <classes>`.

Outcome: `classes: <comma-list> (asked|derived)`.

## Step 4: Seed agent_models

Dispatch the shared seeding primitive — it locates `lazycortex-core`'s `default-tiers.json` (the SOT), selects the `lazycortex-experts:*` keys, and applies them to `agent_models.lazycortex` in the target `lazy.settings.json` with absent→add / equal→unchanged / different→kept-local semantics (never clobbers an operator override, never touches other groups):

```
Skill(skill: "lazycortex-core:lazy-core.agent-models-seed", args: "prefix=lazycortex-experts scope=<scope>")
```

`<scope>` is the value resolved in Step 1 (`user` or `project`). Capture the primitive's report block — its `sot:` path and per-key states — verbatim; Step 7 folds it into the install report and surfaces `sot-missing` / `no-entries` if the primitive returns them.

Outcome: `seeded` (entries added) or `unchanged` (nothing to add).

## Step 5: Seed expert entries

Seed one composed expert entry per (class × role) pair from the **class map** below, for the class set from Step 3. Every seeded entry also carries `lazycortex-core:lazy-memory.persona-aspect` (memory subsystem opt-in) and the cross-cutting aspects the map assigns.

### The class map

| Class kind | Classes | Roles seeded | Cross-cutting aspects (appended after the domain aspect) |
|---|---|---|---|
| technical | `claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`, and any future class not listed as fiction | `interpreter`, `designer`, `planner`, `implementer`, `debugger`, `reviewer`, `tester` | `lazy-experts.discipline-aspect`, `lazy-experts.tech-writing-aspect`, `lazy-memory.persona-aspect` |
| fiction | `sci-fi`, `fantasy` | `fiction-writer` | `lazy-experts.discipline-aspect`, `lazy-memory.persona-aspect` |

Technical classes never seed `fiction-writer`; fiction classes never receive `lazy-experts.tech-writing-aspect` (its bans contradict literary craft). The fiction row is the closed list above; a future genre aspect extends it in the same edit that ships the aspect.

### Compose

For each `(class, role)` pair from the class map (restricted to the Step 3 class set), build the expert key by domain-mapping the class to its short form:

| Class (aspect basename suffix) | Expert-key domain |
|---|---|
| `claude-plugin` | `claude-plugin` |
| `game-dev` | `game` |
| `dotfiles` | `dotfiles` |
| `obsidian-plugin` | `obsidian-plugin` |
| `data-pipeline` | `data-pipeline` |
| `sci-fi` | `sci-fi` |
| `fantasy` | `fantasy` |
| *(other / future)* | `<class>` (verbatim) |

The expert key is `<domain>.<role>` — dot-separated. Examples: `claude-plugin.designer`, `game.interpreter`, `dotfiles.planner`. The domain map is closed-set for the seven shipped classes (five technical + two fiction); future classes fall through to the verbatim class name. This is the marketplace-wide expert-key convention `<domain>.<role>` (cf. `review.historian`, `wiki.curator`, `spec.request-router`).

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

## Step 6: Check system experts

Report-only completeness check for the **system entries** from Step 3 — experts that sibling plugins register via their own install skills. This skill NEVER seeds or edits them (the owning plugin's install is the sole writer); it only detects gaps so a plugin update that shipped a new system expert doesn't go unnoticed.

### The system-expert registry

| Owning plugin | Expert keys it registers | Fix |
|---|---|---|
| `lazycortex-core` | `lazy-runtime.doctor` | `/lazy-core.install` |
| `lazycortex-review` | `review.doc_doctor`, `review.historian` | `/lazy-review.install` |
| `lazycortex-specs` | `spec.request-router` | `/spec.install` |
| `lazycortex-wiki` | `wiki.curator` | `/lazy-wiki.install` |

The registry is closed-set: when a sibling plugin ships a new system expert, this table extends in the same edit that ships it.

### The check

For each registry row, resolve whether the owning plugin is enabled at the current scope: `Bash(lazycortex-core detect-scope <plugin>@lazycortex)` — treat `project`/`user` as enabled, `not-installed` as disabled (skip the row, state `skipped: <plugin> not installed`).

For each enabled plugin's expert keys, check presence in the loaded `experts` section:

- **present** → state `system: <key> (present)`.
- **missing** → state `system: <key> (missing — run <fix> to register, or ignore if the feature is deliberately unconfigured)`. Do NOT seed it yourself.

Additionally, list any system entry (from the Step 3 partition) whose key is absent from the registry table as `system: <key> (unknown — not in the registry; registered by a plugin this table doesn't know yet)`. Informational only.

Outcome: `system-experts: complete` or `system-experts: <N> missing`.

## Step 7: Verify / Report

- Read back the written `lazy.settings.json` and confirm it parses + contains the `lazycortex-experts:*` keys under `agent_models.lazycortex` (one per shipped generic agent) AND the expert keys the Step 5 class map prescribes for the class set under `experts`.
- For each seeded expert, confirm every aspect ref the class map assigns resolves: the class aspect (already proved by the Step 3 glob), `lazy-experts.discipline-aspect` and — for technical-class experts — `lazy-experts.tech-writing-aspect` (both under `<installPath>/references/`), and `lazy-memory.persona-aspect` (under `~/.claude/plugins/cache/lazycortex/lazycortex-core/*/references/`).
- For each seeded expert, confirm its `agent` ref resolves to an existing file under `<installPath>/agents/` (i.e. `lazy-experts.<role>.md` exists). A missing agent file is a `verify-failed: agent-ref-unresolved <expert-key>` outcome.
- Report to the user:
  - Scope detected.
  - Plugin version + commit synced from (from `installed_plugins.json`).
  - Class set + whether it was `asked` or `derived` (Step 3).
  - The `agent_models` seed result: fold in the Step 4 primitive's report block (its `sot:` defaults path + per-key states). If the primitive returned `sot-missing` or `no-entries`, surface that line prominently.
  - Per-key outcome for `experts`.
  - System-expert check result (Step 6): the `system-experts:` outcome plus one line per missing/unknown key.
  - If any existing technical-class experts lack the tech-writing aspect: `hint: <N> existing expert(s) missing lazycortex-experts:lazy-experts.tech-writing-aspect — append it to their aspects[] by hand, or remove the entries and re-run to re-seed.`

Outcome: `verified` or `verify-failed: <reason>`.

## Step 8: Log the run

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
- **Class set is sticky once seeded**: with no domain-class entries (fresh project, or system experts only) the skill prompts for classes; once domain entries exist it derives the classes already present and completes their roles. To ADD a new class to an already-populated project, register one expert of that class by hand (or remove all domain entries and re-run to be re-prompted — system entries don't block the prompt).
- **Re-run after `/plugin update`**: `/plugin update` refreshes the plugin cache but does not re-sync settings. Re-run if `default-tiers.json` shipped new `lazycortex-experts:*` rows OR a new role agent shipped — Step 5 fills the missing entries the class map prescribes for the existing class set.
- **Scope independence**: project-scope installs do not affect global config.
- **Not daemon-gated**: experts and tiers are routing config used by interactive dispatch too, so this skill seeds them whether or not the project runs the daemon. The daemon only affects whether *routines* fire (registered by `lazy-core.install` and the routine-owning plugins).
- **Memory side-effect**: every seeded expert carries `lazycortex-core:lazy-memory.persona-aspect`, which lets the expert write to `.memory/<self>/` via `lazy-memory.write`. `lazy-core.install` ensures the `.memory/` directory exists. Removing the persona aspect from a seeded expert is supported (the expert just stops growing memory) — the install skill never re-adds it on re-run.
