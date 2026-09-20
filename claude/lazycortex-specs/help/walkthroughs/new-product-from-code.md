---
chapter_type: walkthrough
summary: Register a product bound to existing code, generate vision/design/tech docs from source, then gap-scan for anything missed.
last_regen: 2026-09-20
diagram_spec:
  anchor: "How the skills hand off"
  request: "Sequence diagram showing the three-skill journey: operator runs lazy-spec.product-config to register the product and write settings, then runs lazy-spec.create-from-code to scan source and produce vision + design + tech docs (and scaffold any candidate features), then runs lazy-spec.coverage to gap-scan the code against the spec tree and materialize anything missed; show the operator, each skill, and the spec vault as actors, with the key handoff points between them."
source_skills:
  - lazy-spec.product-config
  - lazy-spec.create-from-code
  - lazy-spec.create-feature
  - lazy-spec.coverage
source_sha: 363d44e24bc3b51a232b4ca6f637dba8c931b2f7
---
# How do I get specs for a codebase that already exists?

You have a working codebase — a service, a library, an application — and no spec to go with it. This walkthrough starts from the vault spec that has to exist before any product can be registered, then takes you through registering the product in the spec system, generating a behavior-and-source-grounded specification directly from the code, and running a gap-scan to catch anything the auto-generated docs and candidate features missed. Three skills carry the bulk of the work; your job is to answer their wizard questions and review what lands. A fourth, `lazy-spec.create-feature`, comes in if you want to scaffold a feature the code scan didn't already surface.

## Outcome

After completing this walkthrough you will have:

- A project-wide vault spec (`vision.md` at the spec content root — or, for a vault seeded before the vision-document kind existed, a pre-vision `design.md`) confirmed present — either an existing one or a freshly seeded draft.
- A product record in `lazy.settings.json[products]` that names your codebase's source repo and the paths within it your product covers.
- A product `vision.md` — goals, requirements, and value proposition, authored first from the code survey.
- A `design.md` — behavior-only, no source URLs, opening with a reference to the sibling vision doc — describing what the product does for its users.
- A `tech.md` — code-grounded, with forge-correct source URLs — covering the source map, architecture, and components.
- Optionally, once your product's `vision.md` approves, a product-root `ui-design.md` — the product's shared look (design system, recurring screen patterns, navigation skeleton) that each asset's own `ui-design.md` refines — available as a `Write ui-design` launch checkbox on the product's folder-note. It is a separate document from the three above: none of this walkthrough's skills author it, and it is optional at the level a `design.md` / `tech.md` are not.
- Optionally a product-level `use-cases.md` — actors and cross-feature scenarios — if you opted in when `lazy-spec.create-from-code` asked.
- At least one feature folder under `<slug>/` — at the product root, inside a group folder, or, if you promoted one of the code's semantic areas to its own product, at that nested product's root — with a scaffolded `design.md` ready.
- A coverage report from `/lazy-spec.coverage` naming any capability the code already has that the generated docs and candidate features didn't pick up — optionally materialized as an additional feature, printed as a pasteable asset-proposal block, or skipped for a later pass.
- Review classes wired so every doc enters the review loop automatically.

None of `vision.md`, `design.md`, or `tech.md` gets a diagram automatically — the product-scan skill draws no pictures at all. If you want one, ask for it afterward via `/lazy-diagram.draw` against a heading in any of them.

## What you need

