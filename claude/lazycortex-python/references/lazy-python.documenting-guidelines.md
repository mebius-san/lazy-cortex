---
description: Docstring rules (class, method, property), comments, marker comments, contract comments, and DOC comments for Python projects that adopt these conventions.
---
# Documentation Standards

Docstring rules (class, method, property), comments, marker comments,
contract comments, and DOC comments for Python projects that adopt
these conventions.

## LLM Output Contract — Docstring Overrides
- Zero-tolerance blockers (must never appear):
  - Removing a correct public field from the Attributes section when it exists in the source or the code (assigned to `self.<name>` in `__init__` or declared as a public class variable).
  - Adding Notes that restate the summary, list private internals (e.g., `_idx_dtype`, `_crd_dtype`), mention storage or backing fields, or contain obvious tautologies (“Stores X.”, “Keeps Y.”).
  - Migrating content from Attributes, Args, Returns, Yields, Raises to Notes.
  - Starting section text in the same column as the section name.
  - Adding any custom section that is not described in these guidelines.
  - Skipping mandatory sections when criteria are met.
  - Keeping any empty line before the Summary section of at the end of the docstring.
  - Adding private attributes (starting with underscore) to the **Attributes** section of any docstring, regardless of perceived importance or documentation value.
  - Adding any property to the **Attributes** section of any docstring, regardless of perceived importance or documentation value.
  - Adding docstring to methods that are defined inside other methods or functions.
  - Adding `TODO:`, `TMP:` or any other information about work in progress if the class or method is not finished yet.
  - Adding `DBG:`, `REF:`, `DOC(…):` or any other special comments or tags in the docstring or comments.
  - Adding sections **Args**, **Returns**, or **Yields** to any property method created with `@property` decorator.
  - Adding implementation steps in Summary or Scope, e.g., “It validates…,” “It sets up…,” “It assigns…,” or “with the given X and Y…”.
  - Mentioning private internal components or backing storage in Scope or Notes unless explicitly part of the public API.
  - Rewriting Scope to include algorithms, loops, or call sequences instead of caller-visible guarantees.
  - Exciding the line length limit of 117 characters.
- Preservation rules:
  - When editing an existing docstring, keep all valid parts intact unless they are: Probably wrong or Do not describe the current code or describe it incorrectly or Violate these guidelines.
  - Do not remove existing **Guarantees** sections from method docstrings unless they are factually wrong or contradict the current code behavior.
  - Do not remove or weaken sentences that describe caller-visible invariants or postconditions (for example, index alignment between frame states, turns, and chapter entities), unless they are clearly incorrect.
  - When in doubt whether an existing sentence describes an internal algorithm or a caller-visible guarantee, treat it as a guarantee and keep it, preferably under **Guarantees**, but do not create any new guarantees based on the implementation.
  - If a docstring currently places a caller-visible invariant or postcondition in **Notes** (for example, that lists are kept in sync and share the same indices), you may move that bullet into a **Guarantees** section instead of deleting it. The content must remain semantically equivalent or stricter.
- No-filler rules:
  - If there is nothing meaningful to add to a particular section, omit that section.
  - If you can't determine something from the code do not generate it based on your imagination, omit it.
  - If a method is defined inside another method or function, do not add a docstring to it.
- No-change rules:
  - If a section violates the rules, normalize and fix it, but do not delete or move it. 
  - Always keep a section if it exists, unless it is empty or redundant.
- `TODO:`, `TMP:`, `DBG:`, `REF:`, `opt:`, `guard:`, `DOC(…):` and other special comments interpretation rules:
  - Treat any code or comments marked with `TMP:` as non-existent for the purposes of documentation, behavior description, and refactoring suggestions. Do not mention `TMP:` blocks or derive documented behavior from them.
  - Treat any code region marked with `TODO:` as if it were already fully and correctly implemented. Do not mention missing implementation, stubs, placeholders, or the need to finish `TODO:` blocks in docstrings, Notes, or any other generated text, even if the underlying code is incomplete.
  - Treat `opt:` comments as optimization annotations that explain why a non-obvious implementation choice was made for performance reasons. Do not alter or remove them.
  - `REF:` comments are source references that point to related code, classes, constants, or `DOC(…)` groups elsewhere in the codebase. They are stripped automatically when docstring sections are read during generation, so they serve only as human-readable traceability links. Do not alter or remove them.
  - Ignore any comments or tags like `DBG:`, `DOC(…):` in the docstring or comments for the docstring generation or modification process.
- Change Rules:
  - If you can convert one big Scope section into the correct sections, do it.
  - If you can add meaningful missing sections, do it.
  - You must fix the section order if it is wrong.
  - You must fix or change the section if it violates the guidelines or if its usage is wrong.
  - You must add missed Attributes, Args, Returns, Yields, or Raises.
- Style rules:
  - Use complete sentences and end them with periods.
  - Keep paragraphs short and task-oriented.
  - Avoid redundant sections when there is nothing meaningful to add.
  - Start section text with two spaces of indentation relative to the section title.
  - Limit the length of any text line to 117 characters.
  - No LaTeX or math markup in docstrings. Forbidden in any docstring section: `$...$` / `$$...$$` inline and block math, `\(...\)` / `\[...\]` delimiters, and backslash commands (`\frac`, `\sum`, `\in`, `\leq`, `\geq`, `\cdot`, `\times`, `\alpha`–`\omega`, `\sqrt`, `\mathbb`, etc.). Write formulas in plain prose with backticked identifiers and unicode operators where needed (e.g. "the effective factor is `1 - r`, with `r` in `[-1, 1]`"). LaTeX is allowed ONLY in `DOC(...)` line comments, where Obsidian renders it — docstrings are read by Python tooling, which does not render math.

