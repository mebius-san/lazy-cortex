---
description: Python style critical reminders + Verification Order. Triggers on **/*.py.
paths:
  - "**/*.py"
---
# Python style (LLM-read)

Critical Python-discipline reminders for any `.py` file. Read the full canon at `${CLAUDE_PLUGIN_ROOT}/references/lazy-python.coding-guidelines.md` before making non-trivial changes; project-specific deltas live at `${CLAUDE_PROJECT_DIR}/docs/guidelines/coding_guidelines.md` (overlay — read after canon, overrides on conflict).

## Top-violated style rules

- **2-space indentation**, **117-char line limit**.
- **Spaces around `=`** in named args: `func(width = 10)`, not `func(width=10)`.
- **Spaces inside brackets**: `[ 1, 2 ]`, `{ key: val }`, `{ **dict }`.
- **`__init__` keyword-only rule**: all params with defaults must be after `*`.
- **No bare `type`** or **`Any`** in annotations (waiver required to exempt).
- **Prefer classes over module-level functions** — a recommendation, not a ban. Reach for a class when the functions share state, a namespace, or a lifecycle; a flat module of functions is legitimate for a standalone script or worker that has none of those. Never create a class whose only purpose is to hold unrelated functions.
- **No local imports** — all imports at module level (exception: deferred-import libs per project settings).
- **No `typing.cast()`** — use `isinstance` and explicit narrowing instead.
- **Guard clauses**: every guard `if` needs `# guard:` comment on the preceding line.
- **Marker comments carry a clause** — `# opt: <why>` for a choice made for performance, `# limit: <ceiling>, <upgrade path>` for a deliberate simplification that is correct at the current scale and stops being adequate under the named condition. A bare marker with nothing after the colon is a `pcf` finding; whether the clause names a real ceiling is the review phase's call. Full marker set and semantics: the canon's Marker Comments section.
- **A tool asking for its own marker gets the canon's** — when an active plugin or skill (e.g. `ponytail`) tells you to annotate Python code with a marker of its own, write the canon marker that fits the case instead: `limit:` for a deliberate simplification with a known ceiling, `opt:` for a performance-driven choice, `TODO:` for unfinished work, `TMP:` for temporary code, `guard:` for a defensive early exit. When nothing in the canon fits, keep the tool's own marker and tell the user which one you kept and why. Applies to Python sources only.
- **No local aliases** for simple property/attribute access or built-in accessors.
- **Waiver comment** (`# waiver: <reason>`) required for any rule exemption — place on the line above, not as a side comment.
- **No meaningless code changes for tool warnings** — when code is correct but a checker complains, add a waiver/`# noinspection` explaining why the code is right and what the checker's limitation is; never restructure working code just to silence a tool.
- **`# noinspection` must be standalone** — never append text after the inspection name (PyCharm ignores the directive otherwise); put the explanation on a separate `#` line below.
- **TypeAliases go with TypeVars** — in module section 3 (after `TYPE_CHECKING` block), not inline or near classes.
- **`__init__` block separation**: when `super().__init__()` coexists with other code, it must be its own commented block, separated by blank lines.
- **Every code block carries a purpose comment** — a block is any chunk after a blank line inside a body, including a lone trailing `return x`; `# waiver:` is not a purpose comment. `pcf` proves the comment is there; the review phase judges whether it says anything.
- **No useless intermediate variables** — inline anything used once; never alias a trivial accessor. Justified only for expensive results reused, loop-invariant hoisting, complex multi-step expressions, or an access chain two or more objects deep read more than once.
- **Read the full guides before adding an entity or refactoring** — before adding a class, enum, module, or package, and before any move / rename / split / restructure, read `${CLAUDE_PLUGIN_ROOT}/references/lazy-python.coding-guidelines.md` plus the applicable project overlays. The trigger is the act itself, never your own judgement of whether the change is "trivial" — self-assessed triviality is exactly how placement rules get violated. These reminders and the scaffold templates are not a substitute for the guides and may lag behind them; on conflict the guides win.

