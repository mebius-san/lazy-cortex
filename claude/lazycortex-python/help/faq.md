---
chapter_type: faq
summary: Answers to common questions about installing, running, and customising lazycortex-python across style, docstrings, tests, and the checker stack.
last_regen: 2026-06-01
no_diagram: true
source_skills:
  - lazy-python.install
  - lazy-python.audit
  - lazy-python.check-style
  - lazy-python.docstring-writer
  - lazy-python.test-writer
  - lazy-python.style
  - lazy-python.tests
---
# Frequently asked questions

## Do I need to run `/lazy-python.install` again after a plugin update?

Yes. `/lazy-python.install` is idempotent — re-running it after an update is the correct way to pick up new canon rules, refreshed wrapper scripts, and any new `pyproject.toml` sections the update introduces. It only overwrites the three mirrored rule files (your `.claude/rules/lazy-python.*.md`) and any sections that are missing from your `pyproject.toml`; your existing project additions are left untouched. Consumer-edited files (overlay guidelines, `CLAUDE.md`, etc.) are never clobbered.

---

## The PostToolUse hook is not firing after install. How do I enable it?

The hook auto-registers from the plugin's `hooks/hooks.json` manifest when the plugin is enabled — no step in `/lazy-python.install` writes to your `settings.json`. If the hook is not firing, check that `lazycortex-python@lazycortex` appears in `enabledPlugins` in your `~/.claude/settings.json`, then restart Claude Code. The hook takes effect on the next `.py` edit once the session is live.

---

## `/lazy-python.audit` reports Check 1 as FAIL (drift). What does that mean?

One or more of the mirrored rule files under `.claude/rules/lazy-python.*.md` has drifted from the plugin canon — either a manual edit was made to a file that is plugin-managed, or the install was interrupted. Re-run `/lazy-python.install` to restore them. The install intentionally overwrites the mirror; any changes you wanted to make to those rules belong in your project overlay under `docs/guidelines/`, not in the mirrored files themselves.

---

## `/lazy-python.audit` warns about PyCharm inspect.sh (Check 6). Is that a problem?

Not for most of the checker stack. `pch.py` (the PyCharm inspection phase) requires `inspect.sh` from a PyCharm installation, but the other phases — `pcf`, `toi`, `cmp`, `mypy`, `ruff`, and `pylint` — run without it. `pch` is also not part of the `chk-py all` gate; it is a separate, slower manual subcommand (`chk-py pch <file>`). If you do not have PyCharm installed, Check 6 will always be `WARN` and `chk-py pch` will be unavailable. The rest of the pipeline remains fully functional.

---

## `/lazy-python.audit` warns about the venv (Check 11). How do I fix it?

Check 11 warns when no usable venv is found and bootstrapping one is not possible (e.g. `uv` is not on `$PATH`). Re-running `/lazy-python.install` re-probes the venv chain and attempts to bootstrap the plugin-local fallback venv under `${CLAUDE_PLUGIN_DATA}/venv`. If `uv` is available when you re-run, the venv is created automatically. If it is not, install `uv` first (`pip install uv` or the standalone installer), then re-run the install.

---

## When should I use `/lazy-python.check-style` versus the PostToolUse hook?

The PostToolUse hook runs `pcf.py` automatically on every `.py` edit and surfaces violations inline in the next turn — it is your fast inner loop. `/lazy-python.check-style` is the deeper six-step review you invoke before committing: it adds a manual pass over semantic issues the automated checkers cannot see (docstring quality, contract consistency, guard-clause coverage, special-comment preservation) and runs the full `chk-py all` sweep plus `tst-py` to gate the change. Use the hook continuously and `/lazy-python.check-style` at the end of a meaningful edit batch.

---

## Can I run `mypy`, `pylint`, or `ruff` directly instead of `chk-py`?

No. The plugin enforces running all style and type validation through `chk-py`. The aggregator runs `pcf`, `toi`, `cmp`, `mypy`, `ruff`, and `pylint` in the correct order with shared config from `pyproject.toml`; calling any one tool directly skips earlier phases and can produce misleading results. Similarly, use `tst-py` rather than raw `pytest` — the wrapper applies project-wide pytest args and uses the correct venv.

---

