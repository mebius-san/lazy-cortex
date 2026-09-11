---
description: Comment canon for Python projects that adopt these conventions — purpose comments and guard clauses, marker comments, contract comments, and Domain comments.
---
# Comment Standards

Extracted from `lazy-python.documenting-guidelines.md`, which keeps the
docstring canon; this file carries the comment half — purpose comments and
guard clauses, marker comments, contract comments, and Domain comments for
Python projects that adopt these conventions.

## Comments
- Always explain why the code exists, not just what it does.
- Add comments to clarify complex logic, algorithms, or transformations.
- Split long or multistep methods into logical sections and comment each section’s purpose.
- **Every code block starts with a purpose comment.** A block is any chunk of code that follows a blank separator line inside a function or method body. Its FIRST line must be a purpose comment (`# <what this block is for>`). This applies to every block, including a single trailing `return x` after a blank line.
  - A `# waiver: ...` line is NOT a purpose comment — it exempts a checker rule, nothing more. When a block needs both, the purpose comment goes first, the waiver below it, then the code.
  - Do not verify this with line-count heuristics ("no more than N uncommented lines") — check every block start after a blank line.
  - Complex logic (branching decisions, math, data reshaping, batching, protocol interplay) is commented in detail — explain the why, not a restatement of the code.
  - Applies to production, tests, and test stubs/fakes equally.
  - `pcf`'s `check_block_comments` enforces the *presence* of the comment; whether the comment states a real purpose is the review phase's call. A block that goes green on `pcf` with `# return the result` above `return result` satisfies nothing.
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
  - A `try`/`except` validation whose `except` block exits the scope the same way (e.g. a contract cast that logs and returns on `TypeError`) also qualifies as a guard. Calls that always raise (`pytest.skip`, `sys.exit`) count as exits.
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

The register of a marker's name encodes its category: CAPS markers (`TODO:`, `TMP:`, `DBG:`) are temporary and die before the work is done; Capitalized markers (`Domain(…):`, `Contract:`, `Decision:`) open standalone knowledge blocks; lowercase markers (`opt:`, `guard:`, `limit:`, `waiver:`, `ref:`) are one-line annotations.

A block marker is **not a comment to the code** — it is a standalone block, separated by an empty line from the surrounding code and from any other comments. Never glue it to a statement in place of the block's purpose comment, and never glue other comments to it: every `#` line adjacent to the block is treated as the block's own text.
- `TODO:` — marks unfinished work or a planned enhancement that has not been implemented yet.
- `TMP:` — marks temporary code (debugging aids, workarounds, scaffolding) that must be removed before the feature is considered complete.
- `DBG:` — marks diagnostic/debug code blocks used during development to inspect runtime state.
- `ref:` — marks source references pointing to related code, classes, constants, or `Domain(…)` groups elsewhere in the codebase. Stripped automatically during generation; serves only as human-readable traceability links.
- `opt:` — marks optimization annotations that explain why a non-obvious implementation choice was made for performance reasons.
- `limit:` — marks a deliberate simplification with a known ceiling: the implementation is correct at the current scale but stops being adequate under the named condition. One line, naming the ceiling and the upgrade path.
  - Correct:
      # limit: global lock, per-account locks if throughput matters
      # limit: O(n²) scan, index it if the list grows past a few hundred
  - Not `TODO:` — the code is finished as written; the marker records a boundary, not unfinished work.
  - Not `opt:` — that annotates a choice made **for** performance; this one annotates a choice made **against** it, knowingly.
  - Not `waiver:` — no checker rule is being broken.
  - `pcf` proves only that the clause is non-empty; whether it names a real ceiling and a real upgrade path is the review phase's call.
- `Decision:` — marks a recorded design decision: a real fork where the author chose X over Y and the why is worth keeping next to the code. Hybrid format: the thesis is mandatory on the marker line — `# Decision: <chose X, not Y> — <why>`; rationale or rejected alternatives that do not fit the line continue on the following `#` lines. A short decision stays a single line.
  - Correct:
      # Decision: dict over dataclass — the schema drifts with the config
      # Decision: core/features/export#D-007 — records are append-only
      # rejected in-place edits: anchors point at heading text,
      # rewriting the thesis breaks every inbound link
  - The multi-line form is a standalone block — separated by an empty line from the surrounding code and from any other comments. Never glue it to a statement in place of the block's purpose comment, and never glue other comments to it: every `#` line adjacent to the block is treated as decision text.
  - A qualified token `<asset-or-product path>#D-NNN` at the start of the clause links the marker to a decision record in the spec catalog. Before reworking code that carries such a link, read the record it points to. A bare `D-NNN` without a path resolves to nothing and does not count as a link.
  - Record a decision only when all three tests hold: a real fork existed (at least two viable options were considered); revisiting is costly (the choice constrains further work, or reverting it touches more than one place); the why is not recoverable from the code and its artifacts. Consequences of an already-recorded decision, repository conventions, and anything dictated by existing code or contracts are not decisions.
  - Not `opt:` — that annotates a choice made **for** performance; this one records a fork with no performance motive.
  - Not `limit:` — that annotates a deliberate simplification with a named ceiling; a decision has no ceiling to name.
  - Not `waiver:` — no checker rule is being broken.
  - The clause is written in English, like every other comment — even when the linked registry record is in another language; the thesis is then a translated paraphrase and the original stays behind the link.
  - `pcf` proves only that the thesis is non-empty; whether it records a real fork with an honest why is the review phase's call.
