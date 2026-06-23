---
name: spec.create-from-code
description: Use when generating a specification FROM an existing codebase for an already-registered, code-bound product — fans heavy source scanning out to parallel Explore agents, then writes a behavior-only product design doc and a code-grounded product tech doc with source URLs. Product mode documents the product itself; feature mode delegates one feature-candidate to spec.create-asset. Requires the product to be registered with a `source` binding via /spec.product-config first.
allowed-tools: Read, Glob, Grep, Bash, Edit, Write, Skill, Task, AskUserQuestion, TaskCreate, TaskUpdate, TaskList
---
# Create Spec from Code

Generate a specification from existing source code for a product that is **already registered and code-bound**. This skill does NOT register products — `/spec.product-config` owns the product record and the operator-zone folder tree. This skill reads the registered product's `source` binding, scans the code, and authors the code-derived spec docs.

Two modes:

- **Product mode** (default): document the whole product from code — a behavior-only `design.md`, a code-grounded `tech.md`, the empty asset-category dirs, and the PRODUCT-level diagrams.
- **Feature mode**: scaffold ONE feature-candidate discovered in the code by delegating to `spec.create-asset <product> feature <slug>`. This skill does NOT author the feature folder itself — create-asset owns the asset scaffold, its docs, and its diagrams.

Heavy source reading runs through parallel Explore agents so the main session stays on synthesis. Filenames, folder structure, header section, frontmatter keys, and wikilink format are owned by `${CLAUDE_PLUGIN_ROOT}/references/` — this skill never inlines those patterns.

## Execution discipline (MANDATORY — read before any action)

This skill has two modes (`product` + `feature`) with mode-specific step lists. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with the entry-phase tasks (canonical titles verbatim):
   - `Step 0 — Resolve the product`
   - `Step M — Mode detection`

   Immediately after Mode detection picks one of `product` / `feature`, `TaskCreate` the mode's full step list. Use these canonical titles verbatim — no merging, abbreviation, or renaming. Each `diagram <file>:<anchor>:<kind>` task corresponds to one declared product-diagram seam, and its outcome word IS the `lazycortex-diagram:lazy-diagram.draw` return value (`created` | `replaced` | `unchanged` | `failed:<reason>` | `split-into-N`).

   **Product mode**:
   - `Step P1 — Detect the branch`
   - `Step P2 — Scan source code (parallel agents)`
   - `Step P3 — Create the doc structure`
   - `Step P4 — Author product-design prose`
   - `Step P5 — Draw design.md:## Behavior:flow`
   - `Step P6 — Draw design.md:## Layout:layout`
   - `Step P7 — Author product-tech prose`
   - `Step P8 — Draw tech.md:## Architecture:c4-container`
   - `Step P9 — Draw tech.md:## Components:class`
   - `Step P10 — Scaffold candidate features (delegate)`
   - `Step P11 — Verify`
   - `Step P12 — Log the run`

   **Feature mode**:
   - `Step F1 — Determine the feature slug`
   - `Step F2 — Delegate to spec.create-asset`
   - `Step F3 — Verify`
   - `Step F4 — Log the run`

2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". A no-op counts only when it emits an explicit outcome word (`created`, `unchanged`, `no-candidates`, `delegated`, …).
3. **Do not reach Verify until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task at Verify time is a bug — stop and execute it first.
4. **Verify is a structural verifier.** Its checks (per the per-mode Verify subsection) MUST include diffing the declared product-diagram seam set against the seams actually logged to `.logs/claude/lazy-diagram.draw/` during this run. Any non-empty difference is a Verify failure; do not render the report with gaps.

## Input

The user provides a product compound-key (e.g. `dashboards`, `server-tester-chapter`) or a source path under a registered product. For feature mode, the user names a feature-candidate slug (or picks one from the product-mode candidate preview). If ambiguous, ask which product or candidate they mean.

## Product nesting is forbidden

Per `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`, a product folder MUST NOT contain another product. If the scanned source area contains a sub-area that would historically have been a sub-product, document it as an **architectural area** inside the product's tech doc (`## Architectural Areas`), never as a separate product. Promoting a sub-area to a sibling product is a deliberate `/spec.product-config` run by the operator, not an automatic action of this skill.

## Step 0 — Resolve the product

Resolve the product record:

```bash
lazycortex-specs resolve-product by-key <product>
```

