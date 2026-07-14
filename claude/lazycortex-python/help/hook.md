---
chapter_type: block
summary: The PostToolUse hook that runs `pcf.py` on every `.py` edit and surfaces style violations inline in the next turn — zero install steps, zero config writes.
last_regen: 2026-07-14
no_diagram: true
source_skills:
  - lazy-python.check-style.sh
  - hooks.json
---
# Inline style feedback on every Python edit

Every time you save a `.py` file — via `Edit` or `Write` — the plugin's PostToolUse hook runs `pcf.py` against that file and returns any violations as `additionalContext` for the next turn. Style problems appear inline, right after the edit that introduced them, without waiting for a manual `chk-py` run or a commit hook. The hook adds no install step and writes nothing to your project's `settings.json`; it self-registers via the plugin's `hooks/hooks.json` manifest the moment the plugin is enabled.

## When you'd use this

- Getting immediate feedback when a new file violates import ordering, docstring structure, line length, or code-format rules — without breaking focus to run `chk-py` manually.
- Iterating on a file that touches multiple `[tool.pcf]` checks at once: each save cycle reports the remaining violations so you can work through them one at a time.
- Working in a project where some directories are excluded from `pcf.py` in `pyproject.toml`: the hook silently no-ops on excluded paths so you are never interrupted by noise from generated or vendored code.

## How it fits together

**`hooks.json`** is the plugin manifest that tells Claude Code's hook engine to fire `lazy-python.check-style.sh` on every `Edit` or `Write` call. It declares a single `PostToolUse` entry with `matcher: "Edit|Write"` and a 15-second timeout. When the plugin is enabled, Claude Code reads this manifest and wires the hook automatically — nothing in your project's `settings.json` is touched.

**`lazy-python.check-style.sh`** is the script the hook engine invokes after each `Edit` or `Write`. It reads the tool call's JSON payload from stdin, pulls out the file path, and immediately exits if the file is not a `.py` file — so the hook is truly silent on every non-Python edit. For `.py` files it resolves both the project directory and the edited file to their real (symlink-resolved) absolute paths, then runs `python3 -m py_compile` on the just-written file: if the file is syntactically incomplete (an in-progress multi-step edit), it exits cleanly rather than reporting spurious violations. When the file parses, it calls `pcf.py` — located via the `$CLAUDE_PLUGIN_ROOT` environment variable the plugin engine exports, so no path configuration is needed — and captures the output. If `pcf.py` emits any `: note:` lines it writes a `hookSpecificOutput` JSON payload to stdout with an `additionalContext` block containing the violation list; if the file is clean (or excluded by `pcf.py`'s own exclude logic) it exits without producing any output.

**`pcf.py`** owns the exclude decision. The hook passes the symlink-resolved absolute path of the edited file to `pcf.py` and lets `pcf.py` decide whether to scan it. If the path matches an entry in `[tool.pcf] exclude` in `pyproject.toml`, `pcf.py` exits cleanly and the hook produces no output. This means adding a directory to the `exclude` list in `pyproject.toml` is the only thing you need to do to silence the hook for that directory — there is no separate hook configuration.

The violation format the hook surfaces is the same `file:line: note: message` format that `chk-py pcf` emits, so findings look identical whether they come from the hook or from a manual checker run.

`/lazy-python.install` never writes to the hook registration itself — it stays out of the hook's own path entirely, since the manifest-based registration needs no consumer-side setup. Install's job is the checker stack the hook depends on: it bootstraps `[tool.pcf]` (and the rest of the checker sections) in `pyproject.toml`, so the hook has exclude rules and check flags to read from the moment it first fires.

## Common adjustments

**Silencing the hook for a directory.** Add the path to the `exclude` list under `[tool.pcf]` in `pyproject.toml`. `/lazy-python.install` Phase 3 seeds this section with `.venv`, `.claude`, `tests`, `~archive`, and `~sandbox`; extend it for any generated or third-party directories you do not want scanned.

**Waiving a specific violation inline.** Add `# waiver: <reason>` on the flagged line, the line above it, or the line below it (class-level waivers also cover an entire class body). `pcf.py` recognises the waiver and suppresses that finding. The waiver comment must carry a non-empty explanation — bare `# waiver:` is not accepted.

**Disabling individual checks project-wide.** Set the relevant flag under `[tool.pcf]` in `pyproject.toml` — for example `check_assert = false` or `check_magic_literal = false`. `/lazy-python.install` Phase 3 seeds a `[tool.pcf]` section with defaults; edit the values there. No skill verb is needed; `pyproject.toml` is a plain project file, not a skill-managed config.

**Per-directory relaxed rules.** Add entries to `[tool.pcf.overrides]` for subdirectories that need different limits, for example `"tools" = { check_magic_literal = false }`. The last matching path prefix wins.

**Checking whether jq is available.** The hook depends on `jq` to parse the Claude Code payload. If `jq` is absent it exits silently rather than erroring. Install `jq` via your system package manager if you want the hook to function.

## See also

- [checkers](checkers.md) — the `chk-py` CLI aggregator that runs `pcf.py` (and four other checks) on demand
- [install-and-audit](install-and-audit.md) — installs the plugin and enables the manifest-based hook registration
