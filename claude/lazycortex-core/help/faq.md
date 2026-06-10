---
chapter_type: faq
summary: Answers to non-obvious questions about skill selection, upgrade flows, settings placement, plugin composition, agent routing, MCP scope decisions, the expert runtime, memory subsystem, routine types, git coordination, change-history agents, and run-log housekeeping.
last_regen: 2026-06-09
no_diagram: true
source_skills:
  - lazy-core.install
  - lazy-core.audit
  - lazy-core.doctor
  - lazy-core.optimize
  - lazy-core.setup
  - lazy-repo.mark-public
  - lazy-guard.check-public
  - lazy-guard.allow-mcp
  - lazy-routine.register
  - lazy-routine.unregister
  - lazy-runtime.recover
  - lazy-expert.dispatch-job
  - lazy-expert.collect-job
  - lazy-expert.cancel-job
  - lazy-expert.list-jobs
  - lazy-memory.write
  - lazy-memory.index
  - lazy-memory.reflect
  - lazy-memory.mark-persona
  - lazy-core.agent-models
  - lazy-core.git-status
  - lazy-core.git-unlock
  - lazy-log.clean
  - lazy-log.distill
  - lazy-log.recall
  - lazy-log.timeline
  - lazy-log.summary
  - lazy-log.bullets
---
# FAQ

## What is the difference between `/lazy-core.audit` and `/lazy-core.doctor`?

`/lazy-core.audit` is read-only and focuses on measurement: it tells you how many kilobytes load into context on every turn, flags oversized rule files, checks authoring compliance (missing Execution-Discipline preambles, "Optional" headings, narrative padding), verifies rule-file frontmatter and scope, scans MCP enablement state, and checks Python runtime availability for plugin hooks. It also covers help-doc coverage and staleness via its Agent C. No changes are made.

`/lazy-core.doctor` is the full health check: it runs the same content scans and then continues into plugin version currency checks, waiver reconciliation, delegated audits (public-repo guard, logging coverage, diagram coverage, review coverage), and an interactive fix phase where you can repair findings in place, waive persistent WARNs, or migrate settings. It distinguishes between local-tool mode (you are authoring plugins here) and release mode (you are consuming them), suppressing content findings on plugin-owned rules when a newer version of that plugin is available.

Use `/lazy-core.audit` when you want a quick, safe read of the current state. Use `/lazy-core.doctor` when something feels off and you want to diagnose and repair in the same session.

---

## When should I run `/lazy-core.install` versus `/lazy-core.setup`?

`/lazy-core.install` installs one plugin — `lazycortex-core` — by syncing its rule templates and authoring templates into the target `.claude/` directory, and seeding `lazy.settings.json` with the built-in agent-model defaults. `/lazy-core.setup` is the meta-installer: it discovers every enabled plugin that ships a `<namespace>.install` skill (or opts in via `lazy_setup_phase:` frontmatter) and runs them all in the correct order, with `lazy-core.install` going first.

Before any plugin installer runs, `/lazy-core.setup` automatically migrates `.claude/lazy.settings.json` to the current per-section schema (Step 0). This happens transparently — you do not need to run a migration command by hand, and you do not need to know which schema version you are on. If the migration step fails, setup surfaces the reason and stops before touching any plugin files.

Use `/lazy-core.install` directly when you want to re-sync just the core plugin after a `lazycortex-core` update. Use `/lazy-core.setup` after any plugin update, after enabling a new plugin, or on a fresh project clone — it is the single command that brings all plugins current in one pass, settings migration included.

---

## Do I need to migrate `lazy.settings.json` by hand after a plugin update?

No. `/lazy-core.setup` runs a settings migration as its first step (Step 0) before any plugin installer touches the file. The migration ladder upgrades each section of `.claude/lazy.settings.json` to the current schema automatically. The step is transparent: if nothing needs to change, it prints `migrated: 0 sections (N up-to-date)` and continues; if sections are upgraded, it lists each one in the Step 6 report. Only if the migration itself errors (a malformed ladder entry) does setup stop and ask you to investigate.

---

## Do I need to re-run `/lazy-core.install` after a plugin update?

