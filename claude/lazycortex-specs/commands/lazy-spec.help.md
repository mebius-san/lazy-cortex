---
description: "Run when the operator asks what lazycortex-specs can do, which verb creates or advances a spec, or how the readiness gates work — lists the spec-vault surface grouped by phase: product bootstrap, asset authoring, gates and per-doc stages, request intake and routing, code sync and doctor, plus the resolver primitives other skills call."
execution-discipline-waiver: "help command — static text, no multi-step logic"
logging-waiver: "static text — no executable steps"
---
Output the block below verbatim to the user. Do not summarize, rephrase, or add commentary. Do not invoke any tools. Do not log this run.

---

**lazycortex-specs** — specification and design skills for Claude Code.

Authors product / feature / change / bug (and operator-defined) specs as Markdown notes in an Obsidian-friendly vault, scaffolds a gate-driven folder structure, and keeps the spec aligned with the source repo. Product config lives in `lazy.settings.json[products]`; asset state is five flat boolean gates per asset folder-note.

## Bootstrap

- `lazy-spec.install` — Ensure consumer spec dirs exist, register the `lazy-spec.gate-tick` routine, optionally chain into `lazy-spec.product-config`. Idempotent.
- `lazy-spec.product-config` — Wizard to create or edit a product record in `lazy.settings.json[products]`; scaffolds folder-notes with icons and built-in review classes; auto-detects deps.
- `lazy-spec.add-asset-type` — Declare a new asset type on a product (icon, start document, default tools and path) and settle its playbook; review coverage is inherited from the shared behavior-keyed classes.
- `lazy-spec.create-from-code` — Generate product- or feature-level spec from an existing codebase via parallel Explore agents (code-bound products only).

## Authoring

- `lazy-spec.create-asset` — Universal: scaffold an asset of any category (built-in or operator-defined) — folder-note + authored docs + behavioral diagram(s); `--empty` for a bare scaffold.
- `lazy-spec.create-feature` / `lazy-spec.create-change` / `lazy-spec.create-bug` — Thin wrappers that pin the category and delegate to `lazy-spec.create-asset`.
- `lazy-spec.create-request` — Capture a raw idea into the product's `requests/` inbox as a body-only file; the request subsystem adds frontmatter and routes it during review.
- `lazy-spec.decide` — Interactive wrapper over the `decide` CLI primitive (`add` / `supersede <id>` / `obsolete <id>` / `promote <living-doc>`) for an asset's or product's `decisions.md` registry.

## Gates & lifecycle

- `lazy-spec.flip-gate` — The single channel for flipping one asset gate (`spec_design_done` … `spec_released`); flips unconditionally once confirmed (refuses only a cancelled asset) — interactive confirm, or `--auto`.
- `lazy-spec.gate-tick` (worker) — Script-only md-scan worker: polls an asset's active expert job for a terminal marker and structurally checks the folder-note. Dispatched by the `lazy-spec.gate-tick` routine.
- `spec.coordinator` (agent, `lazy-spec.coordinator-watch` git-watch routine) — Decides gate readiness, promotes doc stages, and dispatches launch-checkbox / cascade jobs, woken on a commit that reaches the daemon's own checkout; see `lazy-spec.coordination-playbook.md`.
- `lazy-spec.set-stage` — Change one authored doc's `spec_stage` (`empty | draft | approved | rejected | cancelled`), mirror the `spec/<stage>` tag, and log to the folder-note `# History` section.
- `lazy-spec.finalize-branch` — Rebase pinned specs back to the repo's default branch after a source branch is merged or deleted; propose `spec_released` flips.

## Request processing

