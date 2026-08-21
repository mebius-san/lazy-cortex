---
chapter_type: faq
summary: Answers to common questions about installing, running, and customising lazycortex-python across style, docstrings, knowledge markers, tests, and the checker stack.
last_regen: 2026-08-19
no_diagram: true
source_skills:
  - lazy-python.install
  - lazy-python.audit
  - lazy-python.check-style
  - lazy-python.knowledge-sweep
  - lazy-python.docstring-writer
  - lazy-python.test-writer
  - lazy-python.code-reviewer
  - lazy-python.domain-writer
  - lazy-python.contract-writer
  - chk
  - tst
  - pcf.py
  - toi.py
  - pch.py
  - review.py
  - lazy-python.coding-guidelines
  - lazy-python.checking-guidelines
source_sha: 7e55c7700a727bafa0a894c538571d86f4359c7b
---
# Frequently asked questions

## Do I need to re-run `/lazy-python.install` after a plugin update?

It depends on what you want to pick up. The `chk-py` and `tst-py` wrappers self-resolve the active plugin at exec time — they locate the current plugin source each time they run, so they keep working correctly across a `/plugin update` without a re-install. Any new canon rules, updated checker configuration, or new overlay stubs that came with the update do require a re-run of `/lazy-python.install`, because those artifacts land in your project tree only when the install phases run.

A practical rule: re-run `/lazy-python.install` after any plugin update where the release notes mention changes to rules, `pyproject.toml` defaults, or the wrapper scripts themselves. The install is idempotent — it only overwrites the mirrored rule files and adds missing sections; your existing project additions are left untouched.

---

## The PostToolUse hook is not firing after install. How do I enable it?

The hook auto-registers from the plugin's `hooks/hooks.json` manifest when the plugin is enabled — no step in `/lazy-python.install` writes to your `settings.json`. If the hook is not firing, check that `lazycortex-python@lazycortex` appears in `enabledPlugins` in your `~/.claude/settings.json`, then restart Claude Code. The hook takes effect on the next `.py` edit once the session is live.

---

## `/lazy-python.audit` reports Check 1 as FAIL (drift). What does that mean?

One or more of the mirrored rule files under `.claude/rules/lazy-python.*.md` has drifted from the plugin canon — either a manual edit was made to a file that is plugin-managed, or the install was interrupted. Re-run `/lazy-python.install` to restore them. The install intentionally overwrites the mirror; any changes you wanted to make to those rules belong in your project overlay under `docs/guidelines/`, not in the mirrored files themselves.

---

## `/lazy-python.audit` warns about PyCharm inspect.sh (Check 6). Is that a problem?

Not for most of the checker stack. `pch.py` (the PyCharm inspection phase) requires `inspect.sh` from a PyCharm installation, but the other phases — `pcf`, `toi`, `cmp`, `mypy`, `ruff`, `pylint`, and `review` — run without it. `pch` is also not part of the `chk-py all` gate; it is a separate, slower manual subcommand (`chk-py pch <file>`). If you do not have PyCharm installed, Check 6 will always be `WARN` and `chk-py pch` will be unavailable. The rest of the pipeline remains fully functional.

---

## `/lazy-python.audit` warns about the venv (Check 11). How do I fix it?

Check 11 warns when no usable venv is found and bootstrapping one is not possible (e.g. `uv` is not on `$PATH`). Re-running `/lazy-python.install` re-probes the venv chain and attempts to bootstrap the plugin-local fallback venv under `${CLAUDE_PLUGIN_DATA}/venv`. If `uv` is available when you re-run, the venv is created automatically. If it is not, install `uv` first (`pip install uv` or the standalone installer), then re-run the install.

---

## How does `chk-py` decide which Python environment to use?

