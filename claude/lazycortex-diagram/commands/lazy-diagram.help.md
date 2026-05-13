---
description: Show lazycortex-diagram purpose and a one-line summary of each skill, agent, and rule it ships
execution-discipline-waiver: "static help text — no executable steps"
logging-waiver: "static text — no executable steps"
---
Output the block below verbatim to the user. Do not summarize, rephrase, or add commentary. Do not invoke any tools. Do not log this run.

---

**lazycortex-diagram** — format-agnostic diagram engine. A dispatcher skill picks `(kind, format)` from request context and dispatches per-format drawer agents (mermaid, ascii). Ships exemplar templates per `(kind, format)`, an authoring contract that governs the closure between templates / styles / emitted fences, and styles JSON files for the mermaid pipeline (per-role hex + the whole `blocks.init.<kind>` init line per kind).

**Skills** (invoke as `/<name>` or via Skill tool):

- `lazy-diagram.draw` — entry point. Takes a free-form request (plus optional `kind` / `format` / `scheme` pins), resolves `(kind, format)` via an inline heuristic, dispatches the matching drawer agent, byte-compares against any existing fence under the anchor, and writes (or skips) one diagram block. Outcome vocabulary: `created` / `replaced` / `unchanged` / `skipped-below-threshold` / `failed:<reason>` / `split-into-N`.
- `lazy-diagram.fix` — for migrating existing fences to current standards. Takes the host section's prose as the request and the existing fence's syntax marker as the kind hint, then re-runs the drawer pipeline and replaces the fence in place when the body differs. Use when an old diagram drifted from the contract.
- `lazy-diagram.audit` — read-only audit of the plugin's own surface: template well-formedness, exemplar conformance against drawer-agent sanity checks, and role + init-block coverage in `styles-*.json` schemes. Parallel-scan coordinator. Read-first; nothing mutated until approved.
- `lazy-diagram.install` — bootstrap the plugin for the current project (or globally). Syncs the authoring rule into the consumer's rules directory, seeds agent model tiers, and cleans up orphaned rules. Idempotent — safe to re-run.

**Agents** (invoke via Agent tool, normally only via the draw / fix skills):

- `lazy-diagram.draw-mermaid` — single-pass writer. Produces a mermaid diagram body for a given `(kind, request, scheme)`; returns the fence content (without surrounding triple-backticks). Self-contained: enforces every drawing-time sanity check itself.
- `lazy-diagram.draw-ascii` — single-pass writer. Produces an ASCII diagram body for a given `(kind, request, exemplar)`; returns the block content (without surrounding triple-backticks). Self-contained: enforces every drawing-time sanity check itself.

**Rules**:

- `lazy-diagram.authoring` — authoring contract: the closure relationship between templates, style files, and emitted fences (every field a template references must resolve in every shipped style file's `roles{}` / `textConstants{}` / `blocks.init.<kind>`; nothing fabricated). Loaded only when a template or `styles-*.json` is being edited.

**Commands**:

- `lazy-diagram.help` — this listing.

<!-- help-block:start -->
**Documentation:**

- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-diagram/help/install-and-audit.md) — Bootstrap lazycortex-diagram in your project — sync the authoring rule, seed agent-model tiers, and clean up orphans.
- [drawing](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-diagram/help/drawing.md) — Insert new diagrams and refresh existing ones — dispatcher picks kind and format from your prose, writer agents render against shipped templates and style schemes.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-diagram/help/troubleshooting.md) — Common failure modes across lazycortex-diagram skills — symptoms, likely causes, and fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-diagram/help/faq.md) — Answers to common questions about kind/format selection, scheme palettes, draw vs fix, ASCII vs mermaid, density bounds, and split behaviour.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-diagram/help/`.
<!-- help-block:end -->

See `README.md` in the plugin for full scenarios and the kind/format matrix.
