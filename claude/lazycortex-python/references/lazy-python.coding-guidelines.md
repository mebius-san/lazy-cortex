---
description: Code style, formatting, naming, imports, class/method design, error handling, debug logging, and module-specific patterns for Python projects that adopt these conventions.
---
# Coding Guidelines

Code style, formatting, naming, imports, class and method design, error handling,
debug logging, and module-specific patterns for Python projects that adopt these
conventions.


# AI Contract

## AI Output Contract (Overrides)
- These guidelines override any external style guides. When in doubt, omit rather than guess.
- You must newer remove or alter `TODO:`, `TMP:`, `DBG:`, `REF:`, `opt:`, `guard:`, `DOC(…):` comments in the code.

## AI MCP Tools Usage Contract (Overrides)
- Always use the Context7 MCP server to fetch the most up-to-date documentation when asked about specific libraries or frameworks.


## AI Behavioral Guidelines

### Code Quality Rules
- **Always choose the simplest solution first.** No unnecessary copies, no intermediate data structures, no over-engineering. If a simple loop works, use a simple loop.
- **Think before coding.** Before writing any code, ask: "Is there a simpler way?" If yes, use it.
- **Do not create unnecessary intermediate objects.** For example, don't use `dict(iterator)` when you can iterate directly; don't copy via `export_dict()` when a new empty instance suffices.
- **No local aliases for built-in accessors.** Never assign `inst = self.__dict__` or similar aliases for `self.__dict__`, `self.__class__`, etc. Use the original accessor directly everywhere. **Exception:** capturing `self.__class__` for `super()` calls inside nested functions is allowed because Python requires an explicit class reference in that context.

### Communication Rules
- **Always answer "why" questions before making any edits.** When the user asks "why did you do X?", explain first, then wait for approval before changing code.
- **Never say, "I'll keep this in mind" or similar.** You have no persistent memory between sessions — only these guidelines persist. Be honest about this.
- **Do not jump to editing.** When the user points out a problem or asks a question, respond with an explanation first. Only edit after the user confirms or instructs you to proceed.
- **When the user asks a question, only answer the question — do not modify any code.** Questions include requests for suggestions, explanations, analysis, opinions, or any inquiry that does not contain an explicit instruction to change code. You must never create, edit, or delete any project files in response to a question. Wait for the user to explicitly tell you to make changes before touching any code.

### Safety Rules
- **Never run `git checkout`, `git restore`, or any command that discards uncommitted changes without explicit user approval.** Always ask the user first before reverting, checking out, or discarding any file changes. Uncommitted work may contain important additions that are not recoverable.
- **Always work with the current version of files unless directly asked to change this behavior.** Never assume the committed version is the correct one. The working copy may contain important uncommitted additions.



# General Principles

## Python Version and Compatibility
- Target Python 3.12+.
- Use modern Python features like match / case statements where appropriate.
- Leverage new union syntax (`|`) for type hints when suitable.

## Code Style Philosophy
- Prioritize readability and maintainability over brevity.
- Follow the principle of the least surprise.
- Use explicit over implicit approaches.
- Maintain consistency with existing codebase patterns.
- Prefer composition to inheritance when designing class relationships.


# Code Formatting and Visual Structure

## Code Formatting
- In function calls with named arguments, always put spaces around '=' (use `width = self.width`, not `width=self.width`).
- Use two spaces for indentation (except for continuation lines in function parameters).
- Maintain consistent indentation (two spaces for continuation lines in function parameters).
- Align parameters vertically when they span multiple lines.
- In list, dict, and set **literals and comprehensions** (and generator expressions inside braces/brackets), always put a space after the opening bracket and before the closing bracket.
- Correct: `[ 1, 2, 3 ]`, `{ key: val }`, `[ member for member in cls if member.is_valid ]`, `{ key: val for key, val in items }`.
- Incorrect: `[1, 2, 3]`, `{key: val}`, `[member for member in cls if member.is_valid]`, `{key: val for key, val in items}`.

## Separator line rules
- A separator line must separate sections and top-level classes.
- `# ----------------------------------------------------------------------------------------`.
- All imports must be in the first section of the file.
- Must be used to separate top-level classes in the same file.
- Must not be used inside classes, methods, or functions.
- Must not be used inside imports.
- Must not have blank lines after separator and before class definition.

## Blank line rules
- Always use exactly 3 blank lines followed by a separator between a top-level class definition and other code.
- Always use exactly 2 blank lines between non-top-level class definitions and other code.
- Always use exactly 2 blank lines between any class definition inside methods/functions and other code.
- Always use exactly 2 blank lines between any top-level function and other code.
- Always use exactly 2 blank lines between any class method and other code (explicit override of PEP 8).
- Use 1 blank line between import groups and within methods/functions.
- Use 1 blank line between logical sections within methods/functions.
- Exception (nested definitions only): Inside the body of a class or a method, place exactly 1 blank line between the parent's docstring and the immediately following nested def/class definition. This exception applies only within the same enclosing block to separate the parent docstring from the nested definition. It does not apply to top‑level method boundaries, where the "exactly 2 blank lines between methods" rule remains in force.
- Non-cumulative rule: These blank line rules are mutually exclusive for any single boundary. Do not apply multiple rules to the same code fragment in sequence. For example, the "2 blank lines between methods" rule and the "1 blank line between a parent docstring and a nested definition" rule must never be combined to create 3 blank lines. Always choose the single applicable rule for the given context.
- Overload stubs: Use exactly 1 blank line between consecutive `@overload` decorated function stubs, and exactly 1 blank line between the last `@overload` stub and the actual implementation. This rule applies regardless of the "2 blank lines between methods" rule. See the Overload Stubs Pattern section below.

## Function/Method Signatures — Multi-line Wrapping
- Keep the function name and opening parenthesis on the same line. Do not place the opening parenthesis on its own line.
- If parameters do not fit on one line (or the line would exceed the 117-character limit), break after self, * (or after * for functions) and put one parameter per line. End each line with a comma.
- Keep * after cls/self on its own line, put * on a separate line if there are other positional parameters.
- Vertically align all continued parameters to the same column.
- Place the closing parenthesis `)` on the same line as the last parameter, followed by the return annotation and the colon on that same line.
- Use keyword-only parameters with * when there are multiple parameters (see Parameter Design).
- Short signatures that fit within the limit may stay on one line. In particular, if the only "parameter" before the keyword-only arguments is bare `*` and there is a single keyword argument, keep everything on one line (do not break after `*`). Example: `def create_plain(*, proc_time: float | None = None) -> Result:`.
- This rule complements “Align parameters vertically when they span multiple lines.” and the two-space indentation policy for continuation lines in parameter lists.
- Apply this consistently across methods and functions, including `__init__`.
- Correct examples.
```python
def _build_worker(self, *,
                  mode: RunMode = RunMode.INVALID,
                  store: Store | None = None) -> Worker | None:

def move(self,
         src: Location,
         dst: Location,
         *,
         mode: PathMode = PathMode.SAFE,
         timeout_ms: int = 0,
         rng: Rng | None = None) -> bool:
```
- Incorrect (opening parenthesis and closing paren on separate lines).
```python
def _build_worker(
                  self, *,
                  mode: RunMode = RunMode.INVALID,
                  store: Store | None = None
                 ) -> Worker | None:

def move(self, src: Location, dst: Location, *,
         mode: PathMode = PathMode.SAFE,
         timeout_ms: int = 0,
         rng: Rng | None = None) -> bool:
```

