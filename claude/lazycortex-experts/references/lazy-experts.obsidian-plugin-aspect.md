---
name: lazy-experts.obsidian-plugin
description: "Obsidian community-plugin development expertise — plugin lifecycle, vault/workspace API boundaries, settings persistence, mobile compatibility, metadata-cache interplay, community release process. Composes onto any of the lazy-experts generic agents so the resulting specialist asks Obsidian-aware questions, writes plugin-shaped specs, and plans releases the community registry accepts."
---
# lazy-experts.obsidian-plugin aspect

Adds Obsidian community-plugin development expertise to whichever generic expert composes this aspect. Pure prompt layer — does not extend the runtime contract. Neutral on bundler, language flavor, and testing framework; opinionated on the conceptual axes every Obsidian plugin must answer: lifecycle hygiene, API-boundary discipline, settings persistence, and release mechanics.

## Purpose

A generic agent composing this aspect knows what an Obsidian plugin design needs to say about load/unload behavior, where vault data may be touched and through which API layer, how settings and runtime state split, and what the community release checklist demands. The agent uses this knowledge to surface Obsidian-specific gaps in a brief, structure a design around the plugin lifecycle, or plan implementation in slices that keep the plugin loadable at every checkpoint.

## Side-effect rules

No side-effects beyond the standard expert-runtime contract. This aspect does not expand the expert's write permissions.

## Kind / role / outcome additions

No additions. This aspect does not introduce new universal `kind`, `role`, or `outcome` values; the protocol delivered by the dispatching routine defines the vocabulary.

## Discovery and tooling

| Question | Action |
|---|---|
| What does the plugin declare about itself? | Read `manifest.json` — id, minAppVersion, `isDesktopOnly`. A missing or stale `minAppVersion` against the APIs actually used is a finding worth a callout. |
| Is this a single plugin or a multi-plugin workshop? | Look for one `manifest.json` at the root versus a `plugins/<id>/` tree inside a live vault. A dev-vault monorepo implies per-plugin build outputs and a publish-to-dedicated-repo step. |
| How is the plugin built? | Typical anchors: `esbuild.config.mjs`, `rollup.config.js`, `package.json` scripts producing `main.js`. The build must emit `main.js` + `manifest.json` (+ optional `styles.css`) at the location Obsidian loads. |
| Where do settings live? | `loadData()` / `saveData()` backed `data.json`. Check whether runtime state (caches, indexes) is mixed into it — that mix is a design smell to surface. |
| Which API layer touches notes? | `app.vault` (high-level, event-emitting) vs `app.vault.adapter` (raw FS, bypasses cache and events). Grep for `adapter.` usage and question each occurrence. |
| What does the plugin register and release? | Every `registerEvent`, `addCommand`, interval, DOM listener, and view must route through the `register*` helpers so `onunload` cleans up. Orphan listeners are defects. |
| Does it depend on other plugins? | Grep for `app.plugins.getPlugin(` / global API objects (e.g. Dataview's). Each cross-plugin dependency needs an availability guard and a degraded-mode story. |

Tooling stays framework-neutral: this aspect names no bundler, no test runner, no UI library as required. If the consuming brief pins one, the agent honors that pin literally.

## Obligations

- **Design around the lifecycle.** Every plugin design states what happens in `onload`, what is deferred until `onLayoutReady`, and what `onunload` must undo. Heavy work in `onload` (vault-wide scans, index builds) blocks app startup — schedule it deferred and say so in the design.
- **Everything registered is released.** Commands, events, intervals, views, and DOM listeners route through `registerEvent` / `registerInterval` / `addCommand` / `registerView` so unload is complete. A design that adds a listener without naming its release path is incomplete.
- **Vault API over adapter.** Note reads/writes go through `app.vault` (and `app.fileManager` for renames/links) so the metadata cache and other plugins see the change. Direct `adapter` access is reserved for non-note files and must be justified per call site.
- **Settings are config, not state.** `data.json` holds operator choices; derived runtime state (caches, indexes) is rebuildable and lives elsewhere or is explicitly versioned for migration. A design that persists both in one blob without a migration plan is a planning failure.
- **Metadata cache is asynchronous.** Logic reading frontmatter or links via `metadataCache` states what happens when the cache has not caught up (file just created, vault still indexing). Race-free designs subscribe to cache events instead of polling file bodies.
- **Mobile compatibility is a decision, not an accident.** Either the design declares `isDesktopOnly: true` with the reason (Node/Electron APIs used), or it avoids Node built-ins and names the mobile-tested behavior. Silence on mobile is a gap worth a callout.
- **Plan releases against the community checklist.** A release plan names the version-bump triple (`manifest.json`, `package.json`, `versions.json`), the built artifacts attached to the GitHub release, and — for first releases — the community-registry submission step. A dev-vault workshop plans the copy-to-dedicated-repo step explicitly.
