---
chapter_type: block
summary: Install click-to-zoom for mermaid diagram fences in your Obsidian vault; the fit-CSS that keeps diagrams inside the column lives in the shared install step, not here.
last_regen: 2026-08-19
no_diagram: true
source_skills:
  - lazy-obsidian.diagram-install
source_sha: 23dd4455aa42f1de52873e78d8bb336a31474adb
---
# Diagram rendering

`/lazy-obsidian.diagram-install` installs `mermaid-popup`, the community plugin that lets you click any mermaid fence in Reading Mode to zoom it. That is the only artifact this skill writes to your vault. It does **not** install or enable the CSS snippets that fit mermaid SVGs and ASCII diagrams to your editor column — `mermaid-fit.css` and `ascii-fit.css` are installed and enabled by `/lazy-obsidian.install`'s shared snippet step instead, so there is only one writer of `appearance.json`'s `enabledCssSnippets` array in a given run.

You do not need the lazycortex-diagram engine installed for this to be useful. Any vault that already contains mermaid fences benefits from the popup plugin; the engine is the recommended producer, not a requirement.

## When you'd use this

- You want click-to-zoom on mermaid fences without configuring it yourself.
- You just enabled lazycortex-obsidian and want the full diagram experience wired up alongside Iconize.
- You updated the plugin and want to pick up revised `mermaid-popup` zoom-ratio overrides.

**Mermaid fences overflowing the column, sitting on a white box, or clipped ASCII diagrams are not this skill's job.** Those symptoms are fixed by `/lazy-obsidian.install`'s shared snippet step — run that instead.

## How it fits together

Running `/lazy-obsidian.diagram-install` takes care of click-to-zoom in a single command. It first locates your repo root via `git rev-parse --show-toplevel` and verifies that `.obsidian/` is present — if Obsidian has never been opened in this repo, it tells you to open it once first, then re-run.

With the vault confirmed, it invokes `/lazy-obsidian.update-plugin mermaid-popup`. That primitive resolves the plugin from the Obsidian community registry, fetches the latest release binaries, deep-merges the opinionated override block (10% zoom step per scroll wheel tick, calibrated for diagram fences), and registers the plugin in `community-plugins.json`. `update-plugin` is version-aware and idempotent, so this step runs unconditionally on every call — "manifest present" doesn't mean "already current". If the registry is unreachable or the plugin isn't found, the skill notes the failure and continues rather than aborting: mermaid SVG fit and theme color still work via the CSS snippets alone (once `/lazy-obsidian.install` has enabled them). You can re-run `/lazy-obsidian.update-plugin mermaid-popup` later, or install the plugin via Obsidian's Community Plugins UI.

Finally, it checks for a legacy `mermaid-no-bg.css` snippet left behind by an earlier diagram skill. The current engine ships every mermaid fence with a transparent-background theme directive, making that snippet redundant — the skill leaves it in place (it does no harm) and notes it in the run report so you can remove it manually if you want a clean snippets directory.

## Common adjustments

**Re-running after a plugin update.** `/lazy-obsidian.install` chains into this skill unconditionally. If you update lazycortex-obsidian and want to pick up revised `mermaid-popup` overrides without re-running the full install, run `/lazy-obsidian.diagram-install` directly — it is idempotent and safe to re-run at any time.

**Installing or refreshing the popup plugin independently.** Use `/lazy-obsidian.update-plugin mermaid-popup` directly. It is version-aware and no-ops when the vault already has the current release.

**Legacy `mermaid-no-bg.css`.** Vaults that previously used an earlier diagram skill may have a `mermaid-no-bg.css` snippet in `.obsidian/snippets/`. The engine's built-in transparent-background directive makes it redundant. The skill detects it, leaves it in place, and notes it in the run report so you can remove it manually if you want a clean snippets directory.

## See also

- [Obsidian vault setup](./install-and-audit.md) — the `install-and-audit` block that owns the fit-CSS snippets and chains into this skill as part of the full vault bootstrap
