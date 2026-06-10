---
chapter_type: faq
summary: Answers to common questions about products, gates, assets, requests, code sync, and the request pipeline in lazycortex-specs.
last_regen: 2026-06-10
no_diagram: true
source_skills:
  - spec.create-asset
  - spec.create-feature
  - spec.create-change
  - spec.create-bug
  - spec.add-asset-category
  - spec.create-from-code
  - spec.create-request
  - spec.flip-gate
  - spec.gate-tick
  - spec.set-stage
  - spec.sync-with-code
  - spec.finalize-branch
  - spec.resolve-repo
  - spec.resolve-dependency
  - spec.source-url
  - spec.request-router
  - spec.request-classify
  - spec.request-find-candidates
  - spec.request-attach
  - spec.request-spawn
  - spec.install
  - spec.product-config
  - spec.doctor
  - spec.help
---
# Frequently asked questions

## What is a "product" and do I need one before I can create any assets?

Yes — a product must be registered first. A product is the top-level unit in the spec system: it has a folder path in the vault, an optional binding to a source-code repo, and a language setting that controls what language the plugin uses for narrative prose. Every asset (feature, change, bug, or any operator-defined category) lives under a product.

Run `/spec.product-config` to register a new product. The wizard asks for the folder location, whether there is source code to bind, and which review experts should handle each doc type. Once the product is saved, `/spec.create-feature`, `/spec.create-change`, and `/spec.create-bug` will accept it by name.

---

## What is the difference between a feature, a change, and a bug?

All three are assets — they share the same gate ladder and folder layout — but the problem they capture is different. A **feature** describes new behaviour that does not yet exist. A **change** is the atomic modification of something that already exists: a rename, a constraint relaxation, a behaviour adjustment. A **bug** describes a defect: what was supposed to happen, what happened instead, and how to reproduce it.

The document layout differs too. Features and changes get `design.md` + `plan.md`; bugs get `bug.md` + `plan.md` (no `design.md`). You can reach for `/spec.create-feature`, `/spec.create-change`, or `/spec.create-bug` directly, or use the universal `/spec.create-asset` and specify the category yourself.

---

## I want to track characters, scenes, or chapters — can the plugin handle non-software work?

Yes. Run `/spec.add-asset-category` on your product to declare an operator-defined category (e.g. `characters`, `scenes`, `chapters`). The skill writes the category into the product's settings record, scaffolds the category folder and its folder-note, seeds local template files so you can customise the design and plan structure for that category, and wires the design and plan review classes so the review daemon picks up docs of that type automatically.

Once registered, `/spec.create-asset <product> characters <slug>` works the same way as `/spec.create-feature`. The request classifier also recognises operator-defined categories on the next run without any rubric update.

---

## What are the five gates and how do they advance?

Every asset has five flat boolean gates on its status folder-note: `spec_design_done`, `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, and `spec_released`. They form a strict linear ladder — each gate requires every earlier gate to be true before it can be flipped on.

The first two (`spec_design_done`, `spec_plan_done`) are **derived**: the daemon's `spec.gate-tick` routine flips them automatically when the corresponding doc (`design.md` / `plan.md`) reaches `spec_stage: approved`. The last three are **human-signal** gates: the daemon drops a `[!ready]` callout in the asset's `## Gates` section prompting you to flip the gate once the external condition is actually met. To flip any gate manually, run `/spec.flip-gate <asset> <gate>`. The skill confirms with you before running the primitive, and the primitive enforces the precondition — it refuses cleanly if the ladder is not satisfied.

---

## How do I move an asset forward — do I edit the gate frontmatter directly?

No. Gate frontmatter is managed entirely by `/spec.flip-gate` (interactive) and `spec.gate-tick` (daemon-driven, automatic for derived gates). Editing the frontmatter directly bypasses the side-effects: the history line in `## History`, the log entry, and the tag mirror update. Always use `/spec.flip-gate` for manual flips.

Similarly, per-file stage (`spec_stage` on `design.md`, `plan.md`, `bug.md`) is always changed through `/spec.set-stage` — not by hand-editing the frontmatter. That skill rewrites both `spec_stage` and the `spec/<stage>` mirror tag in a single atomic edit, and appends a transition line to the folder-note's `## History`.

---

## My asset's gate won't advance even though I ran `/spec.flip-gate`. What is blocking it?

The flip primitive enforces preconditions. The most common blocks are:

- **`spec_design_done` won't flip** — `design.md` (or `bug.md` for a bug) is not yet `spec_stage: approved`. Get the doc through its review cycle and approved first, then the daemon's `spec.gate-tick` routine will auto-flip it on the next tick.
- **`spec_plan_done` won't flip** — `plan.md` is still `draft` or `empty`. Approve the plan doc.
- **`spec_released` is refused** — the full ladder (`spec_tests_passing`, and below it `spec_develop_done`, `spec_plan_done`, `spec_design_done`) must all be true. The refusal message names which gate is holding the release up.
- **Asset is cancelled** — `spec_cancelled: true` freezes all gates. Remove the cancelled flag before flipping.

