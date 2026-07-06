---
chapter_type: block
summary: The `chk-py` and `tst-py` CLI wrappers that gate every Python change — style, type-only imports, syntax, mypy, ruff, pylint, and pytest — backed by a shared venv resolver that works from any terminal.
last_regen: 2026-07-06
diagram_spec:
  anchor: "How the pieces connect"
  request: "Flow diagram showing chk-py and tst-py as entry points; chk-py fans out to six subcommands in the all gate (pcf, toi, cmp, mypy, rf, pylint) plus pch as a separate standalone subcommand outside the all gate; tst-py calls pytest; both wrappers source _ensure_venv.sh which probes four venv locations in order (VIRTUAL_ENV env var, project .venv, pyproject.toml config path, fallback create/augment project .venv), then source _ensure_env.sh which optionally sources a repo-declared env-bootstrap script named by python.env_source; pcf is also invoked by the PostToolUse hook on every .py edit; all tools read pyproject.toml for configuration."
source_skills:
  - chk
  - tst
  - pcf.py
  - toi.py
  - pch.py
  - _ensure_venv.sh
  - _ensure_env.sh
---
# Python checkers

`chk-py` and `tst-py` are the two commands you use every day in a project that has lazycortex-python installed. `chk-py` runs the style and type pipeline — format rules, type-only import analysis, syntax checking, mypy, ruff, and pylint — against any path you point it at. `tst-py` runs pytest scoped to the module you name, or the whole `tests/` tree when you omit the argument. Both are thin wrappers in your project's `cli/` directory; they resolve the active lazycortex-python plugin at exec time rather than delegating to a path frozen at install time, so they keep working across plugin version updates without needing to be re-deployed. If a wrapper ever cannot find the plugin it prints a clear error directing you to re-run `/lazy-python.install`.

Behind both commands sits `_ensure_venv.sh`, a shared venv resolver that finds mypy, pylint, pytest, and ruff wherever they live in your project — an activated venv, a project-local `.venv/`, a path in `pyproject.toml`, or a fallback that creates and augments `.venv/` in the repo root — without requiring any environment setup beyond a plain terminal. Right after the venv is active, both wrappers also source `_ensure_env.sh`, an optional hook that loads your project's own environment-bootstrap script when one is on record, so checks and tests run with the same secrets/config your project normally needs.

## What's in this block

**`chk`** is the style and type aggregator wrapper. You call it as `chk-py <subcommand> [path ...]`. The `all` subcommand runs six checks in sequence — `pcf`, `toi`, `cmp`, `mypy`, `rf`, `pylint` — across every path you supply (defaulting to `.`). Each subcommand is also callable on its own, so `chk-py mypy src/` runs only mypy. The `-q` flag is accepted as a no-op for compatibility with the `lazy-python.style.md` verification-order mandate. `pch` is a separate standalone subcommand (`chk-py pch <file>`) that is NOT part of the `all` gate; it is also opt-in per repo via a `[tool.pch]` section in `pyproject.toml` — when that section is absent, `chk-py pch` prints a diagnostic and exits cleanly without affecting any other check.

**`pcf.py`** is the Python Code Format checker. It parses each `.py` file with the `ast` module and checks import block ordering (future → typing → stdlib → third-party → project → local → TYPE_CHECKING), blank-line rules between import blocks, required `from __future__ import annotations` and `if TYPE_CHECKING:` guards, docstring structure and banned phrases, line length, and code-level rules such as bare `assert` statements and magic literals. Configuration lives under `[tool.pcf]` in `pyproject.toml`; per-path overrides go in `[tool.pcf.overrides]`. `pcf.py` is also the tool the PostToolUse hook invokes on every `.py` edit — the hook passes the just-written file through `pcf.py` and surfaces any violations as `additionalContext` in the next turn so style errors appear inline rather than at commit time.

**`toi.py`** is the type-only import analyzer. It walks the AST and distinguishes names used at runtime from names used only in type annotations. For each import that is annotation-only, it emits a `file:line: note:` suggestion to move it into the `if TYPE_CHECKING:` block. This keeps the runtime import footprint lean and avoids circular-import problems caused by type-only dependencies. Configuration is under `[tool.toi]` in `pyproject.toml`.

