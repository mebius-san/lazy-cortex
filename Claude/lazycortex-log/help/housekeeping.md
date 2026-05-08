---
chapter_type: block
summary: Keep .logs/claude/ tidy as skills and agents come and go by running /lazy-log.clean to classify, merge, distill, and delete orphaned log folders.
last_regen: 2026-05-08
no_diagram: true
source_skills:
  - lazy-log.clean
---
# Housekeeping

Every skill, agent, and command in a lazycortex-log project writes a timestamped run log into `.logs/claude/<name>/`. Over time, as skills are renamed, subagent tasks accumulate, and old experiments are abandoned, that directory fills with folders that no longer correspond to any live canonical name. `/lazy-log.clean` is the dedicated housekeeping skill for this problem: it walks every subfolder, classifies each one against the current canonical name set, and gives you one interactive decision per orphan (or per cluster) before touching a single file.

## What's in this block

This block contains one skill: `lazy-log.clean`. It covers the full housekeeping lifecycle for `.logs/claude/` — finding what belongs, surfacing what doesn't, and applying the right resolution (merge, distill-then-delete, delete, or leave) for each case. The block exists because log-folder drift is a predictable side-effect of normal project evolution, and it deserves a dedicated, safe, read-first workflow rather than manual `rm -rf`.

## How it works

`/lazy-log.clean` begins by resolving the canonical name set: every skill, agent, and command name currently registered in the project. It then classifies each immediate subdirectory of `.logs/claude/` into one of five buckets.

**Canonical folders** are those whose name matches a live canonical name exactly. They are left alone unless their newest log is more than 30 days old, in which case you are asked whether to keep, archive-then-delete, or delete without archiving.

**Waivered folders** belong to a current artifact that carries a `logging-waiver` declaration — logging was intentionally turned off for that artifact. The folder itself is leftover residue from before the waiver was added. You are shown the waiver reason and up to three log previews, then asked whether to delete, distill-then-delete, or leave. A `delete-all-waivered` shortcut is available on the first prompt if you want to clear the whole waivered bucket at once without reviewing each individually.

**Rename candidates** are orphan folders whose name closely resembles a canonical name (a similarity score of 0.8 or higher). The most common cause is a skill that was renamed mid-project, leaving its old log folder behind. For each candidate you choose to merge (moving its logs into the canonical folder), distill-then-delete, delete outright, or leave.

**Pattern-clustered orphans** are folders matching anonymous-run patterns: `task-N`, `subagent-task-N`, `plan-execute`, `plan-execute-N`, and similar. These are the residue of ephemeral subagent threads that logged under generated names rather than a skill name. Because they tend to appear in bulk, `/lazy-log.clean` batches the entire cluster under one prompt — `delete-all`, `distill-then-delete-all`, `leave-all`, or `per-folder` if you want to review each individually.

**Other orphans** are everything else: folders whose name matches neither a canonical name, a waivered artifact, a rename candidate, nor a known anonymous pattern. You see the folder name, file count, date range, and a one-line preview of the most recent result before choosing `distill-then-delete`, `delete`, or `leave`.

The distill-then-delete path is not simply "read before deleting". It calls Hindsight memory for each substantive finding extracted from the logs — decisions taken, errors hit, surprising results — so that `/lazy-log.recall` can surface them later even after the raw files are gone. Logs whose combined extracted text is under 100 characters with no error or decision keywords are treated as trivial and skipped without a memory call.

The read-first contract is strict: no folder is touched until you have answered every prompt. All mutations are deferred to a single application pass that runs merges first (so source folders exist when their logs are being moved), then deletions.

## Where this fits

The logs that `/lazy-log.clean` manages are the same run logs that underpin the change-history block. `/lazy-log.recall`, `/lazy-log.timeline`, and `/lazy-log.summary` all search `.logs/claude/**` as one of their primary sources. Housekeeping that deletes raw logs without distilling them first would silently degrade those recall results; the distill-then-delete path exists precisely to avoid that trade-off. When you archive a folder through `/lazy-log.clean`, its substantive facts enter Hindsight memory and remain searchable. When you delete without distilling, you are making an explicit choice that those logs are not worth retaining.

Run `/lazy-log.clean` whenever `.logs/claude/` feels cluttered — after a significant rename refactor, after a long subagent-heavy session, or as periodic maintenance before a release cut.
