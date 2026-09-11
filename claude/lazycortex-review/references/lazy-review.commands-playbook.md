---
description: The command callout — the operator's free-text channel into the review loop, its unfolding into a marked mini-plan, mid-command failure locking, completion into `# History`, and why it runs on a stuck document. Conditional chapter 5 of the coordination playbook, read on a non-empty command callout.
---
# The command callout — conditional chapter of the coordination playbook

Extracted chapter 5 of `lazy-review.coordination-playbook.md`, loaded on demand: read this file when `parse-note`'s report shows a non-empty `> [!todo] #review/command` callout. Every "Chapter N" cross-reference below names a chapter of that common playbook.

`> [!todo] #review/command` is the operator's free-text channel into the loop. It is deliberately **not** a checkbox — `- [ ]` is reserved for an ask-the-operator gesture, and a command is the reverse: the operator telling the coordinator to act. It is deliberately not inside the banner either: the banner is repainted by the system and any operator text there is destroyed on the next repaint, while a separate callout survives every repaint.

**A pending command runs on EVERY wake, first.** Whatever trigger woke you, `parse-note`'s report is in front of you — if it shows a non-empty command callout, execute (or resume) it before any other business of the wake. The trigger names why you woke, not the only thing you may see; an operator who commits a command alongside answers or edits has given an instruction, and an instruction outranks your routine reaction to the same commit. Deferring a visible command to some future `command`-labeled wake is the failure mode, not a discipline.

**Unfolding into a mini-plan.** On waking to a command, expand it into a numbered mini-plan written into the **same callout**, so the operator sees the plan before execution starts and can intervene between steps. Progress is a prefix mark at the start of each line — unicode symbols, never markdown checkboxes, which would be read as gestures: `✓` done, `→` in progress, `·` not started.

**Memory of the command.** The mini-plan is the only memory needed. Every later wake on this document re-reads the same block and resumes from wherever the marks left off; there is no separate state.

**Mid-command failure.** A step failing partway stops the whole chain — no continuation past a failed step. Lock the block with an outcome line naming where it stopped: `reached step N, failed at <what failed>`.

**Completion.** Once every step reads `✓`, or the chain locked on a failure, the callout is removed, leaving the channel empty again, and `# History` gets one ordinary content line for the command: what the document now says (or no longer says) because of it — for a failed command, what the operator asked and where it stopped. The mini-plan with its step marks is the coordinator's working state and dies with the callout; internal dispatch steps are process the operator never needs back.

**A command runs on a stuck document.** Whatever else is true — a turn in flight, a barrier held, a job whose marker never cleared — the command is an operator gesture aimed deliberately at this document, and it is how the operator directs recovery. It is also the operator's manual wake: a trigger that was lost to a detection edge is recovered by dropping a command in. Never blocked.
