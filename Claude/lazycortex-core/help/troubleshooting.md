---
chapter_type: troubleshooting
summary: Common failure modes across lazycortex-core skills — symptoms, likely causes, and fixes.
last_regen: 2026-05-08
diagram_spec:
  anchor: "Diagnostic flowchart"
  request: "diagnostic decision tree routing lazycortex-core troubleshooting entries by observed symptom. Top-level branch on symptom: pre-commit hook silent → hook-not-firing; MCP tools still prompting after allow-mcp → split on cause (server-not-found / server-not-loaded / permission-loop); lazy-core.install failures → split on sub-error (plugin-not-installed / cache-empty / cache-broken / tiers-missing / settings-unwritable); lazy-core.agent-models invalid flag → invalid-scope; lazy-core.setup child fails → setup-child-failed; lazy-repo.mark-public FAIL findings → mark-public-fail-unresolved; lazy-repo.mark-public gh missing → gh-not-installed; doctor or audit stalls → skill-stalls; agent dispatches to wrong model → split (wrong-model / floor-ignored / duplicate-key); experts directory missing → experts-not-init; dispatch payload rejected → payload-missing-fields; collect-job status missing → job-not-found; list-jobs invalid status filter → invalid-status-filter; cancel-job job not found → job-absent; routine register name invalid → routine-name-format; routine already registered → routine-conflict; unregister pump without force → pump-protected; daemon stalled → daemon-stale; runtime recover still dirty → recover-still-dirty; audit experts json invalid → experts-json-invalid; audit reference did not resolve → ref-unresolvable; audit protocol contract false-positive → protocol-heading-mismatch; doctor routine command unresolvable → routine-command-missing; lazy-core.audit global rules empty → audit-global-empty."
  kind_hint: decision-tree
source_skills:
  - lazy-core.install
  - lazy-core.audit
  - lazy-core.doctor
  - lazy-core.setup
  - lazy-core.agent-models
  - lazy-expert.dispatch-job
  - lazy-expert.collect-job
  - lazy-expert.cancel-job
  - lazy-expert.list-jobs
  - lazy-guard.allow-mcp
  - lazy-repo.mark-public
  - lazy-routine.register
  - lazy-routine.unregister
  - lazy-runtime.recover
---
# Troubleshooting

## The pre-commit hook doesn't fire on commits

**Symptom**: You commit to a public repo and Claude Code does not scan staged changes.

**Likely cause**: `.guard-waivers.json` is missing from the repo root. The pre-commit hook uses the presence of this file as the opt-in signal — without it, scanning is disabled.

**Fix**: Run `/lazy-repo.mark-public`. The skill creates `.guard-waivers.json` at the repo root with the correct schema (and any `public_scopes` you select), which is the opt-in signal that activates the hook. From the next commit onward, every `git commit` triggers the scan automatically.

---

## `/lazy-core.install` aborts saying the plugin isn't installed

**Symptom**: Running `/lazy-core.install` produces an error like "plugin isn't actually installed — enable it first".

**Likely cause**: `lazycortex-core@lazycortex` is not listed in `enabledPlugins` in your `~/.claude/settings.json`, or the marketplace entry for `lazycortex` is missing from `extraKnownMarketplaces`.

**Fix**: Add both blocks to `~/.claude/settings.json`:
```json
{
  "extraKnownMarketplaces": {
    "lazycortex": {
      "source": { "source": "github", "repo": "mebius-san/lazy-cortex" },
      "autoUpdate": true
    }
  },
  "enabledPlugins": {
    "lazycortex-core@lazycortex": true
  }
}
```
Restart Claude Code, then re-run `/lazy-core.install`.

---

## `/lazy-core.install` aborts saying the plugin cache is empty

**Symptom**: Running `/lazy-core.install` produces an error like "plugin cache is empty — run `/plugin update` first".

**Likely cause**: The rule glob under the plugin's `installPath` returned zero files. This typically happens on a fresh machine where the plugin was enabled in `settings.json` but the cache was never populated, or after a cache corruption.

**Fix**: Run `/plugin update lazycortex-core@lazycortex` to refresh the local cache, then re-run `/lazy-core.install`.

---

## `/lazy-core.install` Step 4 aborts: "plugin cache is broken"

**Symptom**: `/lazy-core.install` fails at Step 4 (Sync authoring templates) with a message about the templates directory being missing or empty.

