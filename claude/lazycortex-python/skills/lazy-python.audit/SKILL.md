---
name: lazy-python.audit
description: Read-only health check across the 11 invariants the lazycortex-python plugin promises — rules mirror integrity, reference resolution, artifact presence, wrappers, pyproject sections (incl. [tool.ruff]), hook registration, venv state (mypy/pylint/pytest/ruff + pytest-clarity/pytest-sugar).
allowed-tools: Bash, Read, Glob, Grep
user-invocable: true
---
# Audit lazycortex-python

Read-only health check that walks the 11 invariants `/lazy-python.install` promises to hold. Each check is a separate sub-process call against `bin/audit_checks.py`; the skill aggregates `{severity, message}` payloads into a single report. Findings are surfaced; nothing is mutated. To fix, re-run `/lazy-python.install` (the install is idempotent and overwrites mirror artifacts).

## Execution discipline (MANDATORY — read before any action)

This skill has 12 ordered steps (11 checks plus the log write). The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Check 1 — Rules mirror integrity`
   - `Check 2 — References resolve`
   - `Check 3 — Artifacts present`
   - `Check 4 — Wrappers deployed`
   - `Check 5 — Pyproject checker sections`
   - `Check 6 — PyCharm inspect.sh available`
   - `Check 7 — Overlay scaffolding headers`
   - `Check 8 — Scaffold registry entry`
   - `Check 9 — CLAUDE.md pointer (informational)`
   - `Check 10 — PostToolUse hook registration`
   - `Check 11 — Venv bootstrap state`
   - `Step 12 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND captured an outcome word for it" — `PASS` / `WARN` / `FAIL` for the check steps, `logged` for Step 12.
3. **Do not reach the Report block until `TaskList` shows every prior task `completed`.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report block is a structural verifier.** Its output MUST contain one line per check above with its severity. A missing line is a bug; do not render the report with gaps.

## Check 1: Rules mirror integrity

Verify the three plugin rule files (`lazy-python.style.md`, `lazy-python.docstrings.md`, `lazy-python.tests.md`) are present and byte-identical in `<consumer>/.claude/rules/` versus `${CLAUDE_PLUGIN_ROOT}/rules/`. Drift means either a manual edit (forbidden — mirrors are plugin-managed) or an interrupted install; both lift with a re-run of `/lazy-python.install`.

Run:

```
Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.audit/bin/audit_checks.py check1 ${CLAUDE_PROJECT_DIR})
```

Outcome: `PASS` / `WARN` (any rule missing) / `FAIL` (any rule drifted).

## Check 2: References resolve

Verify every `${CLAUDE_PLUGIN_ROOT}/references/lazy-python.*.md` path cited from the mirrored consumer rules resolves to an existing file under the plugin's `references/`. A broken pointer means the canon was renamed or removed without updating the rule body.

Run:

```
Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.audit/bin/audit_checks.py check2 ${CLAUDE_PROJECT_DIR})
```

Outcome: `PASS` / `WARN` (no consumer rules to scan) / `FAIL` (any cited path missing).

## Check 3: Artifacts present

Verify the plugin tree at `${CLAUDE_PLUGIN_ROOT}` carries every required artifact — manifest + overview, 3 rules, 5 references, 6 binaries, the PostToolUse hook script + its `hooks.json` manifest, the check-style skill, both authoring agents, and the 5 templates. Missing artifact means the plugin install is incomplete on this machine.

Run:

```
Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.audit/bin/audit_checks.py check3 ${CLAUDE_PROJECT_DIR})
```

Outcome: `PASS` / `FAIL` (any artifact missing).

## Check 4: Wrappers deployed

Verify `<consumer>/cli/chk-py` and `<consumer>/cli/tst-py` exist, carry the executable bit, and contain no unsubstituted `{{CHK_BIN_PATH}}` / `{{TST_BIN_PATH}}` placeholders. Missing wrappers mean install Phase 2 never ran; unsubstituted placeholders mean the install completed with a corrupted template.

