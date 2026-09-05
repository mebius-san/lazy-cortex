---
chapter_type: faq
summary: Answers to common questions about products, assets, vision/design docs, gates, requests, decisions, coverage gaps, spec lookups, and the coordinator agent.
last_regen: 2026-09-05
no_diagram: true
source_skills:
  - lazy-spec.install
  - lazy-spec.product-config
  - lazy-spec.doctor
  - lazy-spec.create-asset
  - lazy-spec.create-feature
  - lazy-spec.create-change
  - lazy-spec.create-bug
  - lazy-spec.create-from-code
  - lazy-spec.create-request
  - lazy-spec.add-asset-type
  - lazy-spec.record-decision
  - lazy-spec.flip-gate
  - lazy-spec.gate-tick
  - lazy-spec.set-stage
  - lazy-spec.sync-with-code
  - lazy-spec.rebase-pins
  - lazy-spec.coverage
  - lazy-spec.upstream-run
  - lazy-spec.resolve-repo
  - lazy-spec.source-url
  - lazy-spec.lookup
  - lazy-spec.coordinator
  - lazy-spec.drive
  - lazy-spec.refresh-sources
  - lazy-spec.request-classify
  - lazy-spec.request-find-candidates
  - lazy-spec.resolve-dependency
source_sha: 8cf0ec8412bf97623e74bdf4d6a5cba5b82d957f
---
# Frequently asked questions

## Do I need to run anything before registering my first product?

Yes — run `/lazy-spec.install` once per project (or once globally, if you want the plugin available everywhere). It ensures the per-type template-override directories exist, seeds the repo's authoring language (asks only if none is on record), registers the `lazy-spec.gate-tick` and `lazy-spec.coordinator-watch` daemon routines — the pair that clears finished job markers / structurally checks each note and hands operator activity to `spec.coordinator`, which is what actually decides and flips gates — and wires the requests-inbox runtime (open / apply routines, the request-routing expert, and its review class) at project scope. At project scope it also seeds a draft of the **vault spec** — the project-wide `vision.md` at the spec content-root, instantiated from the `vault-vision.md` template — whenever neither it nor a pre-existing `design.md` without a vision (the legal pre-vision state, migrated by the operator by hand) is already there; this file is now mandatory groundwork, not an optional nicety, because `/lazy-spec.product-config` refuses to register your first product while both are absent — the split into products is a consequence of the repo-wide spec. It's idempotent — re-running it is always safe and never overwrites config you've customized since. At the end it offers to chain straight into `/lazy-spec.product-config` so you can register your first product in the same pass, or you can skip and run that separately whenever you're ready.

---

## What is a "product" and do I need one before I can create any assets?

Yes — a product must be registered first. A product is the top-level unit in the spec system: it has a folder path in the vault, an optional binding to a source-code repo, a language setting that controls what language the plugin uses for narrative prose, and optional per-product `asset_types` / `tool_types` declarations that extend the kinds of asset and the tools the plugin ships with.

Run `/lazy-spec.product-config` to register a new product. The wizard asks for the product's folder name, its place in the vault, whether there is source code to bind, which review experts (use-case-writer / designer / system-designer / architect / ui-designer / planner / developer / tester / data-writer) should handle each doc type, and any dependencies. Every product gets an icon — decline the question and the wizard falls back to a default (`LiPackage`) rather than leaving the folder-note unpainted. Once the product is saved, `/lazy-spec.create-feature`, `/lazy-spec.create-change`, `/lazy-spec.create-bug`, and the universal `/lazy-spec.create-asset` will accept it by name — attempting to create an asset under an unregistered product refuses with a message pointing you back to `/lazy-spec.product-config`.

---

## Can I generate a product's spec from an existing codebase instead of writing it by hand?

Yes, for a product that is already registered with a source binding. Run `/lazy-spec.create-from-code <product>` — it scans the source in parallel, then authors the product's `vision.md` (goals and value, from the code's evidenced outcomes) when one doesn't already exist, followed by a behaviour-only product design doc and a code-grounded product tech doc, complete with the primary behavioural and architecture diagrams. It also surfaces feature-candidates it found in the code and, per candidate, asks whether to scaffold a full feature (delegating to `/lazy-spec.create-asset`, which seeds its own `vision.md` + `design.md`), record it only as an architectural area inside the tech doc, or skip it.

