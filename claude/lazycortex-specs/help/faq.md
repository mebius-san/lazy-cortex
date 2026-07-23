---
chapter_type: faq
summary: Answers to common questions about products, assets, gates, code sync, releases, requests, and source links in lazycortex-specs.
last_regen: 2026-07-23
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
  - spec.product-config
  - spec.doctor
---
# Frequently asked questions

## What is a "product" and do I need one before I can create any assets?

Yes — a product must be registered first. A product is the top-level unit in the spec system: it has a folder path in the vault, an optional binding to a source-code repo, a language setting that controls what language the plugin uses for narrative prose, and optional operator-defined asset categories.

Run `/spec.product-config` to register a new product. The wizard asks for the product's folder name, its place in the vault (subsystem, optional namespace), whether there is source code to bind, which review experts (designer / developer / tester / historian) should handle each doc type, and any dependencies. Once the product is saved, `/spec.create-feature`, `/spec.create-change`, `/spec.create-bug`, and the universal `/spec.create-asset` will accept it by name — attempting to create an asset under an unregistered product refuses with a message pointing you back to `/spec.product-config`.

---

## Can I generate a product's spec from an existing codebase instead of writing it by hand?

Yes, for a product that is already registered with a source binding. Run `/spec.create-from-code <product>` — it scans the source in parallel, then writes a behaviour-only product design doc and a code-grounded product tech doc, complete with the primary behavioural and architecture diagrams. It also surfaces feature-candidates it found in the code and, per candidate, asks whether to scaffold a full feature (delegating to `/spec.create-asset`), record it only as an architectural area inside the tech doc, or skip it.

The skill requires the product to already carry a `source` binding — register that first with `/spec.product-config`. On a design-only product (no source attached) it no-ops rather than guessing at code that isn't wired in.

---

## What is the difference between a feature, a change, and a bug?

All three are assets — they share the same gate ladder and folder layout — but the problem they capture is different. A **feature** describes new behaviour that does not yet exist. A **change** is the atomic modification of something that already exists: a rename, a constraint relaxation, a behaviour adjustment. A **bug** describes a defect: what was supposed to happen, what happened instead, and how to reproduce it.

The document layout differs too. Features and changes get `design.md` + `plan.md`; bugs get `bug.md` + `plan.md` (no `design.md`). `/spec.create-feature`, `/spec.create-change`, and `/spec.create-bug` are thin wrappers that pin the category and delegate to the universal `/spec.create-asset`, which asks category-scaled clarifying questions, authors the prose, and draws the primary behavioural diagram(s).

---

## Can the plugin track non-software work — characters, scenes, chapters?

Yes, as long as the category has already been declared on the product. Run `/spec.add-asset-category <product> <category>` to register a new category — it writes the category into the product's `asset_categories`, scaffolds the category folder, and renders its operator-zone folder-note. Once registered, `/spec.create-asset <product> <category> <slug>` accepts it; naming a category that has not been registered is refused, with the refusal message naming the category and the product and pointing you at `/spec.add-asset-category`.

Once a category exists on the product, `/spec.create-asset` scales its clarifying questions to it: for an operator-defined category the questions are grounded in whatever the category's `design.md` template is meant to capture. The result behaves identically to a feature — five gates, the same folder-note shape, the same review flow. A category's docs are covered automatically by the product's existing behaviour-keyed review classes (their globs already span every category folder) — registering a category never touches `review.classes`.

---

## What are the five gates and how do they advance?

Every asset has five flat boolean gates on its status folder-note: `spec_design_done`, `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, and `spec_released`. They form a strict linear ladder — each gate requires every earlier gate to be true before it can be flipped on.

The first two (`spec_design_done`, `spec_plan_done`) are **derived**: the daemon's `spec.gate-tick` routine ticks each asset's status folder-note roughly once a minute and auto-flips them the moment the corresponding doc (`design.md` or `bug.md`, then `plan.md`) reaches `spec_stage: approved`. The last three are **human-signal** gates: on its tick, `spec.gate-tick` drops a `[!ready]` callout in the asset's `# Gates` section prompting you to flip the gate once the external condition (deploy landed, tests are green, branch merged) is actually met — and if that condition later regresses, the next tick rewrites the callout to an "readiness withdrawn" notice instead of leaving a stale prompt. To flip any gate manually, run `/spec.flip-gate <asset> <gate>`; the skill confirms with you before running the primitive, which enforces the ladder precondition and refuses cleanly if it isn't satisfied.