**`pch.py`** is the PyCharm offline inspection runner. It is opt-in per repo: `chk-py pch` only runs when `[tool.pch]` is present in `pyproject.toml`; without that section it prints a skip diagnostic and exits zero. When enabled, it locates `inspect.sh` (via `PYCHARM_HOME`, then known macOS paths), builds a sandbox config directory that symlinks your real PyCharm SDK and stubs while skipping exclusively-locked files, runs the inspection scoped to the path you supply, parses the XML results, filters them through `[tool.pch]` exclusions in `pyproject.toml`, and prints findings in the same `file:line: severity: description [inspection]` format as `pcf.py` and mypy. When PyCharm is not installed, the command prints a diagnostic and exits non-zero. Because `pch` is slow and depends on an optional external IDE, it is invoked manually rather than being part of the `all` gate. The install adds `[tool.pch]` to `pyproject.toml` automatically when PyCharm is present on the machine (and omits it otherwise — no prompt); if you install PyCharm later, add the section by hand to enable `pch` for the repo.

**`tst`** is the test runner aggregator wrapper. You call it as `tst-py [module]`. With no argument it runs `pytest -q tests/`; with a module name it runs `pytest -q tests/<module>/`. The `-q` flag is accepted as a no-op for compatibility. Pytest configuration lives under `[tool.pytest.ini_options]` in `pyproject.toml`.

**`_ensure_venv.sh`** is sourced by both `chk` and `tst` before invoking any tool. It resolves the project root via `git rev-parse --show-toplevel` (falling back to `$PWD` when git is unavailable), then tries four probes in order: (1) `$VIRTUAL_ENV` if it is set and contains mypy, pylint, pytest, ruff, pytest-clarity, and pytest-sugar; (2) `<project>/.venv/` if present and equipped with those tools; (3) the path in `[tool.lazy-python] venv` in `pyproject.toml`; (4) a fallback that creates or augments `.venv/` in the repo root using `uv`. The fallback never wipes an existing `.venv/` — if a project `.venv/` already exists but lacks the checker tools, `uv pip install` adds them in place without touching project dependencies. Once probe 4 creates `.venv/`, subsequent runs hit probe 2 and skip the fallback entirely. Using the git-derived root means the fallback always places `.venv/` at the repo root, even when you run `chk-py` from a subdirectory.

**`_ensure_env.sh`** runs immediately after `_ensure_venv.sh`, in the same shell, so any exports it makes are visible to the checker or pytest process that runs next. It looks up `python.env_source` in `<cwd>/.claude/lazy.settings.json`: if the key is absent, it is a silent no-op — behavior is byte-identical to a project with no env hook. If the key is set and the named script exists, it sources that script, so whatever your project's own bootstrap does (secret-path exports, provider credentials, and the like) is in place before the checker or pytest process starts. If the key is set but the resolved file is missing, `chk-py` / `tst-py` abort with a message naming the key and the resolved path — the tools refuse to run checks or tests in a half-configured environment. `/lazy-python.install` records `python.env_source` automatically when it recognises a bootstrap script in your repo (`cli/env`, `.env.sh`, or `scripts/env.sh`); if more than one candidate is present it asks you to pick one during install, and it never overwrites a value already on record.

## How they work together

`chk-py all` is the canonical gate you run before committing. It executes the six-step pipeline in order: `pcf` (import and format rules), `toi` (type-only import suggestions), `cmp` (`py_compile` syntax check), `mypy` (type checking), `rf` (ruff lint), `pylint` (semantic lint). Each step runs to completion before the next begins; if any step exits non-zero, the overall command exits non-zero.

`chk-py pch` is a separate, slower flow. Because PyCharm's offline inspection requires `inspect.sh` from a PyCharm installation and takes noticeably longer than the other checks, it is invoked on demand rather than as part of the `all` gate. It also requires an explicit `[tool.pch]` section in `pyproject.toml` to activate for your repo — without it the command skips cleanly. Run it when you want the depth of PyCharm's cross-file and semantic analysis, particularly for inspections that mypy and pylint do not cover.

