---
name: lazy-python.install
description: Seven-phase install wizard that wires lazycortex-python into a consumer repo — mirrors rules, deploys chk-py / tst-py wrappers, bootstraps pyproject.toml checker stack, scaffolds project overlay guidelines, syncs the scaffold template, and offers an opt-in CLAUDE.md pointer. The PostToolUse check-style hook auto-registers from the plugin manifest — no install step writes to settings.json.
allowed-tools: Bash, Read, Edit, Write, Glob, Grep, AskUserQuestion
user-invocable: true
---
# Install lazycortex-python

Idempotent seven-phase install (plus a log write). Mirrors the three plugin rules into `.claude/rules/`, deploys the `chk-py` / `tst-py` wrappers into `cli/`, bootstraps the checker sections of `pyproject.toml`, scaffolds project-overlay guideline stubs, syncs the scaffold template, and optionally adds a discipline pointer to `CLAUDE.md`. Safe to re-run after every plugin update.

The PostToolUse check-style hook auto-registers from the plugin's `hooks/hooks.json` when the plugin is enabled — no install step writes to the consumer's settings.json.

## Execution discipline (MANDATORY — read before any action)

This skill has 8 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Mirror plugin rules into .claude/rules/`
   - `Step 2 — Deploy chk-py and tst-py wrappers into cli/ and ensure .venv/ gitignored`
   - `Step 3 — Bootstrap pyproject.toml checker sections`
   - `Step 4 — Detect PyCharm inspect.sh prerequisite`
   - `Step 5 — Scaffold project overlay guidelines under docs/guidelines/`
   - `Step 6 — Sync scaffold templates via lazy-core.scaffold-sync`
   - `Step 7 — Offer to add discipline pointer to CLAUDE.md`
   - `Step 8 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`mirrored-3`, `wrappers-deployed-2`, `pending-implementation`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1: Mirror plugin rules into `.claude/rules/`

Copy the three plugin rule files (`lazy-python.style.md`, `lazy-python.docstrings.md`, `lazy-python.tests.md`) byte-identical from `${CLAUDE_PLUGIN_ROOT}/rules/` to `<consumer>/.claude/rules/`. References, checkers, skills, agents, hooks, and templates stay in the plugin and are read by absolute path from `${CLAUDE_PLUGIN_ROOT}/...` — only rules ship into the consumer's session-loaded set.

The mirror is plugin-managed — consumers MUST NOT hand-edit the mirrored files (`/lazy-python.audit` check 1 flags drift as FAIL). Re-running this step overwrites local changes intentionally.

Run:

```
Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.install/bin/install_phases.py phase1 ${CLAUDE_PROJECT_DIR})
```

Outcome: `mirrored-3` when all three rules were copied (any source content rewrite is a successful mirror); `mirrored-skipped-unchanged` when re-run on already-current files (no detectable diff after copy).

## Step 2: Deploy chk-py and tst-py wrappers into `cli/` and ensure `.venv/` gitignored

Read `${CLAUDE_PLUGIN_ROOT}/templates/chk-wrapper.sh` and `tst-wrapper.sh`, substitute `{{CHK_BIN_PATH}}` and `{{TST_BIN_PATH}}` with absolute paths to `${CLAUDE_PLUGIN_ROOT}/bin/chk` and `${CLAUDE_PLUGIN_ROOT}/bin/tst` respectively, write the rendered scripts to `<consumer>/cli/chk-py` and `<consumer>/cli/tst-py`, and `chmod +x` each. Then ensure the consumer's `.gitignore` contains a `.venv/` line — the fallback venv (`_ensure_venv.sh` probe 4) is created in the repo root at `<consumer>/.venv`, so it must be ignored. The phase reads `<consumer>/.gitignore` (creating it if absent) and appends `.venv/` only when no `.venv` / `.venv/` line is already present — idempotent.

After this step `./cli/chk-py` and `./cli/tst-py` are callable from the terminal. The `-py` suffix is fixed — it lets per-language wrappers from other plugins coexist without name collisions. Adding `cli` to `$PATH` is the consumer's call.

Run:

```
Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.install/bin/install_phases.py phase2 ${CLAUDE_PROJECT_DIR})
```

Outcome: `wrappers-deployed-2 + gitignore-ensured` when `.venv/` was added to the consumer's `.gitignore`; `wrappers-deployed-2 + gitignore-already-present` when the `.venv/` line was already there (idempotent re-run).

## Step 3: Bootstrap pyproject.toml checker sections

Merges checker sections from `${CLAUDE_PLUGIN_ROOT}/templates/pyproject-defaults.toml` into the consumer's `pyproject.toml`. Existing sections are preserved (consumer wins) — only missing sections are appended. No user prompt — runs unconditionally.

Run:

```
Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.install/bin/install_phases.py phase3 ${CLAUDE_PROJECT_DIR})
```