Every `chk-py` and `tst-py` invocation resolves the venv chain first, in order: an already-activated `$VIRTUAL_ENV`, then `<repo>/.venv`, then a path configured under `[tool.lazy-python]` in `pyproject.toml`, then the plugin-local fallback venv created or augmented on first run. Once a venv is active, the wrappers separately check `python.env_source` in `.claude/lazy.settings.json` — if it names a repo-specific bootstrap script, that script is sourced in the same shell before any checker or `pytest` runs, so provider credentials or secret-path exports your project depends on are in place first. The `review` subcommand is the one exception — it skips the venv resolver entirely, since it is pure stdlib by design, so the guideline-review phase also works from pre-commit hooks and CI runners that never set up a venv.

`python.env_source` is not something you set by hand: `/lazy-python.install` Step 7 detects a recognised bootstrap script (`cli/env`, `.env.sh`, or `scripts/env.sh`) in your repo and records it automatically. Zero or one candidate is handled silently; if more than one is found, install asks once which script to use. A value already on record is never re-asked or overwritten, and no audit check inspects it — recording `python.env_source` is an install-time convenience, not a verified invariant.

---

## When should I use `/lazy-python.check-style` versus the PostToolUse hook?

The PostToolUse hook runs `pcf.py` automatically on every `.py` edit and surfaces violations inline in the next turn — it is your fast inner loop. `/lazy-python.check-style` is the deeper seven-step review you invoke before committing: it adds a manual pass over semantic issues the automated checkers cannot see (docstring quality, contract consistency, guard-clause coverage, special-comment preservation), then dispatches the full `chk-py all` sweep (which itself ends with the `review` phase) plus `tst-py` to gate the change. Use the hook continuously and `/lazy-python.check-style` at the end of a meaningful edit batch.

---

## Can I run `mypy`, `pylint`, or `ruff` directly instead of `chk-py`?

No. The plugin enforces running all style and type validation through `chk-py`. The aggregator runs `pcf`, `toi`, `cmp`, `mypy`, `ruff`, `pylint`, and `review` in the correct order with shared config from `pyproject.toml`; calling any one tool directly skips earlier phases and can produce misleading results. Similarly, use `tst-py` rather than raw `pytest` — the wrapper applies project-wide pytest args and uses the correct venv.

---

## `chk-py all` finished but printed a "review" step at the end. What is that?

That is the guideline-review phase, the seventh and final step of `chk-py all`. Unlike the other six checks, `review.py` does not run a deterministic tool against your code — it resolves the scope (your current working-tree diff plus untracked files, or explicit paths you pass), collects every applicable canon and overlay layer, and writes a manifest under `.runtime/lazy-python/review/` in your project. It then prints that manifest path and names the `lazy-python.code-reviewer` agent to dispatch against it — a judgement pass over clauses no checker AST-walk can prove (comment purpose and density, `# guard:` semantics, naming-prefix correctness, useless intermediate variables, docstring-vs-code contract drift, suppression hygiene). Dispatch the agent against that manifest; it writes a findings document (FAIL / WARN / INFO) and never edits your code itself. `chk-py review --render <findings.json>` renders the findings the agent already produced, and is what actually clears the gate.

---

## `chk-py all` is failing with `review: PENDING` even though every other check is clean. How do I clear it?

A pending review now fails the gate instead of passing silently past it: `review.py` exits a distinct `PENDING` code (2) whenever the scope has changed since its last review and nobody has decided it yet. Dispatch the `lazy-python.code-reviewer` agent against the manifest path printed just above the `PENDING` line, then run `chk-py review --render <findings.json>` — that render step is what actually clears the gate, and it exits non-zero itself if the agent found a `FAIL`. `review.py` also takes a `--base <ref>` flag to resolve the scope against a landed range (a unit of work that shipped intermediate commits) instead of the current diff plus untracked files. If you genuinely cannot dispatch an agent in that context — a nested writer agent, a scripted sweep — set `CHK_REVIEW=skip` for that single invocation; it exits 0 but records no decision, so the same scope is still pending the next time anyone runs `chk-py all` against it. For CI or automation where the `claude` CLI is installed but no one is present to dispatch manually, set `CHK_REVIEW=headless` instead — `review.py` dispatches the reviewer agent itself through the CLI and renders its findings in the same run. Neither flag is a substitute for an actual review decision; a scope that has not changed since its last real review reuses those findings rather than re-manifesting.

---