## Docstrings
- Coverage: All classes, functions, methods, and properties must have docstrings.
- Style: Use Google/Sphinx-style docstrings. Add a newline after the opening quotes.
- Focus: Describe externally visible behavior and purpose. Omit internal algorithms and implementation details.
- Sections (when applicable): `Attributes`, `Args`, `Returns`, `Raises`, `Yields`.
  - Attributes: `name: description`. Separate public and private with an empty line.
  - Args: `name: description`.
  - Returns / Yields: concise prose only.
  - Raises: `exception class name: description`.
- Typing: Do not include types in any section. Types belong to the signature only.
- Identifiers: In narrative text, wrap code identifiers in backticks (e.g., `ClassName`, `method_name`, `module.func(arg)`). In definition lists (`Args:`, `Parameters:`, `Attributes:`), the item label must match code exactly, with no backticks or extras; wrap other identifiers in backticks within the description.
- Practical rule: If the identifier is the list label at line start, do not wrap it. Elsewhere, wrap it in backticks.
- Summary line rules:
  - The first line is a single, complete sentence that starts with a capital letter and uses the imperative mood.
  - Leave one blank line after the summary before any additional details.
  - Examples: Good — “Parse the input and return a normalized DataFrame”. Bad — “parses the input and returns a normalized dataframe”.

## Class Documentation
- Keep the following order of sections when they exist: Summary, Scope, Responsibilities, Guarantees, Subclassing, Notes, Type Parameters, Attributes — plus any project-registered sections at their configured positions. Fix the order if it is wrong.
- Summary line.
  - Summary is mandatory. If non-compliant, normalize it; do not delete or move. Always keep a Summary section for every class.
  - The first line is a noun phrase: “Planner for turn-based tactics.”
  - Avoid “This class …”.
  - Style:
    - This section must not have an empty line before it.
    - This section must not have a title.
- Scope:
  - For all cases:
    - Do not mention any input arguments or parameters in the Scope section.
    - Do not mention base classes or inheritance details.
    - Omit internal algorithms, data structures, and implementation notes.
    - Omit the title 'Scope' for this section.
    - These rules override external style guides where they conflict.
    - For enums describe what the enum represents and how it is used by callers but do not use particular enum members in the description and to make descriptions more general. Description must be invariant to the addition or removal of enum members.
  - For a common case:
    - Describe what the class represents and how it is used by callers.
  - For ABCs/Protocols:
    - Describe the purpose and role of the class in the system.
    - Omit internal algorithms, data structures, and implementation details.
  - Style:
    - This section must have an empty line before it.
    - This section must not have a title.
- Responsibilities:
  - Allow this section only and only if there are meaningful caller-visible responsibilities to document based on the class code and behavior.
  - Typical triggers include:
    - The class orchestrates or coordinates other components, workflows, or main loops (e.g. planners, managers, controllers).
    - The class performs visible side effects beyond returning values, such as I/O, logging, event emission, registry updates, or scheduling.
    - The class exposes multiple public methods whose interplay forms a caller-visible contract not obvious from names alone.
    - The class participates in concurrency, async execution, or multithreaded contexts where caller expectations must be set.
    - The class is an ABC or Protocol and defines required behaviors for implementers.
    - The class uses caching or lazy evaluation that changes when and how results appear to callers.
  - What to include:
    - High-level duties the class fulfills, observable behaviors, side effects, and guarantees to callers. Describe the “what”, not the “how”.
  - What to exclude:
    - Algorithms, data structures, and micro-flow details.
  - Style:
    - Must be a bulleted list, even for a single item.
    - Each line must start with an indent of exactly two spaces relative to the section title, followed by a hyphen, and a space.
    - Must be indented under the section; do not use bullets at column zero.
    - The section must have an empty line before it.
- Guarantees:
  - Allow this section only and only if there are meaningful caller-visible guarantees to document based on the class code and behavior.
  - Typical triggers include:
    - Any relationship between public fields must always hold, including bounds, units, shapes, or cross-field dependencies.
    - The class guarantees ordering, uniqueness, identity stability, or immutability across calls.
    - The class defines `__eq__`, `__hash__`, ordering comparisons, or exposes keys/ids that underpin equality or lookup semantics.
    - The class promises iteration order, stability of results, or determinism given fixed inputs and seed.
    - The class maintains caches, memoized values, or derived views whose validity depends on explicit conditions or invalidation rules.
    - The class claims thread-safety, reentrancy, or single-thread confinement, or becomes immutable after construction.
    - The class has lifecycle states (e.g. initialized → active → closed) with conditions that must hold in each state.
    - The class serializes/deserializes data and relies on schema or version constraints that must remain consistent.
    - Numeric domains, ranges, or unit constraints must always be satisfied in public attributes or results.
    - External resource handles (e.g. attached world, open session) must obey “attached/not-attached” or “open/closed” invariants visible to callers.
  - What to include:
    - Conditions that must always hold after construction and across method calls, including relationships between attributes, ordering guarantees, identity/uniqueness constraints, and thread-safety guarantees. Include only statements that are testable.
  - What to exclude:
    - One-off preconditions or optional behaviors.
  - Style:
    - Must be a bulleted list, even for a single item.
    - Each line must start with an indent of exactly two spaces relative to the section title, followed by a hyphen, and a space.
    - Must be indented under the section; do not use bullets at column zero.
    - The section must have an empty line before it.
