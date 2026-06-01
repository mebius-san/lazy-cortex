---
name: lazy-obsidian.diagram-install
description: "Scaffold the Obsidian render glue for the lazycortex-diagram engine into a vault: install the `mermaid-fit.css` and `ascii-fit.css` snippets, enable them in `appearance.json`, and install the `mermaid-popup` community plugin (click-to-zoom for mermaid fences) via `/lazy-obsidian.update-plugin`. Per-file wizard — asks before creating, shows diff on drift, never auto-overwrites local edits. Re-runnable; idempotent. Project-scope only (no global mode — Obsidian render glue is per-vault). Detects and offers to retire the legacy `mermaid-no-bg.css` snippet (made redundant by the engine's theme directive)."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(git rev-parse*), Bash(cp *), Bash(rm *), Bash(test *), Bash(date *), Bash(diff *), Bash(jq *), AskUserQuestion, TaskCreate, TaskUpdate, TaskList
argument-hint: "(no arguments — scaffolds into <repo-root>/.obsidian/)"
---
# Install diagram render glue (Obsidian)

Scaffold the Obsidian-side render glue for diagrams emitted by the lazycortex-diagram engine. Three artifacts land in the vault:

| Artifact | Target | Source |
|---|---|---|
| `mermaid-fit.css` snippet | `<vault>/.obsidian/snippets/mermaid-fit.css` | `${CLAUDE_PLUGIN_ROOT}/templates/obsidian/snippets/mermaid-fit.css` |
| `ascii-fit.css` snippet | `<vault>/.obsidian/snippets/ascii-fit.css` | `${CLAUDE_PLUGIN_ROOT}/templates/obsidian/snippets/ascii-fit.css` |
| `mermaid-popup` plugin | `<vault>/.obsidian/plugins/mermaid-popup/` | Obsidian community registry (deep-merged with overrides from `templates/obsidian/plugin-settings.json`) |

The engine ships every mermaid fence with the theme directive `%%{init: {'themeVariables':{'background':'transparent'}}}%%` so the SVG inherits the Obsidian panel background. `mermaid-fit.css` fits the SVG to container width without aspect-ratio distortion. `ascii-fit.css` shrinks ASCII-diagram code blocks (`language-text` / `language-ascii`) in Reading Mode so wide diagrams fit the editor column with horizontal scroll fallback. The `mermaid-popup` plugin adds click-to-zoom on every fence.

## Scope

Project-local only. There is no global scope — Obsidian render glue is inherently per-vault.

## Execution discipline (MANDATORY — read before any action)