## `chk-py` is flagging blocks for missing a purpose comment. What is `check_block_comments`?

`pcf` now proves presence of a purpose comment mechanically, on top of the review phase judging whether it says anything. `check_block_comments` (on by default) flags any block inside a function body whose first line after the blank separator is not a comment — including a lone trailing `return x`, which counts as a block on its own. A `# waiver:`, `# noqa`, `# type:`, `# pylint:`, `# fmt:`, or `# noinspection` line does not count as a purpose comment; those are directives. Clause headers, split-call continuations, the docstring, nested-function headers, and the body's own opening block are left alone — the check only fires on blocks after a blank-line separator.

Getting `pcf` green does not mean the review pass will be clean too: presence is now structural and belongs to `pcf`, but meaningfulness still belongs to `chk-py review` and the `lazy-python.code-reviewer` agent, which flags a comment that just restates the code below it (`# return the result` above `return result`) or names the syntax rather than the intent.

To disable the check, set `[tool.pcf] check_block_comments = false` in `pyproject.toml` — but silently switching off a checker without the user's explicit approval for that exact change is a serious violation per the checking guidelines. Don't turn it off on your own judgement; propose it and ask.

---

## `chk-py` is flagging a comment or docstring line for not being written in a configured language. What is this check?

`pcf` proves the *language* of every comment and docstring, on top of proving content and format: `check_language` (on by default, admitting only `english`) walks each letter in a comment or docstring and reports the first one whose Unicode script belongs to no configured language — one finding per offending line, naming the character and the languages the project allows. Punctuation, digits, and symbols carry no language and never trip the check.

This backs the coding canon's *Source Language* rule: every source file — comments, docstrings, `Domain(…)` and `Contract:` blocks, log messages, error strings, identifiers — is written in English regardless of the language a project's own documents, specs, or operator conversations are in. A project's configured language governs *generated* documents (the domain-spec writer translates a group's `Domain(…)` blocks into that language when it materialises the doc); the source block it translates from stays English. A quoted foreign-language literal the code genuinely handles — a user-facing string, a test fixture, a term being matched — is data, not prose, and is exempt.

To admit an additional language, set `[tool.pcf] allowed_languages = ["english", "<language>"]` in `pyproject.toml`; a letter belonging to any listed language's script is accepted. A genuinely one-off exception (a proper noun, a quoted foreign term inline in prose) takes a `# waiver: <reason>` comment like any other pcf finding — propose the change and get the user's explicit approval rather than widening `allowed_languages` on your own judgement, per the checking guidelines' rule against silently loosening a checker.

---

## `chk-py` reports import-classification findings differently than before. What changed with `project_package`?

`pcf` classifies every import as stdlib, third-party, or project (first-party) to enforce import ordering and grouping — and it used to key that classification off a hardcoded package name. It now resolves the consumer's first-party package via `project_package`: an explicit `[tool.pcf] project_package = "<name>"` in `pyproject.toml` always wins; when that key is unset, `pcf` autodetects a single top-level package under the project root or `src/` and uses it. When neither the config key nor autodetection yields exactly one candidate, project-import classification is disabled — imports that would have been "project" findings are simply not flagged, since there is no root to anchor them on.

If your repo has more than one top-level package (a monorepo, a `src/` layout with several packages) and you were relying on project-import findings, set `project_package` explicitly in `pyproject.toml`. A repo with exactly one top-level package needs no configuration — autodetection already covers it.

---

## `pcf.py` is flagging LaTeX math markup in a comment. Why?

LaTeX markup (`$...$`, `\frac{}{}`, and similar) is forbidden in every code comment, including `Domain(…):` blocks describing formulas — the canon requires plain prose with backticked identifiers instead. This is a guideline the `lazy-python.domain-writer` and `lazy-python.contract-writer` agents follow when they write a block, and `chk-py review`'s guideline-review phase (backed by `lazy-python.code-reviewer`) is what actually catches a violation slipping through — `pcf` itself does not run a dedicated mechanical LaTeX check. Rewrite the formula as prose (`the result is` `base` `times` `multiplier`, with backticks around the real identifiers) rather than embedding math notation.

