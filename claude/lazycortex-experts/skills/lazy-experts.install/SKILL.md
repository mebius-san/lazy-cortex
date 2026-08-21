---
name: lazy-experts.install
description: "Run when the operator asks to set up lazycortex-experts in a repo, to add or complete an expert class (`claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`, `software-product`, `sci-fi`, `fantasy`), or when dispatching an expert fails because `lazy.settings.json` has no matching `experts` entry or no model tier for a generic agent. Unlike the sibling install skills, it syncs no rules — it only seeds composed expert entries per the class map plus agent-model tiers, asks for classes only on a project that has none yet, and never overwrites what an operator chose — the one thing it completes on an existing entry is a missing mandatory cross-cutting aspect. Idempotent and quiet on re-run; install scope is detected."
allowed-tools: Read, Write, Edit, Glob, Skill, AskUserQuestion, TaskCreate, TaskUpdate, TaskList, TaskGet, Bash(mkdir -p *), Bash(git rev-parse*), Bash(test *), Bash(date *), Bash(ls *), Bash(python3 *), Bash(lazycortex-core *), Agent
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

- **Expert classes** — which domain aspects to register (e.g. `claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`, `software-product`, `sci-fi`, `fantasy`). Asked ONLY when the `experts` section holds no domain-class entries — a fresh project, or one that so far carries only system experts seeded by sibling plugins (`wiki.curator`, `review.doc_doctor`, …). When domain-class entries exist, the skill derives the classes already present from their `aspects` and completes those — never re-asking, never silently dragging in classes you didn't choose.
- **Install scope** is derived from where the plugin is *enabled* (see Step 1); a project-scope enablement wins even when the install record's `scope` is `user`.
- **Expert git identity** is a deterministic bot id (`{name: <title-cased expert>, email: <expert-key>@bot.invalid}`), never the operator's `git config`.
- **Existing entries are never overwritten**, including hand-customized composed experts. A missing mandatory cross-cutting aspect is appended to `aspects[]` and nothing else is touched — completing a mandatory list is not overwriting a choice (Step 5).
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
- **Classes (domain aspects)**: `Glob <installPath>/references/lazy-experts.*-aspect.md`, minus the cross-cutting aspects `discipline`, `research`, `tech-writing`, `terms`, and `structure` (they compose onto experts, they are not classes). The class key is the basename minus the `lazy-experts.` prefix and the `-aspect.md` suffix — currently `claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`, `software-product`, `sci-fi`, `fantasy`.
- **Roles (agents)**: `Glob <installPath>/agents/lazy-experts.*.md`. The agent basenames minus the `lazy-experts.` prefix and `.md` suffix are the agent set — currently `interpreter`, `designer`, `architect`, `planner`, `implementer`, `data-implementer`, `docs-writer`, `debugger`, `reviewer`, `tester`, `fiction-writer`. Which roles a class seeds — and which agent each role resolves to (three roles map onto an agent of a different basename, see Step 5's mapping table) — is decided by the class map in Step 5.

If either glob is empty, abort with `plugin-cache-incomplete: <missing-dir>`.

### Decide the class set

Load the `experts` section (via `lazy_settings.load_tracked_section`). Partition the entries (besides `_version`) into two groups:

- **Domain entries** — entries whose `aspects` list contains at least one ref of the form `lazycortex-experts:lazy-experts.<domain>-aspect`, excluding the cross-cutting aspects `discipline`, `research`, `tech-writing`, `terms`, and `structure` (they compose onto every technical expert and are not classes). These are the working expert sets this skill owns.
- **System entries** — everything else: experts seeded by sibling plugins (`wiki.curator`, `review.doc_doctor`, `spec.coordinator`, `runtime.doctor`, …). They never count toward the class decision.

Decide on the **domain entries only**:

- **No domain entries** (fresh project, or only system experts so far) → ask the operator which classes to register:

```
AskUserQuestion:
  question: "Which expert classes should this project register?"
  description: "Each class is a domain the generic experts specialise in (the aspect they load). Pick the domain(s) this project works in — re-run later to add more. Roles are seeded per the class map: technical classes get all eight engineering roles; sci-fi/fantasy get fiction-writer."
  multiSelect: true
  options: one per available class (e.g. "claude-plugin", "game-dev", "dotfiles", "obsidian-plugin", "data-pipeline", "software-product", "sci-fi", "fantasy")
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
| technical | `claude-plugin`, `game-dev`, `dotfiles`, `obsidian-plugin`, `data-pipeline`, `software-product`, and any future class not listed as fiction | `interpreter`, `designer`, `system-designer`, `architect`, `planner`, `developer`, `debugger`, `reviewer`, `tester` | `lazy-experts.discipline-aspect`, `lazy-experts.research-aspect`, `lazy-experts.tech-writing-aspect`, `lazy-experts.terms-aspect`, `lazy-experts.structure-aspect`, `lazy-memory.persona-aspect` |
| data | `game-dev` | `data-writer` | the same cross-cutting aspects the technical row assigns |
| fiction | `sci-fi`, `fantasy` | `fiction-writer` | `lazy-experts.discipline-aspect`, `lazy-experts.research-aspect`, `lazy-memory.persona-aspect` |

The `data` row is additive, not a separate class kind: `game-dev` seeds every technical role AND `data-writer`. Writing entity data files against an approved design is a subject-matter particularity of game development — a project of another class that wants the role asks for it by an explicit operator action rather than receiving it by default.

Technical classes never seed `fiction-writer`; fiction classes never receive `lazy-experts.tech-writing-aspect` (its bans contradict literary craft) or `lazy-experts.terms-aspect` (an obligation to call a thing by its registered term, read literally inside a scene, replaces pronouns and descriptive phrases with the entity name) or `lazy-experts.structure-aspect` (a repository map has nothing to say inside a scene). The fiction row is the closed list above; a future genre aspect extends it in the same edit that ships the aspect.

### Compose

For each `(class, role)` pair from the class map (restricted to the Step 3 class set), build the expert key by domain-mapping the class to its short form:

| Class (aspect basename suffix) | Expert-key domain |
|---|---|
| `claude-plugin` | `claude-plugin` |
| `game-dev` | `game` |
| `dotfiles` | `dotfiles` |
| `obsidian-plugin` | `obsidian-plugin` |
| `data-pipeline` | `data-pipeline` |
| `software-product` | `software` |
| `sci-fi` | `sci-fi` |
| `fantasy` | `fantasy` |
| *(other / future)* | `<class>` (verbatim) |

The expert key is `<domain>.<role>` — dot-separated. Examples: `claude-plugin.designer`, `game.interpreter`, `dotfiles.planner`. The domain map is closed-set for the eight shipped classes (six technical + two fiction); future classes fall through to the verbatim class name. This is the marketplace-wide expert-key convention `<domain>.<role>` (cf. `review.doc_doctor`, `wiki.curator`, `spec.coordinator`).

Three roles do not share their agent's basename — the role names the job, the agent stays under its own name:

| Role | Agent |
|---|---|
| `developer` | `lazycortex-experts:lazy-experts.implementer` |
| `data-writer` | `lazycortex-experts:lazy-experts.data-implementer` |
| `system-designer` | `lazycortex-experts:lazy-experts.designer` |

Every other role's agent is `lazycortex-experts:lazy-experts.<role>` verbatim.

The composed entry's shape:

```jsonc
"<expert-key>": {
  "agent": "lazycortex-experts:lazy-experts.<role>",   // or the mapped agent from the table above
  "aspects": [
    "lazycortex-experts:lazy-experts.<class>-aspect",
    "lazycortex-experts:lazy-experts.discipline-aspect",
    "lazycortex-experts:lazy-experts.research-aspect",
    "lazycortex-experts:lazy-experts.tech-writing-aspect",   // technical classes only — omit for fiction classes
    "lazycortex-experts:lazy-experts.terms-aspect",          // technical classes only — omit for fiction classes
    "lazycortex-experts:lazy-experts.structure-aspect",      // technical classes only — omit for fiction classes
    "lazycortex-core:lazy-memory.persona-aspect"
  ],
  "git_author": {
    "name": "<title-case-with-spaces>",
    "email": "<expert-key>@bot.invalid"
  },
  "workspace": "branch",   // developer/data-writer/docs-writer/tester roles only — omit for every other role
  "can_commit_in_repo": true   // writing roles only (see below) — omit for interpreter/reviewer/fiction-writer
}
```

The `git_author.name` is the expert key with the `.` separator and any `-` replaced by spaces, title-cased (e.g. `claude-plugin.designer` → `Claude Plugin Designer`, `game.interpreter` → `Game Interpreter`). The email pins the canonical local domain so commits attributed to the expert are visibly distinct from operator commits.

`workspace: branch` is seeded ONLY when `<role>` is `developer`, `data-writer`, `docs-writer`, or `tester` — the acceptance-cycle classes `lazycortex-specs.optional-plan-and-auto-implementation.md` describes run their launch-checkbox job and every continuation on a job-scoped branch (`lazy-core.runtime-schema.md` § Workspace). Every other role stays on `workspace: main` (the field omitted entirely) — same as today. This is a seed proposal only: the per-key semantics in Apply below apply here too, a developer/tester expert that already exists keeps whatever `workspace` (or its absence) the operator left it at.

`can_commit_in_repo: true` is seeded for every **writing role** — `designer`, `system-designer`, `architect`, `planner`, `developer`, `data-writer`, `docs-writer`, `debugger`, `tester` — and omitted for `interpreter`, `reviewer`, and `fiction-writer`. The writing roles land their work as files in the working tree: a launch-checkbox job's doc writer (architect, planner) writes its document in place and the coordinator only opens review on it via `submit` on the job-done wake (`lazy-spec.coordination-playbook.md` Chapter 6); the acceptance-cycle roles commit on their job-scoped branch; designer additionally serves the change-cascade's in-place edits (`lazy-spec.install` § 6e); debugger fixes code in the tree. Without the flag, `expert_pump` extends the spawn prompt with a no-commit clause, and the job's document never reaches the tracked tree — it strands in the job's own `result/`, which the coordinator can only flag as undelivered. The non-writing roles deliver through the review payload channel (interpreter, fiction-writer) or deliver findings without editing at all (reviewer), so they stay without commit rights.

### Apply

Ensure `experts` exists as an object with `_version: 1` (create if absent — never overwrite). For each composed entry, per-key semantics matching Step 4:

- **absent** → add the entry verbatim. State `added`.
- **present** (any shape) → leave every field the operator owns untouched. State `kept-local`. Do NOT overwrite a differing `agent` ref, `git_author`, `workspace`, or the domain aspect — operators may have customized. The one exception is the mandatory cross-cutting aspects, below.

### Complete the mandatory cross-cutting aspects

Five cross-cutting aspects are **mandatory on every domain-class entry**, whenever that entry was created: `lazy-experts.discipline-aspect` and `lazy-experts.research-aspect` on every entry regardless of class kind, plus `lazy-experts.tech-writing-aspect`, `lazy-experts.terms-aspect`, `lazy-experts.structure-aspect` on **technical**-class entries only, per the class map in Step 5. An entry created before one of them shipped is not a customized entry — it is an incomplete one, and leaving it that way means an expert seeded a year ago silently writes to a different contract than the one seeded today.

So for every existing entry that references a domain aspect of this plugin — technical or fiction — append `lazy-experts.discipline-aspect` and `lazy-experts.research-aspect` when missing from its `aspects` array; for every entry that references a **technical**-class domain aspect specifically, also append each of `lazy-experts.tech-writing-aspect`, `lazy-experts.terms-aspect`, `lazy-experts.structure-aspect` that is missing. Appending only: order is preserved, nothing is reordered, nothing is removed, and no other field is touched. Fiction-class entries receive `discipline` and `research` alone — `tech-writing`, `terms`, and `structure` never compose onto them.

`can_commit_in_repo` follows the same completion rule: an existing writing-role entry (per the role list in Step 5) that carries NO `can_commit_in_repo` key at all gets `true` seeded — the absence is an incomplete entry from before the flag shipped, and without it the expert's launch-job documents strand in the job's `result/`. An explicit `false` is an operator's choice and stays untouched, exactly like a customized `workspace`.

This narrows the "existing entries are never overwritten" promise rather than breaking it: completing a mandatory list is not overwriting a choice. An operator who deliberately dropped one of the five sees it named in the report and can drop it again; there is no opt-out marker, and adding one would be config for a case nobody has had.

State one line per touched entry: `experts.<expert-key> (completed: <aspect>[, <aspect>…])` — a seeded commit flag is reported the same way (`completed: can_commit_in_repo`).

Load → modify → save uses `lazy_settings.load_tracked_section` so the local overlay never leaks into the tracked file. If any mutation happened, write the file with `_version: 1` preserved at the top of both `agent_models` and `experts`.

Outcome (one line per composed entry): `experts.<expert-key> (<state>)`.

The completion pass above replaces the counting this step used to do for `research` and `tech-writing`: those two are now appended, not tallied.

## Step 6: Check system experts

Report-only completeness check for the **system entries** from Step 3 — experts that sibling plugins register via their own install skills. This skill NEVER seeds or edits them (the owning plugin's install is the sole writer); it only detects gaps so a plugin update that shipped a new system expert doesn't go unnoticed.

### The system-expert registry

| Owning plugin | Expert keys it registers | Fix |
|---|---|---|
| `lazycortex-core` | `runtime.doctor` | `/lazy-core.install` |
| `lazycortex-review` | `review.doc_doctor` | `/lazy-review.install` |
| `lazycortex-specs` | `spec.coordinator` | `/lazy-spec.install` |
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
- For each seeded expert, confirm every aspect ref the class map assigns resolves: the class aspect (already proved by the Step 3 glob), `lazy-experts.discipline-aspect`, `lazy-experts.research-aspect`, and — for technical-class experts — `lazy-experts.tech-writing-aspect`, `lazy-experts.terms-aspect`, and `lazy-experts.structure-aspect` (all under `<installPath>/references/`), and `lazy-memory.persona-aspect` (under `~/.claude/plugins/cache/lazycortex/lazycortex-core/*/references/`).
- For each seeded expert, confirm its `agent` ref resolves to an existing file under `<installPath>/agents/` (i.e. `lazy-experts.<role>.md` exists). A missing agent file is a `verify-failed: agent-ref-unresolved <expert-key>` outcome.
- Report to the user:
  - Scope detected.
  - Plugin version + commit synced from (from `installed_plugins.json`).
  - Class set + whether it was `asked` or `derived` (Step 3).
  - The `agent_models` seed result: fold in the Step 4 primitive's report block (its `sot:` defaults path + per-key states). If the primitive returned `sot-missing` or `no-entries`, surface that line prominently.
  - Per-key outcome for `experts`. On a `game-dev` class set this includes `game.data-writer`, seeded by the class map's `data` row.
  - System-expert check result (Step 6): the `system-experts:` outcome plus one line per missing/unknown key.
  - One line per entry the Step 5 completion pass touched, naming the aspects appended: `experts.<expert-key> (completed: <aspect>[, <aspect>…])`.

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

- **Idempotent**: re-running this skill is safe. Entries are only added when absent; an existing entry keeps every field the operator owns, and the only thing a re-run changes on it is appending a mandatory cross-cutting aspect it lacks — so a second run right after the first changes nothing.
- **Class set is sticky once seeded**: with no domain-class entries (fresh project, or system experts only) the skill prompts for classes; once domain entries exist it derives the classes already present and completes their roles. To ADD a new class to an already-populated project, register one expert of that class by hand (or remove all domain entries and re-run to be re-prompted — system entries don't block the prompt).
- **Re-run after `/plugin update`**: `/plugin update` refreshes the plugin cache but does not re-sync settings. Re-run if `default-tiers.json` shipped new `lazycortex-experts:*` rows OR a new role agent shipped — Step 5 fills the missing entries the class map prescribes for the existing class set.
- **Scope independence**: project-scope installs do not affect global config.
- **Not daemon-gated**: experts and tiers are routing config used by interactive dispatch too, so this skill seeds them whether or not the project runs the daemon. The daemon only affects whether *routines* fire (registered by `lazy-core.install` and the routine-owning plugins).
- **Memory side-effect**: every seeded expert carries `lazycortex-core:lazy-memory.persona-aspect`, which lets the expert write to `.memory/<self>/` via `lazy-memory.write`. `lazy-core.install` ensures the `.memory/` directory exists. Removing the persona aspect from a seeded expert is supported (the expert just stops growing memory) — the install skill never re-adds it on re-run.
