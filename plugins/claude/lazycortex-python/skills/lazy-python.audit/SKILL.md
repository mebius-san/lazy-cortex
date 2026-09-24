---
name: lazy-python.audit
description: "Run when the operator asks whether the Python tooling is wired up correctly, or when it silently isn't working — `chk-py` / `tst-py` missing or failing to launch, the check-style hook never firing, the python rules absent from `.claude/rules/`, a checker not in the venv. Read-only; every finding names its own repair route on its own line — most of them a re-run of `/lazy-python.install`."
allowed-tools: Bash, Read, Write, Glob, Grep, Agent
user-invocable: true
---
# Audit lazycortex-python

Read-only health check that walks the 12 invariants the Python surface promises to hold. Each check is a separate sub-process call against `bin/audit_checks.py`; the skill aggregates `{severity, message}` payloads into a single report. Findings are surfaced; nothing is mutated, and every finding carries its own repair route.

The run follows the shared audit shape in `plugins/claude/lazycortex-core/references/lazy-core.audit-contract.md` — severity vocabulary, finding shape, and the read-only boundary come from there.

A check that reports `FAIL` is a finding, and its exit code stays 0. A non-zero exit from `audit_checks.py check<N>` is the check itself crashing — a missing positional argument, an unknown check id, an internal exception — so inspect its stderr and re-run that check with a valid argument before judging the surface.

## Execution discipline (MANDATORY — read before any action)

This skill has 13 ordered steps (12 checks plus the log write). The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
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
   - `Check 12 — Domain-groups dictionary`
   - `Step 13 — Log the run`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND captured an outcome word for it" — `PASS` / `WARN` / `FAIL` for the check steps, `logged` for Step 13.
3. **Do not reach the Report block until the ledger shows every prior task `completed`.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report block is a structural verifier.** Its output MUST contain one line per check above with its severity. A missing line is a bug; do not render the report with gaps.

## Check 1: Rules mirror integrity

Verify the three plugin rule files (`lazy-python.style.md`, `lazy-python.docstrings.md`, `lazy-python.tests.md`) are present and byte-identical in `<consumer>/.claude/rules/` versus `${CLAUDE_PLUGIN_ROOT}/rules/`. Drift means either a manual edit (forbidden — mirrors are plugin-managed) or an interrupted install; both lift with a re-run of `/lazy-python.install`.

Run:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.audit/bin/audit_checks.py" check1 ${CLAUDE_PROJECT_DIR})
```

Outcome: `PASS` / `WARN` (a rule is missing from `<consumer>/.claude/rules/` → re-run `/lazy-python.install` (idempotent; it overwrites the mirror artifacts)) / `FAIL` (a rule was hand-edited away from the plugin canon → re-run `/lazy-python.install` (idempotent; it overwrites the mirror artifacts), an intentional clobber of the mirror).

## Check 2: References resolve

Verify every `${CLAUDE_PLUGIN_ROOT}/references/lazy-python.*.md` path cited from the mirrored consumer rules resolves to an existing file under the plugin's `references/`. A broken pointer means the canon was renamed or removed without updating the rule body.

Run:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.audit/bin/audit_checks.py" check2 ${CLAUDE_PROJECT_DIR})
```

Outcome: `PASS` / `WARN` (no mirrored rules under `<consumer>/.claude/rules/` to scan → re-run `/lazy-python.install` (idempotent; it overwrites the mirror artifacts)) / `FAIL` (a mirrored rule cites a `${CLAUDE_PLUGIN_ROOT}/references/lazy-python.*.md` path that no longer exists → re-run `/lazy-python.install` (idempotent; it overwrites the mirror artifacts) when the mirror is stale; when the canon itself is gone from the plugin tree, file a plugin bug).

## Check 3: Artifacts present

Verify the plugin tree at `${CLAUDE_PLUGIN_ROOT}` carries every required artifact — manifest + overview, 3 rules, 5 references, 6 binaries, the PostToolUse hook script + its `hooks.json` manifest, the check-style skill, every agent under `agents/`, and the 6 templates. Missing artifact means the plugin install is incomplete on this machine.

Run:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.audit/bin/audit_checks.py" check3 ${CLAUDE_PROJECT_DIR})
```

Outcome: `PASS` / `FAIL` (the plugin tree at `${CLAUDE_PLUGIN_ROOT}` is incomplete on this machine → `/plugin update lazycortex-python@lazycortex` restores it).

## Check 4: Wrappers deployed

Verify `<consumer>/cli/chk-py` and `<consumer>/cli/tst-py` exist, open with a shebang, and contain no unsubstituted `{{CHK_BIN_PATH}}` / `{{TST_BIN_PATH}}` placeholders. Missing wrappers mean install Phase 2 never ran; unsubstituted placeholders mean the install completed with a corrupted template.

Run:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.audit/bin/audit_checks.py" check4 ${CLAUDE_PROJECT_DIR})
```