**Likely cause**: The `templates/core/` directory inside the plugin cache is absent or empty. This can happen if the plugin was only partially downloaded, or the cache entry was truncated.

**Fix**: Run `/plugin update lazycortex-core@lazycortex` to re-fetch the full plugin, then re-run `/lazy-core.install`.

---

## `/lazy-core.install` Step 6 fails: "default-tiers.json missing or invalid"

**Symptom**: `/lazy-core.install` fails at Step 6 (Seed lazy.settings.json) with a message like "default-tiers.json missing or invalid at `<path>`; reinstall lazycortex-core".

**Likely cause**: `lazy-core.agent-models/default-tiers.json` inside the plugin cache cannot be read or parsed. This file is the single source of truth for built-in subagent model tiers; the skill refuses to fall back to hardcoded values to prevent silent drift.

**Fix**: Reinstall `lazycortex-core` by running `/plugin update lazycortex-core@lazycortex`, then re-run `/lazy-core.install`.

---

## `/lazy-core.install` Step 7 fails: "settings file unwritable"

**Symptom**: `/lazy-core.install` fails at Step 7 (Bootstrap runtime defaults) with a message indicating that `lazy_settings.save_section` encountered a permission or I/O error when writing `lazy-core.runtime` into `.claude/lazy.settings.json`.

**Likely cause**: The `.claude/lazy.settings.json` file or its parent directory has permissions that prevent the skill from writing, or the file was locked by another process.

**Fix**: Check the file permissions on `.claude/lazy.settings.json` and the `.claude/` directory. Ensure both are writable by your current user. Then re-run `/lazy-core.install`.

---

## `/lazy-core.audit` shows empty results for global rules

**Symptom**: The audit reports zero files found under `~/.claude/rules/` even though files exist there.

**Likely cause**: The `Glob` and `Read` tools do not shell-expand `~` or `$HOME`. The audit dispatches subagents that must expand `$HOME` first with a `Bash(echo $HOME)` call before using the resulting absolute path. If the session was started in an unusual environment the expansion may have failed silently.

**Fix**: This is typically transient. Restart the Claude Code session and re-run `/lazy-core.audit`. If it persists, run `/lazy-core.doctor` — it performs the same expansion check and reports the resolved paths, making the failure visible.

---

## `/lazy-core.audit` exits with "experts.settings.json is not valid JSON"

**Symptom**: Running `/lazy-core.audit` produces an error reporting that `experts.settings.json` is not valid JSON.

**Likely cause**: The file was hand-edited and broke its JSON syntax, or a partial write left it in a truncated state.

**Fix**: Run `/lazy-core.install`. The install skill's expert-add wizard re-scaffolds `experts.settings.json` by merging a fresh `{"_version": 1}` base with any previously accepted expert entries — it does not require you to re-register experts if you provide the same names during the wizard. If you want to correct the file manually, inspect it at `.experts/experts.settings.json` and fix the syntax, then re-run `/lazy-core.audit` to confirm.

---

## `/lazy-core.audit` reports an expert agent or protocol reference "did not resolve"

**Symptom**: The expert-runtime section of the `/lazy-core.audit` report contains a FAIL like "expert `<key>`: agent reference `<value>` did not resolve" or "protocol reference `<value>` did not resolve".

**Likely cause**: The `agent` or `protocol` field in `experts.settings.json` uses an unrecognised format, or the artifact it points to is no longer installed. Valid formats are `<plugin-name>:<agent-stem>`, `user:<stem>`, or bare `<stem>`.

**Fix**: Run `/lazy-core.install` to re-register the affected expert — the wizard re-resolves the agent and protocol references and writes only the fields that pass validation. If the referenced plugin has been removed, install it first or update the expert entry to point to a valid replacement.

---

## `/lazy-core.audit` protocol-contract WARN fires even though the sections exist

**Symptom**: The expert-runtime section of `/lazy-core.audit` emits a `WARN` like "protocol for expert `<key>` missing required section(s): kind, role" even though your protocol file visibly contains all five required sections.

**Likely cause**: The section-detection heuristic looks for the literal keywords (`kind`, `role`, `outcome`, `source`, `result`) in heading lines. If your protocol uses alternative heading text — for example `## Request kinds` instead of `## kind` — the heuristic does not match and the WARN fires as a false positive.

**Fix**: Align the protocol file headings with the keywords expected by `lazy-core.expert-protocols-contract.md` (the contract documents the exact heading patterns). Renaming the headings to match the keywords clears the WARN on the next `/lazy-core.audit` run.

