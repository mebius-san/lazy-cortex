# Execution-Discipline Preamble — canonical template

Copy the block below verbatim into your skill, command, or script, immediately after the H1 title and opening descriptive paragraph, before any `##` phase/step heading. Substitute the `«…»` placeholders with concrete values. Never abbreviate the step list, merge two steps, or omit the "structurally impossible" framing.

```markdown
## Execution discipline (MANDATORY — read before any action)

This «skill / command / script» has «N» ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `«Step 1 — Short name»`
   - `«Step 2 — Short name»`
   - …
   - `«Step N−1 — Report»`
   - `«Step N — Log the run»`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced a report line for it". No-ops count only if they produced an explicit outcome line (e.g. `asserted`, `already-ignored`, `absent`, `skipped-per-user-choice`).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.
```

## Notes for authors

- The canonical list IS the contract. When a phase/step is added or removed, update the list in the same edit. Drift between the list and the actual step sections is a `FAIL` in `lazy-core.audit`.
- The outcome vocabulary (one-word per step) keeps the Report step honest — see `lazy-core.skill-writing § 3`.
- To opt out, declare `execution-discipline-waiver: "<concrete reason>"` in frontmatter. `true` / `yes` / `""` are rejected. See `lazy-core.skill-writing § 1.4`.
- Agents share this mechanism — see `lazy-core.agent-writing § 4`.
