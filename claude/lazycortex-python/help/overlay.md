---
chapter_type: block
summary: Project-specific guideline files in docs/guidelines/ plus [tool.pcf] declarations in pyproject.toml let you extend the project-neutral canon per repo.
last_regen: 2026-08-19
no_diagram: true
source_skills:
  - lazy-python.install
  - lazy-python.coding-guidelines
  - lazy-python.documenting-guidelines
  - lazy-python.testing-guidelines
  - lazy-python.guidelines-index
source_sha: 612e0dc5f599c02a8079c2fda95dce662c02757a
---
# Per-repo overlay guidelines

Every Python project has conventions that belong to it alone — a base test class, a copyright header format, a custom docstring section for domain-specific fields, internal naming prefixes. The overlay convention is how you supply those specifics without forking the plugin or editing files it owns. You add content to `docs/guidelines/` files and, where the rule is mechanical rather than prose, to `[tool.pcf]` in `pyproject.toml`. Writer and reviewer agents read canon first, then overlay, on every dispatch; overlay rules win on conflict.

When `/lazy-python.install` runs its Step 5, it scaffolds four stub files under `docs/guidelines/` with placeholder headers. You fill them in. The plugin never touches these files again after the initial scaffold — they are yours to maintain.

## What's in this block

**`lazy-python.install`** owns the scaffold. Its Step 5 creates `coding_guidelines.md`, `documenting_guidelines.md`, `testing_guidelines.md`, and `checking_guidelines.md` under `docs/guidelines/` — each a stub with a `# Project additions to <topic>` header — only for files that don't already exist; a stub is never overwritten and the step is silently skipped once all four are present.

