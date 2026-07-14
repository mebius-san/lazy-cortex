---
chapter_type: block
summary: Manual code-quality review via /lazy-python.check-style plus two dispatch-ready writer agents that enforce project conventions for docstrings and tests.
last_regen: 2026-07-14
diagram_spec:
  anchor: "How the three members fit together"
  request: "Flow showing three parallel entry points: (1) user invokes /lazy-python.check-style — reads canon coding + documenting guidelines and project overlay, runs seven-category manual review, then chk-py per-file (or per-dir when >3 files share a directory) and whole-project, then tst-py per touched module; (2) user or skill dispatches lazy-python.docstring-writer — reads documenting guidelines and overlay, writes or fixes docstrings only, runs pre-return self-check (8 semantic checks), then chk-py; (3) user or skill dispatches lazy-python.test-writer — reads testing and checking guidelines and overlay, writes test files only (no production code), then chk-py and tst-py. Highlight the shared guideline-read step and the no-production-code constraint on test-writer."
  kind_hint: flow
source_skills:
  - lazy-python.check-style
  - lazy-python.docstring-writer
  - lazy-python.test-writer
---
# Code quality agents — review, document, test

Every meaningful batch of Python edits touches three concerns a linter alone cannot resolve: whether the code matches the project's style and docstring contracts, whether every public API is documented to spec, and whether tests verify documented behaviour rather than reverse-engineering the implementation. This block owns all three through three purpose-built members.

`/lazy-python.check-style` is the manual review entry point you run before committing. It opens by loading both the plugin's canonical guidelines and the project overlay, then walks your change set through seven inspection categories — the ones the automated tools cannot see — before handing off to `chk-py` and `tst-py` for a full gate. `lazy-python.docstring-writer` is a dispatched agent whose only job is writing and fixing docstrings; it never touches production code and self-checks eight semantic failure patterns before returning. It is project-neutral by design — its section set and its rules for private-attribute exposure come from your project's declarations, not from anything baked into the agent. `lazy-python.test-writer` is a second dispatched agent that writes test files covering all seven Paranoid-Testing categories, deriving every expected value from the documented contract rather than from the implementation.

All three members share one non-negotiable design: guidelines are never cached. On every invocation, each member re-reads the plugin's canonical reference files from `${CLAUDE_PLUGIN_ROOT}/references/` and the project overlay from `docs/guidelines/`, so a rule change in either layer takes effect immediately.

## When you'd use this

- You've finished a batch of Python edits and want a thorough review before committing — including semantic docstring quality, contract drift, and guard-clause placement, which `chk-py` cannot verify.
- A class is missing docstrings or has ones that have drifted from the project's documentation conventions; you want them written or corrected to spec without touching production code.
- Your project needs a docstring section the canon doesn't define — a domain-specific block your team always wants on certain classes — and you want the writer agent to honour it consistently instead of improvising a new shape each dispatch.
- A new class arrived without tests, or an existing class changed its public contract and the test file needs to track it; you want tests derived from the documented contract, not from what the implementation happens to return.
- You want consistent results across Claude Code sessions — every dispatch of the writer agents starts from the same authoritative source, not from whatever was loaded in the calling session.
- Another skill needs docstrings or tests produced as part of a larger workflow; both writer agents are designed to be dispatched from within other skills.

## How it fits together

`/lazy-python.check-style` is a seven-step workflow. It starts by reading the coding and documenting guidelines from the plugin plus your project overlay — both layers, every run, regardless of what is already in context. It then enumerates the modified Python files via `git diff` (or uses any file paths you pass explicitly). For each file it walks seven inspection categories: docstring quality, contract consistency, guard clauses, method organisation, naming, structural rules, and comment preservation. Only after the manual pass does it run `chk-py all <file>.py -q` per file — switching to `chk-py all <dir>/ -q` when more than three modified files share a directory — then `chk-py all -q` across the whole project, then `tst-py <module> -q` for each touched module. Every violation from either pass is fixed in a targeted single-line edit, and the skill re-verifies before it closes.

`lazy-python.docstring-writer` is a focused seven-step agent. On dispatch it reads the documenting guidelines plus your overlay, reads the target files, identifies every missing or non-compliant docstring, and writes or fixes them — never touching any production code. Its scope is class, method, and property docstrings only; it never adds a module-level docstring to a regular source file. Under the canon, module docstrings belong to `__init__.py` only — a new `__init__.py` gets its package docstring from the `init-template.py` scaffold, and every other `.py` file carries no module docstring at all. The canonical section order (Summary, Scope, Responsibilities, Guarantees, Subclassing, Notes, Type Parameters, Attributes for classes) is fixed, but any class-docstring section your project registers is inserted at its configured position alongside them — the agent carries no hardcoded knowledge of what those extra sections mean; it defers entirely to what the project declares. The same project-neutral stance applies to the `Attributes` section: private fields and `@property` methods are excluded unless the project has declared an escape hatch for them, and the agent invents nothing beyond what that declaration covers. Before returning the agent walks a mandatory pre-return self-check across eight semantic failure patterns: HOW-not-WHAT leakage, comma-chained call sequences in Summary, private internals in prose, algorithm narration in Scope, speculative future-plans, tautology on dunder summaries, missing `Returns:` sections, and private attributes in `Attributes:`. After the self-check it runs `chk-py` on every changed file. The full class, method, and property docstring rule set is embedded directly in the agent body, so the rules travel with every dispatch.

