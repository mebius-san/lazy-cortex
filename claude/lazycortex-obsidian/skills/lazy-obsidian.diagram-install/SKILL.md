---
name: lazy-obsidian.diagram-install
description: "Scaffold the Obsidian render glue for the lazycortex-diagram engine into a vault: install the `mermaid-fit.css` and `ascii-fit.css` snippets, enable them in `appearance.json`, and install the `mermaid-popup` community plugin (click-to-zoom for mermaid fences) via `/lazy-obsidian.update-plugin`. Quiet file-sync — writes silently when absent or unchanged, merges silently when the shipped delta doesn't contradict local edits, and asks only on a genuine conflict. Re-runnable; idempotent. Project-scope only (no global mode — Obsidian render glue is per-vault). Detects and silently keeps the legacy `mermaid-no-bg.css` snippet (made redundant by the engine's theme directive)."
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
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome word (e.g. `installed`, `unchanged`, `merged`, `already-enabled`, `kept-orphan`, `absent`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Locate repo root and vault

- Repo root: `git rev-parse --show-toplevel` (fall back to cwd and WARN if not in a git repo).
- Vault: `<repo_root>/.obsidian`. If `.obsidian/` does not exist, abort with: "No Obsidian vault found at `<repo-root>/.obsidian/`. Initialize Obsidian first, then re-run."
- `mkdir -p <vault>/snippets` so later phases can write safely even in greenfield vaults.

Outcome: `asserted (vault=<path>)` or `[FAIL] no-vault`.

## Step 2 — Sync CSS snippets (file-sync policy)

Iterate over the shipped snippet list — order is `mermaid-fit`, `ascii-fit`. For each `<name>`:

- Source: `${CLAUDE_PLUGIN_ROOT}/templates/obsidian/snippets/<name>.css`.
- Target: `<vault>/snippets/<name>.css`.

These are quiet-sync artifacts — no per-file install prompt, no drift overwrite/keep prompt. The three cases:

- **Absent or byte-identical** (target missing, or present and equal to source) → `cp <source> <target>` silently (`mkdir -p` parents first). State **installed** (missing) or **unchanged** (identical). No prompt.
- **Locally changed, shipped delta applies cleanly** — the local file differs from source but the difference is confined to regions the shipped version did not change (the local edits and the shipped edits touch disjoint regions). Apply the shipped delta on top of the local edits silently. State **merged**.
- **Genuine conflict** — the local file and the shipped version changed the *same* region incompatibly, and there is no way to tell which should survive. This is the ONLY case that prompts. `AskUserQuestion`:
  - question: `<name>.css — conflicting edits in the same region. Which version wins for that region?`
  - description: ``**Conflicting region:**\n```diff\n<the conflicting hunk(s), both sides>\n```\n\nYou customized this snippet (e.g. tightened the selector, added per-theme tweaks) in the same place the shipped version changed. Merge-shipped takes the shipped version for that region; keep-local preserves yours and skips that part of the upstream change.``
  - options: **merge-shipped** / **keep-local**.
  - **merge-shipped** → write the shipped version for the conflicting region, keep non-conflicting local edits. State **merged**.
  - **keep-local** → leave the conflicting region as the user has it; still apply any non-conflicting shipped delta. State **kept-local**.

Use `Read` + `Write` so the merge stays visible. "Conflict" means same region changed incompatibly on both sides — not merely "bytes differ".

Outcome: per-snippet status word from `installed` / `unchanged` / `merged` / `kept-local`. Record for the Step 6 report.

## Step 3 — Enable snippets in appearance.json

Read `<vault>/appearance.json`. If missing or unparseable, treat its contents as `{}`.

- Ensure `enabledCssSnippets` exists as an array (create empty `[]` if absent).
- For each snippet `<name>` in `[mermaid-fit, ascii-fit]`:
  - If `<vault>/snippets/<name>.css` does not exist on disk, do NOT add the entry — pointing `enabledCssSnippets` at a missing file is dead config. Record per-snippet outcome **deferred** in this case. (Step 2's quiet sync always writes the file unless a conflict was kept-local in a way that removed it — normally the file is present.)
  - Otherwise, if the array does NOT contain `"<name>"`, append it.
- Atomic write (`appearance.json.tmp` → `mv`) only when the array changed.

Per-snippet outcome:
- `enabled` — added to the array this run.
- `already-enabled` — entry was already present.
- `deferred` — snippet file absent on disk; refused to register a stale entry.

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
2. If present → leave it in place silently. State **kept-orphan**. Orphans are never deleted: the user may have customized the file or still reference it, and we can't prove it's safe to remove. No prompt.

The report (Step 6) notes the legacy snippet is present and redundant so the user can remove it manually if they wish. The skill never deletes it.

## Step 6 — Report

One bullet per step, in order — missing bullet = skipped step, back up and run it.

- **Step 1** — repo-root + vault paths (or abort reason).
- **Step 2** snippets — one bullet per snippet (`mermaid-fit.css`, `ascii-fit.css`): **installed** / **unchanged** / **merged** / **kept-local**, with target path.
- **Step 3** appearance.json — one bullet per snippet: **enabled** / **already-enabled** / **deferred**.
- **Step 4** mermaid-popup: state tuple (`binary=... overrides=... community=...`) or **failed:`<reason>`**.
- **Step 5** legacy mermaid-no-bg.css: **kept-orphan** / **absent**.

Next steps shown to user:
- If any Step 3 outcome was **enabled**, remind: "Reload Obsidian (or click ↻ next to the snippet in Settings → Appearance → CSS snippets) — snippets won't apply mid-session."
- If any Step 2 outcome was **kept-local**, remind: "you kept a conflicting region in `mermaid-fit` / `ascii-fit` — re-run later to pick up the upstream change once you've reconciled it."
- If Step 5 outcome was **kept-orphan**, remind: "`mermaid-no-bg.css` is present but redundant (the engine emits a transparent-background directive natively) — remove it manually if you want a clean snippets dir."
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

Safe to re-run. Step 2's quiet sync is silent on absent/identical/clean-merge and prompts only on a genuine same-region conflict. Step 3 no-ops when the array entry is already present. Step 4 delegates to `/lazy-obsidian.update-plugin`, which is itself idempotent. Step 5 never deletes — the legacy snippet reports **kept-orphan** on every run while it's on disk (no prompt), **absent** once the user removes it manually.

## Notes

- **No diagram authoring in this skill.** This skill only sets up render glue. Authoring + emitting fences belongs to `/lazy-diagram.draw` (engine entry point).
- **No engine-side dependency.** This skill works whether or not `lazycortex-diagram` is enabled — the CSS + plugin are useful for any vault that contains mermaid fences. The engine is the recommended *producer*; nothing here requires it.
- **Chained from `/lazy-obsidian.install`.** That skill runs this one unconditionally as part of the standard vault setup (no per-chain opt-in — full vault setup means full functionality). Re-running this skill directly (after install) is the way to pick up template changes after a `/plugin update`.
