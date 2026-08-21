---
chapter_type: walkthrough
summary: Install lazycortex-python, then run chk-py all -q directly to build the project venv and prove the six-step checker gate is clean.
last_regen: 2026-08-19
diagram_spec:
  anchor: "Install-and-first-check flow"
  request: "Sequence diagram: user runs /lazy-python.install (quiet install wizard, detail out of scope here) → user runs cli/chk-py all -q from a terminal → the shared venv resolver probes $VIRTUAL_ENV, then <project>/.venv, then a configured path, finds none, creates a project-local .venv and installs mypy/pylint/pytest/ruff plus the pytest-clarity/pytest-sugar plugins → the six-step gate runs in order: pcf, toi, cmp, mypy, ruff, pylint, each reporting clean on the still-untouched repo (the guideline-review phase is deliberately NOT part of this run — it has its own cadence) → user runs cli/tst-py -q to confirm the same venv's pytest works → pytest completes with no failures."
  kind_hint: sequence
source_skills:
  - lazy-python.install
  - chk
  - tst
  - pcf.py
source_sha: 7e55c7700a727bafa0a894c538571d86f4359c7b
---
# Bootstrap the plugin in a clean repo and confirm the checker stack is wired up

This walkthrough is for anyone enabling `lazycortex-python` in a repo for the first time and wanting proof — not just an install report — that the checker stack actually works: the project-local venv builds, and the aggregator wrappers run clean end to end.

## Outcome

After this walkthrough you have:

- The plugin installed — rule mirrors, `cli/chk-py` / `cli/tst-py` wrappers, bootstrapped `pyproject.toml` sections, and overlay stubs all in place (see the **install-and-audit** block article for the full wizard).
- A project-local `.venv` at the repo root with `mypy`, `pylint`, `pytest`, `ruff`, `pytest-clarity`, and `pytest-sugar` installed, built automatically the first time you invoke either wrapper.
- A completed `chk-py all -q` run reporting all six deterministic steps clean — `pcf`, `toi`, `cmp`, `mypy`, `ruff`, `pylint` — and a completed `tst-py -q` run confirming the same venv's pytest works.
- Confidence that the venv resolver and the six-step gate are correctly wired before you start relying on them for real edits.

## What you need

- `lazycortex-core` installed and enabled in Claude Code (this plugin layers on its runtime).
- `lazycortex-python@lazycortex` installed and enabled — `enabledPlugins` in your `~/.claude/settings.json`.
- Python 3.12+ reachable on `$PATH`, and `uv` on `$PATH` if you want the venv-bootstrap fallback to work (`brew install uv` on macOS).
- A terminal at the repo root — the wrappers run standalone once deployed, no Claude Code session required.

## The journey

### Step 1 — Install the plugin

```
/lazy-python.install
```

This is a quiet, mostly prompt-free install — the only two prompts it can ever raise are a genuine file-sync conflict and, when your repo ships more than one recognised environment-bootstrap script, a one-time choice of which one `python.env_source` should record. The full step-by-step breakdown — rule mirroring, wrapper deployment, the PyCharm `pch` probe, `pyproject.toml` bootstrapping, overlay scaffolding, scaffold-template sync, `env_source` detection, and the closing agent-model-tier and code-reviewer-expert registration — is covered in the **install-and-audit** block article, not here.

**Verification gate**: the install ends with a one-line-per-step report. Confirm every line shows an outcome word (`installed`, `wrappers-deployed-2 + gitignore-ensured`, `pyproject-bootstrapped + pch-skipped-no-pycharm`, etc.) with no `ERROR`. Once that report is clean, `./cli/chk-py` and `./cli/tst-py` exist at the repo root and are executable.

### Step 2 — Run the six-step gate and let it build the venv

From a plain terminal at the repo root:

```
./cli/chk-py all -q
```

`chk-py` is the rendered wrapper around the plugin's shared `chk` aggregator. `all` runs six deterministic checks in order — `pcf` (code format), `toi` (type-only imports), `cmp` (`py_compile` syntax check), `mypy`, `ruff`, and `pylint` — against `.` by default. Before the first check runs, the shared venv resolver probes for a usable venv in this order: an already-activated `$VIRTUAL_ENV`, an existing `<repo>/.venv`, then a `[tool.lazy-python] venv` path configured in `pyproject.toml`. On a freshly installed repo none of those exist yet, so the resolver falls back to creating `<repo>/.venv` with `uv venv --python 3.12` and installing `mypy`, `pylint`, `pytest`, `ruff`, `pytest-clarity`, and `pytest-sugar` into it — never wiping a pre-existing venv, only adding what's missing.

The guideline-review phase (`chk-py review`) is deliberately **not** part of this run. It used to be the seventh step of `all`, but it now runs on its own cadence — recommended at the end of a logical unit of work, mandatory at the end of a full cycle of planned work — so its fixed per-dispatch cost (the whole guideline canon, every time) is paid once per unit of work rather than once per `chk-py all` invocation. It is pure stdlib and skips the venv entirely, so it also works from pre-commit and CI. See "After you're done" below for how to run it.

