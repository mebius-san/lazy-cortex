---
chapter_type: faq
summary: Answers to common questions about products, assets, gates, requests, decisions, coverage gaps, spec lookups, and the coordinator agent.
last_regen: 2026-08-21
no_diagram: true
source_skills:
  - lazy-spec.install
  - lazy-spec.product-config
  - lazy-spec.doctor
  - lazy-spec.audit
  - lazy-spec.create-asset
  - lazy-spec.create-feature
  - lazy-spec.create-change
  - lazy-spec.create-bug
  - lazy-spec.create-from-code
  - lazy-spec.create-request
  - lazy-spec.add-asset-type
  - lazy-spec.decide
  - lazy-spec.flip-gate
  - lazy-spec.gate-tick
  - lazy-spec.set-stage
  - lazy-spec.sync-with-code
  - lazy-spec.finalize-branch
  - lazy-spec.coverage
  - lazy-spec.upstream-run
  - lazy-spec.resolve-repo
  - lazy-spec.source-url
  - lazy-spec.lookup
  - lazy-spec.coordinator
source_sha: 302cf4ffd01e473afa10f9a3f323feae9ee06b31
---
# Frequently asked questions

## Do I need to run anything before registering my first product?

Yes — run `/lazy-spec.install` once per project (or once globally, if you want the plugin available everywhere). It ensures the per-type template-override directories exist, seeds the repo's authoring language (asks only if none is on record), registers the `lazy-spec.gate-tick` and `lazy-spec.coordinator-watch` daemon routines — the pair that clears finished job markers / structurally checks each note and hands operator activity to `spec.coordinator`, which is what actually decides and flips gates — and wires the requests-inbox runtime (open / apply routines, the request-routing expert, and its review class) at project scope. It's idempotent — re-running it is always safe and never overwrites config you've customized since. At the end it offers to chain straight into `/lazy-spec.product-config` so you can register your first product in the same pass, or you can skip and run that separately whenever you're ready.

---

## What is a "product" and do I need one before I can create any assets?

Yes — a product must be registered first. A product is the top-level unit in the spec system: it has a folder path in the vault, an optional binding to a source-code repo, a language setting that controls what language the plugin uses for narrative prose, and optional per-product `asset_types` / `tool_types` declarations that extend the kinds of asset and the tools the plugin ships with.

Run `/lazy-spec.product-config` to register a new product. The wizard asks for the product's folder name, its place in the vault, whether there is source code to bind, which review experts (designer / system-designer / architect / planner / developer / tester / data-writer) should handle each doc type, and any dependencies. Every product gets an icon — decline the question and the wizard falls back to a default (`LiPackage`) rather than leaving the folder-note unpainted. Once the product is saved, `/lazy-spec.create-feature`, `/lazy-spec.create-change`, `/lazy-spec.create-bug`, and the universal `/lazy-spec.create-asset` will accept it by name — attempting to create an asset under an unregistered product refuses with a message pointing you back to `/lazy-spec.product-config`.

---

## Can I generate a product's spec from an existing codebase instead of writing it by hand?

Yes, for a product that is already registered with a source binding. Run `/lazy-spec.create-from-code <product>` — it scans the source in parallel, then writes a behaviour-only product design doc and a code-grounded product tech doc, complete with the primary behavioural and architecture diagrams. It also surfaces feature-candidates it found in the code and, per candidate, asks whether to scaffold a full feature (delegating to `/lazy-spec.create-asset`), record it only as an architectural area inside the tech doc, or skip it.

The skill requires the product to already carry a `source` binding — register that first with `/lazy-spec.product-config`. On a design-only product (no source attached) it no-ops rather than guessing at code that isn't wired in.

---

## What is `system-design` / `system-tech`, and is there a spec for the whole project, not just one product?