- `lazycortex-specs` installed and running (`/lazy-spec.install` completed at least once in this repo).
- `lazycortex-core` available — it provides the `settings-get` / `settings-set` CLI and the runtime daemon.
- A local checkout of the source repo you want to document — either the same repo that holds your spec vault (`/lazy-spec.product-config` can register it with `local_path: "."`, so every checkout resolves its own root with no absolute path needed), or a separate checkout that exists on disk at a path Claude Code can read.
- At least one expert registered in `lazy.settings.json[experts]` for each review role you plan to assign — use-case-writer, designer, system-designer, architect, ui-designer, planner, developer, and tester (plus data-writer and researcher if your product needs them) — unless this is not your first product in the vault, in which case you can ride the shared expert set an earlier product already set up. If you have not set up experts yet, run `/lazy-spec.install` — it offers to configure them — or run `lazycortex-experts` to compose the personas first.
- `lazycortex-diagram` available — a feature scaffold draws a flow diagram automatically, whether it comes from Step 3's candidate scaffolding or a gap you choose to materialize in Step 4; Steps 1, 2, and a plain gap-scan run in Step 4 draw nothing on their own.
- `lazycortex-wiki` available *(optional)* — if its project-structure map (`docs/structure.md`) or domain-group tree is configured for this repo, Step 4's gap-scan reads them for richer signal. Without either, it falls back to a raw scan of your source paths, so this walkthrough works either way.

## The journey

### Step 1 — Confirm the vault spec exists

Before any product can be registered, the spec catalog needs a starting point: a project-wide `vision.md` at the vault's content root (`specs/vision.md` by default), stating the intent and value of the whole project — every product is a consequence of that document, not the other way around. `/lazy-spec.product-config` enforces this: in create mode it checks for `vision.md` — or, for a vault seeded before the vision-document kind existed, a pre-existing `design.md` without a vision (the legal pre-vision state; migrating it to a vision doc is the operator's own call, by hand) — and aborts with `aborted:no-vault-spec` when neither is present, before asking you a single wizard question.

`<specs-cli>` stands for the specs plugin's `bin/lazycortex-specs` file — the newest copy under `~/.claude/plugins/cache/lazycortex/lazycortex-specs/<version>/`, or `claude/lazycortex-specs/` in a checkout that authors the plugin. Every verb runs through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> <verb>`: the file carries no exec bit and is not on `PATH`.

If `/lazy-spec.install` has already run in this repo, its own seeding step (Step 6.9) already created a draft `vision.md` here — either it was `already-present` (your vault already had one) or it wrote one (`seeded`), seeded by `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> seed-doc` beside the catalog root's level note with the type's icon and colour already in place, no questions asked. If you have not run `/lazy-spec.install` yet, run it now; the vault-vision seed is part of its normal setup, not a separate step you invoke by hand.

The seeded draft is deliberately minimal — presence is the whole gate `/lazy-spec.product-config` checks, not any particular level of completeness. You can flesh it out before or after registering your first product; the review loop picks it up through the standard `system-vision` class either way.

**Verification gate.** `<content-root>/vision.md` exists on disk (content root defaults to `specs/`), in any state — draft or approved. A vault that predates the vision-document kind may instead carry a pre-vision `<content-root>/design.md` with no vision — either satisfies the gate.

### Step 2 — Register the product with `/lazy-spec.product-config`

Run `/lazy-spec.product-config`. The skill opens a wizard and asks one question at a time.

The key decisions you will make:

- **Product key** — an arbitrary stable string you choose for the record under `products[<key>]` (lowercase-with-hyphens recommended, e.g. `api-gateway`). It is the product's stable identity across config and every skill invocation — it is not derived from the folder path and never changes when the folder moves.
- **Spec path** — the content-root-relative folder where this product's specs will live, any shape you like: a top-level folder, or nested under organizational folders of your own choosing. The wizard offers existing folders as suggestions plus a free-text path.
- **Language** — an optional override of the vault-wide default language for this product's generated prose.
- **Source** — whether this product has source code (it does) and which registered repo key maps to it. If the checkout is not registered yet, the wizard runs an inline sub-wizard to capture the local path and default branch for you. When the code lives in the very repo that holds your spec vault, pick `this repo (.)` — the wizard writes the literal `"."` so every checkout (dev machine, or a runtime checkout elsewhere) resolves its own root, no absolute path required. Otherwise point it at the root of a separate checkout that lives elsewhere on disk.
- **Source paths** — the subdirectories within the repo that this product covers. A single path like `src/api` is fine; you can add more paths if the product spans multiple subdirectories. The skill validates that each path exists on disk.
- **Dependencies** — the skill dispatches a read-only scan of your source paths and presents each detected dependency (internal products, cross-repo, or external packages) for you to accept or skip, one at a time.
- **Icon** — every product gets one: pick a concrete suggestion or type your own, or decline and the product still gets the default `LiPackage` — a product never ends up icon-less in the file explorer. The product root is also the only ordinary container the wizard paints a colour on (a neutral, state-independent shade); the group folders that appear under it as you add assets carry no colour of their own.
- **Guidelines** (optional) — per-role file paths whose contents are folded into an expert's job context whenever an operator later ticks a launch checkbox on this product's assets.
- **Review experts** — ten roles review this product's docs: **use-case-writer** (`use-cases.md`), **designer** (asset-level `design.md`, plus a validation pass on `use-cases.md`), **system-designer** (the product's own `vision.md` / `design.md`, and the project-wide `vision.md` / `design.md`), **architect** (the product's `tech.md` plus any `architecture.md`, and a standing validator on every design-shaped doc including `ui-design.md`), **ui-designer** (asset-level `ui-design.md`, plus the product-root `ui-design.md` — the shared look each asset's own `ui-design.md` refines), **planner** (`code-plan.md`), **developer** (`code-report.md`), **tester** (`bug.md`, `test-plan.md`, `test-report.md`), **data-writer** (`data-report.md`, only relevant if your product produces data-report docs), and **researcher** (a research asset's `research.md`, plus a validation pass on `research-design.md`, only relevant if your product uses the research asset type). If the vault already carries a shared expert set from an earlier product, you can ride it as-is or define a product-specific override; otherwise your answers here seed the vault's shared set. A vault whose shared set predates the use-case-writer, ui-designer, or researcher roles is asked for those separately, even when it rides the shared set for everything else.
- **Asset types** — optional; declare any beyond the shipped feature/change/bug set now, or later via `/lazy-spec.add-asset-type`.
- **Workflow mode** — `full` (design through implementation and testing, the default) or `spec-only` (stops after `design.md` approves, released only by an explicit operator word). Most code-bound products want `full`.

When the wizard finishes, the skill writes the product record into settings, creates the product folder with its folder-note — now the level note the `spec.catalog-coordinator` owns, carrying `spec_role: product`, the four level gates (all starting `false`), and the coordinator's own sections (`# Summary`, `# Gates`, `# Status brief`, `# Coordinator rules`, `# Coordinator commands`, `# History`, `# Attachments`) alongside its précis and stats markers — plus the shared vault-root request inbox, and generates the built-in review classes — one per document type marked for review (use-cases, design, system-vision, system-design, system-tech, system-ui-design, code-plan, test-plan, bug, plus the implementation and testing report docs) — reusing the vault's shared set when your expert choices match it. It then runs `/lazy-spec.audit` automatically and reports any issues.

If `/lazy-spec.product-config` points you at `lazycortex-experts` before finishing, it means a chosen expert name is not registered. Compose the persona via `lazycortex-experts`, then re-run `/lazy-spec.product-config`.

**Verification gate.** Before continuing, confirm that `lazy-spec.audit` in the report shows no failures. The product folder and its folder-note should exist on disk, carrying `spec_role: product` and its four level gates all `false` — group folders are created lazily, the first time an asset lands in one; candidates land straight in the product root unless you chose a group folder or a nested product for their area.

### Step 3 — Generate the spec from code with `/lazy-spec.create-from-code`

Run `/lazy-spec.create-from-code <compound-key>` where `<compound-key>` is the product key the previous step just wrote (e.g. `backend-api-gateway`).

The skill resolves your product's source binding, then fans out four parallel Explore agents to scan the codebase:

- **Agent A** — classes, functions, routes, and their signatures.
- **Agent B** — data structures, constants, and UI or template surfaces.
- **Agent C** — known limitations, TODOs, and cross-repo imports.
- **Agent D** — candidate features: sub-folders or route groups that cohere as independently nameable units, each tagged with the semantic area of the codebase it belongs to.

Before it writes a single document, the skill groups Agent D's candidates by area and asks you, one area at a time, how that area enters the spec tree:

- **nested product** — the area becomes a product of its own, registered under yours (`<compound-key>-<area>`) with the area's folder as its source path; it inherits your language, experts, asset types, and guidelines unless you give it its own. The skill runs `/lazy-spec.product-config` on your behalf to register it — you don't fill out that wizard a second time by hand.
- **group folder** — the area's candidates land together under a folder inside your product; the first one scaffolded seeds the folder's own note.
- **flat** — the area's candidates land at the product root, same as any candidate with no area of its own.

This is a per-area call, not all-or-nothing: a codebase with three semantic areas can end up with one promoted to its own product, one kept as a group folder, and one left flat. The skill flags an area as a likely nested-product candidate when it has its own entry point, two or more candidates, and its own README/docs or test cluster — that flag is a hint for you, never a decision made on your behalf.

After the area decisions are recorded, the skill authors the product's docs in order.

**`vision.md`** comes first, when your product does not already have one: an overview of what the product is and who it is for, its goals, the hard requirements the solution must not violate, the value proposition, and a short design-concept paragraph pointing at the sibling design — all filled from the code survey, then marked `draft`. Risk is not a vision-level section — the vision states intent and constraints, and the design works out what to do about risk (see `design.md` below). A `vision.md` that already exists is left untouched.

**`design.md`** is behavior-only: what the product does, who uses it, and what the user-visible limitations are. It never contains source URLs or file paths — just observable behavior — and it opens with a reference to the sibling vision doc rather than restating goals and value, which live only in `vision.md`. Where the code shows a genuine fork was taken — a real alternative existed, reversal would be expensive, and the "why" is not recoverable from the code itself — the skill records it inline as a decision callout in the design body; approving the design later promotes these into the product's `decisions.md` automatically. The design also names any area you promoted to a nested product as one of the product's components — what it is for, never its mechanics. This skill draws no diagrams — if you want a picture under `## Behavior` (or a UI subsection you add later), ask for one via `/lazy-diagram.draw` against that heading once the doc exists.

Once `design.md` is written, the skill asks one question: also author the product-level `use-cases.md` (actors and cross-feature scenarios) from the same code survey? This is opt-in — decline and the doc is simply never created, with no gap to fix later.

**`tech.md`** is code-grounded: the source map, architecture narrative, component breakdown, route tables (if applicable), and a dependency table with forge-correct source URLs. Its `## Architectural Areas` section covers only the areas you kept flat or as a group folder — an area you promoted to a nested product gets a spec of its own instead and is not listed here. Like the other docs, no diagram is drawn automatically here either — request one via `/lazy-diagram.draw` against `## Architecture` or `## Components` if you want one.

`lazy-spec.create-from-code` does not author the product-root `ui-design.md`. That document has its own lifecycle: once `design.md` and `tech.md` are written here and `vision.md` approves, a `Write ui-design` checkbox appears on the product's folder-note (the level note `/lazy-spec.product-config` created in Step 2), and ticking it dispatches your registered ui-designer to write it. It is optional — a product with nothing to say about shared screen patterns can leave it unwritten.

Once every doc is written, the skill re-presents Agent D's candidate list — your area decisions are already recorded, so it does not ask those again — and asks what to do with each candidate:

- **scaffold feature** — scaffolds the feature wherever its area was placed: the nested product's root, the group folder, or the product root. `lazy-spec.create-asset` is called with `--empty` for the folder and the start doc, the mandatory `vision.md` is seeded beside it, and the skill then writes both documents from the scan it already ran — you are asked nothing further about a candidate that is already in the code. Pick this for features you want to document now. Scaffolded features leave no trace in `design.md` — the folder-notes aggregate the decomposition catalog.
- **treat as architectural area** — adds a subsection to the tech doc's `## Architectural Areas`; no feature folder is created. Only offered for a candidate whose area you kept flat or as a group folder — a candidate under a promoted nested product scaffolds into that product instead.
- **skip** — leaves no trace.

Work through each candidate. You do not need to scaffold all of them now — re-run this skill later to see the current candidate list again, or let Step 4's gap-scan catch anything you skipped that still has no spec asset.

Agent D only flags candidates it can already see as coherent units in the code — sub-folders and route groups that already exist there. For a feature you want documented that isn't in the code yet, or that Agent D's scan didn't pick up as its own unit, scaffold it directly instead of waiting on a future run: `/lazy-spec.create-feature <compound-key> <new-slug>` pins the asset type to `feature` and hands off to `lazy-spec.create-asset` for its full wizard — 2 to 5 clarifying questions about the feature's scope, an opt-in prompt for `use-cases.md` / `ui-design.md`, and hand-authored prose — since there is no code scan behind it to answer those questions automatically.

**Verification gate.** `vision.md`, `design.md`, and `tech.md` should exist and carry `spec_stage: draft` (`use-cases.md` too, if you opted in). The design doc must contain no source URLs and no `spec_source_branches` frontmatter. All the docs should carry the default `spec_source_docs` frontmatter and a body `# Sources` section pointing at each other. Any area you promoted to a nested product should now show up as its own entry under `lazy.settings.json[products]`, with its own level note and a seeded `vision.md`.

### Step 4 — Find what's still missing with `/lazy-spec.coverage`

Run `/lazy-spec.coverage <compound-key>`. This is a read-only gap-scan: it compares what the code visibly does against what the spec tree already documents, and it only ever writes to the vault when you explicitly confirm a single gap — nothing is materialized behind your back.

The skill gathers two independent signals about the code side, both bounded queries rather than a whole-file read:

- If `lazycortex-wiki`'s project-structure map (`docs/structure.md`) is configured for this repo, it queries a bounded slice per `source.paths` entry — a directory role plus per-file lines for load-bearing files.
- If the wiki's domain groups are configured, it greps your source paths for `Domain(...)` blocks, keeps the groups that also appear in the domain-spec tree, and pulls their Mechanics and Contracts excerpts — a Contract entry is a caller-visible guarantee the code already commits to, so it counts as a capability just like a Mechanic does.
- When neither signal is available (or the structure map has no entry yet for a path), it falls back to a shallow scan of your source paths for sub-folders carrying their own entry point — the same heuristic Agent D used in Step 3, just applied inline rather than through a dispatched agent.

It then compares the combined candidate list against every status folder-note already in the product's asset tree — the same `(type, path, summary)` reading `lazy-spec.lookup` does — and drops anything an existing asset already names or clearly describes, using judgment rather than a literal string match. For everything left over, it proposes a category (`feature` by default, `bug` when the evidence is a hazard or TODO comment naming a defect, `change` when it is an increment on an already-documented asset) and a lowercase-with-hyphens slug.

The report prints one line per phase — resolve, structure-map query, domain-group query, spec-tree enumeration, gap-compute — then the gap list and how many capabilities were already covered. When there is genuinely no code-side signal at all (no structure map, no domain groups, and the fallback scan finds nothing), it says so plainly: that is an honest "nothing to compare against yet", not a bug, and it reports `no-gaps` rather than a false "fully covered".

For each remaining gap, one `AskUserQuestion` at a time offers:

- **materialize via lazy-spec.create-from-code** — offered only for code-bound `feature` gaps; runs `/lazy-spec.create-from-code <compound-key> feature <slug>` in feature mode right away — landing in the group folder you named for the gap when you named one, the product root otherwise. Feature mode calls `lazy-spec.create-asset` with `--empty` for the scaffold and then writes the feature's `vision.md` and `design.md` from its own scan of that candidate's files, so no clarifying questions are asked about a feature that already exists in the code.
- **print asset-proposal markup** — any category; prints a pasteable proposal block for you to drop into a living doc (`design.md`, `tech.md`, `architecture.md`) yourself, where the coordinator materializes it once that document is next approved. The skill does not write it into any document itself.
- **skip** — no trace; the gap is re-reported the next time you run `/lazy-spec.coverage`.

**Verification gate.** The report names an outcome for every phase, ending in either `no-gaps` or a gap list whose count matches the number of `AskUserQuestion` rounds you answered. Anything you chose to materialize should exist on disk under `<spec_path>/<slug>/`, under the group folder you chose, or at the nested product's root (when you ran this step against a nested product's own compound-key); anything you chose to print should be sitting in your own paste buffer, not yet landed in any document.