## Long String Formatting
- For long strings that exceed the line length limit, use multiline string concatenation instead of triple-quoted strings (`""" ... """`).
- Use parentheses to group the concatenated string parts.
- Each line should be a separate string literal, properly indented.
- This approach provides better control over whitespace and line breaks.
- Correct example:
```python
message = (
  "This is a long message that needs to span multiple lines. "
  "Each part is a separate string literal that Python will "
  "automatically concatenate at compile time."
)
```
- Incorrect example (using triple quotes):
```python
message = """This is a long message that needs to span multiple lines.
Each part includes unwanted newlines and leading whitespace
that can cause formatting issues."""
```

## Conditional Statements
- **Use implicit booleanness for empty-collection checks.** Never compare to `[]`, `{}`, or `()` — use truthiness instead. This applies everywhere: `if`, `while`, `assert`, `return`, ternary expressions, etc.
  - Correct: `if not items:`, `while data:`, `assert not result`, `return bool(entries)`
  - Wrong: `if items == []`, `if data == {}`, `assert result == ()` (triggers pylint C1803)
- Avoid unnecessary `elif` after `return`, `raise`, `break`, or `continue`. Since these statements exit the current block, the following condition does not need `elif`—use `if` instead.
- Correct example:
```python
if isinstance(data, dict):
  return process_dict(data)
if isinstance(data, list):
  return process_list(data)
return data
```
- Incorrect example:
```python
if isinstance(data, dict):
  return process_dict(data)
elif isinstance(data, list):  # unnecessary "elif" after "return"
  return process_list(data)
return data
```
- **Prefer init-before-branch over if/else for default values.** When a variable needs a default value and is conditionally reassigned, initialize it with the default first and use a plain `if` — do not use `if/else` to assign both branches.
- Correct example:
```python
deleted_count = 0
if del_age is not None:
  deleted_count = compute_deleted(del_age)
```
- Incorrect example:
```python
if del_age is not None:
  deleted_count = compute_deleted(del_age)
else:
  deleted_count = 0
```
- **Prefer walrus `:=` for fetch-then-check patterns.** When the next line of code only checks the result of an assignment to decide whether to continue, fold the assignment into the condition with `:=` instead of writing two separate lines. The intermediate name is still available below the guard for use within the surviving branch.
- Correct examples:
```python
if not (prop_mods := tracker.modifiers.get(prop_name)):
  continue
# prop_mods is bound and truthy here

if (existing := self.get_modifier(prop_name, name)) is None:
  self.set_modifier(prop_name, name, mod)
  continue
# existing is bound and non-None here
```
- Incorrect example (separate lines that only feed the guard):
```python
prop_mods = tracker.modifiers.get(prop_name)
if not prop_mods:
  continue
```


# File Organization

## Copyright Headers
Always include the project's standard copyright/license header at the top of all source files. Example shape (replace the owner and license text with your project's actual values):
```python
#  Copyright (c) <YEAR> <Project Owner>. All rights reserved.
#  -
#  <License notice or proprietary terms describing how this file may be used.>
```

## Error Suppression
- **Never suppress linter or type-checker errors** (`# type: ignore`, `# noqa`, `# pylint: disable`, etc.) without explicit user approval.
- If a linter or type checker reports an error, fix the root cause.
- If suppression is truly the only option, ask the user first and explain why.
- When suppression is approved, add a `# waiver: <reason>` comment (see Waiver Comments below).
- **No meaningless code changes for tool warnings.** Do not add redundant guards, restructure control flow, or otherwise change working code solely to silence a static analysis tool (PyCharm, mypy, etc.) when the change has no real effect on runtime behavior or type correctness. Instead, add a waiver or `# noinspection` comment that explains (a) why the code is correct as-is and (b) what limitation of the checker triggers the warning.
- **Abstract intermediate classes**: when an intermediate class in an inheritance chain intentionally does not override an abstract method (because concrete subclasses provide the implementation), suppress with `# pylint: disable=abstract-method` and a `# waiver:` comment. Both comments must be placed **inside the class body, immediately after the docstring** — never inline on the `class` line or above it. Do not copy empty `NotImplementedError`-raising stubs just to silence the warning.

## Waiver Comments
- When code must deviate from a coding rule, add a `# waiver: <explanation>` comment explaining why the exception is justified.
- **Prefer line comments over side comments.** Place waiver and `# noinspection` comments on the line immediately above the exempted code, not as trailing (side) comments on the same line. Side comments reduce readability and risk exceeding the line-length limit.
- **`# noinspection` must be standalone.** PyCharm only recognizes `# noinspection InspectionName` when the line contains nothing else after the inspection name. Never append a dash, em-dash, or explanation on the same line. Place the explanation on a separate comment line immediately below:
  ```python
  # noinspection PyCallingNonCallable
  # guarded by is-not-None; PyCharm doesn't narrow `type | None`
  result = factory(value)
  ```
- The waiver comment may be placed:
  - On the line immediately above the exempted code (preferred).
  - On the line immediately below the exempted code.
  - Inline on the same line as the exempted code (discouraged — use only when the line stays well under the length limit).
- The explanation after `waiver:` is mandatory and must be non-empty. A bare `# waiver:` without text is not accepted.
- Rules that commonly need a `# waiver:` comment:
  - Error suppression comments (`# type: ignore`, `# noqa`, `# pylint: disable`).
  - Local (in-function) imports.
  - `typing.cast()` usage.
  - Separator line format deviations.
  - Bare `type` annotations (use `type[SpecificClass]` instead).
  - `Any` annotations (use specific types instead; `*args`/`**kwargs` and dunder methods are auto-exempt).
- Correct example:
```python
# waiver: third-party API returns untyped dict, cast needed for downstream type safety
from typing import cast
```
- Incorrect example (missing explanation):
```python
# waiver:
from typing import cast
```