- Subclassing:
  - Required by default for extensible classes. 
    - Add only if the project has derived classes from this class or if the class is designed for inheritance (not final).
    - Omit for final classes not intended for inheritance.
    - Omit for all enums because they are not subclassable.
  - What to include:
    - Subclassing guidelines for extensible types.
    - Initializations that must be performed in derived classes.
    - Important private or public fields that need to be set in derived classes to change the behavior.
    - Attribute fields, private and public, that must be initialized in derived classes.
    - Initialization order dependencies in complex hierarchies.
  - What to exclude:
    - Restatements of responsibilities, guarantees, or general usage notes unrelated to inheritance.
  - Style:
    - Must be a bulleted list, even for a single item.
    - Each line must start with an indent of exactly two spaces relative to the section title, followed by a hyphen, and a space.
    - Must be indented under the section; do not use bullets at column zero.
    - The section must have an empty line before it.
- Project-registered sections:
  - A project may register additional class-docstring sections in its `pyproject.toml` via `[tool.pcf] extra_docstring_sections` (section name, list style, order anchor, optional `ref_exempt` flag for sections whose body carries `# REF:` lines consumed by project tooling).
  - The content rules for such sections live in the project overlay (`docs/guidelines/documenting_guidelines.md`), not in this canon. The checker enforces only order, list style, and the `ref_exempt` shield.
  - Order anchors (`after` / `before`) must name a built-in section or a previously declared entry; an unresolved anchor appends the section at the end of the order.
  - Registered sections with `style = "definition"` are skipped by the private-name narrative check (D9), like the built-in definition sections (`Attributes`, `Args`, `Raises`, `Type Parameters`).
- Notes:
  - Allow this section only and only if there is something meaningful to add based on the class code and behavior.
  - What to include: 
    - Caller-visible caveats.
    - Performance implications.
    - Compatibility constraints.
    - Serialization format hints.
    - Deprecations.
    - Environment assumptions.
  - What to exclude: Restatements of responsibilities or invariants.
  - Boundaries:
    - Exceptions and their triggers belong under **Raises**.
    - Do not restate returned values or iteration behavior; keep those in **Returns** or **Yields**.
    - Do not list public fields; keep those in **Attributes**.
  - Style:
    - Must be a bulleted list, even for a single item.
    - Each line must start with an indent of exactly two spaces relative to the section title, followed by a hyphen, and a space.
    - Must be indented under the section; do not use bullets at column zero.
    - The section must have an empty line before it.
  - Allowed (caller-visible) only:
    - Mutability and thread-safety caveats.
    - Caching or laziness and invalidation triggers.
    - Performance or cost at a high level (e.g. “O(n) on first access.”).
    - Lifecycle, serialization, or compatibility constraints.
    - Deprecations.
  - Prohibited:
    - Internal storage details (backing arrays, dtypes, private names like `_idx_dtype`, `_crd_dtype`).
    - Restating the summary or duplicating **Attributes**.
    - Repeating types or annotations in prose.
- Type Parameters:
  - Mandatory when the class has any type parameters.
  - Add this section only if the class is a Generic template and has type parameters.
  - What to include: 
    - Type parameters and their constraints.
  - What to exclude: 
    - Private internals and type annotations.
  - Style:
    - Do not include type annotations.
    - For a common case:
      - A line per item, noun phrase, ends with a period.
    - Must be indented under the section; do not use bullets at column zero.
    - Must not have any bullets, dashes, or other prefixes.
    - Each line must start with an indent of exactly two spaces relative to the section title, followed by the attribute name, colon, and space.
    - The section must have an empty line before it.
- Attributes:
  - Mandatory when the class has any attributes to show.
  - What to include:
    - Public fields that callers read or set.
      - Instance fields assigned in `__init__` as `self.name` without a leading underscore (public).
      - Public class variables without a leading underscore (public).
    - Private members or properties only when the project declares a documented escape hatch for them (see the project overlay; enforced via `[tool.pcf] d2_exempt_marker_attrs`).
    - Mention meaning, units, allowed ranges, defaults, mutability (read-only or writable), and whether `None` is possible.
    - All enum members except `INVALID`.
  - What to exclude: 
    - All private fields (starting with an underscore), both class-level and those created in the `__init__` method, unless covered by the project's declared escape hatch.
    - Any property (public or private) methods created with `@property` decorator, unless covered by the project's declared escape hatch.
    - Type annotations.
    - Only and only `INVALID` member of enums. All other members MUST be documented.
  - Style:
    - Do not include type annotations.
    - For a common case:
      - A line per item, noun phrase, ends with a period.
    - Must be indented under the section; do not use bullets at column zero.
    - Must not have any bullets, dashes, or other prefixes.
    - Each line must start with an indent of exactly two spaces relative to the section title, followed by the attribute name, colon, and space.
    - The section must have an empty line before it.
    - Separate public and private attributes with an empty line if private attributes are included.
- Interface / ABC / Protocol specifics:
  - Start with “Interface base for …” or “Abstract base for …” or “Protocol for …”.
  - State behavioral contracts, not implementations.
- See the Class Documentation Patterns and Good Examples section below.
- See the Bad Class Documentation Examples section below.

## Method Documentation
- Keep the following order of sections when they exist: Summary, Scope, Guarantees, Overriding, Notes, Args, Returns, Yields, Raises. Fix the order if it is wrong.
- Summary line.
  - Summary is mandatory. If non-compliant, normalize it; do not delete or move. Always keep a Summary section for every method.
  - Use imperative mood: “Compute…”, “Select…”, “Return…”, “Update…”, “Remove…”, etc.
  - Avoid “This method …”.
  - Style:
    - This section must not have an empty line before it.
    - This section must not have a title.
