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
- **No module-level functions** — code lives on classes; module-level is for constants, imports, and class definitions only.
- **No local imports** — all imports at module level (exception: deferred-import libs per project settings).
- **No `typing.cast()`** — use `isinstance` and explicit narrowing instead.
- **Guard clauses**: every guard `if` needs `# guard:` comment on the preceding line.
- **No local aliases** for simple property/attribute access or built-in accessors.
- **Waiver comment** (`# waiver: <reason>`) required for any rule exemption — place on the line above, not as a side comment.
- **No meaningless code changes for tool warnings** — when code is correct but a checker complains, add a waiver/`# noinspection` explaining why the code is right and what the checker's limitation is; never restructure working code just to silence a tool.
- **`# noinspection` must be standalone** — never append text after the inspection name (PyCharm ignores the directive otherwise); put the explanation on a separate `#` line below.
- **TypeAliases go with TypeVars** — in module section 3 (after `TYPE_CHECKING` block), not inline or near classes.
- **`__init__` block separation**: when `super().__init__()` coexists with other code, it must be its own commented block, separated by blank lines.

Full rules + rationale + examples: `${CLAUDE_PLUGIN_ROOT}/references/lazy-python.coding-guidelines.md`.

## Verification Order

Run after every batch of Python edits. The three steps escalate from per-file fast feedback to whole-project gating to test execution; do not skip ahead.

1. **`chk-py all <file>.py -q`** — per-file style/type sweep (pcf + toi + cmp + mypy + ruff + pylint). Run after editing one or two files; for a module-wide refactor (>3 files in the same dir) run `chk-py all <module-dir>/ -q` instead. This is your inner loop — fix every violation before moving on.
2. **`chk-py all -q`** — whole-project sweep. Run after the per-file step is clean to catch cross-file regressions (broken imports, removed APIs, dangling type references). No further work until this is clean.
3. **`tst-py <module> -q`** — pytest for the affected module(s). Run **only** after both checker steps are clean — running tests on a project with style/type breakage wastes time on noise. Pass the bare module name (e.g. `core`, `rpg`), not a path and not `.py`. Without an argument runs all modules.

Full check semantics + config keys: `${CLAUDE_PLUGIN_ROOT}/references/lazy-python.checking-guidelines.md`.

## Hard prohibitions

- **Never run `mypy` / `pylint` / `ruff` directly** — all style/type validation goes through `chk-py`. The aggregator orchestrates the canonical pipeline (`pcf` + `toi` + `cmp` + `mypy` + `ruff` + `pylint`) in the correct order with shared config; calling tools individually skips earlier phases and produces misleading findings. (`pch` is a separate, slower manual check — `chk-py pch <file>` — not part of the `all` gate.)
- **Never run `pytest` directly** — use `tst-py`. The wrapper applies project pytest args, sets up the venv, and prints a stable summary; raw `pytest` bypasses all of that.
- **Always pass `-q` to `chk-py` / `tst-py`** — without `-q`, desktop notifications fire and per-file output is too verbose for the context window. `-q` is mandatory for any automated invocation.
