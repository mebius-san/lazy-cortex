---
chapter_type: faq
summary: Answers to non-obvious questions about skill selection, upgrade flows, settings placement, plugin composition, agent routing, MCP scope decisions, and the expert runtime.
last_regen: 2026-05-06
no_diagram: true
source_skills:
  - lazy-core.install
  - lazy-core.audit
  - lazy-core.doctor
  - lazy-core.optimize
  - lazy-core.setup
  - lazy-core.agent-models
  - lazy-core.git-status
  - lazy-core.git-unlock
  - lazy-expert.dispatch-job
  - lazy-expert.collect-job
  - lazy-expert.cancel-job
  - lazy-expert.list-jobs
  - lazy-guard.allow-mcp
  - lazy-guard.check-public
  - lazy-repo.mark-public
  - lazy-routine.register
  - lazy-routine.unregister
  - lazy-runtime.recover
---
# FAQ

## What is the difference between `/lazy-core.audit` and `/lazy-core.doctor`?

`/lazy-core.audit` is read-only and focuses on measurement: it tells you how many kilobytes load into context on every turn, flags oversized rule files, checks authoring compliance (missing Execution-Discipline preambles, "Optional" headings, narrative padding), verifies rule-file frontmatter and scope, scans MCP enablement state, and checks Python runtime availability for plugin hooks. It also covers help-doc coverage and staleness via its Agent C. No changes are made.

`/lazy-core.doctor` is the full health check: it runs the same content scans and then continues into plugin version currency checks, waiver reconciliation, delegated audits (public-repo guard, logging coverage, diagram coverage, review coverage), and an interactive fix phase where you can repair findings in place, waive persistent WARNs, or migrate settings. It distinguishes between local-tool mode (you are authoring plugins here) and release mode (you are consuming them), suppressing content findings on plugin-owned rules when a newer version of that plugin is available.

Use `/lazy-core.audit` when you want a quick, safe read of the current state. Use `/lazy-core.doctor` when something feels off and you want to diagnose and repair in the same session.

---

## When should I run `/lazy-core.install` versus `/lazy-core.setup`?

`/lazy-core.install` installs one plugin — `lazycortex-core` — by syncing its rule templates and authoring templates into the target `.claude/` directory, and seeding `lazy.settings.json` with the built-in agent-model defaults. `/lazy-core.setup` is the meta-installer: it discovers every enabled plugin that ships a `<namespace>.install` skill (or opts in via `lazy_setup_phase:` frontmatter) and runs them all in the correct order, with `lazy-core.install` going first.

Use `/lazy-core.install` directly when you want to re-sync just the core plugin after a `lazycortex-core` update. Use `/lazy-core.setup` after any plugin update, after enabling a new plugin, or on a fresh project clone — it is the single command that brings all plugins current in one pass.

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

`/lazy-core.optimize` has several phases beyond Phase 2's rule-file slimming. Phase 2.5 runs an LLM-readability audit across all agent-consumed artifact files — detecting decision-logic tables, abstract-header tables, narrative preamble, restated cross-references, decorative markers, and over-long prose paragraphs — and offers rewrites or permanent waivers per finding. Phase 3 and 4 audit global `settings.json` for project-specific entries that have leaked in and offer to migrate them to the correct project `settings.local.json`. Phase 5 checks memory index health. Phase 6 identifies skills that would benefit from the coordinator-plus-parallel-Explore-agents pattern. Phase 7 delegates to `/lazy-core.agent-models` to fill any missing agent routing entries in `lazy.settings.json`. Run it when startup feels slow, after adding new rules or agents, or when `/lazy-core.audit` surfaces readability findings.

---

## Do plugins share settings, or is each plugin's configuration independent?

Each plugin installs its own rule templates and may seed its own section of `lazy.settings.json` (for agent-model routing), but all plugins share the same `settings.json` / `settings.local.json` pair and the same `.guard-waivers.json`. `/lazy-core.setup` runs every plugin's installer in dependency order (core first, then others alphabetically, then post-install cross-cutters) so that later plugins can rely on templates and settings keys seeded by earlier ones. Plugin-owned rule files in `.claude/rules/` are identified by their dot-namespace prefix (e.g. `lazy-core.*`, `lazy-guard.*`), which lets `/lazy-core.install` do orphan detection without touching rules from other plugins or user-authored rules.

---

## When should I use `/lazy-core.agent-models` versus editing `lazy.settings.json` by hand?

Always use `/lazy-core.agent-models`. The skill enforces structural routing rules that hand-edits routinely miss: `_user.*` group entries belong in the global `~/.claude/lazy.settings.json`, `_project.*` entries belong in the project `.claude/lazy.settings.json`, and plugin-domain groups follow the plugin's install scope. Writing an entry to the wrong file produces a split-brain config that `lazy-core.audit` will flag as a finding. The skill also reads `default-tiers.json` to surface curated tier suggestions for every known LazyCortex agent, and it is idempotent — a second run on a fully-configured vault returns "nothing to do" immediately. If you want to see what it would write without touching anything, pass `--dry-run`.