- Scope.
  - Describe what the method guarantees to the caller and why it exists. Do not narrate internal steps that achieve it.
  - Do not mention private components or storage (trainers, managers, caches, configs, registries) unless they are part of the public API contract.
  - Do not mention any input arguments or parameters in the Scope section.
  - Omit internal algorithms, data structures, and micro-flow details.
  - Omit a Scope section for test methods named `test_...` from test classes.
  - These rules override external style guides where they conflict.
  - Style:
    - This section must have an empty line before it.
    - This section must not have a title.
- Guarantees:
  - Allow this section only and only if the method provides caller-visible guarantees about its results, outputs, or the resulting state that are not obvious from the name and signature.
    - Never derive new **Guarantees** items from the method implementation body, control flow, or concrete attribute usage.
    - Only describe guarantees that are explicitly defined by the public protocol:
      - The function or method signatures and their type hints.
      - The owning class or interface docstring and public API description.
      - Explicit comments marked with `Contract!` in the code.
    - Do not restate implementation details such as “returns `self.is_permanent`”, “iterates over all items”, or “runs in O(1)” unless they are explicitly required by the documented protocol or a `Contract!` comment.
    - If no explicit protocol-level guarantees are available, do not invent or expand the **Guarantees** section. Omit this section entirely or keep only the guarantees that already exist in the docstring.
    - When editing an existing **Guarantees** section, you may reformat or clarify sentences, but you must not strengthen, weaken, or extend the contract beyond what is already stated in the source docstring or `Contract!` comments.
  - Typical triggers include:
    - The method establishes or maintains stable relationships between collections, such as index alignment between entity lists and corresponding states, turns, or other per-entity data.
    - The method guarantees ordering, uniqueness, or determinism of returned values given the same inputs and seed.
    - The method ensures consistency between multiple objects or views after it completes (for example, lengths of related lists always match; item i in one list refers to the same domain object as item i in another list).
    - The method maintains invariants on numeric ranges, units, or validity of public attributes or results.
    - The method moves the owning object to a new lifecycle state with clearly defined invariants (e.g. fully initialized, attached, closed).
  - What to include:
    - Stable, testable postconditions that must hold after a successful call.
    - Cross-collection or cross-object invariants that callers rely on to interpret data correctly (for example, index relationships, alignment, or synchronization).
    - Determinism and ordering guarantees for return values or mutated structures.
    - Lifecycle and validity guarantees about the resulting state visible to callers.
    - Do not infer guarantees from the method body or internal control flow. The **Guarantees** section must be based only on the public protocol: the method signature, class or interface documentation, and explicit `Contract!` comments in the code.
  - What to exclude:
    - One-off preconditions that are better expressed in **Notes** or **Raises**.
    - Internal algorithms, loops, or data structures are used to achieve the guarantees.
    - Restatements of return types or trivial facts that follow from the signature.
  - Style:
    - Must be a bulleted list, even for a single item.
    - Each line must start with an indent of exactly two spaces relative to the
      section title, followed by a hyphen, and a space.
    - Must be indented under the section; do not use bullets at column zero.
    - The section must have an empty line before it.
- Overriding:
  - Allow this section only if the method overrides a base class or protocol and has special rules or conditions.
  - What to include:
    - Differences from the base contract: strengthened or weakened preconditions, postconditions, and guarantees.
    - Changes in side effects, ordering, performance characteristics, or external interactions relative to the base method.
    - Requirements to call or not call `super()`, and what is guaranteed before or after that call.
    - Compatibility notes for LSP, deprecations, and versioning or migration guidance for implementers.
    - Extension points or hooks that subclasses must preserve.
  - What to exclude:
    - Restating the base behavior without changes.
    - Parameter lists or return details; keep those in **Args** and **Returns** or **Yields**.
    - Internal algorithms or micro-flow details.
  - Style:
    - Must be a bulleted list, even for a single item.
    - Each line must start with an indent of exactly two spaces relative to the section title, followed by a hyphen, and a space.
    - Must be indented under the section; do not use bullets at column zero.
    - The section must have an empty line before it.
