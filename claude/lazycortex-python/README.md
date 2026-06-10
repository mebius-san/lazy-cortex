---
iconize_icon: LiInfo
iconize_color: "#fde68a"
---
# lazycortex-python

Python coding discipline as a plugin: shared rules + reference guidelines + chk/tst checkers + PostToolUse hook + docstring-writer/test-writer agents + canonical file template. Installs once per repo via /lazy-python.install.

## Why this plugin

Python codebases drift fast. Style conventions vary per author. Docstrings rot or never get written. Tests grow ad-hoc with no shared shape. And the same checker stack gets copy-pasted into every new repo with subtle drift each time.

`lazycortex-python` is the opinionated Python-coding discipline layer for projects that already use `lazycortex-core`. It ships shared rules that constrain how Claude writes Python, reference guidelines the writer agents consult, `chk` / `tst` checker scripts that gate every change, a PostToolUse hook that wires the checks into the edit loop, and dedicated docstring-writer and test-writer agents so the writers know the project's exact shape rather than guessing per file.

## Who it's for

- **Python projects using Claude Code** that want a consistent style and test shape without re-deriving it per repo.
- **Maintainers** who are tired of reviewing Claude-authored Python that ignores the project's conventions.
- **Teams adopting test-first discipline** who want every code change gated by a fast checker run before the commit.
- **Plugin authors** who ship Python and want the same writer/checker contract their consumers will see.

## Blocks