The skill requires the product to already carry a `source` binding — register that first with `/lazy-spec.product-config`. On a design-only product (no source attached) it no-ops rather than guessing at code that isn't wired in.

---

## What is `system-design` / `system-tech`, and is there a spec for the whole project, not just one product?

Yes, at three levels. Every asset type that carries a `vision` contract gets its own `vision.md` — goals, value, one-screen "what this is and for whom" (the asset's goals live ONLY here) — ahead of `design.md`, which opens with a reference back to the sibling vision instead of restating goals. The same vision-then-design pairing repeats one level up, at the product root, and one level further up still, at the vault's content-root (the `spec.vault_root` setting, default `specs/`), describing the whole project above every individual product. This is the **vault spec**, and `vision.md` is now its anchor: `/lazy-spec.install` seeds a draft there automatically (project scope only, from the `vault-vision.md` template) whenever neither it nor a pre-vision `design.md` already exists, and `/lazy-spec.product-config` refuses to register a product while both are absent — the split into products is a consequence of the repo-wide spec. A `design.md` present without a sibling `vision.md` is the legal pre-vision state (a vault migrated before the vision document existed); the plugin never seeds over it, only the operator migrates it by hand. `/lazy-spec.doctor` flags a vault carrying neither file as `[WARN] vault-spec-missing`, and a pre-vision vault as `[INFO] pre-vision vault`; re-run `/lazy-spec.install` to seed the missing draft.

Every product's own `design.md` + `tech.md` pair — loose at the product root, not inside any asset folder — is typed `system-design` / `system-tech` rather than the asset-level `design` type feature/change/bug docs carry; the same three-doc set (`vision.md`, `design.md`, `tech.md`) can also exist loose at the content-root, typed `system-vision` / `system-design` / `system-tech` exactly like the product-root copy. The content-root `tech.md` half stays entirely optional and is never auto-created — write it by hand (copying the plugin's own `system-tech.md` template) whenever the project wants one.