- Notes:
  - Allow this section only and only if there is something meaningful to add based on the method code and behavior.
  - Mandatory when:
    - Any requirement beyond type annotations must hold to avoid runtime errors or undefined behavior.
    - The object must be in a specific lifecycle state (e.g., initialized, open, attached, not disposed) for the call to be valid.
    - Inputs must satisfy content constraints such as non-emptiness, ordering, uniqueness, bounds, shapes, or units.
    - External resources must exist or be available, such as an open session, connected database, attached world, or valid handle.
    - Caller context must provide permissions, ownership, thread confinement, or execution context (sync vs async) guarantees.
    - Feature flags, configuration keys, or environment conditions must be enabled or set.
    - Concurrency constraints must hold, such as “no concurrent writers,” “must be called from the main thread,” or “reentrant safe only if X.”
    - The method changes the observable state and must guarantee specific results, ordering, or persistence after success.
    - Collections, queues, or graphs must satisfy ordering, membership, uniqueness, or consistency properties after the call.
    - Caches or lazy fields are created, updated, or invalidated, and their new validity conditions must be stated.
    - External effects must have occurred, such as an event emitted, a file written, a transaction committed, or a job scheduled.
    - Resource or lifecycle state must advance deterministically, including handles being opened, closed, attached, or released.
    - Concurrency-related guarantees must hold after completion, such as locks released, no leaked tasks, or idempotent final state.
    - Determinism or stability is promised under fixed inputs and seeds, and this guarantee must be explicit.
    - The method mutates any public object state or externally visible state, including registries or shared models.
    - The method performs I/O, networking, database access, inter-process calls, or enqueues work on schedulers or event buses.
    - The method logs, emits metrics or traces, or interacts with observability backends visible to operators.
    - The method consumes randomness, advances RNG state, or otherwise introduces nondeterminism observable to callers.
    - The method touches global singletons, environment variables, process-wide configuration, locale, or time sources.
    - The method updates, invalidates, or warms caches or lazy fields in ways visible to callers.
    - The method acquires or releases locks, influences thread affinity, or yields to an event loop in a caller-observable way.
    - The method can block, sleep, throttle, or trigger backoff that affects caller timing.
  - What to include:
    - Preconditions about inputs, lifecycle, or context that must hold before the call.
    - Observable mutations and external interactions that occur during the call.
    - Caller-facing caveats, performance implications, compatibility, deprecations, or idempotency.
    - List state mutations, I/O, logging, cache updates, RNG consumption, and interaction with global singletons.
    - State thread-safety or reentrancy constraints if relevant.
  - What to exclude:
    - Stable postconditions and invariants that always hold after a successful call, including index alignment and cross-collection synchronization. These belong in the **Guarantees** section, not **Notes**.
    - Preconditions that raise exceptions; those belong under **Raises**.
    - Internal algorithms, data structures, and micro-flow details.
    - Do not restate returned values or iteration behavior; keep those in **Returns** or **Yields**.
    - Do not list parameters; keep those in **Args**.
  - Style:
    - Must be a bulleted list, even for a single item.
    - Each line must start with an indent of exactly two spaces relative to the section title, followed by a hyphen, and a space.
    - Must be indented under the section; do not use bullets at column zero.
    - The section must have an empty line before it.
- Args:
  - Mandatory when the method has any parameters.
  - What to include:
    - Each parameter’s meaning, units, accepted ranges, shapes, nullability, and behavioral impact.
    - Mention defaults only if behavior changes materially.
  - What to exclude:
    - Type annotations and redundant restatements of parameter names.
  - Style:
    - One line per parameter as `name: description`.
    - Keep sentences short and precise.
    - Must be indented under the section; do not use bullets at column zero.
    - Must not have any bullets, dashes, or other prefixes.
    - Each line must start with an indent of exactly two spaces relative to the section title, followed by the argument name, colon, and space.
    - The section must have an empty line before it.
  - Exception: Use a type annotation for the parameter if it can have different types, and for each type the method has different behaviour. In this case, use a bullet list with one line per type.
- Returns:
  - Mandatory when the method has any return value except `None`.
  - Omit this section if the method does not return a value or returns `None`.
  - What to include:
    - The semantic meaning of the returned value, units, shape, ordering guarantees, and special cases such as `None`.
  - What to exclude:
    - Type annotations.
  - Style:
    - One concise sentence or a short bullet list.
    - Must be indented under the section; do not use bullets at column zero.
    - Each line must start with an indent of exactly two spaces relative to the section title.
    - The section must have an empty line before it.
- Yields:
  - Mandatory when the method yields values.
  - Use instead of Returns: for iterators and generators.
  - Include emission order, termination conditions, and whether items are unique or cached.
  - Style:
    - Must be indented under the section; do not use bullets at column zero.
    - Must not have any bullets, dashes, or other prefixes.
    - Each line must start with an indent of exactly two spaces relative to the section title.
    - The section must have an empty line before it.
- Raises:
  - Mandatory when the method can raise exceptions.
  - List exceptions that can propagate to callers and the precise conditions that trigger them.
  - Exclude internal guard exceptions that cannot reach the caller.
  - Style:
    - Must be indented under the section; do not use bullets at column zero.
    - Must not have any bullets, dashes, or other prefixes.
    - Each line must start with an indent of exactly two spaces relative to the section title, followed by the exception name, colon, and space.
    - The section must have an empty line before it.
- See the Method Documentation Patterns and Good Examples section below.
- See the Bad Method Documentation Examples section below.

## Property Documentation
- Use these rules for all methods decorated with `@property`.
- Use the method docstring rules for properties unless they are overwritten below.
- Args:
  - Must be omitted.
- Returns:
  - Must be omitted.
- Yields:
  - Must be omitted.
- See the Property Documentation Patterns and Good Examples section below.

## Property Setter Documentation
- Use these rules for all methods decorated with `@*.setter`.
- Every writable property must provide a separate docstring on its setter with an Args: section.
- Use the method docstring rules for properties unless they are overwritten below.
- Returns:
  - Must be omitted.
- See the Property Documentation Patterns and Good Examples section below.

## Prohibited and Allowed Patterns
- Prohibited:
  - Args:\n key (str): ....
  - Returns:\n Iterator[Item]: ....
  - Yields:\n Item: ....
- Allowed:
  - Args:\n key: ....
  - Returns:\n The found item.
  - Yields:\n Each chunk in read order.
  - Raises:\n ValueError: If the shape is invalid.

## Comments
- Always explain why the code exists, not just what it does.
- Add comments to clarify complex logic, algorithms, or transformations.
- Split long or multistep methods into logical sections and comment each section’s purpose.
- Use inline comments only when the intent is not obvious.
- Never leave more than five consecutive lines of code inside functions or methods without a comment.
- Do not comment on self-explanatory code (e.g. library imports or simple assignments).
- Prefer meaningful explanations to repeating code in words.
- Each member of the class must have a comment explaining its purpose.
- All inline comments must:
  - Start with a lowercase letter.
  - Be concise (one sentence when possible).
  - Do not add any comments to any imports and all import sections even if it has more than five lines.