### Class-Level Waivers
- A `# waiver:` comment at **body indent level anywhere in the class body** (outside methods) acts as a **class-level waiver**.
- It covers all direct class-body statements (attributes, class variables) — no per-member waiver is needed.
- It does **not** cover code inside methods — those still need per-line waivers.
- `# type: ignore` must remain on each affected line (mypy only supports line-level suppression); the class-level waiver eliminates only the per-member `# waiver:` comments.
- Before (per-member waivers):
```python
class StatsInit(BaseInit, Generic[FieldType]):
  """..."""

  # waiver: assignment — default is float; base class converts to FieldType at init
  health:  FieldType = 0.0  # type: ignore[assignment]
  # waiver: assignment — default is float; base class converts to FieldType at init
  mana:    FieldType = 0.0  # type: ignore[assignment]
```
- After (class-level waiver):
```python
class StatsInit(BaseInit, Generic[FieldType]):
  """..."""

  # waiver: assignment — default is float; base class converts to FieldType at init

  health:  FieldType = 0.0  # type: ignore[assignment]
  mana:    FieldType = 0.0  # type: ignore[assignment]
```


## Module Structure
Organize modules in the following order:
1. Copyright header.
2. Module docstring — `__init__.py` only (see __init__.py File Patterns below). Regular source files carry no module docstring.
3. Imports (see Import Organization below).
4. Module-level constants, TypeVars, TypeAliases, and enums.
5. Classes and functions.

- **No module-level (global) mutable variables.** Do not create mutable variables at module scope. Module-level constants, TypeVars, TypeAliases, and enums are permitted.

## __init__.py File Patterns
- Use wildcard imports for module exports: `from .submodule import *`.
  - This import MUST go first before any other imports, except  `from __future__ import annotations`
- Group imports logically (core functionality first, then extensions).
- Do not add `from __future__ import annotations` if the file has no other imports and no meaningful code lines.
- Every source `__init__.py` under the main project package(s) must have a module-level docstring describing the
  package's purpose. Insert the docstring after the copyright header and before any imports. Follow this format:
  - Summary: One sentence describing the package's purpose.
  - Extended description (optional): 1–3 sentences on the package's role.
  - Subpackages (if any): `  name: Description.` (2-space indent, one per line).
  - Dependencies (if any): Which sibling packages this module imports from.
  - Dependents (if any): Which packages import from this one.
  - Omit empty sections entirely.


# Import Organization

## Import Order and Grouping
- Organize modules import in the following strict order of blocks:
  1. Future imports: `from __future__ import annotations`.
  2. Wildcard imports for module exports in `__init__.py` files only.
  3. Typing imports: `from typing import ...`, `from types import ...`.
  4. Standard library imports.
  5. Third-party imports.
  6. Local project imports.
  7. Local module imports.
  8. TYPE_CHECKING imports block.
- Blocks must be separated by a single blank line.
```python
from __future__ import annotations

from typing import Generic, TypeVar

from contextlib import contextmanager
import numpy as np

from myproject.utils import SingletonMeta
from myproject.core import (
  BaseClass,
  Entity,
  ValueType,
  Matrix,
)

from ..core import RunContext
from .types import (
  RunContextType,
  HandlerType,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import Any, Generator, Self

  from myproject.core import Entity
  from myproject.utils import (
    HelperOne,
    SingletonMeta,
  )
```

## Import Guidelines
- **Never use local (in-function or in-method) imports.** All imports must be at module level. If a circular import issue arises, ask the user for guidance instead of adding a local import.
  - **Exception — deferred-import libraries:** libraries listed in `docs/project_settings.md` under "Deferred-Import Libraries" must **always** be imported locally inside the method that uses them, never at module level. Add `# waiver: deferred import for optional dependency` on the preceding line and `# noqa: PLC0415` on the import line.
- Always use absolute imports for cross-package dependencies.
- Use full module and do not use submodule imports for cross-package dependencies (e.g., use `from myproject.core import BaseClass` instead of `from myproject.core.base_class import BaseClass`).
- Use submodule imports for local package dependencies (e.g., use `from .base_class import BaseClass` if the import is from the same package).
- Use relative imports (`.core`, `..core`, etc) for same-package or parent-package imports.
  - Do not use unnamed relative imports (e.g., `from .. import BaseClass`).
- When importing from a sibling subpackage, import from its `__init__.py` (the package), not from individual files inside it:
  - **WRONG:** `from .gcl.sec_manager import SecretStoreGcl` — reaches into the subpackage's internal file.
  - **RIGHT:** `from .gcl import SecretStoreGcl` — imports via the subpackage's public `__init__.py`.
- Group multiple imports from the same module in a single blocķ.
  - For imports from the main project package or for the local package imports always use multi-line with parentheses except for one item imports.
  - For standard library and third-party imports always use single-line imports.
- Import specific items rather than entire modules when possible.
- Use wildcard imports (`*`) only in `__init__.py` files for module exports.
- The import of `TYPE_CHECKING` must be separated from other typing imports
  - It must be placed after all other import blocks and just before the `if TYPE_CHECKING:` block with a blank line.
  - It must not be grouped with other typing imports.
  - It must not be imported at the top typing imports block.
- Always separate `TYPE_CHECKING` imports: 
  - To avoid circular dependencies between modules.
  - To reduce runtime overhead by putting here imports that are only needed for type checking.
  - To import modules that are used exclusively for static type checking (type-only).
  - This block must always be the last import block in the file.
- Separate with a blank line all non-empty import blocks. 
  - Do not allow more than one empty line between nonempty import blocks.
  - Put two blank lines after the last import block before any other code or comments.
- Do not change any order of format of the import section in the __init__.py files. Keep the existing format and order.
- Do not change the existing order of imports inside any import block. But change the order of import blocks if needed to comply with the overall import order rules.
- Sort imports inside the local imports block
  - By import dependency order if possible (e.g., if module A depends on module B, import B before A).
  - By import depth (if no dependency order is clear, import shallower modules before deeper ones).
- Use the same rules for imports under `if TYPE_CHECKING:`.
- Run `ruff check <path>` to validate import order and grouping — its `I` (isort) and `F401` rules cover most violations.


# Naming Conventions

## Classes

### Core Constraints.
- Use PascalCase only. No underscores, hyphens, or spaces.
- Keep names concise and descriptive. Prefer length ≤ **35** characters when possible without losing clarity.
- Avoid digits unless they are part of an established term (e.g., `Vec2`, `Sha256`).
- Do not prefix interfaces with `I`. Use suffixes to indicate roles instead.
- Keep naming stable. Rename it only for semantic correctness.

