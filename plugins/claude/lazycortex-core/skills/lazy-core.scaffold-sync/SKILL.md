---
name: lazy-core.scaffold-sync
description: "Dispatched by a plugin's install skill (`lazy-core.install` Step 4, `lazy-python.install` Step 6) to copy that plugin's authoring templates into the consumer and upsert its scaffold-registry entries; not for direct use. Repo-specific `_local` entries are `/lazy-core.scaffold-local`'s business, not this skill's."
allowed-tools: Read, Write, Glob, Bash(ls *), Bash(diff *), Bash(cp *), Bash(mkdir -p *), Bash(date *), Bash(git rev-parse*), Bash(python3 *), Bash("${LAZYCORTEX_PYTHON:-python3}" *), Agent
---
# Sync Scaffold Templates and Registry

Copies every authoring template shipped by a plugin into the consumer's `.claude/templates/<group>/` directories, then upserts the corresponding entries into the scaffold registry. Invoked from a plugin's own install skill via `Skill(skill: "lazycortex-core:lazy-core.scaffold-sync", args: "plugin=<name> installPath=<path> scope=<project|user>")`. Safe to re-invoke; all file operations are idempotent.

Note: `lazy-core.install` Step 4 becomes an invocation of this skill for `lazycortex-core` itself — this skill is its own registry sync path (dogfood).

## Execution discipline (MANDATORY — read before any action)