Review-wise, a `system-designer` expert writes both the `system-vision` and `system-design` classes (each covering the product-root and content-root copy), and an `architect` expert writes the `system-tech` class, distinct from the asset-level `designer` (writes a feature/change/bug's own `vision.md` and `design.md`) and from `architect`'s other job of writing opt-in `architecture.md` code-structure docs. `system-vision` (like the asset-level `vision` class) carries no validators — the writer and the operator close the loop — while `system-design` keeps an `architect_review` validation slot, same as the asset-level `design` class. These are among the nine roles `/lazy-spec.product-config` Step 8 asks for. `/lazy-spec.create-from-code <product>` still scaffolds the product-level `vision.md` → `design.md` → `tech.md` trio for a code-bound product (see above) — the content-root, project-wide `vision.md` gets its draft from `/lazy-spec.install` instead, and `tech.md` at that level still has no dedicated creation skill.

---

## What is the difference between a feature, a change, and a bug?

All three are assets — they share the same gate ladder and folder layout — but the problem they capture is different. A **feature** describes new behaviour that does not yet exist. A **change** is the atomic modification of something that already exists: a rename, a constraint relaxation, a behaviour adjustment. A **bug** describes a defect: what was supposed to happen, what happened instead, and how to reproduce it.

The document layout differs too. Features and changes get `design.md` (no `bug.md`); bugs get `bug.md` (no `design.md`, and no `vision.md` either — the shipped `bug` type declares no vision contract at all). A feature's `vision` contract is `mandatory` — `vision.md` is seeded automatically ahead of `design.md`. A change's `vision` contract is `opt-in` — offered via a multi-select question at scaffold time, alongside `use-cases.md` / `ui-design.md`, and can still be added later if declined up front. Either way, the scaffold seeds only what the type's contract calls for — `code-plan.md` and `test-plan.md` are opt-in, authored later, never part of the scaffold. `/lazy-spec.create-feature`, `/lazy-spec.create-change`, and `/lazy-spec.create-bug` are thin wrappers that pin the asset type and delegate to the universal `/lazy-spec.create-asset`, which asks type-scaled clarifying questions, authors the prose, and draws the primary behavioural diagram(s).

---

## Does every asset get a `vision.md`, or is it optional?

Depends on the asset's declared type. A type's `vision` contract is one of three shapes: `mandatory` (the shipped `feature` type — `vision.md` is seeded automatically ahead of `design.md`, and the `Write design` checkbox does not even appear until `vision.md` reaches `approved`), `opt-in` (the shipped `change` type, plus `content` / `research` — offered through a multi-select question at scaffold time alongside `use-cases.md` / `ui-design.md`, and can still be added later), or absent entirely (the shipped `bug` type declares no vision at all — a `bug.md` captures repro/observed/expected, not goals). `vision.md` covers `Overview / Goals / Requirements / Value Proposition / Design Concept` — the asset's goals live ONLY here, never restated in `design.md`, which opens instead with a reference back to the sibling vision and covers what the asset does in behaviour terms. `Requirements` states the obligations the solution must satisfy — each one a single, verifiable statement free of implementation detail (the canonical shape behind the section is "condition, subject, action, object, constraint" per ISO/IEC/IEEE 29148, the same standard `design.md`'s own sections now cite inline) — never a to-do list of tasks. `design.md` does not restate or "work within" those requirements as its own section; instead it carries a separate `## Constraints` section of its own, holding a different thing entirely — facts of the environment and decisions taken elsewhere (a platform limit, a prior architectural commitment) that narrow the design's freedom, distinct from the needs the vision's `Requirements` obliges it to satisfy. `vision.md` carries no `Risks` section: risks are worked in the sibling `design.md`'s own `## Risks` section instead, stating what could sink the design and what it does about each. Both `/lazy-spec.create-asset` (and its thin wrappers `create-feature` / `create-change` / `create-bug`) and `/lazy-spec.create-from-code` author `vision.md` first when the type calls for it, and both mark any genuine decision fork the vision or design settles as an inline `[!decision]` callout, ready to `promote` into the decisions registry once the doc is approved.

---

## Can I add use-cases or a UI-design pass to a feature or change before architecture is written?

Yes, on both feature and change assets. `use-cases.md` (written by the use-case-writer) captures actor-level scenarios — main and alternative flows in the user's own language, no system internals — and `ui-design.md` (written by the ui-designer) settles screens, states, and interaction decisions, with self-contained HTML mockups attached beside it; neither ships production code. Both are opt-in: neither is part of `/lazy-spec.create-asset`'s scaffold, and each appears only once its own launch checkbox (`Write use-cases`, `Write ui-design`) is ticked — unless the product or the asset declares it mandatory.

Both hold the step after them, and `vision.md` (where the type declares it) holds ahead of both. The reading chain is `vision → use-cases → design → tech`: a document's review proceeds only once every EXISTING upstream sibling in that chain has reached `approved` — an absent opt-in document never blocks, so a change that declined `vision.md` and `use-cases.md` goes straight to `design.md`. Concretely: on a `feature` (mandatory vision), the `Write design` checkbox does not even appear until `vision.md` is `approved` — the coordinator seeds and starts the vision itself, on the asset's first wake, ahead of any checkbox. Once `design.md` exists, it is not dispatched (or continued) while a `use-cases.md` sibling exists and hasn't yet reached `approved` or `cancelled` — the use cases are meant to settle before the behaviour they describe is written down for good. `Write architecture` doesn't queue until `ui-design.md` is absent, `approved`, or `cancelled` — the screens are meant to be cast before the module boundaries built to serve them. Once each gap closes, dispatch resumes as an ordinary launch-checkbox job, no special-casing.