- Use `# guard: <description>` ONLY for a guard clause: an `if` whose body exits the current scope — `return`, `continue`, `break`, `raise`, or `sys.exit`. If the body does anything else (assign, append, call, mutate), it is NOT a guard — use a plain `# <description>` comment or none.
  - Hard test: cover the `if` body. If control leaves the function or loop iteration, it is a guard. Otherwise it is not.
  - Place the guard comment immediately before the `if` statement that performs the check.
  - The description states what the check rejects, literally. Never invent a "skip"/"else" narrative the code does not execute.
  - Keep the description short and focused on what is being validated.
  - Correct:
      # guard: no target position, nothing to move
      if target is None:
        return
  - Wrong (accumulation if — not a guard, comment invents a "skip"):
      # guard: skip rows whose action carries no asset id
      if row[ChapterField.SKILL_AID]:
        asset_aids.add(row[ChapterField.SKILL_AID])
  - Right version of the above:
      # collect asset ids present on skill rows
      if row[ChapterField.SKILL_AID]:
        asset_aids.add(row[ChapterField.SKILL_AID])
- Correct:
```python
# convert vector back to original coordinates
inverse_matrix = np.linalg.inv(self.matrix)
transformed_vector = inverse_matrix @ vector
```
- Wrong:
```python
# Convert vector back to original coordinates
inverse_matrix = np.linalg.inv(self.matrix)  # get inverse matrix
transformed_vector = inverse_matrix @ vector  # apply transformation
```
- Error handling blocks that log and `return` / `break` must have **one** comment explaining the problem — not
  a comment per line. A single comment before the block is enough.
- Correct:
```python
# invalid request, can't be fixed by retries
except BadRequestError as error:
  logger.error(f"raise BadRequestError: {error} response: {response}")
  return None
```
- Wrong:
```python
except BadRequestError as error:
  # log error about invalid request
  logger.error(f"raise BadRequestError: {error} response: {response}")
  # this error can't be fixed by retries
  return None
```

## Marker Comments
The codebase uses several marker prefixes in comments. Each serves a specific purpose and must never be removed or altered without explicit user approval.
- `TODO:` — marks unfinished work or a planned enhancement that has not been implemented yet.
- `TMP:` — marks temporary code (debugging aids, workarounds, scaffolding) that must be removed before the feature is considered complete.
- `DBG:` — marks diagnostic/debug code blocks used during development to inspect runtime state.
- `REF:` — marks source references pointing to related code, classes, constants, or `DOC(…)` groups elsewhere in the codebase. Stripped automatically during generation; serves only as human-readable traceability links.
- `opt:` — marks optimization annotations that explain why a non-obvious implementation choice was made for performance reasons.
- `guard:` — marks a guard clause: an `if` whose body exits the current scope (`return`/`continue`/`break`/`raise`/`sys.exit`). Not for accumulation or branch ifs (see guard rules in Comments section above).
- `DOC(…):` — marks documentation comments that describe domain rules, mechanics, algorithms, or other domain-specific concepts (see DOC Comments section below).
- `waiver:` — marks an intentional exception from a coding rule. The comment must explain **why** the exception is justified. Required whenever `typing.cast()` is used (see Type Casting rules) or any other banned pattern is unavoidable.

## Contract Comments
- `# Contract!` comments mark **caller-visible guarantees** that must survive refactoring.
- They are the **source of truth** for docstring `Guarantees` sections — the `Guarantees` section must only contain items that trace back to a `Contract!` comment or the public protocol (see the Method Documentation rules above).
- When to use:
  - Data ownership guarantees: "returns a deep copy", "modifying the returned value will NOT modify the original".
  - Transaction requirements: "method must support DB transactions".
  - Ordering / lifecycle constraints: "must be called after X", "resets only dynamic data".
  - Override obligations: "subclasses must override X".
  - Coordinate / spatial invariants: "coordinates MUST always be in local space".
  - Algorithm invariants: "all effects must be correctly sorted before applying".
- When **not** to use:
  - Pure implementation details that are invisible to callers.
  - Information that is already obvious from the method signature and type hints.
- Format:
  - Place the comment **inside the method or class body**, on its own line, right before the code it governs.
  - Start with `# Contract!` on its own line (no text after the `!`).
  - The guarantee text follows on subsequent `#` comment lines:
    ```python
    # Contract!
    # The returned clone is a fully independent deep copy;
    # mutating it never affects the original.
    ```
- Treatment rules:
  - Never remove or alter `# Contract!` comments without explicit user approval.
  - When generating or updating a method's docstring `Guarantees` section, include every `Contract!` comment from that method.

## DOC Comments
- DOC comments (`# DOC(group name):`) are special documentation comments that describe domain rules, mechanics, algorithms, or other domain-specific principles.
- The **group name** in parentheses categorizes the comment by topic. **Always use an existing group already present in the codebase** (grep for `# DOC(` to discover existing groups). Do not invent new groups without explicit user approval.
- DOC comments explain **principles and concepts**, not method implementation details.
- DOC comments must always be placed **inside methods or functions**, near the code that implements the described mechanic, or **at class body level** when documenting enum members, class-level constants, or weight mappings that are not tied to a single method. Never place DOC comments between class definitions, above class definitions, or at module level outside a class or function. When a constant or mapping is used by only one method, prefer placing the DOC comment inside that method.
- Never describe what "this method does" or how the code works internally. Instead, describe the underlying domain mechanics, formulas, or rules that the code implements.
- Focus on answering "what are the rules/principles?" rather than "what does the code do?"
- **Never reference code constructs** (class names, method names, variable names, constants, module paths) in DOC comments. DOC comments describe domain concepts and rules in plain language, not code.
- DOC comments are written for human reading and for future extraction tooling (none currently ships in this project).
- Format:
  - Start with `# DOC(group):` followed by optional tags in square brackets.
  - The group name must be lowercase. It can be a single word (e.g., `mechanics`, `principles`, `algorithms`) or dot-separated for subcategories (e.g., `mechanics.fighting`, `mechanics.skills`). Dots are converted to subfolder separators in the generated documentation tree: `DOC(mechanics.fighting)` → `<Specs>/mechanics/fighting/`.
  - Use `# #` for the title line.
  - Continue with `#` for the body text describing the principles.
