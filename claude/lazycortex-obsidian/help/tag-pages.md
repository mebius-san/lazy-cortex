---
chapter_type: block
summary: Keep a Tags/ folder in sync with every tag used across your vault — pages created, updated, and pruned automatically.
last_regen: 2026-06-10
no_diagram: true
source_skills:
  - lazy-obsidian.gen-tag-pages
---
# Tag page generation

When a vault accumulates tags across dozens or hundreds of notes, navigating by tag becomes friction: you can search, but you can't browse a tag the way you browse a note. Tag pages solve that — one page per tag, auto-populated by a Dataview query, sitting in a `Tags/` folder whose hierarchy mirrors the tag hierarchy. The `lazy-obsidian.gen-tag-pages` agent builds and maintains that folder for you: it scans every `.md` file's frontmatter, derives the full set of tags (including implicit parent segments for nested tags like `rpg/effects/layers`), and creates, keeps, or removes pages to match reality.

The template each page is rendered from lives in your repo at `.claude/templates/obsidian.tag-page-template.md`. It ships with a DataviewJS `Index` block that lists every note carrying the tag. You can edit the template freely — the agent reads it fresh each run and never overwrites pages it has already created, so your customised summaries survive regeneration.

## When you'd use this

- You added a batch of notes with new tags and want the `Tags/` folder to catch up.
- You renamed or removed a tag from several notes and want the stale tag page cleaned up.
- You've just bootstrapped the vault and want to generate the full tag hierarchy from scratch.
- You want a browsable index of every tag in the vault without building it by hand.

## How it fits together

Run `/lazy-obsidian.gen-tag-pages` and the agent handles everything in one pass. It opens with a scan — all `.md` files outside system directories (`.claude/`, `Ω System/`, `Tags/` itself) are grepped for `tags:` frontmatter. Template/placeholder tags (anything containing `<` and `>`) are silently ignored.

Once the tag set is collected, the agent expands it: `rpg/effects/layers/aura` implicitly requires pages for `rpg`, `rpg/effects`, and `rpg/effects/layers` as well, so those parent entries are added automatically. It then inventories what already exists under `Tags/`, computes the three-way diff (create / keep / delete), and acts on it.

Pages in the "keep" set are left untouched — their summaries survive across runs. Pages in the "delete" set are removed and any directories they leave empty are pruned. Pages in the "create" set are written from your local template: the agent infers a concise 1–2 sentence summary for each tag (drawing on the tag name, the notes that carry it, and its position in the hierarchy) before substituting `{{TAG_PATH}}` and `{{SUMMARY}}` into the template.

The Dataview `Index` block inside the template is identical for every page and is never modified during a run — all live queries resolve at Obsidian render time.

Before the agent can run, the template must exist. If it's missing, the agent stops and tells you to run `/lazy-obsidian.install`, which scaffolds the default template in one step.

## Common adjustments

**Changing how pages look.** Edit `.claude/templates/obsidian.tag-page-template.md` directly — the DataviewJS block, any frontmatter you want each page to carry, extra headings. The agent reads the template fresh on every run.

**Resetting a page's summary.** Delete the page under `Tags/` (or the whole `Tags/` folder). The next run treats those tags as new and regenerates the pages with freshly inferred summaries.

**Bootstrapping the template.** If the template is absent or you want to reset it to the plugin default, run `/lazy-obsidian.install`. It scaffolds the template via quiet file-sync — no-ops when the file already exists and is unchanged, asks only on a genuine conflict.

## See also

- [install-and-audit](install-and-audit.md) — installs the plugin and scaffolds the tag-page template as part of the full vault bootstrap