Run:

```
Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.audit/bin/audit_checks.py check4 ${CLAUDE_PROJECT_DIR})
```

Outcome: `PASS` (both wrappers deployed and substituted) / `WARN` (one or both wrappers missing) / `FAIL` (placeholder still present — install was interrupted).

## Check 5: Pyproject checker sections

Verify `<consumer>/pyproject.toml` carries the six always-on checker sections (`[tool.pcf]`, `[tool.toi]`, `[tool.pytest]`, `[tool.mypy]`, `[tool.pylint]`, `[tool.ruff]`). Install merges these from `pyproject-defaults.toml`; absence usually means the install never ran on this repo. `[tool.pch]` is NOT required — install adds it only when PyCharm is present on the machine, so its absence is never a finding here.

Run:

```
Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.audit/bin/audit_checks.py check5 ${CLAUDE_PROJECT_DIR})
```

Outcome: `PASS` (all six always-on sections present) / `WARN` (1-2 sections missing) / `FAIL` (3+ sections missing, or `pyproject.toml` itself absent).

## Check 6: PyCharm inspect.sh available

Probe for the PyCharm `inspect.sh` script on `$PATH`. The check is informational — `pch.py` won't run without it, but the rest of the stack (`pcf`, `toi`, `mypy`, `pylint`, `pytest`) is unaffected. Absence is `WARN`, never `FAIL`.

Run:

```
Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.audit/bin/audit_checks.py check6 ${CLAUDE_PROJECT_DIR})
```

Outcome: `PASS` (`inspect.sh` found) / `WARN` (not on `$PATH` — `pch.py` will be skipped).

## Check 7: Overlay scaffolding headers

Verify each of the four overlay files (`coding_guidelines.md`, `documenting_guidelines.md`, `testing_guidelines.md`, `checking_guidelines.md`) under `<consumer>/docs/guidelines/` opens with the canonical `# Project additions to <topic>` header. Install Phase 5 scaffolds the stubs; consumer-edited overlays must preserve the header so writer agents recognize the file as an overlay (not as the canon itself).

Run:

```
Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.audit/bin/audit_checks.py check7 ${CLAUDE_PROJECT_DIR})
```

Outcome: `PASS` (all four headers correct) / `WARN` (1-2 missing or wrong header) / `FAIL` (3+ missing or wrong).

## Check 8: Scaffold registry entry

Verify `<consumer>/.claude/rules/lazy-core.scaffold.md` mentions the `python-template.py` entry (typically under the `_local:` section). Absence means `/lazy-python.install` did not run, or the consumer hand-edited the rule.

Run:

```
Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.audit/bin/audit_checks.py check8 ${CLAUDE_PROJECT_DIR})
```

Outcome: `PASS` (entry present) / `WARN` (file missing or entry absent).

## Check 9: CLAUDE.md pointer (informational)

Report whether `<consumer>/CLAUDE.md` carries a `lazy-python` pointer. This is **informational only** — install never writes such a pointer (the plugin rules load from `.claude/rules/` regardless), so a present pointer is `PASS` and an absent one is `INFO`, never a `WARN`/`FAIL`. An operator may add one by hand if they want it surfaced in their CLAUDE.md.

Run:

```
Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.audit/bin/audit_checks.py check9 ${CLAUDE_PROJECT_DIR})
```

Outcome: `PASS` (pointer present) / `INFO` (CLAUDE.md absent, or no `lazy-python` mention — optional, never a finding).

## Check 10: PostToolUse hook manifest