This skill has 7 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Resolve inputs and registry path`
   - `Step 2 — Discover manifests`
   - `Step 3 — Copy templates per group`
   - `Step 4 — Merge entries`
   - `Step 5 — Resolve core CLI`
   - `Step 6 — Upsert registry`
   - `Step 7 — Report`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`none`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Resolve inputs and registry path

Parse the three inputs from the `args` string (or from the invoking skill's context):

- `plugin` — the plugin's installed name (e.g. `lazycortex-core`).
- `installPath` — absolute path to the plugin's install root (from `installed_plugins.json`).
- `scope` — `project` or `user`.

Resolve the scaffold registry path:

| Scope | Registry path |
|---|---|
| `project` | `<repo-root>/.claude/rules/lazy-core.scaffold.md` |
| `user` | `~/.claude/rules/lazy-core.scaffold.md` |

Where `<repo-root>` is `git rev-parse --show-toplevel` in the current working directory.

State outcome `resolved`.

## Step 2 — Discover manifests

Run:

```
Bash(ls "<installPath>"/templates/*/scaffold.entries.json)
```

A single-pattern `ls` is the one listing every executor may issue, the headless autosetup agent included; `find`, `Path.glob()` and `Path.rglob()` are not used here — the tech-stack contract bans the last two, and the autosetup discipline refuses the first.

Each result path has the form `<installPath>/templates/<group>/scaffold.entries.json`. The parent directory name is the `<group>`. A manifest always sits exactly one directory below `templates/`, so the pattern misses nothing.

If no manifest files are found → state outcome `none` (no-op), emit a brief message ("no scaffold.entries.json manifests found under `<installPath>/templates/`"), and stop. The remaining steps are skipped with outcome `skipped-no-manifests`.

Otherwise state outcome `discovered-N` where N is the number of manifests found.

## Step 3 — Copy templates per group

**3a. Collect the operator's own template paths.**

Read the registry's `_local` key before anything is written — its entries are templates the operator authored, and this plugin owns none of them however its own shipped files happen to be named:

```bash
"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/lazycortex-core" scaffold list --registry <regPath>
```

Parse the JSON output and take `registry._local`; an absent key means an empty map. Resolve every entry key to an absolute path — a key starting with `~/` expands against `$HOME`, any other key is relative to `<repo-root>` for `project` scope and to `$HOME` for `user` scope. `<protectArgs>` is one `--protect <absolute path>` per resolved key; with no `_local` entries it is the empty string.

State outcome `protecting-N` where N is the number of resolved paths.

**3b. Sync the shipped templates.**

For each `<group>` discovered in Step 2, sync the template files from `<installPath>/templates/<group>/` into the consumer's `.claude/templates/<group>/` directory (where "consumer" scope = `~/.claude/` for `user`, `<repo-root>/.claude/` for `project`) with the deterministic sync script — the current/not-current verdict comes from the receipt, never from impression:

```bash
"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/file_sync.py" --src <installPath>/templates/<group> --dst <consumerScope>/.claude/templates/<group> --copy-diverged --exclude scaffold.entries.json <protectArgs>
```

`scaffold.entries.json` is plugin-internal and must not land in the consumer tree. The script creates the target directory, copies absent targets (state **installed**), byte-compares the rest (**unchanged**), overwrites every stale target from the shipped source (**refreshed**), and re-compares each write before reporting it. Subdirectories are ignored — template groups are flat.

**The script is the whole step — there is nothing here to judge.** An authoring template is plugin-owned: a consumer who wants a different template authors their own file and registers it under the registry's `_local` key, where it wins over the plugin entry at equal glob specificity. So a target that differs from the shipped source is a stale copy, not a customisation, and it is overwritten without a diff preview, a merge, or a question.

**A path the registry lists under `_local` is the one exception, and the script enforces it.** Such a path is the operator's own file: `--protect` makes the script leave it byte-for-byte as it is on disk — never compared, never overwritten — and report it as **protected**. A shipped template that carries the same filename confers no claim on it. What this catches is a `_local` template sitting in a group a plugin supplies — `/lazy-core.scaffold-local` Step 3a refuses to create one, but a hand-edited registry bypasses that refusal. Protection is a safety net, not the fix: surface every skip and name the `_local` entry behind it.

Exit code 3 with a non-empty `failed` array means a write did not verify — report it as **failed** and never restate it as applied.

State for the group as a whole: one line per file as `<group>/<filename>: <state>`, plus the receipt's `counts` line verbatim.

## Step 4 — Merge entries

Read each group's `scaffold.entries.json`. Each manifest contains a `templates` map whose **keys are consumer-scope template paths verbatim** (e.g. `.claude/templates/<group>/<filename>`) and whose values are glob lists: `{ ".claude/templates/<group>/<filename>": ["<glob1>", "<glob2>", ...], ... }`. These keys are used **as-is** — they become `data[<plugin>]` verbatim, with no rewriting.

Union the `templates` maps from every group into a single merged map.

Collision rule: if two groups contribute the same template path key with **different** glob arrays, FAIL with the message:

> `scaffold-sync: collision — template path "<key>" declared by both group "<groupA>" and group "<groupB>" with conflicting globs; resolve before continuing`

State outcome `merged-N` where N is the total number of entries across all groups; `collision-FAIL` on error.

## Step 5 — Resolve core CLI

When this repo authors the plugin itself (`<repo-root>/plugins/claude/lazycortex-core/.claude-plugin/plugin.json` exists), `<core-cli>` is `<repo-root>/plugins/claude/lazycortex-core/bin/lazycortex-core` — the sources in the tree, never the cached copy, which lags them until the next publish. Otherwise read `~/.claude/plugins/installed_plugins.json`. Find the `lazycortex-core@lazycortex` key. If absent or its array is empty → FAIL with:

> `scaffold-sync: cannot resolve core CLI — lazycortex-core not installed; run /lazy-core.install first`

Take the `installPath` of the entry with the highest `version` — the registry keeps one record per project that ever installed the plugin, so the first or last entry may name an older cache dir. `<core-cli>` is `<installPath>/bin/lazycortex-core`; every verb below runs it through the interpreter, `"${LAZYCORTEX_PYTHON:-python3}" <core-cli> <verb>`, because the file carries no exec bit.

Verify the file exists with `Bash(test -f <core-cli>)`. If not → FAIL with:

> `scaffold-sync: core CLI not found at <core-cli>; run /plugin update lazycortex-core@lazycortex to restore`

State outcome `resolved`.

Note: `$LAZYCORTEX_PLUGIN_DIRS` may be unset at install time — outside an authoring repo, always resolve via `installed_plugins.json`.

## Step 6 — Upsert registry

Write the merged entries map to a temp file at `~/tmp/scaffold-sync-entries-<timestamp>.json`:

```bash
mkdir -p ~/tmp
```

Then `Write` the JSON to `~/tmp/scaffold-sync-entries-<timestamp>.json`.

Run:

```bash
"${LAZYCORTEX_PYTHON:-python3}" <core-cli> scaffold upsert --plugin <plugin> --entries @~/tmp/scaffold-sync-entries-<timestamp>.json --registry <regPath>
```

Capture the JSON output on stdout. The primitive returns a top-level `status` field with one of: `registered`, `unchanged`, `created-and-registered`, `removed`, `absent`, `error`.

On `error` → FAIL, surfacing the full output as the error message.

State outcome: the value of `status` from the returned JSON.

## Step 7 — Report

Emit a table of per-template copy states (Step 3) plus the registry upsert outcome (Step 6):

```
Templates synced:
  <group>/<filename>: <state>
  ...

Registry upsert: <status>
```

One line per template file. State one of: `installed`, `unchanged`, `refreshed`, `protected`, `failed`. A `protected` line carries the reason and the entry behind it — `<group>/<filename>: protected — registered under `_local`, left as authored`. Then the upsert status line.

## Failure modes

- **`scaffold-sync: no scaffold.entries.json manifests found`** — the plugin ships no `templates/*/scaffold.entries.json` files → no templates were registered; the plugin may not use the scaffold system. State `none` and stop normally.
- **`scaffold-sync: collision — template path "<key>" declared by …`** — two groups declare the same template path with different globs → resolve by editing the plugin's `scaffold.entries.json` manifests so there is no overlap, then re-run.
- **`scaffold-sync: cannot resolve core CLI — lazycortex-core not installed`** — `installed_plugins.json` has no `lazycortex-core@lazycortex` entry → install the plugin first (`/lazy-core.install`), then re-run.
- **`scaffold-sync: core CLI not found at <path>`** — the `installPath` in `installed_plugins.json` points to a path that no longer exists → run `/plugin update lazycortex-core@lazycortex` to refresh the cache, then re-run.
- **`scaffold upsert` returns `error`** — the core CLI rejected the entries (malformed JSON, schema mismatch, or registry write failure) → inspect the full error output, fix the manifest, then re-run.
- **A template reports `protected`** — the consumer path is registered under `_local`, so the operator's own file was kept and the shipped template did not land → not an error; the `_local` entry sits in a group this plugin supplies, which `/lazy-core.scaffold-local` refuses to create. Re-file that entry under a group of its own with `/lazy-core.scaffold-local mode=remove` followed by `mode=add`, then re-run this skill.
