---
chapter_type: block
summary: Project-specific guideline files in docs/guidelines/ plus [tool.pcf] declarations in pyproject.toml let you extend the project-neutral canon per repo.
last_regen: 2026-07-13
no_diagram: true
source_skills:
  - lazy-python.install
  - lazy-python.docstring-writer
  - lazy-python.test-writer
---
# Per-repo overlay guidelines

Every Python project has conventions that belong to it alone — a base test class, a copyright header format, a custom docstring section for domain-specific fields, internal naming prefixes. The overlay convention is how you supply those specifics without forking the plugin or editing files it owns. You add content to `docs/guidelines/` files and, where the rule is mechanical rather than prose, to `[tool.pcf]` in `pyproject.toml`. Writer agents read canon first, then overlay, on every dispatch; overlay rules win on conflict.

When `/lazy-python.install` runs its Step 5, it scaffolds four stub files under `docs/guidelines/` with placeholder headers. You fill them in. The plugin never touches these files again after the initial scaffold — they are yours to maintain.

## What's in this block

**`lazy-python.docstring-writer`** is a documentation specialist agent that writes and fixes docstrings on classes, methods, and properties — never modifying code. On every dispatch it reads two layers before writing a single byte: the canonical `lazy-python.documenting-guidelines.md` from the plugin, then your project's `docs/guidelines/documenting_guidelines.md` overlay. Overlay rules override on conflict. The shipped canon is project-neutral — it ships no built-in extra sections and no built-in private-attribute escape hatch. Your project-specific documentation shape — a custom section for domain fields, the copyright header format, which private names are allowed to leak into narrative prose — lives entirely in your overlay plus the matching `[tool.pcf]` declarations, and is always in scope without you having to mention it in the prompt.

**`lazy-python.test-writer`** is a test engineer agent that writes unit test files following the Paranoid-Testing strategy (seven categories: happy path, wrong/invalid arguments, boundary values, error conditions, state transitions, operator overloading, and documented guarantees). On every dispatch it reads four layers before writing: the canonical `lazy-python.testing-guidelines.md` and `lazy-python.checking-guidelines.md` from the plugin, then your project's `docs/guidelines/testing_guidelines.md` and `docs/guidelines/checking_guidelines.md` overlays. The base test class your project requires, the aggregate test file patterns, the log-level suppression helper, and any project-specific test placement rules all live in the overlay and take effect automatically on the next dispatch.

## How they work together

The two agents share the same overlay infrastructure but draw from different topic files. `lazy-python.docstring-writer` reads the `documenting_guidelines.md` overlay; `lazy-python.test-writer` reads `testing_guidelines.md` and `checking_guidelines.md`. The `coding_guidelines.md` overlay (copyright headers, naming rules, import ordering) is read by both agents as a background layer from the consumer's `CLAUDE.md` `## Documenting` / `## Testing` sections if you place shared project-wide notes there.

The practical workflow: fill in the overlay stub for the topic you care about, add any matching `[tool.pcf]` declaration to `pyproject.toml` if the rule is mechanical, then dispatch the relevant agent. The agent picks up your additions immediately — no flag, no re-install, no changes to the prompt. If you later tighten or extend a rule, re-run the agent against the affected files; it re-reads the overlay on every dispatch and its output will reflect the updated spec.

Neither agent requires the overlay to be present. When `docs/guidelines/` does not exist or a topic file is missing, the agent proceeds with the project-neutral canon alone. The stubs created by `/lazy-python.install` Step 5 are intentionally minimal — add only what differs from the canon.

## When you'd use this