- **install-and-audit** — Bootstrap and verify the lazycortex-python plugin in your project. `/lazy-python.install` is a 7-phase wizard that drops rule mirrors, plants `chk-py`/`tst-py` wrappers (and ensures `.venv/` is gitignored), edits `pyproject.toml` defaults, scaffolds `docs/guidelines/*.md` overlay stubs, syncs `python-template.py` into `.claude/templates/python/` and registers it in `lazy-core.scaffold.md` via `lazy-core.scaffold-sync`, and appends a CLAUDE.md bullet. The checker tools (mypy/pylint/pytest) land in a project-local `.venv` (repo root), created/augmented on first `chk-py`. The PostToolUse check-style hook is NOT an install step — it auto-registers from the plugin's `hooks/hooks.json` manifest when the plugin is enabled. `/lazy-python.audit` is the read-only 11-check counterpart. Members: lazy-python.install, lazy-python.audit.
- **discipline** — Three always-loaded rules constraining how Claude writes Python, plus the five reference guidelines the writer agents and `chk-py`/`tst-py` consult. Rules are path-scoped: style + docstrings load on `**/*.py`, tests load on `tests/**/*.py`. Members: lazy-python.style, lazy-python.docstrings, lazy-python.tests, lazy-python.coding-guidelines, lazy-python.documenting-guidelines, lazy-python.testing-guidelines, lazy-python.checking-guidelines, lazy-python.guidelines-index.
- **checkers** — `chk-py` (style + type) and `tst-py` (pytest) aggregator wrappers installed into `cli/` per repo from the shipped `chk` / `tst` aggregators, layered over the three shipped binaries (`pcf` style critical-fail, `toi` test-of-intent, `pch` PyCharm inspect) plus a shared venv resolver. `chk-py all` runs the canonical six-step gate `pcf → toi → cmp → mypy → ruff → pylint` (`cmp` = py_compile syntax check, `rf` = ruff); `pch` is a separate, slower manual subcommand (`chk-py pch <file>`, needs PyCharm's `inspect.sh`) and is NOT in the `all` gate. The resolver reuses an existing venv (`$VIRTUAL_ENV` / `<repo>/.venv` / configured path); when none exists it creates/augments a project-local `.venv` in the repo root — never wiping it, only adding the missing tools (`mypy`/`pylint`/`pytest`/`ruff` + the `pytest-clarity`/`pytest-sugar` plugins; install ensures `.venv/` is gitignored). Callable from the terminal, from skills, and from the PostToolUse hook. Members: chk, tst, pcf.py, toi.py, pch.py, _ensure_venv.sh.
- **agents** — Manual-invoke skill that runs `chk-py` and reports findings, plus two dispatched writer agents that consult canon references + the project overlay before writing docstrings or tests. Members: lazy-python.check-style, lazy-python.docstring-writer, lazy-python.test-writer.
- **hook** — PostToolUse hook fired on every `.py` edit. Auto-registers from the plugin's `hooks/hooks.json` manifest when the plugin is enabled (no consumer settings.json write; no install step). Runs `pcf.py` against the touched file — honoring the `[tool.pcf] exclude` list in `pyproject.toml`, so excluded paths are a no-op — and returns any violations as `additionalContext` so the next turn sees them inline. Members: lazy-python.check-style.sh, hooks.json.
- **scaffold** — Canonical Python file skeleton. `/lazy-python.install` Step 6 dispatches `lazy-core.scaffold-sync`, which copies the template into `.claude/templates/python/python-template.py` and registers that consumer-local path in `lazy-core.scaffold.md`, so any new `**/*.py` Claude composes starts from the template rather than from memory. Members: python/python-template.py, python/scaffold.entries.json.
- **overlay** — Per-repo overlay convention: `docs/guidelines/<topic>_guidelines.md` files (scaffolded as stubs by `/lazy-python.install` Phase 5) hold project-specific additions to the canon. Writer agents read canon first, then overlay; overlay rules override on conflict. Documentation-only — no shipped files.

## Walkthroughs

- **install-and-first-check** — Bootstrap the plugin in a clean repo and confirm the checker stack is wired up. Path: `/lazy-python.install` (7-phase wizard drops rule mirrors, plants `chk-py` / `tst-py` wrappers, gitignores `.venv/`, scaffolds overlay stubs; the PostToolUse hook auto-registers from the plugin manifest) → `chk-py all -q` creates/augments the project-local `.venv` on first run and verifies the resolver works → confirm zero violations on a clean tree.
- **add-project-overlay** — Layer project-specific style on top of the canon guidelines so the writer agents honor it. Path: edit `<repo>/docs/guidelines/coding_guidelines.md` (overlay stub created by `/lazy-python.install` Phase 5) → next `lazy-python.docstring-writer` dispatch reads canon first, then the overlay → verify the project-specific delta shows up in the generated docstring.
- **write-tests-for-new-class** — Generate a test file that walks the full Paranoid-Testing shape rather than ad-hoc cases. Path: dispatch `lazy-python.test-writer` against a new class → it walks the seven Paranoid-Testing categories from `lazy-python.testing-guidelines` → `tst-py <module> -q` runs the resulting suite.
- **migrate-existing-repo** — Adopt the plugin in a repo with pre-existing Python that drifted from the canon. Path: `cd` into the repo → `/lazy-python.install` (wizard edits `pyproject.toml` defaults and scaffolds the `docs/guidelines/` overlay) → `chk-py all -q` flags every existing violation → fix iteratively in chunks, committing as you go.

## Requirements

- **lazycortex-core** — installed and enabled (this plugin layers on its rules + runtime).
- **Python 3** — the checkers and hook scripts are Python.
- **mypy** / **pylint** / **pytest** / **ruff** (+ **pytest-clarity** / **pytest-sugar**) — installed automatically into a project-local `.venv` (repo root) on first `chk-py` / `tst-py` (alongside the plugin-shipped `pcf` / `toi` / `pch` checkers). Reuses an existing venv if one is found; install gitignores `.venv/`.

## Dependencies

Requires these plugins from the same marketplace:

- [`lazycortex-core`](../lazycortex-core/) — Core skills, agents, and runtime daemon for Claude Code (expert runtime + agent-model routing + settings management)

## Skills

| Skill | Description |
|---|---|
| `lazy-python.audit` | Read-only health check across the 11 invariants the lazycortex-python plugin promises — rules mirror integrity, reference resolution, artifact presence, wrappers, pyproject sections (incl. [tool.ruff]), hook registration, venv state (mypy/pylint/pytest/ruff + pytest-clarity/pytest-sugar). |
| `lazy-python.check-style` | Six-step Python code/style review — manually-invoked workflow that reads canon + overlay, identifies modified files, runs manual inspection categories, then dispatches chk-py + tst-py to gate. |
| `lazy-python.install` | Seven-phase install wizard that wires lazycortex-python into a consumer repo — mirrors rules, deploys chk-py / tst-py wrappers, bootstraps pyproject.toml checker stack, scaffolds project overlay guidelines, syncs the scaffold template, and offers an opt-in CLAUDE.md pointer. The PostToolUse check-style hook auto-registers from the plugin manifest — no install step writes to settings.json. |

## Documentation

Step-by-step walkthroughs, troubleshooting decision-tree, and FAQ for the scenarios above:

- [agents](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/agents.md) — Manual code-quality review via /lazy-python.check-style plus two dispatch-ready writer agents that enforce project conventions for docstrings and tests.
- [checkers](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/checkers.md) — The `chk-py` and `tst-py` CLI wrappers that gate every Python change — style, type-only imports, syntax, mypy, ruff, pylint, and pytest — backed by a shared venv resolver that works from any terminal.
- [discipline](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/discipline.md) — Three always-loaded rules shape every Python edit; five reference guidelines back the writer agents and chk-py/tst-py with the full canon.
- [hook](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/hook.md) — The PostToolUse hook that runs `pcf.py` on every `.py` edit and surfaces style violations inline in the next turn — zero install steps, zero config writes.
- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/install-and-audit.md) — Bootstrap lazycortex-python into your repo with a 7-phase install wizard and verify the installation with the 11-check read-only audit.
- [overlay](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/overlay.md) — Project-specific guideline files in docs/guidelines/ let you extend or override the lazycortex-python canon per repo without touching plugin-managed files.
- [scaffold](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/scaffold.md) — Canonical Python file skeleton that seeds every new .py file Claude composes — installed once via /lazy-python.install Step 6.
- [add-project-overlay](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/walkthroughs/add-project-overlay.md) — Layer project-specific docstring rules on top of the canon guidelines so lazy-python.docstring-writer honours your project's conventions on every dispatch.
- [install-and-first-check](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/walkthroughs/install-and-first-check.md) — Run /lazy-python.install in a clean repo, confirm the checker stack is wired, and get zero violations on first chk-py all.
- [migrate-existing-repo](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/walkthroughs/migrate-existing-repo.md) — Adopt lazycortex-python in a repo with pre-existing Python, run chk-py all to surface every drift violation, and fix them in committed chunks.
- [write-tests-for-new-class](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/walkthroughs/write-tests-for-new-class.md) — Dispatch lazy-python.test-writer against a new class and get a test file that covers all seven Paranoid-Testing categories, verified by tst-py.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/troubleshooting.md) — Symptoms, causes, and fixes for lazycortex-python install, audit, and style checks.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/faq.md) — Answers to common questions about installing, running, and customising lazycortex-python across style, docstrings, tests, and the checker stack.