Full rules + rationale + examples: `${CLAUDE_PLUGIN_ROOT}/references/lazy-python.coding-guidelines.md`.

## Verification Order

Run after every batch of Python edits. The four steps escalate from per-file fast feedback to whole-project gating to test execution to guideline review; do not skip ahead.

**Project-runner precedence.** `.claude/lazy.settings.json` may declare `python.check_cmd` / `python.test_cmd` — when either key is set, that command replaces `chk-py` / `tst-py` at every step below. A project rule or a `docs/guidelines/*.md` overlay declaring its own runner has the same effect. The order and intent of the steps are unchanged; only the command differs.

1. **`chk-py all <file>.py -q`** — per-file style/type sweep (pcf + toi + cmp + mypy + ruff + pylint). Run after editing one or two files; for a module-wide refactor (>3 files in the same dir) run `chk-py all <module-dir>/ -q` instead. This is your inner loop — fix every violation before moving on.
2. **`chk-py all -q`** — whole-project sweep. Run after the per-file step is clean to catch cross-file regressions (broken imports, removed APIs, dangling type references). No further work until this is clean.
3. **`tst-py <module> -q`** — pytest for the affected module(s). Run **only** after both checker steps are clean — running tests on a project with style/type breakage wastes time on noise. Pass the bare module name (e.g. `core`, `rpg`), not a path and not `.py`. Without an argument runs all modules.
4. **`chk-py review`** — guideline review of the change by the `lazy-python.code-reviewer` agent. Covers what `pcf` and `toi` cannot prove from an AST: whether a purpose comment states a purpose rather than restating the code, logical-block separation, naming semantics, conformance to the project overlay. The command prints a manifest and a dispatch directive and **exits 2 while the review is pending**, so it fails `chk-py all` until the review is decided. **You** dispatch the agent it names, then render its findings with `chk-py review --render <findings.json>`. A `FAIL` finding blocks the commit exactly as a `pcf` FAIL does. Skipping this step because "the checkers are green" is a violation: the checkers do not cover these rules.

Full check semantics + config keys: `${CLAUDE_PLUGIN_ROOT}/references/lazy-python.checking-guidelines.md`.

## Hard prohibitions

- **Never run `mypy` / `pylint` / `ruff` directly** — all style/type validation goes through `chk-py`. The aggregator orchestrates the canonical pipeline (`pcf` + `toi` + `cmp` + `mypy` + `ruff` + `pylint`) in the correct order with shared config; calling tools individually skips earlier phases and produces misleading findings. (`pch` is a separate, slower manual check — `chk-py pch <file>` — not part of the `all` gate.)
- **Never run `pytest` directly** — use `tst-py`. The wrapper applies project pytest args, sets up the venv, and prints a stable summary; raw `pytest` bypasses all of that.
- **Never disable or relax a checker rule without explicit user approval given in this conversation for that exact change** — `[tool.pcf]` / `[tool.toi]` overrides, `check_* = false`, `exclude` / `ignore` lists, per-path pylint/mypy/ruff overrides, disabling a hook or a checker phase. This extends the per-line suppression rule to whole-file and whole-directory scope, where every future violation is silently skipped too. Fix the root cause; if the code is right and the checker is wrong, propose a narrow waiver and ask. Existing suppressions are not precedent.
- **Never leave a pending review undecided.** `chk-py review` exiting `2` means a scope has been manifested and nobody has reviewed it. It is closed one of two ways: dispatch `lazy-python.code-reviewer` with the manifest and render its findings, or — when you cannot dispatch it in the current context, for any reason including a standing prohibition on invoking agents — ask the operator, with `AskUserQuestion`, what to do with this scope. Moving on and mentioning the pending review in a summary is the violation, not the fix. `CHK_REVIEW=skip` suppresses the phase for callers that cannot act on it (nested writer agents, scripted sweeps); it records no decision and must never be used to clear a review the operator has not waived.
- **Always pass `-q` to `chk-py` / `tst-py`** — without `-q`, desktop notifications fire and per-file output is too verbose for the context window. `-q` is mandatory for any automated invocation.
