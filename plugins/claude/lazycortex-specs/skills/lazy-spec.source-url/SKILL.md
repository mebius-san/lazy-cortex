---
name: lazy-spec.source-url
description: "Dispatched by every `spec.*` skill and generator agent that emits a link to a file of the product's code — `lazy-spec.create-from-code`, `lazy-spec.sync-with-code`, `lazy-spec.audit`, `lazy-spec.product-config`. Not for direct use except when a human is debugging a wrong link. Nobody writes a code link by hand anywhere else."
execution-discipline-waiver: "Single-purpose primitive — formats one root link; no multi-phase orchestration where step-skip can hide."
---
# Source URL

Primitive skill that builds one link from a spec doc to the product's code. A product's code lives in the same repository as the spec catalog, so the link is a plain in-repo markdown link written from the repository root with a leading `/`. Every emitter in the system (skills + agents) goes through this call.

The contract (root form, files only, where source links may appear) lives in `${CLAUDE_PLUGIN_ROOT}/references/lazy-spec.sources-protocol.md` → "Part 2 — Source-code links". This skill applies it.

## Input

1. **Path** — repo-root-relative path to the target file or folder (e.g., `myapp/chapter.py`). No leading slash.

## Process

### 1. Classify the path

The path names a folder when it ends in `/` or when it is a directory in the working tree; otherwise it names a file.

### 2. Build the result

- **File** → `[<basename>](/<path>)`, where `<basename>` is the last path segment (e.g., `[chapter.py](/myapp/chapter.py)`).
- **Folder** → the path in backticks with no link (e.g., `` `myapp/` ``). Obsidian reads a link to a folder as a new note and creates it, so a folder is never linked.

No URL encoding is performed on `<path>` — callers pass paths whose segments are already safe (standard source files). If the target file has spaces in its path, the caller must encode them.

### 3. Return

The link or the backticked folder path. The skill refuses no input and does not check that the file exists — `lazy-spec.audit` reports a link whose target is missing.

## Output

`[chapter.py](/myapp/chapter.py)` for a file; `` `myapp/` `` for a folder.

## Usage patterns

- **File**: `lazy-spec.source-url("myapp/chapter.py")` — most common; skills emitting source links in `tech`, `code-plan` and `test-plan` files.
- **Folder**: `lazy-spec.source-url("myapp/")` — a directory named in prose, returned as backticked text.
- **Own display text**: a caller that wants other display text keeps the target and swaps the bracketed part — `[the chapter model](/myapp/chapter.py)`.

## Key Rules

- **Root form only.** The target starts with `/` and is relative to the repository root — never relative to the doc, never a forge URL.
- **Files only.** A folder is backticked text, never a link.
- **Never strip or mutate the caller's `path`.** Pass it through verbatim.
- **No line fragments.** Never append `#L<line>`.
- **Idempotent** — given the same input and tree, always returns the same result.