- `spec.coordinator` (agent) — Routing mode, woken at the terminal group of a request's own review cycle: classifies, finds candidates, writes the `# Routing` section as a per-target description + structured decision block (surfaces the routing decision as a `[!question]`, folds the answer to prose). Composes the two read-only primitives below.
- `lazy-spec.request-apply` (worker) — Post-finalize executor (Python primitive at `bin/apply_request.py`): reads the resolved routing prose, calls `lazycortex-specs scaffold-asset` for spawns, seeds each entity's primary doc with the coordinator's per-target description (never the request body — the doc's own main writer pulls the request from `context/` on its review round), opens review cycles, stamps the terminal `request_status`. No LLM dispatch; attach and spawn are both branches inside this one primitive.
- `lazy-spec.request-classify` — Primitive: body → `request_class` (open set: closed meta classes plus the product's asset types).
- `lazy-spec.request-find-candidates` — Primitive: body + class → ranked existing-entity matches.

## Sync & validation

- `lazy-spec.sync-with-code` — Diff source-repo commits against the last synced commit and propagate relevant changes into a product spec; propose gate flips.
- `lazy-spec.upstream-run` — Manual, no-daemon counterpart of the `lazy-spec.upstream-tick` routine: mirrors every configured external design source, derives each unit's status, opens a request for a ticked unit, and unfreezes an `in-review` unit whose linked request concluded.
- `lazy-spec.doctor` — Audit a product spec for staleness, broken links, role/gate/stage inconsistencies; offer targeted fixes.
- `lazy-spec.coverage` — Gap-scan a product's structure map and domain groups against its spec-asset tree; report uncovered capabilities with a proposed category + slug for a retro-spec.
- `lazy-spec.audit` — Read-only health check of the plugin's own artifacts (rule invariants, CLI-to-help coverage, reference/template wiring); the plugin's `<namespace>.audit`, distinct from `lazy-spec.doctor`'s consumer-content checks.
- `lazycortex-specs pins` (CLI, no skill wrapper) — One-shot backfill: add `wiki_pinned_topics` to every role-bearing spec doc missing it (pre-dates the pin landing in its template, or was scaffolded from an unrefreshed per-product/per-category override). Idempotent, repeatable — `lazy-spec.doctor` reports missing pins but never writes them.

## Primitives (called by other skills)

- `lazy-spec.resolve-repo` — Resolve a repo key (from the `lazy.settings.json[repos]` section) to runtime metadata (`local_path`, `branch`, `host`, `owner`, `repo`, `forge`, `base_url`).
- `lazy-spec.resolve-dependency` — Resolve a product's `dependencies` entry to concrete links (spec wikilink, source URL).
- `lazy-spec.source-url` — Build a single forge-correct source URL for a file in a source repo.
- `lazy-spec.refresh-sources` — Re-project a doc's body `# Sources` sub-sections (`## Requests`, `## Docs`) from its `spec_source_requests` / `spec_source_docs` frontmatter, preserving operator-authored glosses.
- `lazy-spec.lookup` — Bounded research slice of the spec tree around a product or asset: a question or token plus an optional anchor, returning matching paths with short excerpts, never whole documents.

See `${CLAUDE_PLUGIN_ROOT}/references/` for the protocol contracts each skill respects (config files, folder structure, per-file stages, gate semantics). The plugin's first rule, `spec.decisions` (mirrored into `.claude/rules/` by `lazy-spec.install`), holds the two decisions-registry duties every spec-catalog edit is bound by: read the accumulated decisions before the first edit, and reserve a decision statement for a genuine fork.

<!-- help-block:start -->
**Documentation:**

- [authoring](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/authoring.md) — Create spec assets of any type — features, changes, bugs, and operator-declared kinds — record the decisions behind them, and capture raw ideas into the requests inbox.
- [code-sync](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/code-sync.md) — Keep a product spec aligned with its source repo — pull in-flight code changes into the tech doc, rebase branch pins after a merge, and gap-scan for capabilities the spec tree never documented.
- [gates](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/gates.md) — Drive an asset's readiness gates and per-file doc stages from creation through release using a two-layer progression model.
- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/install-and-audit.md) — Bootstrap the plugin, register products, and audit both the plugin's own sources and a product's spec health.
- [requests](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/requests.md) — Ingest free-form requests and route them into the right place in the spec tree — classify, find candidates, then let the deterministic apply worker attach, spawn, or link.
- [research](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/research.md) — Answer one question against the spec tree without loading whole documents into your context.
- [source-links](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/source-links.md) — Resolve repos, dependencies, and build forge-correct source URLs so every spec link stays accurate regardless of where code is hosted.
- [upstream](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/upstream.md) — Mirror external design repos into your vault and keep a spec doc's visible source list matching its frontmatter.
- [asset-to-release](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/walkthroughs/asset-to-release.md) — Take one spec asset from a blank slate through all five readiness gates to a confirmed release.
- [new-product-from-code](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/walkthroughs/new-product-from-code.md) — Register a product bound to an existing codebase, generate its design and tech docs from source, then scaffold the first feature.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/troubleshooting.md) — Common failure modes across lazycortex-specs skills — symptoms, likely causes, and targeted fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-specs/help/faq.md) — Answers to common questions about products, assets, gates, requests, decisions, coverage gaps, spec lookups, and the coordinator agent.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-specs/help/`.
<!-- help-block:end -->