---

## Does `lazy-python.code-reviewer` duplicate what `pcf` / `mypy` / `ruff` / `pylint` already check?

No — by design it refuses to. The agent's whole job is guideline clauses no deterministic checker can prove: whether a comment explains the right thing, whether a `# guard:` marker is on an actual defensive early-exit rather than an ordinary branch, whether a docstring's `Args:`/`Returns:`/`Raises:` still match the real signature, whether a suppression comment (`# type: ignore`, `# noqa`, `# pylint: disable`) carries a real `# waiver:` reason. If a finding duplicates something `pcf` or `ruff` would already have flagged, that is a bug in the agent's output, not an expected overlap.

---

## How do I add my own docstring section?

Declare it in `pyproject.toml` under a `[[tool.pcf.extra_docstring_sections]]` table — the section's `name`, its list `style` (`bulleted`, `definition`, or `plain`), and an `after`/`before` anchor naming a built-in or previously declared section to position it relative to. Add `ref_exempt = true` if the section's body carries `# ref:` lines that should be shielded from the phrasing and private-name checks. The shipped `pyproject-defaults.toml` template ships all three `[tool.pcf]` keys as commented-out examples, ready to uncomment and adapt.

Registering the section only tells `chk-py` where it belongs, its list style, and its exemptions — it does not tell anyone what to write inside it. Add the section's actual content rules to `docs/guidelines/documenting_guidelines.md` (the overlay). `lazy-python.docstring-writer` reads both the registration and the overlay on every dispatch and never invents a section your project hasn't declared.

---

## My classes used to get "Generation Rules" / "Value Ranges" docstring sections automatically. Now `chk-py` flags them as missing. What happened?

As of the 2.0.0 release, `pcf`'s docstring-section and field-name defaults are project-neutral: those two sections, and the hardcoded `_field_filters` private-name escape hatch, no longer ship built in. If your repo relied on them, re-run `/lazy-python.install` to pick up the current `pyproject-defaults.toml` template, then find the commented-out `extra_docstring_sections`, `d2_exempt_marker_attrs`, and `private_name_allowlist` examples under `[tool.pcf]` in your `pyproject.toml` — uncomment and adapt them to your project's actual section names and field names. The install's merge step only appends checker sections that are missing; it never overwrites or removes a `[tool.pcf]` block you've already customised, so this migration is opt-in per repo and safe to run at any time.

---

## Should I write docstrings by hand, or always use the agent?

Always use the `lazy-python.docstring-writer` agent. The canon enforces section ordering, a Zero-Tolerance Blocker list, an eight-point semantic Pre-Return Self-Check (checking for algorithm narration, private-internal references, tautological summaries, etc.), and an overlay merge from `docs/guidelines/documenting_guidelines.md`. Writing docstrings by hand from session memory of the canon reliably misses at least one of those checks. Dispatch the agent and let it own the result.

---

## The docstring-writer agent left a section blank. Is that a bug?

No. The agent omits sections that would be empty — that is correct behaviour per the style rules. For example, if a method has no documented exceptions, there is no `Raises:` section; if a class has no public instance fields, there is no `Attributes:` section. Do not add empty section headers to fill the gap.

---

## My new module has no module docstring. Is that a bug?

No. Module docstrings belong to `__init__.py` files only — regular source files carry no module docstring by canon. A regular `.py` file scaffolds from `python-template.py`, which has no docstring block, and `lazy-python.docstring-writer` will not add one to a non-`__init__.py` file. Only `**/__init__.py` files get a module-level docstring, scaffolded from the dedicated `init-template.py` (the more specific glob wins over the general `**/*.py` template) and describing the package per the canon's `__init__.py` File Patterns.

If a new `__init__.py` in your project is not picking up the dedicated template, re-run `/lazy-python.install` — Step 6 syncs both scaffold templates and registers the `**/__init__.py` entry alongside the general one. An older module that still carries a leftover module docstring is left as-is; the agent does not retroactively strip it.

---