**Verification gate**: expect this run to take roughly 30–60 seconds the first time (venv creation + package installs); every later run reuses the venv and is fast. The output prints `>>> [N/6] <step> - ...` for each of the six steps. On a clean tree you should see all six report success with no `ERROR`, no `py_compile errors detected`, and no violation lines. If any check reports findings, those are real issues against your existing code, not an install problem — work through them (or point `chk-py all -q <path>` at a single known-clean file first to confirm the plumbing) before treating the checker stack as verified.

### Step 3 — Confirm the shared venv also serves pytest

```
./cli/tst-py -q
```

`tst-py` sources the same venv the previous step built or reused — it never creates its own — then runs `pytest -q` across everything under `tests/`. Because Step 2 already installed `pytest` (plus the `pytest-clarity` and `pytest-sugar` plugins) into `<repo>/.venv`, this step should activate instantly with no new installs.

**Verification gate**: on a repo with no `tests/` directory yet, `pytest` reports no tests collected — that's expected and not a failure. On a repo with existing tests, confirm the run completes with `0 failed` (whatever the passed/skipped counts happen to be). Either outcome confirms the venv resolver and the pytest wiring both work; a hard error here (e.g. `pytest: command not found`) means the venv from Step 2 didn't build correctly and is worth re-running `chk-py all -q` to diagnose before moving on.

## After you're done

`chk-py all -q` is the routine gate to run before committing any real edit — it stays fast because it never touches the guideline-review phase. `tst-py -q` (or `tst-py <module> -q` to scope to one `tests/<module>/` directory) is the routine test pass once you have tests to run.

`chk-py review` is the separate guideline-review pass — run it at the end of a logical piece of work, and mandatorily at the end of a full cycle of planned work. It resolves its scope from the working-tree diff plus any untracked `.py` files (or `chk-py review --base <ref>` to widen the scope to everything since a given commit, so a unit of work with intermediate commits gets reviewed as a whole rather than just its tail), builds a manifest of every applicable guideline layer, and prints a dispatch directive naming the `lazy-python.code-reviewer` agent — it never calls an LLM itself, so it also works unattended from pre-commit and CI. A manifested-but-undecided review exits `2` (`PENDING`): dispatch the named agent against the printed manifest and render its findings with `chk-py review --render <findings.json>` to close it.

The venv you built in Step 2 persists at the repo root and is reused by every future `chk-py` / `tst-py` run — it's only rebuilt if you delete it, and re-running the resolver only adds missing tools, never removes anything. If you ever suspect the install itself has drifted (missing wrapper, stale rule mirror, broken venv resolution) rather than the checker findings themselves, `/lazy-python.audit` — covered in the install-and-audit block article — is the read-only diagnostic to reach for before re-running install.

## Install-and-first-check flow

```mermaid
%%{init: {'themeVariables':{'background':'transparent','primaryColor':'#1e3a5f','primaryBorderColor':'#4a90e2','primaryTextColor':'#fff','lineColor':'#4ae290','actorBkg':'#1e3a5f','actorBorder':'#4a90e2','actorTextColor':'#fff','actorLineColor':'#4a90e2','signalColor':'#4ae290','signalTextColor':'#000','noteBkgColor':'#5f4a1e','noteBorderColor':'#e2a14a','noteTextColor':'#fff','labelBoxBkgColor':'#5f4a1e','labelBoxBorderColor':'#e2a14a','labelTextColor':'#fff','loopTextColor':'#e2a14a'},'sequence':{'diagramPadding':5,'useMaxWidth':true}}}%%
sequenceDiagram
  participant user as User
  participant terminal as Terminal
  participant venvResolver as Venv Resolver
  participant gate as Seven-Step Gate
  participant pytest as Pytest

  user->>terminal: run /lazy-python.install
  Note over terminal: quiet 8-step wizard, detail out of scope
  user->>terminal: run cli/chk-py all -q
  terminal->>venvResolver: resolve shared venv
  venvResolver->>venvResolver: probe $VIRTUAL_ENV
  venvResolver->>venvResolver: probe project .venv
  venvResolver->>venvResolver: probe configured path
  venvResolver-->>terminal: no venv found
  venvResolver->>venvResolver: create project-local .venv
  venvResolver->>venvResolver: install mypy, pylint, pytest, ruff, pytest-clarity, pytest-sugar
  terminal->>gate: run seven-step gate in order
  loop pcf, toi, cmp, mypy, ruff, pylint
    gate-->>terminal: report clean
  end
  gate->>gate: resolve review scope from working-tree diff and untracked .py files
  alt nothing in scope
    gate-->>terminal: SKIPPED, exit 0
  else changes in scope
    gate-->>terminal: PENDING, exit 2, print manifest and dispatch directive for lazy-python.code-reviewer
  end
  user->>terminal: run cli/tst-py -q
  terminal->>pytest: run pytest against resolved venv
  pytest-->>terminal: no failures
```
