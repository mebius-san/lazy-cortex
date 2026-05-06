---
chapter_type: block
summary: Bootstrap lazycortex-diagram in your project — sync the authoring rule, seed agent-model tiers, and clean up orphans.
last_regen: 2026-05-05
no_diagram: true
source_skills:
  - lazy-diagram.install
---
# Install lazycortex-diagram

One command wires the plugin into whichever scope you enabled it at. The bootstrap is small by design: a single authoring rule, agent-model tier seeds for the two drawer agents, and orphan cleanup for any rules left over from earlier versions. Templates and style schemes ship inside the plugin itself and are never copied out.

## What's in this block

`/lazy-diagram.install` does four things in one pass: it detects whether you enabled the plugin at user scope or project scope, syncs the `lazy-diagram.authoring` rule into the matching `.claude/rules/` directory, seeds `lazy.settings.json` with the agent-model tiers for `lazy-diagram.draw-mermaid` and `lazy-diagram.draw-ascii` (tier values come from `lazycortex-core`'s `default-tiers.json` so they stay consistent across plugins), and offers to delete any `lazy-diagram.*` rules that a previous version shipped but no longer does. Every action is idempotent — re-running after `/plugin update` is safe and is the correct way to pick up rule changes.

## How it works

Run `/lazy-diagram.install` once after enabling the plugin. The skill detects your install scope automatically, walks you through one rule-sync prompt per file it finds, and confirms each `agent_models` entry it writes. When the run completes, `/lazy-diagram.draw` and `/lazy-diagram.fix` are ready to use. If the authoring rule was newly installed or updated, restart Claude Code so the rule loads into your next session.

To check overall plugin health after install, run `/lazy-core.doctor`. lazycortex-diagram has no user-facing audit skill; doctor is the right tool for health verification.

## Where this fits

The install block is the foundation for everything else in lazycortex-diagram. Once it's done, the drawing block covers inserting new diagrams (`/lazy-diagram.draw`) and refreshing existing ones (`/lazy-diagram.fix`).