## Should I write `Domain(…):` or `Contract:` blocks by hand, or use an agent?

Always use `lazy-python.domain-writer` for a `Domain(…):` block and `lazy-python.contract-writer` for a `Contract:` block. Both agents read the documenting canon and the project's domain-groups dictionary (for domain-writer) on every dispatch, validate against them, and verify their own edits with `chk-py all <file>.py -q` before finishing — a hand-written block reliably drifts from the format canon or, for domain blocks, uses a group that is not in the project's dictionary. `lazy-python.contract-writer` also carries the one sanctioned exception to "docstrings go through `lazy-python.docstring-writer`": it syncs the owning docstring's `Guarantees` (or `Subclassing`) section in the same pass, since that section's content is authoritative from the contract block it was written for.

Neither agent invents a domain group: when no listed group in the dictionary fits a mechanic, `lazy-python.domain-writer` parks the block under the reserved `Domain(unfiled):` group and reports a candidate name and gloss for you to file. That parked block shows up as a checker finding on every run until it is filed — see the next question for the sweep that clears a backlog of them.

---

## What is `/lazy-python.knowledge-sweep`, and when do I need it?

The canon expects `Domain(…):` and `Contract:` markers to be written at the same time as the code they describe — `lazy-python.domain-writer` and `lazy-python.contract-writer` are the per-edit route. `/lazy-python.knowledge-sweep` is the backfill route for code that predates that discipline, or for a repo whose domain-groups dictionary just grew: it walks a scope of Python sources, first growing the dictionary from whatever `Domain(unfiled):` blocks and subject-area vocabulary are already parked in the sources (proposing candidate groups to you one `AskUserQuestion` at a time — nothing is added without your tick), then dispatches the two writer agents file by file against the grown dictionary, and finally re-verifies and commits everything it touched.

Run it when: a batch of `Domain(unfiled):` findings has piled up and nobody is clearing them by hand one file at a time; you just adopted domain/contract markers in an existing repo and want a first pass; or the dictionary grew (new groups accepted) and you want the sweep's `refile=true` dispatch to re-file blocks that are still parked under `Domain(unfiled):` against the new groups. It never invents a permanent group on its own — every accepted group in the dictionary traces back to your explicit choice.

---

## Where does the domain-groups dictionary live, and who owns it?