Each window closes on its own schedule: `vision.md` itself closes the moment `spec_design_done` closes (a late goals revision past that point is a change asset's business, not this asset's own definition half), `Write use-cases` closes at the same point, and `Write ui-design` closes once `architecture.md` is approved (or, for an asset that never becomes code, once `spec_plan_done` closes instead). Past any window a further revision belongs to a new change asset, not a reopening of this one. An edit landing on `vision.md`, `use-cases.md`, or `ui-design.md` after the document it feeds has already approved triggers no automatic rewrite — the coordinator drops an `[!attention]` callout into the downstream document and names the edit in `# Status brief`, leaving the decision to fold it in with you.

`/lazy-spec.product-config` Step 8 assigns the use-case-writer and ui-designer roles alongside the other seven, and generates their `use-cases` / `ui-design` review classes the same way it generates every other doc-kind class.

---

## Can the plugin track non-software work — characters, scenes, chapters?

Yes, as long as the asset type has been declared on the product. Run `/lazy-spec.add-asset-type <product> <type>` — a wizard that settles the type's key and whether it stands alone or aliases an existing type's playbook, its icon and optional color, the one document a fresh asset of it starts from, its default tools (preset, explicitly none, or left for the coordinator to determine), the folder new assets land in, and — unless it aliases another type — the playbook the coordinator works assets of that type under. It writes all of that into `products[<key>].asset_types.<type>`, plus (only if you choose to write your own playbook rather than borrow a shipped one) a playbook stub under `.claude/references/`. It creates **nothing else** — no type folder, no folder-note, no templates. The folder appears the first time an asset of that type is scaffolded. Once declared, `/lazy-spec.create-asset <product> <type> <slug>` accepts it; naming a type that has not been declared is refused, with the refusal naming the type and the product and pointing you at `/lazy-spec.add-asset-type`.

Once a type exists on the product, `/lazy-spec.create-asset` scales its clarifying questions to it, grounded in the type's playbook rather than in templates of its own — a type needs none, because every document resolves from the plugin's per-doc-type base templates. The result behaves identically to a feature: five gates, the same folder-note shape, the same review flow. The asset's kind is the `spec_asset_type` key on its own status folder-note, not the folder it sits in, so assets of a type may be placed anywhere under the product — including inside another asset's folder. A type's docs are covered automatically by the product's existing behaviour-keyed review classes (their globs already span every asset folder) — declaring a type never touches `review.classes`.

---

## What are the five gates and how do they advance?

Every asset has five flat boolean gates on its status folder-note: `spec_design_done`, `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, and `spec_released`. They form a strict linear ladder — each gate requires every earlier gate to be true before it can be flipped on.

The first two (`spec_design_done`, `spec_plan_done`) are **derived**: readiness follows mechanically from doc state (the corresponding doc — `design.md` or `bug.md`, then `code-plan.md` if one was authored, its absence already satisfying the second gate — reaching `spec_stage: approved`). The last three are **human-signal** gates: readiness needs an external condition (deploy landed, tests are green, branch merged) nothing can derive from doc state alone. Deciding when either kind is ready, and calling `/lazy-spec.flip-gate` to move it, is `spec.coordinator`'s job — it wakes on a commit that changes the asset's folder-note, clears its active-job marker, or lands a review approval on one of the asset's own docs (`design.md`, `code-plan.md`, ...) once that commit reaches the daemon's own checkout, reasons from its playbook set, and narrates what it's waiting on in `# Status brief`. Because the daemon typically runs in a different checkout than the one you edit in, a wake needs your gesture committed AND pushed first, and the coordinator's own answer needs its commit pushed and pulled back to you — not an instant round trip. To flip any gate manually yourself, run `/lazy-spec.flip-gate <asset> <gate>`; the skill confirms with you, then the primitive performs the flip unconditionally (it no longer checks the gate's readiness itself — only a cancelled asset is refused).

---

## How do I move an asset forward — do I edit the gate frontmatter directly?

No. Gate frontmatter is managed entirely by `/lazy-spec.flip-gate` (interactive, or `spec.coordinator` calling it non-interactively once it decides a gate is ready — `lazy-spec.gate-tick` itself no longer touches a gate at all). Editing it by hand bypasses the side-effects — the callout, the `# History` line — that the primitive writes on every flip. Always use `/lazy-spec.flip-gate` for a manual flip; pass `--off` to regress a gate.

