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

## Re-export shim de-duplication (automatic)

`tst-py <module>` scopes a run at the directory level (`pytest tests/<module>/`). In repositories that aggregate their suites through **re-export shims** — a `test_all.py` that star-imports every package, plus per-package shim files that re-export a package's own test classes — each test class is then collected **twice**: once through its own shim and once through the aggregator. Double collection doubles the reported test count and can produce false failures when the repeated instances share mutable state between runs.

The runner loads a small pytest plugin (`bin/_pytest_dedup.py`, injected via `-p _pytest_dedup`) that removes these duplicates automatically — no setting to enable, nothing in `lazy.settings.json`.

### How it works

- On `pytest_collection_modifyitems` the plugin builds a key for each item from the **collected class** — its defining module (`cls.__module__`), qualified name (`cls.__qualname__`), and the item name (`item.name`, which already carries any parametrization suffix) — never from the node id. A duplicate's node id differs (it is reached through a different shim file), but the class object is shared by reference across every shim, so its `__module__` / `__qualname__` always point at the module where the class is *defined* and both copies share one key. Tests written as module-level functions (no class) fall back to a function-based key (`function.__module__` / `function.__qualname__` / `item.name`).
- Keying on the **class**, not the test function, is essential: an inherited test method is a single function object shared by every subclass, so a function-based key would wrongly collapse distinct subclasses (e.g. `TestA(Base)` and `TestB(Base)` both inheriting `Base.test_x`) into one and drop all but the first. The collected class differs per subclass, so the class-based key keeps them apart.
- The first item collected for each key survives; every later duplicate is de-selected (`pytest_deselected` + removal from the item list). The surviving instance is the first in collection order, so run order stays stable and predictable.
- Items that are neither a class method nor a plain function (e.g. `DoctestItem`, which exposes no `cls` or `function`) are skipped and never de-duplicated.

### Seeing it in the output

When at least one duplicate is removed, the plugin prints one summary line:

```
[lazy-python] deduplicated N re-exported test items
```

In a repository **without** re-export shims no key ever repeats, so the plugin is a no-op: the collected-test count is unchanged and the summary line is not printed. Parametrized tests are never collapsed — different parameters yield different keys.

## Performance / property-based tests

- Use `hypothesis` for property-based testing when appropriate.
- Place performance tests under `tests/pf/` and run them on demand with `pytest tests/pf/<path>`.

## Project environment bootstrap (`python.env_source`)

Some projects must set up their environment before tests or checkers run — export a secret-store path, resolve provider credentials, extend `PYTHONPATH`. When that bootstrap lives in the project's own shell script, the plugin runners (`chk-py` / `tst-py`) source it automatically so pytest and the checkers see a fully-configured environment. Without it, a project whose tests read the environment (AI-provider clients, secret resolvers) runs half-configured — client constructors fail, provider tests error, and unrelated tests fail falsely.

### How to set it

Set `python.env_source` in the repo's `.claude/lazy.settings.json` to the bootstrap script's path, relative to the repo root:

```json
{
  "python": {
    "env_source": "cli/env"
  }
}
```

`lazy-python.install` records this automatically when the repo ships a recognised bootstrap script (`cli/env`, `.env.sh`, or `scripts/env.sh`) — and asks which to use when more than one is present. For any other path, or to add it later, set the key by hand: it is a plain string under a `python` section, and the runners pick it up on the next invocation.

### Semantics

- Resolved relative to the current working directory (the same cwd that scopes `tests/<module>/`), so run the runners from the repo root.
- Sourced **after** the venv is active and **before** pytest / the checker is exec'd, in the same shell — the script's `export`s are inherited by the checker / test process.
- Key absent, `null`, or empty → no bootstrap runs; behaviour is byte-identical to not setting it.
- Key set but the file is missing → the runner aborts non-zero, naming the key and the resolved path, rather than running in a half-configured environment. Fix the path or remove the key.

The script is a repo-declared file sourced into the runner's shell — the same trust boundary as running the repo's own tests and `conftest` code; it adds no new trust surface.