---

## How do I move an asset forward — do I edit the gate frontmatter directly?

No. Gate frontmatter is managed entirely by `/spec.flip-gate` (interactive) and `spec.gate-tick` (daemon-driven, automatic for derived gates). Editing it by hand bypasses the side-effects — the `# History` line, the precondition check — that these primitives write on every flip. Always use `/spec.flip-gate` for a manual flip; pass `--off` to regress a gate.

Similarly, a doc's per-file stage (`spec_stage` on `design.md`, `plan.md`, `bug.md`) is always changed through `/spec.set-stage`, never by hand-editing frontmatter. That skill rewrites `spec_stage`, mirrors the matching `spec/<stage>` tag in the same edit, and appends a transition line to the folder-note's `# History` section — the two writes never happen separately.

---

## I ran `/spec.flip-gate` but the gate refuses to flip. What is blocking it?

The primitive enforces the ladder precondition and reports it verbatim rather than working around it. The common cases:

- **`spec_design_done` won't flip** — `design.md` (or `bug.md` for a bug) is not yet `spec_stage: approved`. Get the doc through review and approved; `spec.gate-tick` auto-flips this gate on its next tick.
- **`spec_plan_done` won't flip** — `plan.md` is still `draft` or `empty`. Approve the plan doc first.
- **`spec_released` is refused** — the full ladder below it (`spec_tests_passing`, `spec_develop_done`, `spec_plan_done`, `spec_design_done`) must all be true; the refusal message names which one is holding it up.
- **Asset is cancelled** — `spec_cancelled: true` freezes every gate. Uncancel the asset before flipping.

---

## Why did my asset's `spec_design_done` gate flip on its own?

`spec_design_done` and `spec_plan_done` are derived gates, not something you flip by hand. The `spec.gate-tick` script-only worker runs per asset on the daemon's schedule (about once a minute) and auto-flips the lowest false gate whose precondition just became true — the moment `design.md` (or `bug.md`) reaches `spec_stage: approved`, the next tick flips `spec_design_done` for you, and the same happens for `spec_plan_done` once `plan.md` is approved. It performs no other writes: for the three human-signal gates it only drops or refreshes a `[!ready]` callout for you to act on manually via `/spec.flip-gate`.

---

## What does `/spec.sync-with-code` actually change?

It compares the source commits that landed since the last sync against the product's tech doc and proposes updates for anything that changed at the code level — new routes, renamed functions, new files, removed components, changed constants. It never silently rewrites files: every tech-doc edit is presented for approval first, and any change that looks user-visible is flagged as a candidate for the product design doc for you to decide on separately.

After the tech-doc pass it also reconciles branch pins (source links still pointing at a feature branch that has since merged or been deleted) and, per asset, proposes a `spec_develop_done` flip when the synced commits objectively landed that asset's code on the default branch — always via a confirmation, never silently. The skill no-ops on a design-only product that has no source binding, and it always finishes by running `/spec.doctor` so you see whether the sync introduced any structural issues.

---

## How do I release an asset after its branch merges?

Run `/spec.finalize-branch <branch>` after merging or deleting the source branch. The skill fetches fresh refs, finds every spec whose `spec_source_branches` frontmatter pins that branch, rewrites those source links to the default branch, and then proposes the `spec_released` gate flip for each affected asset via `/spec.flip-gate`. If the release precondition isn't met yet (typically `spec_tests_passing` is still false), the flip is refused cleanly and reported — the link rebase is applied regardless, so you only need to settle the holding gate and re-run.

For squash-merges, where the ancestor check comes back false, pass `--force-merged` to skip it. To reconcile every merged branch across the vault in one pass, run `/spec.finalize-branch --merged`.

