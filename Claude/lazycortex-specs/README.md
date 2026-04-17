# lazycortex-specs

Specification and design skills for Claude Code

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
