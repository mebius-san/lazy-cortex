---
description: CLI tools, verification order, and formatter/type-checker/linter configurations for Python projects that adopt these conventions.
---
# Code Checking and QA Tools

CLI commands, tool configurations, and verification order
for Python projects that adopt these conventions.

## Toolchain

| Tool   | Purpose                                  | Invocation                |
|--------|------------------------------------------|---------------------------|
| ruff   | Fast linter + style enforcement          | `ruff check <path>`       |
| mypy   | Static type checking                     | `mypy <path>`             |
| pylint | Deep static analysis                     | `pylint <package>`        |
| pytest | Test runner                              | `pytest <tests-or-node>`  |
| py_compile | Fast syntax / bytecode-compile check | `python -m py_compile <files>` |

Run from the project root with the project venv active. Tool configuration lives in `pyproject.toml` under `[tool.ruff]`, `[tool.ruff.lint]`, `[tool.mypy]`, `[tool.pylint]`, and `[tool.pytest.ini_options]`.

## Verification order after changes (MANDATORY)

After making code changes, **always** verify in this exact order:

1. **Lint + type-check each changed file**:
   ```bash
   ruff check <file>.py
   mypy <file>.py
   pylint <file>.py
   ```
   If more than three files in the same module changed, target the module directory instead of one-by-one.
2. **Full-project lint + type-check** before declaring done:
   ```bash
   ruff check .
   mypy .
   pylint <top_level_packages>
   ```
3. **Tests**: run the relevant pytest selection only **after** all checks pass:
   ```bash
   pytest tests/<module>/
   # or, scoped:
   pytest tests/<module>/test_<file>.py::TestClass
   ```

Do not run tests before lint and type-check are clean — typing errors mask test failures and create wasted iteration.

## Ruff

- Fast linter written in Rust; covers most format rules plus a large slice of pylint / pyflakes / isort.
- Run during local edits and pre-commit; runs in the `all` check sequence before mypy / pylint because it is the fastest.
- Configuration lives under `[tool.ruff]` and `[tool.ruff.lint]` in `pyproject.toml`.
- Common invocation: `ruff check <path>`. Use `ruff check --fix <path>` to auto-apply safe fixes; review the diff before committing.

## MyPy

- Strict static type checking. Catches type-narrowing mistakes ruff/pylint miss.
- Configuration in `[tool.mypy]` in `pyproject.toml`.
- Common invocation: `mypy <path>`. The first run on a cold cache is slow; subsequent runs are fast.

## PyLint

- Deeper analysis than ruff (control-flow inspection, attribute-existence checks, doc / naming rules).
- Slower than ruff; run after ruff on the same path so trivial style errors are already gone.
- Configuration in `[tool.pylint]` in `pyproject.toml`.
- Common invocation: `pylint <package_or_module>` (pylint targets are packages or dotted module paths, not file paths).

## Py-compile

- Fast syntax / bytecode check via `python -m py_compile <files>`.
- Use when you want to confirm "this parses and compiles" without running the test suite or invoking heavy type-check tools.
- Does NOT perform type checking, style linting, or import availability validation.

## PyTest

- Run from the project root with the project venv active.
- Configuration in `[tool.pytest.ini_options]` in `pyproject.toml`.
- Common invocations:
  - All tests under a module:        `pytest tests/<module>/`
  - One test file:                   `pytest tests/<module>/test_<file>.py`
  - One test class:                  `pytest tests/<module>/test_<file>.py::TestClassName`
  - One test method:                 `pytest tests/<module>/test_<file>.py::TestClassName::test_method`
  - Keyword filter:                  `pytest -k <expression>`
  - Verbose / fail-fast:             `pytest -vv -x`
- Use `pytest --collect-only` to verify test discovery before running anything heavy.

## Performance / property-based tests

- Use `hypothesis` for property-based testing when appropriate.
- Place performance tests under `tests/pf/` and run them on demand with `pytest tests/pf/<path>`.
