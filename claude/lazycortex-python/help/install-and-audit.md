---
chapter_type: block
summary: Bootstrap lazycortex-python into your repo with a 7-phase install wizard and verify the installation with the 11-check read-only audit.
last_regen: 2026-06-01
diagram_spec:
  anchor: "How install and audit relate"
  request: "Show the two-skill lifecycle: /lazy-python.install runs 7 phases (mirror rules → deploy wrappers → bootstrap pyproject → detect PyCharm → scaffold overlays → sync scaffold template → offer CLAUDE.md pointer) producing a verified install state, then /lazy-python.audit walks 11 read-only checks against that state and emits PASS/WARN/FAIL per check. Depict the flow from user invocation through install phases to installed-state artifacts, then through audit checks to the audit report. Highlight that re-running install is the fix for any FAIL."
  kind_hint: flow
source_skills:
  - lazy-python.install
  - lazy-python.audit
---
# Install and audit

Getting the lazycortex-python plugin working in a new repo is a two-verb operation: `/lazy-python.install` wires everything in, and `/lazy-python.audit` tells you whether it's all still healthy. Install is idempotent — you can re-run it after any plugin update without fear of overwriting your own work. Audit is read-only — it never changes anything, so it's safe to run at any time.

Both skills operate against the current working directory, so run them once per repo that adopts the plugin.

## When you'd use this

- You've just enabled `lazycortex-python@lazycortex` in your `~/.claude/settings.json` and need to wire it into an existing Python project.
- You've updated the plugin from the marketplace and want to refresh the rule mirrors and wrapper scripts in a consumer repo.
- Something feels off — checks aren't running, `chk-py` is missing, or a rule file looks wrong — and you want a read-only diagnosis before you fix anything.
- You're onboarding a new machine or a new team member to a repo that already has the plugin and need to confirm all 11 invariants hold.

## How it fits together

You start with `/lazy-python.install`. The wizard runs seven phases in order, each targeting a different piece of the installation contract. Phase 1 copies the three plugin rule files (`lazy-python.style.md`, `lazy-python.docstrings.md`, `lazy-python.tests.md`) byte-identical into your project's `.claude/rules/` — these are plugin-managed mirrors that Claude Code loads automatically, and you must not hand-edit them. Phase 2 renders `chk-py` and `tst-py` wrapper scripts into your `cli/` directory so you can call the checker stack from the terminal, and ensures `.venv/` is listed in your `.gitignore` (adding the line if absent). Phase 3 merges the always-on checker sections (`[tool.pcf]`, `[tool.toi]`, `[tool.pytest]`, `[tool.mypy]`, `[tool.pylint]`, `[tool.ruff]`) into your `pyproject.toml` without touching sections you've already configured — consumer wins on every merge. Phase 3 also asks — once — whether to add `[tool.pch]` for PyCharm offline inspections (it's opt-in, since it requires PyCharm's `inspect.sh` to be useful). Phase 4 probes for the PyCharm `inspect.sh` script that the `pch` checker needs; it reports the result but makes no changes. Phase 5 scaffolds four overlay stub files under `docs/guidelines/` with canonical `# Project additions to <topic>` headers; existing files are left alone. Phase 6 dispatches `lazy-core.scaffold-sync`, which copies the Python file template into `.claude/templates/python/` and upserts the matching entry in `lazy-core.scaffold.md` so new `.py` files start from the canonical skeleton. Phase 7 asks you — once — whether to add a discipline pointer to your `CLAUDE.md`. The PostToolUse hook that runs `pcf.py` on every `.py` edit is not an install step; it auto-registers from the plugin's `hooks/hooks.json` manifest the moment the plugin is enabled.

