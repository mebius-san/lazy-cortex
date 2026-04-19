---
name: lazy-obsidian.iconize-file
description: "Add, update, clear, read, and bulk-reconcile folder/file icons managed by the Obsidian Iconize plugin (`obsidian-icon-folder`). Works directly on `.obsidian/plugins/obsidian-icon-folder/data.json` — no Obsidian runtime needed. Safe for concurrent writes (mtime guard + retry). Preserves `settings`, `rules`, and `recentlyUsedIcons`. Callable standalone or as a primitive from other skills. Does NOT manage rules-array auto-assignment, icon-pack installation, or UI toggles."
allowed-tools: Read, Bash(python3 *), Bash(mkdir -p *), Bash(date *), Bash(git rev-parse*), Write
argument-hint: "<subcommand> [args] | e.g. set <path> <iconName> [--color #hex] | set --file policy.json | set-folder <dir> <iconName> [--color] [--also-folder-note[=filename]] | clear <path> | get <path> | list [--prefix PATH] | reconcile --declared policy.json [--prefix PATH]"
---

# Iconize File (Obsidian)

Manipulates the Obsidian Iconize plugin's `data.json` via a Python helper (`iconize.py`, co-located with this file). Every mutation is concurrent-safe: the helper reads, computes the new object, checks the file hasn't changed, then writes. On conflict it retries.

**Vault-agnostic.** The helper auto-detects the vault by walking up from the current working directory looking for `.obsidian/`, or accepts an explicit `--vault <root>`.

**Mechanics only.** This skill does not care what the icons mean, which files they belong to, or which conventions drive the choice. Callers provide path + iconName (+ optional color); the skill writes the entry.

## Operations

All subcommands accept `--vault <root>`, `--dry-run`, and `--strict-paths` as global flags (pass BEFORE the subcommand).

### set — single path

```
python3 iconize.py set <path> <iconName> [--color #hex]
```

- `<path>` is vault-relative, forward slashes, no leading `/`, no trailing `/` on folders.
- `<iconName>` is typically `Li<PascalName>` (Lucide is bundled). Emoji characters work too.
- `--color` accepts `#rgb` or `#rrggbb`. Omit for monochrome.

### set — bulk from policy file

```
python3 iconize.py set --file <policy.json>
```

Policy format:
```json
[
  { "path": "Some/Folder",                    "iconName": "LiHammer",    "iconColor": "#fed7aa" },
  { "path": "Some/Folder/design.md",          "iconName": "LiDraftingCompass" },
  { "path": "Some/Folder/plan.md",            "iconName": "LiListTodo" }
]
```

### set-folder — folder plus optional folder-note

```
python3 iconize.py set-folder <folder-path> <iconName> [--color #hex] [--also-folder-note[=FILENAME]]
```

- Writes `<folder-path>` (paints the folder in the file tree).
- If `--also-folder-note` is passed, also writes `<folder-path>/<FILENAME>` with the same icon/color.
  - `FILENAME` defaults to `_folder.md` (the user's existing folder-notes convention).

Use this when the caller wants a colored folder + matching folder-note icon in one shot.

### clear — remove an icon entry

```
python3 iconize.py clear <path>
```

No error if the entry didn't exist. Reserved top-level keys (`settings`, `rules`, `recentlyUsedIcons`) cannot be cleared — the helper refuses.

### get — read the icon entry for a path

```
python3 iconize.py get <path>
```

Prints a JSON object like `{"iconName": "LiBook", "iconColor": "#bfdbfe"}` (always long form, even if stored as short form). Empty stdout with exit 0 means "no entry".

### list — enumerate entries

```
python3 iconize.py list [--prefix <path>]
```

Prints a JSON object mapping path → entry. With `--prefix`, filters to the subtree rooted at that path (inclusive of the prefix itself).

### reconcile — declarative convergence

```
python3 iconize.py reconcile --declared <policy.json> [--prefix <path>]
```

Within the `--prefix` subtree (or whole vault if omitted):

- **Add or update** every entry declared in the policy file.
- **Drop** every existing entry that is NOT declared.
- Non-`--prefix` subtrees are untouched.

Use for subtree-wide refreshes where the caller owns the complete list of icons for that subtree.

## Global flags

| Flag | Effect |
|---|---|
| `--vault <root>` | Explicit vault root. Default: walk up from cwd. |
| `--dry-run` | Print the planned change (JSON) and exit without writing. |
| `--strict-paths` | Exit 4 if any target path doesn't exist on disk (default: WARN on stderr and write anyway). |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success (including `get` with no entry). |
| 1 | Validation error (bad args, bad color, bad iconName, malformed policy). |
| 2 | `data.json` not found / vault not detected. |
| 3 | Concurrent-write conflict unresolved after retries. |
| 4 | Target path missing (only with `--strict-paths`). |

## Behavior notes (surfaced by the helper)

- **Frontmatter conflict warning**: for `.md` targets when `settings.iconInFrontmatterEnabled == true` and the file has `icon:` in its frontmatter, the helper prints a WARN on stderr (the plugin will overwrite the `data.json` entry on next sweep — prefer writing frontmatter). The write still happens.
- **Missing-target warning**: if the target path doesn't exist on disk, the helper prints a WARN on stderr. Unless `--strict-paths` is set, the write still happens, but the plugin's background reconciliation sweep may prune the entry.
- **Short-form tolerated, long-form emitted**: reads handle `"path": "iconName"`; writes always use `{"iconName": "...", "iconColor": "..."}` for round-trip safety.
- **Reserved keys preserved**: `settings`, `rules`, `recentlyUsedIcons` are never read or written by path operations.
- **File formatting**: writes use 2-space indent, UTF-8 (no ASCII escapes), trailing newline. Matches the plugin's own output.

## Path conventions (Iconize-specific)

- Vault-relative, forward slashes, no leading `/`.
- Folders: no trailing slash (`Some/Folder`, not `Some/Folder/`).
- Files: include extension (`Some/Folder/design.md`).
- Case-sensitive — must match on-disk exactly.
- To paint a folder AND its folder-note consistently, register both keys: `Some/Folder` and `Some/Folder/_folder.md` (use `set-folder --also-folder-note`).

## How callers should use this skill

1. **One-off fix** ("set `LiBook` on `Docs/Reading/`"): invoke with `set`.
2. **Primitive for another skill** (e.g. a status-file skill painting many files): build a policy JSON in-memory, write to a temp file, call `set --file <temp>` or `reconcile --declared <temp> --prefix <subtree>`.
3. **Script the whole subtree**: use `reconcile` — callers don't need to track deltas; declare the desired state and the helper diff-applies.

## Logging

Log every invocation to `./.logs/claude/lazy-obsidian.iconize-file/YYYY-MM-DD_HH-MM-SS.md` per the logging rule. Frontmatter: `git_sha`, `git_branch`, `date`, `input` (the subcommand + args). Actions: what the helper reported. Result: success/failure + any warnings.

Use two separate steps: `Bash(mkdir -p ...)` then `Write` tool. Never chain with `&&`.

## Non-goals

- Managing the `rules` array (pattern-based auto-icon) — out of scope for v1.
- Installing / removing icon packs.
- Editing frontmatter on markdown files — callers that want the frontmatter path should write frontmatter themselves; this skill only touches `data.json`.
- UI-layer behavior (tabs, title bar, inline notes rendering). Those are plain settings keys.