- Your project has a base test class that every test should inherit from, and you want `lazy-python.test-writer` to use it automatically without being told each time.
- Your copyright header format differs from the example in `lazy-python.coding-guidelines.md` and you want the correct version in every new file.
- You have internal naming conventions (module prefixes, enum naming patterns, import grouping rules) that extend the shared canon rather than replacing it.
- You want to tighten a rule the canon leaves flexible — for example, mandating a specific maximum function length or disallowing a pattern that is technically allowed by the shared style.
- Your project needs an extra class-docstring section beyond the built-in set (Summary, Scope, Responsibilities, Guarantees, Subclassing, Notes, Type Parameters, Attributes) — for example, to document generation rules for a data-set-initializer class or field-level semantics that don't fit `Attributes:`. You declare it once in `[tool.pcf] extra_docstring_sections` and describe its content rules in the overlay; `lazy-python.docstring-writer` then writes it on every dispatch.
- Your project has private attributes or `@property` methods that should legitimately appear in a class's `Attributes:` section — you declare the marker attribute(s) that exempt a class via `[tool.pcf] d2_exempt_marker_attrs` and document the convention in the overlay.
- Your project exposes a log-level suppression helper or a test generator import path that `lazy-python.test-writer` should use in every test file.

## How it fits together

The overlay lives in four files, one per topic, each matching a plugin reference file:

- `docs/guidelines/coding_guidelines.md` extends `lazy-python.coding-guidelines.md`
- `docs/guidelines/documenting_guidelines.md` extends `lazy-python.documenting-guidelines.md`
- `docs/guidelines/testing_guidelines.md` extends `lazy-python.testing-guidelines.md`
- `docs/guidelines/checking_guidelines.md` extends `lazy-python.checking-guidelines.md`

After `/lazy-python.install` Step 5 runs, each file exists as a stub with the header `# Project additions to <topic>`. You add content below that header. The stubs are left untouched on re-runs — the installer never overwrites existing overlay content.

This follows the same File-sync policy `/lazy-python.install` applies to every artifact it manages, but the overlay gets the friendliest treatment in it: `pyproject.toml` and the `docs/guidelines/*.md` overlays are both consumer-owned config, so a missing stub is a clean, non-contradictory write and an existing stub — however you've edited it — is left alone. A stub versus your edited content is never treated as a conflict; Step 5 never interrupts you with a merge question over these files.

**Two overlay mechanisms, not one.** Docstring conventions split across two places depending on whether the rule is mechanical or prose:

- **`docs/guidelines/documenting_guidelines.md`** — the content rules for any extra section you register (what belongs in it, how to phrase it) and any narrative conventions the checker can't enforce mechanically.
- **`pyproject.toml` `[tool.pcf]`** — the mechanical declarations that the checker and the writer agent both need to parse: `extra_docstring_sections` (section name, list style, order anchor, optional `ref_exempt` flag for sections whose body carries `# REF:` lines), `d2_exempt_marker_attrs` (class attribute names whose declaration exempts a class from the private-attributes-in-Attributes check), and `private_name_allowlist` (private identifiers tolerated in docstring narrative). The shipped `pyproject-defaults.toml` template ships all three as commented-out examples under `[tool.pcf]`.

**How `lazy-python.docstring-writer` uses the overlay.** Step 1 of the agent always reads `lazy-python.documenting-guidelines.md` from the plugin, then attempts to read `${CLAUDE_PROJECT_DIR}/docs/guidelines/documenting_guidelines.md`. If the overlay file exists, its rules are merged with the canon; overlay rules win on conflict. The agent also reads the `## Documenting` section of `CLAUDE.md` as a third overlay layer for project-wide notes. Section registration itself is read from `pyproject.toml` `[tool.pcf]` rather than the overlay — the overlay supplies the section's content rules, `[tool.pcf]` supplies its name, order, and style. If none of these optional files or settings exist the agent proceeds with the project-neutral canon alone: no extra sections, no private-attribute escape hatch.

**How `lazy-python.test-writer` uses the overlay.** Step 1 of the agent reads `lazy-python.testing-guidelines.md` and `lazy-python.checking-guidelines.md` from the plugin, then attempts to read `${CLAUDE_PROJECT_DIR}/docs/guidelines/testing_guidelines.md` and `${CLAUDE_PROJECT_DIR}/docs/guidelines/checking_guidelines.md`. The overlay is the only place to declare your project's base test class, aggregate test file patterns, and log-level helper — if the overlay is silent, the agent falls back to the generic `<YourBaseTest>` placeholder and asks you. The `## Testing` section of `CLAUDE.md` serves as a third layer for project-wide notes.