---

## `/lazy-core.agent-models` fails immediately with "invalid --scope value"

**Symptom**: Running `/lazy-core.agent-models` (or `/lazy-core.optimize` Phase 7) produces an error about an unrecognised flag.

**Likely cause**: A flag other than `--scope=auto`, `--scope=project`, `--scope=global`, or `--dry-run` was passed to the skill. Any unrecognised token causes an immediate fail.

**Fix**: Re-run with a valid flag. Valid scope values are `auto` (default), `project`, and `global`. Example: `/lazy-core.agent-models --scope=project`.

---

## `/lazy-core.doctor` or `/lazy-core.audit` stalls mid-run

**Symptom**: One of the multi-phase skills appears to stop making progress after completing a few phases.

**Likely cause**: These skills use `TaskCreate` to track each phase. A still-`pending` task is treated as a bug by the skill's execution discipline — it will refuse to proceed to the report step until every prior task is either `completed` or explicitly `skipped`. A context compaction between turns can occasionally leave the task list in an inconsistent state.

**Fix**: Start a fresh session and re-run the skill. Both `/lazy-core.doctor` and `/lazy-core.audit` are idempotent — re-running is safe. If the stall is consistent, run `/lazy-core.audit` first (it is the lighter read-only scan) to confirm the project context loads correctly before re-running the doctor.

---

## `/lazy-core.doctor` Fix L1: "launchctl kickstart" fails with "No such process"

**Symptom**: Accepting the "Restart via supervisor" fix offer (Fix L1) from `/lazy-core.doctor` fails with "No such process" from `launchctl`.

**Likely cause**: The launchd plist for the runtime daemon has been written to `~/Library/LaunchAgents/` but has not yet been loaded via `launchctl load`. `launchctl kickstart` can only restart a service that launchd already knows about.

**Fix**: Run `launchctl load ~/Library/LaunchAgents/com.lazycortex.runtime.<repo-name>.plist` manually from your terminal, then re-run `/lazy-core.doctor` and accept the Fix L1 restart offer again. If the plist file is missing, re-run `/lazy-core.install` to reinstall the supervisor.

---

## `/lazy-core.doctor` Fix L3: routine command path does not exist

**Symptom**: `/lazy-core.doctor` reports a FAIL on a routine under `lazy-core.runtime.routines` with message "routine `<name>` command path does not exist: `<path>`".

**Likely cause**: The plugin that registered this routine has been removed or updated, leaving behind a stale `command` path in `lazy.settings.json` that no longer resolves to an installed plugin binary.

**Fix**: Accept the "Unregister" offer in the doctor's Fix L3 prompt to remove the stale routine entry via `/lazy-routine.unregister`. If the plugin that owned the routine is still installed, re-run `/lazy-core.install` for that plugin to re-register it with the correct current bin path.

---

## `/lazy-core.setup` stops: user declined the confirmation

**Symptom**: `/lazy-core.setup` exits at Step 4 without running any child skills, with a message that setup was aborted.

**Likely cause**: The confirmation prompt at Step 4 (Confirm) was answered with "abort". The skill halts before executing any children when the user declines the plan.

**Fix**: Re-run `/lazy-core.setup` when ready to proceed. All discovered children are idempotent — those that ran in a prior partial execution will simply complete again cleanly.

---

## `/lazy-core.setup` reports one or more child skills failed

**Symptom**: `/lazy-core.setup` completes its run but the report shows one or more child skills under the "failed" section with a reason.

**Likely cause**: A child skill (such as `/lazy-core.install`, `/lazy-guard.allow-mcp`, or `/lazy-core.agent-models`) encountered a failure that appears in its own report. `/lazy-core.setup` never aborts the chain on a child failure — it collects all results and surfaces them together.

**Fix**: Read the reason listed per failed child in the setup report. Address the root cause for each (the other entries in this guide cover the most common child failure modes). Then re-run `/lazy-core.setup` — it is idempotent, so children that already succeeded will complete cleanly again and the previously-failed ones will be retried.

---

## MCP tools keep prompting for permission after running `/lazy-guard.allow-mcp`

**Symptom**: You ran `/lazy-guard.allow-mcp` for a server but Claude Code still asks for permission every time a tool from that server is called.

