---
chapter_type: block
summary: The PostToolUse hook that runs `pcf.py` on every `.py` edit and surfaces style violations inline in the next turn — zero install steps, zero config writes.
last_regen: 2026-11-13
no_diagram: true
source_skills:
  - lazy-python.check-style
  - lazy-python.check-style.sh
  - hooks.json
  - pcf.py
source_sha: 902130049897392c176eceb5a8d7a8348db7a9bf
surface_sha: 07f1ec927cae56e421bda5f29b09d4d863f5ea629ddf68e87c50fc83c8cb1e8d
---
# Inline style feedback on every Python edit

Every time you save a `.py` file — via `Edit` or `Write` — the plugin's PostToolUse hook runs `pcf.py` against that file and returns any violations as `additionalContext` for the next turn. Style problems appear inline, right after the edit that introduced them, without waiting for a manual `chk-py` run or a commit hook. The hook adds no install step and writes nothing to your project's `settings.json`; it self-registers via the plugin's `hooks/hooks.json` manifest the moment the plugin is enabled.

## When you'd use this

- Getting immediate feedback when a new file violates import ordering, docstring structure, line length, or code-format rules — without breaking focus to run `chk-py` manually.
- Iterating on a file that touches multiple `[tool.pcf]` checks at once: each save cycle reports the remaining violations so you can work through them one at a time.
- Reviewing a finished batch of changes before you commit: `/lazy-python.check-style` adds the manual guideline review and the full `chk-py` + `tst-py` gate on top of what the hook reports per file.
- Working in a project where some directories are excluded from `pcf.py` in `pyproject.toml`: the hook silently no-ops on excluded paths so you are never interrupted by noise from generated or vendored code.

## How it fits together

**`hooks.json`** is the plugin manifest that tells Claude Code's hook engine to fire `lazy-python.check-style.sh` on every `Edit` or `Write` call. It declares a single `PostToolUse` entry with `matcher: "Edit|Write"`, a 15-second timeout, and a command that runs the script explicitly through `bash` rather than relying on the script's own executable bit — so the hook keeps firing even after a sync path that resets file permissions (a mobile git client, a fresh clone that lands the file as non-executable). When the plugin is enabled, Claude Code reads this manifest and wires the hook automatically — nothing in your project's `settings.json` is touched.