---

## What is the requests inbox and how does an idea become an asset?

The vault-root `requests/` folder is the intake inbox. Run `/spec.create-request` with a raw idea; the skill asks three to five wizard questions to clarify scope, outcome, and constraints, then writes a body-only Markdown file at `requests/<slug>.md` — it never sets frontmatter itself, that lands automatically once the request enters the review loop.

Once the request body is approved during review, the `spec.request-router` agent takes over: it classifies the request, searches the vault for existing entities it could attach to, and always surfaces its proposed routing — spawn a new asset, attach to an existing one, or both — as an explicit confirmation you tick before it settles. You can also edit the proposed routing block directly instead of just accepting or rejecting it. The whole pipeline runs without you hand-editing any frontmatter.

---

## The requests pipeline mentions classify / find-candidates / attach / spawn — do I ever run those myself?

Normally no — `spec.request-router` calls them for you once a request's body is approved in review: it classifies the body (`spec.request-classify`), searches for existing attach targets (`spec.request-find-candidates`), then either attaches to an existing entity (`spec.request-attach`) or spawns a brand-new one (`spec.request-spawn`) once you confirm the routing.

Each is also a standalone primitive you can invoke directly if you want manual control — for example to re-classify a request after editing it, or to attach a request to a specific entity without waiting for the router's ranking. `spec.request-attach` and `spec.request-spawn` are idempotent on the request side: re-running with the same request/target pair is a safe no-op rather than a duplicate append.

---

## Source links in my tech doc point at the wrong forge URL format. How do I fix that?

Every source URL in the spec system is built by the `spec.source-url` primitive from a known-forges table (GitHub, GitLab, Bitbucket, Gitea, Forgejo, SourceHut) — never inlined as a hard-coded `/blob/<branch>/<path>`. Run `/spec.doctor <product>` to find links that were not produced that way; it reports every source link whose format doesn't match, or whose branch segment doesn't match the file's pin or the repo default.

If the underlying repo record is missing or the remote's hostname isn't recognized, `spec.resolve-repo` — the primitive `spec.source-url` calls to get the repo's base URL and forge — aborts with a message describing the gap. Fix the repo record by running `/spec.product-config` (it writes the `repos` entry), then re-run the sync or creation skill that emits the source links.

---

## `/spec.doctor` is reporting "old-model artifact" on my status folder-note. What does that mean?

An older version of the plugin used a `gates:` dict, a `stage:` key, an `awaits_human:` field, or a `## Workflow` section on asset folder-notes. The current model uses five flat boolean fields directly on the folder-note frontmatter (`spec_design_done`, `spec_plan_done`, `spec_develop_done`, `spec_tests_passing`, `spec_released`) plus the `spec_cancelled` overlay. `spec.doctor` treats any of the old-model fields as a hard error rather than trying to migrate them — there is no migration path, only a strip.

Re-run `/spec.doctor <product> --apply` — the fix loop offers to strip the obsolete fields per finding, with a confirmation before each write.

---

## I registered a repo but `spec.resolve-repo` still aborts with "unknown forge". How do I fix that?

`spec.resolve-repo` detects the forge from the remote URL's hostname against a built-in known-forges table (GitHub, GitLab, Bitbucket, Gitea, Forgejo, SourceHut). When you run a self-hosted instance on a custom hostname not in that table, auto-detection fails. Add an explicit `forge: <key>` to the repo record — run `/spec.product-config` and re-attach the source, or edit the product's source step, supplying one of the supported forge keys (`github`, `gitlab`, `bitbucket`, `gitea`, `forgejo`, `sourcehut`). Once the record carries the override, resolution and URL construction both work normally.

---

## A dependency in my product record points at a product or repo key that no longer exists. What do I do?

`spec.resolve-dependency` refuses with a clear error naming the missing key rather than silently dropping or guessing at it. Run `/spec.product-config` on the product — its dependency step lets you review, extend, or correct the `dependencies` list; it never removes an entry you don't explicitly touch, so you can fix just the stale one.
</content>