## After you're done

The product is registered and its initial spec is live. From here:

- **Find more gaps** — re-run `/lazy-spec.coverage <compound-key>` whenever the codebase grows; it re-scans the current code state against whatever is already documented and only proposes what's still missing. Re-running `/lazy-spec.create-from-code <compound-key>` also re-surfaces Agent D's current candidate list from Step 3, in case a sub-area you skipped earlier now looks more feature-shaped.
- **Keep docs in sync with code** — when source changes land, run `/lazy-spec.sync-with-code <compound-key>` to surface behavior changes for the design doc, update branch pins if you are working on a non-default branch, and propose gate/stage corrections (e.g. flipping `spec_develop_done`) grounded in what actually shipped — always with your confirmation before anything is written.
- **Drive assets through their gates** — use `/lazy-spec.flip-gate` to advance a feature's readiness gates (`spec_design_done` → `spec_plan_done` → …), or let `spec.coordinator` advance derived gates for you on its next wake (the `lazy-spec.gate-tick` routine itself only polls jobs and checks note structure).
- **Write the product's shared UI look** — once `vision.md` approves, tick the `Write ui-design` checkbox on the product's folder-note if your product needs one place for its design system, recurring screen patterns, and navigation skeleton; each asset's own `ui-design.md` then refines that shared look rather than inventing its own.
- **Re-run the doc scan** — if the codebase grows significantly, re-run `/lazy-spec.create-from-code <compound-key>` to refresh the design and tech docs. The skill reconciles existing branch pins before overwriting, and leaves an already-present `vision.md` untouched.
- **Audit checks** — run `/lazy-spec.audit <compound-key>` at any time to audit the product tree for broken links, missing sections, role violations, and source-link staleness. It is read-only and only reports: each finding names the verb, skill, or hand edit that clears it.

