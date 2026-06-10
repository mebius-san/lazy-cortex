---
chapter_type: block
summary: Wire the lazycortex-diagram engine's CSS snippets and click-to-zoom plugin into your Obsidian vault so mermaid and ASCII diagrams render correctly in Reading Mode.
last_regen: 2026-06-10
no_diagram: true
source_skills:
  - lazy-obsidian.diagram-install
---
# Diagram rendering

When the lazycortex-diagram engine writes a mermaid or ASCII fence into a note, Obsidian needs a small set of render-glue artifacts to display it well: a CSS snippet that fits the SVG to column width without distorting its aspect ratio, a second snippet that gives wide ASCII code blocks horizontal scroll fallback, and an optional community plugin that lets you click any mermaid fence to zoom it. `/lazy-obsidian.diagram-install` places all three into your vault in one pass — silently if nothing conflicts, with a targeted prompt only if a snippet you've customized has changed in the same region upstream.

You do not need the lazycortex-diagram engine installed for this to be useful. Any vault that already contains mermaid fences benefits from the fit CSS and the popup plugin; the engine is the recommended producer, not a requirement.

## When you'd use this

- Your vault contains mermaid diagrams and they overflow their column width in Reading Mode.
- You want click-to-zoom on mermaid fences without configuring it yourself.
- You just enabled lazycortex-obsidian and want the full diagram experience wired up alongside Iconize.
- You updated the plugin and want to pick up revised snippet templates.

## How it fits together

Running `/lazy-obsidian.diagram-install` takes care of everything in a single command. It first locates your repo root via `git rev-parse --show-toplevel` and verifies that `.obsidian/` is present — if Obsidian has never been opened in this repo, it tells you to open it once first, then re-run.

With the vault confirmed, it syncs two CSS snippets into `.obsidian/snippets/`. `mermaid-fit.css` sizes the rendered SVG to container width so wide diagrams don't overflow the reading pane; the engine emits every mermaid fence with a transparent-background theme directive, and this snippet completes the fit without clipping. `ascii-fit.css` targets `language-text` and `language-ascii` code blocks in Reading Mode, applying a smaller font and horizontal scroll so wide ASCII diagrams stay legible in a normal editor column. Both files follow a quiet-sync policy: they install silently when absent, no-op when byte-identical to the shipped version, and apply upstream changes on top of your local edits when the edits don't overlap. You only see a prompt when you and the upstream template edited the exact same region — in that case, you pick which version wins for that conflict region.

After syncing the files, the skill registers both snippets in `.obsidian/appearance.json` under `enabledCssSnippets`. If a snippet file was somehow not written (rare: only if you chose "keep-local" in a conflict that removed all content), the registration for that snippet is deferred rather than pointing `appearance.json` at a missing file. When snippets are newly enabled you'll need to reload Obsidian — or click the refresh icon next to each snippet in Settings → Appearance → CSS snippets — for them to take effect mid-session.

Finally, it invokes `/lazy-obsidian.update-plugin mermaid-popup` to install the click-to-zoom community plugin. That primitive resolves the plugin from the Obsidian community registry, fetches the latest release binaries, deep-merges the opinionated override block (10% zoom step per scroll wheel tick, calibrated for diagram fences), and registers the plugin in `community-plugins.json`. If the registry is unreachable or the plugin isn't found, the skill notes the failure and continues — mermaid SVG fit and theme color still work via the CSS snippets alone. You can re-run `/lazy-obsidian.update-plugin mermaid-popup` later, or install the plugin via Obsidian's Community Plugins UI.

## Common adjustments

**Re-running after a plugin update.** `/lazy-obsidian.install` chains into this skill unconditionally. If you update lazycortex-obsidian and want to pick up revised snippet templates without re-running the full install, run `/lazy-obsidian.diagram-install` directly — it is idempotent and safe to re-run at any time.

**Installing or refreshing the popup plugin independently.** Use `/lazy-obsidian.update-plugin mermaid-popup` directly. It is version-aware and no-ops when the vault already has the current release.

**Legacy `mermaid-no-bg.css`.** Vaults that previously used an earlier diagram skill may have a `mermaid-no-bg.css` snippet in `.obsidian/snippets/`. The engine's built-in transparent-background directive makes it redundant. The skill detects it, leaves it in place (it does no harm), and notes it in the run report so you can remove it manually if you want a clean snippets directory.

## See also

- [Obsidian vault setup](./install-and-audit.md) — the `install-and-audit` block that chains into this one as part of the full vault bootstrap
