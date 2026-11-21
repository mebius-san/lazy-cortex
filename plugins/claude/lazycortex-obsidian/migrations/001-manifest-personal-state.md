---
since: 7.0.0
supersedes: []
applies_when:
  - {verb: [lazycortex-obsidian, vault-manifest, strip-personal, --check]}
writes:
  - ".obsidian.manifest.json"
---
## Why

The vault manifest `.obsidian.manifest.json` no longer carries personal state of whoever uses a device: Obsidian's bookmarks (`config["bookmarks.json"]`) and Iconize's recently used icons (the `recentlyUsedIcons` key of the `obsidian-icon-folder` plugin's data). Capture stops recording both, deploy never lays them down even from a manifest that still carries them, and drift never reports them. Bookmarks become per-device state: each device keeps its own `.obsidian/bookmarks.json`, and nothing touches that file.

A manifest captured by an earlier release still holds both entries. Until they are stripped, every bookmark change on another device leaves the manifest stale, and the manifest keeps shipping one device's bookmarks to every clone that pulls it.

The `vault-manifest strip-personal` verb removes exactly those two entries from the manifest and leaves every other key, its value and its order as they are. It never reads or writes `.obsidian/`.

## Steps

`<core-cli>` is the core plugin's `bin/lazycortex-core` file; `<obsidian-cli>` is `bin/lazycortex-obsidian` under the root step 1 prints; `<repo-root>` is the root of the repository being migrated.

1. `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> plugin-root lazycortex-obsidian --cwd "<repo-root>"`
2. `"${LAZYCORTEX_PYTHON:-python3}" <obsidian-cli> vault-manifest strip-personal "<repo-root>"`

## Done when

- `"${LAZYCORTEX_PYTHON:-python3}" <obsidian-cli> vault-manifest strip-personal --check "<repo-root>"` exits 1: the manifest carries neither `config["bookmarks.json"]` nor Iconize's `recentlyUsedIcons` key.
