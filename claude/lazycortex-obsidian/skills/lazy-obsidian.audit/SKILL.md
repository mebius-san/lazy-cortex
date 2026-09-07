---
name: lazy-obsidian.audit
description: "Run when the operator asks whether this vault's live Obsidian config still matches its captured manifest — icons or plugin settings changed by hand, a plugin updated past its captured version, or after pulling a checkout onto a new machine. Compares `.obsidian.manifest.json` against the live config directory and reports drift; the fix is the operator's pick between `/lazy-obsidian.capture` and `/lazy-obsidian.deploy`. Read-first; presents findings, then asks which to fix."
allowed-tools: Read, Glob, Grep, Bash(python3 *), Bash(test *), Bash(mkdir -p *), Bash(date *), Bash(git rev-parse*), AskUserQuestion, Write, Agent
argument-hint: "(no arguments — runs the vault-manifest drift check)"
---
# lazycortex-obsidian audit

Vault-manifest drift check: does the live `.obsidian/` config still match the manifest `/lazy-obsidian.capture` recorded. Consumer-facing only — the plugin's own shipped artifacts are audited by the maintainer's tooling, not here.

## Execution discipline (MANDATORY — read before any action)

This skill has 3 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — Vault manifest drift`
   - `Phase 2 — Report + fix loop`
   - `Phase 3 — Log the run`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `no-manifest`, `skipped-per-user-choice`).
3. **Do not reach the Report step until the ledger shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Phase 1 — Vault manifest drift

Only when the repo carries a vault manifest — `test -f <repo_root>/.obsidian.manifest.json`. Absent → outcome `no-manifest`, skip the phase (the vault predates `/lazy-obsidian.capture`, or this checkout is not a vault).

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/vault_manifest.py" drift <repo_root>
```

The worker writes nothing; it compares the live config directory against the manifest and returns two lists.

- **WARN** per entry in `drift` — the live vault and its manifest disagree. Never auto-resolve: only the operator knows which side is right. Offer the two moves in the fix loop and let them choose — `/lazy-obsidian.capture` (the vault is right, record it) or `/lazy-obsidian.deploy` (the manifest is right, restore it).
- **WARN** per entry in `warnings` — not drift. A plugin whose installed version moved past the one its settings were captured under, and credentials the manifest can never carry.
- **PASS** when both lists are empty.

Outcome: `clean`, `drift: <N>`, or `no-manifest`.

## Phase 2 — Report + fix loop

Collect all findings. Present a grouped report with `PASS` / `WARN` / `FAIL` prefixes. For each `WARN`, one `AskUserQuestion`, its context filled per finding:

```
Context (print before asking):
- Where: /lazy-obsidian.audit · Phase 2 — Report + fix loop; target <repo_root>/.obsidian/ vs <repo_root>/.obsidian.manifest.json
- Found: <the WARN line verbatim — the drifted entry with its live and manifest values, or the warning>
- Why asking: only the operator knows which side is right — the live vault or the manifest
- Answers: `fix` — drift routes through `/lazy-obsidian.capture` (the vault is right, record it) or `/lazy-obsidian.deploy` (the manifest is right, restore it) per the operator's pick, never resolved by hand here; `skip` — left as is, nothing written, shown again on the next audit
AskUserQuestion: header "Drift", question "<entry> differs between the live vault and the manifest at <repo_root> — fix or skip?", options `fix`, `skip` with those descriptions.
```

## Phase 3 — Log the run

`./.logs/claude/lazy-obsidian.audit/YYYY-MM-DD_HH-MM-SS.md` per the logging rule.
