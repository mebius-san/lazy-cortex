---
description: "Run when the operator asks what lazycortex-python enforces, how Python is checked in this repo, which verb runs the checkers, or where domain and contract markers come from — lists the Python-discipline surface: install / audit / check-style / knowledge-sweep, the `chk-py` and `tst-py` wrappers, the docstring-writer / test-writer / code-reviewer agents plus the domain-writer / contract-writer knowledge-marker pair, the always-loaded style, docstring and test rules, and the PostToolUse style hook."
execution-discipline-waiver: "static help text — no executable steps"
logging-waiver: "static text — no executable steps"
---
Output the block below verbatim to the user. Do not summarize, rephrase, or add commentary. Do not invoke any tools. Do not log this run.

---

**lazycortex-python** — Python coding discipline as a plugin. Ships three path-scoped rules, five reference guidelines, `chk-py`/`tst-py` checker wrappers, a PostToolUse hook, docstring-writer / test-writer / code-reviewer / domain-writer / contract-writer agents, and a canonical file template. Install once per repo via `/lazy-python.install`.

**Skills** (invoke as `/<name>` or via Skill tool):

- `lazy-python.install` — quiet install: mirrors rules, deploys `chk-py`/`tst-py` wrappers into `cli/`, bootstraps `pyproject.toml` checker sections (adds `[tool.pch]` automatically when PyCharm is present), gitignores `.venv/`, scaffolds `docs/guidelines/` overlay stubs, syncs the scaffold template. Asks nothing — scope and pch are derived, and it never touches CLAUDE.md. The PostToolUse hook auto-registers from the plugin manifest — no install step needed. Idempotent.
- `lazy-python.audit` — read-only 12-check health report: rules mirror integrity, reference resolution, artifact presence, wrappers, pyproject sections (incl. `[tool.ruff]`), hook manifest, venv state (`mypy`/`pylint`/`pytest`/`ruff` + `pytest-clarity`/`pytest-sugar`), domain-groups dictionary.
- `lazy-python.check-style` — manual 6-step review: reads canon + overlay, identifies modified files, runs manual inspection categories, then dispatches `chk-py` + `tst-py` to gate.
- `lazy-python.knowledge-sweep` — grows the domain-groups dictionary from the knowledge parked under `Domain(unfiled):` (operator ticks the candidate groups), reconciles groups used in code but absent from the dictionary, then sweeps the sources with both knowledge-marker agents so every block lands under a real group.

**Agents** (dispatched via `Agent(subagent_type: "lazycortex-python:<name>")`):

- `lazy-python.docstring-writer` — adds or fixes docstrings on classes, methods, and properties; reads canonical guidelines + project overlay on every dispatch.
- `lazy-python.test-writer` — writes pytest test files covering all seven Paranoid-Testing categories; reads canonical testing + checking guidelines + project overlay. Never modifies production code.
- `lazy-python.code-reviewer` — reviews new or changed code against the canon plus the project overlay — the guideline layer no checker can prove. Runs as the `chk-py review` phase of the check pipeline; reports findings only, never edits code.
- `lazy-python.domain-writer` — writes `Domain(<group>):` blocks for domain mechanics, formulas, and rules, validating every group against the project's domain-groups dictionary; parks knowledge under `Domain(unfiled):` when no listed group fits, and refiles parked blocks when dispatched with `refile=true`.
- `lazy-python.contract-writer` — writes `Contract:` blocks for caller-visible guarantees and syncs the owning docstring's `Guarantees` / `Subclassing` section in the same pass.

**Rules** (loaded automatically):

- `lazy-python.style` — Python style critical reminders + Verification Order. Triggers on `**/*.py`.
- `lazy-python.docstrings` — docstring discipline; use the `lazy-python.docstring-writer` agent. Triggers on `**/*.py`.
- `lazy-python.tests` — test placement, naming, and writing discipline; use the `lazy-python.test-writer` agent. Triggers on `tests/**/*.py`.

**Hook** (auto-registered from `hooks/hooks.json` when the plugin is enabled):

- `lazy-python.check-style` (`Edit|Write`) — PostToolUse: runs `pcf.py` on every edited `.py` file and returns violations as `additionalContext` in the next turn.

<!-- help-block:start -->
**Documentation:**

- [agents](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/agents.md) — Manual review via /lazy-python.check-style, the chk-py review guideline phase and its lazy-python.code-reviewer agent, docstring/test writer agents, a Domain/Contract knowledge-marker pair, and the knowledge-sweep skill that backfills markers across an existing codebase.
- [checkers](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/checkers.md) — chk-py runs pcf, toi, cmp, mypy, ruff, pylint plus guideline review; tst-py runs pytest; both share a venv resolver that works anywhere.
- [discipline](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/discipline.md) — Three always-loaded rules shape every Python edit; five reference guidelines back the writer agents and chk-py/tst-py with the full canon.
- [hook](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/hook.md) — The PostToolUse hook that runs `pcf.py` on every `.py` edit and surfaces style violations inline in the next turn — zero install steps, zero config writes.
- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/install-and-audit.md) — Bootstrap lazycortex-python with a 10-step install wizard (incl. env_source detection) and verify with the 12-check read-only audit.
- [overlay](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/overlay.md) — Project-specific guideline files in docs/guidelines/ plus [tool.pcf] declarations in pyproject.toml let you extend the project-neutral canon per repo.
- [scaffold](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/scaffold.md) — Canonical Python file skeletons — python-template.py for regular files, init-template.py for __init__.py — installed once via /lazy-python.install Step 6.
- [add-project-overlay](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/walkthroughs/add-project-overlay.md) — Register a documentation-guideline clause in the project overlay, then confirm lazy-python.docstring-writer honors it in the generated docstring.
- [install-and-first-check](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/walkthroughs/install-and-first-check.md) — Install lazycortex-python, then run chk-py all -q directly to build the project venv and prove the six-step checker gate is clean.
- [migrate-existing-repo](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/walkthroughs/migrate-existing-repo.md) — Adopt lazycortex-python in a repo with pre-existing Python, run chk-py all to surface every drift violation (including pcf's language and project-package checks), then backfill Domain/Contract markers with knowledge-sweep.
- [write-tests-for-new-class](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/walkthroughs/write-tests-for-new-class.md) — Dispatch lazy-python.test-writer against a new class and get a test file that covers all seven Paranoid-Testing categories, verified by tst-py.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/troubleshooting.md) — Symptoms, causes, and fixes for lazycortex-python install, audit, style checks, the guideline-review gate, and writer agents.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/faq.md) — Answers to common questions about installing, running, and customising lazycortex-python across style, docstrings, knowledge markers, tests, and the checker stack.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-python/help/`.
<!-- help-block:end -->

See `README.md` in the plugin for full scenarios and examples.
