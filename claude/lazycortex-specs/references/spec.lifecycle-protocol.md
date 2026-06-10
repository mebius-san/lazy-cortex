# Asset lifecycle protocol — per-file stages and gates

Asset progression is tracked at two levels that feed each other:

- **Per-file `spec_stage`** on every authored doc — author-level state of `design.md` / `plan.md` / `bug.md` / `docs/tech.md` / `docs/design.md`. Closed set: `empty | draft | approved | rejected | cancelled`.
- **Five flat gates** on the status folder-note — the asset's overall progress through `S0..S5`. Gates are flipped from per-file `spec_stage` (derived gates) or from external signals (human-signal gates).

The two layers share one mutator-per-layer: `spec.set-stage` for per-file stages, `spec.flip-gate` (driven by `gate-tick` for derived gates) for gates. No other code path mutates these fields.

## Part 1 — Per-file `spec_stage` (authored docs)

### Frontmatter

Every authored doc carries:

```yaml
spec_stage: draft        # empty | draft | approved | rejected | cancelled
tags:
  - spec/draft           # mirror of spec_stage value (see "Status mirror tag" below)
```

### Closed stage set

Exactly five values. The old `review`, `done`, and `wtr` are gone — "in review" is now `spec_stage: draft` + `review_active: true`; "accepted" is `approved`.

- `empty` — doc not needed right now (resolved for optional docs). No review.
- `draft` — content being written. Maps to `review_active: true` once opted into the loop, OR pre-review (authored but not yet submitted). No separate waiting-room state.
- `approved` — accepted: `review_active: false` AND `review_approved: true`. Approved-with-concerns collapses to `approved` (the `review_approved_with_concerns` flag stays readable on the doc for downstream consumers, but `spec_stage` is plain `approved`).
- `rejected` — review or implementer flagged the doc unworkable (a finalize-revert): a rejection callout sits in the body. **NOT terminal** — the doc returns to `draft` to re-open the loop.
- `cancelled` — doc abandoned. Terminal.

### Applies to

Authored docs that carry `spec_stage`: feature/change-level `design.md` and `plan.md`; bug-level `bug.md` and `plan.md`; product-level `docs/tech.md` and `docs/design.md`.

Does NOT carry `spec_stage`: the status folder-note (carries gates instead); container folder-notes (`docs/docs.md`, `features/features.md`, …).

### Mapping to lazycortex-review v4 flags

| `spec_stage` | lazycortex-review v4 flags |
|---|---|
| `empty` | no review opened on the doc |
| `draft` | `review_active: true` (in the loop), OR pre-review (authored, not yet submitted) |
| `approved` | `review_active: false` + `review_approved: true`; approved-with-concerns collapses here (`review_approved_with_concerns` stays readable) |
| `rejected` | finalize-revert; a rejection callout in the body |
| `cancelled` | abandoned, terminal |

### Transitions

Forward: `empty → draft → approved`.

`rejected` is reachable when a review or implementer rejects the doc; the only path out is back to `draft` (re-open). `cancelled` is reachable from any non-terminal stage.

`approved` and `cancelled` are terminal; `rejected` is a re-open marker, NOT terminal.

`cancelled` is refused on `design.md` and on `bug.md` (mandatory docs). `tech.md` and `plan.md` MAY be `cancelled` — a docs-only feature has no code, a no-code bug fix has no actionable plan. (Enforced by `spec.set-stage`.)

### Status mirror tag

Every doc carrying `spec_stage:` ALSO carries a hierarchical Obsidian tag mirroring the value:

```yaml
spec_stage: approved
tags:
  - spec/approved
```

The mirror is maintained in lock-step by `spec.set-stage` (the only writer of both fields). Backfill paths (`spec.sync-with-code`) call `spec.set-stage`, never raw-edit `spec_stage`. `spec.doctor` validates that the tag matches the field; a mismatch is a finding.

The tag enables Obsidian queries (`#spec` for all stage-bearing docs, `#spec/approved` for accepted only, etc.) without requiring Dataview to parse frontmatter values.

