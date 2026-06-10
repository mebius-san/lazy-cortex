---
name: lazy-python.install
description: Seven-phase install wizard that wires lazycortex-python into a consumer repo — mirrors rules, deploys chk-py / tst-py wrappers, bootstraps pyproject.toml checker stack, scaffolds project overlay guidelines, syncs the scaffold template, and offers an opt-in CLAUDE.md pointer. The PostToolUse check-style hook auto-registers from the plugin manifest — no install step writes to settings.json.
allowed-tools: Bash, Read, Edit, Write, Glob, Grep, AskUserQuestion, TaskCreate, TaskUpdate, TaskList, TaskGet
user-invocable: true
---
# Install lazycortex-python

Idempotent and quiet seven-phase install (plus a log write). Mirrors the three plugin rules into `.claude/rules/`, deploys the `chk-py` / `tst-py` wrappers into `cli/`, bootstraps the checker sections of `pyproject.toml`, scaffolds project-overlay guideline stubs, syncs the scaffold template, and optionally adds a discipline pointer to `CLAUDE.md`. Every file it writes follows the File-sync policy below — silent on a clean write or merge, asking only on a genuine conflict; every choice it makes is persisted and read first, so a re-run never re-asks. Install scope is derived (never asked); the Python ≥ 3.12 floor is owned by `/lazy-core.install` and not re-probed here. Safe to re-run after every plugin update.

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
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`installed`, `unchanged`, `merged`, `wrappers-deployed-2`, `already-present`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Decisions are remembered, never re-asked

This skill is **idempotent and quiet on re-run**. Every choice it makes is read first and honoured silently — the user is asked again only when nothing is on record yet.

- **Plugin enabled = full functionality.** An enabled plugin installs its whole surface. There is no per-file "install this?" prompt and no per-artifact opt-in — wanting the plugin means wanting its rules, wrappers, checker stack, overlays, and template.
- **Install scope is derived, not asked.** Read the `scope` field of the `lazycortex-python@lazycortex` entries in `~/.claude/plugins/installed_plugins.json`. If both `user` and `project` appear, default to `project` silently. Never ask user-vs-project.
- **The one persisted choice is the CLAUDE.md pointer** (Step 7) — a real edit to a consumer-owned file. Asked once; the answer (added / declined) is recorded so a "no" is never re-raised. See Step 7.
- **Everything else derivable is derived:** pch enablement (Step 3) follows the recorded flag; `inspect.sh` presence (Step 4) is probed, not asked.

The Python ≥ 3.12 floor is owned by `/lazy-core.install` (its single Step 0 probe). This skill MUST NOT re-probe the floor — there is no Python-version question here.

## File-sync policy (applies to every file this skill writes)

Every file this skill creates or updates — the rule mirror, the `chk-py` / `tst-py` wrappers, the `pyproject.toml` checker stack, the `docs/guidelines/*.md` overlays, and the scaffold template — follows three cases. No per-file "install?" prompt, no drift merge/overwrite/keep-local wizard:

1. **Absent or unchanged** — target missing, or byte-identical to the shipped / last-known version → write silently. State `installed` / `unchanged`.
2. **Locally changed but cleanly mergeable** — target diverged, but the shipped delta applies without contradicting local edits (new rules / sections / keys added, every local-only chunk left untouched) → merge silently. State `merged`.
3. **Genuine conflict** — the same region was changed both locally and in the shipped version in ways that cannot be reconciled automatically → the ONLY case that asks. `AskUserQuestion` naming the file, quoting the conflicting region, showing a unified diff; options `merge-shipped` / `keep-local`.

"Conflict" means you cannot determine what should survive — **not** merely "the bytes differ". No contradiction → no question. A no-longer-shipped file (orphan) is left in place silently (`kept-orphan`); this skill never deletes consumer files.

**Consumer-owned config nuance** — `pyproject.toml` and the `docs/guidelines/*.md` overlays are config the consumer routinely edits. Adding a missing checker section or a missing overlay stub is a clean, non-contradictory merge → always silent. Only a direct contradiction (the consumer set a checker key to a value that opposes a required one) is a conflict that asks per case 3.

## Step 1: Mirror plugin rules into `.claude/rules/`

Mirror the three plugin rule files (`lazy-python.style.md`, `lazy-python.docstrings.md`, `lazy-python.tests.md`) from `${CLAUDE_PLUGIN_ROOT}/rules/` into `<consumer>/.claude/rules/` under the **File-sync policy**, per rule. References, checkers, skills, agents, hooks, and templates stay in the plugin and are read by absolute path from `${CLAUDE_PLUGIN_ROOT}/...` — only rules ship into the consumer's session-loaded set.