### Roles: Prefixes and Suffixes.
- Abstract base private classes: **prefix** `_Base`. Examples: `_BaseHandler`, `_BaseStore`.
- Abstract base public classes: **prefix** `Base`. Examples: `BaseService`, `BaseRepository`.
- Mixins: **suffix** `Mixin`. Examples: `LoggingMixin`, `SlotAccessMixin`.
- Structural interfaces: **suffix** `Protocol`. Examples: `EntityViewProtocol`, `PathfinderProtocol`.
- Exceptions: **suffix** `Error`. Examples: `ValidationError`, `RealmConfigError`.
- Enums (categorical): **mandatory suffix** that clearly marks the name as an enum. Approved enum suffixes: `Type`, `Mode`, `Phase`, `State`, `Level`, `Layer`, `Kind`, `Scope`, `Role`, `Policy`, `Category`, `Depth`, `Prop`, `Id`. Choose the suffix that best describes the enum's semantic role. Examples: `PlatformType`, `RunMode`, `LifecyclePhase`, `JobState`, `LogLevel`, `MapLayer`, `TargetKind`, `TargetScope`, `UserRole`, `SharingPolicy`, `EventCategory`, `RenderDepth`, `EntityProp`, `FeatureId`.
- Bitmask enums: **suffix** `Flags`. Example: `PermissionFlags`.
- Data access and services: **suffix** `Repository` or `Service`. Examples: `UserRepository`, `CombatService`.
- Factories and builders: **suffix** `Factory` or `Builder`. Examples: `EnemyFactory`, `LoadoutBuilder`.
- Registries and managers: **suffix** `Registry` or `Manager`. Examples: `SkillRegistry`, `EventManager`.
- Data carriers: **suffix** `Dto` or `Record`. Examples: `CharDto`, `DamageRecord`.
- Value objects: clear noun; `Value` or `Vo` suffix acceptable if helpful. Examples: `PriceValue`, `RangeVo`.

### Acronyms.
- Write acronyms in CapWords form. Examples: `HttpClient`, `JsonEncoder`, `UrlBuilder`, `IoStream`, `IdCodec`, `UiTheme`, `AiAgent`.
- Keep acronym styling consistent across the codebase.

### TypeVars (Generics).
- For bounded generics, append `Type` to the bound class name. Example: `RunContextType = TypeVar("RunContextType", bound="RunContext")`.
- For unbounded generics, use short names. Examples: `T`, `K`, `V`, `R`.
- Do not mix `…T` and `…Type` for the same concept within the same scope. Prefer the `…Type` convention for bounded variables.

### TypeAliases.
- Define `TypeAlias` assignments in the same module section as TypeVars and constants (section 3 of module structure), after the `TYPE_CHECKING` block.
- Import `TypeAlias` from `typing` in the regular imports block (not under `TYPE_CHECKING`).
- Each alias must have a preceding comment explaining its purpose.

### Type Casting.
- **Never use `cast()` from the `typing` module** — it has zero runtime validation and defeats type checking.
- Use `isinstance(obj, TargetClass)` and explicit narrowing when the situation where the instance does not support the class is possible during normal code operation and can be handled without breaking execution.
- **Exception**: When `typing.cast()` is the only viable option (e.g., TypeVar narrowing after prior validation, third-party API type stub issues, class-type defaults), the call **must** be preceded by a `# waiver:` comment explaining why the exception is justified.

### Bare `type` and `type[object]` in Annotations.
- **Never use bare `type` or `type[object]`** as a type annotation. Use `type[SpecificClass]` (the generic form) to annotate class types.
- `type[object]` is semantically identical to bare `type` and equally forbidden.
- Bare `type` includes: `: type`, `-> type`, `type | None`, `dict[str, type]`, `tuple[Any, type | None]`.
- When bare `type` is truly unavoidable, add a `# waiver: <reason>` comment.

### `Any` in Annotations.
- **Avoid `Any` in type annotations.** Prefer specific types, protocols, or generics.
- **Auto-exempt** (no waiver needed): `*args: Any`, `**kwargs: Any`, and any `Any` inside dunder methods (`__init__`, `__eq__`, `__add__`, `__getitem__`, etc.).
- When `Any` is truly unavoidable elsewhere, add a `# waiver: <reason>` comment.

### Name Length and Abbreviations.
- Prefer shorter names that remain descriptive.
- Use approved abbreviations to fit within 35 characters, keeping readability. Approved list: `Ctx` (Context), `Cfg` (Config), `Repo` (Repository), `Svc` (Service), `Mgr` (Manager), `Reg` (Registry), `Dto` (Data Transfer Object), `Vo` (Value Object), `Id` (Identifier), `Io` (Input/Output), `Init` (Initialize/Initialization), `Ops` (Operations), `Prop` (Property), `Auto` (Automatic), `Curr` (Current), `Prev` (Previous).
- Avoid non-standard or cryptic abbreviations.

### Prohibited Patterns.
- No Hungarian notation. Do not prefix class names with module or package identifiers.
- Do not encode types or units in names when the type system or docstrings already convey them.
- Do not conflate role suffixes. A `Service` is not a repository, and vice versa.

### Generator Guidance (Soft Checks).
- If a class is abstract and not intended for direct instantiation, prefer the `Base` prefix.
- If a class is intended as a mixin, ensure the `Mixin` suffix and keep it single-purpose.
- If a class serves as a structural interface, ensure the `Protocol` suffix.
- If a class derives from `Exception`, ensure the `Error` suffix.
- If an enum uses bitwise semantics, ensure the `Flags` suffix; otherwise ensure one of the approved enum suffixes is present (`Type`, `Mode`, `Phase`, `State`, `Level`, `Layer`, `Kind`, `Scope`, `Role`, `Policy`, `Category`, `Depth`, `Prop`, `Id`).
- If a name exceeds 35 characters, shorten using approved abbreviations while preserving meaning.
- If acronyms appear in ALLCAPS, convert to CapWords consistently.


## Methods and Functions

### General Rules.
- Use **snake_case** for all method and function names: `format_diag_msg`, `add_entity`, `apply_to_point`.
- Use leading underscore for private/internal methods: `_record_diag`, `_reset_state`.
- Use descriptive names that indicate the action being performed.
- For specific categories of methods, use consistent prefixes. 
- Do not use `get_` except for trivial in-memory access with no I/O and no mutations.
- Encode the I/O source and cost in the verb.
- Encode cardinality in the name: singular for one result, plural for collections.
- Append the `_async` suffix for `async def` functions.
- Use the `list_` prefix for generators that use `yield`.
- Use the `_batch` suffix for bulk operations.
- Avoid vague verbs like `do`, `process`, or `handle` when a more precise verb exists.

