---
description: End-to-end narration of one asset cycle — design approved in review through gate flip, checkbox reconcile, tick, dispatch, job-done and the next approve — showing every link as a coordinator decision over an unconditional primitive. Companion walkthrough to the asset lifecycle protocol.
---
# A narrated example — design approved → a launch checkbox dispatches

Extracted from `lazy-spec.lifecycle-protocol.md`, where it closed the contract as a worked illustration: the protocol carries the shapes, this file walks one cycle through them. Every "Part N" cross-reference below names a Part of that protocol.

The old cross-layer chain in that file described a fully automatic sequence with no operator step in the middle. That sequence no longer exists as code — every link below is now a `spec.coordinator` decision, woken by a commit to the asset's folder-note that has reached the *daemon's own checkout* (`daemon.run_here` — never the operator's checkout, per the model-audit's Step 0 topology), reasoning from `lazy-spec.coordination-playbook.md` plus the playbooks the asset's own frontmatter names. Every arrow marked "operator" below is a full commit + push + pull round trip, not an in-process step:

`<specs-cli>` stands for the specs plugin's `bin/lazycortex-specs` file — the newest copy under `~/.claude/plugins/cache/lazycortex/lazycortex-specs/<version>/`, or `claude/lazycortex-specs/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

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
  → coordinator calls `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> flip-gate <asset> spec_design_done --auto`
       (unconditional flip; callout + history line + atomic commit — flip_gate's own work, Part 2)
  → coordinator reconciles the checkbox set the playbooks declare (the protocol's Part 3 is only
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