Yes. `/plugin update` refreshes the plugin cache but does not re-sync rule files into `.claude/rules/`. Your project keeps running the old rule content until you explicitly re-run `/lazy-core.install` (or `/lazy-core.setup`, which includes it). This is intentional: syncing can overwrite local edits, so the install skill walks you through each changed file one at a time — overwrite, keep-local, or delete if the file was removed upstream — before touching anything.

---

## Which bump level requires what action from me?

A **patch bump** (e.g. `1.0.0` → `1.0.1`) is safe to drop in with no action — the plugin cache updates automatically when `autoUpdate: true` and the change is backward-compatible. A **minor bump** (e.g. `1.0.0` → `1.1.0`) means new rules, settings keys, or templates were added; re-run `/lazy-core.install` (or `/lazy-core.setup`) to pick them up. A **major bump** (e.g. `1.0.0` → `2.0.0`) means user-data migration is required — read `CHANGELOG.public.md` for the migration steps before re-installing. The README banner at the top of each plugin describes this same contract.

---

## What is `lazy.settings.json` and why does it exist alongside `settings.json`?

`lazy.settings.json` is a separate config file used by the `lazy-core.model-router` hook to route subagent dispatches to model tiers (`haiku`, `sonnet`, `opus`, or `default`). It lives alongside the Claude Code `settings.json` files but is not read by Claude Code itself — it is read by the hook at dispatch time.

The file exists separately because model-routing preferences are architectural decisions (cheapest agent for Explore work, strongest for commit-message generation) that belong in a structured config, not interleaved with per-tool permission lists. Run `/lazy-core.agent-models` to fill and update it interactively. The scope rules are: entries under `_user.*` go to the global `~/.claude/lazy.settings.json`; entries under `_project.*` go to the project `.claude/lazy.settings.json`; plugin-domain groups go to the plugin's own install scope. Run `/lazy-core.optimize` to create the file if it does not exist yet.

---

## What is safe to commit to git, and what should stay gitignored?

The tracked `settings.json` files (global `~/.claude/settings.json` and project `.claude/settings.json`) are for enablement-only entries: `enabledPlugins`, `enabledMcpjsonServers`, `hooks` registrations, non-secret `env` vars, model selection, and status-line config. Per-tool permission entries (`permissions.allow`, `permissions.ask`), `additionalDirectories`, and machine-specific `env` values belong in the gitignored `settings.local.json` files. Committing permission lists leaks your personal risk preferences to teammates who may have different policies. The `lazy-guard.settings` PreToolUse hook enforces this split by intercepting writes to settings files that violate it.

---

## Does `/lazy-guard.allow-mcp` write to `settings.json` or `settings.local.json`?

It writes to `settings.local.json` by default — the gitignored file — because permission choices are personal and machine-local. For a server defined in `.mcp.json` (project scope), it targets `.claude/settings.local.json`. For a server defined in `~/.mcp.json` (global scope), it checks whether existing `mcp__<server>__*` entries already pin the server to global or project scope; if they do, it infers the scope silently. Only when the scope is genuinely undetermined does it ask. It never writes to tracked `settings.json` unless you explicitly override that default during the Phase 5 confirmation.

---

## Why does `/lazy-guard.allow-mcp` leave some tools out of both `allow` and `ask`?

The skill uses a three-bucket classifier. Safe and reversible tools go to `permissions.allow` (no prompt). Truly destructive tools — deletions, force-pushes, working-tree resets — go to `permissions.ask` (prompt on every call). A third category, medium-risk tools, goes to neither list deliberately. Examples include `git_commit` (creates a commit that is locally reversible but worth an acknowledgment) and `cancel_operation`. Tools left out of both lists fall back to Claude Code's built-in per-call prompt, where you decide in context. This skip bucket is intentional: Claude Code's default behavior is a reasonable one-time prompt, and pinning medium-risk tools to either list would either over-trust or over-restrict them.

---

## What is the SessionStart preload hook that `/lazy-guard.allow-mcp` offers, and should I install it?

