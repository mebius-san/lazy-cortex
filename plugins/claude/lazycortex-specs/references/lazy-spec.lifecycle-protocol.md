---
name: lazy-spec.lifecycle-protocol
version: 6
description: Asset progression contract — per-file spec_stage on authored docs, the recorded `spec_asset_type` / `spec_tools` facts and the flat gates on the status folder-note (the six S0..S6 gates on a release note, `spec_design_done` / `spec_released` / `spec_cancelled` on a design-only one), and the shapes the launch-checkbox ladder and change cascade write. The WORKFLOW layer (what closes a gate, which checkbox exists, what a label dispatches, how a cascade is ordered) belongs to the type and tool playbooks, applied by `spec.coordinator` — this protocol documents the wire shapes and the primitives still living in code, never a workflow rule and never a script-side decision.
---
# Asset lifecycle protocol — per-file stages and gates

Asset progression is tracked at two levels that feed each other:

- **Per-file `spec_stage`** on every authored doc — author-level state of `use-cases.md` / `design.md` / `ui-design.md` / `test-plan.md` / `bug.md`, a release's `code-plan.md` / `test-plan.md`, product-level `tech.md` / `design.md` / `architecture.md`. Closed set: `empty | draft | approved | rejected | cancelled | deferred`. The append-only report journals of a release (`code-report.md` / `test-report.md`), and the opt-in `decisions.md` registry, carry no `spec_stage` — they sit outside this whole layer (see § Applies to below).
- **Flat gates** on the status folder-note — the asset's overall progress: a design-only note (every type but `release`) carries `spec_design_done`, `spec_released` and `spec_cancelled`; a `release` note carries the six ladder gates through `S0..S6` (Part 2).

**Who decides, who executes.** `spec.coordinator` (agent + expert record; its law is `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.coordination-playbook.md`) is the SOLE judge of every sequencing decision this protocol used to hardcode — which sibling doc to promote, which gate's precondition currently holds, which launch checkbox to hang or dispatch, whether and how a change cascades. It acts only through a small set of primitives that remain script-level and unconditional on call: `lazy-spec.set-stage` (per-file stage), `lazy-spec.flip-gate` (gate booleans — refuses a gate off the note's ladder and any flip on a cancelled asset, no sequencing precondition of its own), `lazy-spec.gate-tick`'s worker (a pure poller now, no decisions), and the `note-set-key` / `note-check` verbs (`${CLAUDE_PLUGIN_ROOT}/skills/lazy-spec.audit/SKILL.md`'s sibling primitives, documented in `${CLAUDE_PLUGIN_ROOT}/bin/note_ops.py`). Anything below that reads like a rule the SYSTEM enforces is, since the coordinator's arrival, a rule the COORDINATOR follows, declared by the asset's type playbook (`asset_types.<name>.playbook`) and the playbooks of the tools in its `spec_tools` (`tool_types.<name>.playbook`) — marked "playbook, not code" wherever the distinction matters. The shapes (frontmatter keys, callout formats, the launch-marker record) are still exact contracts; the workflow that decides when to apply them lives in the playbooks, never here.

## Part 1 — Per-file `spec_stage` (authored docs)

### Frontmatter

Every authored doc carries:

```yaml
spec_stage: draft        # empty | draft | approved | rejected | cancelled | deferred
tags:
  - spec/draft           # mirror of spec_stage value (see "Status mirror tag" below)
```

### Closed stage set

Exactly six values. The old `review`, `done`, and `wtr` are gone — "in review" is now `spec_stage: draft` + `review_active: true`; "accepted" is `approved`.

- `empty` — doc not needed right now (resolved for optional docs). No review.
- `draft` — content being written. Maps to `review_active: true` once opted into the loop, OR pre-review (authored but not yet submitted). No separate waiting-room state.
- `approved` — accepted: `review_approved: true`, with no review running at the moment of approval. The document may be put under review again later (the catalog and coordination playbooks reopen review on an approved document) and stays `approved` while that review runs: `review_active: true` on an `approved` document is a legal state, and only `lazy-spec.set-stage` moves the stage. Approved-with-concerns collapses to `approved`: the outcome is read from `review_result` (`approved` | `approved-with-concerns`), the one review key finalize leaves on the doc, but `spec_stage` is plain `approved`.
- `rejected` — review or developer flagged the doc unworkable (a finalize-revert): a rejection callout sits in the body. **NOT terminal** — the doc returns to `draft` to re-open the loop.
- `cancelled` — doc abandoned. Its one exit is `draft`, taken when the asset it belongs to is un-cancelled (§ Transitions).
- `deferred` — doc parked: it exists, it is not abandoned, and nothing automatic acts on it. Its own `review_result` raises no doc-transition wake, stage promotion passes it over, it closes no gate, no `Write` row is hung or replacement seeded for it, and no coordinator edits it. A commit touching it still wakes the owning coordinator as an ordinary operator edit, so the folder note is kept in order around it. Not terminal — it has two exits: `draft` brings it back, `cancelled` abandons it where it sits.

### Applies to

Documents whose `spec_doc_type` is declared with `stages: true` (the shipped types with the flag set: `vision`, `system-vision`, `use-cases`, `system-use-cases`, `design`, `system-design`, `ui-design`, `system-ui-design`, `code-plan`, `test-plan`, `bug`, `system-tech`, `system-architecture`, `system-test-plan`, `content-design`, `research-design`, `research-report`). Which document kinds those are is a property of the declaration, not of a filename — see `lazy-spec.file-roles-protocol.md` § Document type. Which of them a given asset actually carries is the type playbook's declaration, not this file's: a plan document exists exactly for a tool whose `tool_types.<name>` record names a `plan_doc`, and its absence is a declared state, not a gap `lazy-spec.audit` flags.

