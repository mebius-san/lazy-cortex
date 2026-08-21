---
name: lazy-spec.lifecycle-protocol
version: 5
description: Asset progression contract — per-file spec_stage on authored docs, the recorded `spec_asset_type` / `spec_tools` facts and the five flat S0..S5 gates on the status folder-note, and the shapes the launch-checkbox ladder and change cascade write. The WORKFLOW layer (what closes a gate, which checkbox exists, what a label dispatches, how a cascade is ordered) belongs to the type and tool playbooks, applied by `spec.coordinator` — this protocol documents the wire shapes and the primitives still living in code, never a workflow rule and never a script-side decision.
---
# Asset lifecycle protocol — per-file stages and gates

Asset progression is tracked at two levels that feed each other:

- **Per-file `spec_stage`** on every authored doc — author-level state of `design.md` / `architecture.md` / `code-plan.md` / `test-plan.md` / `bug.md` / product-level `tech.md` / `design.md`. Closed set: `empty | draft | approved | rejected | cancelled`. The append-only report journals (`code-report.md` / `test-report.md` / `data-report.md` / `docs-report.md`), and the opt-in `decisions.md` registry, carry no `spec_stage` — they sit outside this whole layer (see § Applies to below).
- **Five flat gates** on the status folder-note — the asset's overall progress through `S0..S5`.