## Should I write docstrings by hand, or always use the agent?

Always use the `lazy-python.docstring-writer` agent. The canon enforces section ordering, a Zero-Tolerance Blocker list, an eight-point semantic Pre-Return Self-Check (checking for algorithm narration, private-internal references, tautological summaries, etc.), and an overlay merge from `docs/guidelines/documenting_guidelines.md`. Writing docstrings by hand from session memory of the canon reliably misses at least one of those checks. Dispatch the agent and let it own the result.

---

## The docstring-writer agent left a section blank. Is that a bug?

No. The agent omits sections that would be empty — that is correct behaviour per the style rules. For example, if a method has no documented exceptions, there is no `Raises:` section; if a class has no public instance fields, there is no `Attributes:` section. Do not add empty section headers to fill the gap.

---

## Should I write tests by hand, or always use the agent?

Always use the `lazy-python.test-writer` agent. The agent applies the Paranoid Testing Strategy (7 mandatory test categories per class), selects the correct base test class from your project overlay, enforces 2-space indentation and the 117-character line limit, derives expected values from docstring contracts rather than implementation, and runs `chk-py` plus `tst-py` as a verification gate. Hand-writing tests from session memory reliably skips categories or picks the wrong base class.

---

## A test written by the agent fails against the current implementation. Should I fix the test?

No. Per the Golden Rule in `lazy-python.test-writer`: if a test correctly reflects documented behaviour but fails against the current implementation, the implementation is suspect. The agent will add a `# FAILS: <reason>` comment above the test method and report the divergence to you. Fix the production code (or update the docstring if the spec has changed), not the test. Modifying an existing test also requires your explicit approval naming the specific test file — the agent will ask before touching it.

---

## How do I add project-specific style or testing rules without touching the plugin?

Use the overlay convention. The four overlay stubs under `docs/guidelines/` (`coding_guidelines.md`, `documenting_guidelines.md`, `testing_guidelines.md`, `checking_guidelines.md`) are where you add project-specific additions. Each overlay file opens with a `# Project additions to <topic>` header that the writer agents and `/lazy-python.check-style` recognise. Rules in an overlay override the corresponding canon rule on conflict; they extend it otherwise. If the overlay stubs are missing, re-run `/lazy-python.install` — Phase 5 scaffolds them without overwriting any existing content.

---

## The overlay stubs are present but the writer agents are not picking them up.

Check that each overlay file still opens with its canonical `# Project additions to <topic>` header. The agents use that header to distinguish an overlay from the canon itself — if it was removed or renamed, run `/lazy-python.audit` (Check 7) to confirm. Restore the header and re-dispatch the agent. The overlay files are never plugin-managed; `/lazy-python.install` will not overwrite them.

---

## `/lazy-python.install` aborts saying the plugin source was not found.

`${CLAUDE_PLUGIN_ROOT}` is unset or points at a path with no `rules/lazy-python.*.md` files. Confirm that `lazycortex-python@lazycortex` is listed in `enabledPlugins` in your `~/.claude/settings.json`, restart Claude Code so the plugin is loaded, then re-run `/lazy-python.install`.

---

## The `chk-py` wrapper is missing or not executable after install.

Re-run `/lazy-python.install` — Phase 2 deploys `cli/chk-py` and `cli/tst-py` and sets the executable bit. If the phase reports `wrappers-deployed-2` but the files are still absent, check that `cli/` exists in your project root; the phase creates it if missing. If the problem persists, run `/lazy-python.audit` (Check 4) to see whether unsubstituted `{{CHK_BIN_PATH}}` placeholders are present, which would indicate an interrupted or partial install.

---

## `pyproject.toml` is missing the checker sections after install.

Run `/lazy-python.audit` Check 5 to confirm which of the seven required sections (`[tool.pcf]`, `[tool.toi]`, `[tool.pch]`, `[tool.pytest]`, `[tool.mypy]`, `[tool.pylint]`, `[tool.ruff]`) are absent, then re-run `/lazy-python.install`. Phase 3 merges only the missing sections from `pyproject-defaults.toml` into your `pyproject.toml`; existing sections are never overwritten. If your `pyproject.toml` does not exist at all, Phase 3 creates it with the defaults.