The only time hand-editing `lazy.settings.json` is appropriate is when you are deliberately overriding a tier for a single project (using `/lazy-core.agent-models --scope=project`) and you want to inspect or revert the exact entry afterward. Even then, use the skill for the write and only read the file to verify.

---

## When does `/lazy-core.setup` help versus running each plugin's install skill manually?

`/lazy-core.setup` is the right default after any multi-plugin change: it discovers all enabled plugins automatically (no list to maintain), resolves dependency order (core before others, post-install configurators last), and continues even if one child fails so you get a single coherent summary rather than hunting for which installer you missed. It is also idempotent — every child skill is idempotent, so re-running setup after a partial failure is safe.

Run a plugin's install skill directly only when you want to re-sync exactly one plugin and you are certain it has no cross-plugin dependencies. The most common case is a `lazycortex-core`-only update where running `/lazy-core.install` is faster and clearer. For everything else — fresh clone, adding a new plugin, upgrading multiple plugins at once — `/lazy-core.setup` is the single command that brings the whole project current.

---

## Why is my new skill, rule, or agent forced into a template?

The `lazy-core.scaffold` rule is always-loaded and fires whenever you create a new file whose path matches the scaffold registry. For skills and commands it points to `skill-template.md`; for agents to `agent-template.md`; for rules to `rule-template.md`. Each template carries the Execution-Discipline preamble (for skills and agents), mandatory frontmatter, and an authoring-notes block you delete before saving.

The reason templates are mandatory rather than optional is that every artifact class has structural requirements enforced by `lazy-core.audit`: skills need the `TaskCreate` preamble so skipped phases stay visible, agents need `tools:` allowlists and `model: inherit`, rules need either `paths:` or an `always_loaded:` waiver. Starting from memory reliably misses at least one of these, and the audit finding surfaces after the artifact is already in use. Starting from the template makes the requirement visible on the first edit, before any code runs.

The `lazy-core.skill-writing`, `lazy-core.rule-writing`, and `lazy-core.agent-writing` path-scoped rules then stay loaded for the duration of the edit to enforce the full contract — not just structure, but outcome vocabulary, size budget, and narrative-padding checks.

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

The expert runtime is opt-in per repo. When you run `/lazy-core.install`, a wizard phase asks whether to bootstrap runtime and experts for the current repo. If you answer yes, the skill writes the `lazy-core.runtime` block into `.claude/lazy.settings.json`, creates `.experts/experts.settings.json`, copies the `lazy.runtime.sh` shim to `.claude/bin/`, and adds `.experts/.jobs/` to `.gitignore`. It also offers to install a daemon supervisor (macOS launchd or Linux systemd) and registers the `lazy-expert.pump` routine automatically once you add at least one expert. If you skip that phase or answer no, none of those files are created and the `/lazy-expert.*` skills will abort at Step 2 with "`.claude/experts/` not initialised — run `/lazy-core.install` first."

To enable it later without re-running the full install flow, run `/lazy-core.install` again — it is idempotent and will offer the runtime wizard phase again.

---

## What is the expert runtime actually for?

It gives you a team of named workers running in the background. You dispatch a job to a named expert, keep doing other work, and collect the result later when the daemon has finished it. The daemon is a long-lived process (started via the `.claude/bin/lazy.runtime.sh` shim or a supervisor unit) that drains the job queue and runs registered plugin routines on each cycle. Because it runs outside Claude Code's conversation thread, expert jobs do not consume turns or stack against nesting limits; those are footnotes, not the point. The point is that slow work — doc reviews, lint sweeps, analysis passes — runs in parallel while you keep your session focused on the next task.

---

## What payload fields does `/lazy-expert.dispatch-job` require?

Every job payload must contain three fields: `kind` (the job type, e.g. `"doc-review"`), `role` (the expert role to handle it, e.g. `"designer"`), and `request` (the task description string). These are the minimum the protocol contract enforces; if any field is missing, dispatch aborts with "payload missing required field(s): `<list>`."

Optional fields — `source` (array of input file paths), `context` (array of context file paths), and `result` (array of expected output paths) — are supported but not required. Protocol-specific extras are also allowed. The full contract is in `claude/lazycortex-core/references/lazy-core.expert-protocols-contract.md`.

---

## How do I check whether an expert job has finished?

Run `/lazy-expert.collect-job` with the `expert_name` and `job_id` returned by `/lazy-expert.dispatch-job`. The skill returns one of four statuses: `pending` (the daemon has not processed it yet), `done` (completed successfully — result file paths are listed), `failed` (the daemon ran it but the expert reported an error), or `missing` (the job directory does not exist — wrong `job_id` or `expert_name`, or the job was already cancelled).