---

## What does `/spec.sync-with-code` actually change?

It compares the source commits that landed since the last sync against the product's tech doc, and proposes updates for anything that changed at the code level — new routes, renamed functions, new files, removed components. It never silently rewrites files: every proposed edit to the tech doc is presented for your approval before being applied, and any change that looks user-visible is flagged as a candidate for the product design doc (you decide whether to update that one).

After sync it also reconciles branch pins (source links that still point at a feature branch that has since merged) and proposes `spec_develop_done` flips for assets whose implementation landed in the source repo's default branch. The skill no-ops on a design-only product that has no source binding.

---

## How do I release an asset after its branch merges?

Run `/spec.finalize-branch <branch>` after merging or deleting the source branch. The skill fetches fresh refs, finds every spec whose `spec_source_branches` frontmatter pins that branch, rewrites those source links to the default branch, and then proposes the `spec_released` gate flip for each affected asset via `/spec.flip-gate`. If the release precondition is not yet met (typically `spec_tests_passing` is still false), the flip is refused cleanly and the rebase is applied regardless — you settle the holding gate later and re-run.

For squash-merges where the ancestor check returns false, pass `--force-merged` to skip the ancestor check. If you want to reconcile all merged branches in one pass, use `spec.finalize-branch --merged`.

---

## What does `/spec.create-from-code` do differently from `/spec.create-feature`?

`/spec.create-from-code` works at the product level and derives its content from the source code itself. It fans out parallel scan agents across the codebase to collect routes, classes, data structures, and hazards, then authors the product design doc (behaviour only, no source URLs) and the product tech doc (code-grounded, with forge-correct source links). It also identifies feature-candidate units in the source and lets you decide, per candidate, whether to scaffold a feature folder, document as an architectural area, or skip.

`/spec.create-feature` (and the other per-asset creation skills) work at the asset level: they scaffold one asset folder, ask clarifying questions about that one asset, author its `design.md`, and draw a behavioural diagram. Use `create-from-code` once at the start to bootstrap a product's spec from existing code; use `create-feature` for each new piece of planned work going forward.

---

## What is the requests inbox and how does an idea become an asset?

The `requests/` folder at the vault root is the intake inbox. Run `/spec.create-request` with a raw idea; the skill asks three to five wizard questions to clarify scope, outcome, and constraints, then writes a body-only Markdown file at `requests/<slug>.md`. Frontmatter is added automatically by the `spec.request-open` daemon routine on the next tick.

Once the request is in the review loop the `spec.request-router` agent classifies it (via `spec.request-classify`), searches for existing entities it might belong to (via `spec.request-find-candidates`), and surfaces a routing decision for you to confirm. If the request should attach to an existing feature or change, `spec.request-attach` distributes the body across that entity's docs and opens a fresh review cycle. If it spawns new work, `spec.request-spawn` scaffolds an empty entity and then delegates to `spec.request-attach` to populate it. The whole pipeline runs without you hand-editing any frontmatter.

---

## Can I add a request to an asset that already has approved docs?

Yes, but the attachment works differently depending on the target doc's stage. If the doc is `draft`, the content is appended flat. If the doc is `approved` (a frozen accepted artifact), `spec.request-attach` inserts the new content as diff blocks, moves the doc back to `draft`, and opens the review loop on the reviewer round directly — the diff is then reviewed and either accepted or rejected as an explicit delta against the approved body.

If the doc is `rejected` or `cancelled`, the attach is refused. Those are terminal stages: run `/spec.set-stage <doc> draft` to revive the doc first, then re-attach.

---

## Source links in my tech doc are pointing at the wrong forge URL format. How do I fix that?

All source URLs in the spec system are produced by the `spec.source-url` primitive, which looks up the forge-correct URL template from a known-forges table rather than inlining a GitHub-style `/blob/<branch>/<path>`. If a doc contains a hard-coded URL in the wrong format, run `/spec.doctor <product>` — Agent A reports every source link that was not produced by this primitive and flags links whose branch segment doesn't match the file's pin or the repo default.

If a repo key is missing from the `repos` settings section or has an unknown forge hostname, `spec.resolve-repo` will abort with a message describing the gap. Fix the repo record by running `/spec.product-config` in edit mode, which writes the `repos` entry. Once the record is correct, re-run the sync or the creation skill that emits source links.

---

## `/spec.doctor` is reporting "old-model artifact" on my status folder-note. What does that mean?

An older version of the plugin used a `gates:` dict, a `stage:` key, an `awaits_human:` field, or a `## Workflow` section on asset folder-notes. The current model uses five flat boolean fields directly on the folder-note frontmatter (`spec_design_done`, `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, `spec_released`). Any of the old-model fields are treated as errors by `spec.doctor`.

Re-run `/spec.doctor <product> --apply` — the fix loop will offer to strip the obsolete fields per finding, with a confirmation before each write.

---

## How do I see what lazycortex-specs can do without reading all the docs?

Run `/spec.help` — it prints the plugin's purpose and a one-line summary of every skill it ships.