MCP tools are surfaced to the agent as deferred — only tool names appear at session start; calling one requires a `ToolSearch` round-trip to load its schema. That friction is asymmetric with always-loaded tools like `Bash`, so the agent can drift to shell equivalents even when a rule forbids it. The SessionStart hook injects a short instruction at session start that tells the agent to resolve specific MCP tool schemas via `ToolSearch` immediately, making them first-class for the rest of the session. The cost is approximately 1.1k tokens per session.

`/lazy-guard.allow-mcp` asks whether to install this hook after registering a server's tools. If you say yes, it also asks whether to install at project scope (`.claude/settings.local.json`) or global scope (`~/.claude/settings.local.json`). Because the token cost varies by user and workload, the hook is written only to the gitignored `settings.local.json` — never to tracked `settings.json`.

---

## Can I use `lazy-guard.check-public` on a private repo that has a public subtree?

Yes. The skill supports a `public_scopes` array in `.guard-waivers.json`. When that array is set, only files matching one of its globs are treated as the public surface — everything else is implicitly private and excluded from the scan. The pre-commit hook respects the same array, so commits that only touch files outside the public scopes are not scanned. Run `/lazy-repo.mark-public <glob>` with one or more scope glob arguments to set this up: it adds the globs to `public_scopes`, runs the audit scoped to those paths, walks you through fixes and waivers, and never touches your GitHub repo visibility.

---

## What is the difference between `/lazy-guard.check-public` and `/lazy-repo.mark-public`?

`/lazy-guard.check-public` is a point-in-time audit: it scans, reports, and offers to walk you through fixes, but it does not create the waiver file and does not change GitHub visibility. `/lazy-repo.mark-public` is the full workflow: it calls `/lazy-guard.check-public` internally, then additionally creates `.guard-waivers.json` (which activates the pre-commit hook for future commits), and in whole-repo mode optionally flips the GitHub repo to public via the `gh` CLI. Run `/lazy-guard.check-public` for ongoing hygiene checks on an already-public repo; run `/lazy-repo.mark-public` when you are preparing a repo or subtree for its first public release.

---

## How does `/lazy-core.doctor` handle findings I want to permanently ignore?

After the fix batch, doctor enters a per-WARN waive loop. For each remaining WARN you have not fixed, it offers two options: skip for now (the finding reappears next run) or waive permanently. If you choose waive permanently, a second prompt confirms the action and asks whether to save the waiver under this project or for all projects on this machine. Doctor writes the waiver to a `doctor.waivers/` directory inside your project memory folder; future runs load it and suppress the matching finding automatically. To remove a waiver you delete the file directly — there is no un-waive command. FAIL findings are never offered a waive option.

---

## What does `/lazy-core.optimize` do beyond slimming rule files?

`/lazy-core.optimize` has several phases beyond Phase 2's rule-file slimming. Phase 2.5 runs an LLM-readability audit across all agent-consumed artifact files — detecting decision-logic tables, abstract-header tables, narrative preamble, restated cross-references, decorative markers, and over-long prose paragraphs — and offers rewrites or permanent waivers per finding. Phase 3 and 4 audit global `settings.json` for project-specific entries that have leaked in and offer to migrate them to the correct project `settings.local.json`. Phase 5 checks memory index health (oversized index, orphaned files, broken links, stale entries). Phase 5.5 goes deeper into per-expert memory under `.memory/<expert>/`: it surfaces orphan notes (notes whose tags appear in no local `.tags/` file) and near-duplicate notes (same-tagged notes with very similar titles), offering to reindex, delete, or leave each one. Phase 6 identifies skills that would benefit from the coordinator-plus-parallel-Explore-agents pattern. Phase 7 delegates to `/lazy-core.agent-models` to fill any missing agent routing entries in `lazy.settings.json`. Run it when startup feels slow, after adding new rules or agents, or when `/lazy-core.audit` surfaces readability findings.

---

## Do plugins share settings, or is each plugin's configuration independent?