Outcome: `pyproject-bootstrapped` when at least one missing section was appended; `pyproject-already-complete` when every required section was already present.

## Step 4: Detect PyCharm inspect.sh prerequisite

Probes for the PyCharm `inspect.sh` script that `pch` depends on. Emits status only — does not install or modify anything. No user prompt.

Run:

```
Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.install/bin/install_phases.py phase4 ${CLAUDE_PROJECT_DIR})
```

Outcome: `pch-ready` when `inspect.sh` was located; `pch-missing-inspect-sh` when it was not (consumer must install PyCharm or point the checker at the right path before `chk pch` will work).

## Step 5: Scaffold project overlay guidelines under `docs/guidelines/`

Creates stub overlay files (`coding_guidelines.md`, `documenting_guidelines.md`, `testing_guidelines.md`, `checking_guidelines.md`) under `<consumer>/docs/guidelines/` with the canonical `# Project additions to <topic>` headers. Existing files are left untouched (consumer wins). No user prompt.

Run:

```
Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.install/bin/install_phases.py phase5 ${CLAUDE_PROJECT_DIR})
```

Outcome: `overlay-created-N` (where `N` is the count of newly-created stubs) when at least one stub was scaffolded; `overlay-already-present` when all four overlay files already existed.

## Step 6: Sync scaffold templates via lazy-core.scaffold-sync

Copies the plugin's authoring templates into the consumer's `.claude/templates/python/` and upserts the matching scaffold-registry entry — so `lazy-core.scaffold` matches new `*.py` files against the consumer-local copy of the Python template. The registry value is the consumer-local path `.claude/templates/python/python-template.py`, never `${CLAUDE_PLUGIN_ROOT}/...` (rule bodies do not expand `${CLAUDE_PLUGIN_ROOT}`). No user prompt unless template drift is detected.

Resolve this plugin's own `<installPath>` (the `installPath` field of `lazycortex-python@lazycortex` in `~/.claude/plugins/installed_plugins.json`) and the detected `<scope>` (`project` / `user`), then dispatch:

```
Skill(skill: "lazycortex-core:lazy-core.scaffold-sync", args: "plugin=lazycortex-python installPath=<installPath> scope=<scope>")
```

The skill discovers `<installPath>/templates/python/scaffold.entries.json`, copies `templates/python/*` (excluding the manifest) into `<consumerScope>/.claude/templates/python/`, and upserts the `lazycortex-python` registry key via `scaffold upsert` (surgical — the consumer's `lazycortex-core` and `_local` keys stay byte-for-byte).

Outcome: the `scaffold-sync` report — per-template copy state (`installed` / `unchanged` / `merged` / `updated` / `kept-local`) plus the registry upsert status (`registered` / `unchanged` / `created-and-registered`).

## Step 7: Offer to add discipline pointer to CLAUDE.md

Use `AskUserQuestion` to ask the user whether to append a pointer in their `CLAUDE.md` to the lazy-python discipline rules. One question, one decision: `"Add Python discipline pointer to CLAUDE.md? (yes / no)"`.

The pointer goes into whichever `CLAUDE.md` Claude Code already auto-loads for this repo, resolved in order: the repo-root `<repo>/CLAUDE.md` if present, otherwise `<repo>/.claude/CLAUDE.md`. If neither file exists the step skips — phase7 never creates a `CLAUDE.md`.

If yes:

```
Bash(LAZY_PYTHON_INSTALL_ACCEPT=1 python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.install/bin/install_phases.py phase7 ${CLAUDE_PROJECT_DIR})
```

If no, skip the invocation entirely.

Outcome: `claude-md-pointer-added` (yes — pointer appended to the resolved CLAUDE.md) / `claude-md-pointer-skipped` (no — user declined, or no CLAUDE.md exists at either location).

## Step 8: Log the run

Log to `./.logs/claude/lazy-python.install/YYYY-MM-DD_HH-MM-SS.md` per the logging rule (include `git_sha`, `git_branch`, `date`, `input` frontmatter).

Use two separate steps: `Bash(mkdir -p ./.logs/claude/lazy-python.install)` then the `Write` tool. Never chain with `&&` or `cat > file <<'EOF'`.

Outcome: `logged`.

## Report

One line per task in the canonical list, with its outcome word. A missing line is a bug.

## Failure modes

- **`/lazy-python.install` aborts: plugin source not found** — `${CLAUDE_PLUGIN_ROOT}` is unset or points at a path with no `rules/lazy-python.*.md` files → ensure the plugin is installed and enabled, then re-run.
- **Step 1: target rule file is read-only** — consumer's `.claude/rules/lazy-python.*.md` is write-protected → unlock the file and re-run; the mirror always overwrites.
- **Step 2: wrapper template missing** — `${CLAUDE_PLUGIN_ROOT}/templates/{chk,tst}-wrapper.sh` absent from the plugin cache → run `/plugin update lazycortex-python@lazycortex` to restore templates, then re-run.
