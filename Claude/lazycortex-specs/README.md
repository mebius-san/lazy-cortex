---
iconize_icon: LiInfo
iconize_color: "#93c5fd"
---
# lazycortex-specs

Specification and design skills for Claude Code

> **Versioning** — On upgrade from a previous public release: a **patch bump** is safe to drop in. A **minor bump** means re-run the plugin's install command to pick up new rules, settings, or templates. A **major bump** means user-data migration is required — see the release notes in [`CHANGELOG.public.md`](../../CHANGELOG.public.md).

## Why this plugin

`lazycortex-specs` is a placeholder for spec-authoring and design-review tooling
that will live alongside `lazycortex-core`. It ships no skills yet; it exists so
downstream plugins and the marketplace can start depending on the namespace
before the first real skill lands.

## Who it's for

- **Teams that write specs and design docs** alongside code in the same repo,
  and want Claude Code skills that understand spec conventions.
- **Plugin authors** who want to reserve a `lazy-specs.*` namespace in the
  LazyCortex ecosystem before the first public release.

## Scenarios

This plugin has no user-facing scenarios yet. Run `/lazy-specs.help` for the
current status. Future releases will surface spec-drafting, design-review, and
plan-execution skills here.

## Commands

| Command | Description |
|---|---|
| `lazy-specs.help` | Show lazycortex-specs purpose and a one-line summary of each skill it ships |

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
    "lazycortex-specs@lazycortex": true
  }
}
```

Restart Claude Code. Skills appear as `lazycortex-specs:<skill.name>`.