Does NOT carry `spec_stage` — every type declared `stages: false`, plus the untyped notes: the status folder-note (carries gates instead); container folder-notes (`<product>.md`, `bugs/bugs.md`, …); the append-only report journals (a release's `code-report.md` / `test-report.md`, and any other `report_doc` a tool declares with `append_only: true`) — they are written during execution, never approved into a stage, and carry no lifecycle state of their own; the opt-in `decisions.md` registry (product-level or asset-level) — it is an append-only registry written only by the `decide` primitive, never opted into review, and carries no lifecycle state of its own. They sit outside both layers of this protocol: no per-file stage, no role in any gate precondition. A tool whose report is declared with stages — the `research` tool's `research.md`, typed `research-report` — carries a per-file stage like any authored document and is not in this set.

### Mapping to lazycortex-review v4 flags

| `spec_stage` | lazycortex-review v4 flags |
|---|---|
| `empty` | no review opened on the doc |
| `draft` | `review_active: true` (in the loop), OR pre-review (authored, not yet submitted) |
| `approved` | `review_approved: true`; `review_active` reads `false`, or `true` while a reopened review runs on the still-approved document; approved-with-concerns collapses here (the outcome is read from `review_result`) |
| `rejected` | finalize-revert; a rejection callout in the body |
| `cancelled` | abandoned; leaves only for `draft` when its asset is un-cancelled |
| `deferred` | parked; whatever review flags the doc carries raise no transition while it stays here |

### Transitions

Forward: `empty → draft → approved`.

`rejected` is reachable when a review or developer rejects the doc; the only path out is back to `draft` (re-open). `cancelled` is reachable from `empty`, `draft`, `approved`, `rejected` and `deferred`.

`cancelled` has one way back: `draft`. It is taken when the operator un-cancels the asset with `flip-gate <asset> spec_cancelled --off` — the verb clears `spec_cancelled` and moves every authored document of that asset that sits at `cancelled` to `draft` through `lazy-spec.set-stage`, its `spec/<stage>` tag following, all in one commit; from there each document takes the ordinary path, review then approval. The return to `draft` also drops the document's `review_result`, so a document cancelled after approval is not promoted straight back on the verdict it carried before the cancellation. Every other move out of `cancelled` — to `approved`, `rejected`, `deferred` or `empty` — is refused, a direct `set-stage` call included. `approved` is terminal for every writer but one: on a `Rebuild` tick `spec.coordinator` moves a release's approved `code-plan.md` / `test-plan.md` back to `draft` when an included asset's document the plan was made from changed — a re-approved design, a newly included asset, a new or re-approved `ui-design.md` or test-cases document — while a plan of the release's own re-approved after the last build stays `approved` (`lazy-spec.release-playbook.md`, "Rebuild", step 3) — the only downward stage move in the system, always with a `# Status brief` sentence naming the change. The move also drops the document's `review_result`: the verdict no longer describes it, and a draft still carrying an accepted verdict would be promoted straight back to `approved` on the next promote walk. A re-approved source never lowers the stage of a document that depends on it; contradictions between documents are caught by the coherence check after approval (`lazy-spec.coordination-playbook.md` Chapter 19). `rejected` is a re-open marker, NOT terminal.

`deferred` is reachable from any stage on any stage-bearing type — asset-level and level documents alike — and its only exits are `draft` (unpark) and `cancelled` (abandon the parked document). Those three calls are the whole vocabulary of parking: `lazy-spec.set-stage <doc> deferred` parks, `lazy-spec.set-stage <doc> draft` unparks, `lazy-spec.set-stage <doc> cancelled` abandons it where it sits, and no other target stage is accepted while the document sits parked. Nothing else moves the stage on its own — a review verdict landing on a parked document is recorded on the file and read by nobody until it comes back.

`cancelled` is refused on `design.md` (asset-level and system-level alike), on `bug.md`, and on the product root's `architecture.md` (type `system-architecture`) — an asset's defining documents are abandoned as a whole through `spec_cancelled`, never one at a time, and a system's design and its architecture are its defining documents too. No asset carries an `architecture.md` of its own. `tech.md` (type `system-tech`) and the plan documents (`code-plan.md`, `test-plan.md`) MAY be `cancelled` — a plan whose work turned out not to be needed is walked back without abandoning the asset. (Enforced by `lazy-spec.set-stage`.) Report journals carry no `spec_stage` at all (see § Applies to), so cancellability is not a question that applies to them.

### Status mirror tag

Every doc carrying `spec_stage:` ALSO carries a hierarchical Obsidian tag mirroring the value:

```yaml
spec_stage: approved
tags:
  - spec/approved
```

The `set-stage` verb behind `lazy-spec.set-stage` is the only writer of both fields. The one exception is a document `lazy-spec.sync-with-code` creates: it is born at `deferred` with both keys written by hand in its Step 8; every later stage change goes through the verb. `lazy-spec.audit` validates that the tag matches the field; a mismatch is a finding.

The tag enables Obsidian queries (`#spec` for all stage-bearing docs, `#spec/approved` for accepted only, etc.) without requiring Dataview to parse frontmatter values.

### The single mutator — `lazy-spec.set-stage`

`lazy-spec.set-stage <file-path> <new-stage>` is the ONLY primitive that changes a per-file stage. Every per-file stage change in the system goes through it; no skill, worker, or coordinator call raw-edits `spec_stage`. The skill runs the `set-stage` CLI verb, which owns every check, the mirror tag and the `spec_approved_at` stamp; its refusals arrive in `reason`. The stamp is the moment the document last entered `approved`, and it exists only while the document is `approved`: it is written on entry into `approved` (and on an explicit restamp), and removed on every move out of `approved`, so a reader such as the coherence check never takes a stale stamp for a current approval. Its type check reads the declaration, never the path or basename, which is what keeps the status folder-note, every `report_doc` type a tool declares and the `decisions` registry out of reach — none of them carries an independently-settable stage. No history line is written on any stage move.

It does NOT advance the folder-note's gates — deciding whether a gate is ready to move, and calling `lazy-spec.flip-gate` to move it, is `spec.coordinator`'s call (§ Part 2 below). The full skill contract lives at `${CLAUDE_PLUGIN_ROOT}/skills/lazy-spec.set-stage/SKILL.md`.

### Stage promotion — a coordinator decision, executed through this same primitive

**Playbook, not code.** Nothing in this repo auto-promotes a stage anymore. Per `lazy-spec.coordination-playbook.md` Chapter 4 ("Stage promotion"), the coordinator itself runs one `promote-approved <note>` call on every wake, before evaluating any gate; the verb owns which documents it promotes and which it skips, and reports each refusal in `reason` without stopping the walk. Running it before the gates matters because a gate reads the promoted stage. Each promotion is the exact same mutation `lazy-spec.set-stage` always performed (the `set-stage` verb's write, no history line), simply invoked through a coordinator primitive rather than by a dedicated worker step. There is no longer a separate "auto-promotion" code path, and no separate `empty → draft` pre-review promotion tied to a gate flip's own side effect — opening review on a freshly-authored plan document is itself now a coordinator-dispatched launch-checkbox job (§ Part 3), not something a gate flip triggers as a cascade.

## Part 2 — Gates (asset progression)

### Frontmatter

The status folder-note carries the asset's two recorded facts, its gate booleans, and one overlay flag. Every type but `release` is design-only and carries two gates:

```yaml
spec_asset_type: feature                       # the asset's type; `unknown` is the sentinel, never a guess
spec_tools: ["code", "test"]                   # absent = not determined; [] = determined to need none
spec_design_done: false
spec_released: false
spec_cancelled: false
spec_state: draft                              # derived; the coordinator's, read by the iconize registry
```

A `release` note carries all six, `spec_design_done` true from creation, plus `spec_version` and `spec_includes` (`lazy-spec.status-note-protocol.md` Part 4). The four middle keys — `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, `spec_built` — are absent from every other note, and `lazy-spec.flip-gate` refuses to turn one on there.

There is no `gates:` dict, no `stage:` on the folder-note, no `awaits_human:`, and no `## Workflow` section — these keys are the entire model.

**`spec_state` is derived, not recorded.** It is the one key here nothing downstream reasons with: the coordinator writes it on the same wake that rebuilds `# Status brief`, and its only consumer is the iconize registry, which paints the asset folder from it. Legal values are `draft`, `in-review`, `implementation`, `testing`, `deferred`, `waits-operator`, `awaiting-release`, `in-release`, `done` (`spec_keys.py::AssetState`); `spec_halted` and `spec_cancelled` paint over it from their own keys rather than taking a value of their own. Two of the values are not derivable from this note at all — `in-review` lives as `review_active` on a sibling document, and `implementation` / `testing` track a job in the gitignored runtime sidecar — which is why the key exists instead of a matcher computing the state itself. A gate flip never writes it as a side effect; the coordinator sets it, exactly like every other key it owns.

**`spec_asset_type` is a recorded fact, not an inference.** It names one type declared under `products[<key>].asset_types` (over the shipped defaults in `references/lazy-spec.asset-types.json`), and it is what resolves the asset's type playbook. The sentinel `unknown` — and an absent key, which reads the same — means the type has not been determined yet; nothing downstream guesses it. The asset's FOLDER is a place, not a fact: where the operator filed the thing takes no part in resolving what it is, and a legally-typed asset may sit anywhere in the catalog, nested inside another asset included.

**The asset's boundary is its status folder-note** — the folder whose folder-note carries `spec_role: status`. A nested asset is its own asset with its own status note and its own gates, never a part of the asset it sits inside.

**`spec_tools` distinguishes three states, and the difference is load-bearing.** An absent key means the tool set has not been determined; an empty list means it HAS been determined and the answer is "no tool at all"; a non-empty list names the tools whose playbooks (`tool_types.<name>.playbook`) govern the asset's work inside the release build that ships it — every type but `release` is design-only and runs no build of its own. WHEN the list is written, and from which source, is the type playbook's declaration — the coordinator writes it through `note-set-key` like every other frontmatter key it owns.

**Cross-asset tokens are paths relative to the product's `spec_path`.** A `spec_targets` token (Part 4) is a path from `spec_path` down to the asset's own folder, so every asset is addressed by its full path from `spec_path`; for an asset sitting at the product root that path is its bare slug, and never a folder it does not actually sit under.

### Linear map S0..S6

The gates are a strict ladder. Each gate requires the one before it to be true:

| State | Meaning | True gates |
|---|---|---|
| S0 | new asset | (none) |
| S1 | design done | `spec_design_done` |
| S2 | plan done | + `spec_plan_done` |
| S3 | develop done | + `spec_develop_done` |
| S4 | tests passing | + `spec_tests_passing` |
| S5 | built | + `spec_built` |
| S6 | released | + `spec_released` |

Only a `release` note walks the whole ladder; a design-only note steps from S1 straight to S6 — its `spec_released` is written by the release that ships it, with the four middle keys absent.

**`spec_released` is the readiness flag.** On every asset status note it alone answers "is this published and ready for a downstream consumer": `true` means published and ready, absent or `false` means not ready. A re-approved start document turns it off (`lazy-spec.coordination-playbook.md` Chapter 4), so the asset stops reading as ready until a release publishes it again. On a release note `spec_built` holds the state "tests pass and the build is merged, not yet published", and `spec_released` means published, exactly as on the assets the release includes. The shape a healthy note's gate state must respect follows from its type, and `lazy-spec.audit`'s precedence check (Part 2-adjacent, its own SKILL.md) flags a later gate true while an earlier one is false on a release note, and a middle key present at all on any other. What changed is who enforces the ORDER of flips at flip time: nobody. `lazy-spec.flip-gate` flips whichever gate it is called on, unconditionally, and trusts the coordinator's own reasoning (below) to have called it in the right order.

### Gate readiness (playbook, not code)

**No readiness rule lives in this file.** What each gate closes on is declared by the asset's own playbooks, and this protocol describes only the mechanism of the booleans and the S0..S6 order above. `spec_design_done` is the type playbook's subject — what the type's defining document is and when it counts as approved is a property of the type, not of the ladder. `spec_plan_done`, `spec_develop_done`, `spec_tests_passing` and `spec_built` exist on a release note only and are the release playbook's: the settled architecture and the plans, the accepted `code-report.md` and the merged build, the accepted green `test-report.md`; the tool playbooks say what each tool's share of a build is. `spec_built` closes by itself on a release once its tests pass and the build is merged. `spec_released`, on the release and on every included asset, is the release's `Publish` tick's write (`release-publish`), together with the asset's version tag — the one freeze point of the ladder; a research asset's closes on its report's approval, and a spec-only product's on the operator's word.

`lazy-spec.flip-gate` reads none of this — it flips the named gate on call, refusing only a gate off the note's ladder (above) and every flip on a cancelled asset regardless of direction but the un-cancel `spec_cancelled --off`. `lazy-spec.audit` still validates the coupling (a gate reading true while the state its playbook names has not been reached is a doctor finding, per its Agent D check); the playbooks are its reference for what "ready" means, exactly as they are the coordinator's.

`spec_cancelled: true` freezes all gates — `lazy-spec.flip-gate` refuses every flip, forward or `--off`, while the asset is cancelled, with one exception: `spec_cancelled --off` itself, the un-cancel. Beside the ladder-shape refusals above, this is the one state the primitive still enforces on its own, because it is the asset's own state, not a sequencing precondition. The un-cancel, `flip-gate <asset> spec_cancelled --off`, clears the flag and moves every authored document of the asset at `cancelled` back to `draft` (§ Transitions), in one commit; the asset then follows its normal path. An operator or the coordinator invoking `--off` on any other gate by hand needs no precondition — turning a gate off has never needed one — but is still refused while cancelled.

### Derived vs human-signal gates — vocabulary, not enforcement

Each gate is still one of two kinds, a distinction the coordinator's own reasoning (and `lazy-spec.audit`) still uses, even though no script branches on it anymore:

- **Derived** = `{spec_design_done, spec_plan_done}`. Readiness is fully derivable from document state — the coordinator flips these the moment the playbook's own condition holds, no operator input needed.
- **Human-signal** = `{spec_develop_done, spec_tests_passing, spec_built, spec_released}`. Readiness needs a signal the coordinator cannot derive from a document's existence alone — an accepted report, a green test run, a merge, the operator's `Publish` tick. The coordinator flips the first three on a release from that signal; `spec_released` on the release and on every included asset is `release-publish`'s own write.

### The single mutation channel — `lazy-spec.flip-gate`

`<specs-cli>` stands for the specs plugin's `bin/lazycortex-specs` file — the copy under `~/.claude/plugins/cache/lazycortex/lazycortex-specs/<version>/` that `~/.claude/plugins/installed_plugins.json` records as installed, or `plugins/claude/lazycortex-specs/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

`bin/flip_gate.py` (driven by the `/lazy-spec.flip-gate` skill, and called directly by `spec.coordinator` through the `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> flip-gate` CLI verb) is the **only** writer of gate booleans. The flip is unconditional on call:

1. Reads the folder-note frontmatter.
2. Refuses, before anything is written, an unknown gate name, a gate off the note's own `spec_role` ladder (§ Part 2, level notes), a middle gate turned on anywhere but a `release` note, and every flip while the asset is cancelled (`spec_cancelled: true`) except the un-cancel `spec_cancelled --off` — no sequencing precondition check.
3. Rewrites the gate boolean in frontmatter.
4. Writes `spec_<gate>_at` (an unquoted ISO 8601 UTC datetime) beside a gate turning true and removes it when the gate turns false. Nothing is written to `# Gates` or `# History`; the reason (`--reason`, prefixed `auto:` under `--auto`) is recorded in the run log only.
5. **Atomic git commit of the folder-note edit** under `lazy-spec.flip-gate@bot.invalid` (subject `lazy-spec.flip-gate: <gate> → <true|false> on <asset>`). Without this commit the daemon's next iteration trips its dirty-tree-skip guard and silently halts every routine on the asset. Defensive skip when the asset is not inside a git repository (test-fixture path) — the file write remains but the commit step is no-op.
6. Writes a run log under `.logs/claude/lazy-spec.flip-gate/`.

There is no post-flip cascade anymore — a forward flip of `spec_design_done` does not itself open review on a plan document. Opening that review is now a coordinator decision executed as an ordinary launch-checkbox dispatch (§ Part 3), ordered by the playbooks, not a side effect wired into the flip primitive.

CLI: `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> flip-gate <asset_dir> <gate> [--off] [--auto] [--reason TEXT]`.

### The `gate-tick` md-scan worker — a pure poller, no decisions

`bin/gate_tick.py` is dispatched per matched status folder-note by the `lazy-spec.gate-tick` `md-scan` routine, same as before. It performs exactly two concerns now, both mechanical:

1. **Active-job polling.** An asset whose runtime sidecar tracks an `active_job` has that job bundle's terminal marker (`DONE` / `DEAD` / `CANCELLED`, read file-wise from the `lazycortex-core` job-runtime layout, never imported cross-plugin) checked before anything else. Every marker clears the tracked job and raises `pending_wake: job-done` in its place — both sidecar writes, so that half costs no commit. `DONE` and `CANCELLED` then journal one `# History` line each (through the core `history-append` verb, never composed by hand). `DEAD` sets `spec_halted: true`, journals the halt, and appends a persistent `[!failure]` callout to `# Gates` — un-halting is a manual operator act, out of scope for this worker.

**This worker opens no review.** Opening review on any freshly-written document, a job's report included, is a `lazy-review.submit` call made by the coordinator on the `job-done` wake this very pass raises (`lazy-spec.coordination-playbook.md` Chapter 6) — never a follow-up wired into the poller.
2. **Structural note-check.** `note_ops.note_check`'s violations (an unrecognized or mistyped frontmatter key, a missing or misordered required section) are folded into the tick's own result — read-only; repairing what it finds is the coordinator's job, through its pen and `note-set-key`, never this worker's.

Everything this worker used to decide — sibling-doc stage promotion, gate readiness, the launch-checkbox ladder, downward reconciliation, change-cascade dispatch — is gone from this file entirely; it lives in `lazy-spec.coordination-playbook.md`, executed by `spec.coordinator`. A no-op tick (no terminal marker yet, note structurally clean) returns `{"action": "noop"}`.

CLI: `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> gate-tick <asset_note> [--today YYYY-MM-DD]`.

## Part 2b — Level gates (catalog root and product root)

A LEVEL note — the catalog root's (`spec_role: catalog`) or a product root's (`spec_role: product`), see [status-note](./lazy-spec.status-note-protocol.md) Part 4b — carries its own five level booleans instead of the five asset gates above:

```yaml
spec_vision_done: false
spec_use_cases_done: false
spec_design_done: false
spec_ui_design_done: false
spec_tech_done: false
spec_halted: false
```

- **All five are derived, and each from exactly one document** loose beside the note: `spec_vision_done` from `vision.md`, `spec_use_cases_done` from `use-cases.md`, `spec_design_done` from `design.md`, `spec_ui_design_done` from `ui-design.md`, `spec_tech_done` from `tech.md`. There is no human-signal gate at this level and no operator gesture that closes one — `spec.catalog-coordinator` flips every one of them with `flip-gate --auto`.
- **An absent optional document closes its gate.** `use-cases.md`, `design.md`, `ui-design.md` and `tech.md` are optional, so `spec_use_cases_done` / `spec_design_done` / `spec_ui_design_done` / `spec_tech_done` each close when their document is ABSENT or exists at stage `approved`, and open only in the middle state — the document exists at some other stage. `vision.md` is the one mandatory document of the ladder, so `spec_vision_done` alone requires an approved document and never closes on absence.
- **There is no ladder among them.** Unlike the asset gates' strict S0..S6 order, the five level gates are independent booleans: `vision` gates the launch CHECKBOXES that write the other four documents, never their gate values, and any of `use-cases` / `design` / `ui-design` / `tech` may close before another or never close at all. The one ordering on a product root — `use-cases.md` holding the review of `design.md` — is a hold on a review, never on a gate value. A doctor precedence check does not apply here.
- **A gate may be undeclared.** An operator may declare in a level note's `# Coordinator rules` that this level needs no `use-cases`, no `design`, no `ui-design` or no `tech` document at all (a `tech.md` or `use-cases.md` at stage `cancelled` says the same after the fact), and `use-cases.md` / `ui-design.md` are product-root documents only — the catalog root never owes either, so `spec_use_cases_done` / `spec_ui_design_done` there read closed on absence like any optional document. An undeclared gate is not a gap and never a finding — the level playbook owns which of the five this level actually has.
- **`spec_halted` is the level's only overlay.** There is no `spec_cancelled` and no `spec_released` on a level note: a level is not abandoned and not shipped.

`lazy-spec.flip-gate` validates both halves of the pairing on every call: a gate name outside `{the five asset gates} ∪ {the five level gates}` is refused, and so is an asset gate on a level note or a level gate on a status note. What each gate closes on is the level playbook's (`${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.catalog-playbook.md` § 2), exactly as the asset gates' readiness is the type playbook's.

## Part 3 — Launch checkboxes (operator-triggered dispatch)

A layer on top of the gates: checkbox blocks the coordinator renders, reconciles, and dispatches in `# Gates`, letting the operator queue the next unit of work with a single tick. **This section documents the WIRE shape only — the frontmatter keys, the runtime job marker, and the checkbox block's markdown shape.** Which labels exist, when each appears, when it comes down, and what a tick dispatches is declared by the asset's type and tool playbooks and applied by the coordinator (`lazy-spec.coordination-playbook.md` Chapter 5) — no script hangs, removes, or dispatches a checkbox anymore.

### Frontmatter and the job marker

One additional frontmatter key:

```yaml
spec_halted: true                                              # absent by default; only present once an active job dies
```

Readiness for a downstream repo (another repo's own `lazy-spec.upstream-tick` when this repo happens to be its configured source) is `spec_released` alone (Part 2, Linear map). Notes written before the readiness flag moved there still carry a `spec_draft` key; the `migrate-readiness` verb, run by `/lazy-spec.install`, rewrites them.

The dispatched job itself is NOT frontmatter. It lives in the gitignored runtime sidecar at `<repo>/.runtime/lazy-specs.jobs.json`, keyed by the note's repo-relative path, under the `active_job` field:

```json
{"checkbox": "Build", "expert": "claude-plugin.developer", "job_id": "20260101-abcd"}
```

Writes go through `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> mark-job <asset_note> active <json>` (or `--clear`), which validates the object's SHAPE and nothing else: exactly the three keys `checkbox` / `expert` / `job_id`, each a non-empty string. The label's spelling is not checked against any list — the vocabulary belongs to the playbooks, not to this primitive. The coordinator writes the marker as part of dispatching the job it tracks; `lazy-spec.gate-tick`'s active-job polling pass (Part 2 above) is the one piece of code that clears it. Because the marker is runtime state rather than document content, neither write costs a commit, and an operator hand-editing the folder-note cannot lose a live job's record. Read it back through `note-check`, whose result carries the note's `job_markers` entry; a `spec_active_job` key found in frontmatter is a regression, not a source.

### The label set is open

There is no fixed list of labels in this protocol, and no primitive holds one. The VOCABULARY — which labels exist on a note, what each one's appearance condition is, and what a tick enacts — is declared by the note's type playbook (and, on a level note, the level playbook); the coordinator reconciles exactly that declared set on every relevant wake (`lazy-spec.coordination-playbook.md` Chapter 5). A design-only asset hangs `Write <doc>` rows only; a release note hangs `Write code-plan`, `Write test-plan`, `Rebuild` and `Publish`, and dispatches its build jobs by rule under the labels `Revise architecture`, `Build` and `Test`; a product note hangs `Start release` beside its `Write` rows. No `Start coding` / `Start data entry` / `Start documentation` / `Start testing` row exists any more — the implementation of every asset is a release's build (`lazy-spec.release-playbook.md`).

The one label outside that arrangement is the review-launch label documented below. It belongs to no playbook's vocabulary because it is not a unit of work a playbook could declare — its condition is per-file and reads only a document's own type declaration, its `review_active` flag and its `spec_stage`, so every asset of every type hangs it under the same rule.

`spec_halted: true` overrides every declared label unconditionally in the coordinator's own reasoning — no checkbox is hung, and any already up come down, regardless of gate state.

### Checkbox block shape

```
> [!gate] Write code-plan
> - [ ] Write code-plan
>
> tick to dispatch: planner writes code-plan.md from the included assets' start documents
```

Four lines, in this order: a `[!gate]` callout head carrying the bare label, a `- [ ]` / `- [x]` line repeating the same label, a blank quoted line (`>`), and a `tick to dispatch: <one-line description>` line. The blank quoted line is structural: without it the description is the checkbox item's continuation, and Obsidian's task renderer hides it in reading view (`lazy-spec.status-note-protocol.md` Part 4). `[!gate]` blocks in `# Gates` are checkbox blocks and nothing else — `lazy-spec.flip-gate` writes no callout of its own.

A head line therefore reads one of two ways, and both are checkbox blocks: a **dispatch label** declared by the asset's type or tool playbook, or the **review-launch label** `Review <file>.md`, naming a reviewable markdown file of the asset. The second is the one label class this protocol names itself, because it belongs to no playbook's vocabulary — see below.

### The review-launch block

The second class of `[!gate]` block. Same callout, same single `- [ ]` row, the same blank quoted line, label `Review <file>.md`, and a fourth line that says `tick to open review` rather than `tick to dispatch`:

```
> [!gate] Review pricing.md
> - [ ] Review pricing.md
>
> tick to open review: pricing.md re-enters the loop at the reviewer round
```

The blocks are written by one verb, `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> review-rows <note>`: it computes the reviewable set below for the note, hangs the missing blocks in exactly this four-line shape, takes down an un-ticked block whose document left the set, never removes a ticked one, and commits nothing. The coordinator runs it on every wake and again after enacting a tick; when it runs and how a tick is enacted is `lazy-spec.coordination-playbook.md` Chapter 5.

- **The reviewable set.** One row per markdown file of the asset whose `spec_doc_type` declares `review: true` and not `append_only: true`, in any `spec_stage` except `cancelled`. The verb reads each file's type declaration; a document whose type has `review: false` never hangs a box, and neither does a file carrying no type at all. The append-only report journals never hang one: a report enters review only when the job writing it finishes. Ownership does not enter this — an attachment and a canonical document are gathered by exactly the same rule, which is the point of typing. A level note (product root, catalog root) is gathered by the same rule over the level's own documents.
- **Granularity is the file.** The asset layout is flat, so there is nothing coarser to offer.
- **A document already under review hangs no box.** A file carrying `review_active: true` is in the loop; a second entry gesture is meaningless. The box returns when the review ends.
- **The tick opens review, it does not dispatch.** It invokes `lazy-review.submit` for that file — preceded by the `set-stage` verb with `<file> draft` when the file sits at `empty` or `deferred` — so review opens at the reviewer round, and the writer-round entry is never reachable from this block. A file that is still the untouched template has nothing to review, and its tick launches nothing. No expert job is queued and no `active_job` marker is written, which is the one structural difference from a dispatch label. In that respect it behaves like `Publish` below, but it clears no flag and hangs on a per-file rather than a per-asset condition.
- **Class resolution is not this block's business.** Every row resolves its class the same way any document does, from its own `spec_doc_type`. The block only decides which files get a row.
- **`spec_halted: true` takes every un-ticked row down**, exactly as it does for a dispatch label.

### Dispatch (ticked checkbox → expert job)

A `[!gate]` block a human left ticked is queued as one expert job through the `dispatch-job` verb. WHICH role, source, context and result each label carries is named by the playbook that declares the label; what stays fixed across every label is the wire below:

- **`target_doc` in the payload** — every job dispatched to write a catalog document carries `target_doc` in its `request.json` payload: the repo-relative path of the document that job writes. The job returns only content, through its own `result/`; where that content belongs is settled at dispatch, by the side that knows the ladder, and travels with the job. The `land-result` collector reads the key to place the returned document, and refuses a job that declares none — nothing is landed, the document stays in the job's `result/`, and the job reads as undelivered. A declared path outside the asset's own folder is refused the same way — except a cascade job, whose target lies in another asset's folder by design and is named explicitly by the coordinator at landing time (Part 4).
- **Expert resolution** — the dispatched expert is resolved from the review class of the checkbox's own RESULT document (its basename with `.md` stripped — for a release's `Build` job, the declared `report_doc` of the implementer's tool), read from `review.classes[<class>].experts.main[0].name` — the same class the document's own review loop uses once it exists.
- **Guidelines context** — the product's `guidelines[<role>]` paths, then the asset type's `asset_types[<type>].guidelines`, then the wildcard `guidelines["*"]` paths (per `lazy-spec.config-protocol.md`) fold into the job's `context`; a declared path that does not resolve to a file is a dispatch warning journaled in `# History` as a job that failed to start, never a silent drop.
- **Dedup key** — `<note-path>:<label>` (the status note's repo-relative path plus the label, per `lazy-spec.coordination-playbook.md` Chapter 5's dedup clause), guarding a second tick of the same checkbox while the first job is still active.
- **On success** — the coordinator removes the ticked block and marks `active_job: {"checkbox", "expert", "job_id"}` via `mark-job`. Nothing is journaled for the dispatch itself — the job's finish, death, or cancellation is the history event.
- **Guards** — a halted asset ignores every ticked checkbox; an asset already tracking an `active_job` also waits — one active job per asset at a time, checked by the coordinator before it dispatches.

### `Publish` — the release's freeze point

`Publish` hangs on a release note only, once the release's `spec_built` has closed while its `spec_released` is still false; a design-only asset never hangs it. The tick is enacted with `release-publish <release-note>`, which never queues an expert job: when the product declares `release.deploy.production` it deploys there first — a failed deploy writes one `# History` line, changes nothing else and re-hangs the row — and on success it sets `spec_released: true` with its moment and adds the `release/<x-y-z>` tag on every asset in `spec_includes`, sets the release's own `spec_released: true` with its moment, writes the version into the product's manifest when one is named, and lands the whole set in one commit. The release is frozen from that commit on; every later edit goes into the next release (`lazy-spec.release-playbook.md`, "Release and Publish").

`spec_released` names one downstream consumer today (another repo's own `lazy-spec.upstream-tick`, when it configures this repo as one of its `spec.upstream` sources), but its documented meaning is not tied to that path — it is "this asset is published and ready for a downstream consumer to pick up" (absent or false means not ready). Two notes close it without a release: a research asset's closes on the approval of its `research.md`, and in a spec-only product (`lazy-spec.coordination-playbook.md` Chapter 17) the coordinator closes it on the operator's explicit word.

### Wake hops between notes

Three wakes travel between notes, each one hop, each raised after the raising note's own write has landed, each best-effort: `asset-approved` (the `spec_design_done` or `spec_cancelled` of an asset of any type but `release` changing value, in either direction, reaches the level note of the product that owns releases, with `payload["asset"]` relative to that product; it re-hangs rows and rewrites `# Status brief`, and beyond that may only cancel an open release whose delta has emptied — `lazy-spec.catalog-playbook.md` § 5), and `release-start` (the product coordinator waking a release's own note once after `Start release` or `Rebuild`, and again on a verdict over the revised `architecture.md` of the build's first step, through `coordinator-dispatch --release-start <release-note>` — the one downward hop a level makes; a note that is not a release refuses it), and `release-published` (`release-publish` waking the level note of the product that owns the release once, after the publish commit; a failed production deploy raises nothing, and a failed wake never fails the publish; it only re-hangs rows). `asset-approved` and `release-start` are raised by `coordinator_dispatch.py`.

## Part 4 — Change cascade (`spec_targets`)

An asset MAY declare `spec_targets` — the existing assets its own change modifies. **This section documents the frontmatter shape and the virtual dispatch labels the cascade rides on, and nothing else. The order of the cascade's phases is a chapter of the `change` type playbook (`lazy-spec.change-playbook.md`), not a rule of this protocol.**

### Frontmatter (on the change asset's status folder-note)

```yaml
spec_targets: ["csv-export", "audit-log"]                      # optional; paths relative to the product's spec_path
spec_cascade_done: false                                       # true once every declared target has been folded
spec_cascade_targets_done: ["csv-export"]                      # tokens already folded, in fold order
```

Tokens are paths relative to the product's `spec_path` (Part 2 § Frontmatter), so a nested target is addressed by its full path.

`spec_cascade_done` and `spec_cascade_targets_done` are written by the coordinator through `note-set-key`, the same primitive that writes every other coordinator-owned frontmatter key on this note.

### The virtual dispatch labels

A cascade job is dispatched through the same `dispatch-job` verb the launch-checkbox ladder uses, keyed by labels that are **virtual**: they are never ticked checkboxes and never appear in `# Gates` at all. The expert behind such a label resolves exactly as a launch checkbox's does (from the review class of the document the job writes), and the target token a cascade job concerns rides in the dispatched job's own payload — never in the `active_job` marker, whose shape is the same three keys for every dispatch.

A cascade job carries `target_doc` like every other document-writing dispatch (Part 3 § Dispatch), and it is the one case where that path points into ANOTHER asset's folder: the target's own `design.md` or `test-plan.md`, not the change asset's. The writer never touches that document in the working tree — it returns the folded document through its own `result/`, exactly as a launch job does. Because the destination lies outside the dispatching asset's folder, the landing is the coordinator's own move on the job-done wake rather than `gate-tick`'s: it calls the `land-result` verb with an explicit target (`lazy-spec.change-playbook.md` § The cascade), which is the one route allowed to place a document outside one asset folder, bounded by the spec catalog.

A cascade job reporting `conflict: true` (per `lazy-spec.expert-signals-protocol.md`) halts the asset (`HaltReason.MERGE_CONFLICT`, Part 5) via an ordinary `flip-gate --halt` call — the coordinator invokes the same primitive any other halting caller would, never a bespoke phrase.

## Part 5 — Halt reasons (closed four-item set)

`spec_halted: true` is set exclusively by `flip_gate.halt_asset` / `flip_gate.halt_asset_text` — the single writer, regardless of which component calls it. Every caller passes a `reason` string drawn verbatim from the closed `HaltReason` class in `${CLAUDE_PLUGIN_ROOT}/bin/spec_keys.py`; no caller composes or invents a new phrase. The reason lands byte-for-byte in both the `# Gates` callout (`> [!failure] asset halted: <reason>`) and the `# History` line. Reproduced here exactly as the class defines them, in declaration order:

| # | `HaltReason` member | Phrase (verbatim) | Fired by |
|---|---|---|---|
| 1 | `JOB_DIED` | `job {job_id} ({label}) died` (format template, `job_id`/`label` substituted) | `gate_tick.py` (`apply_job_marker`) — an asset's active job bundle carries a `DEAD` terminal marker. |
| 2 | `MERGE_CONFLICT` | `change delta could not be applied cleanly to the feature docs` | `spec.coordinator`, via `flip-gate --halt` — a change-cascade job reports `conflict: true` (Part 4; `lazy-spec.expert-signals-protocol.md`) folding its delta into a target doc. |
| 3 | `PLAN_DROP_PARTIAL` | `plan drop left the asset half-cleaned` | `apply_request.py` (`_drop_attached_docs`, Part 6) on an attach drop step failure; `spec.coordinator`, via `flip-gate --halt`, on a cascade's own document-drop failure or a vanished cascade target (Part 4). |
| 4 | `GATE_PRECEDENCE` | `later gate true while an earlier gate is false` | The operator, by hand — the escalation `lazy-spec.audit` names as the alternative to turning the orphaned later gate back off on a gate-precedence FAIL. |

(The split-repo push-question / import-drift reasons — `DESIGN_DRIFT_ON_PUSH`, `IMPORT_DRIFT`, `NO_PUSH_ACCESS`, `PUSH_UNDELIVERED`, `IMPORTED_EDITED` — were removed with the `push_question.py` / `import_specs.py` channel they served.)

Un-halting (`spec_halted: false`) is always a manual operator edit — no worker ever clears the flag on its own. While `spec_halted: true`, the coordinator's own reasoning hangs no checkbox and dispatches no cascade job (playbook § 1), but the five gate booleans themselves are left exactly as they were — `spec_halted` silences the automation layers built on top of the gates, never the gates.

## Part 6 — Attach drop (a request attaching with documents to drop)

**Conditional chapter — read `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.attach-drop-playbook.md` when a request's routing resolves to an ATTACH target whose attach line names documents in `drop=`, BEFORE any of them is deleted.** An attach never flips a gate, for any asset type: `spec_design_done` and `spec_released` keep their values — and so do `spec_plan_done`, `spec_develop_done`, `spec_tests_passing` and `spec_built`, which exist on a release note only — and `spec_released` turns off only later, on re-approval of the start document. What `lazy-spec.request-apply` does before seeding the attach delta (`lazy-spec.request-protocol.md` § Body distribution rules, point 2) is delete the documents the attach line's own `drop=` names, so the request does not land on top of in-flight planning work a fresh design change is about to revise. Whether a request attaches at all, rather than spawning a change that names the asset via `targets=`, is the operator's tick on the request's routing `[!question]`; apply never refuses an attach because of implementation signals. The extracted Part carries the unconditional halted- and cancelled-target refusals, and the ordered steps — cancel the active job, stop review, drop the named documents, seed and reopen review through `start` — each with the halt-and-abort rule that governs a failure at that step. An attach with an empty `drop=` deletes nothing and cancels nothing, and this summary is all this Part contributes.

## A narrated example — design approved → a launch checkbox dispatches

**Moved out — read `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.lifecycle-example.md`** for the end-to-end narration: one asset walked from a review approval through stage promotion, the gate flip, checkbox reconciliation, the operator's tick, dispatch, `job-done`, and the next approve — every link a `spec.coordinator` decision over an unconditional primitive, and every operator arrow a full commit-push-pull round trip. It illustrates the shapes this protocol contracts; nothing normative lives there.