`lazy-python.test-writer` is an eight-step agent. It reads the testing and checking guidelines plus your overlay first, then reads the production class fully — paying special attention to the docstrings, because the docstring is the specification. It enumerates every testable claim: `__init__` paths, public methods, properties, documented guarantees, documented exceptions, and operator overloads. Tests are written across all seven Paranoid-Testing categories: happy path, wrong or invalid arguments, boundary values, error conditions, state transitions, operator overloading, and documented guarantees. A dedicated step then adds class and method docstrings to the test file itself (`"Test unit for ..."` on the class, `"Test that ..."` on each method), so the test file meets the same documentation standard as production code. When a correctly-specified test fails against the current implementation, the agent marks it `# FAILS: <reason>` and reports the divergence rather than silently adjusting the test. It verifies with `chk-py` and `tst-py` before returning and never writes a single line of production code.

The two writer agents and the review skill have a clean separation of concern: `/lazy-python.check-style` is the audit-and-fix entry point you run on your change set; the writer agents are composition units you (or another skill) dispatch when work needs to be created from scratch or brought up to a standard the review step surfaced.

## Common adjustments

**Passing an explicit file list to check-style.** If you pass file paths when invoking `/lazy-python.check-style`, the skill uses those instead of running `git diff` to find the change set. This is useful for reviewing a file that is not yet staged, or for re-checking a specific file after a targeted fix.

**Overlay rules take precedence.** Both writer agents apply the project overlay over the plugin canon when there is a conflict. The overlay for docstrings lives in `docs/guidelines/documenting_guidelines.md`; the overlays for tests live in `docs/guidelines/testing_guidelines.md` and `docs/guidelines/checking_guidelines.md`. Add or override rules there; the agents pick them up on the next dispatch without any plugin change. Run `/lazy-python.install` to get stub files for those overlay paths if they don't exist yet.

**Registering a project-specific docstring section.** If your project wants a class-docstring section beyond the canonical set (Summary, Scope, Responsibilities, Guarantees, Subclassing, Notes, Type Parameters, Attributes), declare it under `[tool.pcf] extra_docstring_sections` in `pyproject.toml` — name, list style, and an order anchor (`after` / `before` another section) — then document its content rules in the project overlay. `lazy-python.docstring-writer` inserts it at the configured position and follows the overlay's rules for it; it never invents such a section on its own, and a project that declares nothing gets only the canonical set.

**Declaring the private-attribute escape hatch.** By default, private fields and `@property` methods never appear in a class's `Attributes` section. If your project genuinely needs some documented (e.g. a marker attribute other tooling reads), list them under `[tool.pcf] d2_exempt_marker_attrs` in `pyproject.toml` and describe the convention in the overlay. `lazy-python.docstring-writer` only documents names covered by that declared list — it does not extend the exemption to any other private name.

**Module docstrings are not part of docstring-writer's job.** If you dispatch `lazy-python.docstring-writer` expecting it to add a missing module-level docstring to a regular `.py` file, it won't — that's expected, not a gap. The canon only mandates a module docstring on `__init__.py`, and that one is seeded once by the `init-template.py` scaffold when the file is first created, not backfilled by the writer agent on later dispatches. If an existing `__init__.py` is missing its package docstring, add it by hand against the canon's `__init__.py` File Patterns section (or re-scaffold the file).

**Test base class mapping.** `lazy-python.test-writer` inherits the correct base test class from the overlay's `## Testing` declarations in `CLAUDE.md` or in `docs/guidelines/testing_guidelines.md`. When the overlay is silent on which base class to use for a given production-class category, the agent asks before proceeding — it never invents a class variable name or base class.

**Aggregate test files.** Some projects validate many sibling classes from one module through a single aggregate test file using `BaseClass.__subclasses__()` auto-discovery. When such a file is declared in the testing overlay, `lazy-python.test-writer` honours it: classes it covers do not get individual test files, and the aggregate file is placed at the root of the relevant test module directory.

**Implementation-vs-spec mismatches.** When `lazy-python.test-writer` finds that a correctly-specified test fails against the current implementation, it flags the test with `# FAILS:` rather than adjusting it. That flag is a prompt to investigate the implementation or update the docstring — not a signal to retune the test.

