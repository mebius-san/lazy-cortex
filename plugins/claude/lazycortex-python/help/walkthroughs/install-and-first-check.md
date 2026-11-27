---
chapter_type: walkthrough
summary: Install lazycortex-python, let the install bring the project venv up to date, then run chk-py all -q and tst-py -q to prove the checker stack is clean.
last_regen: 2026-11-27
diagram_spec:
  anchor: "Install-and-first-check flow"
  request: "Sequence diagram: user runs /lazy-python.install (quiet install wizard, detail out of scope here); its last step creates or updates the project-local .venv from pyproject.toml with mypy/pylint/pytest/ruff plus pytest-clarity/pytest-sugar/pytest-xdist → user runs cli/chk-py all -q from a terminal → the shared venv resolver probes $VIRTUAL_ENV, then the target venv ([tool.lazy-python] venv or <repo>/.venv), finds it fresh and activates it (it would configure a missing or stale one itself unless protected mode or bootstrap-fallback = false forbids it) → the six-step gate runs in order: pcf, toi, cmp, mypy, rf (ruff), pylint, each reporting clean on the still-untouched repo (the guideline-review phase is deliberately NOT part of this run — it has its own cadence) → user runs cli/tst-py -q to confirm the same venv's pytest works → pytest completes with no failures."
  kind_hint: sequence
source_skills:
  - lazy-python.install
  - chk
  - tst
  - pcf.py
source_sha: 0044ac4308cce96cc832c6dbbbe2042b5ad738d5
surface_sha: 41a6ab6e495989683fab3e3b566f5504d289e820401e6a0ec0811c34a8a801ec
---
# Bootstrap the plugin in a clean repo and confirm the checker stack is wired up

This walkthrough is for anyone enabling `lazycortex-python` in a repo for the first time and wanting proof — not just an install report — that the checker stack actually works: the project-local venv is ready, and the aggregator wrappers run clean end to end.

## Outcome

After this walkthrough you have:

- The plugin installed — the four rule mirrors in `.claude/rules/` (style, docstrings, tests, and failing-tests, which tells Claude to judge a failing test before touching either side and never to edit or exclude a test without your explicit yes), `cli/cfg-py` / `cli/chk-py` / `cli/tst-py` wrappers plus the plugin locator they run (`cli/lazy_python_locator.py`) and the mypy plugin shim at `cli/mypy/protected_access.py` (no exec bit required — the wrappers launch through `bash`), matching human-facing `~/.local/bin/cfg-py` / `chk-py` / `tst-py` copies, bootstrapped `pyproject.toml` sections, and overlay stubs under `docs/guidelines/python/` all in place (see the **install-and-audit** block article for the full wizard).
- A project-local `.venv` at the repo root (or at the path your `pyproject.toml` names under `[tool.lazy-python] venv`), configured from your `pyproject.toml`: an interpreter that satisfies `requires-python` (or `.python-version`), your project dependencies, extras and dependency groups, plus the checker tools `mypy`, `pylint`, `pytest`, `ruff`, `pytest-clarity`, `pytest-sugar`, and `pytest-xdist`. The install brings it up to date as its closing step; later it is also configured automatically by `chk-py` or `tst-py` whenever it is missing or stale, or on demand with `cfg-py`.
- A completed `chk-py all -q` run reporting all six deterministic steps clean — `pcf`, `toi`, `cmp`, `mypy`, `rf` (ruff), `pylint` — and a completed `tst-py -q` run confirming the same venv's pytest works.
- Confidence that the venv resolver and the six-step gate are correctly wired before you start relying on them for real edits.

## What you need

- `lazycortex-core` installed and enabled in Claude Code (this plugin layers on its runtime).
- `lazycortex-python@lazycortex` installed and enabled — `enabledPlugins` in your `~/.claude/settings.json`.
- Python 3.12+ reachable on `$PATH`, and `uv` on `$PATH` so the project venv can be created or updated (`brew install uv` on macOS).
- A terminal at the repo root — the wrappers run standalone once deployed, no Claude Code session required.

## The journey

### Step 1 — Install the plugin

```
/lazy-python.install
```