The command prints `{"key": "<product>", "record": <record-or-null>}`. The record (when present) carries `spec_path` (required, vault-relative), optional `source` (`{ repo, paths }`), optional `language` (defaults to `en`), and optional `asset_categories`.

Branch on the record:

- **`record` is `null`** — the product is not registered. This skill does NOT register products. Refuse with a message naming `<product>` and telling the operator to run `/spec.product-config` first. Do NOT proceed.
- **`record` present but no `source` block** — the product is design-only (specs ahead of code). This skill has nothing to scan. No-op with the message: "product has no code binding; use /spec.product-config to attach a repo." Do NOT proceed.
- **`record` present with a `source` block** — capture `spec_path`, `source.repo`, `source.paths`, `language` (default `en`), and `asset_categories`. Resolve `source.repo` via the `spec.resolve-repo` primitive to get `{ local_path, branch, host, owner, repo, forge, base_url, … }`. Continue.

All narrative prose this skill authors (design body, tech architecture narrative, diagram request prose) is rendered in the product's `language`. Frontmatter keys/values, fixed section headers, role words, source URLs, wikilinks, and code identifiers stay English per `${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md`.

## Step M — Mode detection

1. If the user explicitly says "feature spec" / "feature for <product>" / names a single feature-candidate slug → **feature mode**.
2. Otherwise → **product mode**.

In product mode the per-candidate scaffold decisions (Step P10) re-enter feature mode by delegating to `spec.create-asset` — they do NOT re-invoke this skill.

## Branch handling (applies to both modes)

### Detect the current branch (pin-on-create)

Before writing any doc that may emit source URLs:

```bash
git -C <repo-config>.local_path rev-parse --abbrev-ref HEAD
```

If `<current-branch>` differs from the repo config's default `branch` AND the doc body will emit any source URL for that repo, add `spec_source_branches: {<repo-key>: <current-branch>}` to the doc's frontmatter and emit URLs via `spec.source-url(<repo-key>, <path>, <kind>, branch=<current-branch>)`.

Per `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`, pins belong only on docs that may carry source URLs — `tech` (and `plan`) docs. The product `design.md` NEVER carries pins because it never contains source URLs.

### Reconcile existing pins (regeneration)

If the target doc already exists with `spec_source_branches` frontmatter, run the **Pin Reconciliation** primitive (see `${CLAUDE_PLUGIN_ROOT}/references/spec.sources-protocol.md`) on it **before** overwriting any content. Merged/deleted pins get rewritten to the default branch; unmerged pins are left intact and new content inherits the still-open branch for that repo.

## Parallel code scanning

For both modes, heavy source reading is delegated to parallel Explore agents launched in a single message (`subagent_type: "Explore"`, `mode: "dontAsk"`, read-only). Each agent's prompt MUST include the resolved `source.paths` globs under `<repo-config>.local_path`, the product's `language` hint, and the structured-report contract. Never inline-read entire source files in the main session when an agent can summarize them.

Suggested splits:

- **Agent A — structure & APIs**: classes, functions, routes, signatures, docstrings.
- **Agent B — data & surfaces**: data structures, constants, template/UI surfaces, named regions.
- **Agent C — hazards & history**: TODO/TMP comments, known limitations, imports (for dependency mapping).
- **Agent D — candidate features (product mode only)**: feature-sized units of behavior already present in the source, ranked with evidence. See the contract below.

Each agent returns a structured summary (names, one-line purposes, file paths) per the parallel-scan coordinator pattern in `claude/lazycortex-core/references/lazy-core.parallel-scan.md`. The main session synthesizes these into the docs below.

### Agent D contract (candidate-feature detection)

Word budget: "Report under 500 words." Heuristics (priority order):

1. Distinct sub-folders under `source.paths` carrying their own entry point (`__init__.py`, `index.ts`, `mod.rs`, package manifest, …).
2. Route groups / command namespaces sharing a URL prefix or command root (decorators, router registrations, CLI dispatch tables).
3. Classes or modules exposing a self-contained public API (imported as a unit by consumers).
4. Test-file clusters naming a feature (`test_<feature>_*`, `<feature>.spec.ts`, …).

Expected report block:

```markdown
## scan: candidate-features

### findings
- [FEAT] <candidate-slug> | <one-line purpose>
  evidence:
    - <file-path> — <symbol or route group>
    - <file-path> — <symbol or route group>
  rationale: <one sentence: why these files cohere as a feature>

### summary
count: <n>
```

