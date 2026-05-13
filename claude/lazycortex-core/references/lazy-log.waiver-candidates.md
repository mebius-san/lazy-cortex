# Logging-Waiver Candidate Heuristic

Shared classification rules for `lazy-log.install` and `lazy-log.audit`. One source of truth.

## Classes

| Class | Signal |
|---|---|
| `should-waive` | One of: (a) frontmatter declares `execution-discipline-waiver:` (no executable steps); (b) body contains the verbatim `Do not log this run` instruction; (c) the only tool call in the body is one `Agent(subagent_type: ...)` dispatch (pure delegator); (d) name matches the pre-commit / pre-tool-use pattern (high-frequency, mechanical); (e) deterministic mechanical worker — no `AskUserQuestion`, no judgment / branching language (`decide`, `judge`, `if … then`), body is a fixed pipeline of `Bash` / `Read` / `Write` / `Edit` calls; the artifact is essentially a substitute for a `bin/<name>.py` script; (f) read-only status query — single `Read` (or equivalent inspection), no `Write` / `Edit` / `Bash` mutation, no `AskUserQuestion`, returns a fixed-shape report (e.g. `lazy-expert.list-jobs`, `lazy-core.git-status`, `lazy-review.status`). |
| `already-waived-ok` | Frontmatter has `logging-waiver:` set to a concrete non-empty string. |
| `waiver-suspect` | Frontmatter has `logging-waiver:` but value is empty / `true` / `yes` / a generic single word. |
| `should-log` | Anything else — including any artifact that takes user decisions, makes judgments, or has variable-shape outcomes. |

## Suggested-reason templates per signal

| Signal | Template |
|---|---|
| (a) | `static text — no executable steps` |
| (b) | `static text — no executable steps` (same as (a); both classify help-text artifacts) |
| (c) | `pure delegator — target skill owns the log` |
| (d) | `thin pipeline invoked on every commit — outcome rides the caller's commit message` |
| (e) | `mechanical worker — deterministic pipeline, no judgment to capture` |
| (f) | `read-only status query — single read, no mutation, no decision` |

## Detection notes

- **Signal (e) "judgment language"**: scan SKILL.md body for `\bdecide\b`, `\bjudge\b`, `\bif .+ then\b` (case-insensitive). Absence is necessary but not sufficient — also confirm the body contains no `AskUserQuestion` reference.
- **Signal (c) "pure delegator"**: the body's executable section (after the Execution-Discipline preamble) contains at most one tool reference, and that reference is `Agent(...)` or `Skill(...)`.
- **Class-level exemption** (ephemeral subagents): not a per-file class. Detection is by dispatch context (`Agent(subagent_type: ...)` in some coordinator's body), not frontmatter scan. Already covered by `lazy-log.logging`'s class clause.