This is a quiet, mostly prompt-free install — the only two prompts it can ever raise are a genuine file-sync conflict and, when your repo ships more than one recognised environment-bootstrap script, a one-time choice of which one `python.env_source` should record. The full step-by-step breakdown — rule mirroring, wrapper and mypy-shim deployment, the `~/.local/bin/cfg-py` / `chk-py` / `tst-py` human-facing copies, the PyCharm `pch` probe, `pyproject.toml` bootstrapping, overlay scaffolding under `docs/guidelines/python/`, scaffold-template sync, `env_source` detection, agent-model-tier and code-reviewer-expert registration, the step that lists an in-checkout project venv among the links every isolated job worktree carries, and the closing step that brings the project venv up to date — is covered in the **install-and-audit** block article, not here. If your repo kept overlay guidelines at the older `docs/guidelines/<topic>_guidelines.md` location, `/lazy-core.setup` runs the plugin's migration that moves them into `docs/guidelines/python/`; the install itself never moves them.

**Verification gate**: the install ends with a one-line-per-step report. Confirm every line shows an outcome word (`installed`, `wrappers-deployed-4 + gitignore-ensured`, `pyproject-bootstrapped + pch-skipped-no-pycharm`, etc.) with no `ERROR`. Once that report is clean, `cli/cfg-py`, `cli/chk-py` and `cli/tst-py` exist at the repo root — run through `bash`, no exec bit needed, so a mode-blind sync client can never break them — and `~/.local/bin/cfg-py` / `chk-py` / `tst-py` are installed alongside them, so a bare `cfg-py` / `chk-py` / `tst-py` works from anywhere under the repo once `~/.local/bin` is on your `$PATH` (the install report calls out a `path-warning` if it isn't). The install also makes sure `.venv/` is listed in your `.gitignore`, so the project venv never lands in a commit. The final step reports the venv as `venv-fresh` (already up to date), `venv-configured` (created or updated now) or `venv-refresh-failed` (for example no `uv` on `$PATH`; the report carries the tool's output, so fix what it names and re-run the install or `cfg-py`), followed by a `daemon-venv-<state>` line for the checkout this host's daemon runs in. The closing worktree step reports one of `worktree-link-added`, `worktree-link-already-present`, `worktree-link-not-needed` (the venv lives at an absolute path outside the checkout), `worktree-link-unreachable` (a relative `[tool.lazy-python] venv` that climbs out of the checkout; the fix is an absolute path there) or `worktree-link-failed` (`pyproject.toml` does not parse; fix it and re-run). The link matters once expert jobs run in isolated git worktrees: a gitignored `.venv/` is not in a fresh worktree, so without the link `chk-py` and `tst-py` would break inside the job. If the `pyproject.toml` step could not make a safe edit on its own (for example, a section without a header line of its own), the report ends that line with `+manual-edit` and prints what to change by hand — apply it yourself, because the install never forces such an edit.

### Step 2 — Run the six-step gate and let it build the venv

From a plain terminal at the repo root:

```
bash ./cli/chk-py all -q
```

`chk-py` is the rendered wrapper around the plugin's shared `chk` aggregator, launched through `bash` — the tracked copy carries no exec bit on purpose, so it keeps working even after a git client that resets file modes to `100644`. If `~/.local/bin` is on your `$PATH` (Step 1's install put the human-facing copy there), the same run is just `chk-py all -q` typed from anywhere under the repo. `all` runs six deterministic checks in order — `pcf` (code format; pytest test files are exempt from its assert and magic-literal checks by default, and a `# waiver:` comment is honoured), `toi` (type-only imports), `cmp` (`py_compile` syntax check), `mypy`, `rf` (ruff), and `pylint` — against `.` by default. Run from a subdirectory, the wrapper still resolves the repo root, so the venv is never created in the wrong folder. Before the first check runs, the shared venv resolver looks for a usable venv in this order: an already-activated `$VIRTUAL_ENV` that carries the checker tools (used as is — nothing is installed into it; one that lacks a tool is passed over with a one-line note naming it), then the target venv — the `[tool.lazy-python] venv` path from `pyproject.toml` when set, otherwise `<repo>/.venv`. The target venv counts as ready only when it carries the checker tools and its configuration stamp still matches your `pyproject.toml` requirements; editing an unrelated section such as `[tool.ruff]` does not make it stale. After a clean install the venv is already fresh, so the resolver simply activates it and the first check starts at once. If it went missing or stale in the meantime, the resolver configures it from `pyproject.toml`: `uv` picks an interpreter that satisfies `requires-python` / `.python-version`, then installs your project dependencies, every extra and dependency group, and the checker tools `mypy`, `pylint`, `pytest`, `ruff`, `pytest-clarity`, `pytest-sugar`, and `pytest-xdist` — recreating the venv if its interpreter no longer satisfies the project's Python requirement, otherwise updating it in place.

