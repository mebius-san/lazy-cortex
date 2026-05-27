---
chapter_type: block
summary: The `chk-py` and `tst-py` CLI wrappers that gate every Python change — style, type-only imports, syntax, mypy, ruff, pylint, and pytest — backed by a shared venv resolver that works from any terminal.
last_regen: 2026-05-27
diagram_spec:
  anchor: "How the pieces connect"
  request: "Flow diagram showing chk-py and tst-py as entry points; chk-py fans out to six subcommands in the all gate (pcf, toi, cmp, mypy, rf, pylint) plus pch as a separate standalone subcommand outside the all gate; tst-py calls pytest; both wrappers source _ensure_venv.sh which probes four venv locations in order (VIRTUAL_ENV env var, project .venv, pyproject.toml config path, fallback create/augment project .venv); pcf is also invoked by the PostToolUse hook on every .py edit; all tools read pyproject.toml for configuration."
source_skills:
  - chk
  - tst
  - pcf.py
  - toi.py
  - pch.py
  - _ensure_venv.sh
---
# Python checkers

`chk-py` and `tst-py` are the two commands you use every day in a project that has lazycortex-python installed. `chk-py` runs the style and type pipeline — format rules, type-only import analysis, syntax checking, mypy, ruff, and pylint — against any path you point it at. `tst-py` runs pytest scoped to the module you name, or the whole `tests/` tree when you omit the argument. Both are thin wrappers in your project's `cli/` directory that delegate to the shipped `chk` and `tst` aggregators in the plugin; re-running `/lazy-python.install` refreshes the wrappers if the plugin updates.

Behind both commands sits `_ensure_venv.sh`, a shared venv resolver that finds mypy, pylint, pytest, and ruff wherever they live in your project — an activated venv, a project-local `.venv/`, a path in `pyproject.toml`, or a fallback that creates and augments `.venv/` in the repo root — without requiring any environment setup beyond a plain terminal.

## What's in this block

**`chk`** is the style and type aggregator wrapper. You call it as `chk-py <subcommand> [path ...]`. The `all` subcommand runs six checks in sequence — `pcf`, `toi`, `cmp`, `mypy`, `rf`, `pylint` — across every path you supply (defaulting to `.`). Each subcommand is also callable on its own, so `chk-py mypy src/` runs only mypy. The `-q` flag is accepted as a no-op for compatibility with the `lazy-python.style.md` verification-order mandate. `pch` is a separate standalone subcommand (`chk-py pch <file>`) that is NOT part of the `all` gate because it is slower and requires PyCharm to be installed.

**`pcf.py`** is the Python Code Format checker. It parses each `.py` file with the `ast` module and checks import block ordering (future → typing → stdlib → third-party → project → local → TYPE_CHECKING), blank-line rules between import blocks, required `from __future__ import annotations` and `if TYPE_CHECKING:` guards, docstring structure and banned phrases, line length, and code-level rules such as bare `assert` statements and magic literals. Configuration lives under `[tool.pcf]` in `pyproject.toml`; per-path overrides go in `[tool.pcf.overrides]`. `pcf.py` is also the tool the PostToolUse hook invokes on every `.py` edit — the hook passes the just-written file through `pcf.py` and surfaces any violations as `additionalContext` in the next turn so style errors appear inline rather than at commit time.

**`toi.py`** is the type-only import analyzer. It walks the AST and distinguishes names used at runtime from names used only in type annotations. For each import that is annotation-only, it emits a `file:line: note:` suggestion to move it into the `if TYPE_CHECKING:` block. This keeps the runtime import footprint lean and avoids circular-import problems caused by type-only dependencies. Configuration is under `[tool.toi]` in `pyproject.toml`.

**`pch.py`** is the PyCharm offline inspection runner. It locates `inspect.sh` (via `PYCHARM_HOME`, then known macOS paths), builds a sandbox config directory that symlinks your real PyCharm SDK and stubs while skipping exclusively-locked files, runs the inspection scoped to the path you supply, parses the XML results, filters them through `[tool.pch]` exclusions in `pyproject.toml`, and prints findings in the same `file:line: severity: description [inspection]` format as `pcf.py` and mypy. When PyCharm is not installed, the command prints a diagnostic and exits non-zero; no other check is affected. Because `pch` is slow and depends on an optional external IDE, it is invoked manually rather than being part of the `all` gate.