**Likely cause 1**: The permissions were written to `settings.json` (tracked) but Claude Code applies permissions from `settings.local.json` (gitignored). The skill defaults to `settings.local.json`; if you have a `settings.json` entry for the same tool, the two files may conflict.

**Likely cause 2**: The server's tools fall into the "medium-risk / skip" bucket — these are intentionally left out of both `allow` and `ask` lists so Claude Code prompts once per call for the user to decide in context. This is the intended behaviour for tools in that bucket.

**Fix for cause 1**: Re-run `/lazy-guard.allow-mcp` — it will detect the cross-scope duplicates and strip the redundant entries from the tracked `settings.json` automatically after per-entry confirmation.

**Fix for cause 2**: If you want the tool always allowed without a prompt, run `/lazy-guard.allow-mcp` again and explicitly override the classifier for that tool when prompted.

---

## `/lazy-guard.allow-mcp` stops: "server not found"

**Symptom**: Running `/lazy-guard.allow-mcp <server-name>` produces an error like "server not found — discovered servers are: …".

**Likely cause**: The server name passed as input is not defined in `~/.mcp.json` or `./.mcp.json` at this scope. Either the name is misspelled or the server definition hasn't been added to the relevant `.mcp.json` file yet.

**Fix**: Check the server name against the list shown in the error. Correct the typo, or add the server entry to the appropriate `.mcp.json` file, then re-run `/lazy-guard.allow-mcp`.

---

## `/lazy-guard.allow-mcp` skips a server with "server isn't loaded"

**Symptom**: `/lazy-guard.allow-mcp` emits a warning like "server isn't loaded — restart Claude Code and re-run" and skips the server without registering any tools.

**Likely cause**: The server is defined in `.mcp.json` but has zero matching `mcp__<server>__*` tools visible in the current session. MCP servers are surfaced as deferred tool lists — if the server failed to start or the session pre-dates its definition, no tool names are available to enumerate. The skill never invents tool names.

**Fix**: Restart Claude Code so the server loads and its tools become visible in the session, then re-run `/lazy-guard.allow-mcp`.

---

## `/lazy-repo.mark-public` Step 4 won't proceed: FAIL findings still unresolved

**Symptom**: `/lazy-repo.mark-public` halts at Step 4 (Create `.guard-waivers.json`) with a message that FAIL findings remain.

**Likely cause**: At least one secret-class (category A) finding from the Step 2 audit was not resolved during Step 3. The skill requires every FAIL finding to be encrypted, template-ized, or redacted before it will write the waiver file or proceed to the GitHub visibility flip.

**Fix**: Return to Step 3 and choose a resolution strategy for each outstanding FAIL finding — encrypt the value, replace it with a template placeholder, or redact it from the file. Once all FAIL findings are gone, re-run `/lazy-repo.mark-public` to continue from Step 4 (the skill is idempotent and will resume cleanly).

---

## `/lazy-repo.mark-public` Step 5 fails: `gh` not on PATH or unauthenticated

**Symptom**: The GitHub visibility flip at Step 5 of `/lazy-repo.mark-public` does not run, with an error about `gh` not being found or requiring login.

**Likely cause**: GitHub CLI (`gh`) is not installed on the current machine, or `gh auth login` has not been run and the tool is unauthenticated.