### The single mutator — `spec.set-stage`

`spec.set-stage <file-path> <new-stage>` is the ONLY primitive that changes a per-file stage. Every per-file stage change in the system goes through it; no skill raw-edits `spec_stage`. The skill:

1. Validates the file's role (`design` / `tech` / `plan` / `bug`) and path, and validates the requested stage against the closed set. Anything outside the set — including the removed `review` / `done` / `wtr` — is refused with a clear error.
2. Rewrites `spec_stage` in frontmatter, preserving all other keys and their order.
3. Updates the `spec/<stage>` tag in `tags:` in the same edit (strips the old `spec/*` entry, appends `spec/<new>`).
4. Appends one line to the nearest enclosing folder-note's `## History`: `- <YYYY-MM-DD> — spec.set-stage · <doc>.md spec_stage <old>→<new>` (substituting a passed author for `spec.set-stage`). For product-level authored docs under `docs/` the history line lands in the `docs/docs.md` operator folder-note (`## History` section appended if absent).

It does NOT advance the folder-note's gates — gate flips are the responsibility of `spec.flip-gate` / the `gate-tick` worker (see Part 2 below). The full skill contract lives at `${CLAUDE_PLUGIN_ROOT}/skills/spec.set-stage/SKILL.md`.

### Auto-promotion equivalents (worker-driven)

The `gate-tick` worker performs the same `spec_stage` mutation set as `spec.set-stage` (rewrite scalar + mirror tag + folder-note `## History` line + atomic commit) for two transitions it can derive without operator input:

- **`empty → draft`** at `_auto_open_plan_review` time. When the design-done cascade is about to open `plan.md` for review, `flip_gate` promotes `plan.md.spec_stage` from `empty` to `draft` BEFORE the `lazycortex-review start` subprocess. Reason: per § Mapping above, `draft` covers "review_active: true (in the loop)"; leaving the stage at `empty` while opt-in lands `review_active: true` would commit an intermediate state that contradicts the mapping. Idempotent: when plan is already `draft`, no mutation; out-of-band stages (`approved` / `cancelled` / `rejected`) are skipped defensively. Commit identity: `spec.flip-gate@bot.lazy-cortex`, subject `spec.flip-gate: plan.md spec_stage empty→draft on <asset>`.
- **`draft → approved`** at `gate-tick` Step 0. On every tick, before evaluating gate flips, the worker walks the asset's sibling authored docs (`design.md` / `bug.md` / `plan.md` / `tech.md`) and promotes each whose `review_result ∈ {approved, approved-with-concerns}` AND `spec_stage == draft`. The `draft` filter is strict — terminal stages (`approved` / `cancelled`) and operator-attention stages (`rejected` / `empty`) are skipped. When one or more docs are promoted, the worker emits one atomic commit under `spec.gate-tick@bot.lazy-cortex` covering every promoted sibling plus the folder-note history append, returns `{action: stage-promoted, docs: [...]}`, and skips gate evaluation for that tick (the next tick re-reads stages and gates flip naturally).

Both transitions are equivalents of `spec.set-stage`: same frontmatter shape, same mirror-tag maintenance, same `## History` line format (substituting `spec.flip-gate` / `spec.gate-tick` for the author). `spec.doctor`'s field-vs-tag consistency checks cannot tell auto-promoted docs from interactively set ones.

## Part 2 — Gates (asset progression)

### Frontmatter

The status folder-note carries five gate booleans and one overlay flag:

```yaml
spec_design_done: false
spec_plan_done: false
spec_develop_done: false
spec_tests_passing: false
spec_released: false
spec_cancelled: false
```

There is no `gates:` dict, no `stage:` on the folder-note, no `awaits_human:`, and no `## Workflow` section — the gate booleans are the entire model.

### Linear map S0..S5

The gates are a strict ladder. Each gate requires the one before it to be true:

