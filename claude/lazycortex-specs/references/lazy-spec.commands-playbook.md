---
description: Multi-step commands — unfolding an operator instruction from # Coordinator commands into a marked mini-plan, failure locking, completion cleared with one note-history line, and the halt exemption. Conditional chapter 7 of the coordination playbook, read on a Command wake.
---
# Multi-step commands — conditional chapter of the coordination playbook

Extracted chapter 7 of `lazy-spec.coordination-playbook.md`, loaded on demand: read this file on a Command wake — a non-empty `# Coordinator commands` section. Every "Chapter N" cross-reference below names a chapter of that common playbook.

An operator instruction dropped into an asset's `# Coordinator commands` section is NOT a checkbox — Markdown canon reserves `- [ ]` for an ask-the-operator gesture, and a command is the reverse: the operator telling the coordinator to act. A non-empty commands section is trigger 3 of the seven live wake triggers (Chapter 1 — eight numbered slots, of which 2 is retired to `spec.catalog-coordinator` and kept only so the others keep their names); an empty section is silence.

**Unfolding into a mini-plan.** On waking to a command, the coordinator expands it into a numbered mini-plan written directly into the SAME section, so the operator sees the plan before execution starts and can intervene between steps. Progress is tracked with a prefix mark at the start of each line — unicode symbols, never markdown checkboxes:

- `✓` — step done.
- `→` — step in progress.
- `·` — step not started yet.

**Memory of the command.** The mini-plan itself is the only memory the coordinator needs — every re-invocation on this asset re-reads the same block and resumes from wherever the marks left off; there is no separate state file.

**Approval bypass.** A command may only skip an ordinary operator-confirmation gate (e.g. a merge that normally asks) when the command's own text, or a rule in scope (Chapter 3), explicitly says so. Absent that explicit grant, the coordinator stops at the gate and drops a `[!question]` exactly as it would outside a command. When a bypass IS explicit, the command's completion line (below) records it as `approved by operator command` — the provenance stays visible even though no interactive confirmation happened.

**Mid-command failure.** A step failing partway stops the whole chain — no partial continuation past a failed step. The command block locks with an outcome line naming where it stopped: `reached step N, failed at <what failed>`.

`<specs-cli>` below is the specs plugin's `bin/lazycortex-specs` file, resolved once per wake exactly as the coordinator agent's own instructions describe.

**Completion.** Once every step reads `✓` (or the chain locked on a failure), the block is removed and ONE line lands in `# History` through `"${LAZYCORTEX_PYTHON:-python3}" <specs-cli> note-history <asset_note> --line "<text>"`, saying what the command did — or where it failed, naming the step — and `# Coordinator commands` goes empty again. The block itself never moves into `# History`; the coordinator supplies only the text, the verb picks the day group and the bullet, and no commit follows — the wake's own commit carries the line like every other pen write. "Empty" keeps the section's own HTML-comment explainer line (`<!-- ... -->`, right under the `#protected/spec/coordinator-commands` tag) — that line is the section's self-description, not a command, and unfolding a mini-plan or clearing a finished block never removes it.

**Commands run on halted assets too.** `spec_halted: true` silences automatic dispatch (checkboxes, cascades, rule-driven "run tests automatically" calls), but a command is an operator gesture aimed straight at a halted asset on purpose — it is how the operator directs recovery. Commands are never blocked by halt.