### Name Length & Abbreviation Rules.
- Prefer shorter method names while keeping them descriptive.
- Use shorter words and common abbreviations when appropriate, for example: 
  - `init` instead of `initialize`, 
  - `ops` instead of `operations`, 
  - `prop` instead of `property`, 
  - `auto` instead of `automatic`, 
  - `curr` instead of `current`, 
  - `prev` instead of `previous`,
  - `str` instead of `string`,
  - etc.
- Limit method and function names to a maximum of **35 characters** when possible without sacrificing clarity.
- Avoid non-standard or cryptic abbreviations that reduce readability.

### Prefixes by Semantics.
- Boolean checks: use `is_`, `has_`, `can_`, or `check_` when returning `bool` without raising.
- Conversion: use `to_` for methods and `as_` for read-only view properties.
- Initialization: use `init_`.
- In-memory creation: use `create_`. Persistent creation: use `db_create_` or `repo_create_`.
- Local loading: use `load_`. File or stream reading: use `read_`. Network retrieval: use `fetch_`. Targeted data request: use `query_`.
- Persistence: use `save_`. Strong durability or transactional semantics: use `persist_`.
- Dependency wiring: use `resolve_`.
- Lookup: single item — `find_`, many — `find_all_`, fuzzy or wide — `search_`.
- Filtering a provided collection: use `filter_`.
- Obtain-or-create idempotently: use `ensure_`. Mandatory presence that raises on missing: use `require_`.
- Mutation: basic state change — `update_`, apply configuration or loadout — `apply_`, sparse delta — `patch_`.
- Cache and lifecycle: `reset_`, `clear_`, `invalidate_`, `refresh_`.
- Pure computations: `compute_`, `evaluate_`, `score_`, `rank_`.
- AI policy steps: `decide_`, `select_`, `plan_`.
- Learning and calibration: `train_`, `calibrate_`, `fit_`.
- Simulation and stochastic flows: `simulate_`, `sample_`, `rollout_`.
- Delegation and scheduling: `assign_`, `schedule_`, `enqueue_`.
- Long-running processes: `start_`, `stop_`, `pause_`, `resume_`.
- Resources and sessions: `open_`, `close_`.
- Validation internal: `validate_`. External verification: `verify_`.
- Diagnostics and observability: `log_`, `trace_`, `profile_`, `dump_`.
- Events and hooks: handlers `on_`, hooks `before_` and `after_`.
- Alternative constructors: `from_`.
- Repository and storage: repository abstractions `repo_`, direct storage calls `db_`.
- Execution and main loops: `run_` for lifecycle or round-based logic execution.
- Construction: `build_` for step-by-step assembly of complex structures.
- Collection manipulation: add items — `add_`, remove structural references — `remove_`.
- Deletion: remove entities or records from storage — `delete_`.
- Registration: enroll in a tracking system — `register_`, withdraw — `unregister_`.
- Binding: establish references between objects — `bind_`, release — `unbind_`.
- Accumulation: layer or stack items — `stack_`.
- In-place data mutation: `mutate_` for direct modification of data values (distinct from `update_` which is a general state change).
- Copying: duplicate data between objects — `copy_`.
- Configuration: explicit value assignment when a property setter doesn't fit — `set_`.
- Parsing: interpret strings or raw data into structured forms — `parse_`.
- Formatting: convert data to a string or display representation — `format_`.
- Rendering and display: convert to displayable or serializable format — `render_`, draw graphics primitives — `draw_`.
- Alignment: quantize or snap values to a grid or scale — `snap_`.
- Communication: transmit data — `send_`, receive data — `receive_`.

### Conflict Resolution.
- If multiple prefixes apply, choose by priority: event or hook → lifecycle → execution (`run_`) → I/O (`read_` or `load_` or `fetch_` or `query_`) → mutation (`update_` or `apply_` or `patch_` or `mutate_`) → computation (`compute_` or `score_`, etc.) → construction (`build_`) → lookup (`find_` or `search_`) → registration (`register_`) → representation (`to_` or `as_` or `render_` or `format_`).
- Do not mix different effects under one verb. Use `fetch_` for network calls rather than `load_`.
- Avoid boolean flags that drastically change behavior. Split into separate methods, for example `save_state` and `save_state_async`.

### Auto-Checks for Generation.
- If a function contains `yield`, the name must start with `list_`.
- If a function returns `bool` and produces no side effects, the name must start with `is_`, `has_`, `can_`, or `check_`.
- If a function performs a network call, the name must start with `fetch_` or `query_`.
- If a function writes to the database, the name must start with `db_` or call a clearly named `repo_` method.
- If a function is `async def`, the name must end with `_async`.
- If a function returns a collection, prefer plural nouns or the `find_all_` form.
- If a method name exceeds 35 characters, shorten it using standard abbreviations without losing clarity.

### Short Examples.
- Generator of candidate targets: `list_targets()`.
- Find one record by id: `find_record_by_id(record_id)`.
- Fuzzy item search: `search_items(text)`.
- Update stats: `update_stats(delta)`.
- Apply loadout: `apply_loadout(loadout)`.
- Save group to a database: `db_save_group(group)`.
- Score a target: `score_target(ctx, target)`.
- Async network profile load: `fetch_profile_async(user_id)`.

## Variables and Attributes
- Use **snake_case** for variable names: `unique_id`, `diag_log`, `pov_ent`, `n_dim`.
- Use leading underscore for private attributes: `_chars`, `_groups`, `_subject_class`.
- Use **snake_case** for constants (including class-level): `_base_delay`, `_max_retries`, `_def_image_width`.
- Use descriptive names that indicate the variable's purpose.
- **Minimum length rule**: all variable names must have at least three characters.
  - Do not use single-letter or two-letter names, even in small loops, comprehensions, or generators.
  - Always choose meaningful names that reflect the purpose of the variable (`idx`, `row`, `col`, `val`, `num`, etc.).

## Magic Literals
- **Every magic numeric or string literal used inline must be moved to an Enum or a class-level constants container, or carry a `# waiver: <reason>` comment on the preceding line.** A "magic literal" is a value that encodes structural or domain meaning (a prefix, a tag, a threshold, a naming convention) but appears as a bare `'...'` or number at the use site. Declare it once — as an `Enum` / `IntEnum` / `StrEnum` member when the value belongs to a finite named set, or as a class attribute on a dedicated constants-container class when it is a singleton value.
- **Applies to**: method-call arguments, comparisons, dict/attribute lookups, return values, augmented-assign RHS, binary operations with a non-constant operand, and subscript slices beyond the trivial set.
- **Auto-exempt numeric values** (no constant required): `-1`, `0`, `1`, `2`, `0.5`, and their float equivalents.
- **Auto-exempt strings** (no constant required):
  - Empty string `''`.
  - Underscore markers: `'_'`, `'__'`.
  - Strings made entirely of whitespace or punctuation (e.g., `' '`, `', '`, `': '`, `'.'`, `'\n'`, `'/'`, `'/'`).
  - Strings containing `{`, `}`, or `%` (format placeholders).