- Example format:
```python
# DOC(mechanics): [tag1] [tag2]
# # Title of the concept
# Description of the domain mechanics, principles, or rules.
# Additional details about how the system works conceptually.
```
- Correct (describes domain principles):
```python
# DOC(mechanics.skills): [rpg.attributes.*] [skill]
# # Skill execution chance check
# When a skill is used, there is a chance that the skill use may fail at the moment of invocation.
# This chance is determined by the skill's control chance value altered by any relevant modifiers.
# A random roll is made, and if the roll exceeds the skill's chance, the skill use fails, and the
# skill enters a FAILED phase for that round.
```
- Wrong (describes method behavior):
```python
# DOC(mechanics.skills): [rpg.attributes.*] [skill]
# # Skill execution chance check
# This method checks if the skill invocation succeeds. It retrieves the invoke_chance from state
# and compares it with a random roll. If the check fails, the method sets the run_phase to FAILED
# and updates the turn resolution accordingly.
```



# Documentation Patterns and Good Examples

## Class Documentation Patterns and Good Examples
```python
class TemplateForAnyClassDocstring:
  """
  <Noun-phrase summary.>

  <What the class represents and how callers use it. Omit internals.>

  Responsibilities:
    - <Verb-led, caller-visible behaviors.>
    - <Additional duties, effects, orchestration points.>

  Guarantees:
    - <Always-true conditions, ordering or identity constraints, determinism, or thread-safety.>
    - <Cache or lifecycle invariants that must hold across calls.>

  Subclassing:
    - <Required initializations in derived classes.>
    - <Fields that must be set or overridden to change behavior.>
    - <Initialization order dependencies in complex hierarchies.>

  Notes:
    - <Caller-visible caveats, performance, compatibility, serialization, or environment assumptions.>
    - <Deprecations or lifecycle considerations.>

  Attributes:
    public_attr: Description with meaning, units/range if relevant, default, and mutability.
    second_attr: Description with meaning, units/range if relevant, default, and mutability.
    
    long_attr:
      First line of the description.
      Second line of the description.
  """


class ExampleForAnyClassDocstring(Generic[FeatureVectorType]):
  """
  Planner that converts goals and context into concrete actions.

  Accepts high-level goals and the current world snapshot from callers, and produces scheduled actions suitable 
  for execution by the tactical layer. Internal selection, scoring, and queuing details are intentionally omitted.

  Responsibilities:
    - Prioritize goals and expand them into executable actions visible to callers.
    - Maintain a stable action queue interface and emit updates when priorities change.
    - Coordinate with caching and time-slicing so callers see deterministic output for fixed inputs.

  Guarantees:
    - Produces a deterministic action sequence for identical inputs and seed.
    - Preserves action identity and ordering once published to callers until explicitly invalidated.
    - Exposes a stable iteration order over pending actions.

  Subclassing:
    - Override the goal-expansion hook to introduce domain-specific actions.
    - Initialize or override scoring weights to adjust decision preferences.
    - If adding caches, define explicit invalidation triggers and call the base invalidation routine first.

  Notes:
    - Uses lazy recomputation; first access may be O(n) while subsequent reads are amortized O(1).
    - Thread confinement: instances are intended for single-threaded use by default.
    - Serialized form is versioned; consumers must respect the embedded schema version.

  Type Parameters:
    FeatureVectorType: The concrete feature vector type used to encode this action.

  Attributes:
    public_attr: Description with units or range if relevant.
    second_attr: Description with units or range if relevant.
  """


class ExampleForInitDerivedClass(BaseInit):
  """
  Emotional State Initialization Class

  Represents the transient emotional forces influencing the char's behavior and decision-making.
  These emotions shape priorities, biases, and reactions to environmental or social stimuli. Each emotion
  can influence char decisions in subtle or dramatic ways depending on its current intensity.

  Guarantees:
    - All emotional states must lie within the range [0, 1], where:
      - 0 represents the complete absence or suppression of the emotion, resulting in apathy or emotional neutrality.
      - 1 represents a peak intensity of the emotion, strongly influencing behavior, often overriding rational priorities.

  Attributes:
    fear:
      Aversion to perceived danger or threat.
      High fear promotes avoidance, hesitation, or retreat in risky situations.

    confidence:
      Belief in one’s own ability to succeed.
      High confidence promotes initiative, bold tactics, and risk-taking.
  """
```