**Narrowing the per-file vs whole-project check.** Both agents and the review skill always run `chk-py all -q` (no path argument) as a final whole-project sweep, after the per-file pass is clean. If the project is large and the whole-project sweep is slow, the per-file pass alone is sufficient for a focused fix; the whole-project run is the regression guard. When invoking `tst-py`, always pass bare module names — never file paths or `.py` extensions.

## How the three members fit together

```mermaid
%%{init: {'themeVariables':{'background':'transparent','lineColor':'#000','textColor':'#000','edgeLabelBackground':'#fff'},'themeCSS':'.edgeLabel{background-color:transparent!important}.edgeLabel p{background-color:transparent!important}','flowchart':{'diagramPadding':5,'useMaxWidth':true}}}%%
flowchart LR
  invokeCheckStyle[User invokes\n/lazy-python.check-style]
  invokeDocstringWriter[User or skill dispatches\nlazy-python.docstring-writer]
  invokeTestWriter[User or skill dispatches\nlazy-python.test-writer]

  readCanonGuidelines[Read canon coding +\ndocumenting guidelines\n+ project overlay]
  readDocGuidelines[Read documenting\nguidelines + overlay]
  readTestGuidelines[Read testing +\nchecking guidelines\n+ overlay]

  manualReview[Run seven-category\nmanual review]
  writeDocstrings[Write or fix\ndocstrings only]
  writeTestFiles[Write test files only\n— no production code]

  noProductionCode{{No production\ncode constraint}}

  selfCheck[Run pre-return\nself-check\n8 semantic checks]

  fileCountGuard{More than 3 files\nshare a directory?}

  chkPyPerFile[chk-py per-file]
  chkPyPerDir[chk-py per-dir]
  chkPyWholeProject[chk-py whole-project]
  tstPyTouchedModules[tst-py per\ntouched module]

  chkPyDocstring[chk-py per-file]
  chkPyTestWriter[chk-py per-file]
  tstPyTestWriter[tst-py per\ntouched module]

  invokeCheckStyle -->|starts| readCanonGuidelines
  invokeDocstringWriter -->|starts| readDocGuidelines
  invokeTestWriter -->|starts| readTestGuidelines

  readCanonGuidelines -->|guidelines loaded| manualReview
  readDocGuidelines -->|guidelines loaded| writeDocstrings
  readTestGuidelines -->|guidelines loaded| noProductionCode

  noProductionCode -->|constraint enforced| writeTestFiles

  manualReview -->|review done| fileCountGuard
  fileCountGuard -->|yes| chkPyPerDir
  fileCountGuard -->|no| chkPyPerFile
  chkPyPerDir -->|dir check done| chkPyWholeProject
  chkPyPerFile -->|file checks done| chkPyWholeProject
  chkPyWholeProject -->|project check done| tstPyTouchedModules

  writeDocstrings -->|docstrings written| selfCheck
  selfCheck -->|self-check passed| chkPyDocstring

  writeTestFiles -->|tests written| chkPyTestWriter
  chkPyTestWriter -->|check passed| tstPyTestWriter

  classDef entry fill:#1e3a5f,stroke:#4a90e2,color:#fff
  classDef guard fill:#5f4a1e,stroke:#e2a14a,color:#fff
  classDef action fill:#1e5f3a,stroke:#4ae290,color:#fff
  classDef success fill:#0d4d2a,stroke:#4ae290,color:#fff,stroke-width:2px
  classDef error fill:#5f1e1e,stroke:#e24a4a,color:#fff,stroke-width:2px

  class invokeCheckStyle entry
  class invokeDocstringWriter entry
  class invokeTestWriter entry
  class readCanonGuidelines action
  class readDocGuidelines action
  class readTestGuidelines action
  class manualReview action
  class writeDocstrings action
  class writeTestFiles action
  class noProductionCode error
  class selfCheck action
  class fileCountGuard guard
  class chkPyPerFile action
  class chkPyPerDir action
  class chkPyWholeProject action
  class tstPyTouchedModules success
  class chkPyDocstring success
  class chkPyTestWriter action
  class tstPyTestWriter success
```

## See also

- [discipline](../discipline.md) — The always-loaded rules and reference guidelines both writer agents consult on every dispatch.
- [checkers](../checkers.md) — The `chk-py` and `tst-py` CLI wrappers these agents call to gate their output.
- [overlay](../overlay.md) — How to add project-specific rules that override the canon the writer agents read.
- [scaffold](../scaffold.md) — The `init-template.py` / `python-template.py` scaffold pair that seeds the module docstring on `__init__.py` and leaves regular modules without one.
- [write-tests-for-new-class](../walkthroughs/write-tests-for-new-class.md) — End-to-end walkthrough of dispatching `lazy-python.test-writer` and verifying the result with `tst-py`.