- **Auto-exempt contexts** (no constant required — the checker mirrors this list exactly):
  - Function/method default argument values (`def f(x = 'foo')`), including keyword-only defaults.
  - `dataclasses.field(default = …)` / `default_factory`, `pydantic.Field(…)`, `attrs.field(…)`, `msgspec.field(…)`.
  - Decorator arguments (e.g., `@retry(max_attempts = 3)`, `@deprecated('reason')`).
  - `__slots__`, `__all__`, `__match_args__`, and any dunder tuple/list assignment.
  - First positional string of `TypeVar`, `NewType`, `ParamSpec`, `TypeVarTuple`, `NamedTuple('X', …)`, `TypedDict('X', …)`, `Enum('X', …)`, `namedtuple('X', …)` — the type/class name.
  - Second argument of `getattr` / `setattr` / `hasattr` / `delattr` — the attribute name.
  - `open(...)` call: the **mode** (2nd positional or `mode=` kwarg) and the **`encoding=`** kwarg — standard file-open parameters.
  - Member-name introspection probes: `'X' in EXPR.__dict__`, `'X' in vars(EXPR)`, `'X' in dir(EXPR)`. The checker **validates** the name: if `X` matches any identifier declared anywhere in the project, it is skipped; otherwise it is flagged as a probable typo or stale reference.
  - Field-name arg of `.field_filter(...)` method calls: `db.field_filter('_store_mode', '==', value)`. Same validation as member-name probes — the first positional string must resolve to a project identifier, else it is flagged.
  - `TypeVar(..., bound = 'X')` / `NewType(..., bound = 'X')` forward-reference string. Same validation as member-name: every identifier token within the bound string (supports union syntax `'A | B | C'`) must resolve to a project identifier, else the bound is flagged.
  - `Path(…)`, `pathlib.Path(…)`, `PurePath(…)`, and related filesystem constructors.
  - Arguments to `raise …`, `warnings.warn`, `warnings.filterwarnings`, `logging.*` / `logger.*` / `log.*` method calls, `.format(…)`, `re.compile|match|search|sub|findall|split|fullmatch`. **Note**: bare `print(...)` is NOT auto-exempt — mark it with `# TMP` or remove it.
  - Arguments to any call whose method name is `indent_by`, `pretty_view`, `pretty_class`, or `pretty_format` (project-wide pretty-print convention — the literal is a layout parameter or display fragment, regardless of receiver type).
  - Literals inside `Literal[…]`, `Annotated[…]`, `match`/`case` patterns, enum class bodies, f-string format parts, and docstrings.
  - RHS of an assignment whose target is an ALL_CAPS `Name` — that *is* the constant definition itself.
  - RHS of any assignment at **class body scope** (including non-ALL_CAPS names like `_protected_fields = { ... }`, `_lookup_tables = { ... }`) — class-body attributes ARE the class's complex constants.
- **TMP exemption**: a `# TMP` marker covers literals inside scratch/debug code:
  - Inline on the same line: `print('debug', x) # TMP`.
  - As a standalone comment on the line immediately above an enclosing statement or block — it covers every statement inside that block.
- **Waiver**: place `# waiver: <reason>` on the line above when a literal is genuinely one-off and extracting it would harm readability.
- **Bad**:
  ```python
  ns_key = entry.name.removeprefix('log_')
  ```
- **Good**:
  ```python
  _LOG_PREFIX = 'log_'

  ns_key = entry.name.removeprefix(_LOG_PREFIX)
  ```

## Enums
- Use **PascalCase** for enum class names with a **mandatory enum suffix**: `LogLevel`, `EntityType`, `PlatformType`, `RunMode`, `LifecyclePhase`.
- Every enum class name must end with one of the approved enum suffixes: `Type`, `Mode`, `Phase`, `State`, `Level`, `Layer`, `Kind`, `Scope`, `Role`, `Policy`, `Category`, `Depth`, `Prop`, `Id`, `Flags`. This makes it immediately clear that the name refers to an enum.
- Use **ALL_CAPS** for enum members: `LogLevel.ERROR`, `EntityType.USER`, `PlatformType.LINUX`.
- Map enum values to standard library constants when appropriate.
- Always include documentation for the constants to the enum class docstring in the `Attributes` section.
- Use `enum.IntEnum`, `enum.StrEnum`, or `enum.IntFlag` from the standard library; reach for a project-specific base only when the project already defines one.
- Always add INVALID member to all enums with value `-1` or `'~inv~'` and do not document it in the class docstring.
- **Use `INVALID` instead of `None` for optional enum parameters.** When a function accepts an optional enum argument, use the enum's `INVALID` member as the default value instead of `None`. This preserves type consistency and avoids `| None` union types. Check for the sentinel with `!= EnumType.INVALID` instead of `is not None`.
- **Enum placement**: all enum classes must live in a dedicated `types.py` file at the package level, never co-located in a class/logic module. Each package that defines enums should have its own `types.py`. The package `__init__.py` must re-export via `from .types import *`.
  - **Exception — low-level utility packages**: low-level utility packages that use stdlib enums (`enum.IntEnum`, `enum.StrEnum`) and have no `types.py` convention may keep enums co-located when they are private (`_`-prefixed) or tightly coupled to a single class.


# Type Hints and Annotations

## General Type Hinting Rules
- **Always** provide type hints for all method parameters and return values.
- **Avoid `Any`** — use specific types, protocols, or generics. `Any` is auto-exempt in `*args`/`**kwargs` and dunder methods; elsewhere it requires a `# waiver: <reason>` comment.
- Use Union types or `|` syntax for multiple possible types (prefer `|` for Python 3.12+).
- Use `None` as default for optional parameters with proper type hints.
- Use `Self` for methods that return the same class instance.
- Use the TYPE_CHECKING pattern to avoid circular imports and runtime overhead.


# Class Design

## Inheritance Patterns
- Use composition over inheritance when appropriate.
- Implement proper `__init__` methods that call `super().__init__(**kwargs)`.
- When `super().__init__()` coexists with other code in `__init__`, it must be a separate commented
  block. Other blocks (member init, guards) must also be commented and separated by blank lines.

## Generic Classes
- Use Generic classes with proper TypeVar bounds.
- Define class attributes with proper type annotations.
- See the Generic Type System section below.