Outcome: `PASS` (both wrappers deployed and substituted) / `WARN` (one or both wrappers missing from `<consumer>/cli/` → re-run `/lazy-python.install` (idempotent; it overwrites the mirror artifacts)) / `FAIL` (a `{{CHK_BIN_PATH}}` / `{{TST_BIN_PATH}}` placeholder is still in the wrapper — the install was interrupted → re-run `/lazy-python.install` (idempotent; it overwrites the mirror artifacts)).

## Check 5: Pyproject checker sections

Verify `<consumer>/pyproject.toml` carries the six always-on checker sections (`[tool.pcf]`, `[tool.toi]`, `[tool.pytest]`, `[tool.mypy]`, `[tool.pylint]`, `[tool.ruff]`). Install merges these from `pyproject-defaults.toml`; absence usually means the install never ran on this repo. `[tool.pch]` is NOT required — install adds it only when PyCharm is present on the machine, so its absence is never a finding here.

Run:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.audit/bin/audit_checks.py" check5 ${CLAUDE_PROJECT_DIR})
```

Outcome: `PASS` (all six always-on sections present) / `WARN` (1-2 sections missing from `<consumer>/pyproject.toml` → re-run `/lazy-python.install` (idempotent; it overwrites the mirror artifacts), which merges them from `pyproject-defaults.toml`) / `FAIL` (3+ sections missing, or `pyproject.toml` itself absent → re-run `/lazy-python.install` (idempotent; it overwrites the mirror artifacts)).

## Check 6: PyCharm inspect.sh available

Probe for the PyCharm `inspect.sh` script on `$PATH`. The check is informational — `pch.py` won't run without it, but the rest of the stack (`pcf`, `toi`, `mypy`, `pylint`, `pytest`) is unaffected. Absence is `WARN`, never `FAIL`.

Run:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.audit/bin/audit_checks.py" check6 ${CLAUDE_PROJECT_DIR})
```