| State | Meaning | True gates |
|---|---|---|
| S0 | new asset | (none) |
| S1 | design done | `spec_design_done` |
| S2 | plan done | + `spec_plan_done` |
| S3 | develop done | + `spec_develop_done` |
| S4 | tests passing | + `spec_tests_passing` |
| S5 | released | + `spec_released` |

### Preconditions

A false→true flip is allowed only when the gate's precondition holds. A refused flip mutates no files.

| Gate | Precondition |
|---|---|
| `spec_design_done` | feature/change: `design.md.spec_stage ∈ {approved, cancelled}`; bug: `bug.md.spec_stage ∈ {approved, cancelled}` |
| `spec_plan_done` | `spec_design_done` true AND `plan.md.spec_stage ∈ {approved, cancelled}` |
| `spec_develop_done` | `spec_plan_done` true |
| `spec_tests_passing` | `spec_develop_done` true |
| `spec_released` | `spec_tests_passing` true |

`spec_cancelled: true` freezes all gates — no flips in either direction while the asset is cancelled. To regress a gate (turn it back off) use `--off`; this skips the precondition check (turning a gate off is always allowed) but is still refused while the asset is cancelled. `--off` is a rare manual operation.

### Derived vs human-signal gates

Each gate is one of two kinds, which determines how it gets flipped:

- **Derived** = `{spec_design_done, spec_plan_done}`. The precondition is fully derivable from sibling per-file approval state, so the `gate-tick` worker auto-flips them (via `flip-gate --auto`) the moment the precondition holds. No human action needed.
- **Human-signal** = `{spec_develop_done, spec_tests_passing, spec_released}`. The precondition (the previous gate being true) does not by itself prove the work is done — it needs an external signal: a deploy, a green test report, a branch merge. The `gate-tick` worker cannot derive these; it drops a `> [!ready]` callout announcing the gate is ready to flip. The actual flip comes from the operator, an LLM, `spec.sync-with-code`, or `spec.finalize-branch`.

### The single mutation channel — `spec.flip-gate`

`bin/flip_gate.py` (driven by the `/spec.flip-gate` skill) is the **only** writer of gate booleans. On a flip it:

1. Reads the folder-note frontmatter + sibling per-file `spec_stage` values.
2. Checks the gate's precondition. On mismatch it refuses with a message and produces no side effects.
3. Rewrites the gate boolean in frontmatter.
4. Appends a callout to the `## Gates` section: `> [!gate] spec_<gate> — flipped <date> (<reason>)`, carrying an `auto:` annotation when invoked with `--auto`.
5. Appends a line to `## History`.
6. **Atomic git commit of the folder-note edit** under `spec.flip-gate@bot.lazy-cortex` (subject `spec.flip-gate: <gate> → <true|false> on <asset>`). Without this commit the daemon's next iteration trips its dirty-tree-skip guard and silently halts every routine on the asset. The commit happens BEFORE the post-flip cascade so any follow-up subprocess sees a clean tree. Defensive skip when the asset is not inside a git repository (test-fixture path) — the file write remains but the commit step is no-op.
7. Writes a run log under `.logs/claude/spec.flip-gate/`.
8. **Post-flip cascade** — after a derived gate flips forward (not `--off`), the primitive opens lazy-review on the next document in the chain (e.g. after `spec_design_done` flips, `/lazy-review.start <plan.md>` is invoked iff `plan.md.spec_stage ∈ {empty, draft}` and `review_active != true`). `spec_plan_done` has no follow-up document (next gate is human-signal). For bug-category assets the same logic applies (design_done flips from `bug.md`, follow-up is still `plan.md`).

   **Pre-subprocess stage promotion.** When the cascade target is `plan.md` and its current `spec_stage` is `empty`, `flip_gate` promotes it to `draft` BEFORE invoking the lazy-review subprocess (atomic commit, separate from the gate-flip commit). See § Auto-promotion equivalents above for the contract. The order is strict: stage flip first, then opt-in subprocess. Reversing the order would commit `review_active: true` alongside `spec_stage: empty`, contradicting the Part 1 mapping.

CLI: `lazycortex-specs flip-gate <asset_dir> <gate> [--off] [--auto] [--reason TEXT]`.