**Who decides, who executes.** `spec.coordinator` (agent + expert record; its law is `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.coordination-playbook.md`) is the SOLE judge of every sequencing decision this protocol used to hardcode — which sibling doc to promote, which gate's precondition currently holds, which launch checkbox to hang or dispatch, whether and how a change cascades. It acts only through a small set of primitives that remain script-level and unconditional on call: `lazy-spec.set-stage` (per-file stage), `lazy-spec.flip-gate` (gate booleans — refuses only a cancelled asset, no precondition check of its own), `lazy-spec.gate-tick`'s worker (a pure poller now, no decisions), and the `note-set-key` / `note-check` verbs (`${CLAUDE_PLUGIN_ROOT}/skills/lazy-spec.doctor/SKILL.md`'s sibling primitives, documented in `${CLAUDE_PLUGIN_ROOT}/bin/note_ops.py`). Anything below that reads like a rule the SYSTEM enforces is, since the coordinator's arrival, a rule the COORDINATOR follows, declared by the asset's type playbook (`asset_types.<name>.playbook`) and the playbooks of the tools in its `spec_tools` (`tool_types.<name>.playbook`) — marked "playbook, not code" wherever the distinction matters. The shapes (frontmatter keys, callout formats, the launch-marker record) are still exact contracts; the workflow that decides when to apply them lives in the playbooks, never here.

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
- `rejected` — review or developer flagged the doc unworkable (a finalize-revert): a rejection callout sits in the body. **NOT terminal** — the doc returns to `draft` to re-open the loop.
- `cancelled` — doc abandoned. Terminal.

### Applies to

Documents whose `spec_doc_type` is declared with `stages: true` (the shipped types with the flag set: `design`, `system-design`, `architecture`, `code-plan`, `test-plan`, `bug`, `system-tech`). Which document kinds those are is a property of the declaration, not of a filename — see `lazy-spec.layout-protocol.md` § Document type. Which of them a given asset actually carries is the type playbook's declaration, not this file's: a plan document exists exactly for a tool whose `tool_types.<name>` record names a `plan_doc`, and its absence is a declared state, not a gap `lazy-spec.doctor` flags.

Does NOT carry `spec_stage` — every type declared `stages: false`, plus the untyped notes: the status folder-note (carries gates instead); container folder-notes (`<product>.md`, `features/features.md`, …); the append-only report journals (`code-report.md` / `test-report.md` / `data-report.md` / `docs-report.md`, and any other `report_doc` a tool declares) — they are written during execution, never approved into a stage, and carry no lifecycle state of their own; the opt-in `decisions.md` registry (product-level or asset-level) — it is an append-only registry written only by the `decide` primitive, never opted into review, and carries no lifecycle state of its own. They sit outside both layers of this protocol: no per-file stage, no role in any gate precondition.

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

`rejected` is reachable when a review or developer rejects the doc; the only path out is back to `draft` (re-open). `cancelled` is reachable from any non-terminal stage.

`approved` and `cancelled` are terminal; `rejected` is a re-open marker, NOT terminal.

`cancelled` is refused on `design.md` (asset-level and system-level alike), on `bug.md`, and on `architecture.md` — an asset's defining documents are abandoned as a whole through `spec_cancelled`, never one at a time, and a system's design is its defining document too. `tech.md` (type `system-tech`) and the plan documents (`code-plan.md`, `test-plan.md`) MAY be `cancelled` — a plan whose work turned out not to be needed is walked back without abandoning the asset. (Enforced by `lazy-spec.set-stage`.) Report journals carry no `spec_stage` at all (see § Applies to), so cancellability is not a question that applies to them.

### Status mirror tag

Every doc carrying `spec_stage:` ALSO carries a hierarchical Obsidian tag mirroring the value:

```yaml
spec_stage: approved
tags:
  - spec/approved
```

The mirror is maintained in lock-step by `lazy-spec.set-stage` (the only writer of both fields). Backfill paths (`lazy-spec.sync-with-code`) call `lazy-spec.set-stage`, never raw-edit `spec_stage`. `lazy-spec.doctor` validates that the tag matches the field; a mismatch is a finding.

The tag enables Obsidian queries (`#spec` for all stage-bearing docs, `#spec/approved` for accepted only, etc.) without requiring Dataview to parse frontmatter values.

### The single mutator — `lazy-spec.set-stage`

`lazy-spec.set-stage <file-path> <new-stage>` is the ONLY primitive that changes a per-file stage. Every per-file stage change in the system goes through it; no skill, worker, or coordinator call raw-edits `spec_stage`. The skill:

1. Validates the document by its declared type, never by its path or basename: it refuses a document carrying no `spec_doc_type`, refuses a type no declaration covers in the product's scope, and refuses a type declared `stages: false` (which is what excludes the status folder-note, every `report_doc` type a tool declares, and the `decisions` registry — none of them carries an independently-settable stage). It then validates the requested stage against the closed set; anything outside it — including the removed `review` / `done` / `wtr` — is refused with a clear error.
2. Rewrites `spec_stage` in frontmatter, preserving all other keys and their order.
3. Updates the `spec/<stage>` tag in `tags:` in the same edit (strips the old `spec/*` entry, appends `spec/<new>`).
4. Appends one line to the nearest enclosing status folder-note's `# History`: `- <YYYY-MM-DD> — lazy-spec.set-stage · <doc>.md spec_stage <old>→<new>` (substituting a passed author for `lazy-spec.set-stage`). Product-level authored docs (`design.md` / `tech.md` at the product root) have no status folder-note in scope — the product folder-note is operator-zone — so the history append is skipped for them.

It does NOT advance the folder-note's gates — deciding whether a gate is ready to move, and calling `lazy-spec.flip-gate` to move it, is `spec.coordinator`'s call (§ Part 2 below). The full skill contract lives at `${CLAUDE_PLUGIN_ROOT}/skills/lazy-spec.set-stage/SKILL.md`.

### Stage promotion — a coordinator decision, executed through this same primitive

**Playbook, not code.** Nothing in this repo auto-promotes a stage anymore. Per `lazy-spec.coordination-playbook.md` Chapter 4 ("Stage promotion"), the coordinator itself walks the asset's sibling authored docs on every wake, before evaluating any gate, and calls `lazy-spec.set-stage <doc> approved` on each one whose review just finalized approved (`review_result ∈ {approved, approved-with-concerns}`) while its `spec_stage` still reads `draft`. This is the exact same mutation `lazy-spec.set-stage` always performed (scalar + mirror tag + folder-note `# History` line), simply invoked by the coordinator through the ordinary primitive rather than by a dedicated worker step. There is no longer a separate "auto-promotion" code path, and no separate `empty → draft` pre-review promotion tied to a gate flip's own side effect — opening review on a freshly-authored plan document is itself now a coordinator-dispatched launch-checkbox job (§ Part 3), not something a gate flip triggers as a cascade.

## Part 2 — Gates (asset progression)

### Frontmatter

The status folder-note carries the asset's two recorded facts, five gate booleans, and one overlay flag:

```yaml
spec_asset_type: feature                       # the asset's type; `unknown` is the sentinel, never a guess
spec_tools: ["code", "test"]                   # absent = not determined; [] = determined to need none
spec_design_done: false
spec_plan_done: false
spec_develop_done: false
spec_tests_passing: false
spec_released: false
spec_cancelled: false
spec_state: draft                              # derived; the coordinator's, read by the iconize registry
```

There is no `gates:` dict, no `stage:` on the folder-note, no `awaits_human:`, and no `## Workflow` section — these keys are the entire model.

**`spec_state` is derived, not recorded.** It is the one key here nothing downstream reasons with: the coordinator writes it on the same wake that rebuilds `# Status brief`, and its only consumer is the iconize registry, which paints the asset folder from it. Legal values are `draft`, `in-review`, `implementation`, `testing`, `waits-operator`, `blocked`, `done` (`spec_keys.py::AssetState`); `spec_halted` and `spec_cancelled` paint over it from their own keys rather than taking a value of their own. Two of the values are not derivable from this note at all — `in-review` lives as `review_active` on a sibling document, and `implementation` / `testing` track a job in the gitignored runtime sidecar — which is why the key exists instead of a matcher computing the state itself. A gate flip never writes it as a side effect; the coordinator sets it, exactly like every other key it owns.

**`spec_asset_type` is a recorded fact, not an inference.** It names one type declared under `products[<key>].asset_types` (over the shipped defaults in `references/lazy-spec.asset-types.json`), and it is what resolves the asset's type playbook. The sentinel `unknown` — and an absent key, which reads the same — means the type has not been determined yet; nothing downstream guesses it. The asset's FOLDER is a place, not a fact: where the operator filed the thing takes no part in resolving what it is, and a legally-typed asset may sit anywhere in the catalog, nested inside another asset included.

**The asset's boundary is its status folder-note** — the folder whose folder-note carries `spec_role: status`. A nested asset is its own asset with its own status note and its own gates, never a part of the asset it sits inside.

**`spec_tools` distinguishes three states, and the difference is load-bearing.** An absent key means the tool set has not been determined; an empty list means it HAS been determined and the answer is "no tool at all"; a non-empty list names the tools whose playbooks (`tool_types.<name>.playbook`) govern the asset's implementation half. WHEN the list is written, and from which source, is the type playbook's declaration — the coordinator writes it through `note-set-key` like every other frontmatter key it owns.

**Cross-asset tokens are paths relative to the product's `spec_path`.** Both `spec_targets` (Part 4) and `spec_depends_on` carry the same token shape: a path from `spec_path` down to the asset's own folder, so a nested asset is addressed by its full path — never by a bare slug, and never by a folder it does not actually sit under.

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

The ladder itself is unchanged — this is still the shape a healthy asset's gate state must respect, and `lazy-spec.doctor`'s precedence check (Part 2-adjacent, its own SKILL.md) still flags a later gate true while an earlier one is false. What changed is who enforces the ORDER of flips at flip time: nobody. `lazy-spec.flip-gate` flips whichever gate it is called on, unconditionally, and trusts the coordinator's own reasoning (below) to have called it in the right order.

### Gate readiness (playbook, not code)

**No readiness rule lives in this file.** What each gate closes on is declared by the asset's own playbooks, and this protocol describes only the mechanism of the booleans and the S0..S5 order above. `spec_design_done` and `spec_plan_done` are the type playbook's subject — what the type's defining documents are and which of them must be approved is a property of the type, not of the ladder. `spec_develop_done` is an AND over every NON-`test` tool in `spec_tools`, each closing its own contribution per its own tool playbook; an asset whose `spec_tools` is an empty determination has an empty AND and is free of the gate by that determination. `spec_tests_passing` is the `test` tool's subject when that tool is in `spec_tools`, and free by the same absence rule when it is not. `spec_released` closes on an external release signal (a deploy, a merge, a branch finalize).

`lazy-spec.flip-gate` reads none of this — it flips the named gate on call, full stop, except that a cancelled asset refuses every flip regardless of direction. `lazy-spec.doctor` still validates the coupling (a gate reading true while the state its playbook names has not been reached is a doctor finding, per its Agent D check); the playbooks are its reference for what "ready" means, exactly as they are the coordinator's.

`spec_cancelled: true` freezes all gates — `lazy-spec.flip-gate` refuses every flip, forward or `--off`, while the asset is cancelled; this is the one refusal the primitive still enforces on its own, because it is the asset's own terminal state, not a sequencing precondition. An operator or the coordinator invoking `--off` by hand needs no precondition — turning a gate off has never needed one — but is still refused while cancelled.

### Derived vs human-signal gates — vocabulary, not enforcement

Each gate is still one of two kinds, a distinction the coordinator's own reasoning (and `lazy-spec.doctor`) still uses, even though no script branches on it anymore:

- **Derived** = `{spec_design_done, spec_plan_done}`. Readiness is fully derivable from sibling per-file approval state — the coordinator flips these the moment the type playbook's own condition holds, no operator input needed.
- **Human-signal** = `{spec_develop_done, spec_tests_passing, spec_released}`. Readiness needs an external signal the coordinator cannot derive from doc state alone — an accepted report, a green test run, a merge. The coordinator flips these from that signal, per the tool playbooks. **Decomposer carve-out** — on a tool-free decomposer asset (`lazy-spec.coordination-playbook.md` Chapter 10, an asset whose own "implementation" is bringing its `spec_depends_on` children to completion), `spec_develop_done` and `spec_tests_passing` stop being human-signal and become fully derivable: an AND over every named child's own copy of the same gate, auto-flipped by the coordinator the instant it holds, with no implementation or testing job ever dispatched for the decomposer itself.

### The single mutation channel — `lazy-spec.flip-gate`

`bin/flip_gate.py` (driven by the `/lazy-spec.flip-gate` skill, and called directly by `spec.coordinator` through the `lazycortex-specs flip-gate` CLI verb) is the **only** writer of gate booleans. The flip is unconditional on call:

1. Reads the folder-note frontmatter.
2. Refuses only when the asset is cancelled (`spec_cancelled: true`) — no other precondition check.
3. Rewrites the gate boolean in frontmatter.
4. Appends a callout to the `# Gates` section: `> [!gate] spec_<gate> — flipped <date> (<reason>)`, carrying an `auto:` annotation when invoked with `--auto`.
5. Appends a line to `# History`.
6. **Atomic git commit of the folder-note edit** under `lazy-spec.flip-gate@bot.invalid` (subject `lazy-spec.flip-gate: <gate> → <true|false> on <asset>`). Without this commit the daemon's next iteration trips its dirty-tree-skip guard and silently halts every routine on the asset. Defensive skip when the asset is not inside a git repository (test-fixture path) — the file write remains but the commit step is no-op.
7. Writes a run log under `.logs/claude/lazy-spec.flip-gate/`.

There is no post-flip cascade anymore — a forward flip of `spec_design_done` does not itself open review on a plan document. Opening that review is now a coordinator decision executed as an ordinary launch-checkbox dispatch (§ Part 3), ordered by the playbooks, not a side effect wired into the flip primitive.

CLI: `lazycortex-specs flip-gate <asset_dir> <gate> [--off] [--auto] [--reason TEXT]`.

### The `gate-tick` md-scan worker — a pure poller, no decisions

`bin/gate_tick.py` is dispatched per matched status folder-note by the `lazy-spec.gate-tick` `md-scan` routine, same as before. It performs exactly two concerns now, both mechanical:

1. **Active-job polling.** An asset whose runtime sidecar tracks an `active_job` has that job bundle's terminal marker (`DONE` / `DEAD` / `CANCELLED`, read file-wise from the `lazycortex-core` job-runtime layout, never imported cross-plugin) checked before anything else. Every marker clears the tracked job and raises `pending_wake: job-done` in its place — both sidecar writes, so that half costs no commit. `DONE` and `CANCELLED` then log a `# History` line each. `DEAD` sets `spec_halted: true` and appends a persistent `[!failure]` callout to `# Gates` — un-halting is a manual operator act, out of scope for this worker.

**This worker opens no review.** Opening review on any freshly-written document, a job's report included, is a `lazy-review.submit` call made by the coordinator on the `job-done` wake this very pass raises (`lazy-spec.coordination-playbook.md` Chapter 6) — never a follow-up wired into the poller.
2. **Structural note-check.** `note_ops.note_check`'s violations (an unrecognized or mistyped frontmatter key, a missing or misordered required section) are folded into the tick's own result — read-only; repairing what it finds is the coordinator's job, through its pen and `note-set-key`, never this worker's.

Everything this worker used to decide — sibling-doc stage promotion, gate readiness, the launch-checkbox ladder, downward reconciliation, change-cascade dispatch — is gone from this file entirely; it lives in `lazy-spec.coordination-playbook.md`, executed by `spec.coordinator`. A no-op tick (no terminal marker yet, note structurally clean) returns `{"action": "noop"}`.

CLI: `lazycortex-specs gate-tick <asset_note> [--today YYYY-MM-DD]`.

## Part 3 — Launch checkboxes (operator-triggered dispatch)

A layer on top of the gates: checkbox blocks the coordinator renders, reconciles, and dispatches in `# Gates`, letting the operator queue the next unit of work with a single tick. **This section documents the WIRE shape only — the frontmatter keys, the runtime job marker, and the checkbox block's markdown shape.** Which labels exist, when each appears, when it comes down, and what a tick dispatches is declared by the asset's type and tool playbooks and applied by the coordinator (`lazy-spec.coordination-playbook.md` Chapter 5) — no script hangs, removes, or dispatches a checkbox anymore.

### Frontmatter and the job marker

Two additional frontmatter keys:

```yaml
spec_halted: true                                              # absent by default; only present once an active job dies
spec_draft: true                                                # present true from asset creation; cleared (false) once "Publish" is ticked
```

`spec_draft` is a negative gate: absent or `false` means the asset is ready for a downstream repo to pick up (read by another repo's own `lazy-spec.upstream-tick` when this repo happens to be its configured source). No frontmatter migration is required for existing notes — the specs cycle this replacement lands in is still unpublished, so no downstream consumer holds data under the old `spec_handoff_ready` key. On a spec-only-mode product (Chapter 17 of the playbook), the coordinator clears it once `design.md` is approved AND the operator gives an explicit word. On a full-mode asset, the `Publish` checkbox (below) is the clearing trigger — the coordinator hangs it once the asset's terminal gate closes, and an operator tick clears the flag; there is no automatic clearing (approved is not the same as ready to hand off, and the operator may want related work finished first).

The dispatched job itself is NOT frontmatter. It lives in the gitignored runtime sidecar at `<repo>/.runtime/lazy-specs.jobs.json`, keyed by the note's repo-relative path, under the `active_job` field:

```json
{"checkbox": "Start implementation", "expert": "claude-plugin.developer", "job_id": "20260101-abcd"}
```

Writes go through `lazycortex-specs mark-job <asset_note> active <json>` (or `--clear`), which validates the object's SHAPE and nothing else: exactly the three keys `checkbox` / `expert` / `job_id`, each a non-empty string. The label's spelling is not checked against any list — the vocabulary belongs to the playbooks, not to this primitive. The coordinator writes the marker as part of dispatching the job it tracks; `lazy-spec.gate-tick`'s active-job polling pass (Part 2 above) is the one piece of code that clears it. Because the marker is runtime state rather than document content, neither write costs a commit, and an operator hand-editing the folder-note cannot lose a live job's record. Read it back through `note-check`, whose result carries the note's `job_markers` entry; a `spec_active_job` key found in frontmatter is a regression, not a source.

### The label set is open

There is no fixed list of labels in this protocol, and no primitive holds one. The VOCABULARY — which labels exist on an asset, what each one's appearance condition is, and what a tick dispatches — is declared by the asset's type playbook and by the playbooks of the tools in its `spec_tools`; the coordinator reconciles exactly that declared set on every relevant wake (`lazy-spec.coordination-playbook.md` Chapter 5). An implementation label is parameterised by tool whenever an asset carries more than one: `Start implementation (<tool>)`, one box per tool, so the ticks stay distinguishable in `# Gates` and in the dedup key.

The one label outside that arrangement is the review-launch label documented below. It belongs to no playbook's vocabulary because it is not a unit of work a playbook could declare — its condition is per-file and reads only a document's own type declaration, so every asset of every type hangs it under the same rule.

`spec_halted: true` overrides every declared label unconditionally in the coordinator's own reasoning — no checkbox is hung, and any already up come down, regardless of gate state.

### Checkbox block shape

```
> [!gate] Write code-plan
> - [ ] Write code-plan
> tick to dispatch: planner writes code-plan.md from design.md
```

Three lines, in this order: a `[!gate]` callout head carrying the bare label, a `- [ ]` / `- [x]` line repeating the same label, and a `tick to dispatch: <one-line description>` line. The block shares the `[!gate]` callout mark with `lazy-spec.flip-gate`'s own flip-record callout (`> [!gate] <gate> — flipped <date> (<reason>)`), but the two never collide: a flip-record's head line names a gate key plus `— flipped …`, while a checkbox block's head line is a bare label and its block is the only one of the two that carries a `- [ ]` / `- [x]` line.

A head line therefore reads one of two ways, and both are checkbox blocks: a **dispatch label** declared by the asset's type or tool playbook, or the **review-launch label** `Review <file>.md`, naming a reviewable markdown file of the asset. The second is the one label class this protocol names itself, because it belongs to no playbook's vocabulary — see below.

### The review-launch block

The second class of `[!gate]` block. Same callout, same single `- [ ]` row, label `Review <file>.md`, and a third line that says `tick to open review` rather than `tick to dispatch`:

```
> [!gate] Review races.md
> - [ ] Review races.md
> tick to open review: races.md re-enters the loop at the reviewer round
```

- **The reviewable set.** One row per markdown file of the asset whose `spec_doc_type` declares `review`. The coordinator scans the asset folder's markdown frontmatter for that key and reads each type's declaration; a document whose type has `review: false` never hangs a box, and neither does a file carrying no type at all. Ownership does not enter this — an attachment and a canonical document are gathered by exactly the same rule, which is the point of typing.
- **Granularity is the file.** The asset layout is flat, so there is nothing coarser to offer.
- **A document already under review hangs no box.** A file carrying `review_active: true` is in the loop; a second entry gesture is meaningless.
- **The tick opens review, it does not dispatch.** It invokes `lazy-review.submit` for that file — the content is already written, so review opens at the reviewer round, and the writer-round entry is never reachable from this block. No expert job is queued and no `active_job` marker is written, which is the one structural difference from a dispatch label. In that respect it behaves like `Publish` below, but it clears no flag and hangs on a per-file rather than a per-asset condition.
- **Class resolution is not this block's business.** Every row resolves its class the same way any document does, from its own `spec_doc_type`. The block only decides which files get a row.
- **`spec_halted: true` takes every row down**, exactly as it does for a dispatch label.

### Dispatch (ticked checkbox → expert job)

A `[!gate]` block a human left ticked is queued as one expert job through the `dispatch-job` verb. WHICH role, source, context and result each label carries is named by the playbook that declares the label; what stays fixed across every label is the wire below:

- **Expert resolution** — the dispatched expert is resolved from the review class of the checkbox's own RESULT document (its basename with `.md` stripped — for an implementation box, the tool's declared `report_doc`), read from `review.classes[<class>].experts.main[0].name` — the same class the document's own review loop uses once it exists.
- **Guidelines context** — the product's `guidelines[<role>]` paths plus its wildcard `guidelines["*"]` paths (per `lazy-spec.config-protocol.md`) fold into the job's `context`; a declared path that does not resolve to a file becomes a `# History` warning line, never a silent drop.
- **Dedup key** — `<asset-slug>:<label>`, guarding a second tick of the same checkbox while the first job is still active.
- **On success** — the coordinator removes the ticked block, marks `active_job: {"checkbox", "expert", "job_id"}` via `mark-job`, and records one `# History` line.
- **Guards** — a halted asset ignores every ticked checkbox; an asset already tracking an `active_job` also waits — one active job per asset at a time, checked by the coordinator before it dispatches.

### `Publish` — the one label that never dispatches a job

Everything about it follows the ordinary ladder above except its outcome: a tick clears `spec_draft` (via `note-set-key <asset> spec_draft false`), which itself appends the `# History` line, then the coordinator removes the checkbox — no expert job is ever queued for this label, and it never carries an `active_job` entry. The coordinator is also the one that hangs it in the first place, at the same wake that closes the asset's terminal gate (`spec_released` flipping true) — not a separate pass. There is no automatic clearing: `spec_released` closing means the design is approved and implemented, not that the operator is ready to hand it to a downstream consumer, who may want related work finished first. An asset that reaches its terminal gate but is never ticked stays a draft, un-published, until the operator ticks it.

`spec_draft` names one downstream consumer today (another repo's own `lazy-spec.upstream-tick`, when it configures this repo as one of its `spec.upstream` sources), but its documented meaning is not tied to that path — it is "this asset is NOT yet ready for a downstream consumer to pick up" (absent or false means ready), where a downstream repo mirrors THIS repo as its own upstream (whatever mechanism that consumer uses to pull). `Publish` is the full-mode ladder's own way of clearing it; a spec-only-mode product (`lazy-spec.coordination-playbook.md` Chapter 17) clears the same flag through a different path — the coordinator, after `design.md` approves and the operator gives an explicit word — since that profile never hangs a `Publish` checkbox at all (it never reaches a terminal gate the way a full-mode asset does).

## Part 4 — Change cascade (`spec_targets`)

An asset MAY declare `spec_targets` — the existing assets its own change modifies. **This section documents the frontmatter shape and the virtual dispatch labels the cascade rides on, and nothing else. The order of the cascade's phases is a chapter of the `change` type playbook (`lazy-spec.change-playbook.md`), not a rule of this protocol.**

### Frontmatter (on the change asset's status folder-note)

```yaml
spec_targets: ["features/csv-export", "features/audit-log"]   # optional; paths relative to the product's spec_path
spec_cascade_done: false                                       # true once every declared target has been folded
spec_cascade_targets_done: ["features/csv-export"]             # tokens already folded, in fold order
```

Tokens are paths relative to the product's `spec_path` — the same shape `spec_depends_on` carries (Part 2 § Frontmatter), so a nested target is addressed by its full path.

`spec_cascade_done` and `spec_cascade_targets_done` are written by the coordinator through `note-set-key`, the same primitive that writes every other coordinator-owned frontmatter key on this note.

### The virtual dispatch labels

A cascade job is dispatched through the same `dispatch-job` verb the launch-checkbox ladder uses, keyed by labels that are **virtual**: they are never ticked checkboxes and never appear in `# Gates` at all. The expert behind such a label resolves exactly as a launch checkbox's does (from the review class of the document the job writes), and the target token a cascade job concerns rides in the dispatched job's own payload — never in the `active_job` marker, whose shape is the same three keys for every dispatch.

A cascade job reporting `conflict: true` (per `lazy-spec.expert-signals-protocol.md`) halts the asset (`HaltReason.MERGE_CONFLICT`, Part 5) via an ordinary `flip-gate --halt` call — the coordinator invokes the same primitive any other halting caller would, never a bespoke phrase.

## Part 5 — Halt reasons (closed four-item set)

`spec_halted: true` is set exclusively by `flip_gate.halt_asset` / `flip_gate.halt_asset_text` — the single writer, regardless of which component calls it. Every caller passes a `reason` string drawn verbatim from the closed `HaltReason` class in `${CLAUDE_PLUGIN_ROOT}/bin/spec_keys.py`; no caller composes or invents a new phrase. The reason lands byte-for-byte in both the `# Gates` callout (`> [!failure] asset halted: <reason>`) and the `# History` line. Reproduced here exactly as the class defines them, in declaration order:

| # | `HaltReason` member | Phrase (verbatim) | Fired by |
|---|---|---|---|
| 1 | `JOB_DIED` | `job {job_id} ({label}) died` (format template, `job_id`/`label` substituted) | `gate_tick.py` (`_apply_job_marker`) — an asset's active job bundle carries a `DEAD` terminal marker. |
| 2 | `MERGE_CONFLICT` | `change delta could not be applied cleanly to the feature docs` | `spec.coordinator`, via `flip-gate --halt` — a change-cascade job reports `conflict: true` (Part 4; `lazy-spec.expert-signals-protocol.md`) folding its delta into a target doc. |
| 3 | `PLAN_DROP_PARTIAL` | `plan drop left the asset half-cleaned` | `apply_request.py` (`_rollback_pre_launch_ladder`, Part 6) on a pre-launch rollback step failure; `spec.coordinator`, via `flip-gate --halt`, on a cascade's own document-drop failure or a vanished cascade target (Part 4). |
| 4 | `GATE_PRECEDENCE` | `later gate true while an earlier gate is false` | `lazy-spec.doctor --apply` — operator-chosen escalation of a gate-precedence FAIL, offered as the alternative to turning the orphaned later gate back off. |

(The split-repo push-question / import-drift reasons — `DESIGN_DRIFT_ON_PUSH`, `IMPORT_DRIFT`, `NO_PUSH_ACCESS`, `PUSH_UNDELIVERED`, `IMPORTED_EDITED` — were removed with the `push_question.py` / `import_specs.py` channel they served.)

Un-halting (`spec_halted: false`) is always a manual operator edit — no worker ever clears the flag on its own. While `spec_halted: true`, the coordinator's own reasoning hangs no checkbox and dispatches no cascade job (playbook § 1), but the five gate booleans themselves are left exactly as they were — `spec_halted` silences the automation layers built on top of the gates, never the gates.

## Part 6 — Pre-launch rollback (a request attaching to a not-yet-launched feature)

When a request's routing resolves to an ATTACH target whose implementation ladder has already started (an `architecture.md`, `code-plan.md`, or `test-plan.md` sibling exists, or any gate from `spec_plan_done` onward already reads `true`) but has NOT yet launched implementation, `lazy-spec.request-apply` rolls the ladder back to its pre-launch state before seeding the attach delta (`lazy-spec.request-protocol.md` § Body distribution rules, point 2) — rather than seeding an attach delta on top of in-flight planning work that a fresh design change is about to revise.

### The launched-feature definition (mechanical, not a judgment call)

A feature counts as LAUNCHED — and must never reach the rollback path at all — when any of:

- `spec_develop_done` reads `true`, OR
- the tracked `active_job` names an implementation checkbox (an implementation job is dispatched, even before `spec_develop_done` itself flips), OR
- a `code-report.md` sibling already exists on disk.

`spec.coordinator`, running in its routing mode (`lazy-spec.coordination-playbook.md` Chapter 9), is responsible for keeping a launched feature off the attach path in the first place — it must propose a change-spawn (naming the feature via the change-spawn line's `targets=` field) instead of a plain attach. `lazy-spec.request-apply` re-checks the same three signals as a worker-side safety net, not the primary enforcement: an attach target found to be launched at apply time is refused outright with a logical error naming the target and the rule, never silently allowed through as a plain attach.

### Halted- and cancelled-asset refusal

An attach target already carrying `spec_halted: true` refuses the ENTIRE attach outright, regardless of ladder state — automation stays off a halted asset until an operator resolves it by hand, so a not-yet-launched-but-halted feature errors rather than touching its ladder. This is unconditional: even a not-yet-started ladder's plain attach-seed step (point 2 of the body-distribution model) is refused the same way, before any mutation — a halted asset gets no automated attach at all, seed included, until the operator resolves it. The same unconditional refusal applies to a `spec_cancelled: true` target, checked first: a cancelled asset would otherwise have its rollback destroy the plan siblings before discovering the refusal at Step 4 below, or (with no ladder started) sail through a plain attach-seed unguarded.

### The five steps (strict order; a failure anywhere halts and aborts rather than proceeding partially)

1. **Cancel the active job.** When the sidecar tracks an `active_job`, invoke the `lazycortex-core cancel-job` CLI (resolved via `$LAZYCORTEX_PLUGIN_DIRS`, the § 1c inter-plugin contract). A return that does not confirm the job is dead halts the asset (`HaltReason.PLAN_DROP_PARTIAL`) and aborts the whole apply run — a half-dropped ladder with a job possibly still running is worse than an intact one. On confirmed success, the `active_job` marker is cleared.
2. **Stop review on the dropped documents.** `lazycortex-review stop` on each named document that exists, best-effort — any failure (CLI crash, timeout) degrades to a silent skip, since the doc is about to be deleted regardless of its review state.
3. **Drop those documents.** Unlink each one from the worktree directly (not `git rm`). A document surviving its own deletion attempt halts the asset (`HaltReason.PLAN_DROP_PARTIAL`) and aborts — proceeding to flip gates over a ladder that is only partly dropped would leave state worse than either extreme.

**WHICH documents Steps 2–3 touch comes from the CALLER, never from a list this worker holds.** The attach line's own `drop=<name>[,...]` field (`lazy-spec.request-protocol.md` → Routing-block grammar) names them; the router decides what a rollback removes, because which documents an asset even has is a property of its type and its tools. An attach line with no `drop=` field drops nothing at all — the gates still roll back and every file stays on disk.
4. **Flip the downstream gates off.** `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, `spec_released`, each via an unconditional `flip_gate.flip_gate(..., off=True, auto=True)` (an `--off` flip needs no precondition, per Part 2). `spec_design_done` is left untouched — design is what the incoming request is about to revise, not what the rollback undoes. A refused flip (the asset went `spec_cancelled` mid-rollback) halts (`HaltReason.PLAN_DROP_PARTIAL`) and aborts — Steps 1–3 already cancelled the job and dropped the named documents, so a refused flip here still leaves that work half-done.
5. **Seed the attach delta and re-submit.** The ordinary attach-seed step runs exactly as it does for any attach target (`lazy-spec.request-protocol.md` § Body distribution rules, point 2), but the primary doc re-enters review via `lazycortex-review submit` (skipping the opening writer round) instead of `start`, since the doc already carries prior approved content the rollback just reopened.

Steps 1–4 are the rollback's own responsibility; Step 5 is the ordinary attach-seed flow every attach target runs — a rollback changes only which review verb (`submit` vs `start`) that step uses on this feature's primary doc, never what the step does. Whether to invoke the rollback AT ALL — versus modifying the target in place, or routing through a change despite it technically not being launched — is `spec.coordinator`'s judgment call in routing mode (playbook Chapter 9); the rollback primitive itself stays unconditional on its own three refusal checks (launched, halted, cancelled) no matter who calls it.

## A narrated example — design approved → a launch checkbox dispatches

The old cross-layer chain in this file described a fully automatic sequence with no operator step in the middle. That sequence no longer exists as code — every link below is now a `spec.coordinator` decision, woken by a commit to the asset's folder-note that has reached the *daemon's own checkout* (`daemon.run_here` — never the operator's checkout, per the model-audit's Step 0 topology), reasoning from `lazy-spec.coordination-playbook.md` plus the playbooks the asset's own frontmatter names. Every arrow marked "operator" below is a full commit + push + pull round trip, not an in-process step:

```
design.md approved in lazy-review (review_result: approved)
  → operator's review-approval commit is pushed from wherever the operator worked
  → the daemon's next `_git_pre` pull fast-forwards it into this checkout
  → this commit touches design.md, not the status folder-note — but `lazy-spec.coordinator-watch`'s
    `filter.any_of` also matches sibling-doc basenames, so the git-watch item fires on design.md
    directly; `coordinator_dispatch.py` resolves it to the owning asset's status folder-note and
    compares design.md's `review_result` against the value it last recorded there
  → the value transitioned (nothing recorded yet → `approved`) → spec.coordinator wakes
    (playbook § 1, trigger 6 doc-transition, `CoordinatorTrigger.DOC_TRANSITION`)
  → FIRST act of the wake: the coordinator reads `spec_asset_type` and `spec_tools` off the
    status note and loads the playbooks they resolve to — the type playbook, plus one tool
    playbook per named tool. Those files, and no others, are the law of this wake
  → Stage promotion (playbook Ch.4): coordinator calls `lazy-spec.set-stage design.md approved`
       (scalar + spec/approved mirror tag + folder-note # History; unchanged primitive)
  → the TYPE playbook's own condition for spec_design_done holds on the promoted state
  → coordinator calls `lazycortex-specs flip-gate <asset> spec_design_done --auto`
       (unconditional flip; callout + history line + atomic commit — flip_gate's own work, Part 2)
  → coordinator reconciles the checkbox set the playbooks declare (this file's Part 3 is only
    the block SHAPE): the next box the type playbook declares at this state is hung in # Gates
  → the daemon's `_git_post` pushes the coordinator's commit; the operator's own pull
    (or their vault's sync) brings the freshly-hung checkbox into view
  → operator ticks it in their own checkout, commits, and pushes
  → the daemon's next pull fast-forwards the tick's commit in — spec.coordinator wakes again
  → coordinator dispatches the job the declaring playbook names (its role, source, context and
    result document), marks active_job via mark-job — which checks the record's SHAPE, not the
    label's spelling — and records # History
  → the job runs, writes its result document, reports DONE
  → on that DONE, spec.coordinator calls lazy-review.submit on the document the job wrote — for
    a plan and for a tool's report alike, this is the ONLY thing that opens review (playbook
    Chapter 6); nothing scans for it and gate_tick opens nothing
  → gate_tick's active-job poll (Part 2's pure-poller pass) clears the active_job marker, raises
    pending_wake: job-done, and logs the outcome; that raised flag wakes spec.coordinator again
    (`CoordinatorTrigger.JOB_DONE`, Part 2 — fires whoever authored the commit)
  → the document approves in review → the approval commit is pushed and pulled the same way as
    design.md's was → coordinator wakes, promotes its stage, re-reads the same playbooks,
    evaluates the next gate's condition, flips it, reconciles the checkbox set again — the
    same loop, one push-pull-decide cycle at a time, forever the coordinator's.
```

Every step above is a `spec.coordinator` decision executed through an unconditional primitive — there is no longer a deterministic script chain that runs from one approve to S2 without an LLM in the loop. The primitives (`lazy-spec.set-stage`, `lazy-spec.flip-gate`, `gate-tick`'s poller) are exactly as fast and exactly as auditable as before; what moved is who decides to call them, and when. **Reaction latency is the daemon's pull cadence, not the routine's `interval_sec`** — a wake can only happen after an operator gesture has been committed, pushed, and picked up by this checkout's next `_git_pre` fetch/pull, and a coordinator answer is only visible to the operator after the matching `_git_post` push reaches them by their own pull. `interval_sec` bounds how often the daemon *looks*, not how fast a gesture crosses the checkout boundary in either direction.