Outcome: `PASS` (`inspect.sh` found) / `WARN` (not on `$PATH`, so `pch.py` stays skipped while the rest of the stack runs → put PyCharm's `inspect.sh` on `$PATH` on this host; no skill in this plugin installs it).

## Check 7: Overlay scaffolding headers

Verify each of the four overlay files (`coding_guidelines.md`, `documenting_guidelines.md`, `testing_guidelines.md`, `checking_guidelines.md`) under `<consumer>/docs/guidelines/` opens with the canonical `# Project additions to <topic>` header. Install Phase 5 scaffolds the stubs; consumer-edited overlays must preserve the header so writer agents recognize the file as an overlay (not as the canon itself).

Run:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.audit/bin/audit_checks.py" check7 ${CLAUDE_PROJECT_DIR})
```

Outcome: `PASS` (all four headers correct) / `WARN` (1-2 overlay files under `<consumer>/docs/guidelines/` missing or carrying the wrong header → re-run `/lazy-python.install` (idempotent; it overwrites the mirror artifacts), whose Phase 5 scaffolds the stubs; a consumer-edited overlay keeps its body, restore the header by hand) / `FAIL` (3+ missing or wrong → re-run `/lazy-python.install` (idempotent; it overwrites the mirror artifacts)).

## Check 8: Scaffold registry entry

Verify `<consumer>/.claude/rules/lazy-core.scaffold.md` mentions the `python-template.py` entry (typically under the `_local:` section). Absence means `/lazy-python.install` did not run, or the consumer hand-edited the rule.

Run:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.audit/bin/audit_checks.py" check8 ${CLAUDE_PROJECT_DIR})
```

Outcome: `PASS` (entry present) / `WARN` (`<consumer>/.claude/rules/lazy-core.scaffold.md` is missing, or carries no `python-template.py` entry → re-run `/lazy-python.install` (idempotent; it overwrites the mirror artifacts)).

## Check 9: CLAUDE.md pointer (informational)

Report whether `<consumer>/CLAUDE.md` carries a `lazy-python` pointer. This is **informational only** — install never writes such a pointer (the plugin rules load from `.claude/rules/` regardless), so a present pointer is `PASS` and an absent one is `INFO`, never a `WARN`/`FAIL`. An operator may add one by hand if they want it surfaced in their CLAUDE.md.

Run:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.audit/bin/audit_checks.py" check9 ${CLAUDE_PROJECT_DIR})
```

Outcome: `PASS` (pointer present) / `INFO` (`<consumer>/CLAUDE.md` absent, or carries no `lazy-python` mention — nothing to act on; install never writes the pointer, and an operator who wants one adds it by hand).

## Check 10: PostToolUse hook manifest

Verify the plugin ships a well-formed PostToolUse hook manifest at `${CLAUDE_PLUGIN_ROOT}/hooks/hooks.json` — it must parse as JSON and declare at least one `hooks.PostToolUse[].hooks[].command` entry referencing `lazy-python.check-style.sh`. The Claude Code engine auto-registers this hook when the plugin is enabled, so there is no consumer `settings.json` write to verify. Missing manifest or no matching entry is `WARN`; malformed JSON is `FAIL` (the engine cannot load the plugin's hooks until it is fixed).

Run:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.audit/bin/audit_checks.py" check10 ${CLAUDE_PROJECT_DIR})
```

Outcome: `PASS` (manifest present + declares the hook) / `WARN` (`${CLAUDE_PLUGIN_ROOT}/hooks/hooks.json` missing, or no PostToolUse entry references `lazy-python.check-style.sh` → `/plugin update lazycortex-python@lazycortex` restores the shipped manifest) / `FAIL` (`hooks.json` is invalid JSON, so the engine loads none of the plugin's hooks → `/plugin update lazycortex-python@lazycortex`).

## Check 11: Venv bootstrap state

Mirror the probe-then-fallback logic of `_ensure_venv.sh`, read-only. A venv is "complete" only when all four bins (`mypy`, `pylint`, `pytest`, `ruff`) are executable AND the two pytest plugins (`pytest_clarity`, `pytest_sugar`) import in the venv's interpreter — the same contract `_venv_has_tools` enforces. Try `$VIRTUAL_ENV`, then `<consumer>/.venv`, then `[tool.lazy-python].venv` from pyproject. When none satisfies the contract, the fallback creates/augments `<consumer>/.venv` (the repo root, == probe 2 target) on first `chk-py` — so "no venv yet but `uv` present and `bootstrap-fallback != false`" is `PASS` (implicit). `WARN` covers every recoverable degradation — missing tools/plugins in a found venv (the fallback will augment it in place), no venv plus `bootstrap-fallback = false`, or no `uv` on PATH.

Run:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.audit/bin/audit_checks.py" check11 ${CLAUDE_PROJECT_DIR})
```

Outcome: `PASS` (probe satisfied or fallback bootstrappable) / `WARN` (recoverable degradation — a found venv missing tools or pytest plugins, no venv plus `bootstrap-fallback = false`, or no `uv` on `$PATH` → re-run `/lazy-python.install` (idempotent; it overwrites the mirror artifacts), or point `[tool.lazy-python].venv` at a venv that satisfies the contract).

## Check 12: Domain-groups dictionary

Verify a domain-groups dictionary exists once the sources carry `Domain(…)` blocks. The path is `.claude/lazy.settings.json[wiki.domains.dictionary]` when configured, else the conventional `docs/guidelines/domain-groups.md`. The style checker deliberately never reads the dictionary — it matches the reserved `unfiled` literal and nothing else — so a repo whose markers all cite groups from a dictionary that was never created passes every checker while validating against nothing. Marked sources plus no dictionary is that condition; the fix is `/lazy-python.knowledge-sweep`, which builds the dictionary from the parked knowledge and refiles the blocks.

Run:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/lazy-python.audit/bin/audit_checks.py" check12 ${CLAUDE_PROJECT_DIR})
```

Outcome: `PASS` (dictionary present, or no `Domain(…)` blocks in the sources yet) / `WARN` (the sources file knowledge under `Domain(…)` groups but the configured or conventional dictionary does not exist, so no group is validated against anything → run `/lazy-python.knowledge-sweep`, which builds it and refiles what is parked).

## Step 13: Log the run

Log to `./.logs/claude/lazy-python.audit/YYYY-MM-DD_HH-MM-SS.md` per the logging rule (include `git_sha`, `git_branch`, `date`, `input` frontmatter).

Use two separate steps: `Bash(mkdir -p ./.logs/claude/lazy-python.audit)` then the `Write` tool. Never chain with `&&` or `cat > file <<'EOF'`.

Outcome: `logged`.

## Report

One line per check in the canonical list, with its severity and the repair route that check's own outcome names — the contract's `[<SEVERITY>] <path-or-artifact> — <what is wrong>; <repair route>` shape, laid out as the fixed-width table below so twelve checks read as one block. A missing line is a bug, and a route repeated across several lines stays repeated — there is no trailing recommendations section. The closing line is the contract's summary, its verdict the highest severity present with `INFO` counting as `PASS`.

```
Check  1 — Rules mirror integrity         [<sev>] <message> | <route>
Check  2 — References resolve             [<sev>] <message> | <route>
Check  3 — Artifacts present              [<sev>] <message> | <route>
Check  4 — Wrappers deployed              [<sev>] <message> | <route>
Check  5 — Pyproject checker sections     [<sev>] <message> | <route>
Check  6 — PyCharm inspect.sh available   [<sev>] <message> | <route>
Check  7 — Overlay scaffolding headers    [<sev>] <message> | <route>
Check  8 — Scaffold registry entry        [<sev>] <message> | <route>
Check  9 — CLAUDE.md pointer (info)       [<sev>] <message> | <route>
Check 10 — PostToolUse hook registration  [<sev>] <message> | <route>
Check 11 — Venv bootstrap state           [<sev>] <message> | <route>
Check 12 — Domain-groups dictionary       [<sev>] <message> | <route>

audit: <PASS|WARN|FAIL> (<n> findings)   pass=<n> info=<n> warn=<n> fail=<n>
```
