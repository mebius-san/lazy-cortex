---
chapter_type: block
summary: Project-specific guideline files in docs/guidelines/ let you extend or override the lazycortex-python canon per repo without touching plugin-managed files.
last_regen: 2026-06-01
no_diagram: true
source_skills: []
---
# Per-repo overlay guidelines

Every Python project has conventions that belong to it alone — a base test class, a copyright header format, internal naming prefixes, domain-specific patterns. The overlay convention is how you supply those specifics without forking the plugin or editing files it owns. You add content to `docs/guidelines/` files; writer agents and the checker read the overlay after the canon on every dispatch, and overlay rules win on conflict.

When `/lazy-python.install` runs its Phase 5, it scaffolds four stub files under `docs/guidelines/` with placeholder headers. You fill them in. The plugin never touches these files again after the initial scaffold — they are yours to maintain.

## When you'd use this

- Your project has a base test class that every test should inherit from, and you want `lazy-python.test-writer` to use it automatically without being told each time.
- Your copyright header format differs from the example in `lazy-python.coding-guidelines.md` and you want the correct version in every new file.
- You have internal naming conventions (module prefixes, enum naming patterns, import grouping rules) that extend the shared canon rather than replacing it.
- You want to tighten a rule the canon leaves flexible — for example, mandating a specific maximum function length or disallowing a pattern that is technically allowed by the shared style.
- Your project's `DOC(…):` marker groups have concrete names and you want `lazy-python.docstring-writer` to know them rather than leaving placeholder references.

## How it fits together

The overlay lives in four files, one per topic, each matching a plugin reference file:

- `docs/guidelines/coding_guidelines.md` extends `lazy-python.coding-guidelines.md`
- `docs/guidelines/documenting_guidelines.md` extends `lazy-python.documenting-guidelines.md`
- `docs/guidelines/testing_guidelines.md` extends `lazy-python.testing-guidelines.md`
- `docs/guidelines/checking_guidelines.md` extends `lazy-python.checking-guidelines.md`

After `/lazy-python.install` Phase 5 runs, each file exists as a stub with the header `# Project additions to <topic>`. You add content below that header. The stubs are left untouched on re-runs — the installer never overwrites existing overlay content.

**How writer agents use them.** Both `lazy-python.docstring-writer` and `lazy-python.test-writer` have an explicit first step that reads the relevant plugin reference and then the matching overlay from `${CLAUDE_PROJECT_DIR}/docs/guidelines/<topic>_guidelines.md`. If the file exists, its rules are merged with the canon; overlay rules override on conflict. If the file does not exist, the agent proceeds with the canon alone. Neither agent requires the overlay to be present.

**How the checker uses it.** `chk-py` applies the mechanical rules from `pyproject.toml` plus the configured checker stack. The overlay guideline files are prose conventions for writer agents, not checker config. If you introduce a project-specific rule that needs mechanical enforcement, add the corresponding setting to `pyproject.toml` directly (the `[tool.ruff]`, `[tool.mypy]`, or `[tool.pylint]` sections that `/lazy-python.install` Phase 3 bootstrapped).

**Conflict resolution.** When the overlay repeats a rule from the canon with a different value, the overlay wins. When it adds a new rule not present in the canon, that rule applies in addition. There is no syntax for "delete a canon rule" — to neutralise a canon rule, override it with the exception you want to allow and document the reason in a comment.

## Common adjustments

**Setting a base test class.** In `docs/guidelines/testing_guidelines.md`, add a section that names the base class to inherit from for each test type your project uses (unit tests, integration tests, async tests). `lazy-python.test-writer` reads this on every dispatch and substitutes the real class name where the canon uses `<YourBaseTest>`.

**Documenting `DOC(…):` marker groups.** In `docs/guidelines/documenting_guidelines.md`, list the `DOC(…)` group names your project uses and what each one triggers. `lazy-python.docstring-writer` reads this before writing Generation Rules sections and will reference the correct group names rather than leaving `DOC(<group>)` placeholders.

**Tightening the copyright header.** In `docs/guidelines/coding_guidelines.md`, replace the canonical placeholder header with your project's exact copyright line, license identifier, and any required SPDX header. Every new file that `lazy-python.docstring-writer` touches after this change will use the project-specific form.

**Adding a project-specific naming rule.** Add a named section to the relevant overlay file. The heading structure does not need to match the canon — agents read the whole file and merge the rules — but clear section names (matching the canon's style) make the intent unambiguous and reduce the chance of misinterpretation.

**Scaffolding the stubs if they are missing.** If the `docs/guidelines/` files were never created — for example, you installed the plugin before Phase 5 was added — re-run `/lazy-python.install`. The install wizard is idempotent; Phase 5 skips any stub file that already exists and creates only the missing ones. It will not create a stub if all four are already present.

## Where this fits

The overlay files are scaffolded by the `install-and-audit` block's `/lazy-python.install` Phase 5. The canon they extend lives in the `discipline` block — the five reference guidelines (`coding-guidelines`, `documenting-guidelines`, `testing-guidelines`, `checking-guidelines`, `guidelines-index`) that writer agents load before reading your overlay. The `add-project-overlay` walkthrough covers the end-to-end flow: scaffold stubs, fill them in, and confirm the delta appears in the next writer-agent dispatch.