## How the skills hand off

```mermaid
%%{init: {'themeVariables':{'background':'transparent','primaryColor':'#1e3a5f','primaryBorderColor':'#4a90e2','primaryTextColor':'#fff','lineColor':'#4ae290','actorBkg':'#1e3a5f','actorBorder':'#4a90e2','actorTextColor':'#fff','actorLineColor':'#4a90e2','signalColor':'#4ae290','signalTextColor':'#000','noteBkgColor':'#5f4a1e','noteBorderColor':'#e2a14a','noteTextColor':'#fff','labelBoxBkgColor':'#5f4a1e','labelBoxBorderColor':'#e2a14a','labelTextColor':'#fff','loopTextColor':'#e2a14a'},'sequence':{'diagramPadding':5,'useMaxWidth':true}}}%%
sequenceDiagram
  participant operator as Operator
  participant productConfig as lazy-spec.product-config
  participant createFromCode as lazy-spec.create-from-code
  participant createFeature as lazy-spec.create-feature
  participant specVault as Spec Vault

  operator->>productConfig: Run lazy-spec.product-config
  productConfig->>specVault: Register product, write settings
  specVault-->>productConfig: Product registered
  productConfig-->>operator: Settings written
  Note over productConfig,createFromCode: Product must be registered before scanning
  operator->>createFromCode: Run lazy-spec.create-from-code
  createFromCode->>specVault: Scan source, write design.md and tech.md
  specVault-->>createFromCode: Design and tech docs written
  createFromCode-->>operator: Design and tech docs ready
  Note over createFromCode,createFeature: Design and tech docs feed the first feature scaffold
  operator->>createFeature: Run lazy-spec.create-feature
  createFeature->>specVault: Scaffold first feature asset
  specVault-->>createFeature: Feature asset scaffolded
  createFeature-->>operator: Feature asset created
```