Similarly, a doc's per-file stage (`spec_stage` on `vision.md`, `use-cases.md`, `design.md`, `ui-design.md`, `code-plan.md`, `test-plan.md`, `bug.md`) is always changed through `/lazy-spec.set-stage`, never by hand-editing frontmatter. That skill rewrites `spec_stage`, mirrors the matching `spec/<stage>` tag in the same edit, and appends a transition line to the folder-note's `# History` section — the two writes never happen separately.

---

## Does `/lazy-spec.set-stage` also touch a doc's markdown attachments?

Yes, automatically. A markdown attachment — a file carrying `spec_owner_doc` pointing back at the doc, e.g. a note an expert dropped beside `design.md` — has no per-file stage of its own: `/lazy-spec.set-stage` cascades the new `spec_stage` and its `spec/<stage>` tag onto every sibling attachment in the same commit, skipping only an attachment that is currently in its own review (the coordinator re-stamps that one once its review finalizes). You can't target an attachment directly — running the skill on one refuses with "document is an attachment of `<owner>`" and points you at the owner document instead.

---

## I ran `/lazy-spec.flip-gate` but the gate refuses to flip. What is blocking it?

The primitive checks exactly one thing on its own: whether the asset is cancelled. `spec_cancelled: true` freezes every gate in either direction — uncancel the asset before flipping. Every other precondition is no longer enforced by the primitive itself; it will flip whatever you ask, so an out-of-order flip is a mistake it will not catch for you. Before flipping by hand, wait instead — if the underlying condition genuinely isn't met yet, `spec.coordinator` won't have flipped it either, and its reasoning (surfaced in the asset's `# Status brief`) says why.

---

## Why did my asset's `spec_design_done` gate flip on its own?

`spec_design_done` and `spec_plan_done` are derived gates, not something you flip by hand. Once `design.md` (or `bug.md`) reaches `spec_stage: approved` and that approval commit has reached the daemon's own checkout, `spec.coordinator` wakes directly off that approval — the daemon also watches sibling docs, not only the asset's own status folder-note, so approving `design.md` reaches the coordinator on its own, no other folder-note activity or manual nudge required. The coordinator promotes it via `/lazy-spec.set-stage`, sees the corresponding gate's readiness now holds, and calls `/lazy-spec.flip-gate --auto` itself. The same mechanism handles `spec_plan_done` once `code-plan.md` is approved and pulled in (or immediately, if you never authored one — it's opt-in). The flip itself is committed under the coordinator's own identity and only becomes visible in your own checkout once you pull it back. For the three human-signal gates it does no flip of its own — it narrates what it's waiting on in `# Status brief`, and you (or an upstream signal like `/lazy-spec.sync-with-code`) flip them manually via `/lazy-spec.flip-gate`. `lazy-spec.gate-tick`, the background daemon worker, is uninvolved in any of this — it only polls active-job markers and structurally checks the note.

---

## Can I ask `spec.coordinator` something directly, or does it only react to gate transitions?