## Method Documentation Patterns and Good Examples
```python
def method_docstring_template(...):
  """
  <Write an imperative one-line summary.>

  <Describe caller-visible purpose and rationale. Omit algorithms and internals.>

  Overriding:
    - <Include only if special override rules apply. State whether to call super() and how contracts change.>.
    - <List strengthened or weakened preconditions, postconditions, guarantees, and ordering or side-effect differences.>.
    - <Note LSP compatibility, deprecations, and extension points to preserve.>.

  Notes:
    - <State caller preconditions beyond types, required lifecycle or context, and feature flags or environment needs.>.
    - <List observable mutations, external I/O, events, caching changes, and determinism or stability guarantees.>.
    - <Document concurrency constraints, thread safety, reentrancy, blocking, and performance caveats.>.

  Args:
    param1: <Meaning, units, accepted ranges or shapes, nullability, and behavioral impact.>.
    param2: <Keep one line per parameter; mention defaults only if behavior materially changes.>.
    # If behavior differs by type, replace the line above with the typed variant below:
    # paramX:
    #   - typeA: <Behavior for typeA.>.
    #   - typeB: <Behavior for typeB.>.

  Returns:
    <Semantic meaning of the value, units, shape or ordering guarantees, and special cases.>.

  Yields:
    <Item meaning, emission order, termination conditions, and uniqueness or caching.>.

  Raises:
    ExceptionType: <Exact condition that triggers this exception and whether it may partially apply changes.>.
    AnotherError: <Condition.>.
  """


def method_docstring_example(self) -> Iterator[BaseAction]:
  """
  Generate the next actions based on goals and available points.

  Select actions that advance active goals while respecting action points from the caller's perspective.

  Notes:
    - Order is stable across runs with identical context and seed.

  Yields:
    Actions in execution order until points are exhausted.

  Raises:
    ValueError: If no valid targets are available.
  """


def __init__(self, init: float | dict[str, Any] | list[float] | str | Self | None = None):
  """
  Initialize the instance and set the initial state.

  Support multiple input formats to construct the internal state from numeric, mapping, sequence, textual, or existing-instance sources.

  Args:
    init:
      - str: Parse and convert into a dictionary.
      - dict[str, Any]: Validate and import mapping fields.
      - list[float]: Provide two values for a range or three values for a range with a comment.
      - float: Import as a single numeric value.
      - Self: Copy values from another instance.
      - None: Use default initialization.
  """
```

## Property Documentation Patterns and Good Examples
```python
@property
def property_docstring_template(self) -> T:
  """
  <Noun-phrase or single-sentence summary of what this property represents.>

  <Scope: Describe why callers use this property and what it represents at a high level.>

  Overriding:
    - <State how this overrides the base contract: stricter/looser guarantees, ordering, or side effects.>
    - <State whether calling super() is required anywhere in the access path (rare for getters).>
    - <LSP notes, deprecations, migration guidance for implementers.>

  Notes:
    - <Lifecycle or context preconditions required for access (e.g., "Requires initialized geometry.").>
    - <Post-access guarantees and stability/determinism under fixed seeds.>
    - <Observable interactions such as cache warm/invalidations triggered by the first access.>
    - <Concurrency guarantees or restrictions (e.g., "Not thread-safe; external synchronization is required.").>
    - <Performance caveats (e.g., "O(V) on cold access; O(1) after cache is warm.").>

  Raises:
    ValueError: <Condition under which reading this property raises ValueError.>
    RuntimeError: <Condition under which reading this property raises RuntimeError.>
    FileNotFoundError: <If access touches filesystem and a file is missing.>
  """

@property
def property_docstring_example(self) -> "AABB":
  """
  Axis-aligned bounding box of the shape.

  Notes:
    - Computed lazily and cached until geometry mutates.
    - O(V) on first access where V is vertex count; O(1) thereafter.
  """
  
@property
def property_get_set_example(self) -> "Node | None":
  """
  Parent node, or None if detached.

  Notes:
    - Updated by the setter; do not mutate from outside.
    - Access is O(1).
  """

@property_get_set_example.setter
def property_get_set_example(self, value: "Node | None") -> None:
  """
  Set the parent node.

  Scope:
    Reparents this node under the given parent and updates bidirectional links.

  Notes:
    - Updates both sides of the relationship and invalidates ancestry caches.
    - Not thread-safe; external synchronization is required.
    - Emits a 'reparented' event if the parent actually changes.

  Args:
    value: New parent node, or None to detach.

  Raises:
    ValueError: If assigning would create a cycle in the scene graph.
    RuntimeError: If the node is sealed and cannot be reparented.
  """
```


# Bad Examples

## Bad Class Documentation Examples
```python
class Template:
  """
  This the the bad example of the class docstring.
  
  Responsibilities:
    Text must be bulleted under the section;
  - Text must be indented under the section;

  Guarantees:
    Text must be bulleted under the section;
  - Text must be indented under the section;

  Subclassing:  
    Text must be bulleted under the section;
  - Text must be indented under the section;

  Notes:
    Text must be bulleted under the section;
  - Text must be indented under the section;

  Attributes:
  public_attr: Must be indentet under the section;
    - second_attr: Must not have any bullets, dashes, or other prefixes.
  """
```

## Bad Method Documentation Examples
```python
def parent(self, value: "Node | None") -> None:
  """
  This the the bad example of the method docstring.
  
  Notes:
    Text must be bulleted under the section;
  - Text must be indented under the section;
  
  Args:
  value: Text must be indentet under the section;
    - value: Text must not have any bullets, dashes, or other prefixes.
    
  Raises:
  ValueError: Text must be indentet under the section;
    - ValueError: Text must not have any bullets, dashes, or other prefixes.
  
  Yields:
  Text must be indentet under the section;
    - Text must not have any bullets, dashes, or other prefixes.

  Returns:
  Text must be indentet under the section;
    - Text must not have any bullets, dashes, or other prefixes.
  """
```

## Bad Property Documentation Examples
```python
@property
def parent(self) -> str:
  """
  This the the bad example of the property docstring.
  
  Returns:
    This section must not appear in property docstrings.
  """
```