The automatic configure has two opt-outs. In protected mode (`LAZYCORTEX_PROTECTED` set) nothing is installed: a missing or stale venv stops the run with a message naming the cause and asking you to run `/lazy-python.install` or `cfg-py` from an interactive session. With `bootstrap-fallback = false` under `[tool.lazy-python]` the run also stops and points you at `cfg-py`. Either way, `bash ./cli/cfg-py` creates or updates the venv on request, without running any check; `bash ./cli/cfg-py --if-stale` leaves a fresh venv untouched and prints `fresh`, otherwise configures it and prints `configured`.

The guideline-review phase (`chk-py review`) is deliberately **not** part of this run. It used to be the seventh step of `all`, but it now runs on its own cadence — recommended at the end of a logical unit of work, mandatory at the end of a full cycle of planned work — so its fixed per-dispatch cost (the whole guideline canon, every time) is paid once per unit of work rather than once per `chk-py all` invocation. It is pure stdlib and skips the venv entirely, so it also works from pre-commit and CI. See "After you're done" below for how to run it.

**Verification gate**: expect the run to start immediately, because the install already built the venv; only if the venv had to be configured here does the first run take longer (venv creation plus installing your project's dependencies and the checker tools), and every later run reuses it. The output prints `>>> [N/6] <step> - ...` for each of the six steps. On a clean tree you should see all six report success with no `ERROR`, no `py_compile errors detected`, and no violation lines. If any check reports findings, those are real issues against your existing code, not an install problem — work through them (or point `bash ./cli/chk-py all -q <path>` at a single known-clean file first to confirm the plumbing) before treating the checker stack as verified.

### Step 3 — Confirm the shared venv also serves pytest

```
bash ./cli/tst-py -q
```

`tst-py` uses the same venv resolver as `chk-py`, so it activates the venv the previous step reused (and would configure it the same way if it were missing or stale), then runs `pytest -q` across everything under `tests/` (a bare `tst-py` and `tst-py all` are the same whole-suite run; `tst-py <module>` scopes to `tests/<module>/`). It also loads a small dedup plugin so a test collected twice through re-export shims runs only once, and a CPU-yield plugin that lowers the test run's priority so the machine stays responsive. Because `pytest` (plus the `pytest-clarity`, `pytest-sugar` and `pytest-xdist` plugins) is already in the project venv, this step should activate instantly with no new installs. Same as Step 2, a bare `tst-py -q` works instead once `~/.local/bin` is on your `$PATH`.

**Verification gate**: on a repo with no `tests/` directory yet, `tst-py` refuses up front with a "does not exist" message instead of handing pytest a missing path — that is expected on a fresh repo and not a venv problem; create a `tests/` directory (or add your first test) and re-run. The same refusal fires for `tst-py <module>` when `tests/<module>/` is missing, and it lists the modules that do exist. On a repo with existing tests, confirm the run completes with `0 failed` (whatever the passed/skipped counts happen to be). Either outcome confirms the venv resolver and the pytest wiring both work. If a test does fail on a repo with existing tests, the failing-tests rule installed in Step 1 applies: the failure is judged first, and no test is edited or excluded from the run without your explicit yes. A hard error here (e.g. `pytest: command not found`) means the project venv didn't build correctly; run `bash ./cli/cfg-py` to rebuild it and re-run `bash ./cli/chk-py all -q` to diagnose before moving on.

## After you're done

`bash ./cli/chk-py all -q` (or bare `chk-py all -q` once `~/.local/bin` is on `$PATH`) is the routine gate to run before committing any real edit — it stays fast because it never touches the guideline-review phase. `bash ./cli/tst-py -q` (or `tst-py <module> -q` to scope to one `tests/<module>/` directory) is the routine test pass once you have tests to run.

`chk-py review` is the separate guideline-review pass — run it at the end of a logical piece of work, and mandatorily at the end of a full cycle of planned work. It resolves its scope from the working-tree diff plus any untracked `.py` files (or `chk-py review --base <ref>` to widen the scope to everything since a given commit, so a unit of work with intermediate commits gets reviewed as a whole rather than just its tail), builds a manifest of every applicable guideline layer, and prints a dispatch directive naming the `lazy-python.code-reviewer` agent — by default it calls no LLM itself, so it also works unattended from pre-commit and CI. A manifested-but-undecided review exits `2` (`PENDING`): dispatch the named agent against the printed manifest and render its findings with `chk-py review --render <findings.json>` to close it.

The project venv persists at the repo root and is reused by every future `chk-py` / `tst-py` run — it is reconfigured only when it goes missing or stale — after you change the dependencies, extras, dependency groups, or Python requirement in `pyproject.toml` — and `bash ./cli/cfg-py` reconfigures it on demand. If you ever suspect the install itself has drifted (missing wrapper, stale rule mirror, broken venv resolution) rather than the checker findings themselves, `/lazy-python.audit` — covered in the install-and-audit block article — is the read-only diagnostic to reach for before re-running install. Among its checks, one warns when an isolated job worktree would run without the venv link; the repair is a re-run of `/lazy-python.install`, which records the link.

## Install-and-first-check flow

```mermaid
%%{init: {'themeVariables':{'background':'transparent','primaryColor':'#1e3a5f','primaryBorderColor':'#4a90e2','primaryTextColor':'#fff','lineColor':'#4ae290','actorBkg':'#1e3a5f','actorBorder':'#4a90e2','actorTextColor':'#fff','actorLineColor':'#4a90e2','signalColor':'#4ae290','signalTextColor':'#000','noteBkgColor':'#5f4a1e','noteBorderColor':'#e2a14a','noteTextColor':'#fff','labelBoxBkgColor':'#5f4a1e','labelBoxBorderColor':'#e2a14a','labelTextColor':'#fff','loopTextColor':'#e2a14a'},'sequence':{'diagramPadding':5,'useMaxWidth':true}}}%%
sequenceDiagram
  participant user as User
  participant installWizard as /lazy-python.install
  participant chkPy as cli/chk-py
  participant venvResolver as Shared venv resolver
  participant gate as Six-step gate
  participant tstPy as cli/tst-py

  user->>installWizard: run /lazy-python.install (quiet wizard)
  Note over installWizard: Wizard detail is out of scope here
  installWizard->>installWizard: last step creates or updates project-local .venv from pyproject.toml
  Note over installWizard: mypy, pylint, pytest, ruff plus pytest-clarity, pytest-sugar, pytest-xdist
  installWizard-->>user: install done

  user->>chkPy: run cli/chk-py all -q from a terminal
  chkPy->>venvResolver: resolve venv
  venvResolver->>venvResolver: probe $VIRTUAL_ENV, then target venv ([tool.lazy-python] venv or repo/.venv)
  Note over venvResolver: A missing or stale venv would be configured here, unless protected mode or bootstrap-fallback = false forbids it
  venvResolver-->>chkPy: venv is fresh, activated
  chkPy->>gate: run gate on the untouched repo
  Note over gate: Steps in order - pcf, toi, cmp, mypy, rf (ruff), pylint
  Note over gate: Guideline-review phase is not part of this run, it has its own cadence
  gate-->>chkPy: all six steps clean
  chkPy-->>user: all clean

  user->>tstPy: run cli/tst-py -q
  tstPy->>tstPy: run pytest in the same venv
  tstPy-->>user: pytest completes with no failures
```