Both `chk-py` and `tst-py` source `_ensure_venv.sh` before doing anything else, so they always run against the same Python environment. The resolver's probe order means an activated shell venv takes priority, the project `.venv/` is second, a `pyproject.toml`-configured path is third, and the fallback bootstrap is last — making the commands safe to call from any terminal, CI runner, or Claude skill without pre-activating an environment. Right after the venv resolves, both wrappers source `_ensure_env.sh` in the same shell — so if your project records `python.env_source`, every checker subcommand and every pytest run picks up that environment automatically, with no extra flag or manual sourcing on your part.

The PostToolUse hook slots into this block at the `pcf` level: on every `.py` edit it runs `pcf.py` against the touched file (honoring the `[tool.pcf] exclude` list, so excluded paths are no-ops) and returns violations as `additionalContext`. This gives you format feedback inline after each write rather than only at the end of a session.

## Where this fits

The `install-and-audit` block is what puts `chk-py` and `tst-py` in your project's `cli/` directory. The wrappers are self-resolving: each time you run one, it locates the active lazycortex-python install (checking the dev source tree first, then the daemon-provided plugin-dirs env, then the Claude Code plugin manifest) rather than delegating to a path frozen at install time. This means the wrappers keep working across plugin version updates — the versioned cache dir changes on every `/plugin update`, but the wrapper finds the new location automatically. If the wrapper cannot locate the plugin — for example after an unusual cache clear — it prints `chk-py: cannot locate the lazycortex-python plugin` and directs you to re-run `/lazy-python.install`. The install also seeds the `[tool.pcf]`, `[tool.toi]`, and `[tool.ruff]` sections in `pyproject.toml` that these checkers read (plus `[tool.pch]` when PyCharm is present on the machine), and it is the same install step that records `python.env_source` when your repo ships an environment-bootstrap script. The `discipline` block documents the rules and guidelines that `pcf.py` enforces and that the writer agents consult when generating or reviewing code.

## Common adjustments

**Excluding directories from pcf or toi.** Add paths to the `exclude` list under `[tool.pcf]` or `[tool.toi]` in `pyproject.toml`. The install wizard seeds these sections with defaults (`.venv`, `.claude`, `tests`, `~archive`, `~sandbox`); extend them for project-specific generated directories. When you explicitly target a directory that is normally excluded — `chk-py pcf tests/` — `pcf.py` drops that directory's exclusion entry so the scan runs as requested.

**Per-path pcf overrides.** Add entries to `[tool.pcf.overrides]` for subdirectories that need relaxed rules, for example `"tools" = { check_magic_literal = false }` or `"tests" = { check_assert = false }`. The last matching prefix wins.

**Banned docstring phrases.** The `banned_docstring_phrases` list under `[tool.pcf]` rejects any phrase appearing anywhere in a docstring body. Add project-specific phrases to the list directly in `pyproject.toml`.

**Enabling PyCharm inspections.** Ask the install wizard to add `[tool.pch]` during `/lazy-python.install`, or add the section to `pyproject.toml` manually. To suppress noisy inspections such as `"Spelling"`, `"Grammar"`, or `"Duplicated code fragment"`, add their names to the `ignore` list under `[tool.pch]`.

**Pointing to a specific venv.** Set `[tool.lazy-python] venv = "<path>"` in `pyproject.toml` to use a venv that is not at `.venv/` and not activated in the shell. Tilde expansion and relative paths (resolved against the project root) are both supported.

**Disabling the fallback bootstrap.** Set `[tool.lazy-python] bootstrap-fallback = false` in `pyproject.toml` when you want `chk-py` and `tst-py` to fail loudly rather than create a `.venv/` automatically. Useful in CI where the project venv is always pre-activated.

**Bootstrapping a repo-specific environment for checks and tests.** If your repo has its own environment script (`cli/env`, `.env.sh`, or `scripts/env.sh`) that exports secret paths or provider credentials, re-run `/lazy-python.install` — it detects the script and records it as `python.env_source`, so `chk-py` and `tst-py` source it automatically on every run. If more than one candidate script is present, the install skill asks you which one to use.

## How the pieces connect