Each plugin installs its own rule templates and may seed its own section of `lazy.settings.json` (for agent-model routing), but all plugins share the same `settings.json` / `settings.local.json` pair and the same `.guard-waivers.json`. `/lazy-core.setup` runs every plugin's installer in dependency order (core first, then others alphabetically, then post-install cross-cutters) so that later plugins can rely on templates and settings keys seeded by earlier ones. Plugin-owned rule files in `.claude/rules/` are identified by their dot-namespace prefix (e.g. `lazy-core.*`, `lazy-guard.*`), which lets `/lazy-core.install` do orphan detection without touching rules from other plugins or user-authored rules.

---

## When should I use `/lazy-core.agent-models` versus editing `lazy.settings.json` by hand?

Always use `/lazy-core.agent-models`. The skill enforces structural routing rules that hand-edits routinely miss: `_user.*` group entries belong in the global `~/.claude/lazy.settings.json`, `_project.*` entries belong in the project `.claude/lazy.settings.json`, and plugin-domain groups follow the plugin's install scope. Writing an entry to the wrong file produces a split-brain config that `lazy-core.audit` will flag as a finding. The skill also reads `default-tiers.json` to surface curated tier suggestions for every known LazyCortex agent, and it is idempotent — a second run on a fully-configured vault returns "nothing to do" immediately. If you want to see what it would write without touching anything, pass `--dry-run`.

The only time hand-editing `lazy.settings.json` is appropriate is when you are deliberately overriding a tier for a single project (using `/lazy-core.agent-models --scope=project`) and you want to inspect or revert the exact entry afterward. Even then, use the skill for the write and only read the file to verify.

---

## When does `/lazy-core.setup` help versus running each plugin's install skill manually?

`/lazy-core.setup` is the right default after any multi-plugin change: it discovers all enabled plugins automatically (no list to maintain), migrates `lazy.settings.json` to the current schema before any installer runs, resolves dependency order (core before others, post-install configurators last), and continues even if one child fails so you get a single coherent summary rather than hunting for which installer you missed. It is also idempotent — every child skill is idempotent, so re-running setup after a partial failure is safe.

Run a plugin's install skill directly only when you want to re-sync exactly one plugin and you are certain it has no cross-plugin dependencies. The most common case is a `lazycortex-core`-only update where running `/lazy-core.install` is faster and clearer. For everything else — fresh clone, adding a new plugin, upgrading multiple plugins at once — `/lazy-core.setup` is the single command that brings the whole project current.

---

## Why is my new skill, rule, or agent forced into a template?

The `lazy-core.scaffold` rule is always-loaded and fires whenever you create a new file whose path matches the scaffold registry. For skills and commands it points to `skill-template.md`; for agents to `agent-template.md`; for rules to `rule-template.md`. Each template carries the Execution-Discipline preamble (for skills and agents), mandatory frontmatter, and an authoring-notes block you delete before saving.

The reason templates are mandatory rather than optional is that every artifact class has structural requirements enforced by `lazy-core.audit`: skills need the `TaskCreate` preamble so skipped phases stay visible, agents need `tools:` allowlists and `model: inherit`, rules need either `paths:` or an `always_loaded:` waiver. Starting from memory reliably misses at least one of these, and the audit finding surfaces after the artifact is already in use. Starting from the template makes the requirement visible on the first edit, before any code runs.

---

## Why does Claude refuse to write to `~/.claude/` by default?

The `lazy-core.hygiene` rule (always-loaded) sets project-local scope as the default for every artifact — skills, agents, hooks, rules, and config. Writing to `~/.claude/` without an explicit request violates this rule because global artifacts affect every project on the machine: a rule added globally loads into every session, a permission entry allowed globally persists after the project context is gone, and MCP server configs placed globally expose that server everywhere.

The rule is enforced by `lazy-core.audit` and `lazy-core.doctor`. It does not make global writes impossible — it makes them require an explicit instruction ("add this globally" or "this is a cross-project artifact"). When you give that instruction, writes to `~/.claude/` proceed normally. The same rule also enforces dot-namespace naming for every artifact (`namespace.name`, not a flat name like `logging`), the settings split between tracked `settings.json` and gitignored `settings.local.json`, and narrowest-scope MCP placement (project `.mcp.json` unless the server is truly universal).

---

## What is a waivable WARN versus an unwaivable FAIL in the guard scanner?

The distinction is whether the finding represents a certain security boundary violation or a context-dependent judgment call.

