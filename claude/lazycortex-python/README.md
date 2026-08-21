---
iconize_icon: LiInfo
iconize_color: "#fca5a5"
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

- **install-and-audit** — Bootstrap and verify the lazycortex-python plugin in your project. `/lazy-python.install` is a quiet install that drops rule mirrors, plants `chk-py`/`tst-py` wrappers (and ensures `.venv/` is gitignored), edits `pyproject.toml` defaults (adding `[tool.pch]` automatically when PyCharm is present), scaffolds `docs/guidelines/*.md` overlay stubs, and syncs `python-template.py` into `.claude/templates/python/` and registers it in `lazy-core.scaffold.md` via `lazy-core.scaffold-sync`. It asks nothing and never touches your CLAUDE.md (the plugin rules load from `.claude/rules/` regardless). The checker tools (mypy/pylint/pytest) land in a project-local `.venv` (repo root), created/augmented on first `chk-py`. The PostToolUse check-style hook is NOT an install step — it auto-registers from the plugin's `hooks/hooks.json` manifest when the plugin is enabled. `/lazy-python.audit` is the read-only audit counterpart. Members: lazy-python.install, lazy-python.audit.
- **discipline** — Three always-loaded rules constraining how Claude writes Python, plus the five reference guidelines the writer agents and `chk-py`/`tst-py` consult. Rules are path-scoped: style + docstrings load on `**/*.py`, tests load on `tests/**/*.py`. Members: lazy-python.style, lazy-python.docstrings, lazy-python.tests, lazy-python.coding-guidelines, lazy-python.documenting-guidelines, lazy-python.testing-guidelines, lazy-python.checking-guidelines, lazy-python.guidelines-index.
- **checkers** — `chk-py` (style + type) and `tst-py` (pytest) aggregator wrappers installed into `cli/` per repo from the shipped `chk` / `tst` aggregators, layered over the three shipped binaries (`pcf` style critical-fail, `toi` test-of-intent, `pch` PyCharm inspect) plus a shared venv resolver. `chk-py all` runs the canonical six-step gate `pcf → toi → cmp → mypy → ruff → pylint` (`cmp` = py_compile syntax check, `rf` = ruff). The guideline review is a seventh step that runs on its own cadence and is deliberately NOT part of `all`: one dispatch carries the entire guideline canon, so its cost is fixed per run rather than per file, and it belongs at the end of a unit of work rather than inside the edit loop. `chk-py review` resolves the scope (current diff plus untracked, explicit paths, or `--base <ref>` for a unit of work that landed intermediate commits), collects every applicable guideline layer, writes a manifest, and names the `lazy-python.code-reviewer` agent to run against it — it never calls an LLM itself and exits 2 while the review is pending, so CI stays red until the review is dispatched or the operator waives the scope. Findings render back through `chk-py review --render <findings.json>`, which does exit non-zero on a FAIL; an unchanged scope reuses its previous verdict. `pch` is a separate, slower manual subcommand (`chk-py pch <file>`, needs PyCharm's `inspect.sh`) and is NOT in the `all` gate. The resolver reuses an existing venv (`$VIRTUAL_ENV` / `<repo>/.venv` / configured path); when none exists it creates/augments a project-local `.venv` in the repo root — never wiping it, only adding the missing tools (`mypy`/`pylint`/`pytest`/`ruff` + the `pytest-clarity`/`pytest-sugar` plugins; install ensures `.venv/` is gitignored). Callable from the terminal, from skills, and from the PostToolUse hook. Members: chk, tst, pcf.py, toi.py, pch.py, review.py, _ensure_venv.sh.
- **agents** — Manual-invoke skill that runs `chk-py` and reports findings, plus three dispatched agents that consult canon references + the project overlay before acting: two writers (docstrings, tests) and a reviewer. `lazy-python.code-reviewer` is the review phase's agent — it reads the manifest `chk-py review` builds, walks the guideline clauses no AST check can prove (a purpose comment on every block, logical-block boundaries, naming semantics, the project's own overlay), and writes findings as JSON. It never edits the code under review. Members: lazy-python.check-style, lazy-python.docstring-writer, lazy-python.test-writer, lazy-python.code-reviewer.
- **hook** — PostToolUse hook fired on every `.py` edit. Auto-registers from the plugin's `hooks/hooks.json` manifest when the plugin is enabled (no consumer settings.json write; no install step). Runs `pcf.py` against the touched file — honoring the `[tool.pcf] exclude` list in `pyproject.toml`, so excluded paths are a no-op — and returns any violations as `additionalContext` so the next turn sees them inline. Members: lazy-python.check-style.sh, hooks.json.
- **scaffold** — Canonical Python file skeletons. `/lazy-python.install` Step 6 dispatches `lazy-core.scaffold-sync`, which copies both templates into `.claude/templates/python/` and registers the consumer-local paths in `lazy-core.scaffold.md`, so any new `.py` file Claude composes starts from a template rather than from memory: `python-template.py` for regular `**/*.py` files (no module docstring — those belong to `__init__.py` only) and `init-template.py` for `**/__init__.py` (package docstring per the canon's `__init__.py` File Patterns; the more specific glob wins). Members: python/python-template.py, python/init-template.py, python/scaffold.entries.json.
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
| `lazy-python.audit` | Run when the operator asks whether the Python tooling is wired up correctly, or when it silently isn't working — `chk-py` / `tst-py` missing or failing to launch, the check-style hook never firing, the python rules absent from `.claude/rules/`, a checker not in the venv. Read-only; the fix is always a re-run of `/lazy-python.install`. |
| `lazy-python.check-style` | Use when the user asks to review, check, or clean up Python code they just changed — 'check my style', 'review these files against our guidelines', 'is this ready to commit'. Run it after a batch of edits and before committing: it pairs manual guideline inspection (the things `chk-py` cannot see, read fresh from the canon plus the project overlay) with the full `chk-py` + `tst-py` gate and a re-verify pass. |
| `lazy-python.install` | Run when the operator asks to set up Python tooling in a repo, after a lazycortex-python update, or when `/lazy-python.audit` reports missing rules, wrappers, pyproject checker sections, or overlay guidelines. Also the fix whenever `chk-py` / `tst-py` aren't on hand in a repo that should have them. Idempotent and near-silent — it asks only on a genuine file conflict or when several env-bootstrap scripts are candidates. |
| `lazy-python.knowledge-sweep` | Run when the operator asks to update or grow the domain-groups dictionary — 'add these groups', 'the dictionary is missing half our domains', 'file the unfiled blocks' — or when parked `Domain(unfiled):` findings have piled up in the checker output and nobody can clear them by hand. Also the backfill route for a repo that just adopted domain markers: clusters the parked knowledge into candidate groups, writes the ones the operator accepts into the dictionary, then sweeps the sources so every block lands under a real group. |

## Documentation

Step-by-step walkthroughs, troubleshooting decision-tree, and FAQ for the scenarios above:

- [agents](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/agents.md) — Manual review via /lazy-python.check-style, the chk-py review guideline phase and its lazy-python.code-reviewer agent, docstring/test writer agents, a Domain/Contract knowledge-marker pair, and the knowledge-sweep skill that backfills markers across an existing codebase.
- [checkers](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/checkers.md) — chk-py runs pcf, toi, cmp, mypy, ruff, pylint plus guideline review; tst-py runs pytest; both share a venv resolver that works anywhere.
- [discipline](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/discipline.md) — Three always-loaded rules shape every Python edit; five reference guidelines back the writer agents and chk-py/tst-py with the full canon.
- [hook](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/hook.md) — The PostToolUse hook that runs `pcf.py` on every `.py` edit and surfaces style violations inline in the next turn — zero install steps, zero config writes.
- [install-and-audit](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/install-and-audit.md) — Bootstrap lazycortex-python with a 10-step install wizard (incl. env_source detection) and verify with the 12-check read-only audit.
- [overlay](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/overlay.md) — Project-specific guideline files in docs/guidelines/ plus [tool.pcf] declarations in pyproject.toml let you extend the project-neutral canon per repo.
- [scaffold](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/scaffold.md) — Canonical Python file skeletons — python-template.py for regular files, init-template.py for __init__.py — installed once via /lazy-python.install Step 6.
- [add-project-overlay](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/walkthroughs/add-project-overlay.md) — Register a documentation-guideline clause in the project overlay, then confirm lazy-python.docstring-writer honors it in the generated docstring.
- [install-and-first-check](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/walkthroughs/install-and-first-check.md) — Install lazycortex-python, then run chk-py all -q directly to build the project venv and prove the six-step checker gate is clean.
- [migrate-existing-repo](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/walkthroughs/migrate-existing-repo.md) — Adopt lazycortex-python in a repo with pre-existing Python, run chk-py all to surface every drift violation (including pcf's language and project-package checks), then backfill Domain/Contract markers with knowledge-sweep.
- [write-tests-for-new-class](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/walkthroughs/write-tests-for-new-class.md) — Dispatch lazy-python.test-writer against a new class and get a test file that covers all seven Paranoid-Testing categories, verified by tst-py.
- [troubleshooting](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/troubleshooting.md) — Symptoms, causes, and fixes for lazycortex-python install, audit, style checks, the guideline-review gate, and writer agents.
- [faq](https://github.com/mebius-san/lazy-cortex/blob/main/claude/lazycortex-python/help/faq.md) — Answers to common questions about installing, running, and customising lazycortex-python across style, docstrings, knowledge markers, tests, and the checker stack.

(`mebius-san` resolves from `.guard-public.json` `public_author` block — fall back to repo name from `git remote get-url origin` if absent.)

## Agents

| Agent | Description |
|---|---|
| `lazy-python.code-reviewer` | Dispatch as the review phase of the Python check pipeline — `chk-py review` prints a manifest and names this agent — or directly with an explicit file list when new or changed Python needs judging against the `lazy-python.*` guidelines plus the project's own overlay, the layer no script can check. It reports findings only; it never edits code. Examples: <example> Context: The checkers are green and the change is ready for the review phase. user: "chk-py review printed a manifest" assistant: "I'll dispatch the lazy-python.code-reviewer agent against that manifest." </example> <example> Context: The user wants an existing file reviewed for guideline conformance. user: "Review src/core/entity.py against our guidelines" assistant: "I'll use the lazy-python.code-reviewer agent to review that file." </example> |
| `lazy-python.contract-writer` | Use this agent when a caller-visible guarantee needs formalizing as a `Contract:` block — adding a new guarantee to a method, class, or attribute, updating an existing contract's wording, or lifting a guarantee out of prose into a formal contract. Writes the block and syncs the owning docstring's `Guarantees` / `Subclassing` section in the same pass. Examples: <example> Context: A method returns a deep copy but nothing records the guarantee. user: "Formalize the deep-copy guarantee on create_clone" assistant: "I'll use the lazy-python.contract-writer agent to write the Contract block and sync Guarantees." </example> <example> Context: A subclassing obligation lives only in a code comment. user: "Make the override obligation on _sys_crd_val a contract" assistant: "I'll dispatch lazy-python.contract-writer for the contract and the Subclassing note." </example> |
| `lazy-python.docstring-writer` | Use this agent when adding or fixing docstrings on classes, methods, or properties in a Python codebase that adopts the `lazy-python.*` documentation conventions. Reads canonical guidelines from the plugin plus the project overlay on every dispatch. Examples: <example> Context: A class or method is missing a docstring or has a non-compliant one. user: "Write docstrings for this class" assistant: "I'll use the lazy-python.docstring-writer agent to generate compliant docstrings." </example> |
| `lazy-python.domain-writer` | Use this agent when domain knowledge implemented in code needs a `Domain(…):` block — documenting a mechanic, formula, or domain rule, adding concept-level rationale, or updating an existing block after the mechanic changed — or when a file's parked `Domain(unfiled):` blocks must be refiled because the dictionary has since grown (dispatch with `refile=true`). Validates groups and tags against the project's domain-groups dictionary and never invents a permanent group. Examples: <example> Context: A calculation implements a domain rule that is documented nowhere. user: "Document the hit-chance mechanic next to its calculation" assistant: "I'll use the lazy-python.domain-writer agent to write the Domain block." </example> <example> Context: An existing Domain block describes a mechanic that has since changed. user: "The stacking rules changed — update their Domain comment" assistant: "I'll dispatch lazy-python.domain-writer to rewrite that block." </example> |
| `lazy-python.test-writer` | Use this agent when writing unit tests for a class or module in a Python codebase that adopts the `lazy-python.*` testing conventions. Reads canonical testing and checking guidelines from the plugin plus the project overlay on every dispatch. Never modifies production code — only writes test files. Examples: <example> Context: A new class was written and needs tests. user: "Write tests for DataRoll" assistant: "I'll use the lazy-python.test-writer agent to create compliant tests." </example> |

## Commands

| Command | Description |
|---|---|
| `lazy-python.help` | Run when the operator asks what lazycortex-python enforces, how Python is checked in this repo, which verb runs the checkers, or where domain and contract markers come from — lists the Python-discipline surface: install / audit / check-style / knowledge-sweep, the `chk-py` and `tst-py` wrappers, the docstring-writer / test-writer / code-reviewer agents plus the domain-writer / contract-writer knowledge-marker pair, the always-loaded style, docstring and test rules, and the PostToolUse style hook. |

## Rules

| Rule | Description |
|---|---|
| `lazy-python.docstrings.md` | Python docstring discipline — use the lazy-python.docstring-writer agent. Triggers on **/*.py. |
| `lazy-python.style.md` | Python style critical reminders + Verification Order. Triggers on **/*.py. |
| `lazy-python.tests.md` | Python test placement, naming, and writing discipline — use the lazy-python.test-writer agent. Triggers on tests/**/*.py. |

## Hooks

| Hook | Trigger | Description |
|---|---|---|
| `lazy-python.check-style` | `Edit\|Write` | PostToolUse hook for lazy-python. |

## Installation

Add the marketplace once, then install this plugin — run inside Claude Code:

```
/plugin marketplace add mebius-san/lazy-cortex
/plugin install lazycortex-python@lazycortex
/reload-plugins
```

Skills appear as `lazycortex-python:<skill.name>`.

## Usage

Invoke skills with slash commands:

```
/lazy-python.audit
/lazy-python.check-style
/lazy-python.install
/lazy-python.knowledge-sweep
```