**`lazy-python.check-style.sh`** is the script the hook engine invokes after each `Edit` or `Write`. It is a thin shim that hands the tool call's JSON payload on stdin to `bin/check_style_hook.py`, run under the plugin's Python interpreter, so the hook needs no separate JSON tool such as `jq`. That script exits immediately if the payload doesn't parse or the tool name isn't `Edit`/`Write`, then pulls out the file path and exits if the file is not a `.py` file — so the hook is truly silent on every non-Python edit. For `.py` files it resolves both the project directory and the edited file to their real (symlink-resolved) absolute paths, then compiles the just-written file: if the file is syntactically incomplete (an in-progress multi-step edit), it exits cleanly rather than reporting spurious violations. When the file parses, it calls `pcf.py --honor-excludes` — located via the `$CLAUDE_PLUGIN_ROOT` environment variable the plugin engine exports, so no path configuration is needed — and captures the output. If `pcf.py` emits any `: note:` lines it writes a `hookSpecificOutput` JSON payload to stdout with an `additionalContext` block containing the violation list; if the file is clean (or excluded by `pcf.py`'s own exclude logic) it exits without producing any output.

**`pcf.py`** owns both the exclude decision and everything it reports through the hook. The hook passes the symlink-resolved absolute path of the edited file to `pcf.py` with the `--honor-excludes` flag, which is what makes `pcf.py` honor `[tool.pcf] exclude` for a single explicitly-named file — a bare `chk-py pcf <file>` call, or any other invocation without that flag, always checks the exact file it's given regardless of the exclude list, so a manual run and a hook-triggered run can disagree on an excluded path by design. Under `--honor-excludes`, if the path matches an entry in `[tool.pcf] exclude` in `pyproject.toml`, `pcf.py` exits cleanly and the hook produces no output. This means adding a directory to the `exclude` list in `pyproject.toml` is the only thing you need to do to silence the hook for that directory — there is no separate hook configuration. `pcf.py` runs a broad catalog of checks by default — import order, docstring shape, line length, code format, purpose comments, magic literals, assert placement, and the language a comment or docstring is written in — and every finding from any of them, not just formatting, surfaces through the same `additionalContext` path the moment you save the file. Two of those checks step aside for a pytest test file through a shipped `[tool.pcf.overrides]` entry for `**/tests/**/test_*.py`: magic-literal and bare-assert findings never fire there, since a pytest assertion and its expected-value literal are the check doing its job, not production code that needs softening. A test tree with other file names adds its own entry, such as `"tests/**/*.py" = { check_assert = false, check_magic_literal = false }`.

The violation format the hook surfaces is the same `file:line: note: message` format that `chk-py pcf` emits, so findings look identical whether they come from the hook or from a manual checker run.

`/lazy-python.install` never writes to the hook registration itself — it stays out of the hook's own path entirely, since the manifest-based registration needs no consumer-side setup. Install's job is the checker stack the hook depends on: it bootstraps `[tool.pcf]` (and the rest of the checker sections) in `pyproject.toml`, so the hook has exclude rules and check flags to read from the moment it first fires.

**`/lazy-python.check-style`** is the on-demand counterpart to the hook. The hook sees one file at a time, right after you save it, and only reports what `pcf.py` can detect. Run the skill after a batch of edits and before committing ("check my style", "is this ready to commit"): it reviews every Python file in your change set (the union of staged and unstaged changes against `HEAD`, or the paths you pass) in six steps — read the guidelines, identify the modified files, review them manually, run the automated checks, fix what remains, and re-verify.

- **Guidelines are re-read on every run.** It loads the three canonical guidelines shipped with the plugin (coding, documenting, comments), then your project overlay in `docs/guidelines/` and the `## Style` section of your `CLAUDE.md`, if present. The overlay wins on conflict.
- **A manual pass covers what the checkers cannot see.** Docstring quality, contract consistency between signatures and docstrings, guard-clause comments, method organization, naming, structural rules, the substance of `opt:` / `limit:` / `Decision:` marker clauses, and preservation of the special comment markers. A clean hook or a clean `chk-py` run does not replace this pass.
- **Then the full gate.** It runs `chk-py all -q` per file (or per directory when more than three modified files share one), then across the whole project, applies minimal targeted fixes, and re-runs `chk-py all -q` plus `tst-py <module> -q` for each module the edits touched.
- **Tests are never edited silently.** If a fix would change a file under `tests/`, the skill stops and asks you, naming that file, whether to edit the test or keep it and fix the code instead.
- **Persistent violations are escalated.** If checks still fail after the fixes, the skill reports the remaining issues and asks how to proceed rather than looping.

The run ends with one outcome line per step, so a skipped step is visible. The hook gives you the quick signal while you work; the skill is the deliberate review before you commit.

## Common adjustments

**Silencing the hook for a directory.** Add the path to the `exclude` list under `[tool.pcf]` in `pyproject.toml`. `/lazy-python.install` Phase 3 seeds this section with `.venv`, `.claude`, `tests`, `~archive`, and `~sandbox`; extend it for any generated or third-party directories you do not want scanned.

**Waiving a specific violation inline.** Add `# waiver: <reason>` on the flagged line, the line above it, or the line below it (class-level waivers also cover an entire class body). `pcf.py` recognises the waiver and suppresses that finding. The waiver comment must carry a non-empty explanation — bare `# waiver:` is not accepted.

**Disabling individual checks project-wide.** Set the relevant flag under `[tool.pcf]` in `pyproject.toml` — for example `check_assert = false` or `check_magic_literal = false`. `/lazy-python.install` Phase 3 seeds a `[tool.pcf]` section with defaults; edit the values there. No skill verb is needed; `pyproject.toml` is a plain project file, not a skill-managed config.

**Per-directory relaxed rules.** Add entries to `[tool.pcf.overrides]` for subdirectories that need different limits, for example `"tools" = { check_magic_literal = false }`. The last matching path prefix wins.

**Allowing comments or docstrings in another language.** `check_language` (on by default) reports any letter in a comment or docstring that belongs to a script none of `[tool.pcf] allowed_languages` admits — the default is `["english"]`. Add the language you write in (e.g. `"russian"`, `"chinese"`, `"japanese"`) to that list in `pyproject.toml` and the hook stops flagging it; a single quoted foreign word inside a string literal is never scanned, and `# waiver: <reason>` exempts one specific line without widening the project-wide setting.

**Tolerating private names in docstrings.** Two further `[tool.pcf]` lists in `pyproject.toml` quiet docstring findings about private names without turning a check off: `d2_exempt_attr_names` lists private labels that any class may carry in its `Attributes:` section, and `private_name_allowlist` lists private identifiers the docstring checks tolerate in narrative text.

## See also

- [checkers](checkers.md) — the `chk-py` CLI aggregator that runs `pcf.py` (and four other checks) on demand
- [install-and-audit](install-and-audit.md) — installs the plugin and enables the manifest-based hook registration