# Method and Function Design

## Parameter Design
- Use only one / two clearly understandable parameters as positional parameters, prefer keyword arguments for all other parameters.
- Use keyword-only arguments with `*` separator for methods with multiple parameters.
- Provide sensible defaults for optional parameters.
- Use `**kwargs` for extensibility when inheriting from base classes.
- Example parameter patterns:
```python
def transform(self, vector, *, ndim: int | None = None) -> None:
```

## Keyword-Only Parameters (after *) — Selection Rules.
- **`__init__` rule (mandatory).** In every `__init__` method, all parameters with default values **must** be keyword-only (placed after `*`). Only truly required positional operands (parameters without defaults) may appear before `*`. When every parameter after `self` has a default, use `self, *,`. When a mix of required and defaulted parameters exists, place `*` after the last required parameter. `**kwargs` always comes after `*`.
  ```python
  # All params have defaults — * immediately after self:
  def __init__(self, *,
               proto: ProtoEntity | None = None,
               source: SkillSourceType = SkillSourceType.INVALID,
               **kwargs: Any) -> None:

  # bid is required, root_path has default — * after bid:
  def __init__(self, bid: str, *,
               root_path: str = '/') -> None:
  ```
- Use * and make a parameter keyword-only in the following cases. The goal is to prevent positional mistakes, keep call sites self-documenting, and allow safe API evolution.
  - Flags and behavior switches. All booleans and modifiers must be keyword-only, e.g. dry_run, strict, overwrite, use_cache. Prefer affirmative names (allow_create) over negatives (do_not_create). If a negative is unavoidable, keep the default False.
  - Modes, strategies, and types (often enums). Parameters like mode, strategy, policy, kind, rel_type are keyword-only.
  - Thresholds and tuning knobs. Use names such as timeout, retries, limit, threshold, temperature, top_p, seed. Include units in the name when relevant, e.g. timeout_ms, distance_cells.
  - Contexts and resources. Dependency/context objects are keyword-only: db, logger, clock, cache, session, db, http, rng.
  - Callbacks and hooks. Use keyword-only for on_error, predicate, key_fn, scorer, comparator.
  - Rarely used or orthogonal options. Any option that does not define the core meaning of the operation should be keyword-only.
  - After *args. All parameters after *args are, by definition, keyword-only and must remain so.
- What may remain positional (before *).
  - self/cls.
  - Up to three short, essential operands that define the operation’s meaning, e.g. entity, src, dst, value, index, path.
  - Data without which the call is meaningless.
  - If you need more than three positional operands, introduce * and convert the rest to keyword-only.
- Cross-reference.
  - For wrapping and indentation of multi-line signatures, see 'Function/Method Signatures — Multi-line Wrapping'. 
- Recommended order in the signature.
  - self/cls.
  - One to three essential positional operands.
  - * 
  - keyword-only groups:
    - modes/strategies,
    - control flags,
    - environment/resources,
    - thresholds/settings,
    - callbacks/hooks,
    - debug/tracing.
- Examples.
```python
def _build_worker(self, *,
                  mode: RunMode = RunMode.INVALID,
                  allow_create: bool = False,
                  store: Store | None = None) -> Worker | None:
    ...

def move(self,
         src: Location,
         dst: Location,
         *,
         mode: PathMode = PathMode.SAFE,
         timeout_ms: int = 0,
         rng: Rng | None = None) -> bool:
    ...
```

## Method Organization
- Place `__init__` methods first.
- Place private/service helper methods immediately after `__init__`.
- Place property methods after private helpers.
- Place public methods (update, apply, compute, etc.) after properties.
- Place interface/protocol method implementations at the **end** of the class, each group preceded by a `# ----- InterfaceName` comment separator.
- When a class implements multiple interfaces, order the `# ----- InterfaceName` sections to match the interface declaration order in the original interface file (parent interfaces before child interfaces).
- Group related methods together within each section.
- Use `@property` decorators for computed attributes.

## Context Managers
- Use `@contextmanager` decorator for temporary state changes.
- Implement proper cleanup in context managers.
- See the Context Manager Pattern section below.

## Return Type Patterns
- Use `Self` for methods that return the same class instance, see the Fluent Interface Pattern section below.
- Use specific return types rather than generic ones when possible.

## Pattern Matching
- Use match/case statements for handling different entity types or states.
- Always include a default case with the appropriate error handling.
- See the Match/Case Pattern section below.


# Error and Exception Handling and Debugging

## General Principles
- Avoid overuse of exceptions: Do not use exceptions for normal control flow. Reserve them for truly exceptional or unexpected conditions.
- Use guard clauses (if, match) and validations instead of relying on exceptions.
- Validate inputs early to prevent downstream errors.
- Always catch specific exceptions, not Exception or BaseException, unless in final fail-safe handlers (e.g. logging wrappers).
- Log or handle exceptions meaningfully, do not silently pass unless explicitly justified (e.g. polling or optional probe logic).

## When try ... except is Recommended
- Operations involving external dependencies where failure is expected and must be handled gracefully.
- Parsing or type conversion with uncertain input.
- Errors due to file absence, permissions, or network state should be caught and handled.
- Third-party APIs with inconsistent error signaling, especially when catching known exception patterns.
- Final safety wrappers (top-level handlers), when catching errors globally (e.g. main loop or service entrypoint).
- For the proper way to handle exceptions, see the Try ... Except ... Pattern section below.

## Additional Rules
- Don’t catch and ignore silently.
- Don’t catch too early: Let low-level exceptions bubble up if the caller can handle it better.
- Don’t wrap exceptions unnecessarily unless you’re adding semantic context or abstracting layer details.

## Custom Exceptions
- Use a built-in Python exception (e.g., `ValueError`, `TypeError`, `RuntimeError`) whenever one fits the case.
- Define a project-specific subclass only when callers need to catch the new condition separately from the built-in.
- Always provide a short, clear error message with relevant context.
- When wrapping another exception, use `raise ... from error` to preserve the cause chain.
- Use `error` as the parameter name for exceptions to maintain consistency.

## Error Messages
- Use descriptive error messages that include expected vs actual values.
- Include parameter names and context in error messages.
- See the Error Context Pattern section below.

## Broad exception warning handling
- When intentionally using a broad exception handler that does not bind or use the exception value (e.g., `except Exception:`), add PyCharm suppression to silence the PyBroadException inspection `# noinspection PyBroadException`.
- Place the suppression comment immediately before the `try` line.
- Prefer catching specific exceptions whenever possible; use broad handlers only when justified.
- Even in case of broad exception handling, always provide a comment explaining why the code exists and what it is intended to do.
- Even in case of broad exception handling, prefer to log the exception or provide a warning message to avoid silent failures if the failure is unexpected and is not the intended behavior.