**How the checker uses it.** `chk-py` applies the mechanical rules from `pyproject.toml` plus the configured checker stack, including whatever `[tool.pcf] extra_docstring_sections`, `d2_exempt_marker_attrs`, and `private_name_allowlist` you've declared. The overlay guideline files are prose conventions for writer agents, not checker config. If you introduce a project-specific rule that needs mechanical enforcement beyond the docstring-section machinery, add the corresponding setting to `pyproject.toml` directly (the `[tool.ruff]`, `[tool.mypy]`, or `[tool.pylint]` sections that `/lazy-python.install` bootstrapped).

**Conflict resolution.** When the overlay repeats a rule from the canon with a different value, the overlay wins. When it adds a new rule not present in the canon, that rule applies in addition. There is no syntax for "delete a canon rule" — to neutralise a canon rule, override it with the exception you want to allow and document the reason in a comment.

## Common adjustments

**Setting a base test class.** In `docs/guidelines/testing_guidelines.md`, add a section that names the base class to inherit from for each test type your project uses (unit tests, integration tests, async tests). `lazy-python.test-writer` reads this on every dispatch and substitutes the real class name where the canon uses `<YourBaseTest>`.

**Declaring aggregate test file patterns.** In `docs/guidelines/testing_guidelines.md`, add a section describing any aggregate test files that validate many sibling classes at once. When declared, `lazy-python.test-writer` skips individual test files for the covered classes rather than generating per-class files that would duplicate coverage.

**Declaring a log-level suppression helper.** In `docs/guidelines/testing_guidelines.md`, name the context manager your project exposes for suppressing expected warning or error logs during tests (e.g. `with_log_level`). `lazy-python.test-writer` uses this helper in fixture and setup code rather than leaving the generic placeholder.

**Registering an extra class-docstring section.** In `pyproject.toml`, add a `[[tool.pcf.extra_docstring_sections]]` table with `name`, `style` (`"bulleted"`, `"definition"`, or `"plain"`), and an `after` / `before` order anchor naming a built-in section or a previously declared entry (an unresolved anchor appends the section at the end of the order). Set `ref_exempt = true` if the section's body carries `# REF:` lines. Then describe the section's content rules — what belongs in it and how to phrase it — in `docs/guidelines/documenting_guidelines.md`. `lazy-python.docstring-writer` reads both before writing the section and will never invent it in a project that hasn't registered it.

**Declaring the private-attribute escape hatch.** If your project has classes where private fields or `@property` methods should legitimately appear in `Attributes:`, add the marker attribute name(s) to `pyproject.toml` `[tool.pcf] d2_exempt_marker_attrs`. A class is exempt when it declares one of the listed attribute names. Document the convention (which marker names exist and what they signal) in `docs/guidelines/documenting_guidelines.md`.

**Tightening the copyright header.** In `docs/guidelines/coding_guidelines.md`, replace the canonical placeholder header with your project's exact copyright line, license identifier, and any required SPDX header. Every new file that either writer agent touches after this change will use the project-specific form.

**Adding a project-specific naming rule.** Add a named section to the relevant overlay file. The heading structure does not need to match the canon — agents read the whole file and merge the rules — but clear section names (matching the canon's style) make the intent unambiguous and reduce the chance of misinterpretation.

**Scaffolding the stubs if they are missing.** If the `docs/guidelines/` files were never created — for example, you installed the plugin before Step 5 was added — re-run `/lazy-python.install`. The install wizard is idempotent; Step 5 skips any stub file that already exists and creates only the missing ones. It will not create a stub if all four are already present.

## Where this fits

The overlay files are scaffolded by the `install-and-audit` block's `/lazy-python.install` Step 5. The canon they extend lives in the `discipline` block — the five reference guidelines (`coding-guidelines`, `documenting-guidelines`, `testing-guidelines`, `checking-guidelines`, `guidelines-index`) that writer agents load before reading your overlay. The `agents` block is where `lazy-python.docstring-writer` and `lazy-python.test-writer` live; their full dispatch discipline is described in the agents block article. The `add-project-overlay` walkthrough covers the end-to-end flow: scaffold stubs, fill them in, and confirm the delta appears in the next writer-agent dispatch.