The mirror is plugin-managed — consumers are not meant to hand-edit the mirrored files (`/lazy-python.audit` check 1 flags drift). Apply the policy: absent or byte-identical → write silently; locally changed but the shipped delta applies cleanly → merge silently; same region changed incompatibly in both → the only case that asks.

The `phase1` helper copies all three byte-identical (the absent / unchanged path). When a target rule has diverged, do NOT run `phase1` over it blindly — apply the policy via `Read` + `Edit` so a genuine conflict is surfaced, not silently clobbered.

```
Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.install/bin/install_phases.py phase1 ${CLAUDE_PROJECT_DIR})
```

Outcome per rule: `installed` (absent → copied) / `unchanged` (byte-identical) / `merged` (drift, clean delta) / `kept-local` (conflict, user chose local).

## Step 2: Deploy chk-py and tst-py wrappers into `cli/` and ensure `.venv/` gitignored

Read `${CLAUDE_PLUGIN_ROOT}/templates/chk-wrapper.sh` and `tst-wrapper.sh`, substitute `{{CHK_BIN_PATH}}` and `{{TST_BIN_PATH}}` with absolute paths to `${CLAUDE_PLUGIN_ROOT}/bin/chk` and `${CLAUDE_PLUGIN_ROOT}/bin/tst` respectively, write the rendered scripts to `<consumer>/cli/chk-py` and `<consumer>/cli/tst-py`, and `chmod +x` each. Then ensure the consumer's `.gitignore` contains a `.venv/` line — the fallback venv (`_ensure_venv.sh` probe 4) is created in the repo root at `<consumer>/.venv`, so it must be ignored. The phase reads `<consumer>/.gitignore` (creating it if absent) and appends `.venv/` only when no `.venv` / `.venv/` line is already present — idempotent.

After this step `./cli/chk-py` and `./cli/tst-py` are callable from the terminal. The `-py` suffix is fixed — it lets per-language wrappers from other plugins coexist without name collisions. Adding `cli` to `$PATH` is the consumer's call.

Run:

```
Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.install/bin/install_phases.py phase2 ${CLAUDE_PROJECT_DIR})
```

The wrappers are rendered plugin artifacts (substituted absolute paths, not consumer-authored). Under the File-sync policy this is the absent / unchanged write path — `phase2` writes the current render; a re-run with an unchanged render is a no-op rewrite. The `.gitignore` append is idempotent (case 2 clean merge — adds the `.venv/` line only when absent).

Outcome: `wrappers-deployed-2 + gitignore-ensured` when `.venv/` was added to the consumer's `.gitignore`; `wrappers-deployed-2 + gitignore-already-present` when the `.venv/` line was already there (idempotent re-run).

## Step 3: Bootstrap pyproject.toml checker sections

Merges checker sections from `${CLAUDE_PLUGIN_ROOT}/templates/pyproject-defaults.toml` into the consumer's `pyproject.toml` under the **File-sync policy** (consumer-owned-config nuance): missing sections are appended (clean merge, silent); existing sections are preserved verbatim (consumer wins). Only a direct contradiction — a consumer checker key set to a value that opposes a required one — is a conflict that asks per case 3.

The always-on sections (`pcf`, `toi`, `pytest`, `mypy`, `pylint`, `ruff`) deploy unconditionally. The `pch` section (PyCharm offline inspections) is opt-in — it spins up a headless PyCharm and is meaningless without it.

**Read the recorded pch choice first; ask only when nothing is on record.** Read `lazy-python.pch_enabled` from the install scope's `lazy.settings.json` (`~/.claude/lazy.settings.json` at `user` scope, `<repo-root>/.claude/lazy.settings.json` at `project` scope):

```bash
PYTHONPATH=${CLAUDE_PLUGIN_ROOT_CORE}/bin python3 -c "
from lazy_settings import load_section
from pathlib import Path
sec = load_section(Path('<settings-path>'), 'lazy-python')
print(sec.get('pch_enabled', 'unset'))
"
```

- `True` → deploy `[tool.pch]`; do NOT ask.
- `False` → leave pch out; do NOT ask.
- `unset` → ask once with `AskUserQuestion`, one question: `"Enable PyCharm inspections (pch)? Adds a [tool.pch] section. Only useful if you run PyCharm; pch stays out of 'chk all' and is run manually."` (yes / no). Persist the answer so it is never re-raised:

```bash
PYTHONPATH=${CLAUDE_PLUGIN_ROOT_CORE}/bin python3 -c "
from lazy_settings import load_section, save_section
from pathlib import Path
p = Path('<settings-path>')
sec = load_section(p, 'lazy-python')
sec['pch_enabled'] = <True|False>
save_section(p, 'lazy-python', sec)
"
```

(`${CLAUDE_PLUGIN_ROOT_CORE}` is `lazycortex-core`'s `installPath` — resolve it from `installed_plugins.json` the same way Step 6 resolves this plugin's; the settings helpers ship with core.)

Run phase3, passing the resolved choice through the `LAZY_PYTHON_ENABLE_PCH` env flag:

```
# pch enabled — also deploy [tool.pch]:
Bash(LAZY_PYTHON_ENABLE_PCH=1 python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.install/bin/install_phases.py phase3 ${CLAUDE_PROJECT_DIR})
# pch disabled — leave pch out (default):
Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.install/bin/install_phases.py phase3 ${CLAUDE_PROJECT_DIR})
```

Outcome: `pyproject-bootstrapped` when at least one missing section was appended; `pyproject-already-complete` when every required section was already present — suffixed `+pch-enabled` / `+pch-declined` (from record) or `+pch-asked-enabled` / `+pch-asked-declined` (asked this run).

## Step 4: Detect PyCharm inspect.sh prerequisite

Probes for the PyCharm `inspect.sh` script that `pch` depends on. Emits status only — does not install or modify anything. No user prompt.

Run:

```
Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.install/bin/install_phases.py phase4 ${CLAUDE_PROJECT_DIR})
```

Outcome: `pch-ready` when `inspect.sh` was located; `pch-missing-inspect-sh` when it was not (consumer must install PyCharm or point the checker at the right path before `chk pch` will work).

## Step 5: Scaffold project overlay guidelines under `docs/guidelines/`

Creates stub overlay files (`coding_guidelines.md`, `documenting_guidelines.md`, `testing_guidelines.md`, `checking_guidelines.md`) under `<consumer>/docs/guidelines/` with the canonical `# Project additions to <topic>` headers, under the **File-sync policy**. These are consumer-owned config: absent → write the stub silently; present → left untouched silently (the consumer's overlay is authoritative — case "kept-local"). A stub vs a consumer-edited overlay is never a conflict, so this step never asks.

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

Appending a pointer to the consumer's `CLAUDE.md` is a real edit to a consumer-owned file, so this is the **one kept question** — but read-first, and a decline is persisted so it is never re-raised.

The pointer goes into whichever `CLAUDE.md` Claude Code already auto-loads for this repo, resolved in order: the repo-root `<repo>/CLAUDE.md` if present, otherwise `<repo>/.claude/CLAUDE.md`. If neither file exists the step skips silently — phase7 never creates a `CLAUDE.md`.

**Read first, then decide whether to ask:**

1. **Pointer already present** — if the resolved `CLAUDE.md` already contains the `lazy-python plugin rules` marker, skip silently. State `already-present`. Do NOT ask.
2. **Previously declined** — read `lazy-python.claude_md_pointer` from the install scope's `lazy.settings.json` (path resolved as in Step 3). If it is `declined`, skip silently. State `skipped-declined`. Do NOT ask.
3. **Nothing on record** — ask once with `AskUserQuestion`, one decision: `"Add a Python discipline pointer to your CLAUDE.md? (a one-line link to the lazy-python rules — yes / no)"`.
   - **Yes** → append via phase7, then record the choice:

```
Bash(LAZY_PYTHON_INSTALL_ACCEPT=1 python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.install/bin/install_phases.py phase7 ${CLAUDE_PROJECT_DIR})
```

```bash
PYTHONPATH=${CLAUDE_PLUGIN_ROOT_CORE}/bin python3 -c "
from lazy_settings import load_section, save_section
from pathlib import Path
p = Path('<settings-path>')
sec = load_section(p, 'lazy-python')
sec['claude_md_pointer'] = 'added'
save_section(p, 'lazy-python', sec)
"
```

   - **No** → do not call phase7; persist the decline so a re-run never re-asks:

```bash
PYTHONPATH=${CLAUDE_PLUGIN_ROOT_CORE}/bin python3 -c "
from lazy_settings import load_section, save_section
from pathlib import Path
p = Path('<settings-path>')
sec = load_section(p, 'lazy-python')
sec['claude_md_pointer'] = 'declined'
save_section(p, 'lazy-python', sec)
"
```

Outcome: `added` (yes — pointer appended) / `already-present` (marker already in CLAUDE.md) / `skipped-declined` (declined this run or previously) / `skipped-no-claude-md` (no CLAUDE.md exists at either location — the question is never raised since there is nothing to edit).

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
