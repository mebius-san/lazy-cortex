---
name: lazy-experts.audit
description: "Run when the operator asks whether this project's expert composition is still sound, or when dispatching an expert fails in a way that smells like config — a job aborts saying the agent ref does not resolve, an expert writes to a contract it should not have, a role the class map prescribes turns out to have no entry. Delegated from `lazy-core.doctor` Phase 3. Read-only check of the plugin's shipped agents and aspect references against the `experts` entries in `.claude/lazy.settings.json`; reports PASS / WARN / FAIL / INFO and never writes — the fix is `/lazy-experts.install`."
allowed-tools: Read, Glob, Grep, Write, Bash(python3 *), Bash("${LAZYCORTEX_PYTHON:-python3}" *), Bash(mkdir -p *), Bash(date *), Bash(git rev-parse*), Bash(lazycortex-core *), Agent
---
# lazy-experts.audit

Verify that what `/lazy-experts.install` promised is still true: the class map's roles all resolve to shipped agent files, the aspect references the map assigns all exist, and every seeded `experts` entry still points at an agent and a set of aspects this plugin actually ships. Read-only — it collects findings and names the fix per finding; it never edits `lazy.settings.json`, never seeds an entry, and never asks a question.

## Execution discipline (MANDATORY — read before any action)

This skill has 6 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — Resolve plugin root and settings`
   - `Phase 2 — Shipped surface`
   - `Phase 3 — Seeded expert entries`
   - `Phase 4 — Render report`
   - `Phase 5 — Log the run`
   - `Report`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". Each check inside a phase ends with one of `PASS` / `WARN` / `FAIL` / `INFO`.
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above with its outcome word.

## Phase 1 — Resolve plugin root and settings

Two paths to resolve before anything is checked.

- **Plugin root** — the `installPath` field for `lazycortex-experts@lazycortex` in `~/.claude/plugins/installed_plugins.json`. When the repo at hand authors this plugin, `claude/lazycortex-experts/` is the root instead and wins, so the audit judges the sources being edited rather than a stale cached copy. Neither present → `FAIL plugin-root-unresolved`; stop, no further phase runs.
- **Settings** — `<repo-root>/.claude/lazy.settings.json` (root from `git rev-parse --show-toplevel`, cwd when not in a git repo), falling back to `~/.claude/lazy.settings.json` when the plugin is enabled only at user scope. Resolve the scope with `Bash(lazycortex-core detect-scope lazycortex-experts@lazycortex)`. File absent, or its `experts` section absent or holding nothing besides `_version` → report `INFO no-experts-configured` and run Phase 2 alone; Phase 3 states `skipped (no entries)`.

Read the `experts` section through `lazy_settings.load_tracked_section` so a local overlay is never mistaken for tracked config.

Outcome: `resolved (root=<path>, settings=<path>)` / `FAIL plugin-root-unresolved` / `INFO no-experts-configured`.

## Phase 2 — Shipped surface

The class map lives in `/lazy-experts.install` Step 5 and is this phase's reference — read it there rather than restating it, so the audit cannot drift from the seeder it verifies. Two checks over the plugin root resolved in Phase 1.

**S1 — every class-map role resolves to an agent file.** For each role the map assigns to either class kind, resolve it through the map's role→agent table (three roles do not share their agent's basename) and confirm `<root>/agents/lazy-experts.<agent>.md` exists.

- Missing file → `FAIL agent-missing: <role> → lazy-experts.<agent>.md`. Every expert the map would seed for that role dispatches to nothing.
- All present → `PASS <N> roles resolve`.

**S2 — every aspect the class map assigns resolves to a reference file.** Confirm `<root>/references/lazy-experts.<class>-aspect.md` exists for each class the map names, and `<root>/references/lazy-experts.<aspect>-aspect.md` for each cross-cutting aspect either row assigns. The persona aspect the map also assigns belongs to `lazycortex-core` — confirm it under that plugin's own cached `references/`, and state `INFO persona-aspect-unresolved` rather than `FAIL` when `lazycortex-core` is not installed at this scope.

- Missing file → `FAIL aspect-missing: lazy-experts.<name>-aspect.md`.
- All present → `PASS <N> aspects resolve`.

Outcome: `scanned (<N> checks)`.

## Phase 3 — Seeded expert entries

Partition the `experts` section exactly as `/lazy-experts.install` Step 3 does: a **domain entry** carries at least one `lazycortex-experts:lazy-experts.<class>-aspect` ref that is not one of the cross-cutting aspects; everything else is a **system entry** owned by a sibling plugin. This phase judges domain entries only — a system entry is another plugin's business and is listed as `INFO system-entry: <expert-key>` without being checked.

For each domain entry, derive its class kind (technical or fiction) from the domain aspect it carries, then:

**C1 — the `agent` ref resolves.** A ref of the form `lazycortex-experts:lazy-experts.<name>` must have `<root>/agents/lazy-experts.<name>.md` on disk. Missing → `FAIL agent-ref-unresolved: <expert-key> → <ref>`. A ref naming another plugin is out of scope — state `INFO foreign-agent: <expert-key> → <ref>`.

**C2 — every `lazycortex-experts:` aspect ref resolves.** Each such ref must have its file under `<root>/references/`. Missing → `FAIL aspect-ref-unresolved: <expert-key> → <ref>`. Refs naming another plugin are that plugin's to verify; skip them silently.

**C3 — the mandatory cross-cutting aspects are present for the entry's class kind.** Technical entries carry `discipline`, `research`, `tech-writing`, `terms`, and `structure`; fiction entries carry `discipline` and `research` only, and carrying any of the other three is itself the finding — the class map states plainly why those three never compose onto fiction.

- Technical entry missing one or more → `WARN aspects-incomplete: <expert-key> (missing: <names>)`.
- Fiction entry carrying `tech-writing`, `terms`, or `structure` → `WARN aspect-not-for-fiction: <expert-key> (<names>)`.
- Both satisfied → `PASS`.

**C4 — the install-managed keys are present on the roles that need them.** A writing-role entry with no `can_commit_in_repo` key at all, or one of the four isolated roles with no `workspace` key at all, is an entry from before those keys shipped — the role lists are in `/lazy-experts.install` Step 5. An explicit `false` or an explicit `"main"` is the operator's choice and is never a finding; only total absence is.

- Absent → `WARN key-absent: <expert-key> (<key>)`.
- Present in either direction → `PASS`.

Outcome: `audited (<N> domain entries)` / `skipped (no entries)`.

## Phase 4 — Render report

Print one bullet per finding grouped by severity, `FAIL` first, then `WARN`, then `INFO`; drop the `PASS` bullets and carry them as counts. Every `FAIL` and `WARN` bullet names its fix — for every finding this skill raises the fix is `/lazy-experts.install` (it seeds a missing entry, appends a missing mandatory aspect, and backfills an absent install-managed key), except `agent-missing` and `aspect-missing`, whose fix is `/plugin update lazycortex-experts@lazycortex` because the shipped tree itself is incomplete. Close with the summary line `audit: <LEVEL> (<N> findings)`, where `<LEVEL>` is the worst severity seen.

Nothing is written to `lazy.settings.json` in this phase or any other.

Outcome: `rendered`.

## Phase 5 — Log the run

Log to `./.logs/claude/lazy-experts.audit/YYYY-MM-DD_HH-MM-SS.md` per `lazy-log.logging`. Required frontmatter: `git_sha`, `git_branch`, `date` (UTC), `input`.

Use two separate steps: `Bash(mkdir -p ./.logs/claude/lazy-experts.audit)` then the `Write` tool. Never chain.

Outcome: `logged: <path>`.

## Report

One line per task in the canonical list above, with its outcome word, followed by the summary line from Phase 4.

## Failure modes

- **`/lazy-experts.audit` aborts: "plugin-root-unresolved"** — `lazycortex-experts@lazycortex` has no `installPath` in `~/.claude/plugins/installed_plugins.json` and the repo does not author the plugin → run `/plugin install lazycortex/lazycortex-experts`, then re-run.
- **The audit reports `INFO no-experts-configured`** — the project has no `experts` entries yet, so only the shipped surface was checked → run `/lazy-experts.install` to seed the class set.
- **The audit reports `FAIL agent-missing` or `FAIL aspect-missing`** — the plugin cache is incomplete, not the settings → run `/plugin update lazycortex-experts@lazycortex`, then re-run.
- **The audit reports `FAIL agent-ref-unresolved`** — an entry points at an agent basename this plugin no longer ships, usually a hand-edited `agent` field → correct the ref in `lazy.settings.json`, or delete the entry and re-run `/lazy-experts.install` to reseed it from the class map.
