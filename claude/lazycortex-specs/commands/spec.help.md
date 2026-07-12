---
description: Show lazycortex-specs purpose and a one-line summary of each skill it ships
execution-discipline-waiver: "help command — static text, no multi-step logic"
logging-waiver: "static text — no executable steps"
---
Output the block below verbatim to the user. Do not summarize, rephrase, or add commentary. Do not invoke any tools. Do not log this run.

---

**lazycortex-specs** — specification and design skills for Claude Code.

Authors product / feature / change / bug (and operator-defined) specs as Markdown notes in an Obsidian-friendly vault, scaffolds a gate-driven folder structure, and keeps the spec aligned with the source repo. Product config lives in `lazy.settings.json[products]`; asset state is five flat boolean gates per asset folder-note.

## Bootstrap

- `spec.install` — Ensure consumer spec dirs exist, register the `spec.gate-tick` routine, optionally chain into `spec.product-config`. Idempotent.
- `spec.product-config` — Wizard to create or edit a product record in `lazy.settings.json[products]`; scaffolds folder-notes with icons and built-in review classes; auto-detects deps.
- `spec.add-asset-category` — Register an operator-defined asset category on a product (icon + folder-note); review coverage is inherited from the product's behavior-keyed classes.
- `spec.create-from-code` — Generate product- or feature-level spec from an existing codebase via parallel Explore agents (code-bound products only).

## Authoring

- `spec.create-asset` — Universal: scaffold an asset of any category (built-in or operator-defined) — folder-note + authored docs + behavioral diagram(s); `--empty` for a bare scaffold.
- `spec.create-feature` / `spec.create-change` / `spec.create-bug` — Thin wrappers that pin the category and delegate to `spec.create-asset`.
- `spec.create-request` — Capture a raw idea into the product's `requests/` inbox as a body-only file; the request subsystem adds frontmatter and routes it during review.

## Gates & lifecycle

- `spec.flip-gate` — The single channel for flipping one asset gate (`spec_design_done` … `spec_released`) after its precondition is met; interactive confirm, or `--auto`.
- `spec.gate-tick` (worker) — Script-only md-scan worker: auto-flips derived gates and drops `[!ready]` callouts for human-signal gates. Dispatched by the `spec.gate-tick` routine.
- `spec.set-stage` — Change one authored doc's `spec_stage` (`empty | draft | approved | rejected | cancelled`), mirror the `spec/<stage>` tag, and log to the folder-note `# History` section.
- `spec.finalize-branch` — Rebase pinned specs back to the repo's default branch after a source branch is merged or deleted; propose `spec_released` flips.

## Request processing

- `spec.request-router` (agent) — Review-loop specialist: classifies, finds candidates, writes the `# Routing` section (surfaces the routing decision as a `[!question]`, folds the answer to prose). Composes the two read-only primitives below.
- `spec.request-apply` (worker) — Post-finalize executor (Python primitive at `bin/apply_request.py`): reads the resolved routing prose, calls `lazycortex-specs scaffold-asset` for spawns, distributes the body across each entity's WTR doc, opens review cycles, stamps the terminal `request_status`. No LLM dispatch.
- `spec.request-classify` — Primitive: body → `request_class` (open set: closed meta classes plus the product's asset categories).
- `spec.request-find-candidates` — Primitive: body + class → ranked existing-entity matches.
- `spec.request-attach` — Primitive: distribute body across an existing entity's docs; link-only in the folder-note `# Sources` → `## Requests` sub-section; opens fresh review on populated docs.
- `spec.request-spawn` — Primitive: scaffold empty entity (`spec.create-asset --empty`) + delegate to `spec.request-attach`.

## Sync & validation

- `spec.sync-with-code` — Diff source-repo commits against the last synced commit and propagate relevant changes into a product spec; propose gate flips.
- `spec.doctor` — Audit a product spec for staleness, broken links, role/gate/stage inconsistencies; offer targeted fixes.

## Primitives (called by other skills)

- `spec.resolve-repo` — Resolve a repo key (from the `lazy.settings.json[repos]` section) to runtime metadata (`local_path`, `branch`, `host`, `owner`, `repo`, `forge`, `base_url`).
- `spec.resolve-dependency` — Resolve a product's `dependencies` entry to concrete links (spec wikilink, source URL).
- `spec.source-url` — Build a single forge-correct source URL for a file in a source repo.
- `spec.refresh-sources` — Re-project a doc's body `# Sources` sub-sections (`## Requests`, `## Docs`) from its `spec_source_requests` / `spec_source_docs` frontmatter, preserving operator-authored glosses.

See `${CLAUDE_PLUGIN_ROOT}/references/` for the protocol contracts each skill respects (config files, folder structure, per-file stages, gate semantics).

<!-- help-block:start -->
**Documentation:**

- [authoring](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/authoring.md) — Create spec assets of any category — features, changes, bugs, and operator-defined kinds — and capture raw ideas into the requests inbox.
- [code-sync](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/code-sync.md) — Keep a product spec aligned with its source repo — pull in-flight code changes into the tech doc and rebase branch pins after a merge.
- [gates](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/gates.md) — Drive an asset's readiness gates and per-file doc stages from creation through release using a two-layer progression model.
- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/install-and-audit.md) — Bootstrap the plugin, register products, audit spec health, and discover all available skills — the starting point before any authoring work begins.
- [requests](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/requests.md) — Ingest free-form requests and route them into the right place in the spec tree — classify, find candidates, then attach or spawn.
- [source-links](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/source-links.md) — Resolve repos, dependencies, and build forge-correct source URLs so every spec link stays accurate regardless of where code is hosted.
- [asset-to-release](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/walkthroughs/asset-to-release.md) — Take one spec asset from a blank slate through all five readiness gates to a confirmed release.
- [new-product-from-code](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/walkthroughs/new-product-from-code.md) — Register a product bound to an existing codebase, generate its design and tech docs from source, then scaffold the first feature.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/troubleshooting.md) — Common failure modes across lazycortex-specs skills — symptoms, likely causes, and targeted fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/faq.md) — Answers to common questions about products, gates, assets, requests, code sync, source links, and the request pipeline in lazycortex-specs.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-specs/help/`.
<!-- help-block:end -->