**FAILs are never waivable.** They cover secrets that would be directly exploitable if the repo went public: private keys, AWS access keys, API key or token literals, bearer tokens, high-entropy base64 on lines that look like credential assignments, and connection strings with embedded credentials. The scanner blocks the commit or the public-repo workflow and requires you to encrypt, template-ize, or redact the value before proceeding. There is no waiver path for these — the threat model does not have a "it's fine this time" branch.

**WARNs are waivable with a documented reason.** They cover findings that are often real problems but sometimes legitimate: email addresses (yours on a public README is fine; a customer's in a config is not), service user IDs, Tailscale or public IP addresses, internal hostnames, and hardcoded local paths (`/Users/…` or `~/Dropbox/…` style). To accept a WARN, re-run `/lazy-guard.check-public` and pick the "Add waiver" option when the scanner presents the finding — the skill writes the waiver entry including check ID, scope glob, match pattern, reason, and date. Waivers live in `.guard-waivers.json` and are checked on every subsequent scan.

Author-name findings in tracked manifests (`plugin.json`, `package.json`, etc.) are also WARNs. Set your `public_author` by letting `/lazy-guard.check-public` prompt you for it on first use; it records the value in `.guard-waivers.json` and auto-waives matching literals on all future scans.

---

## Do I need to enable the expert runtime, or is it on by default?

The expert runtime is opt-in per repo. When you run `/lazy-core.install`, a wizard phase asks whether to bootstrap runtime and experts for the current repo. If you answer yes, the skill writes the flat `daemon` and `routines` sections into `.claude/lazy.settings.json`, creates `lazy.settings.json[experts]`, copies the `lazy.runtime.sh` shim to `.claude/bin/`, and adds `.experts/` to `.gitignore`. It also offers to install a daemon supervisor (macOS launchd or Linux systemd) and registers the `lazy-expert.pump` routine automatically once you add at least one expert. If you skip that phase or answer no, none of those files are created and the `/lazy-expert.*` skills will abort at Step 2 with "`.experts/` not initialised — run `/lazy-core.install` first."

To enable it later without re-running the full install flow, run `/lazy-core.install` again — it is idempotent and will offer the runtime wizard phase again.

---

## What payload fields does `/lazy-expert.dispatch-job` require?

Every job payload must contain three fields: `kind` (the job type, e.g. `"doc-review"`), `role` (the expert role to handle it, e.g. `"designer"`), and `request` (the task description string). These are the minimum the protocol contract enforces; if any field is missing, dispatch aborts with "payload missing required field(s): `<list>`."

Optional fields — `source` (array of input file paths), `context` (array of context file paths), and `result` (array of expected output paths) — are supported but not required. Protocol-specific extras are also allowed. The full contract is in `claude/lazycortex-core/references/lazy-core.expert-protocols-contract.md`.

---

## How do I check whether a job has finished, and how do I retrieve its output?

Run `/lazy-expert.collect-job` with the `expert_name` and `job_id` returned by `/lazy-expert.dispatch-job`. The skill returns one of four statuses: `pending` (the daemon has not yet processed it), `done` (success), `failed` (the expert wrote an error outcome), or `missing` (the job directory does not exist — the job was never dispatched or was already cancelled). When the status is `done`, the skill also prints the `result` file paths from `response.json` so you can `Read` the output directly.

`/lazy-expert.list-jobs` gives you an overview before you call collect: it prints a table of all jobs — or a filtered subset by expert name or status — with each job's age in seconds. Use the `--status queued` filter to see what is still waiting in the queue, and `--status failed` to identify jobs that need attention.

---

## How do I cancel a job I no longer need?

Run `/lazy-expert.cancel-job` with the `expert_name` and `job_id`. The skill checks whether the job is already `done` (DONE marker present) or still `pending` (READY marker, no DONE). In both cases it asks for confirmation before deleting the job directory. If you cancel a pending job, the daemon may be processing it at that moment — the skill warns you about this and waits for your answer before acting. Cancellation is irreversible: the job directory is removed, and a cancelled job produces no output.

---

## What does `/lazy-routine.unregister` do if the routine name does not exist?

It exits cleanly with an INFO message — "routine `<name>` not found — nothing to unregister" — and logs the outcome as `already-absent`. Unregistering a non-existent routine is treated as a no-op, not an error, so the call is safe to make idempotently.

The one exception is `lazy-expert.pump`, the built-in pump routine. Removing it without passing `--force` aborts with an explicit warning: the pump routine drives the entire expert queue, so removing it stops all expert job processing. If you pass `--force`, the skill removes it with a warning and notes that expert jobs will not run until the routine is re-registered or `/lazy-core.install` is re-run.

---

## When does the runtime daemon halt, and how do I recover it?

The daemon halts in two distinct situations. A **working-tree halt** (`uncommitted_changes`) happens when a routine or expert job leaves the repo in a dirty state — the daemon stops rather than proceeding with uncommitted changes in the tree. A **remote-sync halt** (`git_pull_diverged`, `git_push_failed`, `git_remote_unavailable`) happens when the daemon's pre- or post-tick git sync fails unrecoverably.

Run `/lazy-runtime.recover` to unblock it. For working-tree halts the skill walks you through four options: commit the dirty files (you supply the message), stash them, discard them, or abort and leave the halt in place. For remote-sync halts the skill surfaces reason-specific guidance (the exact git commands to inspect and fix the divergence or push failure) and waits for you to confirm you have resolved the situation before clearing the halt block. Once the halt block is cleared from `.runtime/state.json`, the daemon resumes on its next iteration.

If the cleanup does not produce a clean tree, the skill reports "working tree still dirty; refusing to resume" and leaves the halt intact — inspect with `git status` and re-run the skill.

---

## What routine types does `/lazy-routine.register` support?

Five types, each suited to a different scheduling pattern:

- **subprocess** — the default. Runs a CLI command on every daemon cycle whose `interval_sec` has elapsed.
- **inbox** — watches a directory and dispatches one expert job per file it finds there. Good for ingestion pipelines.
- **schedule** — fires on a cron expression boundary, not on a fixed interval. Useful for calendar-aligned tasks (daily summaries, weekly sweeps).
- **git** — watches local HEAD for new commits, new files, changed files, deleted files, or renamed files and dispatches an expert job per matched event.
- **md-scan** — scans markdown files matching vault-relative globs, filters by frontmatter key/value, and fires in-place (no file move) on each match. Good for processing items whose lifecycle state is tracked in their own frontmatter.

All five require a dot-namespaced `name` (e.g. `acme-lint.tick`). The wizard in `/lazy-routine.register` asks for the type first, then prompts only for the fields that type needs.

---

## What happens if I register a routine whose `inbox_dir` is not gitignored?

`/lazy-routine.register` checks this for `inbox`-type routines using `git check-ignore`. If the directory is tracked rather than gitignored, the skill warns you: an inbox routine moves files between iterations, which dirties the working tree and triggers the daemon's halt protection on every cycle. You get three options — add the directory to `.gitignore` now (recommended), continue anyway and commit moves manually, or abort the registration. If you choose to add it, the skill appends the entry to `.gitignore` but does not auto-commit; you commit when you are ready to coordinate with other in-flight changes.

---

## How do I give an expert long-term memory?

Run `/lazy-memory.mark-persona <expert>` to opt the expert into the memory subsystem. The skill appends `lazycortex-core:lazy-memory.persona-aspect` to the expert's `aspects[]` in `lazy.settings.json[experts]`. From that point:

- The expert may write notes under `.memory/<expert>/` via `/lazy-memory.write` (the only blessed writer of `.memory/`).
- The expert must consult `.memory/<expert>/.tags/*.md` before its primary work.
- Periodic consolidation runs via `/lazy-memory.reflect <expert>` (or the daemon's `memory-reflect-all` routine if enabled).

Memory notes are markdown files with frontmatter (`title`, `tags`, `type`, `summary`) and live in `.memory/<expert>/`. They are tracked in git — the directory is un-ignored explicitly so consolidated learnings travel with the repo.

---

## Why does `/lazy-memory.mark-persona` refuse with "expert not registered"?

`/lazy-memory.mark-persona` checks `lazy.settings.json[experts]` for the expert name you passed. If the key is missing, the skill aborts rather than creating a dangling memory directory for an expert the daemon does not know about. Register the expert first via `/lazy-core.install` (expert-add wizard, Step 11) and then re-run `/lazy-memory.mark-persona`.

---

## Can I write to `.memory/` by hand or must I go through `/lazy-memory.write`?

`/lazy-memory.write` is the only supported writer for `.memory/`. It validates note frontmatter (requiring `title`, `tags` with `memory/` prefixes, `type`, and `summary`), picks a non-colliding slug, regenerates the `.tags/` index files for both the expert and the global `.memory/.tags/`, and commits the change atomically under a `memory.<expert>` git identity. Hand-editing bypasses all of that: tag files go stale, the slug counter gets confused, and the commit identity is wrong.

If you do hand-edit and the tag files drift out of sync with the notes, run `/lazy-memory.index` to rebuild the entire `.tags/` tree from scratch. The index skill walks every expert under `.memory/`, recomputes topic sets from note frontmatter, regenerates tag files, and removes stale tag files that have no backing note.

---

## When should I use `/lazy-core.git-status` versus `/lazy-core.git-unlock`?

`/lazy-core.git-status` is always safe to run first — it is purely read-only and tells you everything: who holds the staging lock, how old the lock is, whether the holder's PID is still alive, and whether the automatic break-the-lock heuristics (dead PID, different host, stale-and-idle) would allow breaking it. Run it whenever a `git add` is unexpectedly refused or a session seems stuck.

Only run `/lazy-core.git-unlock` if the status shows a lock that the automatic heuristics will not break — for example, the holder's PID is alive but you know that session has abandoned its staging window (it crashed mid-stage, or you killed it). The skill shows you the lock details and asks for confirmation before deleting `.git/lazy-git.lock`. Skipping status and going straight to unlock when a lock is legitimately held by an active staging session would corrupt that session's commit.

---

## What is the difference between `lazy-log.recall`, `lazy-log.timeline`, and `lazy-log.summary`?

All three search the same five sources — `.logs/changelog.md`, run logs under `.logs/claude/`, `.logs/commits.jsonl`, git log, and memory files — but they answer different questions.

`lazy-log.recall` answers "why was X changed?" or "when did we touch Y?". It returns ranked matches with git SHAs so you can jump to the exact commit. Use it for point lookups.

`lazy-log.timeline` answers "what happened when?" across a date range or topic. It produces a chronological list grouped by day, marking internal commits (chore/refactor) so you can skim past them. Use it when you want the sequence of events.

`lazy-log.summary` answers "what is the whole story of this feature or area?". It synthesizes a multi-paragraph narrative grouped by sub-theme rather than date, citing SHAs inline and flagging gaps where the historical record is incomplete. Use it when you need to understand the arc of a decision, not just find a single change.

---

## What does `/lazy-log.distill` do and when does it run?

`/lazy-log.distill` reads raw commit entries from `.logs/commits.jsonl` (written by the `lazy-log.commit-recorder` PostToolUse hook on every successful commit) and converts them into themed human-readable prose in `.logs/changelog.md`. Commits sharing a Conventional-commits scope form one theme block; same-day re-runs merge new commits into today's paragraph rather than appending fragments. The agent bumps touched theme blocks to the top of the file so the most recently active areas are always visible first.

The `lazy-log.logging` rule decides whether to invoke the agent after each commit. It skips when there is no commit on the current turn, when the changelog was written less than four hours ago (the 4h floor), or when the commit is not narration-worthy (a version bump or README re-render, for example). It runs unconditionally when you ask for it explicitly ("distill" or "catch up"). You can also trigger it by passing `force` in the prompt to bypass the throttle.

---

## What does `/lazy-log.bullets` produce and when should I invoke it?

`/lazy-log.bullets` converts a commit range scoped to one plugin into a formatted `### <version> — <date> UTC` release block ready to prepend to `CHANGELOG.public.md`. It reads commits via git, filters out internal-only work (pure chore/refactor/style/test commits and dev-tooling plumbing), groups surviving commits by scope, and rewrites them as outcome-led user-facing bullets. The coordinator in a release flow (`/pub.publish`) dispatches this agent automatically; you do not normally invoke it directly. If you need a release block outside that flow — for example, to draft changelog copy before a release — dispatch it with the `plugin`, `plugin_dir`, `range`, `new_version`, and `date` fields the agent requires.

---

## What does `/lazy-log.clean` do and when should I run it?

`/lazy-log.clean` is housekeeping for `.logs/claude/`. Over time that directory accumulates directories from subagent runs that used ephemeral names like `task-3` or `subagent-task-17`, from skills that were renamed after their logs were written, and from waivered artifacts that stopped logging. The skill classifies every subdirectory against the live set of canonical skill/agent/command names and presents each non-canonical folder for your decision — merge into the canonical target, distill substantive logs into project memory before deleting, delete outright, or leave alone. Anonymous pattern clusters (all `task-N` folders at once, for example) are batched into a single prompt so you are not asked dozens of times.

Run it periodically — after a major refactor that renames several skills, after a long development session that generated many ephemeral subagent runs, or whenever `/lazy-core.audit` flags `.logs/claude/` as containing orphaned directories. The skill is read-first: nothing is touched until you have approved every action.

---

## Why does `/lazy-core.install` check Python version before anything else?

Every plugin in the lazycortex marketplace requires Python 3.12 or newer. The install skill runs the Python check as Step 0 — before it touches any files — because all plugin hooks (`lazy-guard.check-public.py`, `lazy-guard.settings.py`, `lazy-core.model-router.py`, `lazy-core.git-guard.py`) will fail silently at runtime if the Python floor is not met. Failing at Step 0 with a clear "install Python 3.12 via brew or pyenv" message is better than installing all the rule files and discovering hook failures later.

Note that `/lazy-core.audit` uses a lower floor of Python 3.12 for its own runtime probe — that check covers whether the Python version is sufficient for hooks' `__future__` annotations and f-strings. The 3.12 install-floor is stricter and is set as the single marketplace-wide requirement so all plugins can rely on it without per-plugin version guards.

---

## Which skills support `--dry-run` and what does it do?

Three skills in this plugin accept `--dry-run`:

- `/lazy-core.setup` — builds and previews the install plan (which skills would run, in what order) without executing any of them. The settings migration step (Step 0) still runs in dry-run mode so the preview reflects the post-migration state.
- `/lazy-core.agent-models` — walks the wizard and reports what tier assignments would be written, without touching either `lazy.settings.json` file.
- `/lazy-guard.allow-mcp` — computes and previews the diff (which tools would land in `allow`, `ask`, or skip) without writing to any settings file.

In all three cases, `--dry-run` is purely read-only: no files are created or modified, and the skill exits after the preview. It is safe to run at any time and does not require undoing anything afterward.

---

## How do I search change history for when or why something was modified?

Use the `lazy-log.recall` agent, dispatched automatically when you ask questions like "why was X changed?" or "when did we change Y?". The agent searches across five sources in priority order: the functional prose in `.logs/changelog.md`, individual skill/agent run logs under `.logs/claude/`, the raw commit feed in `.logs/commits.jsonl`, git log (both commit-message search and diff-content search), and project memory files. Matches are ranked by how strongly they corroborate each other — entries with multiple keyword hits across changelog prose rank highest, while diff-only matches rank lowest. Results come back as a table with git SHAs so you can run `git show <sha>` to jump directly to the actual code change.

The agent does not modify any files. If your query is ambiguous, it shows matches for both interpretations rather than guessing.

---

## What is the difference between a protocol and an aspect?

A **protocol** is routine-side config that defines the request/response contract for the jobs a routine dispatches — the `kind` enum, `role` vocabulary, field shapes, and outcome enum. Different routines can dispatch jobs against the same protocol.

An **aspect** is expert-side config that shapes how the expert acts on top of its protocol. The same protocol can be paired with different aspects across experts. For example, two experts could share the doc-review protocol but only one carries `lazy-memory.persona-aspect` to keep notes between runs. Protocols and aspects are listed in parallel in the expert's user-message prompt — the expert reads both before acting.
