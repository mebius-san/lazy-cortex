---
iconize_icon: LiInfo
iconize_color: "#fde68a"
---
# lazycortex-diagram

Format-agnostic diagram engine: /lazy-diagram.draw dispatcher + per-format writer agents (mermaid, ascii, more later). Picks kind and format from request context, ships exemplar templates plus an authoring contract, and bundles a fixture-based regression suite.

## Why this plugin

Mermaid and ASCII diagrams in long-running docs drift from house style as palettes, init directives, and per-kind conventions evolve. Each one-off diagram becomes a tiny exception that nobody owns. lazycortex-diagram centralises diagram production behind a single dispatcher that picks the right kind and format for the request, hands it to a per-format writer agent, and renders against shipped templates and named style schemes. New diagrams stay current; old fences can be re-conformed in place.

## Who it's for

- Authors of Markdown documentation (architecture notes, runbooks, ADRs) who want consistent, theme-correct mermaid and ASCII diagrams without hand-tweaking each fence.
- Plugin authors who want to ship style-aware diagrams whose palette, init directive, and density bounds are governed by a contract instead of memory.

## Blocks

- **install-and-audit** — Bootstrap lazycortex-diagram in your project. Covers what `/lazy-diagram.install` drops (the authoring rule, templates under `templates/diagram.<format>/`, style schemes, agent-model tier seeds for the per-format writer agents). lazycortex-diagram has no user-facing audit — for health verification use `/lazy-core.doctor`. Members: lazy-diagram.install.
- **drawing** — Insert and refresh diagrams in Markdown documentation against shipped templates and named style schemes. Members: lazy-diagram.draw, lazy-diagram.fix, lazy-diagram.draw-mermaid, lazy-diagram.draw-ascii.

## Requirements

- **Claude Code** with plugin support.
- `lazycortex-core` plugin (declared dependency) — supplies the install skill, doctor checks, and parallel-scan reference used by `lazy-diagram.audit`.

## Quick start

1. Install the marketplace and enable the plugin (`/plugin install lazycortex-diagram@lazycortex`).
2. Run `/lazy-diagram.install` to wire local config.
3. Insert a new diagram: `/lazy-diagram.draw target_file=<abs path> anchor_section="## <H2>" request="<one-line description>"`. The skill picks `(kind, format)`, dispatches the per-format writer agent, and writes a fence under the heading.
4. Re-conform an existing diagram: `/lazy-diagram.fix target_file=<abs path> anchor_section="## <H2>"`. The skill infers `(kind, format)` from the fence and rewrites it against the current scheme.
5. To embed diagram seams inside another skill, follow the `Caller contract` in `skills/lazy-diagram.draw/SKILL.md` (numbered substep, per-seam TaskCreate, Verify section).

## Dependencies

Requires these plugins from the same marketplace:

- [`lazycortex-core`](../lazycortex-core/) — Core skills, agents, and runtime daemon for Claude Code (expert runtime + agent-model routing + settings management)

## Skills

| Skill | Description |
|---|---|
| `lazy-diagram.audit` | Audit the lazycortex-diagram plugin: verify template well-formedness, exemplar conformance against the authoring rule, and role + init-block coverage in styles-*.json schemes. Parallel-scan coordinator dispatching 3 read-only Explore agents (A2, A3, A5). Read-first; presents findings, asks before fixing. Severity: PASS / WARN / FAIL / INFO. TODO: re-add fixture-related scans (A1, A4) when the final dev-vs-shipped split is decided. |
| `lazy-diagram.draw` | Diagram dispatcher — picks (kind, format) for a free-form request, dispatches the per-format drawer agent, byte-compares against the existing fence under the anchor, and writes (or skips) one fenced diagram. Outcome vocabulary: created / replaced / unchanged / skipped-below-threshold / failed:<reason> / split-into-N. Use when you want a NEW diagram inserted under a named heading; for migrating an existing fence to current standards see /lazy-diagram.fix. |
| `lazy-diagram.fix` | Take an existing diagram fence and re-conform it to the current drawer-agent standards. Reads the host section's prose as the request, infers (kind, format) from the existing fence's syntax marker, dispatches the per-format drawer agent, and replaces the fence in place when the body differs. Outcome vocabulary: replaced / unchanged / failed:<reason>. Use when an old diagram drifted from the contract (palette removed, theme directive missing, terminology changed); for inserting a NEW fence under a heading see /lazy-diagram.draw. |
| `lazy-diagram.install` | Bootstrap the lazycortex-diagram plugin for the current project (or globally). Syncs the authoring rule shipped by the plugin into the consumer's rules directory and seeds agent model tiers for the per-format drawer agents. Idempotent and quiet on re-run — an enabled plugin installs its whole surface, decisions are derived not asked, and orphaned rules are left in place. Detects install scope automatically. |

## Documentation

Step-by-step walkthroughs, troubleshooting decision-tree, and FAQ for the scenarios above:

- [drawing](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-diagram/help/drawing.md) — Insert new diagrams and refresh existing ones — dispatcher picks kind and format from your prose, writer agents render against shipped templates and style schemes.
- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-diagram/help/install-and-audit.md) — Bootstrap lazycortex-diagram in your project — sync the authoring rule, seed agent-model tiers, and clean up orphans.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-diagram/help/troubleshooting.md) — Common failure modes across lazycortex-diagram skills — symptoms, likely causes, and fixes.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-diagram/help/faq.md) — Answers to common questions about kind/format selection, scheme palettes, draw vs fix, ASCII vs mermaid, density bounds, split behaviour, direct agent invocation, and install.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-diagram/help/`.

## Agents

| Agent | Description |
|---|---|
| `lazy-diagram.draw-ascii` | Single-pass writer agent: produces an ASCII diagram body for a given (kind, request, exemplar). Dispatched by /lazy-diagram.draw or /lazy-diagram.fix, or invokable directly by any caller that supplies kind=<X>. Returns the diagram block content (without surrounding triple-backticks) as its response. Use when you have already chosen kind=<one of: flow, fs-tree, layout> and format=ascii. |
| `lazy-diagram.draw-mermaid` | Single-pass writer agent: produces a mermaid diagram body for a given (kind, request, scheme). Dispatched by /lazy-diagram.draw or /lazy-diagram.fix, or invokable directly by any caller that supplies kind=<X>. Returns the diagram fence content (without surrounding triple-backticks) as its response. Use when you have already chosen kind=<one of: flow, sequence, state, erd, class, architecture, layout, nav, tree, controls-scheme, decision-tree, screen-scheme, journey, mindmap, gantt, timeline> and format=mermaid. |

## Commands

| Command | Description |
|---|---|
| `lazy-diagram.help` | Show lazycortex-diagram purpose and a one-line summary of each skill, agent, and rule it ships |

## Rules

| Rule | Description |
|---|---|
| `lazy-diagram.authoring.md` | Authoring contract — closure relationship between diagram templates, style files, and emitted fences. |

## Installation

Add the marketplace and enable the plugin in your global `~/.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "lazycortex": {
      "source": {
        "source": "github",
        "repo": "mebius-san/lazy-cortex"
      },
      "autoUpdate": true
    }
  },
  "enabledPlugins": {
    "lazycortex-diagram@lazycortex": true
  }
}
```

Restart Claude Code. Skills appear as `lazycortex-diagram:<skill.name>`.

## Usage

Invoke skills with slash commands:

```
/lazy-diagram.audit
/lazy-diagram.draw
/lazy-diagram.fix
/lazy-diagram.install
```