You can also run `/lazy-expert.list-jobs` to see the queue at a glance. Filter by `status=pending` to see what is still waiting, or by `expert=<name>` to narrow to one expert's queue.

---

## Can I cancel a job that is already being processed by the daemon?

Yes, but with a caveat. `/lazy-expert.cancel-job` asks for confirmation before removing a pending job because the runtime daemon may already be processing it — there is currently no lockfile that distinguishes "queued but not started" from "actively running." If you confirm, the job directory is removed. If the daemon is mid-run, the expert process is left to finish (or fail) but its `response.json` will have nowhere to land, which is a no-op from your perspective.

For jobs that are already `done`, the skill also asks for confirmation before removing them, since done job directories contain the result files you may still want to read. If you answer no to either prompt, no files are deleted.

---

## What is the difference between `/lazy-expert.list-jobs` and `/lazy-expert.collect-job`?

`/lazy-expert.list-jobs` gives a tabular overview of all jobs across all experts (or filtered by expert or status), sorted oldest-first. It is the right tool when you want situational awareness — how many jobs are queued, which ones have finished, which ones failed.

`/lazy-expert.collect-job` is targeted: given a specific `expert_name` and `job_id`, it returns the current status and, when the job is done, the result file paths you should `Read` to retrieve the output. Use it after dispatching a job when you know exactly which job you are waiting on.

---

## How do routines differ from expert jobs?

Expert jobs are one-off, user-initiated tasks: you dispatch a job, the daemon picks it up, and the result lands in `response.json`. Routines are repeating, plugin-registered tasks: a plugin's install skill calls `/lazy-routine.register` with a name, type, and type-specific config, and the daemon calls that command on every cycle whose interval has elapsed. Routines are intended for ongoing background work (e.g. a lint tick, a review sweep), not for ad-hoc requests.

The built-in `lazy-expert.pump` routine is what drives the expert job queue — it is itself a routine registered at install time. Additional routines registered by other plugins run alongside it in the same daemon cycle.

---

## What routine types does `/lazy-routine.register` support?

Four types, each suited to a different scheduling pattern:

- **subprocess** — the default. Runs a CLI command on every daemon cycle whose `interval_sec` has elapsed.
- **inbox** — watches a directory and dispatches one expert job per file it finds there. Good for ingestion pipelines.
- **schedule** — fires on a cron expression boundary, not on a fixed interval. Useful for calendar-aligned tasks (daily summaries, weekly sweeps).
- **git** — watches a remote branch for new commits, new files, changed files, deleted files, or renamed files and dispatches an expert job per matched event.

All four require a dot-namespaced `name` (e.g. `acme-lint.tick`). The wizard in `/lazy-routine.register` asks for the type first, then prompts only for the fields that type needs.

---

## Can I remove a routine that another plugin registered?

Yes, with `/lazy-routine.unregister <name>`. The skill is idempotent — unregistering a routine that does not exist is a no-op (it prints an INFO message rather than an error). The only routine with built-in protection is `lazy-expert.pump`: removing it stops all expert job processing, so the skill requires `--force` and warns you explicitly before proceeding.

If you accidentally remove a plugin's routine, re-running that plugin's install skill re-registers it. For `lazy-expert.pump` specifically, re-running `/lazy-core.install` restores it.

---

## What is the staging lock, and why would it get stuck?

The `lazy-core.git-guard` hook uses `.git/lazy-git.lock` to prevent two Claude Code sessions from staging files simultaneously. The lock is held by the session currently running `git add` and released after the commit. In normal operation it is held for a few seconds at most.

It can get stuck when a session is interrupted mid-staging — for example, if Claude Code crashes or the network drops between the `add` and the `commit`. The hook's automatic heuristics handle most stuck-lock cases: if the holding PID is dead, the host differs, or the lock is old and idle, it breaks automatically. Run `/lazy-core.git-status` to see the current lock state without touching it. If the lock is genuinely stuck and the heuristics will not break it (the holder is still alive but you know it has abandoned staging), run `/lazy-core.git-unlock` to confirm and force-delete the lock.

---

## When does the runtime daemon halt, and how do I resume it?

The daemon halts when a routine or expert job leaves the working tree dirty — meaning it wrote or modified tracked files without committing them. This is a safety guard: a dirty tree from one routine can corrupt the next routine's git operations. When a halt occurs, the daemon records the triggering routine, the expert and job ID (if it came from inside an expert), and the captured `git status` lines in `state.json`.

Run `/lazy-runtime.recover` to get out. The skill reads the halt context, shows you exactly which paths are dirty, and asks how you want to clean up: commit the changes, stash them for later, discard them entirely, or abort (leave the daemon halted and exit). Once the tree is clean, the skill clears the `daemon_halted` block from `state.json` and the daemon resumes scheduling on its next iteration. If the tree is still dirty after cleanup (e.g. submodules left uncommitted state), the skill tells you to run `git status` manually and re-invoke it.