- `guard:` — marks a guard clause: an `if` (or equivalent `try`/`except` validation) whose body exits the current scope (`return`/`continue`/`break`/`raise`/`sys.exit`). Not for accumulation or branch ifs (see guard rules in Comments section above).
- `Domain(…):` — marks documentation comments that describe domain rules, mechanics, algorithms, or other domain-specific concepts (see Domain Comments section below).
- `waiver:` — marks an intentional exception from a coding rule. The comment must explain **why** the exception is justified. Required whenever `typing.cast()` is used (see Type Casting rules) or any other banned pattern is unavoidable.

## Contract Comments
- `# Contract:` comments mark **caller-visible guarantees** that must survive refactoring.
- They are the **source of truth** for docstring `Guarantees` sections — the `Guarantees` section must only contain items that trace back to a `Contract:` comment or the public protocol (see the Method Documentation rules in `lazy-python.documenting-guidelines.md`).
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
  - Presentation details: the exact wording or format of human-readable output — exception message text, log lines, pretty-print or repr formatting. These are presentation, not API; pinning them freezes wording that must stay free to change. A contract on such a string is justified only when a caller demonstrably parses it programmatically, and then it names the parsed structure, not the prose.
- Format:
  - Place the comment **inside the method or class body**, on its own line, above the code it governs — separated from it (and from everything above) by a blank line, per the standalone-block rule in Marker Comments.
  - Start with `# Contract:` on its own line (no text after the colon).
  - The guarantee text follows on subsequent `#` comment lines:
    ```python
    # Contract:
    # The returned clone is a fully independent deep copy;
    # mutating it never affects the original.
    ```
  - Placement by layer. A guarantee that an interface declares for every implementation is written once, on the abstract declaration in the interface: the block sits inside the abstract method's body, above its `raise NotImplementedError`, and states what every implementation MUST honour. An implementation of that method in a subclass never repeats the block; its docstring `Guarantees` section carries the promise and traces it to the interface's contract. A method with no interface declaration — a private helper, a concrete-only method — keeps its contract at the load-bearing spot in its own body, as before.
  - A contract that only one implementation adds on top of the interface's promise, and that callers of that concrete class rely on, goes in that implementation and is not lifted to the interface.
- Treatment rules:
  - Never remove or alter `# Contract:` comments without explicit user approval.
  - When generating or updating a method's docstring `Guarantees` section, include every `Contract:` comment from that method.
  - When a method carries the same `Contract:` block on both its interface declaration and its implementation, the duplicate on the implementation is a finding: keep the interface's block, drop the implementation's, and keep the implementation's `Guarantees` section pointing at the interface.

## Domain Comments
- Domain comments (`# Domain(group name):`) are special documentation comments that describe domain rules, mechanics, algorithms, or other domain-specific principles.
- The **group name** in parentheses categorizes the comment by topic. **Always use a group listed in the project's domain-groups dictionary** (`docs/guidelines/domain-groups.md` — a language-neutral project registry shared by every language's markers). Do not invent new groups without explicit user approval.
- The group `unfiled` is **reserved**: it marks a block whose real group is not in the dictionary yet. It is never listed in the dictionary, and the checker flags every `Domain(unfiled)` block until the operator adds the real group and renames the block.
- Domain comments explain **principles and concepts**, not method implementation details.
- Domain comments must always be placed **inside methods or functions**, near the code that implements the described mechanic, or **at class body level** when documenting enum members, class-level constants, or weight mappings that are not tied to a single method. Never place Domain comments between class definitions, above class definitions, or at module level outside a class or function. When a constant or mapping is used by only one method, prefer placing the Domain comment inside that method.
- Never describe what "this method does" or how the code works internally. Instead, describe the underlying domain mechanics, formulas, or rules that the code implements.
- Focus on answering "what are the rules/principles?" rather than "what does the code do?"
- **Never reference code constructs** (class names, method names, variable names, constants, module paths) in Domain comments. Domain comments describe domain concepts and rules in plain language, not code.
- Domain comments are written for human reading and for extraction: the wiki plugin's domain routine collects the blocks of one group and regenerates that group's document from them, so a block's wording is published prose, not a private note.
- Format:
  - Start with `# Domain(group):`.
  - The group name must be lowercase. It can be a single word (e.g., `mechanics`, `principles`, `algorithms`) or dot-separated for subcategories (e.g., `mechanics.fighting`, `mechanics.skills`). Dots lay the group out in the generated documentation tree: every segment but the last is a directory and the last is the document itself, under the configured output root (`docs/domains` unless the project sets its own) — `Domain(mechanics.fighting)` becomes the `fighting` document inside the `mechanics` directory.
  - Use `# #` for the title line.
  - Continue with `#` for the body text describing the principles.
- Example format:
```python
# Domain(mechanics):
# # Title of the concept
# Description of the domain mechanics, principles, or rules.
# Additional details about how the system works conceptually.
```
- Correct (describes domain principles):
```python
# Domain(mechanics.skills):
# # Skill execution chance check
# When a skill is used, there is a chance that the skill use may fail at the moment of invocation.
# This chance is determined by the skill's control chance value altered by any relevant modifiers.
# A random roll is made, and if the roll exceeds the skill's chance, the skill use fails, and the
# skill enters a FAILED phase for that round.
```
- Wrong (describes method behavior):
```python
# Domain(mechanics.skills):
# # Skill execution chance check
# This method checks if the skill invocation succeeds. It retrieves the invoke_chance from state
# and compares it with a random roll. If the check fails, the method sets the run_phase to FAILED
# and updates the turn resolution accordingly.
```