## Exception Logging
- When catching exceptions, log a message with the exception details to aid in debugging.
- Use error / warning log levels based on the severity of the issue.
- Do not log any message if the exception is expected and is the intended behavior.
- See the Try ... Except ... Pattern section below.

## Error Logging
- Use the project's logger for consistent logging.
- Include stack traces for debugging when appropriate.
- Provide different log levels: error, warning, info, debug.
- Start all log messages with a small letter.



# Code Patterns and Good Examples

## TYPE_CHECKING Patterns
```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
  from typing import Any, Generator, Self

  from myproject.core import Entity
  from myproject.runtime import (
    Place,
    RunContext,
  )
```

## Generic Type System
```python
# ----------------------------------------------------------------------------------------
# TypeVar with bounds for type safety
SubjectType = TypeVar('SubjectType', bound = 'Subject')


# ----------------------------------------------------------------------------------------
class DecisionScope(Generic[SubjectType]):

  # Class attribute with type annotation
  _subject_class: type[SubjectType]


  def build(self) -> list[SubjectType]:
    """
    Build and return a list of subjects.
    """
    return []
```

## Singleton Pattern
```python
class Cache(metaclass = SingletonMeta):
  """
  Cache class provides a process-wide singleton store.
  """

  def __init__(self) -> None:
    """
    Initialize the Cache instance.
    """
    pass
```

## Conditional Import Pattern
```python
if AppEnvironment().is_remote_env:
  import remote_runtime
```

## Context Manager Pattern
```python
@contextmanager
def temp_log_level(self, level: LogLevel) -> Generator[None, None, None]:
  """
  Temporarily change log level.
  """
  old_level = self._current_level
  self._current_level = level
  try:
    yield
  finally:
    self._current_level = old_level
```

## Fluent Interface Pattern
```python
def inverse(self) -> Self:
  """
  Returns the inverse of this transformation.
  """
  return type(self)(matrix = np.linalg.inv(self.matrix))

def transform_method(self) -> Self:
  """
  Returns modified instance for chaining.
  """
  return type(self)(modified_data)

# Usage: obj.method1().method2().method3()
```

## Overload Stubs Pattern
```python
@overload
def __mul__(self, other: float) -> Self: ...

@overload
def __mul__(self, other: np.ndarray) -> Self: ...

@overload
def __mul__(self, other: Self) -> Self: ...

@overload
def __mul__(self, other: Any) -> Self: ...

def __mul__(self, other: Any) -> Self:
  """
  Multiplies the tensor by a scalar or a vector with the same shape.
  """
  ...
```

## Generic Exception Pattern
```python
class SpecialError(Exception):
  """
  Project-specific exception raised by callers that need to catch this case
  separately from built-in exceptions.
  """

  def __init__(self, owner: object, message: str):
    """
    Initialize with the owning object (for diagnostics) and an error message.
    """
    # store owner context for diagnostics
    self.owner = owner

    # call parent with error message
    super().__init__(message)
```

## Error Context Pattern
```python
# include context in error messages
if condition_failed:
  raise ValueError(f"expected {expected}, got {actual} for parameter '{param_name}'")
```

## Try ... Except ... Pattern
```python
try:
  # code that may raise any exception

except SpecialError as error:
  # log message about specific error
  logger.error(f"a specific error occurred: {error}")

except Exception as error:
  # log message about unexpected error
  logger.exception(f"an unexpected error occurred: {error}")

else:
  # no error occurred

finally:
  # clean up resources
```

## Match/Case Pattern
```python
# pattern matching with comprehensive error handling
match entity_type:
  # known entity type
  case EntityType.KNOWN_TYPE:
    handle_known_type()
  # in the case of an unknown entity type
  case _:
    raise ValueError(f"unsupported entity type: {entity_type}")
```

## Numpy Integration Pattern
```python
def process_arrays(self, data: np.ndarray) -> np.ndarray:
  """
  Process numpy arrays with proper shape validation.
  """
  # validate input shape
  if data.shape[-1] != self.expected_dim:
    raise ValueError(f"expected last dim = {self.expected_dim}, got {data.shape[-1]}")
  
  # process with broadcasting support
  result = self._transform_matrix @ data.T
  return result.T
```

## Operator Overloading and NotImplemented
- For magic methods that combine two operands (e.g., `__matmul__`, `__add__`), always return `NotImplemented` for unsupported operand types instead of rising within the method. This allows Python to:
  - Try the reverse operator on the other operand (`__rmatmul__`, `__radd__`, etc.).
  - Raise a consistent `TypeError` with the standard "unsupported operand type(s)" message if neither side supports the operation.
- Implement the corresponding reverse operator when a natural reversed form exists (e.g. support both `roll @ dataset` and `dataset @ roll`).
- Example pattern:
```python
def __matmul__(self, other: Any) -> Any:
  """
  Combine this Roll with a DataSet to produce a DataVal.
  """
  if not isinstance(other, DataSet):
    return NotImplemented
  # ... perform operation ...


def __rmatmul__(self, other: Any) -> Any:
  """
  Combine this Roll with a DataSet to produce a DataVal.
  """
  if isinstance(other, DataSet):
    return self.__matmul__(other)
  return NotImplemented
```

## Dataclass Post-Init and Dynamic Docstrings
- Always call `super().__init__()` in `__post_init__` to ensure proper initialization of base classes.
- For dataclasses with fields that depend on constructor parameters, declare them with `init = False` and initialize them in `__post_init__`.
- If instances benefit from dynamic docstrings for debugging or tests, set `self.__doc__` in `__post_init__` to a deterministic value (e.g., `f"Roll for {self._val_cls.__name__}."`).
- When instantiating types provided by users (like `val_cls`), guard with try/except and re-raise as a clear `ValueError` while preserving the cause (`raise ... from error`).
```python
@dataclass
class Roll(Generic[T]):
  """
  Carries random samples to convert a DataSet into a concrete DataVal.
  """

  # The class of the DataVal to produce
  val_cls: type[T]

  # Random samples for uniform and normal distributions
  uniform: T = field(init = False)

  # Random samples for normal distribution
  normal: T = field(init = False)


  def __post_init__(self) -> None:
    """
    Initialize uniform and normal samples and set dynamic docstring.
    """
    # call init for the base class
    super().__init__()

    self.__doc__ = f"Roll for {self._val_cls.__name__}."
    try:
      self.uniform = self._val_cls()
      self.normal = self._val_cls()
    except Exception as error:
      raise ValueError(f"failed to instantiate {self._val_cls.__name__}: {error}") from error
    self.reroll()
```