**Fix**: Install GitHub CLI (`brew install gh` on macOS, or see [cli.github.com](https://cli.github.com)) and run `gh auth login`. Then execute `gh repo edit --visibility public` manually from the repo root when ready. The security audit and waiver file created by earlier steps remain valid — no need to re-run the full flow.

---

## An agent dispatches to the default model despite a tier being configured

**Symptom**: An agent you assigned a tier via `/lazy-core.agent-models` (e.g. `opus`) runs on the default model instead. The `model-router` hook fires without applying the configured tier.

**Likely cause**: The tier value stored in `lazy.settings.json` is not one of the three recognised strings (`haiku`, `sonnet`, `opus`). A typo (e.g. `"sonnet-3-7"`, `"claude-opus"`) causes the hook to treat the entry as unset and fall through to the default model. The hook emits a warning to stderr but never blocks the dispatch.

**Fix**: Run `/lazy-core.agent-models` to review and correct the entries. The skill fills only missing entries by default — to replace an incorrect value, remove the bad entry from `lazy.settings.json` first (the skill will then detect it as missing and prompt you to fill it in), or run `/lazy-core.doctor` which flags unrecognised tier values as a configuration error and offers to fix them.

---

## The `LAZY_AGENT_MODEL_FLOOR` cap has no effect on dispatched agents

**Symptom**: You set `LAZY_AGENT_MODEL_FLOOR` in your environment to cap the maximum model tier, but agents still dispatch at a higher tier than intended.

**Likely cause**: The env var value is not one of the three recognised tier names (`haiku`, `sonnet`, `opus`). The hook logs a warning to stderr and ignores an unrecognised floor value entirely, leaving agent dispatch unchanged.

**Fix**: Confirm the value of `LAZY_AGENT_MODEL_FLOOR` in your shell environment (`echo $LAZY_AGENT_MODEL_FLOOR`). Correct it to one of `haiku`, `sonnet`, or `opus`, then restart Claude Code so the hook picks up the updated environment.

---

## A dispatch string appears in multiple `agent_models` groups and routes unexpectedly

**Symptom**: An agent routes to an unexpected model tier. Inspecting `lazy.settings.json` reveals the same dispatch string (e.g. `general-purpose`) listed under two different group keys with different tier values.

**Likely cause**: The `model-router` hook flattens all groups at load time. When the same dispatch string appears in more than one group, the last group processed wins and a warning is emitted to stderr. The winning entry may not be the one you intended.

**Fix**: Run `/lazy-core.agent-models` to audit the current state. After the skill reports, remove the duplicate entry from the group where it should not appear — the skill writes only missing entries and will not remove duplicates automatically. Then verify the intended tier is the sole remaining entry for that dispatch string. Running `/lazy-core.doctor` will also flag cross-group duplicate keys as a configuration error.

---

## `/lazy-expert.dispatch-job` fails: "`.experts/` not initialised"

**Symptom**: Running `/lazy-expert.dispatch-job` produces an error like "`.experts/` not initialised — run `/lazy-core.install` first."

**Likely cause**: The expert runtime has not been bootstrapped for this repo. `/lazy-expert.dispatch-job` requires the `.experts/` directory layout to exist before it can write job files.

**Fix**: Run `/lazy-core.install`. When the wizard asks whether to enable the expert runtime, answer yes. The install skill creates `.experts/`, writes `experts.settings.json`, and bootstraps the required directory layout. Then re-run `/lazy-expert.dispatch-job`.

---

## `/lazy-expert.dispatch-job` rejects the payload with "missing required field(s)"

**Symptom**: `/lazy-expert.dispatch-job` aborts immediately with a message like "payload missing required field(s): kind, role".

**Likely cause**: The payload dict passed to the skill is missing one or more of the three standard fields — `kind`, `role`, and `request` — that every expert protocol requires.

**Fix**: Add the missing fields to your payload. All three must be present: `kind` (the task type, e.g. `"doc-review"`), `role` (the expert role, e.g. `"designer"`), and `request` (the natural-language task description). See the protocol contract at `claude/lazycortex-core/references/lazy-core.expert-protocols-contract.md` for the full field reference.

---

## `/lazy-expert.collect-job` returns `status: missing`

**Symptom**: `/lazy-expert.collect-job` reports `status: missing` along with "Job `<job_id>` not found for expert `<expert_name>`."

**Likely cause**: The job directory was never created (the dispatch failed silently or the wrong `expert_name` was used), or the job was already cancelled by `/lazy-expert.cancel-job`.

**Fix**: Verify the `job_id` and `expert_name` match exactly what `/lazy-expert.dispatch-job` returned. Run `/lazy-expert.list-jobs` to see all active jobs and confirm whether the job was dispatched. If the job is absent, re-dispatch with the correct payload.

---

## `/lazy-expert.cancel-job` reports "Job not found"

**Symptom**: Running `/lazy-expert.cancel-job` produces a message like "Job `<job_id>` not found for expert `<expert_name>`."

**Likely cause**: The job directory does not exist — either the job was never dispatched under that `expert_name` and `job_id` combination, or it was already cancelled and its directory removed.

**Fix**: Run `/lazy-expert.list-jobs` to confirm currently active jobs and verify the `job_id` and `expert_name`. If the job is absent, no cancellation is needed. If the job was dispatched under a different expert key, repeat the cancel with the correct `expert_name`.

---

## `/lazy-expert.list-jobs` rejects the status filter

**Symptom**: Running `/lazy-expert.list-jobs` with a `status` argument fails immediately with "status must be one of: pending, done, failed."

**Likely cause**: The value passed to the `status` filter is not one of the three recognised strings. Common mistakes include passing `READY`, `IN_PROGRESS`, or `DONE` (the internal daemon status names, which differ from the skill's output vocabulary).

**Fix**: Use one of the three valid filter values: `pending`, `done`, or `failed`. To see all jobs regardless of status, omit the `status` argument entirely.

---

## `/lazy-routine.register` rejects the routine name

**Symptom**: Running `/lazy-routine.register` fails immediately with "routine names must be `<plugin>.<verb>` format."

**Likely cause**: The `name` argument does not contain exactly one dot, or one of the two parts (before or after the dot) is empty. The skill enforces the `<plugin>.<verb>` dot-namespace convention for all routine names.

**Fix**: Rename the routine to follow the convention, for example `acme-lint.tick` or `my-plugin.sweep`. Both parts must be non-empty and there must be exactly one dot separator.

---

## `/lazy-routine.register` fails: routine already registered

**Symptom**: Running `/lazy-routine.register` produces an error like "routine `<name>` already registered. Use `--force` to overwrite."

**Likely cause**: A routine with the same name is already present in the `lazy-core.runtime` section of `.claude/lazy.settings.json`. The skill refuses to silently overwrite an existing entry.

**Fix**: If you want to update the existing registration (new command or interval), re-run `/lazy-routine.register` with the `--force` flag. If you want to remove the routine entirely first, run `/lazy-routine.unregister <name>` then re-register.

---

## `/lazy-routine.unregister` refuses to remove `lazy-expert.pump`

**Symptom**: Running `/lazy-routine.unregister lazy-expert.pump` fails with "`lazy-expert.pump` is the built-in expert pump; removing it breaks the experts pipeline."

**Likely cause**: The skill protects the built-in pump routine from accidental removal. Without `lazy-expert.pump`, the runtime daemon stops draining the job queue and expert jobs queue indefinitely.

**Fix**: If removal is intentional, pass the `--force` flag: `/lazy-routine.unregister lazy-expert.pump --force`. Be aware that expert jobs will stop being processed until the routine is re-registered. To restore it later, re-run `/lazy-core.install` — the install skill re-registers the pump if experts are configured.

---

## The runtime daemon appears stale after a restart or fresh install

**Symptom**: `/lazy-core.doctor` reports "runtime daemon appears stale" even after running `/lazy-core.install` and setting up the supervisor. Re-running the doctor immediately after install still shows the same warning.

**Likely cause 1**: On macOS, the launchd plist was written to `~/Library/LaunchAgents/` but has not been loaded yet. A `launchctl load` step is required before `launchctl kickstart` can start the daemon.

**Likely cause 2**: The daemon started successfully but has not yet written a JSONL log line — this takes up to one polling interval (`polling_interval_sec`, default 5 seconds). The liveness check uses log recency as one of its signals.

**Fix for cause 1**: Run `/lazy-core.doctor`. When it reports the daemon as stalled, accept the "Restart via supervisor" fix offer (Fix L1). If `launchctl kickstart` fails with "No such process", the plist is not loaded — run `launchctl load ~/Library/LaunchAgents/com.lazycortex.runtime.<repo-name>.plist` manually, then re-run `/lazy-core.install` to re-register the supervisor if needed.

**Fix for cause 2**: Wait one polling cycle (5 seconds by default), then re-run `/lazy-core.doctor` to confirm the daemon is now live.

---

## The runtime daemon halted and refuses to resume after cleanup

**Symptom**: Running `/lazy-runtime.recover` reports "working tree still dirty; refusing to resume" even after you chose a cleanup mode (commit, stash, or discard).

**Likely cause**: The cleanup operation did not produce a fully clean working tree. This can happen when a submodule has dirty state that `git checkout -- .` or `git stash` does not cover, when a routine left behind untracked files that the chosen mode did not address, or when the cleanup itself raised an error mid-run and left the tree partially cleaned.

**Fix**: Run `git status` manually to see what remains dirty. Resolve any outstanding files by hand — commit them, stash them, or discard them as appropriate — then re-invoke `/lazy-runtime.recover`. The skill re-reads the halt state and re-attempts the resume once the tree is clean. If the state file at `.logs/lazy-core/runtime/state.json` is the source of confusion (e.g., a false positive halt report), you can inspect it directly; the daemon treats an unparseable file as "not halted" and will resume on its next iteration.

---

## Diagnostic flowchart
