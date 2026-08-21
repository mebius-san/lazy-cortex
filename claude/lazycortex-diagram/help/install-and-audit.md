---
chapter_type: block
summary: Bootstrap lazycortex-diagram in your project — sync the authoring rule, seed agent-model tiers, and clean up orphans.
last_regen: 2026-08-19
no_diagram: true
source_skills:
  - lazy-diagram.install
source_sha: 4aec8c6f6f952dc8b1c993f13bdec2a1a00a9ab9
---
# Install lazycortex-diagram

One command wires the plugin into whichever scope you enabled it at. The bootstrap is small by design: a single authoring rule, agent-model tier seeds for the two drawer agents, and orphan cleanup for any rules left over from earlier versions. Templates and style schemes ship inside the plugin itself and are never copied out.

## What's in this block

`/lazy-diagram.install` does four things in one pass: it detects whether you enabled the plugin at user scope or project scope, syncs the `lazy-diagram.authoring` rule into the matching `.claude/rules/` directory, seeds `lazy.settings.json` with the agent-model tiers for `lazy-diagram.draw-mermaid` and `lazy-diagram.draw-ascii` (tier values come from `lazycortex-core`'s `default-tiers.json` so they stay consistent across plugins), and offers to delete any `lazy-diagram.*` rules that a previous version shipped but no longer does. Every action is idempotent — re-running after `/plugin update` is safe and is the correct way to pick up rule changes.

## How it works

Run `/lazy-diagram.install` once after enabling the plugin. The skill detects your install scope automatically, then syncs its rule files without a single prompt: each one is byte-compared against the shipped source — absent means it's copied, byte-identical means nothing happens, and anything that has drifted is overwritten from the shipped source, since a rule mirror isn't an editing surface. A rule the plugin no longer ships is left in place rather than deleted. It reports what it did per file. After rule sync, it seeds the `agent_models` entries it owns. When the run completes, `/lazy-diagram.draw` and `/lazy-diagram.fix` are ready to use. If any rule was newly installed or updated, restart Claude Code so the updated rule loads into your next session.

To check overall plugin health after install, run `/lazy-core.doctor`. lazycortex-diagram has no user-facing audit skill; doctor is the right tool for health verification.

## Where this fits

The install block is the foundation for everything else in lazycortex-diagram. Once it's done, the drawing block covers inserting new diagrams (`/lazy-diagram.draw`) and refreshing existing ones (`/lazy-diagram.fix`).
