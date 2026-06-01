---
description: Show lazycortex-experts purpose and a one-line summary of each agent, aspect, skill, and command it ships
execution-discipline-waiver: "static help text — no executable steps"
logging-waiver: "static text — no executable steps"
---
Output the block below verbatim to the user. Do not summarize, rephrase, or add commentary. Do not invoke any tools. Do not log this run.

---

**lazycortex-experts** — generic doc-producing experts plus a starter set of domain aspects. Three persona-only agents (interpreter / designer / planner) combine with composable aspect files (claude-plugin / game-dev / dotfiles) to form specialists you assemble in `lazy.settings.json[experts]`. No protocols, routines, or dispatcher ship from this plugin — the dispatching routine supplies the protocol and the agent follows it.

**Agents** (invoke via Agent tool, normally only via a routine that dispatches expert jobs):

- `lazy-experts.interpreter` — takes a free-form human request / doc / log, produces a gap-free premise-first structured brief. Surfaces unresolved gaps as callouts in the output; never calls AskUserQuestion. Models its iteration shape on `superpowers:brainstorming`.
- `lazy-experts.designer` — takes a brief, produces a detailed design specification with premise-led structure, scope discipline, and declarative-over-prescriptive language. Stays out of implementation choices.
- `lazy-experts.planner` — takes a design spec, produces an ordered bite-sized implementation plan with file-level tasks, test plan, and rollback. Models its output on `superpowers:writing-plans`. Stays out of design choices.

**Aspects** (compose into any of the three agents via `lazy.settings.json[experts][<expert>].aspects[]`):

- `lazy-experts.claude-plugin-aspect` — Claude Code plugin authoring expertise (plugin tree, marketplace, artifact contracts, install / sync / publish lifecycle, consumer-effort versioning).
- `lazy-experts.game-dev-aspect` — general game-development expertise (core loop, progression, balance, telemetry, content vs mechanics separation).
- `lazy-experts.dotfiles-aspect` — general principles for personal-computer / network configuration management (dotfile-repo conventions, shell rc structure, host-vs-personal split, package manifests, init systems, secret handling). Public-marketplace-safe.

**Skills** (invoke as `/<name>` or via Skill tool):

- `lazy-experts.install` — bootstrap the plugin for the current project (or globally). Seeds agent-model tiers from `lazycortex-core`'s defaults into `lazy.settings.json[agent_models].lazycortex`. Idempotent.

**Commands**:

- `lazy-experts.help` — this listing.

**Composition example** (consumer-side, `<repo>/.claude/lazy.settings.json`):

```jsonc
"experts": {
  "_version": 1,
  "claude-plugin-designer": {
    "agent": "lazycortex-experts:lazy-experts.designer",
    "aspects": ["lazycortex-experts:lazy-experts.claude-plugin-aspect"]
  },
  "game-designer": {
    "agent": "lazycortex-experts:lazy-experts.designer",
    "aspects": ["lazycortex-experts:lazy-experts.game-dev-aspect"]
  }
}
```

The expert never runs until a routine elsewhere dispatches a job to it — by design.

<!-- help-block:start -->
**Documentation:**

- [agents](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/agents.md) — Three persona-only agents (interpreter, designer, planner) that transform a raw request into a structured brief, a design spec, and an implementation plan.
- [aspects](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/aspects.md) — Three domain aspect files (claude-plugin, game-dev, dotfiles) that layer domain knowledge onto any generic expert via lazy.settings.json composition.
- [composition](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/composition.md) — Assemble a named specialist by pairing one generic agent with one or more domain aspects in lazy.settings.json[experts].
- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/install-and-audit.md) — Bootstrap lazycortex-experts by seeding agent-model tiers and pre-composed expert entries for all agent × domain-aspect pairs into lazy.settings.json.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/troubleshooting.md) — Common failure modes during lazycortex-experts setup — symptoms, likely causes, and fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-experts/help/faq.md) — Common questions about installing lazycortex-experts, composing specialists, understanding the three-agent pipeline, and working with domain aspects.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-experts/help/`.
<!-- help-block:end -->