### The `gate-tick` md-scan worker

`bin/gate_tick.py` is a pure script — zero Claude calls, no checkboxes ever. It is dispatched per matched status folder-note by the `spec.gate-tick` `md-scan` routine. For each asset it advances state in two passes:

**Step 0 — per-file stage promotion.** Before evaluating any gate, the worker walks the asset's sibling authored docs (`design.md` / `bug.md` / `plan.md` / `tech.md`) and promotes each whose `review_result ∈ {approved, approved-with-concerns}` AND `spec_stage == draft` to `spec_stage: approved`. Mutations are equivalent to `spec.set-stage` (scalar + mirror tag + folder-note `## History`); commit identity is `spec.gate-tick@bot.lazy-cortex`. When one or more docs are promoted, the worker emits one atomic commit covering every promoted sibling plus the folder-note append, returns `{action: stage-promoted, docs: [...]}`, and skips gate evaluation for that tick. The next tick re-reads stages and the gate-flip path picks up the newly-approved sibling. See § Auto-promotion equivalents in Part 1 for the full contract.

**Step 1 — gate advancement.** Find the lowest gate that is currently false and whose precondition holds, then advance the asset one notch:

- **Next gate is derived** → auto-flip it in-process via `flip_gate.flip_gate(..., auto=True)` (the worker imports the sibling primitive and calls it directly so the callout / history / log side effects are produced exactly once by their one owner; `flip_gate`'s atomic commit obligation, § single mutation channel step 6, applies).
- **Next gate is human-signal** → append a `> [!ready]` callout to `## Gates` telling the operator how to flip it by hand, then **atomic commit** of the folder-note under `spec.gate-tick@bot.lazy-cortex` (subject `spec.gate-tick: drop readiness callout for <gate> on <asset>`). Idempotent — when the callout is already present, no mutation and no commit. Without the commit the daemon's next iteration would trip its dirty-tree-skip guard.
- **A previously-dropped `[!ready]` whose precondition has since regressed** → rewrite it in place as a `> [!info] readiness withdrawn — <gate> precondition no longer met` callout, then **atomic commit** of the folder-note under `spec.gate-tick@bot.lazy-cortex` (subject `spec.gate-tick: withdraw readiness for <gate> on <asset>`). Same dirty-tree-guard rationale.

CLI: `lazycortex-specs gate-tick <asset_note> [--today YYYY-MM-DD]`.

## Cross-layer chain — design.md approved → spec_design_done → review opens on plan.md

```
design.md одобрен в lazy-review (review_result: approved)
  → gate-tick Step 0: spec.gate-tick promote design.md spec_stage draft→approved
       (worker-owned mutation: scalar + spec/approved mirror tag + folder-note ## History,
        atomic commit under spec.gate-tick@bot.lazy-cortex; equivalent to spec.set-stage)
  → gate-tick Step 1: precondition spec_design_done выполнен (sibling design.md.spec_stage == approved)
  → flip_gate.py --auto: spec_design_done: true (callout in ## Gates, line in ## History)
       (atomic commit under spec.flip-gate@bot.lazy-cortex — single mutation channel step 6)
  → flip_gate.py post-flip cascade:
       1) plan.md spec_stage empty→draft (atomic commit; promote BEFORE subprocess so
          opt-in lands on a doc whose stage already matches the review_active mapping)
       2) /lazy-review.start <plan.md> subprocess (atomic commit under operator)
  → developer-expert pulls plan.md as source; design.md ships into context/ via spec_source_docs
  → plan.md approved → same gate-tick Step 0 + Step 1 cycle promotes plan.md → spec_plan_done
  → next gates are human-signal — chain stops; operator / sync-with-code / finalize-branch flips them explicitly
```

Полностью детерминированная цепочка от первого approve до S2 без операторских шагов в середине, кроме approve в каждом отдельном ревью. Каждая mutation атомарна и коммитится сразу — daemon's dirty-tree-skip guard никогда не срабатывает на промежуточных состояниях cascade.