Yes, two ways, both on the asset's own folder-note. Write anything into its `# Coordinator commands` section and the coordinator treats it as an operator instruction the next time it wakes on that asset — it unfolds your ask into a numbered mini-plan in the same section, marking each step's progress, and moves the whole plan into `# History` once every step finishes (or locks it there with what failed, if one step doesn't). A command runs even on a halted asset — halt only silences automatic dispatch, never a direct instruction.

The second way is answering one of the coordinator's own `[!question]` callouts — tick the option you want and it acts on that answer, then removes the callout and records the choice in `# History`. Both surfaces are the coordinator's own pen; you never need to hand-edit the rest of the note to get its attention. When a decision doesn't follow unambiguously from its playbook and the rule layers in scope, the coordinator does not guess or act "just in case" — it raises exactly this kind of `[!question]` with concrete options and stops on that asset until your tick.

A product folder-note and every container folder-note under it (`features/`, `changes/`, `bugs/`, and any folder you add) may also each carry their own `# Coordinator rules` section — the coordinator reads the whole chain top-down (playbook, then the product note, then every container note down to the asset, then the asset's own `# Coordinator rules`) before it decides anything on that asset. Writing a constraint at the product or container level applies it to every asset underneath without repeating it on each one; leaving the section empty (or absent) is normal until you actually need a group-wide rule.

---

## Can I drive an asset through its gates without the daemon running?

Yes — run `/lazy-spec.drive <asset-note-path>` (or a bare `<category>/<slug>` shorthand; with no argument at all it lists every live asset and asks you to pick one). It is a no-daemon session orchestrator: on a checkout where the runtime daemon isn't acting on this asset, it drives the whole ladder in one continuous session by reading the same `lazy-spec.coordination-playbook.md` law `spec.coordinator` follows under the daemon. You speak a word — tick a checkbox, answer a `[!question]`, write a `# Coordinator commands` line — and the skill translates it into the exact gesture an operator would make (never a decision of its own), commits it, wakes the coordinator through the same CLI the daemon's git-watch routine uses, and pumps whatever expert job results to completion with a local manual pump, looping until the ladder settles. It refuses to start while a live daemon could act on the same checkout — the two are mutually exclusive against the same asset, never run in parallel.

---

## How do I record a design decision, and does the plugin write `decisions.md` for me?

Never by hand-editing `decisions.md` — always through `/lazy-spec.record-decision`, an interactive wrapper over four operations: `add` a new entry, `supersede` an older one with a new entry that marks it superseded, `obsolete` an existing entry with a reason, or `promote` — transfer decision blocks already written inline in a `vision.md` / `design.md` / `bug.md` / `tech.md` / `architecture.md` body out into a sibling `decisions.md` registry. `decisions.md` itself lives at one of three levels, resolved along a placement ladder: `<asset_dir>/decisions.md` for a feature/change/bug's own forks, `<spec_path>/decisions.md` for a product-wide decision, or `<content-root>/decisions.md` for a decision about the project as a whole (the system pair, or a cross-product concern) — the file need not exist yet at any level; the first record lazily creates it. Before recording a new decision, the skill holds you to a three-part weight test: a real fork existed, reversing it is expensive, and the "why" is unrecoverable from the artifact itself — a cheap, reversible, or self-explanatory detail isn't worth a record; per `spec.decisions.md`, the Why/Rejected reasoning belongs only in the decision record, never restated in the surrounding design prose.

Most decision blocks never need the manual `add` path. `/lazy-spec.create-asset` and `/lazy-spec.create-from-code` already mark a genuine fork the clarification or the code evidence settles — while authoring `vision.md`, `design.md`, or the product-level docs — as an inline `[!decision] <thesis> #spec/decision` callout with its `**Why.**` / `**Rejected.**` lines, right where the fork was made. `promote` then happens automatically too: once a living doc (`vision.md`, `design.md`, `bug.md`, `tech.md`, `architecture.md`) is approved via `/lazy-spec.set-stage`, that step calls the same promote operation itself, lifting those inline blocks into the sibling registry without you running `/lazy-spec.record-decision` at all — the manual path exists for adding a decision straight into the registry, or for promoting a doc that skipped the usual approve step. A `promote` call refuses on a plan or report (neither originates decisions), and on a cancelled, halted, or released asset.

---

## What does `/lazy-spec.sync-with-code` actually change?

It compares the source commits that landed since the last sync against the product's tech doc and proposes updates for anything that changed at the code level — new routes, renamed functions, new files, removed components, changed constants. It never silently rewrites files: every tech-doc edit is presented for approval first, and any change that looks user-visible is flagged as a candidate for the product design doc for you to decide on separately.

After the tech-doc pass it also reconciles branch pins (source links still pointing at a feature branch that has since merged or been deleted) and, per asset, proposes a `spec_develop_done` flip when the synced commits objectively landed that asset's code on the default branch — always via a confirmation, never silently. The skill no-ops on a design-only product that has no source binding, and it always finishes by running `/lazy-spec.doctor` so you see whether the sync introduced any structural issues.

---

## How do I release an asset after its branch merges?

Run `/lazy-spec.rebase-pins <branch>` after merging or deleting the source branch. The skill fetches fresh refs, finds every spec whose `spec_source_branches` frontmatter pins that branch, rewrites those source links to the default branch, and then proposes the `spec_released` gate flip for each affected asset via `/lazy-spec.flip-gate` — but only when its own check finds the release readiness already met (typically `spec_tests_passing` already `true`); `/lazy-spec.flip-gate` itself no longer double-checks this. When it isn't met yet, the skill skips the proposal for that asset instead — the link rebase is applied regardless, so you only need to settle the holding gate and re-run.

For squash-merges, where the ancestor check comes back false, pass `--force-merged` to skip it. To reconcile every merged branch across the vault in one pass, run `/lazy-spec.rebase-pins --merged`.

---

## How do I find capabilities my code already has that the spec tree doesn't cover yet?

Run `/lazy-spec.coverage <product>` on a code-bound product. It reads the code side from two existing knowledge maps — the structure map and the domain-group tree, each queried for bounded slices rather than swallowed whole — compares that against what the spec tree already documents (every status folder-note's `# Summary` line), and reports uncovered capabilities as a gap list, each with a proposed category (`feature` by default, `bug` when the evidence looks like a defect, `change` when it modifies an already-documented asset) and a proposed slug.

Nothing is written to the spec tree without you confirming it — per gap, you're asked whether to materialize it via `/lazy-spec.create-from-code`, get a printed `[!asset-proposal]` block to paste into a living doc yourself, or skip it. On a design-only product (no source binding) it reports plainly that there's nothing to gap-scan rather than inventing a comparison. When neither knowledge map is configured for the repo yet, it still runs a shallow fallback scan over the source tree so the report isn't empty for no reason.

---

## Can I pull design content from another repo instead of writing everything locally?

Yes, via the `spec` settings section's `upstream` sub-key — a configured foreign git repo mirrors into `upstream/<repo-key>/` outside your product hierarchy. Every mirrored unit gets its own note with a live status (`new` / `drifted` / `in-review` / `postponed` / `processed` / …); ticking its `# Actions` checkbox turns the current state into a request that the usual review-and-routing loop carries into as many asset spawns, attaches, or `reference` links as the design actually needs, in whichever products it belongs to. Run `/lazy-spec.upstream-run` to force a fetch/detect pass now — it mirrors and diffs every configured unit, opens a request for any unit whose checkbox was ticked in a prior commit, and unfreezes an `in-review` unit once its linked request's review has concluded — or let the daemon-registered `lazy-spec.upstream-tick` routine do the same pass on a schedule; running the skill by hand and waiting for the routine produce identical results. It never dispatches an expert job itself — a landed request enters the standard review pipeline on its own schedule. Configuration is a hand-edit of the `spec` settings section's `upstream` sub-key.

---

## What is the requests inbox and how does an idea become an asset?

The vault-root `requests/` folder is the intake inbox. Run `/lazy-spec.create-request` with a raw idea; the skill asks three to five wizard questions to clarify scope, outcome, and constraints, then writes a body-only Markdown file at `requests/<slug>.md` — it never sets frontmatter itself, that lands automatically once the request enters the review loop.

Once the request body is approved during review, `spec.coordinator` wakes at the terminal group of that review cycle and takes over the routing: it classifies the idea, checks the vault for existing assets it could attach to or an asset that already implements it, and always surfaces its proposed routing — spawn a new asset, attach to an existing one, mark an asset that already covers it as the reference (with its reasoning stated in the same block), or a mix — as an explicit `[!question]` confirmation you tick before anything is materialized. You can also edit the proposed routing block directly instead of just accepting or rejecting it.

Applying the decision never seeds document prose anywhere. A **spawn** creates only the asset's folder and its status folder-note, carrying the request's attribution — no `vision.md`, no `design.md`, no review opened yet. Every document the asset gets, `vision.md` and `design.md` included, is created later, one launch-checkbox tick at a time: ticking a `Write <doc>` checkbox seeds an empty skeleton at stage `empty`, copies the folder-note's request attribution onto it, and opens review on it. An **attach** works the other way — it stamps the request's attribution onto the existing target's own primary doc (`design.md` for a feature/change, `bug.md` for a bug) and re-opens review on that doc, without touching its existing content. Either way, the request body itself is never copied into any doc, whole or in sections — the doc's own review writer reads the linked request directly from its job context when it drafts the real prose. A **reference** decision writes nothing onto the target at all — it just links the request to the asset that already covers it. The whole pipeline runs without you hand-editing any frontmatter.

---

## Source links in my tech doc point at the wrong forge URL format. How do I fix that?

Every source URL in the spec system is built by the `lazy-spec.source-url` primitive from a known-forges table (GitHub, GitLab, Bitbucket, Gitea, Forgejo, SourceHut) — never inlined as a hard-coded `/blob/<branch>/<path>`. Run `/lazy-spec.doctor <product>` to find links that were not produced that way; it reports every source link whose format doesn't match, or whose branch segment doesn't match the file's pin or the repo default.

If the underlying repo record is missing or the remote's hostname isn't recognized, `lazy-spec.resolve-repo` — the primitive `lazy-spec.source-url` calls to get the repo's base URL and forge — aborts with a message describing the gap. Fix the repo record by running `/lazy-spec.product-config` (it writes the `repos` entry), then re-run the sync or creation skill that emits the source links.

---

## `/lazy-spec.doctor` is reporting "old-model artifact" on my status folder-note. What does that mean?

An older version of the plugin used a `gates:` dict, a `stage:` key, an `awaits_human:` field, or a `## Workflow` section on asset folder-notes. The current model uses five flat boolean fields directly on the folder-note frontmatter (`spec_design_done`, `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, `spec_released`) plus the `spec_cancelled` overlay. `lazy-spec.doctor` treats any of the old-model fields as a hard error rather than trying to migrate them — there is no migration path, only a strip.

Re-run `/lazy-spec.doctor <product> --apply` — the fix loop offers to strip the obsolete fields per finding, with a confirmation before each write.

---

## I registered a repo but `lazy-spec.resolve-repo` still aborts with "unknown forge". How do I fix that?

`lazy-spec.resolve-repo` detects the forge from the remote URL's hostname against a built-in known-forges table (GitHub, GitLab, Bitbucket, Gitea, Forgejo, SourceHut). When you run a self-hosted instance on a custom hostname not in that table, auto-detection fails. Add an explicit `forge: <key>` to the repo record — run `/lazy-spec.product-config` and re-attach the source, or edit the product's source step, supplying one of the supported forge keys (`github`, `gitlab`, `bitbucket`, `gitea`, `forgejo`, `sourcehut`). Once the record carries the override, resolution and URL construction both work normally.

---

## How do I get an answer from the spec tree without loading whole documents into context?

Run `/lazy-spec.lookup` with a query and an optional anchor — a product key, a vault-relative path, or a `<category>/<slug>` pair. It walks the spec tree in three bounded directions from that anchor — up toward the vault root (the asset's own summary, then the owning product's design/tech docs), down through declared dependencies and materialized links, across to sibling assets and backlinks — and returns matching paths with a one-line excerpt each, never a whole document. This is the primitive an expert's research pass, a subagent gathering context before writing, or you asking "where does X live in specs" should reach for instead of grepping the tree by hand; it works from inside a one-shot dispatch too, since it never fans out to further subagents itself. With no anchor at all it falls back to a vault-wide search on the query token.

---

## My product is design-only — do I really need the full architecture/plan/implementation/test ladder for every asset?

No. Set `/lazy-spec.product-config`'s workflow-mode step to `spec-only` (edit mode works on an existing product too) and every asset under that product stops once its `design.md` is approved — no `architecture.md`, no `code-plan.md`/`test-plan.md`, no implementation or test checkboxes ever hang. The coordinator releases the asset on your own word instead of a checkbox completing.