The default path is `docs/guidelines/domain-groups.md`, beside the project's other guideline documents — a language-neutral registry of `## <group>` headings with one-line glosses, shared by every language's knowledge markers (not just Python's). `.claude/lazy.settings.json[wiki.domains.dictionary]` overrides that convention when set. `/lazy-python.install` deliberately does not seed this file — it is either created by the wiki plugin's domain configurator (for a repo that runs that tooling) or by `/lazy-python.knowledge-sweep` the first time it grows a dictionary from parked knowledge. Both `lazy-python.domain-writer` and `/lazy-python.knowledge-sweep` read whatever path the dispatch or settings name, falling back to the `docs/guidelines/domain-groups.md` convention only when nothing else is configured.

---

## `/lazy-python.audit` warns about the domain-groups dictionary (Check 12). What does that mean?

Check 12 fires when your sources already carry `Domain(…):` blocks but no dictionary exists at the configured (or conventional) path. The style checker deliberately never reads the dictionary itself — it only recognises the reserved `unfiled` literal — so marked code with no dictionary passes every checker while validating its groups against nothing. The fix is `/lazy-python.knowledge-sweep`: it builds the dictionary from whatever knowledge is already parked and refiles the blocks against it. A repo with no `Domain(…)` blocks yet, or one whose dictionary already exists, reports `PASS` here regardless.

---

## Should I write tests by hand, or always use the agent?

Always use the `lazy-python.test-writer` agent. The agent applies the Paranoid Testing Strategy (7 mandatory test categories per class), selects the correct base test class from your project overlay, enforces 2-space indentation and the 117-character line limit, derives expected values from docstring contracts rather than implementation, and runs `chk-py` plus `tst-py` as a verification gate. Hand-writing tests from session memory reliably skips categories or picks the wrong base class.

---

## A test written by the agent fails against the current implementation. Should I fix the test?

No. Per the Golden Rule in `lazy-python.test-writer`: if a test correctly reflects documented behaviour but fails against the current implementation, the implementation is suspect. The agent will add a `# FAILS: <reason>` comment above the test method and report the divergence to you. Fix the production code (or update the docstring if the spec has changed), not the test. Modifying an existing test also requires your explicit approval naming the specific test file — the agent will ask before touching it.

---

## The code-reviewer agent flagged a violation, but our overlay explicitly allows it. Is that a bug?

Yes, and it shouldn't happen if the overlay is being read correctly. The agent reads four layers in precedence order — canon, project overlay, project `.claude/rules/*.md`, then `CLAUDE.md` — and a later layer overrides an earlier one on conflict. If the overlay contradicts the canon, the overlay wins and the canon clause must not be reported as a finding. Check that your overlay file still opens with its canonical `# Project additions to <topic>` header (see the next question) — a missing header is the most common reason an override gets missed.

---

## How do I add project-specific style or testing rules without touching the plugin?

Use the overlay convention. The four overlay stubs under `docs/guidelines/` (`coding_guidelines.md`, `documenting_guidelines.md`, `testing_guidelines.md`, `checking_guidelines.md`) are where you add project-specific additions. Each overlay file opens with a `# Project additions to <topic>` header that the writer agents, the code-reviewer agent, and `/lazy-python.check-style` recognise. Rules in an overlay override the corresponding canon rule on conflict; they extend it otherwise. If the overlay stubs are missing, re-run `/lazy-python.install` — Phase 5 scaffolds them without overwriting any existing content.

---

## The overlay stubs are present but the writer agents are not picking them up.

Check that each overlay file still opens with its canonical `# Project additions to <topic>` header. The agents use that header to distinguish an overlay from the canon itself — if it was removed or renamed, run `/lazy-python.audit` (Check 7) to confirm. Restore the header and re-dispatch the agent. The overlay files are never plugin-managed; `/lazy-python.install` will not overwrite them.

---

## `/lazy-python.install` aborts saying the plugin source was not found.

`${CLAUDE_PLUGIN_ROOT}` is unset or points at a path with no `rules/lazy-python.*.md` files. Confirm that `lazycortex-python@lazycortex` is listed in `enabledPlugins` in your `~/.claude/settings.json`, restart Claude Code so the plugin is loaded, then re-run `/lazy-python.install`.

---

## The `chk-py` wrapper is missing or not executable after install.

Re-run `/lazy-python.install` — Phase 2 deploys `cli/chk-py` and `cli/tst-py` and sets the executable bit. If the phase reports `wrappers-deployed-2` but the files are still absent, check that `cli/` exists in your project root; the phase creates it if missing. If the problem persists, run `/lazy-python.audit` (Check 4) to see whether unsubstituted `{{CHK_BIN_PATH}}` placeholders are present, which would indicate an interrupted or partial install.

---

## `pyproject.toml` is missing the checker sections after install.

Run `/lazy-python.audit` Check 5 to confirm which of the six always-on sections (`[tool.pcf]`, `[tool.toi]`, `[tool.pytest]`, `[tool.mypy]`, `[tool.pylint]`, `[tool.ruff]`) are absent, then re-run `/lazy-python.install` (`[tool.pch]` is separate — added only when PyCharm is present, never a Check 5 finding). The install merges only the missing sections from `pyproject-defaults.toml` into your `pyproject.toml`; existing sections are never overwritten. If your `pyproject.toml` does not exist at all, it is created with the defaults.

---

## `/lazy-python.install` mentions registering a "code-reviewer expert". What is that for?

Step 7.6 registers `lazy-python.code-reviewer` as an expert in `.claude/lazy.settings.json`, additively and only if nothing is on record yet. This makes the review phase dispatchable two ways: directly (as `chk-py review` already names the agent) and through the expert runtime, the same dispatch path other plugins use for background or queued work. If the entry is already on record — you configured it yourself, or a previous install already added it — this step leaves it untouched; your own expert configuration is always authoritative.
