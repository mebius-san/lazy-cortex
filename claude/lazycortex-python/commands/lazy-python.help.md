---
description: Show lazycortex-python purpose and a one-line summary of each skill, agent, rule, and hook it ships
execution-discipline-waiver: "static help text — no executable steps"
logging-waiver: "static text — no executable steps"
---
Output the block below verbatim to the user. Do not summarize, rephrase, or add commentary. Do not invoke any tools. Do not log this run.

---

**lazycortex-python** — Python coding discipline as a plugin. Ships three path-scoped rules, five reference guidelines, `chk-py`/`tst-py` checker wrappers, a PostToolUse hook, docstring-writer and test-writer agents, and a canonical file template. Install once per repo via `/lazy-python.install`.

**Skills** (invoke as `/<name>` or via Skill tool):

- `lazy-python.install` — quiet install: mirrors rules, deploys `chk-py`/`tst-py` wrappers into `cli/`, bootstraps `pyproject.toml` checker sections (adds `[tool.pch]` automatically when PyCharm is present), gitignores `.venv/`, scaffolds `docs/guidelines/` overlay stubs, syncs the scaffold template. Asks nothing — scope and pch are derived, and it never touches CLAUDE.md. The PostToolUse hook auto-registers from the plugin manifest — no install step needed. Idempotent.
- `lazy-python.audit` — read-only 11-check health report: rules mirror integrity, reference resolution, artifact presence, wrappers, pyproject sections (incl. `[tool.ruff]`), hook manifest, venv state (`mypy`/`pylint`/`pytest`/`ruff` + `pytest-clarity`/`pytest-sugar`).
- `lazy-python.check-style` — manual 6-step review: reads canon + overlay, identifies modified files, runs manual inspection categories, then dispatches `chk-py` + `tst-py` to gate.

**Agents** (dispatched via `Agent(subagent_type: "lazycortex-python:<name>")`):

- `lazy-python.docstring-writer` — adds or fixes docstrings on classes, methods, and properties; reads canonical guidelines + project overlay on every dispatch.
- `lazy-python.test-writer` — writes pytest test files covering all seven Paranoid-Testing categories; reads canonical testing + checking guidelines + project overlay. Never modifies production code.

**Rules** (loaded automatically):

- `lazy-python.style` — Python style critical reminders + Verification Order. Triggers on `**/*.py`.
- `lazy-python.docstrings` — docstring discipline; use the `lazy-python.docstring-writer` agent. Triggers on `**/*.py`.
- `lazy-python.tests` — test placement, naming, and writing discipline; use the `lazy-python.test-writer` agent. Triggers on `tests/**/*.py`.

**Hook** (auto-registered from `hooks/hooks.json` when the plugin is enabled):

- `lazy-python.check-style` (`Edit|Write`) — PostToolUse: runs `pcf.py` on every edited `.py` file and returns violations as `additionalContext` in the next turn.

<!-- help-block:start -->
**Documentation:**

- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/install-and-audit.md) — Bootstrap lazycortex-python into your repo with a 7-phase install wizard and verify the installation with the 11-check read-only audit.
- [discipline](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/discipline.md) — Three always-loaded rules shape every Python edit; five reference guidelines back the writer agents and chk-py/tst-py with the full canon.
- [checkers](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/checkers.md) — The `chk-py` and `tst-py` CLI wrappers that gate every Python change — style, type-only imports, syntax, mypy, ruff, pylint, and pytest — backed by a shared venv resolver that works from any terminal.
- [hook](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/hook.md) — The PostToolUse hook that runs `pcf.py` on every `.py` edit and surfaces style violations inline in the next turn — zero install steps, zero config writes.
- [agents](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/agents.md) — Manual code-quality review via /lazy-python.check-style plus two dispatch-ready writer agents that enforce project conventions for docstrings and tests.
- [scaffold](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/scaffold.md) — Canonical Python file skeleton that seeds every new .py file Claude composes — installed once via /lazy-python.install Step 6.
- [overlay](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/overlay.md) — Project-specific guideline files in docs/guidelines/ let you extend or override the lazycortex-python canon per repo without touching plugin-managed files.
- [add-project-overlay](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/walkthroughs/add-project-overlay.md) — Layer project-specific docstring rules on top of the canon guidelines so lazy-python.docstring-writer honours your project's conventions on every dispatch.
- [install-and-first-check](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/walkthroughs/install-and-first-check.md) — Run /lazy-python.install in a clean repo, confirm the checker stack is wired, and get zero violations on first chk-py all.
- [migrate-existing-repo](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/walkthroughs/migrate-existing-repo.md) — Adopt lazycortex-python in a repo with pre-existing Python, run chk-py all to surface every drift violation, and fix them in committed chunks.
- [write-tests-for-new-class](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/walkthroughs/write-tests-for-new-class.md) — Dispatch lazy-python.test-writer against a new class and get a test file that covers all seven Paranoid-Testing categories, verified by tst-py.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/troubleshooting.md) — Symptoms, causes, and fixes for lazycortex-python install, audit, style checks, and writer agents.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/faq.md) — Answers to common questions about installing, running, and customising lazycortex-python across style, docstrings, tests, and the checker stack.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-python/help/`.
<!-- help-block:end -->

See `README.md` in the plugin for full scenarios and examples.
