---
chapter_type: faq
summary: FAQ on products, nested products, assets, vision/design docs, gates, requests, decisions, coverage gaps, and spec lookups.
last_regen: 2026-09-21
no_diagram: true
source_skills:
  - lazy-spec.install
  - lazy-spec.product-config
  - lazy-spec.audit
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
source_sha: b9cc732063fd5d0d05c3e9e7be1bb76cd38af2a6
surface_sha: 2f41e48dd0638f6e7e56dd55c64834877c582b80cd3590ab5dc1981639007ded
---
# Frequently asked questions

## Do I need to run anything before registering my first product?

`<specs-cli>` stands for the specs plugin's `bin/lazycortex-specs` file — the newest copy under `~/.claude/plugins/cache/lazycortex/lazycortex-specs/<version>/`, or `claude/lazycortex-specs/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

Yes — run `/lazy-spec.install` once per project (or once globally, if you want the plugin available everywhere). It ensures the per-type template-override directories exist, seeds the repo's authoring language (asks only if none is on record), registers the `lazy-spec.gate-tick` and `lazy-spec.coordinator-watch` daemon routines — the pair that clears finished job markers / structurally checks each note and hands operator activity to `spec.coordinator`, which is what actually decides and flips gates — and wires the requests-inbox runtime (open / apply routines, the request-routing expert, and its review class) at project scope. At project scope it also seeds a draft of the **vault spec** — the project-wide `vision.md` at the spec content-root, seeded through `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> seed-doc` from the `system-vision` type's template — whenever neither it nor a pre-existing `design.md` without a vision (the legal pre-vision state, migrated by the operator by hand) is already there; this file is now mandatory groundwork, not an optional nicety, because `/lazy-spec.product-config` refuses to register your first product while both are absent — the split into products is a consequence of the repo-wide spec. It's idempotent — re-running it is always safe and never overwrites config you've customized since. At the end it offers to chain straight into `/lazy-spec.product-config` so you can register your first product in the same pass, or you can skip and run that separately whenever you're ready.

---

## What is a "product" and do I need one before I can create any assets?

Yes — a product must be registered first. A product is the top-level unit in the spec system: it has a folder path in the vault, an optional binding to a source-code repo, a language setting that controls what language the plugin uses for narrative prose, and optional per-product `asset_types` / `tool_types` declarations that extend the kinds of asset and the tools the plugin ships with.

Run `/lazy-spec.product-config` to register a new product. The wizard asks for the product's folder name, its place in the vault, whether there is source code to bind, which review experts (use-case-writer / designer / system-designer / architect / ui-designer / planner / developer / tester / data-writer / researcher) should handle each doc type, and any dependencies. Every product gets an icon — decline the question and the wizard falls back to a default (`LiPackage`) rather than leaving the folder-note unpainted. Once the product is saved, `/lazy-spec.create-feature`, `/lazy-spec.create-change`, `/lazy-spec.create-bug`, and the universal `/lazy-spec.create-asset` will accept it by name — attempting to create an asset under an unregistered product refuses with a message pointing you back to `/lazy-spec.product-config`. The folder name itself has one restriction: it can't be `vision`, `design`, `ui-design`, `tech`, `use-cases`, or `decisions` — those are the product-level docs that live loose at the product root, and a product folder of the same name would collide with its own folder-note; the wizard refuses the name and `/lazy-spec.audit` flags it if it slips through some other way.

---

## Can a product contain another product?

Yes. A product's `spec_path` may sit under another product's `spec_path` — a **nested product** is a full product record of its own (its own `products[<key>]` entry, its own level note carrying `spec_role: product`, its own four level gates, its own vision/design/tech trio), just registered at a folder inside a parent product's tree instead of at the vault content-root. Ownership of any path belongs to the innermost product — the one with the longest matching `spec_path` — so the parent never claims a nested product's own documents or assets.

Register one directly with `/lazy-spec.product-config`'s caller form — `create <key> at <spec_path> source <repo-key>:<path>` — or let `/lazy-spec.create-from-code` decide per semantic area while it documents a code-bound product: for each area it found, it asks whether the area becomes a **nested product** (its own registered product, its candidates landing at that product's root), a **group folder** (an ordinary container under this product, no registration), or **flat** (candidates land straight at this product's root like any other). Only the first of the three creates a new `products[<key>]` entry.

A nested product doesn't have to declare everything itself. Whatever key it leaves unset — `language`, `mode`, `asset_types`, `guidelines` — is read through its ancestor chain: `asset_types` merges key-by-key from the outermost ancestor down to the product's own, `guidelines` is a per-role ordered union along the same chain, and `language` / `mode` take the nearest declaration. `source`, `dependencies`, `icon`, and `color` are never inherited — those describe this one product, not its lineage. `/lazy-spec.product-config`'s own wizard steps reflect this: any step whose key the nested product already carries through inheritance is skipped with outcome `inherited` rather than asked again, though edit mode still lets you declare a local override, which wins. The same innermost-wins rule governs review routing — a nested product's own review-class override outranks its ancestor's.

This is a different thing from a **nested asset** — an ordinary feature/change/bug/etc. placed inside another asset's own folder via `--path`, still owned by the same product. A nested product is a whole extra product with its own gates; a nested asset is still just one asset, wherever it happens to sit.

The parent stays aware of a nested product too: re-approving a nested product's own `vision.md` or `design.md` wakes the parent's coordinator (a one-hop `child-reapproved` dispatch), and the parent's own asset/product counter reports every nested product as a separate `N products` count rather than folding its assets into the parent's own tally.

---

## Can I generate a product's spec from an existing codebase instead of writing it by hand?

Yes, for a product that is already registered with a source binding. Run `/lazy-spec.create-from-code <product>` — it scans the source in parallel, then authors the product's `vision.md` (goals and value, from the code's evidenced outcomes) when one doesn't already exist, followed by a behaviour-only product design doc and a code-grounded product tech doc, complete with the primary behavioural and architecture diagrams. It also surfaces feature-candidates it found in the code and, per candidate, asks whether to scaffold a full feature (`/lazy-spec.create-asset` with `--empty` for the folder and the start doc, the mandatory `vision.md` seeded beside it, and both documents then written from the same scan — no further questions), record it only as an architectural area inside the tech doc, or skip it.

