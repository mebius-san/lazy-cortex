---
chapter_type: walkthrough
summary: Run /lazy-python.install in a clean repo, confirm the checker stack is wired, and get zero violations on first chk-py all.
last_regen: 2026-06-01
diagram_spec:
  anchor: "Install-and-first-check flow"
  request: "Sequence diagram: user invokes /lazy-python.install → 7 phases (mirror rules, deploy wrappers, bootstrap pyproject.toml, detect pch, scaffold overlay, sync scaffold template, offer CLAUDE.md pointer) → PostToolUse hook auto-registers from plugin manifest → user runs chk-py all -q → venv resolver creates .venv and runs the six-step gate → zero violations reported"
  kind_hint: sequence
source_skills:
  - lazy-python.install
---
# Bootstrap the plugin in a clean repo and confirm the checker stack is wired up

This walkthrough is for anyone enabling `lazycortex-python` in a new or existing Python repo for the first time. You'll run the seven-phase install wizard, confirm that `chk-py` and `tst-py` land in `cli/`, watch the venv resolver build the project-local `.venv` on first run, and verify the checker stack reports zero violations on a clean tree. The PostToolUse hook that fires on every `.py` edit wires itself up automatically — no settings file touch required.

## Outcome

After this walkthrough you have:

- Three plugin rule mirrors in `.claude/rules/` that constrain how Claude writes Python in this repo.
- `cli/chk-py` and `cli/tst-py` wrapper scripts callable from any terminal.
- A project-local `.venv` (repo root) with `mypy`, `pylint`, `pytest`, `ruff`, `pytest-clarity`, and `pytest-sugar` installed — plus `.venv/` gitignored so it never enters source control.
- `pyproject.toml` bootstrapped with checker-default sections (`pcf`, `toi`, `pytest`, `mypy`, `pylint`, `ruff`).
- Overlay stub files under `docs/guidelines/` ready for project-specific additions.
- The PostToolUse hook live, running `pcf.py` against every `.py` edit and surfacing violations inline.
- A clean `chk-py all -q` exit on the existing tree.

## What you need

- `lazycortex-core` installed and enabled in Claude Code (this plugin layers on its runtime).
- `lazycortex-python@lazycortex` installed and enabled — `enabledPlugins` in your `~/.claude/settings.json`.
- Python 3 reachable on `$PATH` (the checker scripts and hook are Python).
- A repo with at least one tracked file — the wizard reads and optionally edits `pyproject.toml` and `CLAUDE.md` from the repo root.
- Write access to the repo root (for `.gitignore`, `pyproject.toml`, `cli/`, `docs/guidelines/`, and `.claude/`).

## The journey

### Step 1 — Run the install wizard

In your Claude Code session, invoke:

```
/lazy-python.install
```

The wizard runs eight ordered phases. You will be asked two questions during the run:

1. **Enable PyCharm inspections (`pch`)?** — `pch` runs a headless PyCharm inspect and is kept out of `chk-py all`; it is only useful if you have PyCharm. Answer `no` for a standard setup.
2. **Add Python discipline pointer to `CLAUDE.md`?** — Appends a short pointer to the auto-loaded `CLAUDE.md` so the discipline rules surface in every session. Answer `yes` to get the reminder in context; `no` to skip.

The wizard will not ask anything else. Every other phase is automatic and idempotent.

**Verification gate**: the wizard ends with a one-line-per-phase report. Confirm each phase shows an outcome word — `mirrored-3`, `wrappers-deployed-2 + gitignore-ensured`, `pyproject-bootstrapped`, and so on. Any `ERROR` or missing line means a phase failed; see the troubleshooting doc before continuing.

### Step 2 — Confirm the wrappers landed

After the wizard exits, check that `cli/chk-py` and `cli/tst-py` are executable:

```bash
ls -la cli/chk-py cli/tst-py
```

Both should show `-rwxr-xr-x`. If the `cli/` directory is new to this repo, optionally add it to your shell `$PATH` — the wrappers work by absolute path too, so this step is convenience only.

### Step 3 — Confirm the rule mirrors landed

```bash
ls .claude/rules/lazy-python.*.md
```

You should see `lazy-python.style.md`, `lazy-python.docstrings.md`, and `lazy-python.tests.md`. These are plugin-managed — do not hand-edit them. If drift is detected later, `/lazy-python.audit` flags it as a failure and re-running `/lazy-python.install` overwrites the local copies.

### Step 4 — Run the checker stack for the first time

```bash
./cli/chk-py all -q
```

On first run the venv resolver finds no pre-existing venv, creates `.venv/` at the repo root, and installs `mypy`, `pylint`, `pytest`, `ruff`, `pytest-clarity`, and `pytest-sugar` into it. This takes roughly 30–60 seconds. Subsequent runs reuse the venv and are fast.

The resolver probe order is: `$VIRTUAL_ENV` → `<repo>/.venv` → any path configured in `pyproject.toml [tool.pcf]`. The first match wins; the fallback `<repo>/.venv` creation happens only when none of the earlier probes resolves.

`chk-py all` runs the six-step gate in order: `pcf` (style critical-fail) → `toi` (test-of-intent) → `cmp` (py_compile syntax check) → `mypy` → `ruff` → `pylint`. The `-q` flag suppresses per-file progress lines and shows only violations and the final summary.

**Verification gate**: on a clean tree with no pre-existing Python violations, the final line should be `All checks passed` (or equivalent zero-violation output from each checker). If any checker reports violations, they are findings against your existing code — work through them before treating the install as complete.

### Step 5 — Confirm the PostToolUse hook is live

Edit any `.py` file in Claude Code (a one-character whitespace change is enough). The PostToolUse hook fires automatically — it does not appear in the wizard output because it auto-registers from the plugin's `hooks/hooks.json` manifest the moment the plugin is enabled. You do not need to touch `settings.json`.

After the edit, the next Claude turn should include any `pcf.py` violations for that file in its context. On a clean file you will see no violations appended — that is the expected outcome.

### Step 6 — Confirm the overlay stubs exist

```bash
ls docs/guidelines/
```

You should see four stub files: `coding_guidelines.md`, `documenting_guidelines.md`, `testing_guidelines.md`, and `checking_guidelines.md`. Each is a minimal stub with a `# Project additions to <topic>` header and no content yet. These are yours to fill in — the writer agents (`lazy-python.docstring-writer`, `lazy-python.test-writer`) read them on every dispatch and honour any project-specific delta you add. The **add-project-overlay** walkthrough covers that step.

## After you're done

The install is idempotent — you can re-run `/lazy-python.install` after every plugin update and it will overwrite only what changed, leaving your `pyproject.toml` consumer sections and overlay stubs untouched (consumer wins on conflict). Re-running is the recommended upgrade path.

To verify the installation is healthy at any future point without re-installing, run `/lazy-python.audit`. It runs 11 read-only checks covering rule mirror integrity, wrapper presence, pyproject sections, venv state, hook registration, and overlay presence — no writes, no prompts.

`chk-py all` is the routine gate for any Python change you commit. `tst-py <module>` runs pytest scoped to a module or path. Both are callable from the terminal and from Claude skills; the PostToolUse hook additionally runs `pcf.py` (the style critical-fail subset) automatically after every `.py` edit so violations surface inline without a manual check.

## Install-and-first-check flow