Once the install completes, `/lazy-python.audit` is the instrument you reach for to verify the result. It walks all 11 invariants in order: Check 1 confirms the three mirrored rules are byte-identical to the plugin canon. Check 2 confirms every `${CLAUDE_PLUGIN_ROOT}/references/...` path cited from a mirrored rule resolves to an existing file. Check 3 confirms the plugin tree on disk carries every required artifact — the manifest and overview, three rules, five references, six binaries, the PostToolUse hook script and its `hooks.json` manifest, the check-style skill, both authoring agents, and four templates. Check 4 confirms both wrappers exist and are executable; a missing wrapper is `WARN`, but an unsubstituted `{{CHK_BIN_PATH}}` or `{{TST_BIN_PATH}}` placeholder is `FAIL` (the install was interrupted before substitution completed). Check 5 confirms all seven `pyproject.toml` checker sections are present (`pcf`, `toi`, `pch`, `pytest`, `mypy`, `pylint`, `ruff`). Check 6 probes for `inspect.sh` (informational — its absence is always `WARN`, never `FAIL`). Check 7 confirms each of the four overlay files opens with the canonical header so writer agents can identify them. Check 8 confirms the scaffold registry entry for `python-template.py` is present in `lazy-core.scaffold.md`. Check 9 checks for a `lazy-python` pointer in `CLAUDE.md` (`WARN` on absence, never `FAIL` — you own that file). Check 10 confirms the plugin ships a well-formed `hooks.json` declaring the PostToolUse hook. Check 11 probes the venv resolution chain (`$VIRTUAL_ENV` → `<repo>/.venv` → `[tool.lazy-python].venv` in pyproject → implicit fallback) and verifies that all four tools (`mypy`, `pylint`, `pytest`, `ruff`) plus the two pytest plugins (`pytest-clarity`, `pytest-sugar`) are available in whichever venv is found, or that the `uv`-driven fallback can bootstrap them on first `chk-py`. Nothing is modified. The final report shows `pass=<n> warn=<n> fail=<n>`.

The connection between them is intentionally simple: the fix for any `FAIL` or `WARN` from audit is to re-run install. Install is idempotent and always overwrites its own outputs, so a fresh run resets every check to green.

## Common adjustments

**Updating after a plugin version bump.** Re-run `/lazy-python.install` in each repo. The rule mirrors, wrapper scripts, and scaffold templates are overwritten with the new plugin versions. Your `pyproject.toml` custom sections are preserved — consumer wins on the merge.

**PyCharm inspections (pch).** Install Phase 3 asks whether to add `[tool.pch]` to `pyproject.toml`. Say yes only if you have PyCharm installed and its `inspect.sh` is on your `$PATH`; the rest of the checker stack runs regardless of your answer. If you said no at install time and change your mind later, re-run `/lazy-python.install` — Phase 3 skips sections that are already present, so the only thing it will add is the missing `[tool.pch]`.

**Overlay guidelines.** After install, open the four stub files under `docs/guidelines/` and add your project-specific rules. Writer agents read the canon first, then the overlay; the `# Project additions to <topic>` header must be preserved so agents recognise the file as an overlay rather than the canon. If audit's Check 7 reports `WARN` or `FAIL` on an overlay header, you can restore the header by hand — it's a single-line edit to the consumer file, and it's the one field the overlay check reads.

**PyCharm `inspect.sh` not found.** Check 6 and install Phase 4 both probe for this script and report `WARN` when it's missing; the rest of the checker stack (`pcf`, `toi`, `mypy`, `pylint`, `ruff`, `pytest`) is unaffected. If you want `pch.py` to work, install PyCharm and ensure its `bin/inspect.sh` is on your `$PATH`.

**Venv.** Check 11 probes `$VIRTUAL_ENV`, then `<repo>/.venv`, then `[tool.lazy-python].venv` in `pyproject.toml`, then falls back to an implicit bootstrap via `uv`. If Check 11 reports `WARN` and you have a venv that's missing some tools, activate it and run `chk-py` once — `_ensure_venv.sh` augments the existing venv in place rather than replacing it. A `WARN` from Check 11 never blocks the rest of the checker stack; it only means the bootstrap hasn't run yet.

**Declining the CLAUDE.md pointer.** If you said no at install time and change your mind later, re-run `/lazy-python.install` and say yes at Phase 7. The pointer is additive — it won't duplicate if it's already there.

**Plugin not found.** If install aborts with a "plugin source not found" message, `${CLAUDE_PLUGIN_ROOT}` is unset or points at an incomplete tree. Confirm the plugin is enabled in `~/.claude/settings.json` and restart Claude Code, then re-run.

## How install and audit relate

## See also

- **discipline** — the three rules and five reference guidelines that install puts in place and audit verifies.
- **checkers** — the `chk-py` and `tst-py` wrappers that Phase 2 deploys.
- **hook** — the PostToolUse hook that auto-registers from the plugin manifest; audit Check 10 verifies its manifest is well-formed.