Yes. Every product's own `design.md` + `tech.md` pair — loose at the product root, not inside any asset folder — is typed `system-design` / `system-tech` rather than the asset-level `design` type feature/change/bug docs carry. The same pair can also exist loose at the vault's content-root (the `spec.vault_root` setting, default `specs/`), describing the whole project above every individual product. Nothing in config declares that project-wide pair — the files' existence at the content-root IS the declaration, so it's entirely optional and never auto-created; write it by hand (copying the plugin's own `system-design.md` / `system-tech.md` templates) whenever the project is big enough to want one.

Review-wise, a `system-designer` expert writes the design half (the `system-design` class — covers both the product-root and the content-root copy) and the `architect` expert writes the tech half (the `system-tech` class), distinct from the asset-level `designer` (writes a feature/change/bug's own `design.md`) and from `architect`'s other job of writing opt-in `architecture.md` code-structure docs. These are two of the seven roles `/lazy-spec.product-config` Step 8 asks for. `/lazy-spec.create-from-code <product>` still scaffolds the product-level pair for a code-bound product (see above) — the content-root, project-wide pair has no dedicated creation skill.

---

## What is the difference between a feature, a change, and a bug?

All three are assets — they share the same gate ladder and folder layout — but the problem they capture is different. A **feature** describes new behaviour that does not yet exist. A **change** is the atomic modification of something that already exists: a rename, a constraint relaxation, a behaviour adjustment. A **bug** describes a defect: what was supposed to happen, what happened instead, and how to reproduce it.

The document layout differs too. Features and changes get `design.md` (no `bug.md`); bugs get `bug.md` (no `design.md`). Either way, the scaffold seeds only that one doc — `code-plan.md` and `test-plan.md` are opt-in, authored later, never part of the scaffold. `/lazy-spec.create-feature`, `/lazy-spec.create-change`, and `/lazy-spec.create-bug` are thin wrappers that pin the asset type and delegate to the universal `/lazy-spec.create-asset`, which asks type-scaled clarifying questions, authors the prose, and draws the primary behavioural diagram(s).

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

Similarly, a doc's per-file stage (`spec_stage` on `design.md`, `code-plan.md`, `test-plan.md`, `bug.md`) is always changed through `/lazy-spec.set-stage`, never by hand-editing frontmatter. That skill rewrites `spec_stage`, mirrors the matching `spec/<stage>` tag in the same edit, and appends a transition line to the folder-note's `# History` section — the two writes never happen separately.

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

---

## How do I record a design decision, and does the plugin write `decisions.md` for me?

Never by hand-editing `decisions.md` — always through `/lazy-spec.decide`, an interactive wrapper over four operations: `add` a new entry, `supersede` an older one with a new entry that marks it superseded, `obsolete` an existing entry with a reason, or `promote` — transfer decision blocks already written inline in a `design.md` / `bug.md` / `tech.md` / `architecture.md` body out into that asset's or product's own `decisions.md` registry. Before recording a new decision, the skill holds you to a three-part weight test: a real fork existed, reversing it is expensive, and the "why" is unrecoverable from the artifact itself — a cheap, reversible, or self-explanatory detail isn't worth a record.

`promote` also happens automatically: once a living doc (`design.md`, `bug.md`, `tech.md`, `architecture.md`) is approved via `/lazy-spec.set-stage`, that step calls the same promote operation itself, so decision blocks you wrote inline usually reach the registry without you running `/lazy-spec.decide` at all — the manual path exists for adding a decision straight into the registry, or for promoting a doc that skipped the usual approve step. A `promote` call refuses on a plan or report (neither originates decisions), and on a cancelled, halted, or released asset.

---

## What does `/lazy-spec.sync-with-code` actually change?

It compares the source commits that landed since the last sync against the product's tech doc and proposes updates for anything that changed at the code level — new routes, renamed functions, new files, removed components, changed constants. It never silently rewrites files: every tech-doc edit is presented for approval first, and any change that looks user-visible is flagged as a candidate for the product design doc for you to decide on separately.

After the tech-doc pass it also reconciles branch pins (source links still pointing at a feature branch that has since merged or been deleted) and, per asset, proposes a `spec_develop_done` flip when the synced commits objectively landed that asset's code on the default branch — always via a confirmation, never silently. The skill no-ops on a design-only product that has no source binding, and it always finishes by running `/lazy-spec.doctor` so you see whether the sync introduced any structural issues.

---

## How do I release an asset after its branch merges?

Run `/lazy-spec.finalize-branch <branch>` after merging or deleting the source branch. The skill fetches fresh refs, finds every spec whose `spec_source_branches` frontmatter pins that branch, rewrites those source links to the default branch, and then proposes the `spec_released` gate flip for each affected asset via `/lazy-spec.flip-gate` — but only when its own check finds the release readiness already met (typically `spec_tests_passing` already `true`); `/lazy-spec.flip-gate` itself no longer double-checks this. When it isn't met yet, the skill skips the proposal for that asset instead — the link rebase is applied regardless, so you only need to settle the holding gate and re-run.

For squash-merges, where the ancestor check comes back false, pass `--force-merged` to skip it. To reconcile every merged branch across the vault in one pass, run `/lazy-spec.finalize-branch --merged`.

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

Once the request body is approved during review, `spec.coordinator` wakes at the terminal group of that review cycle and takes over the routing: it classifies the idea, checks the vault for existing assets it could attach to instead of spawning something new, and always surfaces its proposed routing — spawn a new asset, attach to an existing one, or both — as an explicit `[!question]` confirmation you tick before anything is materialized. You can also edit the proposed routing block directly instead of just accepting or rejecting it. The whole pipeline runs without you hand-editing any frontmatter.

---

## Source links in my tech doc point at the wrong forge URL format. How do I fix that?

Every source URL in the spec system is built by the `lazy-spec.source-url` primitive from a known-forges table (GitHub, GitLab, Bitbucket, Gitea, Forgejo, SourceHut) — never inlined as a hard-coded `/blob/<branch>/<path>`. Run `/lazy-spec.doctor <product>` to find links that were not produced that way; it reports every source link whose format doesn't match, or whose branch segment doesn't match the file's pin or the repo default.

If the underlying repo record is missing or the remote's hostname isn't recognized, `lazy-spec.resolve-repo` — the primitive `lazy-spec.source-url` calls to get the repo's base URL and forge — aborts with a message describing the gap. Fix the repo record by running `/lazy-spec.product-config` (it writes the `repos` entry), then re-run the sync or creation skill that emits the source links.

---

## What's the difference between `/lazy-spec.doctor` and `/lazy-spec.audit`?

`/lazy-spec.doctor <product>` audits your own spec content in this repo — a product's folder tree, its status folder-notes, per-file stages, source links, wikilinks — for staleness, broken links, or inconsistency with the actual source code, and can apply targeted fixes. `/lazy-spec.audit` checks the plugin's own installed surface instead — whether the decisions-registry rule still matches what the code relies on, every CLI verb is documented in `/lazy-spec.help`, and every skill and reference the plugin ships still resolves. It's read-only: findings name the fix (re-run `/lazy-spec.install`, hand-edit the drifted file, run `/lazy-spec.doctor`) rather than applying one itself. Reach for `doctor` when a specific product's specs look wrong; reach for `audit` when the plugin itself seems to be missing a piece.

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