Offline copy at `~/.claude/plugins/cache/.../claude/lazycortex-python/help/`.

## Agents

| Agent | Description |
|---|---|
| `lazy-python.docstring-writer` | Use this agent when adding or fixing docstrings on classes, methods, or properties in a Python codebase that adopts the `lazy-python.*` documentation conventions. Reads canonical guidelines from the plugin plus the project overlay on every dispatch. |
| `lazy-python.test-writer` | Use this agent when writing unit tests for a class or module in a Python codebase that adopts the `lazy-python.*` testing conventions. Reads canonical testing and checking guidelines from the plugin plus the project overlay on every dispatch. Never modifies production code — only writes test files. |

## Rules

| Rule | Description |
|---|---|
| `lazy-python.docstrings.md` | Python docstring discipline — use the lazy-python.docstring-writer agent. Triggers on **/*.py. |
| `lazy-python.style.md` | Python style critical reminders + Verification Order. Triggers on **/*.py. |
| `lazy-python.tests.md` | Python test placement, naming, and writing discipline — use the lazy-python.test-writer agent. Triggers on tests/**/*.py. |

## Commands

| Command | Description |
|---|---|
| `lazy-python.help` | Show lazycortex-python purpose and a one-line summary of each skill, agent, rule, and hook it ships |

## Hooks

| Hook | Trigger | Description |
|---|---|---|
| `lazy-python.check-style` | `Edit\|Write` | PostToolUse hook fired on every .py edit — runs pcf.py against the touched file and returns violations as additionalContext. |

## Installation

Add the marketplace and enable the plugin in your global `~/.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "lazycortex": {
      "source": {
        "source": "github",
        "repo": "mebius-san/lazy-cortex"
      },
      "autoUpdate": true
    }
  },
  "enabledPlugins": {
    "lazycortex-python@lazycortex": true
  }
}
```

Restart Claude Code. Skills appear as `lazycortex-python:<skill.name>`.

## Usage

Invoke skills with slash commands:

```
/lazy-python.audit
/lazy-python.check-style
/lazy-python.install
/lazy-python.help
```
