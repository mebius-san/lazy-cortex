---
name: lazy-obsidian.audit
description: "Run when the operator asks whether this vault's live Obsidian config still matches its captured manifest — icons or plugin settings changed by hand, a plugin updated past its captured version, or after pulling a checkout onto a new machine. Delegated from `lazy-core.doctor` Phase 3. Read-only comparison of `.obsidian.manifest.json` against the live config directory: every finding names both repair routes — `/lazy-obsidian.capture` when the vault is right, `/lazy-obsidian.deploy` when the manifest is — and the audit runs neither."
allowed-tools: Read, Write, Glob, Grep, Bash(python3 *), Bash("${LAZYCORTEX_PYTHON:-python3}" *), Bash(test *), Bash(mkdir -p *), Bash(date *), Bash(git rev-parse*), Agent
argument-hint: "(no arguments — runs the vault-manifest drift check)"
---
# lazycortex-obsidian audit

Vault-manifest drift check: does the live `.obsidian/` config still match the manifest `/lazy-obsidian.capture` recorded. Consumer-facing only — the plugin's own shipped artifacts are audited by the maintainer's tooling, not here.

The run follows the shared audit shape in `plugins/claude/lazycortex-core/references/lazy-core.audit-contract.md` — severity vocabulary, finding shape, and the read-only boundary come from there. This skill asks nothing and resolves no drift: it names the repair route on the finding line and stops. The one file it writes is its own run log, which `lazy-log.logging` makes mandatory for every run.

## Execution discipline (MANDATORY — read before any action)

This skill has 3 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Phase 1 — Vault manifest drift`
   - `Phase 2 — Report`
   - `Phase 3 — Log the run`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `clean`, `no-manifest`, `logged`).
3. **Do not reach the Report step until the ledger shows Phase 1 `completed`.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Phase 1 — Vault manifest drift

Only when the repo carries a vault manifest — `test -f <repo_root>/.obsidian.manifest.json`. Absent → outcome `no-manifest`, skip the phase (the vault predates `/lazy-obsidian.capture`, or this checkout is not a vault).

```
"${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/vault_manifest.py" drift <repo_root>
```

The worker writes nothing; it compares the live config directory against the manifest and returns two lists.

Outcomes — each finding line carries both repair routes, and the audit runs neither:

- `PASS` — both lists are empty; the live vault and its manifest agree.
- `INFO no-manifest` — `<repo_root>/.obsidian.manifest.json` is absent, so there is nothing to compare; nothing to act on unless the operator wants a manifest, which `/lazy-obsidian.capture` records.
- `INFO` per entry in `warnings` — not drift: a plugin whose installed version moved past the one its settings were captured under, or a credential value the manifest can never carry. Nothing to act on; neither `/lazy-obsidian.capture` nor `/lazy-obsidian.deploy` changes it.
- `WARN` per entry in `drift` — `<repo_root>/.obsidian/` and `<repo_root>/.obsidian.manifest.json` disagree on that entry, and only the operator knows which side is right → `/lazy-obsidian.capture` when the vault is right (record it), `/lazy-obsidian.deploy` when the manifest is (restore it). Never resolved here, and never by hand.
- `FAIL worker-refused` — the worker raised: the manifest at `<repo_root>` does not parse, or the vault has no `.obsidian/` config directory to compare it against → `/lazy-obsidian.capture` rewrites an unparseable manifest from the live vault; a checkout with no config directory at all needs `/lazy-obsidian.install` first.

Outcome: `clean`, `drift: <N>`, `no-manifest`, or `worker-refused`.

## Phase 2 — Report

Render the findings as one line each, in the contract's finding shape, grouped by severity:

```
[<SEVERITY>] <entry> — <live value vs manifest value>; <repair route>
```

The route on each line is the one Phase 1's outcome list names for that severity, repeated per line; there is no trailing recommendations section, and nothing is dispatched. Close with the contract's summary line — `audit: <PASS|WARN|FAIL> (<n> findings)`, the verdict being the highest severity present and `INFO` counting as `PASS`.

Outcome: `reported`.

## Phase 3 — Log the run

Log the run to `./.logs/claude/lazy-obsidian.audit/YYYY-MM-DD_HH-MM-SS.md` per `lazy-log.logging`. Read-only is not an exemption: the finding set this skill produces is variable-shaped, so it is `should-log`, never a waiver candidate. The log is the one file this skill writes.

1. `Bash(mkdir -p ./.logs/claude/lazy-obsidian.audit)` — a separate step from the `Write`, never chained.
2. `Bash(date -u +%Y-%m-%d_%H-%M-%S)` for the filename; `Bash(git rev-parse HEAD)` and `Bash(git rev-parse --abbrev-ref HEAD)` for `git_sha` / `git_branch` (`no-git` when either fails).
3. `Write` the file. Frontmatter: `git_sha`, `git_branch`, `date` (UTC), `input` (the arguments passed, or `none`).
4. Body: `# lazy-obsidian.audit` heading, then `## Actions` — one line per step with its outcome word, plus the per-severity finding counts — and `## Result` with the outcome word and a one-sentence summary.

Outcome: `logged`.