This skill has 7 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Locate repo root and vault`
   - `Step 2 — Sync CSS snippets`
   - `Step 3 — Enable snippets in appearance.json`
   - `Step 4 — Install/update mermaid-popup`
   - `Step 5 — Detect legacy mermaid-no-bg.css`
   - `Step 6 — Report`
   - `Step 7 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome word (e.g. `installed`, `unchanged`, `kept-local`, `already-enabled`, `skipped-per-user-choice`, `absent`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Locate repo root and vault

- Repo root: `git rev-parse --show-toplevel` (fall back to cwd and WARN if not in a git repo).
- Vault: `<repo_root>/.obsidian`. If `.obsidian/` does not exist, abort with: "No Obsidian vault found at `<repo-root>/.obsidian/`. Initialize Obsidian first, then re-run."
- `mkdir -p <vault>/snippets` so later phases can write safely even in greenfield vaults.

Outcome: `asserted (vault=<path>)` or `[FAIL] no-vault`.

## Step 2 — Sync CSS snippets (per-file wizard)

Iterate over the shipped snippet list — order is `mermaid-fit`, `ascii-fit`. For each `<name>`:

- Source: `${CLAUDE_PLUGIN_ROOT}/templates/obsidian/snippets/<name>.css`.
- Target: `<vault>/snippets/<name>.css`.

State machine per snippet (one `AskUserQuestion` per file):

- **New** (target missing) → `AskUserQuestion` with:
  - question: ``Install the `<name>.css` snippet into this vault?``
  - description: per-snippet purpose, then ``**What this does:** Copies the shipped snippet to `<targetPath>`. Future installs will show a drift diff, not silently overwrite. Step 3 then enables it in `appearance.json`.``
    - `mermaid-fit`: `**Purpose:** Fits mermaid SVG to container width without aspect-ratio distortion.`
    - `ascii-fit`: `**Purpose:** Shrinks ASCII-diagram code blocks (\`language-text\` / \`language-ascii\`) in Reading Mode so wide diagrams fit the editor column; adds horizontal scroll fallback.`
  - options: **install** / **skip**.
- **Unchanged** (byte-identical) → no prompt. State **unchanged**.
- **Drift** (differ) → show unified diff via `Bash(diff -u <target> <source>)`. `AskUserQuestion`:
  - question: `<name>.css has drift — overwrite with shipped version?`
  - description: ``**What changed:** <one-sentence summary of the diff>\n\n**Why this matters:** You may have customized the snippet (e.g. tightened the selector, added per-theme tweaks). Overwriting discards those edits. Keep-local preserves your version but means you won't pick up upstream improvements — re-run this skill later to resolve.\n\n**Full diff:**\n```diff\n<unified diff, truncated to ~40 lines if longer>\n````
  - options: **overwrite** / **keep-local**.

Use `Read` + `Write` so diffs are visible to the wizard. Create missing parents with `Bash(mkdir -p ...)`.

Outcome: per-snippet status word from `installed` / `unchanged` / `overwritten` / `kept-local` / `skipped`. Record both for the Step 6 report.

## Step 3 — Enable snippets in appearance.json

Read `<vault>/appearance.json`. If missing or unparseable, treat its contents as `{}`.

- Ensure `enabledCssSnippets` exists as an array (create empty `[]` if absent).
- For each snippet `<name>` in `[mermaid-fit, ascii-fit]`:
  - If the array does NOT contain `"<name>"`, append it.
  - If Step 2's per-snippet outcome was **skipped** or **kept-local** AND `<vault>/snippets/<name>.css` does not exist on disk, do NOT add the entry — pointing `enabledCssSnippets` at a missing file is dead config. Record per-snippet outcome **deferred** in this case.
- Atomic write (`appearance.json.tmp` → `mv`) only when the array changed.

Per-snippet outcome:
- `enabled` — added to the array this run.
- `already-enabled` — entry was already present.
- `deferred` — Step 2 left the file absent; refused to register a stale entry.

Reload note: Obsidian does not watch `appearance.json` for changes mid-session. The Step 6 report tells the user to reload Obsidian (or click ↻ next to each snippet in Settings → Appearance → CSS snippets) when any snippet's outcome this step was **enabled**.

## Step 4 — Install/update mermaid-popup

`mermaid-popup` is the click-to-zoom community plugin (registry id: `mermaid-popup`). The plugin's data.json is configured via the `mermaid-popup` override block in `${CLAUDE_PLUGIN_ROOT}/templates/obsidian/plugin-settings.json` (`{"ZoomRatioValue": "0.1"}` — 10% zoom step per scroll wheel tick, calibrated for mermaid fences).

`update-plugin` is version-aware and idempotent — invoke it unconditionally. "Manifest present" does NOT mean "already current" — that's `update-plugin`'s job.

1. Invoke `/lazy-obsidian.update-plugin mermaid-popup`.
2. Record the state tuple (`binary=created|updated-<x>-to-<y>|unchanged overrides=applied|unchanged community=registered|already-registered`) for the Step 6 report.
3. If `update-plugin` returns **FAIL** (registry fetch failed, plugin id not in registry, etc.), surface the failure. Diagram rendering still works without `mermaid-popup` (the snippet alone covers fit + theme color), so DO NOT abort the skill — record `failed:<reason>` for the Step 6 report and continue.

Outcome: state tuple or `failed:<reason>`.

## Step 5 — Detect legacy `mermaid-no-bg.css`

Vaults that previously used the spec-system's `spec.draw-diagram` skill may carry `<vault>/snippets/mermaid-no-bg.css`. The new engine's theme directive (`background:transparent`) makes that snippet redundant — keeping it does no harm but it's dead config.

1. `test -f <vault>/snippets/mermaid-no-bg.css`. If absent → state **absent**, no prompt.
2. If present, `AskUserQuestion`:
   - question: ``Retire legacy `mermaid-no-bg.css`? It is no longer needed — the diagram engine now emits a transparent-background theme directive on every mermaid fence.``
   - description: ``**What this does:** Deletes `<vault>/snippets/mermaid-no-bg.css` and removes `"mermaid-no-bg"` from `appearance.json`'s `enabledCssSnippets`. Reversible — re-add the snippet manually if needed.\n\n**Why retire it:** The engine's per-fence theme directive sets `themeVariables.background` to transparent natively, which renders the CSS rule a no-op. Keeping the snippet is harmless but it's stale config.``
   - options: **retire** / **keep**.
3. **retire** → `rm <target>` AND remove `"mermaid-no-bg"` from `enabledCssSnippets` (preserve other entries; rewrite `appearance.json` only when the array changed). State **retired**.
4. **keep** → state **kept**.

Never auto-delete — wizard discipline.

## Step 6 — Report

One bullet per step, in order — missing bullet = skipped step, back up and run it.

- **Step 1** — repo-root + vault paths (or abort reason).
- **Step 2** snippets — one bullet per snippet (`mermaid-fit.css`, `ascii-fit.css`): **installed** / **unchanged** / **overwritten** / **kept-local** / **skipped**, with target path.
- **Step 3** appearance.json — one bullet per snippet: **enabled** / **already-enabled** / **deferred**.
- **Step 4** mermaid-popup: state tuple (`binary=... overrides=... community=...`) or **failed:`<reason>`**.
- **Step 5** legacy mermaid-no-bg.css: **retired** / **kept** / **absent**.

Next steps shown to user:
- If any Step 3 outcome was **enabled**, remind: "Reload Obsidian (or click ↻ next to the snippet in Settings → Appearance → CSS snippets) — snippets won't apply mid-session."
- If any Step 2 outcome was **skipped** or **kept-local**, remind: "`mermaid-fit` left absent → mermaid SVGs may render with default sizing; `ascii-fit` left absent → wide ASCII diagrams will overflow the editor column."
- If Step 4 outcome was **failed:**, remind: "click-to-zoom is unavailable until `mermaid-popup` is installed; re-run `/lazy-obsidian.update-plugin mermaid-popup` later or install via Obsidian's Community Plugins UI."

## Step 7 — Log the run

Per `./.claude/rules/lazy-log.logging.md`:

1. `Bash(mkdir -p ./.logs/claude/lazy-obsidian.diagram-install)`
2. `Write` to `./.logs/claude/lazy-obsidian.diagram-install/<UTC-timestamp>.md` with frontmatter (`git_sha`, `git_branch`, `date`, `input`) and the Step 6 report body.

Two-step write: never chain with `&&`.

## Failure modes

- **`/lazy-obsidian.diagram-install` aborts: "No Obsidian vault found at `<repo-root>/.obsidian/`"** — `.obsidian/` is absent from the repo root → initialize Obsidian in this repo first, then re-run.
- **Step 4 reports `failed:<reason>` for mermaid-popup** — the Obsidian community registry was unreachable or `mermaid-popup` was not found in it → mermaid SVG fit and theme color still work via the CSS snippets alone; re-run `/lazy-obsidian.update-plugin mermaid-popup` later when the network is available, or install the plugin via Obsidian's Community Plugins UI.

## Idempotency

Safe to re-run. Drift prompts only fire when content actually differs. Step 3 no-ops when the array entry is already present. Step 4 delegates to `/lazy-obsidian.update-plugin`, which is itself idempotent. Step 5's prompt fires only while the legacy snippet is still on disk — once retired, re-runs report **absent**.

## Notes

- **No diagram authoring in this skill.** This skill only sets up render glue. Authoring + emitting fences belongs to `/lazy-diagram.draw` (engine entry point).
- **No engine-side dependency.** This skill works whether or not `lazycortex-diagram` is enabled — the CSS + plugin are useful for any vault that contains mermaid fences. The engine is the recommended *producer*; nothing here requires it.
- **Chained from `/lazy-obsidian.install`.** That skill offers to chain into this one as part of the standard vault setup. Re-running this skill directly (after install) is the way to pick up template changes after a `/plugin update`.