`<candidate-slug>` is lowercase-with-hyphens per `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`.

## Product Mode Process

### P1 — Detect the branch

Run the **Detect the current branch** primitive from "Branch handling" above. Capture `<current-branch>` for the pin-on-create decision in Step P7.

### P2 — Scan source code (parallel agents)

Launch the four parallel agents (A + B + C + D) per "Parallel code scanning", scoped to the product's `source.paths`. Collect their structured summaries. Agent D's candidate list drives Step P10's per-candidate scaffold/architectural-area/skip decisions **after** the product docs are written — the operator sees the product frame first, then decides which sub-units deserve their own feature folders.

### P3 — Create the doc structure

Product docs live loose at the product root (no `docs/` subfolder). Per `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md` (filenames are role-only):

```
<spec_path>/
├── <product>.md    # product folder-note (operator-zone; product-config's territory — do NOT author)
├── design.md       # behavior only — NO source URLs
└── tech.md         # code-grounded — source URLs via spec.source-url
```

The empty asset-category dirs (`features/`, `changes/`, `bugs/`, `requests/`) and the operator-zone category folder-notes are owned by `/spec.product-config` and already exist for a registered product. Do NOT create them here, do NOT create `backlog/`, do NOT author any operator-zone folder-note, and do NOT create `human-tasks.md`, any `changelog.md` (the role is removed from the model), any `spec_role: layout` doc, or any `layout.excalidraw` file — those roles are removed from the model (the `## Layout` diagram in Step P6 is an inline mermaid fence in `design.md`, not a doc). If a category dir is somehow absent, create the empty dir with `Bash(mkdir -p …)` but author NO folder-note (that is product-config's territory).

### P4 — Author product-design prose

The product design doc describes WHAT the product is, who uses it, and what it does — behavior terms only. NO source URLs, file paths, or class/function names. Per `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md` this doc MUST NOT contain source URLs, and per "Branch handling" it never carries `spec_source_branches`.

Emit the mandatory header section per `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`, with the migrated `spec_role` key. The frontmatter MUST carry `spec_source_docs` and the body MUST end with the `# Sources` section (both authored inline here — `design.md` is not scaffolded from an asset template):

```markdown
---
tags:
  - <product-tag>
  - spec/draft
subsystem: <Subsystem>
product: <product>
spec_role: design
spec_stage: draft
spec_source_docs:
  - "[[<spec_path>/tech]]"
---

# <product> — design

> **<Subsystem>** · **<product>** — design

## Overview
What it is, who it's for, how to access it (URL, command, entry point — as user-facing behavior, not a route handler name).

## Behavior
User-visible capabilities grouped by area. Describe what the product DOES for the user. The flow diagram (Step P5) anchors here — do not author an ASCII sketch.

## Layout
The product's UI surface arrangement — screens, panels, regions, navigation as the user encounters them, in behavior terms (no component / file names). The layout diagram (Step P6) anchors here — do not author an ASCII sketch. Omit the section body prose only if the product has no UI to lay out; the draw step then reports `skipped-section-empty`.

## Known Limitations
User-facing constraints derived from TODOs and current scope. Phrase as observable behavior, not source-level references.

## Roadmap
Placeholder: "_Planned improvements. Each item becomes a feature design doc under features/ when work begins._"

# Sources
```

Write the default `spec_source_docs` (`<spec_path>` resolved to the product's absolute vault path from Step 0):

| Doc | default `spec_source_docs` |
|---|---|
| `design.md` | `[[<spec_path>/tech]]` |

Write that array into the doc's `spec_source_docs:` frontmatter key, then project the body `# Sources` section (`## Docs` from that list; `## Requests` empty — no request origin) per `${CLAUDE_PLUGIN_ROOT}/references/spec.sources-protocol.md` — follow its marker boundaries, gloss/display rules, and the `#protected/spec/sources` tag exactly; do not restate the format here. Emit outcome `projected`.

After writing, set the per-file stage authoritatively via the `Skill` tool (`skill: "lazycortex-specs:spec.set-stage"`) → `draft` on `design.md` (keeps the folder-note `# History` line and the tag mirror in sync).

### P5 — Draw `## Behavior` flow

Invoke `lazycortex-diagram:lazy-diagram.draw` (via the `Skill` tool) with `target_file=<spec_path>/design.md`, `anchor_section="## Behavior"`, `kind="flow"`, `format="mermaid"`, and `request=` a one-sentence summary of what the diagram depicts followed by `facts: the actors, decision points, and outcomes named in the prose just authored` (terminology parity with the host section is the only contract). Pass `exemplar_override_dir=<spec_path>/.claude/templates/spec.diagrams/<compound-key>` if that directory exists (`<exemplar_override_dir>/diagram.mermaid/diagram-<kind>.md`). The return value IS the outcome for `Step P5`.

### P6 — Draw `## Layout` layout

Invoke `lazycortex-diagram:lazy-diagram.draw` (via the `Skill` tool) with `target_file=<spec_path>/design.md`, `anchor_section="## Layout"`, `kind="layout"`, `format="mermaid"`, and `request=` a one-sentence summary of the product's UI arrangement followed by `facts: the screens, panels, regions, and navigation named in the prose just authored`. Pass `exemplar_override_dir` as in Step P5 if present. This is an inline diagram only — it does NOT create any `spec_role: layout` doc or `layout.excalidraw` file. If the product has no UI to lay out (the `## Layout` body is empty), the draw outcome `skipped-section-empty` is acceptable. The return value IS the outcome for `Step P6`.

### P7 — Author product-tech prose

The product tech doc holds the source map, route tables, component breakdowns, data structures, and cross-repo dependencies. Source URLs are expected and required. Apply the pin-on-create rule from "Branch handling". The `spec.product/tech.md` template already carries the `# Sources` skeleton and `spec_source_docs: []` — this step fills the default values.

```markdown
---
tags:
  - <product-tag>
  - spec/draft
subsystem: <Subsystem>
product: <product>
spec_role: tech
spec_stage: draft
spec_source_docs:
  - "[[<spec_path>/design]]"
# Pin-on-create: add only when the body emits a source URL for a repo whose
# <current-branch> != <repo-config>.branch:
# spec_source_branches:
#   <repo-key>: <current-branch>
---

# <product> — tech

> **<Subsystem>** · **<product>** — tech

## Source Map
Entry point: [<module-path>](<spec.source-url(<repo-key>, <source.paths[0]>, "tree")>)

Brief prose: how the source tree maps to product behavior.

## Architecture
Key design decisions: state management, rendering approach, data flow. Reference source files via forge URLs per `${CLAUDE_PLUGIN_ROOT}/references/spec.sources-protocol.md`.

## Architectural Areas (if any)
Sub-areas that would historically be sub-products — one subsection each, with its own source link and short description. Do NOT create a separate product spec for them.

## Components
One subsection per source file or logical unit. Include: purpose, key functions/classes, data shapes (as tables).

## Routes (if applicable)
Tables grouped by category. Columns: Method | Path | Handler | Description. NO declared diagram seam — the route table IS the artifact.

## Dependencies
Table: Package | Usage. Path-qualified wikilinks to existing specs for internal dependencies (per `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`); external dependencies use plain text.

# Sources
```

Write the default `spec_source_docs` (`<spec_path>` resolved as in Step P4):

| Doc | default `spec_source_docs` |
|---|---|
| `tech.md` | `[[<spec_path>/design]]` |

Fill the template's `spec_source_docs: []` with that array, then project the body `# Sources` section (`## Docs` from that list; `## Requests` empty) per `${CLAUDE_PLUGIN_ROOT}/references/spec.sources-protocol.md` — follow it exactly; do not restate the format here. Emit outcome `projected`.

After writing, set the per-file stage via `spec.set-stage` → `draft` on `tech.md`.

### P8 — Draw `## Architecture` c4-container

Invoke `lazycortex-diagram:lazy-diagram.draw` with `target_file=<spec_path>/tech.md`, `anchor_section="## Architecture"`, `kind="c4-container"`, `format="mermaid"`, and `request=` a one-sentence summary followed by `facts: the components, layers, and wires identified by the scan agents`. Pass `exemplar_override_dir` as in Step P5 if present. Return value IS the outcome for `Step P8`.

### P9 — Draw `## Components` class

Invoke `lazycortex-diagram:lazy-diagram.draw` with `target_file=<spec_path>/tech.md`, `anchor_section="## Components"`, `kind="class"`, `format="mermaid"`, and `request=` a one-sentence summary followed by `facts: the named classes/interfaces and their relations`. Pass `exemplar_override_dir` as in Step P5 if present. Return value IS the outcome for `Step P9`.

### P10 — Scaffold candidate features (delegate)

Print Agent D's candidate list to the operator as an informational preview (no question yet). Then, **per candidate, one `AskUserQuestion`** (full-context block per the Wizard-question explanation standard in `${CLAUDE_PLUGIN_ROOT}/references/spec.config-protocol.md`) with options:

- `scaffold feature` — delegate to `spec.create-asset` (below).
- `treat as architectural area` — append a subsection under the product tech doc's `## Architectural Areas` with the candidate's source link and short description. No feature folder.
- `skip` — omit entirely, no trace.

After every candidate is decided, run the scaffolds serially. For each `scaffold feature` candidate, invoke via the `Skill` tool:

```
Skill(skill: "lazycortex-specs:spec.create-asset", args: "<product> feature <candidate-slug>")
```

Pass the candidate's source files / one-line purpose / behavior summary in the dispatch prompt so create-asset's clarifying step has grounding. Optionally pass `--empty` first (`<product> feature <candidate-slug> --empty`) when you want to scaffold the shell and populate the design body yourself afterward — but the default is the full create-asset run, which authors the design doc and draws the feature's own behavioral diagram. For a candidate, this skill does NOT author the feature folder, does NOT scaffold a per-asset `tech.md` (removed — only the product carries `tech.md`), and does NOT seed any workflow. create-asset owns the asset scaffold + its diagrams. (The product-level `## Layout` diagram in Step P6 is the only `layout`-kind diagram this skill draws, and it lands inline in `design.md`, not in a feature folder.)

After every candidate is resolved:

- If any candidate was scaffolded, add a path-qualified wikilink to each under the product design doc's `## Roadmap` section.

This step emits `no-candidates` if Agent D returned an empty `findings` list.

### P11 — Verify

- Product design doc contains zero source URLs (no `/blob/`, `/-/blob/`, `/src/`, `/tree/` for any forge) and no `spec_source_branches` frontmatter.
- Both product docs carry the default `spec_source_docs` frontmatter array and a body `# Sources` section with the `#protected/spec/sources` tag and a `## Docs` sub-section whose bullets match the frontmatter list (per `${CLAUDE_PLUGIN_ROOT}/references/spec.sources-protocol.md`).
- Product tech doc source URLs are all produced by `spec.source-url` (never inlined forge path schemes) and carry no line-number fragments.
- Both product docs carry the migrated `spec_role` + `spec_stage` frontmatter and the mandatory header (frontmatter + H1 + breadcrumb) per `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`.
- No operator-zone folder-note, no `human-tasks.md`, no `spec_role: layout` doc, no `layout.excalidraw` file, and no `backlog/` were created (those are removed roles / product-config's territory). The `## Layout` diagram is an inline mermaid fence in `design.md`, not a separate doc.
- No sub-product folders were created (scaffolded candidates are **features** under `<spec_path>/features/`, delegated to create-asset, never sibling products).
- Wikilinks use path-qualified form per `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md` and target existing pages.
- **Product-diagram-seam coverage** (Caller-contract clause 3 of `lazycortex-diagram:lazy-diagram.draw`): the declared product seam set is `{design.md:## Behavior:flow, design.md:## Layout:layout, tech.md:## Architecture:c4-container, tech.md:## Components:class}` — four seams (the `layout` kind is drawn inline in `design.md`, not as the removed `layout` doc-role / excalidraw). List `.logs/claude/lazy-diagram.draw/` entries created in this run (compare timestamps against this run's start) and confirm every declared seam appears as one logged invocation with an outcome word (`skipped-section-empty` is a valid outcome for the layout seam when the product has no UI). Any declared seam without a log entry — or any logged invocation outside the declared set — is a Verify failure. Feature-candidate diagrams are owned and logged by create-asset, not counted here.

### P12 — Log the run

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/spec.create-from-code/YYYY-MM-DD_HH-MM-SS.md`. Create the dir with `Bash(mkdir -p ./.logs/claude/spec.create-from-code)`, then `Write` the file — never chain. Frontmatter: `git_sha` (`git rev-parse HEAD`), `git_branch`, `date` (UTC, `date -u +'%Y-%m-%d %H:%M:%S UTC'`), `input` (the arguments passed, or `none`). Body: `# spec.create-from-code` heading, then `## Actions` and `## Result`. The `## Actions` list MUST record one line per task in the product-mode canonical list with its outcome word — a missing line is a bug.

## Feature Mode Process

Feature mode scaffolds ONE feature-candidate from code by delegating to `spec.create-asset`. This skill no longer authors the feature folder itself.

### F1 — Determine the feature slug

If the slug is obvious from the user's input or the source path, use it (lowercase-with-hyphens per `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`). Otherwise ask the user via `AskUserQuestion`. If the parent product's `source` is needed for grounding, it was already captured in Step 0.

### F2 — Delegate to spec.create-asset

Invoke via the `Skill` tool:

```
Skill(skill: "lazycortex-specs:spec.create-asset", args: "<product> feature <slug>")
```

Pass the candidate's behavior summary / source files in the dispatch prompt so create-asset's clarifying step (Step 3) and prose step (Step 6) have code grounding. Optionally append `--empty` to scaffold the shell only, then populate the design body afterward; the default full run authors `design.md` and draws the feature's `flow` diagram.

create-asset owns: the asset folder + status folder-note, the authored docs (`design.md` + `plan.md` — NO per-asset `tech.md`, NO `layout` doc), per-file start stages, the prose, and the behavioral diagram(s). This skill seeds NO workflow, scaffolds NO `tech.md`, and draws NO `layout` diagram. Capture create-asset's report for this skill's report. The drawer/scaffold outcomes belong to create-asset's run — do not re-verify its internal seams here.

### F3 — Verify

- `spec.create-asset` returned a complete report (one line per its canonical task). Surface that report.
- The feature folder exists at `<spec_path>/features/<slug>/` with the docs create-asset scaffolds (folder-note + `design.md` + `plan.md`); confirm NO `tech.md` and NO `layout` doc were created.
- This skill drew no diagrams and authored no folder-note — confirm `.logs/claude/lazy-diagram.draw/` carries only entries owned by the delegated create-asset run, none authored directly by this skill.

### F4 — Log the run

Per `.claude/rules/lazy-log.logging.md`, write a run log to `./.logs/claude/spec.create-from-code/YYYY-MM-DD_HH-MM-SS.md` exactly as in Step P12, with one `## Actions` line per feature-mode task and its outcome word.

## Report

One line per task in the active mode's canonical list, with its outcome word. A missing line is a bug. In product mode, end with the product-diagram-seam coverage line from Step P11. In feature mode, include the `spec.create-asset` report captured in Step F2.

## Key Rules

- **Never invent behavior** — only document what the code actually does.
- **This skill never registers products** — `/spec.product-config` owns the product record and the operator-zone folder tree. Requires a registered, code-bound product (has `source`); refuses an unregistered product, no-ops a design-only one.
- **Strict file roles** — the product design doc NEVER contains source URLs; the product tech doc DOES (per `${CLAUDE_PLUGIN_ROOT}/references/spec.layout-protocol.md`).
- **No nested products** — sub-areas become `## Architectural Areas` subsections of the product tech doc, not separate product spec folders.
- **Delegate heavy reads** — parallel Explore agents scan source; the main session synthesizes and decides.
- **Feature mode delegates to create-asset** — it owns the asset scaffold, docs, and diagrams. No per-asset `tech.md`, no `layout` diagram, no seeded workflow originate from this skill.
- **Product diagrams: `flow` + `layout` + `c4-container` + `class`** — four inline mermaid seams. `flow` + `layout` land in `design.md` (`## Behavior` / `## Layout`), `c4-container` + `class` in `tech.md`. The `layout` seam is an inline diagram only — never the removed `spec_role: layout` doc / `layout.excalidraw` file. `layout` reports `skipped-section-empty` when the product has no UI.
- **Source attribution** — both product docs carry default `spec_source_docs` frontmatter and a body `# Sources` section (`## Docs` projected from that list; `## Requests` empty), mirroring `spec.create-asset`, per `${CLAUDE_PLUGIN_ROOT}/references/spec.sources-protocol.md`.
- **Migrated frontmatter keys** — authored docs use `spec_role` / `spec_stage`; per-file stages flow through `spec.set-stage`. Pins use `spec_source_branches`.
- **Naming, folder structure, header section, and wikilink format** are owned by `${CLAUDE_PLUGIN_ROOT}/references/` — this skill never inlines those patterns.

## Failure modes

- **Refuses naming an unregistered product** — `<product>` has no record in `lazy.settings.json[products]` → register it via `/spec.product-config`, then re-invoke.
- **No-ops on a design-only product** — the product has no `source` block → attach a repo via `/spec.product-config` (edit mode), then re-invoke.