**`tst`** is the test runner aggregator wrapper. You call it as `tst-py [module]`. With no argument it runs `pytest -q tests/`; with a module name it runs `pytest -q tests/<module>/`. The `-q` flag is accepted as a no-op for compatibility. Pytest configuration lives under `[tool.pytest.ini_options]` in `pyproject.toml`.

**`_ensure_venv.sh`** is sourced by both `chk` and `tst` before invoking any tool. It tries four probes in order: (1) `$VIRTUAL_ENV` if it is set and contains mypy, pylint, pytest, ruff, pytest-clarity, and pytest-sugar; (2) `<project>/.venv/` if present and equipped with those tools; (3) the path in `[tool.lazy-python] venv` in `pyproject.toml`; (4) a fallback that creates or augments `.venv/` in the repo root using `uv`. The fallback never wipes an existing `.venv/` — if a project `.venv/` already exists but lacks the checker tools, `uv pip install` adds them in place without touching project dependencies. Once probe 4 creates `.venv/`, subsequent runs hit probe 2 and skip the fallback entirely.

## How they work together

`chk-py all` is the canonical gate you run before committing. It executes the six-step pipeline in order: `pcf` (import and format rules), `toi` (type-only import suggestions), `cmp` (`py_compile` syntax check), `mypy` (type checking), `rf` (ruff lint), `pylint` (semantic lint). Each step runs to completion before the next begins; if any step exits non-zero, the overall command exits non-zero.

`chk-py pch` is a separate, slower flow. Because PyCharm's offline inspection requires `inspect.sh` from a PyCharm installation and takes noticeably longer than the other checks, it is invoked on demand rather than as part of the `all` gate. Run it when you want the depth of PyCharm's cross-file and semantic analysis, particularly for inspections that mypy and pylint do not cover.

Both `chk-py` and `tst-py` source `_ensure_venv.sh` before doing anything else, so they always run against the same Python environment. The resolver's probe order means an activated shell venv takes priority, the project `.venv/` is second, a `pyproject.toml`-configured path is third, and the fallback bootstrap is last — making the commands safe to call from any terminal, CI runner, or Claude skill without pre-activating an environment.

The PostToolUse hook slots into this block at the `pcf` level: on every `.py` edit it runs `pcf.py` against the touched file (honoring the `[tool.pcf] exclude` list, so excluded paths are no-ops) and returns violations as `additionalContext`. This gives you format feedback inline after each write rather than only at the end of a session.

## Where this fits

The `install-and-audit` block is what puts `chk-py` and `tst-py` in your project's `cli/` directory. The install wizard also seeds the `[tool.pcf]`, `[tool.toi]`, `[tool.pch]`, and `[tool.ruff]` sections in `pyproject.toml` that these checkers read. The `discipline` block documents the rules and guidelines that `pcf.py` enforces and that the writer agents consult when generating or reviewing code.

## Common adjustments

**Excluding directories from pcf or toi.** Add paths to the `exclude` list under `[tool.pcf]` or `[tool.toi]` in `pyproject.toml`. The install wizard seeds these sections with defaults (`.venv`, `.claude`, `tests`, `~archive`, `~sandbox`); extend them for project-specific generated directories. When you explicitly target a directory that is normally excluded — `chk-py pcf tests/` — `pcf.py` drops that directory's exclusion entry so the scan runs as requested.

**Per-path pcf overrides.** Add entries to `[tool.pcf.overrides]` for subdirectories that need relaxed rules, for example `"tools" = { check_magic_literal = false }` or `"tests" = { check_assert = false }`. The last matching prefix wins.

**Banned docstring phrases.** The `banned_docstring_phrases` list under `[tool.pcf]` rejects any phrase appearing anywhere in a docstring body. Add project-specific phrases to the list directly in `pyproject.toml`.

**Ignoring PyCharm inspections.** Add inspection names to the `ignore` list under `[tool.pch]` in `pyproject.toml` to suppress noisy inspections such as `"Spelling"`, `"Grammar"`, or `"Duplicated code fragment"`.

**Pointing to a specific venv.** Set `[tool.lazy-python] venv = "<path>"` in `pyproject.toml` to use a venv that is not at `.venv/` and not activated in the shell. Tilde expansion and relative paths (resolved against the project root) are both supported.

**Disabling the fallback bootstrap.** Set `[tool.lazy-python] bootstrap-fallback = false` in `pyproject.toml` when you want `chk-py` and `tst-py` to fail loudly rather than create a `.venv/` automatically. Useful in CI where the project venv is always pre-activated.

## How the pieces connect
