---
name: lazy-experts.claude-plugin
description: "Claude Code plugin authoring expertise. Composes onto any of the lazy-experts generic agents so the resulting specialist knows the plugin tree layout, marketplace conventions, artifact contracts, install patterns, and consumer-effort versioning."
---
# lazy-experts.claude-plugin aspect

Adds Claude Code plugin authoring expertise to whichever generic expert composes this aspect. Pure prompt layer — does not extend the runtime contract. Composes onto `lazy-experts.interpreter` (clarifying a plugin request), `lazy-experts.designer` (writing a plugin design spec), `lazy-experts.planner` (writing a plugin implementation plan), and any future generic agent in this plugin.

## Purpose

A generic agent composing this aspect knows the LazyCortex plugin tree layout, the marketplace registration contract, the per-artifact authoring contracts (agents, skills, rules, references), the install / sync / publish lifecycle, and the consumer-effort versioning semantics. The agent uses this knowledge to interpret a plugin-related request more precisely, to write a design that fits the marketplace's expectations, or to plan a plugin change as a sequence of conventional commits with the correct version-bump semantics.

## Side-effect rules

No side-effects beyond the standard expert-runtime contract. This aspect does not expand the expert's write permissions; the expert writes only under `result/` per the protocol delivered by its dispatching routine.

## Kind / role / outcome additions

No additions. This aspect does not introduce new universal `kind`, `role`, or `outcome` values; the protocol delivered by the dispatching routine defines the vocabulary.

## Discovery and tooling

| Question | Action |
|---|---|
| What does a LazyCortex plugin's directory look like? | `Glob claude/<plugin>/**` — every plugin under `claude/` is a sibling. Standard subdirs: `.claude-plugin/`, `agents/`, `skills/`, `commands/`, `rules/`, `references/`, `templates/`, `hooks/`, `help/`, `bin/`. |
| Where is the marketplace registered? | `Read .claude-plugin/marketplace.json` — owner block plus alphabetical `plugins[]` array of `{name, description, source}` rows. |
| What does the plugin manifest look like? | `Read claude/<plugin>/.claude-plugin/plugin.json` — `name`, `version`, `description`, `author`, optional `dependencies[]`. |
| What does the plugin's user-facing overview look like? | `Read claude/<plugin>/.claude-plugin/overview.md` — `## Blocks`, `## Walkthroughs`, `## Requirements`, `## Quick start`. |
| What rules govern authoring an agent / skill / rule / reference? | `Read claude/lazycortex-core/rules/lazy-core.agent-writing.md`, `…skill-writing.md`, `…rule-writing.md`, `…reference-writing.md`. |
| What templates exist for scaffolding? | `Glob claude/lazycortex-core/templates/core/*.md` plus the `.claude/templates/help/` overview / walkthrough / block / faq / troubleshooting templates. |
| Where is the scaffold registry that pins each template to a glob? | `Read ~/.claude/rules/lazy-core.scaffold.md` and `.claude/rules/lazy-core.scaffold.md`. |
| What does the per-plugin lifecycle look like? | Three LazyCortex conventions: (1) **consumer-effort SemVer** — Patch = drop-in (no consumer action), Minor = re-run install (new artifacts ship), Major = migrate data (incompatible on-disk schema change); (2) **per-plugin lifecycle artifacts** — every plugin SHOULD ship an audit skill and a `<namespace>.help` command (not a help skill); (3) **commit pipeline** — staged changes under `claude/<plugin>/` route through `/pub.pre-commit <wip\|final> "<subject>"` before any commit lands. |

Skills / commands available to the expert in this domain (read-only unless otherwise noted):

- `/lazy-core.audit` — read-only configuration audit; merge findings into design or plan output where relevant.
- `/lazy-core.doctor` — health check across consumer config; cite findings rather than re-run.
- `/pub.pre-commit <wip|final> "<subject>"` — invoked by the *operator*, not the expert. Mention it in a plan, never call it from inside an agent run.

## Obligations

- **Anchor every claim to a contract file.** When a design or plan references "the agent-writing rule" or "the marketplace schema", spell the path: `claude/lazycortex-core/rules/lazy-core.agent-writing.md`, `.claude-plugin/marketplace.json`. Vague references are an audit finding.
- **Honor consumer-effort versioning.** Patch = drop-in (nothing for consumer); Minor = re-run install (new artifacts ship); Major = migrate data (incompatible on-disk schema change). New artifact in a design → the plan's commit subject implies a Minor bump; a hand-edit of `version:` mid-plan is a planning bug.
- **Every new agent registers a model tier.** Per `lazy-core.agent-writing § 8`, a new agent appears in `lazy.settings.json[agent_models]` (consumer-side wiring) and, if the agent is a canonical default, in `claude/lazycortex-core/skills/lazy-core.agent-models/default-tiers.json` (template defaults). A design that adds an agent without naming the tier registration is incomplete.
- **Every new artifact starts from its scaffold template.** Per the scaffold registry, write tasks for new agents / skills / rules / references must explicitly call out reading the matching template first.
- **Per-tool `allow` / `ask` permissions stay in `settings.local.json`.** Never propose adding them to tracked `settings.json`; per-tool `deny` is allowed in tracked. Cite `lazy-core.hygiene § Settings split strategy`.
- **Plugin-shipped help is a COMMAND, not a skill.** `claude/<plugin>/commands/<namespace>.help.md`, not `skills/<namespace>.help/`.
- **No hardcoded absolute paths in shipped files.** Use `~`, `$HOME`, `${CLAUDE_PLUGIN_ROOT}`, or relative `.claude/…`. Per `lazy-core.hygiene § Path hygiene`.
- **Plugin source under `claude/`, not `.claude/`.** Edits to `.claude/{rules,agents,skills}/<X>` that mirror plugin source are install-managed; the source of truth is `claude/<plugin>/`.