Verify the plugin ships a well-formed PostToolUse hook manifest at `${CLAUDE_PLUGIN_ROOT}/hooks/hooks.json` — it must parse as JSON and declare at least one `hooks.PostToolUse[].hooks[].command` entry referencing `lazy-python.check-style.sh`. The Claude Code engine auto-registers this hook when the plugin is enabled, so there is no consumer `settings.json` write to verify. Missing manifest or no matching entry is `WARN`; malformed JSON is `FAIL` (the engine cannot load the plugin's hooks until it is fixed).

Run:

```
Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.audit/bin/audit_checks.py check10 ${CLAUDE_PROJECT_DIR})
```

Outcome: `PASS` (manifest present + declares the hook) / `WARN` (manifest missing or no matching PostToolUse entry) / `FAIL` (hooks.json is invalid JSON).

## Check 11: Venv bootstrap state

Mirror the probe-then-fallback logic of `_ensure_venv.sh`, read-only. A venv is "complete" only when all four bins (`mypy`, `pylint`, `pytest`, `ruff`) are executable AND the two pytest plugins (`pytest_clarity`, `pytest_sugar`) import in the venv's interpreter — the same contract `_venv_has_tools` enforces. Try `$VIRTUAL_ENV`, then `<consumer>/.venv`, then `[tool.lazy-python].venv` from pyproject. When none satisfies the contract, the fallback creates/augments `<consumer>/.venv` (the repo root, == probe 2 target) on first `chk-py` — so "no venv yet but `uv` present and `bootstrap-fallback != false`" is `PASS` (implicit). `WARN` covers every recoverable degradation — missing tools/plugins in a found venv (the fallback will augment it in place), no venv plus `bootstrap-fallback = false`, or no `uv` on PATH.

Run:

```
Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.audit/bin/audit_checks.py check11 ${CLAUDE_PROJECT_DIR})
```

Outcome: `PASS` (probe satisfied or fallback bootstrappable) / `WARN` (recoverable degradation — re-run `/lazy-python.install` or configure a venv manually).

## Step 12: Log the run

Log to `./.logs/claude/lazy-python.audit/YYYY-MM-DD_HH-MM-SS.md` per the logging rule (include `git_sha`, `git_branch`, `date`, `input` frontmatter).

Use two separate steps: `Bash(mkdir -p ./.logs/claude/lazy-python.audit)` then the `Write` tool. Never chain with `&&` or `cat > file <<'EOF'`.

Outcome: `logged`.

## Report

One line per check in the canonical list, with its severity. A missing line is a bug.

```
Check  1 — Rules mirror integrity         [<sev>] <message>
Check  2 — References resolve             [<sev>] <message>
Check  3 — Artifacts present              [<sev>] <message>
Check  4 — Wrappers deployed              [<sev>] <message>
Check  5 — Pyproject checker sections     [<sev>] <message>
Check  6 — PyCharm inspect.sh available   [<sev>] <message>
Check  7 — Overlay scaffolding headers    [<sev>] <message>
Check  8 — Scaffold registry entry        [<sev>] <message>
Check  9 — CLAUDE.md pointer (info)       [<sev>] <message>
Check 10 — PostToolUse hook registration  [<sev>] <message>
Check 11 — Venv bootstrap state           [<sev>] <message>

Summary: pass=<n> warn=<n> fail=<n>
```

## Failure modes

- **`audit_checks.py check<N>` exits non-zero** — the check itself crashed (missing positional argument, unknown check id, internal exception); inspect stderr and re-run with a valid argument. A check returning `FAIL` is a finding, not a crash — exit code stays 0.
- **`check1` reports `FAIL` (drift)** — a consumer rule under `.claude/rules/lazy-python.*.md` has been hand-edited away from the plugin canon → re-run `/lazy-python.install` to overwrite the mirror (intentional clobber).
- **`check2` reports `FAIL` (broken pointer)** — a mirrored rule cites a `${CLAUDE_PLUGIN_ROOT}/references/lazy-python.*.md` path that no longer exists in the plugin → either the canon was removed (file a plugin bug) or the consumer's mirror is stale (re-run `/lazy-python.install`).
- **`check3` reports `FAIL` (missing artifact)** — the plugin tree at `${CLAUDE_PLUGIN_ROOT}` is incomplete on this machine → re-run `/plugin update lazycortex-python@lazycortex` to restore.