**`lazy-python.coding-guidelines`** is the canon that `docs/guidelines/coding_guidelines.md` extends: style, formatting, naming, imports, class and method design, error handling, and the copyright-header shape (a placeholder owner/license line you replace with your project's actual text). One clause here is deliberately closed to the overlay: every source file — comments, docstrings, `Domain(…)`/`Contract:` blocks, log and error strings, identifiers — must be written in English, regardless of the language your project's documents or operator conversations use and regardless of any `language` key your settings declare. The overlay tightens or adds rules; it cannot reopen this one.

**`lazy-python.documenting-guidelines`** is the canon that `documenting_guidelines.md` extends: the fixed class-docstring section order (Summary, Scope, Responsibilities, Guarantees, Subclassing, Notes, Type Parameters, Attributes), plus two hooks the canon leaves for your project to fill — an extra section registered via `[tool.pcf] extra_docstring_sections`, and a private-attribute escape hatch registered via `[tool.pcf] d2_exempt_marker_attrs`. The overlay file itself carries the content rules for whatever you register.

**`lazy-python.testing-guidelines`** is the canon that `testing_guidelines.md` extends: the `<YourBaseTest>` placeholder every generated test class inherits from, the seven Paranoid-Testing categories tests are expected to cover, and the log-level suppression pattern (`with_log_level(...)`) tests use around expected warnings or errors. Your overlay is the only place that names the real base class, any aggregate test file pattern, and the log-suppression helper your project actually ships.

**`lazy-python.guidelines-index`** is the entry point tying the four canon files together, and its own "Portability notes" section is effectively a pointer at what belongs in your overlay: CLI tool names (`chk`/`tst`/`imp`), the copyright header owner/license text, and the base test class are all called out there as placeholders a project ships in its own overlay rather than in the plugin.

## How they work together

The overlay lives in four files, one per canon topic:

- `docs/guidelines/coding_guidelines.md` extends `lazy-python.coding-guidelines.md`
- `docs/guidelines/documenting_guidelines.md` extends `lazy-python.documenting-guidelines.md`
- `docs/guidelines/testing_guidelines.md` extends `lazy-python.testing-guidelines.md`
- `docs/guidelines/checking_guidelines.md` extends `lazy-python.checking-guidelines.md`

`docs/guidelines/` also holds a fifth file that is not one of these four: `domain-groups.md`, the language-neutral domain-groups dictionary that `Domain(<group>):` knowledge markers draw their group names from (per `lazy-python.coding-guidelines.md`'s Knowledge Marker Rules and the `docs/guidelines/domain-groups.md` path named in `lazy-python.documenting-guidelines.md`). `/lazy-python.install` Step 5 does not scaffold it — the dictionary is owned by the wiki plugin's domain tooling and built by `/lazy-python.knowledge-sweep` when a repo adopts markers without that tooling. Don't mistake it for a fifth overlay stub; it shares the directory, not the mechanism.

The practical workflow: fill in the overlay stub for the topic you care about, add any matching `[tool.pcf]` declaration to `pyproject.toml` if the rule is mechanical, then dispatch the relevant writer or reviewer agent (see the agents block article for their full dispatch discipline). The agent picks up your additions immediately — no flag, no re-install, no changes to the prompt. If you later tighten or extend a rule, re-run the agent against the affected files; it re-reads the overlay on every dispatch and its output will reflect the updated spec.

Neither writer agent requires the overlay to be present. When `docs/guidelines/` does not exist or a topic file is missing, the writer proceeds with the project-neutral canon alone. The reviewer agent behaves the same way — an empty or missing `docs/guidelines/` tree just means its `overlay` guideline layer is empty, and it reviews against canon only. The stubs created by `/lazy-python.install` Step 5 are intentionally minimal — add only what differs from the canon.

## When you'd use this

- Your project has a base test class that every test should inherit from, and you want the test-writer agent to use it automatically without being told each time.
- Your copyright header format differs from the example in `lazy-python.coding-guidelines.md` and you want the correct version in every new file.
- You have internal naming conventions (module prefixes, enum naming patterns, import grouping rules) that extend the shared canon rather than replacing it.
- You want to tighten a rule the canon leaves flexible — for example, mandating a specific maximum function length or disallowing a pattern that is technically allowed by the shared style.
- Your project needs an extra class-docstring section beyond the built-in set (Summary, Scope, Responsibilities, Guarantees, Subclassing, Notes, Type Parameters, Attributes) — for example, to document generation rules for a data-set-initializer class or field-level semantics that don't fit `Attributes:`. You declare it once in `[tool.pcf] extra_docstring_sections` and describe its content rules in the overlay; the docstring-writer agent then writes it on every dispatch.
- Your project has private attributes or `@property` methods that should legitimately appear in a class's `Attributes:` section — you declare the marker attribute(s) that exempt a class via `[tool.pcf] d2_exempt_marker_attrs` and document the convention in the overlay.
- Your project exposes a log-level suppression helper or a test generator import path that the test-writer agent should use in every test file.
- You want a guideline clause enforced during code review — block-comment discipline, naming semantics, structural placement rules specific to your project — without writing a new automated checker. State it once in the overlay and the code-reviewer agent's "overlay-specific clauses" checklist item picks it up on every review dispatch.

## How it fits together

After `/lazy-python.install` Step 5 runs, each of the four overlay files exists as a stub with the header `# Project additions to <topic>`. You add content below that header. The stubs are left untouched on re-runs — the installer never overwrites existing overlay content.

This follows the same File-sync policy `/lazy-python.install` applies to every artifact it manages, but the overlay gets the friendliest treatment in it: `pyproject.toml` and the `docs/guidelines/*.md` overlays are both consumer-owned config, so a missing stub is a clean, non-contradictory write and an existing stub — however you've edited it — is left alone. A stub versus your edited content is never treated as a conflict; Step 5 never interrupts you with a merge question over these files.

**Two overlay mechanisms, not one.** Docstring conventions split across two places depending on whether the rule is mechanical or prose:

- **`docs/guidelines/documenting_guidelines.md`** — the content rules for any extra section you register (what belongs in it, how to phrase it) and any narrative conventions the checker can't enforce mechanically.
- **`pyproject.toml` `[tool.pcf]`** — the mechanical declarations that the checker and the writer agent both need to parse: `extra_docstring_sections` (section name, list style, order anchor, optional `ref_exempt` flag for sections whose body carries `# ref:` lines), `d2_exempt_marker_attrs` (class attribute names whose declaration exempts a class from the private-attributes-in-Attributes check), and `private_name_allowlist` (private identifiers tolerated in docstring narrative). The shipped `pyproject-defaults.toml` template ships all three as commented-out examples under `[tool.pcf]`.

**How the writer and reviewer agents use it.** Each reads the plugin canon first, then the matching overlay file(s) — docstring-writer reads `documenting_guidelines.md`, test-writer reads `testing_guidelines.md` and `checking_guidelines.md`, the code-reviewer reads every file under `docs/guidelines/` plus any Python-scoped `.claude/rules/*.md` and project notes. Overlay rules win on conflict, and a missing overlay file just means the agent falls back to canon alone. The agents block article covers the per-agent dispatch steps, self-checks, and precedence order in full; this block is about what the overlay files themselves declare.

**How the checker uses it.** `chk-py` applies the mechanical rules from `pyproject.toml` plus the configured checker stack, including whatever `[tool.pcf] extra_docstring_sections`, `d2_exempt_marker_attrs`, and `private_name_allowlist` you've declared. The overlay guideline files are prose conventions for writer and reviewer agents, not checker config. If you introduce a project-specific rule that needs mechanical enforcement beyond the docstring-section machinery, add the corresponding setting to `pyproject.toml` directly (the `[tool.ruff]`, `[tool.mypy]`, or `[tool.pylint]` sections that `/lazy-python.install` bootstrapped).

**Conflict resolution.** When the overlay repeats a rule from the canon with a different value, the overlay wins. When it adds a new rule not present in the canon, that rule applies in addition. There is no syntax for "delete a canon rule" — to neutralise a canon rule, override it with the exception you want to allow and document the reason in a comment. The one rule the overlay cannot touch at all is the coding canon's English-only source-language requirement — see "What's in this block" above.

## Common adjustments

**Setting a base test class.** In `docs/guidelines/testing_guidelines.md`, add a section that names the base class to inherit from for each test type your project uses (unit tests, integration tests, async tests). The test-writer agent reads this on every dispatch and substitutes the real class name where the canon uses `<YourBaseTest>`.

**Declaring aggregate test file patterns.** In `docs/guidelines/testing_guidelines.md`, add a section describing any aggregate test files that validate many sibling classes at once. When declared, the test-writer agent skips individual test files for the covered classes rather than generating per-class files that would duplicate coverage.

**Declaring a log-level suppression helper.** In `docs/guidelines/testing_guidelines.md`, name the context manager your project exposes for suppressing expected warning or error logs during tests (e.g. `with_log_level`). The test-writer agent uses this helper in fixture and setup code rather than leaving the generic placeholder.

**Registering an extra class-docstring section.** In `pyproject.toml`, add a `[[tool.pcf.extra_docstring_sections]]` table with `name`, `style` (`"bulleted"`, `"definition"`, or `"plain"`), and an `after` / `before` order anchor naming a built-in section or a previously declared entry (an unresolved anchor appends the section at the end of the order). Set `ref_exempt = true` if the section's body carries `# ref:` lines. Then describe the section's content rules — what belongs in it and how to phrase it — in `docs/guidelines/documenting_guidelines.md`. The docstring-writer agent reads both before writing the section and will never invent it in a project that hasn't registered it.

**Declaring the private-attribute escape hatch.** If your project has classes where private fields or `@property` methods should legitimately appear in `Attributes:`, add the marker attribute name(s) to `pyproject.toml` `[tool.pcf] d2_exempt_marker_attrs`. A class is exempt when it declares one of the listed attribute names. Document the convention (which marker names exist and what they signal) in `docs/guidelines/documenting_guidelines.md`.

**Tightening the copyright header.** In `docs/guidelines/coding_guidelines.md`, replace the canonical placeholder header with your project's exact copyright line, license identifier, and any required SPDX header. Every new file that either writer agent touches after this change will use the project-specific form.

**Adding a project-specific naming rule.** Add a named section to the relevant overlay file. The heading structure does not need to match the canon — agents read the whole file and merge the rules — but clear section names (matching the canon's style) make the intent unambiguous and reduce the chance of misinterpretation.

**Adding a rule the checkers can't enforce.** If the convention is judgement-based rather than mechanical (a naming nuance, a structural placement rule, a phrasing convention), it belongs in the overlay prose, not in `pyproject.toml`. The code-reviewer agent picks it up as an overlay-specific clause on its next dispatch — no separate registration step.

**Scaffolding the stubs if they are missing.** If the `docs/guidelines/` files were never created — for example, you installed the plugin before Step 5 was added — re-run `/lazy-python.install`. The install wizard is idempotent; Step 5 skips any stub file that already exists and creates only the missing ones. It will not create a stub if all four are already present.

## Where this fits

The overlay files are scaffolded by the `install-and-audit` block's `/lazy-python.install` Step 5. The canon they extend lives in the `discipline` block — the five reference guidelines (`coding-guidelines`, `documenting-guidelines`, `testing-guidelines`, `checking-guidelines`, `guidelines-index`) that writer and reviewer agents load before reading your overlay. The `agents` block is where the docstring-writer, test-writer, and code-reviewer agents live; their full dispatch discipline — including exactly how each one reads canon and overlay together — is described in that block's article. The `add-project-overlay` walkthrough covers the end-to-end flow: scaffold stubs, fill them in, and confirm the delta appears in the next writer-agent dispatch.