The skill requires the product to already carry a `source` binding — register that first with `/lazy-spec.product-config`. On a design-only product (no source attached) it no-ops rather than guessing at code that isn't wired in.

---

## What is `system-design` / `system-tech`, and is there a spec for the whole project, not just one product?

Yes, at three levels. Every asset type that carries a `vision` contract gets its own `vision.md` — goals, value, one-screen "what this is and for whom" (the asset's goals live ONLY here) — ahead of `design.md`, which opens with a reference back to the sibling vision instead of restating goals. The same vision-then-design pairing repeats one level up, at the product root, and one level further up still, at the vault's content-root (the `spec.vault_root` setting, default `specs/`), describing the whole project above every individual product. This is the **vault spec**, and `vision.md` is now its anchor: `/lazy-spec.install` seeds a draft there automatically (project scope only, through `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> seed-doc` from the `system-vision` type's template) whenever neither it nor a pre-vision `design.md` already exists, and `/lazy-spec.product-config` refuses to register a product while both are absent — the split into products is a consequence of the repo-wide spec. A `design.md` present without a sibling `vision.md` is the legal pre-vision state (a vault migrated before the vision document existed); the plugin never seeds over it, only the operator migrates it by hand. `/lazy-spec.audit` flags a vault carrying neither file as `[WARN] vault-spec-missing`, and a pre-vision vault as `[INFO] pre-vision vault`; re-run `/lazy-spec.install` to seed the missing draft.

Every product's own `design.md` + `tech.md` pair — loose at the product root, not inside any asset folder — is typed `system-design` / `system-tech` rather than the asset-level `design` type feature/change/bug docs carry; the same three-doc set (`vision.md`, `design.md`, `tech.md`) can also exist loose at the content-root, typed `system-vision` / `system-design` / `system-tech` exactly like the product-root copy. The content-root `tech.md` half stays entirely optional and is never auto-created — write it by hand, copying the plugin's own `spec.vault/tech.md` template (the content-root variant, carrying the same narrow Stack / Platforms / Constraints / Infrastructure decisions / Boundaries sections as the product-level `spec.product/tech.md` template, minus the per-product frontmatter) whenever the project wants one. Both `design.md` and `tech.md` at either level are optional too — a level with nothing but an approved vision is a complete, honest state, not a gap to fill. A product root may also carry `ui-design.md`, typed `system-ui-design`: the product's shared look — design system, recurring screen patterns, navigation skeleton — that each asset's own `ui-design.md` refines. It is optional like the other two, hangs a `Write ui-design` checkbox on the product note once the vision is approved, and has no content-root counterpart.

Review-wise, a `system-designer` expert writes both the `system-vision` and `system-design` classes (each covering the product-root and content-root copy), and an `architect` expert writes the `system-tech` class, distinct from the asset-level `designer` (writes a feature/change/bug's own `vision.md` and `design.md`) and from `architect`'s other job of writing opt-in `architecture.md` code-structure docs. `system-vision` (like the asset-level `vision` class) carries no validators — the writer and the operator close the loop — while `system-design` keeps an `architect_review` validation slot, same as the asset-level `design` class. The `ui-designer` writes the `system-ui-design` class alongside the asset-level `ui-design` class, the architect validating both. These are among the ten roles `/lazy-spec.product-config` Step 8 asks for. `/lazy-spec.create-from-code <product>` still scaffolds the product-level `vision.md` → `design.md` → `tech.md` trio for a code-bound product (see above) — the content-root, project-wide `vision.md` gets its draft from `/lazy-spec.install` instead, and `tech.md` at that level still has no dedicated creation skill.

---

## What is the difference between a feature, a change, and a bug?

All three are assets — they share the same gate ladder and folder layout — but the problem they capture is different. A **feature** describes new behaviour that does not yet exist. A **change** is the atomic modification of something that already exists: a rename, a constraint relaxation, a behaviour adjustment. A **bug** describes a defect: what was supposed to happen, what happened instead, and how to reproduce it.

The document layout differs too. Features and changes get `design.md` (no `bug.md`); bugs get `bug.md` (no `design.md`, and no `vision.md` either — the shipped `bug` type declares no vision contract at all). A feature's `vision` contract is `mandatory` — `vision.md` is seeded automatically ahead of `design.md`. A change's `vision` contract is `opt-in` — offered via a multi-select question at scaffold time, alongside `use-cases.md` / `ui-design.md`, and can still be added later if declined up front. Either way, the scaffold seeds only what the type's contract calls for — `code-plan.md` and `test-plan.md` are opt-in, authored later, never part of the scaffold. `/lazy-spec.create-feature`, `/lazy-spec.create-change`, and `/lazy-spec.create-bug` are thin wrappers that pin the asset type and delegate to the universal `/lazy-spec.create-asset`, which asks type-scaled clarifying questions, authors the prose, and draws the primary behavioural diagram(s).

Where an asset lands defaults differently per type, too: a `feature`, `content`, or `research` asset defaults straight to the product root, while only `bug` and `change` default to a folder of their own (`bugs/`, `changes/`) that appears the first time an asset actually lands in it. Either way it is only a default — pass `--path <dir>` to place any asset anywhere under the product, including inside another asset's own folder.

---

## Is there a built-in asset type for research — one that ends at an answer instead of shipped code?

Yes. `research` ships alongside `feature` / `change` / `bug` / `content` as one of the plugin's built-in asset types — you don't need to declare it with `/lazy-spec.add-asset-type` first. Create one with `/lazy-spec.create-asset <product> research <slug>`; there is no thin `create-research` wrapper, the same way there's none for `content`.

A research asset carries the same five gates as any other asset, but its definition half is a `design.md` typed `research-design` — the questions (each with a hypothesis as its second sentence when you already expect an answer), the goals, the scope, what's already known, and the approach the researcher is expected to take — written by the designer and validated by the researcher in a "Researcher review" section. Its work half is a single `research` tool whose report, `research.md` (`spec_doc_type: research-report`), carries the method, findings, options, and an explicit verdict on each hypothesis; it's the only authored document allowed to cite external URLs, and once approved it's treated as ordinary content, never rewritten afterward. `spec_plan_done` closes by absence (no `code-plan.md` on this type) and `spec_tests_passing` closes by absence too (no `test` tool); `spec_released` only closes on your own external signal that the conclusions were handed on — never on a checkbox completing, unlike the other four gates.

`/lazy-spec.product-config` Step 8 now asks for a tenth role, `researcher`, alongside the other nine — it writes `research.md` under the `research-report` review class (no validators) and validates `research-design`. The type declares no `vision.md`: the questions, the goals and the decision that depends on the answers live in the research design itself. Work that grows out of a research asset always lands as a brand-new asset — proposed via `[!asset-proposal]` and linked back through `spec_depends_on` — never as a mutation of the research asset itself; a conclusion that turns out wrong gets a fresh research asset citing the old one, not a rewrite of the approved report.

---

## Does every asset get a `vision.md`, or is it optional?

Depends on the asset's declared type. A type's `vision` contract is one of three shapes: `mandatory` (the shipped `feature` type — `vision.md` is seeded automatically ahead of `design.md`, and the `Write design` checkbox does not even appear until `vision.md` reaches `approved`), `opt-in` (the shipped `change` type, plus `content` — offered through a multi-select question at scaffold time alongside `use-cases.md` / `ui-design.md`, and can still be added later), or absent entirely (the shipped `bug` and `research` types declare no vision at all — a `bug.md` captures repro/observed/expected, not goals, and a research design carries its own question and goals). `vision.md` covers `Overview / Goals / Requirements / Value Proposition / Design Concept` — the asset's goals live ONLY here, never restated in `design.md`, which opens instead with a reference back to the sibling vision and covers what the asset does in behaviour terms. `Requirements` states the obligations the solution must satisfy — each one a single, verifiable statement free of implementation detail (the canonical shape behind the section is "condition, subject, action, object, constraint" per ISO/IEC/IEEE 29148, the same standard `design.md`'s own sections now cite inline) — never a to-do list of tasks. `design.md` does not restate or "work within" those requirements as its own section; instead it carries a separate `## Constraints` section of its own, holding a different thing entirely — facts of the environment and decisions taken elsewhere (a platform limit, a prior architectural commitment) that narrow the design's freedom, distinct from the needs the vision's `Requirements` obliges it to satisfy. `vision.md` carries no `Risks` section: risks are worked in the sibling `design.md`'s own `## Risks` section instead, stating what could sink the design and what it does about each. Both `/lazy-spec.create-asset` (and its thin wrappers `create-feature` / `create-change` / `create-bug`) and `/lazy-spec.create-from-code` author `vision.md` first when the type calls for it, and both mark any genuine decision fork the vision or design settles as an inline `[!decision]` callout, ready to `promote` into the decisions registry once the doc is approved.

---

## Can I add use-cases or a UI-design pass to a feature or change before architecture is written?

Yes, on both feature and change assets. `use-cases.md` (written by the use-case-writer) captures actor-level scenarios — main and alternative flows in the user's own language, no system internals — and `ui-design.md` (written by the ui-designer) settles screens, states, and interaction decisions, with self-contained HTML mockups attached beside it; neither ships production code. Both are opt-in: neither is part of `/lazy-spec.create-asset`'s scaffold, and each appears only once its own launch checkbox (`Write use-cases`, `Write ui-design`) is ticked — unless the product or the asset declares it mandatory.

Both hold the step after them, and `vision.md` (where the type declares it) holds ahead of both. The reading chain is `vision → use-cases → design → tech`: a document's review proceeds only once every EXISTING upstream sibling in that chain has reached `approved` — an absent opt-in document never blocks, so a change that declined `vision.md` and `use-cases.md` goes straight to `design.md`. Concretely: on a `feature` (mandatory vision), the `Write design` checkbox does not even appear until `vision.md` is `approved` — the coordinator seeds and starts the vision itself, on the asset's first wake, ahead of any checkbox. Once `design.md` exists, it is not dispatched (or continued) while a `use-cases.md` sibling exists and hasn't yet reached `approved` or `cancelled` — the use cases are meant to settle before the behaviour they describe is written down for good. `Write architecture` doesn't queue until `ui-design.md` is absent, `approved`, or `cancelled` — the screens are meant to be cast before the module boundaries built to serve them. Once each gap closes, dispatch resumes as an ordinary launch-checkbox job, no special-casing.

Each window closes on its own schedule: `vision.md` itself closes the moment `spec_design_done` closes (a late goals revision past that point is a change asset's business, not this asset's own definition half), `Write use-cases` closes at the same point, and `Write ui-design` closes once `architecture.md` is approved (or, for an asset that never becomes code, once `spec_plan_done` closes instead). Past any window a further revision belongs to a new change asset, not a reopening of this one. An edit landing on `vision.md`, `use-cases.md`, or `ui-design.md` after the document it feeds has already approved triggers no automatic rewrite — the coordinator drops an `[!attention]` callout into the downstream document and names the edit in `# Status brief`, leaving the decision to fold it in with you.

`/lazy-spec.product-config` Step 8 assigns the use-case-writer and ui-designer roles alongside the other eight, and generates their `use-cases` / `ui-design` / `system-ui-design` review classes the same way it generates every other doc-kind class.

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

No. Gate frontmatter is managed entirely by `/lazy-spec.flip-gate` (interactive, or `spec.coordinator` calling it non-interactively once it decides a gate is ready — `lazy-spec.gate-tick` itself no longer touches a gate at all). Editing it by hand bypasses the side-effect the primitive writes on every flip — the `spec_<gate>_at` moment stamped beside the gate (and dropped on `--off`), which the coordinator's staleness rule reads. The gate's own state lives only in the frontmatter boolean now; the flip's reason (with an `auto:` mark when the coordinator called it) is recorded in the run log, not in a note callout on the folder-note itself. Always use `/lazy-spec.flip-gate` for a manual flip; pass `--off` to regress a gate.

Similarly, a doc's per-file stage (`spec_stage` on `vision.md`, `use-cases.md`, `design.md`, `ui-design.md`, `code-plan.md`, `test-plan.md`, `bug.md`) is always changed through `/lazy-spec.set-stage`, never by hand-editing frontmatter. That skill rewrites `spec_stage`, mirrors the matching `spec/<stage>` tag in the same edit, and on an approval stamps `spec_approved_at` on the doc — the writes never happen separately. No history line is written: `# History` is reserved for what you commanded, what the experts finished, what you answered, and halts. Every stage write also cascades to the doc's own markdown attachments (files carrying `spec_owner_doc` back to it) — an attachment has no lifecycle of its own, so its `spec_stage` is always a mirror of its owner's, updated in the same commit, except while the attachment sits in its own review. Landing `approved` on a living doc (a type carrying `stages: true` and `append_only: false` — `design.md`, `bug.md`, `tech.md`, `architecture.md`, and the vision docs) also triggers the decision-promotion primitive automatically, lifting any inline `[!decision]` blocks into the sibling `decisions.md` registry in the same step.

---

## Does `/lazy-spec.set-stage` also touch a doc's markdown attachments?

Yes, automatically. A markdown attachment — a file carrying `spec_owner_doc` pointing back at the doc, e.g. a note an expert dropped beside `design.md` — has no per-file stage of its own: `/lazy-spec.set-stage` cascades the new `spec_stage` and its `spec/<stage>` tag onto every sibling attachment in the same commit, skipping only an attachment that is currently in its own review (the coordinator re-stamps that one once its review finalizes). You can't target an attachment directly — running the skill on one refuses with "document is an attachment of `<owner>`" and points you at the owner document instead.

---

## What does the `deferred` stage do, and how do I get a parked document moving again?

`deferred` is a sixth `spec_stage` value alongside `empty | draft | approved | rejected | cancelled` — a park, not a review outcome. Run `/lazy-spec.set-stage <doc> deferred` on any stage-bearing document, at asset level or at a product/vault system-document level, and nothing acts on it automatically afterward: no gate closes on it, the coordinator never promotes it by review result, replaces it, or edits it, and (with the wiki plugin installed, once `/lazy-spec.install` has seeded the predicate into its scan routines) the terms and structure curators skip it too. `/lazy-spec.sync-with-code` uses this stage by default for every document it creates from scratch rather than edits — a batch of retro-specs generated from your codebase lands parked instead of flooding the review queue before you've picked which ones to work on.

A committed edit to a parked document still wakes its owning coordinator the same as any operator edit — the folder-note's gates and status brief stay current — but the document's own content is left alone. The only way out is `draft`: either tick the `Review <doc>` row the folder note grows in place of the usual `Write <doc>` checkbox (ticking it moves the document to `draft` and opens its review in one action), or run `/lazy-spec.set-stage <doc> draft` yourself. Asking for any other stage on a parked document — `approved`, `rejected`, `cancelled`, `empty` — is refused.

When every stage-bearing document under an asset ends up parked this way, the asset's own folder-note picks up a matching asset-level state, `spec_state: deferred` — decided purely from the documents' own stages, whatever else the note happens to hang (an open launch row, a pending question, or nothing at all) — and its folder paints grey instead of the orange `waits-operator` colour: a parked backlog reads differently at a glance from an asset that's genuinely waiting on you to act. One live (non-parked) document among the rest is enough to put the asset back on the ordinary state table, where the parked documents simply close nothing. This `spec_state` value is distinct from the per-document `spec_stage: deferred` described above — one is the asset's own derived status (what the coordinator and the icon registry read), the other is a single document's park state — and `/lazy-spec.audit` treats both as legal, unrelated values.

---

## I ran `/lazy-spec.flip-gate` but the gate refuses to flip. What is blocking it?

The primitive checks exactly one thing on its own: whether the asset is cancelled. `spec_cancelled: true` freezes every gate in either direction — uncancel the asset before flipping. Every other precondition is no longer enforced by the primitive itself; it will flip whatever you ask, so an out-of-order flip is a mistake it will not catch for you. Before flipping by hand, wait instead — if the underlying condition genuinely isn't met yet, `spec.coordinator` won't have flipped it either, and its reasoning (surfaced in the asset's `# Status brief`) says why.

---

## Why did my asset's `spec_design_done` gate flip on its own?

`spec_design_done` and `spec_plan_done` are derived gates, not something you flip by hand. Once `design.md` (or `bug.md`) reaches `spec_stage: approved` and that approval commit has reached the daemon's own checkout, `spec.coordinator` wakes directly off that approval — the daemon also watches sibling docs, not only the asset's own status folder-note, so approving `design.md` reaches the coordinator on its own, no other folder-note activity or manual nudge required. The coordinator promotes it via `/lazy-spec.set-stage`, sees the corresponding gate's readiness now holds, and calls `/lazy-spec.flip-gate --auto` itself. The same mechanism handles `spec_plan_done` once `code-plan.md` is approved and pulled in (or immediately, if you never authored one — it's opt-in). The flip itself is committed under the coordinator's own identity and only becomes visible in your own checkout once you pull it back. For the three human-signal gates it does no flip of its own — it narrates what it's waiting on in `# Status brief`, and you (or an upstream signal like `/lazy-spec.sync-with-code`) flip them manually via `/lazy-spec.flip-gate`. `lazy-spec.gate-tick`, the background daemon worker, is uninvolved in any of this — it only polls active-job markers and structurally checks the note.

---

## An approved document (or a gate that was already closed) went back to draft / turned off by itself. Why?

This is `spec.coordinator`'s source-staleness rule — the one case in which it lowers a stage on its own rather than only ever promoting one. Most dependent documents have exactly one upstream source: `design.md`'s source is the asset's own `vision.md` when one exists, `architecture.md` / `ui-design.md`'s source is `design.md`, `code-plan.md`'s source is `architecture.md` when it exists (else `design.md`), `test-plan.md`'s source is `design.md`, and a tool's report that has no plan of its own (`data-report.md`, `docs-report.md`, `research.md`) also sources from `design.md`. `bug.md` has no upstream source and this rule never touches it.

When a source document gets re-approved AFTER the dependent it feeds was already accepted, the coordinator compares their `spec_approved_at` moments on the wake that sees it (for a report without a stage, the `spec_<gate>_at` of the gate it closed), finds the dependent now older than its source, moves the dependent back to `draft` (via `/lazy-spec.set-stage` — the one case where it lowers a stage on its own), flips the gate that dependent had closed back off, and immediately re-runs its upward checks in the same commit — so a `Review <file>` row, or a continuation tick on a tool's job, reappears the same cycle rather than lagging a tick behind. It writes one `# Status brief` sentence naming what went stale, so the reason is visible without digging. A doc-transition wake whose value comes back empty just means the source re-entered review, not that it was re-approved — this rule fires only once the source itself lands `approved` again.

---

## Can I ask `spec.coordinator` something directly, or does it only react to gate transitions?

Yes, two ways, both on the asset's own folder-note. Write anything into its `# Coordinator commands` section and the coordinator treats it as an operator instruction the next time it wakes on that asset — it unfolds your ask into a numbered mini-plan in the same section, marking each step's progress, and once every step finishes (or one fails and the chain locks) clears the plan and lands a single `# History` line saying what the command did or where it stopped. A command runs even on a halted asset — halt only silences automatic dispatch, never a direct instruction.

The second way is answering one of the coordinator's own `[!question]` callouts — tick the option you want and it acts on that answer, then removes the callout and records the choice in `# History`. Both surfaces are the coordinator's own pen; you never need to hand-edit the rest of the note to get its attention. When a decision doesn't follow unambiguously from its playbook and the rule layers in scope, the coordinator does not guess or act "just in case" — it raises exactly this kind of `[!question]` with concrete options and stops on that asset until your tick.

A product folder-note and every container folder-note under it (`bugs/`, `changes/`, and any folder you add or name with `--path`) may also each carry their own `# Coordinator rules` section. Features, content and research assets sit straight in the product root. The coordinator reads the whole chain top-down (playbook, then the level note of every enclosing product, outermost first, then the product's own, then every container note down to the asset, then the asset's own `# Coordinator rules`) before it decides anything on that asset. Writing a constraint at the product or container level applies it to every asset underneath without repeating it on each one; leaving the section empty (or absent) is normal until you actually need a group-wide rule.

Request routing — deciding whether a submitted request attaches to an existing asset or spawns a new one — is handled by a sibling persona, `spec.catalog-coordinator`, not by `spec.coordinator`; see the requests-inbox question below for how that works.

---

## Can I drive an asset through its gates without the daemon running?

Yes — run `/lazy-spec.drive <asset-note-path>` (or a bare product-relative path token of any depth — a slug on its own for an asset at the product root; with no argument at all it lists every live asset and asks you to pick one). It is a no-daemon session orchestrator: on a checkout where the runtime daemon isn't acting on this asset, it drives the whole ladder in one continuous session by reading the same `lazy-spec.coordination-playbook.md` law `spec.coordinator` follows under the daemon. You speak a word — tick a checkbox, answer a `[!question]`, write a `# Coordinator commands` line — and the skill translates it into the exact gesture an operator would make (never a decision of its own), commits it, wakes the coordinator through the same CLI the daemon's git-watch routine uses, and pumps whatever expert job results to completion with a local manual pump, looping until the ladder settles. It refuses to start while a live daemon could act on the same checkout — the two are mutually exclusive against the same asset, never run in parallel.

The note you point it at doesn't have to be an asset's own status note — a product's level folder-note or the catalog root's own level note work too, and the session then drives that LEVEL through its four level gates under `spec.catalog-coordinator` instead of the asset ladder; the dialog loop (tick / answer / command) and the daemon-liveness refusal work identically either way. Before ticking a box whose dispatch reads `design.md` or `architecture.md`, you can run `/lazy-spec.sync-with-code <asset>` first as a pre-step — its asset mode (see the next question) checks those docs against the current code before you commit to trusting them mid-session. Re-running `/lazy-spec.drive` on the same note always resumes rather than restarts — it settles anything left over from an interrupted session (a job that finished while nobody was watching, uncommitted hand-edits) before showing you the next menu.

---

## How do I record a design decision, and does the plugin write `decisions.md` for me?

Never by hand-editing `decisions.md` — always through `/lazy-spec.record-decision`, an interactive wrapper over four operations: `add` a new entry, `supersede` an older one with a new entry that marks it superseded, `obsolete` an existing entry with a reason, or `promote` — transfer decision blocks already written inline in a `vision.md` / `design.md` / `bug.md` / `tech.md` / `architecture.md` body out into a sibling `decisions.md` registry. `decisions.md` itself lives at one of three levels, resolved along a placement ladder: `<asset_dir>/decisions.md` for a feature/change/bug's own forks, `<spec_path>/decisions.md` for a product-wide decision, or `<content-root>/decisions.md` for a decision about the project as a whole (the system pair, or a cross-product concern) — the file need not exist yet at any level; the first record lazily creates it. Before recording a new decision, the skill holds you to a three-part weight test: a real fork existed, reversing it is expensive, and the "why" is unrecoverable from the artifact itself — a cheap, reversible, or self-explanatory detail isn't worth a record; per `spec.decisions.md`, the justification belongs only in the decision record, never restated in the surrounding design prose.

Most decision blocks never need the manual `add` path. `/lazy-spec.create-asset` and `/lazy-spec.create-from-code` already mark a genuine fork the clarification or the code evidence settles — while authoring `vision.md`, `design.md`, or the product-level docs — as an inline `[!decision] <thesis> #spec/decision` callout whose body is the justification in plain prose — no `Why` / `Rejected` labels, no list of alternatives — right where the fork was made. `promote` then happens automatically too: once a living doc (`vision.md`, `design.md`, `bug.md`, `tech.md`, `architecture.md`) is approved via `/lazy-spec.set-stage`, that step calls the same promote operation itself, lifting those inline blocks into the sibling registry without you running `/lazy-spec.record-decision` at all — the manual path exists for adding a decision straight into the registry, or for promoting a doc that skipped the usual approve step. A `promote` call refuses on a plan or report (neither originates decisions), and on a cancelled, halted, or released asset.

---

## Why did `/lazy-spec.set-stage` refuse to approve my document with a "decision-candidate" message, or why does `/lazy-spec.audit` flag an approved doc as carrying an unfolded one?

An expert may drop a `[!decision-candidate]` callout in the document it is itself writing when it takes a call the job wasn't told to make ("used X instead of Y") — a signal for you to accept or reject, never a decision applied on its own. Asking `/lazy-spec.set-stage <doc> approved` on a document that still carries the callout, ticked or not, is refused outright: approving would ship a questionnaire instead of a settled document. Fold it first — a document still inside its own review loop takes the candidate through the loop's ordinary rounds (your tick reopens the round, the writer folds the verdict, the loop's own finalize refuses the doc while a candidate remains); a document already finalized needs its review reopened at the writer round (`/lazy-review.start`) so the writer can fold the carried, already-answered callout before you set the stage again. `/lazy-spec.audit` catches the same gap after the fact: "Unfolded candidate in an approved document" (FAIL) on any living doc, or any document carrying `review_result: approved` / `approved-with-concerns`, that reached that state with a `[!decision-candidate]` still in its body — this check is scoped to living docs; the same marker in a tool's report (`code-report.md`, `test-report.md`, …) is a standing to-do, not a finding. A sibling check, "Unmaterialized asset proposal in an approved document" (WARN), catches the matching gap for an `[!asset-proposal]` callout the coordinator's post-acceptance materialization never picked up — wake the asset's coordinator with a `# Coordinator commands` line naming the proposal to get it scaffolded, linked, or reopened.

---

## What does `/lazy-spec.sync-with-code` actually change?

It reads the source commits that landed since the last sync and flags every change that looks user-visible as a candidate for the product design doc, for you to approve or decline one by one. It never silently rewrites a file, and it never touches the product's `tech.md` at all: that document is a narrow hand-written statement of stack, platforms, constraints, infrastructure decisions and boundaries, not a mirror of the code, and it changes only through its own review. A code-level change nothing user-visible follows from — a renamed internal function, a moved file — lands in the run log and in no document. Any authored document a run creates from scratch — a new asset `design.md` or `architecture.md`, for instance — is written parked at `spec_stage: deferred` rather than `draft`, so nothing acts on it until you tick its `Review <doc>` row or run `/lazy-spec.set-stage <doc> draft`; a document the run only edits keeps whatever stage it already carried.

After the design-doc pass it also reconciles branch pins (source links still pointing at a feature branch that has since merged or been deleted) and, per asset, proposes a `spec_develop_done` flip when the synced commits objectively landed that asset's code on the default branch — always via a confirmation, never silently. The skill no-ops on a design-only product that has no source binding, and it always finishes by running `/lazy-spec.audit` so you see whether the sync introduced any structural issues.

Given one feature or change asset instead of a bare product key — `/lazy-spec.sync-with-code <asset>` — the skill runs in **asset mode** instead of the product-wide flow above: it reconciles that ONE asset's `design.md` (and `architecture.md`, when the asset has one) against the current code by anchor rather than by commit diff. It follows whatever anchors resolve — source links already pinned in an opt-in `code-plan.md` / `test-plan.md`, a term the design names against the domain-group tree when `lazycortex-wiki`'s domains are configured, or a component name against the project-structure map — and compares the anchored code to what the doc claims. Asset mode never edits `design.md` / `architecture.md` prose itself: a discrepancy becomes exactly one of an `[!attention]` callout spliced into the doc, a proposed change asset (via `/lazy-spec.create-change`) to reconcile the drift with its own plan, or the same `spec_develop_done` / per-file-stage correction proposals product mode makes, confirmed the same way. No anchors resolving at all is a normal, honest outcome, not a failure — it just means the doc only gets the ordinary structural pass from `/lazy-spec.audit`. Bug assets are out of scope for asset mode — a bug folder carries neither `design.md` nor `architecture.md` — use product mode's per-asset gate proposals for those instead. Asset mode has no scheduled routine of its own; it runs on demand, as a pre-step inside `/lazy-spec.drive`, or as a check `spec.coordinator` makes before a gate-flip or status-brief decision that depends on code state.

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

Once the request body is approved during review, `spec.catalog-coordinator` wakes at the terminal group of that review cycle and takes over the routing. That is the sibling persona that runs on the catalog root — the level note sitting above every registered product — rather than on any one asset, because only from there is every product visible at once; `spec.coordinator`, which owns each individual asset's own status folder-note, never receives that wake and never writes into a request's `# Routing` section. The routing coordinator first labels the idea's class, then searches the vault for plausible attach targets — ranking existing features/changes/bugs by how closely their own design or bug doc overlaps the request's wording and title — and always surfaces its proposed routing from that search — spawn a new asset, attach to an existing one, mark an asset that already covers it as the reference (with its reasoning stated in the same block), or a mix — as an explicit `[!question]` confirmation you tick before anything is materialized. You can also edit the proposed routing block directly instead of just accepting or rejecting it.

Applying the decision never seeds document prose anywhere. A **spawn** creates only the asset's folder and its status folder-note, carrying the request's attribution — no `vision.md`, no `design.md`, no review opened yet. Every document the asset gets, `vision.md` and `design.md` included, is created later, one launch-checkbox tick at a time: ticking a `Write <doc>` checkbox seeds an empty skeleton at stage `empty`, copies the folder-note's request attribution onto it, and opens review on it. An **attach** works the other way — it stamps the request's attribution onto the existing target's own primary doc (`design.md` for a feature/change, `bug.md` for a bug) and re-opens review on that doc, without touching its existing content. Either way, the request body itself is never copied into any doc, whole or in sections — the doc's own review writer reads the linked request directly from its job context when it drafts the real prose. A **reference** decision writes nothing onto the target at all — it just links the request to the asset that already covers it. The whole pipeline runs without you hand-editing any frontmatter.

---

## Source links in my tech doc point at the wrong forge URL format. How do I fix that?

Every source URL in the spec system is built by the `lazy-spec.source-url` primitive from a known-forges table (GitHub, GitLab, Bitbucket, Gitea, Forgejo, SourceHut) — never inlined as a hard-coded `/blob/<branch>/<path>`. Run `/lazy-spec.audit <product>` to find links that were not produced that way; it reports every source link whose format doesn't match, or whose branch segment doesn't match the file's pin or the repo default.

If the underlying repo record is missing or the remote's hostname isn't recognized, `lazy-spec.resolve-repo` — the primitive `lazy-spec.source-url` calls to get the repo's base URL and forge — aborts with a message describing the gap. Fix the repo record by running `/lazy-spec.product-config` (it writes the `repos` entry), then re-run the sync or creation skill that emits the source links.

---

## `/lazy-spec.audit` is reporting "old-model artifact" on my status folder-note. What does that mean?

An older version of the plugin used a `gates:` dict, a `stage:` key, an `awaits_human:` field, or a `## Workflow` section on asset folder-notes. The current model uses five flat boolean fields directly on the folder-note frontmatter (`spec_design_done`, `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, `spec_released`) plus the `spec_cancelled` overlay. `lazy-spec.audit` treats any of the old-model fields as a hard error rather than trying to migrate them — there is no migration path, only a strip.

Run `/lazy-spec.audit <product>` — it names each obsolete field and the verb that strips it (`"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> note-drop-key <asset_dir> <key>` for an unrecognised `spec_*` key); the audit itself writes nothing.

---

## `/lazy-spec.audit` reports a `spec_doc_type` FAIL on a product or catalog folder-note. How do I clear it?

A folder-note never carries `spec_doc_type` — not an asset's status note, not a product's or the catalog root's own level note. Both directions are the same finding: the key missing from an authored document, or the key present on a note that must not have one. Run `Bash("${LAZYCORTEX_PYTHON:-python3}" <specs-cli> doc-type backfill)` (the primitive `/lazy-spec.install`'s Step 7c also calls during a fresh install) — it walks the spec content-root, writes the missing key onto authored documents that lack it, and strips a stray key off any level note that carries one, reporting `touched` / `skipped` / `cleaned` counts. A `cleaned` count above zero means the note was typed by an earlier release that derived a type from the `product` / `catalog` role and wrote it onto the level note itself, which no level-note schema has room for; the same backfill walk takes it back off. For a single note, `Bash("${LAZYCORTEX_PYTHON:-python3}" <specs-cli> note-drop-key <note_dir> spec_doc_type)` does the same strip without touching the rest of the catalog — it's the exact verb `spec.coordinator` and `spec.catalog-coordinator` reach for themselves the moment their own structural check spots the stray key, so a level note under an active coordinator often clears itself before you ever need to run backfill or doctor again. The backfill leaves its writes in the worktree — committing them is yours to do.

---

## Why did an unrecognized `spec_*` key disappear from my folder-note's frontmatter on its own?

`spec.coordinator` (for an asset's status note) and `spec.catalog-coordinator` (for a product or catalog-root level note) now clear it for you, the moment their own structural check reports the key as unrecognized. This closes a gap that used to leave the litter in place: the coordinator could see a stray key but had nothing in its toolset that could take it back off, so all it could do was name a "repair route" in `# Status brief` that fixed nothing on its own. It only ever removes a key that genuinely qualifies — one in the `spec_` namespace that the schema does not recognize — and refuses on a key the schema does know (that key carries real state, and state is set, never dropped) or on any key outside the `spec_` namespace at all, since another worker owns those.

You don't need to run anything yourself: the cleanup lands as an ordinary commit the next time the coordinator wakes on that note. `/lazy-spec.audit` still catches the same class of stray key on a note that isn't currently under an active coordinator wake — its report points you at the same fix.

---

## Where does a note's one-line description come from, and why did it stay blank (or show a placeholder) on a product with no assets yet?

Every product root note, the catalog root note, and every asset status note carries a one-line description in its `# Summary` section — one plain sentence saying what the product, the vault, or the asset IS, drawn from `vision.md`, never a statement of state (that's `# Status brief`'s job). It's written by whichever coordinator already owns that note: `spec.coordinator` writes an asset's line directly under the section's explainer, and `spec.catalog-coordinator` writes the product-root or catalog-root précis between that section's `<!-- spec:precis:start -->` / `<!-- spec:precis:end -->` markers. Either one writes it the first time it wakes and finds the line empty, and rewrites it later only once the note's actual subject changed — a wake that only moves a gate or a stage leaves the line untouched.

Group containers (`bugs/`, `changes/`, and any folder you add or name with `--path`) and the vault-root `requests/` inbox note carry no description at all, only a `<!-- spec:stats:* -->` counter — a collection has no subject of its own to describe, only a count of what's inside it. Features, content and research assets sit straight in the product root. That counter reads through the group folders below it: an asset you filed under `bugs/` is counted on the product root's line just like one sitting loose there, and the group folder itself is never counted as an asset. A nested product is the one thing that stops the reading — it shows up whole in the line's trailing `N products` segment, outside the asset total, and its own assets are counted on its own note.

If a product's `# Summary` still shows nothing, or an old English placeholder, the coordinator that owns it has simply never woken on that note — a product registered with no assets under it yet is the common case, since nothing has committed a reason for `spec.catalog-coordinator` to look at it. The description used to be written as a side effect of `/lazy-spec.refresh-sources`, which only ever ran when a doc's Sources needed re-projecting — so a product with nothing to refresh never got one written, and the note sat on its placeholder indefinitely. That side effect is gone: `/lazy-spec.refresh-sources` now touches only the one doc's own `# Sources` container and nothing else, so the description is exclusively the owning coordinator's to write. To get it filled in, give the coordinator a reason to wake — commit something under the asset, or on the product's own note or system docs — or run `/lazy-spec.drive` to walk the note in a no-daemon session.

`/lazy-spec.audit` checks the section's shape, not its wording: the product root's `# Summary` MUST carry both the précis marker and the stats marker, every other container MUST carry the stats marker alone (a leftover précis marker there is a WARN — a category was never meant to have one), and an asset note carries neither marker at all, since its description is a plain line rather than a marked region.

---

## I registered a repo but `lazy-spec.resolve-repo` still aborts with "unknown forge". How do I fix that?

`lazy-spec.resolve-repo` detects the forge from the remote URL's hostname against a built-in known-forges table (GitHub, GitLab, Bitbucket, Gitea, Forgejo, SourceHut). When you run a self-hosted instance on a custom hostname not in that table, auto-detection fails. Add an explicit `forge: <key>` to the repo record — run `/lazy-spec.product-config` and re-attach the source, or edit the product's source step, supplying one of the supported forge keys (`github`, `gitlab`, `bitbucket`, `gitea`, `forgejo`, `sourcehut`). Once the record carries the override, resolution and URL construction both work normally.

---

## How do I get an answer from the spec tree without loading whole documents into context?

Run `/lazy-spec.lookup` with a query and an optional anchor — a product key, a vault-relative path, or a product-relative path token of any depth (a bare slug at the product root). It walks the spec tree in three bounded directions from that anchor — up toward the vault root (the asset's own summary, then the owning product's design/tech docs), down through declared dependencies and materialized links, across to sibling assets and backlinks — and returns matching paths with a one-line excerpt each, never a whole document. This is the primitive an expert's research pass, a subagent gathering context before writing, or you asking "where does X live in specs" should reach for instead of grepping the tree by hand; it works from inside a one-shot dispatch too, since it never fans out to further subagents itself. With no anchor at all it falls back to a vault-wide search on the query token.

---

## My product is design-only — do I really need the full architecture/plan/implementation/test ladder for every asset?

No. Set `/lazy-spec.product-config`'s workflow-mode step to `spec-only` (edit mode works on an existing product too) and every asset under that product stops once its `design.md` is approved — no `architecture.md`, no `code-plan.md`/`test-plan.md`, no implementation or test checkboxes ever hang. The coordinator releases the asset on your own word instead of a checkbox completing.
